"""Page context: Methodik. Adds the archive figures F29 and F21 from the page "Idee und Aufbau"."""
from __future__ import annotations

from . import Quellen
from .idee import archiv_daten, f21_figure, f29_figure, versionen


def context(q: Quellen) -> dict:
    return {"f29": f29_figure(archiv_daten(q)), "f21": f21_figure(versionen(q.archive_root))}
