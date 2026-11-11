"""National product registers that fill gaps in foreign shortage reports (ATC, marketing authorisation holder).

- `sukl_dlp`: SÚKL CZ medicinal product database (monthly ZIP, open data): SÚKL code -> holder, ATC. The Czech
  shortage log names no holder; the register gives today's holder, so older reports may show a later one.
- `fimea_reg`: Fimea FI basic register, package file pakkaus1.txt: VNR -> product, strength, form, ATC, holder.
  Fimea's shortage file has only the VNR. The public code does not fetch either file; already archived files are read.
- `cima_reg`: AEMPS ES, CIMA REST `medicamento?cn=` per national code of a supply report (ATC level 5, holder).
  Looked up once per code at one request per second; each run stores its raw answers as one JSONL file.

Registers only fill empty fields; what a shortage list states itself is kept.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
import zipfile
from typing import Callable

from .archive import Archive, user_agent

CIMA_MEDICINE = "https://cima.aemps.es/cima/rest/medicamento?cn={cn}"
CIMA_PAUSE = 1.0
CIMA_MAX = 1500  # per run; the first run covers all codes of the archive


def parse_sukl_dlp(body: bytes) -> dict[str, dict]:
    """SÚKL code -> {atc5, holder} from dlp_lecivepripravky.csv and dlp_organizace.csv (cp1250, ';')."""
    z = zipfile.ZipFile(io.BytesIO(body))

    def table(name: str) -> list[dict]:
        member = next(n for n in z.namelist() if n.lower().endswith(name))
        return list(csv.DictReader(io.StringIO(z.read(member).decode("cp1250")), delimiter=";"))

    orgs = {(r["ZKR_ORG"], r["ZEM"]): r["NAZEV"].split(",")[0].strip() for r in table("dlp_organizace.csv")}
    out = {}
    for r in table("dlp_lecivepripravky.csv"):
        atc = (r.get("ATC_WHO") or "").strip()
        out[r["KOD_SUKL"]] = {"atc5": atc if len(atc) == 7 else None,
                              "holder": orgs.get((r.get("DRZ") or "", r.get("ZEMDRZ") or "")) or None}
    return out


def parse_fimea_reg(body: bytes) -> dict[str, dict]:
    """VNR (six digits, as in the shortage file) -> product, strength, form, ATC, holder (cp1252, ';')."""
    out = {}
    for r in csv.DictReader(io.StringIO(body.decode("cp1252"), newline=""), delimiter=";"):
        vnr = (r.get("VNRNRO") or "").strip()
        if not vnr.isdigit():
            continue
        atc = (r.get("ATCKOODI") or "").strip()
        out[vnr.zfill(6)] = {"atc5": atc if len(atc) == 7 else None, "holder": (r.get("HALTIJA") or "").strip() or None,
                             "product": " ".join(x for x in ((r.get("LAAKENIMI") or "").strip(), (r.get("VAHVUUS") or "").strip()) if x) or None,
                             "strength": (r.get("VAHVUUS") or "").strip() or None,
                             "form": (r.get("LAAKEMUOTONIMI") or "").strip() or None}
    return out


def parse_cima_reg(body: bytes) -> dict[str, dict]:
    """National code -> {atc5, holder, substances} from stored CIMA answers (one JSON object per line)."""
    out = {}
    for line in body.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if "error" in rec:
            continue  # not known: looked up again in the next run
        med = rec.get("medicamento") or {}
        atc5 = next((a["codigo"] for a in med.get("atcs") or [] if a.get("nivel") == 5), None)
        out[rec["cn"]] = {"atc5": atc5, "holder": med.get("labtitular"), "substances": med.get("pactivos")}
    return out


PARSERS = {"sukl_dlp": parse_sukl_dlp, "cima_reg": parse_cima_reg, "fimea_reg": parse_fimea_reg}
FOR_SOURCE = {"sukl_cz": "sukl_dlp", "cima": "cima_reg", "fimea": "fimea_reg"}
CUMULATIVE = frozenset({"cima_reg"})  # each file holds only the codes looked up in that run


def load(archive: Archive, unique_files) -> dict[str, dict[str, dict]]:
    """Register maps by foreign source: the latest file, or all files for registers built up over runs."""
    out: dict[str, dict[str, dict]] = {}
    for source, register in FOR_SOURCE.items():
        files = unique_files(archive, register)
        if register not in CUMULATIVE:
            files = files[-1:]
        merged: dict[str, dict] = {}
        for e in files:
            try:
                merged.update(PARSERS[register](archive.read(e["path"])))
            except Exception:  # noqa: BLE001 - an unreadable register file must not break the build
                continue
        out[source] = merged
    return out


def fill(items: list[dict], registers: dict[str, dict[str, dict]]) -> int:
    """Fill missing ATC, holder, substances, product, strength and form of foreign items; returns filled items."""
    n = 0
    for it in items:
        reg = registers.get(it["source"])
        if not reg:
            continue
        for code in (it.get("native_ids") or "").split():
            hit = reg.get(code)
            if not hit:
                continue
            changed = False
            for field in ("atc5", "holder", "substances", "product", "strength", "form"):
                if not it.get(field) and hit.get(field):
                    it[field] = hit[field]
                    changed = True
                    if field == "atc5":
                        it["atc_method"] = "register"
            n += changed
            break
    return n


def _get(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": user_agent()}), timeout=timeout) as r:
        return r.read()


def sync_cima(archive: Archive, unique_files, *, get: Callable[[str], bytes] = _get,
              sleep: Callable[[float], None] = time.sleep, limit: int = CIMA_MAX) -> dict | None:
    """Look up national codes of the archived CIMA reports not yet in the register; store the answers."""
    from .foreign import parse_cima

    files = unique_files(archive, "cima")
    if not files:
        return None
    known: set[str] = set()
    for e in unique_files(archive, "cima_reg"):
        known |= set(parse_cima_reg(archive.read(e["path"])))
    codes: set[str] = set()
    for e in files:
        try:
            codes |= {cn for it in parse_cima(archive.read(e["path"])) for cn in it["native_ids"]}
        except Exception:  # noqa: BLE001
            continue
    todo = sorted(codes - known)[:limit]
    if not todo:
        return None
    lines = []
    for cn in todo:
        sleep(CIMA_PAUSE)
        try:
            body = get(CIMA_MEDICINE.format(cn=cn))
            med = json.loads(body) if body.strip() else None
        except Exception as exc:  # noqa: BLE001 - recorded in the file, looked up again next time
            lines.append(json.dumps({"cn": cn, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
            continue
        lines.append(json.dumps({"cn": cn, "medicamento": med}, ensure_ascii=False))
    body = "\n".join(lines).encode()
    from .archive import iso, utcnow
    stamp = utcnow().strftime("%Y-%m-%dT%H%M%SZ")
    return archive.store("cima_reg", body, ext="jsonl", stamp=stamp, meta={
        "origin": "live", "url": CIMA_MEDICINE, "fetched_at": iso(utcnow()), "codes": len(todo),
        "warnings": [f"{sum('error' in l for l in lines)} Fehler"] if any('"error"' in l for l in lines) else []})
