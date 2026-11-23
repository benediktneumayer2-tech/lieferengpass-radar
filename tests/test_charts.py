"""F22 "Vorhersage gegen Meldung": data contract, future states on a synthetic log, privacy of the markup."""
import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from stockout_at import live, modell, showcase
from stockout_at.archive import Archive
from stockout_at.charts import NARROW, WIDE
from stockout_at.charts.live import f22, status_sentence
from stockout_at.site import generate
from stockout_at.vorlauf import _wilson

DB = Path(__file__).resolve().parents[1] / "data" / "derived" / "stockout.sqlite"
ARCHIVE = DB.parents[1] / "archive"
SHA = modell.load_plan()[0]["sha256"]
RESULTS = showcase.load_results()
CLASS_P = (0.005, 0.015, 0.03, 0.06, 0.12, 0.25)  # one value inside each of the six classes
START = date(2027, 1, 1)
# Words that would read as a verdict on the running test; none may appear before the report.
VERDICT = re.compile(r"bestanden|bestätigt|Stufenregel|stufen_v0", re.I)


def code(i: int) -> str:
    return f"N{i // 100:02d}AX{i % 100:02d}"


def day_rows(per_class: int = 40, classes: tuple = CLASS_P) -> dict[str, float]:
    return {code(c * 100 + i): p for c, p in enumerate(classes) for i in range(per_class)}


def write_day(root: Path, day: date, ps: dict[str, float], sha: str = SHA) -> None:
    rows = {a: {"stufe": "-", "p": {h: {n: p for n in modell.METHODS} for h in modell.HORIZONS}} for a, p in ps.items()}
    modell.write_log(root, day.isoformat(), rows, sha)


def make_db(path: Path, stand: date, reports: list[tuple[str, date]]) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE snapshots (snapshot_date TEXT)")
    conn.execute("CREATE TABLE episodes (atc5 TEXT, start_date TEXT, first_seen TEXT, end_upper TEXT, active INTEGER)")
    conn.execute("INSERT INTO snapshots VALUES (?)", (stand.isoformat(),))
    conn.executemany("INSERT INTO episodes VALUES (?, ?, ?, NULL, 1)", [(a, t.isoformat(), t.isoformat()) for a, t in reports])
    conn.commit()
    return conn


def hits(day: date, per_class: tuple = (1, 2, 3, 5, 8, 12), after: int = 20) -> list[tuple[str, date]]:
    """The first `n` substances of each class get a new report `after` days later."""
    return [(code(c * 100 + i), day + timedelta(days=after)) for c, n in enumerate(per_class) for i in range(n)]


def render(data: dict) -> tuple[str, str, dict]:
    return f22(data, width=WIDE, uid="w"), f22(data, width=NARROW, uid="n"), showcase.f22_context(data, RESULTS)


def assert_no_substance(ps: dict[str, float], *texts: str) -> None:
    blob = "".join(texts)
    assert not [a for a in ps if a in blob]


def public_text(ctx: dict) -> str:
    fig = ctx["figure"]
    return " ".join([fig["svg_wide"], fig["svg_narrow"], fig["caption"], fig["source"], json.dumps(fig["table"], ensure_ascii=False),
                     json.dumps(ctx["phases"], ensure_ascii=False)])


def test_retrospective_band_reproduces_the_appendix():
    block = RESULTS["vorhersage_gegen_meldung"]
    band = block["horizonte"]["56"]
    assert block["basg_stand"] == "2026-11-23" and block["art"] == "rueckblick"
    assert (band["faelle"], band["treffer"], band["stichtage"]) == (27506, 901, 20)
    expected = [(9030, 617, 43, 17, 0.77, 0.48, 0.28, 0.81), (7397, 608, 99, 33, 1.37, 1.34, 0.92, 1.94),
                (5106, 465, 145, 53, 2.84, 2.84, 2.13, 3.78), (3176, 349, 185, 65, 5.62, 5.82, 4.44, 7.60),
                (1959, 261, 236, 90, 11.17, 12.05, 9.74, 14.81), (838, 123, 193, 68, 20.36, 23.03, 18.15, 28.76)]
    for p, (n, g, k, gk, pred, obs, lo, hi) in zip(band["punkte"], expected, strict=True):
        assert (p["n"], p["wirkstoffe"], p["treffer"], p["wirkstoffe_mit_meldung"]) == (n, g, k, gk)
        for value, target in ((p["vorhergesagt"], pred), (p["beobachtet"], obs), (p["ki95"][0], lo), (p["ki95"][1], hi)):
            assert abs(value * 100 - target) < 0.0051


def test_first_einlauf_points_after_16_december(tmp_path):
    ps = day_rows()
    first = date(2026, 10, 21)
    for i in range(3):
        write_day(tmp_path, first + timedelta(days=i), ps)
    before = make_db(tmp_path / "a.sqlite", date(2026, 12, 15), hits(first))
    data = live.build(before, tmp_path, RESULTS)
    assert data["einlauf"]["punkte"] == [] and data["einlauf"]["naechster_termin"] == "2026-12-16"
    assert "Erste Punkte der Einlaufphase am 16.12.2026" in f22(data, width=WIDE, uid="w")

    conn = make_db(tmp_path / "b.sqlite", date(2026, 12, 16), hits(first))
    data = live.build(conn, tmp_path, RESULTS)
    e = data["einlauf"]
    assert (e["protokolltage_reif"], e["faelle"], e["treffer"]) == (1, 240, 31)
    assert [p["klassen"] for p in e["punkte"]] == [[i] for i in range(6)]
    assert e["naechster_termin"] == "2026-12-17"
    wide, narrow, ctx = render(data)
    for svg in (wide, narrow):
        assert 'class="mk ser-main mk-hollow"' in svg and "Erste Punkte der Prüfung am 26.02.2027" in svg
    assert_no_substance(ps, public_text(ctx))
    assert not VERDICT.search(public_text(ctx))


def test_first_pruefung_diamonds_match_bewerten(tmp_path):
    ps = day_rows()
    write_day(tmp_path, date(2026, 12, 31), ps)  # Einlaufphase, last day
    write_day(tmp_path, START, ps)
    write_day(tmp_path, START + timedelta(days=1), ps)  # not a reference day of the plan
    write_day(tmp_path, START + timedelta(days=14), ps, sha="0" * 64)  # reference day, but written without the plan
    near = hits(START, after=3)  # two days after the last log before them
    far = [(code(5 * 100 + 30), START + timedelta(days=50))]  # no log in the 7 days before: a hit in panel b, no dot in panel a
    conn = make_db(tmp_path / "t.sqlite", date(2027, 3, 12), near + far)
    data = live.build(conn, tmp_path, RESULTS)
    p = data["pruefung"]
    scored = modell.bewerten(conn, tmp_path, START, None, SHA)["horizonte"]["56"]
    assert (p["faelle"], p["treffer"], p["stichtage_reif"]) == (scored["faelle"], scored["meldungen"], scored["stichtage"])
    assert p["stichtage_reif"] == 1 and p["faelle"] == 240

    # Phases are never pooled: the last Einlaufphase day and the reference day stay separate.
    assert data["einlauf"]["protokolltage_reif"] == 1 and data["einlauf"]["faelle"] == 240
    # A new report is counted in the phase of the prediction day before it.
    assert p["meldungen"]["anzahl"] == len(near)
    assert p["meldungen"]["je_klasse"] == [1, 2, 3, 5, 8, 12] and data["einlauf"]["meldungen"]["anzahl"] == 0

    wide, narrow, ctx = render(data)
    for svg in (wide, narrow):
        assert re.search(r'<path class="mk ser-main" d="M[^"]+Z"/>', svg)  # filled diamonds
        assert 'class="mk ser-main mk-hollow"' in svg  # hollow circles of the Einlaufphase beside them
    test_phase = ctx["phases"][2]
    assert test_phase["led"] == "working" and test_phase["word"] == "Prüfung läuft"
    assert_no_substance(ps, public_text(ctx))
    assert not VERDICT.search(public_text(ctx))


def test_class_pooling_below_30_substances(tmp_path):
    ps = {**day_rows(40, CLASS_P[:5]), **{code(500 + i): 0.25 for i in range(10)}}  # the top class has only 10 substances
    first = date(2026, 10, 21)
    write_day(tmp_path, first, ps)
    conn = make_db(tmp_path / "p.sqlite", date(2026, 12, 16), hits(first, (1, 2, 3, 5, 8, 4)))
    data = live.build(conn, tmp_path, RESULTS)
    groups = [p["klassen"] for p in data["einlauf"]["punkte"]]
    assert groups == [[0], [1], [2], [3], [4, 5]]
    assert data["einlauf"]["punkte"][-1]["wirkstoffe"] == 50
    wide, narrow, ctx = render(data)
    assert "zusammengelegt" in wide and "zusammengelegt" in narrow
    assert "zusammengelegt" in json.dumps(ctx["figure"]["table"], ensure_ascii=False)


def test_too_few_substances_show_a_sentence_and_no_point(tmp_path):
    first = date(2026, 10, 21)
    ps = {code(i): 0.05 for i in range(20)}
    write_day(tmp_path, first, ps)
    conn = make_db(tmp_path / "f.sqlite", date(2026, 12, 16), [(code(0), first + timedelta(days=9))])
    data = live.build(conn, tmp_path, RESULTS)
    assert data["einlauf"]["zu_wenige"] and data["einlauf"]["punkte"] == []
    assert "Noch zu wenige Fälle" in f22(data, width=WIDE, uid="w")


def test_zero_hits_sit_on_the_axis_with_an_arrow(tmp_path):
    ps = day_rows()
    first = date(2026, 10, 21)
    write_day(tmp_path, first, ps)
    conn = make_db(tmp_path / "z.sqlite", date(2026, 12, 16), hits(first, (0, 2, 3, 5, 8, 12)))
    data = live.build(conn, tmp_path, RESULTS)
    p = data["einlauf"]["punkte"][0]
    assert p["treffer"] == 0 and p["ki95"][0] == 0
    assert p["ki95"][1] == pytest.approx(1 - 0.05 ** (1 / 40))
    assert 'class="f22-arrow"' in f22(data, width=WIDE, uid="w") and 'class="f22-arrow"' in f22(data, width=NARROW, uid="n")


def test_interval_is_close_to_wilson_for_a_single_log_day():
    per = {code(i): [1, int(i < 10)] for i in range(100)}
    lo, hi = live._interval(per, 100, 10)
    wilson = _wilson(10, 100)
    assert abs(lo - wilson[0]) < 0.01 and abs(hi - wilson[1]) < 0.015


def test_many_dots_shrink_and_stay_countable(tmp_path):
    ps = day_rows(60)
    first = date(2026, 10, 21)
    write_day(tmp_path, first, ps)
    reports = [(code(500 + i), first + timedelta(days=1)) for i in range(60)] + [(code(i), first + timedelta(days=1)) for i in range(3)]
    conn = make_db(tmp_path / "m.sqlite", date(2026, 11, 1), reports)
    data = live.build(conn, tmp_path, RESULTS)
    assert data["einlauf"]["meldungen"]["je_klasse"] == [3, 0, 0, 0, 0, 60]
    for width in (WIDE, NARROW):
        svg = f22(data, width=width, uid="x")
        assert svg.count('class="mk ser-main mk-hollow"') >= 63  # every report keeps its own dot


def test_real_figure_has_no_substance_codes_and_is_repeatable():
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    days = sorted((ARCHIVE / modell.LOG_DIR).glob("*/*.csv.gz"))
    if not days:
        pytest.skip("keine Vorhersageprotokolle")
    logged = live._read_logs(ARCHIVE, "z3_v0_p8", START, SHA[:12])
    first = live.build(conn, ARCHIVE, RESULTS)
    second = live.build(conn, ARCHIVE, RESULTS)
    conn.close()
    assert first == second
    a, b = showcase.f22_context(first, RESULTS), showcase.f22_context(second, RESULTS)
    assert a["figure"]["svg_wide"] == b["figure"]["svg_wide"] and a["figure"]["svg_narrow"] == b["figure"]["svg_narrow"]
    text = public_text(a)
    codes = {c for rows in logged.values() for c in rows}
    assert codes and not [c for c in codes if c in text]
    assert not VERDICT.search(text)
    assert sum(first["heute"]["je_klasse"]) == first["heute"]["wirkstoffe"]
    assert RESULTS["referenzinstanz_satz"] in a["figure"]["caption"]


def test_start_page_without_logs_and_no_forecast_words(tmp_path):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    out = tmp_path / "site"
    generate(DB, out, ref=date(2026, 10, 17), archive=None)
    html = (out / "index.html").read_text(encoding="utf-8")
    for region in ("search", "situation-summary", "early-warning", "weekly-changes", "fig-f22"):
        assert f'id="{region}"' in html, region
    assert RESULTS["referenzinstanz_satz"] in html
    assert "Noch keine Protokolle" in html
    assert "Vorhersage gegen Meldung" in html
    assert 'href="../' not in html
