"""Z3: probability that a substance gets a new BASG report within 4, 8 or 12 weeks, from what was known that day.

Unit is the substance (ATC5) on a reference day: marketed ("lieferbar") in the ASP version before that day and
without an active Austrian report. All features are binary and computed from data dated before the reference day:
foreign reports (number of countries, same Austrian holder abroad, a new report in the last four weeks), Austrian
history (earlier shortage, one in the last year, one that ended in the last 90 days), number of marketed products,
a change of the holder entry, a market exit and an EKO deletion of another product in the last eight weeks, ATC
main group and quarter.

Several methods are frozen side by side and scored on the same cases (`METHODS`): the ridge logistic regression
z3_v0, the same model without foreign reports (does the foreign data add anything?), the same model with BfArM
reports (private only: what the consent would be worth), the tier rule as a probability (hit rate per tier) and
the average of z3_v0, z3_v0_mit_de and the tier rule. Each is learned on 2024–2025 and checked on 2026 (`measure`);
the frozen files keep the tested parameters and parameters refitted on all labelled days, which make the daily
predictions. `models/pruefplan.json` fixes the methods (by sha256), the main comparison and the measures before
the prospective check starts on 2027-01-01. The daily prediction log (`<archive>/protokoll/vorhersagen/`) holds
every method's prediction per substance, and `bewerten` scores it once the horizons have passed. Nothing of this
is shown on the website.

Learning and the retrospective run can be made point in time (`zeitpunktgenau`, off by default = as frozen): a BASG
report counts only from its publication (`published`) in the case selection, the history and the outcome ("begins or
first appears", as in the plan), and the ASP version only from the day it was captured. The daily run needs neither:
on the day itself the database knows only published reports and captured versions.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import io
import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from . import rueckblick, vorlauf
from .archive import Archive
from .schaerfe import _bootstrap, _solve, auc, top_rate
from .vorlauf import HORIZONS, Intervals, _d, _wilson

MODELS = Path(__file__).resolve().parents[2] / "models"
PLAN = MODELS / "pruefplan.json"
VERSION = "z3_v0"  # the main model; its predictions also go into the feature log
LOG_DIR = Path("protokoll") / "vorhersagen"
PROSPECTIVE_START = date(2027, 1, 1)
STEP = 14
START = date(2024, 1, 1)
LEARN_END = date(2025, 12, 31)
TEST_START = date(2026, 1, 1)
RECENT = 56
LAMBDAS = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
TOP_K = (25, 50, 100)
LEAD_K = 50
ATC_GROUPS = "ABCDGHJLMNPRSV"
FOREIGN = ["laender_1", "laender_2", "laender_3_4", "laender_5plus", "inhaber_1plus", "inhaber_3plus", "ausland_neu_28"]
FEATURES = (
    FOREIGN + ["frueher_engpass", "engpass_365", "ende_90", "groesse_1", "groesse_2_3", "groesse_10plus",
               "inhaberwechsel_56", "marktaustritt_56", "eko_56"]
    + [f"atc_{g}" for g in ATC_GROUPS] + [f"quartal_{q}" for q in range(1, 5)]
)
INDEX = {f: i + 1 for i, f in enumerate(FEATURES)}  # 0 = intercept
METHODS = {  # members of an average come before it
    "z3_v0": {"art": "logit", "ohne_quellen": ["bfarm"], "merkmale": FEATURES, "rolle": "Hauptmodell"},
    "z3_v0_ohne_ausland": {"art": "logit", "ohne_quellen": ["bfarm"], "merkmale": [f for f in FEATURES if f not in FOREIGN],
                           "rolle": "Diagnose: dasselbe Modell ohne Auslandsmeldungen"},
    "z3_v0_mit_de": {"art": "logit", "ohne_quellen": [], "merkmale": FEATURES,
                     "rolle": "Herausforderer mit BfArM-Meldungen, nur intern"},
    "stufen_v0": {"art": "stufen", "ohne_quellen": ["bfarm"], "rolle": "Vergleich: Stufenregel der Frühwarnliste als Quote je Stufe"},
    "mittel_v0": {"art": "mittel", "aus": ["z3_v0", "z3_v0_mit_de", "stufen_v0"], "rolle": "Herausforderer: Mittel der Wahrscheinlichkeiten"},
}
MAIN = {"modell": "z3_v0", "gegen": "stufen_v0", "horizont": 56, "k": 50}
VARIANTS = sorted({frozenset(m["ohne_quellen"]) for m in METHODS.values() if "ohne_quellen" in m}, key=sorted)


def published(s: date, fs: date, dm: date | None, complete: list[date]) -> date:
    """Publication day of a BASG report: min(first sighting, max(start, Datum_Meldung + 1)), but never before the day
    after the last complete snapshot before the first sighting (it was missing there). In the daily archive this is
    the first sighting. Same rule as in the model search (November 2026)."""
    pub = min(fs, max(s, dm + timedelta(days=1) if dm else s))
    i = bisect.bisect_left(complete, fs) - 1
    return max(pub, complete[i] + timedelta(days=1)) if i >= 0 else pub


def _published_reports(conn: sqlite3.Connection, latest: date) -> dict[str, list[tuple[date, date, date]]]:
    """ATC5 -> (start, publication, end) of every Austrian report, ends as in `rueckblick._episode_rows`."""
    complete = [_d(d) for d, in conn.execute("SELECT snapshot_date FROM snapshots WHERE complete = 1 ORDER BY snapshot_date")]
    out: dict[str, list[tuple[date, date, date]]] = defaultdict(list)
    for atc5, s, fs, dm, end_upper, active in conn.execute(
            "SELECT e.atc5, e.start_date, e.first_seen, substr(sp.Datum_Meldung, 1, 10), e.end_upper, e.active "
            "FROM episodes e JOIN snapshot_packages sp ON sp.snapshot_id = e.first_snapshot "
            "AND sp.package_key = e.package_key WHERE e.atc5 IS NOT NULL"):
        s = _d(s)
        e = latest if active or not end_upper else _d(end_upper)
        if s and e and s <= latest:
            out[atc5].append((s, published(s, _d(fs), _d(dm), complete), max(e, s)))
    return dict(out)


class Knowledge:
    """Everything needed to compute features on any day; each lookup only uses entries dated before that day.
    With `zeitpunktgenau`, BASG reports count from their publication and ASP versions from their capture."""

    pit: dict[str, list[tuple[date, date, date]]] | None = None  # with the switch: (start, publication, end) per ATC5
    _known: tuple | None = None

    def __init__(self, conn: sqlite3.Connection, archive: Archive, zeitpunktgenau: bool = False):
        latest = _d(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
        self.latest = latest
        eps = rueckblick._episode_rows(conn, latest)
        self.subst = Intervals([(e["atc5"], e["start"], e["end"]) for e in eps])
        self.pit = _published_reports(conn, latest) if zeitpunktgenau else None
        self.hist = rueckblick.AspHistory.load(archive)
        self.items: dict[str, list[dict]] = defaultdict(list)
        for source, its in vorlauf._signals(conn, latest).items():
            for it in its:
                self.items[it["atc5"]].append({**it, "source": source})
        self.events: dict[str, dict[str, list[date]]] = defaultdict(lambda: defaultdict(list))
        verl = rueckblick._latest(archive, "mia_verl")
        for e in rueckblick.mia_events(verl, self.hist.atc) if verl else []:
            if e["kind"] == "inhaberwechsel":
                self.events["inhaberwechsel"][e["atc5"]].append(e["date"])
        for e in rueckblick.asp_exits(self.hist, eps):
            if not e["own"]:
                self.events["marktaustritt"][e["atc5"]].append(e["date"])
        names = [(zl, (atc or "")[:7], name) for zl, atc, name in conn.execute(
            "SELECT DISTINCT zulassungsnummer, atc, approval_name FROM asp_packages WHERE approval_name != ''")]
        for e in rueckblick.eko_events(archive, names):
            self.events["eko"][e["atc5"]].append(e["date"])
        for by_atc in self.events.values():
            for ds in by_atc.values():
                ds.sort()
        self._version: tuple[date, dict] | None = None

    def marketed(self, t: date) -> dict[str, dict]:
        """Substances marketed in the ASP version before t: number of marketed products and holder keys."""
        if self._version and self._version[0] == t:
            return self._version[1]
        prods = (self.hist.before(t) if self.pit is None else self.hist.known_before(t)) or {}
        out: dict[str, dict] = {}
        for zl, (m, a, h) in prods.items():
            if m and a:
                s = out.setdefault(a, {"n": 0, "holders": set()})
                s["n"] += 1
                if h:
                    s["holders"].add(h)
        self._version = (t, out)
        return out

    def _recent(self, kind: str, a: str, t: date, days: int = RECENT) -> bool:
        ds = self.events[kind].get(a, [])
        i = bisect.bisect_left(ds, t)  # strictly before t
        return i > 0 and ds[i - 1] >= t - timedelta(days=days)

    def _basg(self, a: str, t: date) -> tuple[bool, list[tuple[date, date]]]:
        """Is a report on a active on day t, and the merged report intervals of a (with the switch: known on day t)."""
        if self.pit is None:
            return self.subst.active(a, t), self.subst.intervals.get(a, [])
        if self._known and self._known[0] == (a, t):
            return self._known[1]
        known = [(s, e) for s, p, e in self.pit.get(a, []) if p <= t]
        out = any(s <= t <= e for s, e in known), Intervals([(a, s, e) for s, e in known]).intervals.get(a, [])
        self._known = ((a, t), out)
        return out

    def onset_within(self, a: str, t: date, h: int) -> bool:
        """Outcome: start of a merged report interval in (t, t+h]; with the switch as in the plan: a report begins or
        first appears in (t, t+h]."""
        if self.pit is None:
            return self.subst.onset_within(a, t, h)
        end = t + timedelta(days=h)
        return any(t < s <= end or t < p <= end for s, p, _ in self.pit.get(a, []))

    def _active(self, a: str, t: date, hidden: frozenset) -> list[dict]:
        return [it for it in self.items.get(a, []) if it["date"] < t <= it["until"] and it["source"] not in hidden]

    def features(self, a: str, t: date, at: dict, hidden: frozenset = frozenset()) -> list[str] | None:
        """Names of the features that are 1 for substance a on day t, None outside the universe."""
        reported, ivs = self._basg(a, t)
        if reported:
            return None
        act = self._active(a, t, hidden)
        countries = {it["country"] for it in act}
        n = len(countries)
        f = []
        if n:
            f.append("laender_1" if n == 1 else "laender_2" if n == 2 else "laender_3_4" if n <= 4 else "laender_5plus")
            same: dict[str, set] = defaultdict(set)
            for it in act:
                if it["holder"] and it["holder"] in at["holders"]:
                    same[it["holder"]].add(it["country"])
            best = max((len(cs) for cs in same.values()), default=0)
            f += ["inhaber_1plus"] * (best >= 1) + ["inhaber_3plus"] * (best >= 3)
            f += ["ausland_neu_28"] * any(it["date"] >= t - timedelta(days=28) for it in act)
        if any(s < t for s, _ in ivs):
            f.append("frueher_engpass")
            f += ["engpass_365"] * any(t - timedelta(days=365) <= s < t for s, _ in ivs)
            f += ["ende_90"] * any(t - timedelta(days=90) <= e < t for _, e in ivs)
        size = at["n"]
        f += ["groesse_1"] * (size == 1) + ["groesse_2_3"] * (2 <= size <= 3) + ["groesse_10plus"] * (size >= 10)
        f += ["inhaberwechsel_56"] * self._recent("inhaberwechsel", a, t)
        f += ["marktaustritt_56"] * self._recent("marktaustritt", a, t)
        f += ["eko_56"] * self._recent("eko", a, t)
        if a[0] in ATC_GROUPS:
            f.append(f"atc_{a[0]}")
        f.append(f"quartal_{(t.month - 1) // 3 + 1}")
        return f

    def tier(self, a: str, t: date, hidden: frozenset) -> str:
        n = len({it["country"] for it in self._active(a, t, hidden)})
        return vorlauf.tier(n) if n else "-"

    def case(self, a: str, t: date, at: dict) -> dict | None:
        """Features and tier of substance a on day t for every source variant; None outside the universe."""
        out = {"x": {}, "stufe": {}}
        for v in VARIANTS:
            f = self.features(a, t, at, v)
            if f is None:
                return None
            out["x"][v] = tuple(sorted(INDEX[n] for n in f))
            out["stufe"][v] = self.tier(a, t, v)
        return out


def table(k: Knowledge, start: date, end: date, step: int = STEP) -> list[dict]:
    """Cases per reference day t in [start, end] and substance in the universe, with outcomes where observable."""
    rows = []
    t = start
    while t <= end:
        for a, at in sorted(k.marketed(t).items()):
            c = k.case(a, t, at)
            if c is not None:
                rows.append({"t": t, "atc5": a, **c,
                             "y": {h: k.onset_within(a, t, h) for h in HORIZONS if t + timedelta(days=h) <= k.latest}})
        t += timedelta(days=step)
    return rows


# --- fitting --------------------------------------------------------------------------------------

def fit(rows: list[dict], h: int, l2: float, iters: int = 50) -> list[float]:
    """Ridge logistic regression (intercept unpenalised) on rows {"x": feature indices, "y": {h: outcome}};
    identical feature vectors are grouped, so the fit is fast in plain Python."""
    groups: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if h in r["y"]:
            g = groups[r["x"]]
            g[0] += 1
            g[1] += r["y"][h]
    k = len(FEATURES) + 1
    w = [0.0] * k
    for _ in range(iters):
        grad = [-l2 * w[i] if i else 0.0 for i in range(k)]
        hess = [[(l2 if i == j and i else 0.0) for j in range(k)] for i in range(k)]
        for x, (n, y) in groups.items():
            idx = (0, *x)
            p = 1 / (1 + math.exp(-sum(w[i] for i in idx)))
            for i in idx:
                grad[i] += y - n * p
                for j in idx:
                    hess[i][j] += n * p * (1 - p)
        step = _solve(hess, grad)
        w = [a + b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return w


def prob(w: list[float], x: tuple) -> float:
    return 1 / (1 + math.exp(-(w[0] + sum(w[i] for i in x))))


def _logloss(ps: list[float], ys: list[int]) -> float:
    eps = 1e-6
    return -sum(math.log(max(p, eps) if y else max(1 - p, eps)) for p, y in zip(ps, ys)) / len(ys)


def choose_l2(rows: list[dict], h: int) -> dict:
    """Ridge strength by an inner time split of the learning period: fit 2024, validate 2025."""
    inner_end = date(2024, 12, 31)
    train = [r for r in rows if r["t"] + timedelta(days=h) <= inner_end]
    val = [r for r in rows if r["t"] > inner_end and h in r["y"] and r["t"] + timedelta(days=h) <= LEARN_END]
    ys = [int(r["y"][h]) for r in val]
    losses = {}
    for l2 in LAMBDAS:
        w = fit(train, h, l2)
        losses[l2] = round(_logloss([prob(w, r["x"]) for r in val], ys), 5)
    return {"l2": min(losses, key=losses.get), "logloss_validierung": losses}


def _weights(w: list[float], names: list[str]) -> dict:
    return {"achsenabschnitt": round(w[0], 4), **{f: round(w[INDEX[f]], 4) for f in names}}


def _rates(rows: list[dict], h: int, v: frozenset) -> dict:
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if h in r["y"]:
            for key in (r["stufe"][v], "grundrate"):
                tally[key][0] += r["y"][h]
                tally[key][1] += 1
    return {key: round(hit / n, 5) for key, (hit, n) in sorted(tally.items())}


def learn_methods(rows: list[dict]) -> dict[str, dict]:
    """Parameters per method and horizon: tested (learned 2024–2025) and final (all labelled reference days)."""
    out = {}
    for name, spec in METHODS.items():
        m = {"art": spec["art"], "rolle": spec["rolle"], "horizonte": {}}
        if spec["art"] == "mittel":
            m["aus"] = spec["aus"]
        else:
            m["ohne_quellen"] = spec["ohne_quellen"]
            v = frozenset(spec["ohne_quellen"])
        if spec["art"] == "logit":
            m["merkmale"] = spec["merkmale"]
            keep = {INDEX[f] for f in spec["merkmale"]}
            mrows = [{"t": r["t"], "x": tuple(i for i in r["x"][v] if i in keep), "y": r["y"]} for r in rows]
        for h in HORIZONS:
            learn = [r for r in (mrows if spec["art"] == "logit" else rows) if r["t"] + timedelta(days=h) <= LEARN_END]
            labelled = [r for r in (mrows if spec["art"] == "logit" else rows) if h in r["y"]]
            if spec["art"] == "logit":
                choice = choose_l2(mrows, h)
                m["horizonte"][str(h)] = {
                    "wahl_l2": choice, "lernfaelle": sum(h in r["y"] for r in learn), "faelle_gesamt": len(labelled),
                    "gewichte_geprueft": _weights(fit(learn, h, choice["l2"]), spec["merkmale"]),
                    "gewichte": _weights(fit(labelled, h, choice["l2"]), spec["merkmale"])}
            elif spec["art"] == "stufen":
                m["horizonte"][str(h)] = {"quoten_geprueft": _rates(learn, h, v), "quoten": _rates(labelled, h, v)}
            else:
                m["horizonte"][str(h)] = {}
        out[name] = m
    return out


def predict_case(methods: dict[str, dict], c: dict, h: int, tested: bool = False) -> dict[str, float]:
    """Probability of every method for one case at horizon h (tested or final parameters)."""
    out: dict[str, float] = {}
    for name, m in methods.items():
        block = m["horizonte"][str(h)]
        if m["art"] == "logit":
            w = block["gewichte_geprueft" if tested else "gewichte"]
            x = c["x"][frozenset(m["ohne_quellen"])]
            out[name] = 1 / (1 + math.exp(-(w["achsenabschnitt"] + sum(w.get(FEATURES[i - 1], 0.0) for i in x))))
        elif m["art"] == "stufen":
            q = block["quoten_geprueft" if tested else "quoten"]
            out[name] = q.get(c["stufe"][frozenset(m["ohne_quellen"])], q["grundrate"])
        else:
            out[name] = sum(out[x] for x in m["aus"]) / len(m["aus"])
    return out


# --- scoring --------------------------------------------------------------------------------------

def average_precision(ps: list[float], ys: list[int]) -> float | None:
    """Area under the precision-recall curve with thresholds at the distinct scores (ties stay together)."""
    pos = sum(ys)
    if not pos:
        return None
    by_score: dict[float, list[int]] = defaultdict(lambda: [0, 0])
    for p, y in zip(ps, ys):
        by_score[p][0] += y
        by_score[p][1] += 1
    tp = n = 0
    ap = 0.0
    for p in sorted(by_score, reverse=True):
        hits, cnt = by_score[p]
        tp += hits
        n += cnt
        ap += hits / pos * tp / n
    return ap


def _recalibration(ps: list[float], ys: list[int], slope: bool) -> float | None:
    """Calibration intercept (slope fixed at 1) or slope: logistic regression of the outcome on logit(p)."""
    zs = [math.log(min(max(p, 1e-6), 1 - 1e-6) / (1 - min(max(p, 1e-6), 1 - 1e-6))) for p in ps]
    a, b = 0.0, 1.0
    for _ in range(30):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for z, y in zip(zs, ys):
            q = 1 / (1 + math.exp(-(a + b * z)))
            r, v = y - q, q * (1 - q)
            g0 += r
            g1 += r * z
            h00 += v
            h01 += v * z
            h11 += v * z * z
        if slope:
            det = h00 * h11 - h01 * h01
            if det <= 1e-12:
                return None
            da, db = (h11 * g0 - h01 * g1) / det, (h00 * g1 - h01 * g0) / det
        else:
            if h00 <= 1e-12:
                return None
            da, db = g0 / h00, 0.0
        a, b = a + da, b + db
        if abs(da) + abs(db) < 1e-9:
            break
    else:
        return None  # no convergence (e.g. perfectly separated small samples)
    return round(b if slope else a, 3)


def _calibration(ps: list[float], ys: list[int], bins: int = 10) -> list[dict]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    out = []
    for b in range(bins):
        idx = order[b * len(order) // bins:(b + 1) * len(order) // bins]
        if idx:
            out.append({"vorhergesagt": round(sum(ps[i] for i in idx) / len(idx), 4),
                        "beobachtet": round(sum(ys[i] for i in idx) / len(idx), 4), "faelle": len(idx)})
    return out


def _top(cases: list[dict], scores: list[float], k: int) -> tuple[float, float, float]:
    """Per reference day the k highest scores (ties at the cut-off count with their average):
    (hits, picked, all onsets of those days)."""
    by_day: dict[date, list[int]] = defaultdict(list)
    for i, c in enumerate(cases):
        by_day[c["t"]].append(i)
    hits = picked = total = 0.0
    for idx in by_day.values():
        ys = [cases[i]["y"] for i in idx]
        kk = min(k, len(idx))
        hits += top_rate([scores[i] for i in idx], ys, kk) * kk
        picked += kk
        total += sum(ys)
    return hits, picked, total


def _brier(sample: list[dict], name: str) -> float:
    return sum((c["p"][name] - c["y"]) ** 2 for c in sample) / len(sample)


def _top_quote(sample: list[dict], name: str, k: int) -> float:
    hits, picked, _ = _top(sample, [c["p"][name] for c in sample], k)
    return hits / picked


def score(cases: list[dict], intervals: bool = False) -> dict:
    """All measures for every method on the same cases {"t", "atc5", "y": 0/1, "p": {method: probability}}.
    With `intervals`: the main comparison with 95 % intervals over substances and the set of best methods."""
    ys = [c["y"] for c in cases]
    names = list(cases[0]["p"])
    ref = _brier(cases, MAIN["gegen"]) if MAIN["gegen"] in names else None
    out = {"faelle": len(cases), "stichtage": len({c["t"] for c in cases}), "meldungen": sum(ys),
           "quote": round(sum(ys) / len(cases), 4), "verfahren": {}}
    for name in names:
        ps = [c["p"][name] for c in cases]
        brier = _brier(cases, name)
        a = auc(ps, ys)
        ap = average_precision(ps, ys)
        tops = {}
        for k in TOP_K:
            hits, picked, total = _top(cases, ps, k)
            tops[str(k)] = {"quote": round(hits / picked, 4), "anteil_aller_meldungen": round(hits / total, 4) if total else None}
        out["verfahren"][name] = {
            "brier": round(brier, 5), "brier_skill_gegen_stufen": round(1 - brier / ref, 4) if ref else None,
            "logloss": round(_logloss(ps, ys), 5), "auc": round(a, 3) if a is not None else None,
            "average_precision": round(ap, 4) if ap is not None else None,
            "mittel_vorhergesagt": round(sum(ps) / len(ps), 4),
            "kalibrierung_achsenabschnitt": _recalibration(ps, ys, slope=False),
            "kalibrierung_steigung": _recalibration(ps, ys, slope=True),
            "kalibrierung": _calibration(ps, ys), "spitze": tops,
        }
    if intervals and MAIN["modell"] in names and MAIN["gegen"] in names:
        m, s, k = MAIN["modell"], MAIN["gegen"], MAIN["k"]
        v, r = out["verfahren"][m], out["verfahren"][s]

        def d_auc(sample: list[dict]) -> float | None:
            yb = [c["y"] for c in sample]
            x, y = auc([c["p"][m] for c in sample], yb), auc([c["p"][s] for c in sample], yb)
            return None if x is None or y is None else x - y

        gain = r["brier"] - v["brier"]
        top_diff = v["spitze"][str(k)]["quote"] - r["spitze"][str(k)]["quote"]
        out["hauptvergleich"] = {
            "modell": m, "gegen": s, "brier_gewinn": round(gain, 5),
            "brier_gewinn_ki95": _bootstrap(cases, lambda x: _brier(x, s) - _brier(x, m), digits=5),
            f"top{k}_differenz": round(top_diff, 4),
            f"top{k}_differenz_ki95": _bootstrap(cases, lambda x: _top_quote(x, m, k) - _top_quote(x, s, k)),
            "auc_differenz": round(v["auc"] - r["auc"], 3), "auc_ki95": _bootstrap(cases, d_auc),
            "bestanden": gain > 0 and top_diff > 0,
        }
        best = min(names, key=lambda n: out["verfahren"][n]["brier"])
        out["beste_menge"] = {"bestes": best, "abstand_ki95": {}}
        for n in names:
            if n != best:
                out["beste_menge"]["abstand_ki95"][n] = _bootstrap(cases, lambda x, n=n: _brier(x, n) - _brier(x, best), digits=5)
        out["beste_menge"]["menge"] = [best] + [n for n, ci in out["beste_menge"]["abstand_ki95"].items() if ci and ci[0] <= 0]
    return out


def lead_and_churn(logs: dict[date, dict[str, dict]], reports: dict[str, list[date]], h: int = 56, k: int = LEAD_K) -> dict:
    """From daily logs (day -> ATC5 -> {"p": {h: {method: p}}}), per method and its daily top k (ties in a fixed
    order per substance): for each new report on day D whose substance was in the logged universe in the h days
    before, was it on the list on the last logged day before D, for how many days in a row, and was it on the list
    on any day of those h days. Also the share of the top k that changes from one day to the next."""
    days = sorted(logs)
    if not days:
        return {}
    pos = {d: i for i, d in enumerate(days)}
    names = list(next(iter(next(iter(logs.values())).values()))["p"][h])
    order = {a: hashlib.md5(a.encode()).hexdigest() for d in days for a in logs[d]}
    tops: dict[str, dict[date, set]] = {n: {} for n in names}
    for d in days:
        rows = logs[d]
        for n in names:
            tops[n][d] = set(sorted(rows, key=lambda a: (-rows[a]["p"][h][n], order[a]))[:k])
    out = {}
    for n in names:
        churn = [len(tops[n][d1] - tops[n][d0]) / k for d0, d1 in zip(days, days[1:]) if (d1 - d0).days == 1]
        counted = ever = 0
        runs = []
        for a, ds in reports.items():
            for rd in ds:
                lo, hi = bisect.bisect_left(days, rd - timedelta(days=h)), bisect.bisect_left(days, rd)
                window = [d for d in days[lo:hi] if a in logs[d]]
                if rd - timedelta(days=h) < days[0] or not window:
                    continue
                counted += 1
                ever += any(a in tops[n][d] for d in window)
                last = window[-1]
                if a in tops[n][last]:
                    i = pos[last]
                    while i > 0 and (days[i] - days[i - 1]).days == 1 and a in tops[n][days[i - 1]]:
                        i -= 1
                    runs.append((rd - days[i]).days)
        runs.sort()
        out[n] = {"meldungen": counted,
                  "auf_der_liste": round(len(runs) / counted, 3) if counted else None,
                  "auf_der_liste_ki95": _wilson(len(runs), counted),
                  "seit_tagen_median": runs[len(runs) // 2] if runs else None,
                  "mind_7_tage": round(sum(x >= 7 for x in runs) / counted, 3) if counted else None,
                  "irgendwann_in_8_wochen": round(ever / counted, 3) if counted else None,
                  "wechsel_je_tag": round(sum(churn) / len(churn), 3) if churn else None}
    return out


# --- frozen versions, plan and daily log ----------------------------------------------------------

PLAN_RULES = {
    "beginn": PROSPECTIVE_START.isoformat(),
    "stichtage": "alle 14 Tage ab Beginn; je Stichtag alle Wirkstoffe des Vorhersageprotokolls dieses Tages",
    "ergebnis": "neue BASG-Meldung zum Wirkstoff: eine Meldung beginnt oder erscheint erstmals binnen 28, 56 bzw. 84 Tagen "
                "nach dem Stichtag; ein Horizont zählt erst, wenn er im BASG-Stand abgelaufen ist",
    "hauptvergleich": {**MAIN, "bestanden": "Brier-Score niedriger und Trefferquote der 50 höchsten Wirkstoffe je Stichtag "
                                            "höher als bei stufen_v0 (Punktschätzer, 8 Wochen); 95-%-Intervalle über Wirkstoffe "
                                            "werden berichtet"},
    "nebenkennzahlen": ["Log-Loss", "Kalibrierung in Zehnteln, Achsenabschnitt und Steigung", "AUC", "Average Precision",
                        "Top 25/50/100 je Stichtag: Quote und Anteil aller Meldungen",
                        "Vorlauf: Anteil der neuen Meldungen, deren Wirkstoff am letzten Protokolltag davor unter den 50 "
                        "höchsten stand, seit wie vielen Tagen ununterbrochen (Median, Anteil mit mindestens 7 Tagen) und ob "
                        "an irgendeinem Tag der 8 Wochen davor; Gleichstände in fester Reihenfolge je Wirkstoff",
                        "Listenstabilität: Anteil der Top 50, der von einem Tag zum nächsten wechselt"],
    "beste_menge": "Verfahren, deren Brier-Abstand zum besten im 95-%-Intervall über Wirkstoffe 0 einschließt (8 Wochen); "
                   "alles außer dem Hauptvergleich ist sekundär",
    "auswertung": "stockout bewertung, monatlich; Bericht zum Go/No-Go am 30.04.2027",
    "regeln": ["Es zählen nur Vorhersagen aus dem täglichen Vorhersageprotokoll, die mit diesem Prüfplan (sha256) "
               "geschrieben wurden.",
               "Ab Beginn wird nichts mehr eingefroren oder geändert; eine neue Fassung bekommt einen neuen Namen und "
               "einen eigenen Prüfplan.",
               "z3_v0_mit_de nutzt BfArM-Meldungen und dient nur der internen Bewertung, nicht der Anzeige."],
}


def _write_json(path: Path, data: dict) -> dict:
    body = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    data = {**data, "sha256": hashlib.sha256(body.encode()).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return data


def freeze(result: dict, models: Path = MODELS, today: date | None = None) -> dict:
    """Write every method to models/<name>.json and the plan that fixes them by sha256 (only before the check)."""
    today = today or date.today()
    if today >= PROSPECTIVE_START:
        raise SystemExit(f"Einfrieren ist ab dem {PROSPECTIVE_START.isoformat()} nicht mehr erlaubt (Prüfplan).")
    common = {k: result[k] for k in ("basg_stand", "lernen", "pruefen", "schritt_tage")} | {"eingefroren_am": today.isoformat()}
    plan = {**PLAN_RULES, **common, "verfahren": {}}
    for name, m in result["verfahren"].items():
        f = _write_json(models / f"{name}.json", {"name": name, **common, **m})
        plan["verfahren"][name] = {"datei": f"models/{name}.json", "sha256": f["sha256"], "rolle": m["rolle"]}
    return _write_json(models / PLAN.name, plan)


def load_plan(models: Path = MODELS) -> tuple[dict, dict[str, dict]] | None:
    """The plan and its frozen methods in plan order; None if nothing is frozen."""
    path = models / PLAN.name
    if not path.exists():
        return None
    plan = json.loads(path.read_text(encoding="utf-8"))
    order = [n for n in METHODS if n in plan["verfahren"]]
    return plan, {n: json.loads((models / f"{n}.json").read_text(encoding="utf-8")) for n in order}


def predictions(k: Knowledge, methods: dict[str, dict], day: date, tested: bool = False) -> dict[str, dict]:
    """ATC5 -> {"stufe": tier as on the site, "p": {horizon: {method: probability}}} for the universe of the day."""
    out = {}
    for a, at in sorted(k.marketed(day).items()):
        c = k.case(a, day, at)
        if c is not None:
            out[a] = {"stufe": c["stufe"][frozenset({"bfarm"})], "p": {h: predict_case(methods, c, h, tested) for h in HORIZONS}}
    return out


def predict_all(conn: sqlite3.Connection, archive: Archive, day: date, models: Path = MODELS) -> dict | None:
    """Predictions of all frozen methods for `day` with the plan's sha256 and the version of each method."""
    loaded = load_plan(models)
    if not loaded:
        return None
    plan, methods = loaded
    return {"pruefplan": plan["sha256"], "fassungen": {n: m["sha256"] for n, m in methods.items()},
            "zeilen": predictions(Knowledge(conn, archive), methods, day)}


def _columns(names: list[str]) -> list[str]:
    return ["datum", "atc5", "stufe"] + [f"{n}_p{h // 7}" for n in names for h in HORIZONS] + ["pruefplan"]


def write_log(root: Path, day: str, rows: dict[str, dict], plan_sha: str) -> Path:
    names = list(next(iter(rows.values()))["p"][HORIZONS[0]]) if rows else list(METHODS)
    target = root / LOG_DIR / day[:4] / f"{day}.csv.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_columns(names))
    for a, r in rows.items():
        w.writerow([day, a, r["stufe"]] + [f"{r['p'][h][n]:.5f}" for n in names for h in HORIZONS] + [plan_sha[:12]])
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as fh:
        fh.write(buf.getvalue().encode("utf-8"))
    os.replace(tmp, target)
    return target


def read_logs(root: Path, start: date, end: date | None = None, plan_sha: str | None = None) -> dict[date, dict[str, dict]]:
    """Daily logs from `start` (and only rows written with the given plan, if any) in the shape of `predictions`."""
    out: dict[date, dict[str, dict]] = {}
    for path in sorted((root / LOG_DIR).glob("*/*.csv.gz")):
        day = date.fromisoformat(path.name[:10])
        if day < start or (end and day > end):
            continue
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            names = [c[:-3] for c in reader.fieldnames if c.endswith(f"_p{HORIZONS[0] // 7}")]
            rows = {}
            for r in reader:
                if plan_sha and r["pruefplan"] != plan_sha[:12]:
                    continue
                rows[r["atc5"]] = {"stufe": r["stufe"], "p": {h: {n: float(r[f"{n}_p{h // 7}"]) for n in names} for h in HORIZONS}}
        if rows:
            out[day] = rows
    return out


def report_days(conn: sqlite3.Connection) -> tuple[dict[str, list[date]], dict[str, list[date]], dict[str, list[date]], date]:
    """Per substance: start days and first-seen days of all Austrian reports, the substance-level report days
    (merged reports, dated by the earlier of start and first sighting) and the latest BASG day."""
    latest = _d(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
    starts: dict[str, list[date]] = defaultdict(list)
    seen: dict[str, list[date]] = defaultdict(list)
    spans = []
    for a, s, fs, end_upper, active in conn.execute(
        "SELECT atc5, start_date, first_seen, end_upper, active FROM episodes WHERE atc5 IS NOT NULL"
    ):
        s, fs = _d(s), _d(fs)
        if not s:
            continue
        starts[a].append(s)
        if fs:
            seen[a].append(fs)
        first = min(s, fs) if fs else s
        e = latest if active or not end_upper else _d(end_upper)
        spans.append((a, first, max(e, first)))
    for d in (starts, seen):
        for v in d.values():
            v.sort()
    return dict(starts), dict(seen), Intervals(spans).onsets, latest


def _within(ds: list[date], t: date, h: int) -> bool:
    i = bisect.bisect_right(ds, t)
    return i < len(ds) and ds[i] <= t + timedelta(days=h)


def bewerten(conn: sqlite3.Connection, root: Path, start: date, end: date | None = None, plan_sha: str | None = None,
             step: int = STEP) -> dict:
    """Score the daily prediction log from `start`: every method on the same cases of each reference day."""
    logs = read_logs(root, start, end, plan_sha)
    starts, seen, onsets, latest = report_days(conn)
    out = {"beginn": start.isoformat(), "basg_stand": latest.isoformat(), "protokolltage": len(logs), "horizonte": {}}
    ref_days = [d for d in sorted(logs) if (d - start).days % step == 0]
    for h in HORIZONS:
        cases = [{"t": d, "atc5": a, "y": int(_within(starts.get(a, []), d, h) or _within(seen.get(a, []), d, h)),
                  "p": r["p"][h]}
                 for d in ref_days if d + timedelta(days=h) <= latest for a, r in logs[d].items()]
        out["horizonte"][str(h)] = score(cases, intervals=h == MAIN["horizont"]) if cases else {"faelle": 0}
    reports = {a: [d for d in ds if start + timedelta(days=MAIN["horizont"]) <= d <= latest] for a, ds in onsets.items()}
    out["vorlauf_und_stabilitaet"] = lead_and_churn(logs, reports)
    return out


# --- runs -----------------------------------------------------------------------------------------

def measure(conn: sqlite3.Connection, archive: Archive, zeitpunktgenau: bool = False) -> tuple[dict, Knowledge]:
    """Learn every method on 2024–2025 and score all of them on the same 2026 cases."""
    k = Knowledge(conn, archive, zeitpunktgenau)
    rows = table(k, START, k.latest - timedelta(days=min(HORIZONS)))
    methods = learn_methods(rows)
    test = [r for r in rows if r["t"] >= TEST_START]
    out = {"basg_stand": k.latest.isoformat(), "lernen": [START.isoformat(), LEARN_END.isoformat()],
           "pruefen": [TEST_START.isoformat(), k.latest.isoformat()], "schritt_tage": STEP,
           "verfahren": methods, "pruefung": {}}
    for h in HORIZONS:
        cases = [{"t": r["t"], "atc5": r["atc5"], "y": int(r["y"][h]), "p": predict_case(methods, r, h, tested=True)}
                 for r in test if h in r["y"]]
        out["pruefung"][str(h)] = score(cases, intervals=h == MAIN["horizont"])
    return out, k


def simulate(k: Knowledge, methods: dict[str, dict], start: date, end: date, root: Path) -> int:
    """Daily logs from `start` to `end` as if the tested parameters had run each day (retrospective dry run)."""
    n = 0
    d = start
    while d <= end:
        write_log(root, d.isoformat(), predictions(k, methods, d, tested=True), "rueckblick")
        n += 1
        d += timedelta(days=1)
    return n


def _fmt_score(s: dict, title: str) -> list[str]:
    if not s.get("faelle"):
        return [f"{title}: noch keine auswertbaren Fälle"]
    lines = [f"{title}: {s['faelle']} Fälle an {s['stichtage']} Stichtagen, {s['meldungen']} Meldungen ({s['quote']:.1%})"]
    for name, v in s["verfahren"].items():
        tops = ", ".join(f"Top {k} {t['quote']:.1%} ({t['anteil_aller_meldungen'] or 0:.0%})" for k, t in v["spitze"].items())
        skill = f"{v['brier_skill_gegen_stufen']:+.1%}" if v["brier_skill_gegen_stufen"] is not None else "–"
        lines.append(f"  {name:19} Brier {v['brier']:.5f} (gegen Stufen {skill}), AUC {v['auc']}, AP {v['average_precision']}, "
                     f"Kal. {v['kalibrierung_achsenabschnitt']}/{v['kalibrierung_steigung']}; {tops}")
    if "hauptvergleich" in s:
        g = s["hauptvergleich"]
        k = MAIN["k"]
        def ci(x: list | None, fmt: str) -> str:
            return f"[{x[0]:{fmt}} bis {x[1]:{fmt}}]" if x else "[–]"

        lines.append(f"  Hauptvergleich {g['modell']} gegen {g['gegen']}: Brier-Gewinn {g['brier_gewinn']:+.5f} "
                     f"{ci(g['brier_gewinn_ki95'], '+.5f')}, Top {k} {g[f'top{k}_differenz']:+.1%} "
                     f"{ci(g[f'top{k}_differenz_ki95'], '+.1%')}, AUC {g['auc_differenz']:+.3f} {ci(g['auc_ki95'], '+.3f')} "
                     f"→ {'bestanden' if g['bestanden'] else 'nicht bestanden'}")
        b = s["beste_menge"]
        lines.append(f"  Menge der besten (Brier): {', '.join(b['menge'])}")
    return lines


def render(r: dict) -> str:
    lines = [f"Z3-Verfahren: lernen {r['lernen'][0]}–{r['lernen'][1]}, prüfen {r['pruefen'][0]}–{r['pruefen'][1]} "
             f"(BASG-Stand {r['basg_stand']}), Stichtage alle {r['schritt_tage']} Tage"]
    for h, s in r["pruefung"].items():
        lines += [""] + _fmt_score(s, f"{int(h) // 7} Wochen")
    s = r["pruefung"][str(MAIN["horizont"])]["verfahren"][MAIN["modell"]]
    lines.append("  Kalibrierung z3_v0 (Zehntel): " + "; ".join(f"{c['vorhergesagt']:.1%}→{c['beobachtet']:.1%}" for c in s["kalibrierung"]))
    return "\n".join(lines)


def render_bewertung(r: dict) -> str:
    lines = [f"Bewertung ab {r['beginn']} (BASG-Stand {r['basg_stand']}, {r['protokolltage']} Protokolltage)"]
    for h, s in r["horizonte"].items():
        lines += [""] + _fmt_score(s, f"{int(h) // 7} Wochen")
    lc = r.get("vorlauf_und_stabilitaet") or {}
    if lc:
        lines += ["", f"Vorlauf (Top {LEAD_K}, 8 Wochen davor) und Listenstabilität:"]
        for n, v in lc.items():
            if v["meldungen"]:
                lines.append(f"  {n:19} {v['meldungen']} Meldungen: am Vortag auf der Liste {v['auf_der_liste']:.0%} "
                             f"[{v['auf_der_liste_ki95'][0]:.0%}–{v['auf_der_liste_ki95'][1]:.0%}], seit Median "
                             f"{v['seit_tagen_median']} Tagen, mind. 7 Tage {v['mind_7_tage']:.0%}, irgendwann in 8 Wochen "
                             f"{v['irgendwann_in_8_wochen']:.0%}; Wechsel je Tag {v['wechsel_je_tag']:.1%}")
    return "\n".join(lines)


def run(db_path: Path, archive: Archive, json_path: Path | None = None, freeze_models: Path | None = None,
        zeitpunktgenau: bool = False) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        result, _ = measure(conn, archive, zeitpunktgenau)
    finally:
        conn.close()
    if freeze_models:
        result["pruefplan"] = freeze(result, freeze_models)["sha256"]
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result
