"""Page context: radar. F23 on `/ueberfaellig/`, from the announced dates the site has already loaded."""
from __future__ import annotations

from datetime import date
from statistics import median

from markupsafe import Markup, escape

from ..charts import NARROW, WIDE, num
from ..charts.radar import f23
from ..timeline import d, de
from . import Quellen


def termine(data, ref: date) -> dict | None:
    """Date changes seen between two daily snapshots. The first daily snapshot is the baseline, not a change.

    A change dated on that first day only compares it with an older, sparse snapshot, so it is not counted.
    """
    live = [date.fromisoformat(s["snapshot_date"]) for s in data.snapshots if s["origin"] == "live"]
    start = min(live, default=None)
    if start is None or start >= ref:
        return None
    lines: list[dict] = []
    with_date: set[str] = set()
    for key, episodes in data.eps.items():
        for e in episodes:
            if e.last_seen < start:
                continue
            dates = [(day, seen) for day, seen in ((d(a), seen) for a, seen in e.resupply) if day and seen <= ref]
            if not dates:
                continue
            with_date.add(key)
            before = [x for x in dates if x[1] <= start]
            after = [x for x in dates if x[1] > start]
            chain = before[-1:] + after
            if len(chain) < 2:
                continue
            p = data.packages[key]
            steps = [(chain[i][1], chain[i - 1][0], chain[i][0]) for i in range(1, len(chain))]
            lines.append({
                "key": key, "pzn": p["pzn"] or "", "path": p["path"], "substance": p["substance"] or "",
                "start": max(chain[0][1], start), "end": min(e.last_seen, ref) if e.end_reason else ref,
                "first": chain[0][0], "steps": steps,
            })
    if not lines:
        return None
    lines.sort(key=lambda ln: (ln["steps"][0][0], ln["pzn"], ln["key"]))
    moves = [(ln, seen, old, new) for ln in lines for seen, old, new in ln["steps"]]
    days = [(new - old).days for _, _, old, new in moves]
    return {
        "start": start, "ref": ref, "lines": lines,
        "n_with_date": len(with_date), "n_packages": len({ln["key"] for ln in lines}), "n_changes": len(moves),
        "n_later": sum(v > 0 for v in days), "n_earlier": sum(v < 0 for v in days),
        "median_days": median(days), "n_after_due": sum(seen > old for _, seen, old, _ in moves), "moves": moves,
    }


def _table(t: dict) -> dict:
    """One row per change, newest first. Packages appear by PZN and substance, never by holder."""
    rows = []
    for ln, seen, old, new in sorted(t["moves"], key=lambda m: (-m[1].toordinal(), m[0]["pzn"], m[0]["key"], m[2])):
        name = escape(ln["pzn"] or "ohne PZN")
        rows.append([Markup('<a href="../{}">{}</a> <span class="small">{}</span>').format(ln["path"], name, ln["substance"]),
                     de(seen), de(old), de(new), num((new - old).days, 0, signed=True)])
    return {
        "caption": f'Alle {num(t["n_changes"])} Terminänderungen von {de(t["start"])} bis {de(t["ref"])}, neueste zuerst',
        "head": ["Packung (PZN, Wirkstoff)", "gesehen am", "Termin bisher", "neuer Termin", "Änderung in Tagen"],
        "rows": rows,
    }


def context(q: Quellen) -> dict:
    t = termine(q.data, q.ref)
    if t is None:
        return {}
    start, ref = de(t["start"]), de(t["ref"])
    decimals = 0 if t["median_days"] == int(t["median_days"]) else 1
    return {"f23": {
        "wide": f23(t, width=WIDE, uid="f23w"),
        "narrow": f23(t, width=NARROW, uid="f23n"),
        "n_with_date": num(t["n_with_date"]),
        "n_packages": num(t["n_packages"]),
        "n_changes": num(t["n_changes"]),
        "n_later": num(t["n_later"]),
        "n_earlier": num(t["n_earlier"]),
        "median": f'{num(t["median_days"], decimals, signed=True)} Tage',
        "n_after_due": num(t["n_after_due"]),
        "start": start,
        "caption": (f'Eine Linie je Packung, deren angekündigter Termin sich seit Beginn des Tagesarchivs am {start} '
                    f'geändert hat: {num(t["n_packages"])} von {num(t["n_with_date"])} Packungen mit Termin. Eine Stufe nach '
                    'oben heißt, der Termin wurde später gelegt. Die Diagonale ist der jeweilige Tag: Eine Linie darunter zeigt '
                    'einen Termin, der an diesem Tag schon verstrichen war. Jenseits der gestrichelten Linien ist die Achse '
                    f'gestaucht. Änderungen vor dem {start} fehlen, weil das Archiv davor lückenhaft ist. Die Grafik beschreibt '
                    'die Meldungen und sagt nichts darüber, ob ein Termin hält.'),
        "source": f'BASG-Liste, tägliche Stände vom {start} bis {ref}. Termine wörtlich, Änderungen: eigene Auswertung.',
        "table": _table(t),
    }}
