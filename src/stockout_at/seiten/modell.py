"""Page "Modell und Prüfung": data of the figures F09, F10, F11, F15, F25, F26, F27, F36.

Display only. Live figures read the daily prediction logs and the report days and return aggregates; no ATC code,
name, rank or probability of a single substance leaves this module. The three phases are never pooled, and from the
start of the test no figure compares the model with the tier rule.

`rueckblick_block` computes the fixed block `modell_rueckblick` of `ergebnisse.json`; a test recomputes it.
"""
from __future__ import annotations

import gzip
import hashlib
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from markupsafe import Markup

from .. import live, showcase
from .. import modell as kern
from ..charts import NARROW, WIDE, num, pct
from ..charts import modell as charts
from ..timeline import de
from ..vorlauf import _wilson
from . import Quellen

HORIZONTE = (28, 56, 84)
PLATZ_RASTER = (25, 50, 100, 200, 400, 800)  # coarse on purpose: the curve never gives the exact place of one report
TOP = kern.LEAD_K
MITTE_BIS = 400  # F26: behind this place a new report counts as a surprise
GRUENDE = (("Mehrbedarf", "Erhöhter Mehrbedarf"), ("Kapazität", "Kapazitätsengpässe bei der Herstellung"),
           ("Verzögerung bei der Herstellung", "Verzögerung bei der Herstellung"),
           ("Auslieferung", "Verzögerung bei der Auslieferung"), ("Wirkstoff", "Verknappung des Wirkstoffes"))
SONSTIGE = "Sonstige Gründe"
TAG_NICHT_VALIDIERT = '<span class="tag tone-warn">nicht validiert</span>'


def _day(value: str) -> str:
    return de(date.fromisoformat(value))


def _legend(text: str) -> Markup:
    return Markup(f'{text} {TAG_NICHT_VALIDIERT}')


# --- the fixed retrospective block ---------------------------------------------------------------------------------

def _grund(value: str | None) -> str:
    value = value or ""
    return next((name for key, name in GRUENDE if key in value), SONSTIGE)


def _read_rows(root: Path, before: date) -> dict[date, dict[str, tuple[str, float]]]:
    """Day -> ATC5 -> (tier, 8-week probability), only days before the test: this block never holds test data."""
    out: dict[date, dict[str, tuple[str, float]]] = {}
    for path in sorted((Path(root) / kern.LOG_DIR).glob("*/*.csv.gz")):
        day = date.fromisoformat(path.name[:10])
        if day >= before:
            continue
        with gzip.open(path, "rb") as fh:
            lines = fh.read().split(b"\n")
        head = lines[0].decode().split(",")
        ia, ip, ist = head.index("atc5"), head.index("z3_v0_p8"), head.index("stufe")
        out[day] = {f[ia].decode(): (f[ist].decode(), float(f[ip])) for f in (x.split(b",") for x in lines[1:] if x)}
    return out


def _gesamtzahl(conn, rueckblick_root: Path) -> dict:
    """F27: expected against observed number of new reports per reference day of the simulated log."""
    beginn, _, sha = live._plan()
    starts, seen, _, stand = kern.report_days(conn)
    events = live._events(starts, seen)
    grid = {live.RUECKBLICK_START + timedelta(days=i * kern.STEP) for i in range(27)}
    logs = live._read_logs(Path(rueckblick_root), "z3_v0_p8", beginn, sha, grid)
    rows = [_zeile(d, logs[d], events) for d in sorted(logs) if d + timedelta(days=56) <= stand]
    e, o = [z["erwartet"] for z in rows], [z["eingetroffen"] for z in rows]
    me, mo = sum(e) / len(e), sum(o) / len(o)
    cov = sum((a - me) * (b - mo) for a, b in zip(e, o))
    corr = cov / math.sqrt(sum((a - me) ** 2 for a in e) * sum((b - mo) ** 2 for b in o))
    return {"horizont_tage": 56, "stichtage": len(rows), "korrelation": round(corr, 3), "zeilen": rows}


def _zeile(day: date, rows: dict[str, float], events: dict[str, list[int]]) -> dict:
    """One reference day: sum of the probabilities, its 95 % range if the substances were independent, what came."""
    t = day.toordinal()
    expected = sum(rows.values())
    spread = 1.96 * math.sqrt(sum(p * (1 - p) for p in rows.values()))
    hits = 0
    for a in rows:
        ev = events.get(a)
        if ev:
            i = bisect_left(ev, t + 1)
            hits += i < len(ev) and ev[i] <= t + 56
    return {"stichtag": day.isoformat(), "wirkstoffe": len(rows), "erwartet": round(expected, 2),
            "bereich": [round(max(expected - spread, 0.0), 2), round(expected + spread, 2)], "eingetroffen": int(hits)}


def _blinde_flecken(conn, rueckblick_root: Path) -> dict:
    """F26, Rückblick only: new reports by their place on the last simulated log day before them, with the BASG reason.

    The phase follows the prediction day, so a report counts only if the day before it lies in the simulated log."""
    beginn, _, _ = live._plan()
    logs = _read_rows(rueckblick_root, beginn)
    _, _, onsets, stand = kern.report_days(conn)
    reasons: dict[tuple[str, date], list[str]] = defaultdict(list)
    for a, s, fs, g in conn.execute("SELECT atc5, start_date, first_seen, grund FROM episodes WHERE atc5 IS NOT NULL ORDER BY episode_id"):
        s, fs = kern._d(s), kern._d(fs)
        if s:
            reasons[(a, min(s, fs) if fs else s)].append(g)
    days = sorted(logs)
    last = min(days[-1] + timedelta(days=1), stand)
    events = []
    for a, ds in onsets.items():
        for report in ds:
            if not days[0] < report <= last:
                continue
            d = days[bisect_left(days, report) - 1]
            if (report - d).days > live.MAX_ABSTAND or a not in logs[d]:
                continue
            rows = logs[d]
            place = 1 + sum(1 for _, p in rows.values() if p > rows[a][1])
            reason = Counter(reasons.get((a, report), [""])).most_common(1)[0][0]
            events.append((report, place, rows[a][0], _grund(reason)))
    groups = {"treffer": lambda p: p <= TOP, "mitte": lambda p: TOP < p <= MITTE_BIS, "ueberraschung": lambda p: p > MITTE_BIS}
    out: dict = {"meldungen": len(events), "von": min(e[0] for e in events).isoformat(), "bis": max(e[0] for e in events).isoformat(), "gruppen": {}}
    for key, test in groups.items():
        part = [e for e in events if test(e[1])]
        count = Counter(e[3] for e in part)
        out["gruppen"][key] = {"n": len(part), "ohne_auslandssignal": sum(1 for e in part if e[2] == "-"),
                               "gruende": {name: count.get(name, 0) for name in (*(n for _, n in GRUENDE), SONSTIGE)}}
    return out


def rueckblick_block(conn, rueckblick_root: Path | str) -> dict:
    """The block `modell_rueckblick` of `ergebnisse.json`. Same target and reference days as the published band."""
    bands = {}
    for h in (28, 84):
        band = live.rueckblick_band(conn, rueckblick_root, h)
        stand = band.pop("basg_stand")
        bands[str(h)] = band
    return {
        "art": "rueckblick",
        "quelle": "Simuliertes Vorhersageprotokoll 2026 mit den geprüften Gewichten von z3_v0; Ziel wie im Prüfplan; "
                  "Stichtage alle 14 Tage ab 01.01.2026; die Gründe je neuer Meldung aus dem täglichen simulierten Protokoll",
        "berechnung": "seiten/modell.py, rueckblick_block",
        "hinweis": "Rückblick, simuliert, nicht validiert. Das Archiv vor dem 17.10.2026 ist lückenhaft und sieht kurze Meldungen nicht.",
        "abhaengig_von_nicht_gezeigten_quellen": True,
        "basg_stand": stand,
        "kalibrierung_horizonte": bands,
        "gesamtzahl": _gesamtzahl(conn, Path(rueckblick_root)),
        "blinde_flecken": _blinde_flecken(conn, Path(rueckblick_root)),
    }


# --- live data ------------------------------------------------------------------------------------------------------

def read_logs(root: Path, beginn: date, sha: str) -> dict[int, dict[date, dict[str, float]]]:
    """Horizon -> day -> ATC5 -> probability in one pass over the logs: the rows of `live._read_logs`."""
    out: dict[int, dict[date, dict[str, float]]] = {h: {} for h in HORIZONTE}
    for path in sorted((Path(root) / kern.LOG_DIR).glob("*/*.csv.gz")):
        day = date.fromisoformat(path.name[:10])
        with gzip.open(path, "rb") as fh:
            lines = fh.read().split(b"\n")
        head = lines[0].decode().split(",")
        ia, iz = head.index("atc5"), head.index("pruefplan")
        columns = [(out[h].setdefault(day, {}), head.index(f"z3_v0_p{h // 7}")) for h in HORIZONTE]
        want = sha.encode() if day >= beginn else None
        for row in lines[1:]:
            if row:
                f = row.split(b",")
                if want is None or f[iz] == want:
                    a = f[ia].decode()
                    for rows, c in columns:
                        rows[a] = float(f[c])
        for h in HORIZONTE:
            if not out[h][day]:
                del out[h][day]
    return out


def panel(logs: dict, starts: dict, seen: dict, stand: date, beginn: date, step: int, results: dict, horizon: int) -> dict:
    """`live.build` for one horizon on logs that are already read; a test holds the two equal."""
    events = live._events(starts, seen)
    reports = live._new_reports(logs, seen, live.EINLAUF_START, beginn)

    def phase(key: str, von: date, bis: date | None, days: list[date], every: int) -> dict:
        next_day = live._next_date(logs, von, bis, every, stand, horizon)
        return {"von": von.isoformat(), "bis": bis.isoformat() if bis else None, **live.aggregate(logs, days, events, stand, horizon),
                "naechster_termin": next_day.isoformat() if next_day else None, "meldungen": live._reports_summary(reports[key])}

    einlauf_bis = beginn - timedelta(days=1)
    einlauf = phase("einlauf", live.EINLAUF_START, einlauf_bis, sorted(d for d in logs if live.EINLAUF_START <= d <= einlauf_bis), 1)
    pruefung = phase("pruefung", beginn, None, sorted(d for d in logs if d >= beginn and (d - beginn).days % step == 0), step)
    pruefung["stichtage_reif"] = pruefung["protokolltage_reif"]
    last = max(logs) if logs else None
    rows = logs[last] if last else {}
    je = [0] * len(live.KLASSEN)
    for p in rows.values():
        je[live._klasse(p)] += 1
    block = results.get("vorhersage_gegen_meldung") or {}
    band = (block.get("horizonte") or {}).get(str(horizon))
    return {
        "stand": stand.isoformat(), "protokoll_bis": last.isoformat() if last else None, "horizont_tage": horizon,
        "beginn": beginn.isoformat(), "grenzen": list(live.GRENZEN),
        "klassen": [{"name": n, "kurz": k} for n, k in zip(live.KLASSEN, live.KLASSEN_KURZ)],
        "heute": {"wirkstoffe": len(rows), "je_klasse": je, "erwartet": round(sum(rows.values()), 1)},
        "einlauf": einlauf, "pruefung": pruefung,
        "rueckblick": {**band, "basg_stand": block.get("basg_stand")} if band else None,
    }


def with_bands(results: dict) -> dict:
    """`results` with the retrospective bands of all three horizons, leaving the published block untouched."""
    block = results["vorhersage_gegen_meldung"]
    extra = (results.get("modell_rueckblick") or {}).get("kalibrierung_horizonte") or {}
    return {**results, "vorhersage_gegen_meldung": {**block, "horizonte": {**block["horizonte"], **extra}}}


def _orders(logs: dict[date, dict[str, float]]) -> dict[str, str]:
    """Fixed tie-break per substance, as in `modell.lead_and_churn`."""
    return {a: hashlib.md5(a.encode()).hexdigest() for rows in logs.values() for a in rows}


def rangkurve(logs: dict[date, dict[str, float]], seen: dict[str, list[date]], beginn: date) -> dict:
    """F25: how many new reports stood within the first k places of the list on the last log day before them.

    Same reports as panel a of F22. Only counts at the fixed places of `PLATZ_RASTER` leave this function."""
    days = sorted(logs)
    order = _orders(logs)
    ranked: dict[date, dict[str, int]] = {}
    found: dict[str, list[tuple[int, int]]] = {"einlauf": [], "pruefung": []}
    for a, ds in seen.items():
        for t in sorted(set(ds)):
            i = bisect_left(days, t) - 1
            if i < 0:
                continue
            last = days[i]
            if (t - last).days > live.MAX_ABSTAND or last < live.EINLAUF_START or a not in logs[last]:
                continue
            if last not in ranked:
                rows = logs[last]
                ranked[last] = {b: n + 1 for n, b in enumerate(sorted(rows, key=lambda b: (-rows[b], order[b])))}
            found["einlauf" if last < beginn else "pruefung"].append((ranked[last][a], len(logs[last])))

    def phase(rows: list[tuple[int, int]]) -> dict:
        n = len(rows)
        points = []
        for k in PLATZ_RASTER:
            hits = sum(1 for place, _ in rows if place <= k)
            # x is the share a random order would put within these places: the diagonal is chance by construction
            points.append({"platz": k, "anteil_liste": sum(min(1.0, k / size) for _, size in rows) / n if n else None,
                           "meldungen": hits, "anteil": hits / n if n else 0.0})
        top = next(p["meldungen"] for p in points if p["platz"] == TOP)
        return {"anzahl": n, "top50": top, "top50_ki95": _wilson(top, n) if n >= live.MIN_MELDUNGEN_ANTEIL else None, "punkte": points}

    return {"einlauf": phase(found["einlauf"]), "pruefung": phase(found["pruefung"]), "beginn": beginn.isoformat(),
            "mindestens": live.MIN_MELDUNGEN_ANTEIL}


def _top(rows: dict[str, float], order: dict[str, str]) -> set[str]:
    """The top 50 with ties in the fixed order; only substances at or above the 50th value are sorted."""
    cut = sorted(rows.values(), reverse=True)[min(TOP, len(rows)) - 1]
    return {t[2] for t in sorted((-p, order[a], a) for a, p in rows.items() if p >= cut)[:TOP]}


def wechsel(logs: dict[date, dict[str, float]], beginn: date) -> dict:
    """F36: share of the top 50 that changes from one log day to the next, per phase; a pair across phases counts in neither."""
    order = _orders(logs)
    days = sorted(logs)
    tops = {d: _top(logs[d], order) for d in days}
    rows = [{"tag": b.isoformat(), "anteil": len(tops[b] - tops[a]) / TOP, "phase": "einlauf" if b < beginn else "pruefung"}
            for a, b in zip(days, days[1:]) if (b - a).days == 1 and (a < beginn) == (b < beginn)]

    def summary(key: str) -> dict | None:
        part = [r["anteil"] for r in rows if r["phase"] == key]
        return {"tage": len(part), "mittel": sum(part) / len(part), "hoechstens": max(part), "ohne_wechsel": sum(v == 0 for v in part)} if part else None

    return {"zeilen": rows, "einlauf": summary("einlauf"), "pruefung": summary("pruefung"), "beginn": beginn.isoformat()}


def gesamtzahl_live(logs: dict[date, dict[str, float]], events: dict[str, list[int]], stand: date, beginn: date, step: int) -> list[dict]:
    """F27: mature reference days of the real log, every 14 days per phase, on the grid of the Prüfplan from its start."""
    out = []
    for d in sorted(logs):
        if d + timedelta(days=56) > stand:
            continue
        if d < beginn and (d - live.EINLAUF_START).days % step == 0 and d >= live.EINLAUF_START:
            out.append({**_zeile(d, logs[d], events), "phase": "einlauf"})
        elif d >= beginn and (d - beginn).days % step == 0:
            out.append({**_zeile(d, logs[d], events), "phase": "pruefung"})
    return out


# --- figures --------------------------------------------------------------------------------------------------------

def _f09(results: dict) -> dict:
    z3 = results["z3_rueckblick"]
    rows = []
    for d in z3["differenz_z3_minus_stufen"]:
        decimals = charts.F09_PANELS[d["mass"]]["decimals"]
        unit = f' {d["einheit"]}' if d["einheit"] else ""
        rows.append([d["mass"], f'{num(d["wert"], decimals, signed=True)}{unit}', f'{num(d["ki95"][0], decimals)} bis {num(d["ki95"][1], decimals)}'])
    return {"id": "f09", "kind": "rueckblick", "legend": "Wie sicher ist der Abstand zur Stufenregel?",
            "svg_wide": charts.f09(z3, width=WIDE, uid="f09w"), "svg_narrow": charts.f09(z3, width=NARROW, uid="f09n"),
            "caption": "Abstand von Z3 v0 zur Stufenregel in drei Maßen, jeweils mit eigener Einheit: Trennschärfe (AUC), "
                       "Genauigkeit der Wahrscheinlichkeiten (Brier-Gewinn) und Trefferquote der 50 höchsten Wirkstoffe je Stichtag. "
                       f'Rechts der Nulllinie liegt Z3 v0 vorn. {z3["intervall_hinweis"]}',
            "table": {"caption": "Abstand Z3 v0 minus Stufenregel, Rückblick 2026", "head": ["Maß", "Abstand", "95-%-Intervall"], "rows": rows},
            "source": z3["quelle"]}


def _f11(results: dict) -> dict:
    w = results["z3_gewichte_8_wochen"]
    rows = [[f'{g["gruppe"]}: {m["name"]}', num(m["gewicht"], 4, signed=True), g["bezug"]] for g in w["gruppen"] for m in g["merkmale"]]
    rows += [[s["name"], f'{num(s["von"], 4, signed=True)} bis {num(s["bis"], 4, signed=True)}', "Spanne"] for s in w["spannen"]]
    return {"id": "f11", "kind": "rueckblick", "legend": "Was trägt das Modell?",
            "svg_wide": charts.f11(w, width=WIDE, uid="f11w"), "svg_narrow": charts.f11(w, width=NARROW, uid="f11n"),
            "caption": "Gewichte der regularisierten logistischen Regression für 8 Wochen, gelernt 2024–2025, als logarithmische Chance: "
                       "rechts der Nulllinie erhöht ein Merkmal die geschätzte Wahrscheinlichkeit einer neuen Meldung, links senkt es sie. "
                       f'Jede Gruppe ist gegen ihren Bezug gerechnet. {w["hinweis"]}',
            "table": {"caption": "Gewichte für 8 Wochen, in logarithmischer Chance", "head": ["Merkmal", "Gewicht", "Bezug"], "rows": rows},
            "source": w["quelle"]}


def _f15(results: dict, ref: date) -> dict:
    plan = results["vorab_registrierung"]
    data = {"zeitleiste": plan["zeitleiste"], "stand": ref.isoformat()}
    def when(e: dict) -> str:
        return f'{_day(e["von"])} bis {_day(e["bis"])}' if "von" in e else _day(e["am"])
    rows = [[when(e), e["text"]] for e in sorted(plan["zeitleiste"], key=lambda e: e.get("am") or e["von"])]
    return {"id": "f15", "kind": "plan", "legend": "Was ist wann festgelegt, was kommt wann?",
            "svg_wide": charts.f15(data, width=WIDE, uid="f15w"), "svg_narrow": charts.f15(data, width=NARROW, uid="f15n"),
            "caption": f"Gefüllte Punkte liegen vor dem Datenstand vom {de(ref)}, hohle danach. "
                       "Die Ergebnisse werden in jedem Fall veröffentlicht, auch ein No-Go.",
            "table": {"caption": "Zeitleiste der Vorab-Registrierung", "head": ["Datum", "Schritt"], "rows": rows},
            "source": plan["quelle"]}


def _f10(panels: list[dict], results: dict) -> dict:
    def at(points: list[dict], i: int) -> dict | None:
        return next((p for p in points if i in p["klassen"]), None)
    rows = []
    for d in panels:
        band = d["rueckblick"]
        for i, k in enumerate(d["klassen"]):
            rows.append([f'{d["horizont_tage"] // 7} Wochen, {k["name"]}', showcase._f22_cell(at(band["punkte"] if band else [], i)),
                         showcase._f22_cell(at(d["einlauf"]["punkte"], i)), showcase._f22_cell(at(d["pruefung"]["punkte"], i))])
    stand = panels[1]["stand"]
    early = " ".join(f'Die Punkte der Einlaufphase bei {d["horizont_tage"] // 7} Wochen beruhen bisher auf {num(d["einlauf"]["faelle"])} '
                     f'Wirkstoff-Tagen mit {num(d["einlauf"]["treffer"])} Treffern aus nur {num(d["einlauf"]["wirkstoffe_mit_meldung"])} Wirkstoffen.'
                     for d in panels if d["einlauf"]["punkte"] and d["einlauf"]["wirkstoffe_mit_meldung"] < 100)
    return {"id": "f10", "kind": "live", "legend": _legend("Stimmen die Wahrscheinlichkeiten?"),
            "svg_wide": charts.f10(panels, width=WIDE, uid="f10w"), "svg_narrow": charts.f10(panels, width=NARROW, uid="f10n"),
            "caption": "Je Horizont: vorhergesagte Wahrscheinlichkeit einer neuen BASG-Meldung gegen den Anteil, für den sie wirklich kam, "
                       "in sechs festen Klassen. Auf der Diagonale stimmen beide überein. Das blasse Band ist der simulierte Rückblick 2026, "
                       "hohle Kreise sind die Einlaufphase, die nicht für die Prüfung zählt, Rauten die Prüfung als Zwischenstand ohne Urteil. "
                       "Die Striche zeigen 95-%-Bereiche über Wirkstoffe. Klassen unter 30 Wirkstoffen sind mit der Nachbarklasse zusammengelegt (waagrechte Linie). "
                       f'{early + " " if early else ""}{results["referenzinstanz_satz"]}',
            "table": {"caption": "Vorhergesagt → eingetroffen (95-%-Bereich) je Horizont und Klasse; die Phasen sind getrennt gerechnet",
                      "head": ["Horizont und Klasse", "Rückblick 2026 (simuliert)", "Einlaufphase", "Prüfung"], "rows": rows},
            "source": f"BASG-Meldungen bis {_day(stand)}, tägliches Vorhersageprotokoll. Bereits reife Anteile können sich noch ändern, "
                      "weil manche Meldungen rückdatiert erscheinen. Das Archiv vor dem 17.10.2026 ist lückenhaft."}


def _f25(data: dict, results: dict) -> dict:
    e, p = data["einlauf"], data["pruefung"]
    def cell(phase: dict, point: dict) -> str:
        return f'{num(point["meldungen"])} von {num(phase["anzahl"])} ({pct(point["anteil"], 0)})' if phase["anzahl"] else "–"
    def share(a: dict, b: dict) -> str:  # the two phases have lists of nearly the same length; the first with reports stands for both
        value = a["anteil_liste"] if a["anteil_liste"] is not None else b["anteil_liste"]
        return pct(value, 1) if value is not None else "–"
    rows = [[f'bis Platz {num(a["platz"])}', share(a, b), cell(e, a), cell(p, b)] for a, b in zip(e["punkte"], p["punkte"])]
    return {"id": "f25", "kind": "live", "legend": _legend("Wo standen die neu Gemeldeten in der Reihung?"),
            "svg_wide": charts.f25(data, width=WIDE, uid="f25w"), "svg_narrow": charts.f25(data, width=NARROW, uid="f25n"),
            "caption": "Alle Wirkstoffe, für die erstmals eine BASG-Meldung erschien, nach ihrem Platz in der Liste des Modells am Tag davor. "
                       "Die Treppe zeigt, welcher Anteil dieser Meldungen in den obersten Plätzen stand. Auf der Diagonale läge eine Liste "
                       "in zufälliger Reihenfolge. Die Plätze sind bewusst nur in sechs groben Abschnitten gezählt, damit keine einzelne Meldung erkennbar ist. "
                       f'Die Prüfung wertet nur ihre Stichtage alle 14 Tage. {results["referenzinstanz_satz"]}',
            "table": {"caption": "Neue Meldungen bis zu einem Platz der Liste am Tag davor",
                      "head": ["Platz", "Anteil der Liste", "Einlaufphase", "ab Prüfungsbeginn"], "rows": rows},
            "source": "BASG-Meldungen und tägliches Vorhersageprotokoll seit 21.10.2026."}


def _f26(data: dict, block: dict, results: dict) -> dict:
    g = data["gruppen"]
    names = list(g["treffer"]["gruende"])
    def cell(key: str, name: str) -> str:
        n = g[key]["n"]
        return f'{num(g[key]["gruende"][name])} ({pct(g[key]["gruende"][name] / n, 0)})'
    rows = [[name, cell("treffer", name), cell("mitte", name), cell("ueberraschung", name)] for name in names]
    rows.append(["Summe", num(g["treffer"]["n"]), num(g["mitte"]["n"]), num(g["ueberraschung"]["n"])])
    rows.append(["ohne Auslandssignal", num(g["treffer"]["ohne_auslandssignal"]), num(g["mitte"]["ohne_auslandssignal"]), num(g["ueberraschung"]["ohne_auslandssignal"])])
    return {"id": "f26", "kind": "rueckblick", "legend": "Was sieht das Modell nicht kommen?",
            "svg_wide": charts.f26(data, width=WIDE, uid="f26w"), "svg_narrow": charts.f26(data, width=NARROW, uid="f26n"),
            "caption": f'{num(data["meldungen"])} neue Meldungen im simulierten Rückblick vom {_day(data["von"])} bis {_day(data["bis"])}, '
                       f'nach ihrem Platz in der Liste am Tag davor und dem Grund laut BASG. Die Einlaufphase ist nicht enthalten. '
                       f'Oben in der Liste stehen vor allem Herstellungs- und Lieferprobleme. Plötzlicher Mehrbedarf kommt dort selten vor '
                       f'und ist unter den Überraschungen der häufigste Grund. Von den {num(g["ueberraschung"]["n"])} Überraschungen hatten '
                       f'{num(g["ueberraschung"]["ohne_auslandssignal"])} kein Auslandssignal, von den {num(g["treffer"]["n"])} Treffern keine. '
                       "Der Grund ist erst mit der Meldung bekannt und dient hier nur der Beschreibung. Gezählt ist je Wirkstoff der Beginn "
                       "eines neuen Engpasses, überlappende Meldungen gelten als eine.",
            "table": {"caption": "Neue Meldungen nach Grund und Platz am Tag davor, Anzahl und Anteil je Gruppe",
                      "head": ["Grund laut BASG", "Platz 1–50", "Platz 51–400", "hinter Platz 400"], "rows": rows},
            "source": f'Simuliertes Vorhersageprotokoll 2026 mit den geprüften Gewichten von z3_v0; Grund laut BASG; BASG-Stand {_day(block["basg_stand"])}. '
                      "Das Archiv vor dem 17.10.2026 ist lückenhaft."}


def _f27(block: dict, extra: list[dict], results: dict) -> dict:
    data = {**block["gesamtzahl"], "live": extra}
    rows = [[_day(z["stichtag"]), "Rückblick", num(z["wirkstoffe"]), num(z["erwartet"], 1),
             f'{num(z["bereich"][0], 1)}–{num(z["bereich"][1], 1)}', num(z["eingetroffen"])] for z in data["zeilen"]]
    names = {"einlauf": "Einlaufphase", "pruefung": "Prüfung"}
    rows += [[_day(z["stichtag"]), names[z["phase"]], num(z["wirkstoffe"]), num(z["erwartet"], 1),
              f'{num(z["bereich"][0], 1)}–{num(z["bereich"][1], 1)}', num(z["eingetroffen"])] for z in extra]
    return {"id": "f27", "kind": "live" if extra else "rueckblick", "legend": _legend("Sagt das Modell auch die Gesamtzahl voraus?") if extra else "Sagt das Modell auch die Gesamtzahl voraus?",
            "svg_wide": charts.f27(data, width=WIDE, uid="f27w"), "svg_narrow": charts.f27(data, width=NARROW, uid="f27n"),
            "caption": "Je Stichtag die Summe der vorhergesagten Wahrscheinlichkeiten (Linie) gegen die Zahl der Wirkstoffe, für die binnen 8 Wochen "
                       "wirklich eine neue Meldung kam (Punkte). Das Band umfasst 95 % der Streuung, die allein durch Zufall zu erwarten wäre, wenn die "
                       "Wahrscheinlichkeiten stimmen und Meldungen unabhängig wären; Meldungen kommen aber in Schüben. Die 8-Wochen-Fenster "
                       "benachbarter Stichtage überlappen sich."
                       + (" Hohle Kreise sind Stichtage der Einlaufphase, Rauten Stichtage der Prüfung als Zwischenstand ohne Urteil, "
                          f'jeweils mit ihrem eigenen Zufallsbereich. {results["referenzinstanz_satz"]}' if extra else ""),
            "table": {"caption": "Erwartete und eingetroffene Zahl neuer Meldungen je Stichtag, 8 Wochen",
                      "head": ["Stichtag", "Phase", "Wirkstoffe", "Erwartet", "Zufallsband 95 %", "Eingetroffen"], "rows": rows},
            "source": "Simuliertes Vorhersageprotokoll 2026 mit den geprüften Gewichten von z3_v0; Ziel wie im Prüfplan; Stichtage alle 14 Tage "
                      f'ab 01.01.2026; BASG-Stand {_day(block["basg_stand"])}. Das Archiv vor dem 17.10.2026 ist lückenhaft.'}


def _f36(data: dict, results: dict) -> dict:
    months: dict[str, list[dict]] = defaultdict(list)
    for z in data["zeilen"]:
        months[z["tag"][:7] + "|" + z["phase"]].append(z)
    names = {"einlauf": "Einlaufphase", "pruefung": "Prüfung"}
    rows = []
    for key, part in months.items():
        month, phase = key.split("|")
        values = [z["anteil"] for z in part]
        rows.append([f"{month[5:]}/{month[:4]}", names[phase], num(len(part)), pct(sum(values) / len(values)), pct(max(values), 0)])
    return {"id": "f36", "kind": "live", "legend": _legend("Wie stabil ist die Liste der 50 höchsten?"),
            "svg_wide": charts.f36(data, width=WIDE, uid="f36w"), "svg_narrow": charts.f36(data, width=NARROW, uid="f36n"),
            "caption": "Anteil der 50 am höchsten gereihten Wirkstoffe, der von einem Protokolltag zum nächsten wechselt. Eine Liste, die täglich "
                       "stark springt, wäre als Hinweis wenig wert. Die Phasen sind getrennt gerechnet, der Übergang zwischen ihnen zählt nicht. "
                       f'{results["referenzinstanz_satz"]}',
            "table": {"caption": "Täglicher Wechsel der Top 50 je Monat", "head": ["Monat", "Phase", "Tage", "Mittel", "Höchstens"], "rows": rows},
            "source": "Tägliches Vorhersageprotokoll seit 21.10.2026; nur aufeinanderfolgende Tage."}


def _facts(results: dict, ref: date) -> dict:
    """Numbers and sentences of the page text, all read from the published block."""
    z3 = results["z3_rueckblick"]
    plan = results["vorab_registrierung"]
    bench = showcase.pruefstand(results, ref)
    vorlauf = z3["vorlauf"]
    v = next(m for m in vorlauf["verfahren"] if m["id"] == "z3_v0")
    methods = [{"id": m["id"], "rolle": m["rolle"], "sha": m["sha256"][:12]} for m in plan["verfahren"]]
    auc = [{"wochen": a["wochen"], "z3": num(a["z3_v0"], 3), "stufen": num(a["stufen_v0"], 3)} for a in z3["horizonte_auc"]]
    return {
        "bench": bench, "regel": plan["bestehensregel"], "methods": methods, "auc": auc, "grenzen": z3["grenzen"],
        "nachtrag": z3["nachtrag_2026_11_16"]["text"], "nachtrag_quelle": z3["nachtrag_2026_11_16"]["quelle"],
        "plan_hash": plan["pruefplan_kurz"], "repository": plan["repository"], "doi": plan["doi_alle_versionen"],
        "verfahren_hinweis": plan["verfahren_hinweis"], "pruefsummen_hinweis": plan["pruefsummen_hinweis"],
        "vorlauf": {"anteil": pct(v["tag_davor"], 0), "ki": f'{num(v["tag_davor_ki95"][0] * 100)}–{num(v["tag_davor_ki95"][1] * 100)} %',
                    "tage": num(v["median_tage_auf_liste"]), "meldungen": num(vorlauf["neue_meldungen"])},
        "bedingungen": z3["bedingungen"], "faelle": num(z3["bedingungen"]["faelle"]), "meldungen": num(z3["bedingungen"]["meldungen"]),
    }


def _gesamtzahl_facts(block: dict) -> dict:
    rows = block["gesamtzahl"]["zeilen"]
    e = [z["erwartet"] for z in rows]
    o = [z["eingetroffen"] for z in rows]
    out = [z for z in rows if not z["bereich"][0] <= z["eingetroffen"] <= z["bereich"][1]]
    first = rows[0]
    low = min(rows, key=lambda z: z["eingetroffen"])
    return {"erwartet": f"{num(min(e))}–{num(max(e))}", "eingetroffen": f"{num(min(o))}–{num(max(o))}",
            "korrelation": num(block["gesamtzahl"]["korrelation"], 1), "stichtage": num(len(rows)), "ausserhalb": num(len(out)),
            "erster": {"tag": _day(first["stichtag"]), "kam": num(first["eingetroffen"]), "erwartet": num(first["erwartet"])},
            "tief": {"tag": _day(low["stichtag"]), "kam": num(low["eingetroffen"]), "erwartet": num(low["erwartet"])}}


def _live_figures(q: Quellen, results: dict, block: dict) -> dict:
    beginn, step, sha = live._plan()
    merged = with_bands(results)
    starts, seen, _, stand = kern.report_days(q.conn)
    logs = read_logs(q.archive_root, beginn, sha) if q.archive_root else {h: {} for h in HORIZONTE}
    panels = [panel(logs[h], starts, seen, stand, beginn, step, merged, h) for h in HORIZONTE]
    out: dict = {"f10": _f10(panels, results)}
    rang = rangkurve(logs[56], seen, beginn)
    out["f25"] = _f25(rang, results)
    out["f25_stand"] = {k: num(rang["einlauf"][k]) for k in ("anzahl", "top50")}
    list_stats = wechsel(logs[56], beginn)
    if list_stats["zeilen"]:
        out["f36"] = _f36(list_stats, results)
        e = list_stats["einlauf"]
        out["f36_stand"] = {"mittel": pct(e["mittel"]), "hoechstens": pct(e["hoechstens"], 0), "tage": num(e["tage"])} if e else None
    extra = gesamtzahl_live(logs[56], live._events(starts, seen), stand, beginn, step)
    out["f27"] = _f27(block, extra, results)
    return out


def context(q: Quellen) -> dict:
    results = q.results
    block = results["modell_rueckblick"]
    out: dict = {"fakten": _facts(results, q.ref), "f08": showcase.f08_figure(results), "f09": _f09(results), "f11": _f11(results),
                 "f15": _f15(results, q.ref), "f26": _f26(block["blinde_flecken"], block, results), "f27": _f27(block, [], results),
                 "f27_fakten": _gesamtzahl_facts(block)}
    try:  # display only: if the logs cannot be read, the page keeps its fixed figures
        out.update(_live_figures(q, results, block))
    except Exception as exc:
        print(f"WARNUNG Modellseite, Live-Grafiken: {type(exc).__name__}: {exc}")
    return out
