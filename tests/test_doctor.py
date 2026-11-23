"""S-002: provider transports against a fake HTTP server, and doctor."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sartor.cli import app
from sartor.config import ConfigurationError
from sartor.doctor import probe_provider, run_doctor
from sartor.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    ProviderError,
    get_provider,
)

runner = CliRunner()
MODELS = [{"id": "fake-1"}, {"id": "fake-2"}]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # keep tests quiet
        pass

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _auth_failed(self) -> bool:
        auth = self.headers.get("Authorization", "")
        key = self.headers.get("x-api-key", "")
        return auth == "Bearer bad-key" or key == "bad-key"

    def do_GET(self) -> None:
        if self._auth_failed():
            self._send(401, {"error": "unauthorized"})
        elif self.path.endswith("/models"):
            self._send(200, {"object": "list", "data": MODELS})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self._auth_failed():
            self._send(401, {"error": "unauthorized"})
        elif self.path.endswith("/chat/completions"):
            self._send(
                200,
                {"choices": [{"message": {"content": f"echo:{body['model']}"}}]},
            )
        elif self.path.endswith("/v1/messages"):
            self._send(
                200,
                {"content": [{"type": "text", "text": f"echo:{body['model']}"}]},
            )
        else:
            self._send(404, {"error": "not found"})


@pytest.fixture()
def server_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()


def test_openai_compatible_chat_and_models(server_url: str):
    provider = OpenAICompatibleProvider(
        base_url=f"{server_url}/v1", model="fake-1", timeout=5
    )
    assert provider.list_models() == ["fake-1", "fake-2"]
    assert provider.chat("sys", "hi") == "echo:fake-1"


def test_openai_compatible_no_key_needed(server_url: str):
    # The Ollama case: no api_key at all.
    provider = OpenAICompatibleProvider(
        base_url=f"{server_url}/v1", api_key=None, model="fake-2", timeout=5
    )
    assert provider.chat("sys", "hi") == "echo:fake-2"


def test_anthropic_chat_and_models(server_url: str):
    provider = AnthropicProvider(
        api_key="sk-test", model="fake-1", base_url=server_url, timeout=5
    )
    assert provider.list_models() == ["fake-1", "fake-2"]
    assert provider.chat("sys", "hi") == "echo:fake-1"


def test_bad_key_is_auth_error(server_url: str):
    provider = OpenAICompatibleProvider(
        base_url=f"{server_url}/v1", api_key="bad-key", timeout=5
    )
    with pytest.raises(ProviderError) as exc_info:
        provider.list_models()
    assert exc_info.value.kind == "auth"


def test_unreachable_is_distinct():
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:1/v1", timeout=2)
    with pytest.raises(ProviderError) as exc_info:
        provider.list_models()
    assert exc_info.value.kind == "unreachable"


def test_anthropic_missing_key_names_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MY_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="MY_ANTHROPIC_KEY") as exc_info:
        get_provider(
            {
                "provider": "anthropic",
                "api_key": None,
                "api_key_env": "MY_ANTHROPIC_KEY",
            }
        )
    assert "sk-" not in str(exc_info.value)


def test_doctor_ok(server_url: str):
    result = run_doctor(
        {
            "provider": "openai-compatible",
            "base_url": f"{server_url}/v1",
            "model": "fake-1",
            "timeout": 5,
        }
    )
    assert result.ok
    text = "\n".join(result.lines)
    assert "openai-compatible" in text
    assert f"{server_url}/v1" in text
    assert "fake-1" in text
    assert result.lines[-1] == "ok"


def test_doctor_failure_lines_are_distinct(server_url: str):
    unreachable = run_doctor(
        {
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:1/v1",
            "timeout": 2,
        }
    )
    bad_key = run_doctor(
        {
            "provider": "openai-compatible",
            "base_url": f"{server_url}/v1",
            "api_key": "bad-key",
            "timeout": 5,
        }
    )
    missing_model = run_doctor(
        {
            "provider": "openai-compatible",
            "base_url": f"{server_url}/v1",
            "model": "nope-9",
            "timeout": 5,
        }
    )
    assert not (unreachable.ok or bad_key.ok or missing_model.ok)
    assert "unreachable" in unreachable.lines[-1]
    assert "auth" in bad_key.lines[-1]
    assert "not offered" in missing_model.lines[-1]


def test_doctor_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server_url: str):
    (tmp_path / "sartor.yaml").write_text(
        f"provider: openai-compatible\nbase_url: {server_url}/v1\n"
        "model: fake-1\ntimeout: 5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "ok" in result.output


def _probe_cfg(server_url: str, **overrides: object) -> dict:
    cfg: dict = {
        "provider": "openai-compatible",
        "base_url": f"{server_url}/v1",
        "model": "fake-1",
        "timeout": 5,
    }
    cfg.update(overrides)
    return cfg


def test_probe_refresh_models(server_url: str):
    result = probe_provider(_probe_cfg(server_url))
    assert result.status == "connected"
    assert result.connected and not result.ok and not result.generated
    assert result.models == ["fake-1", "fake-2"]
    assert result.model_offered is True
    assert "2 models" in result.message


def test_probe_test_connection_requires_generation(server_url: str):
    result = probe_provider(_probe_cfg(server_url), generate=True)
    assert result.status == "ok"
    assert result.ok and result.generated
    assert result.reply == "echo:fake-1"

    no_model = probe_provider(_probe_cfg(server_url, model=None), generate=True)
    assert no_model.status == "connected_no_model"
    assert no_model.connected and not no_model.ok

    missing = probe_provider(_probe_cfg(server_url, model="nope-9"), generate=True)
    assert missing.status == "model_not_offered"
    assert missing.model_offered is False


def test_probe_failure_statuses_are_distinct(server_url: str):
    unreachable = probe_provider(
        {"provider": "openai-compatible", "base_url": "http://127.0.0.1:1/v1"},
        list_timeout=2,
    )
    assert unreachable.status == "unreachable"
    assert "Cannot reach" in unreachable.message

    bad_key = probe_provider(_probe_cfg(server_url, api_key="bad-key"), generate=True)
    assert bad_key.status == "auth"
    assert "bad-key" not in bad_key.message

    unconfigured = probe_provider({})
    assert unconfigured.status == "config"
    assert unconfigured.provider is None


def test_probe_anthropic_generate(server_url: str):
    result = probe_provider(
        {
            "provider": "anthropic",
            "base_url": server_url,
            "api_key": "sk-test",
            "model": "fake-1",
            "timeout": 5,
        },
        generate=True,
    )
    assert result.status == "ok"
    assert result.models == ["fake-1", "fake-2"]
    assert result.reply == "echo:fake-1"
    assert "sk-test" not in result.message


def test_doctor_json_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server_url: str):
    (tmp_path / "sartor.yaml").write_text(
        "provider: openai-compatible\nmodel: fake-1\ntimeout: 5\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(
        app,
        ["doctor", "--json", "--generate", "--base-url", f"{server_url}/v1"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["models"] == ["fake-1", "fake-2"]
    assert payload["generated"] is True
