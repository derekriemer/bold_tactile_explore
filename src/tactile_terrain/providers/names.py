"""Name normalisation for include_names matching."""

from __future__ import annotations

import re

ABBREVIATIONS = {
    "ck": "creek",
    "cr": "creek",
    "crk": "creek",
    "mt": "mount",
    "mtn": "mountain",
    "riv": "river",
    "rd": "road",
    "hwy": "highway",
    "ft": "fort",
    "lk": "lake",
    "pk": "peak",
}


def normalise_name(name: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    return " ".join(ABBREVIATIONS.get(t, t) for t in tokens)


def name_matches(name: str, wanted: list[str]) -> bool:
    return bool(name) and normalise_name(name) in {normalise_name(w) for w in wanted}
