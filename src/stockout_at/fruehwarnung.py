"""Early-warning list: Austrian substances (ATC5) still available and not reported at BASG, with current foreign reports.

A hint, not a forecast. The tier follows the lead-time measurement: one country alone adds nothing measurable,
two countries a little, three or four more, five or more the most. A shared marketing authorisation holder is shown
but no longer sets the tier: at the same number of countries it added nothing that held in 2026 (`schaerfe`).
Each tier carries its historical hit rate from `vorlauf` (same hidden sources).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import rueckblick, vorlauf
from .archive import SOURCES, Archive
from .foreign import holder_key

COUNTRY_NAMES = {
    "DE": "Deutschland", "EU": "EU (EMA)", "IT": "Italien", "CZ": "Tschechien", "SK": "Slowakei", "HU": "Ungarn",
    "SI": "Slowenien", "BE": "Belgien", "FI": "Finnland", "ES": "Spanien", "US": "USA", "FR": "Frankreich",
    "PL": "Polen",
}
SOURCE_NAMES = {
    "bfarm": "BfArM", "ema": "EMA", "aifa": "AIFA", "sukl_cz": "SÚKL", "sukl_sk": "ŠÚKL", "ogyei": "OGYÉI",
    "jazmp": "JAZMP", "famhp": "FAMHP", "fimea": "Fimea", "cima": "AEMPS (CIMA)", "fda": "FDA", "ansm": "ANSM",
    "pl_mz": "Gesundheitsministerium PL",
}
SOURCE_PAGES = {"ansm": "https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments",  # instead of the export
                "pl_mz": "https://dziennikmz.mz.gov.pl/"}
TIERS = {
    "A": "5 oder mehr Länder",
    "B": "3 oder 4 Länder",
    "C": "2 Länder",
}
MAX_PRODUCTS = 5
CHANGE_DAYS = 56  # changes of the holder entry from the last 8 weeks (the measured horizon)


def source_url(source: str) -> str:
    return SOURCE_PAGES.get(source) or SOURCES[source].url.format(page=1)


def current_items(conn: sqlite3.Connection, hidden: frozenset) -> list[dict]:
    """Foreign reports listed in the latest file of their source, not ended and not a permanent discontinuation."""
    out = []
    for r in conn.execute(
        "SELECT * FROM foreign_items WHERE still_listed = 1 AND atc5 IS NOT NULL AND coalesce(status, '') != 'einstellung' "
        "ORDER BY country, source, signal_date, item_id"
    ):
        r = dict(r)
        if r["source"] in hidden or (r["end_date"] and r["end_date"] <= r["last_seen"]):
            continue
        out.append(r)
    return out


def by_country(items: list[dict], matches: dict[str, dict] | None = None) -> list[dict]:
    """Group reports of one substance by country for display (first few products, holders, dates)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it["country"]].append(it)
    out = []
    for country in sorted(groups, key=lambda c: COUNTRY_NAMES.get(c, c)):
        its = groups[country]
        products = sorted({it["product"] or it["substances"] or "–" for it in its})
        m = [matches[it["item_id"]] for it in its if matches and it["item_id"] in matches]
        out.append({
            "country": country,
            "name": COUNTRY_NAMES.get(country, country),
            "sources": sorted({it["source"] for it in its}),
            "source_names": ", ".join(sorted({SOURCE_NAMES.get(it["source"], it["source"]) for it in its})),
            "source_url": source_url(its[0]["source"]),
            "n": len(its),
            "products": products[:MAX_PRODUCTS],
            "more": max(len(products) - MAX_PRODUCTS, 0),
            "holders": sorted({it["holder"] for it in its if it["holder"]})[:3],
            "since": min((it["signal_date"] for it in its if it["signal_date"]), default=None),
            "until": max((it["expected_end"] for it in its if it["expected_end"]), default=None),
            "holder_match": any(x["holder_match"] for x in m),
            "strength_match": any(x["strength_match"] for x in m),
        })
    return out


def _rate(block: dict) -> dict:
    return {k: block[k] for k in ("8_wochen", "12_wochen")}


def substance_tier(its: list[dict], holders: dict[str, str]) -> tuple[list[str], list[dict], str | None]:
    """Countries, holder matches (`holders`: holder key -> name of the Austrian holders) and tier of one substance."""
    countries = sorted({it["country"] for it in its})
    holder_hits = []
    for hk, name in holders.items():
        cs = sorted({it["country"] for it in its if holder_key(it["holder"]) == hk})
        if cs:
            holder_hits.append({"holder": name, "countries": cs})
    holder_hits.sort(key=lambda h: (-len(h["countries"]), h["holder"]))
    return countries, holder_hits, vorlauf.tier(len(countries)) if countries else None


# --- hints from the BASG registers (retrospective test: `stockout rueckblick`) -------------------

def asp_products(conn: sqlite3.Connection) -> dict[str, dict]:
    """Products of the ASP list by Zulassungsnummer: name, ATC5, holder, packages, marketed packages."""
    out: dict[str, dict] = {}
    for zl, name, atc, inhaber, lieferbar, subs in conn.execute(
        "SELECT zulassungsnummer, coalesce(approval_name, name), atc, inhaber, lieferbar, substances FROM asp_packages "
        "WHERE valid = 1 AND zulassungsnummer IS NOT NULL AND zulassungsnummer != '' ORDER BY pzn"
    ):
        p = out.setdefault(zl, {"zl": zl, "name": name, "atc5": atc[:7] if atc and len(atc) >= 7 else None,
                                "holder": inhaber, "holder_key": holder_key(inhaber), "substances": subs,
                                "packages": 0, "lieferbar": 0})
        p["packages"] += 1
        p["lieferbar"] += lieferbar or 0
    return out


def basg_active(conn: sqlite3.Connection) -> tuple[set[str], dict[str, dict[str, str]]]:
    """Zulassungsnummern with an active BASG report, and per ATC5 the reporting holders (key -> name)."""
    active_zl = {zl for (zl,) in conn.execute(
        "SELECT DISTINCT p.zulassungsnummer FROM episodes e JOIN packages p USING (package_key) "
        "WHERE e.active = 1 AND p.zulassungsnummer IS NOT NULL")}
    by_atc: dict[str, dict[str, str]] = defaultdict(dict)
    for atc5, holder in conn.execute("SELECT atc5, zulassungsinhaber FROM episodes WHERE active = 1 AND atc5 IS NOT NULL"):
        name = rueckblick._company(holder or "") or "unbekannt"
        by_atc[atc5].setdefault(holder_key(holder) or name, name)
    return active_zl, dict(by_atc)


def holder_changes(archive: Archive | None, products: dict[str, dict]) -> dict[str, dict]:
    """Latest change of the holder entry per Zulassungsnummer (MIA Verlautbarungen)."""
    body = rueckblick._latest(archive, "mia_verl") if archive is not None else None
    if not body:
        return {}
    out: dict[str, dict] = {}
    for e in rueckblick.mia_events(body, {zl: p["atc5"] for zl, p in products.items() if p["atc5"]}):
        if e["kind"] == "inhaberwechsel" and (e["zl"] not in out or e["date"] >= out[e["zl"]]["date"]):
            out[e["zl"]] = e
    return out


def register_rates(path: Path | None) -> dict | None:
    """Hit rates of the two register hints from the retrospective JSON (`stockout rueckblick`)."""
    if path is None or not Path(path).exists():
        return None
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    iw = ((r.get("t1_ausstieg") or {}).get("inhaberwechsel") or {}).get("vermarktet", {}).get("ja")
    oh = (r.get("t6_nachbarn") or {}).get("anderer_inhaber_gleicher_wirkstoff")
    if not oh:
        return None
    return {
        "period": r["zeitraum"],
        "inhaberwechsel": {k: iw[k] for k in ("8_wochen", "12_wochen")} if iw else None,  # None without announcements
        "anderer_inhaber": {k: {**oh[k]["mit"], "sir": oh[k]["sir"], "sir_ki95": oh[k]["sir_ki95"], "ohne": oh[k]["ohne"]["quote"]}
                            for k in ("8_wochen", "12_wochen")},
    }


def other_holder_reported(p: dict, active_zl: set[str], active_by_atc: dict[str, dict[str, str]]) -> bool:
    """Marketed product without own report whose substance is reported by another holder."""
    reported = active_by_atc.get(p["atc5"])
    return bool(reported and p["lieferbar"] and p["zl"] not in active_zl and p["holder_key"] not in reported)


def register_hints(products: dict[str, dict], active_zl: set[str], active_by_atc: dict[str, dict[str, str]],
                   changes: dict[str, dict], ref: date, substance_paths: dict[str, tuple[str, str | None]]) -> dict:
    """Marketed products after a recent change of the holder entry (substance not reported), and reported
    substances with marketed products of other holders."""
    names: dict[str, Counter] = defaultdict(Counter)
    for p in products.values():
        if p["atc5"] and p["substances"]:
            names[p["atc5"]][p["substances"]] += 1

    def label_path(atc5: str) -> tuple[str, str | None]:
        label, path = substance_paths.get(atc5, (None, None))
        return label or (names[atc5].most_common(1)[0][0] if names.get(atc5) else atc5), path

    rows = []
    for zl, e in changes.items():
        p = products.get(zl)
        atc5 = (p or {}).get("atc5") or e["atc5"]
        if not p or not p["lieferbar"] or atc5 in active_by_atc or not 0 <= (ref - e["date"]).days < CHANGE_DAYS:
            continue
        label, path = label_path(atc5)
        rows.append({"zl": zl, "name": p["name"] or e["product"], "atc5": atc5, "label": label, "path": path,
                     "date": e["date"], "prev": e["prev_name"], "now": e["holder_name"], "same_company": e["same_company"],
                     "lieferbar": p["lieferbar"], "packages": p["packages"]})
    rows.sort(key=lambda r: (r["date"], r["zl"]), reverse=True)

    others = []
    for atc5, reported in active_by_atc.items():
        remaining: dict[str, dict] = {}
        for zl, p in products.items():
            if p["atc5"] == atc5 and other_holder_reported(p, active_zl, active_by_atc):
                h = remaining.setdefault(p["holder_key"] or zl, {"holder": rueckblick._company(p["holder"] or "") or "unbekannt",
                                                                 "lieferbar": 0, "products": 0})
                h["lieferbar"] += p["lieferbar"]
                h["products"] += 1
        if remaining:
            label, path = label_path(atc5)
            others.append({"atc5": atc5, "label": label, "path": path, "reported": sorted(reported.values()),
                           "remaining": sorted(remaining.values(), key=lambda h: (-h["lieferbar"], h["holder"]))})
    others.sort(key=lambda o: (len(o["remaining"]), o["label"]))
    return {"changes": rows, "others": others}


def build(conn: sqlite3.Connection, hidden: frozenset, substance_paths: dict[str, tuple[str, str | None]],
          archive: Archive | None = None, rates_path: Path | None = None, ref: date | None = None) -> dict:
    """Rows of the early-warning list, per-ATC5 report groups for detail pages, historical rates per tier, and
    the hints from the BASG registers (only with the archive; their rates from the retrospective JSON).

    `substance_paths`: ATC5 -> (label, site path or None) for substances that have a page.
    """
    items = current_items(conn, hidden)
    items_by_atc: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        items_by_atc[it["atc5"]].append(it)

    at: dict[str, dict] = defaultdict(lambda: {"packages": 0, "lieferbar": 0, "holders": {}, "substances": Counter()})
    for _pzn, inhaber, atc, subs, lieferbar in conn.execute(
        "SELECT pzn, inhaber, atc, substances, lieferbar FROM asp_packages WHERE valid = 1 AND length(atc) >= 7"
    ):
        a = at[atc[:7]]
        a["packages"] += 1
        a["lieferbar"] += lieferbar or 0
        hk = holder_key(inhaber)
        if hk:
            a["holders"].setdefault(hk, inhaber)
        if subs:
            a["substances"][subs] += 1
    reported = {r[0] for r in conn.execute("SELECT DISTINCT atc5 FROM episodes WHERE active = 1 AND atc5 IS NOT NULL")}
    last_at = dict(conn.execute("SELECT atc5, max(start_date) FROM episodes WHERE atc5 IS NOT NULL GROUP BY atc5"))

    rows, single = [], 0
    for atc5, its in items_by_atc.items():
        a = at.get(atc5)
        if not a or not a["lieferbar"] or atc5 in reported:
            continue
        countries, holder_hits, tier = substance_tier(its, a["holders"])
        if tier == "1":
            single += 1
            continue
        label, path = substance_paths.get(atc5, (None, None))
        rows.append({
            "atc5": atc5,
            "label": label or (a["substances"].most_common(1)[0][0] if a["substances"] else atc5),
            "path": path,
            "tier": tier,
            "countries": countries,
            "country_names": [COUNTRY_NAMES.get(c, c) for c in countries],
            "holder_hits": holder_hits[:3],
            "lieferbar": a["lieferbar"],
            "packages": a["packages"],
            "last_at": last_at.get(atc5),
            "newest": max(it["signal_date"] for it in its if it["signal_date"]),
            "groups": by_country(its),
        })
    rows.sort(key=lambda r: (r["tier"], -len(r["countries"]), -len(r["holder_hits"][0]["countries"]) if r["holder_hits"] else 0,
                             r["newest"] and -int(r["newest"].replace("-", "")), r["atc5"]))

    ref = ref or date.fromisoformat(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
    products = asp_products(conn)
    active_zl, active_by_atc = basg_active(conn)
    register = register_hints(products, active_zl, active_by_atc, holder_changes(archive, products), ref, substance_paths)
    register["available"] = archive is not None
    # the holder-change hint needs archived BASG announcements (`mia_verl`), which this code does not fetch: shown only with them
    register["holder_data"] = archive is not None and bool(rueckblick._unique_files(archive, "mia_verl"))
    register["rates"] = register_rates(rates_path)

    m = vorlauf.measure(conn, exclude_sources=hidden)
    tiers = m["laender_kombiniert"]["wirkstoff"]["nach_stufe"]
    rates = {t: _rate(tiers[t]) if t in tiers else None for t in ("A", "B", "C", "1")}
    return {
        "rows": rows,
        "counts": Counter(r["tier"] for r in rows),
        "single": single,
        "rates": rates,
        "base": _rate(m["grundrate_wirkstoff_engpass_vorgeschichte"]),
        "period": m["zeitraum"],
        "items_by_atc": items_by_atc,
        "countries": sorted({it["country"] for it in items}, key=lambda c: COUNTRY_NAMES.get(c, c)),
        "sources": sorted({it["source"] for it in items}),
        "register": register,
    }
