"""One-off import of the sparse history: legacy BASG files, TermGit ASP list versions, Internet Archive captures.

A local data package (folder with `manifests/basg_snapshots.csv`, `manifests/product_master_versions.csv` and the
files they list) is only read; nothing there is changed. Only public data (BASG XML, ASP list) is taken from it.
Its folder comes from `--package` or STOCKOUT_LEGACY_PACKAGE; there is no default.
"""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .archive import SOURCES, Archive, _check, basg_produced_on, iso, user_agent, utcnow
from . import foreign

PACKAGE_ENV = "STOCKOUT_LEGACY_PACKAGE"
DEFAULT_PACKAGE = Path(os.environ[PACKAGE_ENV].strip()) if os.environ.get(PACKAGE_ENV, "").strip() else None
BASG_URLS = (
    "https://webservices.basg.gv.at/medicineshortage/export/v1/download",
    "https://www.basg.gv.at/fileadmin/uploadVERE/VertriebseinschraenkungenASP.xml",
)
# Internet Archive URLs per source (current endpoint plus known predecessors).
WAYBACK_URLS = {"basg": BASG_URLS}


def import_basg_package(archive: Archive, package: Path) -> list[dict]:
    out = []
    with open(package / "manifests" / "basg_snapshots.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            body = (package / row["local_path"]).read_bytes()
            produced_on = basg_produced_on(body) or row["produced_on"] or None
            warnings = []
            if hashlib.sha256(body).hexdigest() != row["sha256"]:
                warnings.append("SHA-256 weicht vom Paket-Manifest ab")
            wayback = row["source_kind"].startswith("wayback")
            out.append(
                archive.store(
                    "basg",
                    body,
                    ext="xml",
                    stamp=produced_on.replace(":", "-"),
                    meta={
                        "origin": "wayback" if wayback else "legacy_local",
                        "url": row["source_url"],
                        "captured_at": row["archive_capture_at"] or row["available_at"],
                        "evidence_urls": json.loads(row["evidence_urls_json"] or "[]"),
                        "produced_on": produced_on,
                        "imported_from": str(package / row["local_path"]),
                        "warnings": warnings,
                    },
                )
            )
    return out


def import_asp_package(archive: Archive, package: Path) -> list[dict]:
    out = []
    with open(package / "manifests" / "product_master_versions.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            body = gzip.decompress((package / row["raw_local_path"]).read_bytes())
            warnings = [] if hashlib.sha256(body).hexdigest() == row["sha256"] else ["SHA-256 weicht vom Paket-Manifest ab"]
            stamp = (row["source_effective_date"] or row["git_commit_at"])[:10]
            out.append(
                archive.store(
                    "asp",
                    body,
                    ext="xml",
                    stamp=stamp,
                    meta={
                        "origin": "termgit_history",
                        "url": row["source_url"],
                        "source_git_commit": row["source_git_commit"],
                        "captured_at": row["git_commit_at"],
                        "source_version": row["source_version"],
                        "imported_from": str(package / row["raw_local_path"]),
                        "warnings": warnings,
                    },
                )
            )
    return out


def wayback_digest(body: bytes) -> str:
    """Internet Archive CDX digest: base32 SHA-1 of the original bytes."""
    return base64.b32encode(hashlib.sha1(body).digest()).decode()


def _get(url: str, timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def import_wayback(
    archive: Archive,
    source: str = "basg",
    *,
    get: Callable[[str], bytes] = _get,
    sleep: Callable[[float], None] = time.sleep,
    pause: float = 3.0,
) -> list[dict]:
    """Fetch every distinct Internet Archive capture of a source's export not yet archived.

    BASG captures are stamped with `producedOn`; other sources with the capture time and must
    yield at least one item with the source's parser.
    """
    known = {wayback_digest(archive.read(path)) for path in archive.known_hashes(source).values()}
    urls = WAYBACK_URLS.get(source) or (SOURCES[source].url,)
    ext = SOURCES[source].ext
    out = []

    def fail(url: str, error: str) -> None:
        entry = {"recorded_at": iso(utcnow()), "source": source, "origin": "wayback", "url": url, "ok": False, "error": error}
        archive.append(entry)
        out.append(entry)

    for url in urls:
        query = urllib.parse.urlencode(
            {"url": url, "output": "json", "filter": "statuscode:200", "collapse": "digest", "fl": "timestamp,original,digest"}
        )
        rows = json.loads(_retry(lambda: get(f"https://web.archive.org/cdx/search/cdx?{query}"), sleep) or b"[]")
        for timestamp, original, digest in rows[1:]:
            if digest in known:
                continue
            sleep(pause)
            capture = f"https://web.archive.org/web/{timestamp}id_/{original}"
            try:
                body = _retry(lambda: get(capture), sleep)
            except Exception as exc:
                fail(capture, f"{type(exc).__name__}: {exc}")
                continue
            captured = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}T{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}Z"
            if source == "basg":
                produced_on = basg_produced_on(body)
                if not produced_on:
                    fail(capture, "kein BASG-XML mit producedOn")
                    continue
                stamp = produced_on.replace(":", "-")
            else:
                produced_on = None
                parse = foreign.PARSERS.get(source)
                try:
                    ok = bool(parse(body)) if parse else not _check(SOURCES[source], body, None)
                except Exception as exc:  # noqa: BLE001 - unreadable capture is recorded, not fatal
                    ok, error = False, f"{type(exc).__name__}: {exc}"
                else:
                    error = "keine Meldungen lesbar" if parse else "Format passt nicht"
                if not ok:
                    fail(capture, error)
                    continue
                stamp = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}T{timestamp[8:14]}Z"
            known.add(wayback_digest(body))
            out.append(
                archive.store(
                    source,
                    body,
                    ext=ext,
                    stamp=stamp,
                    meta={"origin": "wayback", "url": original, "captured_at": captured,
                          "evidence_urls": [capture], "produced_on": produced_on, "warnings": []},
                )
            )
    return out


def import_pl_mz(archive: Archive, *, get: Callable[[str], bytes] = _get, sleep: Callable[[float], None] = time.sleep,
                 first_year: int = 2015, pause: float = 2.0) -> list[dict]:
    """All issues of the Polish at-risk list since 2015 not yet archived; capture day = publication day."""
    from .archive import PL_JOURNAL, pl_acts

    have = {e.get("act") for e in archive.entries() if e.get("source") == "pl_mz" and e.get("ok")}
    out = []
    for year in range(first_year, utcnow().year + 1):
        for act in pl_acts(year):
            if act["eli"] in have:
                continue
            sleep(pause)
            url = PL_JOURNAL + act["eli"] + "/akt.pdf"
            try:
                body = _retry(lambda: get(url), sleep)
            except Exception as exc:
                entry = {"recorded_at": iso(utcnow()), "source": "pl_mz", "origin": "backfill", "url": url, "ok": False,
                         "error": f"{type(exc).__name__}: {exc}", "act": act["eli"]}
                archive.append(entry)
                out.append(entry)
                continue
            day = act["promulgation"][:10]
            out.append(archive.store("pl_mz", body, ext="pdf", stamp=day, meta={
                "origin": "backfill", "url": url, "captured_at": f"{day}T00:00:00Z", "act": act["eli"], "published": day,
                "warnings": _check(SOURCES["pl_mz"], body, None)}))
    return out


def _retry(fn: Callable[[], bytes], sleep: Callable[[float], None], attempts: int = 3) -> bytes:
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            sleep(20 * (i + 1))
    raise AssertionError("unreachable")
