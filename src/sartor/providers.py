"""LLM providers (S-002): exactly two, plus a fake for tests.

``openai-compatible`` covers OpenAI, OpenRouter, Groq, LM Studio and
Ollama (``http://localhost:11434/v1``, key ignored). ``anthropic`` is
the native Messages API. Real transports land with S-002; the
``FakeProvider`` here lets every later story test offline with
recorded replies keyed by exact prompt text.
"""

from __future__ import annotations

from typing import Protocol


class ProviderError(Exception):
    """Raised when a provider call fails."""


class Provider(Protocol):
    """The one operation every pipeline stage needs."""

    name: str
    model: str | None

    def chat(self, system: str, prompt: str) -> str:
        """Return the model's reply text for one system+user exchange."""
        ...


class FakeProvider:
    """Recorded replies for tests: maps prompt text to reply text."""

    name = "fake"

    def __init__(self, replies: dict[str, str], model: str | None = "fake-1"):
        self.replies = replies
        self.model = model
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        try:
            return self.replies[prompt]
        except KeyError:
            raise ProviderError(
                f"FakeProvider has no recorded reply for prompt: {prompt[:80]!r}"
            ) from None
