"""Building blocks for the site's charts: pure functions from numbers to inline SVG strings.

The contract for every chart function:

    def name(data, *, width: int, uid: str) -> str

It returns one `<svg class="ch ch-<form>" viewBox="0 0 W H" role="img" aria-labelledby="{uid}-t {uid}-d">`
with `<title>` and `<desc>`. Colours and fonts come only from CSS classes (`web/assets/css/50-charts.css`),
never from attributes; ids start with `uid`; coordinates carry one decimal; numbers go through `num`/`pct`.
No clock, no randomness: the same input gives the same bytes. Every chart is drawn twice, about 720 and
300 wide, and CSS shows one of them (`WIDE`, `NARROW`).

A minimal chart, as a pattern to copy (`charts/modell.py` holds a complete one, F08):

    from . import Linear, frame, marker, num, text, x_axis

    def beispiel(data, *, width, uid):
        x = Linear((0, 10), (120, width - 16))
        body = [x_axis(x, y=70, top=10, fmt=lambda v: num(v, 0))]
        for i, (name, value) in enumerate(data):
            y = 24 + i * 24
            body += [text(112, y + 4, name, "ch-lbl", "end"), marker("circle", x(value), y, "ser-main", title=f"{name}: {num(value, 1)}")]
        return frame("dots", width, 100, uid, "Titel", "Beschreibung in einem Satz.", body)
"""
from __future__ import annotations

from html import escape
from math import ceil, floor, log10
from typing import Callable, Iterable, Sequence

WIDE = 720
NARROW = 300
MINUS = "−"
NBSP = " "


def r(value: float) -> str:
    """Coordinate with at most one decimal and no `-0`."""
    text = f"{round(value + 0.0, 1):.1f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def num(value: float, decimals: int = 0, signed: bool = False) -> str:
    """German number: `23.461`, `0,819`, `−0,017`; `signed=True` adds `+` to positive values."""
    text = f"{abs(value):,.{decimals}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")
    if float(f"{abs(value):.{decimals}f}") == 0:
        return text
    return (MINUS if value < 0 else "+" if signed else "") + text


def pct(fraction: float, decimals: int = 1) -> str:
    """Share as a German percentage: `pct(0.202)` is `20,2 %`."""
    return f"{num(fraction * 100, decimals)}{NBSP}%"


def text_width(s: str, size: float, mono: bool = False) -> float:
    """Rough width in px, for layout decisions only (Barlow averages about 0.5 em, Plex Mono is 0.6 em)."""
    return len(s) * size * (0.6 if mono else 0.5)


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round tick values (1, 2 or 5 times a power of ten) that cover [lo, hi]."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(count, 1)
    power = 10 ** floor(log10(raw))
    step = next((m * power for m in (1, 2, 5, 10) if m * power >= raw - 1e-12), 10 * power)
    decimals = max(0, -floor(log10(step)))
    first, last = ceil(lo / step - 1e-9), floor(hi / step + 1e-9)
    return [round(i * step, decimals) for i in range(first, last + 1)]


def log_ticks(lo: float, hi: float, steps: Sequence[int] = (1, 2, 5)) -> list[float]:
    """Ticks for a logarithmic axis: 1, 2, 5 times each power of ten inside [lo, hi]."""
    out = []
    for exp in range(floor(log10(lo)), ceil(log10(hi)) + 1):
        for m in steps:
            value = round(m * 10.0 ** exp, 10)
            if lo - 1e-12 <= value <= hi + 1e-12:
                out.append(value)
    return out


class Linear:
    """Linear scale: `x = Linear((0, 25), (120, 700)); x(10)`."""

    def __init__(self, domain: tuple[float, float], rng: tuple[float, float]):
        self.domain, self.range = domain, rng

    def __call__(self, value: float) -> float:
        (d0, d1), (r0, r1) = self.domain, self.range
        return r0 + (value - d0) / (d1 - d0) * (r1 - r0)

    def ticks(self, count: int = 5) -> list[float]:
        return nice_ticks(*self.domain, count)


class Log(Linear):
    """Logarithmic scale with the same interface; the domain must be positive."""

    def __call__(self, value: float) -> float:
        (d0, d1), (r0, r1) = self.domain, self.range
        return r0 + (log10(value) - log10(d0)) / (log10(d1) - log10(d0)) * (r1 - r0)

    def ticks(self, count: int = 5) -> list[float]:
        return log_ticks(*self.domain)


def _cls(*names: str) -> str:
    return " ".join(n for n in names if n)


def line(x1: float, y1: float, x2: float, y2: float, cls: str) -> str:
    return f'<line class="{cls}" x1="{r(x1)}" y1="{r(y1)}" x2="{r(x2)}" y2="{r(y2)}"/>'


def text(x: float, y: float, s: str, cls: str = "ch-lbl", anchor: str | None = None) -> str:
    """Escaped label; `anchor` is `middle` or `end`."""
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text class="{cls}" x="{r(x)}" y="{r(y)}"{a}>{escape(s, quote=False)}</text>'


def _shape(shape: str, x: float, y: float, size: float, cls: str) -> str:
    if shape == "circle":
        return f'<circle class="{cls}" cx="{r(x)}" cy="{r(y)}" r="{r(size)}"/>'
    if shape == "square":
        s = size * 0.9
        return f'<rect class="{cls}" x="{r(x - s)}" y="{r(y - s)}" width="{r(2 * s)}" height="{r(2 * s)}"/>'
    if shape == "diamond":
        s = size * 1.25
        return f'<path class="{cls}" d="M{r(x)} {r(y - s)}L{r(x + s)} {r(y)}L{r(x)} {r(y + s)}L{r(x - s)} {r(y)}Z"/>'
    if shape == "triangle":
        s = size * 1.2
        return f'<path class="{cls}" d="M{r(x)} {r(y - s)}L{r(x + s)} {r(y + s * 0.8)}L{r(x - s)} {r(y + s * 0.8)}Z"/>'
    raise ValueError(f"unknown marker shape: {shape}")


def marker(shape: str, x: float, y: float, series: str, *, size: float = 5, hollow: bool = False, title: str | None = None) -> str:
    """Series marker: `circle`, `square`, `diamond` or `triangle`; `series` is `ser-main`, `ser-comp` or `ser-base`.

    With `title` the marker gets a native tooltip and a hit area of 24 px. Series are told apart by shape as well as colour.
    """
    cls = _cls("mk", series, "mk-hollow" if hollow else "")
    mark = _shape(shape, x, y, size, cls)
    if title is None:
        return mark
    return (f'<g class="mk-g"><title>{escape(title, quote=False)}</title>'
            f'<circle class="mk-hit" cx="{r(x)}" cy="{r(y)}" r="12"/>{mark}</g>')


def whisker(x0: float, x1: float, y: float, series: str = "ser-main", cap: float = 4) -> str:
    """Horizontal interval with end caps, 1.25 px in the series colour."""
    return (f'<path class="ch-wh {series}" d="M{r(x0)} {r(y - cap)}V{r(y + cap)}M{r(x0)} {r(y)}H{r(x1)}'
            f'M{r(x1)} {r(y - cap)}V{r(y + cap)}"/>')


def x_axis(scale: Linear, y: float, top: float | None = None, ticks: Iterable[float] | None = None,
           fmt: Callable[[float], str] = lambda v: num(v), label: str | None = None) -> str:
    """Bottom axis with tick labels; `top` extends each tick upward as a hairline gridline."""
    x0, x1 = scale.range
    out = [line(min(x0, x1), y, max(x0, x1), y, "ch-axis")]
    for v in (scale.ticks() if ticks is None else ticks):
        xx = scale(v)
        if top is not None:
            out.append(line(xx, top, xx, y, "ch-grid"))
        out.append(line(xx, y, xx, y + 4, "ch-axis"))
        out.append(text(xx, y + 18, fmt(v), "ch-tick", "middle"))
    if label:
        out.append(text((x0 + x1) / 2, y + 36, label, "ch-axt", "middle"))
    return "".join(out)


def y_axis(scale: Linear, x: float, right: float | None = None, ticks: Iterable[float] | None = None,
           fmt: Callable[[float], str] = lambda v: num(v), label: str | None = None) -> str:
    """Left axis with tick labels; `right` extends each tick as a hairline gridline."""
    y0, y1 = scale.range
    out = [line(x, min(y0, y1), x, max(y0, y1), "ch-axis")]
    for v in (scale.ticks() if ticks is None else ticks):
        yy = scale(v)
        if right is not None:
            out.append(line(x, yy, right, yy, "ch-grid"))
        out.append(line(x - 4, yy, x, yy, "ch-axis"))
        out.append(text(x - 7, yy + 4, fmt(v), "ch-tick", "end"))
    if label:
        out.append(text(x, min(y0, y1) - 8, label, "ch-axt", "start"))
    return "".join(out)


def frame(form: str, width: int, height: float, uid: str, title: str, desc: str, body: Iterable[str]) -> str:
    """The accessible `<svg>` around a chart: `form` becomes the class `ch-<form>`, title and desc name it."""
    return (f'<svg class="ch ch-{form}" viewBox="0 0 {width} {r(height)}" role="img" aria-labelledby="{uid}-t {uid}-d">'
            f'<title id="{uid}-t">{escape(title, quote=False)}</title><desc id="{uid}-d">{escape(desc, quote=False)}</desc>'
            f'{"".join(body)}</svg>')
