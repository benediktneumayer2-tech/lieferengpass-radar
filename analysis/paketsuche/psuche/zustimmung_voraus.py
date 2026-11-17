"""s28 Zusatzprüfung: treffen Top-50-Warnungen von z3_v0, denen das eingefrorene Inhabermodell zustimmt, prospektiv
öfter ein als solche ohne Zustimmung? Regel: `analysis/paketsuche/zusatzpruefung/ZUSATZPRUEFPLAN.md` und
`zusatzpruefplan.json` (festgelegt 16.11.2026; das Skript prüft beim Start die dort eingetragenen sha256).

    cd analysis/paketsuche; PY=../modellsuche/.venv/bin/python; export PSUCHE_THREADS=8 CUDA_VISIBLE_DEVICES=""
    # zuerst die s23-Spätprüfung mit demselben Stand (baut Archivsicht und Datenbank unter analysis/modellsuche/work):
    (cd ../modellsuche && nice -n 10 .venv/bin/python -m msuche.spaetpruefung --bis 2027-03-01T23:59:59Z)
    nice -n 10 $PY -m psuche.zustimmung_voraus --bis 2027-03-01T23:59:59Z   # → results/zustimmung_voraus.json
    nice -n 10 $PY -m psuche.zustimmung_voraus --bis heute   # Stand der Modellsuche (16.11.2026): vor 2027 nichts auswertbar
    nice -n 10 $PY -m psuche.zustimmung_voraus --probe   # Montage ab 26.10.2026, Stand heute; zählt nicht
    nice -n 10 $PY -m psuche.zustimmung_voraus --test    # Rückblick 2024–2026 auf s23/s25-Vorhersagen; zählt nicht

Ablauf (Auswertung mit --bis):
1. sha256 von Prüfplan, z3_v0, eingefrorenem Inhabermodell, E_S3z_C und diesem Skript gegen `zusatzpruefplan.json`;
   bei Abweichung keine Auswertung. Ebenso müssen die Regelwerte im Skript (`REGEL`) denen der Datei gleichen.
2. Montagsprotokolle ab 04.01.2027 (`stockout_at.modell.read_logs`, nur Zeilen mit Prüfplan 35a230a0a9bd).
3. Je Montag d ≤ BASG-Stand: Inhaberpanel und Merkmale zeitpunktgenau mit dem s27-Rechenweg
   (`psuche.zusammenspiel_voraus.merkmale`), T04_I_lin_klein je Inhaber-Fall, q = 1 − Π(1 − p) je Wirkstoff
   (`zusammenspiel.zusammen`), dazu E_S3z_C. Einmal gerechnete Montage werden nie neu gerechnet
   (`work/zusatzpruefung/werte.parquet`).
4. Liste = 50 höchste `z3_v0_p8` je Montag (Gleichstand: ATC5 aufsteigend); bestätigt = q unter den 50 höchsten q der
   Wirkstoffe des Protokolls (gleicher Gleichstand; ohne q nicht bestätigt).
5. Ziel und Fälle wie `stockout bewertung` (`modell.report_days`, `modell._within`): Meldung beginnt oder erscheint
   erstmals in (d, d + h], nur wenn d + h ≤ BASG-Stand der Datenbank des Stands (nur lesend).
6. Hauptendpunkt: Quote bestätigt − nicht bestätigt (56 Tage) mit 95-%-Bereich aus dem Bootstrap über ganze Wirkstoffe;
   Nebenpunkte beschreibend (eingetroffen/angesagt, 28 und 84 Tage, E_S3z_C als Hauptmodell).

Testmodus: dieselben Funktionen auf den Rückblickvorhersagen (z3_v0 äußer aus s23 mp1, q_I und E_S3z_C aus s25/s27,
`zusammenspiel.w_basis`), dazu die Ziele über `stockout_at` gegen die Panelziele des Rückblicks.

Schreibt nur unter analysis/paketsuche (results/zustimmung_voraus*.json, work/zusatzpruefung/). Archiv, Protokolle,
models/ und analysis/modellsuche werden nur gelesen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import pfade
from . import zusammenspiel as zs
from . import zusammenspiel_voraus as zv

REPO = pfade.MS_ROOT.parents[1]
PLAN_DIR = pfade.ROOT / "zusatzpruefung"
PLAN_JSON = PLAN_DIR / "zusatzpruefplan.json"
WORK = pfade.WORK / "zusatzpruefung"
WERTE = WORK / "werte.parquet"
ERGEBNIS = pfade.RESULTS / "zustimmung_voraus.json"
PROBE = pfade.RESULTS / "zustimmung_voraus_probe.json"
TEST = pfade.RESULTS / "zustimmung_voraus_test.json"
SPAET = pfade.MS_WORK / "spaet" / "vorhersagen.parquet"
Z3_RUECK = pfade.MS_WORK / "vorhersagen" / "basis_mp1_z3_v0.parquet"

K = 50
H = 56
HS = (28, 56, 84)
BEGINN = date(2027, 1, 4)
FENSTER = (date(2027, 1, 4), date(2027, 6, 28))
ZWISCHEN = date(2027, 4, 30)
B = 2000
SEED = 20261116
PROBE_AB = date(2026, 10, 26)
PRUEFPLAN_KURZ = "35a230a0a9bd"

DATEIEN = {  # Pfad (relativ zum Repo) → Rolle; sha256 stehen in zusatzpruefplan.json
    "models/pruefplan.json": "Prüfplan der Hauptprüfung",
    "models/z3_v0.json": "Hauptmodell z3_v0",
    "analysis/paketsuche/work/zusammenspiel/zusammenspiel_fest_2026-11-16.pkl": "eingefrorenes Inhabermodell T04_I_lin_klein",
    "analysis/modellsuche/work/spaet/modell_E_S3z_C_2026-10-20.pkl": "eingefrorenes E_S3z_C (s23)",
    "analysis/paketsuche/psuche/zustimmung_voraus.py": "Auswerteskript",
}

REGEL = {
    "hauptmodell": {"verfahren": "z3_v0", "spalte": "z3_v0_p8", "quelle": "data/archive/protokoll/vorhersagen/JJJJ/JJJJ-MM-TT.csv.gz",
                    "pruefplan": PRUEFPLAN_KURZ},
    "stichtage": {"wochentag": "Montag", "ab": BEGINN.isoformat(), "nur_mit_protokoll": True},
    "liste": {"k": K, "gleichstand": "atc5 aufsteigend"},
    "zustimmung": {"modell": "T04_I_lin_klein",
                   "objekt": "analysis/paketsuche/work/zusammenspiel/zusammenspiel_fest_2026-11-16.pkl",
                   "daten": "je Stichtag aus dem Archiv, nur Daten vor dem Stichtag (Rechenweg s27); einmal gerechnet, nie neu",
                   "zusammenfassung": "q = 1 - prod(1 - p) über die Inhaber-Fälle des Wirkstoffs, roh",
                   "bestaetigt": "Wirkstoff steht am selben Stichtag auch unter den k höchsten q",
                   "k": K, "rang_unter": "Wirkstoffe des Protokolls", "gleichstand": "atc5 aufsteigend",
                   "ohne_q": "nicht bestätigt"},
    "ziel": {"regel": "wie stockout bewertung: eine BASG-Meldung zum Wirkstoff beginnt oder erscheint erstmals in (d, d + h]",
             "horizont": H, "zaehlt_ab": "d + h <= BASG-Stand"},
    "hauptendpunkt": {"groesse": "Trefferquote bestätigt minus nicht bestätigt innerhalb der Top k, gepoolt über die Stichtage",
                      "bootstrap": {"einheit": "ganze Wirkstoffe (ATC5)", "B": B, "seed": SEED, "niveau": 0.95,
                                    "bereich": "Perzentil"},
                      "erfuellt": "95-%-Bereich liegt über 0 (untere Grenze > 0)"},
    "auswertung": {"entscheidend": {"montage_von": FENSTER[0].isoformat(), "montage_bis": FENSTER[1].isoformat(),
                                    "endgueltig_ab_basg_stand": (FENSTER[1] + timedelta(days=H)).isoformat()},
                   "zwischenauswertung": {"am": ZWISCHEN.isoformat(), "art": "nur beschreibend (Go/No-Go)"}},
    "nebenpunkte": {"verhaeltnis": "je Gruppe eingetroffen zu angesagt (Summe y / Summe der Werte des Hauptmodells)",
                    "horizonte": [28, 84],
                    "horizonte_lesart": "Liste und Zustimmung mit den Werten des Horizonts (z3_v0_p4 bzw. z3_v0_p12, q für "
                                        "28 bzw. 84 Tage); daneben die 8-Wochen-Liste mit Ziel 28/84 Tage",
                    "E_S3z_C": "dieselbe Teilung mit E_S3z_C (56 Tage) als Hauptmodell; Werte aus msuche.spaetpruefung "
                               "(work/spaet/vorhersagen.parquet), sonst aus derselben Nachrechnung",
                    "art": "beschreibend"},
}


# --- Zusatzprüfplan -------------------------------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan_pruefen(pflicht: bool) -> dict:
    """sha256 und Regelwerte gegen zusatzpruefplan.json; ohne Datei nur im Probe-/Testmodus weiter."""
    if not PLAN_JSON.exists():
        if pflicht:
            raise SystemExit(f"{PLAN_JSON} fehlt: keine Auswertung ohne festgelegten Zusatzprüfplan")
        print(f"Hinweis: {PLAN_JSON.name} fehlt (nur Probe/Test)")
        return {"status": "fehlt"}
    raw = PLAN_JSON.read_bytes()
    plan = json.loads(raw)
    falsch = {p: {"soll": d["sha256"], "ist": _sha(REPO / p)} for p, d in plan["dateien"].items()
              if _sha(REPO / p) != d["sha256"]}
    if set(plan["dateien"]) != set(DATEIEN):
        falsch["dateiliste"] = {"soll": sorted(plan["dateien"]), "ist": sorted(DATEIEN)}
    if json.loads(json.dumps(REGEL)) != plan["regel"]:
        falsch["regel"] = "Regelwerte im Skript weichen von zusatzpruefplan.json ab"
    pp = json.loads((REPO / "models/pruefplan.json").read_text(encoding="utf-8"))["sha256"]
    if not pp.startswith(PRUEFPLAN_KURZ):
        falsch["pruefplan_sha256"] = pp
    if falsch:
        raise SystemExit("Zusatzprüfplan verletzt, keine Auswertung: " + json.dumps(falsch, ensure_ascii=False))
    return {"status": "geprüft", "sha256": hashlib.sha256(raw).hexdigest(),
            "dateien": {p: d["sha256"][:12] for p, d in plan["dateien"].items()}}


def einfrieren() -> None:
    """zusatzpruefplan.json einmal schreiben (nur vor dem 01.01.2027 und nur, wenn sie noch nicht existiert)."""
    if date.today() >= date(2027, 1, 1):
        raise SystemExit("Ab dem 01.01.2027 wird der Zusatzprüfplan nicht mehr geschrieben")
    if PLAN_JSON.exists():
        raise SystemExit(f"{PLAN_JSON} existiert schon; nichts überschrieben")
    pp = json.loads((REPO / "models/pruefplan.json").read_text(encoding="utf-8"))
    dateien = {p: {"rolle": r, "sha256": _sha(REPO / p)} for p, r in DATEIEN.items()}
    dateien["models/pruefplan.json"]["pruefplan_sha256"] = pp["sha256"]
    dateien["models/z3_v0.json"]["sha256_im_pruefplan"] = pp["verfahren"]["z3_v0"]["sha256"]
    plan = {"name": "Zusatzprüfung: Zustimmung des Inhabermodells (s28)", "festgelegt_am": "2026-11-16",
            "owner_entscheidung": "2026-11-16", "regeltext": "analysis/paketsuche/zusatzpruefung/ZUSATZPRUEFPLAN.md",
            "auswerteskript": "analysis/paketsuche/psuche/zustimmung_voraus.py", "regel": REGEL,
            "unberuehrt": ["Hauptprüfung nach models/pruefplan.json (35a230a0a9bd)", "models/", "src/", "deploy/",
                           "data/", "Anzeige auf der Website (frühestens nach dem Go/No-Go und nur nach Owner-Entscheidung)"],
            "dateien": dateien, "geschrieben": datetime.now().astimezone().isoformat(timespec="seconds")}
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_JSON.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{PLAN_JSON} geschrieben, sha256 {_sha(PLAN_JSON)}")


# --- Liste, Zustimmung, Endpunkt -------------------------------------------------------------------------------------

def _rang(F: pd.DataFrame, col: str) -> pd.Series:
    """Rang je Stichtag t nach col absteigend (fehlend = ganz unten), Gleichstand ATC5 aufsteigend."""
    x = F[col].to_numpy(float)
    S = pd.DataFrame({"t": F["t"].to_numpy(), "x": -np.where(np.isnan(x), -np.inf, x), "a": F["atc5"].to_numpy()},
                     index=F.index).sort_values(["t", "x", "a"], kind="mergesort")
    return (S.groupby("t", sort=False).cumcount() + 1).reindex(F.index)


def markiere(F: pd.DataFrame, wert: str, q: str, k: int = K) -> pd.DataFrame:
    """F: alle Fälle (t, atc5, wert, q) → Spalten rang, rang_q, top (k höchste wert), bestaetigt (auch k höchste q)."""
    F = F.copy()
    F["rang"], F["rang_q"] = _rang(F, wert), _rang(F, q)
    F["top"] = F["rang"] <= k
    F["bestaetigt"] = F["top"] & (F["rang_q"] <= k) & F[q].notna()
    return F


def _ki(T: pd.DataFrame, y: str, b: int, seed: int) -> dict:
    """Bootstrap über ganze Wirkstoffe: Quote bestätigt − nicht bestätigt, 95-%-Perzentilbereich."""
    bb = T["bestaetigt"].to_numpy(bool)
    yy = T[y].to_numpy(float)
    G = pd.DataFrame({"a": T["atc5"].to_numpy(), "nb": bb * 1.0, "yb": yy * bb, "nn": (~bb) * 1.0,
                      "yn": yy * ~bb}).groupby("a").sum()
    n = len(G)
    w = np.random.default_rng(seed).multinomial(n, np.full(n, 1.0 / n), size=b).astype(float)
    NB, YB, NN, YN = (w @ G[c].to_numpy(float) for c in ("nb", "yb", "nn", "yn"))
    with np.errstate(divide="ignore", invalid="ignore"):
        d = YB / NB - YN / NN
    ok = np.isfinite(d)
    lo, hi = np.percentile(d[ok], [2.5, 97.5]) if ok.any() else (np.nan, np.nan)
    return {"ki95": [float(lo), float(hi)], "wirkstoffe": int(n), "ziehungen": int(b), "gueltig": int(ok.sum()), "seed": seed}


def endpunkt(T: pd.DataFrame, y: str, p: str, b: int = B, seed: int = SEED) -> dict:
    """T: Listenzeilen (top) mit bestaetigt; nur Zeilen mit bekanntem Ziel zählen."""
    g = T[T[y].notna()]
    if g.empty:
        return {"status": "noch nicht auswertbar", "montage": 0, "faelle": 0}
    nw = int(g["t"].nunique())
    out = {"montage": nw, "erster": str(pd.Timestamp(g["t"].min()).date()), "letzter": str(pd.Timestamp(g["t"].max()).date()),
           "faelle": int(len(g)), "treffer": int(g[y].sum()), "quote_top": float(g[y].mean())}
    for name, m in (("bestaetigt", g["bestaetigt"]), ("nicht_bestaetigt", ~g["bestaetigt"])):
        x = g[m.to_numpy(bool)]
        sp = float(x[p].sum())
        out[name] = {"faelle": int(len(x)), "je_montag": round(len(x) / nw, 2), "treffer": int(x[y].sum()),
                     "quote": float(x[y].mean()) if len(x) else None, "angesagt": sp,
                     "eingetroffen_zu_angesagt": float(x[y].sum() / sp) if sp > 0 else None}
    qb, qn = out["bestaetigt"]["quote"], out["nicht_bestaetigt"]["quote"]
    out["differenz"] = float(qb - qn) if qb is not None and qn is not None else None
    if out["differenz"] is not None and b:
        out["bootstrap"] = _ki(g, y, b, seed)
    return out


# --- Werte des Inhabermodells je Montag -------------------------------------------------------------------------------

def rechne(stand: str, tage: list[date], fest: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(Werte je t, h, atc5: q, n_einheiten, pe; D; U) mit dem s27-Rechenweg, nur Daten vor dem Stichtag."""
    D, U, _ = zv.merkmale(stand, tage, fest)
    I = fest["I_modell"]
    F = U[U["fall"].astype(bool)]
    rows = []
    for h in HS:
        d = pd.DataFrame({"jahr": F["t"].dt.year.to_numpy(np.int16), "h": np.int16(h), "t": F["t"].to_numpy(),
                          "einheit": F["einheit"].to_numpy(), "atc5": F["atc5"].to_numpy(),
                          "p": I["modelle"][h].p(F[I["spalten"]], h)})
        Q = zs.zusammen(d)[["t", "atc5", "q", "n"]].rename(columns={"n": "n_einheiten"})
        Q["t"] = pd.to_datetime(Q["t"]).astype("datetime64[ns]")
        E = D[["t", "atc5", f"pe{h}"]].rename(columns={f"pe{h}": "pe"})
        E["t"] = pd.to_datetime(E["t"]).astype("datetime64[ns]")
        rows.append(Q.merge(E, on=["t", "atc5"], how="outer", validate="one_to_one").assign(h=np.int16(h)))
    W = pd.concat(rows, ignore_index=True)
    W["t"] = pd.to_datetime(W["t"]).astype("datetime64[ns]")
    return W, D, U


def _spaet() -> pd.DataFrame | None:
    """E_S3z_C aus der s23-Spätprüfung (einmal gerechnet je Protokolltag), falls vorhanden."""
    if not SPAET.exists():
        return None
    S = pd.read_parquet(SPAET)
    if set(S["kombination"].unique()) != {"E_S3z_C"}:
        return None
    S["t"] = pd.to_datetime(S["datum"]).astype("datetime64[ns]")
    return S[["t", "atc5", "p28", "p56", "p84"]]


def rahmen(logs: dict, tage: list[date], W: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Alle Wirkstoffe der Montagsprotokolle mit z3_v0 (p4/p8/p12), q{h} und pe{h} (E bevorzugt aus der Spätprüfung)."""
    rows = [{"t": pd.Timestamp(d), "atc5": a, "z3_p4": r["p"][28]["z3_v0"], "z3_p8": r["p"][56]["z3_v0"],
             "z3_p12": r["p"][84]["z3_v0"]} for d in tage for a, r in logs[d].items()]
    F = pd.DataFrame(rows)
    F["t"] = F["t"].astype("datetime64[ns]")
    for h in HS:
        x = W[W["h"] == h][["t", "atc5", "q", "pe"]].rename(columns={"q": f"q{h}", "pe": f"pe{h}_eigen"})
        F = F.merge(x, on=["t", "atc5"], how="left", validate="one_to_one")
    S = _spaet()
    quelle = {}
    for h in HS:
        F[f"pe{h}"] = F[f"pe{h}_eigen"]
    if S is not None:
        F = F.merge(S, on=["t", "atc5"], how="left", validate="one_to_one")
        s_tage = set(S["t"].dt.date)
        m = F["t"].dt.date.isin(s_tage).to_numpy()
        for h in HS:
            F.loc[m, f"pe{h}"] = F.loc[m, f"p{h}"]
        both = m & F["p56"].notna().to_numpy() & F["pe56_eigen"].notna().to_numpy()
        quelle["max_abweichung_spaet_eigen"] = {str(h): float(np.max(np.abs(F.loc[both, f"p{h}"] - F.loc[both, f"pe{h}_eigen"])))
                                                if both.any() else None for h in HS}
        F = F.drop(columns=["p28", "p56", "p84"])
    else:
        s_tage = set()
    quelle["je_montag"] = {str(d): ("spaetpruefung" if d in s_tage else "eigene Nachrechnung") for d in tage}
    return F, quelle


def ziele(conn, F: pd.DataFrame) -> tuple[pd.DataFrame, date]:
    """y{h} wie `stockout_at.modell.bewerten`; NaN, solange d + h > BASG-Stand."""
    from stockout_at.modell import _within, report_days
    starts, seen, _, latest = report_days(conn)
    F = F.copy()
    tage = F["t"].dt.date.to_numpy()
    for h in HS:
        F[f"y{h}"] = [float(_within(starts.get(a, []), d, h) or _within(seen.get(a, []), d, h))
                      if d + timedelta(days=h) <= latest else np.nan for a, d in zip(F["atc5"], tage)]
    return F, latest


# --- Auswertung --------------------------------------------------------------------------------------------------------

TEILE = {  # name → (Wert der Liste, q, Ziel, angesagt)
    "haupt_z3_v0_56": ("z3_p8", "q56", "y56", "z3_p8"),
    "neben_z3_v0_28": ("z3_p4", "q28", "y28", "z3_p4"),
    "neben_z3_v0_84": ("z3_p12", "q84", "y84", "z3_p12"),
    "neben_liste56_ziel28": ("z3_p8", "q56", "y28", "z3_p4"),
    "neben_liste56_ziel84": ("z3_p8", "q56", "y84", "z3_p12"),
    "neben_E_S3z_C_56": ("pe56", "q56", "y56", "pe56"),
}


def listen(F: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {n: markiere(F, w, q)[lambda x: x["top"]] for n, (w, q, _, _) in TEILE.items()}


def auswerten(L: dict[str, pd.DataFrame], latest: date) -> dict:
    out = {}
    fertig = latest >= FENSTER[1] + timedelta(days=H)
    for n, (_, _, y, p) in TEILE.items():
        T = L[n]
        tt = T["t"].dt.date
        r = {"fenster": endpunkt(T[(tt >= FENSTER[0]) & (tt <= FENSTER[1])], y, p)}
        if (tt > FENSTER[1]).any():
            r["alle_montage_ab_beginn"] = endpunkt(T, y, p)
        out[n] = r
    h = out["haupt_z3_v0_56"]["fenster"]
    if h.get("faelle", 0) == 0:
        h["status"] = "noch nicht auswertbar"
    elif not fertig:
        h["status"] = (f"vorläufig, nur beschreibend ({h['montage']} Montage; entscheidend erst ab BASG-Stand "
                       f"{FENSTER[1] + timedelta(days=H)})")
    else:
        h["status"] = "entscheidend"
        ki = h.get("bootstrap", {}).get("ki95")
        h["erfuellt"] = bool(ki and np.isfinite(ki[0]) and ki[0] > 0)
    return out


def _zusammenfassung(L: dict[str, pd.DataFrame], F: pd.DataFrame) -> dict:
    T = L["haupt_z3_v0_56"]
    out = {}
    for t, g in F.groupby("t"):
        x = T[T["t"] == t]
        out[str(pd.Timestamp(t).date())] = {"protokoll": int(len(g)), "mit_q56": int(g["q56"].notna().sum()),
                                            "liste": int(len(x)), "bestaetigt": int(x["bestaetigt"].sum()),
                                            "liste_mit_q": int(x["q56"].notna().sum()),
                                            "ziel_bekannt_56": int(x["y56"].notna().sum())}
    return out


def _stand_db(stand: str) -> Path:
    from msuche import panel as ms_panel
    _, name, db, _ = ms_panel.STAENDE[stand]
    db = Path(db) if db else pfade.MS_WORK / f"stockout_{name}.sqlite"
    if not db.exists():
        raise SystemExit(f"Datenbank des Stands {db} fehlt: zuerst msuche.spaetpruefung mit demselben --bis")
    return db


def lauf(probe: bool, bis: str | None, lauf_info: dict) -> dict:
    from msuche import pfade as ms_pfade
    from msuche import sicht
    from stockout_at.modell import read_logs
    fest, fsha = zv.lade_fest()
    stand = zv.stand_einrichten(None if probe or bis == "heute" else bis)
    conn = sicht.connect(_stand_db(stand))
    lat = date.fromisoformat(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
    pp = json.loads((REPO / "models/pruefplan.json").read_text(encoding="utf-8"))["sha256"]
    ab = PROBE_AB if probe else BEGINN
    logs = read_logs(ms_pfade.ARCHIVE, ab, None, pp)
    montage = sorted(d for d in logs if d.weekday() == 0)
    rechenbar = [d for d in montage if d <= lat]
    info = {**lauf_info, "art": "Probe (zählt nicht)" if probe else "Auswertung", "fest_sha256": fsha, "stand": stand,
            "basg_stand": str(lat), "pruefplan": pp[:12], "montage_mit_protokoll": [str(d) for d in montage],
            "montage_rechenbar": [str(d) for d in rechenbar],
            "montage_wartend": [str(d) for d in montage if d > lat],
            "zeitplan": {"erste_auswertung": {str(h): str(BEGINN + timedelta(days=h)) for h in HS},
                         "zwischenauswertung": str(ZWISCHEN),
                         "endgueltig_ab_basg_stand": str(FENSTER[1] + timedelta(days=H))}}
    if not rechenbar:
        info["status"] = f"noch nicht auswertbar: kein Montag ab {ab} mit Protokoll bis zum BASG-Stand {lat}"
        conn.close()
        return info
    alt = pd.read_parquet(WERTE) if WERTE.exists() and not probe else pd.DataFrame()
    fertig = set(pd.to_datetime(alt["t"]).dt.date) if len(alt) else set()
    neu = [d for d in rechenbar if d not in fertig]
    info["neu_gerechnet"] = [str(d) for d in neu]
    if neu:
        Wn, D, U = rechne(stand, neu, fest)
        Wn["stand_gerechnet"], Wn["fest_sha256"] = stand, fsha
        Wn["gerechnet_am"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if probe:
            info["probe"] = _probe_pruefen(D, U, Wn, fest)
        else:
            alt = pd.concat([alt, Wn], ignore_index=True) if len(alt) else Wn
            WORK.mkdir(parents=True, exist_ok=True)
            alt.to_parquet(WERTE, index=False)
        W = Wn if probe else alt
    else:
        W = alt
    W = W.assign(t=pd.to_datetime(W["t"]).astype("datetime64[ns]"))
    F, quelle = rahmen(logs, rechenbar, W)
    F, latest = ziele(conn, F)
    conn.close()
    L = listen(F)
    WORK.mkdir(parents=True, exist_ok=True)
    pd.concat([x.assign(teil=n) for n, x in L.items()], ignore_index=True).to_parquet(
        WORK / ("listen_probe.parquet" if probe else "listen.parquet"), index=False)
    info["E_S3z_C_quelle"] = quelle
    info["montage"] = _zusammenfassung(L, F)
    info["ergebnis"] = auswerten(L, latest)
    info["status"] = info["ergebnis"]["haupt_z3_v0_56"]["fenster"]["status"] if not probe else \
        "Probe: " + ("noch nicht auswertbar" if F[["y28", "y56", "y84"]].notna().sum().sum() == 0 else "Ziele teilweise bekannt")
    return info


def _probe_pruefen(D: pd.DataFrame, U: pd.DataFrame, Wn: pd.DataFrame, fest: dict) -> dict:
    """s27-Abgleich (Merkmale gegen das s25-Panel, E gegen die s23-Spätprüfung) und q gegen den s27-Weg (W-Zeilen)."""
    Vw, Vi = zv.vorhersagen(D, U, fest)
    V = pd.concat([Vw.assign(ebene="W"), Vi.assign(ebene="I")], ignore_index=True)
    out = zv.probe_pruefen(D, U, V, fest)
    m = Wn.merge(Vw[["h", "t", "atc5", "q"]].rename(columns={"q": "q_s27"}), on=["h", "t", "atc5"], how="inner")
    ok = m["q"].notna() & m["q_s27"].notna()
    out["q_gegen_s27_weg"] = {"zeilen": int(ok.sum()), "max_abs_diff": float(np.max(np.abs(m.loc[ok, "q"] - m.loc[ok, "q_s27"])))
                              if ok.any() else None,
                              "q_nur_hier": int((m["q"].notna() & m["q_s27"].isna()).sum())}
    return out


# --- Testmodus: Rückblick 2024–2026 ------------------------------------------------------------------------------------

REFERENZ_56 = {"2024": (0.215, 0.104), "2025": (0.224, 0.099), "2026": (0.278, 0.173)}   # Nachrechnung 16.11.2026


def test() -> dict:
    """Rechenweg der Auswertung auf den Rückblickvorhersagen: z3_v0 äußer (s23 mp1), q_I und E_S3z_C aus s25/s27."""
    Wb = zs.w_basis()
    z = pd.read_parquet(Z3_RUECK)[["jahr", "h", "t", "atc5", "p"]].rename(columns={"p": "pz3"})
    z["t"] = pd.to_datetime(z["t"]).astype("datetime64[ns]")
    z[["jahr", "h"]] = z[["jahr", "h"]].astype(np.int16)
    M = Wb.merge(z, on=["jahr", "h", "t", "atc5"], how="inner", validate="one_to_one")
    out = {"hinweis": "Rückblick (Testjahre schon gesehen); prüft nur den Rechenweg, zählt nicht",
           "zeilen": {"w_basis": int(len(Wb)), "z3_v0": int(len(z)), "verbunden": int(len(M))}, "teile": {}}
    for h in HS:
        g = M[M["h"] == h]
        for modell, col in (("z3_v0", "pz3"), ("E_S3z_C", "pe")):
            T = markiere(g, col, "q_I")[lambda x: x["top"]]
            r = {str(Y): endpunkt(T[T["jahr"] == Y], "y", col) for Y in zs.JAHRE}
            r["alle"] = endpunkt(T, "y", col)
            out["teile"][f"{modell}_{h}"] = r
    # Gleichstand: ATC5 aufsteigend (Regel) gegen rank(method="first") der Nachrechnung vom 16.11.
    g = M[M["h"] == H]
    A = markiere(g, "pz3", "q_I")
    rz = g.groupby("t")["pz3"].rank(method="first", ascending=False)
    rq = g.groupby("t")["q_I"].rank(method="first", ascending=False)
    top_f, best_f = rz <= K, (rz <= K) & (rq <= K)
    out["gleichstand"] = {"liste_anders": int((A["top"] != top_f).sum()), "bestaetigt_anders": int((A["bestaetigt"] != best_f).sum())}
    v = {}
    for Y, (qb, qn) in REFERENZ_56.items():
        e = out["teile"]["z3_v0_56"][Y]
        v[Y] = {"soll": [qb, qn], "ist": [round(e["bestaetigt"]["quote"], 4), round(e["nicht_bestaetigt"]["quote"], 4)],
                "je_montag": [e["bestaetigt"]["je_montag"], e["nicht_bestaetigt"]["je_montag"]],
                "gleich_auf_0_1_pp": bool(abs(e["bestaetigt"]["quote"] - qb) < 5e-4 and abs(e["nicht_bestaetigt"]["quote"] - qn) < 5e-4)}
    out["reproduktion_56"] = v
    out["reproduziert"] = all(x["gleich_auf_0_1_pp"] for x in v.values())
    # Ziele über stockout_at (wie stockout bewertung, Datenbank Stand heute) gegen die Panelziele des Rückblicks
    from msuche import sicht
    zv.stand_einrichten(None)
    conn = sicht.connect(_stand_db("heute"))
    abg, mit = {}, {}
    for h in HS:
        g = M[M["h"] == h]
        Fz, lat = ziele(conn, g[["jahr", "t", "atc5", "y", "pz3", "q_I"]])
        for Y, x in Fz.groupby("jahr"):
            a, b = x["y"].to_numpy(), x[f"y{h}"].to_numpy()
            abg[f"{h}_{Y}"] = {"faelle": int(len(x)), "gleich": float(np.mean(a == b)), "treffer_panel": int(a.sum()),
                               "treffer_bewertung": int(np.nansum(b)), "nur_panel": int(((a == 1) & (b == 0)).sum()),
                               "nur_bewertung": int(((a == 0) & (b == 1)).sum())}
        if h == H:
            T = markiere(Fz, "pz3", "q_I")[lambda x: x["top"]]
            mit = {str(Y): endpunkt(T[T["jahr"] == Y], f"y{h}", "pz3") for Y in zs.JAHRE}
    conn.close()
    out["ziele_bewertung_gegen_panel"] = {"basg_stand": str(lat), "je_horizont_jahr": abg,
                                          "hinweis": "Panelziele (s23) nutzen die geschätzte Veröffentlichung in den Lücken "
                                                     "vor dem 17.10.2026; stockout bewertung nur Beginn und erstes Sehen"}
    out["teile"]["z3_v0_56_ziel_bewertung"] = mit
    return out


# --- Ausgabe -----------------------------------------------------------------------------------------------------------

def _drucke(info: dict) -> None:
    print(json.dumps({k: v for k, v in info.items() if k not in ("ergebnis", "montage", "teile", "probe")},
                     ensure_ascii=False, indent=1, default=str)[:4000])
    if "montage" in info:
        for d, m in info["montage"].items():
            print(f"  {d}: Protokoll {m['protokoll']}, mit q {m['mit_q56']}, Liste {m['liste']}, bestätigt {m['bestaetigt']}, "
                  f"Ziel 56 T. bekannt {m['ziel_bekannt_56']}")
    for n, r in info.get("ergebnis", {}).items():
        e = r["fenster"]
        if not e.get("faelle"):
            print(f"  {n}: noch nicht auswertbar")
            continue
        b, nb = e["bestaetigt"], e["nicht_bestaetigt"]
        ki = e.get("bootstrap", {}).get("ki95", [np.nan, np.nan])
        print(f"  {n}: {e['montage']} Montage, bestätigt {b['quote']:.3f} ({b['faelle']}), nicht {nb['quote']:.3f} "
              f"({nb['faelle']}), Differenz {e['differenz']:+.3f} [{ki[0]:+.3f}; {ki[1]:+.3f}]")
    if "status" in info:
        print(info["status"])


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bis", help="Stand (ISO, UTC) wie bei msuche.spaetpruefung, z. B. 2027-03-01T23:59:59Z; "
                                 "'heute' = Stand der Modellsuche (Datenbank 16.11.2026)")
    g.add_argument("--probe", action="store_true", help="Montage ab 26.10.2026 auf dem Stand heute (zählt nicht)")
    g.add_argument("--test", action="store_true", help="Rechenweg auf den Rückblickvorhersagen 2024–2026 (zählt nicht)")
    g.add_argument("--einfrieren", action="store_true", help="zusatzpruefplan.json einmal schreiben (vor 01.01.2027)")
    a = ap.parse_args()
    if a.einfrieren:
        einfrieren()
        return
    beginn = datetime.now().astimezone()
    plan = plan_pruefen(pflicht=not (a.probe or a.test))
    pfade.nice()
    lauf_info = {"zusatzpruefplan": plan, "lauf": {"beginn": beginn.isoformat(timespec="seconds"),
                                                   "fenster": pfade.check_window()}}
    if a.test:
        info = {**lauf_info, **test()}
        ziel = TEST
    else:
        info = lauf(a.probe, a.bis, lauf_info)
        ziel = PROBE if a.probe else ERGEBNIS
    info["lauf"]["ende"] = datetime.now().astimezone().isoformat(timespec="seconds")
    zs._json(ziel, info)
    if a.test:
        print(json.dumps({"reproduziert": info["reproduziert"], "reproduktion_56": info["reproduktion_56"],
                          "gleichstand": info["gleichstand"]}, ensure_ascii=False, indent=1))
        for n, r in info["teile"].items():
            for Y, e in r.items():
                ki = e.get("bootstrap", {}).get("ki95", [np.nan, np.nan])
                print(f"  {n} {Y}: bestätigt {e['bestaetigt']['quote']:.3f} ({e['bestaetigt']['je_montag']}/Wo.), nicht "
                      f"{e['nicht_bestaetigt']['quote']:.3f} ({e['nicht_bestaetigt']['je_montag']}/Wo.), Differenz "
                      f"{e['differenz']:+.3f} [{ki[0]:+.3f}; {ki[1]:+.3f}], eingetroffen/angesagt "
                      f"{e['bestaetigt']['eingetroffen_zu_angesagt']:.2f} / {e['nicht_bestaetigt']['eingetroffen_zu_angesagt']:.2f}")
    else:
        _drucke(info)
    print(f"→ {ziel}")


if __name__ == "__main__":
    main()
