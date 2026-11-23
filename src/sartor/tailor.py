"""Tailoring: select and rephrase, never add facts (S-006).

The model returns a *plan*, not a resume: which profile entries to
keep (by section + index), in what order, and how to rephrase each
kept bullet, citing source span ids. Sartor then assembles the
tailored resume by copying profile entries verbatim and swapping in
the rephrased bullets — so employers, titles, dates, and skill names
cannot be invented by construction. A deterministic guard drops any
rewritten bullet whose numbers or dates do not appear anywhere in
the profile, or that ends up with no valid evidence.

Output is an internal model: JSON Resume shape, except highlights
are objects ``{"text", "evidence", "original"}`` so S-007 can flag
them and S-009 can flatten them back to plain JSON Resume.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from sartor.modeljson import ModelJsonError, parse_model_json
from sartor.profile import ProfileError, all_spans, check_profile, load_sources
from sartor.providers import Provider
from sartor.target import TargetError, load_target
from sartor.textmatch import dates, leaf_strings, numbers, overlap

BULLET_SECTIONS = ("work", "volunteer", "projects")
COPY_SECTIONS = (
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
    "You tailor a resume to one job target by selecting and rephrasing. "
    "You may only rephrase existing highlights; never add facts, "
    "numbers, dates, skills, or employers that are not in the profile. "
    "Reply with one JSON plan object."
)

TAILOR_VOICES = ("standard", "framework")
_LEVEL_CLAIM_RE = re.compile(
    r"\b(?:sfia\s*)?(?:level|lvl)\s*(?:[:#-]\s*)?"
    r"(?:[0-9]+(?:\.[0-9]+)?|one|two|three|four|five|six|seven)\b"
    r"|\bsfia\s*[0-9]\b",
    re.IGNORECASE,
)


def _contains_level_claim(text: str) -> bool:
    return _LEVEL_CLAIM_RE.search(text) is not None


def _validate_framework_voice(framework_name: str | None, voice: str) -> None:
    if voice not in TAILOR_VOICES:
        raise TailorError(
            f"unknown tailor voice {voice!r}; expected standard or framework"
        )
    if voice == "framework" and not framework_name:
        raise TailorError("--voice framework needs --framework NAME")
    if framework_name and voice != "framework":
        raise TailorError("--framework needs --voice framework")


class TailorError(Exception):
    """Raised when tailoring cannot produce an evidence-linked model."""


def build_tailor_prompt(
    profile: dict[str, Any],
    target: dict[str, Any],
    spans: dict[str, str],
    *,
    framework_context: str | None = None,
) -> str:
    """The exact prompt ``tailor_resume`` sends (exposed for recorded tests)."""
    lines = [
        "Return a plan JSON object:",
        '  {"summary": optional rephrased basics.summary or null,',
        '   "sections": [{"section": "work", "index": 0,',
        '     "highlights": [{"index": 0, "text": "rephrased bullet",',
        '                     "evidence": ["src://file#s1"]}]}]}',
        "List sections/entries in the order they should appear. Omit "
        "entries irrelevant to the target. For entries without "
        "highlights, omit the highlights key to keep them unchanged.",
    ]
    if framework_context:
        lines.extend(["", framework_context])
    lines.extend(
        [
            "",
            "TARGET:",
            json.dumps(target, ensure_ascii=False),
            "",
            "PROFILE (JSON Resume; indexes below refer to this):",
            json.dumps(profile, ensure_ascii=False),
            "",
            "SOURCE SPANS (cite these ids as evidence):",
        ]
    )
    lines.extend(f"[{span_id}] {text}" for span_id, text in spans.items())
    return "\n".join(lines)


def _profile_numbers_dates(profile: dict[str, Any]) -> tuple[set[str], set[str]]:
    text = " ".join(leaf_strings(profile))
    return numbers(text), dates(text)


def _derive_evidence(
    original: str,
    entry_path: str,
    profile_evidence: dict[str, Any],
    spans: dict[str, str],
) -> list[str]:
    seeded = [s for s in profile_evidence.get(entry_path, []) if s in spans]
    matched = [
        span_id
        for span_id, text in spans.items()
        if overlap(original, text) >= 0.6 or original.strip().lower() in text.lower()
    ]
    merged: list[str] = []
    for span_id in [*matched, *seeded]:
        if span_id not in merged:
            merged.append(span_id)
    return merged[:5]


def tailor_resume(
    project: Path,
    target_name: str,
    provider: Provider,
    *,
    framework_name: str | None = None,
    voice: str = "standard",
) -> Path:
    """Write ``exports/<target>/tailored.json``."""
    _validate_framework_voice(framework_name, voice)
    try:
        profile = check_profile(project)
    except ProfileError as exc:
        raise TailorError(str(exc)) from exc
    try:
        target = load_target(project, target_name)
    except TargetError as exc:
        raise TailorError(str(exc)) from exc

    spans = all_spans(load_sources(project))
    framework_context: str | None = None
    if framework_name:
        from sartor.frameworks import FrameworkError, framework_voice_context

        try:
            framework_context = framework_voice_context(
                project, target_name, framework_name
            )
        except FrameworkError as exc:
            raise TailorError(str(exc)) from exc
    try:
        plan = parse_model_json(
            provider.chat(
                SYSTEM_PROMPT,
                build_tailor_prompt(
                    profile,
                    target,
                    spans,
                    framework_context=framework_context,
                ),
            )
        )
    except ModelJsonError as exc:
        raise TailorError(str(exc)) from exc
    plan_sections = plan.get("sections")
    if not isinstance(plan_sections, list) or not plan_sections:
        raise TailorError("model plan has no sections; nothing was tailored")

    allowed_numbers, allowed_dates = _profile_numbers_dates(profile)
    profile_evidence: dict[str, Any] = (
        (profile.get("meta") or {}).get("sartor", {}).get("evidence", {})
    )

    tailored: dict[str, Any] = {}
    if profile.get("$schema"):
        tailored["$schema"] = profile["$schema"]
    basics = copy.deepcopy(profile.get("basics") or {})
    summary = plan.get("summary")
    if isinstance(summary, str) and summary.strip():
        if (
            numbers(summary) <= allowed_numbers
            and dates(summary) <= allowed_dates
            and not (voice == "framework" and _contains_level_claim(summary))
        ):
            basics["summary"] = summary.strip()
    tailored["basics"] = basics

    kept: dict[str, int] = {}
    bullets_kept = 0
    bullets_dropped = 0

    for item in plan_sections:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section", ""))
        index = item.get("index")
        entries = profile.get(section)
        if section not in COPY_SECTIONS or not isinstance(entries, list):
            continue
        if not isinstance(index, int) or not (0 <= index < len(entries)):
            continue
        entry = copy.deepcopy(entries[index])
        if section in BULLET_SECTIONS:
            originals = [
                str(h) for h in entry.get("highlights", []) if isinstance(h, str)
            ]
            planned = item.get("highlights")
            bullets: list[dict[str, Any]] = []
            if planned is None:
                planned_items: list[Any] = [
                    {"index": i, "text": text, "evidence": []}
                    for i, text in enumerate(originals)
                ]
            elif isinstance(planned, list):
                planned_items = planned
            else:
                planned_items = []
            for bullet in planned_items:
                if not isinstance(bullet, dict):
                    bullets_dropped += 1
                    continue
                b_index = bullet.get("index")
                text = str(bullet.get("text", "")).strip()
                if (
                    not isinstance(b_index, int)
                    or not (0 <= b_index < len(originals))
                    or not text
                ):
                    bullets_dropped += 1
                    continue
                if not (
                    numbers(text) <= allowed_numbers and dates(text) <= allowed_dates
                ):
                    bullets_dropped += 1
                    continue
                if voice == "framework" and _contains_level_claim(text):
                    bullets_dropped += 1
                    continue
                evidence = [
                    str(e) for e in bullet.get("evidence", []) if str(e) in spans
                ]
                if not evidence:
                    evidence = _derive_evidence(
                        originals[b_index],
                        f"{section}[{index}]",
                        profile_evidence,
                        spans,
                    )
                if not evidence:
                    bullets_dropped += 1
                    continue
                bullets.append(
                    {
                        "text": text,
                        "evidence": evidence,
                        "original": originals[b_index],
                    }
                )
                bullets_kept += 1
            entry["highlights"] = bullets
        tailored.setdefault(section, []).append(entry)
        kept[section] = kept.get(section, 0) + 1

    dropped = {
        section: len(profile.get(section, [])) - kept.get(section, 0)
        for section in COPY_SECTIONS
        if isinstance(profile.get(section), list)
    }
    sartor_meta: dict[str, Any] = {
        "target": target_name,
        "kept": kept,
        "dropped": dropped,
        "bullets_kept": bullets_kept,
        "bullets_dropped": bullets_dropped,
    }
    if framework_name:
        sartor_meta["framework"] = {
            "name": framework_name,
            "voice": voice,
            "display": "voice-only",
        }
    tailored["meta"] = {"sartor": sartor_meta}

    out_dir = project / "exports" / target_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "tailored.json"
    out.write_text(
        json.dumps(tailored, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def load_tailored(project: Path, target_name: str) -> dict[str, Any]:
    path = project / "exports" / target_name / "tailored.json"
    if not path.is_file():
        raise TailorError(
            f"Nothing tailored for {target_name!r}: "
            f"run `sartor tailor {target_name}` first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def save_tailored(project: Path, target_name: str, tailored: dict[str, Any]) -> Path:
    out = project / "exports" / target_name / "tailored.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(tailored, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def bullet_entries(
    tailored: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """(path, bullet) for every highlight object, e.g. work[0].highlights[1]."""
    found: list[tuple[str, dict[str, Any]]] = []
    for section in BULLET_SECTIONS:
        for e_index, entry in enumerate(tailored.get(section, []) or []):
            if not isinstance(entry, dict):
                continue
            for b_index, bullet in enumerate(entry.get("highlights", []) or []):
                if isinstance(bullet, dict):
                    found.append(
                        (f"{section}[{e_index}].highlights[{b_index}]", bullet)
                    )
                elif isinstance(bullet, str):
                    found.append(
                        (
                            f"{section}[{e_index}].highlights[{b_index}]",
                            {"text": bullet, "evidence": []},
                        )
                    )
    return found
