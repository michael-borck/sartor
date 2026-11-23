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


def test_serve_framework_and_research(tmp_path: Path):
    from sartor.search import FakeSearch, build_queries
    from sartor.target import load_target

    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    target = load_target(project, "acme")
    fake = FakeSearch(
        {
            q: [
                {
                    "title": "Acme overview",
                    "url": "https://example.com/acme",
                    "snippet": "Public company context.",
                }
            ]
            for q in build_queries(target)
        }
    )
    # serve research uses configured chain, so exercise it via injected
    # provider path: pre-run research with the fake, then check pages.
    from sartor.search import research_target

    research_target(project, "acme", {"search_enabled": True}, chain=[fake])
    app = create_app(
        project,
        config={"provider": "openai-compatible", "search_enabled": False},
        provider=FakeProvider({}),
    )
    client = TestClient(app)
    csv_bytes = (
        Path(__file__).parents[1] / "examples/jane-doe/framework-demo.csv"
    ).read_bytes()
    response = client.post(
        "/actions/frameworks",
        data={"name": "demo", "kind": "custom"},
        files=[("file", ("framework-demo.csv", csv_bytes, "text/csv"))],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (project / "frameworks/demo.json").is_file()
    response = client.post(
        "/targets/acme/actions/framework",
        data={"framework": "demo"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    mapping = project / "exports/acme/framework-demo.json"
    assert mapping.is_file()
    page = client.get("/targets/acme")
    assert page.status_code == 200
    assert "Frameworks" in page.text
    assert "matched" in page.text or "target_gap" in page.text
    assert "Research (grounding)" in page.text
    assert "https://example.com/acme" in page.text
    download = client.get("/targets/acme/files/framework-demo.json")
    assert download.status_code == 200
    assert download.json()["framework"] == "demo"
    assert client.get("/targets/acme/files/research.json").status_code == 200
    assert client.get("/api/project").json()["frameworks"][0]["name"] == "demo"

    response = client.post(
        "/targets/acme/actions/framework-statement",
        data={"framework": "demo", "display": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    statement = project / "exports/acme/statement-demo.md"
    assert statement.is_file()
    assert "Level 4" not in statement.read_text(encoding="utf-8")
    page = client.get("/targets/acme")
    assert page.status_code == 200
    assert "Framework statements" in page.text
    assert "internal only" in page.text.lower()
    assert client.get("/targets/acme/files/statement-demo.md").status_code == 200
    assert client.get("/targets/acme/files/statement-demo.json").status_code == 200
    detail = client.get("/api/targets/acme").json()
    assert detail["framework_statements"][0]["framework"] == "demo"

    response = client.post(
        "/targets/acme/actions/framework-confirm",
        data={"framework": "demo", "code": "SQL", "level": "4"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/targets/acme")
    assert "confirmed 4" in page.text
    mapping = json.loads(
        (project / "exports/acme/framework-demo.json").read_text(encoding="utf-8")
    )
    sql = {row["code"]: row for row in mapping["skills"]}["SQL"]
    assert sql["confirmed_level"] == 4


def test_help_checklist_and_template(tmp_path: Path):
    client, _ = _client(tmp_path)
    home = client.get("/")
    assert home.status_code == 200
    assert "Getting started" in home.text
    assert "Refresh models" in home.text
    assert "Test connection" in home.text
    # Panels follow pipeline order: Sources before Profile.
    assert home.text.index("Step 2") < home.text.index("Step 3")

    help_page = client.get("/help")
    assert help_page.status_code == 200
    assert "The workflow" in help_page.text
    assert "framework-template.csv" in help_page.text
    assert SECRET not in help_page.text

    template = client.get("/help/framework-template.csv")
    assert template.status_code == 200
    assert template.text.splitlines()[0] == "code,name,level,description,keywords"


def test_provider_probe_endpoints(tmp_path: Path):
    from sartor.doctor import PROBE_PROMPT

    project = seed_project(tmp_path)
    config = {
        "provider": "openai-compatible",
        "model": "fake-1",
        "api_key": SECRET,
        "timeout": 5,
    }
    fake = FakeProvider({PROBE_PROMPT: "OK"}, models=["fake-1", "fake-2"])
    app = create_app(project, config=config, provider=fake)
    client = TestClient(app)

    models = client.post("/api/provider/models", json={})
    assert models.status_code == 200
    payload = models.json()
    assert payload["status"] == "connected"
    assert payload["models"] == ["fake-1", "fake-2"]
    assert SECRET not in models.text

    tested = client.post("/api/provider/test", json={})
    assert tested.status_code == 200
    payload = tested.json()
    assert payload["status"] == "ok"
    assert payload["generated"] is True
    assert payload["reply"] == "OK"
    assert SECRET not in tested.text


def test_provider_probe_endpoints_token_gated(tmp_path: Path):
    client, _ = _client(tmp_path, token="tok123")
    assert client.post("/api/provider/models", json={}).status_code == 401
    assert client.get("/help").status_code == 401
    ok = client.post("/api/provider/models?token=tok123", json={})
    assert ok.status_code == 200
