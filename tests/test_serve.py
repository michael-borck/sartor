"""S-013: serve pages, downloads, actions, token gate, path safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from seedkit import AD, seed_project, span_id_containing
from test_render import _tailored

from sartor.providers import FakeProvider
from sartor.render import render_bundle
from sartor.serve import create_app, serve
from sartor.tailor import save_tailored
from sartor.target import build_parse_prompt
from sartor.verify import verify_resume

SECRET = "sk-secret-value-123"


def _client(tmp_path: Path, token: str | None = None) -> tuple[TestClient, Path]:
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    verify_resume(project, "acme")
    try:
        render_bundle(project, "acme")
    except Exception:
        pass  # partial bundle is still downloadable
    config = {
        "provider": "openai-compatible",
        "model": "fake-1",
        "base_url": "http://localhost:11434/v1",
        "api_key": SECRET,
        "theme": "ats-plain",
        "timeout": 5,
    }
    app = create_app(project, config=config, provider=FakeProvider({}), token=token)
    return TestClient(app), project


def test_health_and_project_no_secret(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert client.get("/api/health").json()["ok"] is True
    project_response = client.get("/api/project")
    assert project_response.status_code == 200
    assert SECRET not in project_response.text
    assert client.get("/").status_code == 200
    assert SECRET not in client.get("/").text
    home = client.get("/").text
    assert "acme" in home
    assert "Jane Doe" in home or "Present and valid" in home


def test_profile_page(tmp_path: Path):
    client, _ = _client(tmp_path)
    response = client.get("/profile")
    assert response.status_code == 200
    assert "Jane Doe" in response.text
    assert "profile.json" in response.text


def test_target_page_verdict_words_and_downloads(tmp_path: Path):
    client, _ = _client(tmp_path)
    page = client.get("/targets/acme")
    assert page.status_code == 200
    assert "supported" in page.text
    assert "unsupported" in page.text  # planted 30% bullet
    assert "Download bundle" in page.text
    pitch = client.get("/targets/acme/files/pitch.md")
    assert pitch.status_code == 200
    assert "Jane Doe" in pitch.text
    manifest = client.get("/targets/acme/files/manifest.json")
    assert manifest.status_code == 200
    assert (manifest.json()).get("target") == "acme"


def test_download_path_safety(tmp_path: Path):
    client, project = _client(tmp_path)
    assert client.get("/targets/acme/files/sartor.yaml").status_code == 404
    assert client.get("/targets/..%2f..%2fprofile/files/resume.md").status_code in (
        400,
        404,
    )
    assert client.get("/targets/nope").status_code == 404
    assert (project / "profile.json").is_file()


def test_upload_ingest_action(tmp_path: Path):
    client, project = _client(tmp_path)
    response = client.post(
        "/actions/ingest",
        files=[
            (
                "files",
                ("extra.md", b"# Extra\n\nDid a workshop in 2024.", "text/markdown"),
            )
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (project / "sources" / "extra.md.json").is_file()


def test_profile_check_and_target_add_actions(tmp_path: Path):
    project = seed_project(tmp_path)
    parsed = {
        "title": "Analyst",
        "organisation": "Acme Corp",
        "seniority": "senior",
        "keywords": ["SQL"],
        "must_haves": [
            {"text": "Expert SQL", "quote": "Expert SQL, including window functions."}
        ],
        "nice_to_haves": [],
        "selection_criteria": [],
    }
    fake = FakeProvider({build_parse_prompt(AD): json.dumps(parsed)})
    app = create_app(project, config={"provider": "openai-compatible"}, provider=fake)
    client = TestClient(app)
    response = client.post("/actions/profile/check", follow_redirects=False)
    assert response.status_code == 303
    response = client.post(
        "/actions/targets",
        data={"name": "acme2", "ad_text": AD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (project / "targets" / "acme2.json").is_file()


def test_verify_report_render_actions(tmp_path: Path):
    client, project = _client(tmp_path)
    for action in ("verify", "report", "render"):
        data = {"theme": "modern"} if action == "render" else {}
        response = client.post(
            f"/targets/acme/actions/{action}", data=data, follow_redirects=False
        )
        assert response.status_code == 303, action
    out = project / "exports" / "acme"
    assert (out / "report.md").is_file()
    assert (out / "manifest.json").is_file()
    assert 'theme": "modern"' in (out / "manifest.json").read_text(encoding="utf-8")


def test_token_gate(tmp_path: Path):
    client, _ = _client(tmp_path, token="letmein")
    assert client.get("/").status_code == 401
    assert client.get("/api/project").status_code == 401
    assert client.get("/", params={"token": "letmein"}).status_code == 200
    assert (
        client.get("/api/project", headers={"X-Sartor-Token": "letmein"}).status_code
        == 200
    )
    assert client.get("/api/health").status_code == 200  # health stays open


def test_serve_refuses_remote_without_token(tmp_path: Path, monkeypatch):
    project = seed_project(tmp_path)
    monkeypatch.delenv("SARTOR_SERVE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="Refusing to bind beyond localhost"):
        serve(project, host="0.0.0.0", port=0)


def test_tailor_action_uses_injected_provider(tmp_path: Path):
    from sartor.profile import all_spans, check_profile, load_sources
    from sartor.tailor import build_tailor_prompt
    from sartor.target import load_target

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
                    }
                ],
            }
        ],
    }
    prompt = build_tailor_prompt(
        check_profile(project),
        load_target(project, "acme"),
        all_spans(load_sources(project)),
    )
    fake = FakeProvider({prompt: json.dumps(plan)})
    app = create_app(project, config={"provider": "openai-compatible"}, provider=fake)
    client = TestClient(app)
    response = client.post("/targets/acme/actions/tailor", follow_redirects=False)
    assert response.status_code == 303
    tailored = json.loads(
        (project / "exports/acme/tailored.json").read_text(encoding="utf-8")
    )
    assert tailored["work"][0]["highlights"][0]["text"].startswith("Delivered")
