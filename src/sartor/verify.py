"""Verification: every claim checked against its evidence (S-007).

Deterministic checks first (evidence present; dates, titles and
numbers appear in the cited spans; no unsupported skills), optional
LLM entailment second. Verdicts per bullet: supported, weak,
unsupported. Default keeps-and-flags; ``strict`` drops instead.
"""

from __future__ import annotations

from pathlib import Path

VERDICTS = ("supported", "weak", "unsupported")


class VerifyError(Exception):
    """Raised when verification cannot run."""


def verify_resume(
    project: Path, target: str, *, strict: bool = False, llm: bool = False
) -> Path:
    """Write ``exports/<target>/verify.json``; flag or drop per ``strict``."""
    raise NotImplementedError("S-007: verify")
