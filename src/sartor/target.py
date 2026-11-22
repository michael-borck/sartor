"""Job targets: parsed advertisements (S-005).

A target keeps must-haves, nice-to-haves, keywords, seniority and
explicit selection criteria — each requirement with the verbatim ad
sentence it came from. The raw ad text is stored beside the parse.
"""

from __future__ import annotations

from pathlib import Path

from sartor.providers import Provider


class TargetError(Exception):
    """Raised when an advertisement cannot be parsed into a target."""


def add_target(project: Path, name: str, ad_text: str, provider: Provider) -> Path:
    """Parse ``ad_text`` into ``targets/<name>.json`` (+ ``.txt``)."""
    raise NotImplementedError("S-005: target add")
