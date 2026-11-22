"""Job targets: parsed advertisements (S-005).

A target keeps must-haves, nice-to-haves, keywords, seniority and
explicit selection criteria — each requirement with the verbatim ad
sentence it came from, so the person can audit the parse. The raw ad
text is stored beside the parse (``targets/<name>.txt``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sartor.modeljson import ModelJsonError, parse_model_json
from sartor.providers import Provider
from sartor.textmatch import norm

SYSTEM_PROMPT = (
    "You parse job advertisements into structured requirements. Copy "
    "each requirement's source sentence exactly as written in the ad. "
    "Never invent requirements. Reply with one JSON object."
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class TargetError(Exception):
    """Raised when an advertisement cannot be parsed into a target."""


def build_parse_prompt(ad_text: str) -> str:
    """The exact prompt ``add_target`` sends (exposed for recorded tests)."""
    return "\n".join(
        [
            "Parse this job advertisement into JSON with keys:",
            "  title, organisation, seniority, keywords (list of strings),",
            "  must_haves, nice_to_haves, selection_criteria — each a list of",
            '  {"text": short requirement, "quote": exact sentence from the ad}.',
            "",
            ad_text,
        ]
    )


def _clean_requirements(raw: Any, ad_text: str) -> list[dict[str, str]]:
    """Keep only requirements whose quote really appears in the ad."""
    if not isinstance(raw, list):
        return []
    haystack = norm(ad_text)
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            text, quote = item.strip(), item.strip()
        elif isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            quote = str(item.get("quote", text)).strip()
        else:
            continue
        if text and quote and norm(quote) in haystack:
            out.append({"text": text, "quote": quote})
    return out


def parse_target(name: str, ad_text: str, provider: Provider) -> dict[str, Any]:
    """Parse ad text into a target dict (no files are written)."""
    if not ad_text.strip():
        raise TargetError("No requirements found in the advertisement text")
    try:
        data = parse_model_json(
            provider.chat(SYSTEM_PROMPT, build_parse_prompt(ad_text))
        )
    except ModelJsonError as exc:
        raise TargetError(str(exc)) from exc
    must = _clean_requirements(data.get("must_haves"), ad_text)
    nice = _clean_requirements(data.get("nice_to_haves"), ad_text)
    criteria = _clean_requirements(data.get("selection_criteria"), ad_text)
    if not (must or nice or criteria):
        raise TargetError("No requirements found in the advertisement text")
    keywords_raw = data.get("keywords")
    keywords = (
        [str(k).strip() for k in keywords_raw if str(k).strip()]
        if isinstance(keywords_raw, list)
        else []
    )
    return {
        "name": name,
        "title": str(data.get("title", "")).strip(),
        "organisation": str(data.get("organisation", "")).strip(),
        "seniority": str(data.get("seniority", "")).strip(),
        "keywords": keywords,
        "must_haves": must,
        "nice_to_haves": nice,
        "selection_criteria": criteria,
    }


def add_target(
    project: Path,
    name: str,
    ad_text: str,
    provider: Provider,
    *,
    force: bool = False,
    source_label: str = "the advertisement text",
) -> Path:
    """Parse ``ad_text`` into ``targets/<name>.json`` (+ ``.txt``)."""
    if not _NAME_RE.match(name):
        raise TargetError(
            f"Invalid target name {name!r}: use letters, digits, '.', '_' or '-'"
        )
    targets_dir = project / "targets"
    out = targets_dir / f"{name}.json"
    if out.exists() and not force:
        raise TargetError(f"Target {name!r} exists; pass --force to replace it")
    if not ad_text.strip():
        raise TargetError(f"No requirements found in {source_label}")
    try:
        target = parse_target(name, ad_text, provider)
    except TargetError as exc:
        if str(exc).startswith("No requirements found in the advertisement"):
            raise TargetError(f"No requirements found in {source_label}") from exc
        raise
    targets_dir.mkdir(parents=True, exist_ok=True)
    (targets_dir / f"{name}.txt").write_text(ad_text, encoding="utf-8")
    out.write_text(
        json.dumps(target, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def load_target(project: Path, name: str) -> dict[str, Any]:
    path = project / "targets" / f"{name}.json"
    if not path.is_file():
        raise TargetError(
            f"No target {name!r}: run `sartor target add {name} --file ad.txt`"
        )
    return json.loads(path.read_text(encoding="utf-8"))
