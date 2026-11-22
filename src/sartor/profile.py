"""The profile: a hand-owned JSON Resume file (S-004).

``build`` drafts ``profile.json`` from the sources via the provider;
the person then edits it by hand and ``check`` validates it. Building
never silently overwrites an existing profile.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sartor.providers import Provider


class ProfileError(Exception):
    """Raised when the profile cannot be built or is invalid."""


def build_profile(project: Path, provider: Provider) -> Path:
    """Draft profile.json from ingested sources."""
    raise NotImplementedError("S-004: profile build")


def check_profile(project: Path) -> dict[str, Any]:
    """Validate profile.json; return it parsed."""
    raise NotImplementedError("S-004: profile check")
