"""Rendering: one tailored model, five files (S-009).

``resume.md``, ``resume.html``, ``resume.pdf`` (WeasyPrint from the
HTML, so the two never diverge), ``resume.docx`` (python-docx) and
``resume.json`` (JSON Resume). M1 ships one theme: ``ats-plain`` —
single column, real headings, ATS-parseable.
"""

from __future__ import annotations

from pathlib import Path

THEMES = ("ats-plain",)


class RenderError(Exception):
    """Raised when a format cannot be rendered."""


def render_bundle(project: Path, target: str, theme: str = "ats-plain") -> list[Path]:
    """Render every format into ``exports/<target>/``; return the paths."""
    raise NotImplementedError("S-009: render")
