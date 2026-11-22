"""S-004: profile build/check against the Jane Doe seed + FakeProvider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sartor.ingest import ingest_file
from sartor.profile import (
    ProfileError,
    build_distil_prompt,
    build_profile,
    check_profile,
    load_sources,
    validate_profile,
)
from sartor.project import init_project
from sartor.providers import FakeProvider

SEED = Path(__file__).resolve().parents[1] / "examples" / "jane-doe"


def _project(tmp_path: Path, *seed_files: str) -> Path:
    project = init_project(tmp_path / "p")
    for name in seed_files:
        ingest_file(SEED / name, project)
    return project


def _fake_for(project: Path) -> FakeProvider:
    prompt = build_distil_prompt(load_sources(project))
    reply = (SEED / "profile.json").read_text(encoding="utf-8")
    return FakeProvider({prompt: reply})


def test_build_with_fake_provider(tmp_path: Path):
    project = _project(tmp_path, "resume.md", "publications.txt")
    fake = _fake_for(project)
    out = build_profile(project, fake)
    profile = json.loads(out.read_text(encoding="utf-8"))
    validate_profile(profile)  # valid JSON Resume incl. meta
    assert profile["basics"]["name"] == "Jane Doe"
    evidence = profile["meta"]["sartor"]["evidence"]
    assert evidence["work[0]"], "work entry must carry source span ids"
    assert all(s.startswith("src://") for s in evidence["work[0]"])
    assert len(fake.calls) == 1


def test_build_refuses_overwrite(tmp_path: Path):
    project = _project(tmp_path, "resume.md")
    build_profile(project, _fake_for(project))
    with pytest.raises(ProfileError, match="exists"):
        build_profile(project, _fake_for(project))
    build_profile(project, _fake_for(project), force=True)


def test_build_from_json_resume_candidate_needs_no_model(tmp_path: Path):
    project = _project(tmp_path, "profile.json")
    fake = FakeProvider({})  # any model call would raise
    out = build_profile(project, fake)
    profile = json.loads(out.read_text(encoding="utf-8"))
    assert profile["basics"]["name"] == "Jane Doe"
    assert fake.calls == []


def test_build_invalid_model_reply_saves_draft(tmp_path: Path):
    project = _project(tmp_path, "resume.md")
    prompt = build_distil_prompt(load_sources(project))
    fake = FakeProvider({prompt: "not json at all"})
    with pytest.raises(ProfileError, match="profile.draft.txt"):
        build_profile(project, fake)
    assert (project / "profile.draft.txt").is_file()
    assert not (project / "profile.json").exists()


def test_build_without_sources(tmp_path: Path):
    project = init_project(tmp_path / "p")
    with pytest.raises(ProfileError, match="No sources"):
        build_profile(project, FakeProvider({}))


def test_check_names_first_invalid_field(tmp_path: Path):
    project = _project(tmp_path, "profile.json")
    build_profile(project, FakeProvider({}))
    profile = json.loads((project / "profile.json").read_text(encoding="utf-8"))
    profile["work"][0]["startDate"] = "March 2021"  # not YYYY-MM-DD-ish
    (project / "profile.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8"
    )
    with pytest.raises(ProfileError, match=r"work\[0\]"):
        check_profile(project)


def test_check_passes_hand_edited_profile(tmp_path: Path):
    project = _project(tmp_path, "profile.json")
    build_profile(project, FakeProvider({}))
    profile = check_profile(project)
    assert profile["basics"]["name"] == "Jane Doe"
