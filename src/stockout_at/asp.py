"""Parse the ASP list (all Austrian human medicinal packages, TermGit/ELGA value set) as denominator.

Two formats: the TermGit SVS export (XML, archived history until 2026-06) and the ELGA FHIR terminology server's
CodeSystem (JSON, daily from 2026-10); both carry the same property names."""
from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
from typing import BinaryIO

from .substances import base_substance


def _code(value: str | None) -> str:
    return (value or "").rsplit(":", 1)[-1]


def concept_row(a: dict) -> dict:
    """One package; `equiv_key` = form + normalised substances with strength (equivalence hint)."""
    ingredients = []
    for key in sorted(k for k in a if k.startswith("ELGA_ActiveIngredient_") and k.endswith("_text")):
        nn = key.split("_")[2]
        ingredients.append(
            (
                a[key].strip(),
                (a.get(f"ELGA_Ingredient_low_strength_{nn}") or "").strip(),
                (a.get(f"ELGA_Ingredient_low_strength_unit_{nn}") or "").strip(),
            )
        )
    forms = [a[k] for k in sorted(a) if k.startswith("ELGA_MedikationDarreichungsform_") and k.endswith("_text")]
    form = " / ".join(f.strip() for f in forms)
    strength = sorted({(base_substance(n), s, u) for n, s, u in ingredients})
    substances = sorted({b for b, _, _ in strength})
    equiv = form + " | " + " + ".join(f"{b} {s} {u}".strip() for b, s, u in strength) if ingredients else None
    return {
        "pzn": a.get("code", ""),
        "name": a.get("displayName") or a.get("deutsch") or "",
        "approval_name": a.get("Bezeichnung_Arzneispezialitaet_Zulassung") or "",
        "zulassungsnummer": _code(a.get("ZulassungsNummer")),
        "zulassungsstatus": a.get("ELGA_Zulassungsstatus") or "",
        "valid": 1 if a.get("ELGA_Gültigkeit") == "true" else 0,
        "lieferbar": 1 if a.get("ELGA_MedikationPackungsstatusLieferbar") == "true" else 0,
        "inhaber": a.get("ELGA_Inhaber") or "",
        "atc": _code(a.get("ELGA_whoATC_01_code")),
        "ingredients": " + ".join(f"{n} {s} {u}".strip() for n, s, u in ingredients),
        "substances": " + ".join(substances),
        "form": form,
        "size": a.get("GroesseGewicht") or "",
        "equiv_key": equiv,
    }


def fhir_date(body: bytes) -> str | None:
    """Effective date of a FHIR CodeSystem file (top-level "date", before the concepts)."""
    m = re.search(rb'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})', body[:5000])
    return m.group(1).decode() if m else None


def parse_fhir(body: bytes) -> tuple[str | None, list[dict]]:
    cs = json.loads(body)
    rows = []
    for c in cs.get("concept", []):
        a = {"code": c.get("code"), "displayName": c.get("display")}
        for p in c.get("property", []):
            a[p["code"]] = next((v for k, v in p.items() if k.startswith("value")), None)
        rows.append(concept_row(a))
    return cs.get("version"), rows


def parse(fh: BinaryIO) -> tuple[str | None, list[dict]]:
    """Return (version, rows) of one ASP-list file object (SVS XML streamed, FHIR JSON at once)."""
    data = fh.read()
    if data.lstrip()[:1] == b"{":
        return parse_fhir(data)
    version, rows = None, []
    for event, elem in ET.iterparse(io.BytesIO(data), events=("start", "end")):
        if event == "start":
            if elem.tag == "valueSet" and version is None:
                version = elem.get("version")
            continue
        if elem.tag == "concept":
            rows.append(concept_row(elem.attrib))
            elem.clear()
    return version, rows
