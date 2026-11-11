"""Foreign shortage lists (other EU countries) -> uniform report items, linked to Austrian packages.

Each archived file of a source is parsed into items (one per report and product). Items are
aggregated over all files: first/last seen in the archive, still listed in the latest file.
Most foreign lists drop ended reports, so the archive is the only memory of them.

Linking to Austria uses ATC level 5 where the source has it; otherwise the ATC is derived from
the Austrian ASP list via the substance name (language-tolerant skeleton) or the brand name.
Contact columns (phone, e-mail) are never read into items.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from datetime import date, timedelta

from .substances import base_substance

COUNTRY = {
    "bfarm": "DE", "ema": "EU", "aifa": "IT", "sukl_cz": "CZ", "sukl_sk": "SK", "ogyei": "HU", "jazmp": "SI",
    "famhp": "BE", "fimea": "FI", "cima": "ES", "fda": "US", "ansm": "FR", "pl_mz": "PL",
}

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_xlsx(body: bytes, sheet: int = 1) -> list[list[str | None]]:
    """Rows of one worksheet as lists of cell texts (stdlib only; enough for plain data exports)."""
    z = zipfile.ZipFile(io.BytesIO(body))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
    rows = []
    for r in ET.fromstring(z.read(f"xl/worksheets/sheet{sheet}.xml")).iter(f"{_NS}row"):
        cells: dict[int, str | None] = {}
        for c in r.iter(f"{_NS}c"):
            col = 0
            for ch in re.match(r"[A-Z]+", c.get("r", "A")).group():
                col = col * 26 + ord(ch) - 64
            t, v = c.get("t"), c.find(f"{_NS}v")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{_NS}t"))
            elif v is None:
                val = None
            else:
                val = shared[int(v.text)] if t == "s" else v.text
            cells[col - 1] = val.strip() if isinstance(val, str) else val
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i) for i in range(width)])
    return rows


def read_xls(body: bytes, sheet: int = 0) -> list[list[str]]:
    """Rows of one worksheet of an old Excel file (BIFF, via xlrd) as lists of cell texts."""
    import xlrd

    with open("/dev/null", "w") as quiet:  # xlrd reports tolerated OLE quirks on its log file
        book = xlrd.open_workbook(file_contents=body, ignore_workbook_corruption=True, logfile=quiet)
    sh = book.sheet_by_index(sheet)
    return [[str(c.value).strip() for c in sh.row(i)] for i in range(sh.nrows)]


def parse_date(value) -> str | None:
    """ISO date from dd.mm.yyyy, dd/mm/yyyy, yyyy-mm-dd(...) or an Excel serial number; else None."""
    s = str(value or "").strip()
    if not s or s.upper() in {"N/A", "NA", "-"}:
        return None
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
    else:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            y, mo, d = map(int, m.groups())
        elif re.fullmatch(r"\d{5}(\.\d+)?", s):  # Excel serial day
            return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
        else:
            return None
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _clean(value) -> str | None:
    s = str(value or "").strip()
    return None if not s or s.upper() == "N/A" else s


def _item_id(source: str, report: str, product: str | None) -> str:
    return f"{source}:{report}:" + hashlib.sha1((product or "").encode("utf-8")).hexdigest()[:8]


def parse_bfarm(body: bytes) -> list[dict]:
    """BfArM CSV: one row per PZN; a report keeps its identity via 'Referenzierte Erstmeldung'."""
    text = body.decode("utf-8-sig") if body[:3] == b"\xef\xbb\xbf" else body.decode("cp1252")
    items: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        report = _clean(r.get("Referenzierte Erstmeldung")) or _clean(r.get("Bearbeitungsnummer"))
        product = _clean(r.get("Arzneimittlbezeichnung"))
        if not report:
            continue
        iid = _item_id("bfarm", report, product)
        it = items.setdefault(iid, {
            "item_id": iid, "source": "bfarm", "country": "DE", "report_id": report, "product": product,
            "substances": _clean(r.get("Wirkstoffe")), "atc5": (_clean(r.get("Atc Code")) or "").upper()[:7] or None,
            "strength": None, "form": _clean(r.get("Darreichungsform")), "holder": _clean(r.get("Zulassungsinhaber")),
            "signal_date": parse_date(r.get("Datum der Erstmeldung")) or parse_date(r.get("Beginn")),
            "start_date": parse_date(r.get("Beginn")), "expected_end": parse_date(r.get("Ende")),
            "reason": " / ".join(x for x in (_clean(r.get("Art des Grundes")), _clean(r.get("Grund"))) if x) or None,
            "status": _clean(r.get("Meldungsart")), "native_ids": set(), "end_date": None,
        })
        it["native_ids"].add(_clean(r.get("PZN")) or "")
    return list(items.values())


def parse_ema(body: bytes) -> list[dict]:
    """EMA shortages catalogue (xlsx): header row starts with 'Category'."""
    rows = read_xlsx(body)
    head = next((i for i, r in enumerate(rows) if r and r[0] == "Category"), None)
    if head is None:
        return []
    cols = {name: i for i, name in enumerate(rows[head]) if name}

    def get(r, name):
        i = cols.get(name)
        return r[i] if i is not None and i < len(r) else None

    out = []
    for r in rows[head + 1:]:
        url = _clean(get(r, "Shortage URL"))
        product = _clean(get(r, "Medicine affected"))
        if not (url or product):
            continue
        report = (url or product).rstrip("/").rsplit("/", 1)[-1]
        out.append({
            "item_id": _item_id("ema", report, product), "source": "ema", "country": "EU", "report_id": report,
            "product": product, "substances": _clean(get(r, "International non-proprietary name (INN) or common name")),
            "atc5": None, "strength": _clean(get(r, "Strengths affected")), "form": _clean(get(r, "Pharmaceutical forms affected")),
            "holder": None,
            "signal_date": parse_date(get(r, "First published date")) or parse_date(get(r, "Start of shortage date")),
            "start_date": parse_date(get(r, "Start of shortage date")),
            "expected_end": parse_date(get(r, "Expected resolution date")),
            "reason": None, "status": _clean(get(r, "Supply shortage status")), "native_ids": set(), "end_date": None,
        })
    return out


# --- further national lists ----------------------------------------------------------------

EINSTELLUNG = "einstellung"  # permanent end of marketing, kept apart from temporary shortages
UNTERBRECHUNG = "unterbrechung"


def _decode(body: bytes, fallback: str) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode(fallback)


def _one_line(value) -> str | None:
    return _clean(re.sub(r"\s+", " ", str(value or "")))


def _atc(value) -> str | None:
    m = re.match(r"[A-Z]\d\d[A-Z]{2}\d\d", str(value or "").strip().upper())
    return m.group() if m else None


def _csv(text: str, first_col: str) -> list[dict]:
    """Rows after the header line whose first cell is `first_col` (skips notes above the header)."""
    rows = csv.reader(io.StringIO(text), delimiter=";")
    for head in rows:
        if head and head[0].strip() == first_col:
            head = [h.strip() for h in head]
            return [dict(zip(head, r)) for r in rows if any(c.strip() for c in r)]
    return []


def _item(source: str, report: str, product: str | None, **fields) -> dict:
    it = {"item_id": _item_id(source, report, product), "source": source, "country": COUNTRY[source],
          "report_id": report, "product": product, "substances": None, "atc5": None, "strength": None, "form": None,
          "holder": None, "signal_date": None, "start_date": None, "expected_end": None, "end_date": None,
          "reason": None, "status": None, "native_ids": set()}
    it.update(fields)
    it["signal_date"] = it["signal_date"] or it["start_date"]
    return it


def _unique(items: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for it in items:
        if it["item_id"] in out:
            out[it["item_id"]]["native_ids"] |= it["native_ids"]
        else:
            out[it["item_id"]] = it
    return list(out.values())


def _cases(source: str, events: list[dict]) -> list[dict]:
    """Event log -> cases. An event has code, kind (interrupt/resume/stop), optional native report and item fields.

    Events are given oldest first for equal dates. Each interruption opens a case that the next resumption or stop
    ends (end_date); a repeated interruption only updates expected end and reason. A stop is a case of its own.
    """
    status = {"interrupt": UNTERBRECHUNG, "stop": EINSTELLUNG}
    events = sorted(events, key=lambda e: (e["code"], e["start_date"] or e["signal_date"] or "", e["signal_date"] or ""))
    out, open_ = [], {}
    for ev in events:
        code, kind, report = ev.pop("code"), ev.pop("kind"), ev.pop("report", None)
        cur = open_.get(code)
        if cur and cur["status"] == status.get(kind):
            cur.update({k: ev[k] for k in ("expected_end", "reason") if ev.get(k)})
            continue
        if cur:
            cur["end_date"] = ev["start_date"] or ev["signal_date"]
            del open_[code]
        if kind in status:
            report = report or f"{code}:{ev['start_date'] or ev['signal_date']}"
            product = ev.pop("product", None)
            open_[code] = _item(source, report, product, status=status[kind], native_ids={code}, **ev)
            out.append(open_[code])
    return out


def parse_aifa(body: bytes) -> list[dict]:
    """AIFA shortage list (CSV, cp1252, notes above the header): one row per AIC pack and shortage start.

    Announced future shortages are public since the list date ('aggiornato al dd/mm/yyyy'), not from their start.
    """
    text = _decode(body, "cp1252")
    m = re.search(r"aggiornato al (\d{1,2}/\d{1,2}/\d{4})", text[:2000])
    listed = parse_date(m.group(1)) if m else None
    out = []
    for r in _csv(text, "Nome medicinale"):
        aic, start = _clean(r.get("Codice AIC")), parse_date(r.get("Data inizio"))
        if not aic:
            continue
        reason = _one_line(r.get("Motivazioni"))
        out.append(_item(
            "aifa", f"{aic}:{start}", _one_line(r.get("Nome medicinale")), substances=_one_line(r.get("Principio attivo")),
            atc5=_atc(r.get("Codice ATC")), strength=_one_line(r.get("Forma farmaceutica e dosaggio")),
            holder=_one_line(r.get("Titolare AIC")), start_date=start, expected_end=parse_date(r.get("Fine presunta")),
            signal_date=min(filter(None, (start, listed)), default=None),
            reason=reason, native_ids={aic},
            status=EINSTELLUNG if "cessata commercializzazione definitiva" in (reason or "").lower() else "carenza",
        ))
    return _unique(out)


def parse_sukl_cz(body: bytes) -> list[dict]:
    """SÚKL CZ notifications (mr.zip -> mr_hlaseni.csv, cp1250): full event log per SÚKL code since 2008."""
    if body[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(body))
        body = z.read(next(n for n in z.namelist() if n.lower().endswith("mr_hlaseni.csv")))
    kinds = {"preruseni": "interrupt", "obnoveni": "resume", "zahajeni": "resume", "ukonceni": "stop"}
    events = []
    for r in reversed(_csv(_decode(body, "cp1250"), "POSLEDNI_PLATNE_HLASENI")):  # file is newest first
        code, kind = _clean(r.get("KOD_SUKL")), kinds.get((r.get("TYP_OZNAMENI") or "").strip().lower())
        if code and kind:
            events.append({
                "code": code, "kind": kind, "product": _one_line(r.get("NAZEV")), "strength": _one_line(r.get("DOPLNEK")),
                "atc5": _atc(r.get("ATC")), "start_date": parse_date(r.get("PLATNOST_OD")),
                "signal_date": parse_date(r.get("DATUM_HLASENI")), "expected_end": parse_date(r.get("TERMIN_OBNOVENI")),
                "reason": _one_line(r.get("DUVOD_PRERUSENI_UKONCENI")),
            })
    return _cases("sukl_cz", events)


def parse_sukl_sk(body: bytes) -> list[dict]:
    """ŠÚKL SK notifications (CSV, UTF-8): event log since 2019, U/R/O/Z = launch/interruption/resumption/stop."""
    kinds = {"U": "resume", "R": "interrupt", "O": "resume", "Z": "stop"}
    events = []
    for r in reversed(_csv(_decode(body, "cp1250"), "Podanie")):  # file is newest first
        code, kind = _clean(r.get("Kód")), kinds.get((r.get("Predmet") or "").strip().upper())
        if code and kind:
            holder = re.sub(r"\s*\([^()]*\)$", "", _one_line(r.get("Držiteľ")) or "")
            events.append({
                "code": code, "kind": kind, "product": _one_line(r.get("Liek")), "holder": holder or None,
                "start_date": parse_date(r.get("Účinnosť")), "signal_date": parse_date(r.get("Podanie")),
            })
    return _cases("sukl_sk", events)


def parse_ogyei(body: bytes) -> list[dict]:
    """OGYÉI HU shortage list (CSV, ISO-8859-2): one row per pack (TK number) and shortage start."""
    out = []
    for r in _csv(_decode(body, "iso-8859-2"), "Termék neve"):
        tk, start = _clean(r.get("TK szám")), parse_date(r.get("A hiány kezdete"))
        if not tk:
            continue
        reason = _one_line(r.get("A hiány oka"))
        out.append(_item(
            "ogyei", f"{tk}:{start}", _one_line(r.get("Termék neve")), substances=_one_line(r.get("Hatóanyag")),
            atc5=_atc(r.get("ATC kód 1/ATC kód 2")), form=_one_line(r.get("Kiszerelés neve")),
            holder=_one_line(r.get("Forg Eng Jog")), start_date=start, expected_end=parse_date(r.get("A hiány tervezett vége")),
            reason=reason, native_ids={tk},
            status=EINSTELLUNG if "megszüntetése" in (reason or "").lower() else "hiány",
        ))
    return _unique(out)


def _jazmp_kind(text: str | None) -> str | None:
    t = re.sub(r"\s+", " ", (text or "").lower())
    if "preklic" in t:
        return None
    if "prihod" in t or "začetka prometa" in t:
        return "resume"
    if "začasn" in t or "motnj" in t:  # also 'začasnega ali stalnega prenehanja' (unclear -> temporary)
        return "interrupt"
    if "staln" in t:
        return "stop"
    return None


def parse_jazmp(body: bytes) -> list[dict]:
    """JAZMP SI notifications (xlsx, sheet 1 = all notifications since 2008): event log per DŠ number."""
    rows = read_xlsx(body, 1)
    head = next((i for i, r in enumerate(rows) if r and r[0] == "DŠ zdravila"), None)
    if head is None:
        return []
    cols = {name: i for i, name in enumerate(rows[head]) if name}

    def get(r, name):
        i = cols.get(name)
        return r[i] if i is not None and i < len(r) else None

    events = []
    for r in reversed(rows[head + 1:]):  # newest first
        code, kind = _clean(get(r, "DŠ zdravila")), _jazmp_kind(get(r, "Vrsta obvestila"))
        if code and kind:
            holder = _one_line(get(r, "Poročevalec"))
            events.append({
                "code": code, "kind": kind, "report": _clean(get(r, "Zadeva")), "product": _one_line(get(r, "Zdravilo")),
                "holder": None if holder == "0" else holder, "start_date": parse_date(get(r, "Datum začetka")),
                "signal_date": parse_date(get(r, "Datum prejema obvestila")),
                "expected_end": parse_date(get(r, "Napovedani datum konca")),
            })
    return _cases("jazmp", events)


def parse_famhp(body: bytes) -> list[dict]:
    """FAMHP BE PharmaStatus export (xlsx): status snapshot per pack; 'Available' rows are no report."""
    rows = read_xlsx(body)
    head = next((i for i, r in enumerate(rows) if r and r[0] == "Medicine"), None)
    if head is None:
        return []
    cols = {name: i for i, name in enumerate(rows[head]) if name}

    def get(r, name):
        i = cols.get(name)
        return r[i] if i is not None and i < len(r) else None

    out = []
    for r in rows[head + 1:]:
        status = _clean(get(r, "Notification status"))
        if status not in ("Temporarily unavailable", "Limited availability", "Available again", "Stop of commercialisation"):
            continue
        cti, cnk = _clean(get(r, "CTI extended")), _clean(get(r, "CNK"))
        pub, frm = parse_date(get(r, "Date of publication")), parse_date(get(r, "From"))
        again = status == "Available again"
        out.append(_item(
            "famhp", f"{cti or cnk}:{pub or frm}", _one_line(get(r, "Medicine")),
            substances=_one_line(get(r, "Active substance")), atc5=_atc(get(r, "ATC")), holder=_one_line(get(r, "Company")),
            signal_date=pub, start_date=None if again else frm, end_date=frm if again else None,
            expected_end=None if again else parse_date(get(r, "To")), reason=_one_line(get(r, "Reason")),
            status=EINSTELLUNG if status == "Stop of commercialisation" else status, native_ids={x for x in (cti, cnk) if x},
        ))
    return _unique(out)


def parse_fimea(body: bytes) -> list[dict]:
    """Fimea FI availability disruptions (CSV, UTF-8): VNR only, no name; K = active, E = starts within 2 weeks."""
    out = []
    for r in _csv(_decode(body, "cp1252"), "VNR"):
        vnr, start = _clean(r.get("VNR")), parse_date(r.get("SaatavuushairioAlkupaiva"))
        if not vnr:
            continue
        flag = (r.get("Voimassa") or "").strip()
        out.append(_item(
            "fimea", f"{vnr}:{start}", None, holder=_one_line(r.get("Yritys")),
            signal_date=parse_date(r.get("Ilmoituspaiva")), start_date=start,
            expected_end=parse_date(r.get("SaatavuushairioLoppupaiva")),
            status={"K": "aktiv", "E": "angekündigt"}.get(flag, flag or None), native_ids={vnr},
        ))
    return _unique(out)


def _epoch_day(ms) -> str | None:
    """Day of a CIMA epoch-millisecond timestamp (local midnight in Madrid, i.e. 22/23 h UTC the day before)."""
    if ms in (None, ""):
        return None
    return (date(1970, 1, 1) + timedelta(milliseconds=int(ms) + 43_200_000)).isoformat()


def _us_date(value) -> str | None:
    """MM/DD/YYYY (current openFDA export) or ISO (older exports)."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(value or ""))
    if not m:
        return parse_date(value) if re.match(r"\d{4}-", str(value or "")) else None
    mo, d, y = map(int, m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_fda(body: bytes) -> list[dict]:
    """openFDA drug shortages (bulk zip with one JSON file): one row per package NDC, grouped per shortage.

    A shortage is identified by generic name and initial posting date; 'To Be Discontinued' is a permanent
    discontinuation ('einstellung'), 'Resolved' ends the shortage at its update date.
    """
    z = zipfile.ZipFile(io.BytesIO(body))
    rows = json.loads(z.read(z.namelist()[0])).get("results", [])
    items: dict[str, dict] = {}
    for r in rows:
        product = _clean(r.get("generic_name"))
        posted = _us_date(r.get("initial_posting_date"))
        if not product:
            continue
        raw_status = _clean(r.get("status")) or ""
        status = {"To Be Discontinued": "einstellung", "Resolved": "resolved"}.get(raw_status, raw_status.lower() or None)
        subs = (r.get("openfda") or {}).get("substance_name") or []
        report = f"{product}|{posted}"
        it = items.get(report)
        if it is None:
            it = items[report] = _item(
                "fda", report, product,
                substances=" + ".join(sorted(set(subs))) or None, form=_clean(r.get("dosage_form")),
                holder=_clean(r.get("company_name")), signal_date=posted, start_date=posted,
                end_date=_us_date(r.get("update_date")) if status == "resolved" else None,
                reason=_clean(r.get("shortage_reason")), status=status,
            )
        elif status != "einstellung" and it["status"] == "einstellung":
            it["status"] = status  # a current shortage outweighs single discontinued packages
        it["native_ids"].add(_clean(r.get("package_ndc")) or "")
    return list(items.values())


def parse_cima(body: bytes) -> list[dict]:
    """AEMPS CIMA supply problems: JSONL bundle, one raw API page (psuministro?pagina=N) per line."""
    try:
        pages = [json.loads(body)]
    except ValueError:
        pages = [json.loads(line) for line in body.splitlines() if line.strip()]
    out = []
    for page in pages:
        for r in page.get("resultados") or []:
            cn, start = _clean(r.get("cn")), _epoch_day(r.get("fini"))
            if not cn:
                continue
            out.append(_item(
                "cima", f"{cn}:{start}", _one_line(r.get("nombre")), start_date=start,
                expected_end=_epoch_day(r.get("ffin")), reason=_one_line(r.get("observ")),
                status="activo" if r.get("activo") else "inactivo", native_ids={cn},
            ))
    return _unique(out)


ANSM_STATUS = {"Rupture de stock": "rupture", "Tension d'approvisionnement": "tension",
               "Arrêt de commercialisation": EINSTELLUNG, "Remise à disposition": "remise"}


def ansm_title(title: str) -> tuple[str, str | None]:
    """'Rythmol 300 mg, comprimé – [propafénone (chlorhydrate de)]' -> ('Rythmol 300 mg, comprimé', 'propafénone')."""
    m = re.match(r"(.*?)\s+[–-]\s+\[(.*)\]?\s*$", title)
    if not m:
        return title, None
    subs = re.sub(r"\s*\([^)]*\)", "", m.group(2).rstrip("] ")).strip()  # drop salts in brackets
    return m.group(1), subs or None


def parse_ansm(body: bytes) -> list[dict]:
    """ANSM FR availability list (xls): title 'Product – [substances]', start, return to supply, status."""
    rows = read_xls(body)
    if not rows:
        return []
    cols = {name: i for i, name in enumerate(rows[0])}
    out = []
    for r in rows[1:]:
        get = lambda name: r[cols[name]] if name in cols and cols[name] < len(r) else ""  # noqa: E731
        status = ANSM_STATUS.get(get("Statut"))
        if status is None or get("Produit(s) de santé") not in ("Médicaments", "Vaccins"):
            continue
        title = _one_line(get("Titre")) or ""
        product, subs = ansm_title(title)
        url = get("URL de la page")
        created, start = parse_date(get("Date de création")), parse_date(get("Date de début de situation"))
        back = parse_date(get("Date de remise à disposition")) or parse_date(get("Date de mise à jour")) if status == "remise" else None
        out.append(_item(
            "ansm", url.rstrip("/").rsplit("/", 1)[-1] or title, product, substances=subs or None,
            signal_date=created, start_date=start or created, end_date=back, status=status,
        ))
    return _unique(out)


def pdf_blocks(body: bytes) -> list[list[dict]]:
    """Text blocks per page with PDF coordinates (poppler `pdftotext -bbox-layout`); a table cell is one block."""
    out = subprocess.run(["pdftotext", "-bbox-layout", "-", "-"], input=body, capture_output=True, check=True).stdout
    pages = []
    for page in re.findall(rb"<page .*?</page>", out, re.S):
        blocks = []
        for x0, y0, x1, y1, inner in re.findall(
                rb'<block xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</block>', page, re.S):
            lines = [" ".join(html.unescape(w.decode()) for w in re.findall(rb">([^<]*)</word>", line))
                     for line in re.findall(rb"<line.*?</line>", inner, re.S)]
            blocks.append({"x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1), "lines": lines})
        pages.append(blocks)
    return pages


PL_HEADERS = {"lp": ("Lp.",), "inn": ("Nazwa międzynarodowa",), "form": ("Postać",), "strength": ("Moc",),
              "pack": ("Wielkość opakowania",), "code": ("Kod EAN", "Kod GTIN"), "product": ("Nazwa produktu", "spożywczego")}


def latin_inn(name: str) -> str:
    """Polish lists use Latin INNs: 'Methylphenidati hydrochloridum' -> 'Methylphenidat hydrochlorid',
    'Ipratropii bromidum' -> 'Ipratropium bromid', 'Natrii valproas' -> 'Natrium valproat'."""
    def word(w: str) -> str:
        lw = w.lower()
        if re.fullmatch(r"(an|mono|di|tri|sesqui|hemi)?hydricus|(an|mono|di|tri)?hydrat\w*", lw):
            return ""
        if lw.endswith("icum") and lw[:-4] in ("natr", "kal", "calc", "magnes"):
            return w[:-4] + "ium"
        if lw.endswith("ii"):
            return w[:-1] + "um"
        if lw.endswith("ium") or len(lw) < 5:
            return w
        if lw.endswith("um"):
            return w[:-2]
        if lw.endswith("as"):
            return w[:-2] + "at"
        if lw.endswith("i"):
            return w[:-1]
        return w
    return re.sub(r"\s+", " ", re.sub(r"[A-Za-zÀ-ž]+", lambda m: word(m.group()), name)).strip()


def pl_rows(pages: list[list[dict]]) -> list[dict]:
    """Rows of the Polish list: header blocks give the column centres (same on every page); each cell joins the
    row whose number (vertically centred like every cell) is closest, cells above a page's first number continue
    the last row of the previous page."""
    centres: dict[str, float] = {}
    rows: list[dict] = []
    for blocks in pages:
        if "inn" not in centres:
            head = {}
            for b in blocks:
                text = " ".join(b["lines"])
                for col, keys in PL_HEADERS.items():
                    if col not in head and any(k in text for k in keys) and len(text) < 160:
                        head[col] = b
            if "inn" not in head or "lp" not in head:
                continue
            centres = {col: (b["x0"] + b["x1"]) / 2 for col, b in head.items()}
            top = max(b["y1"] for b in head.values())
            blocks = [b for b in blocks if b["y0"] > top]
        lp_right = (centres["lp"] + centres.get("product", centres["inn"])) / 2
        anchors = [b for b in blocks if b["x1"] <= lp_right + 5 and len(b["lines"]) == 1 and re.fullmatch(r"\d+\.?", b["lines"][0])]
        page_rows = sorted(({"lp": int(a["lines"][0].rstrip(".")), "y": (a["y0"] + a["y1"]) / 2, "cells": defaultdict(list)}
                            for a in anchors), key=lambda r: r["y"])
        for b in blocks:
            if b in anchors or not page_rows:
                continue
            col = min(centres, key=lambda c: abs(centres[c] - (b["x0"] + b["x1"]) / 2))
            if col == "lp":
                continue
            if b["y1"] < page_rows[0]["y"] - 12 and rows:
                target = rows[-1]
            else:
                target = min(page_rows, key=lambda r: 0 if b["y0"] - 2 <= r["y"] <= b["y1"] + 2 else min(abs(r["y"] - b["y0"]), abs(r["y"] - b["y1"])))
            target["cells"][col].append((b["y0"], " ".join(b["lines"])))
        rows += page_rows
    out = []
    for r in rows:
        cell = {c: " ".join(t for _, t in sorted(v)) for c, v in r["cells"].items()}
        cell["codes"] = re.findall(r"\b\d{13,14}\b", cell.get("code", ""))
        out.append({"lp": r["lp"], **cell})
    return out


def parse_pl_mz(body: bytes) -> list[dict]:
    """Polish list of products at risk of unavailability (PDF): one item per product and strength; the list has no
    dates, so `load` turns consecutive issues into listings (signal = first issue of an uninterrupted listing)."""
    out = []
    for r in pl_rows(pdf_blocks(body)):
        product, inn = _one_line(r.get("product")), _one_line(r.get("inn"))
        if not product and not inn:
            continue
        strength = _one_line(r.get("strength"))
        out.append(_item("pl_mz", f"{skeleton(product)}|{strength or ''}", product,
                         substances=latin_inn(inn) if inn and inn != "-" else None, strength=strength,
                         form=_one_line(r.get("form")), status="zagrożony", native_ids=set(r["codes"])))
    return _unique(out)


PARSERS = {
    "bfarm": parse_bfarm, "ema": parse_ema, "aifa": parse_aifa, "sukl_cz": parse_sukl_cz, "sukl_sk": parse_sukl_sk,
    "ogyei": parse_ogyei, "jazmp": parse_jazmp, "famhp": parse_famhp, "fimea": parse_fimea, "cima": parse_cima,
    "fda": parse_fda, "ansm": parse_ansm, "pl_mz": parse_pl_mz,
}


def file_day(entry: dict) -> str:
    """Archive day of a stored file: capture/fetch time, else the date in the file name."""
    for key in ("captured_at", "fetched_at"):
        if entry.get(key):
            return entry[key][:10]
    return entry["path"].rsplit("/", 1)[-1][:10]


def aggregate(files: list[tuple[str, list[dict]]]) -> list[dict]:
    """Merge parsed files (day, items) of one source; files must be in day order."""
    merged: dict[str, dict] = {}
    latest_day = files[-1][0] if files else None
    latest_ids = {it["item_id"] for it in files[-1][1]} if files else set()
    for day, items in files:
        for it in items:
            m = merged.get(it["item_id"])
            if m is None:
                m = merged[it["item_id"]] = {**it, "first_seen": day, "n_files": 0, "native_ids": set()}
            else:
                first_signal = min(filter(None, (m["signal_date"], it["signal_date"])), default=None)
                m.update({k: v for k, v in it.items() if v not in (None, set()) and k != "native_ids"})
                m["signal_date"] = first_signal
            m["native_ids"] |= it["native_ids"]
            m["last_seen"] = day
            m["n_files"] += 1
    for m in merged.values():
        m["still_listed"] = int(m["item_id"] in latest_ids and m["last_seen"] == latest_day)
        m["native_ids"] = " ".join(sorted(x for x in m["native_ids"] if x)) or None
    return sorted(merged.values(), key=lambda m: m["item_id"])


# --- matching helpers ---------------------------------------------------------------------

LEGAL_WORDS = frozenset(
    "GMBH AG KG CO SE SA SAS SL SPA S P A SRL BV NV LTD LIMITED PLC INC LLC AB AS OY APS SRO KFT DOO "
    "PHARMA PHARMACEUTICALS PHARMACEUTICAL PHARMACEUTICA PHARMACEUTIQUE ARZNEIMITTEL HEALTHCARE LABORATORIES "
    "LABORATORIOS LABORATOIRES LABORATORIO LABS LAB INTERNATIONAL GROUP HOLDING VERTRIEB VERTRIEBS "
    "DEUTSCHLAND AUSTRIA OSTERREICH OESTERREICH GERMANY ITALIA ITALY FRANCE ESPANA EUROPE EU THE AND UND".split()
)


def _ascii(text: str) -> str:
    text = text.replace("ß", "ss")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


LEGAL_FORMS = frozenset("GMBH AG KG CO SE SA SAS SL SPA S P A SRL BV NV LTD LIMITED PLC INC LLC AB AS OY APS SRO KFT DOO "
                        "EHF SARL SPOL ZOO".split())
# Companies of one corporate group count as the same holder (public group structure as of 2026; keys as returned
# for the company names). Novartis and Sandoz are separate since the 2023 spin-off, as are Sanofi/Opella, GSK/Haleon.
GROUPS = {
    "HEXAL": "SANDOZ", "LEK": "SANDOZ", "EBEWE": "SANDOZ", "1APHARMA": "SANDOZ",
    "RATIOPHARM": "TEVA", "ACTAVIS": "TEVA", "PLIVA": "TEVA",
    "MYLAN": "VIATRIS", "UPJOHN": "VIATRIS", "MEDA": "VIATRIS",
    "ALIUD": "STADA", "EG": "STADA",
    "TAD": "KRKA", "INTAS": "ACCORD", "EGIS": "SERVIER", "BERLIN": "MENARINI",
    "SHIRE": "TAKEDA", "BAXALTA": "TAKEDA", "HOSPIRA": "PFIZER", "WYETH": "PFIZER",
    "GLAXO": "GLAXOSMITHKLINE", "GSK": "GLAXOSMITHKLINE", "CILAG": "JANSSEN", "PUREN": "AUROBINDO",
    "RANBAXY": "SUN", "BASICS": "SUN", "HORMOSAN": "LUPIN", "BETAPHARM": "REDDY", "VALEANT": "BAUSCH",
}


def holder_key(name: str | None) -> str | None:
    """Company key for "same holder": the first distinctive word of the name ('Sandoz GmbH' -> 'SANDOZ'), else the
    short words before the legal form ('G.L. Pharma GmbH' -> 'GLPHARMA'), mapped to its corporate group."""
    words = re.findall(r"[A-Z0-9]+", _ascii(name or "").upper())
    key = next((w for w in words if len(w) >= 3 and w not in LEGAL_WORDS), None)
    if key is None:
        head = []
        for w in words:
            if w in LEGAL_FORMS and head and (len(w) > 1 or len(head[-1]) > 1):  # 'EG S.P.A.' stops, '1 A Pharma' not
                break
            head.append(w)
        key = "".join(head) or None
    return GROUPS.get(key, key) if key else None


def skeleton(name: str | None) -> str:
    """Language-tolerant spelling key: amoxicillina / amoxicilina / Amoxicillin -> same key."""
    s = re.sub(r"[^a-z]", "", _ascii(name or "").lower())
    for a, b in (("ph", "f"), ("th", "t"), ("y", "i"), ("x", "cs"), ("k", "c"), ("z", "c"), ("qu", "c")):
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)
    return re.sub(r"[aeio]$", "", s)


_STRENGTH = re.compile(r"(\d+(?:[.,]\d+)?)\s*(MG|G|µG|UG|MCG|ML|IE|I\.E\.|IU|E|%)(?![A-Z])", re.I)


def strengths(text: str | None) -> set[str]:
    """Normalised strength tokens, e.g. 'Ospamox 500 mg' -> {'500MG'}."""
    out = set()
    for num, unit in _STRENGTH.findall(text or ""):
        unit = unit.upper().replace("µ", "U").replace("I.E.", "IE").replace("MCG", "UG").replace("IU", "IE")
        num = num.replace(",", ".")
        num = num.rstrip("0").rstrip(".") if "." in num else num
        out.add(num + unit)
    return out


def atc_lookup(asp_rows: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(substance skeleton -> ATC5s, brand word -> ATC5s) from single-substance Austrian packages."""
    by_substance: dict[str, set[str]] = {}
    by_brand: dict[str, set[str]] = {}
    for r in asp_rows:
        atc = (r.get("atc") or "")[:7]
        if len(atc) != 7:
            continue
        subs = [s for s in (r.get("substances") or "").split(" + ") if s]
        if len(subs) == 1:
            for key in {skeleton(subs[0]), skeleton(base_substance(subs[0].upper()))}:
                by_substance.setdefault(key, set()).add(atc)
        brand = re.match(r"[A-ZÄÖÜ]+", (r.get("name") or "").upper())
        if brand and len(brand.group()) >= 5:
            by_brand.setdefault(brand.group(), set()).add(atc)
    return by_substance, by_brand


_COMBO = re.compile(r"[,;+/]| (?:and|und|e|y|et|i|a|og|ja|och|en|és|in) ", re.I)
_COMBO_STRENGTH = re.compile(r"\d\s*(?:mg|g|µg|ug|mcg|ie|iu|ui)?\s*/\s*\d", re.I)  # 10 mg/80 mg, not 5 mg/ml


def _lead_words(product: str) -> list[str]:
    """Words of a product name before the first strength, comma or bracket: 'Amoxicillin Sandoz 500 mg' -> 2 words."""
    words = []
    for w in re.split(r"[,;(]", product)[0].split():
        if re.search(r"\d", w):
            break
        words.append(w)
    return words


def derive_atc(item: dict, by_substance: dict[str, set[str]], by_brand: dict[str, set[str]]) -> tuple[str | None, str | None]:
    """(ATC5, method) for an item without ATC: substance name, else leading words of the product name, then brand.

    Only a unique ATC counts. Names that look like a combination (connector, '+', 10 mg/80 mg, two substance
    words) get no ATC from the product name, nor from a brand word that is itself a substance.
    """
    subs, product = item.get("substances"), item.get("product") or ""
    words = _lead_words(product)
    combo = ("+" in product or _COMBO.search(f" {' '.join(words)} ")
             or _COMBO_STRENGTH.search(f"{product} {item.get('strength') or ''}")
             or sum(skeleton(base_substance(w.upper())) in by_substance for w in words if len(w) >= 5) > 1)
    if subs and not _COMBO.search(subs):
        hit = by_substance.get(skeleton(base_substance(subs.upper())))
        if hit and len(hit) == 1:
            return next(iter(hit)), "wirkstoff"
        for word in sorted(re.findall(r"[A-Za-zÀ-ÿ]{5,}", subs), key=len, reverse=True):
            hit = by_substance.get(skeleton(word))
            if hit and len(hit) == 1:
                return next(iter(hit)), "wirkstoff_wort"
    elif not subs and words and not combo:
        for n in range(min(3, len(words)), 0, -1):
            if n == 1 and len(words[0]) < 5:
                break
            hit = by_substance.get(skeleton(base_substance(" ".join(words[:n]).upper())))
            if hit and len(hit) == 1:
                return next(iter(hit)), "produktname"
    brand = re.match(r"[A-ZÄÖÜ]+", _ascii(product).upper())
    if brand and len(brand.group()) >= 5 and not (combo and skeleton(brand.group()) in by_substance):
        hit = by_brand.get(brand.group())
        atc = next(iter(hit)) if hit and len(hit) == 1 else None
        # with a known substance the brand ATC must fit one of its words (brand families differ in content)
        if atc and (not subs or any(atc in by_substance.get(skeleton(w), ()) for w in re.findall(r"[A-Za-zÀ-ÿ]{5,}", subs))):
            return atc, "handelsname"
    return None, None


def link(items: list[dict], asp_rows: list[dict]) -> list[dict]:
    """Fill atc5/atc_method on all items; return links to Austrian ASP packages of the same ATC5 for current items.

    Current = still listed in the latest file, not a permanent discontinuation, and no end before the
    file date. Each link says whether a strength of the foreign item appears in the Austrian package
    name and whether the marketing authorisation holder matches (first distinctive company word).
    """
    by_substance, by_brand = atc_lookup(asp_rows)
    by_atc: dict[str, list[dict]] = {}
    for r in asp_rows:
        if r.get("valid") and len(r.get("atc") or "") >= 7:
            by_atc.setdefault(r["atc"][:7], []).append(r)
    links = []
    for it in items:
        if it.get("atc5"):
            it["atc_method"] = it.get("atc_method") or "quelle"
        else:
            it["atc5"], it["atc_method"] = derive_atc(it, by_substance, by_brand)
        current = (it.get("still_listed") and it.get("status") != "einstellung"
                   and not (it.get("end_date") and it["end_date"] <= it.get("last_seen", "")))
        if not it["atc5"] or not current:
            continue
        it_strengths = strengths(it.get("strength")) | strengths(it.get("product"))
        it_holder = holder_key(it.get("holder"))
        for r in by_atc.get(it["atc5"], []):
            links.append({
                "item_id": it["item_id"], "pzn": r["pzn"],
                "strength_match": int(bool(it_strengths & strengths(r.get("name")))),
                "holder_match": int(bool(it_holder) and it_holder == holder_key(r.get("inhaber"))),
            })
    return links


# Event logs that carry their full history in every file: only the latest file is parsed.
FULL_HISTORY = frozenset({"sukl_cz", "sukl_sk", "jazmp"})
# Lists without dates: an item is reported from the first issue of each uninterrupted listing.
DATELESS_LISTS = frozenset({"pl_mz"})


def listings(files: list[tuple[str, list[dict]]]) -> list[tuple[str, list[dict]]]:
    """One item per uninterrupted listing over consecutive issues; its signal date is the first issue's day."""
    prev: set[str] = set()
    start: dict[str, str] = {}
    out = []
    for day, items in files:
        ids = {it["item_id"] for it in items}
        new = []
        for it in items:
            if it["item_id"] not in prev:
                start[it["item_id"]] = day
            new.append({**it, "item_id": f"{it['item_id']}:{start[it['item_id']]}", "signal_date": start[it["item_id"]]})
        prev = ids
        out.append((day, new))
    return out


def load(archive, unique_files) -> list[dict]:
    """All items of all foreign sources in the archive, aggregated per source."""
    out = []
    for source, parse in PARSERS.items():
        files = []
        entries = sorted(unique_files(archive, source), key=lambda e: (file_day(e), e["path"]))
        if source in FULL_HISTORY:
            entries = entries[-1:]
        for e in entries:
            try:
                files.append((file_day(e), parse(archive.read(e["path"]))))
            except Exception:  # noqa: BLE001 - one unreadable file must not break the build
                continue
        out += aggregate(listings(files) if source in DATELESS_LISTS else files)
    from . import registers
    registers.fill(out, registers.load(archive, unique_files))
    return out
