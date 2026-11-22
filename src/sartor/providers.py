"""LLM providers (S-002): exactly two, plus a fake for tests.

``openai-compatible`` covers OpenAI, OpenRouter, Groq, LM Studio and
Ollama (``http://localhost:11434/v1``, key ignored). ``anthropic`` is
the native Messages API. Both speak plain HTTPS via ``requests`` — no
vendor SDKs. The ``FakeProvider`` lets later stories test offline
with recorded replies keyed by exact prompt text.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import requests

from sartor.config import PROVIDERS, ConfigurationError


class ProviderError(Exception):
    """A provider call failed. ``kind`` separates the fixable causes:

    ``unreachable`` (host down), ``auth`` (bad/missing key),
    ``http`` (other non-2xx), ``bad-response`` (unparseable reply).
    """

    def __init__(self, message: str, kind: str = "http"):
        super().__init__(message)
        self.kind = kind


class Provider(Protocol):
    """What every pipeline stage needs from a model backend."""

    name: str
    model: str | None
    base_url: str

    def chat(self, system: str, prompt: str) -> str:
        """Return the model's reply text for one system+user exchange."""
        ...

    def list_models(self) -> list[str]:
        """Return the model ids the backend offers."""
        ...


def _request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    try:
        response = session.request(
            method, url, headers=headers, json=payload, timeout=timeout
        )
    except requests.RequestException as exc:
        raise ProviderError(
            f"Cannot reach {url} ({exc.__class__.__name__})", kind="unreachable"
        ) from exc
    if response.status_code in (401, 403):
        raise ProviderError(
            f"Authentication failed at {url} (HTTP {response.status_code})",
            kind="auth",
        )
    if response.status_code >= 400:
        raise ProviderError(
            f"HTTP {response.status_code} from {url}: {response.text[:200]}",
            kind="http",
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError(
            f"Reply from {url} is not JSON", kind="bad-response"
        ) from exc
    if not isinstance(data, dict):
        raise ProviderError(f"Reply from {url} is not an object", kind="bad-response")
    return data


class OpenAICompatibleProvider:
    """Any ``/v1/chat/completions`` endpoint; the key is optional."""

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 300,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def list_models(self) -> list[str]:
        data = _request(
            self.session,
            "GET",
            f"{self.base_url}/models",
            headers=self._headers(),
            payload=None,
            timeout=self.timeout,
        )
        return [str(item["id"]) for item in data.get("data", []) if "id" in item]

    def chat(self, system: str, prompt: str) -> str:
        if not self.model:
            raise ProviderError(
                "No model configured; set `model:` in sartor.yaml "
                "(sartor doctor lists what the server offers)",
                kind="bad-response",
            )
        data = _request(
            self.session,
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            payload={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self.timeout,
        )
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "Reply has no choices[0].message.content", kind="bad-response"
            ) from exc


class AnthropicProvider:
    """Anthropic Messages API; the key is required."""

    name = "anthropic"
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 300,
        max_tokens: int = 8192,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
        }

    def list_models(self) -> list[str]:
        data = _request(
            self.session,
            "GET",
            f"{self.base_url}/v1/models",
            headers=self._headers(),
            payload=None,
            timeout=self.timeout,
        )
        return [str(item["id"]) for item in data.get("data", []) if "id" in item]

    def chat(self, system: str, prompt: str) -> str:
        if not self.model:
            raise ProviderError(
                "No model configured; set `model:` in sartor.yaml "
                "(sartor doctor lists what the server offers)",
                kind="bad-response",
            )
        data = _request(
            self.session,
            "POST",
            f"{self.base_url}/v1/messages",
            headers=self._headers(),
            payload={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout,
        )
        parts = [
            str(block.get("text", ""))
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if not parts:
            raise ProviderError("Reply has no text content", kind="bad-response")
        return "".join(parts)


class FakeProvider:
    """Recorded replies for tests: maps prompt text to reply text."""

    name = "fake"
    base_url = "fake://local"

    def __init__(
        self,
        replies: dict[str, str],
        model: str | None = "fake-1",
        models: list[str] | None = None,
    ):
        self.replies = replies
        self.model = model
        self.models = models if models is not None else [model or "fake-1"]
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        try:
            return self.replies[prompt]
        except KeyError:
            raise ProviderError(
                f"FakeProvider has no recorded reply for prompt: {prompt[:80]!r}",
                kind="bad-response",
            ) from None

    def list_models(self) -> list[str]:
        return list(self.models)


def _api_key_for(config: dict[str, Any], default_env: str) -> str | None:
    key = config.get("api_key")
    if key:
        return str(key)
    return os.environ.get(default_env) or None


def get_provider(config: dict[str, Any]) -> Provider:
    """Build the configured provider. Raises ConfigurationError."""
    provider = config.get("provider")
    if provider is None:
        raise ConfigurationError(
            "No provider configured; set `provider:` in sartor.yaml "
            f"to one of: {', '.join(PROVIDERS)}"
        )
    timeout = float(config.get("timeout") or 300)
    model = config.get("model")
    if provider == "openai-compatible":
        return OpenAICompatibleProvider(
            base_url=str(config.get("base_url") or "http://localhost:11434/v1"),
            api_key=_api_key_for(config, "OPENAI_API_KEY"),
            model=model,
            timeout=timeout,
        )
    if provider == "anthropic":
        key = _api_key_for(config, "ANTHROPIC_API_KEY")
        if not key:
            env_name = config.get("api_key_env") or "ANTHROPIC_API_KEY"
            raise ConfigurationError(
                f"Anthropic needs an API key: set {env_name} in the "
                "environment (referenced as api_key: ${"
                + str(env_name)
                + "} in sartor.yaml)"
            )
        return AnthropicProvider(
            api_key=key,
            model=model,
            base_url=str(config.get("base_url") or AnthropicProvider.DEFAULT_BASE_URL),
            timeout=timeout,
        )
    raise ConfigurationError(
        f"unknown provider {provider!r}; expected one of: {', '.join(PROVIDERS)}"
    )
