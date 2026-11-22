"""Configuration for Sartor (S-001).

Layers, later wins:

1. Built-in defaults
2. ``~/.sartor.yaml`` — provider + keys, set once
3. ``./sartor.yaml``   — per-project overrides (or an explicit path)

Secrets are referenced as ``${VAR}`` and expanded from the environment,
so no plaintext keys need to live in config files.

Exactly two providers exist (SPEC): ``openai-compatible`` (any
``/v1/chat/completions``; Ollama is this provider at
``http://localhost:11434/v1`` with the key ignored) and ``anthropic``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

PROVIDERS = ("openai-compatible", "anthropic")


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""


DEFAULT_CONFIG: dict[str, Any] = {
    "provider": None,
    "model": None,
    "base_url": None,
    "api_key": None,
    "timeout": 300,
    "theme": "ats-plain",
}

EXAMPLE_CONFIG = """\
# Sartor config. Exactly two providers (docs/SPEC.md):
#   openai-compatible — any /v1/chat/completions endpoint.
#                       Ollama: base_url http://localhost:11434/v1, no key.
#   anthropic         — native Messages API, key required.
# Keys by ${ENV_VAR} reference only; never paste a key here.
provider: openai-compatible
base_url: http://localhost:11434/v1
model: null          # e.g. qwen3:4b (Ollama) — sartor doctor lists models
api_key: null        # e.g. ${OPENAI_API_KEY}; ignored by local servers
timeout: 300
theme: ats-plain
"""

_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        match = _ENV_REF.match(value.strip())
        if match:
            return os.environ.get(match.group(1))
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{path}: invalid YAML ({exc})") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")
    return data


def load_config(start: Path | None = None, home: Path | None = None) -> dict[str, Any]:
    """Load merged config: defaults < ~/.sartor.yaml < ./sartor.yaml."""
    start = Path.cwd() if start is None else start
    home = Path.home() if home is None else home
    merged: dict[str, Any] = dict(DEFAULT_CONFIG)
    for candidate in (home / ".sartor.yaml", start / "sartor.yaml"):
        if candidate.is_file():
            merged.update(_load_yaml(candidate))
    config = {key: _expand(value) for key, value in merged.items()}
    raw_key = merged.get("api_key")
    if isinstance(raw_key, str):
        match = _ENV_REF.match(raw_key.strip())
        if match:
            # Remember which env var the key was meant to come from, so a
            # missing key can be reported by name (never by value).
            config["api_key_env"] = match.group(1)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    provider = config.get("provider")
    if provider is not None and provider not in PROVIDERS:
        raise ConfigurationError(
            f"unknown provider {provider!r}; expected one of: {', '.join(PROVIDERS)}"
        )


def save_example_config(path: Path) -> None:
    path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
