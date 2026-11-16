"""Static website generator: derived SQLite database -> complete site directory (Jinja2 + inline SVG).

The site is built into a temporary sibling directory and then swapped in, so a failed run never
leaves a half-written site. All links are relative, so the site works under any path prefix.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import basg, fruehwarnung, metrics, status as archive_status
from .archive import Archive
from .timeline import Ep, d, de, events, mini_svg, status_class, timeline_svg

SITE_TITLE = "Lieferengpass-Radar"  # display name on the website; the code keeps its working title "Stockout Forecaster AT"
WEB = Path(__file__).parent / "web"
STALE_HOURS = archive_status.STALE_HOURS
STATUS_ORDER = ("Nicht verfügbar", "eingeschränkt verfügbar", "verfügbar gemäß §4 (1)", "verfügbar")
HIDDEN_FIELDS = {"Zulassungsinhaber_Tel"}  # never published
HIDDEN_SOURCES = frozenset({"bfarm"})  # foreign sources not shown (BfArM: only after written consent)
# Public website rules (public repo, documentation/DATENQUELLEN.md § 4), for the site only: HIDDEN_SOURCES and the register
# hints also feed the feature and prediction log (merkmale), which stays unchanged until the Go/No-Go on 30.04.2027.
SITE_HIDDEN_SOURCES = HIDDEN_SOURCES | {"fimea"}  # Fimea: until Fimea confirms the use
SITE_HOLDER_CHANGES = False  # register hint from the BASG announcements (MIA, mia_verl): until the BASG permits the use
FIELD_LABELS = {
    "PZN": "PZN",
    "Zulassungsnummer": "Zulassungsnummer",
    "Datum_Meldung": "Datum der Meldung",
    "Datum_letzte_Aenderung": "Datum der letzten Änderung",
    "Beginn_Vertriebseinschraenkung": "Beginn der Vertriebseinschränkung",
    "Datum_voraussichtliche_Wiederbelieferung": "Voraussichtliche Wiederbelieferung",
    "Bezeichnung_Arzneispezialitaet": "Bezeichnung der Arzneispezialität",
    "Status": "Status",
    "Staerke": "Stärke",
    "Unit": "Einheit",
    "ATCCodes": "ATC-Code",
    "Darreichungsform": "Darreichungsform",
    "Parallelexportverbot": "Parallelexportverbot",
    "Packungsgroesse": "Packungsgröße",
    "Packungseinheit": "Packungseinheit",
    "Packungscontainer": "Packungscontainer",
    "Packungsbeschreibung": "Packungsbeschreibung",
    "Melder": "Melder",
    "Zulassungsinhaber": "Zulassungsinhaber",
    "Grund": "Grund",
    "Wirkstoffe": "Wirkstoffe",
    "Mitteilung_Fachkreise": "Mitteilung an Fachkreise",
    "Rechtsgrundlage_Meldung": "Rechtsgrundlage der Meldung",
    "Hinweis_BASG": "Hinweis des BASG",
}
ATC1 = {
    "A": "Alimentäres System und Stoffwechsel",
    "B": "Blut und blutbildende Organe",
    "C": "Kardiovaskuläres System",
    "D": "Dermatika",
    "G": "Urogenitalsystem und Sexualhormone",
    "H": "Systemische Hormonpräparate (ohne Sexualhormone und Insuline)",
    "J": "Antiinfektiva zur systemischen Anwendung",
    "L": "Antineoplastische und immunmodulierende Mittel",
    "M": "Muskel- und Skelettsystem",
    "N": "Nervensystem",
    "P": "Antiparasitäre Mittel, Insektizide und Repellenzien",
    "R": "Respirationstrakt",
    "S": "Sinnesorgane",
    "V": "Varia",
    "Q": "Tierarzneimittel (ATCvet)",
    "?": "ohne ATC-Angabe",
}
# Foreign sources as shown on the method page (attribution and terms as found on 18.10.2026).
FOREIGN_SOURCES = [
    ("Italien", "AIFA, Elenco dei medicinali carenti", "aifa", "CC BY 4.0, Quelle AIFA"),
    ("Tschechien", "SÚKL, Hlášení o přerušení a obnovení dodávek (Open Data)", "sukl_cz", "Open-Data-Bedingungen SÚKL, Quelle SÚKL"),
    ("Slowakei", "ŠÚKL, Oznámenia o prerušení dodávok", "sukl_sk", "keine Bedingungen veröffentlicht"),
    ("Ungarn", "OGYÉI, Shortage-Liste", "ogyei", "keine Lizenz veröffentlicht"),
    ("Slowenien", "JAZMP, Seznam prenehanj in motenj", "jazmp", "Urheberrechtshinweis, keine offene Lizenz"),
    ("Belgien", "FAMHP, PharmaStatus", "famhp", "keine Lizenz veröffentlicht"),
    ("Spanien", "AEMPS, CIMA Problemas de suministro", "cima", "keine Lizenz veröffentlicht"),
    ("EU", "EMA, Medicine shortages (Output)", "ema", "Weiterverwendung mit Quellenangabe EMA"),
    ("USA", "FDA, openFDA Drug Shortages", "fda", "CC0 (gemeinfrei)"),
    ("Frankreich", "ANSM, Disponibilité des produits de santé (Export)", "ansm", "noch nicht geprüft"),
    ("Polen", "Gesundheitsministerium, Liste der von Nichtverfügbarkeit bedrohten Arzneimittel (Amtsblatt)", "pl_mz",
     "amtliches Dokument, nach Art. 4 des polnischen Urheberrechtsgesetzes nicht geschützt"),
]
START_SHORT = {"beginn": "Beginn laut BASG", "meldung": "Meldedatum laut BASG", "first_seen": "erstmals gesehen"}


def package_slug(key: str) -> str:
    """PZN for normal packages; `z-<hash>` for PZN-less keys (old files) to keep paths URL-safe."""
    return key if re.fullmatch(r"[0-9A-Za-z]+", key) else "z-" + hashlib.sha1(key.encode()).hexdigest()[:10]


def substance_slug(label: str) -> str:
    """Lowercase ASCII slug, e.g. ZOLPIDEM -> zolpidem, A + B -> a-b; long combinations shortened with a hash."""
    text = label.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "x"
    if len(slug) > 80:
        slug = slug[:60].rstrip("-") + "-" + hashlib.sha1(label.encode()).hexdigest()[:8]
    return slug


def _status_rank(s: str | None) -> int:
    return STATUS_ORDER.index(s) if s in STATUS_ORDER else (len(STATUS_ORDER) if s else len(STATUS_ORDER) + 1)


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=archive_status.VIENNA)


def _local(dt: datetime | None) -> str:
    return dt.astimezone(archive_status.VIENNA).strftime("%d.%m.%Y, %H:%M") if dt else "unbekannt"


class Data:
    """Everything the templates need, loaded once from the database."""

    def __init__(self, conn: sqlite3.Connection, ref: date | None):
        self.sid, latest_day = metrics.latest_snapshot(conn)
        self.ref = ref or latest_day
        self.m = metrics.collect(conn, self.ref)
        self.snapshots = [dict(r) for r in conn.execute("SELECT * FROM snapshots ORDER BY snapshot_id")]
        self.archive_days = sorted({date.fromisoformat(s["snapshot_date"]) for s in self.snapshots})
        self.meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        statuses, resupply = defaultdict(list), defaultdict(list)
        for r in conn.execute("SELECT * FROM episode_status ORDER BY episode_id, seq"):
            statuses[r["episode_id"]].append((r["status"], date.fromisoformat(r["first_seen"])))
        for r in conn.execute("SELECT * FROM episode_resupply ORDER BY episode_id, seq"):
            resupply[r["episode_id"]].append((r["announced"], date.fromisoformat(r["first_seen"])))
        self.eps: dict[str, list[Ep]] = defaultdict(list)
        self.ep_rows: dict[str, list[dict]] = defaultdict(list)
        for r in conn.execute("SELECT * FROM episodes ORDER BY package_key, seq_no"):
            self.ep_rows[r["package_key"]].append(dict(r))
            self.eps[r["package_key"]].append(
                Ep(
                    seq_no=r["seq_no"],
                    start=date.fromisoformat(r["start_date"]),
                    start_source=r["start_source"],
                    first_seen=date.fromisoformat(r["first_seen"]),
                    last_seen=date.fromisoformat(r["last_seen"]),
                    active=bool(r["active"]),
                    end_reason=r["end_reason"],
                    end_lower=d(r["end_lower"]),
                    end_upper=d(r["end_upper"]),
                    end_last_change=r["end_last_change"],
                    history_quality=r["history_quality"],
                    duration_min=r["duration_min_days"],
                    duration_max=r["duration_max_days"],
                    statuses=statuses[r["episode_id"]],
                    resupply=resupply[r["episode_id"]],
                )
            )
        self.listed: dict[str, list[date]] = defaultdict(list)
        self.latest_row: dict[str, dict] = {}
        sql = "SELECT sp.*, s.snapshot_date FROM snapshot_packages sp JOIN snapshots s USING (snapshot_id) ORDER BY sp.snapshot_id"
        for r in conn.execute(sql):
            self.listed[r["package_key"]].append(date.fromisoformat(r["snapshot_date"]))
            self.latest_row[r["package_key"]] = dict(r)
        overdue = {o["package_key"]: o for o in self.m["overdue"]}
        self.packages: dict[str, dict] = {}
        for r in conn.execute("SELECT * FROM packages ORDER BY package_key"):
            p = dict(r)
            key = p["package_key"]
            row = self.latest_row[key]
            current = row["snapshot_id"] == self.sid
            p.update(
                slug=package_slug(key),
                path=f"packung/{package_slug(key)}/",
                sub_path=f"wirkstoff/{substance_slug(p['substance'])}/" if p["substance"] else None,
                current_status=row["Status"] if current else None,
                announced=(row["Datum_voraussichtliche_Wiederbelieferung"] or None) if current else None,
                overdue=overdue.get(key),
                label=p["name"] or key,
            )
            self.packages[key] = p
        self.by_pzn = {p["pzn"].zfill(7): p for p in self.packages.values() if p["pzn"]}
        self._mini: dict[str, Markup] = {}

    def mini(self, key: str) -> Markup:
        if key not in self._mini:
            p = self.packages[key]
            self._mini[key] = Markup(mini_svg(self.eps.get(key, []), self.ref, p["announced"]))
        return self._mini[key]


def _duration_text(e: Ep, ref: date) -> str:
    if e.end_reason:
        if e.duration_min == e.duration_max:
            return f"{e.duration_min} Tage"
        return f"zwischen {e.duration_min} und {e.duration_max} Tagen"
    n = max((ref - e.start).days, 0)
    return f"mindestens {n} Tage (Beginn unbekannt, erstmals gesehen)" if e.start_source == "first_seen" else f"{n} Tage bis zum Stichtag"


def _end_text(e: Ep) -> str:
    if not e.end_reason:
        return "noch gemeldet"
    why = {"status": "Status „verfügbar“", "disappeared": "aus der Liste verschwunden", "rereported": "neu gemeldet"}.get(e.end_reason, e.end_reason)
    if e.end_upper == e.end_lower:
        return f"{de(e.end_upper)} ({why})"
    return f"zwischen {de(e.end_lower)} und {de(e.end_upper)} ({why})"


def _package_context(data: Data, key: str, fw: dict, links: dict) -> dict:
    p = data.packages[key]
    row = data.latest_row[key]
    eps = data.eps.get(key, [])
    official = [
        (FIELD_LABELS.get(f, f), row[f]) for f in basg.FIELDS if f not in HIDDEN_FIELDS and row.get(f) is not None
    ]
    label = f"Zeitleiste {p['label']}"
    episodes = []
    for e in eps:
        episodes.append(
            {
                "seq_no": e.seq_no,
                "start": f"{de(e.start)} ({START_SHORT.get(e.start_source, e.start_source)})",
                "end": _end_text(e),
                "duration": _duration_text(e, data.ref),
                "shifts": len(e.shifts()),
                "announced": e.resupply[-1][0] if e.resupply else None,
                "sparse": e.history_quality == "sparse",
                "active": not e.end_reason,
                "events": events(e, data.ref),
            }
        )
    return {
        "p": p,
        "official": official,
        "official_sid": row["snapshot_id"],
        "is_current": p["current_status"] is not None,
        "episodes": episodes,
        "sparse": any(e.history_quality == "sparse" for e in eps),
        "tl_wide": Markup(timeline_svg(eps, data.listed[key], data.archive_days, data.ref, 880, "tlw", label)),
        "tl_narrow": Markup(timeline_svg(eps, data.listed[key], data.archive_days, data.ref, 300, "tln", label)),
        "n_listed": len(data.listed[key]),
        "n_archive": len(data.archive_days),
        "listed_first": de(data.listed[key][0]),
        "listed_last": de(data.listed[key][-1]),
        "foreign": fruehwarnung.by_country(fw["items_by_atc"].get(p["atc5"], []), links.get((p["pzn"] or "").zfill(7))),
    }


def _week_rows(data: Data, entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        key = e["episode_id"].rsplit("#", 1)[0]
        p = data.packages[key]
        out.append({**e, "p": p, "start": d(e["start_date"]), "end_lower": d(e["end_lower"]), "end_upper": d(e["end_upper"])})
    return out


def _substances(data: Data) -> dict[str, dict]:
    subs: dict[str, dict] = {}
    for p in data.packages.values():
        if p["substance"]:
            s = subs.setdefault(p["substance"], {"label": p["substance"], "path": p["sub_path"], "packages": []})
            s["packages"].append(p)
    equiv = {s["substance"]: s for s in data.m["substances"]}
    for label, s in subs.items():
        s["packages"].sort(key=lambda p: (p["current_status"] is None, _status_rank(p["current_status"]), -(int(p["last_seen"].replace("-", ""))), p["label"]))
        s["current"] = sum(1 for p in s["packages"] if p["current_status"] is not None)
        s["active"] = sum(1 for p in s["packages"] if p["current_status"] in metrics.RESTRICTED)
        s["groups"] = equiv.get(label, {}).get("equivalence_groups", [])
        for g in s["groups"]:
            for u in g["unreported"]:
                u["p"] = data.by_pzn.get(u["pzn"])
    seen: dict[str, str] = {}
    for label in sorted(subs):  # disambiguate slug collisions deterministically
        path = subs[label]["path"]
        if path in seen.values():
            path = f"wirkstoff/{substance_slug(label)}-{hashlib.sha1(label.encode()).hexdigest()[:6]}/"
            subs[label]["path"] = path
            for p in subs[label]["packages"]:
                p["sub_path"] = path
        seen[label] = path
    return subs


def _letter(label: str) -> str:
    c = substance_slug(label)[:1].upper()
    return c if "A" <= c <= "Z" else "#"


def _substance_paths(subs: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """ATC5 -> (substance label, page path), using the substance most packages with that ATC5 have."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for s in subs.values():
        for p in s["packages"]:
            if p["atc5"]:
                votes[p["atc5"]][s["label"]] += 1
    return {atc: (c.most_common(1)[0][0], subs[c.most_common(1)[0][0]]["path"]) for atc, c in votes.items()}


def _links(conn: sqlite3.Connection, pzns: set[str]) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for item_id, pzn, strength, holder in conn.execute("SELECT item_id, pzn, strength_match, holder_match FROM foreign_links"):
        if pzn in pzns:
            out[pzn][item_id] = {"strength_match": strength, "holder_match": holder}
    return out


def generate(db_path: Path, out_dir: Path, ref: date | None = None, archive: Archive | None = None, now: datetime | None = None) -> dict:
    """Generate the complete site into `out_dir` (atomic swap). Return page counts."""
    now = now or datetime.now(timezone.utc)
    conn = metrics.connect(Path(db_path))
    try:
        data = Data(conn, ref)
        subs = _substances(data)
        fw = fruehwarnung.build(conn, SITE_HIDDEN_SOURCES, _substance_paths(subs), archive,
                                Path(db_path).parent / "json" / "rueckblick.json", data.ref)
        fw["register"]["holder_data"] = SITE_HOLDER_CHANGES
        links = _links(conn, set(data.by_pzn))
    finally:
        conn.close()
    for s in subs.values():
        atcs = {p["atc5"] for p in s["packages"] if p["atc5"]}
        s["atc5s"] = sorted(atcs)
        s["foreign"] = fruehwarnung.by_country([it for a in sorted(atcs) for it in fw["items_by_atc"].get(a, [])])
    coverage = archive_status.collect(archive, None, now) if archive is not None and archive.manifest.exists() else None
    basg_ok = _ts(coverage["sources"]["basg"]["last_ok"]) if coverage else None
    data_time = basg_ok or _ts(data.sid)
    stale = data_time is None or now - data_time > timedelta(hours=STALE_HOURS)

    env = Environment(loader=FileSystemLoader(WEB / "templates"), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["de"] = lambda v: de(v if isinstance(v, date) else d(v))
    env.filters["sclass"] = status_class
    env.filters["pct"] = lambda v: f"{v * 100:.1f} %".replace(".", ",") if v is not None else "–"
    env.globals.update(
        SITE_TITLE=SITE_TITLE,
        sid=data.sid,
        ref=data.ref,
        generated=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        generated_local=_local(now),
        basg_fetch=(basg_ok.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if basg_ok else ""),
        basg_fetch_local=_local(basg_ok) if basg_ok else "unbekannt",
        stale=stale,
        stale_hours=STALE_HOURS,
        asp_version=data.meta.get("asp_version"),
        mini=data.mini,
        START_SHORT=START_SHORT,
        daily_start=coverage["basg_first_live_day"] if coverage else None,
        TIERS=fruehwarnung.TIERS,
        COUNTRY_NAMES=fruehwarnung.COUNTRY_NAMES,
        fw_counts=fw["counts"],
    )

    out_dir = Path(out_dir).resolve()
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}-", dir=out_dir.parent))
    counts: dict[str, int] = defaultdict(int)

    def write(rel: str, template: str, kind: str, **ctx) -> None:
        depth = rel.count("/") + 1 if rel else 0
        target = tmp / rel / "index.html" if rel else tmp / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(env.get_template(template).render(root="../" * depth, **ctx), encoding="utf-8")
        counts[kind] += 1

    try:
        shutil.copytree(WEB / "assets", tmp / "assets")
        sit = data.m["situation"]
        status_rows = sorted(sit["by_status"].items(), key=lambda kv: _status_rank(kv[0]))
        atc_rows = sorted(((k, ATC1.get(k, k), v) for k, v in sit["active_by_atc1"].items()), key=lambda r: (-r[2], r[0]))
        week = {
            "from": d(data.m["week"]["from"]),
            "to": d(data.m["week"]["to"]),
            "new": _week_rows(data, data.m["week"]["new"]),
            "ended": _week_rows(data, data.m["week"]["ended"]),
        }
        overdue = [{**o, "p": data.packages[o["package_key"]]} for o in data.m["overdue"]]

        write("", "index.html", "start", sit=sit, status_rows=status_rows, atc_rows=atc_rows, week=week, n_overdue=len(overdue))
        for key in data.packages:
            write(data.packages[key]["path"].rstrip("/"), "package.html", "packung", **_package_context(data, key, fw, links))
        for s in subs.values():
            write(s["path"].rstrip("/"), "substance.html", "wirkstoff", s=s)
        letters: dict[str, list] = defaultdict(list)
        for label in sorted(subs, key=substance_slug):
            letters[_letter(label)].append(subs[label])
        write("wirkstoffe", "substances.html", "liste", letters=sorted(letters.items()))
        write("ueberfaellig", "overdue.html", "liste", overdue=overdue)
        write("fruehwarnung", "fruehwarnung.html", "liste", fw=fw)
        write("woche", "week.html", "liste", week=week)
        write("methodik", "method.html", "text", coverage=coverage, snapshots=data.snapshots, n_complete=sum(s["complete"] for s in data.snapshots),
              fw=fw, foreign_sources=[(c, title, fruehwarnung.source_url(key), terms) for c, title, key, terms in FOREIGN_SOURCES
                                               if key not in SITE_HIDDEN_SOURCES])
        write("impressum", "impressum.html", "text")
        write("datenschutz", "datenschutz.html", "text")
        index = {
            "p": [[p["pzn"] or "", p["label"], p["substance"] or "", p["path"], p["current_status"] or ""] for p in data.packages.values()],
            "s": [[s["label"], s["path"], len(s["packages"])] for s in subs.values()],
        }
        (tmp / "search-index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.chmod(0o755)
        old = None
        if out_dir.exists():
            old = out_dir.with_name(f".{out_dir.name}-old-{now.strftime('%Y%m%d%H%M%S')}")
            out_dir.rename(old)
        tmp.rename(out_dir)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return dict(counts)
