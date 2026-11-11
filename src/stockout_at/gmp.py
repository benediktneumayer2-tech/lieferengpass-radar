"""GMP signals of active-substance manufacturers: EDQM CEP file and EudraGMDP non-compliance reports (NCR).

A CEP certifies one manufacturer (holder) of one active substance. The substance name (English) is linked to
all Austrian ATC5 codes of that substance, since an active-substance supplier can serve every product; which
supplier is in which Austrian dossier is confidential. NCRs carry no substance: they are linked to CEP holders
by SPOR location ID, else by company word and country, and through their CEPs to substances.

Shadow features only: logged and tested retrospectively, not shown. The CEP file shows the current status; a
suspension that EDQM has lifted again is no longer visible, so older GMP events are undercounted.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from .foreign import LEGAL_WORDS, _ascii, holder_key, parse_date, read_xls, skeleton
from .substances import base_substance

GMP_STATUS = ("Suspended by EDQM GMP non-compliance", "Withdrawn by EDQM GMP non-compliance")
COUNTRY_CODES = {
    "India": "IN", "China": "CN", "Netherlands": "NL", "Italy": "IT", "Czechia": "CZ", "Poland": "PL", "Spain": "ES",
    "United States": "US", "Canada": "CA", "South Africa": "ZA", "Romania": "RO", "Austria": "AT", "Sri Lanka": "LK",
    "Portugal": "PT", "Malaysia": "MY", "Türkiye": "TR", "Taiwan": "TW", "Indonesia": "ID", "Lebanon": "LB",
    "Bangladesh": "BD", "Cyprus": "CY", "France": "FR", "Hungary": "HU", "Germany": "DE", "Switzerland": "CH",
    "Korea, Republic of": "KR", "Japan": "JP", "Israel": "IL", "Slovenia": "SI", "Ireland": "IE", "Belgium": "BE",
    "United Kingdom": "GB", "Mexico": "MX", "Brazil": "BR", "Argentina": "AR", "Egypt": "EG", "Jordan": "JO",
}


NAME_FILLERS = frozenset("CO LTD PVT PRIVATE SDN BHD CITY INC CORP CORPORATION COMPANY PHARM".split())


def name_words(name: str) -> list[str]:
    """Distinctive words of a company name ('Lianyungang Guike Pharmaceutical Co. Ltd' -> LIANYUNGANG, GUIKE)."""
    return [w for w in re.findall(r"[A-Z0-9]+", _ascii(name).upper())
            if len(w) >= 2 and w not in LEGAL_WORDS and w not in NAME_FILLERS]


def substance_atcs(name: str, by_substance: dict[str, set[str]]) -> set[str]:
    """ATC5 codes of an (English) active-substance name: whole name, base form, then its longest words."""
    head = name.split(",")[0].strip()
    for key in (skeleton(head), skeleton(base_substance(head.upper()))):
        if key in by_substance:
            return set(by_substance[key])
    for word in sorted(re.findall(r"[A-Za-z]{5,}", _ascii(head)), key=len, reverse=True):
        hit = by_substance.get(skeleton(word))
        if hit:
            return set(hit)
    return set()


def parse_cep(body: bytes) -> list[dict]:
    """CEP file rows (tab-separated): substance, holder, SPOR IDs, holder country, status and its end date."""
    out = []
    for r in csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""), delimiter="\t"):
        if r.get("Type CEP") == "TSE":  # TSE-only certificates cover excipients' animal origin, not supply
            continue
        holder = (r.get("Certificate (CEP) Holder") or "").strip()
        country = holder.rsplit(" ", 1)[-1] if re.search(r" [A-Z]{2}$", holder) else None
        out.append({
            "substance": (r.get("Substance") or "").strip(), "holder": holder, "holder_key": holder_key(holder),
            "country": country, "ids": {x.strip() for x in (r.get("Holder SPOR ORG-ID / SPOR LOC-ID") or "").split("/") if x.strip()},
            "status": (r.get("Status CEP") or "").strip(), "end": parse_date(r.get("End date CEP")),
        })
    return out


def parse_ncr(body: bytes) -> list[dict]:
    """EudraGMDP non-compliance list export (xls): report, site, location ID, country, dates."""
    rows = read_xls(body)
    head = next((i for i, r in enumerate(rows) if "Report Number" in r), None)
    if head is None:
        return []
    out = []
    for r in rows[head + 1:]:
        n = dict(zip(rows[head], r))
        if not n.get("Report Number"):
            continue
        out.append({
            "report": n["Report Number"], "site": n.get("Site Name", ""), "loc": n.get("OMS Location Identifier", "").removeprefix("LOC-"),
            "country": COUNTRY_CODES.get(n.get("Country", "")), "inspection_end": parse_date(n.get("Inspection End Date")),
            "issue": parse_date(n.get("Issue Date")),
        })
    return out


def cep_atcs(ceps: list[dict], by_substance: dict[str, set[str]]) -> None:
    """Add the ATC5 set to each certificate (cached per substance name)."""
    cache: dict[str, set[str]] = {}
    for c in ceps:
        if c["substance"] not in cache:
            cache[c["substance"]] = substance_atcs(c["substance"], by_substance)
        c["atcs"] = cache[c["substance"]]


def valid_holders(ceps: list[dict]) -> dict[str, int]:
    """Number of distinct holders with a valid CEP per ATC5."""
    holders: dict[str, set[str]] = {}
    for c in ceps:
        if c["status"] == "Valid":
            for atc in c["atcs"]:
                holders.setdefault(atc, set()).add(c["holder_key"] or c["holder"])
    return {atc: len(h) for atc, h in holders.items()}


def cep_events(ceps: list[dict]) -> list[dict]:
    """Suspensions and withdrawals by EDQM for GMP non-compliance, one per certificate and ATC5."""
    return [{"atc5": atc, "date": date.fromisoformat(c["end"]), "holder": c["holder"], "substance": c["substance"]}
            for c in ceps if c["status"] in GMP_STATUS and c["end"] for atc in c["atcs"]]


def ncr_events(ncrs: list[dict], ceps: list[dict]) -> list[dict]:
    """NCRs linked to the substances of matching CEP holders (location ID, else company word and country)."""
    by_id: dict[str, list[dict]] = {}
    by_first: dict[tuple, list[tuple[list[str], dict]]] = {}
    for c in ceps:
        for i in c["ids"]:
            by_id.setdefault(i, []).append(c)
        words = name_words(c["holder"])
        if words and c["country"]:
            by_first.setdefault((words[0], c["country"]), []).append((words, c))
    out = []
    for n in ncrs:
        matched = by_id.get(n["loc"]) if n["loc"] else None
        how = "standort_id"
        if not matched:
            # Chinese and Indian names often start with a province or city: the first two words must agree
            # (the CEP holder field continues with city and country, so the site's words are a prefix)
            words = name_words(n["site"])[:2]
            if words and (len(words) == 2 or len(words[0]) >= 4):
                matched = [c for w, c in by_first.get((words[0], n["country"]), []) if w[:len(words)] == words]
            how = "name_land"
        if not matched or not n["issue"]:
            continue
        for atc in sorted({a for c in matched for a in c["atcs"]}):
            out.append({"atc5": atc, "date": date.fromisoformat(n["issue"]), "site": n["site"], "report": n["report"], "match": how})
    return out


def load(archive, asp_rows: list[dict]) -> dict:
    """Latest CEP file and NCR list from the archive, linked to ATC5 (empty parts when a source is missing)."""
    from .foreign import atc_lookup
    from .rueckblick import _latest

    by_substance, _ = atc_lookup(asp_rows)
    cep_body, ncr_body = _latest(archive, "edqm"), _latest(archive, "eudragmdp")
    ceps = parse_cep(cep_body) if cep_body else []
    cep_atcs(ceps, by_substance)
    ncrs = parse_ncr(ncr_body) if ncr_body else []
    return {"valid_holders": valid_holders(ceps), "cep_events": cep_events(ceps), "ncr_events": ncr_events(ncrs, ceps),
            "n_ceps": len(ceps), "n_ncrs": len(ncrs)}
