import io
import json
import zipfile

from stockout_at import registers


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text.encode("cp1250"))
    return buf.getvalue()


def test_sukl_register_gives_holder_by_organisation_code():
    body = _zip({
        "dlp_lecivepripravky.csv": "KOD_SUKL;NAZEV;DRZ;ZEMDRZ;ATC_WHO\n0000009;ACYLCOFFIN;ZNB;SK;N02BA51\n0000010;X;TEV;CZ;N02\n",
        "dlp_organizace.csv": "ZKR_ORG;ZEM;NAZEV;VYROBCE;DRZITEL\nZNB;SK;Zentiva, a.s., Hlohovec;;D\nTEV;CZ;Teva Czech Industries s.r.o., Opava;;D\n",
    })
    reg = registers.parse_sukl_dlp(body)
    assert reg["0000009"] == {"atc5": "N02BA51", "holder": "Zentiva"}
    assert reg["0000010"] == {"atc5": None, "holder": "Teva Czech Industries s.r.o."}


def test_cima_answers_and_filling_keep_what_the_list_states():
    body = "\n".join(json.dumps(r) for r in (
        {"cn": "600223", "medicamento": {"labtitular": "Fresenius Kabi España, S.A.U.", "pactivos": "ACETATO SODIO",
                                         "atcs": [{"codigo": "B05BB", "nivel": 4}, {"codigo": "B05BB01", "nivel": 5}]}},
        {"cn": "600767", "error": "HTTPError: 500"},  # looked up again next time
    )).encode()
    reg = registers.parse_cima_reg(body)
    assert set(reg) == {"600223"} and reg["600223"]["atc5"] == "B05BB01"
    items = [{"source": "cima", "native_ids": "600223", "atc5": None, "holder": None, "substances": None},
             {"source": "cima", "native_ids": "600223", "atc5": "B05XA01", "holder": "Listed", "substances": "X"},
             {"source": "aifa", "native_ids": "600223", "atc5": None, "holder": None, "substances": None}]
    assert registers.fill(items, {"cima": reg}) == 1
    assert items[0]["atc5"] == "B05BB01" and items[0]["atc_method"] == "register" and items[0]["holder"].startswith("Fresenius")
    assert items[1]["atc5"] == "B05XA01" and items[1]["holder"] == "Listed" and items[2]["atc5"] is None


def test_fimea_register_pads_vnr_and_fills_product():
    head = "PAKKAUSNRO;VNRNRO;PAKKAUSKOKO;LAAKENIMI;VAHVUUS;LAAKEMUOTONIMI;HALTIJA;ATCKOODI\n"
    body = (head + "25;460105;50;CARBO MEDICINALIS;250 mg;tabletti;Orifarm Healthcare A/S;A07BA01\n"
            "26;51;30;PARACETAMOL;500 mg;tabletti;Orion Oyj;N02BE01\n160484;;1;LENTOCILIN;1 ml;inj;Atral;J01CE08\n").encode("cp1252")
    reg = registers.parse_fimea_reg(body)
    assert set(reg) == {"460105", "000051"}
    items = [{"source": "fimea", "native_ids": "000051", "atc5": None, "holder": "Orion Pharma", "product": None}]
    registers.fill(items, {"fimea": reg})
    assert items[0]["atc5"] == "N02BE01" and items[0]["product"] == "PARACETAMOL 500 mg" and items[0]["holder"] == "Orion Pharma"
