"""Page context: Befunde. What was tested, what carried, what did not, and what became of each idea."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..charts import NARROW, WIDE, num
from ..charts import befunde as ch
from ..showcase import pruefstand
from . import Quellen

ARCHIV_SATZ = "Das Archiv vor dem 17.10.2026 ist lückenhaft."

# F07 may read these four blocks of rueckblick.json and nothing else. The other tests in that file use sources
# this site does not show, so a new signal is added here only after that has been checked.
F07_SIGNALE = (
    (("t6_nachbarn", "anderer_inhaber_gleicher_wirkstoff", "8_wochen"), "Anderer Inhaber, gleicher Wirkstoff",
     "Hinweis auf der Frühwarnliste"),
    (("t6_nachbarn", "atc4_nachbarn", "nachbar_in_at", "8_wochen"), "ATC-4-Nachbar in Österreich", "nicht verwendet"),
    (("t8_marktaustritt", "alle", "8_wochen"), "Marktaustritt eines anderen Produkts", "Merkmal in Z3 v0"),
    (("t9_eko_streichung", "alle", "8_wochen"), "EKO-Streichung eines anderen Produkts", "Merkmal in Z3 v0"),
)

TONE = {"trägt": "accent", "kein Gewinn": "neutral", "unklar": "warn", "zu wenige Fälle": "info", "kein Urteil": "neutral"}
F18_KURZ = ("Höchste Stufe ab fünf Ländern", "Gewichte für einzelne Länder", "Grund der Auslandsmeldung", "Stärke und Darreichungsform")
F18_ACHSE = ("zusätzliche spätere Meldungen 2026", "AUC-Differenz")
WEITERE_FOLGE = {
    "Preisband-Runden 2017–2025": "nicht verwendet",
    "Infektionswellen (ERVISS)": "nicht verwendet",
    "Ein einzelnes meldendes Land": "nicht gelistet",
    "GMP-Mängel bei Wirkstoffherstellern": "wird mitgeschrieben",
}
KONTROLLE = {"nicht bestanden": "Kontrolle fehlgeschlagen", "bestanden": "Kontrolle wie erwartet"}


def urteil_sir(lo: float, hi: float) -> str:
    """Verdict from the interval alone, so that it follows the daily recalculation."""
    return "trägt" if lo > 1 else "kein Gewinn" if hi < 1 else "unklar"


def _rueckblick_path(conn: sqlite3.Connection) -> Path | None:
    main = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "")
    return Path(main).parent / "json" / "rueckblick.json" if main else None


def f07_rows(path: Path | None) -> list[dict]:
    """Copy exactly the whitelisted values out of rueckblick.json; empty if the file is missing."""
    if path is None or not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for keys, name, folge in F07_SIGNALE:
        block = raw
        for key in keys:
            block = block[key]
        counts = block.get("mit", block)
        lo, hi = block["sir_ki95"]
        rows.append({"name": name, "folge": folge, "sir": block["sir"], "ki": [lo, hi], "faelle": counts["faelle"],
                     "treffer": counts["treffer"], "erwartet": block["erwartet"], "urteil": urteil_sir(lo, hi)})
    return rows


def _f07(rows: list[dict]) -> dict:
    table = {
        "caption": "Beobachtete und erwartete neue BASG-Meldungen binnen 8 Wochen je Signal",
        "head": ["Signal", "Fälle", "Beobachtet", "Erwartet", "SIR", "95-%-Bereich", "Urteil"],
        "rows": [[r["name"], num(r["faelle"]), num(r["treffer"]), num(r["erwartet"], 1), num(r["sir"], 2),
                  f'{num(r["ki"][0], 2)} bis {num(r["ki"][1], 2)}', r["urteil"]] for r in rows],
    }
    caption = ("SIR heißt: beobachtete durch erwartete Meldungen, erwartet aus Wirkstoffen gleicher Produktzahl, gleicher "
               "Engpass-Vorgeschichte und gleichen Jahres. Bei 1 folgten so viele Meldungen wie erwartet. Der Bereich ist ein "
               "95-%-Intervall nach Byar; Stichtage desselben Wirkstoffs sind nicht unabhängig, der Bereich ist daher eher zu eng. "
               "Ein Zusammenhang im Rückblick ist noch kein Nutzen für eine Vorhersage.")
    return {
        "id": "f07",
        "kind": "rueckblick",
        "legend": "Welche Ereignisse in Österreich gingen Meldungen voraus?",
        "svg_wide": ch.f07(rows, width=WIDE, uid="f07w"),
        "svg_narrow": ch.f07(rows, width=NARROW, uid="f07n"),
        "caption": caption,
        "table": table,
        "source": f"eigene Rückblicktests ab 01.01.2022 aus BASG-Meldungen, ASP-Liste und EKO, im Tageslauf neu gerechnet. {ARCHIV_SATZ}",
        "referenz": False,
    }


def _f07_satz(rows: list[dict]) -> str:
    """The sentence above F07 follows the daily numbers, so it can never contradict the figure."""
    carrying = [r["name"] for r in rows if r["urteil"] == "trägt"]
    if not carrying:
        return "Bei keinem der Signale liegt der Bereich derzeit ganz über 1."
    return f'Ganz über 1 liegt der Bereich derzeit bei {len(carrying)} von {len(rows)} Signalen: {", ".join(carrying)}.'


def _f18_rows(block: dict) -> list[dict]:
    rows = []
    measured = 0
    for row, kurz in zip(block["zeilen"], F18_KURZ, strict=True):
        out = {**row, "kurz": kurz, "ki": row.get("ki95")}
        if out["ki"] is not None:
            out["dezimal"] = 0 if float(row["wert"]).is_integer() else 3
            out["achse"] = F18_ACHSE[measured]
            measured += 1
        rows.append(out)
    return rows


def _f18(block: dict) -> dict:
    rows = _f18_rows(block)
    def value(r: dict) -> str:
        return ch.ci(r["wert"], *r["ki"], decimals=r["dezimal"], signed=True) if r["ki"] else "keine Zahl veröffentlicht"
    table = {
        "caption": "Verfeinerungen der Stufen, gelernt 2024–2025, geprüft 2026",
        "head": ["Idee", "Urteil", "Wert [95 %]", "Einheit", "Folge"],
        "rows": [[r["idee"], r["urteil"], value(r), " ".join(p for p in (r.get("einheit"), r.get("zusatz")) if p) or "–", r["folge"]] for r in rows],
    }
    caption = ("Jede Verfeinerung wurde auf 2024–2025 gelernt und auf 2026 gegen die Stufe desselben Falls geprüft. "
               f'Mit der höchsten Stufe ab fünf Ländern folgten {num(rows[0]["wert"])} {rows[0]["einheit"]}, {rows[0]["zusatz"]}. '
               "Die Intervalle ziehen ganze Wirkstoffe neu (500 Ziehungen). Jede Grafikzeile hat ihre eigene Achse.")
    return {
        "id": "f18",
        "kind": "rueckblick",
        "legend": "Lassen sich die Stufen schärfen?",
        "svg_wide": ch.f18(rows, width=WIDE, uid="f18w"),
        "svg_narrow": ch.f18(rows, width=NARROW, uid="f18n"),
        "caption": caption,
        "table": table,
        "source": f'{block["quelle"]}. {ARCHIV_SATZ}',
    }


def _f19(block: dict) -> dict:
    data = {**block, "kontrollen": [{**c, "wort": KONTROLLE[c["ergebnis"]]} for c in block["kontrollen"]]}
    positive = next(c for c in data["kontrollen"] if c["id"] == "positiv")
    gain = ch.ci(positive["prognosegewinn_1e5"], *positive["prognosegewinn_ki"], decimals=1, signed=True)
    rows = [[r["name"], num(r["alle"]["or"], 3), f'{num(r["alle"]["ki"][0], 3)} bis {num(r["alle"]["ki"][1], 3)}',
             num(r["signal"]["or"], 3), f'{num(r["signal"]["ki"][0], 3)} bis {num(r["signal"]["ki"][1], 3)}', "Holm-korrigiert"]
            for r in data["zeilen"]]
    for c in data["kontrollen"]:
        note = f'Zusatzwert {c["zusatzwert"]}, Prognosegewinn {c["prognosegewinn"]}'
        if c["id"] == "positiv":
            note += f" ({gain} × 10⁻⁵)"
        rows.append([f'Kontrolle: {c["name"]}', num(c["or"], 3), f'{num(c["ki"][0], 3)} bis {num(c["ki"][1], 3)}', "–", "–", f'{note}; {c["wort"]}'])
    f = data["faelle"]
    table = {
        "caption": (f'{data["einheit"]}, {data["horizont_tage"]} Tage. Alle Fälle: {num(f["alle"])} mit {num(f["alle_meldungen"])} Meldungen; '
                    f'Fälle mit Signal: {num(f["signal"])} mit {num(f["signal_meldungen"])} Meldungen'),
        "head": ["Prüfung", "OR, alle Fälle", "Bereich", "OR, mit Signal", "Bereich", "Anmerkung"],
        "rows": rows,
    }
    caption = (f'{data["variante"]} {data["intervalle"]} Das bekannte Kontrollsignal lag in der ersten Messung, dem Zusatzwert, über 1. '
               f"In der zweiten Messung, dem Prognosegewinn, wurde es nicht gefunden ({gain} × 10⁻⁵); die Kontrolle ist damit fehlgeschlagen. "
               f'Vergleichsmodell: {data["vergleichsmodell"]}. {data["grenzen"]}')
    return {
        "id": "f19",
        "kind": "rueckblick",
        "legend": "Hilft das Tempo der Signale?",
        "svg_wide": ch.f19(data, width=WIDE, uid="f19w"),
        "svg_narrow": ch.f19(data, width=NARROW, uid="f19n"),
        "caption": caption,
        "table": table,
        "source": f'{data["quelle"]}, Stand {data["stand"][8:10]}.{data["stand"][5:7]}.{data["stand"][:4]}. {ARCHIV_SATZ}',
    }


def _f20(block: dict) -> dict:
    top = {r["jahr"]: r for r in block["top50_differenz"]}
    pooled = top["alle Jahre"]
    rows = [[b["jahr"], ch.ci(b["wert"], *b["ki95"], decimals=1, signed=True),
             ch.ci(top[b["jahr"]]["wert"], *top[b["jahr"]]["ki95"], decimals=1, signed=True)] for b in block["brier_gewinn"]]
    table = {"caption": f'Abstand des Herausforderers {block["name"]} zu z3_v0, Horizont {block["horizont_tage"]} Tage, Wert [95-%-Bereich]',
             "head": ["Testjahr", "Brier-Gewinn in 10⁻⁵", "Differenz Top 50 in Pp"], "rows": rows}
    caption = (f'Verglichen wird der Herausforderer {block["name"]} mit {block["vergleich"]}, also nicht mit der eingefrorenen Fassung. '
               f'{block["ehrlichkeit"]} Über alle Jahre reicht der Top-50-Bereich von {num(pooled["ki95"][0], 1)} bis '
               f'{num(pooled["ki95"][1], 1)} Prozentpunkten. Der Herausforderer ist das Ergebnis von rund {num(block["versuche"]["innen_rund"])} '
               "rückblickenden Versuchen; seine Zahlen sind kein Nachweis eines besseren Modells. z3_v0 bleibt das Hauptmodell.")
    return {
        "id": "f20",
        "kind": "rueckblick",
        "legend": "Modellsuche: Abstand eines Herausforderers zu z3_v0",
        "svg_wide": ch.f20(block, width=WIDE, uid="f20w"),
        "svg_narrow": ch.f20(block, width=NARROW, uid="f20n"),
        "caption": caption,
        "table": table,
        "source": f'{block["quelle"]}, Stand {block["stand"][8:10]}.{block["stand"][5:7]}.{block["stand"][:4]}. {ARCHIV_SATZ}',
    }


def _row(idee: str, urteil: str, befund: str, einheit: str, folge: str) -> dict:
    return {"idee": idee, "urteil": urteil, "tone": TONE[urteil], "befund": befund, "einheit": einheit, "folge": folge}


def _ledger(results: dict, sir: list[dict]) -> dict:
    stufen = []
    for r in _f18_rows(results["stufen_schaerfen"]):
        number = ch.ci(r["wert"], *r["ki"], decimals=r["dezimal"], signed=True) if r["ki"] else ""
        stufen.append(_row(r["idee"], r["urteil"], number, r.get("einheit") or "kein Gewinn gegenüber der Stufe", r["folge"]))
    register = [_row(r["name"], r["urteil"], ch.ci(r["sir"], *r["ki"]), "SIR, 8 Wochen", r["folge"]) for r in sir]
    weitere = [_row(r["idee"], r["urteil"], "", r["text"], WEITERE_FOLGE.get(r["idee"], "–"))
               for r in results["weitere_signale_text"]["nur_text"]]
    tempo = results["signaltempo_tabelle"]
    combo = next(r for r in tempo["zeilen"] if r["id"] == "alle")["alle"]
    suche = results["modellsuche_zusammenfassung"]
    modelle = [
        _row("Tempo, mit dem sich Signale ausbreiten", tempo["urteil"], ch.ci(combo["or"], *combo["ki"], decimals=3),
             "OR der Kombination, alle Fälle; Kontrolle fehlgeschlagen", "in kein Modell übernommen, wird vorwärts geprüft"),
        _row(f'Modellsuche, rund {num(suche["versuche"]["innen_rund"])} Varianten', "kein Urteil", "",
             "Rückblick, Testjahre mehrfach gesehen", "z3_v0 bleibt Hauptmodell; Herausforderer eingefroren, wird nur mitgerechnet"),
    ]
    groups = [g for g in (
        {"name": "Ereignisse in Österreich", "figs": [("f07", "zur Grafik")], "rows": register},
        {"name": "Stufen der Frühwarnliste schärfen", "figs": [("f18", "zur Grafik")], "rows": stufen},
        {"name": "Weitere Signale", "figs": [], "rows": weitere},
        {"name": "Tempo und Modellsuche", "figs": [("f19", "Grafik Tempo"), ("f20", "Grafik Modellsuche")], "rows": modelle},
    ) if g["rows"]]
    every = [r for g in groups for r in g["rows"]]
    counts = [(name, num(sum(r["urteil"] == name for r in every))) for name in TONE if any(r["urteil"] == name for r in every)]
    return {"groups": groups, "counts": counts, "n": len(every)}


def context(q: Quellen) -> dict:
    r = q.results
    sir = f07_rows(_rueckblick_path(q.conn))
    bench = pruefstand(r, q.ref)
    tempo = r["signaltempo_tabelle"]
    suche = r["modellsuche_zusammenfassung"]
    return {
        "ledger": _ledger(r, sir),
        "f07": _f07(sir) if sir else None,
        "f07_satz": _f07_satz(sir),
        "f18": _f18(r["stufen_schaerfen"]),
        "f19": _f19(tempo),
        "f20": _f20(suche),
        "tempo": {"urteil": tempo["urteil"], "text": tempo["urteil_text"], "folge": r["signaltempo"]["folge"]},
        "suche": {"entscheidung": suche["entscheidung"], "beschreibung": suche["beschreibung"]},
        "ausland": r["auslandsdaten_im_modell"]["text"],
        "beginn": bench["start"],
        "go": bench["go"],
    }
