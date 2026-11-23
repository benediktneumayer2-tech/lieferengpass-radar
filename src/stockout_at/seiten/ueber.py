"""Page context: about. Only what the owner has released (D1): name, Vienna, repository."""
from __future__ import annotations

from . import Quellen

NAME = "Benedikt Neumayer"
ORT = "Wien"
# The owner's short personal text goes here, paragraph by paragraph. While empty, the page shows no placeholder.
PERSOENLICHER_TEXT: tuple[str, ...] = ()


def context(q: Quellen) -> dict:
    url = q.results["vorab_registrierung"]["repository"]
    return {"name": NAME, "ort": ORT, "repository": url, "repository_label": url.removeprefix("https://"),
            "persoenlich": PERSOENLICHER_TEXT}
