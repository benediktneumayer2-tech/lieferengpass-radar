"""Contexts for the showcase parts of the site. Imported only inside `site.generate()`, so an error here can
stop the website step but never the import that the daily prediction log needs (`cli.py` -> `site.HIDDEN_SOURCES`)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from markupsafe import Markup

from .charts import NARROW, WIDE, modell, num, pct
from .charts import live as live_chart
from .timeline import de

ERGEBNISSE = Path(__file__).parent / "web" / "data" / "ergebnisse.json"


def load_results() -> dict:
    return json.loads(ERGEBNISSE.read_text(encoding="utf-8"))


def _day(value: str) -> str:
    return de(date.fromisoformat(value))


def f08_figure(results: dict) -> dict:
    """Arguments of the `figure` macro for F08."""
    z3 = results["z3_rueckblick"]
    c = z3["bedingungen"]
    table = {
        "caption": "Top-50-Trefferquote und AUC je Verfahren",
        "head": ["Verfahren", "Top 50", "Top 25", "AUC", "Brier-Score"],
        "rows": [[m["name"], pct(m["top50"]), pct(m["top25"]), num(m["auc"], 3), num(m["brier"], 5)] for m in z3["verfahren"]],
    }
    caption = (f'Anteil der 50 am höchsten gereihten Wirkstoffe je Stichtag, für die binnen {c["horizont_wochen"]} Wochen '
               f'eine neue BASG-Meldung folgte. Gelernt {c["lernen"][0][:4]}–{c["lernen"][1][:4]}, geprüft {c["pruefen"][0][:4]}, '
               f'{num(c["faelle"])} Fälle, {num(c["meldungen"])} Meldungen. Rückblick, keine prospektive Prüfung. {z3["intervall_hinweis"]}')
    return {
        "id": "f08",
        "kind": "rueckblick",
        "legend": "Reiht das Modell besser als die einfache Regel?",
        "svg_wide": modell.f08(z3, width=WIDE, uid="f08w"),
        "svg_narrow": modell.f08(z3, width=NARROW, uid="f08n"),
        "caption": caption,
        "table": table,
        "source": z3["quelle"],
    }


def pruefstand(results: dict, today: date) -> dict:
    """Test-bench panel: the phase is chosen from the date alone; the generator never states a result here."""
    plan = results["vorab_registrierung"]
    phase = next(p for p in plan["phasen"] if p["bis"] is None or today <= date.fromisoformat(p["bis"]))
    dates = {e["text"]: e["am"] for e in plan["zeitleiste"] if "am" in e}
    def when(prefix: str) -> str:
        return _day(next(v for k, v in dates.items() if k.startswith(prefix)))
    return {
        "led": "working" if phase["led"] == "arbeitet" else "off",
        "text": phase["text"],
        "hash": plan["pruefplan_kurz"],
        "frozen": when("Verfahren und Prüfplan eingefroren"),
        "start": when("Beginn der prospektiven Prüfung"),
        "go": when("Go/No-Go"),
        "doi": plan["doi_alle_versionen"],
        "repository": plan["repository"],
    }


def _f22_cell(point: dict | None) -> str:
    """Predicted → observed (95 % range) of one class and phase, for the table."""
    if point is None:
        return "–"
    lo, hi = point["ki95"] or (point["beobachtet"], point["beobachtet"])
    mark = " (zusammengelegt)" if len(point["klassen"]) > 1 else ""
    return (f'{num(point["vorhergesagt"] * 100, 2)} → {num(point["beobachtet"] * 100, 2)} % '
            f'({num(lo * 100, 2)}–{num(hi * 100, 2)}){mark}')


def _f22_table(data: dict) -> dict:
    einlauf, pruefung, band = data["einlauf"], data["pruefung"], data["rueckblick"]
    def at(points: list[dict], i: int) -> dict | None:
        return next((p for p in points if i in p["klassen"]), None)
    rows = [[k["name"], num(data["heute"]["je_klasse"][i]), num(einlauf["meldungen"]["je_klasse"][i]),
             num(pruefung["meldungen"]["je_klasse"][i]), _f22_cell(at(band["punkte"] if band else [], i)),
             _f22_cell(at(einlauf["punkte"], i)), _f22_cell(at(pruefung["punkte"], i))]
            for i, k in enumerate(data["klassen"])]
    rows.append(["Summe", num(data["heute"]["wirkstoffe"]), num(einlauf["meldungen"]["anzahl"]), num(pruefung["meldungen"]["anzahl"]),
                 f'{num(band["faelle"])} Fälle, {num(band["treffer"])} Treffer' if band else "–",
                 f'{num(einlauf["faelle"])} Fälle, {num(einlauf["treffer"])} Treffer',
                 f'{num(pruefung["faelle"])} Fälle, {num(pruefung["treffer"])} Treffer'])
    return {"caption": f'Je Klasse: Wirkstoffe, neue Meldungen und Anteil mit neuer Meldung binnen {data["horizont_tage"] // 7} Wochen '
                       "(vorhergesagt → eingetroffen, in Klammern der 95-%-Bereich). Die Phasen sind getrennt gerechnet.",
            "head": ["Klasse", "Alle Wirkstoffe", "Neu: Einlaufphase", "Neu: ab Prüfungsbeginn", "Rückblick 2026 (simuliert)", "Einlaufphase", "Prüfung"],
            "rows": rows}


def _f22_phases(data: dict, results: dict) -> list[dict]:
    """The three phases for the side panel: LED and word follow the data's date; no result is ever judged here."""
    stand, beginn = date.fromisoformat(data["stand"]), date.fromisoformat(data["beginn"])
    go = date.fromisoformat(next(e["am"] for e in results["vorab_registrierung"]["zeitleiste"] if e["text"].startswith("Go/No-Go")))
    weeks = data["horizont_tage"] // 7

    def facts(p: dict) -> list[tuple[str, str]]:
        m = p["meldungen"]
        out = [("Neu gemeldet", num(m["anzahl"])), ("Davon Top 50", f'{num(m["top50"])} von {num(m["anzahl"])}')]
        if m["top50_ki95"]:
            lo, hi = m["top50_ki95"]
            out.append(("Anteil, 95-%-Bereich", f'{num(m["top50"] / m["anzahl"] * 100)} % ({num(lo * 100)}–{num(hi * 100)})'))
        out.append((f"Reife {weeks}-Wochen-Fälle", num(p["faelle"])))
        if p["naechster_termin"]:
            out.append(("Nächster Termin", _day(p["naechster_termin"])))
        return out

    band = data["rueckblick"]
    retro = [("Stichtage", num(band["stichtage"])), ("Fälle", num(band["faelle"])), ("Treffer", num(band["treffer"]))] if band else []
    if stand < beginn:
        test = {"led": "off", "word": f'Beginnt am {de(beginn)}', "facts": []}
    elif stand <= go:
        test = {"led": "working", "word": "Prüfung läuft", "facts": facts(data["pruefung"])}
    else:
        test = {"led": "off", "word": "Bericht zum Go/No-Go: siehe Repository", "facts": facts(data["pruefung"])}
    running = stand < beginn
    return [
        {"mark": "band", "name": "Rückblick", "label": "simuliert · nicht validiert", "led": "off", "word": "Abgeschlossen", "facts": retro},
        {"mark": "circle", "name": "Einlaufphase", "label": "zählt nicht für die Prüfung", "led": "working" if running else "off",
         "word": "Läuft" if running else "Abgeschlossen", "facts": facts(data["einlauf"])},
        {"mark": "diamond", "name": "Prüfung", "label": "vorab festgelegt · Zwischenstand, kein Urteil", **test},
    ]


def f22_context(data: dict, results: dict) -> dict:
    """F22 for the start page: arguments of the `figure` macro and the side panel with readouts and phases."""
    weeks = data["horizont_tage"] // 7
    go = next(e["am"] for e in results["vorab_registrierung"]["zeitleiste"] if e["text"].startswith("Go/No-Go"))
    caption = ("Oben: Jeder Punkt ist ein Wirkstoff, für den erstmals eine BASG-Meldung erschien, eingeordnet nach der "
               "Wahrscheinlichkeit, die das Modell am Tag davor nannte. Die Balken zeigen, wie sich alle Wirkstoffe verteilen. "
               f"Unten: Anteil der Wirkstoffe je Klasse, für die binnen {weeks} Wochen tatsächlich eine neue Meldung kam. "
               "Auf der Diagonale kommen Meldungen genau so oft wie vorhergesagt; darüber häufiger, darunter seltener. "
               "Die orange Linie ist der Rückblick auf 2026: dieselbe Rechnung auf einem nachträglich simulierten "
               "Vorhersageprotokoll mit Stichtagen alle 14 Tage, das Band um sie ist ihr 95-%-Bereich. "
               "Bei den Punkten der Einlaufphase und der Prüfung zeigen senkrechte Striche den 95-%-Bereich. "
               "Die Einlaufphase zählt nicht für die Prüfung. "
               f'Die Prüfung beginnt am {_day(data["beginn"])}, entschieden wird am {_day(go)} nach der vorab festgelegten Regel. '
               "Die Punkte oben zählen jede neue Meldung, die Prüfung selbst wertet nur ihre Stichtage alle 14 Tage. "
               f'Eine neue Meldung heißt nicht, dass ein Arzneimittel fehlt. {results["referenzinstanz_satz"]}')
    source = (f'BASG-Meldungen bis {_day(data["stand"])}, tägliches Vorhersageprotokoll. Bereits reife Anteile können sich noch '
              "ändern, weil manche Meldungen rückdatiert erscheinen. Das Archiv vor dem 17.10.2026 ist lückenhaft.")
    figure = {
        "id": "f22",
        "kind": "live",
        "legend": Markup('Vorhersage gegen Meldung <span class="tag tone-warn">nicht validiert</span>'),
        "svg_wide": live_chart.f22(data, width=WIDE, uid="f22w"),
        "svg_narrow": live_chart.f22(data, width=NARROW, uid="f22n"),
        "caption": caption,
        "table": _f22_table(data),
        "source": source,
    }
    return {"figure": figure, "stand": _day(data["stand"]), "im_protokoll": num(data["heute"]["wirkstoffe"]),
            "phases": _f22_phases(data, results)}


def start_context(results: dict, today: date) -> dict:
    bench = pruefstand(results, today)
    # Model numbers stay inside the figure, where the macro prints the tag and the reference-instance sentence.
    story = ('Im Rückblick auf 2026 reiht das Modell Wirkstoffe besser als die einfache Stufenregel. '
             f'Validiert ist das nicht: Die prospektive Prüfung beginnt am {bench["start"]}, '
             f'der erste Bericht am {bench["go"]} wird in jedem Fall veröffentlicht.')
    return {"f08": f08_figure(results), "bench": bench, "story": story}
