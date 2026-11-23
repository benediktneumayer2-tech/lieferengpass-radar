"""Page "Modell und Prüfung": published numbers, the live figures on future states, what must never appear."""
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from stockout_at import live, modell, showcase
from stockout_at.archive import Archive
from stockout_at.charts import WIDE
from stockout_at.charts import modell as charts
from stockout_at.seiten import modell as seite
from stockout_at.site import generate

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "derived" / "stockout.sqlite"
ARCHIVE = DB.parents[1] / "archive"
RETRO = DB.parent / "vorhersagen_rueckblick"
RESULTS = showcase.load_results()
BLOCK = RESULTS["modell_rueckblick"]
SHA = modell.load_plan()[0]["sha256"]
START = date(2027, 1, 1)
VERDICT = re.compile(r"bestanden|bestätigt|stufen|ampel", re.I)  # never in a live figure of the test phase
FIGURES = ("f09", "f10", "f11", "f15", "f25", "f26", "f27", "f36")


def ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)


def code(i: int) -> str:
    return f"N{i // 100:02d}AX{i % 100:02d}"


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


def test_bands_reproduce_the_appendix():
    expected = {"28": (28841, 506, [(17221, 959, 84, 45, .54, .49, .36, .66), (5433, 518, 76, 44, 1.42, 1.40, 1.03, 1.89),
                                    (3280, 387, 108, 63, 2.81, 3.29, 2.53, 4.27), (1965, 290, 111, 67, 5.55, 5.65, 4.43, 7.18)]),
                "84": (24791, 1115, [(2156, 320, 23, 5, .89, 1.07, .43, 2.60), (9673, 726, 91, 27, 1.38, .94, .61, 1.44),
                                     (5148, 477, 149, 43, 2.86, 2.89, 2.08, 4.01), (3805, 379, 166, 50, 5.64, 4.36, 3.19, 5.94),
                                     (2380, 283, 268, 80, 11.21, 11.26, 8.83, 14.26), (1629, 206, 418, 106, 23.73, 25.66, 21.23, 30.65)])}
    for h, (cases, hits, rows) in expected.items():
        band = BLOCK["kalibrierung_horizonte"][h]
        assert (band["faelle"], band["treffer"]) == (cases, hits)
        for p, (n, g, k, gk, pred, obs, lo, hi) in zip(band["punkte"], rows):
            assert (p["n"], p["wirkstoffe"], p["treffer"], p["wirkstoffe_mit_meldung"]) == (n, g, k, gk)
            for value, target in ((p["vorhergesagt"], pred), (p["beobachtet"], obs), (p["ki95"][0], lo), (p["ki95"][1], hi)):
                assert abs(value * 100 - target) < 0.0051
    # at 4 weeks the top class has 13 substances and is pooled with its neighbour, as the rule in A5 says
    assert BLOCK["kalibrierung_horizonte"]["28"]["punkte"][-1]["klassen"] == [4, 5]


def test_total_matches_c2_and_blind_spots_hold_only_the_rueckblick():
    g = BLOCK["gesamtzahl"]
    rows = g["zeilen"]
    assert g["stichtage"] == 20 and round(g["korrelation"], 1) == -0.2
    assert (round(min(z["erwartet"] for z in rows)), round(max(z["erwartet"] for z in rows))) == (39, 52)
    assert (min(z["eingetroffen"] for z in rows), max(z["eingetroffen"] for z in rows)) == (24, 67)
    first, march = rows[0], next(z for z in rows if z["stichtag"] == "2026-03-12")
    assert (first["eingetroffen"], round(first["erwartet"])) == (67, 44) and (march["eingetroffen"], round(march["erwartet"])) == (24, 42)
    b = BLOCK["blinde_flecken"]
    t, m, u = b["gruppen"]["treffer"], b["gruppen"]["mitte"], b["gruppen"]["ueberraschung"]
    # Rückblick only, so deliberately fewer than the 291 of section C3, which pooled in the Einlaufphase
    assert (b["meldungen"], t["n"], m["n"], u["n"]) == (253, 67, 127, 59)
    assert b["bis"] <= "2026-10-21" and "davon_einlaufphase" not in json.dumps(b)
    assert (t["gruende"]["Erhöhter Mehrbedarf"], u["gruende"]["Erhöhter Mehrbedarf"]) == (5, 16)
    assert (t["gruende"]["Verzögerung bei der Herstellung"], u["gruende"]["Verzögerung bei der Herstellung"]) == (23, 6)
    assert (u["ohne_auslandssignal"], t["ohne_auslandssignal"]) == (32, 0)
    assert max(u["gruende"], key=u["gruende"].get) == "Erhöhter Mehrbedarf"  # the caption says so


def test_block_is_reproducible():
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    conn = ro()
    stand = conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0]
    if stand != BLOCK["basg_stand"]:
        conn.close()
        pytest.skip("die Datenbank ist neuer als der Block; er bleibt der Stand seines Datums")
    block = seite.rueckblick_block(conn, RETRO)
    conn.close()
    assert json.loads(json.dumps(block)) == BLOCK


def test_weights_equal_the_frozen_model():
    model = json.loads((ROOT / "models" / "z3_v0.json").read_text(encoding="utf-8"))["horizonte"]["56"]["gewichte_geprueft"]
    for g in RESULTS["z3_gewichte_8_wochen"]["gruppen"]:
        for m in g["merkmale"]:
            assert m["gewicht"] == pytest.approx(model[m["id"]], abs=5e-5), m["id"]
    assert "inhaberwechsel_56" not in json.dumps(RESULTS["z3_gewichte_8_wochen"])


def test_one_pass_panels_equal_live_build():
    if not DB.exists() or not list((ARCHIVE / modell.LOG_DIR).glob("*/*.csv.gz")):
        pytest.skip("keine Daten")
    conn = ro()
    merged = seite.with_bands(RESULTS)
    beginn, step, sha = live._plan()
    starts, seen, _, stand = modell.report_days(conn)
    logs = seite.read_logs(ARCHIVE, beginn, sha)
    for h in seite.HORIZONTE:
        assert seite.panel(logs[h], starts, seen, stand, beginn, step, merged, h) == live.build(conn, ARCHIVE, merged, h)
    rang = seite.rangkurve(logs[56], seen, beginn)
    conn.close()
    assert rang["einlauf"]["top50"] == live.build(ro(), ARCHIVE, merged, 56)["einlauf"]["meldungen"]["top50"]


def future(tmp_path: Path) -> tuple[dict, dict]:
    """A synthetic log with an Einlaufphase and a mature test phase, and the page's data on it."""
    ps = {code(c * 100 + i): p for c, p in enumerate((0.005, 0.015, 0.03, 0.06, 0.12, 0.25)) for i in range(40)}
    days = [date(2026, 10, 21) + timedelta(days=i) for i in range(3)] + [START + timedelta(days=i) for i in range(3)] + [START + timedelta(days=14)]
    for d in days:
        write_day(tmp_path, d, ps)
    reports = [(code(500 + i), date(2026, 10, 23)) for i in range(25)] + [(code(400 + i), START + timedelta(days=2)) for i in range(25)]
    conn = make_db(tmp_path / "f.sqlite", date(2027, 3, 12), reports)
    beginn, step, sha = live._plan()
    starts, seen, _, stand = modell.report_days(conn)
    logs = seite.read_logs(tmp_path, beginn, sha)
    merged = seite.with_bands(RESULTS)
    panels = [seite.panel(logs[h], starts, seen, stand, beginn, step, merged, h) for h in seite.HORIZONTE]
    extra = seite.gesamtzahl_live(logs[56], live._events(starts, seen), stand, beginn, step)
    figs = {"f10": seite._f10(panels, RESULTS), "f25": seite._f25(seite.rangkurve(logs[56], seen, beginn), RESULTS),
            "f36": seite._f36(seite.wechsel(logs[56], beginn), RESULTS), "f27": seite._f27(BLOCK, extra, RESULTS)}
    conn.close()
    return figs, ps


def test_test_phase_has_no_verdict_no_tier_curve_and_no_substance(tmp_path):
    figs, ps = future(tmp_path)
    for name, fig in figs.items():
        blob = " ".join([fig["svg_wide"], fig["svg_narrow"], str(fig["legend"]), fig["caption"], fig["source"], json.dumps(fig["table"], ensure_ascii=False)])
        assert not VERDICT.search(blob), name
        assert not [a for a in ps if a in blob], name
        assert RESULTS["referenzinstanz_satz"] in fig["caption"], name
        assert fig["kind"] == "live", name
    for name in ("f10", "f25", "f27"):
        assert re.search(r'<path class="mk ser-main" d="M[^"]+Z"/>', figs[name]["svg_wide"]), name  # diamonds of the test phase
    assert "Prüfungsbeginn" in figs["f36"]["svg_wide"]


def test_phases_are_never_pooled(tmp_path):
    ps = {code(i): 0.02 + i / 10000 for i in range(120)}
    for d in (date(2026, 12, 30), date(2026, 12, 31), START, START + timedelta(days=1)):
        write_day(tmp_path, d, ps)
    out = seite.wechsel(seite.read_logs(tmp_path, START, SHA[:12])[56], START)
    assert [z["tag"] for z in out["zeilen"]] == ["2026-12-31", "2027-01-02"]  # 31.12. to 01.01. crosses the phases and counts in neither
    assert (out["einlauf"]["tage"], out["pruefung"]["tage"]) == (1, 1)


def test_empty_state_builds():
    empty = seite.rangkurve({}, {}, START)
    assert empty["einlauf"]["anzahl"] == 0
    assert "Noch zu wenige neue Meldungen" in charts.f25(empty, width=WIDE, uid="x")
    assert seite._f25(empty, RESULTS)["table"]["rows"][0][1] == "–"


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    out = tmp_path_factory.mktemp("u2") / "site"
    generate(DB, out, archive=Archive(ARCHIVE), now=datetime(2026, 11, 23, 12, tzinfo=timezone.utc))
    return (out / "projekt" / "modell" / "index.html").read_text(encoding="utf-8")


def test_page_has_every_figure_with_table_and_tag(page):
    for name in FIGURES:
        section = page.split(f'id="fig-{name}"')[1].split("</figure>")[0]
        assert "<svg" in section and "Zahlen als Tabelle" in section, name
    assert 'id="fig-f12"' not in page and 'id="fig-f13"' not in page
    assert page.count("Rückblick · nicht validiert") >= 5
    assert "Die Gesamtzahl neuer Meldungen sagt es nicht voraus" in page


def test_page_keeps_the_published_lead_numbers(page):
    v = next(m for m in RESULTS["z3_rueckblick"]["vorlauf"]["verfahren"] if m["id"] == "z3_v0")
    assert (v["tag_davor"], v["median_tage_auf_liste"]) == (0.25, 59)
    readouts = page.split("Probelauf 2026")[1].split("</dl>")[0]
    assert "25" in readouts and ">59<" in readouts


def test_page_rules(page):
    for word in ("Fimea", "Finnland", "Stockout Forecaster", "inhaberwechsel", "z3_v0_mit_de", "mittel_v0", "nicht verfügbar sein"):
        assert word not in page, word
    rule = RESULTS["vorab_registrierung"]["bestehensregel"]
    assert rule.startswith("Bestanden, wenn") and page.count(rule) == 1  # the pre-registered rule, word for word
    assert not re.search(r"bestanden|bestätigt", page.replace(rule, ""), re.I)  # no statement that the model has passed
    f26 = page.split('id="fig-f26"')[1].split("</figure>")[0]
    assert "Die Einlaufphase ist nicht enthalten" in f26 and f26.count("Einlaufphase") == 1
    atc = {a for rows in live._read_logs(ARCHIVE, "z3_v0_p8", START, SHA[:12]).values() for a in rows}
    main = page.split("<main", 1)[1].split("</main>")[0]
    assert atc and not [a for a in atc if a in main]
