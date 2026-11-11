from stockout_at.foreign import latin_inn, listings, pl_rows


def _b(x0, x1, y0, y1, *lines):
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "lines": list(lines)}


HEADER = [_b(80, 92, 60, 68, "Lp."), _b(110, 225, 50, 80, "Nazwa produktu leczniczego, środka spożywczego"),
          _b(240, 330, 60, 68, "Nazwa międzynarodowa"), _b(390, 420, 60, 68, "Postać"), _b(520, 540, 60, 68, "Moc"),
          _b(575, 650, 60, 68, "Wielkość opakowania"), _b(680, 740, 52, 76, "Kod GTIN lub inny kod")]


def test_cells_join_the_row_whose_number_they_straddle_and_continue_across_pages():
    page1 = HEADER + [
        _b(81, 91, 100, 108, "1."), _b(150, 190, 100, 108, "Atenza"),
        _b(240, 328, 96, 112, "Methylphenidati", "hydrochloridum"),  # two lines centred on row 1
        _b(520, 540, 100, 108, "18 mg"), _b(684, 738, 88, 96, "05909991495817"), _b(684, 738, 100, 108, "05909991495800"),
        _b(81, 91, 130, 138, "2."), _b(150, 190, 130, 138, "Zyprexa"), _b(250, 320, 130, 138, "Olanzapinum"),
        _b(520, 540, 130, 138, "10 mg"),
    ]
    page2 = [_b(51, 189, 42, 50, "Dziennik Urzędowy Ministra Zdrowia"),
             _b(684, 738, 80, 88, "05909990954612"),  # continuation of row 2 above the page's first number
             _b(81, 91, 110, 118, "3."), _b(150, 190, 110, 118, "Apidra"), _b(250, 320, 110, 118, "Insulinum glulisinum")]
    rows = pl_rows([page1, page2])
    assert [(r["lp"], r.get("product"), r.get("inn"), r.get("strength")) for r in rows] == [
        (1, "Atenza", "Methylphenidati hydrochloridum", "18 mg"), (2, "Zyprexa", "Olanzapinum", "10 mg"),
        (3, "Apidra", "Insulinum glulisinum", None)]
    assert rows[0]["codes"] == ["05909991495817", "05909991495800"] and rows[1]["codes"] == ["05909990954612"]


def test_latin_inns_become_base_names():
    assert latin_inn("Methylphenidati hydrochloridum") == "Methylphenidat hydrochlorid"
    assert latin_inn("Diclofenacum natricum") == "Diclofenac natrium"
    assert latin_inn("Formoterolum fumaras dihydricus") == "Formoterol fumarat"


def test_listings_start_again_after_a_gap():
    a, b = {"item_id": "a", "signal_date": None}, {"item_id": "b", "signal_date": None}
    out = listings([("2024-01-01", [a]), ("2024-03-01", [a, b]), ("2024-05-01", [b]), ("2024-07-01", [a, b])])
    assert [(it["item_id"], it["signal_date"]) for _, its in out for it in its] == [
        ("a:2024-01-01", "2024-01-01"), ("a:2024-01-01", "2024-01-01"), ("b:2024-03-01", "2024-03-01"),
        ("b:2024-03-01", "2024-03-01"), ("a:2024-07-01", "2024-07-01"), ("b:2024-03-01", "2024-03-01")]
