"""F22 "Vorhersage gegen Meldung": two panels over one logarithmic x-axis of predicted probability.

Panel a: bars show how all substances spread over six fixed classes, one dot per newly reported substance stands in
the class of its prediction from the day before. Panel b: predicted against observed share per class, with the pale
retrospective band, hollow circles for the Einlaufphase and filled diamonds for the Prüfung. `data` is the dictionary
of `stockout_at.live.build`: aggregates only, so nothing here can show a single substance.
"""
from __future__ import annotations

from datetime import date
from math import atan2, ceil, degrees, floor, hypot

from ..timeline import de
from . import WIDE, Log, frame, line, marker, num, r, text, text_width, x_axis, y_axis

AXIS = (0.2, 50.0)  # percent, both axes of panel b
X_TICKS = (0.2, 1, 2, 4, 8, 16, 50)
Y_TICKS = (0.2, 0.5, 1, 2, 5, 10, 20, 50)
BAR_MAX = 0.5  # share of all substances at full bar height; fixed, so the bars only move when the data does
# (distance between dots, dot size, dots per row): the largest that fits; dots get smaller, they are never merged
DOTS_WIDE = ((12, 4.6, 5), (10, 3.7, 6), (8.6, 3.2, 7), (7.2, 2.7, 8), (6, 2.3, 10), (5, 1.9, 12), (4.2, 1.6, 14))
DOTS_NARROW = ((7, 2.7, 4), (6, 2.3, 5), (5, 1.9, 6), (4.2, 1.6, 7), (3.6, 1.35, 8))
PHASES = (("einlauf", "circle", True, "Einlaufphase"), ("pruefung", "diamond", False, "Prüfung"))


def _day(value: str) -> str:
    return de(date.fromisoformat(value))


def _tick(value: float) -> str:
    return num(value, 1) if value < 1 else num(value)


def _in_axis(percent: float) -> float:
    return min(max(percent, AXIS[0]), AXIS[1])


def _span(lo: float, hi: float) -> str:
    return f"{num(lo * 100, 1)}–{num(hi * 100, 1)}"


def _class_name(data: dict, group: list[int]) -> str:
    return " + ".join(data["klassen"][i]["name"] for i in group)


def _wrap(sentence: str, limit: int) -> list[str]:
    lines = [""]
    for word in sentence.split():
        if lines[-1] and len(lines[-1]) + 1 + len(word) > limit:
            lines.append(word)
        else:
            lines[-1] = f"{lines[-1]} {word}".strip()
    return lines


def _stack_height(first: int, second: int, cols: int, pitch: float) -> float:
    return (ceil(first / cols) + ceil(second / cols)) * pitch + (pitch * 0.6 if first and second else 0)


def _dot_layout(counts: list[tuple[int, int]], column: float, height: float, table: tuple) -> tuple[float, float, int, float]:
    """The largest dots that fit; the smallest ones if none do (the strip then grows, no dot is hidden)."""
    for pitch, size, per_row in table:
        cols = max(2, min(per_row, floor((column - 2) / pitch)))
        need = max(_stack_height(a, b, cols, pitch) for a, b in counts)
        if need <= height:
            break
    return pitch, size, cols, need


def _dots(n: int, cx: float, base: float, cols: int, pitch: float, size: float, shape: str, hollow: bool) -> list[str]:
    """`n` unit marks in rows, from `base` upward; a short top row is centred."""
    out = []
    for i in range(n):
        row, col = divmod(i, cols)
        in_row = min(cols, n - row * cols)
        out.append(marker(shape, cx + (col - (in_row - 1) / 2) * pitch, base - (row + 0.5) * pitch, "ser-main",
                          size=size * (1 if shape == "circle" else 0.95), hollow=hollow))
    return out


def _key(items: list[tuple], x0: float, y: float, right: float, step: float) -> tuple[list[str], float]:
    """A printed key that wraps: (mark drawing function, label); a label may run over several lines ("\\n").

    Returns the marks and the y of the last line."""
    out: list[str] = []
    x, extra = x0, 0
    for draw, label in items:
        lines = label.split("\n")
        width = 16 + max(text_width(s, 12.5) for s in lines)
        if x + width > right and x > x0:
            x, y, extra = x0, y + step * (1 + extra), 0
        out += [draw(x + 5, y - 4), *(text(x + 15, y + i * (step - 2), s, "f22-k") for i, s in enumerate(lines))]
        extra = max(extra, len(lines) - 1)
        x += width + 14
    return out, y + (step - 2) * extra


def _count(cx: float, y: float, n: int, mark) -> list[str]:
    width = text_width(str(n), 12.5, mono=True)
    return [mark(cx - width / 2 - 6, y - 4), text(cx - width / 2, y, str(n), "f22-n")]


def _bar_mark(x: float, y: float) -> str:
    return f'<rect class="f22-bar" x="{r(x - 4.5)}" y="{r(y - 4.5)}" width="9" height="9"/>'


def _band_mark(x: float, y: float) -> str:
    """The retrospective as in the plot: its line inside its band."""
    return f'<rect class="f22-band" x="{r(x - 6)}" y="{r(y - 4.5)}" width="12" height="9"/>{line(x - 6, y, x + 6, y, "f22-band-c")}'


def _diagonal_mark(x: float, y: float) -> str:
    return line(x - 6, y + 4, x + 6, y - 4, "f22-diag")


def _circle_mark(x: float, y: float) -> str:
    return marker("circle", x, y, "ser-main", size=3.7, hollow=True)


def _diamond_mark(x: float, y: float) -> str:
    return marker("diamond", x, y, "ser-main", size=3.7)


def _band(points: list[dict], x, y) -> list[str]:
    """Retrospective 95 % range as a pale band with its centre line; deliberately no point."""
    coords = [(x(_in_axis(p["vorhergesagt"] * 100)), y(_in_axis(p["ki95"][0] * 100)), y(_in_axis(p["ki95"][1] * 100)),
               y(_in_axis(p["beobachtet"] * 100))) for p in points]
    upper = "L".join(f"{r(px)} {r(hi)}" for px, _, hi, _ in coords)
    lower = "L".join(f"{r(px)} {r(lo)}" for px, lo, _, _ in reversed(coords))
    centre = "L".join(f"{r(px)} {r(mid)}" for px, _, _, mid in coords)
    return [f'<path class="f22-band" d="M{upper}L{lower}Z"/>', f'<path class="f22-band-c" d="M{centre}"/>']


def _ideal(left: float, right: float, top: float, bottom: float, data_max: float) -> str:
    """The word "Ideal" on the diagonal, just above it: at its upper end when the data stay clear of it, else at its lower end."""
    w, h = right - left, bottom - top
    c, s, angle = w / hypot(w, h), h / hypot(w, h), degrees(atan2(h, w))
    near = max(16, 15 / s)  # distance of the word's ends from the corner, along the line; the word stays inside the plot
    far = near + text_width("Ideal", 13)
    if data_max + 10 < right - far * c:
        px, py, anchor = right - near * c, top + near * s, "end"
    else:
        px, py, anchor = left + near * c, bottom - near * s, "start"
    return (f'<text class="f22-ideal" x="{r(px)}" y="{r(py - 4)}" text-anchor="{anchor}" '
            f'transform="rotate({r(-angle)} {r(px)} {r(py)})">Ideal</text>')


def _points(data: dict, phase: str, shape: str, hollow: bool, name: str, x, y, dx: float, bottom: float, top: float,
            columns: list[tuple[float, float]]) -> list[str]:
    """One mark per class with its vertical 95 % range; below the axis floor it sits on the edge with an arrow."""
    out: list[str] = []
    for p in data[phase]["punkte"]:
        px = x(_in_axis(p["vorhergesagt"] * 100)) + dx
        observed = p["beobachtet"] * 100
        lo, hi = p["ki95"] or (p["beobachtet"], p["beobachtet"])
        y_lo, y_hi = y(_in_axis(lo * 100)), y(_in_axis(hi * 100))
        d = f"M{r(px)} {r(y_lo)}V{r(y_hi)}"
        if lo * 100 >= AXIS[0]:
            d += f"M{r(px - 3)} {r(y_lo)}H{r(px + 3)}"
        if hi * 100 <= AXIS[1]:
            d += f"M{r(px - 3)} {r(y_hi)}H{r(px + 3)}"
        out.append(f'<path class="ch-wh ser-main" d="{d}"/>')
        at = y(_in_axis(observed))
        if observed < AXIS[0]:
            at = bottom - 13
            out.append(f'<path class="f22-arrow" d="M{r(px - 3.5)} {r(bottom - 5)}H{r(px + 3.5)}L{r(px)} {r(bottom)}Z"/>')
        elif observed > AXIS[1]:
            at = top + 13
            out.append(f'<path class="f22-arrow" d="M{r(px - 3.5)} {r(top + 5)}H{r(px + 3.5)}L{r(px)} {r(top)}Z"/>')
        label = _class_name(data, p["klassen"])
        tip = (f'{name}, {label}: vorhergesagt {num(p["vorhergesagt"] * 100, 1)} %, eingetroffen {num(observed, 1)} % '
               f'(95-%-Bereich {_span(lo, hi)} %), {num(p["n"])} Fälle, {num(p["wirkstoffe"])} Wirkstoffe')
        if len(p["klassen"]) > 1:
            out.append(line(columns[p["klassen"][0]][0] + 3, at, columns[p["klassen"][-1]][1] - 3, at, "f22-pool"))
        out.append(marker(shape, px, at, "ser-main", size=4.6, hollow=hollow, title=tip))
    return out


def status_sentence(data: dict) -> str | None:
    """What panel b is waiting for, when it is not yet showing that phase."""
    if not data["protokoll_bis"]:
        return "Noch keine Protokolle"
    einlauf, pruefung = data["einlauf"], data["pruefung"]
    if einlauf["zu_wenige"] or pruefung["zu_wenige"]:
        return "Noch zu wenige Fälle"
    if not einlauf["punkte"] and einlauf["naechster_termin"]:
        return f'Erste Punkte der Einlaufphase am {_day(einlauf["naechster_termin"])}'
    if not pruefung["punkte"] and pruefung["naechster_termin"]:
        return f'Erste Punkte der Prüfung am {_day(pruefung["naechster_termin"])}'
    return None


def f22(data: dict, *, width: int, uid: str) -> str:
    """The figure as one SVG; from `WIDE` on with full labels, below that with the short class names."""
    wide = width >= WIDE
    left, right = (50, width - 10) if wide else (34, width - 4)
    x = Log(AXIS, (left, right))
    edges = [AXIS[0], *(e * 100 for e in data["grenzen"]), AXIS[1]]
    columns = [(x(a), x(b)) for a, b in zip(edges, edges[1:])]
    centres = [(a + b) / 2 for a, b in columns]
    weeks = data["horizont_tage"] // 7
    heute = data["heute"]
    counts = list(zip(data["einlauf"]["meldungen"]["je_klasse"], data["pruefung"]["meldungen"]["je_klasse"]))

    # panel a: title and key
    body: list[str] = [f'<text class="f22-l" x="0" y="15">a</text>']
    if wide:
        body.append(text(16, 15, "Wo standen neu gemeldete Wirkstoffe am Tag davor?", "f22-t"))
        key_y = 35
    else:
        body += [text(14, 15, "Wo standen neu gemeldete", "f22-t"), text(14, 32, "Wirkstoffe am Tag davor?", "f22-t")]
        key_y = 52
    # Dots count every log day; the test itself scores only its 14-day Stichtage, so the label must not call them test cases.
    names = ("neu gemeldet, Einlaufphase", "neu gemeldet, ab Prüfungsbeginn", "alle Wirkstoffe, Anteil je Klasse") if wide else (
             "neu: Einlaufphase", "neu: ab Prüfungsbeginn", "alle Wirkstoffe")
    key, key_y = _key([(_circle_mark, names[0]), (_diamond_mark, names[1]), (_bar_mark, names[2])],
                      left if wide else 0, key_y, right, 17)
    body += key

    # panel a: dots above the shared line, bars hanging below it
    strip_top = key_y + 10
    dots_h = 104 if wide else 92
    bars_h = 46 if wide else 38
    label_h = 32 if any(b for _, b in counts) and not wide else 18
    pitch, size, cols, need = _dot_layout(counts, min(b - a for a, b in columns), dots_h - label_h, DOTS_WIDE if wide else DOTS_NARROW)
    dots_h = max(dots_h, need + label_h)
    base = strip_top + dots_h
    class_y = base + bars_h + (31 if wide else 29)
    for i, (a, b) in enumerate(columns):
        if i % 2:
            body.append(f'<rect class="f22-col" x="{r(a)}" y="{r(strip_top)}" width="{r(b - a)}" height="{r(class_y + 7 - strip_top)}"/>')
    body += [line(a, strip_top, a, base + bars_h + 17, "f22-edge") for a, _ in columns[1:]]
    for i, (cx, (a, b)) in enumerate(zip(centres, columns)):
        share = heute["je_klasse"][i] / heute["wirkstoffe"] if heute["wirkstoffe"] else 0.0
        bar = min(share / BAR_MAX, 1) * bars_h
        percent = (num(share * 100) + (" %" if wide or i == 0 else "")) if heute["wirkstoffe"] else "–"  # narrow: unit once
        half = min((b - a) / 2 - 3, 26 if wide else 12)
        if bar > 0:
            body.append(f'<rect class="f22-bar" x="{r(cx - half)}" y="{r(base)}" width="{r(2 * half)}" height="{r(bar)}"/>')
        body.append(text(cx, base + bar + 13, percent, "f22-s", "middle"))
        first, second = counts[i]
        body += _dots(first, cx, base - 1, cols, pitch, size, "circle", True)
        gap = ceil(first / cols) * pitch + (pitch * 0.6 if first and second else 0)
        body += _dots(second, cx, base - 1 - gap, cols, pitch, size, "diamond", False)
        top = base - _stack_height(first, second, cols, pitch) - 6
        if second:  # the two phases are never added up: each count carries its own mark
            if wide:
                body += _count(cx - 18, top, first, _circle_mark) + _count(cx + 18, top, second, _diamond_mark)
            else:
                body += _count(cx, top, second, _diamond_mark) + _count(cx, top - 14, first, _circle_mark)
        else:
            body.append(text(cx, top, str(first), "f22-n", "middle"))
    body.append(line(left, base, right, base, "f22-base"))
    # what lies above and below the shared line, in the free space left of the first class
    above, below = ("neu gemeldet", "alle Wirkstoffe") if wide else ("neu", "alle")
    body += [text(0, base - 7, above, "f22-k"), text(0, base + 16, below, "f22-k")]
    for i, cx in enumerate(centres):
        body.append(text(cx, class_y, data["klassen"][i]["name" if wide else "kurz"], "f22-c", "middle"))

    # panel b: calibration on log axes, with its key above the plot so that no data point can ever run into it
    title_y = class_y + (27 if wide else 25)
    body.append(f'<text class="f22-l" x="0" y="{r(title_y)}">b</text>')
    if wide:
        body.append(text(16, title_y, f"Wie oft kam binnen {weeks} Wochen wirklich eine Meldung?", "f22-t"))
        key_y = title_y + 20
        legend = [(_band_mark, "Rückblick 2026 · simuliert · nicht validiert · Band: 95-%-Bereich"),
                  (_diagonal_mark, "Ideal: so oft wie vorhergesagt"), (_circle_mark, "Einlaufphase · zählt nicht für die Prüfung"),
                  (_diamond_mark, "Prüfung · vorab festgelegt · Zwischenstand, kein Urteil")]
    else:
        body += [text(14, title_y, f"Wie oft kam binnen {weeks} Wochen", "f22-t"), text(14, title_y + 17, "wirklich eine Meldung?", "f22-t")]
        key_y = title_y + 37
        legend = [(_band_mark, "Rückblick 2026 · simuliert\nBand: 95-%-Bereich"), (_diagonal_mark, "Ideal: so oft wie vorhergesagt"),
                  (_circle_mark, "Einlaufphase"), (_diamond_mark, "Prüfung")]
    key, key_y = _key(legend, left if wide else 0, key_y, right, 17)
    body += key

    # notes on the state of the points stand under the key, so that the plot keeps its corners for the two halves
    note = status_sentence(data)
    pooled = any(len(p["klassen"]) > 1 for ph in ("einlauf", "pruefung") for p in data[ph]["punkte"])
    notes = [*(_wrap("Waagrechte Linie: Klassen zusammengelegt", 200 if wide else 44) if pooled else []),
             *(_wrap(note, 200 if wide else 44) if note else [])]
    for part in notes:
        key_y += 20
        body.append(text(left if wide else 0, key_y, part, "f22-note"))

    plot_top = key_y + 29
    bottom = plot_top + (208 if wide else 190)
    y = Log(AXIS, (bottom, plot_top))
    for i, (a, b) in enumerate(columns):
        if i % 2:
            body.append(f'<rect class="f22-col" x="{r(a)}" y="{r(plot_top)}" width="{r(b - a)}" height="{r(bottom - plot_top)}"/>')
    body.append(y_axis(y, left, right=right, ticks=Y_TICKS, fmt=_tick, label="Anteil mit neuer Meldung, in %"))
    body += [line(a, plot_top, a, bottom, "f22-edge") for a, _ in columns[1:]]
    body.append(x_axis(x, bottom, ticks=X_TICKS, fmt=_tick,
                       label="vorhergesagte Wahrscheinlichkeit einer neuen Meldung, in %" if wide else "vorhergesagte Wahrscheinlichkeit, in %"))
    # the two halves, quiet and behind the data: above the diagonal reports came more often than predicted
    body += [text(left + 8, plot_top + 16, "häufiger als vorhergesagt", "f22-half"),
             text(right - 8, bottom - 10, "seltener als vorhergesagt", "f22-half", "end")]
    band = data["rueckblick"]["punkte"] if data["rueckblick"] else []
    if band:
        body += _band(band, x, y)
    body.append(line(x(AXIS[0]), y(AXIS[0]), x(AXIS[1]), y(AXIS[1]), "f22-diag"))
    data_x = [x(_in_axis(p["vorhergesagt"] * 100)) for p in [*band, *data["einlauf"]["punkte"], *data["pruefung"]["punkte"]]]
    body.append(_ideal(left, right, plot_top, bottom, max(data_x, default=left)))

    both = bool(data["einlauf"]["punkte"] and data["pruefung"]["punkte"])
    for (phase, shape, hollow, name), dx in zip(PHASES, (-3, 3) if both else (0, 0)):
        body += _points(data, phase, shape, hollow, name, x, y, dx, bottom, plot_top, columns)

    e, p = data["einlauf"], data["pruefung"]
    desc = (f'Feld a: Von {num(heute["wirkstoffe"])} Wirkstoffen am letzten Protokolltag liegen je Klasse '
            + ", ".join(f'{k["name"]}: {num(n)}' for k, n in zip(data["klassen"], heute["je_klasse"]))
            + f'. Neu gemeldet in der Einlaufphase: {num(e["meldungen"]["anzahl"])}, je Klasse '
            + ", ".join(str(n) for n in e["meldungen"]["je_klasse"])
            + f'; ab Prüfungsbeginn: {num(p["meldungen"]["anzahl"])}. Feld b: Reife {weeks}-Wochen-Fälle in der Einlaufphase '
            + f'{num(e["faelle"])}, in der Prüfung {num(p["faelle"])}. Rückblick 2026 simuliert und nicht validiert.'
            + (f" {note}." if note else ""))
    return frame("f22", width, bottom + 46, uid, "Vorhersage gegen Meldung", desc, body)
