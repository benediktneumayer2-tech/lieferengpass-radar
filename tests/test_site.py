"""Static site on the real derived database (skipped when it has not been built)."""
import json
import posixpath
import re
import sqlite3
import subprocess
import sys
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
    "projekt/": ["header", "archivieren", "verknuepfen", "pruefen", "footer-sources"],
    "projekt/idee/": ["header", "fig-f16", "fig-f29", "fig-f21", "fig-f04", "data-integrity", "footer-sources"],
    "projekt/modell/": ["header", "frage", "vergleich", "kalibrierung", "reihung", "schwaeche", "gewichte", "grenzen", "vorab"],
    "projekt/befunde/": ["header", "ledger", "ereignisse", "stufen", "tempo", "modellsuche", "folgen"],
    "projekt/ueber/": ["header", "about-h", "footer-sources"],
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


def test_project_pages_only_in_tabs(site):
    rail = re.search(r'<aside class="rail">.*?</aside>', (site / "index.html").read_text(encoding="utf-8"), re.S).group(0)
    assert re.findall(r">([^<]+)</a>", rail) == ["Übersicht", "Frühwarnung", "Überfällig", "Woche", "Wirkstoffe A–Z", "Projekt"]
    for route in ("projekt/", "projekt/idee/", "projekt/modell/", "projekt/befunde/", "methodik/", "projekt/ueber/"):
        tabs = re.search(r'<nav class="subnav".*?</nav>', (site / route / "index.html").read_text(encoding="utf-8"), re.S).group(0)
        assert tabs.count("<a ") == 6 and tabs.count('aria-current="page"') == 1, route


def test_site_import_loads_no_display_code():
    code = ("import sys; from stockout_at.site import HIDDEN_SOURCES as h; assert h == frozenset({'bfarm'}); "
            "assert not [m for m in sys.modules if m.startswith(('stockout_at.charts', 'stockout_at.seiten', 'stockout_at.live'))]")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_links_resolve_and_no_external_assets(site):
    files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    for page in site.rglob("*.html"):
        rel_dir = page.parent.relative_to(site).as_posix()
        html = page.read_text(encoding="utf-8")
        assert not re.search(r'(?:src|<link[^>]*href)="(?:https?:)?//', html), page
        for link in LINK.findall(html):
            if link.startswith(("http://", "https://", "#", "data:", "mailto:")):
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
    assert 'id="holder-changes"' not in html  # public rules: no holder-change hint (MIA) on the site
    others = html.split('id="other-holder-table"')[1].split("</table>")[0]
    listed = set(re.findall(r'ATC <span class="num">([A-Z0-9]{7})</span>', others))
    assert listed and listed <= reported


def test_public_rules(site):
    """Website shows only cleared sources under the display name, with the audience notice and disclaimers."""
    for page in site.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert "Stockout Forecaster" not in html and "Fimea" not in html and "Finnland" not in html, page
        assert 'id="audience"' in html and "kein Angebot des BASG" in html, page
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "<title>" in index and "Lieferengpass-Radar</title>" in index
    early = (site / "fruehwarnung" / "index.html").read_text(encoding="utf-8")
    assert "Keine Prognose, keine Bestellempfehlung" in early and "Verlautbarungsregister" not in early
    method = (site / "methodik" / "index.html").read_text(encoding="utf-8")
    assert "Verlautbarungsregister" not in method
    listed = set(re.findall(r'<th scope="row">([^<]+)</th><td class="num">', method))
    assert "BASG" in listed and not listed & {"BfArM (nur privat archiviert)", "bfarm", "fimea", "fimea_reg", "edqm",
                                              "mia_asp", "mia_abst", "mia_verl", "mia_ve"}
