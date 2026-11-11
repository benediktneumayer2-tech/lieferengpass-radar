"""Erstattungskodex (EKO) changes from the RIS (Amtliche Verlautbarungen der Sozialversicherung, since 2004).

Each monthly "Änderung des Erstattungskodex" is archived as the RIS HTML document (source `eko`, one file per
document, capture day = day of publication). Only deletions from the green, yellow and red box are read. Their
reason comes from the footnotes (withdrawal of the marketing authorisation, "Nichtlieferfähigkeit", withdrawn
application); the procedure number (e.g. "Abschnitt VIII/2598-2026") is kept as given.

RIS rules for the OGD interface (https://www.ris.bka.gv.at/RisInfo/OGD-FAQ.pdf): at most one request every two
seconds, no parallel connections, queries only 20-5 h Vienna time or at weekends. `sync` refuses to run outside
these hours; the one-off backfill of all documents spreads its requests over the night.
"""
from __future__ import annotations

import json
import random
import re
import time
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Callable
from zoneinfo import ZoneInfo

from .archive import Archive, iso, user_agent, utcnow

SEARCH = ("https://data.bka.gv.at/ris/api/v2.6/Sonstige?Applikation=Avsv&Titel=Erstattungskodex"
          "&DokumenteProSeite=OneHundred&Seitennummer={page}")
CHANGE = re.compile(r"Änderung(en)? des Erstattungskodex")
PAUSE = 2.0
VIENNA = ZoneInfo("Europe/Vienna")
BOXES = {"Grünen": "gruen", "Gelben": "gelb", "Roten": "rot"}
ATC = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")


def allowed(now: datetime) -> bool:
    """RIS asks for queries outside office hours: 20-5 h Vienna time or Saturday/Sunday."""
    local = now.astimezone(VIENNA)
    return local.weekday() >= 5 or local.hour >= 20 or local.hour < 5


def _get(url: str, timeout: float = 90) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": user_agent()}), timeout=timeout) as r:
        return r.read()


def hits(body: bytes) -> int:
    """Number of documents the search found (all pages)."""
    res = json.loads(body).get("OgdSearchResult", {}).get("OgdDocumentResults", {})
    return int((res.get("Hits") or {}).get("#text") or 0)


def documents(body: bytes) -> list[dict]:
    """EKO change documents of one search page: id, publication day, title, HTML address."""
    res = json.loads(body).get("OgdSearchResult", {})
    refs = res.get("OgdDocumentResults", {}).get("OgdDocumentReference", [])
    out = []
    for ref in [refs] if isinstance(refs, dict) else refs:
        meta = ref["Data"]["Metadaten"]
        title = meta["Sonstige"]["Kurztitel"]
        if not CHANGE.search(title):
            continue
        content = ref["Data"]["Dokumentliste"]["ContentReference"]
        urls = content["Urls"]["ContentUrl"] if isinstance(content, dict) else content[0]["Urls"]["ContentUrl"]
        urls = [urls] if isinstance(urls, dict) else urls
        html_url = next((u["Url"] for u in urls if u["DataType"] == "Html"), None)
        if html_url:
            out.append({"doc": meta["Technisch"]["ID"], "day": meta["Sonstige"]["Kundmachungsdatum"], "title": title,
                        "url": html_url})
    return out


RETRY_WAITS = (60, 300)  # seconds before the 2nd and 3rd attempt after a server error (RIS answers 500 at times)


def _retry(fn: Callable[[], bytes], sleep: Callable[[float], None], rand: Callable[[], float]) -> bytes:
    for wait in (*RETRY_WAITS, None):
        try:
            return fn()
        except Exception:
            if wait is None:
                raise
            sleep(wait * (0.8 + 0.4 * rand()))
    raise AssertionError("unreachable")


RECENT_DAYS = 90  # the regular run fetches only recent changes; older ones come in through the backfill


def night_end(now: datetime) -> datetime:
    """Next 04:30 Vienna time: a backfill spreads its requests until then and stays inside the RIS hours."""
    local = now.astimezone(VIENNA)
    end = local.replace(hour=4, minute=30, second=0, microsecond=0)
    return end if end > local else end + timedelta(days=1)


def sync(archive: Archive, *, pages: int | None = 1, origin: str = "live", until: datetime | None = None,
         get: Callable[[str], bytes] = _get, sleep: Callable[[float], None] = time.sleep,
         now: Callable[[], datetime] = utcnow, rand: Callable[[], float] = random.random) -> list[dict]:
    """Archive EKO change documents not yet stored, from the newest search pages (`pages=None`: all pages, backfill).

    The regular run (`pages` set) takes only documents of the last 90 days, so it stays a single-document query.
    With `until`, the documents are spread over the time left: each pause is the remaining time per remaining
    document times a random factor between 0.4 and 1.6 (never past `until`, never below the RIS minimum of 2 s).
    Returns the manifest entries; nothing is fetched outside the RIS hours, and a run stops when they end."""
    oldest = (now().date() - timedelta(days=RECENT_DAYS)).isoformat() if pages is not None else ""
    have = {e.get("doc") for e in archive.entries() if e.get("source") == "eko" and e.get("ok")}
    todo: list[dict] = []
    out: list[dict] = []
    page = 1
    while (pages is None or page <= pages) and allowed(now()):
        sleep(PAUSE + (20 * rand() if until else 0))
        url = SEARCH.format(page=page)
        try:
            body = _retry(lambda: get(url), sleep, rand)
            docs, total = documents(body), hits(body)
        except Exception as exc:  # noqa: BLE001 - recorded; documents found so far are still fetched
            entry = {"recorded_at": iso(utcnow()), "source": "eko", "origin": origin, "url": url, "ok": False,
                     "error": f"Suche: {type(exc).__name__}: {exc}"}
            archive.append(entry)
            out.append(entry)
            break
        if not docs and page > 1:
            break
        todo += [d for d in docs if d["doc"] not in have and d["day"] >= oldest]
        have |= {d["doc"] for d in docs}
        if page * 100 >= total:  # RIS answers a page past the end with an error (sometimes HTTP 500)
            break
        page += 1
    for i, d in enumerate(todo):
        gap = PAUSE
        if until:
            left = (until - now()).total_seconds()
            gap = max(PAUSE, min(left, left / (len(todo) - i) * (0.4 + 1.2 * rand())))
        sleep(gap)
        if not allowed(now()):
            break
        try:
            body = _retry(lambda: get(d["url"]), sleep, rand)
        except Exception as exc:  # noqa: BLE001 - recorded, the next run retries
            entry = {"recorded_at": iso(utcnow()), "source": "eko", "origin": origin, "url": d["url"], "ok": False,
                     "doc": d["doc"], "error": f"{type(exc).__name__}: {exc}"}
            archive.append(entry)
            out.append(entry)
            continue
        out.append(archive.store("eko", body, ext="html", stamp=d["day"], meta={
            "origin": origin, "url": d["url"], "doc": d["doc"], "title": d["title"], "published": d["day"],
            "captured_at": f"{d['day']}T00:00:00Z", "warnings": [] if b"Erstattungskodex" in body else ["kein EKO-Text"]}))
    return out


# --- parser -------------------------------------------------------------------------------------

class _Doc(HTMLParser):
    """Headings, tables (rows of cells, bold text kept apart) and paragraphs outside tables, in document order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[tuple] = []
        self._tag: list[str] = []
        self._text: list[str] = []
        self._table: list | None = None
        self._row: list | None = None
        self._cell: list[str] | None = None
        self._bold = 0
        self._bold_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell, self._bold_text = [], []
        elif tag == "span" and "Fett" in cls:
            self._bold += 1
        elif tag in ("h1", "h2", "h3", "p") and self._cell is None:
            self._text = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")
        if tag == "span":
            self._tag.append("bold" if "Fett" in cls else "span")

    def handle_endtag(self, tag):
        if tag == "span" and self._tag:
            if self._tag.pop() == "bold":
                self._bold -= 1
        elif tag == "p" and self._cell is not None:
            self._cell.append("\n")
        elif tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(("".join(self._cell).strip(), " ".join(self._bold_text).strip()))
            self._cell = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.items.append(("table", self._table))
            self._table = None
        elif tag in ("h1", "h2", "h3", "p") and self._table is None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            if text:
                self.items.append(("heading" if tag != "p" else "text", text))
            self._text = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
            if self._bold:
                self._bold_text.append(data.strip())
        else:
            self._text.append(data)


def _day(text: str) -> str | None:
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _reason(footnotes: list[str], product: str) -> str:
    for note in footnotes:
        if product and product in note:
            if "Aufhebung der Zulassung" in note or "Widerruf der Zulassung" in note or "Verzicht" in note:
                return "zulassung"
            if "Nichtlieferfähigkeit" in note or "nicht lieferbar" in note or "Lieferunfähigkeit" in note:
                return "nicht_lieferbar"
            if "Zurückziehung" in note or "Modifikation des Antrages" in note:
                return "antrag_zurueckgezogen"
            return "sonst"
    return "ohne_fussnote"


def parse(body: bytes) -> list[dict]:
    """Deletions of whole products: box, product, pack sizes, ATC, effective day, decision day, procedure, reason.

    Pack-size deletions ("Änderung der Packungsgröße") are not read; the product stays in the code."""
    doc = _Doc()
    doc.feed(body.decode("utf-8", errors="replace"))
    paragraphs = [t for kind, t in doc.items if kind == "text"]
    paragraphs += [p for kind, rows in doc.items if kind == "table" for row in rows for c, _ in row for p in c.split("\n")]
    footnotes = [re.sub(r"\s+", " ", p).strip() for p in paragraphs if p.strip().startswith("Die Streichung")]
    out, box = [], None
    for kind, value in doc.items:
        if kind == "heading":
            m = re.search(r"Streichung von im (Grünen|Gelben|Roten) Bereich", value)
            box = BOXES[m.group(1)] if m else None
            continue
        if kind != "table" or box is None:
            continue
        head = next((r for r in value if any("ATC" in c for c, _ in r)), None)
        if head is None:
            continue
        col = {name: next((i for i, (c, _) in enumerate(head) if key in c), None)
               for name, key in (("product", "Arzneispezialit"), ("menge", "Menge"), ("atc", "ATC"),
                                 ("wirkung", "Wirkung"), ("entscheidung", "Entschei"), ("verfahren", "Verfahrens"))}
        for row in value:
            if row is head or col["atc"] is None or col["atc"] >= len(row):
                continue
            atc = row[col["atc"]][0].split("\n")[0].strip()
            if not ATC.match(atc):
                continue
            cell = lambda name: row[col[name]][0] if col[name] is not None and col[name] < len(row) else ""  # noqa: E731
            text, bold = row[col["product"]] if col["product"] is not None else ("", "")
            product = bold or text.split("\n")[0].strip()
            out.append({
                "box": box, "product": product, "menge": re.sub(r"\s+", " ", cell("menge")).strip(), "atc": atc,
                "wirkung": _day(cell("wirkung")), "entscheidung": _day(cell("entscheidung")),
                "verfahren": re.sub(r"\s+", " ", cell("verfahren")).strip(), "grund": _reason(footnotes, product),
            })
        box = None
    return out
