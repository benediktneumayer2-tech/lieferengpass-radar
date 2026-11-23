"""Chart of the radar pages: F23, how announced resupply dates move in the daily archive."""
from __future__ import annotations

from datetime import date

from ..timeline import MONTHS, de
from . import WIDE, Linear, frame, line, num, r, text, text_width, x_axis, y_axis

SHARE_BEFORE, SHARE_AFTER = 0.12, 0.24  # height of the compressed bands below and above the part drawn to scale
SCALE_DAYS = 90  # dates up to about this far after the reference day are drawn to scale


def _next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


class _DateAxis(Linear):
    """Date axis, linear between knots (day, y). Bands outside the part drawn to scale are compressed and marked."""

    def __init__(self, knots: list[tuple[int, float]]):
        super().__init__((knots[0][0], knots[-1][0]), (knots[0][1], knots[-1][1]))
        self.knots = knots

    def __call__(self, value: float) -> float:
        for (a, ya), (b, yb) in zip(self.knots, self.knots[1:]):
            if value <= b:
                return ya + (value - a) / (b - a) * (yb - ya)
        return self.knots[-1][1]


def _date_scale(values: list[date], start: date, ref: date, bottom: float, top: float) -> tuple[_DateAxis, list[int], int | None, int | None]:
    """The axis, its ticks, and the days where a compressed band begins (below `start`, above `cut`), if any."""
    height = bottom - top
    lo, last = min(values), max(values)
    cut = _next_month(date.fromordinal(ref.toordinal() + SCALE_DAYS))
    has_before, has_after = lo < start, last >= cut
    hi = _next_month(last) if has_after else max(cut, _next_month(last))
    y_start = bottom - height * SHARE_BEFORE if has_before else bottom
    y_cut = top + height * SHARE_AFTER if has_after else top
    knots: list[tuple[int, float]] = [(lo.replace(day=1).toordinal(), bottom)] if has_before else []
    knots.append((start.toordinal(), y_start))
    knots.append((cut.toordinal() if has_after else hi.toordinal(), y_cut))
    if has_after:
        knots.append((hi.toordinal(), top))
    ticks = [lo.replace(day=1).toordinal()] if has_before else []
    day = _next_month(start)
    while day.toordinal() <= knots[-2 if has_after else -1][0]:
        ticks.append(day.toordinal())
        day = _next_month(day)
    if has_after:
        ticks += [c.toordinal() for c in (date(y, m, 1) for y in range(cut.year, hi.year + 1) for m in (1, 7))
                  if cut.toordinal() + 45 < c.toordinal() <= hi.toordinal()]
    return _DateAxis(knots), ticks, start.toordinal() if has_before else None, cut.toordinal() if has_after else None


def _day_ticks(start: date, ref: date, min_gap: int) -> list[int]:
    """First and last day, plus the 1st and 15th of each month where they keep clear of those two."""
    out = [start.toordinal()]
    for n in range(start.toordinal() + 1, ref.toordinal()):
        day = date.fromordinal(n)
        if day.day in (1, 15) and n - out[-1] >= min_gap and ref.toordinal() - n >= min_gap:
            out.append(n)
    return [*out, ref.toordinal()]


def _month_label(value: float) -> str:
    day = date.fromordinal(int(value))
    return f"{MONTHS[day.month - 1]} {day.year % 100:02d}"


def _key(width: int, x0: float) -> tuple[list[str], float]:
    """Key above the plot, wrapping into rows. Returns the marks and the y of its last row."""
    items = (("f23-ln ser-main", "später"), ("f23-ln f23-dn ser-comp", "vorgezogen"), ("f23-today", "heute (Diagonale)"),
             ("f23-past f23-swatch", "Termin verstrichen"), ("f23-break", "Achsbruch"))
    out: list[str] = []
    x, y = x0, 38
    for cls, label in items:
        need = 26 + text_width(label, 13)
        if x > x0 and x + need > width - 4:
            x, y = x0, y + 20
        if "swatch" in cls:
            out.append(f'<rect class="{cls}" x="{r(x)}" y="{r(y - 10)}" width="20" height="11"/>')
        else:
            out.append(line(x, y - 4, x + 20, y - 4, cls))
        out.append(text(x + 26, y, label, "ch-axt"))
        x += need + 14
    return out, y


def f23(data: dict, *, width: int, uid: str) -> str:
    """F23: one stepped line per package whose announced date changed in the daily archive; the diagonal is today.

    `data` comes from `seiten.radar.termine`. Each step up is a date moved later; below the diagonal a date had
    already passed on that day. Beyond the dashed lines the date axis is compressed.
    """
    start, ref = data["start"], data["ref"]
    wide = width >= WIDE
    left, right = (62 if wide else 54), width - 22
    key, key_y = _key(width, 4)
    top = key_y + 18
    bottom = top + (376 if wide else 318)
    values = [start, ref]
    for ln in data["lines"]:
        values += [ln["first"], *(new for _, _, new in ln["steps"])]
    y, y_ticks, band_low, band_high = _date_scale(values, start, ref, bottom, top)
    x = Linear((start.toordinal(), ref.toordinal()), (left, right))
    x_ticks = _day_ticks(start, ref, 6 if wide else 9)

    x0, x1, y_start, y_ref = x(start.toordinal()), x(ref.toordinal()), y(start.toordinal()), y(ref.toordinal())
    body = [
        f'<path class="f23-past" d="M{r(x0)} {r(y_start)}L{r(x1)} {r(y_ref)}V{r(bottom)}H{r(x0)}Z"/>',
        y_axis(y, left, right=right, ticks=y_ticks, fmt=_month_label),
        x_axis(x, bottom, ticks=x_ticks, fmt=lambda v: date.fromordinal(int(v)).strftime("%d.%m."),
               label="Tag im Tagesarchiv, an dem der Termin gelistet war" if wide else "Tag im Tagesarchiv"),
        text(4, 16, "Angekündigter Termin", "ch-axt"),
        *key,
    ]
    body += [line(left, y(day), right, y(day), "f23-break") for day in (band_low, band_high) if day is not None]

    dots: dict[str, list[str]] = {"ser-main": [], "ser-comp": []}
    for ln in data["lines"]:
        px, py = x(ln["start"].toordinal()), y(ln["first"].toordinal())
        path = [f"M{r(px)} {r(py)}"]
        earlier = any(new < old for _, old, new in ln["steps"])
        series = "ser-comp" if earlier else "ser-main"
        for seen, _old, new in ln["steps"]:
            sx, ny = x(seen.toordinal()), y(new.toordinal())
            path.append(f"H{r(sx)}V{r(ny)}")
            dots[series].append(f"M{r(sx)} {r(ny)}h0")
        path.append(f'H{r(x(ln["end"].toordinal()))}')
        tip = ""
        if wide:
            moves = ", ".join(f"{de(old)} auf {de(new)}" for _, old, new in ln["steps"])
            tip = f'<title>PZN {ln["pzn"]}: {moves}</title>' if ln["pzn"] else f"<title>{moves}</title>"
        body.append(f'<path class="f23-ln{" f23-dn" if earlier else ""} {series}" d="{"".join(path)}">{tip}</path>')
    body += [f'<path class="f23-dot {series}" d="{"".join(marks)}"/>' for series, marks in dots.items() if marks]
    body.append(line(x0, y_start, x1, y_ref, "f23-today"))

    median_text = num(data["median_days"], 0 if data["median_days"] == int(data["median_days"]) else 1, signed=True)
    desc = (f'{num(data["n_packages"])} von {num(data["n_with_date"])} Packungen mit Termin haben ihren angekündigten Termin '
            f'zwischen {de(start)} und {de(ref)} geändert, zusammen {num(data["n_changes"])}-mal: '
            f'{num(data["n_later"])}-mal später, {num(data["n_earlier"])}-mal früher. Median der Änderung {median_text} Tage. '
            'Dieselben Änderungen stehen als Tabelle unter der Grafik.')
    return frame("steps", width, bottom + 44, uid, "Verschiebung angekündigter Termine im Tagesarchiv", desc, body)
