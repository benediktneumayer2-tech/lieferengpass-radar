"""Display-only data of the start-page figure F22 "Vorhersage gegen Meldung".

Imported only inside `site.generate()`. Reads the daily prediction logs and the report days, returns one dictionary
and writes nothing. No clock, no random numbers, no cache: mature results can still change when a report is
back-dated, so every run recomputes them. Everything returned is an aggregate; no ATC code, name or probability of a
single substance leaves this module.

Three phases by prediction day, never pooled: Rückblick 2026 (fixed numbers in `ergebnisse.json`), Einlaufphase
(every log day from 21.10.2026 to the day before the plan's start) and Prüfung (from the start, only the plan's
reference days, only rows written with the plan's hash: the same cases as `modell.bewerten`).
"""
from __future__ import annotations

import gzip
import hashlib
import math
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from pathlib import Path

from . import modell
from .vorlauf import _wilson

GRENZEN = (0.01, 0.02, 0.04, 0.08, 0.16)  # lower bound included
KLASSEN = ("unter 1 %", "1–2 %", "2–4 %", "4–8 %", "8–16 %", "ab 16 %")
KLASSEN_KURZ = ("<1", "1–2", "2–4", "4–8", "8–16", "≥16 %")
EINLAUF_START = date(2026, 10, 21)
RUECKBLICK_START = date(2026, 1, 1)
MIN_WIRKSTOFFE = 30  # a point in panel b needs at least this many substances
MIN_MELDUNGEN_ANTEIL = 20  # the top-50 share is given in percent from this many new reports
TOP_K = modell.LEAD_K
MAX_ABSTAND = 7  # days between a new report and the log day it is compared with


def _klasse(p: float) -> int:
    return bisect_right(GRENZEN, p)


def _read_logs(root: Path, column: str, beginn: date, sha: str, only: set[date] | None = None) -> dict[date, dict[str, float]]:
    """Day -> ATC5 -> probability, from the four columns that matter. The day is the file's, as in `modell.read_logs`;
    from the plan's start only rows written with the plan count, and a day without such rows does not exist."""
    out: dict[date, dict[str, float]] = {}
    for path in sorted((Path(root) / modell.LOG_DIR).glob("*/*.csv.gz")):
        day = date.fromisoformat(path.name[:10])
        if only is not None and day not in only:
            continue
        with gzip.open(path, "rb") as fh:
            lines = fh.read().split(b"\n")
        head = lines[0].decode().split(",")
        ia, ip, iz = head.index("atc5"), head.index(column), head.index("pruefplan")
        want = sha.encode() if day >= beginn else None
        rows: dict[str, float] = {}
        for line in lines[1:]:
            if line:
                f = line.split(b",")
                if want is None or f[iz] == want:
                    rows[f[ia].decode()] = float(f[ip])
        if rows:
            out[day] = rows
    return out


def _events(starts: dict[str, list[date]], seen: dict[str, list[date]]) -> dict[str, list[int]]:
    """Per substance the sorted days on which a report begins or first appears: the outcome of the plan."""
    out: dict[str, set[int]] = {}
    for source in (starts, seen):
        for a, days in source.items():
            out.setdefault(a, set()).update(d.toordinal() for d in days)
    return {a: sorted(v) for a, v in out.items()}


def _interval(per: dict[str, list[int]], n: int, k: int) -> list[float] | None:
    """95 % range over substances (cluster-robust on the logit scale); no random numbers."""
    g = len(per)
    if g < 2:
        return None
    if k == 0:
        return [0.0, 1 - 0.05 ** (1 / g)]
    if k == n:
        return [0.05 ** (1 / g), 1.0]
    rate = k / n
    v = g / (g - 1) * sum((kc - rate * nc) ** 2 for nc, kc in per.values()) / n ** 2
    half = 1.96 * math.sqrt(v) / (rate * (1 - rate))
    centre = math.log(rate / (1 - rate))
    return [1 / (1 + math.exp(-(centre - half))), 1 / (1 + math.exp(-(centre + half)))]


def _pool(cells: list[dict]) -> list[list[int]]:
    """Neighbouring classes joined until each group has enough substances; the outermost small group moves to the middle."""
    groups = [[i] for i, c in enumerate(cells) if c["n"]]
    size = lambda group: len({a for i in group for a in cells[i]["per"]})
    while len(groups) > 1:
        small = [i for i, group in enumerate(groups) if size(group) < MIN_WIRKSTOFFE]
        if not small:
            break
        mid = (len(groups) - 1) / 2
        i = max(small, key=lambda j: (abs(j - mid), -j))
        j = i + 1 if i < mid else i - 1
        lo, hi = min(i, j), max(i, j)
        groups[lo:hi + 1] = [groups[lo] + groups[hi]]
    return groups


def _point(cells: list[dict], group: list[int]) -> dict:
    per: dict[str, list[int]] = {}
    n = k = 0
    total = 0.0
    for i in group:
        c = cells[i]
        n, k, total = n + c["n"], k + c["k"], total + c["p"]
        for a, (nc, kc) in c["per"].items():
            s = per.setdefault(a, [0, 0])
            s[0] += nc
            s[1] += kc
    return {"klassen": group, "n": n, "wirkstoffe": len(per), "treffer": k,
            "wirkstoffe_mit_meldung": sum(1 for _, kc in per.values() if kc),
            "vorhergesagt": total / n, "beobachtet": k / n, "ki95": _interval(per, n, k)}


def aggregate(logs: dict[date, dict[str, float]], days: list[date], events: dict[str, list[int]], stand: date, h: int) -> dict:
    """Mature cases of these prediction days, per class: the one function behind all three phases."""
    cells = [{"n": 0, "k": 0, "p": 0.0, "per": {}} for _ in KLASSEN]
    mature = [d for d in days if d + timedelta(days=h) <= stand]
    for d in mature:
        day = d.toordinal()
        for a, p in logs[d].items():
            ev = events.get(a)
            y = 0
            if ev:
                i = bisect_right(ev, day)
                y = int(i < len(ev) and ev[i] <= day + h)
            c = cells[_klasse(p)]
            c["n"] += 1
            c["k"] += y
            c["p"] += p
            s = c["per"].setdefault(a, [0, 0])
            s[0] += 1
            s[1] += y
    substances = {a for c in cells for a in c["per"]}
    hit = {a for c in cells for a, (_, kc) in c["per"].items() if kc}
    enough = len(substances) >= MIN_WIRKSTOFFE
    return {"protokolltage_reif": len(mature), "faelle": sum(c["n"] for c in cells), "wirkstoffe": len(substances),
            "treffer": sum(c["k"] for c in cells), "wirkstoffe_mit_meldung": len(hit),
            "punkte": [_point(cells, g) for g in _pool(cells)] if enough else [],
            "zu_wenige": bool(mature) and not enough}


def _next_date(logs: dict[date, dict], von: date, bis: date | None, step: int, stand: date, h: int) -> date | None:
    """The next day on which another prediction day of this phase becomes mature."""
    if not logs:
        return None
    last = max(logs)
    d = max(von, stand - timedelta(days=h - 1))
    d += timedelta(days=(von - d).days % step)
    while bis is None or d <= bis:
        if d > last or d in logs:
            return d + timedelta(days=h)
        d += timedelta(days=step)
    return None


def _new_reports(logs: dict[date, dict[str, float]], seen: dict[str, list[date]], von: date, beginn: date) -> dict[str, list]:
    """New reports per phase of their prediction day: class and top-50 place on the last log day before the report."""
    days = sorted(logs)
    order: dict[str, str] = {}
    tops: dict[date, set[str]] = {}
    out: dict[str, list] = {"einlauf": [], "pruefung": []}
    for a, ds in seen.items():
        for t in sorted(set(ds)):
            i = bisect_left(days, t) - 1
            if i < 0:
                continue
            last = days[i]
            if (t - last).days > MAX_ABSTAND or last < von or a not in logs[last]:
                continue
            if last not in tops:
                rows = logs[last]
                for b in rows:
                    order.setdefault(b, hashlib.md5(b.encode()).hexdigest())
                tops[last] = set(sorted(rows, key=lambda b: (-rows[b], order[b]))[:TOP_K])
            out["einlauf" if last < beginn else "pruefung"].append((_klasse(logs[last][a]), a in tops[last]))
    return out


def _reports_summary(rows: list[tuple[int, bool]]) -> dict:
    je = [0] * len(KLASSEN)
    for c, _ in rows:
        je[c] += 1
    top = sum(1 for _, on_top in rows if on_top)
    return {"anzahl": len(rows), "je_klasse": je, "top50": top,
            "top50_ki95": _wilson(top, len(rows)) if len(rows) >= MIN_MELDUNGEN_ANTEIL else None}


def _plan() -> tuple[date, int, str]:
    loaded = modell.load_plan()
    if not loaded:
        return modell.PROSPECTIVE_START, modell.STEP, ""
    plan = loaded[0]
    return date.fromisoformat(plan["beginn"]), plan["schritt_tage"], plan["sha256"][:12]


def build(conn, archive_root: Path | str | None, results: dict, horizon: int = 56) -> dict:
    """All numbers of F22 for one horizon in days. Without logs (test build) the empty state."""
    beginn, step, sha = _plan()
    starts, seen, _, stand = modell.report_days(conn)
    logs = _read_logs(Path(archive_root), f"z3_v0_p{horizon // 7}", beginn, sha) if archive_root else {}
    events = _events(starts, seen)
    reports = _new_reports(logs, seen, EINLAUF_START, beginn)

    def phase(key: str, von: date, bis: date | None, days: list[date], every: int) -> dict:
        return {"von": von.isoformat(), "bis": bis.isoformat() if bis else None,
                **aggregate(logs, days, events, stand, horizon),
                "naechster_termin": (lambda t: t.isoformat() if t else None)(_next_date(logs, von, bis, every, stand, horizon)),
                "meldungen": _reports_summary(reports[key])}

    einlauf_bis = beginn - timedelta(days=1)
    einlauf = phase("einlauf", EINLAUF_START, einlauf_bis, sorted(d for d in logs if EINLAUF_START <= d <= einlauf_bis), 1)
    pruefung = phase("pruefung", beginn, None, sorted(d for d in logs if d >= beginn and (d - beginn).days % step == 0), step)
    pruefung["stichtage_reif"] = pruefung["protokolltage_reif"]

    last = max(logs) if logs else None
    rows = logs[last] if last else {}
    je = [0] * len(KLASSEN)
    for p in rows.values():
        je[_klasse(p)] += 1
    block = results.get("vorhersage_gegen_meldung") or {}
    band = (block.get("horizonte") or {}).get(str(horizon))
    return {
        "stand": stand.isoformat(), "protokoll_bis": last.isoformat() if last else None, "horizont_tage": horizon,
        "beginn": beginn.isoformat(), "grenzen": list(GRENZEN),
        "klassen": [{"name": n, "kurz": k} for n, k in zip(KLASSEN, KLASSEN_KURZ)],
        "heute": {"wirkstoffe": len(rows), "je_klasse": je, "erwartet": round(sum(rows.values()), 1)},
        "einlauf": einlauf, "pruefung": pruefung,
        "rueckblick": {**band, "basg_stand": block.get("basg_stand")} if band else None,
    }


def rueckblick_band(conn, root: Path | str, horizon: int = 56) -> dict:
    """The retrospective band for `ergebnisse.json`: the same aggregation on the simulated log
    (`data/derived/vorhersagen_rueckblick`), every 14 days from 01.01.2026."""
    beginn, _, sha = _plan()
    starts, seen, _, stand = modell.report_days(conn)
    grid = {RUECKBLICK_START + timedelta(days=i * modell.STEP) for i in range(27)}
    logs = _read_logs(Path(root), f"z3_v0_p{horizon // 7}", beginn, sha, grid)
    out = aggregate(logs, sorted(logs), _events(starts, seen), stand, horizon)
    del out["zu_wenige"]
    out["stichtage"] = out.pop("protokolltage_reif")
    for p in out["punkte"]:
        p["vorhergesagt"] = round(p["vorhergesagt"], 7)
        p["beobachtet"] = round(p["beobachtet"], 7)
        p["ki95"] = [round(v, 7) for v in p["ki95"]]
    out["basg_stand"] = stand.isoformat()
    return out
