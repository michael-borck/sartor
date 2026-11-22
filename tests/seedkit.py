"""Shared Jane Doe seed setup for story tests (S-006..S-009)."""

from __future__ import annotations

import json
from pathlib import Path

from sartor.ingest import ingest_file
from sartor.profile import build_profile
from sartor.project import init_project
from sartor.providers import FakeProvider
from sartor.target import add_target, build_parse_prompt

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
        {"text": "Kubernetes", "quote": "Kubernetes operations experience."},
    ],
    "nice_to_haves": [
        {"text": "Mentoring", "quote": "Mentoring junior analysts."},
    ],
    "selection_criteria": [],
}


def seed_project(tmp_path: Path) -> Path:
    """Project with Jane ingested, profile built, and target `acme` added."""
    project = init_project(tmp_path / "p")
    for name in ("resume.md", "publications.txt", "profile.json"):
        ingest_file(SEED / name, project)
    build_profile(project, FakeProvider({}))  # JSON Resume candidate path
    fake = FakeProvider({build_parse_prompt(AD): json.dumps(PARSED)})
    add_target(project, "acme", AD, fake, source_label="ad-acme.txt")
    return project


def span_id_containing(project: Path, needle: str) -> str:
    from sartor.profile import all_spans, load_sources

    for span_id, text in all_spans(load_sources(project)).items():
        if needle in text:
            return span_id
    raise AssertionError(f"no span containing {needle!r}")
