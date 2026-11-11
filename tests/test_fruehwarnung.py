from datetime import date

from stockout_at import merkmale
from stockout_at.archive import Archive
from stockout_at.fruehwarnung import register_hints, substance_tier

D = date.fromisoformat


def _p(zl, atc5, holder, lieferbar=1):
    return {"zl": zl, "name": f"Produkt {zl}", "atc5": atc5, "holder": f"{holder} GmbH", "holder_key": holder.upper(),
            "substances": atc5, "packages": 1, "lieferbar": lieferbar}


def _change(zl, atc5, day, same=False):
    return {"zl": zl, "atc5": atc5, "date": D(day), "prev_name": "Alt GmbH", "holder_name": "Neu GmbH",
            "same_company": same, "product": ""}


def test_holder_changes_only_recent_marketed_and_unreported():
    products = {z: _p(z, a, "Neu", l) for z, a, l in
                [("1", "N02BE01", 1), ("2", "N02BE01", 1), ("3", "N02BE01", 0), ("4", "J01CA04", 1), ("5", "N02BE01", 1)]}
    changes = {"1": _change("1", "N02BE01", "2026-08-25"),   # day 55: listed
               "2": _change("2", "N02BE01", "2026-08-24"),   # day 56: too old
               "3": _change("3", "N02BE01", "2026-10-01"),   # not marketed
               "4": _change("4", "J01CA04", "2026-10-01"),   # substance reported
               "5": _change("5", "N02BE01", "2026-10-20")}   # after the reference day
    r = register_hints(products, set(), {"J01CA04": {"X": "X GmbH"}}, changes, D("2026-10-19"), {})
    assert [c["zl"] for c in r["changes"]] == ["1"]


def test_other_holders_exclude_reporting_holder_and_reported_products():
    products = {"1": _p("1", "J01CA04", "Sandoz"),            # reporting holder
                "2": _p("2", "J01CA04", "Ratiopharm"),        # own active report
                "3": _p("3", "J01CA04", "Genericon"),
                "4": _p("4", "J01CA04", "Genericon"),
                "5": _p("5", "J01CA04", "Hexal", lieferbar=0),
                "6": _p("6", "N02BE01", "Genericon")}         # substance not reported
    active_by_atc = {"J01CA04": {"SANDOZ": "Sandoz GmbH", "RATIOPHARM": "Ratiopharm GmbH"}}
    r = register_hints(products, {"2"}, active_by_atc, {}, D("2026-10-19"), {})
    [o] = r["others"]
    assert o["atc5"] == "J01CA04" and o["reported"] == ["Ratiopharm GmbH", "Sandoz GmbH"]
    assert o["remaining"] == [{"holder": "Genericon GmbH", "lieferbar": 2, "products": 2}]


def test_substance_tier():
    its = [{"country": c, "holder": h} for c, h in [("IT", "Sandoz SpA"), ("CZ", "Sandoz s.r.o."), ("SK", "Sandoz")]]
    countries, holders, tier = substance_tier(its, {"SANDOZ": "Sandoz GmbH"})
    assert tier == "B" and holders == [{"holder": "Sandoz GmbH", "countries": ["CZ", "IT", "SK"]}]  # holder shown, not a tier
    more = its + [{"country": c, "holder": None} for c in ("HU", "PL")]
    assert substance_tier(more, {})[2] == "A" and substance_tier(more[:4], {})[2] == "B"
    assert substance_tier(its[:2], {})[2] == "C" and substance_tier(its[:1], {})[2] == "1"


def test_section_21_first_seen_is_carried_over(tmp_path):
    archive = Archive(tmp_path)
    assert merkmale.first_seen({"1-1"}, None, "2026-10-19") == {"1-1": ""}  # log starts: day unknown
    row = {c: "" for c in merkmale.COLUMNS}
    merkmale.write(archive, "2026-10-19", [{**row, "zulassungsnummer": "1-1", "vertrieb_eingestellt_gemeldet": 1,
                                             "vertrieb_eingestellt_seit": ""},
                                            {**row, "zulassungsnummer": "1-2", "vertrieb_eingestellt_gemeldet": 0}])
    prev = merkmale.previous_log(archive, "2026-10-20")
    assert prev == {"1-1": ""} and merkmale.previous_log(archive, "2026-10-19") is None
    assert merkmale.first_seen({"1-1", "1-2"}, prev, "2026-10-20") == {"1-1": "", "1-2": "2026-10-20"}


def test_holder_key_groups_companies_and_handles_short_names():
    from stockout_at.foreign import holder_key
    assert holder_key("Hexal AG") == holder_key("1 A Pharma GmbH") == holder_key("Sandoz GmbH") == "SANDOZ"
    assert holder_key("ratiopharm GmbH") == holder_key("Actavis Group PTC ehf.") == "TEVA"
    assert holder_key("G.L. Pharma GmbH") == holder_key("G.L. PHARMA GMBH") == "GLPHARMA"
    assert holder_key("EG S.P.A.") == "STADA" and holder_key("Novartis Pharma GmbH") == "NOVARTIS"
    assert holder_key("Richter Pharma AG") != holder_key("Gedeon Richter Plc.")


def test_schaerfe_helpers():
    from stockout_at import schaerfe
    assert schaerfe.reason_classes("Elevata richiesta/problemi produttivi") == {"nachfrage", "herstellung"}
    assert schaerfe.reason_classes("Insufficient demand") == {"kommerziell"}
    assert schaerfe.reason_classes("Kapacitní/distribuční důvody") == {"logistik"}
    assert schaerfe.form_class("injektioneste, liuos") == "parenteral"
    assert schaerfe.form_class(None, "PARALEN 500MG TBL NOB") == "oral_fest"
    assert schaerfe.form_class("Lösung zum Einnehmen") == "oral_fluessig" and schaerfe.form_class(None) is None
    assert schaerfe.auc([1, 2, 3, 4], [0, 0, 1, 1]) == 1.0 and schaerfe.auc([1, 1, 1, 1], [0, 1, 0, 1]) == 0.5
    assert schaerfe.top_rate([3, 2, 2, 1], [1, 1, 0, 0], 2) == 0.75  # tie at the cut-off counts half
    w = schaerfe.logit([[1, 0], [1, 0], [1, 1], [1, 1], [1, 1], [1, 0]], [0, 0, 1, 1, 0, 1], l2=0.0)
    assert round(w[1], 2) == round(__import__("math").log(2 / 1) - __import__("math").log(1 / 2), 2)
