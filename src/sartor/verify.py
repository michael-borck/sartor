"""Verification: every claim checked against its evidence (S-007).

Deterministic checks first, with no model: every bullet has evidence;
its numbers and dates appear in the cited spans; its wording overlaps
the cited spans. Verdicts per bullet:

- ``supported`` — numbers/dates all present and strong overlap.
- ``weak`` — evidence exists and partly covers the bullet.
- ``unsupported`` — no evidence, a number/date absent from the cited
  spans, or negligible overlap.

Default keeps-and-flags unsupported bullets (``"flagged": true`` in
tailored.json); ``strict`` drops them. An optional LLM entailment
pass (``--llm``) may downgrade a verdict, never upgrade one.
Tailored skill names not present in the profile or sources are also
reported.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sartor.profile import all_spans, load_sources
from sartor.providers import Provider
from sartor.tailor import TailorError, bullet_entries, load_tailored, save_tailored
from sartor.textmatch import dates, leaf_strings, norm, numbers, overlap

VERDICTS = ("supported", "weak", "unsupported")
_RANK = {"supported": 0, "weak": 1, "unsupported": 2}

ENTAIL_SYSTEM = (
    "You check whether a resume bullet follows from cited evidence. "
    "Reply with exactly one word: SUPPORTED, WEAK, or UNSUPPORTED."
)


class VerifyError(Exception):
    """Raised when verification cannot run."""


def _verdict_for(
    text: str, evidence: list[str], spans: dict[str, str]
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not evidence:
        return "unsupported", ["no evidence cited"]
    cited = " ".join(spans.get(span_id, "") for span_id in evidence)
    missing_numbers = numbers(text) - numbers(cited)
    if missing_numbers:
        reasons.append(
            "number(s) not in cited evidence: " + ", ".join(sorted(missing_numbers))
        )
    missing_dates = dates(text) - dates(cited)
    if missing_dates:
        reasons.append(
            "date(s) not in cited evidence: " + ", ".join(sorted(missing_dates))
        )
    if reasons:
        return "unsupported", reasons
    score = overlap(text, cited)
    if score >= 0.5:
        return "supported", [f"overlap {score:.2f} with cited evidence"]
    if score >= 0.22:
        return "weak", [f"overlap {score:.2f} with cited evidence"]
    return "unsupported", [f"overlap {score:.2f} with cited evidence"]


def _unsupported_skills(tailored: dict[str, Any], profile_text: str) -> list[str]:
    haystack = norm(profile_text)
    unsupported: list[str] = []
    for entry in tailored.get("skills", []) or []:
        if not isinstance(entry, dict):
            continue
        names = [str(entry.get("name", ""))]
        names.extend(str(k) for k in entry.get("keywords", []) or [])
        for name in names:
            if name.strip() and norm(name) not in haystack:
                unsupported.append(name)
    return unsupported


def verify_resume(
    project: Path,
    target_name: str,
    *,
    strict: bool = False,
    llm: bool = False,
    provider: Provider | None = None,
) -> Path:
    """Write ``exports/<target>/verify.json``; flag or drop per ``strict``."""
    try:
        tailored = load_tailored(project, target_name)
    except TailorError as exc:
        raise VerifyError(
            str(exc).replace("Nothing tailored", "Nothing to verify")
        ) from exc
    spans = all_spans(load_sources(project))

    profile_text = ""
    profile_path = project / "profile.json"
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile_text = " ".join(leaf_strings(profile))
    source_text = " ".join(spans.values())

    results: list[dict[str, Any]] = []
    live_bullets = bullet_entries(tailored)
    verdict_by_path: dict[str, str] = {}

    for path, bullet in live_bullets:
        text = str(bullet.get("text", ""))
        evidence = [str(e) for e in bullet.get("evidence", []) or []]
        verdict, reasons = _verdict_for(text, evidence, spans)
        if llm and provider is not None and verdict != "unsupported" and evidence:
            cited = "\n".join(spans.get(e, "") for e in evidence)
            reply = (
                provider.chat(
                    ENTAIL_SYSTEM,
                    f"BULLET: {text}\n\nEVIDENCE:\n{cited}",
                )
                .strip()
                .lower()
            )
            for candidate in VERDICTS:
                if candidate in reply and _RANK[candidate] > _RANK[verdict]:
                    verdict = candidate
                    reasons.append("entailment pass downgraded the verdict")
                    break
        verdict_by_path[path] = verdict
        results.append(
            {
                "path": path,
                "text": text,
                "evidence": evidence,
                "verdict": verdict,
                "reasons": reasons,
            }
        )

    counts = dict.fromkeys(VERDICTS, 0)
    for result in results:
        counts[result["verdict"]] += 1

    dropped = 0
    if strict:
        for section in ("work", "volunteer", "projects"):
            for e_index, entry in enumerate(tailored.get(section, []) or []):
                if not isinstance(entry, dict):
                    continue
                kept = []
                for b_index, bullet in enumerate(entry.get("highlights", []) or []):
                    path = f"{section}[{e_index}].highlights[{b_index}]"
                    if verdict_by_path.get(path) == "unsupported":
                        dropped += 1
                    else:
                        kept.append(bullet)
                entry["highlights"] = kept
    else:
        for path, bullet in live_bullets:
            if verdict_by_path.get(path) == "unsupported":
                bullet["flagged"] = True
            else:
                bullet.pop("flagged", None)
    save_tailored(project, target_name, tailored)

    report = {
        "target": target_name,
        "strict": strict,
        "llm": llm,
        "counts": counts,
        "dropped": dropped,
        "bullets": results,
        "unsupported_skills": _unsupported_skills(
            tailored, profile_text + " " + source_text
        ),
    }
    out = project / "exports" / target_name / "verify.json"
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def load_verify(project: Path, target_name: str) -> dict[str, Any]:
    path = project / "exports" / target_name / "verify.json"
    if not path.is_file():
        raise VerifyError(f"Not verified yet: run `sartor verify {target_name}`")
    return json.loads(path.read_text(encoding="utf-8"))
