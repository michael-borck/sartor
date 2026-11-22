"""Sartor CLI.

M1 commands (docs/STORIES.md): init (S-001), doctor (S-002),
ingest (S-003), profile build/check (S-004), target add (S-005),
tailor (S-006), verify (S-007), report (S-008), render (S-009).
Only ``init`` is implemented in this scaffold; the rest say so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from sartor import __version__
from sartor.project import ProjectError, init_project

app = typer.Typer(
    name="sartor",
    help=(
        "Privacy-first resume tailoring: your evidence in, a tailored "
        "resume out — every claim traceable, nothing invented."
    ),
    no_args_is_help=True,
)
profile_app = typer.Typer(help="Build and check the profile (profile.json).")
target_app = typer.Typer(help="Add parsed job advertisements (targets).")
app.add_typer(profile_app, name="profile")
app.add_typer(target_app, name="target")

console = Console()
err_console = Console(stderr=True)


def _not_yet(story: str, what: str) -> None:
    err_console.print(f"Not yet implemented: {what} ({story}, docs/STORIES.md)")
    raise typer.Exit(code=3)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"sartor {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Print the Sartor version.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Sartor: evidence-linked resume tailoring."""


@app.command()
def init(
    directory: Path = typer.Argument(..., help="Folder to create the project in."),
) -> None:
    """Create a project folder with config you can edit (S-001)."""
    try:
        path = init_project(directory)
    except ProjectError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=2) from exc
    console.print(f"Created Sartor project: {path}")
    console.print("  sartor.yaml  (edit: provider, model, theme)")
    console.print("  sources/  targets/  exports/")
    console.print("Add sources: sartor ingest FILE…")


@app.command()
def doctor() -> None:
    """Check the configured provider before any generation (S-002)."""
    _not_yet("S-002", "doctor")


@app.command()
def ingest(files: list[Path] = typer.Argument(...)) -> None:
    """Ingest source files into the project (S-003)."""
    _not_yet("S-003", "ingest")


@profile_app.command("build")
def profile_build() -> None:
    """Draft profile.json from the sources (S-004)."""
    _not_yet("S-004", "profile build")


@profile_app.command("check")
def profile_check() -> None:
    """Validate a hand-edited profile.json (S-004)."""
    _not_yet("S-004", "profile check")


@target_app.command("add")
def target_add(name: str = typer.Argument(...)) -> None:
    """Parse a job advertisement into targets/NAME.json (S-005)."""
    _not_yet("S-005", "target add")


@app.command()
def tailor(name: str = typer.Argument(...)) -> None:
    """Tailor the profile against a target (S-006)."""
    _not_yet("S-006", "tailor")


@app.command()
def verify(
    name: str = typer.Argument(...),
    strict: bool = typer.Option(
        False, "--strict", help="Drop unsupported bullets instead of flagging."
    ),
    llm: bool = typer.Option(
        False, "--llm", help="Add an entailment pass (network call)."
    ),
) -> None:
    """Check every bullet against its evidence (S-007)."""
    _not_yet("S-007", "verify")


@app.command()
def report(name: str = typer.Argument(...)) -> None:
    """Write the coverage and gap report (S-008)."""
    _not_yet("S-008", "report")


@app.command()
def render(name: str = typer.Argument(...)) -> None:
    """Render the export bundle (MD, HTML, PDF, DOCX, JSON) (S-009)."""
    _not_yet("S-009", "render")
