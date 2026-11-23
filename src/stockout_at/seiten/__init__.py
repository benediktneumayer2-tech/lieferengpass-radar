"""Context of the redesigned pages, one module per page. Display only: nothing here writes.

Imported only inside `site.generate()`, so that figure code can never break `from .site import HIDDEN_SOURCES`.
"""
from __future__ import annotations

import importlib
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

SEITEN = ("start", "projekt", "idee", "modell", "befunde", "methodik", "fruehwarnung", "ueber", "radar")


@dataclass(frozen=True)
class Quellen:
    """What a page may read while the database is open."""
    conn: sqlite3.Connection
    archive_root: Path | None
    results: dict  # web/data/ergebnisse.json
    data: Any  # site.Data
    fw: dict  # fruehwarnung.build
    ref: date  # reference day of the data; pages use no clock


def build(q: Quellen) -> dict[str, dict]:
    """Contexts by page. A failing page must not stop the daily build: it then renders without its figures."""
    out: dict[str, dict] = {}
    for name in SEITEN:
        try:
            out[name] = importlib.import_module(f".{name}", __name__).context(q)
        except Exception as exc:
            out[name] = {}
            print(f"WARNUNG Seite {name}: {type(exc).__name__}: {exc}")
    return out
