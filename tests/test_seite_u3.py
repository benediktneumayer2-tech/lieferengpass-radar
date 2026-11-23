"""Page "Befunde": F07 whitelist, the wording of the verdicts, numbers against ergebnisse.json."""
import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from stockout_at import showcase
from stockout_at.archive import Archive
from stockout_at.charts import NARROW, WIDE, num
from stockout_at.charts import befunde as ch
from stockout_at.seiten import Quellen, befunde
from stockout_at.site import generate

DB = Path(__file__).resolve().parents[1] / "data" / "derived" / "stockout.sqlite"
ARCHIVE = DB.parents[1] / "archive"
RESULTS = showcase.load_results()
POISON = 7.77


def signal(sir, lo, hi):
    return {"faelle": 100, "treffer": 10, "quote": 0.1, "ki95": [0.05, 0.2], "erwartet": 8.0, "sir": sir, "sir_ki95": [lo, hi]}


def poison():
    return {"8_wochen": signal(POISON, POISON, POISON)}


def rueckblick(tmp_path: Path) -> Path:
    raw = {
        "t1_ausstieg": {"alle": poison()},
        "t7_gmp": {"alle": poison()},
        "t6_nachbarn": {
            "anderer_inhaber_gleicher_wirkstoff": {"8_wochen": {"mit": {"faelle": 200, "treffer": 20}, "erwartet": 12.5, "sir": 1.6, "sir_ki95": [1.54, 1.66]}},
            "atc4_nachbarn": {"nachbar_in_at": {"8_wochen": {"mit": {"faelle": 300, "treffer": 30}, "erwartet": 29.1, "sir": 1.03, "sir_ki95": [0.99, 1.08]}},
                              "nachbar_im_ausland": poison()},
        },
        "t8_marktaustritt": {"alle": {"8_wochen": signal(1.2, 0.83, 1.68)}},
        "t9_eko_streichung": {"alle": {"8_wochen": signal(0.8, 0.7, 0.9)}},
    }
    path = tmp_path / "json" / "rueckblick.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def page_context(tmp_path: Path) -> dict:
    rueckblick(tmp_path)
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    try:
        return befunde.context(Quellen(conn, None, RESULTS, None, {}, date(2026, 11, 23)))
    finally:
        conn.close()


def test_f07_reads_only_the_whitelist(tmp_path):
    ctx = page_context(tmp_path)
    blob = json.dumps({k: ctx[k] for k in ("f07", "ledger")}, ensure_ascii=False)
    assert num(POISON, 2) not in blob and str(POISON) not in blob
    assert ctx["f07"]["referenz"] is False
    assert [r[0] for r in ctx["f07"]["table"]["rows"]] == [s[1] for s in befunde.F07_SIGNALE]


def test_f07_verdict_follows_the_interval(tmp_path):
    rows = befunde.f07_rows(rueckblick(tmp_path))
    assert [r["urteil"] for r in rows] == ["trägt", "unklar", "unklar", "kein Gewinn"]
    assert rows[0]["faelle"] == 200 and rows[0]["treffer"] == 20


def test_page_survives_without_rueckblick(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    ctx = befunde.context(Quellen(conn, None, RESULTS, None, {}, date(2026, 11, 23)))
    conn.close()
    assert ctx["f07"] is None and ctx["f19"] and ctx["ledger"]["n"] == 10


def test_signal_speed_verdict_is_verbatim(tmp_path):
    ctx = page_context(tmp_path)
    block = RESULTS["signaltempo_tabelle"]
    assert ctx["tempo"]["urteil"] == "unklar" and ctx["tempo"]["text"] == block["urteil_text"]
    assert "fehlgeschlagen" in ctx["f19"]["caption"]
    text = json.dumps(ctx["f19"]["table"], ensure_ascii=False)
    for row in block["zeilen"]:
        for part in ("alle", "signal"):
            assert num(row[part]["or"], 3) in text and num(row[part]["ki"][1], 3) in text
    for c in block["kontrollen"]:
        assert num(c["or"], 3) in text
    assert not re.search("bestanden", " ".join([ctx["f19"]["svg_wide"], ctx["f19"]["svg_narrow"], ctx["f19"]["caption"], text]))


def test_f20_caption_and_numbers(tmp_path):
    ctx = page_context(tmp_path)
    block = RESULTS["modellsuche_zusammenfassung"]
    caption = ctx["f20"]["caption"]
    assert "je Testjahr" in caption and "neu gelernt" in caption
    assert "Die Top-50-Bereiche der einzelnen Jahre schließen 0 ein." in caption
    assert "kein Nachweis eines besseren Modells" in caption and "z3_v0 bleibt" in ctx["suche"]["entscheidung"]
    for row in block["top50_differenz"]:
        if row["jahr"] != "alle Jahre":
            assert row["ki95"][0] < 0 < row["ki95"][1]
    table = json.dumps(ctx["f20"]["table"], ensure_ascii=False)
    for key in ("brier_gewinn", "top50_differenz"):
        for row in block[key]:
            assert ch.ci(row["wert"], *row["ki95"], decimals=1, signed=True) in table


def test_charts_are_repeatable_and_use_classes_only(tmp_path):
    a, b = page_context(tmp_path), page_context(tmp_path)
    for fig in ("f07", "f18", "f19", "f20"):
        for svg in ("svg_wide", "svg_narrow"):
            assert a[fig][svg] == b[fig][svg]
            assert not re.search(r'(?:fill|stroke|style)="', a[fig][svg])
    assert f'viewBox="0 0 {WIDE} ' in a["f19"]["svg_wide"] and f'viewBox="0 0 {NARROW} ' in a["f19"]["svg_narrow"]


def test_page_renders_without_its_context(monkeypatch, tmp_path):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    def broken(q):
        raise RuntimeError("Test")
    monkeypatch.setattr(befunde, "context", broken)
    generate(DB, tmp_path / "site", ref=date(2026, 10, 17), archive=None)
    html = (tmp_path / "site" / "projekt" / "befunde" / "index.html").read_text(encoding="utf-8")
    assert "<h1" in html and 'id="fig-' not in html and 'id="ledger"' not in html


def test_built_page():
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    out = Path(__import__("tempfile").mkdtemp(prefix="befunde-"))
    try:
        generate(DB, out / "site", ref=date(2026, 10, 17), archive=Archive(ARCHIVE))
        html = (out / "site" / "projekt" / "befunde" / "index.html").read_text(encoding="utf-8")
    finally:
        import shutil
        shutil.rmtree(out, ignore_errors=True)
    for region in ("ledger", "fig-f07", "fig-f18", "fig-f19", "fig-f20"):
        assert f'id="{region}"' in html, region
    f07 = html.split('id="fig-f07"')[1].split("</figure>")[0]
    assert "Rückblick · nicht validiert" in f07 and RESULTS["referenzinstanz_satz"] not in f07
    for fig in ("f18", "f19", "f20"):
        part = html.split(f'id="fig-{fig}"')[1].split("</figure>")[0]
        assert "Rückblick · nicht validiert" in part and RESULTS["referenzinstanz_satz"] in part
    main = html.split("<main")[1].split("</main>")[0]
    for word in ("Fimea", "Finnland", "Stockout Forecaster", "inhaberwechsel", "mittel_v0", "z3_v0_mit_de", "BfArM", "bestanden"):
        assert word not in main, word
