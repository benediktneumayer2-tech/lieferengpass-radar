"""Rebuild the derived SQLite database completely and deterministically from the raw archive.

The database is disposable: same archive -> same table contents. It is written to a temp
file and atomically replaces the old one. No wall-clock values are stored.
"""
from __future__ import annotations

import gzip
import os
import sqlite3
from datetime import date
from pathlib import Path

from . import asp, basg, foreign
from .archive import Archive
from .episodes import Episode, SnapshotView, derive
from .substances import atc_groups, base_substance, normalise, split_components, substance_label

FIELD_COLS = ", ".join(f'"{f}" TEXT' for f in basg.FIELDS)

SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE snapshots (
    snapshot_id TEXT PRIMARY KEY,      -- BASG producedOn, verbatim
    snapshot_date TEXT NOT NULL,
    path TEXT NOT NULL, sha256 TEXT, origin TEXT,
    complete INTEGER NOT NULL,         -- 0 = truncated capture: presence evidence only
    n_packages INTEGER NOT NULL, parse_error TEXT
);
-- One row per (snapshot, package) with all official fields verbatim (None = element absent).
CREATE TABLE snapshot_packages (
    snapshot_id TEXT NOT NULL, package_key TEXT NOT NULL, {FIELD_COLS}, extra TEXT,
    PRIMARY KEY (snapshot_id, package_key)
);
CREATE TABLE packages (
    package_key TEXT PRIMARY KEY, pzn TEXT, zulassungsnummer TEXT, name TEXT, wirkstoffe TEXT,
    substance TEXT, atc5 TEXT, atc3 TEXT, darreichungsform TEXT, staerke TEXT,
    first_seen TEXT, last_seen TEXT, n_snapshots INTEGER, n_episodes INTEGER, in_asp INTEGER
);
CREATE TABLE episodes (
    episode_id TEXT PRIMARY KEY, package_key TEXT NOT NULL, seq_no INTEGER NOT NULL, pzn TEXT,
    start_date TEXT NOT NULL, start_source TEXT NOT NULL,
    first_seen TEXT NOT NULL, first_snapshot TEXT NOT NULL,
    last_seen TEXT NOT NULL, last_snapshot TEXT NOT NULL, last_listed TEXT,
    status TEXT, resupply_date TEXT, n_shifts INTEGER NOT NULL,
    end_reason TEXT, end_lower TEXT, end_upper TEXT, end_last_change TEXT, end_report_date TEXT,
    end_interval_censored INTEGER NOT NULL, history_quality TEXT NOT NULL, active INTEGER NOT NULL,
    duration_min_days INTEGER, duration_max_days INTEGER,
    name TEXT, substance TEXT, atc5 TEXT, atc3 TEXT, grund TEXT, zulassungsinhaber TEXT
);
CREATE TABLE episode_status (episode_id TEXT, seq INTEGER, status TEXT, first_seen TEXT, PRIMARY KEY (episode_id, seq));
CREATE TABLE episode_resupply (episode_id TEXT, seq INTEGER, announced TEXT, first_seen TEXT, PRIMARY KEY (episode_id, seq));
CREATE TABLE substance_map (component TEXT PRIMARY KEY, base TEXT NOT NULL);
CREATE TABLE asp_packages (
    pzn TEXT PRIMARY KEY, name TEXT, approval_name TEXT, zulassungsnummer TEXT, zulassungsstatus TEXT,
    valid INTEGER, lieferbar INTEGER, inhaber TEXT, atc TEXT, ingredients TEXT, substances TEXT,
    form TEXT, size TEXT, equiv_key TEXT
);
-- Foreign shortage reports (one row per report and product), aggregated over all archived files.
CREATE TABLE foreign_items (
    item_id TEXT PRIMARY KEY, source TEXT NOT NULL, country TEXT NOT NULL, report_id TEXT NOT NULL,
    product TEXT, substances TEXT, atc5 TEXT, atc_method TEXT, strength TEXT, form TEXT, holder TEXT,
    signal_date TEXT, start_date TEXT, expected_end TEXT, end_date TEXT, reason TEXT, status TEXT,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, n_files INTEGER NOT NULL, still_listed INTEGER NOT NULL,
    native_ids TEXT
);
-- Austrian ASP packages with the same ATC5 as a foreign item (+ strength / holder agreement).
CREATE TABLE foreign_links (
    item_id TEXT NOT NULL, pzn TEXT NOT NULL, strength_match INTEGER NOT NULL, holder_match INTEGER NOT NULL,
    PRIMARY KEY (item_id, pzn)
);
CREATE INDEX idx_sp_key ON snapshot_packages (package_key);
CREATE INDEX idx_fi_atc ON foreign_items (atc5);
CREATE INDEX idx_ep_key ON episodes (package_key);
CREATE INDEX idx_asp_equiv ON asp_packages (equiv_key);
"""


def _unique_files(archive: Archive, source: str) -> list[dict]:
    """Manifest entries with a stored file, one per distinct path, in path order."""
    seen: dict[str, dict] = {}
    for e in archive.entries():
        if e.get("source") == source and e.get("ok") and e.get("path") and e["path"] not in seen:
            seen[e["path"]] = e
    return [seen[p] for p in sorted(seen)]


def load_snapshots(archive: Archive) -> tuple[list[dict], list[SnapshotView], dict[str, dict]]:
    meta_rows, views, by_id = [], [], {}
    for e in _unique_files(archive, "basg"):
        snap = basg.parse(archive.read(e["path"]))
        sid = snap.produced_on or e.get("produced_on")
        if not sid or sid in by_id:
            continue  # unreadable or same producedOn twice: keep the first (path order)
        rows = {}
        for r in snap.packages:
            rows.setdefault(basg.package_key(r), r)
        by_id[sid] = rows
        meta_rows.append(
            dict(
                snapshot_id=sid,
                snapshot_date=sid[:10],
                path=e["path"],
                sha256=e.get("sha256"),
                origin=e.get("origin"),
                complete=int(snap.complete),
                n_packages=len(rows),
                parse_error=snap.error,
            )
        )
    meta_rows.sort(key=lambda m: m["snapshot_id"])
    for m in meta_rows:
        views.append(SnapshotView(m["snapshot_id"], date.fromisoformat(m["snapshot_date"]), bool(m["complete"]), by_id[m["snapshot_id"]]))
    return meta_rows, views, by_id


def load_asp(archive: Archive) -> tuple[str | None, str | None, list[dict]]:
    """Parse the latest ASP version (by file date, then capture time)."""
    files = _unique_files(archive, "asp")
    if not files:
        return None, None, []
    latest = max(files, key=lambda e: (Path(e["path"]).name[:10], e.get("captured_at") or "", e["path"]))
    with gzip.open(archive.root / latest["path"]) as fh:
        version, rows = asp.parse(fh)
    return latest["path"], version, rows


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _episode_row(ep: Episode, row: dict, asp_by_pzn: dict, latest_day: date) -> dict:
    pzn = row.get("PZN") or ""
    atc5, atc3 = atc_groups(row.get("ATCCodes") or asp_by_pzn.get(pzn.zfill(7), {}).get("atc"))
    end = ep.end_upper if ep.ended else latest_day
    lower = ep.end_lower if ep.ended else latest_day
    return dict(
        episode_id=f"{ep.package_key}#{ep.seq_no}",
        package_key=ep.package_key,
        seq_no=ep.seq_no,
        pzn=pzn,
        start_date=_iso(ep.start_date),
        start_source=ep.start_source,
        first_seen=_iso(ep.first_seen),
        first_snapshot=ep.first_snapshot,
        last_seen=_iso(ep.last_seen),
        last_snapshot=ep.last_snapshot,
        last_listed=_iso(ep.last_listed),
        status=ep.statuses[-1][0] if ep.statuses else None,
        resupply_date=ep.resupply[-1][0] if ep.resupply else None,
        n_shifts=ep.n_shifts,
        end_reason=ep.end_reason,
        end_lower=_iso(ep.end_lower),
        end_upper=_iso(ep.end_upper),
        end_last_change=ep.end_last_change,
        end_report_date=ep.end_report_date,
        end_interval_censored=int(ep.end_interval_censored),
        history_quality=ep.history_quality,
        active=int(not ep.ended),
        duration_min_days=max((lower - ep.start_date).days, 0),
        duration_max_days=max((end - ep.start_date).days, 0),
        name=row.get("Bezeichnung_Arzneispezialitaet"),
        substance=substance_label(normalise(row.get("Wirkstoffe"))) or None,
        atc5=atc5,
        atc3=atc3,
        grund=row.get("Grund"),
        zulassungsinhaber=row.get("Zulassungsinhaber"),
    )


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    sql = f'INSERT INTO {table} ({", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({", ".join("?" * len(cols))})'
    conn.executemany(sql, ([r[c] for c in cols] for r in rows))


def build(archive: Archive, db_path: Path) -> dict:
    """Rebuild `db_path` from the archive; return row counts per table."""
    meta_rows, views, by_id = load_snapshots(archive)
    asp_path, asp_version, asp_rows = load_asp(archive)
    asp_by_pzn = {r["pzn"]: r for r in asp_rows}
    episodes = derive(views)
    f_items = foreign.load(archive, _unique_files)
    f_links = foreign.link(f_items, asp_rows)
    f_cols = ("item_id source country report_id product substances atc5 atc_method strength form holder signal_date "
              "start_date expected_end end_date reason status first_seen last_seen n_files still_listed native_ids").split()
    f_rows = [{c: it.get(c) for c in f_cols} for it in f_items]
    latest_day = views[-1].day if views else date.min

    snap_rows, components, packages = [], set(), {}
    for m in meta_rows:
        sid = m["snapshot_id"]
        for key in sorted(by_id[sid]):
            r = by_id[sid][key]
            snap_rows.append({"snapshot_id": sid, "package_key": key, **{f: r.get(f) for f in basg.FIELDS}, "extra": r["extra"]})
            components.update(c.upper() for c in split_components(r.get("Wirkstoffe")))
            p = packages.setdefault(key, {"first_seen": m["snapshot_date"], "n_snapshots": 0, "row": r})
            p.update(last_seen=m["snapshot_date"], row=r)
            p["n_snapshots"] += 1

    ep_rows, st_rows, rs_rows, n_eps = [], [], [], {}
    for ep in sorted(episodes, key=lambda e: (e.package_key, e.seq_no)):
        row = by_id[ep.last_snapshot][ep.package_key]
        er = _episode_row(ep, row, asp_by_pzn, latest_day)
        ep_rows.append(er)
        n_eps[ep.package_key] = ep.seq_no
        st_rows += [dict(episode_id=er["episode_id"], seq=i, status=s, first_seen=_iso(d)) for i, (s, d) in enumerate(ep.statuses, 1)]
        rs_rows += [dict(episode_id=er["episode_id"], seq=i, announced=a, first_seen=_iso(d)) for i, (a, d) in enumerate(ep.resupply, 1)]

    pkg_rows = []
    for key in sorted(packages):
        p, r = packages[key], packages[key]["row"]
        pzn = r.get("PZN") or ""
        atc5, atc3 = atc_groups(r.get("ATCCodes") or asp_by_pzn.get(pzn.zfill(7), {}).get("atc"))
        pkg_rows.append(
            dict(
                package_key=key,
                pzn=pzn,
                zulassungsnummer=r.get("Zulassungsnummer"),
                name=r.get("Bezeichnung_Arzneispezialitaet"),
                wirkstoffe=r.get("Wirkstoffe"),
                substance=substance_label(normalise(r.get("Wirkstoffe"))) or None,
                atc5=atc5,
                atc3=atc3,
                darreichungsform=r.get("Darreichungsform"),
                staerke=" ".join(x for x in (r.get("Staerke"), r.get("Unit")) if x) or None,
                first_seen=p["first_seen"],
                last_seen=p["last_seen"],
                n_snapshots=p["n_snapshots"],
                n_episodes=n_eps.get(key, 0),
                in_asp=int(bool(pzn) and pzn.zfill(7) in asp_by_pzn),
            )
        )

    meta = {
        "latest_snapshot": meta_rows[-1]["snapshot_id"] if meta_rows else None,
        "n_basg_files": str(len(meta_rows)),
        "asp_path": asp_path,
        "asp_version": asp_version,
        "end_statuses": "verfügbar",
        "packages_without_episode": str(sum(1 for r in pkg_rows if not r["n_episodes"])),
    }

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        _insert(conn, "meta", [{"key": k, "value": v} for k, v in sorted(meta.items())])
        _insert(conn, "snapshots", meta_rows)
        _insert(conn, "snapshot_packages", snap_rows)
        _insert(conn, "packages", pkg_rows)
        _insert(conn, "episodes", ep_rows)
        _insert(conn, "episode_status", st_rows)
        _insert(conn, "episode_resupply", rs_rows)
        _insert(conn, "substance_map", [{"component": c, "base": base_substance(c)} for c in sorted(components)])
        _insert(conn, "asp_packages", sorted(asp_rows, key=lambda r: r["pzn"]))
        _insert(conn, "foreign_items", f_rows)
        _insert(conn, "foreign_links", sorted(f_links, key=lambda r: (r["item_id"], r["pzn"])))
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, db_path)
    return {
        "snapshots": len(meta_rows),
        "snapshot_packages": len(snap_rows),
        "packages": len(pkg_rows),
        "episodes": len(ep_rows),
        "episode_status": len(st_rows),
        "episode_resupply": len(rs_rows),
        "substance_map": len(components),
        "asp_packages": len(asp_rows),
        "foreign_items": len(f_rows),
        "foreign_links": len(f_links),
    }
