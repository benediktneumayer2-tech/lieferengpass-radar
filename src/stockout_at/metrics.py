"""Website metrics from the derived database, exportable as JSON for the static-site generator.

Official BASG fields are passed through verbatim; everything else is "eigene Auswertung".
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

RESTRICTED = ("Nicht verfügbar", "eingeschränkt verfügbar")  # active shortage statuses
DURATION_BINS = ((0, 14), (15, 30), (31, 60), (61, 90), (91, 180), (181, 365), (366, None))


def _d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def latest_snapshot(conn: sqlite3.Connection) -> tuple[str, date]:
    sid = conn.execute("SELECT max(snapshot_id) FROM snapshots").fetchone()[0]
    return sid, date.fromisoformat(sid[:10])


def _current_rows(conn: sqlite3.Connection, sid: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT sp.*, p.substance, p.atc5, p.atc3, e.episode_id, e.start_date, e.n_shifts, e.history_quality
           FROM snapshot_packages sp
           JOIN packages p USING (package_key)
           LEFT JOIN episodes e ON e.package_key = sp.package_key AND e.active = 1
           WHERE sp.snapshot_id = ? ORDER BY sp.package_key""",
        (sid,),
    ).fetchall()


def situation(conn: sqlite3.Connection, sid: str) -> dict:
    """Current situation: counts by status and by ATC group (level 1 and 3) for active shortages."""
    rows = _current_rows(conn, sid)
    by_status = Counter(r["Status"] for r in rows)
    active = [r for r in rows if r["Status"] in RESTRICTED]
    atc1 = Counter((r["atc3"] or "?")[:1] for r in active)
    atc3 = Counter(r["atc3"] or "?" for r in active)
    return {
        "snapshot": sid,
        "packages": len(rows),
        "by_status": dict(sorted(by_status.items())),
        "active": len(active),
        "active_with_resupply_date": sum(1 for r in active if _d(r["Datum_voraussichtliche_Wiederbelieferung"])),
        "active_by_atc1": dict(sorted(atc1.items())),
        "active_by_atc3": dict(sorted(atc3.items())),
    }


def overdue(conn: sqlite3.Connection, sid: str, ref: date) -> list[dict]:
    """Active packages whose currently announced resupply date lies before `ref`."""
    out = []
    for r in _current_rows(conn, sid):
        announced = _d(r["Datum_voraussichtliche_Wiederbelieferung"])
        if r["Status"] in RESTRICTED and announced and announced < ref:
            out.append(
                {
                    "package_key": r["package_key"],
                    "pzn": r["PZN"],
                    "name": r["Bezeichnung_Arzneispezialitaet"],
                    "status": r["Status"],
                    "announced": r["Datum_voraussichtliche_Wiederbelieferung"],
                    "days_overdue": (ref - announced).days,
                    "substance": r["substance"],
                    "atc5": r["atc5"],
                    "episode_id": r["episode_id"],
                    "start_date": r["start_date"],
                    "n_shifts": r["n_shifts"],
                    "history_quality": r["history_quality"],
                }
            )
    return sorted(out, key=lambda x: (-x["days_overdue"], x["package_key"]))


def _ep_brief(r: sqlite3.Row) -> dict:
    keys = ("episode_id", "pzn", "name", "substance", "status", "start_date", "start_source", "first_seen",
            "end_reason", "end_lower", "end_upper", "end_interval_censored", "history_quality")
    return {k: r[k] for k in keys}


def week(conn: sqlite3.Connection, ref: date, days: int = 7) -> dict:
    """New episodes (start in window) and ended episodes (end_upper in window) of the last `days` days."""
    lo, hi = (ref - timedelta(days=days - 1)).isoformat(), ref.isoformat()
    new = conn.execute(
        "SELECT * FROM episodes WHERE start_date BETWEEN ? AND ? ORDER BY start_date DESC, episode_id", (lo, hi)
    ).fetchall()
    ended = conn.execute(
        "SELECT * FROM episodes WHERE end_upper BETWEEN ? AND ? ORDER BY end_upper DESC, episode_id", (lo, hi)
    ).fetchall()
    return {"from": lo, "to": hi, "new": [_ep_brief(r) for r in new], "ended": [_ep_brief(r) for r in ended]}


def durations(conn: sqlite3.Connection) -> dict:
    """Duration distribution of ended episodes; censored intervals are binned by their midpoint."""
    bins: dict[str, Counter] = defaultdict(Counter)
    sql = "SELECT duration_min_days, duration_max_days, end_interval_censored FROM episodes WHERE active = 0"
    for r in conn.execute(sql):
        days = (r[0] + r[1]) // 2
        label = next(f"{lo}-{hi}" if hi else f">{lo - 1}" for lo, hi in DURATION_BINS if hi is None or days <= hi)
        bins[label]["interval_censored" if r[2] else "exact"] += 1
    order = [f"{lo}-{hi}" if hi else f">{lo - 1}" for lo, hi in DURATION_BINS]
    return {"bins": [{"days": b, **{k: bins[b][k] for k in ("exact", "interval_censored")}} for b in order]}


def substances(conn: sqlite3.Connection, sid: str) -> list[dict]:
    """Per base substance: current reports, plus ASP denominator for the reported packages' equivalence groups.

    Equivalence = same normalised ASP substances, strength and dosage form. A hint for enquiries,
    explicitly no substitution recommendation.
    """
    asp = {r["pzn"]: dict(r) for r in conn.execute("SELECT * FROM asp_packages")}
    groups: dict[str, list[dict]] = defaultdict(list)
    for a in asp.values():
        if a["equiv_key"] and a["valid"]:
            groups[a["equiv_key"]].append(a)
    current = _current_rows(conn, sid)
    listed = {r["PZN"].zfill(7): r["Status"] for r in current if r["PZN"]}
    reported = {pzn for pzn, status in listed.items() if status != "verfügbar"}
    rows = [r for r in current if r["substance"]]
    by_sub: dict[str, list] = defaultdict(list)
    for r in rows:
        by_sub[r["substance"]].append(r)
    out = []
    for sub in sorted(by_sub):
        items, eq = by_sub[sub], {}
        for r in items:
            a = asp.get((r["PZN"] or "").zfill(7)) if r["PZN"] else None
            key = a["equiv_key"] if a else None
            if key and key not in eq and key in groups:
                members = groups[key]
                eq[key] = {
                    "equiv_key": key,
                    "authorised": len(members),
                    "reported": sum(1 for m in members if m["pzn"] in reported),
                    "unreported": [
                        {
                            "pzn": m["pzn"],
                            "name": m["name"],
                            "inhaber": m["inhaber"],
                            "lieferbar": bool(m["lieferbar"]),  # ASP flag, as delivered
                            "basg_status": listed.get(m["pzn"]),  # e.g. still listed as "verfügbar"
                        }
                        for m in sorted(members, key=lambda m: m["pzn"])
                        if m["pzn"] not in reported
                    ],
                }
        out.append(
            {
                "substance": sub,
                "atc5": sorted({r["atc5"] for r in items if r["atc5"]}),
                "by_status": dict(sorted(Counter(r["Status"] for r in items).items())),
                "packages": [{"pzn": r["PZN"], "name": r["Bezeichnung_Arzneispezialitaet"], "status": r["Status"]} for r in items],
                "equivalence_groups": [eq[k] for k in sorted(eq)],
            }
        )
    return out


def collect(conn: sqlite3.Connection, ref: date | None = None) -> dict:
    sid, latest = latest_snapshot(conn)
    ref = ref or latest
    over = overdue(conn, sid, ref)
    sit = situation(conn, sid)
    sit.update(reference_date=ref.isoformat(), overdue=len(over))
    return {
        "situation": sit,
        "overdue": over,
        "week": week(conn, ref),
        "durations": durations(conn),
        "substances": substances(conn, sid),
    }


def export_json(conn: sqlite3.Connection, out_dir: Path, ref: date | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in collect(conn, ref).items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        paths.append(path)
    return paths
