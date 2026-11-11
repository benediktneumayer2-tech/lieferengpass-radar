"""Z3 v0: features use only what was known before the day; the grouped ridge fit recovers known log odds."""
import math
from datetime import date, timedelta

from stockout_at import modell
from stockout_at.vorlauf import Intervals

D = date.fromisoformat


def _knowledge(items, episodes=(), events=None):
    k = modell.Knowledge.__new__(modell.Knowledge)
    k.subst = Intervals(list(episodes))
    k.items = {"J01CA04": items}
    k.events = {"inhaberwechsel": {}, "marktaustritt": {}, "eko": {}}
    k.events.update(events or {})
    return k


def _it(country, day, holder=None, until="2026-12-31", source="aifa"):
    return {"country": country, "date": D(day), "until": D(until), "holder": holder, "source": source}


def test_features_only_before_the_day():
    t = D("2026-03-10")
    at = {"n": 1, "holders": {"SANDOZ"}}
    items = [_it(c, "2026-02-01", "SANDOZ") for c in ("IT", "CZ", "SK")] + [_it("HU", "2026-03-10")]  # HU: same day
    k = _knowledge(items, [("J01CA04", D("2025-06-01"), D("2025-12-20"))],
                   {"inhaberwechsel": {"J01CA04": [D("2026-01-20")]}, "eko": {"J01CA04": [D("2026-03-10")]}})
    f = k.features("J01CA04", t, at)
    assert {"laender_3_4", "inhaber_1plus", "inhaber_3plus", "frueher_engpass", "engpass_365", "ende_90", "groesse_1",
            "inhaberwechsel_56", "atc_J", "quartal_1"} == set(f)  # HU and the EKO entry of the day itself do not count
    assert k.tier("J01CA04", t, frozenset({"aifa"})) == "-" and k.tier("J01CA04", t, frozenset()) == "B"
    k = _knowledge(items, [("J01CA04", D("2026-03-01"), D("2026-04-01"))])
    assert k.features("J01CA04", t, at) is None  # reported in Austria that day: outside the universe


def test_fit_recovers_log_odds():
    a, b = modell.INDEX["laender_5plus"], modell.INDEX["quartal_1"]
    rows = []
    for x, n, hits in (((b,), 1000, 100), ((a, b), 1000, 300)):
        rows += [{"x": x, "y": {56: i < hits}, "t": D("2024-01-01") + timedelta(days=i % 7)} for i in range(n)]
    w = modell.fit(rows, 56, l2=1e-6)
    assert abs(modell.prob(w, (b,)) - 0.1) < 1e-3 and abs(modell.prob(w, (a, b)) - 0.3) < 1e-3
    assert abs(w[a] - (math.log(3 / 7) - math.log(1 / 9))) < 1e-2


def _methods():
    w = {"achsenabschnitt": -3.0, "laender_5plus": 1.0}
    q = {"A": 0.2, "-": 0.01, "grundrate": 0.03}
    return {
        "z3_v0": {"art": "logit", "ohne_quellen": ["bfarm"], "rolle": "Haupt", "merkmale": ["laender_5plus"],
                  "horizonte": {str(h): {"gewichte": w, "gewichte_geprueft": w} for h in (28, 56, 84)}},
        "stufen_v0": {"art": "stufen", "ohne_quellen": ["bfarm"], "rolle": "Vergleich",
                      "horizonte": {str(h): {"quoten": q, "quoten_geprueft": q} for h in (28, 56, 84)}},
        "mittel_v0": {"art": "mittel", "aus": ["z3_v0", "stufen_v0"], "rolle": "Mittel", "horizonte": {str(h): {} for h in (28, 56, 84)}},
    }


def test_freeze_plan_log_round_trip(tmp_path):
    import pytest
    result = {"basg_stand": "2026-10-20", "lernen": ["2024-01-01", "2025-12-31"], "pruefen": ["2026-01-01", "2026-10-20"],
              "schritt_tage": 14, "verfahren": _methods()}
    with pytest.raises(SystemExit):
        modell.freeze(result, tmp_path, today=D("2027-01-01"))
    plan = modell.freeze(result, tmp_path, today=D("2026-12-31"))
    loaded, methods = modell.load_plan(tmp_path)
    assert loaded["sha256"] == plan["sha256"] and list(methods) == ["z3_v0", "stufen_v0", "mittel_v0"]
    v = frozenset({"bfarm"})
    p = modell.predict_case(methods, {"x": {v: (modell.INDEX["laender_5plus"],)}, "stufe": {v: "A"}}, 56)
    assert abs(p["z3_v0"] - 1 / (1 + math.exp(2))) < 1e-9 and p["stufen_v0"] == 0.2
    assert abs(p["mittel_v0"] - (p["z3_v0"] + 0.2) / 2) < 1e-12
    rows = {"J01CA04": {"stufe": "A", "p": {h: p for h in (28, 56, 84)}}}
    modell.write_log(tmp_path, "2027-01-02", rows, plan["sha256"])
    back = modell.read_logs(tmp_path, D("2027-01-01"), plan_sha=plan["sha256"])
    assert back[D("2027-01-02")]["J01CA04"]["p"][56]["stufen_v0"] == 0.2
    assert modell.read_logs(tmp_path, D("2027-01-01"), plan_sha="anderer") == {}


def test_scores_and_lead_time():
    assert modell.average_precision([0.9, 0.5, 0.5, 0.1], [1, 1, 0, 0]) == 1 * 0.5 + 0.5 * (2 / 3)  # tie block together
    cases = [{"t": D("2027-01-01"), "atc5": a, "y": y, "p": {"z3_v0": pz, "stufen_v0": ps}}
             for a, y, pz, ps in (("A01", 1, 0.6, 0.1), ("A02", 0, 0.2, 0.1), ("A03", 0, 0.1, 0.1), ("A04", 1, 0.5, 0.1))]
    s = modell.score(cases)
    assert s["verfahren"]["z3_v0"]["auc"] == 1.0 and s["verfahren"]["stufen_v0"]["auc"] == 0.5
    assert s["verfahren"]["z3_v0"]["spitze"]["25"]["quote"] == 0.5  # all four cases, two reported
    # lead time: k = 1; B is top from day 3 on and reported on day 6, A is never reported
    logs = {}
    for i in range(1, 6):
        pb = 0.9 if i >= 3 else 0.1
        logs[D(f"2027-01-0{i}")] = {a: {"p": {3: {"m": p}}} for a, p in (("A", 0.5), ("B", pb))}
    r = modell.lead_and_churn(logs, {"B": [D("2027-01-06")]}, h=3, k=1)["m"]
    assert (r["meldungen"], r["auf_der_liste"], r["seit_tagen_median"], r["irgendwann_in_8_wochen"]) == (1, 1.0, 3, 1.0)  # on the list since day 3, three days before the report
    assert r["wechsel_je_tag"] == 0.25  # one change in four day pairs
