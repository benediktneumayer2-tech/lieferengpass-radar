"""Page context: early warning. Figures F05, F06 and F35, computed from the page's own list and the public sources."""
from __future__ import annotations

import sqlite3
from datetime import date

from markupsafe import Markup

from ..charts import NARROW, WIDE, lage, num, pct
from ..fruehwarnung import COUNTRY_NAMES, TIERS
from ..site import SITE_HIDDEN_SOURCES
from ..timeline import de
from . import Quellen

F06_ROWS = 20
RETRO_TAG = Markup('<span class="tag tone-warn">Rückblick · nicht validiert</span>')


def f05_data(fw: dict) -> dict | None:
    names = {"1": ("Ein Land (nicht gelistet)", "1 Land")}
    short = {"A": "A · ab 5 Länder", "B": "B · 3–4 Länder", "C": "C · 2 Länder"}
    tiers = [{"id": t, "name": names[t][0] if t == "1" else f"{t} · {TIERS[t]}",
              "short": names[t][1] if t == "1" else short[t],
              "8_wochen": fw["rates"][t]["8_wochen"], "12_wochen": fw["rates"][t]["12_wochen"]}
             for t in ("A", "B", "C", "1") if fw["rates"].get(t)]
    if not tiers:
        return None
    return {"tiers": tiers, "horizonte": [
        {"key": "8_wochen", "name": "binnen 8 Wochen", "base": fw["base"]["8_wochen"]["quote"]},
        {"key": "12_wochen", "name": "binnen 12 Wochen", "base": fw["base"]["12_wochen"]["quote"]},
    ]}


def _rate_cell(rate: dict) -> str:
    return f'{pct(rate["quote"])} ({pct(rate["ki95"][0])}–{pct(rate["ki95"][1])})'


def _count_cell(rate: dict) -> str:
    return f'{num(rate["treffer"])} von {num(rate["faelle"])}'


def f05_figure(fw: dict) -> dict | None:
    """Arguments of the `figure` macro. Kind `live`: it is rebuilt from the sources this site shows, so the
    sentence about the reference instance would be wrong here; the label sits in the legend instead."""
    data = f05_data(fw)
    if data is None:
        return None
    start, end = (de(date.fromisoformat(v)) for v in fw["period"])
    base = fw["base"]
    rows = [[t["name"], _rate_cell(t["8_wochen"]), _count_cell(t["8_wochen"]), _rate_cell(t["12_wochen"]), _count_cell(t["12_wochen"])]
            for t in data["tiers"]]
    rows.append(["Vergleich: schon einmal knapp in Österreich", pct(base["8_wochen"]["quote"]), _count_cell(base["8_wochen"]),
                 pct(base["12_wochen"]["quote"]), _count_cell(base["12_wochen"])])
    return {
        "id": "f05",
        "kind": "live",
        "legend": Markup("Wie oft folgte auf einen Hinweis eine BASG-Meldung? ") + RETRO_TAG,
        "svg_wide": lage.f05(data, width=WIDE, uid="f05w"),
        "svg_narrow": lage.f05(data, width=NARROW, uid="f05n"),
        "caption": f"Rückblick {start} bis {end} mit bekannten Verzerrungen. Punkte: Anteil der Hinweise mit neuer BASG-Meldung, "
                   "Striche: 95-%-Bereich. Die senkrechte Linie zeigt die Vergleichsgruppe: Wirkstoffe, die in Österreich schon "
                   "einmal knapp waren, ohne Blick ins Ausland. Ein Hinweis, keine Prognose, keine Bestellempfehlung.",
        "table": {"caption": "Anteil mit BASG-Meldung je Hinweisstufe, in Klammern der 95-%-Bereich",
                  "head": ["Stufe", "8 Wochen", "Meldungen von Fällen", "12 Wochen", "Meldungen von Fällen"], "rows": rows},
        "source": "BASG und die auf dieser Website genannten Engpasslisten anderer Behörden",
    }


def f06_data(fw: dict) -> dict | None:
    """The tier-A substances with the most countries, in the order of the list; columns by how often they report."""
    tier_a = [r for r in fw["rows"] if r["tier"] == "A"]
    chosen = sorted(tier_a, key=lambda r: -len(r["countries"]))[:F06_ROWS]  # stable: ties keep the order of the list
    if not chosen:
        return None
    counts: dict[str, int] = {}
    for row in chosen:
        for c in row["countries"]:
            counts[c] = counts.get(c, 0) + 1
    columns = [{"code": c, "name": COUNTRY_NAMES.get(c, c), "n": n} for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"rows": [{"label": r["label"], "countries": r["countries"], "names": r["country_names"]} for r in chosen],
            "columns": columns, "tier_a": len(tier_a)}


def f06_figure(fw: dict) -> dict | None:
    data = f06_data(fw)
    if data is None:
        return None
    n = len(data["rows"])
    return {
        "id": "f06",
        "kind": "live",
        "legend": "Welche Länder melden, was in Österreich noch lieferbar ist?",
        "svg_wide": lage.f06(data, width=WIDE, uid="f06w"),
        "svg_narrow": lage.f06(data, width=NARROW, uid="f06n"),
        "caption": f"Die {num(n)} von {num(data['tier_a'])} Wirkstoffen der Stufe A mit den meisten meldenden Ländern, bei Gleichstand in der Reihenfolge der Liste; ein Punkt je Land. "
                   "Zuordnung über den ATC-Code. Kein Beleg für einen Engpass in Österreich.",
        "table": {"caption": "Wirkstoffe der Stufe A und meldende Länder", "head": ["Wirkstoff", "Länder", "Gemeldet in"],
                  "rows": [[r["label"], num(len(r["countries"])), ", ".join(r["names"])] for r in data["rows"]]},
        "source": "Engpasslisten der auf dieser Website genannten Behörden; ASP-Liste",
    }


def f35_data(conn: sqlite3.Connection) -> list[dict]:
    """Running reports per public list, by the rule of `fruehwarnung.current_items` but also without an ATC code."""
    marks = ",".join("?" * len(SITE_HIDDEN_SOURCES))
    rows = conn.execute(
        "SELECT i.country, count(*), count(DISTINCT i.atc5), "
        "count(DISTINCT CASE WHEN EXISTS (SELECT 1 FROM foreign_links l WHERE l.item_id = i.item_id) THEN i.atc5 END) "
        f"FROM foreign_items i WHERE i.still_listed = 1 AND i.source NOT IN ({marks}) "
        "AND coalesce(i.status, '') != 'einstellung' AND NOT (i.end_date IS NOT NULL AND i.end_date <= i.last_seen) "
        "GROUP BY i.country", sorted(SITE_HIDDEN_SOURCES)).fetchall()
    data = [{"code": r[0], "name": COUNTRY_NAMES.get(r[0], r[0]), "reports": r[1], "substances": r[2], "at": r[3]} for r in rows]
    return sorted(data, key=lambda c: (-c["reports"], c["code"]))


def f35_figure(conn: sqlite3.Connection) -> dict | None:
    data = f35_data(conn)
    if not data:
        return None
    return {
        "id": "f35",
        "kind": "live",
        "legend": "Wo laufen gerade Meldungen?",
        "svg_wide": lage.f35(data, width=WIDE, uid="f35w"),
        "svg_narrow": lage.f35(data, width=NARROW, uid="f35n"),
        "caption": "Laufend heißt: noch in der Liste der Behörde, nicht dauerhaft eingestellt und ohne erreichtes Ende. "
                   "„In AT“ zählt Wirkstoffe mit mindestens einer Packung in der österreichischen ASP-Liste; der Balken zeigt diese Zahl. "
                   "Die Listen der Behörden sind unterschiedlich aufgebaut, die Zahlen daher nicht direkt vergleichbar und keine Rangfolge der Versorgungslage.",
        "table": {"caption": "Laufende Meldungen je Land", "head": ["Land", "Laufende Meldungen", "Wirkstoffe", "Davon mit Packung in AT"],
                  "rows": [[c["name"], num(c["reports"]), num(c["substances"]), num(c["at"])] for c in data]},
        "source": "Engpasslisten der auf dieser Website genannten Behörden; ASP-Liste",
    }


def context(q: Quellen) -> dict:
    return {"f05": f05_figure(q.fw), "f06": f06_figure(q.fw), "f35": f35_figure(q.conn)}
