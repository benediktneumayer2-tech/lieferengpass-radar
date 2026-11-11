"""Daily feature log for Z3: one row per product (Zulassungsnummer) of the ASP list with what was known that day.

The log is the record for the prospective check and the training data for the Z3 model; nothing reads it back
except the § 21 first-seen date. It is written to <archive>/protokoll/merkmale/<year>/<day>.csv.gz so the mirror
copies it; a later run on the same day replaces the file.

Foreign columns use all archived sources (BfArM too: private, for the model); `hinweis` records what the
early-warning page showed (without hidden sources). Shadow features, logged but not used for any hint: § 21 AMG
("Einstellung des In-Verkehr-Bringens gemeldet" in the MIA product register) with the day it was first seen, and
per substance the number of valid CEP holders, the latest CEP suspension or withdrawal by EDQM for GMP and the
latest EudraGMDP non-compliance report on a CEP holder (module `gmp`), and the latest market exit of another product
of the substance in the ASP history (lieferbar -> not lieferbar, without an own active report; test T8) and the latest
deletion of another product of the substance from the green or yellow box of the EKO (module `eko`; test T9).
`z3_p4`/`z3_p8`/`z3_p12` are the frozen Z3 model's probabilities for the substance (module `modell`, not shown on
the website), empty while its substance has an active report or no model is frozen; `z3_fassung` names the version.
The predictions of all frozen methods go into a separate daily log per substance (`modell.write_log`).
"""
from __future__ import annotations

import csv
import gzip
import io
import os
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import fruehwarnung, gmp, metrics, modell, rueckblick, vorlauf
from .archive import Archive
from .foreign import holder_key

DIR = Path("protokoll") / "merkmale"
STOPPED = "Einstellung des In-Verkehr-Bringens gemeldet"
COLUMNS = [
    "datum", "basg_stand", "zulassungsnummer", "name", "atc5", "inhaber", "packungen", "lieferbar",
    "basg_produkt_aktiv", "basg_wirkstoff_aktiv", "basg_wirkstoff_frueher",
    "ausland_laender", "ausland_gleicher_inhaber", "ausland_stufe",
    "inhaberwechsel_am", "inhaberwechsel_gleiche_firma", "anderer_inhaber_gemeldet", "hinweis",
    "vertrieb_eingestellt_gemeldet", "vertrieb_eingestellt_seit",
    "cep_halter_gueltig", "cep_gmp_aussetzung_am", "gmp_ncr_am", "marktaustritt_anderes_produkt_am",
    "eko_streichung_anderes_produkt_am", "z3_fassung", "z3_p4", "z3_p8", "z3_p12",
]


def _latest_by_atc(events: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in events:
        d = e["date"].isoformat()
        if d > out.get(e["atc5"], ""):
            out[e["atc5"]] = d
    return out


def stopped(body: bytes | None) -> set[str] | None:
    """Zulassungsnummern flagged under § 21 AMG in the MIA product export (None without export)."""
    if not body:
        return None
    return {r["Zulassungsnummer"].strip() for r in rueckblick._csv(body) if r.get(STOPPED) == "Ja"}


def first_seen(flags: set[str], previous: dict[str, str] | None, day: str) -> dict[str, str]:
    """Day each flag was first seen: carried over from the previous log, today if new, '' if the log starts today."""
    if previous is None:
        return {zl: "" for zl in flags}
    return {zl: previous.get(zl, day) for zl in flags}


def previous_log(archive: Archive, day: str) -> dict[str, str] | None:
    """§ 21 first-seen days from the newest earlier log (None if there is none)."""
    files = sorted(p for p in (archive.root / DIR).glob("*/*.csv.gz") if p.name[:10] < day)
    if not files:
        return None
    with gzip.open(files[-1], "rt", encoding="utf-8", newline="") as fh:
        return {r["zulassungsnummer"]: r["vertrieb_eingestellt_seit"] for r in csv.DictReader(fh)
                if r["vertrieb_eingestellt_gemeldet"] == "1"}


def rows(conn: sqlite3.Connection, archive: Archive, day: str, hidden: frozenset, preds: dict | None = None) -> list[dict]:
    basg_day = conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0]
    ref = date.fromisoformat(basg_day)
    products = fruehwarnung.asp_products(conn)
    active_zl, active_by_atc = fruehwarnung.basg_active(conn)
    earlier = {a for (a,) in conn.execute("SELECT DISTINCT atc5 FROM episodes WHERE atc5 IS NOT NULL")}
    changes = fruehwarnung.holder_changes(archive, products)
    shown_changes = {r["zl"] for r in fruehwarnung.register_hints(products, active_zl, active_by_atc, changes, ref, {})["changes"]}

    items: dict[str, list[dict]] = defaultdict(list)
    for it in fruehwarnung.current_items(conn, frozenset()):
        items[it["atc5"]].append(it)
    holders: dict[str, dict[str, str]] = defaultdict(dict)
    marketed: set[str] = set()
    for p in products.values():
        if p["atc5"]:
            if p["holder_key"]:
                holders[p["atc5"]].setdefault(p["holder_key"], p["holder"])
            if p["lieferbar"]:
                marketed.add(p["atc5"])
    tiers, shown_tiers = {}, {}
    for atc5, its in items.items():
        tiers[atc5] = fruehwarnung.substance_tier(its, holders[atc5])
        visible = [it for it in its if it["source"] not in hidden]
        tier = fruehwarnung.substance_tier(visible, holders[atc5])[2] if visible else None
        if tier in ("A", "B", "C") and atc5 in marketed and atc5 not in active_by_atc:
            shown_tiers[atc5] = tier

    g = gmp.load(archive, [dict(r) for r in conn.execute("SELECT pzn, name, atc, substances, valid, inhaber FROM asp_packages")])
    cep_gmp, ncr = _latest_by_atc(g["cep_events"]), _latest_by_atc(g["ncr_events"])

    exits: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in rueckblick.asp_exits(rueckblick.AspHistory.load(archive), rueckblick._episode_rows(conn, ref)):
        if not e["own"]:
            exits[e["atc5"]].append((e["date"].isoformat(), e["zl"]))

    names = [(zl, (atc or "")[:7], name) for zl, atc, name in conn.execute(
        "SELECT DISTINCT zulassungsnummer, atc, approval_name FROM asp_packages WHERE approval_name != ''")]
    deletions: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in rueckblick.eko_events(archive, names):
        deletions[e["atc5"]].append((e["date"].isoformat(), e["zl"]))

    z3 = {a: {h: r["p"][h][modell.VERSION] for h in vorlauf.HORIZONS} for a, r in preds["zeilen"].items()} \
        if preds and modell.VERSION in preds["fassungen"] else {}
    z3_version = f"{modell.VERSION}:{preds['fassungen'][modell.VERSION][:12]}" if z3 else ""

    flags = stopped(rueckblick._latest(archive, "mia_asp"))
    seen = first_seen(flags or set(), previous_log(archive, day), day)

    out = []
    for zl, p in sorted(products.items()):
        atc5 = p["atc5"]
        countries, _, tier = tiers.get(atc5, ([], [], None))
        same = sorted({it["country"] for it in items.get(atc5, []) if p["holder_key"] and holder_key(it["holder"]) == p["holder_key"]})
        e = changes.get(zl)
        other = fruehwarnung.other_holder_reported(p, active_zl, active_by_atc)
        hints = [shown_tiers[atc5]] if atc5 in shown_tiers else []
        hints += ["inhaberwechsel"] * (zl in shown_changes) + ["anderer_inhaber"] * other
        out.append({
            "datum": day, "basg_stand": basg_day, "zulassungsnummer": zl, "name": p["name"], "atc5": atc5 or "",
            "inhaber": p["holder"] or "", "packungen": p["packages"], "lieferbar": p["lieferbar"],
            "basg_produkt_aktiv": int(zl in active_zl), "basg_wirkstoff_aktiv": int(atc5 in active_by_atc),
            "basg_wirkstoff_frueher": int(atc5 in earlier),
            "ausland_laender": " ".join(countries), "ausland_gleicher_inhaber": " ".join(same), "ausland_stufe": tier or "",
            "inhaberwechsel_am": e["date"].isoformat() if e else "", "inhaberwechsel_gleiche_firma": int(e["same_company"]) if e else "",
            "anderer_inhaber_gemeldet": int(other), "hinweis": "+".join(hints),
            "vertrieb_eingestellt_gemeldet": "" if flags is None else int(zl in flags),
            "vertrieb_eingestellt_seit": seen.get(zl, ""),
            "cep_halter_gueltig": g["valid_holders"].get(atc5, 0) if g["n_ceps"] and atc5 else "",
            "cep_gmp_aussetzung_am": cep_gmp.get(atc5, ""), "gmp_ncr_am": ncr.get(atc5, ""),
            "marktaustritt_anderes_produkt_am": max((d for d, z in exits.get(atc5, []) if z != zl), default=""),
            "eko_streichung_anderes_produkt_am": max((d for d, z in deletions.get(atc5, []) if z != zl), default=""),
            "z3_fassung": z3_version if atc5 in z3 else "",
            **{f"z3_p{h // 7}": round(z3[atc5][h], 4) if atc5 in z3 else "" for h in vorlauf.HORIZONS},
        })
    return out


def write(archive: Archive, day: str, data: list[dict]) -> Path:
    target = archive.root / DIR / day[:4] / f"{day}.csv.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(data)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as fh:
        fh.write(buf.getvalue().encode("utf-8"))
    os.replace(tmp, target)
    return target


def run(db_path: Path, archive: Archive, day: str, hidden: frozenset) -> tuple[Path, list[dict], Path | None]:
    """Feature log of the day and, with a frozen plan, the prediction log of all methods (both in the archive)."""
    conn = metrics.connect(db_path)
    try:
        ref = date.fromisoformat(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
        preds = modell.predict_all(conn, archive, ref)
        data = rows(conn, archive, day, hidden, preds)
    finally:
        conn.close()
    log = modell.write_log(archive.root, day, preds["zeilen"], preds["pruefplan"]) if preds else None
    return write(archive, day, data), data, log
