"""Server-side SVG timelines (direction B "Klinischer Zeitstrahl") and their text equivalent.

One row of status bands per package: observed restriction periods in the BASG status colour,
periods the archive did not observe (before the first sighting, end intervals between sparse
snapshots) hatched. Above the band: a dashed marker per announced resupply date and an arrow per
postponement. Below: ticks for archive snapshots (dark = package listed). Styling lives in the
site stylesheet; hatch patterns are defined once per page (`#hatch`, `#dots`, `#stripes`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape

MONTHS = ("Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")
STATUS_CLASS = {
    "Nicht verfügbar": "s-nv",
    "eingeschränkt verfügbar": "s-ev",
    "verfügbar gemäß §4 (1)": "s-s4",
    "verfügbar": "s-ok",
}
END_STATUS = "verfügbar"


def status_class(status: str | None) -> str:
    return STATUS_CLASS.get(status or "", "s-other")


def d(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def de(day: date | None) -> str:
    return day.strftime("%d.%m.%Y") if day else "–"


@dataclass
class Ep:
    """One episode with everything the timeline needs (dates parsed)."""

    seq_no: int
    start: date
    start_source: str
    first_seen: date
    last_seen: date
    active: bool
    end_reason: str | None
    end_lower: date | None
    end_upper: date | None
    end_last_change: str | None
    history_quality: str
    duration_min: int
    duration_max: int
    statuses: list[tuple[str, date]] = field(default_factory=list)
    resupply: list[tuple[str, date]] = field(default_factory=list)

    def known_end(self, ref: date) -> date:
        return self.end_lower if self.end_lower else ref

    def segments(self, ref: date) -> list[tuple[str, date, date, str]]:
        """(kind, from, to, label): kind is a status class or 'unc' for unobserved time."""
        out = []
        end = self.known_end(ref)
        observed_from = min(self.first_seen, end)
        if self.start < observed_from:
            out.append(("unc", self.start, observed_from, "nicht beobachtet"))
        restricted = [(s, day) for s, day in self.statuses if s != END_STATUS]
        for i, (status, since) in enumerate(restricted):
            until = restricted[i + 1][1] if i + 1 < len(restricted) else end
            since, until = max(since, self.start), min(until, end)
            if until >= since and since <= end:
                out.append((status_class(status), since, until, status))
        if self.end_lower and self.end_upper and self.end_upper > self.end_lower:
            out.append(("unc", self.end_lower, self.end_upper, "Ende unsicher"))
        return out

    def shifts(self) -> list[tuple[str, str, date]]:
        return [(self.resupply[i - 1][0], self.resupply[i][0], self.resupply[i][1]) for i in range(1, len(self.resupply))]


def _domain(eps: list[Ep], listed: list[date], ref: date) -> tuple[date, date]:
    lo = [e.start for e in eps] + listed[:1]
    hi = [ref] + [e.end_upper for e in eps if e.end_upper]
    limit = ref + timedelta(days=730)
    hi += [min(x, limit) for e in eps for a, _ in e.resupply if (x := d(a))]
    d0 = min(lo) if lo else ref - timedelta(days=365)
    d1 = max(hi)
    if (d1 - d0).days < 60:
        d0 = d1 - timedelta(days=60)
    pad = timedelta(days=max(7, (d1 - d0).days // 30))
    return d0 - pad, d1 + pad


def _ticks(d0: date, d1: date, px_per_day: float, min_px: int) -> list[tuple[date, str]]:
    for months in (1, 3, 6, 12, 24):
        if months * 30.4 * px_per_day >= min_px:
            break
    out = []
    y, m = d0.year, d0.month
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        t = date(y, m, 1)
        if t > d1:
            return out
        if (y * 12 + m - 1) % months == 0:
            out.append((t, str(y) if m == 1 else MONTHS[m - 1]))


class _Scale:
    def __init__(self, d0: date, d1: date, x0: float, x1: float):
        self.d0, self.span, self.x0, self.w = d0, max((d1 - d0).days, 1), x0, x1 - x0

    def __call__(self, day: date) -> float:
        return round(self.x0 + (day - self.d0).days / self.span * self.w, 1)


def timeline_svg(eps: list[Ep], listed: list[date], archive_days: list[date], ref: date, width: int, uid: str, label: str) -> str:
    """Full timeline for a package page. `width` 880 (desktop) or 340 (phone)."""
    d0, d1 = _domain(eps, listed, ref)
    x = _Scale(d0, d1, 8, width - 8)
    lane, band_y, band_h = 40, 44, 28
    ticks_y = band_y + band_h + 6
    axis_y = ticks_y + 26
    h = axis_y + 6
    p: list[str] = [
        f'<svg class="tl" viewBox="0 0 {width} {h}" width="{width}" height="{h}" role="img" '
        f'aria-labelledby="{uid}-t {uid}-d" preserveAspectRatio="xMinYMin meet">',
        f'<title id="{uid}-t">{escape(label)}</title>',
        f'<desc id="{uid}-d">Statusbänder je Episode, gestrichelte Linien für angekündigte Termine, Pfeile für '
        f'Verschiebungen, schraffiert: nicht beobachtete Zeiträume. Gleicher Inhalt als Text unter der Grafik.</desc>',
        f'<rect class="tl-track" x="{x(d0)}" y="{band_y}" width="{round(x(d1) - x(d0), 1)}" height="{band_h}"/>',
    ]
    for day, text in _ticks(d0, d1, (width - 16) / max((d1 - d0).days, 1), 64 if width > 500 else 48):
        xx = x(day)
        p.append(f'<line class="tl-grid" x1="{xx}" x2="{xx}" y1="{band_y - 4}" y2="{ticks_y + 10}"/>')
        if 16 <= xx <= width - 16:
            p.append(f'<text class="tl-axis" x="{xx}" y="{axis_y}" text-anchor="middle">{text}</text>')
    labels: list[str] = []
    for e in eps:
        for kind, a, b, text in e.segments(ref):
            xa, xb = x(a), x(b)
            w = round(max(xb - xa, 2), 1)
            if kind == "unc":
                p.append(f'<rect class="tl-unc" x="{xa}" y="{band_y}" width="{w}" height="{band_h}"/>')
            else:
                p.append(f'<rect class="tl-band {kind}" x="{xa}" y="{band_y}" width="{w}" height="{band_h}"/>')
                if w > 9 * len(text):
                    labels.append(f'<text class="tl-label {kind}" x="{xa + 6}" y="{band_y + 18}">{escape(text)}</text>')
    listed_set = set(listed)
    for day in archive_days:
        if d0 <= day <= d1:
            cls = "tl-obs on" if day in listed_set else "tl-obs"
            p.append(f'<line class="{cls}" x1="{x(day)}" x2="{x(day)}" y1="{ticks_y}" y2="{ticks_y + 8}"/>')
    k = 0
    for e in eps:
        for a, _seen in e.resupply:
            ad = d(a)
            if ad and d0 <= ad <= d1:
                p.append(f'<line class="tl-resupply" x1="{x(ad)}" x2="{x(ad)}" y1="16" y2="{band_y + band_h}"/>')
        for old, new, _seen in e.shifts():
            od, nd = d(old), d(new)
            if od and nd and d0 <= od <= d1 and d0 <= nd <= d1:
                y = lane - 4 - (k % 3) * 7
                k += 1
                xo, xn = x(od), x(nd)
                if abs(xn - xo) < 6:
                    xn = xo + (6 if nd >= od else -6)
                p.append(f'<line class="tl-shift" x1="{xo}" x2="{xn}" y1="{y}" y2="{y}" marker-end="url(#arrow)"/>')
    p += labels
    xr = x(ref)
    p.append(f'<line class="tl-ref" x1="{xr}" x2="{xr}" y1="14" y2="{ticks_y + 10}"/>')
    anchor = "end" if xr > width - 70 else "start"
    p.append(f'<text class="tl-axis tl-reftext" x="{xr + (-4 if anchor == "end" else 4)}" y="10" text-anchor="{anchor}">Stichtag</text>')
    p.append("</svg>")
    return "".join(p)


def mini_svg(eps: list[Ep], ref: date, announced: str | None = None, width: int = 120, height: int = 14) -> str:
    """Decorative mini timeline (12 months before to 2 months after `ref`); row text carries the facts."""
    d0, d1 = ref - timedelta(days=365), ref + timedelta(days=60)
    x = _Scale(d0, d1, 0, width)
    p = [f'<svg class="mini" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true" focusable="false">',
         f'<rect class="tl-track" x="0" y="3" width="{width}" height="{height - 6}"/>']
    for e in eps:
        for kind, a, b, _ in e.segments(ref):
            if b < d0 or a > d1:
                continue
            xa, xb = x(max(a, d0)), x(min(b, d1))
            cls = "tl-unc" if kind == "unc" else f"tl-band {kind}"
            p.append(f'<rect class="{cls}" x="{xa}" y="3" width="{round(max(xb - xa, 1.5), 1)}" height="{height - 6}"/>')
    ad = d(announced)
    if ad and d0 <= ad <= d1:
        p.append(f'<line class="tl-resupply" x1="{x(ad)}" x2="{x(ad)}" y1="0" y2="{height}"/>')
    p.append(f'<line class="tl-ref" x1="{x(ref)}" x2="{x(ref)}" y1="0" y2="{height}"/></svg>')
    return "".join(p)


START_TEXT = {
    "beginn": "Beginn der Vertriebseinschränkung laut BASG",
    "meldung": "Meldedatum laut BASG (kein Beginn angegeben)",
    "first_seen": "erstmals im Archiv gesehen (kein Beginn angegeben)",
}


def events(e: Ep, ref: date) -> list[tuple[str, str, bool]]:
    """Text equivalent of one episode: (date text, event, derived?) in time order."""
    rows: list[tuple[date, int, str, str, bool]] = [(e.start, 0, de(e.start), START_TEXT.get(e.start_source, e.start_source), False)]
    for status, seen in e.statuses:
        rows.append((seen, 1, de(seen), f"Status „{status}“ erstmals gesehen", False))
    for i, (announced, seen) in enumerate(e.resupply):
        ad = d(announced)
        text = f"angekündigte Wiederbelieferung {de(ad) if ad else announced} (erstmals gesehen {de(seen)})"
        if i:
            prev = d(e.resupply[i - 1][0])
            direction = "später" if ad and prev and ad > prev else "früher" if ad and prev else "geändert"
            text = f"Verschiebung des Termins von {de(prev) if prev else e.resupply[i - 1][0]} auf {de(ad) if ad else announced} ({direction}), gesehen {de(seen)}"
        rows.append((seen, 2, de(seen), text, bool(i)))
    if e.end_reason:
        why = {
            "status": "BASG-Status „verfügbar“",
            "disappeared": "nicht mehr in der BASG-Liste",
            "rereported": "neue Meldung derselben Packung",
        }.get(e.end_reason, e.end_reason)
        when = f"zwischen {de(e.end_lower)} und {de(e.end_upper)}" if e.end_upper != e.end_lower else de(e.end_upper)
        extra = f"; letzte Änderung laut BASG: {e.end_last_change}" if e.end_last_change else ""
        rows.append((e.end_upper, 3, when, f"Ende ({why}){extra}", True))
    else:
        rows.append((ref, 3, de(ref), "zum Stichtag weiterhin gemeldet", True))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [(when, text, derived) for _, _, when, text, derived in rows]
