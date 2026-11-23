"""Page context: "Idee und Aufbau" (F16 pipeline, F29 archive, F21 versions, F04 example package).

The figures F21 and F29 also appear on the Methodik page. Reads only the database and the archive manifest (metadata),
no raw archive file. No clock, no random numbers.
"""
from __future__ import annotations

import json
from bisect import bisect_left
from datetime import date
from pathlib import Path
from statistics import median

from markupsafe import Markup

from ..archive import MANIFEST, SOURCES
from ..charts import NARROW, WIDE, archiv, num
from ..timeline import d as parse_day
from ..timeline import de, events, timeline_svg
from . import Quellen

BEISPIEL_PZN = "0774523"  # Kreon 10.000 Einheiten, the example of the public README
ABSTAENDE = (7, 14, 30)
NAMEN = {"basg": "BASG", "asp": "ASP-Liste", "eudragmdp": "EudraGMDP", "sukl_dlp": "SÚKL-Arzneimitteldatenbank",
         "erviss_ili": "ECDC ERVISS", "sari_region": "SARI nach Region", "sari_patient": "SARI nach Altersgruppe"}
ORIGIN = {"wayback": "Internet Archive", "legacy_local": "Altdatei", "live": "Täglicher Abruf"}


def ausduennen(tage: list[date], episoden: list[tuple[date, date]], abstaende: tuple[int, ...] = ABSTAENDE) -> list[dict]:
    """How many ended reports no kept day would have seen, if only every n-th daily snapshot had been kept.

    `episoden` are (first seen, last seen). Every start offset counts once; mean, smallest and largest number are returned.
    """
    out = []
    for n in abstaende:
        verpasst = []
        for versatz in range(n):
            keep = tage[versatz::n]
            miss = 0
            for von, bis in episoden:
                i = bisect_left(keep, von)
                if i == len(keep) or keep[i] > bis:
                    miss += 1
            verpasst.append(miss)
        out.append({"abstand": n, "mittel": sum(verpasst) / n, "min": min(verpasst), "max": max(verpasst)})
    return out


def archiv_daten(q: Quellen) -> dict:
    """Snapshots by origin, gaps of the old archive and the thinning of the daily archive."""
    staende = sorted(({"tag": date.fromisoformat(s["snapshot_date"]), "origin": s["origin"], "complete": bool(s["complete"])}
                      for s in q.data.snapshots), key=lambda s: s["tag"])
    live = [s["tag"] for s in staende if s["origin"] == "live"]
    alt = [s["tag"] for s in staende if s["origin"] != "live"]
    gaps = [(b - a).days for a, b in zip(alt, alt[1:])]
    neu, beendet = 0, []
    if live:
        rows = q.conn.execute("SELECT first_seen, last_seen, active FROM episodes WHERE first_seen > ?", (live[0].isoformat(),))
        for first, last, active in rows:
            neu += 1
            if not active:
                beendet.append((date.fromisoformat(first), date.fromisoformat(last)))
    zeilen = ausduennen(live, beendet) if live and beendet else []
    for z in zeilen:
        z["label"] = f'alle {z["abstand"]} Tage'
    if zeilen:
        zeilen.insert(0, {"abstand": 1, "label": "täglich", "mittel": 0.0, "min": 0, "max": 0})
    return {
        "staende": staende,
        "abgeschnitten": sum(not s["complete"] for s in staende),
        "tagesstaende": len(live),
        "start": live[0] if live else None,
        "neu": neu,
        "beendet": len(beendet),
        "ausduennung": zeilen,
        "luecke": {"median": median(gaps), "mittel": sum(gaps) / len(gaps), "max": max(gaps)} if gaps else None,
    }


def f29_figure(a: dict) -> dict | None:
    if not a["staende"]:
        return None
    rows = []
    for key, label in ORIGIN.items():
        own = [s for s in a["staende"] if s["origin"] == key]
        if own:
            cut = sum(not s["complete"] for s in own)
            rows.append([label, f'{num(len(own))} {"Stand" if len(own) == 1 else "Stände"}' + (f", davon {num(cut)} abgeschnitten" if cut else ""),
                         de(own[0]["tag"]) if len(own) == 1 else f'{de(own[0]["tag"])} bis {de(own[-1]["tag"])}'])
    total = a["beendet"]
    for z in a["ausduennung"]:
        rows.append([f'Übersehen, {z["label"]}', f'{num(z["mittel"], 1)} von {num(total)}',
                     "–" if z["max"] == 0 else f'{num(z["min"])} bis {num(z["max"])}'])
    first = de(a["staende"][0]["tag"])
    parts = [f'Oben alle {num(len(a["staende"]))} Stände der BASG-Liste seit {first}.']
    if a["start"]:
        lue = a["luecke"]
        if lue:
            parts.append(f'Vor dem {de(a["start"])} ist die Vorgeschichte lückenhaft: nur einzelne Aufnahmen, im Median {num(lue["median"])}, '
                         f'im Mittel {num(lue["mittel"])} und höchstens {num(lue["max"])} Tage auseinander, {num(a["abgeschnitten"])} davon abgeschnitten.')
    if a["ausduennung"]:
        werte = [z for z in a["ausduennung"] if z["abstand"] > 1]
        liste = ", ".join(num(z["mittel"], 1) for z in werte[:-1]) + f' oder {num(werte[-1]["mittel"], 1)}'
        tage = ", ".join(str(z["abstand"]) for z in werte[:-1]) + f' oder {werte[-1]["abstand"]}'
        parts.append(f'Unten wird das Tagesarchiv künstlich ausgedünnt: Von {num(a["neu"])} seit dem {de(a["start"])} neu erschienenen Meldungen sind '
                     f'{num(total)} schon wieder beendet. Bei {tage} Tagen Abstand fielen davon im Mittel über alle Startversätze {liste} ganz '
                     f'zwischen zwei Stände; die Linie reicht vom günstigsten zum ungünstigsten Versatz. Kleine Fallzahl aus {num(a["tagesstaende"])} Tagen, sie wächst täglich.')
    return {
        "id": "f29",
        "kind": "live",
        "legend": "Was sieht ein tägliches Archiv, das ein seltener geführtes nicht sieht?",
        "svg_wide": archiv.f29(a, width=WIDE, uid="f29w"),
        "svg_narrow": archiv.f29(a, width=NARROW, uid="f29n"),
        "caption": " ".join(parts),
        "table": {"caption": "Archivstände und Ausdünnung des Tagesarchivs", "head": ["Reihe", "Wert", "Zeitraum oder Bereich"], "rows": rows},
        "source": "BASG-Liste in den Fassungen des Archivs; Ausdünnung: eigene Auswertung",
    }


def _kurzname(key: str) -> str:
    from ..site import FOREIGN_SOURCES
    if key in NAMEN:
        return NAMEN[key]
    for country, title, k, _ in FOREIGN_SOURCES:
        if k == key:
            return f'{title.split(",")[0]} ({country})'
    return key  # as in the source table of the Methodik page


def versionen(root: Path | None) -> list[dict] | None:
    """New live versions per source, with the same rule and the same sources as the table on the Methodik page."""
    from ..site import SITE_UNLISTED_SOURCES
    if root is None or not (Path(root) / MANIFEST).exists():
        return None
    gezeigt = [k for k, s in SOURCES.items() if not s.watch and k not in SITE_UNLISTED_SOURCES]
    zahl = dict.fromkeys(gezeigt, 0)
    with (Path(root) / MANIFEST).open(encoding="utf-8") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except json.JSONDecodeError:
                continue  # a torn last line, as in `Archive.entries`
            if e.get("source") in zahl and e.get("origin") == "live" and e.get("ok") and not e.get("duplicate"):
                zahl[e["source"]] += 1
    zeilen = [{"key": k, "label": _kurzname(k), "versionen": v, "haupt": k == "basg"} for k, v in zahl.items()]
    return sorted(zeilen, key=lambda z: (-z["versionen"], z["label"]))


def f21_figure(zeilen: list[dict] | None) -> dict | None:
    if not zeilen:
        return None
    data = {"zeilen": zeilen}
    return {
        "id": "f21",
        "kind": "live",
        "legend": "Wie viele Fassungen liegen je Quelle im Archiv?",
        "svg_wide": archiv.f21(data, width=WIDE, uid="f21w"),
        "svg_narrow": archiv.f21(data, width=NARROW, uid="f21n"),
        "caption": ("Neue Fassungen seit dem ersten täglichen Abruf der jeweiligen Quelle. Als neue Fassung zählt nur eine geänderte Datei; "
                    "Quellen, die sich selten ändern, liegen deshalb weit unter der Zahl der Tage, solche mit mehreren Änderungen am Tag darüber. "
                    "Jede Fassung liegt unverändert mit Prüfsumme im Archiv."),
        "table": {"caption": "Archivierte Fassungen je Quelle", "head": ["Quelle", "Fassungen"],
                  "rows": [[z["label"], num(z["versionen"])] for z in zeilen]},
        "source": "Protokoll des Archivs (Manifest); eigene Auswertung",
    }


def _termin(results: dict, prefix: str) -> str:
    return de(date.fromisoformat(next(e["am"] for e in results["vorab_registrierung"]["zeitleiste"]
                                      if "am" in e and e["text"].startswith(prefix))))


def f16_figure(q: Quellen, zeilen: list[dict] | None) -> dict:
    from ..site import FOREIGN_SOURCES, SITE_HIDDEN_SOURCES
    listen = [country for country, _, key, _ in FOREIGN_SOURCES if key not in SITE_HIDDEN_SOURCES]
    data = {
        "auslandslisten": listen,
        "quellen": len(zeilen) if zeilen else 0,
        "fassungen": sum(z["versionen"] for z in zeilen) if zeilen else None,
        "fassungen_basg": next((z["versionen"] for z in zeilen if z["haupt"]), 0) if zeilen else None,
        "staende": len(q.data.snapshots),
        "packungen": len(q.data.packages),
        "episoden": sum(len(v) for v in q.data.eps.values()),
        "eingefroren": _termin(q.results, "Verfahren und Prüfplan eingefroren"),
        "zaehlt_ab": _termin(q.results, "Beginn der prospektiven Prüfung"),
    }
    rows = [["Quellen", f'BASG, ASP-Liste, Erstattungskodex, EudraGMDP und {num(len(listen))} Auslandslisten: {", ".join(listen)}']]
    fass = f'{num(data["fassungen"])} Fassungen der {num(data["quellen"])} Quellen in der Abruftabelle der Methodik-Seite, davon {num(data["fassungen_basg"])} der BASG-Liste; ' if data["fassungen"] is not None else ""
    rows += [["1 Sichern", f"{fass}jede neue Fassung byte-genau mit SHA-256, Manifest nur anhängend"],
             ["2 Verknüpfen", f'Datenbank, jedes Mal neu aus dem Archiv: {num(data["staende"])} BASG-Stände, {num(data["packungen"])} Packungen, {num(data["episoden"])} Episoden'],
             ["3 Schätzen", f'Frühwarnliste nach Länderzahl; Z3-Schätzung, eingefroren am {data["eingefroren"]}'],
             ["4 Zeigen", f'Website aus Datenbank und Frühwarnliste; Tagesprotokoll der Z3-Schätzung, es zählt ab {data["zaehlt_ab"]}; an die Website gehen daraus nur Summen']]
    return {
        "id": "f16",
        "kind": "live",
        "legend": "Von der Behördendatei zur Seite in vier Schritten",
        "svg_wide": archiv.f16(data, width=WIDE, uid="f16w"),
        "svg_narrow": archiv.f16(data, width=NARROW, uid="f16n"),
        "caption": ("Öffentliche Dateien werden unverändert gesichert, die Datenbank entsteht daraus bei jedem Lauf neu. Die Z3-Schätzung je Wirkstoff "
                    "bleibt im Tagesprotokoll; die Website zeigt daraus nur zusammengefasste Zahlen ohne einzelne Wirkstoffe. Die Zahlen stammen aus dem aktuellen Aufbau."),
        "table": {"caption": "Die Schritte des Aufbaus", "head": ["Schritt", "Was geschieht"], "rows": rows},
        "source": "eigene Darstellung; Zahlen aus Archiv und Datenbank",
    }


def f04_figure(q: Quellen, start: date | None) -> dict | None:
    p = q.data.by_pzn.get(BEISPIEL_PZN)
    eps = q.data.eps.get(p["package_key"], []) if p else []
    if not eps:
        return None
    key = p["package_key"]
    label = f'Zeitleiste {p["label"]}'
    args = (eps, q.data.listed[key], q.data.archive_days, q.ref)
    rows = []
    for e in eps:
        for when, what, derived in events(e, q.ref):
            rows.append([when, what + (" (eigene Auswertung)" if derived else "")])
    e = eps[-1]
    n = len(e.shifts())
    letzter = parse_day(e.resupply[-1][0]) if e.resupply else None
    satz = f'{p["label"]} (PZN {BEISPIEL_PZN}): gemeldet seit {de(e.start)}'
    if n and letzter:
        satz += f', der angekündigte Liefertermin in den Aufnahmen {num(n)}-mal verschoben, zuletzt auf den {de(letzter)}'
    satz += "."
    if not e.end_reason and letzter and letzter < q.ref:
        satz += f" Am Stichtag {de(q.ref)} ist dieser Termin verstrichen."
    teile = [satz, "Das Register zeigt davon nur den letzten Eintrag."]
    if start:
        teile.append(f"Schraffiert ist, was nicht beobachtet wurde; vor dem {de(start)} liegen nur einzelne Aufnahmen vor.")
    return {
        "id": "f04",
        "kind": "live",
        "legend": "Was das Register nicht zeigt: der Verlauf einer Packung",
        "svg_wide": Markup(timeline_svg(*args, WIDE, "f04w", label)),
        "svg_narrow": Markup(timeline_svg(*args, NARROW, "f04n", label)),
        "caption": " ".join(teile),
        "table": {"caption": f'Ereignisse der Packung {p["label"]}', "head": ["Datum", "Ereignis"], "rows": rows},
        "source": "BASG-Liste, amtliche Felder; Verschiebungen und Zeitachse: eigene Auswertung",
        "pfad": p["path"],
    }


def context(q: Quellen) -> dict:
    a = archiv_daten(q)
    zeilen = versionen(q.archive_root)
    f04 = f04_figure(q, a["start"])
    pfad = f04.pop("pfad") if f04 else None
    lue = a["luecke"]
    return {
        "f16": f16_figure(q, zeilen),
        "f29": f29_figure(a),
        "f21": f21_figure(zeilen),
        "f04": f04,
        "beispiel_pfad": pfad,
        "archiv": {
            "staende": num(len(a["staende"])),
            "taeglich": num(a["tagesstaende"]),
            "start": de(a["start"]) if a["start"] else None,
            "abstand": num(lue["median"]) if lue else None,
            "abgeschnitten": num(a["abgeschnitten"]),
        },
    }
