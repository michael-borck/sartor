"""User-supplied skill frameworks (S-014, S-015, S-018).

Framework data is never bundled or fetched: the person adds their own
SFIA / O*NET / ESCO / AQF / custom file (CSV or JSON), normalized to
``frameworks/<name>.json``. A code may have several level rows, each
with its own descriptor. Mapping and framework statements are
deterministic — framework names/codes/keywords and level descriptors
are matched against profile text and source spans on one side, target
requirements and keywords on the other. No model call is needed here,
so a mapping or statement is fully auditable.

Suggested levels are internal only. They require descriptor-specific
evidence, never a code or shared keyword alone, and are not a formal
assessment. Statement display defaults to code + skill name with no
level, leaving seniority for the reader to infer from the evidence.
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
from sartor.textmatch import leaf_strings, norm, overlap, words

FRAMEWORK_KINDS = ("sfia", "onet", "esco", "aqf", "custom")
STATEMENT_DISPLAYS = ("none", "code", "code-level")
_BULLET_SECTIONS = ("work", "volunteer", "projects")
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


def _normalized_level(raw: Any) -> Any:
    if isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, int):
        return raw
    text = str(raw if raw is not None else "").strip()
    if not text:
        return None
    return int(text) if text.isdigit() else text


def _level_key(level: Any) -> str:
    return "" if level is None else str(level).strip().lower()


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
    seen: set[tuple[str, str]] = set()
    for position, row in enumerate(rows, start=1):
        code = str(row.get("code", "")).strip()
        skill_name = str(row.get("name", "")).strip()
        if not code or not skill_name:
            raise FrameworkError(
                f"{path.name}: row {position} needs both code and name"
            )
        level = _normalized_level(row.get("level", ""))
        key = (code.lower(), _level_key(level))
        if key in seen:
            raise FrameworkError(
                f"{path.name}: duplicate code and level {code!r}/"
                f"{level!r} at row {position}"
            )
        seen.add(key)
        description = str(
            row.get("description", "") or row.get("descriptor", "")
        ).strip()
        descriptor = str(
            row.get("descriptor", "") or row.get("description", "")
        ).strip()
        skills.append(
            {
                "code": code,
                "name": skill_name,
                "level": level,
                "description": description,
                "descriptor": descriptor,
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


def _framework_path(project: Path, name: str) -> Path:
    return project / "frameworks" / f"{name}.json"


def _write_framework_record(
    project: Path, name: str, record: dict[str, Any]
) -> Path:
    out = _framework_path(project, name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return out


def _confirmed_map(framework: dict[str, Any]) -> dict[str, Any]:
    raw = framework.get("confirmed_levels")
    if not isinstance(raw, dict):
        return {}
    return {
        str(code): _normalized_level(level)
        for code, level in raw.items()
        if _normalized_level(level) is not None
    }


def _valid_confirmed_levels(
    framework: dict[str, Any], candidates: dict[str, Any]
) -> dict[str, Any]:
    valid: dict[str, Any] = {}
    levels_by_code: dict[str, list[dict[str, Any]]] = {}
    for skill in framework.get("skills", []) or []:
        if isinstance(skill, dict):
            levels_by_code.setdefault(str(skill.get("code", "")).lower(), []).append(
                skill
            )
    for code, level in candidates.items():
        rows = levels_by_code.get(str(code).lower(), [])
        for row in rows:
            row_level = _normalized_level(row.get("level"))
            if _level_key(row_level) == _level_key(level):
                valid[str(row.get("code"))] = row_level
                break
    return valid


def add_framework(
    project: Path, path: Path, name: str, kind: str, *, force: bool = False
) -> Path:
    """Normalize and store a framework under ``frameworks/<name>.json``."""
    record = parse_framework(path, name, kind)
    out = _framework_path(project, name)
    if out.exists() and not force:
        raise FrameworkError(f"Framework {name!r} exists; pass --force to replace it")
    if out.is_file():
        try:
            previous = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if isinstance(previous, dict):
            record["confirmed_levels"] = _valid_confirmed_levels(
                record, _confirmed_map(previous)
            )
    return _write_framework_record(project, name, record)


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
        if isinstance(data, dict) and isinstance(data.get("skills"), list):
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


def confirm_framework_level(
    project: Path, framework_name: str, code: str, level: Any
) -> Path:
    """Record a level the applicant explicitly confirms for one code."""
    framework = load_framework(project, framework_name)
    rows = [
        skill
        for skill in framework.get("skills", []) or []
        if isinstance(skill, dict)
        and str(skill.get("code", "")).lower() == code.strip().lower()
    ]
    if not rows:
        raise FrameworkError(
            f"unknown code {code!r} in framework {framework_name!r}"
        )
    requested = _normalized_level(level)
    match = next(
        (
            row
            for row in rows
            if _level_key(_normalized_level(row.get("level")))
            == _level_key(requested)
            and _normalized_level(row.get("level")) is not None
        ),
        None,
    )
    if match is None:
        available = ", ".join(
            str(_normalized_level(row.get("level")))
            for row in rows
            if _normalized_level(row.get("level")) is not None
        )
        raise FrameworkError(
            f"unknown level {level!r} for code {rows[0].get('code')!r}"
            + (f"; available levels: {available}" if available else "")
        )
    confirmed = _valid_confirmed_levels(framework, _confirmed_map(framework))
    confirmed[str(match.get("code"))] = _normalized_level(match.get("level"))
    framework["confirmed_levels"] = confirmed
    return _write_framework_record(project, framework_name, framework)


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


def _group_skills(skills: list[Any]) -> list[dict[str, Any]]:
    """Collapse code+level rows into one scoreable group per code."""
    groups: dict[str, dict[str, Any]] = {}
    for raw in skills:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code", "")).strip()
        if not code:
            continue
        key = code.lower()
        group = groups.setdefault(
            key,
            {
                "code": code,
                "name": str(raw.get("name", "")).strip(),
                "keywords": [],
                "levels": [],
            },
        )
        seen_keywords = {str(item).lower() for item in group["keywords"]}
        for keyword in raw.get("keywords", []) or []:
            text = str(keyword).strip()
            if text and text.lower() not in seen_keywords:
                group["keywords"].append(text)
                seen_keywords.add(text.lower())
        group["levels"].append(raw)
    return list(groups.values())


def _level_rank(level: Any, position: int) -> tuple[int, int, int]:
    normalized = _normalized_level(level)
    if isinstance(normalized, int):
        return (2, normalized, position)
    if normalized is None:
        return (0, 0, position)
    return (1, 0, position)


def _level_details(
    group: dict[str, Any], evidence_spans: dict[str, str]
) -> list[dict[str, Any]]:
    """Descriptor-specific level evidence; codes/keywords alone never qualify."""
    levels = [row for row in group.get("levels", []) if isinstance(row, dict)]
    keyword_counts: dict[str, int] = {}
    for row in levels:
        for keyword in {
            norm(str(item)) for item in row.get("keywords", []) or [] if str(item)
        }:
            keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
    excluded = words(str(group.get("code", ""))) | words(str(group.get("name", "")))
    excluded |= _GENERIC
    details: list[dict[str, Any]] = []
    for row in levels:
        descriptor = str(
            row.get("descriptor", "") or row.get("description", "")
        ).strip()
        descriptor_terms = words(descriptor) - excluded
        distinctive_terms = set(descriptor_terms)
        for keyword in row.get("keywords", []) or []:
            if keyword_counts.get(norm(str(keyword)), 0) == 1:
                distinctive_terms.update(words(str(keyword)) - excluded)
        best = 0.0
        evidence: list[str] = []
        for span_id, text in evidence_spans.items():
            present = distinctive_terms & words(text)
            descriptor_present = descriptor_terms & words(text)
            if not descriptor_present or not distinctive_terms:
                continue
            score = len(present) / len(distinctive_terms)
            best = max(best, score)
            if len(descriptor_present) >= min(2, len(descriptor_terms)) and (
                score >= 0.34
            ):
                evidence.append(span_id)
        details.append(
            {
                "level": _normalized_level(row.get("level")),
                "descriptor": descriptor,
                "description": str(row.get("description", "")).strip(),
                "keywords": [str(item) for item in row.get("keywords", []) or []],
                "profile_score": round(best, 3),
                "profile_evidence": evidence[:5],
            }
        )
    return details


def _suggested_level(details: list[dict[str, Any]]) -> Any:
    ordered = sorted(
        enumerate(details),
        key=lambda item: _level_rank(item[1].get("level"), item[0]),
        reverse=True,
    )
    for _, detail in ordered:
        if detail.get("level") is not None and detail.get("profile_evidence"):
            return detail.get("level")
    return None


def _evidence_for_text(
    text: str,
    entry_path: str,
    profile: dict[str, Any],
    spans: dict[str, str],
) -> list[str]:
    profile_evidence: dict[str, Any] = (
        (profile.get("meta") or {}).get("sartor", {}).get("evidence", {})
    )
    seeded = [s for s in profile_evidence.get(entry_path, []) if s in spans]
    matched = [
        span_id
        for span_id, span_text in spans.items()
        if overlap(text, span_text) >= 0.6 or text.strip().lower() in span_text.lower()
    ]
    evidence: list[str] = []
    for span_id in [*matched, *seeded]:
        if span_id not in evidence:
            evidence.append(span_id)
    return evidence[:5]


def _profile_bullets(
    profile: dict[str, Any], spans: dict[str, str]
) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    for section in _BULLET_SECTIONS:
        for e_index, entry in enumerate(profile.get(section, []) or []):
            if not isinstance(entry, dict):
                continue
            for b_index, raw in enumerate(entry.get("highlights", []) or []):
                if not isinstance(raw, str) or not raw.strip():
                    continue
                path = f"{section}[{e_index}].highlights[{b_index}]"
                bullets.append(
                    {
                        "path": path,
                        "text": raw,
                        "evidence": _evidence_for_text(
                            raw, f"{section}[{e_index}]", profile, spans
                        ),
                        "flagged": False,
                        "source": "profile",
                    }
                )
    return bullets


def _tailored_bullets(
    tailored: dict[str, Any], spans: dict[str, str]
) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    for section in _BULLET_SECTIONS:
        for e_index, entry in enumerate(tailored.get(section, []) or []):
            if not isinstance(entry, dict):
                continue
            for b_index, raw in enumerate(entry.get("highlights", []) or []):
                path = f"{section}[{e_index}].highlights[{b_index}]"
                if isinstance(raw, dict):
                    text = str(raw.get("text", "")).strip()
                    evidence = [
                        str(item) for item in raw.get("evidence", []) or []
                        if str(item) in spans
                    ]
                    flagged = bool(raw.get("flagged"))
                elif isinstance(raw, str):
                    text, evidence, flagged = raw.strip(), [], False
                else:
                    continue
                if text:
                    bullets.append(
                        {
                            "path": path,
                            "text": text,
                            "evidence": evidence,
                            "flagged": flagged,
                            "source": "tailored",
                        }
                    )
    return bullets


def _matched_bullets(
    skill: dict[str, Any],
    bullets: list[dict[str, Any]],
    spans: dict[str, str],
    *,
    include_flagged: bool = True,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bullet in bullets:
        if bullet.get("flagged") and not include_flagged:
            continue
        evidence = [str(item) for item in bullet.get("evidence", []) if item in spans]
        if not evidence:
            continue
        key = (str(bullet.get("path", "")), str(bullet.get("text", "")))
        if key in seen:
            continue
        seen.add(key)
        texts = [str(bullet.get("text", "")), *[spans[item] for item in evidence]]
        score, _ = _score_against(skill, texts)
        if score < 0.6:
            continue
        matched.append(
            {
                "path": bullet.get("path"),
                "bullet": bullet.get("path"),
                "text": bullet.get("text"),
                "evidence": evidence,
                "score": round(score, 3),
                "source": bullet.get("source"),
                "flagged": bool(bullet.get("flagged")),
            }
        )
    return sorted(matched, key=lambda item: (-float(item["score"]), str(item["path"])))[:5]


def build_framework_mapping(
    project: Path, target_name: str, framework_name: str
) -> dict[str, Any]:
    """Build one deterministic mapping row per framework code."""
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
    confirmed_levels = _valid_confirmed_levels(
        framework, _confirmed_map(framework)
    )
    profile_bullets = _profile_bullets(profile, spans)

    rows: list[dict[str, Any]] = []
    counts = {"matched": 0, "target_gap": 0, "profile_only": 0, "neither": 0}
    for skill in _group_skills(list(framework.get("skills", []) or [])):
        profile_score, _ = _score_against(skill, [*profile_texts, *span_texts])
        evidence = [
            span_id
            for span_id, text in spans.items()
            if _score_against(skill, [text])[0] >= 0.6
        ][:5]
        if not evidence and profile_score >= 0.6:
            # Strong profile-text match still needs auditable spans.
            profile_score = min(profile_score, 0.5)
        level_details = _level_details(
            skill, {span_id: spans[span_id] for span_id in evidence}
        )
        suggested_level = _suggested_level(level_details)
        confirmed_level = next(
            (
                level
                for code, level in confirmed_levels.items()
                if code.lower() == str(skill.get("code", "")).lower()
            ),
            None,
        )
        if confirmed_level is not None:
            level_status = "confirmed"
        elif suggested_level is not None:
            level_status = "suggested"
        else:
            level_status = "none"
        chosen_level = (
            confirmed_level if confirmed_level is not None else suggested_level
        )
        chosen_detail = next(
            (
                detail
                for detail in level_details
                if _level_key(detail.get("level")) == _level_key(chosen_level)
            ),
            {},
        )
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
                "keywords": skill.get("keywords", []),
                "level": chosen_level,
                "suggested_level": suggested_level,
                "confirmed_level": confirmed_level,
                "level_status": level_status,
                "descriptor": chosen_detail.get("descriptor", ""),
                "levels": level_details,
                "profile_status": profile_status,
                "profile_score": round(profile_score, 3),
                "profile_evidence": evidence,
                "profile_bullets": _matched_bullets(skill, profile_bullets, spans),
                "target_status": target_status,
                "target_score": round(target_score, 3),
                "target_requirement": matched_requirement if target_present else None,
                "alignment": alignment,
            }
        )
    return {
        "framework": framework.get("name", framework_name),
        "kind": framework.get("kind"),
        "target": target_name,
        "level_note": (
            "Suggested levels are internal suggestions from descriptor-specific "
            "evidence, not a formal assessment."
        ),
        "counts": counts,
        "skills": rows,
    }


def map_framework(project: Path, target_name: str, framework_name: str) -> Path:
    """Write ``exports/<target>/framework-<framework>.json``."""
    mapping = build_framework_mapping(project, target_name, framework_name)
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


# --- framework statements and voice (S-018) -----------------------------


def _statement_bullets(
    project: Path,
    target_name: str,
    profile: dict[str, Any],
    spans: dict[str, str],
) -> tuple[list[dict[str, Any]], str]:
    tailored_path = project / "exports" / target_name / "tailored.json"
    if tailored_path.is_file():
        try:
            tailored = json.loads(tailored_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FrameworkError(f"tailored.json: invalid JSON ({exc})") from exc
        if isinstance(tailored, dict):
            bullets = _tailored_bullets(tailored, spans)
            if bullets:
                return bullets, "tailored"
    return _profile_bullets(profile, spans), "profile"


def framework_statement_data(
    project: Path,
    target_name: str,
    framework_name: str,
    *,
    display: str = "code",
) -> dict[str, Any]:
    """Evidence statements for one target/framework, without writing files."""
    if display not in STATEMENT_DISPLAYS:
        raise FrameworkError(
            f"unknown statement display {display!r}; expected one of: "
            f"{', '.join(STATEMENT_DISPLAYS)}"
        )
    mapping = build_framework_mapping(project, target_name, framework_name)
    try:
        profile = check_profile(project)
        target = load_target(project, target_name)
    except (ProfileError, TargetError) as exc:
        raise FrameworkError(str(exc)) from exc
    spans = all_spans(load_sources(project))
    bullets, bullet_source = _statement_bullets(
        project, target_name, profile, spans
    )

    rows: list[dict[str, Any]] = []
    statement_count = 0
    for row in mapping.get("skills", []) or []:
        statements = _matched_bullets(
            row, bullets, spans, include_flagged=False
        )
        statement_count += len(statements)
        evidence: list[str] = []
        for statement in statements:
            for span_id in statement.get("evidence", []):
                if span_id not in evidence:
                    evidence.append(str(span_id))
        display_level = None
        if display == "code-level":
            display_level = row.get("confirmed_level")
            if display_level is None:
                display_level = row.get("suggested_level")
        rows.append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "keywords": row.get("keywords", []),
                "descriptor": row.get("descriptor", ""),
                "alignment": row.get("alignment"),
                "profile_status": row.get("profile_status"),
                "target_status": row.get("target_status"),
                "target_requirement": row.get("target_requirement"),
                "suggested_level": row.get("suggested_level"),
                "confirmed_level": row.get("confirmed_level"),
                "level_status": row.get("level_status"),
                "display_level": display_level,
                "levels": row.get("levels", []),
                "evidence": evidence,
                "statements": statements,
            }
        )
    return {
        "framework": mapping.get("framework", framework_name),
        "kind": mapping.get("kind"),
        "target": target_name,
        "target_title": target.get("title") or target_name,
        "target_organisation": target.get("organisation", ""),
        "display": display,
        "bullet_source": bullet_source,
        "level_note": (
            "Suggested levels are internal suggestions from descriptor-specific "
            "evidence, not a formal assessment. The default statement display "
            "prints no level."
        ),
        "counts": {
            "skills": len(rows),
            "statements": statement_count,
            "skills_with_statements": sum(
                1 for row in rows if row.get("statements")
            ),
            "target_gaps": (mapping.get("counts") or {}).get("target_gap", 0),
        },
        "skills": rows,
    }


def _statement_bullet_lines(statement: dict[str, Any]) -> list[str]:
    lines = [f"- {statement.get('text', '')}"]
    evidence = [str(item) for item in statement.get("evidence", []) or []]
    if evidence:
        lines.append(f"  Evidence: {', '.join(evidence)}")
    return lines


def render_framework_statement(data: dict[str, Any]) -> str:
    """Render a framework statement; default display prints no level."""
    display = str(data.get("display") or "code")
    title = str(data.get("target_title") or data.get("target") or "")
    org = str(data.get("target_organisation") or "")
    lines = [f"# Framework statement — {title}" + (f" ({org})" if org else ""), ""]
    lines.append(
        f"Framework: {data.get('framework')} ({data.get('kind')}). "
        "Every statement below is linked to supplied evidence."
    )
    if display == "code-level":
        lines.append(
            "Levels are shown only where confirmed by the applicant or "
            "qualified below as suggested; a suggested level is not a "
            "formal assessment."
        )
    else:
        lines.append(
            "No level is printed. Seniority is left for the reader to infer "
            "from scope, autonomy, complexity, influence, and outcomes in "
            "the evidence."
        )
    rows = [row for row in data.get("skills", []) or [] if row.get("statements")]
    if not rows:
        lines.extend(["", "No evidence statements could be formed."])
        return "\n".join(lines) + "\n"
    if display == "none":
        lines.extend(["", "## Evidence statements", ""])
        seen: set[tuple[str, str]] = set()
        for row in rows:
            for statement in row.get("statements", []) or []:
                key = (str(statement.get("path")), str(statement.get("text")))
                if key in seen:
                    continue
                seen.add(key)
                lines.extend(_statement_bullet_lines(statement))
        return "\n".join(lines) + "\n"
    for row in rows:
        heading = f"## {row.get('code')} — {row.get('name')}"
        if display == "code-level" and row.get("display_level") is not None:
            if row.get("level_status") == "confirmed":
                heading += f" — Level {row['display_level']} (confirmed by you)"
            else:
                heading += (
                    f" — Suggested level {row['display_level']} "
                    "(not confirmed; not a formal assessment)"
                )
        lines.extend(["", heading, ""])
        for statement in row.get("statements", []) or []:
            lines.extend(_statement_bullet_lines(statement))
    return "\n".join(lines) + "\n"


def write_framework_statement(
    project: Path,
    target_name: str,
    framework_name: str,
    *,
    display: str = "code",
) -> tuple[Path, Path]:
    """Write ``statement-<framework>.md`` and ``.json``; return both paths."""
    data = framework_statement_data(
        project, target_name, framework_name, display=display
    )
    out_dir = project / "exports" / target_name
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"statement-{framework_name}.md"
    json_path = out_dir / f"statement-{framework_name}.json"
    json_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_framework_statement(data), encoding="utf-8")
    return md_path, json_path


def load_framework_statement(
    project: Path, target_name: str, framework_name: str
) -> dict[str, Any] | None:
    path = project / "exports" / target_name / f"statement-{framework_name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def framework_voice_context(
    project: Path, target_name: str, framework_name: str
) -> str:
    """Prompt context for opt-in, voice-only framework tailoring."""
    mapping = build_framework_mapping(project, target_name, framework_name)
    rows = [
        row
        for row in mapping.get("skills", []) or []
        if row.get("profile_status") in ("evidenced", "weak")
    ]
    rows.sort(
        key=lambda row: (
            0 if row.get("alignment") == "matched" else 1,
            -float(row.get("profile_score") or 0),
            str(row.get("name") or ""),
        )
    )
    lines = [
        "FRAMEWORK VOICE (optional wording only):",
        "Use these framework skill names and keywords only where an existing "
        "profile bullet and its evidence already support them.",
        "Foreground scope, autonomy, complexity, influence, and outcomes "
        "already present in the evidence. Do not upgrade seniority.",
        "Do not mention a framework code or level in the summary or bullets; "
        "let the reader infer seniority from the evidence.",
        "Do not state or imply a formal framework assessment.",
    ]
    for row in rows[:20]:
        keywords = ", ".join(str(item) for item in row.get("keywords", [])[:8])
        line = f"- {row.get('name')}"
        if keywords:
            line += f" (keywords: {keywords})"
        descriptor = str(row.get("descriptor") or "").strip()
        if descriptor:
            line += f" — descriptor voice: {descriptor}"
        lines.append(line)
        for bullet in (row.get("profile_bullets") or [])[:2]:
            lines.append(f"  Evidence wording: {bullet.get('text')}")
    if not rows:
        lines.append("- No framework skill is currently evidenced; add no framework wording.")
    return "\n".join(lines)
