"""Retrospective tests of further early signals.

Unit is the substance (ATC level 5) as in `vorlauf`; an Austrian onset is the start of a merged
shortage interval of the substance. All tests compare the share of cases followed by an onset within
4/8/12 weeks with a reference group, always among substances without an active Austrian report.

T1 Ausstieg: a company-requested withdrawal of a marketing authorisation (MIA Verlautbarungen, since
   2013) - is a report on *another* product of the same substance more likely afterwards? Split by
   whether the product was marketed (ASP history since 2022-05) and by the remaining marketed holders.
   Variants from the same register: deleted manufacturing sites and changes of the holder.
T2 Preisband: rounds in 2017, 2019, 2021, 2023, 2025 (§ 351c Abs. 11-17 ASVG: lowest price on 1 Feb,
   band published by 30 Jun, prices cut by 1 Oct or deletion from the EKO). Share of a year's
   withdrawals and onsets in Jul-Sep and Oct-Dec, round versus other years, substances with at least
   three marketed products (the law's scope) versus the rest.
T4 Infektionswelle: weekly ILI (ERVISS, AT) and SARI admissions (AT); state of the week before last at
   each Monday (no look-ahead past publication); respiratory/analgesic/antibiotic substances versus
   all others, all onsets and "Erhöhter Mehrbedarf" onsets.
T6 Therapeutische Nachbarn: an active report on another substance of the same ATC level-4 group (AT
   or abroad), or by another holder of the same substance.
T7 GMP: a CEP suspension or withdrawal by EDQM for GMP non-compliance, or an EudraGMDP non-compliance report
   on a CEP holder of the substance (module `gmp`) - is an Austrian report on the substance more likely afterwards?
T8 Marktaustritt: a product marketed in one ASP version and not in the next - is a report on another product of the
   same substance more likely afterwards? (Same comparison as T1.)
T9 EKO: a deletion from the green or yellow box of the Erstattungskodex (RIS, module `eko`) - is a report on another
   product of the same substance more likely afterwards? (Same comparison as T1.) T2 also counts EKO deletions.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import io
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from . import asp
from .archive import Archive
from .build import _unique_files
from .foreign import _ascii, file_day, holder_key
from .substances import atc_groups
from .vorlauf import HORIZONS, Intervals, _base_rates, _d, _signals, _wilson

START = date(2022, 1, 1)
STEP = 14
DEDUP_DAYS = 28
MEHRBEDARF = "Erhöhter Mehrbedarf"
WITHDRAWAL = "Aufhebung der Zulassung human auf Antrag der Firma"
SITE_DELETION = ("A.7 Deletion of manufacturer", "E.5 Deletion of manufacturing sites",
                 "B.3.a) Deletion of a manufacturing site")
PREISBAND_YEARS = (2017, 2019, 2021, 2023, 2025)
RESPIRATORY = ("J01", "N02B", "M01A", "R05", "R03AC", "J05AH")  # report: J01, N02B, R05, M01A (+ notes)
WAVE_HORIZONS = (28, 56)


def _rate(hit: int, n: int) -> dict:
    return {"faelle": n, "treffer": hit, "quote": round(hit / n, 4) if n else None, "ki95": _wilson(hit, n)}


def _lift(a: dict, b: dict) -> float | None:
    return round(a["quote"] / b["quote"], 2) if a["quote"] is not None and b["quote"] else None


def _size_bucket(n: int) -> str:
    return "1" if n <= 1 else "2–3" if n <= 3 else "4–9" if n <= 9 else "10+"


def _sir(observed: int, expected: float) -> dict:
    """Observed / expected hits with Byar's 95 % interval."""
    if expected <= 0:
        return {"erwartet": 0.0, "sir": None, "sir_ki95": None}
    o = observed
    lo = 0.0 if o == 0 else o * (1 - 1 / (9 * o) - 1.96 / (3 * math.sqrt(o))) ** 3 / expected
    hi = (o + 1) * (1 - 1 / (9 * (o + 1)) + 1.96 / (3 * math.sqrt(o + 1))) ** 3 / expected
    return {"erwartet": round(expected, 1), "sir": round(o / expected, 2), "sir_ki95": [round(lo, 2), round(hi, 2)]}


class Strata:
    """Onset rates per stratum (number of marketed products of the substance, earlier Austrian shortage,
    calendar year) on 14-day reference dates. Expected hits of a group of cases = sum of their strata's rates, so
    SIR = observed / expected removes the effect of large and shortage-prone substances."""

    def __init__(self, subst: Intervals, marketed: set, size: dict[str, int], start: date, end: date):
        self.subst, self.size = subst, size
        tally: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        t = start
        while t <= end - timedelta(days=min(HORIZONS)):
            for k in marketed:
                if subst.active(k, t):
                    continue
                s = self.of(k, t)
                for h in HORIZONS:
                    if t <= end - timedelta(days=h):
                        tally[(h, s)][0] += subst.onset_within(k, t, h)
                        tally[(h, s)][1] += 1
            t += timedelta(days=STEP)
        self.rate = {key: hit / n for key, (hit, n) in tally.items() if n}

    def of(self, k: str, t: date) -> tuple:
        return _size_bucket(self.size.get(k, 0)), self.subst.had_onset_before(k, t), t.year

    def expected(self, k: str, t: date, h: int) -> float:
        return self.rate.get((h, self.of(k, t)), 0.0)


def _exposure(tally: dict, which: int) -> dict:
    """tally: (h, stratum, a, b) -> [hits, cases]. Exposure a (which=0) or b (which=1), compared within
    strata that include the other exposure: crude rates and SIR against the unexposed rates."""
    out = {}
    for h in HORIZONS:
        groups: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
        for (hh, stratum, a, b), (hit, n) in tally.items():
            if hh != h:
                continue
            exposed, other = (a, b) if which == 0 else (b, a)
            g = groups[(stratum, other)]
            j = 0 if exposed else 2
            g[j] += hit
            g[j + 1] += n
        mit = _rate(sum(g[0] for g in groups.values()), sum(g[1] for g in groups.values()))
        ohne = _rate(sum(g[2] for g in groups.values()), sum(g[3] for g in groups.values()))
        observed = sum(g[0] for g in groups.values() if g[3])
        expected = sum(g[1] * g[2] / g[3] for g in groups.values() if g[3])
        out[f"{h // 7}_wochen"] = {"mit": mit, "ohne": ohne, "lift_roh": _lift(mit, ohne), **_sir(observed, expected)}
    return out


# --- data ---------------------------------------------------------------------------------------

def _latest(archive: Archive, source: str) -> bytes | None:
    files = _unique_files(archive, source)
    return archive.read(max(files, key=lambda e: (e.get("fetched_at") or "", e["path"]))["path"]) if files else None


def _csv(body: bytes, delimiter: str = ",") -> list[dict]:
    return list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""), delimiter=delimiter))


class AspHistory:
    """Marketed ("lieferbar") products per ASP version: zulassungsnummer -> (marketed, atc5, holder).
    `captured`: version day -> day of its first capture (TermGit captured_at, live the first fetch)."""

    def __init__(self, versions: list[tuple[date, dict[str, tuple[bool, str | None, str | None]]]],
                 captured: dict[date, date] | None = None):
        self.versions = sorted(versions, key=lambda v: v[0])
        self.days = [d for d, _ in self.versions]
        self.captured = captured or {}
        self.atc = {}
        for _, prods in self.versions:
            for zl, (_, atc5, _) in prods.items():
                if atc5:
                    self.atc[zl] = atc5

    @classmethod
    def load(cls, archive: Archive) -> "AspHistory":
        versions, seen, captured = [], set(), {}
        for e in _unique_files(archive, "asp"):
            day = date.fromisoformat(Path(e["path"]).name[:10])
            if day in seen:
                continue
            seen.add(day)
            captured[day] = date.fromisoformat(file_day(e))
            with gzip.open(archive.root / e["path"]) as fh:
                _, rows = asp.parse(fh)
            prods: dict[str, tuple[bool, str | None, str | None]] = {}
            for r in rows:
                zl = r["zulassungsnummer"]
                if not zl or not r["valid"]:
                    continue
                old = prods.get(zl)
                prods[zl] = (bool(r["lieferbar"]) or bool(old and old[0]), atc_groups(r["atc"])[0], holder_key(r["inhaber"]))
            versions.append((day, prods))
        return cls(versions, captured)

    def before(self, d: date) -> dict | None:
        i = bisect.bisect_left(self.days, d) - 1
        return self.versions[i][1] if i >= 0 else None

    def known_before(self, d: date) -> dict | None:
        """The newest version dated before d that was captured by day d (point in time; `before` ignores capture)."""
        i = bisect.bisect_left(self.days, d) - 1
        while i >= 0 and self.captured.get(self.days[i], self.days[i]) > d:
            i -= 1
        return self.versions[i][1] if i >= 0 else None

    def marketed_holders(self, prods: dict, atc5: str, exclude: set[str]) -> set[str]:
        return {h or zl for zl, (m, a, h) in prods.items() if m and a == atc5 and zl not in exclude}


def mia_events(body: bytes, atc_of: dict[str, str]) -> list[dict]:
    """Human-medicine events from the MIA Verlautbarungen export; date = BASG vote ("Genehmigt am"), else closure.

    "inhaberwechsel" is any change of the holder entry ("Inhaber:in bisher" filled): a transfer to another company,
    a transfer within a group, or a new name or address. All three precede reports (the holder is printed on the
    pack, so each forces a changeover); `same_company` tells them apart for display."""
    out = []
    for r in _csv(body):
        if "human" not in r["Verfahrenstyp"]:
            continue
        kinds = []
        if r["Verfahrenstyp"] == WITHDRAWAL:
            kinds.append("aufhebung")
        if any(p.startswith(SITE_DELETION) for p in r["Klassifizierung"].split(" | ")):
            kinds.append("standort")
        holder, prev = holder_key(r["Inhaber:in"]), holder_key(r["Inhaber:in bisher"])
        if r["Inhaber:in bisher"]:
            kinds.append("inhaberwechsel")
        day = _d(r["Genehmigt am"] or r["Verfahren abgeschlossen am"])
        zl = r["Zulassungsnummer"].strip()
        atc5 = atc_groups(r["ATC Code"])[0] or atc_of.get(zl)
        for k in kinds:
            if day and atc5:
                out.append({"kind": k, "date": day, "zl": zl, "atc5": atc5, "holder": holder,
                            "holder_name": _company(r["Inhaber:in"]), "prev_name": _company(r["Inhaber:in bisher"]),
                            "same_company": holder == prev, "product": r.get("Betrachtungsobjekt", "")})
    return out


def _company(holder: str) -> str:
    """Company name without the address MIA appends ("Name, Street, City, Country")."""
    return holder.split(",")[0].strip()


def _episode_rows(conn: sqlite3.Connection, latest: date) -> list[dict]:
    out = []
    for atc5, start, end_upper, active, holder, grund, zl in conn.execute(
        "SELECT e.atc5, e.start_date, e.end_upper, e.active, e.zulassungsinhaber, e.grund, p.zulassungsnummer "
        "FROM episodes e LEFT JOIN packages p USING (package_key) WHERE e.atc5 IS NOT NULL"
    ):
        s = _d(start)
        e = latest if active or not end_upper else _d(end_upper)
        if s and e and s <= latest:
            out.append({"atc5": atc5, "start": s, "end": max(e, s), "holder": holder_key(holder), "grund": grund, "zl": zl})
    return out


# --- T1: events of other products ---------------------------------------------------------------

def event_outcomes(cases: list[tuple[str, date, frozenset]], eps_by_atc: dict[str, list[dict]],
                   end: date) -> list[dict]:
    """Per case (substance, day, products to ignore): Austrian onset of another product within h days?

    A case counts only if no other product of the substance has an active report on that day.
    """
    cache: dict[tuple[str, frozenset], Intervals] = {}
    out = []
    for atc5, d, exclude in cases:
        key = (atc5, exclude)
        if key not in cache:
            cache[key] = Intervals([(atc5, e["start"], e["end"]) for e in eps_by_atc.get(atc5, []) if e["zl"] not in exclude])
        iv = cache[key]
        if iv.active(atc5, d):
            continue
        out.append({"atc5": atc5, "date": d, "hits": {h: iv.onset_within(atc5, d, h) for h in HORIZONS if d <= end - timedelta(days=h)}})
    return out


def _summarise(cases: list[dict], base: dict, strata: Strata) -> dict:
    out = {}
    for h in HORIZONS:
        usable = [c for c in cases if h in c["hits"]]
        hit = sum(c["hits"][h] for c in usable)
        r = _rate(hit, len(usable))
        k = f"{h // 7}_wochen"
        r["lift"] = _lift(r, base[k])
        r.update(_sir(hit, sum(strata.expected(c["atc5"], c["date"], h) for c in usable)))
        out[k] = r
    return out


def _bucket(n: int) -> str:
    return "0" if n == 0 else "1" if n == 1 else "2–3" if n <= 3 else "4+"


def _event_entry(evs: list[dict], exclude_self: bool, eps_by_atc: dict, hist: AspHistory, marketed: set, start: date,
                 end: date, base: dict, strata: Strata) -> dict:
    """Cases per substance and day (repeats within 28 days merged). `exclude_self`: the product leaves the market, so
    only reports on other products count; otherwise any report counts, and separately only other products."""
    grouped: dict[tuple[str, date], set[str]] = defaultdict(set)
    for e in evs:
        if e["atc5"] in marketed and start <= e["date"] <= end:
            grouped[(e["atc5"], e["date"])].add(e["zl"])
    cases, others, meta, last = [], [], {}, {}
    for (atc5, d), zls in sorted(grouped.items()):
        if atc5 in last and (d - last[atc5]).days < DEDUP_DAYS:
            continue
        last[atc5] = d
        cases.append((atc5, d, frozenset(zls) if exclude_self else frozenset()))
        others.append((atc5, d, frozenset(zls)))
        prods = hist.before(d)
        if prods is None:
            meta[(atc5, d)] = ("unbekannt", None)
        else:
            was = any(prods.get(z, (False,))[0] for z in zls)
            meta[(atc5, d)] = ("ja" if was else "nein", len(hist.marketed_holders(prods, atc5, set(zls))))
    outcomes = event_outcomes(cases, eps_by_atc, end)
    entry = {"ereignisse": len(evs), "faelle": len(outcomes), "alle": _summarise(outcomes, base, strata)}
    if not exclude_self:
        entry["nur_andere_produkte"] = _summarise(event_outcomes(others, eps_by_atc, end), base, strata)
    groups: dict[str, list] = defaultdict(list)
    rest: dict[str, list] = defaultdict(list)
    for c in outcomes:
        was, n_rest = meta[(c["atc5"], c["date"])]
        groups[was].append(c)
        if was == "ja":
            rest[_bucket(n_rest)].append(c)
    entry["vermarktet"] = {k: _summarise(v, base, strata) for k, v in sorted(groups.items())}
    entry["vermarktet_nach_verbleibenden_anbietern"] = {k: _summarise(rest[k], base, strata)
                                                         for k in ("0", "1", "2–3", "4+") if rest.get(k)}
    return entry


def test_ausstieg(events: list[dict], eps_by_atc: dict, hist: AspHistory, marketed: set, start: date, end: date,
                  base: dict, strata: Strata) -> dict:
    # withdrawals: the product itself leaves; site/holder changes: any further report counts
    return {kind: _event_entry([e for e in events if e["kind"] == kind], kind == "aufhebung", eps_by_atc, hist,
                               marketed, start, end, base, strata)
            for kind in ("aufhebung", "standort", "inhaberwechsel")}


# --- T8: market exits from the ASP history ------------------------------------------------------

def asp_exits(hist: AspHistory, eps: list[dict]) -> list[dict]:
    """Products marketed ("lieferbar") in one ASP version and not in the next (not lieferbar or no longer listed).

    Date = the first version without it (when the exit becomes visible). `own`: the product itself had an active
    Austrian report between the two versions, i.e. the flag may mirror a shortage rather than an exit. `back`
    (known only in hindsight): marketed again in a later version."""
    own_eps: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        if e["zl"]:
            own_eps[e["zl"]].append(e)
    out = []
    v = hist.versions
    for i in range(1, len(v)):
        (d0, before), (d1, now) = v[i - 1], v[i]
        for zl, (marketed, atc5, holder) in before.items():
            nxt = now.get(zl)
            if not marketed or not atc5 or (nxt and nxt[0]):
                continue
            out.append({"kind": "marktaustritt", "date": d1, "zl": zl, "atc5": atc5, "holder": holder,
                        "gone": nxt is None, "back": any(later.get(zl, (False,))[0] for _, later in v[i + 1:]),
                        "own": any(e["start"] <= d1 and e["end"] >= d0 for e in own_eps.get(zl, []))})
    return out


def test_marktaustritt(exits: list[dict], eps_by_atc: dict, hist: AspHistory, marketed: set, start: date, end: date,
                       base: dict, strata: Strata) -> dict:
    """Pre-specified: exits without an own active report; the rest and the later course are shown separately."""
    clean = [e for e in exits if not e["own"]]
    entry = _event_entry(clean, True, eps_by_atc, hist, marketed, start, end, base, strata)
    entry["austritte_gesamt"] = len(exits)
    entry["mit_eigener_meldung"] = _event_entry([e for e in exits if e["own"]], True, eps_by_atc, hist, marketed,
                                                start, end, base, strata)
    entry["nach_verlauf"] = {name: _event_entry([e for e in clean if e["back"] == back], True, eps_by_atc, hist,
                                                marketed, start, end, base, strata)["alle"]
                             for name, back in (("dauerhaft", False), ("wieder_lieferbar", True))}
    return entry


# --- T9: deletions from the Erstattungskodex -----------------------------------------------------

def name_key(name: str) -> tuple[str, ...]:
    """First two name words before the strength or the form, without abbreviations ending in a full stop:
    'Atenolol "Genericon" comp. mite Filmtabl.' and 'Atenolol "Genericon" comp. mite - Filmtabletten' -> (atenolol, genericon)."""
    head = re.split(r"\s-\s|\d", name or "", maxsplit=1)[0]
    words = [w for w in re.findall(r"[^\s\"„“”]+", head) if not w.endswith(".")]
    return tuple(re.sub(r"[^a-z]", "", _ascii(w).lower()) for w in words[:2])


def eko_events(archive: Archive, approval_names: list[tuple[str, str, str]]) -> list[dict]:
    """Deletions from the green and yellow box (module `eko`), dated on the day the change was published.

    `approval_names`: (Zulassungsnummer, ATC5, name) from the ASP list, to leave out the deleted product's own
    reports; a product no longer in the ASP list keeps a placeholder (its own reports then count)."""
    from . import eko
    from .foreign import file_day

    by_key: dict[tuple, set[str]] = defaultdict(set)
    for zl, atc5, name in approval_names:
        by_key[(atc5, name_key(name))].add(zl)
    out = []
    for e in _unique_files(archive, "eko"):
        day = date.fromisoformat(file_day(e))
        try:
            rows = eko.parse(archive.read(e["path"]))
        except Exception:  # noqa: BLE001 - an unreadable document must not stop the test
            continue
        for r in rows:
            if r["box"] == "rot":
                continue  # withdrawn applications, never in the code
            zls = by_key.get((r["atc"], name_key(r["product"]))) or {f"eko:{r['product']}"}
            for zl in sorted(zls):
                out.append({"kind": "eko_streichung", "date": day, "zl": zl, "atc5": r["atc"], "grund": r["grund"],
                            "box": r["box"], "product": r["product"], "verfahren": r["verfahren"]})
    return out


def test_eko(events: list[dict], eps_by_atc: dict, hist: AspHistory, marketed: set, start: date, end: date,
             base: dict, strata: Strata) -> dict:
    """Pre-specified: all deletions from green and yellow; split by the reason in the footnotes."""
    entry = _event_entry(events, True, eps_by_atc, hist, marketed, start, end, base, strata)
    entry["streichungen_gesamt"] = len({(e["date"], e["product"]) for e in events})
    entry["nach_grund"] = {g: _event_entry([e for e in events if e["grund"] == g], True, eps_by_atc, hist, marketed,
                                           start, end, base, strata)["alle"]
                           for g in ("zulassung", "nicht_lieferbar", "ohne_fussnote", "sonst")
                           if any(e["grund"] == g for e in events)}
    return entry


# --- T2: Preisband rounds -----------------------------------------------------------------------

def _share(counts: dict[int, list[int]], years: list[int], months: range) -> dict:
    hit = sum(counts[y][m - 1] for y in years for m in months)
    n = sum(sum(counts[y]) for y in years)
    return _rate(hit, n)


def test_preisband(withdrawals: list[tuple[str, date]], onsets: list[tuple[str, date]], scope: set[str],
                   eko_deletions: list[tuple[str, date]] | None = None) -> dict:
    """Share of a year's events in Jul-Sep and Oct-Dec; uniform would be 25 % each."""
    out = {}
    series_in = [("aufhebungen", withdrawals, range(2014, 2026)), ("basg_meldungen", onsets, range(2021, 2026))]
    if eko_deletions:
        series_in.append(("eko_streichungen", eko_deletions, range(2006, 2026)))
    for name, events, years in series_in:
        series = {}
        for group, members in (("generikakonkurrenz", True), ("uebrige", False)):
            counts: dict[int, list[int]] = defaultdict(lambda: [0] * 12)
            for atc5, d in events:
                if (atc5 in scope) == members and d.year in years:
                    counts[d.year][d.month - 1] += 1
            rounds = [y for y in years if y in PREISBAND_YEARS]
            other = [y for y in years if y not in PREISBAND_YEARS]
            series[group] = {
                "jahre_runde": rounds, "jahre_sonst": other,
                "jul_sep": {"runde": _share(counts, rounds, range(7, 10)), "sonst": _share(counts, other, range(7, 10))},
                "okt_dez": {"runde": _share(counts, rounds, range(10, 13)), "sonst": _share(counts, other, range(10, 13))},
                "je_jahr": {y: {"jan_jun": sum(counts[y][:6]), "jul_sep": sum(counts[y][6:9]), "okt_dez": sum(counts[y][9:])}
                            for y in years},
            }
        out[name] = series
    return out


# --- T4: infection waves ------------------------------------------------------------------------

def _monday(year: int, week: int) -> date:
    return date.fromisocalendar(year, week, 1)


def ili_series(body: bytes) -> dict[date, float]:
    out = {}
    for r in _csv(body):
        if r["countryname"] == "Austria" and r["indicator"] == "ILIconsultationrate" and r["age"] == "total" and r["value"]:
            y, w = r["yearweek"].split("-W")
            out[_monday(int(y), int(w))] = float(r["value"])
    return out


def sari_series(body: bytes) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for r in _csv(body, ";"):
        out[_monday(int(r["JAHR"]), int(r["KW"]))] += float(r["AUFNAHMEN"] or 0)
    return dict(out)


def wave_states(series: dict[date, float]) -> dict[date, str]:
    """State known on each Monday: value of the week before last against the upper third of all weeks."""
    if not series:
        return {}
    values = sorted(series.values())
    high = values[int(len(values) * 2 / 3)]
    out = {}
    for week in sorted(series):
        t = week + timedelta(days=14)
        v, prev = series[week], series.get(week - timedelta(days=14))
        out[t] = ("hoch_steigend" if prev is not None and v > prev else "hoch") if v >= high else "niedrig"
    return out


def test_welle(states: dict[date, str], subst: Intervals, mb: Intervals, marketed: set, end: date,
               skip: tuple[date, date] | None = None) -> dict:
    target = {a for a in marketed if a.startswith(RESPIRATORY)}
    groups = {"atemwege_schmerz_antibiotika": target, "uebrige": marketed - target}
    out = {}
    for gname, keys in groups.items():
        g = {}
        for oname, iv in (("alle_meldungen", subst), ("mehrbedarf", mb)):
            rows = {}
            for h in WAVE_HORIZONS:
                tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
                for t, state in states.items():
                    if t > end - timedelta(days=h) or (skip and skip[0] <= t <= skip[1]):
                        continue
                    for k in keys:
                        if not subst.active(k, t):
                            tally[state][0] += iv.onset_within(k, t, h)
                            tally[state][1] += 1
                hoch = [sum(tally[s][i] for s in ("hoch", "hoch_steigend")) for i in (0, 1)]
                tally["hoch_gesamt"] = hoch
                res = {s: _rate(*tally[s]) for s in ("niedrig", "hoch_gesamt", "hoch_steigend") if tally[s][1]}
                for s in ("hoch_gesamt", "hoch_steigend"):
                    if s in res and "niedrig" in res:
                        res[s]["lift_gegen_niedrig"] = _lift(res[s], res["niedrig"])
                rows[f"{h // 7}_wochen"] = res
            g[oname] = rows
        out[gname] = g
    return out


# --- T6: therapeutic neighbours -----------------------------------------------------------------

def neighbour_rates(subst: Intervals, foreign: list[dict], marketed: set, size: dict[str, int],
                    start: date, end: date) -> dict:
    """Reference dates every 14 days. Exposure a: active Austrian report on another substance of the same
    ATC4 group; b: the same abroad. Strata: substance size, size of the ATC4 group, earlier Austrian shortage,
    own foreign report, calendar year."""
    group = Counter(k[:5] for k in marketed)
    tally: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    t = start
    while t <= end - timedelta(days=min(HORIZONS)):
        at4: dict[str, set] = defaultdict(set)
        ab4: dict[str, set] = defaultdict(set)
        for k in subst.intervals:
            if subst.active(k, t):
                at4[k[:5]].add(k)
        own = set()
        for it in foreign:
            if it["date"] <= t <= it["until"]:
                ab4[it["atc5"][:5]].add(it["atc5"])
                own.add(it["atc5"])
        for k in marketed:
            if subst.active(k, t):
                continue
            a, b = bool(at4.get(k[:5], set()) - {k}), bool(ab4.get(k[:5], set()) - {k})
            stratum = (_size_bucket(size.get(k, 0)), _size_bucket(group[k[:5]]), subst.had_onset_before(k, t), k in own, t.year)
            for h in HORIZONS:
                if t <= end - timedelta(days=h):
                    cell = tally[(h, stratum, a, b)]
                    cell[0] += subst.onset_within(k, t, h)
                    cell[1] += 1
        t += timedelta(days=STEP)
    return {"nachbar_in_at": _exposure(tally, 0), "nachbar_im_ausland": _exposure(tally, 1)}


def other_holder_rates(pairs: Intervals, marketed_pairs: set, start: date, end: date) -> dict:
    """Substance + holder without a report: is another holder of the same substance in shortage?
    Strata: number of marketed holders of the substance, earlier shortage of this holder's product, year."""
    holders = Counter(a for a, _ in marketed_pairs)
    tally: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    t = start
    while t <= end - timedelta(days=min(HORIZONS)):
        active_by_atc: dict[str, set] = defaultdict(set)
        for (a, holder) in pairs.intervals:
            if pairs.active((a, holder), t):
                active_by_atc[a].add(holder)
        for key in marketed_pairs:
            if pairs.active(key, t):
                continue
            other = bool(active_by_atc.get(key[0], set()) - {key[1]})
            stratum = (_size_bucket(holders[key[0]]), pairs.had_onset_before(key, t), t.year)
            for h in HORIZONS:
                if t <= end - timedelta(days=h):
                    cell = tally[(h, stratum, other, None)]
                    cell[0] += pairs.onset_within(key, t, h)
                    cell[1] += 1
        t += timedelta(days=STEP)
    return _exposure(tally, 0)


# --- T7: GMP events of active-substance manufacturers --------------------------------------------

def _holder_bucket(n: int) -> str:
    return "1" if n <= 1 else "2–3" if n <= 3 else "4+"


def test_gmp(events: list[dict], eps_by_atc: dict, marketed: set, start: date, end: date, base: dict,
             strata: Strata, holders: dict[str, int]) -> dict:
    """Cases per substance and event day (repeats within 28 days merged); split by valid CEP holders today."""
    cases, last = [], {}
    for atc5, d in sorted({(e["atc5"], e["date"]) for e in events if e["atc5"] in marketed and start <= e["date"] <= end}):
        if atc5 in last and (d - last[atc5]).days < DEDUP_DAYS:
            continue
        last[atc5] = d
        cases.append((atc5, d, frozenset()))
    outcomes = event_outcomes(cases, eps_by_atc, end)
    groups: dict[str, list] = defaultdict(list)
    for c in outcomes:
        groups[_holder_bucket(holders.get(c["atc5"], 0))].append(c)
    return {"ereignisse": len(events), "faelle": len(outcomes), "alle": _summarise(outcomes, base, strata),
            "nach_gueltigen_cep_haltern": {k: _summarise(groups[k], base, strata) for k in ("1", "2–3", "4+") if groups.get(k)}}


# --- run ----------------------------------------------------------------------------------------

def measure(conn: sqlite3.Connection, archive: Archive, start: date = START, end: date | None = None) -> dict:
    latest = _d(conn.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0])
    end = end or latest
    eps = _episode_rows(conn, latest)
    eps_by_atc: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        eps_by_atc[e["atc5"]].append(e)
    subst = Intervals([(e["atc5"], e["start"], e["end"]) for e in eps])
    mb = Intervals([(e["atc5"], e["start"], e["end"]) for e in eps if e["grund"] == MEHRBEDARF])
    asp_rows = conn.execute("SELECT atc, inhaber FROM asp_packages WHERE valid = 1 AND length(atc) >= 7").fetchall()
    marketed = {atc[:7] for atc, _ in asp_rows}
    marketed_pairs = {(atc[:7], holder_key(inh)) for atc, inh in asp_rows if holder_key(inh)}
    base, base_hist = _base_rates(subst, marketed, start, end)
    size = Counter(atc[:7] for atc, _ in conn.execute(
        "SELECT DISTINCT atc, zulassungsnummer FROM asp_packages WHERE valid = 1 AND length(atc) >= 7"))
    strata = Strata(subst, marketed, size, start, end)

    hist = AspHistory.load(archive)
    verl = _latest(archive, "mia_verl")
    events = mia_events(verl, hist.atc) if verl else []
    t1 = test_ausstieg(events, eps_by_atc, hist, marketed, start, end, base, strata) if events else None
    t8 = test_marktaustritt(asp_exits(hist, eps), eps_by_atc, hist, marketed, start, end, base, strata) if hist.versions else None
    if t1:  # exploratory split, the definition itself stays the pre-specified broad one
        t1["inhaberwechsel"]["nach_art"] = {}
        for name, same in (("andere_firma", False), ("gleiche_firma", True)):
            sub = test_ausstieg([e for e in events if e["kind"] == "inhaberwechsel" and e["same_company"] == same],
                                eps_by_atc, hist, marketed, start, end, base, strata)["inhaberwechsel"]
            t1["inhaberwechsel"]["nach_art"][name] = {"alle": sub["alle"], "vermarktet": sub["vermarktet"].get("ja")}

    mid = hist.versions[len(hist.versions) // 2][1] if hist.versions else {}
    n_products: dict[str, set] = defaultdict(set)
    for zl, (m, a, _) in mid.items():
        if m and a:
            n_products[a].add(zl)
    scope = {a for a, zls in n_products.items() if len(zls) >= 3}
    withdrawals = sorted({(e["atc5"], e["date"]) for e in events if e["kind"] == "aufhebung"})
    onsets = [(a, d) for a, ds in subst.onsets.items() for d in ds]
    names = [(zl, (atc or "")[:7], name) for zl, atc, name in conn.execute(
        "SELECT DISTINCT zulassungsnummer, atc, approval_name FROM asp_packages WHERE approval_name != ''")]
    eko_ev = eko_events(archive, names)
    t9 = test_eko(eko_ev, eps_by_atc, hist, marketed, start, end, base, strata) if eko_ev else None
    eko_deletions = sorted({(e["atc5"], e["date"]) for e in eko_ev})
    t2 = test_preisband(withdrawals, onsets, scope, eko_deletions) if events else None

    t4 = {}
    ili_body, sari_body = _latest(archive, "erviss_ili"), _latest(archive, "sari_region")
    if ili_body:
        states = wave_states(ili_series(ili_body))
        t4["ili"] = {"wochen": len(states), "alle": test_welle(states, subst, mb, marketed, end),
                     "ohne_saison_2022_23": test_welle(states, subst, mb, marketed, end, (date(2022, 10, 1), date(2023, 4, 30)))}
    if sari_body:
        states = wave_states(sari_series(sari_body))
        t4["sari"] = {"wochen": len(states), "alle": test_welle(states, subst, mb, marketed, end)}

    foreign = [it for items in _signals(conn, latest).values() for it in items]
    pairs = Intervals([((e["atc5"], e["holder"]), e["start"], e["end"]) for e in eps if e["holder"]])
    t6 = {"atc4_nachbarn": neighbour_rates(subst, foreign, marketed, size, start, end),
          "anderer_inhaber_gleicher_wirkstoff": other_holder_rates(pairs, marketed_pairs, start, end)}

    from . import gmp
    asp_dicts = [dict(zip(("pzn", "name", "atc", "substances", "valid", "inhaber"), r)) for r in conn.execute(
        "SELECT pzn, name, atc, substances, valid, inhaber FROM asp_packages")]
    g = gmp.load(archive, asp_dicts)
    t7 = None
    if g["n_ceps"]:
        t7 = {"cep_aussetzung": test_gmp(g["cep_events"], eps_by_atc, marketed, start, end, base, strata, g["valid_holders"]),
              "ncr_bericht": test_gmp(g["ncr_events"], eps_by_atc, marketed, start, end, base, strata, g["valid_holders"]),
              "beide": test_gmp(g["cep_events"] + g["ncr_events"], eps_by_atc, marketed, start, end, base, strata, g["valid_holders"])}

    return {
        "zeitraum": [start.isoformat(), end.isoformat()],
        "letzter_basg_stand": latest.isoformat(),
        "vermarktete_wirkstoffe_atc5": len(marketed),
        "asp_fassungen": [hist.days[0].isoformat(), hist.days[-1].isoformat(), len(hist.days)] if hist.days else None,
        "grundrate_wirkstoff": base,
        "grundrate_wirkstoff_engpass_vorgeschichte": base_hist,
        "t1_ausstieg": t1,
        "t2_preisband": t2,
        "t2_wirkstoffe_mit_generikakonkurrenz": len(scope),
        "t4_infektionswelle": t4,
        "t6_nachbarn": t6,
        "t7_gmp": t7,
        "t8_marktaustritt": t8,
        "t9_eko_streichung": t9,
        "grenzen": [
            "Die BASG-Vorgeschichte vor dem 17.10.2026 stammt aus einzelnen Schnappschüssen; kurze Engpässe dazwischen fehlen.",
            "T1: Datum ist die BASG-Abstimmung („Genehmigt am“), sonst der Verfahrensabschluss. Ob ein Produkt vermarktet war, "
            "zeigt erst die ASP-Historie ab Mai 2022; die Zahl der verbleibenden Anbieter zählt Inhaber mit lieferbaren Packungen.",
            "T2: Wirkstoffe mit Generikakonkurrenz = mindestens drei lieferbare Produkte in der mittleren ASP-Fassung, nicht die "
            "EKO-Liste; EKO-Streichungen (RIS) fehlen noch. Wenige Jahre je Gruppe, daher nur beschreibend.",
            "T4: ERVISS-ILI für Österreich nur in der Saison (Kalenderwoche 40 bis etwa 14), SARI ganzjährig ab 2023-W19. "
            "„Hoch“ heißt oberes Drittel aller Wochen der Reihe (eine Schwelle aus der ganzen Reihe, also rückblickend gewählt).",
            "T6: Auslandsmeldungen vor dem Archivbeginn sind nur über Schnappschüsse bekannt; die Ausland-Schichten sind in "
            "älteren Zeiträumen unterbesetzt. Stichtage desselben Wirkstoffs sind nicht unabhängig.",
            "T7: Die CEP-Datei zeigt nur den heutigen Status; von der EDQM wieder aufgehobene Aussetzungen fehlen. "
            "Die EudraGMDP-Liste nennt keine Wirkstoffe; Zuordnung über CEP-Halter (Standort-ID, sonst Firmenname und Land). "
            "Ein Wirkstoffhersteller wird allen österreichischen ATC-Codes seines Wirkstoffs zugeordnet. Zahl gültiger "
            "CEP-Halter = heutiger Stand.",
            "T9: Datum ist die Kundmachung der EKO-Änderung im RIS (Wirkung meist zum Monatsersten danach). Grund laut "
            "Fußnote; Streichungen ohne Fußnote sind seit etwa 2016 meist Verfahren nach Abschnitt VIII oder V der VO-EKO. "
            "Eigene Meldungen des gestrichenen Produkts bleiben nur außen vor, wenn es noch in der ASP-Liste steht.",
            "T8: ASP-Fassungen etwa monatlich (Mai 2022 bis Juni 2026); Datum = erste Fassung ohne Lieferbarkeit, der "
            "Austritt liegt also bis zu einem Monat früher. „Nicht lieferbar“ kann auch einen Engpass des Produkts selbst "
            "anzeigen; Austritte mit eigener aktiver Meldung stehen getrennt. „Wieder lieferbar“ ist erst im Nachhinein bekannt.",
            "Vermarktete Wirkstoffe stammen aus der aktuellen ASP-Liste; ältere Stichtage enthalten daher keine inzwischen "
            "verschwundenen Wirkstoffe.",
        ],
    }


def _fmt(r: dict) -> str:
    if not r or r.get("quote") is None:
        return f"{r.get('treffer', 0)}/{r.get('faelle', 0)}" if r else "–"
    s = f"{r['treffer']}/{r['faelle']} = {r['quote']:.1%} [{r['ki95'][0]:.1%}–{r['ki95'][1]:.1%}]"
    for k, label in (("lift", "Lift roh"), ("lift_gegen_niedrig", "gg. niedrig")):
        if r.get(k) is not None:
            s += f" {label} {r[k]}×"
    return s + _fmt_sir(r)


def _fmt_sir(r: dict) -> str:
    if r.get("sir") is None:
        return ""
    return f", bereinigt {r['sir']}× [{r['sir_ki95'][0]}–{r['sir_ki95'][1]}]"


def _fmt_exposure(v: dict) -> str:
    return (f"mit {_fmt(v['mit'])} | ohne {_fmt(v['ohne'])} | roh {v['lift_roh']}×{_fmt_sir(v)}")


def render(r: dict) -> str:
    lines = [f"Rückblicktests {r['zeitraum'][0]} bis {r['zeitraum'][1]} (BASG-Stand {r['letzter_basg_stand']}, "
             f"{r['vermarktete_wirkstoffe_atc5']} vermarktete Wirkstoffe nach ATC 5)", "",
             "Grundrate neue BASG-Meldung je Wirkstoff (Stichtage alle 14 Tage, nur nicht gemeldete). „Bereinigt“ = "
             "beobachtete / erwartete Treffer, erwartet aus Wirkstoffen gleicher Produktzahl, gleicher "
             "Engpass-Vorgeschichte und gleichen Jahres (1 = kein Zusatznutzen):"]
    for k in r["grundrate_wirkstoff"]:
        lines.append(f"  {k.replace('_', ' ')}: alle {r['grundrate_wirkstoff'][k]['quote']:.1%}, "
                     f"mit früherem Engpass {r['grundrate_wirkstoff_engpass_vorgeschichte'][k]['quote']:.1%}")
    names = {"aufhebung": "Zulassung auf Antrag aufgehoben", "standort": "Herstellerstandort gestrichen",
             "inhaberwechsel": "Änderung beim Zulassungsinhaber (Wechsel, Name oder Adresse)"}
    if r["t1_ausstieg"]:
        lines += ["", "T1 Ereignisse aus den MIA-Verlautbarungen → Meldung eines anderen Produkts desselben Wirkstoffs:"]
        for kind, e in r["t1_ausstieg"].items():
            lines.append(f"  {names[kind]} ({e['ereignisse']} Einträge, {e['faelle']} Fälle):")
            for k, v in e["alle"].items():
                lines.append(f"    {k.replace('_', ' ')}: {_fmt(v)}")
            if "nur_andere_produkte" in e:
                lines.append(f"    nur andere Produkte, 8 Wochen: {_fmt(e['nur_andere_produkte']['8_wochen'])}")
            for was, s in e["vermarktet"].items():
                lines.append(f"    vermarktet {was}: 8 Wochen {_fmt(s['8_wochen'])}")
            for b, s in e["vermarktet_nach_verbleibenden_anbietern"].items():
                lines.append(f"      verbleibende Anbieter {b}: 8 Wochen {_fmt(s['8_wochen'])}")
            for art, s in e.get("nach_art", {}).items():
                lines.append(f"    {art.replace('_', ' ')} (explorativ): 8 Wochen {_fmt(s['alle']['8_wochen'])}")
    if r["t2_preisband"]:
        lines += ["", f"T2 Preisband-Runden {', '.join(map(str, PREISBAND_YEARS))} – Anteil am Jahr "
                  f"(gleichmäßig wären 25 %; Generikakonkurrenz: {r['t2_wirkstoffe_mit_generikakonkurrenz']} Wirkstoffe):"]
        for series, groups in r["t2_preisband"].items():
            for g, s in groups.items():
                lines.append(f"  {series} / {g}: Jul–Sep Runde {_fmt(s['jul_sep']['runde'])} | sonst {_fmt(s['jul_sep']['sonst'])}")
                lines.append(f"  {' ' * len(series)}   {' ' * len(g)}  Okt–Dez Runde {_fmt(s['okt_dez']['runde'])} | sonst {_fmt(s['okt_dez']['sonst'])}")
    for ind, block in r["t4_infektionswelle"].items():
        lines += ["", f"T4 Infektionswelle ({ind.upper()}, {block['wochen']} Wochen), Meldung binnen h nach Stichtag:"]
        for variant in ("alle", "ohne_saison_2022_23"):
            if variant not in block:
                continue
            lines.append(f"  {'alle Wochen' if variant == 'alle' else 'ohne Saison 2022/23'}:")
            for g, outs in block[variant].items():
                for o, rows in outs.items():
                    for h, res in rows.items():
                        lines.append(f"    {g} / {o} / {h.replace('_', ' ')}: " + "; ".join(f"{s} {_fmt(v)}" for s, v in res.items()))
    t6 = r["t6_nachbarn"]
    lines += ["", "T6 Offener Engpass bei einem anderen Wirkstoff derselben ATC-4-Gruppe (bereinigt innerhalb von "
              "Wirkstoffgröße, Größe der ATC-4-Gruppe, früherem Engpass, eigener Auslandsmeldung, Jahr und der jeweils "
              "anderen Nachbarschaft):"]
    for exposure, rows in t6["atc4_nachbarn"].items():
        lines.append(f"  {exposure.replace('_', ' ')}:")
        for h, v in rows.items():
            lines.append(f"    {h.replace('_', ' ')}: {_fmt_exposure(v)}")
    lines.append("T6b Gleicher Wirkstoff, anderer Inhaber im Engpass (Wirkstoff + Inhaber ohne Meldung; bereinigt "
                 "innerhalb von Inhaberzahl, früherem Engpass und Jahr):")
    for h, v in t6["anderer_inhaber_gleicher_wirkstoff"].items():
        lines.append(f"  {h.replace('_', ' ')}: {_fmt_exposure(v)}")
    if r.get("t7_gmp"):
        lines += ["", "T7 GMP-Ereignis bei einem Wirkstoffhersteller → BASG-Meldung des Wirkstoffs:"]
        for kind, label in (("cep_aussetzung", "CEP von der EDQM ausgesetzt oder zurückgezogen (GMP)"),
                            ("ncr_bericht", "EudraGMDP-Nichtkonformitätsbericht"), ("beide", "beide zusammen")):
            e = r["t7_gmp"][kind]
            lines.append(f"  {label} ({e['ereignisse']} Zuordnungen, {e['faelle']} Fälle):")
            for k, v in e["alle"].items():
                lines.append(f"    {k.replace('_', ' ')}: {_fmt(v)}")
            for b, v in e["nach_gueltigen_cep_haltern"].items():
                lines.append(f"      gültige CEP-Halter {b}: 8 Wochen {_fmt(v['8_wochen'])}")
    if r.get("t8_marktaustritt"):
        e = r["t8_marktaustritt"]
        lines += ["", f"T8 Marktaustritt laut ASP-Historie (lieferbar → nicht mehr lieferbar) → Meldung eines anderen "
                  f"Produkts desselben Wirkstoffs ({e['austritte_gesamt']} Austritte; ohne eigene Meldung "
                  f"{e['ereignisse']}, {e['faelle']} Fälle):"]
        for k, v in e["alle"].items():
            lines.append(f"    {k.replace('_', ' ')}: {_fmt(v)}")
        for b, s in e["vermarktet_nach_verbleibenden_anbietern"].items():
            lines.append(f"      verbleibende Anbieter {b}: 8 Wochen {_fmt(s['8_wochen'])}")
        for name, s in e["nach_verlauf"].items():
            lines.append(f"    {name.replace('_', ' ')} (im Nachhinein): 8 Wochen {_fmt(s['8_wochen'])}")
        m = e["mit_eigener_meldung"]
        lines.append(f"    mit eigener Meldung ({m['ereignisse']} Austritte, {m['faelle']} Fälle): 8 Wochen {_fmt(m['alle']['8_wochen'])}")
    if r.get("t9_eko_streichung"):
        e = r["t9_eko_streichung"]
        lines += ["", f"T9 Streichung aus dem Grünen oder Gelben Bereich des EKO → Meldung eines anderen Produkts "
                  f"desselben Wirkstoffs ({e['streichungen_gesamt']} Streichungen, {e['faelle']} Fälle):"]
        for k, v in e["alle"].items():
            lines.append(f"    {k.replace('_', ' ')}: {_fmt(v)}")
        for b, v in e["vermarktet_nach_verbleibenden_anbietern"].items():
            lines.append(f"      verbleibende Anbieter {b}: 8 Wochen {_fmt(v['8_wochen'])}")
        for g, v in e["nach_grund"].items():
            lines.append(f"    Grund {g.replace('_', ' ')}: 8 Wochen {_fmt(v['8_wochen'])}")
    lines += ["", "Grenzen:"] + [f"- {g}" for g in r["grenzen"]]
    return "\n".join(lines)


def run(db_path: Path, archive_root: Path, start: date = START, end: date | None = None,
        json_path: Path | None = None) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        result = measure(conn, Archive(archive_root), start, end)
    finally:
        conn.close()
    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result
