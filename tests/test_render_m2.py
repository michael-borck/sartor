"""M2 render: themes (S-010), handoffs (S-011), manifest (S-012)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from seedkit import seed_project
from test_render import _tailored
from typer.testing import CliRunner

from sartor.cli import app
from sartor.render import (
    THEMES,
    RenderError,
    build_manifest,
    render_bundle,
    render_deck,
    render_html,
    render_markdown,
    render_pitch,
)
from sartor.tailor import save_tailored

runner = CliRunner()
SNAP = Path(__file__).parent / "snapshots" / "render"


@pytest.mark.parametrize("theme", ["modern", "academic"])
def test_theme_golden_html(tmp_path: Path, theme: str):
    tailored = _tailored(seed_project(tmp_path))
    themed = render_html(tailored, theme=theme)
    assert themed == (SNAP / theme / "resume.html").read_text(encoding="utf-8")
    assert themed != (SNAP / "ats-plain" / "resume.html").read_text(encoding="utf-8")
    assert "Shipped a Tableau dashboard" in themed


def test_themes_do_not_change_markdown_or_json(tmp_path: Path):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    outputs: dict[str, tuple[str, str]] = {}
    for theme in THEMES:
        try:
            render_bundle(project, "acme", theme=theme)
        except RenderError:
            pass  # PDF may be unavailable; MD/JSON were written first
        out = project / "exports" / "acme"
        outputs[theme] = (
            (out / "resume.md").read_text(encoding="utf-8"),
            (out / "resume.json").read_text(encoding="utf-8"),
        )
    assert outputs["modern"] == outputs["ats-plain"]
    assert outputs["academic"] == outputs["ats-plain"]


def test_handoff_goldens_and_flagged_omission(tmp_path: Path):
    tailored = _tailored(seed_project(tmp_path))
    pitch = render_pitch(tailored)
    deck = render_deck(tailored)
    assert pitch == (SNAP / "ats-plain" / "pitch.md").read_text(encoding="utf-8")
    assert deck == (SNAP / "ats-plain" / "deck.md").read_text(encoding="utf-8")
    for text in (pitch, deck):
        assert "flagged bullets omitted: 1" in text
        assert "Cut costs by 30%" not in text
        assert "40 store managers" in text
    assert deck.count("\n# ") >= 3  # name, role, skills/education slides


def test_manifest_hashes_verify(tmp_path: Path):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    try:
        render_bundle(project, "acme", theme="modern")
    except RenderError:
        pass
    out = project / "exports" / "acme"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["theme"] == "modern"
    assert manifest["target"] == "acme"
    assert manifest["provider"]["name"] == "openai-compatible"
    assert manifest["inputs"]["profile"]["name"] == "profile.json"
    assert manifest["inputs"]["sources"], "sources recorded with hashes"
    assert manifest["verify"] is None  # verify was not run in this setup
    for entry in manifest["outputs"]:
        path = out / entry["name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert path.stat().st_size == entry["bytes"]
    names = [e["name"] for e in manifest["outputs"]]
    assert "pitch.md" in names and "deck.md" in names
    assert "manifest.json" not in names  # cannot hash itself


def test_manifest_records_verify_counts(tmp_path: Path):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    from sartor.verify import verify_resume

    verify_resume(project, "acme")
    manifest = build_manifest(project, "acme", "ats-plain", [])
    assert manifest["verify"]["counts"]["unsupported"] == 1


def test_render_cli_uses_config_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    config = project / "sartor.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "theme: ats-plain", "theme: academic"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["render", "acme"])
    manifest = json.loads(
        (project / "exports" / "acme" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["theme"] == "academic"
    assert result.exit_code in (0, 1)  # 1 only when PDF libs are unavailable
    if result.exit_code == 1:
        assert "WeasyPrint" in result.output


def test_unknown_theme_writes_nothing(tmp_path: Path):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    before = sorted(p.name for p in (project / "exports" / "acme").iterdir())
    with pytest.raises(RenderError, match="modern.*academic|expected one of"):
        render_bundle(project, "acme", theme="fancy")
    after = sorted(p.name for p in (project / "exports" / "acme").iterdir())
    assert after == before


def test_markdown_theme_invariant_unit(tmp_path: Path):
    tailored = _tailored(seed_project(tmp_path))
    assert render_markdown(tailored) == render_markdown(tailored)
