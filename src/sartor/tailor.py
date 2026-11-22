"""Tailoring: select and rephrase, never add facts (S-006).

The tailored resume is a profile subset ordered for one target, with
bullets rephrased for relevance and keyword match. Every bullet must
carry at least one evidence span id from the profile or sources.
"""

from __future__ import annotations

from pathlib import Path

from sartor.providers import Provider


class TailorError(Exception):
    """Raised when tailoring cannot produce an evidence-linked model."""


def tailor_resume(project: Path, target: str, provider: Provider) -> Path:
    """Write ``exports/<target>/tailored.json``."""
    raise NotImplementedError("S-006: tailor")
