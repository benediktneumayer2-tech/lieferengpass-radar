"""Chart of the radar pages: F23, how far announced resupply dates move, counted per change in the daily archive."""
from __future__ import annotations

from html import escape

from . import WIDE, frame, line, num, r, text, text_width

KEY = (("f23-a", "erst nach Ablauf des alten Termins geändert"), ("f23-b", "vor Ablauf geändert"))
RANGE_X = 94  # narrow: the day ranges as one column right of the class names


def median_text(data: dict) -> str:
    v = data["median_days"]
    return f"{num(v, 0 if v == int(v) else 1, signed=True)} Tage"


def _key(x0: float, y: float, right: float) -> tuple[list[str], float]:
    """The two shades, wrapping into a second row when they do not fit. Returns the marks and the y of the last row."""
    out: list[str] = []
    x = x0
    for cls, label in KEY:
        need = 18 + text_width(label, 13)
        if x > x0 and x + need > right:
            x, y = x0, y + 20
        out += [f'<rect class="{cls}" x="{r(x)}" y="{r(y - 10)}" width="12" height="12"/>', text(x + 18, y, label, "f23-k")]
        x += need + 20
    return out, y


def _bar(c: dict, x0: float, y: float, h: float, k: float) -> list[str]:
    """One class: the dark part first (changed only after the old date had passed), then the pale part.

    The total stands at the end of the bar; the dark part carries its own count where it fits, unless it is the whole bar.
    """
    a, b = c["n_after"], c["n"] - c["n_after"]
    tip = f'{c["name"]} ({c["range"]}): {num(c["n"])} Änderungen, davon {num(a)} erst nach Ablauf'
    out = [f"<g><title>{escape(tip, quote=False)}</title>"]
    if a:
        out.append(f'<rect class="f23-a" x="{r(x0)}" y="{r(y)}" width="{r(a * k)}" height="{r(h)}"/>')
    if b:
        out.append(f'<rect class="f23-b" x="{r(x0 + a * k)}" y="{r(y)}" width="{r(b * k)}" height="{r(h)}"/>')
    out.append("</g>")
    if a and b and a * k >= text_width(num(a), 12.5, mono=True) + 10:
        out.append(text(x0 + a * k / 2, y + h / 2 + 4.3, num(a), "f23-i", "middle"))
    return out


def f23(data: dict, *, width: int, uid: str) -> str:
    """F23: one bar per size class of a date change, split into changes made before and only after the old date had passed.

    `data` comes from `seiten.radar.termine`. The unit is one change. Wide: class names beside the bars; narrow: above them,
    so the bars get the full width. The scale is the largest at which every bar, its count and the median note fit.
    """
    wide = width >= WIDE
    classes, med = data["classes"], data["median_class"]
    bar0 = 150 if wide else 0
    key, key_y = _key(bar0, 15, width)
    note = f'Median {median_text(data)}'
    note_w = 14 + text_width(note, 13)

    count_w = [text_width(num(c["n"]), 13.5, mono=True) for c in classes]
    room = [width - 2 - bar0 - 8 - w - (note_w + 12 if i == med else 0) for i, w in enumerate(count_w)]
    k = min(room[i] / c["n"] for i, c in enumerate(classes) if c["n"])

    pitch, h, gap = (44, 24, 10) if wide else (46, 18, 8)
    top = key_y + (20 if wide else 16)
    body: list[str] = [*key]
    first_bar = last_bar = 0.0
    for i, c in enumerate(classes):
        ty = top + i * pitch + (gap if i else 0)
        if wide:
            by = ty + 6
            body += [text(bar0 - 14, ty + 15, c["name"], "f23-c", "end"), text(bar0 - 14, ty + 31, c["range"], "f23-r", "end")]
        else:
            by = ty + 20
            body += [text(0, ty + 13, c["name"], "f23-c"), text(RANGE_X, ty + 13, c["range"], "f23-r")]
        first_bar = first_bar or by
        last_bar = by + h
        body += _bar(c, bar0, by, h, k)
        end = bar0 + c["n"] * k + 6
        body.append(text(end, by + h / 2 + 4.6, num(c["n"]), "f23-n"))
        if i == med:
            mx = end + count_w[i] + 12
            body += [f'<path class="f23-mk" d="M{r(mx)} {r(by + h / 2)}l6 -4.5v9z"/>', text(mx + 12, by + h / 2 + 4.5, note, "f23-m")]
    if wide:  # narrow: the names stand on the bars' left edge, so a baseline would run through them
        body.insert(len(key), line(bar0 + 0.5, first_bar - 4, bar0 + 0.5, last_bar + 4, "f23-base"))

    parts = ", ".join(f'{c["name"]} ({c["range"]}) {num(c["n"])}, davon {num(c["n_after"])} erst nach Ablauf' for c in classes)
    desc = (f'{num(data["n_changes"])} Änderungen angekündigter Termine zwischen {data["start"].strftime("%d.%m.%Y")} und '
            f'{data["ref"].strftime("%d.%m.%Y")} in {num(data["n_packages"])} von {num(data["n_with_date"])} Packungen mit Termin, '
            f'nach Größe der Verschiebung: {parts}. Median der Änderung {median_text(data)}. '
            'Dieselben Änderungen stehen als Tabelle unter der Grafik.')
    return frame("f23", width, last_bar + 6, uid, "Wie weit sich angekündigte Termine verschieben", desc, body)
