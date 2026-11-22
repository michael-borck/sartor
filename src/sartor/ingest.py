"""Ingest sources into span-addressed JSON (S-003).

PDF, DOCX, HTML, MD, TXT and JSON Resume become
``sources/<name>.json`` with stable span ids (``src://<file>#s<N>``)
that evidence links point at. Originals are never modified.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SUFFIXES = (".pdf", ".docx", ".html", ".htm", ".md", ".txt", ".json")


class IngestError(Exception):
    """Raised when a file cannot be ingested."""


def ingest_file(path: Path, project: Path) -> Path:
    """Ingest one file; return the written ``sources/<name>.json``."""
    raise NotImplementedError("S-003: ingest")
