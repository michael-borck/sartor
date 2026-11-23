"""`sartor doctor`: check the provider before any generation (S-002).

One line per check, final "ok" or the first failure. Unreachable host,
bad key, and missing model each get a distinct line naming the fix.

`probe_provider` (S-025) is the structured form behind Refresh models
and Test connection in the UIs: it lists the provider's models and,
with ``generate=True``, proves the selected model can generate with
one tiny reply. ``ok`` means fully ready (generation verified);
``connected`` alone only means reachable/authorised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from sartor.config import ConfigurationError
from sartor.providers import Provider, ProviderError, get_provider

PROBE_LIST_TIMEOUT = 15.0
PROBE_GENERATE_TIMEOUT = 60.0
PROBE_SYSTEM = "Reply with exactly OK."
PROBE_PROMPT = "OK"


@dataclass
class DoctorResult:
    ok: bool
    lines: list[str] = field(default_factory=list)


@dataclass
class ProbeResult:
    status: str
    ok: bool
    connected: bool
    provider: str | None
    base_url: str | None
    models: list[str] = field(default_factory=list)
    model: str | None = None
    model_offered: bool | None = None
    generated: bool = False
    reply: str | None = None
    message: str = ""


def _is_local(base_url: str) -> bool:
    return "localhost" in base_url or "127.0.0.1" in base_url


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _failure_message(active: Provider, exc: ProviderError) -> tuple[str, str]:
    if exc.kind == "unreachable":
        hint = (
            " — is Ollama running? (`ollama serve`)"
            if _is_local(active.base_url)
            else " — check the URL and your connection"
        )
        return "unreachable", f"Cannot reach {active.base_url}{hint}"
    if exc.kind == "auth":
        return (
            "auth",
            "Authentication failed — check the API key "
            "(local servers like Ollama need none)",
        )
    return "failed", str(exc)


def _set_timeout(active: Provider, timeout: float) -> None:
    if hasattr(active, "timeout"):
        object.__setattr__(active, "timeout", timeout)


def probe_provider(
    config: dict[str, Any],
    *,
    generate: bool = False,
    provider: Provider | None = None,
    list_timeout: float = PROBE_LIST_TIMEOUT,
    generate_timeout: float = PROBE_GENERATE_TIMEOUT,
) -> ProbeResult:
    """Probe a provider config without saving anything (S-025).

    A key may arrive via ``config["api_key"]`` (already expanded) or
    the ``SARTOR_API_KEY`` environment variable the desktop shell
    passes from the OS keychain; it is never echoed in the result.
    """
    candidate = dict(config)
    if not candidate.get("api_key") and os.environ.get("SARTOR_API_KEY"):
        candidate["api_key"] = os.environ["SARTOR_API_KEY"]
    candidate["timeout"] = list_timeout
    try:
        active = provider or get_provider(candidate)
    except ConfigurationError as exc:
        return ProbeResult(
            status="config",
            ok=False,
            connected=False,
            provider=str(candidate.get("provider") or "") or None,
            base_url=str(candidate.get("base_url") or "") or None,
            model=str(candidate.get("model") or "") or None,
            message=str(exc),
        )

    base = {
        "provider": active.name,
        "base_url": active.base_url,
        "model": active.model,
    }
    _set_timeout(active, list_timeout)
    try:
        models = _dedupe(active.list_models())
    except ProviderError as exc:
        status, message = _failure_message(active, exc)
        return ProbeResult(
            status=status, ok=False, connected=False, message=message, **base
        )

    model_offered: bool | None = None
    if active.model and models:
        model_offered = active.model in models

    if not generate:
        return ProbeResult(
            status="connected",
            ok=False,
            connected=True,
            models=models,
            model_offered=model_offered,
            message=f"Connected — {len(models)} models found.",
            **base,
        )
    if not active.model:
        return ProbeResult(
            status="connected_no_model",
            ok=False,
            connected=True,
            models=models,
            message=f"Connected — {len(models)} models found. Choose a model.",
            **base,
        )
    if model_offered is False:
        return ProbeResult(
            status="model_not_offered",
            ok=False,
            connected=True,
            models=models,
            model_offered=False,
            message=(
                f"Connected, but {active.model} is not offered by this "
                "provider. Pick one from the refreshed list."
            ),
            **base,
        )

    _set_timeout(active, generate_timeout)
    try:
        reply = active.chat(PROBE_SYSTEM, PROBE_PROMPT)
    except ProviderError as exc:
        status, message = _failure_message(active, exc)
        if status == "failed":
            status = "generation_failed"
        return ProbeResult(
            status=status,
            ok=False,
            connected=True,
            models=models,
            model_offered=model_offered,
            message=message,
            **base,
        )
    return ProbeResult(
        status="ok",
        ok=True,
        connected=True,
        models=models,
        model_offered=model_offered,
        generated=True,
        reply=reply.strip()[:80],
        message=f"Connected — {active.model} replied.",
        **base,
    )


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
