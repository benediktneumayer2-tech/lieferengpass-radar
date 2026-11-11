"""Parse BASG shortage files (VEASP XML) into snapshot rows with all official fields verbatim.

Parsing is tolerant: missing elements become "" (attributes: None when absent), unknown
child elements are kept in `extra` (JSON), and a truncated file (some Wayback captures stop
at exactly 1 MiB) yields the complete `Packung` elements before the cut with `complete=False`.
"""
from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

ATTRS = (
    "PZN",
    "Zulassungsnummer",
    "Datum_Meldung",
    "Datum_letzte_Aenderung",
    "Beginn_Vertriebseinschraenkung",
    "Datum_voraussichtliche_Wiederbelieferung",
)
CHILDREN = (
    "Bezeichnung_Arzneispezialitaet",
    "Status",
    "Staerke",
    "Unit",
    "ATCCodes",
    "Darreichungsform",
    "Parallelexportverbot",
    "Packungsgroesse",
    "Packungseinheit",
    "Packungscontainer",
    "Packungsbeschreibung",
    "Melder",
    "Zulassungsinhaber",
    "Zulassungsinhaber_Tel",
    "Grund",
    "Wirkstoffe",
    "Mitteilung_Fachkreise",
    "Rechtsgrundlage_Meldung",
    "Hinweis_BASG",
)
FIELDS = ATTRS + CHILDREN


@dataclass
class Snapshot:
    produced_on: str | None
    complete: bool
    packages: list[dict] = field(default_factory=list)
    error: str | None = None


def package_key(row: dict) -> str:
    """Stable package identity: the PZN; if empty (old files), approval number + pack size/unit/description."""
    pzn = (row.get("PZN") or "").strip()
    if pzn:
        return pzn
    parts = (row.get(k) or "" for k in ("Zulassungsnummer", "Packungsgroesse", "Packungseinheit", "Packungsbeschreibung"))
    return "Z:" + "|".join(p.strip() for p in parts)


def _row(elem: ET.Element) -> dict:
    row: dict = {k: elem.get(k) for k in ATTRS}
    for k in CHILDREN:
        row[k] = None  # None = element absent (e.g. Unit/ATCCodes in old files), "" = present but empty
    extra = {}
    for child in elem:
        text = child.text or ""
        if child.tag in CHILDREN:
            row[child.tag] = text
        else:
            extra[child.tag] = text
    unknown_attrs = {k: v for k, v in elem.attrib.items() if k not in ATTRS}
    if unknown_attrs:
        extra["@"] = unknown_attrs
    row["extra"] = json.dumps(extra, ensure_ascii=False, sort_keys=True) if extra else None
    return row


def parse(body: bytes) -> Snapshot:
    """Parse one BASG file; never raises on malformed or truncated XML."""
    snap = Snapshot(produced_on=None, complete=False)
    try:
        for event, elem in ET.iterparse(io.BytesIO(body), events=("start", "end")):
            if event == "start":
                if elem.tag == "Meta" and snap.produced_on is None:
                    snap.produced_on = elem.get("producedOn")
                continue
            if elem.tag == "Packung":
                snap.packages.append(_row(elem))
                elem.clear()
        snap.complete = True
    except ET.ParseError as exc:
        snap.error = str(exc)
    return snap
