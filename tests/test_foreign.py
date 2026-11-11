"""Foreign shortage lists: parsing, matching helpers and the lead-time measurement on a tiny database."""
import io
import sqlite3
import zipfile
from datetime import date

from stockout_at import foreign, vorlauf

BFARM_CSV = (
    "PZN;Bearbeitungsnummer;Referenzierte Erstmeldung;Meldungsart;Beginn;Ende;Arzneimittlbezeichnung;Atc Code;"
    "Wirkstoffe;Zulassungsinhaber;Telefon;E-Mail;Art des Grundes;Grund;Datum der Erstmeldung;Darreichungsform\n"
    "111;LE2;LE1;Änderungsmeldung;03.09.2026;26.11.2026;Pantoprazol X 20 mg Tabletten;A02BC02;Pantoprazol-Natrium;"
    "Micro Labs GmbH;+49 123 456789;info@example.org;Sonstige;Erhöhte Nachfrage;03.07.2026;Tablette\n"
    "112;LE2;LE1;Änderungsmeldung;03.09.2026;26.11.2026;Pantoprazol X 20 mg Tabletten;A02BC02;Pantoprazol-Natrium;"
    "Micro Labs GmbH;+49 123 456789;info@example.org;Sonstige;Erhöhte Nachfrage;03.07.2026;Tablette\n"
).encode("cp1252")


def test_helpers():
    assert foreign.parse_date("03.07.2026") == "2026-07-03"
    assert foreign.parse_date("18/09/2026") == "2026-09-18"
    assert foreign.parse_date("2026-09-18T00:00:00") == "2026-09-18"
    assert foreign.parse_date("46000") == "2025-12-09"
    assert foreign.parse_date("N/A") is None
    assert len({foreign.skeleton(x) for x in ("amoxicillina", "amoxicilina", "Amoxicillin", "AMOXICILLINE")}) == 1
    assert foreign.holder_key("Sandoz GmbH") == foreign.holder_key("SANDOZ S.p.A.") == "SANDOZ"
    assert foreign.holder_key("Fresenius Kabi Deutschland GmbH") == foreign.holder_key("Fresenius Kabi Austria GmbH")
    assert foreign.strengths("Ospamox 500 mg / Ropivacain 2MG/ML 0,5 mg") == {"500MG", "2MG", "0.5MG"}


def test_bfarm_items_group_pzns_and_drop_contacts():
    items = foreign.parse_bfarm(BFARM_CSV)
    assert len(items) == 1
    it = items[0]
    assert (it["report_id"], it["atc5"], it["signal_date"], it["start_date"]) == ("LE1", "A02BC02", "2026-07-03", "2026-09-03")
    assert it["native_ids"] == {"111", "112"}
    assert not any("49 123" in str(v) or "@" in str(v) for v in it.values())


def test_aggregate_tracks_first_last_and_still_listed():
    a = {**foreign.parse_bfarm(BFARM_CSV)[0]}
    merged = foreign.aggregate([("2026-10-17", [dict(a)]), ("2026-10-18", [])])
    assert (merged[0]["first_seen"], merged[0]["last_seen"], merged[0]["still_listed"]) == ("2026-10-17", "2026-10-17", 0)


CASE_KEYS = ("report_id", "status", "signal_date", "start_date", "end_date", "expected_end")


def _cases(items):
    return sorted(tuple(it[k] for k in CASE_KEYS) for it in items)


def test_sukl_cz_event_log_to_cases():
    rows = [  # newest first, as published
        ("", "0000001", "preruseni", "01.05.2022", "28.04.2022", ""),
        ("", "0000001", "obnoveni", "20.03.2021", "21.03.2021", ""),
        ("", "0000001", "preruseni", "10.01.2021", "15.02.2021", "01.04.2021"),
        ("", "0000001", "preruseni", "10.01.2021", "05.01.2021", "01.03.2021"),
        ("", "0000001", "zahajeni", "01.06.2020", "01.06.2020", ""),
        ("ANO", "0000002", "ukonceni", "30.04.2026", "15.04.2026", ""),
    ]
    head = '"POSLEDNI_PLATNE_HLASENI";"KOD_SUKL";"NAZEV";"DOPLNEK";"REG";"ATC";"TYP_OZNAMENI";"PLATNOST_OD";' \
           '"DATUM_HLASENI";"NAHRAZUJICI_LP";"NAHRAZUJICI_LP_POZNAMKA";"DUVOD_PRERUSENI_UKONCENI";"TERMIN_OBNOVENI"\n'
    csv_text = head + "".join(f'"{a}";"{c}";"LÉČIVO";"10MG TBL 30";"R";"N02BE01";"{t}";"{p}";"{h}";"";"";"Výrobní důvody";"{o}"\n'
                              for a, c, t, p, h, o in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mr_hlaseni.csv", csv_text.encode("cp1250"))
        z.writestr("mr_hlaseni_platnost.csv", '"PLATNOST"\n"18.10.2026"\n')
    items = foreign.parse_sukl_cz(buf.getvalue())
    assert _cases(items) == [
        ("0000001:2021-01-10", "unterbrechung", "2021-01-05", "2021-01-10", "2021-03-20", "2021-04-01"),
        ("0000001:2022-05-01", "unterbrechung", "2022-04-28", "2022-05-01", None, None),
        ("0000002:2026-04-30", "einstellung", "2026-04-15", "2026-04-30", None, None),
    ]
    assert items[0]["product"] == "LÉČIVO" and items[0]["atc5"] == "N02BE01" and items[0]["native_ids"] == {"0000001"}


def test_sukl_sk_event_log_to_cases():
    text = (
        "\ufeffPodanie;Držiteľ;Kód;Liek;Účinnosť;Predmet\n"
        '"2024-03-02 10:00:00.000";"Teva B.V. (TEV-NL-4)";1234A;"Metformin Teva 500 mg\n (tbl 60x500 mg)";2024-03-01;O\n'
        '"2024-01-05 09:00:00.000";"Teva B.V. (TEV-NL-4)";1234A;"Metformin Teva 500 mg\n (tbl 60x500 mg)";2024-01-10;R\n'
        '"2023-05-01 09:00:00.000";"Teva B.V. (TEV-NL-4)";1234A;"Metformin Teva 500 mg\n (tbl 60x500 mg)";2023-05-01;U\n'
        '"2025-02-01 09:00:00.000";"Heyl GmbH (HEL-1)";66753;"METALCAPTASE 300";2025-02-28;Z\n'
    )
    items = foreign.parse_sukl_sk(text.encode("utf-8"))
    assert _cases(items) == [
        ("1234A:2024-01-10", "unterbrechung", "2024-01-05", "2024-01-10", "2024-03-01", None),
        ("66753:2025-02-28", "einstellung", "2025-02-01", "2025-02-28", None, None),
    ]
    it = next(i for i in items if i["native_ids"] == {"1234A"})
    assert (it["holder"], it["product"]) == ("Teva B.V.", "Metformin Teva 500 mg (tbl 60x500 mg)")


def _xlsx(rows) -> bytes:
    cell = lambda i, v: f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{v}</t></is></c>' if v is not None else ""
    xml = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
           + "".join("<row>" + "".join(cell(i, v) for i, v in enumerate(r)) + "</row>" for r in rows)
           + "</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", xml)
    return buf.getvalue()


def test_jazmp_event_log_to_cases():
    head = ["DŠ zdravila", "Zadeva", "Zdravilo", "Poročevalec", "Status poročevalca", "Datum prejema obvestila",
            "Vrsta obvestila", "Datum začetka", "Napovedani datum konca", "Opombe JAZMP"]
    rows = [head,  # newest first
            ["111", "2024-0300", "Zdr 5 mg", "Lek d.d.", "x", "45400", "prijava stalnega prenehanja opravljanja prometa", "45420", None, None],
            ["111", "2024-0200", "Zdr 5 mg", "Lek d.d.", "x", "45350", "Ponovni prihod zdravila na trg na debelo po predhodno "
             "priglašeni motnji v preskrbi", "45350", None, None],
            ["111", "2024-0150", "Zdr 5 mg", "Lek d.d.", "x", "45320", "prijava motnje v preskrbi", "45300", "45380", "Podaljšanje motnje"],
            ["111", "2024-0100", "Zdr 5 mg", "Lek d.d.", "x", "45290", "Obvestilo o motnji v preskrbi z zdravilom", "45300", "45330", None],
            ["111", "2023-0001", "Zdr 5 mg", "Lek d.d.", "x", "45000", "datum  začetka prometa z zdravilom", "45000", None, None]]
    items = foreign.parse_jazmp(_xlsx(rows))
    assert _cases(items) == [  # the extension (2024-0150) only moves the expected end
        ("2024-0100", "unterbrechung", "2023-12-30", "2024-01-09", "2024-02-28", "2024-03-29"),
        ("2024-0300", "einstellung", "2024-04-18", "2024-05-08", None, None),
    ]
    assert items[0]["native_ids"] == {"111"} and items[0]["holder"] == "Lek d.d."


def test_cima_jsonl_bundle():
    page = '{"totalFilas":2,"pagina":%d,"tamanioPagina":200,"resultados":[%s]}'
    a = ('{"cn":"762334","nombre":"DABIGATRAN ETEXILATO CINFA 110 MG CAPSULAS DURAS EFG, 60 c\\u00E1psulas",'
         '"tipoProblemaSuministro":5,"fini":1792101600000,"ffin":1797548400000,"activo":true,"observ":"Existe otro."}')
    b = '{"cn":"765890","nombre":"PEDMARQSI 80 MG/ML","tipoProblemaSuministro":4,"fini":1774998000000,"activo":true,"observ":"x"}'
    bundle = b"\n".join(x.encode() for x in (page % (1, a), page % (2, a + "," + b), page % (3, "")))
    items = sorted(foreign.parse_cima(bundle), key=lambda it: it["report_id"])
    assert [it["report_id"] for it in items] == ["762334:2026-10-16", "765890:2026-04-01"]
    it = items[0]
    assert (it["country"], it["signal_date"], it["expected_end"], it["end_date"]) == ("ES", "2026-10-16", "2026-12-18", None)
    assert it["product"].endswith("60 cápsulas") and items[1]["expected_end"] is None


def test_aifa_csv():
    text = (
        "NB: I medicinali carenti … “Lista dei farmaci temporaneamente carenti”;;;;;;;;;;;;\n"
        "Elenco dei farmaci carenti aggiornato al 16/10/2026;;;;;;;;;;;;\n"
        "Nome medicinale;Codice AIC;Principio attivo;Forma farmaceutica e dosaggio;Titolare AIC;Data inizio;Fine presunta;"
        "Equivalente;Motivazioni;Suggerimenti/Indicazioni AIFA;Nota AIFA;Classe di rimborsabilità;Codice ATC\n"
        'ABIOCLAV;037350016;ACIDO CLAVULANICO + AMOXICILLINA;"""875 MG + 125 MG COMPRESSE"" 12 COMPRESSE";'
        "S.F. GROUP S.R.L.;01/06/2025;31/12/2026;Sì;Problemi produttivi;Rivolgersi all’M.M.G;;A;J01CR02\n"
        "ACECLOFENAC EG;012345678;ACECLOFENAC;100 MG;EG S.P.A.;07/12/2026;;Sì;Cessata commercializzazione definitiva;;;A;\n"
    )
    items = foreign.parse_aifa(text.encode("cp1252"))
    a, b = sorted(items, key=lambda it: it["product"])
    assert (a["report_id"], a["atc5"], a["signal_date"], a["expected_end"], a["status"]) == (
        "037350016:2025-06-01", "J01CR02", "2025-06-01", "2026-12-31", "carenza")
    assert a["strength"] == '"875 MG + 125 MG COMPRESSE" 12 COMPRESSE' and a["native_ids"] == {"037350016"}
    # announced for the future: public since the list date, permanent stop marked separately
    assert (b["start_date"], b["signal_date"], b["status"], b["atc5"]) == ("2026-12-07", "2026-10-16", "einstellung", None)


def test_derive_atc_from_product_name_is_conservative():
    asp = [{"atc": "J01CA04", "substances": "AMOXICILLIN TRIHYDRATE", "name": "OSPAMOX FTBL 500MG"},
           {"atc": "J04AB02", "substances": "RIFAMPICIN", "name": "RIFOLDIN KPS 300MG"},
           {"atc": "J05AF06", "substances": "ABACAVIR", "name": "ZIAGEN FTBL 300MG"},
           {"atc": "J05AF05", "substances": "LAMIVUDINE", "name": "EPIVIR FTBL 150MG"},
           {"atc": "N05AH04", "substances": "QUETIAPINE FUMARATE", "name": "SEROQUEL FTBL 25MG"}]
    by_sub, by_brand = foreign.atc_lookup(asp)
    derive = lambda product, subs=None: foreign.derive_atc({"product": product, "substances": subs}, by_sub, by_brand)
    assert derive("Amoxicilina Sandoz 500 mg (tbl flm 12x500 mg)") == ("J01CA04", "produktname")
    assert derive("QUETIAPINA TEVA-RATIO 300 mg COMPRIMIDOS") == ("N05AH04", "produktname")
    assert derive("Seroquel 25 mg filmsko obložene tablete, škatla s 30 tabletami") == ("N05AH04", "handelsname")
    assert derive("RIFAMPICIN 75MG + ISONIAZID 50MG") == (None, None)
    assert derive("ABACAVIR E LAMIVUDINA SUN 600 MG/300 MG") == (None, None)
    assert derive("Abacavir Lamivudin Teva") == (None, None)
    assert derive("Seroquel 25 mg", "Ibuprofen") == (None, None)  # brand ATC must fit the given substance


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE snapshots (snapshot_date TEXT);
        CREATE TABLE episodes (atc5 TEXT, start_date TEXT, end_upper TEXT, active INTEGER, zulassungsinhaber TEXT);
        CREATE TABLE foreign_items (source TEXT, country TEXT, atc5 TEXT, signal_date TEXT, holder TEXT,
                                    end_date TEXT, still_listed INTEGER, last_seen TEXT, status TEXT);
        CREATE TABLE asp_packages (atc TEXT, valid INTEGER, inhaber TEXT);
    """)
    conn.execute("INSERT INTO snapshots VALUES ('2026-10-18')")
    conn.executemany("INSERT INTO asp_packages VALUES (?, 1, ?)",
                     [("A02BC02", "Micro Labs GmbH"), ("C10AA05", "Other AG"), ("N05AH04", "Sandoz GmbH")])
    # A02BC02: DE first public 2026-03-01, AT report starts 2026-04-12 (42 days later) and ends.
    conn.execute("INSERT INTO episodes VALUES ('A02BC02', '2026-04-12', '2026-06-01', 0, 'Micro Labs GmbH')")
    conn.execute("INSERT INTO foreign_items VALUES ('bfarm', 'DE', 'A02BC02', '2026-03-01', 'Micro Labs GmbH', NULL, 1, '2026-10-18', NULL)")
    # C10AA05: DE signal without any Austrian report afterwards.
    conn.execute("INSERT INTO foreign_items VALUES ('bfarm', 'DE', 'C10AA05', '2026-02-01', 'Other AG', NULL, 1, '2026-10-18', NULL)")
    return conn


def test_vorlauf_lead_and_hit_rate():
    r = vorlauf.measure(_db(), date(2026, 1, 1), date(2026, 10, 18))
    de = r["quellen"]["bfarm"]
    sub = de["wirkstoff_neumeldungen"]
    assert (sub["faelle"], sub["mit_vorausgehender_auslandsmeldung"], sub["vorlauf_median_tage"]) == (1, 1, 42.0)
    assert de["inhaber_neumeldungen"]["mit_vorausgehender_auslandsmeldung"] == 1
    assert de["trefferquote_gleicher_inhaber"]["8_wochen"]["treffer"] == 1
    eight = de["trefferquote_wirkstoff"]["8_wochen"]
    assert (eight["faelle"], eight["treffer"], eight["quote"]) == (2, 1, 0.5)
    assert de["trefferquote_wirkstoff"]["4_wochen"]["treffer"] == 0


def test_vorlauf_country_combinations():
    conn = _db()
    # A02BC02: Italy reports two weeks after Germany -> a second case with two active countries.
    conn.execute("INSERT INTO foreign_items VALUES ('aifa', 'IT', 'A02BC02', '2026-03-15', NULL, NULL, 1, '2026-10-18', NULL)")
    # A permanent discontinuation is not a shortage signal.
    conn.execute("INSERT INTO foreign_items VALUES ('sukl_cz', 'CZ', 'N05AH04', '2026-03-01', NULL, NULL, 1, '2026-10-18', 'einstellung')")
    c = vorlauf.measure(conn, date(2026, 1, 1), date(2026, 10, 18))["laender_kombiniert"]["wirkstoff"]
    assert c["faelle"] == 3
    assert c["nach_zahl_der_laender"]["2"]["8_wochen"]["treffer"] == 1
    assert c["nach_zahl_der_laender"]["1"]["8_wochen"]["faelle"] == 2
    assert c["nach_stufe"]["C"]["8_wochen"]["treffer"] == 1


def test_fda_groups_packages_and_marks_discontinuations():
    import io as _io
    import json as _json
    import zipfile as _zip
    rows = [
        {"generic_name": "Lidocaine Injection", "initial_posting_date": "02/22/2012", "package_ndc": "1", "status": "Current",
         "company_name": "Hospira, Inc.", "contact_info": "844-646-4398", "openfda": {"substance_name": ["LIDOCAINE HYDROCHLORIDE"]}},
        {"generic_name": "Lidocaine Injection", "initial_posting_date": "02/22/2012", "package_ndc": "2", "status": "Current"},
        {"generic_name": "Gadobutrol Injection", "initial_posting_date": "2026-06-30", "package_ndc": "3", "status": "To Be Discontinued"},
    ]
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w") as z:
        z.writestr("drug-shortages-0001-of-0001.json", _json.dumps({"results": rows}))
    items = {it["product"]: it for it in foreign.parse_fda(buf.getvalue())}
    lido = items["Lidocaine Injection"]
    assert (lido["country"], lido["signal_date"], lido["status"], lido["native_ids"]) == ("US", "2012-02-22", "current", {"1", "2"})
    assert items["Gadobutrol Injection"]["status"] == "einstellung" and items["Gadobutrol Injection"]["signal_date"] == "2026-06-30"
    assert not any("844" in str(v) for v in lido.values())
