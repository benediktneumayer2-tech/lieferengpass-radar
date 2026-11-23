"""Page context: start. Figure F01 of the situation block; F22 and the page layout come from `site.py`."""
from __future__ import annotations

from ..charts import NARROW, WIDE, lage
from ..site import ATC1, _status_rank
from ..timeline import de, status_class
from . import Quellen

ACTIVE = ("Nicht verfügbar", "eingeschränkt verfügbar")
# Short names for the chart; the full ATC names stay in its tooltips and in the table of the situation block.
ATC_SHORT = {
    "A": "Verdauung, Stoffwechsel", "B": "Blut", "C": "Herz-Kreislauf", "D": "Haut", "G": "Urogenital, Sexualhormone",
    "H": "Hormone, systemisch", "J": "Antiinfektiva", "L": "Onkologie, Immunsystem", "M": "Muskel, Skelett",
    "N": "Nervensystem", "P": "Antiparasitika", "R": "Atemwege", "S": "Sinnesorgane", "V": "Varia",
    "Q": "Tierarzneimittel", "?": "ohne ATC-Angabe",
}


def f01_data(sit: dict) -> dict:
    status = sorted(sit["by_status"].items(), key=lambda kv: _status_rank(kv[0]))
    groups = sorted(sit["active_by_atc1"].items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "total": sit["packages"],
        "active": sit["active"],
        "status": [{"name": s, "n": n, "cls": status_class(s), "active": s in ACTIVE} for s, n in status],
        "groups": [{"code": c, "short": ATC_SHORT.get(c, c), "full": f"{c} {ATC1.get(c, c)}", "n": n} for c, n in groups],
    }


def context(q: Quellen) -> dict:
    data = f01_data(q.data.m["situation"])
    if not data["total"] or not data["groups"]:
        return {}
    return {"f01": {
        "id": "f01",
        "kind": "live",
        "legend": "Status und ATC-Hauptgruppen",
        "svg_wide": lage.f01(data, width=WIDE, uid="f01w"),
        "svg_narrow": lage.f01(data, width=NARROW, uid="f01n"),
        "caption": "Status wörtlich aus der BASG-Liste, Gruppierung nach ATC-Hauptgruppe: eigene Auswertung. "
                   "Die Zahlen stehen in der Tabelle darunter.",
        "table": None,
        "source": f"BASG-Liste vom {de(q.ref)}",
    }}
