"""Charts of the situation block and the early-warning page: F01, F05, F06, F35. Pure functions of their data."""
from __future__ import annotations

from html import escape
from math import ceil

from . import WIDE, Linear, frame, line, marker, num, pct, r, text, whisker, x_axis


def _rect(x: float, y: float, w: float, h: float, cls: str, rx: float = 0) -> str:
    corner = f' rx="{r(rx)}"' if rx else ""
    return f'<rect class="{cls}" x="{r(x)}" y="{r(y)}" width="{r(max(w, 0))}" height="{r(h)}"{corner}/>'


def _row(title: str, body: list[str]) -> str:
    """One readable unit of a chart with a native tooltip."""
    return f'<g class="ch-row"><title>{escape(title, quote=False)}</title>{"".join(body)}</g>'


def _cut(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


# --- F01: status of the listed packages, and active reports per ATC main group ------------------

def _f01_status(data: dict, width: int, wide: bool) -> tuple[list[str], float]:
    """Stacked status bar with a bracket over the active statuses and a legend; returns the marks and the end y."""
    status, total, gap = data["status"], data["total"], 2
    head, bracket_y, bar_y, bar_h = 14, 22 if wide else 38, 26 if wide else 42, 18
    usable = width - gap * (len(status) - 1)
    body = [text(0, head, "Gelistete Packungen nach Status", "ch-lbl ch-strong"),
            text(width, head, f'{num(total)} gesamt', "f01-k", "end")]
    x, spans = 0.0, []
    for s in status:
        w = usable * s["n"] / total
        spans.append((s, x, x + w))
        body.append(_row(f'{s["name"]}: {num(s["n"])} Packungen', [_rect(x, bar_y, w, bar_h, f'f01-seg {s["cls"]}')]))
        x += w + gap
    active = [(a, b) for s, a, b in spans if s["active"]]
    if active:
        a, b = active[0][0], active[-1][1]
        body.append(f'<path class="f01-brace" d="M{r(a + .5)} {r(bracket_y + 3)}V{r(bracket_y)}H{r(b - .5)}V{r(bracket_y + 3)}"/>')
        body.append(text(b, head if wide else bracket_y - 5, f'{num(data["active"])} aktiv eingeschränkt', "f01-k f01-act", "end"))
    y = bar_y + bar_h
    if wide:
        cell = width / len(status)
        for i, s in enumerate(status):
            cx = i * cell
            body.append(_rect(cx, y + 10, 12, 12, f'f01-seg {s["cls"]}'))
            body += [text(cx + 18, y + 20, s["name"], "f01-k"), text(cx + 18, y + 37, num(s["n"]), "ch-val")]
        return body, y + 37
    for i, s in enumerate(status):
        row_y = y + 22 + i * 20
        body.append(_rect(0, row_y - 10, 12, 12, f'f01-seg {s["cls"]}'))
        body += [text(18, row_y, s["name"], "f01-k"), text(width, row_y, num(s["n"]), "ch-val", "end")]
    return body, y + 22 + 3 * 20


def _f01_group(g: dict, x: float, y: float, label_x: float, bar: Linear, end: float) -> str:
    code = [text(x, y + 4, g["code"], "f01-c")] if g["code"] else []
    fill = "f01-bar f01-rest" if not g["code"] else "f01-bar"
    return _row(f'{g["full"]}: {num(g["n"])} Packungen',
                [*code, text(label_x, y + 4, g["short"], "f01-g"), _rect(bar.range[0], y - 4, max(bar(g["n"]) - bar.range[0], 2), 8, fill, 1),
                 text(end, y + 4, num(g["n"]), "ch-val", "end")])


def f01(data: dict, *, width: int, uid: str) -> str:
    """F01: one stacked status bar (patterns as on the package timelines) and ranked bars per ATC main group."""
    wide = width >= WIDE
    body, y = _f01_status(data, width, wide)
    groups = data["groups"]
    top = max(g["n"] for g in groups)
    head = y + 30
    body.append(text(0, head, "Aktiv eingeschränkt nach ATC-Hauptgruppe", "ch-lbl ch-strong"))
    first = head + 20
    if wide:  # all groups, ranked down the first column and on through the second, on one scale
        rows, col_w, gutter = ceil(len(groups) / 2), 346, 28
        for c in range(2):
            x0 = c * (col_w + gutter)
            bar = Linear((0, top), (x0 + 182, x0 + col_w - 36))
            for i, g in enumerate(groups[c * rows:(c + 1) * rows]):
                body.append(_f01_group(g, x0, first + i * 19, x0 + 20, bar, x0 + col_w))
        height = first + (rows - 1) * 19 + 12
    else:  # phone: the largest groups and the rest as one row; every group stays in the table below the figure
        shown = groups if len(groups) <= 8 else groups[:7]
        rest = groups[len(shown):]
        if rest:
            shown = [*shown, {"code": "", "short": f"Übrige {len(rest)} Gruppen",
                              "full": "Übrige Gruppen: " + ", ".join(g["short"] for g in rest), "n": sum(g["n"] for g in rest)}]
        bar = Linear((0, max(g["n"] for g in shown)), (172, width - 34))
        for i, g in enumerate(shown):
            body.append(_f01_group(g, 0, first + i * 21, 18, bar, width))
        height = first + (len(shown) - 1) * 21 + 12
    desc = ("Status der gelisteten Packungen: " + ", ".join(f'{s["name"]} {num(s["n"])}' for s in data["status"]) + ". "
            "Aktiv eingeschränkte Packungen je ATC-Hauptgruppe: " + ", ".join(f'{g["short"]} {num(g["n"])}' for g in groups) + ".")
    return frame("f01", width, height, uid, "Lage nach Status und ATC-Hauptgruppe", desc, body)


# --- F05: how often a BASG report followed a hint ------------------------------------------------

def _f05_row(t: dict, key: str, y: float, x: Linear, val_x: float) -> list[str]:
    rate = t[key]
    lo, hi = rate["ki95"]
    shape, series, hollow = ("square", "ser-base", True) if t["id"] == "1" else ("circle", "ser-main", False)
    tip = (f'{t["name"]}: {pct(rate["quote"])} (95-%-Bereich {pct(lo)} bis {pct(hi)}), '
           f'{num(rate["treffer"])} von {num(rate["faelle"])} Fällen')
    return [whisker(x(lo * 100), x(hi * 100), y, series), marker(shape, x(rate["quote"] * 100), y, series, hollow=hollow, title=tip),
            text(val_x, y + 4.5, pct(rate["quote"]), "ch-val", "end")]


def _f05_ref(x: Linear, value: float, top: float, bottom: float) -> list[str]:
    px = x(value * 100)
    label = f"Vergleich {pct(value)}"
    left = max(px, x.range[0] + 50)  # the label stays over its panel
    return [line(px, top, px, bottom, "ch-ref f05-ref"), text(left, top - 6, label, "f05-rl", "middle")]


def f05(data: dict, *, width: int, uid: str) -> str:
    """F05: forest plot of the hit rates per tier within 8 and 12 weeks; the vertical line is the comparison group."""
    tiers, horizons = data["tiers"], data["horizonte"]
    top = max(30, ceil(max(t[h["key"]]["ki95"][1] for t in tiers for h in horizons) * 20) * 5)
    ticks = range(0, top + 1, 10)
    body: list[str] = []
    if width >= WIDE:
        row_y = [62 + i * 32 for i in range(len(tiers))]
        axis_y = row_y[-1] + 24
        for t, y in zip(tiers, row_y):
            body.append(text(0, y + 5, t["name"], "ch-lbl ch-strong" if t["id"] == "A" else "ch-lbl"))
        for i, h in enumerate(horizons):
            x0 = 192 + i * 272
            x = Linear((0, top), (x0, x0 + 186))
            val_x = x0 + 248
            body.append(text((x0 + x0 + 186) / 2, 15, h["name"], "ch-col", "middle"))
            body.append(x_axis(x, axis_y, top=44, ticks=ticks, label="Anteil mit BASG-Meldung, in %"))
            body += _f05_ref(x, h["base"], 44, axis_y)
            for t, y in zip(tiers, row_y):
                body += _f05_row(t, h["key"], y, x, val_x)
        height = axis_y + 42
    else:
        y0 = 0.0
        for h in horizons:
            x = Linear((0, top), (106, width - 58))
            body.append(text(0, y0 + 15, h["name"], "ch-col"))
            row_y = [y0 + 58 + i * 28 for i in range(len(tiers))]
            axis_y = row_y[-1] + 20
            body.append(x_axis(x, axis_y, top=y0 + 40, ticks=ticks))
            body += _f05_ref(x, h["base"], y0 + 40, axis_y)
            for t, y in zip(tiers, row_y):
                body.append(text(0, y + 5, t["short"], "ch-lbl ch-strong" if t["id"] == "A" else "ch-lbl"))
                body += _f05_row(t, h["key"], y, x, width)
            y0 = axis_y + 38
        body.append(text((106 + width - 58) / 2, y0, "Anteil mit BASG-Meldung, in %", "ch-axt", "middle"))
        height = y0 + 6
    parts = "; ".join(f'{t["name"]}: {h["name"]} {pct(t[h["key"]]["quote"])}' for t in tiers for h in horizons)
    base = ", ".join(f'{h["name"]} {pct(h["base"])}' for h in horizons)
    desc = f"Anteil der Hinweise, auf die eine BASG-Meldung folgte. {parts}. Vergleichsgruppe: {base}. Rückblick, nicht validiert."
    return frame("f05", width, height, uid, "Wie oft folgte auf einen Hinweis eine BASG-Meldung?", desc, body)


# --- F06: which countries report the substances of tier A ----------------------------------------

def f06(data: dict, *, width: int, uid: str) -> str:
    """F06: dot matrix of the tier-A substances with the most countries (rows) by reporting country (columns)."""
    rows, cols = data["rows"], data["columns"]
    wide = width >= WIDE
    x0, x1, limit, step, dot = (262, width - 58, 33, 23, 4.75) if wide else (118, width - 7, 15, 22, 4)
    col_x = {c["code"]: x0 + (x1 - x0) * (i / max(len(cols) - 1, 1)) for i, c in enumerate(cols)}
    head, first = 16, 36
    total_y = first + len(rows) * step + 4
    body: list[str] = []
    for c in cols:
        body.append(_row(f'{c["name"]}: {num(c["n"])} von {num(len(rows))}', [text(col_x[c["code"]], head, c["code"], "f06-c", "middle")]))
        body.append(line(col_x[c["code"]], head + 6, col_x[c["code"]], total_y - 12, "ch-grid"))
    if wide:
        body.append(text(width, head, "Länder", "ch-col", "end"))
    for i, row in enumerate(rows):
        y = first + i * step
        marks = [text(0, y + 4.5, _cut(row["label"], limit), "f06-l")]
        marks += [marker("circle", col_x[c], y, "ser-main", size=dot) for c in row["countries"] if c in col_x]
        if wide:
            marks.append(text(width, y + 4.5, num(len(row["countries"])), "ch-val", "end"))
        body.append(_row(f'{row["label"]}: gemeldet in {", ".join(row["names"])}', marks))
    body.append(line(0, total_y - 12, width, total_y - 12, "ch-axis"))
    body.append(text(0, total_y + 4, f'Von {num(len(rows))}', "f01-k"))
    body += [text(col_x[c["code"]], total_y + 4, num(c["n"]), "f06-n", "middle") for c in cols]
    desc = (f'{num(len(rows))} Wirkstoffe der Stufe A mit den meisten meldenden Ländern. Je Land: '
            + ", ".join(f'{c["name"]} {num(c["n"])}' for c in cols) + ".")
    return frame("f06", width, total_y + 12, uid, "Welche Länder melden die Wirkstoffe der Stufe A?", desc, body)


# --- F35: running reports per country -------------------------------------------------------------

def f35(data: list[dict], *, width: int, uid: str) -> str:
    """F35: one tile per public country list: running reports and substances with an Austrian package."""
    cols = 4 if width >= WIDE else 2
    gap, tile_h = 8, 88
    tile_w = (width - gap * (cols - 1)) / cols
    top = max(c["at"] for c in data) or 1
    body: list[str] = []
    for i, c in enumerate(data):
        x, y = (i % cols) * (tile_w + gap), (i // cols) * (tile_h + gap)
        track = tile_w - 20
        body.append(_row(f'{c["name"]}: {num(c["reports"])} laufende Meldungen, {num(c["substances"])} Wirkstoffe, '
                         f'davon {num(c["at"])} mit österreichischer Packung', [
            _rect(x, y, tile_w, tile_h, "f35-tile", 6),
            text(x + 10, y + 20, c["name"], "f35-n"),
            text(x + 10, y + 45, num(c["reports"]), "f35-v"),
            text(x + tile_w - 10, y + 45, "Meldungen", "f35-s", "end"),
            _rect(x + 10, y + 54, track, 5, "f35-track", 2),
            _rect(x + 10, y + 54, track * c["at"] / top, 5, "f35-bar", 2),
            text(x + 10, y + 77, f'{num(c["at"])} Wirkstoffe in AT', "f35-s"),
        ]))
    rows = ceil(len(data) / cols)
    desc = "Laufende Meldungen je Land: " + ", ".join(f'{c["name"]} {num(c["reports"])}' for c in data) + "."
    return frame("f35", width, rows * tile_h + (rows - 1) * gap, uid, "Laufende Meldungen je Land", desc, body)
