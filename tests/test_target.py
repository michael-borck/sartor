"""S-005: target parsing against the Jane Doe seed ad + FakeProvider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sartor.project import init_project
from sartor.providers import FakeProvider
from sartor.target import (
    TargetError,
    add_target,
    build_parse_prompt,
    load_target,
)

SEED = Path(__file__).resolve().parents[1] / "examples" / "jane-doe"
AD = (SEED / "ad-acme.txt").read_text(encoding="utf-8")

PARSED = {
    "title": "Senior Data Analyst",
    "organisation": "Acme Corp",
    "seniority": "senior",
    "keywords": ["SQL", "Python", "Tableau", "dbt", "Kubernetes", "Go"],
    "must_haves": [
        {"text": "5+ years data analyst", "quote": "5+ years in a data analyst role."},
        {"text": "Expert SQL", "quote": "Expert SQL, including window functions."},
        {"text": "Python pandas", "quote": "Python for data work (pandas or Polars)."},
        {"text": "Invented requirement", "quote": "Must juggle flaming torches."},
    ],
    "nice_to_haves": [
        {"text": "Mentoring", "quote": "Mentoring junior analysts."},
    ],
    "selection_criteria": [
        {
            "text": "Address essentials",
            "quote": "address each essential point with an example.",
        }
    ],
}


def _fake(reply: object = PARSED) -> FakeProvider:
    return FakeProvider({build_parse_prompt(AD): json.dumps(reply)})


def test_add_target(tmp_path: Path):
    project = init_project(tmp_path / "p")
    out = add_target(project, "acme", AD, _fake(), source_label="ad-acme.txt")
    target = json.loads(out.read_text(encoding="utf-8"))
    assert target["title"] == "Senior Data Analyst"
    # The invented requirement's quote is not in the ad, so it is dropped.
    assert [m["text"] for m in target["must_haves"]] == [
        "5+ years data analyst",
        "Expert SQL",
        "Python pandas",
    ]
    assert (project / "targets" / "acme.txt").read_text(encoding="utf-8") == AD
    assert load_target(project, "acme") == target


def test_add_target_refuses_overwrite(tmp_path: Path):
    project = init_project(tmp_path / "p")
    add_target(project, "acme", AD, _fake())
    with pytest.raises(TargetError, match="--force"):
        add_target(project, "acme", AD, _fake())
    add_target(project, "acme", AD, _fake(), force=True)


def test_add_target_empty_ad(tmp_path: Path):
    project = init_project(tmp_path / "p")
    with pytest.raises(TargetError, match="No requirements found in empty.txt"):
        add_target(project, "acme", "  \n", FakeProvider({}), source_label="empty.txt")
    assert not (project / "targets" / "acme.json").exists()


def test_add_target_no_valid_requirements(tmp_path: Path):
    project = init_project(tmp_path / "p")
    empty = {"title": "x", "must_haves": [], "nice_to_haves": []}
    with pytest.raises(TargetError, match="No requirements found"):
        add_target(project, "acme", AD, _fake(empty))


def test_load_missing_target(tmp_path: Path):
    project = init_project(tmp_path / "p")
    with pytest.raises(TargetError, match="target add"):
        load_target(project, "nope")
