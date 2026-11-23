"""Charts of the retrospective Z3 results (page "Modell und Prüfung"). All numbers come from `ergebnisse.json`."""
from __future__ import annotations

from datetime import date
from math import ceil

from ..timeline import de
from . import WIDE, Linear, Log, frame, line, marker, num, pct, r, text, text_width, whisker, x_axis, y_axis
from . import live as live_chart

# How each method is drawn: marker shape, series class, hollow. Shape and label identify a method, colour only helps.
F08_MARKS = {
    "z3_v0": ("circle", "ser-main", False),
    "z3_v0_ohne_ausland": ("circle", "ser-main", True),
    "stufen_v0": ("diamond", "ser-comp", True),
    "vorgeschichte": ("square", "ser-base", False),
    "grundrate": ("square", "ser-base", True),
}
F08_MAX = 25  # percent, upper end of the shared axis


def f08(data: dict, *, width: int, uid: str) -> str:
    """F08: hit rate of the top 50 per method, with AUC, and the interval of the distance to the tier rule.

    `data` is the block `z3_rueckblick` of `ergebnisse.json`. From `WIDE` width on, each method is one row
    (label, plot, numbers); below that the label sits on its own line above the plot and the numbers.
    """
    methods = data["verfahren"]
    base = next(m for m in methods if m["id"] == "grundrate")["top50"] * 100
    delta = next(d for d in data["differenz_z3_minus_stufen"] if d["mass"].startswith("Top 50"))
    delta_auc = next(d for d in data["differenz_z3_minus_stufen"] if d["mass"] == "AUC")
    lo, hi = delta["ki95"]
    interval = f"95-%-Intervall {num(lo, 1)} bis {num(hi, 1)} Pp"
    wide = width >= WIDE
    ticks = range(0, F08_MAX + 1, 5)

    if wide:
        x = Linear((0, F08_MAX), (272, 540))
        col_top, col_auc = 622, width - 8
        row_y = [50 + i * 36 for i in range(len(methods))]
        rule_y, delta_y, axis_y = row_y[-1] + 24, row_y[-1] + 52, row_y[-1] + 86
        height = axis_y + 44
        grid_top = 30
    else:
        x = Linear((0, F08_MAX), (8, width - 122))
        col_top, col_auc = width - 64, width - 4
        row_y = [52 + i * 45 for i in range(len(methods))]
        rule_y, delta_y, axis_y = row_y[-1] + 15, row_y[-1] + 50, row_y[-1] + 88
        height = axis_y + 42
        grid_top = 24

    body = [
        text(col_top, 16, "Top 50", "ch-col", "end"),
        text(col_auc, 16, "AUC", "ch-col", "end"),
        x_axis(x, axis_y, top=grid_top if wide else None, ticks=ticks, fmt=lambda v: num(v),
               label="Anteil mit neuer BASG-Meldung, in %" if wide else "Anteil mit neuer Meldung, in %"),
    ]
    if wide:
        body.append(line(x(base), grid_top, x(base), rule_y, "ch-ref"))
    else:  # labels sit between the tracks here, so grid and reference line are drawn per track and never cross a word
        for y in [*row_y, delta_y]:
            body += [line(x(v), y - 9, x(v), y + 9, "ch-grid") for v in ticks]
        body += [line(x(base), y - 9, x(base), y + 9, "ch-ref") for y in row_y]
    for m, y in zip(methods, row_y):
        share = m["top50"] * 100
        shape, series, hollow = F08_MARKS[m["id"]]
        strong = " ch-strong" if m["id"] == "z3_v0" else ""
        label_y, value_y = (y + 5, y + 5) if wide else (y - 18, y + 5)
        body.append(text(8 if wide else 4, label_y, m["name"], f"ch-lbl{strong}"))
        if m["id"] != "grundrate":
            body.append(line(x(base), y, x(share), y, f"ch-stem {series}"))
        tip = f'{m["name"]}: {pct(m["top50"])} der Top 50, AUC {num(m["auc"], 3)}'
        body.append(marker(shape, x(share), y, series, hollow=hollow, size=5.5 if m["id"] == "z3_v0" else 5, title=tip))
        body.append(text(col_top, value_y, pct(m["top50"]), f"ch-val{strong}", "end"))
        body.append(text(col_auc, value_y, num(m["auc"], 3), f"ch-val{strong}", "end"))

    body.append(line(4, rule_y, width - 4, rule_y, "ch-sep"))
    label = "Abstand Z3 v0 zur Stufenregel"
    if wide:
        body += [text(8, delta_y, label, "ch-lbl"), text(8, delta_y + 16, interval, "ch-sub")]
    else:
        body += [text(4, delta_y - 18, label, "ch-lbl"), text(4, delta_y + 22, interval, "ch-sub")]
    body.append(whisker(x(lo), x(hi), delta_y, "ser-main"))
    body.append(marker("circle", x(delta["wert"]), delta_y, "ser-main", size=4.5,
                       title=f'Abstand Top 50: {num(delta["wert"], 1, signed=True)} Prozentpunkte ({interval})'))
    value_y = delta_y + 5
    body.append(text(col_top, value_y, f'{num(delta["wert"], 1, signed=True)} Pp', "ch-val", "end"))
    body.append(text(col_auc, value_y, num(delta_auc["wert"], 3, signed=True), "ch-val", "end"))

    rows = "; ".join(f'{m["name"]} {pct(m["top50"])}, AUC {num(m["auc"], 3)}' for m in methods)
    desc = (f"Anteil der 50 am höchsten gereihten Wirkstoffe je Stichtag mit neuer BASG-Meldung binnen "
            f'{data["bedingungen"]["horizont_wochen"]} Wochen: {rows}. Abstand von Z3 v0 zur Stufenregel '
            f'{num(delta["wert"], 1, signed=True)} Prozentpunkte, {interval}. Rückblick, nicht validiert.')
    return frame("dots", width, height, uid, "Trefferquote der Top 50 und AUC je Verfahren", desc, body)


# --- shared helpers of the page charts ------------------------------------------------------------------------------

MONATE = ("Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")


def _ord(value: str) -> int:
    return date.fromisoformat(value).toordinal()


def _day(value: str) -> str:
    return de(date.fromisoformat(value))


def _month_ticks(lo: int, hi: int, every: int = 1) -> list[int]:
    """Ordinals of the first day of each month inside [lo, hi], every n-th month."""
    d = date.fromordinal(lo)
    y, m = d.year, d.month
    if d.day > 1:
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    out = []
    while date(y, m, 1).toordinal() <= hi:
        if (m - 1) % every == 0:
            out.append(date(y, m, 1).toordinal())
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _month(value: float) -> str:
    return MONATE[date.fromordinal(int(value)).month - 1]


def _path(points: list[tuple[float, float]]) -> str:
    return "M" + "L".join(f"{r(x)} {r(y)}" for x, y in points)


# --- F09: distance to the tier rule ---------------------------------------------------------------------------------

F09_PANELS = {
    "AUC": {"domain": (-0.03, 0.15), "ticks": (0, 0.05, 0.1, 0.15), "decimals": 3, "tick": 2, "note": "Trennschärfe"},
    "Brier-Gewinn": {"domain": (-0.0006, 0.0024), "ticks": (0, 0.001, 0.002), "decimals": 4, "tick": 3, "note": "Genauigkeit"},
    "Top 50 je Stichtag": {"domain": (-2.5, 12.5), "ticks": (0, 5, 10), "decimals": 1, "tick": 0, "note": "Prozentpunkte"},
}


def f09(data: dict, *, width: int, uid: str) -> str:
    """F09: the three differences Z3 v0 minus tier rule, each in its own small panel with its own unit and a zero line."""
    rows = data["differenz_z3_minus_stufen"]
    wide = width >= WIDE
    gap = 34
    panel_w = (width - 2 * gap) / 3 if wide else width
    panel_h = 128
    body: list[str] = []
    for i, d in enumerate(rows):
        p = F09_PANELS[d["mass"]]
        x0 = i * (panel_w + gap) if wide else 0
        y0 = 0 if wide else i * (panel_h + 16)
        x = Linear(p["domain"], (x0 + 8, x0 + panel_w - (8 if wide else 20)))
        track, axis = y0 + 86, y0 + 104
        lo, hi = d["ki95"]
        value = num(d["wert"], p["decimals"], signed=True)
        interval = f'{num(lo, p["decimals"])} bis {num(hi, p["decimals"])}'
        body += [text(x0 + 8, y0 + 15, d["mass"], "ch-lbl ch-strong"),
                 text(x0 + 8, y0 + 33, p["note"], "md-note"),
                 text(x0 + panel_w - 8, y0 + 33, value, "md-big", "end"),
                 text(x0 + panel_w - 8, y0 + 51, interval, "md-small", "end"),
                 x_axis(x, axis, top=y0 + 62, ticks=p["ticks"], fmt=lambda v, t=p["tick"]: num(v, t if v else 0)),
                 line(x(0), y0 + 62, x(0), axis, "md-zero"),
                 whisker(x(lo), x(hi), track, "ser-main"),
                 marker("circle", x(d["wert"]), track, "ser-main", size=5.5, title=f'{d["mass"]}: {value} (95-%-Intervall {interval})')]
    height = panel_h if wide else 3 * panel_h + 32
    desc = "Abstand von Z3 v0 zur Stufenregel im Rückblick 2026: " + "; ".join(
        f'{d["mass"]} {num(d["wert"], F09_PANELS[d["mass"]]["decimals"], signed=True)}, 95-%-Intervall '
        f'{num(d["ki95"][0], F09_PANELS[d["mass"]]["decimals"])} bis {num(d["ki95"][1], F09_PANELS[d["mass"]]["decimals"])}' for d in rows) + "."
    return frame("f09", width, height, uid, "Abstand zur Stufenregel mit 95-%-Intervallen", desc, body)


# --- F10: calibration at three horizons -----------------------------------------------------------------------------

F10_TICKS = (0.2, 1, 5, 20, 50)


def _f10_panel(d: dict, x0: float, y0: float, w: float, plot_h: float, limit: int) -> list[str]:
    left, right = x0 + 34, x0 + w - 6
    band = d["rueckblick"]
    weeks = d["horizont_tage"] // 7
    head = f'Rückblick {num(band["faelle"])} Fälle' if band else "Rückblick fehlt"
    body = [text(left, y0 + 13, f"{weeks} Wochen", "ch-lbl ch-strong"), text(left, y0 + 30, head, "md-note")]
    top, bottom = y0 + 42, y0 + 42 + plot_h
    x, y = Log(live_chart.AXIS, (left, right)), Log(live_chart.AXIS, (bottom, top))
    edges = [live_chart.AXIS[0], *(e * 100 for e in d["grenzen"]), live_chart.AXIS[1]]
    columns = [(x(a), x(b)) for a, b in zip(edges, edges[1:])]
    for i, (a, b) in enumerate(columns):
        if i % 2:
            body.append(f'<rect class="f22-col" x="{r(a)}" y="{r(top)}" width="{r(b - a)}" height="{r(bottom - top)}"/>')
    body.append(y_axis(y, left, right=right, ticks=F10_TICKS, fmt=live_chart._tick))
    body.append(x_axis(x, bottom, ticks=F10_TICKS, fmt=live_chart._tick))
    if band:
        body += live_chart._band(band["punkte"], x, y)
    body.append(line(x(live_chart.AXIS[0]), y(live_chart.AXIS[0]), x(live_chart.AXIS[1]), y(live_chart.AXIS[1]), "f22-diag"))
    both = bool(d["einlauf"]["punkte"] and d["pruefung"]["punkte"])
    for (phase, shape, hollow, name), dx in zip(live_chart.PHASES, (-3, 3) if both else (0, 0)):
        body += live_chart._points(d, phase, shape, hollow, name, x, y, dx, bottom, top, columns)
    note = live_chart.status_sentence(d)
    if note:
        parts = live_chart._wrap(note, limit)
        for i, part in enumerate(parts):
            body.append(text(right - 4, bottom - 8 - (len(parts) - 1 - i) * 15, part, "md-panel-note", "end"))
    return body


def f10(panels: list[dict], *, width: int, uid: str) -> str:
    """F10: predicted against observed share for 4, 8 and 12 weeks, same classes, phases and marks as F22."""
    wide = width >= WIDE
    legend = [(live_chart._band_mark, "Rückblick · simuliert · nicht validiert" if wide else "Rückblick · simuliert"),
              (live_chart._circle_mark, "Einlaufphase · zählt nicht für die Prüfung" if wide else "Einlaufphase"),
              (live_chart._diamond_mark, "Prüfung · vorab festgelegt · Zwischenstand, kein Urteil" if wide else "Prüfung · kein Urteil"),
              (live_chart._diagonal_mark, "Vorhersage trifft ein")]
    key, key_y = live_chart._key(legend, 2, 14, width - 2, 18)
    body: list[str] = list(key)
    y0 = key_y + 14
    if wide:
        gap = 12
        w = (width - 2 * gap) / 3
        plot_h = 190
        for i, d in enumerate(panels):
            body += _f10_panel(d, i * (w + gap), y0, w, plot_h, 18)
        axis_y = y0 + 42 + plot_h + 38
        body.append(text(width / 2, axis_y, "vorhergesagte Wahrscheinlichkeit einer neuen Meldung, in %", "ch-axt", "middle"))
        height = axis_y + 8
    else:
        plot_h = 176
        step = 42 + plot_h + 40
        for i, d in enumerate(panels):
            body += _f10_panel(d, 0, y0 + i * step, width, plot_h, 24)
        axis_y = y0 + 3 * step - 8
        body.append(text(width / 2, axis_y, "x: vorhergesagt, y: eingetroffen, in %", "ch-axt", "middle"))
        height = axis_y + 8
    parts = []
    for d in panels:
        e = d["einlauf"]
        band = d["rueckblick"]
        parts.append(f'{d["horizont_tage"] // 7} Wochen: Rückblick {num(band["faelle"]) if band else 0} Fälle, '
                     f'Einlaufphase {num(e["faelle"])} reife Fälle, Prüfung {num(d["pruefung"]["faelle"])} reife Fälle')
    desc = "Vorhersage gegen Eintreffen je Klasse auf logarithmischen Achsen. " + "; ".join(parts) + ". Rückblick simuliert und nicht validiert."
    return frame("f10", width, height, uid, "Kalibrierung für 4, 8 und 12 Wochen", desc, body)


# --- F11: weights ---------------------------------------------------------------------------------------------------

F11_DOMAIN = (-1.1, 0.9)
F11_TICKS = (-1, -0.5, 0, 0.5)


def f11(data: dict, *, width: int, uid: str) -> str:
    """F11: log-odds weights as dots on a zero line, grouped; ATC groups and quarter as ranges."""
    wide = width >= WIDE
    if wide:
        x = Linear(F11_DOMAIN, (330, width - 72))
    else:
        x = Linear(F11_DOMAIN, (8, width - 60))
    row_h = 25 if wide else 42
    y = 8.0
    body: list[str] = []
    marks: list[str] = []

    def row(label: str, value: str, draw) -> None:
        nonlocal y
        if wide:
            cy = y + row_h / 2
            body.append(text(12, cy + 5, label, "ch-lbl"))
            body.append(text(width - 4, cy + 5, value, "ch-val", "end"))
        else:
            parts = live_chart._wrap(label, 40)
            for i, part in enumerate(parts):
                body.append(text(4, y + 13 + i * 16, part, "md-row"))
            y += (len(parts) - 1) * 16
            cy = y + 29
            body.append(text(width - 2, cy + 5, value, "ch-val", "end"))
        if not wide:
            marks.extend(line(x(v), cy - 9, x(v), cy + 9, "md-zero" if v == 0 else "ch-grid") for v in F11_TICKS)
        marks.append(draw(cy))
        y += row_h

    for g in data["gruppen"]:
        y += 8
        body.append(text(4, y + 13, g["gruppe"], "ch-col"))
        if wide:
            body.append(text(width - 4, y + 13, f'Bezug: {g["bezug"]}', "md-note", "end"))
        else:
            y += 17
            body.append(text(4, y + 13, f'Bezug: {g["bezug"]}', "md-note"))
        y += 21
        for m in g["merkmale"]:
            w = m["gewicht"]
            row(m["name"], num(w, 2, signed=True),
                lambda cy, w=w, name=m["name"]: line(x(0), cy, x(w), cy, "ch-stem ser-main")
                + marker("circle", x(w), cy, "ser-main", size=5, title=f"{name}: {num(w, 4, signed=True)}"))
    y += 8
    body.append(text(4, y + 13, "Spannen", "ch-col"))
    y += 21
    for s in data["spannen"]:
        a, b = s["von"], s["bis"]
        row(s["name"], f"{num(a, 2, signed=True)} bis {num(b, 2, signed=True)}",
            lambda cy, a=a, b=b, name=s["name"]: whisker(x(a), x(b), cy, "ser-base")
            + f'<g class="mk-g"><title>{name}: {num(a, 4, signed=True)} bis {num(b, 4, signed=True)}</title>'
              f'<rect class="mk-hit" x="{r(x(a))}" y="{r(cy - 10)}" width="{r(x(b) - x(a))}" height="20"/></g>')
    axis_y = y + 8
    grid = [x_axis(x, axis_y, top=4 if wide else None, ticks=F11_TICKS, fmt=lambda v: num(v, 1 if v % 1 else 0, signed=True) if v else "0",
                   label="Gewicht (logarithmische Chance)")]
    if wide:
        grid.append(line(x(0), 4, x(0), axis_y, "md-zero"))
    rows = "; ".join(f'{m["name"]} {num(m["gewicht"], 4, signed=True)}' for g in data["gruppen"] for m in g["merkmale"])
    desc = f"Gewichte der logistischen Regression für 8 Wochen: {rows}. Keine Intervalle für einzelne Gewichte."
    return frame("f11", width, axis_y + 44, uid, "Gewichte des Modells Z3 v0", desc, [*grid, *body, *marks])


# --- F15: timeline --------------------------------------------------------------------------------------------------

def f15(data: dict, *, width: int, uid: str) -> str:
    """F15: proportional strip from 2024 to September 2027 and one row per step; points before the data date are filled."""
    wide = width >= WIDE
    stand = _ord(data["stand"])
    items = sorted(data["zeitleiste"], key=lambda e: e.get("am") or e["von"])
    lo, hi = date(2024, 1, 1).toordinal(), date(2027, 9, 30).toordinal()
    x = Linear((lo, hi), (6, width - 6))
    body: list[str] = []
    strip_y, strip_h = 26, 16
    for e in items:
        if "von" in e:
            a, b = x(_ord(e["von"])), x(_ord(e["bis"]))
            body.append(f'<rect class="md-span" x="{r(a)}" y="{r(strip_y)}" width="{r(b - a)}" height="{strip_h}"/>')
            if b - a > 90:
                body.append(text((a + b) / 2, strip_y + 12.5, e["text"].split(" ")[-1] if not wide else e["text"], "md-span-t", "middle"))
    start = next(e["am"] for e in items if e.get("text", "").startswith("Beginn der prospektiven"))
    a, b = x(_ord(start)), x(hi)
    body.append(f'<rect class="md-span md-span-test" x="{r(a)}" y="{r(strip_y)}" width="{r(b - a)}" height="{strip_h}"/>')
    body.append(text((a + b) / 2, strip_y + 12.5, "Prüfung" if wide else "", "md-span-t", "middle"))
    for year in (2024, 2025, 2026, 2027):
        xx = x(date(year, 1, 1).toordinal())
        body += [line(xx, strip_y + strip_h, xx, strip_y + strip_h + 4, "ch-axis"), text(xx, strip_y + strip_h + 18, str(year), "ch-tick", "start" if year == 2024 else "middle")]
    for e in items:
        if "am" in e:
            xx = x(_ord(e["am"]))
            body.append(line(xx, strip_y - 4, xx, strip_y + 3, "md-tick"))
    now = x(min(max(stand, lo), hi))
    body += [line(now, strip_y - 8, now, strip_y + strip_h + 3, "md-now"),
             f'<path class="md-now-m" d="M{r(now - 4)} {r(strip_y - 12)}H{r(now + 4)}L{r(now)} {r(strip_y - 6)}Z"/>',
             text(min(max(now, 70), width - 70), strip_y - 15, f'Stand {_day(data["stand"])}', "md-now-t", "middle")]

    # one row per step, in order, with a line where the data date falls
    rail = 100 if wide else 10
    y = strip_y + strip_h + 34
    rows: list[tuple[str, str, bool]] = []
    for e in items:
        day = e.get("am") or e["von"]
        when = _day(day) if "am" in e else f'{_day(e["von"])[3:]}–{_day(e["bis"])[3:]}'
        rows.append((when, e["text"], _ord(e.get("bis") or day) <= stand))
    marked = False
    row_top = y
    for when, label, done in rows:
        if not done and not marked:
            marked = True
            cy = y + 13
            if wide:
                body += [line(rail + 104, cy, width - 4, cy, "md-now"), text(rail - 14, cy + 4.5, _day(data["stand"]), "md-now-t", "end"),
                         text(rail + 16, cy + 4.5, "Datenstand", "md-now-t")]
            else:
                body += [line(rail + 14 + 150, cy, width - 4, cy, "md-now"), text(rail + 14, cy + 4.5, f'Stand {_day(data["stand"])}', "md-now-t")]
            body.append(f'<path class="md-now-m" d="M{r(rail - 5)} {r(cy - 5)}L{r(rail + 5)} {r(cy)}L{r(rail - 5)} {r(cy + 5)}Z"/>')
            y += 26
        cy = y + 14
        if wide:
            body += [text(rail - 14, cy + 4.5, when, "md-date", "end"), text(rail + 16, cy + 5, label, "ch-lbl")]
            y += 26
        else:
            parts = live_chart._wrap(label, 39)
            body.append(text(rail + 14, cy + 4, when, "md-date"))
            for i, part in enumerate(parts):
                body.append(text(rail + 14, cy + 22 + i * 16, part, "md-row"))
            y += 26 + len(parts) * 16
        body.append(marker("circle", rail, cy, "ser-main", size=4.5, hollow=not done))
    body.insert(0, line(rail, row_top + 8, rail, y - 8, "md-rail"))
    desc = f'Zeitleiste der Vorab-Registrierung, Stand {_day(data["stand"])}: ' + "; ".join(f"{w}: {t}" for w, t, _ in rows) + "."
    return frame("f15", width, y + 4, uid, "Zeitleiste der Vorab-Registrierung", desc, body)


# --- F25: where the newly reported substances stood -----------------------------------------------------------------

def _f25_stair(phase: dict, x, y) -> list[tuple[float, float]]:
    points = [(x(0), y(0))]
    for p in phase["punkte"]:
        px = x(p["anteil_liste"] * 100)
        points += [(px, points[-1][1]), (px, y(p["anteil"] * 100))]
    points += [(x(100), points[-1][1]), (x(100), y(100))]
    return points


def f25(data: dict, *, width: int, uid: str) -> str:
    """F25: staircase of the share of new reports within the top places of the list; the diagonal is a random order."""
    wide = width >= WIDE
    left, right = (50, 470) if wide else (36, width - 14)
    top, bottom = (14, 330) if wide else (24, 290)
    x, y = Linear((0, 100), (left, right)), Linear((0, 100), (bottom, top))
    fmt = (lambda v: f"{num(v)} %") if wide else (lambda v: num(v))
    body = [y_axis(y, left, right=right, ticks=range(0, 101, 20), fmt=fmt, label=None if wide else "Anteil der neuen Meldungen, in %"),
            x_axis(x, bottom, ticks=range(0, 101, 20), fmt=fmt, label="Anteil der Liste, von oben gezählt" if wide else "Anteil der Liste von oben, in %"),
            line(x(0), y(0), x(100), y(100), "f22-diag"),
            text(x(70) + 7, y(70) + 19, "Zufall", "md-diag-t")]
    einlauf, pruefung = data["einlauf"], data["pruefung"]
    shown = [(einlauf, "circle", True, "Einlaufphase"), (pruefung, "diamond", False, "ab Prüfungsbeginn")]
    shown = [s for s in shown if s[0]["anzahl"] >= data["mindestens"]]
    if shown:
        p50 = next(p for p in shown[0][0]["punkte"] if p["platz"] == 50)
        px = x(p50["anteil_liste"] * 100)
        body += [line(px, top, px, bottom, "md-p50"), text(px + 4, top + 11, "Platz 50", "md-p50-t")]
    for phase, shape, hollow, name in shown:
        body.append(f'<path class="md-stair ser-main{" md-stair-test" if not hollow else ""}" d="{_path(_f25_stair(phase, x, y))}"/>')
        for p in phase["punkte"]:
            body.append(marker(shape, x(p["anteil_liste"] * 100), y(p["anteil"] * 100), "ser-main", size=4, hollow=hollow,
                               title=f'{name}, bis Platz {num(p["platz"])}: {num(p["meldungen"])} von {num(phase["anzahl"])} neuen Meldungen ({pct(p["anteil"], 0)})'))
    if not shown:
        body.append(text((left + right) / 2, (top + bottom) / 2, "Noch zu wenige neue Meldungen", "md-panel-note", "middle"))

    # readouts beside (wide) or below (narrow) the plot
    block_x, block_y = (500, 34) if wide else (4, bottom + 66)
    for phase, shape, hollow, name in [(einlauf, "circle", True, "Einlaufphase"), (pruefung, "diamond", False, "ab Prüfungsbeginn")]:
        if not phase["anzahl"]:
            continue
        body += [marker(shape, block_x + 5, block_y - 5, "ser-main", size=4.5, hollow=hollow), text(block_x + 18, block_y, name, "ch-lbl ch-strong")]
        top_share = phase["top50"] / phase["anzahl"]
        block_y += 24
        body.append(text(block_x, block_y, f'{num(phase["top50"])} von {num(phase["anzahl"])}', "md-big"))
        block_y += 19
        body.append(text(block_x, block_y, "neuen Meldungen auf Platz 1–50", "md-note"))
        block_y += 18
        if phase["top50_ki95"]:
            lo, hi = phase["top50_ki95"]
            body.append(text(block_x, block_y, f'{num(top_share * 100)} % (95 %: {num(lo * 100)}–{num(hi * 100)})', "md-small"))
            block_y += 18
        p = next(q for q in phase["punkte"] if q["platz"] == 50)
        body.append(text(block_x, block_y, f'Platz 1–50 sind {pct(p["anteil_liste"], 1)} der Liste', "md-note"))
        block_y += 34
    height = bottom + 48 if wide else max(block_y - 14, bottom + 56)
    desc = (f'Neue Meldungen der Einlaufphase: {num(einlauf["anzahl"])}, davon {num(einlauf["top50"])} auf Platz 1 bis 50 der Liste am Tag davor; '
            f'ab Prüfungsbeginn: {num(pruefung["anzahl"])}, davon {num(pruefung["top50"])}.')
    return frame("f25", width, height, uid, "Platz der neu gemeldeten Wirkstoffe in der Reihung", desc, body)


# --- F26: what the model does not see coming ------------------------------------------------------------------------

def f26(data: dict, *, width: int, uid: str) -> str:
    """F26: reasons of the top-50 hits against the surprises behind place 400, as paired bars with counts."""
    wide = width >= WIDE
    a, b = data["gruppen"]["treffer"], data["gruppen"]["ueberraschung"]
    names = sorted((n for n in a["gruende"] if n != "Sonstige Gründe"), key=lambda n: -(a["gruende"][n] / a["n"] - b["gruende"][n] / b["n"])) + ["Sonstige Gründe"]
    label_w = 292 if wide else 0
    x = Linear((0, 40), (label_w + 6, width - (86 if wide else 74)))
    row_h = 44 if wide else 62
    key_y = 16
    body: list[str] = [f'<rect class="md-bar-a" x="2" y="{key_y - 9}" width="12" height="10"/>',
                       text(19, key_y, f'Treffer: Platz 1–50 (n = {num(a["n"])})', "md-key")]
    kx = 19 + text_width(f'Treffer: Platz 1–50 (n = {num(a["n"])})', 13) + 22
    if wide:
        second = (kx, key_y)
    else:
        second = (2, key_y + 19)
    body += [f'<rect class="md-bar-b" x="{r(second[0])}" y="{second[1] - 9}" width="12" height="10"/>',
             text(second[0] + 17, second[1], f'Überraschung: hinter Platz 400 (n = {num(b["n"])})', "md-key")]
    y0 = (key_y if wide else key_y + 19) + 18
    axis_y = y0 + row_h * len(names) + 2
    body.append(x_axis(x, axis_y, top=y0, ticks=(0, 10, 20, 30, 40), fmt=lambda v: f"{num(v)} %", label="Anteil an der Gruppe"))
    for i, name in enumerate(names):
        top = y0 + i * row_h
        if wide:
            bar_y = top + 7
            body.append(text(4, top + row_h / 2 + 5, name, "ch-lbl"))
        else:
            body.append(text(4, top + 14, name, "md-row"))
            bar_y = top + 21
        for key, g, cls, dy in (("a", a, "md-bar-a", 0), ("b", b, "md-bar-b", 15)):
            n = g["gruende"][name]
            share = n / g["n"]
            yy = bar_y + dy
            body.append(f'<g class="mk-g"><title>{name}, {"Treffer" if key == "a" else "Überraschung"}: {n} von {g["n"]} ({pct(share, 0)})</title>'
                        f'<rect class="{cls}" x="{r(x(0))}" y="{r(yy)}" width="{r(max(x(share * 100) - x(0), 0.5))}" height="12"/></g>')
            body.append(text(x(share * 100) + 5, yy + 10.5, f"{pct(share, 0)} ({n})", "md-bar-v"))
    desc = (f'Gründe laut BASG bei {num(a["n"])} Treffern auf Platz 1 bis 50 und {num(b["n"])} Überraschungen hinter Platz 400: '
            + "; ".join(f'{n}: {pct(a["gruende"][n] / a["n"], 0)} gegen {pct(b["gruende"][n] / b["n"], 0)}' for n in names) + ".")
    return frame("f26", width, axis_y + 44, uid, "Gründe der Treffer und der Überraschungen", desc, body)


# --- F27: expected against observed total -------------------------------------------------------------------------

F27_MAX = 80


def f27(data: dict, *, width: int, uid: str) -> str:
    """F27: expected number of new reports with its chance band against the number that came, per reference day."""
    wide = width >= WIDE
    rows, extra = data["zeilen"], data.get("live") or []
    all_rows = [*rows, *extra]
    lo, hi = _ord(all_rows[0]["stichtag"]) - 8, _ord(all_rows[-1]["stichtag"]) + 8
    left, right = 42, width - (10 if wide else 6)
    items = [("band", "Zufallsband (95 %) um die Erwartung" if wide else "Zufallsband"), ("line", "erwartet"), ("dot", "eingetroffen")]
    if any(z["phase"] == "einlauf" for z in extra):
        items.append(("hollow", "Einlaufphase"))
    if any(z["phase"] == "pruefung" for z in extra):
        items.append(("diamond", "Prüfung · kein Urteil"))
    key: list[str] = []
    key_x, key_y = 2.0, 13
    for kind, label in items:
        step = 21 + text_width(label, 13) + (16 if wide else 8)
        if key_x + step > width and key_x > 2:
            key_x, key_y = 2.0, key_y + 17
        if kind == "band":
            key.append(f'<rect class="md-band" x="{r(key_x)}" y="{key_y - 10}" width="16" height="10"/>')
        elif kind == "line":
            key.append(line(key_x, key_y - 5, key_x + 16, key_y - 5, "md-exp"))
        else:
            key.append(marker("diamond" if kind == "diamond" else "circle", key_x + 8, key_y - 5, "ser-main", size=4, hollow=kind == "hollow"))
        key.append(text(key_x + 21, key_y, label, "md-key"))
        key_x += step
    top = key_y + 37
    bottom = top + (240 if wide else 212)
    y_max = max(F27_MAX, ceil(max(max(z["eingetroffen"], z["bereich"][1]) for z in all_rows) / 20) * 20)
    x, y = Linear((lo, hi), (left, right)), Linear((0, y_max), (bottom, top))
    ticks = _month_ticks(lo, hi, 1 if wide else 2)
    first_year, last_year = all_rows[0]["stichtag"][:4], all_rows[-1]["stichtag"][:4]
    years = first_year if first_year == last_year else f"{first_year}–{last_year}"
    body = [y_axis(y, left, right=right, ticks=range(0, y_max + 1, 20), fmt=lambda v: num(v), label="neue Meldungen binnen 8 Wochen"),
            x_axis(x, bottom, ticks=ticks, fmt=_month, label=f"Stichtag, {years}")]
    # the band and the line belong to the retrospective rows; real days are never joined to them
    upper = [(x(_ord(z["stichtag"])), y(z["bereich"][1])) for z in rows]
    lower = [(x(_ord(z["stichtag"])), y(z["bereich"][0])) for z in reversed(rows)]
    body.append(f'<path class="md-band" d="{_path(upper + lower)}Z"/>')
    body.append(f'<path class="md-exp" d="{_path([(x(_ord(z["stichtag"])), y(z["erwartet"])) for z in rows])}"/>')
    for z in all_rows:
        phase = z.get("phase")
        shape, hollow, name = {"einlauf": ("circle", True, "Einlaufphase"), "pruefung": ("diamond", False, "Prüfung")}.get(phase, ("circle", False, "Rückblick"))
        px = x(_ord(z["stichtag"]))
        if phase:
            body += [line(px, y(z["bereich"][0]), px, y(z["bereich"][1]), "md-range"), line(px - 5, y(z["erwartet"]), px + 5, y(z["erwartet"]), "md-exp")]
        else:
            body.append(line(px, y(z["erwartet"]), px, y(z["eingetroffen"]), "md-gap"))
        body.append(marker(shape, px, y(z["eingetroffen"]), "ser-main", size=4.5, hollow=hollow,
                           title=f'{name}, Stichtag {_day(z["stichtag"])}: erwartet {num(z["erwartet"], 1)}, eingetroffen {num(z["eingetroffen"])}'))
    first = rows[0]
    low = min(rows, key=lambda z: z["eingetroffen"])
    fx, fy = x(_ord(first["stichtag"])), y(first["eingetroffen"])
    body.append(text(fx + 9, fy - 7, f'{_day(first["stichtag"])[:6]}: {num(first["eingetroffen"])} statt {num(first["erwartet"])}', "md-call"))
    lx, ly = x(_ord(low["stichtag"])), y(low["eingetroffen"])
    label = f'{_day(low["stichtag"])[:6]}: {num(low["eingetroffen"])} statt {num(low["erwartet"])}'
    half = text_width(label, 12.5, mono=True) / 2
    body.append(text(min(max(lx, left + half + 2), right - half - 2), ly + 19, label, "md-call", "middle"))
    body += key
    e, o = [z["erwartet"] for z in rows], [z["eingetroffen"] for z in rows]
    desc = (f'Je Stichtag erwartet {num(min(e))} bis {num(max(e))} neue Meldungen, eingetroffen {num(min(o))} bis {num(max(o))}; '
            f'Korrelation {num(data["korrelation"], 1)} über {num(len(rows))} Stichtage.')
    return frame("f27", width, bottom + 46, uid, "Erwartete und eingetroffene Zahl neuer Meldungen", desc, body)


# --- F36: stability of the list ------------------------------------------------------------------------------------

F36_MAX = 20  # percent


def f36(data: dict, *, width: int, uid: str) -> str:
    """F36: daily share of the top 50 that changes, as a line per phase, with the mean of each phase."""
    wide = width >= WIDE
    rows = data["zeilen"]
    lo, hi = _ord(rows[0]["tag"]) - 1, _ord(rows[-1]["tag"]) + 1
    left, right = 42, width - (10 if wide else 6)
    phases = sum(1 for key in ("einlauf", "pruefung") if data[key])
    top = 26 + 18 * phases
    bottom = top + (176 if wide else 150)
    y_max = max(F36_MAX, ceil(max(z["anteil"] for z in rows) * 100 / 10) * 10)
    x, y = Linear((lo, hi), (left, right)), Linear((0, y_max), (bottom, top))
    span = hi - lo
    ticks = _month_ticks(lo, hi, 1)
    if span < 62:  # short series: weekly marks say more than one or two month ticks
        ticks = list(range(lo + 1, hi, 7 if wide else 14))
        fmt = lambda v: date.fromordinal(int(v)).strftime("%d.%m.")
    else:
        fmt = _month
    body = [y_axis(y, left, right=right, ticks=range(0, y_max + 1, 5 if y_max <= F36_MAX else 10), fmt=lambda v: f"{num(v)} %", label="Anteil der Top 50, der wechselt"),
            x_axis(x, bottom, ticks=ticks, fmt=fmt)]
    beginn = _ord(data["beginn"])
    if lo < beginn <= hi:
        body += [line(x(beginn), top, x(beginn), bottom, "md-p50"), text(x(beginn) + 4, top + 11, "Prüfungsbeginn", "md-p50-t")]
    segment: list[tuple[float, float]] = []
    prev = None
    paths: list[str] = []
    for z in rows:
        day = _ord(z["tag"])
        if prev is not None and (day - prev[0] != 1 or z["phase"] != prev[1]):
            paths.append(_path(segment))
            segment = []
        segment.append((x(day), y(z["anteil"] * 100)))
        prev = (day, z["phase"])
    paths.append(_path(segment))
    body += [f'<path class="md-line" d="{d}"/>' for d in paths]
    notes: list[str] = []
    for key, name in (("einlauf", "Einlaufphase"), ("pruefung", "Prüfung")):
        s = data[key]
        if not s:
            continue
        part = [_ord(z["tag"]) for z in rows if z["phase"] == key]
        m = y(s["mittel"] * 100)
        body.append(line(x(part[0]), m, x(part[-1]), m, "md-mean"))
        notes.append(f'{name}: Mittel {pct(s["mittel"])}{" (gestrichelt)" if not notes else ""}, höchstens {pct(s["hoechstens"], 0)}' if wide
                     else f'{name}: Mittel {pct(s["mittel"])}, max. {pct(s["hoechstens"], 0)}')
    for i, note in enumerate(notes):
        body.append(text(2, 13 + i * 18, note, "md-call"))
    e = data["einlauf"]
    summary = f'Mittel {pct(e["mittel"])}, höchstens {pct(e["hoechstens"], 0)} an {num(e["tage"])} Tagen' if e else ""
    return frame("f36", width, bottom + 32, uid, "Täglicher Wechsel der Liste der 50 höchsten", f"Täglicher Wechsel der Top 50. {summary}.", body)
