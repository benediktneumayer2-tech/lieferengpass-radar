"""Sharper early-warning signals: country weights, reason of the foreign report, strength and dosage form.

Cases as in the lead-time measurement (`vorlauf`): a new foreign signal on a substance (ATC5) that is marketed
and not reported in Austria; a further case on the same substance when a country joins or 28 days have passed.
Outcome: a new BASG report on the substance within 4, 8 or 12 weeks. Every refinement is compared with the
current tier of the same case (and the substance's size and earlier Austrian shortage), learned on 2024–2025
and checked on 2026. Only what also holds in the test period is a candidate for the early-warning list.

Result of the first run (2026-10-20): the number of countries is what counts. Five or more countries replaced
"same holder in three or more countries" as tier A; country weights, reasons, strength and form added nothing.
"""
from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .foreign import _ascii, holder_key, strengths
from .rueckblick import _size_bucket, _sir
from .vorlauf import HORIZONS, Intervals, _d, _episodes, _wilson, tier

LEARN = (date(2024, 1, 1), date(2025, 12, 31))
TEST_START = date(2026, 1, 1)
H8 = 56
TIER_RANK = {"A": 3, "B": 2, "C": 1, "1": 0}
BOOTSTRAP = 500

# Reason of a foreign report, from the national wording (IT, BE, HU, US, CZ; DE is hidden on the site).
REASONS = (
    ("nachfrage", re.compile(r"richiesta|nachfrage|demand increase|increased demand|megnovekedett igeny|poptavk", re.I)),
    ("herstellung", re.compile(
        r"produtt|produktion|herstell|production|endfreigabe|release|chargenpr|gmp|gyartasi|hatoanyag|vyrobni d"
        r"|active (?:ingredient|substance)|inactive ingredient|good manufacturing|wirkstoffhersteller", re.I)),
    ("logistik", re.compile(r"kapacitni/distribucni|szallitasi|logistic|delay in shipping|distribuzione", re.I)),
    ("kommerziell", re.compile(
        r"commerci|piaci megfontolas|obchodni|replacement|insufficient demand|nizka vyse|nizke odbery"
        r"|forgalmazas megszuntetese|registrac|revocation|prechod na|regolator|adminisztrativ", re.I)),
)
# Dosage form classes from form and product text in the languages of the sources.
FORMS = (
    ("parenteral", re.compile(
        r"inj|infus|infuz|infuus|wstrzyk|ruisku|fertigspritze|fertigpen|syringe|parenter|i\.v\.|\bpen\b|vial", re.I)),
    ("oral_fest", re.compile(
        r"tabl|kaps|caps|compress|tablet|\btbl\b|\bcps\b|drag|pastill|granul|kapseli|filmom", re.I)),
    ("oral_fluessig", re.compile(r"einnehmen|oral|sirup|syrup|sciropp|doustn|suun|\bpor\b|tropfen", re.I)),
    ("sonst", re.compile(
        r"creme|crema|cream|salbe|unguent|ointment|gel\b|pflaster|transderm|tapasz|augen|eye|oftalm|inhal|spray"
        r"|nasal|zapf|suppos|czop|kupu|vagin|shampoo|losung zur anwendung|kutan|cutan|emuls", re.I)),
)


def reason_classes(text: str | None) -> set[str]:
    t = _ascii(text or "")
    return {name for name, rx in REASONS if rx.search(t)}


def form_class(*texts: str | None) -> str | None:
    t = _ascii(" ".join(x for x in texts if x))
    return next((name for name, rx in FORMS if rx.search(t)), None)


# --- cases ----------------------------------------------------------------------------------------

def load_items(conn: sqlite3.Connection, latest: date, exclude: frozenset) -> list[dict]:
    out = []
    for r in conn.execute(
        "SELECT source, country, atc5, signal_date, holder, end_date, still_listed, last_seen, reason, strength, form, "
        "product FROM foreign_items WHERE atc5 IS NOT NULL AND signal_date IS NOT NULL AND coalesce(status, '') != 'einstellung'"
    ):
        source, country, atc5, signal, holder, end_date, still, last_seen, reason, strength, form, product = r
        if source in exclude:
            continue
        s = _d(signal)
        until = _d(end_date) or (latest if still else _d(last_seen))
        out.append({"country": country, "atc5": atc5, "date": s, "until": max(until or s, s), "holder": holder_key(holder),
                    "reasons": reason_classes(reason), "has_reason": bool(reason and reason_classes(reason)),
                    "strengths": strengths(strength) | strengths(product), "form": form_class(form, product)})
    return out


def austrian_products(conn: sqlite3.Connection) -> tuple[dict, dict, dict, set]:
    """Per ATC5 of the current ASP list: strengths, form classes, number of products; and (ATC5, holder) pairs."""
    st: dict[str, set] = defaultdict(set)
    fm: dict[str, set] = defaultdict(set)
    zls: dict[str, set] = defaultdict(set)
    pairs = set()
    for atc, name, form, zl, inhaber in conn.execute(
        "SELECT atc, name, form, zulassungsnummer, inhaber FROM asp_packages WHERE valid = 1 AND length(atc) >= 7"
    ):
        a = atc[:7]
        st[a] |= strengths(name)
        f = form_class(form, name)
        if f:
            fm[a].add(f)
        zls[a].add(zl)
        if holder_key(inhaber):
            pairs.add((a, holder_key(inhaber)))
    return dict(st), dict(fm), {a: len(z) for a, z in zls.items()}, pairs


def build_cases(items: list[dict], subst: Intervals, marketed_pairs: set, at_strengths: dict, at_forms: dict,
                size: dict, start: date, end: date) -> list[dict]:
    by_atc: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        if it["atc5"] in size:
            by_atc[it["atc5"]].append(it)
    cases = []
    for a, its in by_atc.items():
        its.sort(key=lambda it: it["date"])
        last_day, last_set = None, frozenset()
        for it in its:
            x = it["date"]
            if not (start <= x <= end) or subst.active(a, x):
                continue
            act = [o for o in its if o["date"] <= x <= o["until"]]
            countries = frozenset(o["country"] for o in act)
            if last_day and not (countries - last_set) and (x - last_day).days < 28:
                continue
            last_day, last_set = x, countries
            by_holder: dict[str, set] = defaultdict(set)
            for o in act:
                if o["holder"] and (a, o["holder"]) in marketed_pairs:
                    by_holder[o["holder"]].add(o["country"])
            n = len(countries)
            t = tier(n)
            fs = set().union(*(o["strengths"] for o in act))
            forms = {o["form"] for o in act if o["form"]}
            reasons = set().union(*(o["reasons"] for o in act))
            cases.append({
                "atc5": a, "date": x, "countries": countries, "tier": t,
                "tier_inhaber": ("A" if any(len(cs) >= 3 for cs in by_holder.values()) else "B") if n >= 3 else t,
                "reasons": reasons if any(o["has_reason"] for o in act) else None,
                "staerke": None if not fs or not at_strengths.get(a) else bool(fs & at_strengths[a]),
                "form": None if not forms or not at_forms.get(a) else bool(forms & at_forms[a]),
                "stratum": (t, _size_bucket(size[a]), subst.had_onset_before(a, x)),
                "hits": {h: subst.onset_within(a, x, h) for h in HORIZONS if x <= end - timedelta(days=h)},
            })
    return cases


# --- comparisons ----------------------------------------------------------------------------------

def _rate(group: list[dict], h: int) -> dict:
    usable = [c for c in group if h in c["hits"]]
    hit = sum(c["hits"][h] for c in usable)
    return {"faelle": len(usable), "treffer": hit, "quote": round(hit / len(usable), 3) if usable else None,
            "ki95": _wilson(hit, len(usable))}


def versus_tier(group: list[dict], period: list[dict], h: int = H8) -> dict:
    """Observed hits of `group` against the rates of its strata (tier, size, earlier shortage) in the period."""
    tally: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for c in period:
        if h in c["hits"]:
            tally[c["stratum"]][0] += c["hits"][h]
            tally[c["stratum"]][1] += 1
    usable = [c for c in group if h in c["hits"]]
    expected = sum(tally[c["stratum"]][0] / tally[c["stratum"]][1] for c in usable)
    return {**_rate(group, h), **_sir(sum(c["hits"][h] for c in usable), expected)}


def _split(cases: list[dict]) -> dict[str, list[dict]]:
    return {"lernen": [c for c in cases if LEARN[0] <= c["date"] <= LEARN[1]],
            "pruefen": [c for c in cases if c["date"] >= TEST_START]}


def compare(cases: list[dict], groups: dict) -> dict:
    """groups: name -> predicate on a case; per period the group's hit rate and SIR against the tier."""
    out = {}
    for period, cs in _split(cases).items():
        out[period] = {name: versus_tier([c for c in cs if pred(c)], cs) for name, pred in groups.items()}
    return out


# --- country weights ------------------------------------------------------------------------------

def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def logit(xs: list[list[float]], ys: list[int], l2: float = 1.0, iters: int = 30) -> list[float]:
    """Ridge logistic regression by Newton steps; column 0 is the unpenalised intercept."""
    k = len(xs[0])
    w = [0.0] * k
    for _ in range(iters):
        g = [-l2 * w[i] if i else 0.0 for i in range(k)]
        hess = [[(l2 if i == j and i else 0.0) for j in range(k)] for i in range(k)]
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-sum(a * b for a, b in zip(w, x))))
            nz = [i for i in range(k) if x[i]]
            for i in nz:
                g[i] += (y - p) * x[i]
                for j in nz:
                    hess[i][j] += p * (1 - p) * x[i] * x[j]
        step = _solve(hess, g)
        w = [a + b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return w


def auc(scores: list[float], ys: list[int]) -> float | None:
    """Area under the ROC curve with tied scores counted half."""
    pos = sum(ys)
    neg = len(ys) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return (sum(r for r, y in zip(ranks, ys) if y) - pos * (pos + 1) / 2) / (pos * neg)


def top_rate(scores: list[float], ys: list[int], k: int) -> float:
    """Hit rate among the k highest scores; ties at the cut-off count with their average."""
    pairs = sorted(zip(scores, ys), reverse=True)
    if k <= 0:
        return 0.0
    cut = pairs[k - 1][0]
    above = [y for s, y in pairs if s > cut]
    tied = [y for s, y in pairs if s == cut]
    return (sum(above) + (k - len(above)) * sum(tied) / len(tied)) / k


def _bootstrap(cases: list[dict], stat, seed: int = 7, digits: int = 3) -> list[float] | None:
    """95 % interval of stat(sample) over resamples of whole substances (cases of one substance are not independent)."""
    by_atc: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        by_atc[c["atc5"]].append(c)
    keys = sorted(by_atc)
    rng = random.Random(seed)
    vals = []
    for _ in range(BOOTSTRAP):
        v = stat([c for key in (rng.choice(keys) for _ in keys) for c in by_atc[key]])
        if v is not None:
            vals.append(v)
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], digits), round(vals[int(0.975 * len(vals)) - 1], digits)] if vals else None


def _auc_of(cs: list[dict], key: str) -> float | None:
    return auc([TIER_RANK[c[key]] for c in cs], [int(c["hits"][H8]) for c in cs])


def tier_rules(cases: list[dict]) -> dict:
    """Tier A as before (same holder in 3+ countries) against 5+ countries, per period: cases and hits in tier A,
    AUC of the four tiers, with intervals of the differences (new minus old)."""
    out = {}
    for period, cs in _split(cases).items():
        cs = [c for c in cs if H8 in c["hits"]]

        def a_stats(sample: list[dict], key: str) -> tuple[int, int]:
            g = [c for c in sample if c[key] == "A"]
            return len(g), sum(c["hits"][H8] for c in g)

        def rate(sample: list[dict], key: str) -> float | None:
            n, hit = a_stats(sample, key)
            return hit / n if n else None

        row = {}
        for name, key in (("alt_gleicher_inhaber", "tier_inhaber"), ("neu_5_laender", "tier")):
            n, hit = a_stats(cs, key)
            row[name] = {"a_faelle": n, "a_treffer": hit, "a_quote": round(hit / n, 3) if n else None,
                         "a_ki95": _wilson(hit, n), "auc": round(_auc_of(cs, key), 3)}
        row["differenz"] = {
            "a_treffer": row["neu_5_laender"]["a_treffer"] - row["alt_gleicher_inhaber"]["a_treffer"],
            "a_treffer_ki95": _bootstrap(cs, lambda s: a_stats(s, "tier")[1] - a_stats(s, "tier_inhaber")[1]),
            "a_quote_ki95": _bootstrap(cs, lambda s: None if rate(s, "tier") is None or rate(s, "tier_inhaber") is None
                                       else rate(s, "tier") - rate(s, "tier_inhaber")),
            "auc": round(row["neu_5_laender"]["auc"] - row["alt_gleicher_inhaber"]["auc"], 3),
            "auc_ki95": _bootstrap(cs, lambda s: _auc_of(s, "tier") - _auc_of(s, "tier_inhaber")),
        }
        out[period] = row
    return out


def country_weights(cases: list[dict], seed: int = 7) -> dict:
    """Weights per country (and same holder in 3+ countries) learned on 2024–2025, ranking checked on 2026
    against the tier rule and the plain number of countries (AUC, hit rate among as many cases as tiers A+B)."""
    sp = {p: [c for c in cs if H8 in c["hits"]] for p, cs in _split(cases).items()}
    countries = sorted({x for c in sp["lernen"] for x in c["countries"]})

    def row(c: dict) -> list[float]:
        return [1.0] + [float(x in c["countries"]) for x in countries] + [float(c["tier_inhaber"] == "A")]

    learn = sp["lernen"]
    w = logit([row(c) for c in learn], [int(c["hits"][H8]) for c in learn])
    weights = {x: round(v, 2) for x, v in zip(countries, w[1:-1])}
    test = sp["pruefen"]
    ys = [int(c["hits"][H8]) for c in test]

    def scorers(ws: dict, holder_w: float) -> dict:
        return {
            "stufe": lambda c: TIER_RANK[c["tier"]],
            "laenderzahl": lambda c: len(c["countries"]) + 0.5 * (c["tier_inhaber"] == "A"),
            "gewichtet": lambda c: sum(ws.get(x, 0.0) for x in c["countries"]) + holder_w * (c["tier_inhaber"] == "A"),
        }

    sc = scorers(weights, w[-1])
    k = sum(c["tier"] in "AB" for c in test)
    result = {name: {"auc": round(auc([f(c) for c in test], ys), 3), "quote_top_k": round(top_rate([f(c) for c in test], ys, k), 3)}
              for name, f in sc.items()}

    def diff(sample: list[dict]) -> float | None:
        yb = [int(c["hits"][H8]) for c in sample]
        a, b = auc([sc["gewichtet"](c) for c in sample], yb), auc([sc["stufe"](c) for c in sample], yb)
        return None if a is None or b is None else a - b

    return {
        "gewichte": dict(sorted(weights.items(), key=lambda kv: -kv[1])),
        "gewicht_gleicher_inhaber_3_laender": round(w[-1], 2),
        "lernfaelle": len(learn), "pruefaelle": len(test), "pruef_treffer": sum(ys), "top_k": k,
        "pruefung": result,
        "auc_differenz_gewichtet_minus_stufe": {
            "wert": round(result["gewichtet"]["auc"] - result["stufe"]["auc"], 3),
            "ki95": _bootstrap(test, diff, seed),
        },
    }


# --- measurement ----------------------------------------------------------------------------------

def measure(conn: sqlite3.Connection, exclude: frozenset = frozenset({"bfarm"}), end: date | None = None) -> dict:
    latest = _d(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
    end = end or latest
    subst = Intervals([(a, s, e) for a, s, e, _ in _episodes(conn, latest)])
    at_strengths, at_forms, size, pairs = austrian_products(conn)
    items = load_items(conn, latest, exclude)
    cases = build_cases(items, subst, pairs, at_strengths, at_forms, size, LEARN[0], end)

    reasons = compare(cases, {
        "mit_grund": lambda c: c["reasons"] is not None,
        "ohne_grund": lambda c: c["reasons"] is None,
        **{f"grund_{name}": (lambda n: lambda c: c["reasons"] is not None and n in c["reasons"])(name) for name, _ in REASONS},
        "nur_kommerziell": lambda c: c["reasons"] is not None and c["reasons"] <= {"kommerziell"} and bool(c["reasons"]),
        "herstellung_oder_nachfrage": lambda c: c["reasons"] is not None and bool(c["reasons"] & {"herstellung", "nachfrage"}),
    })
    match = compare(cases, {
        "staerke_passt": lambda c: c["staerke"] is True,
        "staerke_passt_nicht": lambda c: c["staerke"] is False,
        "staerke_unbekannt": lambda c: c["staerke"] is None,
        "form_passt": lambda c: c["form"] is True,
        "form_passt_nicht": lambda c: c["form"] is False,
        "form_unbekannt": lambda c: c["form"] is None,
    })
    tiers = {p: {t: _rate([c for c in cs if c["tier"] == t], H8) for t in "ABC1"} for p, cs in _split(cases).items()}
    return {
        "lernen": [LEARN[0].isoformat(), LEARN[1].isoformat()],
        "pruefen": [TEST_START.isoformat(), end.isoformat()],
        "ausgeschlossene_quellen": sorted(exclude),
        "faelle": dict(Counter("lernen" if c["date"] <= LEARN[1] else "pruefen" for c in cases)),
        "stufen_8_wochen": tiers,
        "stufenregel": tier_rules(cases),
        "laendergewichte": country_weights(cases),
        "grund": reasons,
        "staerke_form": match,
        "anteile": {
            "mit_grund": round(sum(c["reasons"] is not None for c in cases) / len(cases), 3),
            "staerke_bekannt": round(sum(c["staerke"] is not None for c in cases) / len(cases), 3),
            "form_bekannt": round(sum(c["form"] is not None for c in cases) / len(cases), 3),
        },
        "grenzen": [
            "Stärken, Darreichungsformen und Zulassungsinhaber in Österreich stammen aus der heutigen ASP-Liste.",
            "Fälle desselben Wirkstoffs sind nicht unabhängig; das Intervall der AUC-Differenz zieht deshalb ganze Wirkstoffe.",
            "Der Grund steht nur in den Listen aus IT, BE, HU, CZ und den USA; DE bleibt wie auf der Website ausgeblendet.",
            "SIR hier: beobachtete Treffer gegen die Quote derselben Stufe, Wirkstoffgröße und Vorgeschichte im selben Zeitraum.",
        ],
    }


def _fmt(v: dict) -> str:
    if not v["faelle"]:
        return "0 Fälle"
    s = f"{v['treffer']}/{v['faelle']} = {v['quote']:.1%}"
    if v.get("sir") is not None:
        s += f", SIR {v['sir']} [{v['sir_ki95'][0]}–{v['sir_ki95'][1]}]"
    return s


def render(r: dict) -> str:
    cw = r["laendergewichte"]
    lines = [
        f"Signale schärfen: lernen {r['lernen'][0]}–{r['lernen'][1]}, prüfen {r['pruefen'][0]}–{r['pruefen'][1]} "
        f"(ohne {', '.join(r['ausgeschlossene_quellen'])}); Fälle {r['faelle']}",
        "",
        "Stufen, 8 Wochen:",
    ]
    for p, ts in r["stufen_8_wochen"].items():
        lines.append(f"  {p}: " + "; ".join(f"{t} {_fmt(v)}" for t, v in ts.items()))
    lines += ["", "Stufe A: gleicher Inhaber in 3+ Ländern (alt) gegen 5+ Länder (neu), 8 Wochen:"]
    for p, row in r["stufenregel"].items():
        o, n, d = row["alt_gleicher_inhaber"], row["neu_5_laender"], row["differenz"]
        lines.append(f"  {p}: alt {o['a_treffer']}/{o['a_faelle']} = {o['a_quote']:.1%}, neu {n['a_treffer']}/{n['a_faelle']} = "
                     f"{n['a_quote']:.1%}; Treffer {d['a_treffer']:+d} [{d['a_treffer_ki95'][0]:+.0f} bis {d['a_treffer_ki95'][1]:+.0f}], "
                     f"Quote [{d['a_quote_ki95'][0]:+.1%} bis {d['a_quote_ki95'][1]:+.1%}], AUC {o['auc']} → {n['auc']} "
                     f"[{d['auc_ki95'][0]:+.3f} bis {d['auc_ki95'][1]:+.3f}]")
    lines += ["", f"Ländergewichte (gelernt an {cw['lernfaelle']} Fällen, logarithmische Chance):",
              "  " + ", ".join(f"{k} {v:+.2f}" for k, v in cw["gewichte"].items())
              + f"; gleicher Inhaber in 3+ Ländern {cw['gewicht_gleicher_inhaber_3_laender']:+.2f}",
              f"  Prüfung an {cw['pruefaelle']} Fällen ({cw['pruef_treffer']} Treffer), Spitze = {cw['top_k']} Fälle (so viele wie Stufe A+B):"]
    for name, v in cw["pruefung"].items():
        lines.append(f"    {name}: AUC {v['auc']}, Quote in der Spitze {v['quote_top_k']:.1%}")
    d = cw["auc_differenz_gewichtet_minus_stufe"]
    lines.append(f"  AUC gewichtet minus Stufe: {d['wert']:+.3f} [95 %: {d['ki95'][0]:+.3f} bis {d['ki95'][1]:+.3f}]")
    for title, block in (("Grund der Auslandsmeldung", r["grund"]), ("Stärke und Darreichungsform", r["staerke_form"])):
        lines += ["", f"{title}, 8 Wochen, gegen dieselbe Stufe:"]
        for name in block["lernen"]:
            lines.append(f"  {name}: lernen {_fmt(block['lernen'][name])} | prüfen {_fmt(block['pruefen'][name])}")
    lines += ["", "Anteile: " + ", ".join(f"{k} {v:.0%}" for k, v in r["anteile"].items()), "", "Grenzen:"]
    lines += [f"- {g}" for g in r["grenzen"]]
    return "\n".join(lines)


def run(db_path: Path, json_path: Path | None = None) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        result = measure(conn)
    finally:
        conn.close()
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
