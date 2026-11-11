"""Derive shortage episodes per package from an ordered series of BASG snapshots.

Rules (adapted to what the real archive shows):
- An episode opens at the first row in a non-end status of a listing. It starts at
  `Beginn_Vertriebseinschraenkung`, else `Datum_Meldung`, else the first sighting; a start not
  after the end of the package's previous episode falls back to the first sighting.
- A row in an end status opens an (already ended) episode only if it carries `Beginn_...`
  (an ended restriction seen for the first time). Beginn-less "verfügbar" rows at the start of a
  listing open nothing: they are pre-announcements (e.g. PZN 5509056: listed "verfügbar" from
  2024-04-16, restriction began 2024-11-27) or restrictions that began and ended unseen between
  sparse snapshots - both without a known start. They stay visible in the snapshot table.
- An episode ends at the first snapshot in an end status, or when the package is missing from a
  *complete* snapshot (interval between last seen and first missing). Truncated snapshots
  (incomplete Wayback captures) count as evidence of presence, never of absence.
- A new episode also starts when a row carrying `Beginn_...` shows a report newer than our last
  sighting (`Datum_Meldung` or `Beginn_...` later than the previous observation); the old
  episode then ended unseen in between (`end_reason='rereported'`).
- Status "verfügbar gemäß §4 (1)" is NOT an end status. § 4 (1) of the Verordnung über die
  Sicherstellung der Arzneimittelversorgung (BGBl. II Nr. 30/2020, RIS Gesetzesnummer 20010928)
  covers packages that BASG lists on its own initiative because patient demand is not met
  "obwohl nach Angaben des Zulassungsinhabers keine Einschränkung der Vertriebsfähigkeit
  vorliegt"; § 4 (2) removes them from the list once that ends. The listing is thus an ongoing
  supply problem; the archive carries "§4 (1) ..." as Rechtsgrundlage_Meldung for them.
- Each change of the announced resupply date (non-empty values) counts as a shift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

END_STATUSES = frozenset({"verfügbar"})


@dataclass
class SnapshotView:
    snapshot_id: str
    day: date
    complete: bool
    rows: dict[str, dict]  # package_key -> official row


@dataclass
class Episode:
    package_key: str
    seq_no: int
    start_date: date
    start_source: str  # beginn | meldung | first_seen
    first_seen: date
    first_snapshot: str
    last_seen: date  # last observation before the end (or latest, if still open)
    last_snapshot: str  # snapshot of that observation, used for descriptive fields
    statuses: list[tuple[str, date]] = field(default_factory=list)
    resupply: list[tuple[str, date]] = field(default_factory=list)
    end_reason: str | None = None  # status | disappeared | rereported
    end_lower: date | None = None
    end_upper: date | None = None
    end_last_change: str | None = None  # Datum_letzte_Aenderung of the first end-status row, verbatim
    end_report_date: str | None = None  # Datum_Meldung of a Beginn-less first end-status row, verbatim
    start_daily: bool = False
    last_listed: date | None = None

    @property
    def ended(self) -> bool:
        return self.end_reason is not None

    @property
    def end_interval_censored(self) -> bool:
        return self.ended and (self.end_upper - self.end_lower).days > 1

    @property
    def history_quality(self) -> str:
        daily = self.start_daily and not self.end_interval_censored
        return "daily" if daily else "sparse"

    @property
    def n_shifts(self) -> int:
        return max(len(self.resupply) - 1, 0)


def _d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _newer_report(row: dict, last_obs: date) -> date | None:
    """Return the official date proving a restriction report newer than `last_obs`, else None."""
    if not _d(row.get("Beginn_Vertriebseinschraenkung")):
        return None  # Beginn-less rows are availability reports or announcements
    dates = [d for d in (_d(row.get("Datum_Meldung")), _d(row.get("Beginn_Vertriebseinschraenkung"))) if d]
    newer = [d for d in dates if d > last_obs]
    return min(newer) if newer else None


def derive(snapshots: list[SnapshotView]) -> list[Episode]:
    """Derive all episodes; `snapshots` must be ordered by time."""
    episodes: list[Episode] = []
    listed: dict[str, Episode | None] = {}  # currently listed package -> episode of this listing
    last_ep: dict[str, Episode] = {}
    last_obs: dict[str, date] = {}
    prev_day: date | None = None

    for snap in snapshots:
        if snap.complete:
            for key in [k for k in listed if k not in snap.rows]:
                ep = listed.pop(key)
                if ep is not None and not ep.ended:
                    ep.end_reason, ep.end_lower, ep.end_upper = "disappeared", ep.last_seen, snap.day
        for key in sorted(snap.rows):
            row = snap.rows[key]
            is_end = (row.get("Status") or "") in END_STATUSES
            fresh = key not in listed
            ep = listed.get(key)
            newer = None if fresh else _newer_report(row, last_obs[key])
            if ep is not None and not ep.ended and not newer:
                _observe(ep, row, snap)
                if is_end:
                    _end_by_status(ep, row, ep.last_seen, snap.day)
                else:
                    ep.last_seen, ep.last_snapshot = snap.day, snap.snapshot_id
            elif not is_end or newer or (fresh and _d(row.get("Beginn_Vertriebseinschraenkung"))):
                if ep is not None and not ep.ended:
                    ep.end_reason, ep.end_lower, ep.end_upper = "rereported", ep.last_seen, min(newer, snap.day)
                ep = _open(key, row, snap, prev_day, last_ep.get(key))
                episodes.append(ep)
                last_ep[key] = ep
                if is_end:
                    _end_by_status(ep, row, ep.start_date, snap.day)
            listed[key] = ep
            if ep is not None:
                ep.last_listed = snap.day
            last_obs[key] = snap.day
        prev_day = snap.day
    return episodes


def _end_by_status(ep: Episode, row: dict, lower: date, day: date) -> None:
    ep.end_reason, ep.end_lower, ep.end_upper = "status", lower, day
    ep.end_last_change = row.get("Datum_letzte_Aenderung")
    if not _d(row.get("Beginn_Vertriebseinschraenkung")):
        ep.end_report_date = row.get("Datum_Meldung")


def _open(key: str, row: dict, snap: SnapshotView, prev_day: date | None, prev: Episode | None) -> Episode:
    floor = prev.end_lower if prev is not None else None
    start, source = snap.day, "first_seen"
    for name, src in (("Beginn_Vertriebseinschraenkung", "beginn"), ("Datum_Meldung", "meldung")):
        d = _d(row.get(name))
        if d and d <= snap.day and (floor is None or d > floor):
            start, source = d, src
            break
    ep = Episode(
        package_key=key,
        seq_no=prev.seq_no + 1 if prev is not None else 1,
        start_date=start,
        start_source=source,
        first_seen=snap.day,
        first_snapshot=snap.snapshot_id,
        last_seen=snap.day,
        last_snapshot=snap.snapshot_id,
        start_daily=prev_day is not None and (snap.day - prev_day).days <= 1,
    )
    _observe(ep, row, snap)
    return ep


def _observe(ep: Episode, row: dict, snap: SnapshotView) -> None:
    status = row.get("Status") or ""
    if not ep.statuses or ep.statuses[-1][0] != status:
        ep.statuses.append((status, snap.day))
    resupply = (row.get("Datum_voraussichtliche_Wiederbelieferung") or "").strip()
    if resupply and not (status in END_STATUSES) and (not ep.resupply or ep.resupply[-1][0] != resupply):
        ep.resupply.append((resupply, snap.day))
