"""The profile: a hand-owned JSON Resume file (S-004).

``build`` drafts ``profile.json`` from the ingested sources:

- If a source ingested as a JSON Resume (S-003 ``profile_candidate``),
  that object is used verbatim — no model call.
- Otherwise the provider is asked for a JSON Resume draft built only
  from the source spans. Invalid model JSON is saved to
  ``profile.draft.txt`` for inspection; the profile is not written.

Either way the draft is validated against the bundled JSON Resume
schema, and per-entry evidence span ids are stored under
``meta.sartor.evidence`` (paths like ``work[0]``), matched
deterministically against the source spans. Building never silently
overwrites an existing profile. ``check`` validates the hand-edited
file and names the first invalid field by path.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from sartor.modeljson import ModelJsonError, parse_model_json
from sartor.providers import Provider
from sartor.textmatch import leaf_strings, overlap

SECTIONS = (
    "work",
    "volunteer",
    "education",
    "awards",
    "certificates",
    "publications",
    "skills",
    "languages",
    "interests",
    "references",
    "projects",
)

SYSTEM_PROMPT = (
    "You distil source material into a JSON Resume profile. Use only "
    "facts stated in the sources; never invent dates, employers, "
    "numbers, or skills. Reply with one JSON object and nothing else."
)


class ProfileError(Exception):
    """Raised when the profile cannot be built or is invalid."""


def load_schema() -> dict[str, Any]:
    resource = files("sartor").joinpath("data/resume-schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def load_sources(project: Path) -> list[dict[str, Any]]:
    """Every ingested source record under ``sources/`` (S-003 output)."""
    sources_dir = project / "sources"
    if not sources_dir.is_dir():
        return []
    records = []
    for path in sorted(sources_dir.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def all_spans(records: list[dict[str, Any]]) -> dict[str, str]:
    """Span id -> span text, across every source record."""
    spans: dict[str, str] = {}
    for record in records:
        for span in record.get("spans", []):
            spans[str(span["id"])] = str(span["text"])
    return spans


def _format_path(error: Any) -> str:
    parts: list[str] = []
    for part in error.absolute_path:
        if isinstance(part, int):
            parts.append(f"[{part}]")
        else:
            parts.append(f".{part}" if parts else str(part))
    return "".join(parts) or "(root)"


def validate_profile(profile: dict[str, Any]) -> None:
    """Validate against the bundled schema; raise ProfileError."""
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ProfileError(
            "needs the 'jsonschema' package: pip install \"sartor[schema]\""
        ) from exc
    validator = Draft7Validator(load_schema())
    errors = sorted(validator.iter_errors(profile), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        raise ProfileError(f"{_format_path(first)}: {first.message}")


def check_profile(project: Path) -> dict[str, Any]:
    """Validate profile.json; return it parsed."""
    path = project / "profile.json"
    if not path.is_file():
        raise ProfileError(
            "No profile yet: run `sartor profile build` (after `sartor ingest FILE…`)"
        )
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"profile.json: invalid JSON ({exc})") from exc
    if not isinstance(profile, dict):
        raise ProfileError("profile.json: expected a JSON object")
    validate_profile(profile)
    return profile


def _match_evidence(entry: Any, spans: dict[str, str]) -> list[str]:
    """Best-matching source span ids for one profile entry."""
    leaves = leaf_strings(entry)
    scored: list[tuple[float, str]] = []
    for span_id, text in spans.items():
        score = max((overlap(leaf, text) for leaf in leaves), default=0.0)
        # Small leaves (a name, a date) count strongly when contained.
        contained = any(
            leaf.lower() in text.lower() for leaf in leaves if len(leaf) >= 4
        )
        if contained:
            score = max(score, 0.9)
        if score >= 0.34:
            scored.append((score, span_id))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [span_id for _, span_id in scored[:5]]


def attach_evidence(profile: dict[str, Any], spans: dict[str, str]) -> dict[str, Any]:
    """Store per-entry evidence span ids under meta.sartor.evidence."""
    evidence: dict[str, list[str]] = {}
    if isinstance(profile.get("basics"), dict):
        matched = _match_evidence(profile["basics"], spans)
        if matched:
            evidence["basics"] = matched
    for section in SECTIONS:
        entries = profile.get(section)
        if isinstance(entries, list):
            for index, entry in enumerate(entries):
                matched = _match_evidence(entry, spans)
                if matched:
                    evidence[f"{section}[{index}]"] = matched
    meta = dict(profile.get("meta") or {})
    sartor_meta = dict(meta.get("sartor") or {})
    sartor_meta["evidence"] = evidence
    meta["sartor"] = sartor_meta
    profile["meta"] = meta
    return profile


def build_distil_prompt(records: list[dict[str, Any]]) -> str:
    """The exact prompt ``build`` sends (exposed for recorded tests)."""
    lines = [
        "Build a JSON Resume (schema v1.0.0) from these source spans.",
        "Include basics, work, education, skills, projects, publications "
        "when the sources support them. Keep every date and number exactly "
        "as written (dates as YYYY-MM-DD when a day is known).",
        "",
    ]
    for record in records:
        for span in record.get("spans", []):
            lines.append(f"[{span['id']}] {span['text']}")
    return "\n".join(lines)


def build_profile(project: Path, provider: Provider, *, force: bool = False) -> Path:
    """Draft profile.json from ingested sources."""
    out = project / "profile.json"
    if out.exists() and not force:
        raise ProfileError("profile.json exists; move it aside or pass --force")
    records = load_sources(project)
    if not records:
        raise ProfileError("No sources yet: sartor ingest FILE…")
    spans = all_spans(records)

    candidate = next(
        (r for r in records if r.get("profile_candidate") and "json_resume" in r),
        None,
    )
    if candidate is not None:
        profile = json.loads(json.dumps(candidate["json_resume"]))
    else:
        reply = provider.chat(SYSTEM_PROMPT, build_distil_prompt(records))
        try:
            profile = parse_model_json(reply)
        except ModelJsonError as exc:
            (project / "profile.draft.txt").write_text(reply, encoding="utf-8")
            raise ProfileError(f"{exc} — raw reply saved to profile.draft.txt") from exc

    profile = attach_evidence(profile, spans)
    try:
        validate_profile(profile)
    except ProfileError as exc:
        if candidate is None:
            (project / "profile.draft.txt").write_text(
                json.dumps(profile, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            raise ProfileError(
                f"draft profile is not valid JSON Resume: {exc} "
                "— saved to profile.draft.txt"
            ) from exc
        raise
    out.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out
