"""Charts of the pages "Idee und Aufbau" and "Methodik": pipeline (F16), versions per source (F21), archive barcode
with thinning (F29). Pure functions of the dictionaries built in `seiten/idee.py`; the package timeline F04 comes from
`timeline.py`.
"""
from __future__ import annotations

from datetime import date

from . import WIDE, Linear, frame, line, num, r, text, whisker, x_axis


def _rect(x: float, y: float, w: float, h: float, cls: str, rx: float = 0) -> str:
    rad = f' rx="{r(rx)}"' if rx else ""
    return f'<rect class="{cls}" x="{r(x)}" y="{r(y)}" width="{r(w)}" height="{r(h)}"{rad}/>'


def _arrow(points: list[tuple[float, float]], cls: str = "arc-path") -> str:
    """Axis-aligned path with a triangular head at its last point."""
    (x0, y0), (x1, y1) = points[-2], points[-1]
    dx, dy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
    head = 6.5
    bx, by = x1 - dx * head, y1 - dy * head
    way = [*points[:-1], (bx, by)]
    d = "M" + "L".join(f"{r(x)} {r(y)}" for x, y in way)
    s = 3.6
    tip = (f"M{r(x1)} {r(y1)}L{r(bx - dy * s)} {r(by + dx * s)}L{r(bx + dy * s)} {r(by - dx * s)}Z")
    return f'<path class="{cls}" d="{d}"/><path class="arc-head" d="{tip}"/>'


def _wrap(items: list[str], limit: int) -> list[str]:
    """Join names with commas into lines of at most `limit` characters."""
    lines, cur = [], ""
    for i, item in enumerate(items):
        piece = item + ("," if i < len(items) - 1 else "")
        if cur and len(cur) + 1 + len(piece) > limit:
            lines.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}" if cur else piece
    return [*lines, cur] if cur else lines


def _box(x: float, y: float, w: float, h: float, title: str, lines: tuple[str, ...]) -> list[str]:
    out = [_rect(x, y, w, h, "arc-sub", 4), text(x + 8, y + 19, title, "arc-t")]
    return out + [text(x + 8, y + 36 + i * 15, s, "arc-s") for i, s in enumerate(lines)]


def _head(x: float, y: float, n: int, verb: str, what: str, w: float) -> list[str]:
    return [text(x + 10, y + 22, f"{n}  {verb}", "arc-h"), text(x + w - 10, y + 22, what, "arc-s", "end")]


def _pairs(x: float, y: float, w: float, rows: list[tuple[str, str]], pitch: float = 22) -> list[str]:
    out = []
    for i, (label, value) in enumerate(rows):
        yy = y + i * pitch
        out += [line(x, yy + 7, x + w, yy + 7, "arc-rule"), text(x, yy, label, "arc-s"), text(x + w, yy, value, "arc-n", "end")]
    return out


def _f16_rows(d: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    archive = [("Fassungen", num(d["fassungen"])), ("davon BASG", num(d["fassungen_basg"]))] if d["fassungen"] is not None else []
    base = [("BASG-Stände", num(d["staende"])), ("Packungen", num(d["packungen"])), ("Episoden", num(d["episoden"]))]
    return archive, base


FW_LINES = ("Stufen nach", "Länderzahl")
WEB_LINES = ("statisch, ohne", "Cookies")


def _f16_wide(d: dict, w: int) -> tuple[list[str], float]:
    n = len(d["auslandslisten"])
    p = [_rect(1, 1, w - 2, 86, "arc-src", 6), text(12, 21, "Öffentliche Quellen", "arc-lg")]
    p += [text(12, 43, "BASG", "arc-t"), text(12, 60, "Engpassmeldungen", "arc-s")]
    p += [text(176, 43, "Register", "arc-t"), text(176, 60, "ASP-Liste, Erstattungskodex,", "arc-s"), text(176, 75, "EudraGMDP", "arc-s")]
    p.append(text(382, 43, f"{num(n)} Auslandslisten", "arc-t"))
    p += [text(382, 60 + i * 15, s, "arc-s") for i, s in enumerate(_wrap(d["auslandslisten"], 52)[:2])]

    gap, top, h = 16, 112, 214
    mw = (w - 2 - 3 * gap) / 4
    xs = [1 + i * (mw + gap) for i in range(4)]
    for x, (no, verb, what) in zip(xs, ((1, "Sichern", "Archiv"), (2, "Verknüpfen", "Datenbank"), (3, "Schätzen", "Modelle"), (4, "Zeigen", "Ausgabe"))):
        p.append(_rect(x, top, mw, h, "arc-mod", 6))
        p += _head(x, top, no, verb, what, mw)
    archive, base = _f16_rows(d)
    p += [text(xs[0] + 10, top + 56 + i * 16, s, "arc-s") for i, s in enumerate(("jede neue Fassung", "byte-genau, SHA-256,", "Manifest nur anhängend"))]
    p += _pairs(xs[0] + 10, top + 148, mw - 20, archive)
    p += [text(xs[1] + 10, top + 56 + i * 16, s, "arc-s") for i, s in enumerate(("jedes Mal neu aus", "dem Archiv gebaut"))]
    p += _pairs(xs[1] + 10, top + 126, mw - 20, base)

    ya, yb, bh = top + 42, top + 136, 66
    bx, bw = 8, mw - 16
    p += _box(xs[2] + bx, ya, bw, bh, "Frühwarnliste", FW_LINES)
    p += _box(xs[2] + bx, yb, bw, bh, "Z3-Schätzung", ("eingefroren", d["eingefroren"]))
    p += _box(xs[3] + bx, ya, bw, bh, "Website", WEB_LINES)
    p += _box(xs[3] + bx, yb, bw, bh, "Tagesprotokoll", ("zählt ab", d["zaehlt_ab"]))

    mid = top + h / 2
    p.append(_arrow([(xs[0] + mw / 2, 87), (xs[0] + mw / 2, top)]))
    p.append(_arrow([(xs[0] + mw, mid), (xs[1], mid)]))
    for y in (ya + bh / 2, yb + bh / 2):
        p.append(_arrow([(xs[1] + mw, y), (xs[2] + bx, y)]))
        p.append(_arrow([(xs[2] + bx + bw, y), (xs[3] + bx, y)]))
    cx = xs[3] + mw / 2 - 30
    p.append(_arrow([(cx, yb), (cx, ya + bh)], "arc-path arc-dash"))
    p.append(text(cx + 7, (ya + bh + yb) / 2 + 4, "nur Summen", "arc-s"))
    by = 99  # the database also feeds the website directly, above module 3
    bxx = xs[3] + 92  # between the two words of the module head
    p.append(_arrow([(xs[1] + mw / 2, top), (xs[1] + mw / 2, by), (bxx, by), (bxx, ya)]))
    return p, top + h + 2


def _f16_narrow(d: dict, w: int) -> tuple[list[str], float]:
    x, mw = 14, w - 15
    names = _wrap(d["auslandslisten"], 38)
    src_h = 129 + len(names) * 15
    p = [_rect(x, 1, mw, src_h, "arc-src", 6), text(x + 10, 21, "Öffentliche Quellen", "arc-lg")]
    p += [text(x + 10, 43, "BASG", "arc-t"), text(x + 54, 43, "Engpassmeldungen", "arc-s")]
    p += [text(x + 10, 65, "Register", "arc-t"), text(x + 10, 81, "ASP-Liste, Erstattungskodex,", "arc-s"), text(x + 10, 96, "EudraGMDP", "arc-s")]
    p.append(text(x + 10, 118, f'{num(len(d["auslandslisten"]))} Auslandslisten', "arc-t"))
    p += [text(x + 10, 134 + i * 15, s, "arc-s") for i, s in enumerate(names)]

    archive, base = _f16_rows(d)
    gap = 22
    y1 = src_h + 1 + gap
    h1 = 92 + 22 * len(archive)
    p.append(_arrow([(x + mw / 2, src_h + 1), (x + mw / 2, y1)]))
    p += [_rect(x, y1, mw, h1, "arc-mod", 6), *_head(x, y1, 1, "Sichern", "Archiv", mw)]
    p += [text(x + 10, y1 + 44, "jede neue Fassung byte-genau,", "arc-s"), text(x + 10, y1 + 60, "SHA-256, Manifest nur anhängend", "arc-s")]
    p += _pairs(x + 10, y1 + 86, mw - 20, archive)

    y2 = y1 + h1 + gap
    h2 = 76 + 22 * len(base)
    p.append(_arrow([(x + mw / 2, y1 + h1), (x + mw / 2, y2)]))
    p += [_rect(x, y2, mw, h2, "arc-mod", 6), *_head(x, y2, 2, "Verknüpfen", "Datenbank", mw)]
    p.append(text(x + 10, y2 + 44, "jedes Mal neu aus dem Archiv", "arc-s"))
    p += _pairs(x + 10, y2 + 70, mw - 20, base)

    bh, inner = 74, 8
    bw = (mw - 2 * inner - 18) / 2
    bl, br = x + inner, x + inner + bw + 18
    y3 = y2 + h2 + gap
    h3 = bh + 46
    cl, cr = bl + bw - 16, br + bw / 2  # the arrows run beside the words of the module heads
    p += [_rect(x, y3, mw, h3, "arc-mod", 6), *_head(x, y3, 3, "Schätzen", "Modelle", mw)]
    p += [_arrow([(c, y2 + h2), (c, y3 + 36)]) for c in (cl, cr)]
    p += _box(bl, y3 + 36, bw, bh, "Frühwarnliste", FW_LINES)
    p += _box(br, y3 + 36, bw, bh, "Z3-Schätzung", ("eingefroren", d["eingefroren"]))

    y4 = y3 + h3 + gap
    h4 = bh + 68
    p += [_rect(x, y4, mw, h4, "arc-mod", 6), *_head(x, y4, 4, "Zeigen", "Ausgabe", mw)]
    for c in (cl, cr):
        p.append(_arrow([(c, y3 + 36 + bh), (c, y4 + 36)]))
    p += _box(bl, y4 + 36, bw, bh, "Website", WEB_LINES)
    p += _box(br, y4 + 36, bw, bh, "Protokoll", ("zählt ab", d["zaehlt_ab"]))
    my = y4 + 36 + bh / 2
    p.append(_arrow([(br, my), (bl + bw, my)], "arc-path arc-dash"))
    p.append(text(x + 10, y4 + 36 + bh + 21, "Protokoll an Website: nur Summen", "arc-s"))
    mid2 = y2 + h2 / 2  # the database also feeds the website directly, along the left edge
    p.append(_arrow([(x, mid2), (5, mid2), (5, my), (bl, my)]))
    return p, y4 + h4 + 2


def f16(data: dict, *, width: int, uid: str) -> str:
    """F16: from the public sources through archive and database to the website and the daily log."""
    body, height = _f16_wide(data, width) if width >= WIDE else _f16_narrow(data, width)
    listen = ", ".join(data["auslandslisten"])
    fassungen = f'{num(data["fassungen"])} Fassungen, ' if data["fassungen"] is not None else ""
    desc = (f"Vier Schritte. Quellen: BASG, ASP-Liste, Erstattungskodex, EudraGMDP und Auslandslisten ({listen}). "
            f'1 Sichern im Archiv: {fassungen}byte-genau mit SHA-256. 2 Verknüpfen in der Datenbank: {num(data["staende"])} BASG-Stände, '
            f'{num(data["packungen"])} Packungen, {num(data["episoden"])} Episoden. 3 Schätzen: Frühwarnliste und eingefrorene Z3-Schätzung. '
            "4 Zeigen: Die Website erhält Datenbank und Frühwarnliste; die Z3-Schätzung geht ins Tagesprotokoll, an die Website nur als Summen.")
    return frame("pipe", width, height, uid, "Aufbau des Radars in vier Schritten", desc, body)


def f21(data: dict, *, width: int, uid: str) -> str:
    """F21: ranked bars, archived versions per public source. `data["zeilen"]`: label, versionen, haupt."""
    rows = data["zeilen"]
    top = max((z["versionen"] for z in rows), default=1) or 1
    wide = width >= WIDE
    body: list[str] = []
    if wide:
        pitch, x0, x1 = 24, 244, width - 56
        x = Linear((0, top), (x0, x1))
        for i, z in enumerate(rows):
            y = 14 + i * pitch
            strong = " ch-strong" if z["haupt"] else ""
            body += [text(8, y + 5, z["label"], f"arc-bl{strong}"), line(x0, y - 9, x0, y + 9, "ch-axis"),
                     _rect(x0, y - 6, max(x(z["versionen"]) - x0, 1.5), 12, "arc-bar on" if z["haupt"] else "arc-bar"),
                     text(x(z["versionen"]) + 6, y + 5, num(z["versionen"]), f"ch-val{strong}")]
        height = 14 + len(rows) * pitch
    else:
        pitch, x0, x1 = 34, 2, width - 2
        x = Linear((0, top), (x0, x1))
        for i, z in enumerate(rows):
            y = 15 + i * pitch
            strong = " ch-strong" if z["haupt"] else ""
            body += [text(x0, y, z["label"], f"arc-bl{strong}"), text(x1, y, num(z["versionen"]), f"ch-val{strong}", "end"),
                     _rect(x0, y + 6, x1 - x0, 7, "arc-bar-t"),
                     _rect(x0, y + 6, max(x(z["versionen"]) - x0, 1.5), 7, "arc-bar on" if z["haupt"] else "arc-bar")]
        height = 8 + len(rows) * pitch
    desc = "Archivierte neue Fassungen je Quelle: " + "; ".join(f'{z["label"]} {num(z["versionen"])}' for z in rows) + "."
    return frame("bars", width, height, uid, "Archivierte Fassungen je Quelle", desc, body)


LANES = (("wayback", "Internet Archive"), ("legacy_local", "Altdatei"), ("live", "Täglicher Abruf"))


def _ticks(snaps: list[dict], x: Linear, y: float, h: float) -> list[str]:
    out = []
    for s in snaps:
        xx = x(s["tag"].toordinal())
        out.append(_rect(xx - 1, y, 2, h, "arc-tick") if s["complete"] else _rect(xx - 1.5, y + .5, 3, h - 1, "arc-cut"))
    return out


def _thin_row(row: dict, total: int, x: Linear, y: float, h: float) -> list[str]:
    out = [_rect(x(0), y - h / 2, x(total) - x(0), h, "arc-bar-t")]
    if row["mittel"]:
        out.append(_rect(x(0), y - h / 2, x(row["mittel"]) - x(0), h, "arc-thin"))
    if row["max"] > row["min"]:
        out.append(whisker(x(row["min"]), x(row["max"]), y, "arc-wh", cap=h / 2 + 2))
    return out


def f29(data: dict, *, width: int, uid: str) -> str:
    """F29: barcode of all archive snapshots by origin; below, what a sparser archive would have missed."""
    lanes = [(key, label, [s for s in data["staende"] if s["origin"] == key]) for key, label in LANES]
    lanes = [lane for lane in lanes if lane[2]]
    first, last = data["staende"][0]["tag"], data["staende"][-1]["tag"]
    d0, d1 = date(first.year, 1, 1).toordinal(), last.toordinal() + 14
    years = [date(y, 1, 1).toordinal() for y in range(first.year, last.year + 1)]
    fmt = lambda v: str(date.fromordinal(int(v)).year)
    rows, total = data["ausduennung"], data["beendet"]
    wide = width >= WIDE
    body: list[str] = [text(0 if not wide else 8, 15, f'a  Alle {num(len(data["staende"]))} Stände der BASG-Liste', "arc-pt")]

    if wide:
        x = Linear((d0, d1), (156, width - 44))
        pitch, y0 = 32, 30
        axis_y = y0 + pitch * len(lanes) + 2
        body.append(x_axis(x, axis_y, top=y0 - 2, ticks=years, fmt=fmt))
        for i, (key, label, snaps) in enumerate(lanes):
            y = y0 + i * pitch
            body += [text(8, y + 18, label, "arc-bl"), text(width - 8, y + 18, num(len(snaps)), "ch-val", "end")]
            body += _ticks(snaps, x, y + 3, 22)
            if key == "live":
                body.append(text(x(snaps[0]["tag"].toordinal()) - 7, y + 18, f'täglich seit {snaps[0]["tag"].strftime("%d.%m.%Y")}', "arc-note", "end"))
        key_y = axis_y + 42
        body += [_rect(156, key_y - 11, 2, 13, "arc-tick"), text(164, key_y, "vollständig", "arc-s"),
                 _rect(252, key_y - 11, 3, 13, "arc-cut"), text(261, key_y, "abgeschnitten: belegt nur, dass eine Packung gelistet war", "arc-s")]
        cursor = key_y + 34
    else:
        x = Linear((d0, d1), (17, width - 6))
        pitch, y0 = 46, 28
        axis_y = y0 + pitch * len(lanes) + 2
        body.append(x_axis(x, axis_y, ticks=years[::2] if len(years) > 5 else years, fmt=fmt))
        for i, (key, label, snaps) in enumerate(lanes):
            y = y0 + i * pitch
            note = f'täglich seit {snaps[0]["tag"].strftime("%d.%m.%Y")}' if key == "live" else ""
            body += [text(0, y + 12, label, "arc-bl"), text(width, y + 12, num(len(snaps)), "ch-val", "end")]
            if note:
                body.append(text(width - 32, y + 12, note, "arc-note", "end"))
            body.append(_rect(x(d0), y + 18, x(d1) - x(d0), 22, "arc-lane"))
            body += _ticks(snaps, x, y + 20, 18)
        key_y = axis_y + 40
        body += [_rect(2, key_y - 11, 2, 13, "arc-tick"), text(10, key_y, "vollständig", "arc-s"),
                 _rect(92, key_y - 11, 3, 13, "arc-cut"), text(101, key_y, "abgeschnitten", "arc-s"),
                 text(2, key_y + 17, "(belegt nur, dass eine Packung gelistet war)", "arc-s")]
        cursor = key_y + 44

    if rows and total:
        body.append(line(0, cursor - 16, width, cursor - 16, "ch-sep"))
        if wide:
            body.append(text(8, cursor + 4, f"b  Von {num(total)} kurzen Meldungen im Tagesarchiv wären ganz übersehen worden", "arc-pt"))
            bar = Linear((0, total), (156, width - 112))
            ys = [cursor + 30 + i * 30 for i in range(len(rows))]
            axis = ys[-1] + 22
            body.append(x_axis(bar, axis, top=ys[0] - 14, fmt=lambda v: num(v), label="Meldungen, die in keinen der behaltenen Stände fallen"))
            for row, y in zip(rows, ys):
                body += [text(8, y + 5, row["label"], "arc-bl", None)]
                body += _thin_row(row, total, bar, y, 14)
                body.append(text(width - 8, y + 5, f'{num(row["mittel"], 1)} von {num(total)}', "ch-val", "end"))
            height = axis + 46
        else:
            body += [text(0, cursor + 4, f"b  Von {num(total)} kurzen Meldungen wären", "arc-pt"),
                     text(0, cursor + 22, "ganz übersehen worden", "arc-pt")]
            bar = Linear((0, total), (6, width - 6))
            ys = [cursor + 62 + i * 44 for i in range(len(rows))]
            axis = ys[-1] + 18
            body.append(x_axis(bar, axis, fmt=lambda v: num(v), label="Meldungen"))
            for row, y in zip(rows, ys):
                body += [text(0, y - 13, row["label"], "arc-bl"),
                         text(width, y - 13, f'{num(row["mittel"], 1)} von {num(total)}', "ch-val", "end")]
                body += _thin_row(row, total, bar, y, 12)
            height = axis + 44
    else:
        height = cursor

    lanes_text = "; ".join(f"{label} {num(len(snaps))}" for _, label, snaps in lanes)
    thin = "; ".join(f'{row["label"]}: {num(row["mittel"], 1)} von {num(total)}' for row in rows)
    desc = f"Strichcode aller Stände seit {first.strftime('%d.%m.%Y')}: {lanes_text}." + (f" Ganz übersehene kurze Meldungen, Mittel über alle Startversätze: {thin}." if thin else "")
    return frame("archiv", width, height, uid, "Archivstände und was ein seltener geführtes Archiv übersähe", desc, body)
