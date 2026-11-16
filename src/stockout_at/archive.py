"""Daily raw archive: fetch public sources and store every new version byte-exact.

Raw files are the source of truth. Each response is gzip-compressed (lossless)
and recorded in an append-only JSONL manifest together with the SHA-256 of the
original bytes. A version whose hash is already archived is only noted in the
manifest. Failed requests are recorded too, so gaps stay visible.

A live file whose Last-Modified is older than that of an earlier live fetch of the same source is stale (a cache
served an old version, e.g. ogyei 2026-10-22, sukl_cz 2026-10-23): the build leaves it out (`stale_paths`), and a
new one counts as a failed fetch like an answer that fails the format check.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable

from . import asp

PROJECT_URL = "https://github.com/benediktneumayer2-tech/lieferengpass-radar"
USER_AGENT = f"LieferengpassRadar/0.1 (+{PROJECT_URL})"
CONTACT_ENV = "STOCKOUT_CONTACT"  # optional contact (e.g. an e-mail address) added to the User-Agent; unset: none
MANIFEST = "manifest.jsonl"
RETRY_DELAYS = (15, 60)  # seconds before the 2nd and 3rd attempt


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    ext: str
    paged: bool = False  # url contains {page}; pages 1..n until an empty result, stored as JSONL (one raw page per line)
    min_hours: float = 0  # scheduled runs skip the source while its last successful fetch is younger
    expect: bytes = b""  # marker that must appear near the start of a valid file (format check)


SOURCES = {
    "basg": Source("basg", "https://webservices.basg.gv.at/medicineshortage/export/v1/download", "xml"),
    "bfarm": Source("bfarm", "https://anwendungen.pharmnet-bund.de/lieferengpassmeldungen/public/csv", "csv"),
    "ema": Source(
        "ema", "https://www.ema.europa.eu/en/documents/report/medicines-output-shortages-report_en.xlsx", "xlsx"
    ),
    # Further EU countries (official downloads; see documentation/DATENQUELLEN.md)
    "aifa": Source("aifa", "https://www.aifa.gov.it/documents/20142/847339/elenco_medicinali_carenti.csv", "csv"),
    "sukl_cz": Source("sukl_cz", "https://opendata.sukl.gov.cz/soubory/MR/mr.zip", "zip"),
    "sukl_sk": Source("sukl_sk", "https://portal.sukl.sk/PreruseniePublic/?act=PrerusenieOznList&export=csv", "csv"),
    "ogyei": Source("ogyei", "https://ogyei.gov.hu/generalt_listak/shortage_lista.csv", "csv"),
    "jazmp": Source(
        "jazmp", "https://www.jazmp.si/fileadmin/datoteke/seznami/SFE/Prisotnost/Seznam_24_HUM_prenehanja_motnje.xlsx", "xlsx"
    ),
    "famhp": Source("famhp", "https://pharmastatut.be/api/notifications/export/public?language=en&usage=human", "xlsx"),
    "cima": Source("cima", "https://cima.aemps.es/cima/rest/psuministro?pagina={page}", "jsonl", paged=True),
    # USA: openFDA drug shortages bulk file (CC0), updated with the openFDA export
    "fda": Source("fda", "https://download.open.fda.gov/drug/shortages/drug-shortages-0001-of-0001.json.zip", "zip"),
    # France: ANSM availability list, export of the whole list (old BIFF .xls); robots.txt allows all.
    "ansm": Source("ansm", "https://ansm.sante.fr/disponibilites-des-produits-de-sante/medicaments/export", "xls",
                   min_hours=20),
    # EU GMP non-compliance reports (EudraGMDP): search over the whole period, then the list export (.xls).
    # Withdrawn reports disappear from the list, so history exists only through this archive.
    "eudragmdp": Source("eudragmdp", "https://eudragmdp.ema.europa.eu/inspections/gmpc/searchGMPNonCompliance.do",
                        "xls", min_hours=20),
    # Poland: Minister of Health's list of products at risk of unavailability (art. 37av Prawo farmaceutyczne; export
    # needs notification), a full list every 6-8 weeks in the official journal; the newest issue is found through the
    # journal's ELI listing of the year. Older issues since 2015 come in through `import-legacy --backfill pl_mz`.
    "pl_mz": Source("pl_mz", "https://dziennikmz.mz.gov.pl/api/eli/acts/DUM_MZ/{year}", "pdf", min_hours=20),
    # Product registers that fill gaps of foreign reports (module `registers`): SÚKL CZ product database (monthly
    # ZIP; the catalogue page names the newest file; robots.txt asks for 10 s between requests).
    "sukl_dlp": Source("sukl_dlp", "https://opendata.sukl.gov.cz/katalog-otevrenych-dat/databaze-lecivych-pripravku-dlp", "zip",
                       min_hours=20),
    # ASP list (all human packages incl. "lieferbar") from the ELGA FHIR terminology server; the TermGit history
    # until 2026-06 came in through import-legacy. A new version appears about monthly; files are named by its date.
    "asp": Source("asp", "https://tergi.elga.gv.at/fhir-server/api/v4/CodeSystem/asp-liste?_format=json", "json",
                  min_hours=20, expect=b'"asp-liste"'),
    # Infection waves (demand signal): ECDC ERVISS ILI rates (EUPL-1.2, all countries, AT from 2022-W40) and
    # Austrian SARI hospital admissions by virus (weekly since 2023-W19; the patient file adds age groups).
    "erviss_ili": Source("erviss_ili", "https://raw.githubusercontent.com/EU-ECDC/Respiratory_viruses_weekly_data/main/data/ILIARIRates.csv",
                         "csv", min_hours=20, expect=b"countryname"),
    "sari_region": Source("sari_region", "https://opendata-files.sozialversicherung.at/sari/SARI_Region_Krankenanstalt_v202602.csv",
                          "csv", min_hours=20, expect=b"JAHR;KW"),
    "sari_patient": Source("sari_patient", "https://opendata-files.sozialversicherung.at/sari/SARI_Wohnregion_Patient_v202602.csv",
                           "csv", min_hours=20, expect=b"JAHR;KW"),
}
EUDRAGMDP_FROM = "2000-01-01"
PL_JOURNAL = "https://dziennikmz.mz.gov.pl/"
PL_TITLE = "zagrożonych brakiem dostępności"
MAX_PAGES = 50


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def basg_produced_on(body: bytes) -> str | None:
    """Return the `producedOn` attribute of the BASG `Meta` element, if present."""
    try:
        for _event, elem in ET.iterparse(io.BytesIO(body), events=("start",)):
            if elem.tag == "Meta":
                return elem.get("producedOn")
            if elem.tag == "Packung":
                return None
    except ET.ParseError:
        return None
    return None


def _stamp(produced_on: str | None, fetched: datetime) -> str:
    if produced_on:
        return produced_on.replace(":", "-")
    return fetched.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


class Archive:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / MANIFEST
        self._hashes: dict[str, dict[str, str]] | None = None

    def entries(self) -> list[dict]:
        if not self.manifest.exists():
            return []
        out = []
        with self.manifest.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # a torn last line must not block the archive
        return out

    def known_hashes(self, source: str) -> dict[str, str]:
        if self._hashes is None:
            self._hashes = {}
            for e in self.entries():
                if e.get("sha256") and e.get("path") and not e.get("duplicate"):
                    self._hashes.setdefault(e["source"], {})[e["sha256"]] = e["path"]
        return self._hashes.setdefault(source, {})

    def append(self, entry: dict) -> None:
        with self.manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def store(self, source: str, body: bytes, *, ext: str, stamp: str, meta: dict) -> dict:
        """Store `body` unless an identical version exists; append and return the manifest entry."""
        sha = hashlib.sha256(body).hexdigest()
        entry = {"recorded_at": iso(utcnow()), "source": source, "ok": True, "sha256": sha, "bytes": len(body), **meta}
        known = self.known_hashes(source)
        if sha in known:
            entry.update(duplicate=True, path=known[sha])
        else:
            rel = f"{source}/{stamp[:4]}/{stamp}_{sha[:12]}.{ext}.gz"
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            with open(tmp, "wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
                    gz.write(body)
                raw.flush()
                os.fsync(raw.fileno())
            if hashlib.sha256(gzip.decompress(tmp.read_bytes())).hexdigest() != sha:
                tmp.unlink()
                raise OSError(f"Rücklese-Prüfung fehlgeschlagen für {rel}")
            os.replace(tmp, path)
            known[sha] = rel
            entry.update(duplicate=False, path=rel)
        self.append(entry)
        return entry

    def read(self, rel: str) -> bytes:
        return gzip.decompress((self.root / rel).read_bytes())


Opener = Callable[[urllib.request.Request, float], object]


def _default_opener(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout)


def _check(source: Source, body: bytes, produced_on: str | None) -> list[str]:
    warnings = []
    if not body:
        warnings.append("leere Antwort")
    elif source.name == "basg" and not produced_on:
        warnings.append("BASG-Meta/producedOn fehlt oder XML nicht lesbar")
    elif source.name == "asp" and not produced_on:
        warnings.append("ASP-Liste ohne Datum")
    elif source.ext in ("xlsx", "zip") and not body.startswith(b"PK"):
        warnings.append(f"keine {source.ext}-Datei")
    elif source.ext == "jsonl" and not body.lstrip().startswith(b"{"):
        warnings.append("keine JSON-Seiten")
    elif source.ext == "pdf" and not body.startswith(b"%PDF"):
        warnings.append("keine PDF-Datei")
    elif source.ext == "xls" and not body.startswith(b"\xd0\xcf\x11\xe0"):
        warnings.append("keine xls-Datei")
    elif source.expect:
        if source.expect not in body[:3000]:
            warnings.append(f"Kennung {source.expect.decode()} fehlt")
    elif source.ext == "csv" and b";" not in body[:2000]:
        warnings.append("keine CSV mit Semikolon")
    return warnings


def user_agent() -> str:
    """User-Agent of every request; names the contact only when STOCKOUT_CONTACT is set."""
    contact = " ".join(os.environ.get(CONTACT_ENV, "").split())  # one line, no control characters
    return f"LieferengpassRadar/0.1 (+{PROJECT_URL}; Kontakt: {contact})" if contact else USER_AGENT


def _last_modified(value: str | None) -> datetime | None:
    try:
        lm = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return lm if lm.tzinfo else lm.replace(tzinfo=timezone.utc)


def _dated_live(entries: list[dict]) -> list[tuple[dict, datetime]]:
    """Stored live files with a Last-Modified, in fetch order (repeats of known bytes are left out)."""
    out = [(e, _last_modified(e.get("last_modified"))) for e in entries if e.get("origin") == "live" and e.get("ok")
           and e.get("path") and not e.get("duplicate") and e.get("last_modified")]
    return sorted(((e, lm) for e, lm in out if lm), key=lambda x: x[0].get("fetched_at") or "")


def stale_paths(entries: list[dict]) -> set[str]:
    """Live files whose Last-Modified is older than that of an earlier live fetch of the same source (the rule of
    the model search, November 2026). Left out of the database; the archive keeps them."""
    out, newest = set(), {}
    for e, lm in _dated_live(entries):
        if e["source"] in newest and lm < newest[e["source"]]:
            out.add(e["path"])
        newest[e["source"]] = max(lm, newest.get(e["source"], lm))
    return out


def _stale(archive: Archive, source: str, body: bytes, last_modified: str | None) -> list[str]:
    """Warning for a new answer older than an earlier live fetch; bytes of a file the build uses are harmless."""
    lm = _last_modified(last_modified)
    if lm is None:
        return []
    entries = archive.entries()
    newest = max((x for e, x in _dated_live(entries) if e["source"] == source), default=None)
    if newest is None or lm >= newest:
        return []
    sha, stale = hashlib.sha256(body).hexdigest(), stale_paths(entries)
    if any(e.get("sha256") == sha and e["path"] not in stale for e in entries if e.get("source") == source
           and e.get("ok") and e.get("path") and not e.get("duplicate")):
        return []
    return [f"veraltete Fassung: Last-Modified {last_modified} älter als zuvor {iso(newest)}"]


def _get(url: str, opener: Opener, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with opener(req, timeout) as resp:
        status = getattr(resp, "status", 200)
        body = resp.read()
        if status != 200 or not body:
            raise OSError(f"HTTP {status}, {len(body)} Bytes")
        return body, resp.headers, status


def _get_eudragmdp(source: Source, opener: Opener, timeout: float):
    """GMP non-compliance list: the search runs in a server session (cookie); the export returns its full result."""
    headers = {"User-Agent": user_agent()}

    def call(url: str, data: bytes | None = None):
        req = urllib.request.Request(url, data=data, headers=headers)
        with opener(req, timeout) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read()
            cookies = [c.split(";", 1)[0] for c in (resp.headers.get_all("Set-Cookie") or [])]
            if cookies:
                headers["Cookie"] = "; ".join(cookies)
            if status != 200 or not body:
                raise OSError(f"HTTP {status}, {len(body)} Bytes")
            return body, resp.headers, status

    call(source.url)
    form = urllib.parse.urlencode({"formid": "frmGMPCSearch", "fromDate": EUDRAGMDP_FROM,
                                   "toDate": utcnow().date().isoformat(), "btnSearchGMPNC": ""}).encode()
    page = call(source.url, form)[0]
    if not re.search(rb"\d+ to \d+ of \d+", page):
        raise OSError("EudraGMDP: Suche ohne Trefferzahl")
    return call(source.url + "?ctrl=searchGMPNCResultControlList&action=ExportList")


def pl_acts(year: int, opener: Opener = _default_opener, timeout: float = 90) -> list[dict]:
    """Issues of the Polish at-risk list in one year of the health ministry's journal, oldest first."""
    body, _, _ = _get(SOURCES["pl_mz"].url.format(year=year), opener, timeout)
    items = [it for it in json.loads(body)["items"] if PL_TITLE in it["title"]]
    return sorted(items, key=lambda it: it["pos"])


def _get_pl_mz(source: Source, opener: Opener, timeout: float):
    """PDF of the newest issue (this year, else last year); headers carry the act and its publication day."""
    year = utcnow().year
    acts = pl_acts(year, opener, timeout) or pl_acts(year - 1, opener, timeout)
    if not acts:
        raise OSError("keine Ausgabe der Liste gefunden")
    act = acts[-1]
    body, headers, status = _get(PL_JOURNAL + act["eli"] + "/akt.pdf", opener, timeout)
    return body, {"Content-Type": headers.get("Content-Type"), "Last-Modified": headers.get("Last-Modified"),
                  "ETag": headers.get("ETag"), "X-Act": act["eli"], "X-Published": act["promulgation"][:10]}, status


def _get_sukl_dlp(source: Source, opener: Opener, timeout: float):
    """Newest DLP ZIP linked from the SÚKL open-data catalogue page (by the date in its name)."""
    page, _, _ = _get(source.url, opener, timeout)
    urls = re.findall(rb"https://opendata\.sukl\.(?:gov\.)?cz/soubory/SOD\d+/DLP\d{8}\.zip", page)
    if not urls:
        raise OSError("SÚKL: keine DLP-Datei verlinkt")
    time.sleep(10)
    return _get(max(urls, key=lambda u: u[-12:-4]).decode(), opener, timeout)


def _get_pages(source: Source, opener: Opener, timeout: float):
    """All pages of a paged JSON API, joined as JSONL; stops at the first page without results."""
    pages, headers = [], None
    for page in range(1, MAX_PAGES + 1):
        body, h, _ = _get(source.url.format(page=page), opener, timeout)
        headers = headers or h
        if not json.loads(body).get("resultados"):
            break
        if b"\n" in body:
            raise OSError(f"Seite {page} enthält Zeilenumbrüche")
        pages.append(body)
    else:
        raise OSError(f"mehr als {MAX_PAGES} Seiten")
    if not pages:
        raise OSError("keine Seite mit Ergebnissen")
    return b"\n".join(pages), headers, 200


def fetch_source(
    archive: Archive,
    source: Source,
    *,
    opener: Opener = _default_opener,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 90,
) -> dict:
    """Fetch one source with retries and record the outcome in the manifest.

    An answer that fails the format check (e.g. a maintenance page) or is stale (an older Last-Modified than an earlier
    live fetch) is retried like a network error; if all attempts fail that way, the last answer is kept for diagnosis
    but recorded as a failed fetch (ok=False).
    """
    errors: list[str] = []
    rejected = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt:
            sleep(RETRY_DELAYS[attempt - 1])
        fetched = utcnow()
        try:
            if source.paged:
                body, headers, status = _get_pages(source, opener, timeout)
            elif source.name == "eudragmdp":
                body, headers, status = _get_eudragmdp(source, opener, timeout)
            elif source.name == "pl_mz":
                body, headers, status = _get_pl_mz(source, opener, timeout)
            elif source.name == "sukl_dlp":
                body, headers, status = _get_sukl_dlp(source, opener, timeout)
            else:
                body, headers, status = _get(source.url, opener, timeout)
        except Exception as exc:  # network errors, HTTP errors, timeouts
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        produced_on = basg_produced_on(body) if source.name == "basg" else asp.fhir_date(body) if source.name == "asp" else None
        meta = {
            "origin": "live",
            "url": source.url,
            "fetched_at": iso(fetched),
            "http_status": status,
            "content_type": headers.get("Content-Type"),
            "last_modified": headers.get("Last-Modified"),
            "etag": headers.get("ETag"),
            "produced_on": produced_on,
            "warnings": _check(source, body, produced_on) or _stale(archive, source.name, body, headers.get("Last-Modified")),
            "attempts": attempt + 1,
        }
        if headers.get("X-Act"):
            meta.update(act=headers["X-Act"], published=headers.get("X-Published"))
        if meta["warnings"]:
            errors.append("Formatprüfung: " + "; ".join(meta["warnings"]))
            rejected = (body, _stamp(produced_on, fetched), meta)
            continue
        return archive.store(source.name, body, ext=source.ext, stamp=_stamp(produced_on, fetched), meta=meta)
    if rejected:
        body, stamp, meta = rejected
        meta.update(ok=False, error=" | ".join(errors), attempts=len(errors))
        return archive.store(source.name, body, ext=source.ext, stamp=stamp, meta=meta)
    entry = {
        "recorded_at": iso(utcnow()),
        "source": source.name,
        "origin": "live",
        "url": source.url,
        "ok": False,
        "error": " | ".join(errors),
        "attempts": len(errors),
    }
    archive.append(entry)
    return entry


def _succeeded(e: dict) -> bool:
    return e.get("origin") == "live" and bool(e.get("ok")) and not e.get("warnings")


def last_success(archive: Archive, name: str) -> datetime | None:
    """Time of the last live fetch of `name` that passed the format check."""
    last = max((e["fetched_at"] for e in archive.entries() if e.get("source") == name and _succeeded(e)), default=None)
    return datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None


def _fetched_recently(archive: Archive, source: Source) -> bool:
    last = last_success(archive, source.name)
    return last is not None and (utcnow() - last).total_seconds() < source.min_hours * 3600


def retry_due(archive: Archive) -> list[str]:
    """Sources fetched every run whose latest live attempt failed (for the catch-up run).

    Once-a-day sources (`min_hours`) are left out: the next scheduled run retries them anyway, and an extra
    success at noon would move them off their usual time.
    """
    latest: dict[str, dict] = {}
    for e in archive.entries():
        if e.get("origin") == "live":
            latest[e.get("source")] = e
    return [s.name for s in SOURCES.values()
            if not s.min_hours and s.name in latest and not _succeeded(latest[s.name])]


def fetch_all(archive: Archive, names: list[str] | None = None, **kwargs) -> list[dict]:
    """Fetch the selected sources independently; one failure never blocks the others.

    Without explicit names (scheduled run), sources with `min_hours` are skipped while recently fetched.
    """
    if names:
        selected = [SOURCES[n] for n in names]
    else:
        selected = [s for s in SOURCES.values() if not (s.min_hours and _fetched_recently(archive, s))]
    return [fetch_source(archive, s, **kwargs) for s in selected]
