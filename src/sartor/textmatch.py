"""Small deterministic text-matching helpers shared by S-004..S-008."""

from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9+#.]+")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?(?![\d%])")
_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}(?:-\d{2})?|\d{4}|\d{1,2}/\d{4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)
STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "you",
    "your",
    "will",
    "have",
    "has",
    "this",
    "their",
    "our",
    "we",
    "who",
    "can",
}


def words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in STOP and len(w) > 1}


def numbers(text: str) -> set[str]:
    found = {n.replace(",", "") for n in _NUMBER_RE.findall(text)}
    return found


def dates(text: str) -> set[str]:
    return {d.lower() for d in _DATE_RE.findall(text)}


def overlap(a: str, b: str) -> float:
    """Share of ``a`` words also present in ``b`` (0..1)."""
    wa, wb = words(a), words(b)
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def leaf_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(leaf_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(leaf_strings(item))
    return out


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()
