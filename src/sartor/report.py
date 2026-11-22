"""Coverage and gap report (S-008).

Per requirement: evidenced (with its bullet), weak, or gap — plus the
ATS keyword table. Matching is deterministic word overlap against
non-flagged tailored bullets and the tailored skills/basics text;
a requirement matched only by a flagged bullet counts as weak.
Gaps are only ever phrased as "add evidence or accept the gap".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sartor.tailor import TailorError, bullet_entries, load_tailored
from sartor.target import TargetError, load_target
from sartor.textmatch import leaf_strings, norm, overlap, words
from sartor.verify import VerifyError, load_verify, verify_resume

GAP_PHRASE = "add evidence or accept the gap"
BANNED_PHRASES = (
    "invent",
    "fabricat",
    "make up",
    "exaggerat",
    "pretend",
    "claim you",
    "say you have",
    "lie",
)
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


class ReportError(Exception):
    """Raised when the report cannot be built."""


def _important_words(text: str) -> set[str]:
    return {w for w in words(text) if w not in _GENERIC}


def _match_requirement(
    requirement: dict[str, str],
    bullets: list[tuple[str, dict[str, Any]]],
    other_text: str,
) -> tuple[str, str | None, float]:
    """Return (status, bullet path or None, score)."""
    wanted = _important_words(requirement["text"])
    if not wanted:
        wanted = words(requirement["text"])
    best_path: str | None = None
    best_score = 0.0
    best_flagged = False
    for path, bullet in bullets:
        present = wanted & words(str(bullet.get("text", "")))
        score = len(present) / len(wanted) if wanted else 0.0
        score = max(score, overlap(requirement["text"], str(bullet.get("text", ""))))
        if score > best_score:
            best_score, best_path = score, path
            best_flagged = bool(bullet.get("flagged"))
    other_words = words(other_text)
    other_score = len(wanted & other_words) / len(wanted) if wanted else 0.0
    if other_score > best_score:
        best_score, best_path, best_flagged = other_score, None, False
    if best_score >= 0.6:
        return ("weak" if best_flagged else "evidenced"), best_path, best_score
    if best_score >= 0.25:
        return "weak", best_path, best_score
    return "gap", None, best_score


def build_coverage(target: dict[str, Any], tailored: dict[str, Any]) -> dict[str, Any]:
    bullets = bullet_entries(tailored)
    other_parts = [
        tailored.get("basics", {}),
        tailored.get("skills", []),
        tailored.get("education", []),
    ]
    other_text = " ".join(text for part in other_parts for text in leaf_strings(part))
    sections_out: dict[str, list[dict[str, Any]]] = {}
    counts = {"evidenced": 0, "weak": 0, "gap": 0}
    for key in ("must_haves", "nice_to_haves", "selection_criteria"):
        rows: list[dict[str, Any]] = []
        for requirement in target.get(key, []) or []:
            if not isinstance(requirement, dict):
                continue
            status, path, score = _match_requirement(
                {"text": str(requirement.get("text", ""))}, bullets, other_text
            )
            counts[status] += 1
            rows.append(
                {
                    "requirement": requirement.get("text", ""),
                    "quote": requirement.get("quote", ""),
                    "status": status,
                    "bullet": path,
                    "score": round(score, 3),
                }
            )
        sections_out[key] = rows

    tailored_text = norm(" ".join(leaf_strings(tailored)))
    keyword_rows = []
    for keyword in target.get("keywords", []) or []:
        term = str(keyword)
        present = (
            re.search(
                rf"(?<![a-z0-9]){re.escape(norm(term))}(?![a-z0-9])", tailored_text
            )
            is not None
        )
        keyword_rows.append({"keyword": term, "present": bool(present)})
    return {
        "target": target.get("name", ""),
        "counts": counts,
        "requirements": sections_out,
        "keywords": keyword_rows,
    }


def _render_md(
    coverage: dict[str, Any], verify: dict[str, Any], target: dict[str, Any]
) -> str:
    title = target.get("title") or coverage["target"]
    org = target.get("organisation", "")
    lines = [f"# Coverage — {title}" + (f" ({org})" if org else ""), ""]
    c = coverage["counts"]
    lines.append(
        f"Requirements: {c['evidenced']} evidenced, {c['weak']} weak, {c['gap']} gaps."
    )
    v = verify["counts"]
    lines.append(
        f"Bullets: {v['supported']} supported, {v['weak']} weak, "
        f"{v['unsupported']} unsupported."
    )
    labels = {
        "must_haves": "Must-haves",
        "nice_to_haves": "Nice-to-haves",
        "selection_criteria": "Selection criteria",
    }
    for key, label in labels.items():
        rows = coverage["requirements"].get(key, [])
        if not rows:
            continue
        lines.extend(["", f"## {label}", ""])
        lines.append("| Requirement | Status | Bullet |")
        lines.append("| --- | --- | --- |")
        for row in rows:
            bullet = row["bullet"] or "—"
            lines.append(f"| {row['requirement']} | {row['status']} | {bullet} |")
    gaps = [
        row
        for rows in coverage["requirements"].values()
        for row in rows
        if row["status"] == "gap"
    ]
    lines.extend(["", "## Gaps", ""])
    if gaps:
        for row in gaps:
            lines.append(f"- {row['requirement']} — {GAP_PHRASE}.")
    else:
        lines.append("No gaps.")
    lines.extend(["", "## Keywords (ATS)", ""])
    lines.append("| Keyword | Present |")
    lines.append("| --- | --- |")
    for row in coverage["keywords"]:
        lines.append(f"| {row['keyword']} | {'yes' if row['present'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)


def build_report(project: Path, target_name: str) -> Path:
    """Write ``exports/<target>/report.md`` and ``coverage.json``."""
    try:
        target = load_target(project, target_name)
    except TargetError as exc:
        raise ReportError(str(exc)) from exc
    try:
        tailored = load_tailored(project, target_name)
    except TailorError as exc:
        raise ReportError(str(exc)) from exc
    try:
        verify = load_verify(project, target_name)
    except VerifyError:
        verify_resume(project, target_name)
        verify = load_verify(project, target_name)
        tailored = load_tailored(project, target_name)

    coverage = build_coverage(target, tailored)
    coverage["verify_counts"] = verify["counts"]
    markdown = _render_md(coverage, verify, target)
    lowered = markdown.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:  # internal guard; content is generated above
            raise ReportError(f"report wording check failed: {phrase!r}")

    out_dir = project / "exports" / target_name
    (out_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    out = out_dir / "report.md"
    out.write_text(markdown, encoding="utf-8")
    return out
