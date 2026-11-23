"""Forest plots of the page "Befunde" (F07, F18, F19, F20). Every number comes from the page context."""
from __future__ import annotations

from . import WIDE, Linear, Log, frame, line, marker, nice_ticks, num, text, whisker, x_axis

TRAEGT = "trägt"


def ci(value: float, lo: float, hi: float, decimals: int = 2, signed: bool = False) -> str:
    """`1,60 [1,54; 1,66]`, the way the sources write a value with its interval."""
    return f"{num(value, decimals, signed)} [{num(lo, decimals, signed)}; {num(hi, decimals, signed)}]"


def _short(value: float) -> str:
    """Tick label without trailing zeros: `0,75`, `1`, `1,5`."""
    return num(value, 2).rstrip("0").rstrip(",")


def _track_grid(x: Linear, ticks, y: float, ref: float, half: float = 9) -> list[str]:
    """Grid and reference line for one track, used where labels sit between the tracks."""
    return [*(line(x(t), y - half, x(t), y + half, "ch-grid") for t in ticks), line(x(ref), y - half, x(ref), y + half, "ch-ref")]


def _key(items: list[tuple[str, str, bool, str]], x0: float, y: float, gap: float) -> list[str]:
    """Printed legend: marker shape, series, hollow, label."""
    out, cx = [], x0
    for shape, series, hollow, label in items:
        out += [marker(shape, cx + 5, y - 4, series, hollow=hollow, size=4.5), text(cx + 15, y, label, "ch-axt")]
        cx += gap
    return out


def f07(rows: list[dict], *, width: int, uid: str) -> str:
    """F07: observed against expected reports (SIR) on a log axis, with Byar intervals and a line at 1."""
    wide = width >= WIDE
    lo = min(0.75, *(r["ki"][0] * 0.94 for r in rows))
    hi = max(2.2, *(r["ki"][1] * 1.06 for r in rows))
    ticks = [t for t in (0.5, 0.75, 1, 1.5, 2, 3, 4) if lo <= t <= hi]
    if wide:
        x = Log((lo, hi), (276, 548))
        ys = [58 + i * 50 for i in range(len(rows))]
        axis_y = ys[-1] + 34
    else:
        x = Log((lo, hi), (20, width - 20))
        ys = [66 + i * 80 for i in range(len(rows))]
        axis_y = ys[-1] + 36
    key_y = axis_y + 58
    body = [text(8 if wide else 4, 16, "Signal", "ch-col")]
    body.append(text(width - 8 if wide else width - 4, 16, "SIR [95 %]", "ch-col", "end"))
    body.append(x_axis(x, axis_y, top=28 if wide else None, ticks=ticks, fmt=_short,
                       label="Beobachtet durch erwartet (SIR), log. Achse" if wide else "Beobachtet durch erwartet, log."))
    if wide:
        body.append(line(x(1), 28, x(1), axis_y, "ch-ref"))
    for r, y in zip(rows, ys):
        strong = r["urteil"] == TRAEGT
        series = "ser-main" if strong else "ser-base"
        cls = "ch-lbl ch-strong" if strong else "ch-lbl"
        value = ci(r["sir"], *r["ki"])
        tip = f'{r["name"]}: SIR {value}, {num(r["treffer"])} beobachtet, {num(r["erwartet"], 1)} erwartet'
        if wide:
            track = y + 3
            body += [text(8, y - 2, r["name"], cls),
                     text(8, y + 15, f'{num(r["treffer"])} beobachtet, {num(r["erwartet"], 1)} erwartet', "ch-sub"),
                     text(width - 8, y - 2, value, "ch-val ch-strong" if strong else "ch-val", "end"),
                     text(width - 8, y + 15, r["urteil"], "ch-sub", "end")]
        else:
            track = y
            body += _track_grid(x, ticks, y, 1)
            body += [text(4, y - 18, r["name"], cls), text(4, y + 25, value, "ch-sub"),
                     text(width - 4, y + 25, r["urteil"], "ch-sub", "end")]
        body += [whisker(x(r["ki"][0]), x(r["ki"][1]), track, series),
                 marker("circle", x(r["sir"]), track, series, hollow=not strong, title=tip)]
    body += _key([("circle", "ser-main", False, "Bereich ganz über 1"), ("circle", "ser-base", True, "Bereich schließt 1 ein")],
                 276 if wide else 4, key_y, 170 if wide else 142)
    desc = "; ".join(f'{r["name"]}: SIR {ci(r["sir"], *r["ki"])}, {r["urteil"]}' for r in rows)
    return frame("forest", width, key_y + 10, uid, "Beobachtete gegen erwartete BASG-Meldungen je Signal",
                 f"Verhältnis beobachteter zu erwarteten neuen Meldungen binnen 8 Wochen. {desc}. Rückblick, nicht validiert.", body)


def f18(rows: list[dict], *, width: int, uid: str) -> str:
    """F18: the two refinements with a published interval, each on its own axis, then those without a number."""
    wide = width >= WIDE
    measured = [r for r in rows if r.get("ki") is not None]
    plain = [r for r in rows if r.get("ki") is None]
    body: list[str] = []
    y = 6
    for r in measured:
        lo, hi = min(r["ki"][0], 0), max(r["ki"][1], 0)
        pad = (hi - lo) * 0.14
        domain = (lo - pad, hi + pad)
        x = Linear(domain, (276, 548) if wide else (20, width - 20))
        ticks = nice_ticks(*domain, 6)
        tick_dec = 0 if r["dezimal"] == 0 else 2
        strong = r["urteil"] == TRAEGT
        series = "ser-main" if strong else "ser-base"
        value = ci(r["wert"], *r["ki"], decimals=r["dezimal"], signed=True)
        cls = "ch-lbl ch-strong" if strong else "ch-lbl"
        tip = f'{r["kurz"]}: {value} ({r["achse"]})'
        if wide:
            track, axis_y = y + 24, y + 50
            body += [text(8, y + 22, r["kurz"], cls), text(8, y + 39, r["urteil"], "ch-sub"),
                     text(width - 8, y + 28, value, "ch-val ch-strong" if strong else "ch-val", "end")]
            body.append(x_axis(x, axis_y, top=y + 6, ticks=ticks, fmt=lambda v: num(v, tick_dec, signed=True), label=r["achse"]))
            body.append(line(x(0), y + 6, x(0), axis_y, "ch-ref"))
            y = axis_y + 52
        else:
            track, axis_y = y + 42, y + 68
            body += [text(4, y + 16, r["kurz"], cls), text(width - 4, y + 16, r["urteil"], "ch-sub", "end"),
                     text(width - 4, y + 32, value, "ch-sub", "end")]
            body.append(x_axis(x, axis_y, top=y + 38, ticks=ticks, fmt=lambda v: num(v, tick_dec, signed=True), label=r["achse"]))
            body.append(line(x(0), y + 38, x(0), axis_y, "ch-ref"))
            y = axis_y + 54
        body += [whisker(x(r["ki"][0]), x(r["ki"][1]), track, series),
                 marker("circle", x(r["wert"]), track, series, hollow=not strong, title=tip)]
    body.append(line(4, y, width - 4, y, "ch-sep"))
    y += 22
    for r in plain:
        body.append(text(8 if wide else 4, y, r["kurz"], "ch-lbl"))
        if wide:
            body.append(text(width - 8, y, f'{r["urteil"]}, keine Zahl veröffentlicht', "ch-sub", "end"))
            y += 26
        else:
            body.append(text(4, y + 17, f'{r["urteil"]}, keine Zahl veröffentlicht', "ch-sub"))
            y += 44
    desc = "; ".join(f'{r["kurz"]}: {r["urteil"]}' + (f', {ci(r["wert"], *r["ki"], decimals=r["dezimal"], signed=True)}' if r.get("ki") else "")
                     for r in rows)
    return frame("forest", width, y + 2, uid, "Lassen sich die Stufen schärfen?", f"{desc}. Rückblick, nicht validiert.", body)


def f19(data: dict, *, width: int, uid: str) -> str:
    """F19: odds ratios of the five pre-set tests on two populations, the threshold, and the two controls apart."""
    wide = width >= WIDE
    rows, controls, limit = data["zeilen"], data["kontrollen"], data["schwelle"]
    bounds = [v for r in rows for k in ("alle", "signal") for v in r[k]["ki"]] + [v for c in controls for v in c["ki"]]
    lo, hi = min(0.92, min(bounds) * 0.995), max(1.2, max(bounds) * 1.01)
    ticks = [t / 100 for t in range(90, 135, 5) if lo <= t / 100 <= hi]
    x = Log((lo, hi), (222, 536) if wide else (20, width - 22))
    fmt = lambda v: num(v, 2)
    top = 46 if wide else 72
    step = 54 if wide else 70
    ys = [top + 22 + i * step for i in range(len(rows))]
    rule_y = ys[-1] + (34 if wide else 38)
    head_y = rule_y + 22
    cy = [head_y + (30 if wide else 42) + i * (60 if wide else 88) for i in range(len(controls))]
    axis_y = cy[-1] + (36 if wide else 54)
    height = axis_y + 44

    body = _key([("circle", "ser-main", False, "alle Fälle"), ("diamond", "ser-comp", True, "Fälle mit Signal")],
                222 if wide else 4, 16, 104 if wide else 104)
    if wide:
        body.append(text(width - 8, 16, "OR [Bereich]", "ch-col", "end"))
    else:
        body.append(text(4, top - 24, "Zahl: OR, alle Fälle", "ch-axt"))
    body.append(text(x(limit), top - (8 if wide else 24), f"Schwelle {num(limit, 2)}", "ch-sub", "middle"))
    body.append(x_axis(x, axis_y, top=top if wide else None, ticks=ticks, fmt=fmt,
                       label="Odds Ratio je Standardabweichung, log. Achse" if wide else "OR je Standardabw., log."))
    if wide:
        body += [line(x(1), top, x(1), axis_y, "ch-ref"), line(x(limit), top, x(limit), axis_y, "bf-thr")]

    for r, y in zip(rows, ys):
        combo = r["id"] == "alle"
        cls = "ch-lbl ch-strong" if combo else "ch-lbl"
        a, s = r["alle"], r["signal"]
        ya, ys2 = y - 9.5, y + 9.5
        if wide:
            body += [text(8, y + 5, r["name"], cls),
                     text(width - 8, ya + 4, ci(a["or"], *a["ki"], decimals=3), "ch-val", "end"),
                     text(width - 8, ys2 + 4, ci(s["or"], *s["ki"], decimals=3), "ch-val", "end")]
        else:
            body += _track_grid(x, ticks, y, 1, half=16)
            body.append(line(x(limit), y - 16, x(limit), y + 16, "bf-thr"))
            body += [text(4, y - 22, r["name"], cls), text(width - 4, y - 22, num(a["or"], 3), "ch-val", "end")]
        body += [whisker(x(a["ki"][0]), x(a["ki"][1]), ya, "ser-main", cap=3),
                 marker("circle", x(a["or"]), ya, "ser-main", size=4.5, title=f'{r["name"]}, alle Fälle: OR {ci(a["or"], *a["ki"], decimals=3)}'),
                 whisker(x(s["ki"][0]), x(s["ki"][1]), ys2, "ser-comp", cap=3),
                 marker("diamond", x(s["or"]), ys2, "ser-comp", hollow=True, size=4, title=f'{r["name"]}, Fälle mit Signal: OR {ci(s["or"], *s["ki"], decimals=3)}')]

    body.append(line(4, rule_y, width - 4, rule_y, "ch-sep"))
    body.append(text(8 if wide else 4, head_y, "Kontrollen, nicht Teil der fünf Prüfungen", "ch-col"))
    for c, y in zip(controls, cy):
        shape, hollow = ("square", False) if c["id"] == "positiv" else ("triangle", True)
        value = ci(c["or"], *c["ki"], decimals=3)
        how = f'Zusatzwert {"ja" if c["zusatzwert"] == "gefunden" else "nein"}, Prognosegewinn {"ja" if c["prognosegewinn"] == "gefunden" else "nein"}'
        if wide:
            body += [text(8, y + 5, c["name"], "ch-lbl"), text(8, y + 22, how, "ch-sub"),
                     text(width - 8, y + 4, value, "ch-val", "end"), text(width - 8, y + 22, c["wort"], "ch-sub", "end")]
        else:
            body += _track_grid(x, ticks, y, 1)
            body.append(line(x(limit), y - 9, x(limit), y + 9, "bf-thr"))
            body += [text(4, y - 16, c["name"], "ch-lbl"), text(4, y + 25, how, "ch-sub"), text(4, y + 41, c["wort"], "ch-sub")]
        body += [whisker(x(c["ki"][0]), x(c["ki"][1]), y, "ser-base"),
                 marker(shape, x(c["or"]), y, "ser-base", hollow=hollow, title=f'{c["name"]}: OR {value}, {c["wort"]}')]

    tests = "; ".join(f'{r["name"]}: {ci(r["alle"]["or"], *r["alle"]["ki"], decimals=3)}' for r in rows)
    ctrl = "; ".join(f'{c["name"]}: {ci(c["or"], *c["ki"], decimals=3)}, {c["wort"]}' for c in controls)
    desc = f"Urteil {data['urteil']}. Odds Ratios, alle Fälle: {tests}. Kontrollen: {ctrl}. Schwelle {num(limit, 2)}. Rückblick, nicht validiert."
    return frame("forest", width, height, uid, "Odds Ratios des Signaltempos und zwei Kontrollen", desc, body)


def _f20_panel(rows: list[dict], title: str, y0: float, width: int, decimals: int) -> tuple[list[str], float]:
    wide = width >= WIDE
    lows, highs = [r["ki95"][0] for r in rows], [r["ki95"][1] for r in rows]
    lo, hi = min(0, *lows), max(0, *highs)
    pad = (hi - lo) * 0.08
    domain = (lo - pad, hi + pad)
    x = Linear(domain, (108, 540) if wide else (20, width - 20))
    ticks = nice_ticks(*domain, 5)
    tick_dec = 0 if all(float(t).is_integer() for t in ticks) else 1
    step = 30 if wide else 46
    first = y0 + (56 if wide else 74)
    ys = [first + i * step for i in range(len(rows))]
    axis_y = ys[-1] + (24 if wide else 20)
    body = [text(8 if wide else 4, y0 + 14, title, "ch-lbl ch-strong"),
            text(8 if wide else 4, y0 + 33, "positiv: Herausforderer im Rückblick besser", "ch-axt"),
            x_axis(x, axis_y, top=first - 14 if wide else None, ticks=ticks, fmt=lambda v: num(v, tick_dec))]
    if wide:
        body.append(line(x(0), first - 14, x(0), axis_y, "ch-ref"))
    for r, y in zip(rows, ys):
        pooled = r["jahr"] == "alle Jahre"
        shape = "diamond" if pooled else "square"
        value = ci(r["wert"], *r["ki95"], decimals=decimals, signed=True)
        cls = "ch-lbl ch-strong" if pooled else "ch-lbl"
        if wide:
            body += [text(8, y + 5, r["jahr"], cls), text(width - 8, y + 5, value, "ch-val", "end")]
        else:
            body += _track_grid(x, ticks, y, 0)
            body += [text(4, y - 16, r["jahr"], cls), text(width - 4, y - 16, value, "ch-sub", "end")]
        body += [whisker(x(r["ki95"][0]), x(r["ki95"][1]), y, "ser-base"),
                 marker(shape, x(r["wert"]), y, "ser-base", size=5.5 if pooled else 4.5, title=f'{title}, {r["jahr"]}: {value}')]
    return body, axis_y + 34


def f20(data: dict, *, width: int, uid: str) -> str:
    """F20: distance of the frozen challenger to z3_v0 refitted per test year, in two measures on separate axes."""
    a, next_y = _f20_panel(data["brier_gewinn"], "Brier-Gewinn in 10⁻⁵", 4, width, 1)
    b, end = _f20_panel(data["top50_differenz"], "Differenz der Top-50-Quote in Prozentpunkten", next_y + 6, width, 1)
    brier = "; ".join(f'{r["jahr"]}: {ci(r["wert"], *r["ki95"], decimals=1, signed=True)}' for r in data["brier_gewinn"])
    top = "; ".join(f'{r["jahr"]}: {ci(r["wert"], *r["ki95"], decimals=1, signed=True)}' for r in data["top50_differenz"])
    desc = (f"Abstand des Herausforderers zu z3_v0, je Testjahr neu gelernt. Brier-Gewinn in 10⁻⁵: {brier}. "
            f"Differenz der Top-50-Quote in Prozentpunkten: {top}. Rückblick, nicht validiert; z3_v0 bleibt das Hauptmodell.")
    return frame("forest", width, end, uid, "Modellsuche: Abstand des Herausforderers zu z3_v0", desc, [*a, *b])
