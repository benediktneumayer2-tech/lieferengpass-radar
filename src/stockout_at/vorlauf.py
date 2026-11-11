"""Lead-time measurement: do foreign shortage reports precede BASG reports for the same substance?

Unit is the substance (ATC level 5). Two measurements, both deterministic on the derived database:

1. Vorausgehen: for each new Austrian report in the window, was there a foreign report on the same
   ATC5 in the 365 days before, and how many days earlier was it first public (earliest signal)?
   The same for the reverse direction as a control (foreign only after Austria). At package level
   the same is reported when the foreign marketing authorisation holder matches.
2. Trefferquote: after a foreign signal on a substance that is not reported in Austria, how often does
   an Austrian report follow within 4, 8 or 12 weeks - compared with the base rate of all marketed
   substances at regular reference dates (lift = hit rate / base rate).
"""
from __future__ import annotations

import bisect
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .foreign import holder_key

HORIZONS = (28, 56, 84)
MAX_LEAD = 365
LEAD_BINS = ((1, 13, "1–13 Tage"), (14, 27, "2–4 Wochen"), (28, 55, "4–8 Wochen"), (56, 83, "8–12 Wochen"),
             (84, 181, "12–26 Wochen"), (182, MAX_LEAD, "26–52 Wochen"))


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _median(xs: list[int]) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _quantile(xs: list[int], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return float(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))])


def _wilson(hit: int, n: int, z: float = 1.96) -> list[float] | None:
    """95 % Wilson interval of a proportion."""
    if not n:
        return None
    p = hit / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


class Intervals:
    """Austrian episodes per key (ATC5, or ATC5 + holder) merged into intervals; onset = start of an interval."""

    def __init__(self, events: list[tuple[object, date, date]]):
        by_key: dict[object, list[tuple[date, date]]] = defaultdict(list)
        for key, s, e in events:
            by_key[key].append((s, e))
        self.intervals: dict[object, list[tuple[date, date]]] = {}
        self.onsets: dict[object, list[date]] = {}
        for key, ivs in by_key.items():
            merged: list[list[date]] = []
            for s, e in sorted(ivs):
                if merged and s <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], e)
                else:
                    merged.append([s, e])
            self.intervals[key] = [(s, e) for s, e in merged]
            self.onsets[key] = [s for s, _ in merged]

    def active(self, key, d: date) -> bool:
        ivs = self.intervals.get(key, [])
        i = bisect.bisect_right(ivs, (d, date.max)) - 1
        return i >= 0 and ivs[i][0] <= d <= ivs[i][1]

    def onset_within(self, key, d: date, days: int) -> bool:
        ons = self.onsets.get(key, [])
        i = bisect.bisect_right(ons, d)
        return i < len(ons) and ons[i] <= d + timedelta(days=days)

    def had_onset_before(self, key, d: date) -> bool:
        ons = self.onsets.get(key)
        return bool(ons) and ons[0] < d


def _episodes(conn: sqlite3.Connection, latest: date) -> list[tuple[str, date, date, str | None]]:
    out = []
    for atc5, start, end_upper, active, holder in conn.execute(
        "SELECT atc5, start_date, end_upper, active, zulassungsinhaber FROM episodes WHERE atc5 IS NOT NULL"
    ):
        s = _d(start)
        e = latest if active or not end_upper else _d(end_upper)
        if s and e and s <= latest:
            out.append((atc5, s, max(e, s), holder_key(holder)))
    return out


def _hit_rates(signals: dict, hist: Intervals, universe: set, start: date, end: date) -> dict:
    """After a foreign signal on a key not reported in Austria: Austrian onset within h days?
    Signals on the same key less than 28 days apart count once."""
    out = {}
    for h in HORIZONS:
        cases = hit = 0
        for key, ds in signals.items():
            if key not in universe:
                continue
            last = None
            for x in ds:
                if last and (x - last).days < 28:
                    continue
                last = x
                if not (start <= x <= end - timedelta(days=h)) or hist.active(key, x):
                    continue
                cases += 1
                hit += hist.onset_within(key, x, h)
        out[f"{h // 7}_wochen"] = {"faelle": cases, "treffer": hit, "quote": round(hit / cases, 3) if cases else None,
                                   "ki95": _wilson(hit, cases)}
    return out


def _base_rates(hist: Intervals, universe: set, start: date, end: date) -> tuple[dict, dict]:
    """Austrian onset rate for all keys (and keys with an earlier Austrian shortage) at 14-day reference dates."""
    base, base_hist = {}, {}
    keys = sorted(universe, key=str)
    for h in HORIZONS:
        cases = hit = cases_h = hit_h = 0
        t = start
        while t <= end - timedelta(days=h):
            for key in keys:
                if not hist.active(key, t):
                    got = hist.onset_within(key, t, h)
                    cases += 1
                    hit += got
                    if hist.had_onset_before(key, t):
                        cases_h += 1
                        hit_h += got
            t += timedelta(days=14)
        k = f"{h // 7}_wochen"
        base[k] = {"faelle": cases, "treffer": hit, "quote": round(hit / cases, 4) if cases else None}
        base_hist[k] = {"faelle": cases_h, "treffer": hit_h, "quote": round(hit_h / cases_h, 4) if cases_h else None}
    return base, base_hist


def _add_lift(hits: dict, base: dict, base_hist: dict) -> dict:
    for k, v in hits.items():
        b, bh = base[k]["quote"], base_hist[k]["quote"]
        v["lift"] = round(v["quote"] / b, 1) if v["quote"] is not None and b else None
        v["lift_engpass_vorgeschichte"] = round(v["quote"] / bh, 1) if v["quote"] is not None and bh else None
    return hits


def _signals(conn: sqlite3.Connection, latest: date, exclude: frozenset = frozenset()) -> dict[str, list[dict]]:
    """Foreign items per source with signal date and the last day the report was known to be active."""
    out: dict[str, list[dict]] = defaultdict(list)
    for source, country, atc5, signal, holder, end_date, still, last_seen, status in conn.execute(
        "SELECT source, country, atc5, signal_date, holder, end_date, still_listed, last_seen, status FROM foreign_items "
        "WHERE atc5 IS NOT NULL AND signal_date IS NOT NULL AND coalesce(status, '') != 'einstellung'"
    ):
        if source in exclude:
            continue
        s = _d(signal)
        until = _d(end_date) or (latest if still else _d(last_seen))
        out[source].append({"country": country, "atc5": atc5, "date": s, "until": max(until or s, s),
                            "holder": holder_key(holder), "status": status})
    return out


MIN_COMBO_CASES = 20
TIER_A_COUNTRIES = 5  # s17: 5+ countries beat "same holder in 3+ countries" in 2026 (learned 2024–2025)


def tier(n_countries: int) -> str:
    """Tier of a substance by the number of countries with a current report: A 5+, B 3–4, C 2, '1' one country."""
    return "A" if n_countries >= TIER_A_COUNTRIES else "B" if n_countries >= 3 else "C" if n_countries == 2 else "1"


def _combinations(items: list[dict], key_fn, hist: Intervals, universe: set, start: date, end: date,
                  base: dict, base_hist: dict, tiers: bool = False) -> dict:
    """Hit rates by number and combination of countries with an active report when a new foreign signal arrives.

    A case is (key, day of a new foreign signal) with no active Austrian report; a further case on the same key
    counts when a new country joins or 28 days have passed. Cases on one key are therefore not independent.
    """
    by_key: dict[object, list[dict]] = defaultdict(list)
    for it in items:
        k = key_fn(it)
        if k is not None and k in universe:
            by_key[k].append(it)
    cases = []  # (countries, {h: hit})
    for k, its in by_key.items():
        its.sort(key=lambda it: it["date"])
        last_day, last_set = None, frozenset()
        for it in its:
            x = it["date"]
            if not (start <= x <= end) or hist.active(k, x):
                continue
            active = frozenset(o["country"] for o in its if o["date"] <= x <= o["until"])
            if last_day and not (active - last_set) and (x - last_day).days < 28:
                continue
            last_day, last_set = x, active
            cases.append((active, x, {h: hist.onset_within(k, x, h) for h in HORIZONS}, tier(len(active)) if tiers else None))

    def summarise(group: list) -> dict:
        out = {}
        for h in HORIZONS:
            usable = [c for c in group if c[1] <= end - timedelta(days=h)]
            hit = sum(c[2][h] for c in usable)
            q = round(hit / len(usable), 3) if usable else None
            b, bh = base[f"{h // 7}_wochen"]["quote"], base_hist[f"{h // 7}_wochen"]["quote"]
            out[f"{h // 7}_wochen"] = {"faelle": len(usable), "treffer": hit, "quote": q, "ki95": _wilson(hit, len(usable)),
                                       "lift": round(q / b, 1) if q is not None and b else None,
                                       "lift_engpass_vorgeschichte": round(q / bh, 1) if q is not None and bh else None}
        return out

    by_count: dict[str, list] = defaultdict(list)
    by_combo: dict[str, list] = defaultdict(list)
    for c in cases:
        n = len(c[0])
        by_count["3+" if n >= 3 else str(n)].append(c)
        by_combo["+".join(sorted(c[0]))].append(c)
    combos = {name: summarise(g) for name, g in by_combo.items() if len(g) >= MIN_COMBO_CASES}
    by_tier: dict[str, list] = defaultdict(list)
    for c in cases:
        if c[3]:
            by_tier[c[3]].append(c)

    # Added value of one country: same number of active countries, with versus without it (8 weeks).
    h8 = 56
    usable = [c for c in cases if c[1] <= end - timedelta(days=h8)]
    by_country = {}
    for country in sorted({x for c in cases for x in c[0]}):
        row = {}
        for bucket in ("1", "2", "3+"):
            grp = [c for c in usable if ("3+" if len(c[0]) >= 3 else str(len(c[0]))) == bucket]
            with_c = [c for c in grp if country in c[0]]
            without = [c for c in grp if country not in c[0]]
            if with_c and without:
                hw, ho = sum(c[2][h8] for c in with_c), sum(c[2][h8] for c in without)
                row[bucket] = {"mit": [hw, len(with_c)], "ohne": [ho, len(without)],
                               "quote_mit": round(hw / len(with_c), 3), "quote_ohne": round(ho / len(without), 3),
                               "ki95_mit": _wilson(hw, len(with_c))}
        by_country[country] = row
    return {
        "faelle": len(cases),
        "nach_zahl_der_laender": {n: summarise(by_count[n]) for n in sorted(by_count)},
        "zusatznutzen_land_8_wochen": by_country,
        "nach_kombination": dict(sorted(combos.items(), key=lambda kv: -(kv[1]["8_wochen"]["quote"] or 0))),
        "nach_stufe": {t: summarise(by_tier[t]) for t in sorted(by_tier)},
        "mindestfaelle_kombination": MIN_COMBO_CASES,
    }


def _lead_summary(leads: list[tuple[int, int]], n: int) -> dict:
    """leads: (days since earliest, days since latest foreign signal) per preceded case."""
    last = [b for _, b in leads]
    bins = {label: sum(1 for x in last if lo <= x <= hi) for lo, hi, label in LEAD_BINS}
    return {
        "faelle": n,
        "mit_vorausgehender_auslandsmeldung": len(leads),
        "anteil": round(len(leads) / n, 3) if n else None,
        "vorlauf_median_tage": _median(last),
        "vorlauf_q25_tage": _quantile(last, 0.25),
        "vorlauf_q75_tage": _quantile(last, 0.75),
        "vorlauf_frueheste_median_tage": _median([a for a, _ in leads]),
        "vorlauf_verteilung": bins,
    }


def measure(conn: sqlite3.Connection, start: date | None = None, end: date | None = None,
            exclude_sources: frozenset = frozenset()) -> dict:
    latest = _d(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
    end = end or latest
    start = start or date(2024, 1, 1)
    episodes = _episodes(conn, latest)
    subst = Intervals([(a, s, e) for a, s, e, _ in episodes])
    pairs = Intervals([((a, h), s, e) for a, s, e, h in episodes if h])
    asp = conn.execute("SELECT atc, inhaber FROM asp_packages WHERE valid = 1 AND length(atc) >= 7").fetchall()
    marketed = {atc[:7] for atc, _ in asp}
    marketed_pairs = {(atc[:7], holder_key(inh)) for atc, inh in asp if holder_key(inh)}
    base, base_hist = _base_rates(subst, marketed, start, end)
    pbase, pbase_hist = _base_rates(pairs, marketed_pairs, start, end)

    sources = {}
    all_signals = _signals(conn, latest, frozenset(exclude_sources))
    all_items = [it for sigs in all_signals.values() for it in sigs]
    combined = {
        "wirkstoff": _combinations(all_items, lambda it: it["atc5"], subst, marketed, start, end, base, base_hist,
                                   tiers=True),
        "gleicher_inhaber": _combinations(all_items, lambda it: (it["atc5"], it["holder"]) if it["holder"] else None,
                                          pairs, marketed_pairs, start, end, pbase, pbase_hist),
    }
    for source, sigs in sorted(all_signals.items()):
        by_atc: dict[str, list[date]] = defaultdict(list)
        by_pair: dict[tuple[str, str], list[date]] = defaultdict(list)
        for s in sigs:
            by_atc[s["atc5"]].append(s["date"])
            if s["holder"]:
                by_pair[(s["atc5"], s["holder"])].append(s["date"])
        for v in (*by_atc.values(), *by_pair.values()):
            v.sort()

        # 1a substance onsets in Austria: foreign report on the same ATC5 in the year before?
        onsets = [(a, d) for a, ds in subst.onsets.items() for d in ds if start <= d <= end]
        leads, after_only = [], 0
        for atc5, d in onsets:
            ds = by_atc.get(atc5, [])
            before = [x for x in ds if d - timedelta(days=MAX_LEAD) <= x < d]
            if before:
                leads.append(((d - before[0]).days, (d - before[-1]).days))
            elif any(d <= x <= d + timedelta(days=MAX_LEAD) for x in ds):
                after_only += 1
        sub = _lead_summary(leads, len(onsets))
        sub["nur_danach_im_ausland"] = after_only

        # 1b onsets per substance and holder in Austria: same holder abroad in the year before?
        p_onsets = [(k, d) for k, ds in pairs.onsets.items() for d in ds if start <= d <= end]
        p_leads = []
        for key, d in p_onsets:
            before = [x for x in by_pair.get(key, []) if d - timedelta(days=MAX_LEAD) <= x < d]
            if before:
                p_leads.append(((d - before[0]).days, (d - before[-1]).days))
        pkg = _lead_summary(p_leads, len(p_onsets))

        sources[source] = {
            "land": sigs[0]["country"],
            "meldungen_mit_atc": len(sigs),
            "erste_meldung": min(s["date"] for s in sigs).isoformat(),
            "wirkstoff_neumeldungen": sub,
            "inhaber_neumeldungen": pkg,
            "trefferquote_wirkstoff": _add_lift(_hit_rates(by_atc, subst, marketed, start, end), base, base_hist),
            "trefferquote_gleicher_inhaber": _add_lift(_hit_rates(by_pair, pairs, marketed_pairs, start, end), pbase, pbase_hist),
        }

    return {
        "zeitraum": [start.isoformat(), end.isoformat()],
        "ausgeschlossene_quellen": sorted(exclude_sources),
        "letzter_basg_stand": latest.isoformat(),
        "basg_schnappschuesse": conn.execute("SELECT count(*) FROM snapshots WHERE snapshot_date <= ?", (end.isoformat(),)).fetchone()[0],
        "vermarktete_wirkstoffe_atc5": len(marketed),
        "grundrate_wirkstoff": base,
        "grundrate_wirkstoff_engpass_vorgeschichte": base_hist,
        "grundrate_inhaber": pbase,
        "grundrate_inhaber_engpass_vorgeschichte": pbase_hist,
        "quellen": sources,
        "laender_kombiniert": combined,
        "grenzen": [
            "Die meisten Auslandslisten enthalten nur laufende Meldungen. Vor dem Archivbeginn sind beendete Auslandsmeldungen nur bekannt, "
            "soweit sie in einem Schnappschuss des Internet Archive stehen; kurze Auslandsengpässe zwischen zwei Schnappschüssen fehlen. "
            "Ältere Zeiträume unterschätzen deshalb, wie oft das Ausland vorausging.",
            "Die Grundrate über alle Wirkstoffe überschätzt den Nutzen, weil Auslandsmeldungen vor allem engpassanfällige Wirkstoffe betreffen; "
            "aussagekräftiger ist der Vergleich mit Wirkstoffen, die in Österreich schon einmal knapp waren.",
            "Die BASG-Vorgeschichte vor dem 17.10.2026 stammt aus einzelnen Schnappschüssen; kurze österreichische Engpässe zwischen zwei Schnappschüssen fehlen.",
            "Die Verknüpfung über ATC Ebene 5 ist grob: gleicher Wirkstoff heißt nicht gleiche Stärke, Form oder Hersteller.",
            "Als Signaldatum zählt die erste Veröffentlichung, wo die Quelle sie nennt (BfArM, EMA, CZ, SI, BE, SK: Einreichung); "
            "sonst der Beginn (IT, HU, ES). Dauerhafte Vertriebseinstellungen zählen nicht als Signal.",
            "Länder mit voller Meldehistorie (z. B. CZ, SI, SK) sind in älteren Zeiträumen überrepräsentiert; Kombinationen "
            "mit Ländern ohne Historie erscheinen dort seltener, als sie vorkamen. Fälle desselben Wirkstoffs sind nicht unabhängig.",
        ],
    }


def _rates(d: dict) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v['quote']:.1%}" for k, v in d.items() if v["quote"] is not None)


def _hits(d: dict) -> str:
    return "; ".join(
        f"{k.replace('_', ' ')} {v['treffer']}/{v['faelle']}"
        + (f" = {v['quote']:.1%} [95 %: {v['ki95'][0]:.1%}–{v['ki95'][1]:.1%}] (Lift {v['lift']}×, gegen Vorgeschichte {v['lift_engpass_vorgeschichte']}×)"
           if v["quote"] is not None and v["lift"] is not None else "")
        for k, v in d.items()
    )


def render(r: dict) -> str:
    lines = [
        f"Vorlaufmessung {r['zeitraum'][0]} bis {r['zeitraum'][1]} (BASG-Stand {r['letzter_basg_stand']}, "
        f"{r['basg_schnappschuesse']} Schnappschüsse, {r['vermarktete_wirkstoffe_atc5']} vermarktete Wirkstoffe nach ATC 5)",
        "",
        "Grundrate neue BASG-Meldung, Stichtage alle 14 Tage, nur nicht gemeldete:",
        f"  Wirkstoff: {_rates(r['grundrate_wirkstoff'])}",
        f"  Wirkstoff mit früherem Engpass in AT: {_rates(r['grundrate_wirkstoff_engpass_vorgeschichte'])}",
        f"  Wirkstoff + Inhaber: {_rates(r['grundrate_inhaber'])}",
        f"  Wirkstoff + Inhaber mit früherem Engpass in AT: {_rates(r['grundrate_inhaber_engpass_vorgeschichte'])}",
    ]
    for name, s in r["quellen"].items():
        sub, pkg = s["wirkstoff_neumeldungen"], s["inhaber_neumeldungen"]
        lines += [
            "",
            f"{name.upper()} ({s['land']}): {s['meldungen_mit_atc']} Meldungen mit ATC, erste vom {s['erste_meldung']}",
            f"  Wirkstoff-Neumeldungen in AT: {sub['faelle']}; davon mit Auslandsmeldung im Jahr davor: "
            f"{sub['mit_vorausgehender_auslandsmeldung']} ({(sub['anteil'] or 0):.1%}), nur danach im Ausland: {sub['nur_danach_im_ausland']}",
        ]
        if sub["mit_vorausgehender_auslandsmeldung"]:
            lines.append(
                f"  Vorlauf seit der letzten Auslandsmeldung davor: Median {sub['vorlauf_median_tage']:.0f} Tage, "
                f"Quartile {sub['vorlauf_q25_tage']:.0f}–{sub['vorlauf_q75_tage']:.0f} (seit der frühesten: Median "
                f"{sub['vorlauf_frueheste_median_tage']:.0f}); "
                + ", ".join(f"{k}: {v}" for k, v in sub["vorlauf_verteilung"].items())
            )
        lines += [
            f"  Neumeldungen Wirkstoff + Inhaber in AT: {pkg['faelle']}; davon gleicher Inhaber vorher im Ausland: "
            f"{pkg['mit_vorausgehender_auslandsmeldung']} ({(pkg['anteil'] or 0):.1%})"
            + (f", Vorlauf Median {pkg['vorlauf_median_tage']:.0f} Tage" if pkg["mit_vorausgehender_auslandsmeldung"] else ""),
            f"  Trefferquote nach Auslandsmeldung (Wirkstoff): {_hits(s['trefferquote_wirkstoff'])}",
            f"  Trefferquote nach Auslandsmeldung (gleicher Inhaber): {_hits(s['trefferquote_gleicher_inhaber'])}",
        ]
    for level, c in r.get("laender_kombiniert", {}).items():
        lines += ["", f"Mehrere Länder ({'gleicher Wirkstoff' if level == 'wirkstoff' else 'gleicher Wirkstoff und Inhaber'}): {c['faelle']} Fälle"]
        for n, s in c["nach_zahl_der_laender"].items():
            lines.append(f"  {n} Land/Länder aktiv: {_hits(s)}")
        if c.get("nach_stufe"):
            lines.append("  Hinweisstufen (A: 5+ Länder, B: 3–4 Länder, C: 2 Länder):")
            for tier, s in c["nach_stufe"].items():
                lines.append(f"    {tier}: {_hits(s)}")
        if c.get("zusatznutzen_land_8_wochen"):
            lines.append("  Zusatznutzen je Land (8 Wochen, gleiche Zahl aktiver Länder: mit / ohne dieses Land):")
            for country, row in c["zusatznutzen_land_8_wochen"].items():
                if row:
                    lines.append(f"    {country}: " + "; ".join(
                        f"{b} Länder {v['quote_mit']:.1%} ({v['mit'][0]}/{v['mit'][1]}) / {v['quote_ohne']:.1%}"
                        for b, v in row.items()))
        if c["nach_kombination"]:
            lines.append(f"  Kombinationen mit mindestens {c['mindestfaelle_kombination']} Fällen (sortiert nach 8-Wochen-Quote):")
            for name, s in c["nach_kombination"].items():
                lines.append(f"    {name}: {_hits(s)}")
    lines += ["", "Grenzen:"] + [f"- {g}" for g in r["grenzen"]]
    return "\n".join(lines)


def run(db_path: Path, start: date | None = None, end: date | None = None, json_path: Path | None = None) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        result = measure(conn, start, end)
    finally:
        conn.close()
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
