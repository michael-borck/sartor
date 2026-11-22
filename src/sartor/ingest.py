"""Ingest sources into span-addressed JSON (S-003).

PDF, DOCX, HTML, MD, TXT and JSON become ``sources/<file>.json`` with
stable span ids (``src://<file>#s<N>``) that evidence links point at.
Re-ingesting an unchanged file produces a byte-identical source file:
no timestamps are stored. Originals are never modified.

A JSON Resume file is stored losslessly (the parsed object is kept
verbatim under ``json_resume``) and marked ``profile_candidate`` so
S-004 can use it as a profile directly.

Format libraries are imported lazily; they live in the ``import``
extra (``pip install "sartor[import]"``).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SUPPORTED_SUFFIXES = (".pdf", ".docx", ".html", ".htm", ".md", ".txt", ".json")

_KIND = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".html": "html",
    ".htm": "html",
    ".md": "md",
    ".txt": "txt",
    ".json": "json",
}

_BULLET_RE = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


class IngestError(Exception):
    """Raised when a file cannot be ingested."""


def supported_text() -> str:
    return ", ".join(SUPPORTED_SUFFIXES)


# --- extraction -------------------------------------------------------


def _need(module: str, extra: str) -> None:
    raise IngestError(f'needs the {module!r} package: pip install "sartor[{extra}]"')


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        _need("pypdf", "import")
    try:
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise IngestError(f"cannot read PDF ({exc.__class__.__name__})") from exc
    return "\n\n".join(pages)


def _extract_docx(path: Path) -> str:
    try:
        import docx
    except ImportError:
        _need("python-docx", "import")
    try:
        document = docx.Document(str(path))  # type: ignore[attr-defined]
    except Exception as exc:
        raise IngestError(f"cannot read DOCX ({exc.__class__.__name__})") from exc
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.extend(cell.text for cell in row.cells)
    return "\n".join(lines)


def _extract_html(path: Path) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        _need("beautifulsoup4", "import")
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    # Blank line between block elements, so headings and paragraphs
    # become separate spans instead of one run-on paragraph.
    return soup.get_text("\n\n")


def _extract_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _leaf_strings(value: Any) -> list[str]:
    """Every string leaf of a JSON value, in document order."""
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(_leaf_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_leaf_strings(item))
    return out


def _is_json_resume(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    schema = str(data.get("$schema", ""))
    if "jsonresume" in schema:
        return True
    return "basics" in data and isinstance(data.get("basics"), dict)


# --- spans ------------------------------------------------------------


def split_spans(text: str) -> list[str]:
    """Split extracted text into evidence-sized spans, deterministically.

    Headings and list items are their own spans; other consecutive
    lines form a paragraph that is split into sentences. Blank lines
    are boundaries. The same text always yields the same spans.
    """
    spans: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        joined = " ".join(part.strip() for part in paragraph if part.strip())
        paragraph.clear()
        for sentence in _SENTENCE_RE.split(joined):
            sentence = sentence.strip()
            if sentence:
                spans.append(sentence)

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
        elif _HEADING_RE.match(line):
            flush()
            spans.append(_HEADING_RE.sub("", line).strip())
        elif _BULLET_RE.match(line):
            flush()
            spans.append(_BULLET_RE.sub("", line).strip())
        else:
            paragraph.append(line)
    flush()
    return [span for span in spans if span]


# --- ingest -----------------------------------------------------------


def build_source(path: Path) -> dict[str, Any]:
    """Build the source record for one file (no files are written)."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestError(
            f"{path.name}: unsupported file type {suffix or '(none)'!r}; "
            f"supported: {supported_text()}"
        )
    if not path.is_file():
        raise IngestError(f"{path.name}: no such file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IngestError(f"{path.name}: cannot read file ({exc})") from exc

    record: dict[str, Any] = {
        "source": path.name,
        "kind": _KIND[suffix],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "profile_candidate": False,
    }
    try:
        if suffix == ".json":
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise IngestError(f"{path.name}: invalid JSON ({exc})") from exc
            texts = _leaf_strings(data)
            if _is_json_resume(data):
                record["profile_candidate"] = True
                record["json_resume"] = data
        elif suffix == ".pdf":
            texts = split_spans(_extract_pdf(path))
        elif suffix == ".docx":
            texts = split_spans(_extract_docx(path))
        elif suffix in (".html", ".htm"):
            texts = split_spans(_extract_html(path))
        else:
            texts = split_spans(_extract_text(path))
    except IngestError as exc:
        if str(exc).startswith(path.name):
            raise
        raise IngestError(f"{path.name}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise IngestError(f"{path.name}: not UTF-8 text") from exc

    record["spans"] = [
        {"id": f"src://{path.name}#s{n}", "n": n, "text": text}
        for n, text in enumerate(texts, start=1)
    ]
    return record


def ingest_file(path: Path, project: Path) -> Path:
    """Ingest one file; return the written ``sources/<file>.json``."""
    record = build_source(path)
    sources_dir = project / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    out = sources_dir / f"{path.name}.json"
    out.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def span_count(source_json: Path) -> int:
    data = json.loads(source_json.read_text(encoding="utf-8"))
    return len(data.get("spans", []))
