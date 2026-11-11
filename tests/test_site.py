"""Static site on the real derived database (skipped when it has not been built)."""
import json
import posixpath
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from stockout_at.archive import Archive
from stockout_at.site import generate, package_slug, substance_slug

DB = Path(__file__).resolve().parents[1] / "data" / "derived" / "stockout.sqlite"
ARCHIVE = DB.parents[1] / "archive"
CONTRACT = {
    "": ["header", "search", "situation-summary", "weekly-changes", "footer-sources"],
    "packung/2426051/": ["header", "official-entry", "timeline", "own-analysis", "substance-link", "foreign-reports"],
    "wirkstoff/zolpidem/": ["header", "reported-packages", "unreported-equivalents", "foreign-reports", "disclaimer"],
    "fruehwarnung/": ["header", "warning-summary", "register-summary", "warning-list", "other-holders", "warning-method"],
    "ueberfaellig/": ["header", "overdue-table"],
    "woche/": ["header", "new-reports", "ended-reports"],
    "methodik/": ["header", "method-text", "archive-coverage", "sources"],
    "impressum/": ["header", "legal-text"],
    "datenschutz/": ["header", "legal-text"],
}
LINK = re.compile(r'(?:href|src)="([^"]*)"')


def test_slugs():
    assert substance_slug("ZOLPIDEM") == "zolpidem"
    assert substance_slug("AMIDOTRIZOESÄURE + LYSIN L") == "amidotrizoesaeure-lysin-l"
    assert package_slug("2426051") == "2426051"
    assert re.fullmatch(r"z-[0-9a-f]{10}", package_slug("Z:1-18469|20|Stück|Durchstechflasche 20 x 100 ml"))


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not DB.exists():
        pytest.skip("data/derived/stockout.sqlite fehlt (stockout build)")
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as conn:
        if any(conn.execute(f"SELECT NOT EXISTS (SELECT 1 FROM {t})").fetchone()[0]
               for t in ("foreign_items", "asp_packages")):
            pytest.skip("Datenbank ohne Auslands- oder ASP-Daten (z. B. nach dem BASG-Schnellstart)")
    out = tmp_path_factory.mktemp("w") / "site"
    generate(DB, out, ref=date(2026, 10, 17), archive=Archive(ARCHIVE))
    return out


def test_contract_routes_and_regions(site):
    for route, regions in CONTRACT.items():
        html = (site / route / "index.html").read_text(encoding="utf-8")
        assert '<html lang="de">' in html
        for region in regions:
            assert f'id="{region}"' in html, (route, region)


def test_links_resolve_and_no_external_assets(site):
    files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    for page in site.rglob("*.html"):
        rel_dir = page.parent.relative_to(site).as_posix()
        html = page.read_text(encoding="utf-8")
        assert not re.search(r'(?:src|<link[^>]*href)="(?:https?:)?//', html), page
        for link in LINK.findall(html):
            if link.startswith(("http://", "https://", "#", "data:")):
                continue
            path = link.split("#")[0].split("?")[0]
            target = posixpath.normpath(posixpath.join(rel_dir, path))
            if path.endswith("/") or path == "":
                target = posixpath.normpath(posixpath.join(target, "index.html"))
            assert target in files, (page, link)


def test_no_phone_numbers(site):
    conn = sqlite3.connect(DB)
    tels = {r[0].strip() for r in conn.execute("SELECT DISTINCT Zulassungsinhaber_Tel FROM snapshot_packages")}
    conn.close()
    tels = [t for t in tels if t and len(re.sub(r"\D", "", t)) >= 8]  # shorter values collide with PZNs
    assert tels
    pattern = re.compile("|".join(re.escape(t) for t in sorted(tels, key=len, reverse=True)))
    for path in [*site.rglob("*.html"), site / "search-index.json"]:
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_overdue_rows_and_search_index(site):
    html = (site / "ueberfaellig" / "index.html").read_text(encoding="utf-8")
    table = html.split('id="overdue-table"')[1].split("</table>")[0]
    from stockout_at import metrics
    conn = metrics.connect(DB)
    expected = len(metrics.collect(conn, date(2026, 10, 17))["overdue"])  # the real database grows every day
    conn.close()
    assert expected > 0 and table.split("<tbody>")[1].count("<tr>") == expected
    index = json.loads((site / "search-index.json").read_text(encoding="utf-8"))
    assert any(p[0] == "2426051" and p[3] == "packung/2426051/" for p in index["p"])
    assert ["ZOLPIDEM", "wirkstoff/zolpidem/"] == [s[:2] for s in index["s"] if s[0] == "ZOLPIDEM"][0]


def test_early_warning_hides_bfarm_and_lists_only_unreported(site):
    html = (site / "fruehwarnung" / "index.html").read_text(encoding="utf-8")
    table = html.split('id="warning-table"')[1].split("</table>")[0]
    assert table.count("<tr>") > 10
    assert "<strong>Deutschland</strong>" not in table and "BfArM" not in table and ">Deutschland<" not in table
    for page in [site / "fruehwarnung" / "index.html", site / "packung" / "2426051" / "index.html"]:
        assert "pharmnet-bund.de" not in page.read_text(encoding="utf-8")
    conn = sqlite3.connect(DB)
    reported = {r[0] for r in conn.execute("SELECT DISTINCT atc5 FROM episodes WHERE active = 1 AND atc5 IS NOT NULL")}
    conn.close()
    listed = set(re.findall(r'ATC <span class="num">([A-Z0-9]{7})</span>', table))
    assert listed and not listed & reported


def test_register_hints_list_marketed_unreported_products(site):
    html = (site / "fruehwarnung" / "index.html").read_text(encoding="utf-8")
    conn = sqlite3.connect(DB)
    reported = {r[0] for r in conn.execute("SELECT DISTINCT atc5 FROM episodes WHERE active = 1 AND atc5 IS NOT NULL")}
    conn.close()
    if 'id="holder-change-table"' in html:  # only with archived holder announcements (not fetched by this code)
        changes = html.split('id="holder-change-table"')[1].split("</table>")[0]
        assert not set(re.findall(r'ATC <span class="num">([A-Z0-9]{7})</span>', changes)) & reported
    others = html.split('id="other-holder-table"')[1].split("</table>")[0]
    listed = set(re.findall(r'ATC <span class="num">([A-Z0-9]{7})</span>', others))
    assert listed and listed <= reported

