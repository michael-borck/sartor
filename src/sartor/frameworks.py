"""User-supplied skill frameworks (S-014, S-015).

Framework data is never bundled or fetched: the person adds their own
SFIA / O*NET / ESCO / AQF / custom file (CSV or JSON), normalized to
``frameworks/<name>.json``. Mapping is deterministic — framework
skill names/codes/keywords matched against profile text and source
spans on one side, target requirements and keywords on the other.
No model call, so a mapping is fully auditable.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from sartor.profile import ProfileError, all_spans, check_profile, load_sources
from sartor.target import TargetError, load_target
from sartor.textmatch import leaf_strings, norm, words

FRAMEWORK_KINDS = ("sfia", "onet", "esco", "aqf", "custom")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GENERIC = {
    "experience",
    "experienced",
    "work",
    "working",
    "role",
    "years",
    "year",
    "skills",
    "skill",
    "ability",
    "knowledge",
    "strong",
    "including",
    "using",
    "use",
    "data",
    "team",
    "teams",
}


class FrameworkError(Exception):
    """Raised when a framework cannot be added or mapped."""


def _keywords(raw: Any) -> list[str]:
    if isinstance(raw, list):
        items = [str(item) for item in raw]
    elif isinstance(raw, str):
        items = re.split(r"[;|]", raw)
    else:
        items = []
    return [item.strip() for item in items if item.strip()]


def _rows_from_csv(text: str, filename: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    fields = {(field or "").strip().lower() for field in reader.fieldnames or []}
    if not {"code", "name"} <= fields:
        raise FrameworkError(
            f"{filename}: CSV needs code,name columns (got: "
            f"{', '.join(sorted(fields)) or 'none'})"
        )
    return [
        {(k or "").strip().lower(): (v or "") for k, v in row.items()} for row in reader
    ]


def _rows_from_json(text: str, filename: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FrameworkError(f"{filename}: invalid JSON ({exc})") from exc
    if isinstance(data, dict):
        data = data.get("skills")
    if not isinstance(data, list):
        raise FrameworkError(f'{filename}: JSON must be a list or {{"skills": [...]}}')
    return [row for row in data if isinstance(row, dict)]


def parse_framework(path: Path, name: str, kind: str) -> dict[str, Any]:
    """Parse a CSV/JSON framework file into the normalized record."""
    if not _NAME_RE.match(name):
        raise FrameworkError(
            f"Invalid framework name {name!r}: use letters, digits, '.', '_' or '-'"
        )
    if kind not in FRAMEWORK_KINDS:
        raise FrameworkError(
            f"unknown framework kind {kind!r}; expected one of: "
            f"{', '.join(FRAMEWORK_KINDS)}"
        )
    if not path.is_file():
        raise FrameworkError(f"{path.name}: no such file")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FrameworkError(f"{path.name}: not UTF-8 text") from exc
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _rows_from_csv(text, path.name)
    elif suffix == ".json":
        rows = _rows_from_json(text, path.name)
    else:
        raise FrameworkError(
            f"{path.name}: unsupported framework file type {suffix!r}; use .csv or .json"
        )
    skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, row in enumerate(rows, start=1):
        code = str(row.get("code", "")).strip()
        skill_name = str(row.get("name", "")).strip()
        if not code or not skill_name:
            raise FrameworkError(
                f"{path.name}: row {position} needs both code and name"
            )
        key = code.lower()
        if key in seen:
            raise FrameworkError(
                f"{path.name}: duplicate code {code!r} at row {position}"
            )
        seen.add(key)
        level_raw = row.get("level", "")
        level: Any = None
        if isinstance(level_raw, int):
            level = level_raw
        elif str(level_raw).strip().isdigit():
            level = int(str(level_raw).strip())
        elif str(level_raw).strip():
            level = str(level_raw).strip()
        skills.append(
            {
                "code": code,
                "name": skill_name,
                "level": level,
                "description": str(row.get("description", "")).strip(),
                "keywords": _keywords(row.get("keywords", "")),
            }
        )
    if not skills:
        raise FrameworkError(f"{path.name}: no framework skills found")
    return {
        "name": name,
        "kind": kind,
        "source_file": path.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "skills": skills,
    }


def add_framework(
    project: Path, path: Path, name: str, kind: str, *, force: bool = False
) -> Path:
    """Normalize and store a framework under ``frameworks/<name>.json``."""
    record = parse_framework(path, name, kind)
    out_dir = project / "frameworks"
    out = out_dir / f"{name}.json"
    if out.exists() and not force:
        raise FrameworkError(f"Framework {name!r} exists; pass --force to replace it")
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out


def list_frameworks(project: Path) -> list[dict[str, Any]]:
    frameworks_dir = project / "frameworks"
    out: list[dict[str, Any]] = []
    if not frameworks_dir.is_dir():
        return out
    for path in sorted(frameworks_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def load_framework(project: Path, name: str) -> dict[str, Any]:
    if not _NAME_RE.match(name):
        raise FrameworkError(f"Invalid framework name {name!r}")
    path = project / "frameworks" / f"{name}.json"
    if not path.is_file():
        raise FrameworkError(
            f"No framework {name!r}: run "
            f"`sartor framework add FILE --name {name} --kind sfia` "
            "(framework data is user-supplied, never bundled)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


# --- mapping (S-015) ---------------------------------------------------


def _skill_terms(skill: dict[str, Any]) -> list[str]:
    terms = [str(skill.get("code", "")), str(skill.get("name", ""))]
    terms.extend(str(k) for k in skill.get("keywords", []) or [])
    return [term for term in terms if term.strip()]


def _score_against(skill: dict[str, Any], texts: list[str]) -> tuple[float, str | None]:
    """Best deterministic score of a framework skill against texts."""
    best = 0.0
    best_text: str | None = None
    terms = _skill_terms(skill)
    wanted: set[str] = set()
    for term in terms:
        wanted.update(w for w in words(term) if w not in _GENERIC)
    primary: set[str] = set()
    keyword_terms = [
        str(skill.get("code", "")),
        *[str(k) for k in skill.get("keywords", []) or []],
    ]
    for term in keyword_terms:
        primary.update(w for w in words(term) if w not in _GENERIC)
    if not primary:
        primary = set(wanted)
    for text in texts:
        lowered = norm(text)
        score = 0.0
        for term in terms:
            normalized = norm(term)
            if normalized and re.search(
                rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", lowered
            ):
                score = max(score, 1.0)
        if wanted:
            score = max(score, len(wanted & words(text)) / len(wanted))
        if not (primary & words(text)):
            # Incidental name words ("operations") never make a match alone.
            score = min(score, 0.24)
        if score > best:
            best, best_text = score, text
    return best, best_text


def _status(score: float) -> str:
    if score >= 0.6:
        return "evidenced"
    if score >= 0.25:
        return "weak"
    return "gap"


def map_framework(project: Path, target_name: str, framework_name: str) -> Path:
    """Write ``exports/<target>/framework-<framework>.json``."""
    framework = load_framework(project, framework_name)
    try:
        profile = check_profile(project)
    except ProfileError as exc:
        raise FrameworkError(str(exc)) from exc
    try:
        target = load_target(project, target_name)
    except TargetError as exc:
        raise FrameworkError(str(exc)) from exc

    spans = all_spans(load_sources(project))
    profile_texts = leaf_strings(profile)
    span_texts = list(spans.values())
    requirements: list[str] = []
    for key in ("must_haves", "nice_to_haves", "selection_criteria"):
        for item in target.get(key, []) or []:
            if isinstance(item, dict):
                requirements.append(str(item.get("text", "")))
    keyword_texts = [str(k) for k in target.get("keywords", []) or []]
    target_texts = [*requirements, *keyword_texts]

    rows: list[dict[str, Any]] = []
    counts = {"matched": 0, "target_gap": 0, "profile_only": 0, "neither": 0}
    for skill in framework.get("skills", []):
        profile_score, _ = _score_against(skill, [*profile_texts, *span_texts])
        evidence = [
            span_id
            for span_id, text in spans.items()
            if _score_against(skill, [text])[0] >= 0.6
        ][:5]
        if not evidence and profile_score >= 0.6:
            # Strong profile-text match still needs auditable spans.
            profile_score = min(profile_score, 0.5)
        target_score, matched_requirement = _score_against(skill, target_texts)
        profile_status = _status(profile_score)
        target_status = _status(target_score)
        target_present = target_status in ("evidenced", "weak")
        profile_present = profile_status in ("evidenced", "weak")
        if target_present and profile_present:
            alignment = "matched"
        elif target_present:
            alignment = "target_gap"
        elif profile_present:
            alignment = "profile_only"
        else:
            alignment = "neither"
        counts[alignment] += 1
        rows.append(
            {
                "code": skill.get("code"),
                "name": skill.get("name"),
                "level": skill.get("level"),
                "profile_status": profile_status,
                "profile_score": round(profile_score, 3),
                "profile_evidence": evidence,
                "target_status": target_status,
                "target_score": round(target_score, 3),
                "target_requirement": matched_requirement if target_present else None,
                "alignment": alignment,
            }
        )
    mapping = {
        "framework": framework.get("name", framework_name),
        "kind": framework.get("kind"),
        "target": target_name,
        "counts": counts,
        "skills": rows,
    }
    out_dir = project / "exports" / target_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"framework-{framework_name}.json"
    out.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out


def load_mapping(
    project: Path, target_name: str, framework_name: str
) -> dict[str, Any] | None:
    path = project / "exports" / target_name / f"framework-{framework_name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
