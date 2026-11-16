import gzip
import json
import os
import time
from datetime import datetime, timedelta, timezone
from email.message import Message

import pytest

from stockout_at.archive import Archive, basg_produced_on, fetch_all
from stockout_at.mirror import mirror, verify
from stockout_at.status import collect, missing_basg_days

BASG = b"""<?xml version="1.0" encoding="UTF-8"?>
<VEASP><Meta version="1" countryScope="AUT" producedOn="2026-10-17T02:00:08"><Author>AGES</Author></Meta>
<Packungen><Packung PZN="1"><Status>Nicht verf\xc3\xbcgbar</Status></Packung></Packungen></VEASP>"""
EMA = b"PK\x03\x04fake-xlsx"


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status, self.headers = body, status, Message()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(bodies):
    def opener(req, timeout):
        body = bodies[req.full_url]
        if isinstance(body, Exception):
            raise body
        return Resp(body)
    return opener


def urls():
    from stockout_at.archive import SOURCES
    return {n: s.url for n, s in SOURCES.items()}


def test_fetch_stores_new_versions_and_records_failures_without_blocking(tmp_path):
    u = urls()
    archive = Archive(tmp_path / "a")
    opener = opener_for({u["basg"]: BASG, u["bfarm"]: OSError("kaputt"), u["ema"]: EMA})
    entries = fetch_all(archive, ["basg", "bfarm", "ema"], opener=opener, sleep=lambda s: None)

    by = {e["source"]: e for e in entries}
    assert by["basg"]["ok"] and not by["basg"]["duplicate"]
    assert by["basg"]["produced_on"] == "2026-10-17T02:00:08"
    assert by["basg"]["path"].startswith("basg/2026/2026-10-17T02-00-08_")
    assert gzip.decompress((archive.root / by["basg"]["path"]).read_bytes()) == BASG
    assert not by["bfarm"]["ok"] and by["bfarm"]["attempts"] == 3 and "kaputt" in by["bfarm"]["error"]
    assert by["ema"]["ok"] and by["ema"]["warnings"] == []

    # second run: identical content is only noted, no new file
    again = fetch_all(Archive(archive.root), ["basg"], opener=opener, sleep=lambda s: None)
    assert again[0]["duplicate"] and again[0]["path"] == by["basg"]["path"]
    assert len(list(archive.root.rglob("*.gz"))) == 2
    assert len(archive.entries()) == 4


def test_paged_source_is_stored_as_one_jsonl_bundle(tmp_path):
    from stockout_at.archive import SOURCES
    url = SOURCES["cima"].url
    pages = {url.format(page=1): b'{"pagina":1,"resultados":[{"cn":"1"}]}',
             url.format(page=2): b'{"pagina":2,"resultados":[{"cn":"2"}]}',
             url.format(page=3): b'{"pagina":3,"resultados":[]}'}
    archive = Archive(tmp_path / "a")
    e = fetch_all(archive, ["cima"], opener=opener_for(pages), sleep=lambda s: None)[0]
    assert e["ok"] and e["path"].endswith(".jsonl.gz") and e["warnings"] == []
    assert archive.read(e["path"]).split(b"\n") == [pages[url.format(page=1)], pages[url.format(page=2)]]


def test_produced_on_missing_is_kept_but_counts_as_failure(tmp_path):
    u = urls()
    archive = Archive(tmp_path / "a")
    [e] = fetch_all(archive, ["basg"], opener=opener_for({u["basg"]: b"<html>Wartung</html>"}), sleep=lambda s: None)
    assert not e["ok"] and e["attempts"] == 3 and e["warnings"] and (archive.root / e["path"]).exists()
    assert basg_produced_on(BASG) == "2026-10-17T02:00:08"


def test_maintenance_page_is_retried_and_fetched_again_next_run(tmp_path):
    from stockout_at.archive import SOURCES, _fetched_recently
    from stockout_at.build import _unique_files
    u = urls()
    xls = b"\xd0\xcf\x11\xe0fake-xls"
    answers = [b"<html>Site en maintenance</html>"] * 3 + [xls]
    waits = []

    def opener(req, timeout):
        assert req.full_url == u["ansm"]
        return Resp(answers.pop(0))

    archive = Archive(tmp_path / "a")
    [bad] = fetch_all(archive, ["ansm"], opener=opener, sleep=waits.append)
    assert not bad["ok"] and bad["attempts"] == 3 and len(waits) == 2
    assert "Formatprüfung: keine xls-Datei" in bad["error"]
    assert archive.read(bad["path"]).startswith(b"<html>")  # kept for diagnosis
    assert not _fetched_recently(archive, SOURCES["ansm"]) and _unique_files(archive, "ansm") == []

    [good] = fetch_all(archive, ["ansm"], opener=opener, sleep=waits.append)
    assert good["ok"] and good["warnings"] == [] and archive.read(good["path"]) == xls
    assert _fetched_recently(archive, SOURCES["ansm"]) and [e["path"] for e in _unique_files(archive, "ansm")] == [good["path"]]


def test_stale_capture_is_left_out_and_a_new_one_fails(tmp_path):
    """A cache served an older version (ogyei 2026-10-22): the build ignores it; a new one is a failed fetch."""
    import sqlite3
    from stockout_at.archive import retry_due, stale_paths
    from stockout_at.build import _unique_files, build

    def hu(*tks):
        return ("Termék neve;TK szám;A hiány kezdete;ATC kód 1/ATC kód 2\n"
                + "".join(f"Produkt {tk};{tk};01.06.2026;N02BE01\n" for tk in tks)).encode("iso-8859-2")

    archive = Archive(tmp_path / "a")

    def put(source, body, fetched, lm, ext="csv"):
        return archive.store(source, body, ext=ext, stamp=fetched.replace(":", ""),
                             meta={"origin": "live", "fetched_at": fetched, "last_modified": lm, "warnings": []})

    good = put("ogyei", hu(1, 2), "2026-10-22T05:00:00Z", "Thu, 22 Oct 2026 00:30:45 GMT")
    old = put("ogyei", hu(1, 2, 9), "2026-10-22T16:24:53Z", "Thu, 11 Jun 2026 12:43:44 GMT")  # archived before the rule
    later = put("ogyei", hu(1), "2026-10-23T05:00:00Z", "Fri, 23 Oct 2026 00:30:40 GMT")
    put("basg", BASG, "2026-10-17T02:00:08Z", None, "xml")  # BASG sends no Last-Modified: never stale
    put("basg", BASG.replace(b"2026-10-17", b"2026-10-16"), "2026-10-18T02:00:08Z", None, "xml")
    assert stale_paths(archive.entries()) == {old["path"]}
    assert [e["path"] for e in _unique_files(archive, "ogyei")] == [good["path"], later["path"]]
    assert len(_unique_files(archive, "basg")) == 2
    build(archive, tmp_path / "db.sqlite")
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    hu_items = dict(conn.execute("SELECT product, last_seen FROM foreign_items WHERE source = 'ogyei'"))
    assert hu_items == {"Produkt 1": "2026-10-23", "Produkt 2": "2026-10-22"}  # Produkt 9 only in the stale file
    conn.close()

    def opener(answers):
        def open_(req, timeout):
            body, lm = answers.pop(0)
            r = Resp(body)
            r.headers["Last-Modified"] = lm
            return r
        return open_

    june = (hu(1, 2, 7), "Wed, 10 Jun 2026 08:00:00 GMT")
    [bad] = fetch_all(archive, ["ogyei"], opener=opener([june] * 3), sleep=lambda s: None)
    assert not bad["ok"] and bad["attempts"] == 3 and "veraltete Fassung" in bad["error"]
    assert archive.read(bad["path"]) == hu(1, 2, 7) and "ogyei" in retry_due(archive)  # kept; catch-up run retries
    [again] = fetch_all(archive, ["ogyei"], opener=opener([june] * 3), sleep=lambda s: None)
    assert not again["ok"] and again["duplicate"]  # the same old bytes once more: still a failure
    [same] = fetch_all(archive, ["ogyei"], opener=opener([(hu(1), "Thu, 22 Oct 2026 00:00:00 GMT")]), sleep=lambda s: None)
    assert same["ok"] and same["duplicate"] and same["path"] == later["path"]  # known good bytes are harmless
    assert [e["path"] for e in _unique_files(archive, "ogyei")] == [good["path"], later["path"]]


def test_eudragmdp_search_runs_in_session_and_export_is_stored(tmp_path):
    u = urls()
    xls = b"\xd0\xcf\x11\xe0fake-xls LOC-100096104"
    seen = []

    def opener(req, timeout):
        seen.append((req.full_url, req.get_method(), req.get_header("Cookie")))
        if req.full_url == u["eudragmdp"] and req.get_method() == "GET":
            r = Resp(b"<form name='GMPNCSearchForm'>")
            r.headers["Set-Cookie"] = "JSESSIONID=abc; Path=/; HttpOnly"
            return r
        if req.get_method() == "POST":
            assert b"fromDate=2000-01-01" in req.data
            return Resp(b"<td class='d'>1 to 10 of 84</td>")
        return Resp(xls)

    [e] = fetch_all(Archive(tmp_path / "a"), ["eudragmdp"], opener=opener, sleep=lambda s: None)
    assert e["ok"] and e["path"].endswith(".xls.gz") and e["warnings"] == []
    assert seen[-1] == (u["eudragmdp"] + "?ctrl=searchGMPNCResultControlList&action=ExportList", "GET", "JSESSIONID=abc")


def test_marker_check_flags_wrong_file(tmp_path):
    u = urls()
    [ok] = fetch_all(Archive(tmp_path / "a"), ["erviss_ili"], sleep=lambda s: None,
                     opener=opener_for({u["erviss_ili"]: b"survtype,countryname,yearweek\n"}))
    assert ok["warnings"] == []
    [bad] = fetch_all(Archive(tmp_path / "b"), ["sari_region"], sleep=lambda s: None,
                      opener=opener_for({u["sari_region"]: b"<html>404</html>"}))
    assert bad["warnings"] == ["Kennung JAHR;KW fehlt"]


def test_scheduled_run_fetches_daily_sources_once_a_day(tmp_path, monkeypatch):
    from stockout_at import archive as arch
    u = urls()
    bodies = {url: OSError("nicht abgerufen") for url in u.values()}
    bodies[u["ansm"]] = b"\xd0\xcf\x11\xe0fake-xls"
    archive = Archive(tmp_path / "a")
    fetch_all(archive, ["ansm"], opener=opener_for(bodies), sleep=lambda s: None)
    monkeypatch.setattr(arch, "RETRY_DELAYS", ())
    names = [e["source"] for e in fetch_all(archive, opener=opener_for(bodies), sleep=lambda s: None)]
    assert "ansm" not in names and "basg" in names
    later = arch.utcnow() + timedelta(hours=21)
    monkeypatch.setattr(arch, "utcnow", lambda: later)
    names = [e["source"] for e in fetch_all(archive, opener=opener_for(bodies), sleep=lambda s: None)]
    assert "ansm" in names


def test_mirror_copies_verifies_and_reports_missing_drive(tmp_path):
    archive = Archive(tmp_path / "a")
    archive.store("basg", BASG, ext="xml", stamp="2026-10-17T02-00-08", meta={})
    target = tmp_path / "m"

    assert mirror(archive.root, target, mount=None) == {"ok": True, "copied": 1}
    assert verify(archive.root, target) == []
    assert (target / "manifest.jsonl").exists()
    assert mirror(archive.root, target, mount=None)["copied"] == 0

    log = archive.root / "protokoll" / "merkmale" / "2026" / "2026-10-17.csv.gz"  # replaced later that day, same size
    log.parent.mkdir(parents=True)
    log.write_bytes(b"morgens")
    assert mirror(archive.root, target, mount=None)["copied"] == 1
    log.write_bytes(b"abends!")
    os.utime(log, (time.time() + 5, time.time() + 5))
    assert mirror(archive.root, target, mount=None)["copied"] == 1
    assert (target / log.relative_to(archive.root)).read_bytes() == b"abends!"

    result = mirror(archive.root, target, mount=tmp_path / "not-mounted")
    assert not result["ok"]
    state = json.loads((archive.root / "mirror_state.json").read_text())
    assert "nicht eingehängt" in state["last_error"]


def test_missing_basg_days_and_status(tmp_path):
    entries = [
        {"source": "basg", "origin": "live", "ok": True, "produced_on": f"2026-10-{d}T02:00:08"} for d in (15, 17)
    ]
    now = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)  # 12:00 in Vienna
    first, gaps = missing_basg_days(entries, now)
    assert str(first) == "2026-10-15" and [str(d) for d in gaps] == ["2026-10-16"]

    archive = Archive(tmp_path / "a")
    report = collect(archive, None, now)
    assert any("noch kein erfolgreicher Abruf" in w for w in report["warnings"])


def _fetch_args(archive, source=None, nachholen=False, eko=False):
    import argparse
    return argparse.Namespace(archive=str(archive.root), no_mirror=True, mirror_dir="unused", mirror_mount=None,
                              source=source, nachholen=nachholen, eko=eko)


def test_eko_night_run_fetches_only_eko(tmp_path, monkeypatch):
    from stockout_at import cli
    archive = Archive(tmp_path / "a")
    calls = []
    monkeypatch.setattr(cli, "_eko", lambda a: calls.append("eko") or True)
    monkeypatch.setattr(cli, "fetch_all", lambda a, names: calls.append("quellen") or [])
    assert cli.cmd_fetch(_fetch_args(archive, eko=True)) == 0 and calls == ["eko"]


def test_catch_up_retries_only_failed_every_run_sources(tmp_path, monkeypatch, capsys):
    from stockout_at import cli
    from stockout_at.archive import iso, retry_due, utcnow
    archive = Archive(tmp_path / "a")
    t = iso(utcnow() - timedelta(hours=2))
    for e in ({"source": "bfarm", "ok": True}, {"source": "bfarm", "ok": False, "error": "weg"},
              {"source": "ema", "ok": False, "error": "weg"}, {"source": "ema", "ok": True},
              {"source": "eudragmdp", "ok": False, "error": "weg"},  # once a day: next scheduled run retries it
              {"source": "ansm", "ok": False, "error": "Formatprüfung"}, {"source": "basg", "ok": True}):
        archive.append({"origin": "live", "fetched_at": t, "warnings": [], **e})
    assert retry_due(archive) == ["bfarm"]

    asked = []
    monkeypatch.setattr(cli, "fetch_all", lambda a, names: asked.append(names) or [])
    assert cli.cmd_fetch(_fetch_args(archive, nachholen=True)) == 0
    assert asked == [["bfarm"]] and "Nachholen: bfarm" in capsys.readouterr().out
    archive.append({"source": "bfarm", "origin": "live", "ok": True, "fetched_at": t, "warnings": []})
    assert cli.cmd_fetch(_fetch_args(archive, nachholen=True)) == 0 and asked == [["bfarm"]]


def test_failed_source_is_an_error_only_for_basg_or_after_36_hours(tmp_path, monkeypatch, capsys):
    from stockout_at import cli
    from stockout_at.archive import iso, utcnow
    archive = Archive(tmp_path / "a")
    for name, hours in (("bfarm", 10), ("ema", 40), ("basg", 1)):
        archive.append({"source": name, "origin": "live", "ok": True, "warnings": [],
                        "fetched_at": iso(utcnow() - timedelta(hours=hours))})

    def run(name):
        monkeypatch.setattr(cli, "fetch_all", lambda a, names: [{"source": name, "ok": False, "error": "weg"}])
        return cli.cmd_fetch(_fetch_args(archive, source=[name]))

    assert run("bfarm") == 0 and "WARNUNG bfarm: weg (letzter Erfolg vor 10 h" in capsys.readouterr().out
    assert run("ema") == 1 and "FEHLER ema: weg" in capsys.readouterr().out
    assert run("basg") == 1  # the core source always alarms
    assert run("aifa") == 1  # never fetched successfully


def test_public_code_fetches_none_of_the_withheld_sources():
    from stockout_at import archive as arch
    withheld = {"edqm", "fimea", "fimea_reg", "mia_asp", "mia_abst", "mia_verl", "mia_ve"}
    assert not withheld & set(arch.SOURCES)


def test_user_agent_names_a_contact_only_when_set(tmp_path, monkeypatch):
    seen = []

    def opener(req, timeout):
        seen.append(req.get_header("User-agent"))
        return Resp(BASG)

    monkeypatch.delenv("STOCKOUT_CONTACT", raising=False)
    fetch_all(Archive(tmp_path / "a"), ["basg"], opener=opener, sleep=lambda s: None)
    monkeypatch.setenv("STOCKOUT_CONTACT", "  radar@example.org\n")
    fetch_all(Archive(tmp_path / "b"), ["basg"], opener=opener, sleep=lambda s: None)
    monkeypatch.setenv("STOCKOUT_CONTACT", "")
    fetch_all(Archive(tmp_path / "c"), ["basg"], opener=opener, sleep=lambda s: None)
    base = "LieferengpassRadar/0.1 (+https://github.com/benediktneumayer2-tech/lieferengpass-radar"
    assert seen == [base + ")", base + "; Kontakt: radar@example.org)", base + ")"]


def test_empty_mirror_setting_means_no_copy(tmp_path, monkeypatch, capsys):
    import argparse

    from stockout_at import cli
    from stockout_at.status import MIRROR_OFF
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STOCKOUT_MIRROR", raising=False)
    monkeypatch.delenv("STOCKOUT_MIRROR_MOUNT", raising=False)
    monkeypatch.setattr(cli, "mirror", lambda *a: pytest.fail("keine Kopie erwartet"))
    monkeypatch.setattr(cli, "fetch_all", lambda a, names: [])
    for empty in ("", "  "):  # an empty value never means the working directory
        archive, mirror_root, mount = cli._paths(argparse.Namespace(
            archive="a", no_mirror=False, mirror_dir=empty, mirror_mount="/nicht/da"))
        assert mirror_root is None and mount is None

    assert cli.main(["--archive", "a", "fetch", "--source", "basg"]) == 0
    assert cli.main(["--archive", "a", "--mirror-dir", "", "mirror"]) == 0
    assert cli.main(["--archive", "a", "status"]) == 2  # warnings: nothing fetched yet, none about the copy
    out = capsys.readouterr().out
    assert out.count(MIRROR_OFF) == 2 and "FEHLER" not in out
    assert not any("Kopie" in w for w in cli.collect(Archive(tmp_path / "a"), None, cli.utcnow())["warnings"])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a"] and not list((tmp_path / "a").iterdir())


def test_import_legacy_without_package_fails_with_clear_message(tmp_path, monkeypatch, capsys):
    from stockout_at import cli, legacy
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(legacy, "DEFAULT_PACKAGE", None)
    assert cli.main(["--archive", "a", "--no-mirror", "import-legacy", "--no-wayback"]) == 2
    err = capsys.readouterr().err
    assert "Kein Datenpaket für die Vorgeschichte angegeben" in err and "STOCKOUT_LEGACY_PACKAGE" in err
    assert not (tmp_path / "a" / "manifest.jsonl").exists()
