"""Radar pages: F23 counts only date changes seen between two daily snapshots, and the tool pages keep their contract."""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockout_at.archive import Archive
from stockout_at.charts import NARROW, WIDE, num
from stockout_at.charts.radar import f23
from stockout_at.seiten.radar import KLASSEN, klasse, termine
from stockout_at.site import generate
from stockout_at.timeline import Ep

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "derived" / "stockout.sqlite"
ARCHIVE = ROOT / "data" / "archive"
D = date.fromisoformat


def _data(resupply, last="2026-11-23", end=None):
    ep = Ep(seq_no=1, start=D("2026-06-01"), start_source="beginn", first_seen=D("2026-07-18"), last_seen=D(last), active=end is None,
            end_reason=end, end_lower=None, end_upper=None, end_last_change=None, history_quality="sparse",
            duration_min=1, duration_max=1, statuses=[], resupply=[(a, D(seen)) for a, seen in resupply])
    return SimpleNamespace(
        snapshots=[{"snapshot_date": "2026-07-18", "origin": "legacy_local"}, {"snapshot_date": "2026-10-17", "origin": "live"},
                   {"snapshot_date": "2026-11-23", "origin": "live"}],
        eps={"A": [ep]}, packages={"A": {"pzn": "0000001", "path": "packung/0000001/", "substance": "X"}})


def test_change_on_first_daily_snapshot_is_the_baseline():
    t = termine(_data([("2026-09-30", "2026-07-18"), ("2026-12-31", "2026-10-17"), ("2027-01-31", "2026-11-01")]), D("2026-11-23"))
    assert (t["n_changes"], t["n_later"], t["n_earlier"], t["median_days"]) == (1, 1, 0, 31)
    assert t["moves"][0][2:] == (D("2026-12-31"), D("2027-01-31"))


def test_size_classes_end_at_the_longest_months():
    names = [n for n, _, _ in KLASSEN]
    for days, name in ((-1, "vorgezogen"), (1, "bis 1 Monat"), (31, "bis 1 Monat"), (32, "1–3 Monate"), (92, "1–3 Monate"),
                       (93, "3–6 Monate"), (184, "3–6 Monate"), (185, "6–12 Monate"), (366, "6–12 Monate"), (367, "über 1 Jahr")):
        assert names[klasse(days)] == name, days
    t = termine(_data([("2026-10-20", "2026-10-17"), ("2026-12-31", "2026-11-01"), ("2026-12-01", "2026-11-05")]), D("2026-11-23"))
    by_name = {c["name"]: (c["n"], c["n_after"]) for c in t["classes"]}
    assert by_name["vorgezogen"] == (1, 0) and by_name["1–3 Monate"] == (1, 1)  # +72 days, seen after 20.10.
    assert sum(c["n"] for c in t["classes"]) == t["n_changes"] and sum(c["n_after"] for c in t["classes"]) == t["n_after_due"]


def test_first_announcement_and_later_changes_do_not_count():
    assert termine(_data([("2026-12-31", "2026-11-01")]), D("2026-11-23")) is None  # a first date is not a change
    late = _data([("2026-12-31", "2026-10-17"), ("2027-01-31", "2026-11-20")])
    assert termine(late, D("2026-11-10")) is None  # nothing after the reference day
    assert termine(late, D("2026-10-17")) is None


def test_change_after_the_old_date_passed():
    t = termine(_data([("2026-10-20", "2026-10-17"), ("2026-12-31", "2026-11-01"), ("2026-12-01", "2026-11-05")]), D("2026-11-23"))
    assert (t["n_changes"], t["n_after_due"], t["n_later"], t["n_earlier"]) == (2, 1, 1, 1)


def test_chart_is_deterministic_and_uses_classes_only():
    t = termine(_data([("2026-09-30", "2026-10-17"), ("2028-06-30", "2026-11-01")]), D("2026-11-23"))
    for width in (WIDE, NARROW):
        svg = f23(t, width=width, uid="x")
        assert svg == f23(t, width=width, uid="x") and 'role="img"' in svg and "<desc" in svg
        assert not re.search(r'\s(?:fill|stroke|style)="', svg)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt")
    out = tmp_path_factory.mktemp("u6") / "site"
    generate(DB, out, archive=Archive(ARCHIVE), now=datetime(2026, 11, 23, 22, 0, tzinfo=timezone.utc))
    return out


def test_f23_matches_the_database_and_names_no_holder(site):
    html = (site / "ueberfaellig" / "index.html").read_text(encoding="utf-8")
    assert html.index('id="fig-f23"') < html.index('id="overdue-table"')
    conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    start = conn.execute("SELECT min(snapshot_date) FROM snapshots WHERE origin = 'live'").fetchone()[0]
    rows = conn.execute("""SELECT episode_id FROM (SELECT episode_id, first_seen, lag(announced) OVER (PARTITION BY episode_id ORDER BY seq) AS old
                           FROM episode_resupply) WHERE old IS NOT NULL AND first_seen > ?""", (start,)).fetchall()
    ids = sorted({r[0] for r in rows})
    holders = {r[0] for i in ids for r in conn.execute("SELECT zulassungsinhaber FROM episodes WHERE episode_id = ?", (i,)) if r[0]}
    conn.close()
    assert f'<dt class="lg">davon Termin geändert</dt><dd>{num(len(ids))}</dd>' in html
    assert f'<dd>{num(len(rows))} (' in html
    figure = html.split('id="fig-f23"')[1].split("</figure>")[0]
    assert figure.count("<tr>") == len(rows) + 1
    assert holders and not any(h in figure or escape(h) in figure for h in holders)


def test_overdue_body_rows_stay_plain(site):
    html = (site / "ueberfaellig" / "index.html").read_text(encoding="utf-8")
    body = html.split('id="overdue-table"')[1].split("</table>")[0].split("<tbody>")[1]
    assert body.count("<tr>") == len(re.findall(r"<tr\b", body)) > 0


def test_official_fields_stay_verbatim_and_apart(site):
    html = (site / "packung" / "2426051" / "index.html").read_text(encoding="utf-8")
    official = html.split('id="official-entry"')[1].split("</section>")[0]
    conn = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    name, reason = conn.execute("""SELECT Bezeichnung_Arzneispezialitaet, Grund FROM snapshot_packages
                                   WHERE package_key = '2426051' ORDER BY snapshot_id DESC LIMIT 1""").fetchone()
    conn.close()
    assert f"<dd>{escape(name, quote=True)}</dd>" in official.replace("&#39;", "&#x27;") or f"<dd>{name}</dd>" in official
    assert not reason or f"<dd>{reason}</dd>" in official or f"<dd>{escape(reason)}</dd>" in official
    assert "official-label" in official and "own-label" not in official
