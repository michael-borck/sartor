"""S-006: plan-based tailoring with evidence links and the fact guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seedkit import seed_project, span_id_containing

from sartor.profile import all_spans, check_profile, load_sources
from sartor.project import init_project
from sartor.providers import FakeProvider
from sartor.tailor import TailorError, build_tailor_prompt, tailor_resume
from sartor.target import load_target
from sartor.textmatch import leaf_strings, numbers


def _plan_fake(project: Path, plan: dict) -> FakeProvider:
    profile = check_profile(project)
    spans = all_spans(load_sources(project))
    prompt = build_tailor_prompt(profile, load_target(project, "acme"), spans)
    return FakeProvider({prompt: json.dumps(plan)})


def test_tailor_selects_rephrases_and_links(tmp_path: Path):
    project = seed_project(tmp_path)
    evidence = span_id_containing(project, "40 store managers")
    plan = {
        "summary": None,
        "sections": [
            {
                "section": "work",
                "index": 0,
                "highlights": [
                    {
                        "index": 1,
                        "text": "Delivered a Tableau dashboard used by 40 store managers weekly.",
                        "evidence": [evidence],
                    },
                    {
                        "index": 2,
                        "text": "Cut costs by 30% across the network.",
                        "evidence": [evidence],
                    },
                ],
            },
            {"section": "education", "index": 0},
            {"section": "skills", "index": 0},
        ],
    }
    out = tailor_resume(project, "acme", _plan_fake(project, plan))
    tailored = json.loads(out.read_text(encoding="utf-8"))
    # Second job omitted; employers/dates copied verbatim from profile.
    assert [w["name"] for w in tailored["work"]] == ["ShopFront Retail"]
    bullets = tailored["work"][0]["highlights"]
    # The invented 30% bullet was dropped by the fact guard.
    assert [b["text"] for b in bullets] == [
        "Delivered a Tableau dashboard used by 40 store managers weekly."
    ]
    assert bullets[0]["evidence"] == [evidence]
    assert bullets[0]["original"].startswith("Shipped a Tableau")
    meta = tailored["meta"]["sartor"]
    assert meta["kept"] == {"work": 1, "education": 1, "skills": 1}
    assert meta["dropped"]["work"] == 1
    assert meta["bullets_dropped"] == 1
    # No number in the output is absent from the profile.
    profile = check_profile(project)
    assert numbers(" ".join(leaf_strings(tailored))) <= numbers(
        " ".join(leaf_strings(profile))
    )


def test_tailor_derives_evidence_when_plan_omits_it(tmp_path: Path):
    project = seed_project(tmp_path)
    plan = {"sections": [{"section": "work", "index": 1}]}
    out = tailor_resume(project, "acme", _plan_fake(project, plan))
    tailored = json.loads(out.read_text(encoding="utf-8"))
    bullets = tailored["work"][0]["highlights"]
    assert bullets and all(b["evidence"] for b in bullets)


def test_tailor_unknown_target(tmp_path: Path):
    project = seed_project(tmp_path)
    with pytest.raises(TailorError, match="target add"):
        tailor_resume(project, "nope", FakeProvider({}))


def test_tailor_without_profile(tmp_path: Path):
    project = init_project(tmp_path / "p")
    with pytest.raises(TailorError, match="profile build"):
        tailor_resume(project, "acme", FakeProvider({}))


def test_tailor_empty_plan(tmp_path: Path):
    project = seed_project(tmp_path)
    with pytest.raises(TailorError, match="no sections"):
        tailor_resume(project, "acme", _plan_fake(project, {"sections": []}))
