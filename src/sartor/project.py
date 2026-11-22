"""Project folders (S-001).

A project is a plain folder the person owns:

    sartor.yaml   config (provider, model, theme)
    sources/      ingested sources as JSON (S-003)
    targets/      parsed job ads (S-005)
    exports/      tailored bundles per target (S-006..S-009)
    profile.json  the person's JSON Resume (S-004; absent until built)
"""

from __future__ import annotations

from pathlib import Path

from sartor.config import save_example_config

PROJECT_DIRS = ("sources", "targets", "exports")


class ProjectError(Exception):
    """Raised when a project folder cannot be created or found."""


def is_project(path: Path) -> bool:
    return (path / "sartor.yaml").is_file()


def init_project(path: Path) -> Path:
    """Create a project at ``path``. Refuses to touch an existing one."""
    if is_project(path):
        raise ProjectError(f"Already a Sartor project: {path}")
    path.mkdir(parents=True, exist_ok=True)
    for name in PROJECT_DIRS:
        (path / name).mkdir(exist_ok=True)
    save_example_config(path / "sartor.yaml")
    return path
