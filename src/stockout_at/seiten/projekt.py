"""Page context: project overview. The story panels "Archivieren" and "Verknüpfen"; F08 and the test bench come from `showcase`."""
from __future__ import annotations

from ..charts import num
from ..timeline import de, events, timeline_svg
from . import Quellen
from .fruehwarnung import f05_figure

EXAMPLE_PACKAGE = "0774523"  # Kreon 10.000, the example of the public README


def archiv_panel(q: Quellen) -> dict | None:
    """The example package: one timeline, its text computed from the data."""
    data = q.data
    p, eps = data.packages.get(EXAMPLE_PACKAGE), data.eps.get(EXAMPLE_PACKAGE)
    if not p or not eps:
        return None
    e = eps[-1]
    shifts = len(e.shifts())
    times = "einmal" if shifts == 1 else f"{num(shifts)}-mal"
    since = f"beim BASG gemeldet seit {de(e.start)}" if e.active else f"beim BASG gemeldet ab {de(e.start)}, inzwischen beendet"
    label = f"Zeitleiste {p['label']}"
    rows = [[when, what] for episode in eps for when, what, _derived in events(episode, data.ref)]
    return {
        "name": p["label"],
        "path": p["path"],
        "text": f"Ein Beispiel: {p['label']} ist {since}, der angekündigte Termin wurde {times} verschoben. "
                "Die amtliche Liste zeigt davon nur den heutigen Stand.",
        "figure": {
            "id": "f04k",
            "kind": "live",
            "legend": f"Beispiel: {p['label']}",
            "svg_wide": timeline_svg(eps, data.listed[EXAMPLE_PACKAGE], data.archive_days, data.ref, 880, "f04kw", label),
            "svg_narrow": timeline_svg(eps, data.listed[EXAMPLE_PACKAGE], data.archive_days, data.ref, 300, "f04kn", label),
            "caption": "Band: Status laut BASG; sein schraffierter Anfang liegt vor der ersten Sichtung. Gestrichelt: angekündigte Termine, "
                       "Pfeile: ihre Verschiebungen (eigene Auswertung). Striche unter dem Band: Archivstände, vor dem 17.10.2026 "
                       "nur einzelne, seither täglich.",
            "table": {"caption": f"Ereignisse von {p['label']}", "head": ["Datum", "Ereignis"], "rows": rows},
            "source": "BASG-Liste, tägliches Archiv",
        },
    }


def verknuepf_panel(q: Quellen) -> dict | None:
    figure = f05_figure(q.fw)
    if figure is None:
        return None
    n = len(q.fw["sources"])
    return {
        "text": f"Der Radar gleicht die österreichische Liste mit den Engpasslisten von {num(n)} anderen Behörden ab und "
                "zeigt Wirkstoffe, die hier noch lieferbar, anderswo aber schon gemeldet sind. Ein Hinweis, keine Prognose.",
        "figure": figure,
    }


def context(q: Quellen) -> dict:
    return {"archiv": archiv_panel(q), "verknuepfen": verknuepf_panel(q)}
