"""Skeleton tests: packaging, config, project init (S-001), CLI shape."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import sartor
from sartor.cli import app
from sartor.config import ConfigurationError, load_config, validate_config
from sartor.project import ProjectError, init_project, is_project
from sartor.providers import FakeProvider, ProviderError

runner = CliRunner()


def test_version():
    assert re.match(r"^\d+\.\d+\.\d+", sartor.__version__)


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"sartor {sartor.__version__}" in result.output


def test_help_lists_m1_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "init",
        "doctor",
        "ingest",
        "profile",
        "target",
        "tailor",
        "verify",
        "report",
        "render",
    ):
        assert command in result.output


def test_stub_command_names_its_story():
    result = runner.invoke(app, ["report", "acme"])
    assert result.exit_code == 3
    assert "S-008" in result.output


def test_init_creates_project(tmp_path: Path):
    project = init_project(tmp_path / "my-profile")
    assert is_project(project)
    for name in ("sources", "targets", "exports"):
        assert (project / name).is_dir()
    assert not (project / "profile.json").exists()


def test_init_refuses_existing_project(tmp_path: Path):
    init_project(tmp_path)
    with pytest.raises(ProjectError, match="Already a Sartor project"):
        init_project(tmp_path)


def test_init_cli_exit_codes(tmp_path: Path):
    target = tmp_path / "p"
    first = runner.invoke(app, ["init", str(target)])
    assert first.exit_code == 0
    second = runner.invoke(app, ["init", str(target)])
    assert second.exit_code == 2


def test_config_defaults_and_layering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".sartor.yaml").write_text(
        "provider: anthropic\napi_key: ${SARTOR_TEST_KEY}\n", encoding="utf-8"
    )
    project = tmp_path / "proj"
    project.mkdir()
    (project / "sartor.yaml").write_text("model: claude-x\n", encoding="utf-8")
    monkeypatch.setenv("SARTOR_TEST_KEY", "sk-test")
    config = load_config(start=project, home=home)
    assert config["provider"] == "anthropic"
    assert config["model"] == "claude-x"
    assert config["api_key"] == "sk-test"
    assert config["theme"] == "ats-plain"


def test_config_rejects_unknown_provider():
    with pytest.raises(ConfigurationError, match="openai-compatible"):
        validate_config({"provider": "gemini"})


def test_fake_provider_records_and_replays():
    provider = FakeProvider({"hello": "world"})
    assert provider.chat("sys", "hello") == "world"
    with pytest.raises(ProviderError):
        provider.chat("sys", "unrecorded")
