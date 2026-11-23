"""Unit u5: situation figure F01, early-warning figures F05, F06, F35, project overview, About page."""
import contextlib
import io
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from stockout_at.archive import Archive
from stockout_at.charts import NARROW, WIDE, lage
from stockout_at.seiten.fruehwarnung import f05_data, f06_data, f35_data
from stockout_at.seiten.start import f01_data
from stockout_at.site import generate

DB = Path(__file__).resolve().parents[1] / "data" / "derived" / "stockout.sqlite"
ARCHIVE = DB.parents[1] / "archive"
HIDDEN = re.compile(r"bfarm|fimea|Finnland|Deutschland", re.I)

SIT = {"packages": 100, "active": 70, "by_status": {"Nicht verfügbar": 50, "eingeschränkt verfügbar": 20, "verfügbar": 25, "verfügbar gemäß §4 (1)": 5},
       "active_by_atc1": {"N": 40, "C": 20, "?": 10}}
RATE = {"faelle": 100, "treffer": 20, "quote": 0.2, "ki95": [0.13, 0.29]}
FW = {"rates": {"A": {"8_wochen": RATE, "12_wochen": RATE}, "B": None, "C": {"8_wochen": RATE, "12_wochen": RATE}, "1": {"8_wochen": RATE, "12_wochen": RATE}},
      "base": {"8_wochen": {"faelle": 1000, "treffer": 70, "quote": 0.07}, "12_wochen": {"faelle": 900, "treffer": 90, "quote": 0.1}},
      "rows": [{"tier": "A", "label": f"STOFF {i}", "countries": ["CZ", "IT", "HU", "ES", "SK"][:5 - i % 2], "country_names": ["Tschechien"]} for i in range(25)]
      + [{"tier": "B", "label": "ANDERE", "countries": ["IT"], "country_names": ["Italien"]}]}


def foreign_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE foreign_items (item_id TEXT, source TEXT, country TEXT, atc5 TEXT, status TEXT, end_date TEXT, last_seen TEXT, still_listed INTEGER)")
    conn.execute("CREATE TABLE foreign_links (item_id TEXT, pzn TEXT)")
    day = "2026-11-23"
    conn.executemany("INSERT INTO foreign_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("running", "aifa", "IT", "N01AA01", "unterbrechung", None, day, 1),
        ("future_end", "aifa", "IT", "N01AA02", None, "2026-12-24", day, 1),
        ("no_atc", "aifa", "IT", None, None, None, day, 1),
        ("ended", "aifa", "IT", "N01AA03", None, day, day, 1),
        ("gone", "aifa", "IT", "N01AA04", None, None, day, 0),
        ("stopped", "aifa", "IT", "N01AA05", "einstellung", None, day, 1),
        ("de", "bfarm", "DE", "N01AA06", None, None, day, 1),
        ("fi", "fimea", "FI", "N01AA07", None, None, day, 1),
    ])
    conn.executemany("INSERT INTO foreign_links VALUES (?, ?)", [("running", "1"), ("running", "2"), ("de", "3"), ("fi", "4")])
    return conn


def test_f35_counts_running_reports_of_public_sources_only():
    assert f35_data(foreign_db()) == [{"code": "IT", "name": "Italien", "reports": 3, "substances": 2, "at": 1}]


def test_f06_takes_tier_a_with_most_countries():
    data = f06_data(FW)
    assert len(data["rows"]) == 20 and data["tier_a"] == 25
    assert all(len(r["countries"]) == 5 for r in data["rows"][:13]) and "ANDERE" not in [r["label"] for r in data["rows"]]


def test_charts_are_repeatable_and_use_classes_only():
    f35 = f35_data(foreign_db())
    for chart, data in ((lage.f01, f01_data(SIT)), (lage.f05, f05_data(FW)), (lage.f06, f06_data(FW)), (lage.f35, f35)):
        for width in (WIDE, NARROW):
            svg = chart(data, width=width, uid="t")
            assert svg == chart(data, width=width, uid="t")
            assert not re.search(r'\s(?:style|fill|stroke)="', svg), chart.__name__


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt (stockout build)")
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        if not conn.execute("SELECT EXISTS (SELECT 1 FROM foreign_items)").fetchone()[0]:
            pytest.skip("Datenbank ohne Auslandsdaten")
    out = tmp_path_factory.mktemp("u5") / "site"
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        generate(DB, out, archive=Archive(ARCHIVE))
    assert "WARNUNG Seite" not in log.getvalue(), log.getvalue()
    return out


def page(site: Path, route: str) -> str:
    return (site / route / "index.html").read_text(encoding="utf-8")


def test_start_has_f01_in_the_situation_block_before_f22(built):
    html = page(built, "")
    block = html.split('id="situation-summary"')[1].split('id="forecast-vs-report"')[0]
    assert 'id="fig-f01"' in block and "Zahlen als Tabelle" in block
    assert html.count('id="fig-f01"') == 1 and 'id="fig-f22"' in html.split('id="forecast-vs-report"')[1]


def test_early_warning_figures_and_contract(built):
    html = page(built, "fruehwarnung")
    for fig in ("f05", "f06", "f35"):
        block = html.split(f'id="fig-{fig}"')[1].split("</figure>")[0]
        assert "<table" in block and not HIDDEN.search(block), fig
    assert html.index('id="fig-f05"') < html.index('id="warning-table"') and html.index('id="fig-f06"') < html.index('id="warning-table"')
    assert "Keine Prognose, keine Bestellempfehlung" in html and 'id="other-holder-table"' in html
    assert re.search(r'ATC <span class="num">[A-Z0-9]{7}</span>', html) and 'id="holder-changes"' not in html


def test_project_overview_keeps_f08_and_bench(built):
    html = page(built, "projekt")
    for region in ("archivieren", "verknuepfen", "pruefen", "fig-f04k", "fig-f05", "fig-f08", "bench-h"):
        assert f'id="{region}"' in html, region
    assert html.index('id="archivieren"') < html.index('id="verknuepfen"') < html.index('id="pruefen"')
    assert "Ein Hinweis, keine Prognose." in html


def test_about_shows_only_the_released_facts(built):
    main = page(built, "projekt/ueber").split("<main", 1)[1].split("</main>")[0]
    assert "Benedikt Neumayer" in main and "Wien" in main and "github.com/benediktneumayer2-tech/lieferengpass-radar" in main
    assert "@" not in main and "mailto:" not in main
    assert not re.search(r"\b(?:er|sein|seine|seinem|seinen|ihr|ihre|Autor|Autorin|Apotheker|Apothekerin)\b", re.sub(r"<[^>]+>", " ", main))
