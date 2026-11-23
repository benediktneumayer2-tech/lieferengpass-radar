"""Page "Idee und Aufbau" and the archive figures on Methodik."""
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from stockout_at.archive import Archive, SOURCES
from stockout_at.charts import NARROW, WIDE, archiv
from stockout_at.seiten.idee import ausduennen, versionen
from stockout_at.site import SITE_UNLISTED_SOURCES, generate
from stockout_at.status import collect

DB = Path(__file__).resolve().parents[1] / "data" / "derived" / "stockout.sqlite"
ARCHIVE = DB.parents[1] / "archive"
NOW = datetime(2026, 11, 23, 22, 0, tzinfo=timezone.utc)
HIDDEN_NAMES = re.compile(r"BfArM|Deutschland|Fimea|Finnland|EDQM|\bMIA\b|mia_|fimea|bfarm|edqm", re.I)


def test_thinning_counts_every_start_offset():
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(10)]
    one_day = (days[3], days[3])  # seen by exactly one of the two offsets at spacing 2
    long = (days[0], days[9])  # seen by every offset
    row = ausduennen(days, [one_day, long], (2,))[0]
    assert (row["mittel"], row["min"], row["max"]) == (0.5, 0, 1)


def test_f16_names_only_the_given_sources():
    data = {"auslandslisten": ["Italien", "EU"], "quellen": 2, "fassungen": 5, "fassungen_basg": 3, "staende": 66, "packungen": 4711,
            "episoden": 5572, "eingefroren": "21.10.2026", "zaehlt_ab": "01.01.2027"}
    for width in (WIDE, NARROW):
        svg = archiv.f16(data, width=width, uid="x")
        assert "4.711" in svg and "5.572" in svg and not HIDDEN_NAMES.search(svg)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    out = tmp_path_factory.mktemp("u4") / "site"
    generate(DB, out, archive=Archive(ARCHIVE), now=NOW)
    return out


def test_idee_page_has_all_figures_and_no_hidden_source(site):
    html = (site / "projekt" / "idee" / "index.html").read_text(encoding="utf-8")
    for region in ("fig-f16", "fig-f29", "fig-f21", "fig-f04", "data-integrity"):
        assert f'id="{region}"' in html, region
    assert "fig-f03" not in html and "fig-f02" not in html
    assert "0774523" in html and "keine Validierung" in html
    main = html.split("<main", 1)[1].split("</main>")[0]
    assert not HIDDEN_NAMES.search(main)


def test_methodik_keeps_its_regions_and_source_rows(site):
    html = (site / "methodik" / "index.html").read_text(encoding="utf-8")
    for region in ("method-text", "archive-coverage", "sources", "prognose", "fruehwarnung", "fig-f29", "fig-f21"):
        assert f'id="{region}"' in html, region
    listed = set(re.findall(r'<th scope="row">([^<]+)</th><td class="num">', html))
    assert "BASG" in listed and not listed & SITE_UNLISTED_SOURCES


def test_f21_counts_equal_the_methodik_table(site):
    coverage = collect(Archive(ARCHIVE), None, NOW)["sources"]
    expected = {k: v["versions"] for k, v in coverage.items() if k not in SITE_UNLISTED_SOURCES}
    rows = versionen(ARCHIVE)
    assert {z["key"]: z["versionen"] for z in rows} == expected
    assert not {z["key"] for z in rows} & SITE_UNLISTED_SOURCES and all(not SOURCES[z["key"]].watch for z in rows)


def test_thinning_reproduces_the_analysis_on_the_data_of_23_november():
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    live = [date.fromisoformat(r[0]) for r in conn.execute("SELECT snapshot_date FROM snapshots WHERE origin = 'live' ORDER BY 1")]
    if live[-1] != date(2026, 11, 23):
        pytest.skip("Zahlen der Analyse gelten für den Stand 23.11.2026")
    ended = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in conn.execute(
        "SELECT first_seen, last_seen FROM episodes WHERE first_seen > ? AND active = 0", (live[0].isoformat(),))]
    conn.close()
    assert len(ended) == 27
    assert [round(z["mittel"], 1) for z in ausduennen(live, ended)] == [4.0, 6.2, 13.8]
