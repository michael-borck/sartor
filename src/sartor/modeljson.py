"""Parsing model replies that should be JSON (shared by S-004..S-006)."""

from __future__ import annotations

import json
import re
from typing import Any


class ModelJsonError(Exception):
    """Raised when a provider reply is not the JSON object asked for."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_model_json(reply: str) -> dict[str, Any]:
    text = _FENCE_RE.sub("", reply.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ModelJsonError("model reply contains no JSON object", raw=reply)
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ModelJsonError(
            f"model reply is not valid JSON ({exc})", raw=reply
        ) from exc
    if not isinstance(data, dict):
        raise ModelJsonError("model reply JSON is not an object", raw=reply)
    return data
