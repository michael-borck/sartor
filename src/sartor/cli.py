"""Sartor CLI.

M1 commands (docs/STORIES.md): init (S-001), doctor (S-002),
ingest (S-003), profile build/check (S-004), target add (S-005),
tailor (S-006), verify (S-007), report (S-008), render (S-009).
Only ``init`` is implemented in this scaffold; the rest say so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

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


def _project_or_exit() -> Path:
    from sartor.project import find_project

    project = find_project()
    if project is None:
        err_console.print(
            "Not in a Sartor project: run `sartor init DIR` first, "
            "then run this inside it"
        )
        raise typer.Exit(code=2)
    return project


def _provider_or_exit() -> Any:
    from sartor.config import ConfigurationError, load_config
    from sartor.providers import ProviderError, get_provider

    try:
        return get_provider(load_config())
    except (ConfigurationError, ProviderError) as exc:
        err_console.print(f"config: {exc}")
        raise typer.Exit(code=1) from exc


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
    from sartor.config import ConfigurationError, load_config
    from sartor.doctor import run_doctor

    try:
        config = load_config()
    except ConfigurationError as exc:
        err_console.print(f"config: {exc}")
        raise typer.Exit(code=1) from exc
    result = run_doctor(config)
    target = console if result.ok else err_console
    for line in result.lines:
        target.print(line)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command()
def ingest(files: list[Path] = typer.Argument(None)) -> None:  # noqa: B008
    """Ingest source files into the project (S-003)."""
    from sartor.ingest import IngestError, ingest_file, span_count
    from sartor.project import find_project

    if not files:
        err_console.print("No files given: sartor ingest FILE…")
        raise typer.Exit(code=2)
    project = find_project()
    if project is None:
        err_console.print(
            "Not in a Sartor project: run `sartor init DIR` first, "
            "then run this inside it"
        )
        raise typer.Exit(code=2)
    total_spans = 0
    failures = 0
    for path in files:
        try:
            out = ingest_file(path, project)
        except IngestError as exc:
            err_console.print(str(exc))
            failures += 1
            continue
        count = span_count(out)
        total_spans += count
        console.print(f"{path.name}: {count} spans")
    ok = len(files) - failures
    console.print(f"Ingested {ok} of {len(files)} files, {total_spans} spans")
    if failures:
        raise typer.Exit(code=1)


@profile_app.command("build")
def profile_build(
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing profile.json.")
    ] = False,
) -> None:
    """Draft profile.json from the sources (S-004)."""
    from sartor.profile import ProfileError, build_profile

    project = _project_or_exit()
    provider = _provider_or_exit()
    try:
        out = build_profile(project, provider, force=force)
    except ProfileError as exc:
        err_console.print(str(exc))
        code = 2 if "exists" in str(exc) else 1
        raise typer.Exit(code=code) from exc
    console.print(f"Wrote {out.name} — review it, then: sartor profile check")


@profile_app.command("check")
def profile_check() -> None:
    """Validate a hand-edited profile.json (S-004)."""
    from sartor.profile import ProfileError, check_profile

    project = _project_or_exit()
    try:
        check_profile(project)
    except ProfileError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print("profile.json: ok")


@target_app.command("add")
def target_add(
    name: str = typer.Argument(...),
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Ad file (default: read stdin)."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing target.")
    ] = False,
) -> None:
    """Parse a job advertisement into targets/NAME.json (S-005)."""
    from sartor.target import TargetError, add_target, load_target

    project = _project_or_exit()
    if file is not None:
        if not file.is_file():
            err_console.print(f"{file.name}: no such file")
            raise typer.Exit(code=1)
        ad_text = file.read_text(encoding="utf-8")
        source_label = file.name
    else:
        ad_text = typer.get_text_stream("stdin").read()
        source_label = "stdin"
    provider = _provider_or_exit()
    try:
        add_target(
            project,
            name,
            ad_text,
            provider,
            force=force,
            source_label=source_label,
        )
    except TargetError as exc:
        err_console.print(str(exc))
        code = 2 if "exists" in str(exc) or "Invalid target name" in str(exc) else 1
        raise typer.Exit(code=code) from exc
    target = load_target(project, name)
    console.print(
        f"Target {name}: {len(target['must_haves'])} must-haves, "
        f"{len(target['nice_to_haves'])} nice-to-haves"
    )
    console.print(f"Tailor: sartor tailor {name}")


@app.command()
def tailor(name: str = typer.Argument(...)) -> None:
    """Tailor the profile against a target (S-006)."""
    import json as _json

    from sartor.tailor import TailorError, tailor_resume

    project = _project_or_exit()
    provider = _provider_or_exit()
    try:
        out = tailor_resume(project, name, provider)
    except TailorError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    meta = _json.loads(out.read_text(encoding="utf-8"))["meta"]["sartor"]
    kept_bits = ", ".join(f"{k} {v}" for k, v in meta["kept"].items())
    console.print(f"Tailored for {name}: kept {kept_bits or 'nothing'}")
    console.print(
        f"Bullets: {meta['bullets_kept']} kept, "
        f"{meta['bullets_dropped']} dropped (no evidence or unsupported fact)"
    )
    console.print(f"Verify: sartor verify {name}")


@app.command()
def verify(
    name: str = typer.Argument(...),
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Drop unsupported bullets instead of flagging."),
    ] = False,
    llm: Annotated[
        bool, typer.Option("--llm", help="Add an entailment pass (network call).")
    ] = False,
) -> None:
    """Check every bullet against its evidence (S-007)."""
    import json as _json

    from sartor.verify import VerifyError, verify_resume

    project = _project_or_exit()
    provider = _provider_or_exit() if llm else None
    try:
        out = verify_resume(project, name, strict=strict, llm=llm, provider=provider)
    except VerifyError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    data = _json.loads(out.read_text(encoding="utf-8"))
    for bullet in data["bullets"]:
        console.print(f"{bullet['verdict']}: {bullet['path']} — {bullet['text'][:70]}")
    counts = data["counts"]
    console.print(
        f"supported {counts['supported']}, weak {counts['weak']}, "
        f"unsupported {counts['unsupported']}"
        + (f", dropped {data['dropped']}" if strict else "")
    )
    console.print(f"Report: sartor report {name}")
    if counts["unsupported"]:
        raise typer.Exit(code=1)


@app.command()
def report(name: str = typer.Argument(...)) -> None:
    """Write the coverage and gap report (S-008)."""
    _not_yet("S-008", "report")


@app.command()
def render(name: str = typer.Argument(...)) -> None:
    """Render the export bundle (MD, HTML, PDF, DOCX, JSON) (S-009)."""
    _not_yet("S-009", "render")
