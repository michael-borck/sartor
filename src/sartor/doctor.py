"""`sartor doctor`: check the provider before any generation (S-002).

One line per check, final "ok" or the first failure. Unreachable host,
bad key, and missing model each get a distinct line naming the fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sartor.config import ConfigurationError
from sartor.providers import Provider, ProviderError, get_provider


@dataclass
class DoctorResult:
    ok: bool
    lines: list[str] = field(default_factory=list)


def _is_local(base_url: str) -> bool:
    return "localhost" in base_url or "127.0.0.1" in base_url


def run_doctor(
    config: dict[str, Any], provider: Provider | None = None
) -> DoctorResult:
    lines: list[str] = []
    try:
        active = provider or get_provider(config)
    except ConfigurationError as exc:
        return DoctorResult(ok=False, lines=[f"config: {exc}"])

    lines.append(f"provider: {active.name}")
    lines.append(f"base_url: {active.base_url}")
    lines.append(f"checking {active.name} at {active.base_url}…")
    try:
        models = active.list_models()
    except ProviderError as exc:
        if exc.kind == "unreachable":
            hint = (
                " — is Ollama running? (`ollama serve`)"
                if _is_local(active.base_url)
                else " — check the URL and your connection"
            )
            lines.append(f"unreachable: cannot reach {active.base_url}{hint}")
        elif exc.kind == "auth":
            lines.append(
                "auth: the server rejected the API key — check api_key in "
                "sartor.yaml (local servers like Ollama need none)"
            )
        else:
            lines.append(f"failed: {exc}")
        return DoctorResult(ok=False, lines=lines)

    shown = ", ".join(models[:10]) + ("…" if len(models) > 10 else "")
    lines.append(f"models ({len(models)}): {shown or '(none reported)'}")

    if active.model:
        if models and active.model not in models:
            lines.append(
                f"model: {active.model!r} is not offered by this server — "
                "pick one from the list above in sartor.yaml"
            )
            return DoctorResult(ok=False, lines=lines)
        lines.append(f"model: {active.model}")
    else:
        lines.append("model: (unset — set `model:` in sartor.yaml before generating)")

    lines.append("ok")
    return DoctorResult(ok=True, lines=lines)
