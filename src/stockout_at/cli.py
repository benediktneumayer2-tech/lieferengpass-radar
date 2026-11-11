"""Command line: stockout fetch | mirror | status | import-legacy | build | site | daily | vorlauf | rueckblick | schaerfe | modell | bewertung | protokoll | preview."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from . import legacy, metrics
from .build import build
from .archive import SOURCES, Archive, fetch_all, last_success, retry_due, utcnow
from .mirror import mirror, verify
from .status import MIRROR_OFF, STALE_HOURS, collect, render


def _paths(args) -> tuple[Archive, Path | None, Path | None]:
    """Archive, mirror target and mount to check; an empty value means none (never the working directory)."""
    archive = Archive(Path(args.archive))
    mirror_dir = (args.mirror_dir or "").strip()
    mirror_mount = (args.mirror_mount or "").strip()
    mirror_root = None if args.no_mirror or not mirror_dir else Path(mirror_dir)
    mount = Path(mirror_mount) if mirror_mount and mirror_root is not None else None
    return archive, mirror_root, mount


def _eko(archive: Archive, **kwargs) -> bool:
    """EKO changes from the RIS, only in the hours RIS allows (20-5 h or weekend); False on a failed document."""
    from . import eko

    if not eko.allowed(utcnow()):
        print("eko: außerhalb der RIS-Abfragezeiten (20–5 Uhr, Wochenende), übersprungen")
        return True
    results = eko.sync(archive, **kwargs)
    for e in results:
        print(f"OK eko: {e['doc']} {e['path']}" if e["ok"] else f"FEHLER eko: {e.get('doc') or e['url']}: {e['error']}")
    print(f"eko: {sum(e['ok'] for e in results)} neue EKO-Änderungen")
    return all(e["ok"] for e in results)


def _hours_since_success(archive: Archive, name: str) -> float | None:
    last = last_success(archive, name)
    return None if last is None else (utcnow() - last).total_seconds() / 3600


def cmd_fetch(args) -> int:
    """Fetch and archive; a failed source is an error only for BASG or after STALE_HOURS without success."""
    archive, mirror_root, mount = _paths(args)
    failed = False
    names = args.source
    eko_only = getattr(args, "eko", False)
    if getattr(args, "nachholen", False):
        names = retry_due(archive)
        print("Nachholen: " + (", ".join(names) if names else "nichts offen"))
        if not names:
            return 0
    scheduled = not names
    if scheduled:
        try:
            failed |= not _eko(archive)
        except Exception as exc:  # noqa: BLE001 - RIS must not block the other sources
            print(f"FEHLER eko: {type(exc).__name__}: {exc}")
            failed = True
    for e in ([] if eko_only else fetch_all(archive, names)):
        if not e["ok"]:
            kept = f" (Antwort aufbewahrt: {e['path']})" if e.get("path") else ""
            hours = _hours_since_success(archive, e["source"])
            if e["source"] == "basg" or hours is None or hours > STALE_HOURS:
                failed = True
                print(f"FEHLER {e['source']}: {e['error']}{kept}")
            else:
                print(f"WARNUNG {e['source']}: {e['error']}{kept} "
                      f"(letzter Erfolg vor {hours:.0f} h, FEHLER erst nach {STALE_HOURS} h)")
        else:
            what = "unverändert" if e["duplicate"] else "neu"
            warn = f" WARNUNG: {'; '.join(e['warnings'])}" if e.get("warnings") else ""
            print(f"OK {e['source']}: {what}, {e['bytes']} Bytes, {e['path']}{warn}")
    if not eko_only and (scheduled or "cima" in names):
        from . import registers
        from .build import _unique_files
        try:
            e = registers.sync_cima(archive, _unique_files)
            print(f"OK cima_reg: {e['codes']} Codes nachgeschlagen, {e['path']}" if e else "OK cima_reg: nichts Neues")
        except Exception as exc:  # noqa: BLE001 - the register must not block the other sources
            print(f"FEHLER cima_reg: {type(exc).__name__}: {exc}")
            failed = True
    if mirror_root is not None:
        failed |= not _mirror(archive, mirror_root, mount)
    return 1 if failed else 0


def _mirror(archive: Archive, mirror_root: Path, mount: Path | None) -> bool:
    result = mirror(archive.root, mirror_root, mount)
    if result["ok"]:
        print(f"Kopie: {result['copied']} Dateien nach {mirror_root}")
    else:
        print(f"FEHLER Kopie: {result['error']}")
    return result["ok"]


def cmd_mirror(args) -> int:
    archive, mirror_root, mount = _paths(args)
    if mirror_root is None:
        print(MIRROR_OFF)
        return 0
    return 0 if _mirror(archive, mirror_root, mount) else 1


def cmd_status(args) -> int:
    archive, mirror_root, _ = _paths(args)
    report = collect(archive, mirror_root, utcnow())
    if args.verify and mirror_root is not None:
        bad = verify(archive.root, mirror_root)
        report["mirror"]["verify_mismatches"] = bad
        if bad:
            report["warnings"].append(f"Kopie: {len(bad)} Dateien weichen ab")
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else render(report))
    if args.verify and mirror_root is not None and not args.json:
        print(f"Prüfsummen der Kopie: {'alle gleich' if not report['mirror']['verify_mismatches'] else 'ABWEICHUNGEN'}")
    return 2 if report["warnings"] else 0


def cmd_import_legacy(args) -> int:
    archive, mirror_root, mount = _paths(args)
    package = Path(args.package) if (args.package or "").strip() else legacy.DEFAULT_PACKAGE
    if package is None and not (args.backfill or args.wayback_only):
        print(f"FEHLER: Kein Datenpaket für die Vorgeschichte angegeben. --package <Ordner> angeben "
              f"oder {legacy.PACKAGE_ENV} setzen.", file=sys.stderr)
        return 2
    if args.backfill:
        results = []
        for source in args.backfill:
            if source == "eko":
                from . import eko
                _eko(archive, pages=None, origin="backfill", until=eko.night_end(utcnow()))
            else:
                results += legacy.import_pl_mz(archive)
    elif args.wayback_only:
        results = []
        for source in args.wayback_only:
            results += legacy.import_wayback(archive, source)
    else:
        results = legacy.import_basg_package(archive, package) + legacy.import_asp_package(archive, package)
        if not args.no_wayback:
            results += legacy.import_wayback(archive)
    counts = Counter(
        (e["source"], e.get("origin"), "fehler" if not e["ok"] else ("dublette" if e["duplicate"] else "neu"))
        for e in results
    )
    for (source, origin, kind), n in sorted(counts.items()):
        print(f"{source:<5} {origin:<16} {kind:<8} {n}")
    if mirror_root is not None:
        _mirror(archive, mirror_root, mount)
    return 0


def cmd_build(args) -> int:
    archive = Archive(Path(args.archive))
    started = time.monotonic()
    counts = build(archive, Path(args.db))
    print(f"Datenbank neu gebaut: {args.db} ({time.monotonic() - started:.1f} s)")
    for table, n in counts.items():
        print(f"  {table:<18} {n}")
    if args.export_json:
        ref = date.fromisoformat(args.ref_date) if args.ref_date else None
        conn = metrics.connect(Path(args.db))
        try:
            paths = metrics.export_json(conn, Path(args.export_json), ref)
        finally:
            conn.close()
        print(f"Kennzahlen exportiert: {', '.join(p.name for p in paths)} nach {args.export_json}")
    return 0


def cmd_site(args) -> int:
    from .site import generate

    started = time.monotonic()
    ref = date.fromisoformat(args.ref_date) if args.ref_date else None
    counts = generate(Path(args.db), Path(args.out), ref, Archive(Path(args.archive)))
    pages = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"Website erzeugt: {args.out} ({sum(counts.values())} Seiten: {pages}; {time.monotonic() - started:.1f} s)")
    return 0


def _rueckblick_json(args) -> int:
    """Hit rates of the register hints for the site (data/derived/json/rueckblick.json)."""
    from . import rueckblick

    rueckblick.run(Path(args.db), Path(args.archive), json_path=Path(args.export_json) / "rueckblick.json")
    print(f"Rückblick: {Path(args.export_json) / 'rueckblick.json'}")
    return 0


def cmd_daily(args) -> int:
    """fetch (+Kopie) -> build (+JSON) -> Rückblick -> site -> Merkmalsprotokoll (+Kopie); every step is attempted while BASG data exist."""
    archive = Archive(Path(args.archive))
    failed = []

    def step(name: str, fn) -> None:
        try:
            code = fn()
        except Exception as exc:  # noqa: BLE001 - a failing step must not stop the next one
            print(f"FEHLER {name}: {type(exc).__name__}: {exc}")
            code = 1
        if code:
            failed.append(name)
        print(f"Schritt {name}: {'FEHLER' if code else 'OK'}")

    step("Abruf", lambda: cmd_fetch(args))
    if not any(e.get("source") == "basg" and e.get("ok") and e.get("path") for e in archive.entries()):
        print("FEHLER: keine BASG-Daten im Archiv, Datenbank und Website nicht erzeugt")
        return 1
    args.export_json = args.export_json or str(Path(args.db).parent / "json")
    step("Datenbank", lambda: cmd_build(args))
    step("Rückblick", lambda: _rueckblick_json(args))
    step("Website", lambda: cmd_site(args))
    step("Protokoll", lambda: cmd_protokoll(args))
    print("Tageslauf: " + (f"FEHLER in {', '.join(failed)}" if failed else "alles OK"))
    return 1 if failed else 0


def cmd_vorlauf(args) -> int:
    from . import vorlauf

    start = date.fromisoformat(args.von) if args.von else None
    end = date.fromisoformat(args.bis) if args.bis else None
    result = vorlauf.run(Path(args.db), start, end, Path(args.json) if args.json else None)
    print(vorlauf.render(result))
    return 0


def cmd_rueckblick(args) -> int:
    from . import rueckblick

    start = date.fromisoformat(args.von) if args.von else rueckblick.START
    end = date.fromisoformat(args.bis) if args.bis else None
    result = rueckblick.run(Path(args.db), Path(args.archive), start, end, Path(args.json) if args.json else None)
    print(rueckblick.render(result))
    return 0


def cmd_schaerfe(args) -> int:
    from . import schaerfe

    print(schaerfe.render(schaerfe.run(Path(args.db), Path(args.json) if args.json else None)))
    return 0


def cmd_modell(args) -> int:
    from . import modell

    result = modell.run(Path(args.db), Archive(Path(args.archive)), Path(args.json) if args.json else None,
                        modell.MODELS if args.einfrieren else None)
    print(modell.render(result))
    if args.einfrieren:
        print(f"Eingefroren: {', '.join(result['verfahren'])} und Prüfplan {modell.PLAN} (sha256 {result['pruefplan'][:12]})")
    return 0


def cmd_bewertung(args) -> int:
    """Score the daily prediction log (from the plan's start), or with --rueckblick a simulated log of 2026."""
    import sqlite3

    from . import modell

    archive = Archive(Path(args.archive))
    loaded = modell.load_plan()
    if not loaded:
        print("Kein Prüfplan eingefroren (stockout modell --einfrieren).")
        return 1
    plan, methods = loaded
    conn = sqlite3.connect(args.db)
    try:
        if args.rueckblick:
            root = Path(args.db).parent / "vorhersagen_rueckblick"
            k = modell.Knowledge(conn, archive)
            n = modell.simulate(k, methods, modell.TEST_START, k.latest, root)
            print(f"Rückblick: {n} Tagesprotokolle 2026 mit den geprüften Parametern nach {root}")
            result = modell.bewerten(conn, root, modell.TEST_START)
        else:
            start = date.fromisoformat(args.von) if args.von else date.fromisoformat(plan["beginn"])
            result = modell.bewerten(conn, archive.root, start, plan_sha=None if args.von else plan["sha256"])
    finally:
        conn.close()
    print(modell.render_bewertung(result))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


def cmd_protokoll(args) -> int:
    """Feature log of the day (Z3, § 21 shadow feature) into the archive, then copy it to the mirror."""
    from datetime import datetime

    from . import merkmale
    from .site import HIDDEN_SOURCES
    from .status import VIENNA

    archive, mirror_root, mount = _paths(args)
    day = datetime.now(VIENNA).date().isoformat()
    path, rows, log = merkmale.run(Path(args.db), archive, day, HIDDEN_SOURCES)
    hints = Counter(h for r in rows for h in r["hinweis"].split("+") if h)
    stopped = sum(1 for r in rows if r["vertrieb_eingestellt_gemeldet"] == 1)
    print(f"Merkmalsprotokoll: {path} ({len(rows)} Produkte; Hinweise {dict(sorted(hints.items()))}; § 21 gemeldet {stopped})")
    print(f"Vorhersageprotokoll: {log}" if log else "Vorhersageprotokoll: kein Prüfplan eingefroren")
    if mirror_root is not None:
        return 0 if _mirror(archive, mirror_root, mount) else 1
    return 0


def cmd_preview(args) -> int:
    """Serve the generated site on 127.0.0.1 only (local preview, never on other interfaces)."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    directory = Path(args.dir).resolve()
    if not (directory / "index.html").exists():
        print(f"FEHLER: keine Website in {directory}; zuerst 'stockout site' ausführen")
        return 1
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"Vorschau: http://127.0.0.1:{args.port}/ (Strg+C beendet)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stockout", description="Archiv der Arzneimittel-Engpassmeldungen")
    p.add_argument("--archive", default=os.environ.get("STOCKOUT_ARCHIVE", "data/archive"))
    p.add_argument("--mirror-dir", default=os.environ.get("STOCKOUT_MIRROR", ""),
                   help="Ordner der zweiten Kopie des Archivs (Standard: STOCKOUT_MIRROR; leer = keine Kopie)")
    p.add_argument("--mirror-mount", default=os.environ.get("STOCKOUT_MIRROR_MOUNT", ""),
                   help="Laufwerk, das für die Kopie eingehängt sein muss (Standard: STOCKOUT_MIRROR_MOUNT; leer = keine Prüfung)")
    p.add_argument("--no-mirror", action="store_true", help="keine zweite Kopie, auch wenn STOCKOUT_MIRROR gesetzt ist")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Quellen abrufen und archivieren, danach Kopie")
    f.add_argument("--source", action="append", choices=sorted(SOURCES))
    f.add_argument("--nachholen", action="store_true",
                   help="nur Quellen erneut abrufen, deren letzter Abruf scheiterte (Nachholabruf am Mittag)")
    f.add_argument("--eko", action="store_true",
                   help="nur EKO-Änderungen aus dem RIS (Nachtlauf werktags; nur 20–5 Uhr oder am Wochenende)")
    f.set_defaults(func=cmd_fetch)

    sub.add_parser("mirror", help="fehlende Dateien auf das zweite Laufwerk kopieren").set_defaults(func=cmd_mirror)

    s = sub.add_parser("status", help="Zustand des Archivs")
    s.add_argument("--json", action="store_true")
    s.add_argument("--verify", action="store_true", help="Prüfsummen der Kopie vergleichen")
    s.set_defaults(func=cmd_status)

    i = sub.add_parser("import-legacy", help="Vorgeschichte importieren (einmalig)")
    i.add_argument("--package", metavar="ORDNER",
                   help=f"lokales Datenpaket mit BASG-Altdateien und ASP-Fassungen (Standard: {legacy.PACKAGE_ENV}; ohne Standardwert)")
    i.add_argument("--no-wayback", action="store_true")
    i.add_argument("--wayback-only", action="append", choices=sorted(SOURCES), metavar="QUELLE",
                   help="nur Internet-Archive-Schnappschüsse dieser Quelle importieren (wiederholbar)")
    i.add_argument("--backfill", action="append", choices=["pl_mz", "eko"], metavar="QUELLE",
                   help="frühere Ausgaben nachladen: pl_mz (polnische Liste seit 2015), eko (EKO-Änderungen seit 2004 "
                        "aus dem RIS; nur 20–5 Uhr oder am Wochenende, Abrufe zufällig verteilt bis 4:30 Uhr)")
    i.set_defaults(func=cmd_import_legacy)

    b = sub.add_parser("build", help="abgeleitete Datenbank vollständig neu aus dem Archiv bauen")
    b.add_argument("--db", default=os.environ.get("STOCKOUT_DB", "data/derived/stockout.sqlite"))
    b.add_argument("--export-json", metavar="DIR", help="Kennzahlen für die Website als JSON schreiben")
    b.add_argument("--ref-date", metavar="JJJJ-MM-TT", help="Stichtag (Standard: letzter Schnappschuss)")
    b.set_defaults(func=cmd_build)

    db_default = os.environ.get("STOCKOUT_DB", "data/derived/stockout.sqlite")
    site_default = os.environ.get("STOCKOUT_SITE", "site")
    w = sub.add_parser("site", help="statische Website aus der Datenbank erzeugen")
    w.add_argument("--db", default=db_default)
    w.add_argument("--out", default=site_default)
    w.add_argument("--ref-date", metavar="JJJJ-MM-TT", help="Stichtag (Standard: letzter Schnappschuss)")
    w.set_defaults(func=cmd_site)

    t = sub.add_parser("daily", help="Tageslauf: Abruf (+Kopie), Datenbank (+JSON), Rückblick, Website, Merkmalsprotokoll")
    t.add_argument("--source", action="append", choices=sorted(SOURCES))
    t.add_argument("--db", default=db_default)
    t.add_argument("--out", default=site_default)
    t.add_argument("--export-json", metavar="DIR", help="Standard: <db-Ordner>/json")
    t.add_argument("--ref-date", default=None, help=argparse.SUPPRESS)
    t.set_defaults(func=cmd_daily)

    lv = sub.add_parser("vorlauf", help="Messung: gehen Auslandsmeldungen BASG-Meldungen voraus?")
    lv.add_argument("--db", default=db_default)
    lv.add_argument("--von", metavar="JJJJ-MM-TT", help="Beginn des Zeitraums (Standard 2024-01-01)")
    lv.add_argument("--bis", metavar="JJJJ-MM-TT", help="Ende des Zeitraums (Standard: letzter Schnappschuss)")
    lv.add_argument("--json", metavar="DATEI", help="Ergebnis zusätzlich als JSON schreiben")
    lv.set_defaults(func=cmd_vorlauf)

    rb = sub.add_parser("rueckblick", help="Rückblicktests: Ausstiege, Preisband, Infektionswellen, Nachbarn")
    rb.add_argument("--db", default=db_default)
    rb.add_argument("--von", metavar="JJJJ-MM-TT", help="Beginn des Zeitraums (Standard 2022-01-01)")
    rb.add_argument("--bis", metavar="JJJJ-MM-TT", help="Ende des Zeitraums (Standard: letzter Schnappschuss)")
    rb.add_argument("--json", metavar="DATEI", help="Ergebnis zusätzlich als JSON schreiben")
    rb.set_defaults(func=cmd_rueckblick)

    sc = sub.add_parser("schaerfe", help="Messung: Ländergewichte, Grund, Stärke und Form gegen die Stufen (lernen 2024–25, prüfen 2026)")
    sc.add_argument("--db", default=db_default)
    sc.add_argument("--json", metavar="DATEI", help="Ergebnis zusätzlich als JSON schreiben")
    sc.set_defaults(func=cmd_schaerfe)

    mo = sub.add_parser("modell", help="Z3-Verfahren: lernen 2024–25, prüfen 2026 auf denselben Fällen; --einfrieren schreibt models/ und den Prüfplan")
    mo.add_argument("--db", default=db_default)
    mo.add_argument("--json", metavar="DATEI", help="Ergebnis zusätzlich als JSON schreiben")
    mo.add_argument("--einfrieren", action="store_true", help="eingefrorene Fassung schreiben (nur vor der prospektiven Prüfung)")
    mo.set_defaults(func=cmd_modell)

    bw = sub.add_parser("bewertung", help="Vorhersageprotokoll bewerten (ab Beginn des Prüfplans); --rueckblick: simuliertes Protokoll 2026")
    bw.add_argument("--db", default=db_default)
    bw.add_argument("--von", metavar="JJJJ-MM-TT", help="Beginn (Standard: Beginn des Prüfplans, nur Zeilen dieses Plans)")
    bw.add_argument("--rueckblick", action="store_true", help="2026 mit den geprüften Parametern simulieren und bewerten")
    bw.add_argument("--json", metavar="DATEI", help="Ergebnis zusätzlich als JSON schreiben")
    bw.set_defaults(func=cmd_bewertung)

    pr = sub.add_parser("protokoll", help="Merkmalsprotokoll des Tages (Z3, § 21 als Schattenmerkmal) ins Archiv")
    pr.add_argument("--db", default=db_default)
    pr.set_defaults(func=cmd_protokoll)

    v = sub.add_parser("preview", help="lokale Vorschau der Website, nur auf 127.0.0.1")
    v.add_argument("--port", type=int, required=True, help="freier lokaler Port, z. B. 8000")
    v.add_argument("--dir", default=site_default)
    v.set_defaults(func=cmd_preview)

    args = p.parse_args(argv)
    return args.func(args)
