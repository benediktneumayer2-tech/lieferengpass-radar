from datetime import date

from stockout_at import foreign, gmp

HEAD = ["Titre", "Date de création", "Date de mise à jour", "Date de début de situation", "Date de remise à disposition",
        "Statut", "Produit(s) de santé", "Domaine(s) médical(aux)", "URL de la page"]


def test_ansm_rows_become_items(monkeypatch):
    rows = [HEAD,
            ["Rythmol 300 mg, comprimé – [propafénone (chlorhydrate de)]", "2026-09-01", "", "2026-08-20", "2026-10-01",
             "Remise à disposition", "Médicaments", "Cardiologie", "https://ansm.sante.fr/x/rythmol-300"],
            ["Ikervis 1 mg/mL, collyre – [ciclosporine]", "2026-10-16", "", "2026-07-01", "", "Tension d'approvisionnement",
             "Médicaments", "Ophtalmologie", "https://ansm.sante.fr/x/ikervis-1"],
            ["Pansement X - [cellulose]", "2026-10-16", "", "", "", "Rupture de stock", "Dispositifs médicaux", "", "u/p"]]
    monkeypatch.setattr(foreign, "read_xls", lambda body: rows)
    a, b = sorted(foreign.parse_ansm(b""), key=lambda i: i["report_id"])
    assert (a["report_id"], a["substances"], a["status"], a["start_date"], a["end_date"]) == (
        "ikervis-1", "ciclosporine", "tension", "2026-07-01", None)
    assert (b["product"], b["substances"], b["status"], b["end_date"], b["country"]) == (
        "Rythmol 300 mg, comprimé", "propafénone", "remise", "2026-10-01", "FR")
    assert foreign.ansm_title("Repevax, suspension injectable") == ("Repevax, suspension injectable", None)


def test_substance_names_map_to_all_atc_codes():
    by_substance = {foreign.skeleton("DEXAMETHASON"): {"H02AB02", "S01BA01"}, foreign.skeleton("LOSARTAN"): {"C09CA01"}}
    assert gmp.substance_atcs("Dexamethasone sodium phosphate", by_substance) == {"H02AB02", "S01BA01"}
    assert gmp.substance_atcs("Losartan potassium, Form I", by_substance) == {"C09CA01"}
    assert gmp.substance_atcs("Soya-bean oil, refined", by_substance) == set()


CEP = ("Monograph Number\tSubstance\tType CEP\tCertificate (CEP) Holder\tHolder SPOR ORG-ID / SPOR LOC-ID\t"
       "Certificate (CEP) Number\tIssue Date CEP\tStatus CEP\tRenewal due\tEnd date CEP\tClosure Date of last Procedure\n"
       "1\tBetamethasone\tChemical\tXI'AN GUOKANG RUIJIN PHARMACEUTICAL CO., LTD. Xi'an CN\t100000001 / 100000002\tC1\t"
       "01/01/2020\tSuspended by EDQM GMP non-compliance\t\t27/07/2026\t\n"
       "1\tBetamethasone\tChemical\tSICHUAN GOWELL PHARMACEUTICAL CO., LTD. Meishan CN\t\tC2\t01/01/2020\tValid\t\t\t\n"
       "2\tCisatracurium besilate\tChemical\tLIANYUNGANG GUIKE PHARMACEUTICAL CO., LTD. Lianyungang CN\t\tC3\t"
       "01/01/2020\tValid\t\t\t\n"
       "3\tGelatin\tTSE\tGELITA AG Eberbach DE\t\tC4\t01/01/2020\tValid\t\t\t\n").encode()


def test_cep_events_and_ncr_linking_by_id_and_by_two_name_words():
    ceps = gmp.parse_cep(CEP)
    assert len(ceps) == 3  # TSE-only certificate skipped
    gmp.cep_atcs(ceps, {foreign.skeleton("BETAMETHASON"): {"H02AB01"}, foreign.skeleton("CISATRACURIUM"): {"M03AC11"}})
    assert gmp.valid_holders(ceps) == {"H02AB01": 1, "M03AC11": 1}
    assert [(e["atc5"], e["date"]) for e in gmp.cep_events(ceps)] == [("H02AB01", date(2026, 7, 27))]
    ncrs = [{"report": "r1", "site": "Xi'an Guokang", "loc": "100000002", "country": "CN", "issue": "2026-09-21"},
            {"report": "r2", "site": "Lianyungang Guike Pharmaceutical Co. Ltd", "loc": "", "country": "CN", "issue": "2026-08-21"},
            {"report": "r3", "site": "Sichuan New Hawk Biotechnology Co. Ltd.", "loc": "", "country": "CN", "issue": "2026-07-03"}]
    linked = {(e["report"], e["atc5"], e["match"]) for e in gmp.ncr_events(ncrs, ceps)}
    assert linked == {("r1", "H02AB01", "standort_id"), ("r2", "M03AC11", "name_land")}  # no match on 'Sichuan' alone
