"""Page context: radar. F23 on `/ueberfaellig/`, from the announced dates the site has already loaded."""
from __future__ import annotations

from datetime import date
from statistics import median

from markupsafe import Markup, escape

from ..charts import NARROW, WIDE, num
from ..charts.radar import f23, median_text
from ..timeline import d, de
from . import Quellen

# Size classes of a change, in days from the old to the new date: (name, range as printed, upper bound).
# The bounds are the longest 1, 3, 6 and 12 calendar months, so a move by whole months never lands one class too high.
# A change of 0 days cannot occur: two consecutive announced dates of an episode always differ.
KLASSEN = (
    ("vorgezogen", "neuer Termin früher", -1),
    ("bis 1 Monat", "1–31 Tage später", 31),
    ("1–3 Monate", "32–92 Tage später", 92),
    ("3–6 Monate", "93–184 Tage später", 184),
    ("6–12 Monate", "185–366 Tage später", 366),
    ("über 1 Jahr", "ab 367 Tagen später", None),
)


def klasse(days: float) -> int:
    """Index in `KLASSEN` of a change by `days`."""
    return next(i for i, (_, _, hi) in enumerate(KLASSEN) if hi is None or days <= hi)


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
            lines.append({"key": key, "pzn": p["pzn"] or "", "path": p["path"], "substance": p["substance"] or "", "steps": steps})
    if not lines:
        return None
    lines.sort(key=lambda ln: (ln["steps"][0][0], ln["pzn"], ln["key"]))
    moves = [(ln, seen, old, new) for ln in lines for seen, old, new in ln["steps"]]
    days = [(new - old).days for _, _, old, new in moves]
    # A change counts as "after the date" when the old date had already passed on the day the change was seen.
    classes = [{"name": name, "range": span, "n": 0, "n_after": 0} for name, span, _ in KLASSEN]
    for (_, seen, old, _), v in zip(moves, days):
        c = classes[klasse(v)]
        c["n"] += 1
        c["n_after"] += seen > old
    mid = median(days)
    return {
        "start": start, "ref": ref, "lines": lines,
        "n_with_date": len(with_date), "n_packages": len({ln["key"] for ln in lines}), "n_changes": len(moves),
        "n_later": sum(v > 0 for v in days), "n_earlier": sum(v < 0 for v in days),
        "median_days": mid, "median_class": klasse(mid), "classes": classes,
        "n_after_due": sum(seen > old for _, seen, old, _ in moves), "moves": moves,
    }


def _table(t: dict) -> dict:
    """One row per change, in the order of the figure: by size, then newest first. Packages by PZN and substance, never by holder."""
    rows = []
    for ln, seen, old, new in sorted(t["moves"], key=lambda m: ((m[3] - m[2]).days, -m[1].toordinal(), m[0]["pzn"], m[0]["key"])):
        name = escape(ln["pzn"] or "ohne PZN")
        days = (new - old).days
        rows.append([Markup('<a href="../{}">{}</a> <span class="small">{}</span>').format(ln["path"], name, ln["substance"]),
                     de(seen), de(old), de(new), num(days, 0, signed=True), KLASSEN[klasse(days)][0], "ja" if seen > old else "nein"])
    return {
        "caption": f'Alle {num(t["n_changes"])} Terminänderungen von {de(t["start"])} bis {de(t["ref"])}, nach Größe der Verschiebung',
        "head": ["Packung (PZN, Wirkstoff)", "gesehen am", "Termin bisher", "neuer Termin", "Änderung in Tagen", "Klasse",
                 "erst nach Ablauf"],
        "rows": rows,
    }


def context(q: Quellen) -> dict:
    t = termine(q.data, q.ref)
    if t is None:
        return {}
    start, ref = de(t["start"]), de(t["ref"])
    return {"f23": {
        "wide": f23(t, width=WIDE, uid="f23w"),
        "narrow": f23(t, width=NARROW, uid="f23n"),
        "n_with_date": num(t["n_with_date"]),
        "n_packages": num(t["n_packages"]),
        "n_changes": num(t["n_changes"]),
        "n_later": num(t["n_later"]),
        "n_earlier": num(t["n_earlier"]),
        "median": median_text(t),
        "n_after_due": num(t["n_after_due"]),
        "start": start,
        "caption": (f'Jede Änderung eines angekündigten Termins seit Beginn des Tagesarchivs am {start}, nach der Verschiebung '
                    'vom alten zum neuen Termin; eine Packung mit zwei Änderungen zählt zweimal. „Erst nach Ablauf“ heißt: Der '
                    f'alte Termin war am Tag der Änderung schon verstrichen. Änderungen vor dem {start} fehlen, weil das Archiv '
                    'davor lückenhaft ist. Die Grafik beschreibt die Meldungen und sagt nichts darüber, ob ein Termin hält.'),
        "source": f'BASG-Liste, tägliche Stände vom {start} bis {ref}. Termine wörtlich, Änderungen: eigene Auswertung.',
        "table": _table(t),
    }}
