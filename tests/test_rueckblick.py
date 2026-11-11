from datetime import date

from stockout_at.rueckblick import _exposure, event_outcomes, mia_events, wave_states

D = date.fromisoformat


def test_event_outcomes_ignore_the_leaving_product_and_skip_active_substances():
    eps = {"N02BE01": [{"start": D("2024-03-10"), "end": D("2024-04-01"), "zl": "1-1"},   # leaving product
                       {"start": D("2024-04-20"), "end": D("2024-05-01"), "zl": "1-2"}],  # another product
           "J01CA04": [{"start": D("2024-02-01"), "end": D("2024-06-01"), "zl": "2-1"}]}
    cases = [("N02BE01", D("2024-03-01"), frozenset({"1-1"})),   # other product reports after 50 days
             ("J01CA04", D("2024-03-01"), frozenset({"9-9"}))]   # substance already in shortage: no case
    [c] = event_outcomes(cases, eps, end=D("2026-01-01"))
    assert c["atc5"] == "N02BE01" and c["hits"] == {28: False, 56: True, 84: True}
    # with the leaving product counted, the report on day 9 is a hit within 4 weeks
    [c] = event_outcomes([("N02BE01", D("2024-03-01"), frozenset())], eps, end=D("2026-01-01"))
    assert c["hits"][28] is True


def test_exposure_compares_within_strata():
    # stratum "gross": exposed 4/100 vs unexposed 2/100; stratum "klein": exposed 0/10 vs unexposed 1/100
    tally = {(28, "gross", True, None): [4, 100], (28, "gross", False, None): [2, 100],
             (28, "klein", True, None): [0, 10], (28, "klein", False, None): [1, 100]}
    r = _exposure(tally, 0)["4_wochen"]
    assert r["mit"]["faelle"] == 110 and r["ohne"]["faelle"] == 200
    assert r["erwartet"] == 2.1 and r["sir"] == round(4 / 2.1, 2)


def test_wave_state_uses_the_week_before_last():
    weeks = {D("2024-01-01"): 10.0, D("2024-01-08"): 50.0, D("2024-01-15"): 40.0, D("2024-01-22"): 60.0}
    states = wave_states(weeks)
    # value of week 2024-01-08 is known on Monday 2024-01-22; 50 is in the upper third but 2 weeks earlier no value
    assert states[D("2024-01-22")] == "hoch"
    assert states[D("2024-02-05")] == "hoch_steigend"  # 60 > 50
    assert states[D("2024-01-15")] == "niedrig"


def test_mia_events_kinds_and_dates():
    csv = ("Verfahrensnummer,Verfahren abgeschlossen am,Genehmigt am,Zulassungsnummer,Verfahrenstyp,Klassifizierung,"
           "Inhaber:in,Inhaber:in bisher,ATC Code\n"
           "1,2024-05-02,2024-03-01,1-1,Aufhebung der Zulassung human auf Antrag der Firma,,Sandoz GmbH,,N02BE01\n"
           "2,2024-06-01,,1-2,Variation human AT=CMS,A.7 Deletion of manufacturer,Ratiopharm GmbH,,\n"
           "3,2024-07-01,,1-3,nationale Änderung human,§25_Rechtsübergang (Übertragung),Neu GmbH,Alt GmbH,J01CA04\n"
           "4,2024-07-01,,8-1,Aufhebung der Zulassung veterinär auf Antrag der Firma,,Vet GmbH,,QJ01\n"
           '5,2024-08-01,,1-4,nationale Änderung human,§24_Änderung der Adresse,"Neu GmbH, Weg 2","Neu GmbH, Weg 1",J01CA04\n').encode()
    ev = mia_events(csv, {"1-2": "N02BE01"})
    assert [(e["kind"], e["date"].isoformat(), e["atc5"]) for e in ev] == [
        ("aufhebung", "2024-03-01", "N02BE01"), ("standort", "2024-06-01", "N02BE01"),
        ("inhaberwechsel", "2024-07-01", "J01CA04"), ("inhaberwechsel", "2024-08-01", "J01CA04")]
    assert [e["same_company"] for e in ev if e["kind"] == "inhaberwechsel"] == [False, True]
    assert ev[-1]["holder_name"] == "Neu GmbH" and ev[-1]["prev_name"] == "Neu GmbH"


def test_asp_exits_need_marketed_then_not_and_flag_own_reports():
    from stockout_at.rueckblick import AspHistory, asp_exits
    v1 = {"1-1": (True, "N02BE01", "A"), "1-2": (True, "N02BE01", "B"), "1-3": (False, "N02BE01", "C"), "1-4": (True, None, "D")}
    v2 = {"1-1": (False, "N02BE01", "A"), "1-3": (True, "N02BE01", "C"), "1-4": (False, None, "D")}  # 1-2 delisted
    v3 = {"1-1": (True, "N02BE01", "A"), "1-3": (True, "N02BE01", "C")}
    hist = AspHistory([(D("2024-01-10"), v1), (D("2024-02-10"), v2), (D("2024-03-10"), v3)])
    eps = [{"zl": "1-2", "start": D("2024-01-20"), "end": D("2024-04-01")}]
    ev = {e["zl"]: e for e in asp_exits(hist, eps)}
    assert set(ev) == {"1-1", "1-2"}  # 1-3 entered, 1-4 has no ATC
    assert ev["1-1"]["date"] == D("2024-02-10") and ev["1-1"]["back"] and not ev["1-1"]["gone"] and not ev["1-1"]["own"]
    assert ev["1-2"]["gone"] and not ev["1-2"]["back"] and ev["1-2"]["own"]


def test_asp_fhir_codesystem_gives_the_same_rows_as_svs():
    import io
    import json
    from stockout_at import asp
    concept = {"code": "0000974", "display": "AETHOXYSKLEROL AMP 0,5% 2ML", "property": [
        {"code": "ZulassungsNummer", "valueString": "1.2.40.0.34.4.17:13905"},
        {"code": "ELGA_Gültigkeit", "valueString": "true"},
        {"code": "ELGA_MedikationPackungsstatusLieferbar", "valueString": "false"},
        {"code": "ELGA_Inhaber", "valueString": "Kreussler GmbH"},
        {"code": "ELGA_whoATC_01_code", "valueString": "2.16.840.1.113883.6.73:C05BB02"},
        {"code": "ELGA_ActiveIngredient_01_text", "valueString": "POLIDOCANOL"}]}
    body = json.dumps({"resourceType": "CodeSystem", "version": "2.53.1+20261007", "date": "2026-10-07",
                       "concept": [concept]}, indent=2).encode()
    assert asp.fhir_date(body) == "2026-10-07"
    version, [r] = asp.parse(io.BytesIO(body))
    assert version == "2.53.1+20261007"
    assert (r["pzn"], r["zulassungsnummer"], r["valid"], r["lieferbar"], r["atc"], r["substances"]) == (
        "0000974", "13905", 1, 0, "C05BB02", "POLIDOCANOL")


def test_eko_deletions_with_reason_from_footnotes():
    from stockout_at import eko
    cell = '<td><p class="TabText">{}</p></td>'
    row = lambda *c: "<tr>" + "".join(cell.format(x) for x in c) + "</tr>"  # noqa: E731
    body = ("<html><body><h1>A4. Streichung von im Grünen Bereich des Erstattungskodex angeführten Arzneispezialitäten:</h1>"
            "<table>" + row("", "Arzneispezialität", "Menge", "OP", "ATC-Code", "mit Wirkung vom", "Entscheidung vom", "Verfahrens-nummer")
            + row("", '<span class="Fett">Berotec 100 mcg Dosieraerosol</span>', "14 g", "2", "R03AC04", "1.10.2026", "-", "-")
            + row("", '<span class="Fett">Furostad 40 mg Tabl.</span><br/>IND text', "20 St.", "2", "C03CA01", "1.10.2026", "22.7.2026", "Abschnitt VIII/2327-2026")
            + "</table><h1>B. Gelber Bereich</h1><table>"
            + row("Die Streichung der Arzneispezialität Berotec 100 mcg Dosieraerosol erfolgte wegen der Aufhebung der Zulassung.")
            + "</table></body></html>").encode()
    rows = eko.parse(body)
    assert [(r["product"], r["atc"], r["wirkung"], r["verfahren"], r["grund"]) for r in rows] == [
        ("Berotec 100 mcg Dosieraerosol", "R03AC04", "2026-10-01", "-", "zulassung"),
        ("Furostad 40 mg Tabl.", "C03CA01", "2026-10-01", "Abschnitt VIII/2327-2026", "ohne_fussnote")]


def test_eko_name_key_matches_asp_approval_names():
    from stockout_at.rueckblick import name_key
    assert name_key('Atenolol "Genericon" comp. mite Filmtabl.') == name_key('Atenolol "Genericon" comp. mite - Filmtabletten')
    assert name_key("Gerodorm Tabl.") == name_key("Gerodorm - Tabletten") == ("gerodorm",)
    assert name_key("Blopress Plus 32 mg/12,5 mg Tabl.") == ("blopress", "plus")


def test_eko_sync_only_in_ris_hours():
    from datetime import datetime, timezone
    from stockout_at import eko
    monday_noon = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)   # 12:00 in Vienna
    monday_night = datetime(2026, 10, 19, 19, 30, tzinfo=timezone.utc)  # 21:30 in Vienna
    saturday = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    assert not eko.allowed(monday_noon) and eko.allowed(monday_night) and eko.allowed(saturday)

    class NoArchive:
        def entries(self):
            return []
    calls = []
    assert eko.sync(NoArchive(), get=calls.append, sleep=lambda s: None, now=lambda: monday_noon) == [] and not calls


def test_eko_regular_run_takes_only_recent_documents():
    import json
    from datetime import datetime, timezone
    from stockout_at import eko

    def ref(doc, day):
        return {"Data": {"Metadaten": {"Technisch": {"ID": doc}, "Sonstige": {
            "Kundmachungsdatum": day, "Kurztitel": "265. Änderung des Erstattungskodex - EKO"}},
            "Dokumentliste": {"ContentReference": {"Urls": {"ContentUrl": [{"DataType": "Html", "Url": f"u/{doc}"}]}}}}}
    page = json.dumps({"OgdSearchResult": {"OgdDocumentResults": {"OgdDocumentReference": [
        ref("AVSV_2026_0054", "2026-09-24"), ref("AVSV_2020_0071", "2020-06-29")]}}}).encode()

    class Store:
        def __init__(self):
            self.stored = []
        def entries(self):
            return []
        def store(self, source, body, **kw):
            self.stored.append(kw["meta"]["doc"])
            return {"ok": True, **kw["meta"]}
    got = []
    store = Store()
    saturday = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    eko.sync(store, get=lambda u: got.append(u) or (page if "Seitennummer" in u else b"Erstattungskodex"),
             sleep=lambda s: None, now=lambda: saturday)
    assert store.stored == ["AVSV_2026_0054"]


def test_eko_backfill_spreads_requests_unevenly_until_the_end_of_the_night():
    import json
    import random
    from datetime import datetime, timedelta, timezone
    from stockout_at import eko

    def ref(i):
        return {"Data": {"Metadaten": {"Technisch": {"ID": f"AVSV_{i}"}, "Sonstige": {
            "Kundmachungsdatum": "2010-01-01", "Kurztitel": f"{i}. Änderung des Erstattungskodex - EKO"}},
            "Dokumentliste": {"ContentReference": {"Urls": {"ContentUrl": [{"DataType": "Html", "Url": f"u/{i}"}]}}}}}
    page = json.dumps({"OgdSearchResult": {"OgdDocumentResults": {"OgdDocumentReference": [ref(i) for i in range(50)]}}}).encode()
    clock = [datetime(2026, 10, 19, 18, 10, tzinfo=timezone.utc)]  # 20:10 in Vienna
    gaps = []

    def sleep(s):
        gaps.append(s)
        clock[0] += timedelta(seconds=s)

    class Store:
        def entries(self):
            return []
        def store(self, source, body, **kw):
            return {"ok": True, **kw["meta"]}
    until = eko.night_end(clock[0])
    assert until.astimezone(eko.VIENNA).hour == 4 and until - clock[0] < timedelta(hours=9)
    rng = random.Random(1)
    out = eko.sync(Store(), pages=None, origin="backfill", until=until, sleep=sleep, now=lambda: clock[0], rand=rng.random,
                   get=lambda u: page if "Seitennummer=1" in u else (b"{}" if "Seitennummer" in u else b"Erstattungskodex"))
    doc_gaps = gaps[2:]  # two search pages first
    assert len(out) == 50 and clock[0] <= until and clock[0] > until - timedelta(hours=2)
    assert min(doc_gaps) >= eko.PAUSE and max(doc_gaps) > 2 * min(doc_gaps)


def test_eko_search_retries_after_a_server_error():
    import json
    from datetime import datetime, timezone
    from stockout_at import eko
    page = json.dumps({"OgdSearchResult": {"OgdDocumentResults": {"OgdDocumentReference": [{"Data": {
        "Metadaten": {"Technisch": {"ID": "AVSV_X"}, "Sonstige": {"Kundmachungsdatum": "2026-09-24", "Kurztitel": "265. Änderung des Erstattungskodex - EKO"}},
        "Dokumentliste": {"ContentReference": {"Urls": {"ContentUrl": [{"DataType": "Html", "Url": "u/X"}]}}}}}]}}}).encode()
    calls = []

    def get(u):
        calls.append(u)
        if len(calls) == 1:
            raise OSError("HTTP Error 500")
        return page if "Seitennummer" in u else b"Erstattungskodex"

    class Store:
        def entries(self):
            return []
        def append(self, e):
            raise AssertionError("no failure expected")
        def store(self, source, body, **kw):
            return {"ok": True, **kw["meta"]}
    saturday = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    out = eko.sync(Store(), get=get, sleep=lambda s: None, now=lambda: saturday)
    assert [e["doc"] for e in out] == ["AVSV_X"] and len(calls) == 3
