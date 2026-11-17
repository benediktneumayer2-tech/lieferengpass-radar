"""Archive health: last fetch per source, missing BASG days, mirror state."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .archive import SOURCES, Archive
from .mirror import STATE, missing_files

VIENNA = ZoneInfo("Europe/Vienna")
STALE_HOURS = 36
MIRROR_OFF = "Kopie: ausgeschaltet (STOCKOUT_MIRROR leer oder --no-mirror)"
BASG_READY_HOUR = 6  # the BASG file is produced at 02:00; expect today's version from 06:00 on


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def missing_basg_days(entries: list[dict], now: datetime) -> tuple[date | None, list[date]]:
    """Days since the first live BASG version for which no live version with that producedOn date exists."""
    days = {
        date.fromisoformat(e["produced_on"][:10])
        for e in entries
        if e.get("source") == "basg" and e.get("origin") == "live" and e.get("ok") and e.get("produced_on")
    }
    if not days:
        return None, []
    local = now.astimezone(VIENNA)
    last = local.date() if local.hour >= BASG_READY_HOUR else local.date() - timedelta(days=1)
    first = min(days)
    gaps = []
    d = first
    while d <= last:
        if d not in days:
            gaps.append(d)
        d += timedelta(days=1)
    return first, gaps


def collect(archive: Archive, mirror_root: Path | None, now: datetime) -> dict:
    entries = archive.entries()
    sources, watched = {}, {}  # watched sources in their own block: the website lists only `sources`
    warnings = []
    week_ago = now - timedelta(days=7)
    for name, source in SOURCES.items():
        own = [e for e in entries if e.get("source") == name and e.get("origin") == "live"]
        ok = [e for e in own if e.get("ok")]
        new = [e for e in ok if not e.get("duplicate")]
        failures = [e for e in own if not e.get("ok") and _parse(e["recorded_at"]) >= week_ago]
        last_ok = max((e["recorded_at"] for e in ok), default=None)
        (watched if source.watch else sources)[name] = {
            "last_ok": last_ok,
            "last_new_version": max((e.get("produced_on") or e.get("fetched_at") for e in new), default=None),
            "versions": len(new),
            "failures_7d": len(failures),
            "last_error": failures[-1]["error"] if failures else None,
        }
        limit = STALE_HOURS + source.min_hours if source.watch else STALE_HOURS
        if last_ok is None:
            warnings.append(f"{name}: noch kein erfolgreicher Abruf")
        elif now - _parse(last_ok) > timedelta(hours=limit):
            warnings.append(f"{name}: letzter erfolgreicher Abruf älter als {limit:g} h")
        recent_warn = [w for e in new[-3:] for w in e.get("warnings") or []]
        if recent_warn:
            warnings.append(f"{name}: Inhaltswarnungen {sorted(set(recent_warn))}")

    first, gaps = missing_basg_days(entries, now)
    if gaps:
        warnings.append(f"basg: {len(gaps)} fehlende Tage seit {first}")
    legacy = sorted({e["source"] + ":" + e["origin"] for e in entries if e.get("origin") not in (None, "live")})

    mirror = None
    if mirror_root is not None:
        state_path = archive.root / STATE
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        missing = missing_files(archive.root, mirror_root) if Path(mirror_root).exists() else None
        mirror = {
            "path": str(mirror_root),
            "last_ok": state.get("last_ok"),
            "last_error": state.get("last_error"),
            "missing_files": len(missing) if missing is not None else None,
        }
        if missing is None:
            warnings.append("Kopie: Zielordner nicht erreichbar")
        elif missing:
            warnings.append(f"Kopie: {len(missing)} Dateien fehlen")

    files = [p for p in archive.root.rglob("*.gz")]
    return {
        "archive": str(archive.root),
        "files": len(files),
        "megabytes": round(sum(p.stat().st_size for p in files) / 1e6, 1),
        "sources": sources,
        "watched": watched,
        "basg_first_live_day": first.isoformat() if first else None,
        "basg_missing_days": [d.isoformat() for d in gaps],
        "history_imports": legacy,
        "mirror": mirror,
        "warnings": warnings,
    }


def render(report: dict) -> str:
    lines = [f"Archiv: {report['archive']} ({report['files']} Dateien, {report['megabytes']} MB)"]
    for block in ("sources", "watched"):
        if block == "watched" and report.get(block):
            lines.append("Beobachtete Quellen (nur roh archiviert, Ausfall nur Warnung):")
        for name, s in (report.get(block) or {}).items():
            lines.append(
                f"  {name:<8} letzter Erfolg: {s['last_ok'] or '–'} | neueste Fassung: {s['last_new_version'] or '–'}"
                f" | Fassungen: {s['versions']} | Fehlversuche 7 Tage: {s['failures_7d']}"
            )
    gaps = report["basg_missing_days"]
    lines.append(
        f"BASG-Tage seit Archivbeginn ({report['basg_first_live_day'] or '–'}): "
        + (f"{len(gaps)} fehlen: {', '.join(gaps[:10])}{' …' if len(gaps) > 10 else ''}" if gaps else "lückenlos")
    )
    if report["history_imports"]:
        lines.append(f"Vorgeschichte: {', '.join(report['history_imports'])}")
    m = report["mirror"]
    if m:
        lines.append(
            f"Kopie {m['path']}: zuletzt ok {m['last_ok'] or '–'}, fehlende Dateien: "
            f"{m['missing_files'] if m['missing_files'] is not None else 'unbekannt'}"
        )
    else:
        lines.append(MIRROR_OFF)
    lines.append("Warnungen: " + ("; ".join(report["warnings"]) if report["warnings"] else "keine"))
    return "\n".join(lines)
