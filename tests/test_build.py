from datetime import date

from stockout_at import basg, metrics
from stockout_at.archive import Archive
from stockout_at.build import build
from stockout_at.episodes import SnapshotView, derive
from stockout_at.substances import base_substance, normalise

NV, EV, V, S4 = "Nicht verfügbar", "eingeschränkt verfügbar", "verfügbar", "verfügbar gemäß §4 (1)"


def row(status, beginn="2026-01-05", meldung="2026-01-05", wb=None):
    return {
        "Status": status,
        "Beginn_Vertriebseinschraenkung": beginn,
        "Datum_Meldung": meldung,
        "Datum_letzte_Aenderung": meldung,
        "Datum_voraussichtliche_Wiederbelieferung": wb,
    }


def snaps(*days, complete=True):
    """days: (iso_date, {key: row}) pairs -> SnapshotViews."""
    return [SnapshotView(d, date.fromisoformat(d), complete, rows) for d, rows in days]


def test_start_shift_and_end_by_status_daily():
    eps = derive(
        snaps(
            ("2026-01-09", {}),
            ("2026-01-10", {"A": row(NV, wb="2026-02-01")}),
            ("2026-01-11", {"A": row(EV, wb="2026-02-15")}),
            ("2026-01-12", {"A": row(EV, wb="2026-02-15")}),
            ("2026-01-13", {"A": row(V, beginn=None, meldung="2026-01-12")}),
        )
    )
    assert len(eps) == 1
    ep = eps[0]
    assert (ep.start_date, ep.start_source, ep.first_seen) == (date(2026, 1, 5), "beginn", date(2026, 1, 10))
    assert ep.statuses == [(NV, date(2026, 1, 10)), (EV, date(2026, 1, 11)), (V, date(2026, 1, 13))]
    assert ep.resupply == [("2026-02-01", date(2026, 1, 10)), ("2026-02-15", date(2026, 1, 11))]
    assert ep.n_shifts == 1
    assert (ep.end_reason, ep.end_lower, ep.end_upper) == ("status", date(2026, 1, 12), date(2026, 1, 13))
    assert ep.end_report_date == "2026-01-12"
    assert not ep.end_interval_censored and ep.history_quality == "daily"


def test_disappearance_is_interval_and_truncated_snapshot_is_no_absence():
    days = snaps(("2026-01-10", {"A": row(NV)}), ("2026-03-01", {"A": row(NV)}))
    days += snaps(("2026-04-01", {}), complete=False)  # truncated capture: absence proves nothing
    days += snaps(("2026-05-01", {}))
    (ep,) = derive(days)
    assert (ep.end_reason, ep.end_lower, ep.end_upper) == ("disappeared", date(2026, 3, 1), date(2026, 5, 1))
    assert ep.end_interval_censored and ep.history_quality == "sparse"


def test_rereport_after_end_and_unseen_rereport():
    eps = derive(
        snaps(
            ("2026-01-10", {"A": row(NV)}),
            ("2026-01-11", {"A": row(V, beginn=None)}),
            ("2026-01-12", {}),
            ("2026-02-01", {"A": row(NV, beginn="2026-01-30", meldung="2026-01-30")}),
            # newer Beginn than our last sighting: the 2nd episode ended unseen in between
            ("2026-04-01", {"A": row(NV, beginn="2026-03-20", meldung="2026-03-20")}),
        )
    )
    assert [e.seq_no for e in eps] == [1, 2, 3]
    assert eps[0].end_reason == "status"
    assert eps[1].start_date == date(2026, 1, 30)
    assert (eps[1].end_reason, eps[1].end_lower, eps[1].end_upper) == ("rereported", date(2026, 2, 1), date(2026, 3, 20))
    assert eps[2].start_date == date(2026, 3, 20) and not eps[2].ended


def test_section4_is_not_an_end_and_announcement_opens_nothing():
    eps = derive(
        snaps(
            ("2026-01-10", {"A": row(S4), "B": row(V, beginn=None, meldung="2026-01-09")}),
            ("2026-01-11", {"A": row(S4), "B": row(NV, beginn="2026-01-11", meldung="2026-01-09")}),
        )
    )
    a, b = sorted(eps, key=lambda e: e.package_key)
    assert not a.ended
    # B was pre-announced as "verfügbar" without Beginn: the episode starts with the restriction
    assert (b.seq_no, b.start_date, b.first_seen, b.ended) == (1, date(2026, 1, 11), date(2026, 1, 11), False)


def test_status_flip_with_old_beginn_falls_back_to_first_seen():
    eps = derive(
        snaps(
            ("2026-01-10", {"A": row(NV)}),
            ("2026-01-11", {"A": row(V)}),
            ("2026-01-20", {"A": row(NV)}),
        )
    )
    assert len(eps) == 2
    assert (eps[1].start_date, eps[1].start_source) == (date(2026, 1, 20), "first_seen")


def test_substance_normaliser():
    assert base_substance("ZOLPIDEMTARTRAT") == "ZOLPIDEM"
    assert base_substance("ZOLPIDEM TARTRATE") == "ZOLPIDEM"
    assert base_substance("METAMIZOL NATRIUM MONOHYDRAT") == "METAMIZOL"
    assert base_substance("NATRIUM PREDNISOLON SUCCINAT") == "PREDNISOLON"
    for unchanged in ("NATRIUMCHLORID", "BARIUMSULFAT", "DIMETHYLFUMARAT", "FLUTICASONPROPIONAT", "EISEN(II)-FUMARAT"):
        assert base_substance(unchanged) == unchanged
    assert normalise("LOSARTAN KALIUM, HYDROCHLOROTHIAZID") == ("HYDROCHLOROTHIAZID", "LOSARTAN")
    assert normalise("CALCIPOTRIOL, WASSERFREI") == ("CALCIPOTRIOL",)
    assert normalise("INFLUENZAVIRUS (AUSZUG, PRODUKTE), INFLUENZAVIRUS (AUSZUG, PRODUKTE)") == (
        "INFLUENZAVIRUS (AUSZUG, PRODUKTE)",
    )
    assert normalise("") == ()


def _basg(produced_on, packungen):
    body = f'<?xml version="1.0" encoding="UTF-8"?><VEASP><Meta producedOn="{produced_on}"/><Packungen>{packungen}</Packungen></VEASP>'
    return body.encode()


PACK = (
    '<Packung PZN="{pzn}" Zulassungsnummer="1-1" Datum_Meldung="2026-09-01" Datum_letzte_Aenderung="2026-09-01" '
    'Beginn_Vertriebseinschraenkung="2026-09-01"{wb}><Status>{status}</Status><Wirkstoffe>ZOLPIDEMTARTRAT</Wirkstoffe>'
    "<ATCCodes>N05CF02</ATCCodes><Neu>x</Neu></Packung>"
)


def test_parser_tolerates_truncation_and_unknown_elements():
    body = _basg("2026-10-16T02:00:00", PACK.format(pzn="1", status=NV, wb="") + PACK.format(pzn="2", status=NV, wb=""))
    snap = basg.parse(body[:-30])
    assert snap.produced_on == "2026-10-16T02:00:00" and not snap.complete and len(snap.packages) == 1
    assert snap.packages[0]["Unit"] is None and '"Neu": "x"' in snap.packages[0]["extra"]
    assert basg.package_key({"PZN": "", "Zulassungsnummer": "ALL-1", "Packungsgroesse": "4"}) == "Z:ALL-1|4||"


def test_build_is_deterministic_and_overdue(tmp_path):
    archive = Archive(tmp_path / "archive")
    wb = ' Datum_voraussichtliche_Wiederbelieferung="{}"'
    day1 = PACK.format(pzn="1", status=NV, wb=wb.format("2026-10-01")) + PACK.format(pzn="2", status=EV, wb="")
    day2 = (
        PACK.format(pzn="1", status=NV, wb=wb.format("2026-10-01"))
        + PACK.format(pzn="2", status=EV, wb=wb.format("2026-12-01"))
        + PACK.format(pzn="3", status=V, wb="")
    )
    for stamp, body in (("2026-10-16T02:00:00", day1), ("2026-10-17T02:00:00", day2)):
        archive.store("basg", _basg(stamp, body), ext="xml", stamp=stamp.replace(":", "-"), meta={"produced_on": stamp})
    db1, db2 = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    counts = build(archive, db1)
    build(archive, db2)
    assert counts["snapshots"] == 2 and counts["episodes"] == 3

    def dump(path):
        conn = metrics.connect(path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in tables}

    assert dump(db1) == dump(db2)
    conn = metrics.connect(db1)
    data = metrics.collect(conn)
    assert data["situation"]["active"] == 2 and data["situation"]["active_with_resupply_date"] == 2
    assert [(o["pzn"], o["days_overdue"]) for o in data["overdue"]] == [("1", 16)]
    ep2 = conn.execute("SELECT history_quality, n_shifts FROM episodes WHERE package_key = '2'").fetchone()
    assert tuple(ep2) == ("sparse", 0)  # first file has no predecessor
