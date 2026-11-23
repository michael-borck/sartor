"""Sartor CLI.

Commands (docs/STORIES.md): the M1 core loop — init (S-001),
doctor (S-002), ingest (S-003), profile build/check (S-004),
target add (S-005), tailor (S-006), verify (S-007), report
(S-008), render (S-009) — plus M2 render extras: themes (S-010),
pitch/deck handoffs (S-011), and bundle manifest (S-012).
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
def doctor(
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the probe result as JSON (S-025)")
    ] = False,
    generate: Annotated[
        bool, typer.Option("--generate", help="Also prove the model can generate")
    ] = False,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Override the configured provider")
    ] = None,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="Override the configured base URL")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Override the configured model")
    ] = None,
    timeout: Annotated[
        float | None, typer.Option("--timeout", help="Probe timeout in seconds")
    ] = None,
) -> None:
    """Check the configured provider before any generation (S-002, S-025)."""
    from dataclasses import asdict

    from sartor.config import ConfigurationError, load_config
    from sartor.doctor import probe_provider, run_doctor

    try:
        config = load_config()
    except ConfigurationError as exc:
        err_console.print(f"config: {exc}")
        raise typer.Exit(code=1) from exc
    if provider:
        config["provider"] = provider
    if base_url:
        config["base_url"] = base_url
    if model is not None:
        config["model"] = model or None
    if as_json or generate:
        import json as json_lib

        probe = probe_provider(
            config,
            generate=generate,
            list_timeout=timeout or 15.0,
            generate_timeout=timeout or 60.0,
        )
        if as_json:
            # Plain stdout, not Rich: callers parse this as JSON.
            typer.echo(json_lib.dumps(asdict(probe)))
        else:
            console.print(probe.message)
            if probe.models:
                console.print(
                    f"models ({len(probe.models)}): " + ", ".join(probe.models[:10])
                )
        ready = probe.ok if generate else probe.connected
        if not ready:
            raise typer.Exit(code=1)
        return
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
def tailor(
    name: str = typer.Argument(...),
    framework: Annotated[
        str | None,
        typer.Option(
            "--framework",
            help="Framework for optional framework voice (S-018).",
        ),
    ] = None,
    voice: Annotated[
        str,
        typer.Option(
            "--voice",
            help="standard (default) or framework (voice-only; no level).",
        ),
    ] = "standard",
) -> None:
    """Tailor the profile against a target (S-006, S-018)."""
    import json as _json

    from sartor.tailor import TailorError, tailor_resume

    project = _project_or_exit()
    provider = _provider_or_exit()
    try:
        out = tailor_resume(
            project,
            name,
            provider,
            framework_name=framework,
            voice=voice,
        )
    except TailorError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    meta = _json.loads(out.read_text(encoding="utf-8"))["meta"]["sartor"]
    kept_bits = ", ".join(f"{k} {v}" for k, v in meta["kept"].items())
    console.print(f"Tailored for {name}: kept {kept_bits or 'nothing'}")
    if meta.get("framework"):
        console.print(
            f"Framework voice: {meta['framework']['name']} "
            "(voice-only; no level printed)"
        )
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
    import json as _json

    from sartor.report import ReportError, build_report

    project = _project_or_exit()
    if not (project / "exports" / name / "verify.json").is_file():
        console.print("Not verified yet — running deterministic verify first.")
    try:
        out = build_report(project, name)
    except ReportError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    coverage = _json.loads(
        (project / "exports" / name / "coverage.json").read_text(encoding="utf-8")
    )
    c = coverage["counts"]
    console.print(
        f"Coverage: {c['evidenced']} evidenced, {c['weak']} weak, {c['gap']} gaps"
    )
    console.print(f"Report: {out}")
    console.print(f"Render: sartor render {name}")


@app.command()
def render(
    name: str = typer.Argument(...),
    theme: Annotated[
        str | None,
        typer.Option(
            "--theme",
            help="ats-plain (default), modern, or academic; else sartor.yaml theme.",
        ),
    ] = None,
) -> None:
    """Render the export bundle incl. pitch, deck, manifest (S-009..S-012)."""
    from sartor.config import load_config
    from sartor.render import RenderError, render_bundle

    project = _project_or_exit()
    selected_theme = theme
    if selected_theme is None:
        try:
            selected_theme = str(load_config(start=project).get("theme") or "ats-plain")
        except Exception:
            selected_theme = "ats-plain"
    try:
        written = render_bundle(project, name, theme=selected_theme)
    except RenderError as exc:
        for path in exc.written:
            console.print(f"Wrote {path.name}")
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for path in written:
        console.print(f"Wrote {path.name}")
    console.print(f"Bundle: exports/{name}/")


@app.command()
def serve(
    host: Annotated[
        str, typer.Option("--host", help="Bind host (default localhost only).")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Bind port.")] = 5384,
) -> None:
    """Run the local web UI for this project (S-013)."""
    project = _project_or_exit()
    try:
        from sartor.serve import serve as run_serve
    except RuntimeError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    console.print(f"Sartor serve: http://{display_host}:{port}/")
    console.print("Open that URL in your browser. Stop with Ctrl-C.")
    try:
        run_serve(project, host=host, port=port)
    except RuntimeError as exc:
        err_console.print(str(exc))
        if "FastAPI" in str(exc) or "serve" in str(exc).lower():
            err_console.print('Install with: pip install "sartor[serve]"')
        raise typer.Exit(code=1) from exc


framework_app = typer.Typer(
    help="User-supplied skill frameworks (SFIA, O*NET, ESCO, AQF, custom)."
)
app.add_typer(framework_app, name="framework")


@framework_app.command("add")
def framework_add(
    file: Path = typer.Argument(...),
    name: str = typer.Option(..., "--name", help="Framework name used in commands."),
    kind: Annotated[
        str,
        typer.Option("--kind", help="sfia, onet, esco, aqf, or custom."),
    ] = "custom",
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing framework.")
    ] = False,
) -> None:
    """Add a user-supplied framework CSV/JSON file (S-014)."""
    from sartor.frameworks import FrameworkError, add_framework

    project = _project_or_exit()
    try:
        out = add_framework(project, file, name, kind, force=force)
    except FrameworkError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"Framework {name} ({kind}) written: {out.name}")
    console.print(f"Map it: sartor framework map TARGET --framework {name}")


@framework_app.command("list")
def framework_list() -> None:
    """List frameworks added to this project (S-014)."""
    from sartor.frameworks import list_frameworks

    project = _project_or_exit()
    frameworks = list_frameworks(project)
    if not frameworks:
        console.print(
            "No frameworks yet: sartor framework add FILE --name NAME --kind sfia"
        )
        return
    for framework in frameworks:
        skills = [
            row for row in framework.get("skills", []) or [] if isinstance(row, dict)
        ]
        codes = {
            str(row.get("code", "")).lower() for row in skills if row.get("code")
        }
        console.print(
            f"{framework.get('name')}: kind {framework.get('kind')}, "
            f"{len(codes)} codes, {len(skills)} rows, "
            f"{len(framework.get('confirmed_levels', {}) or {})} confirmed levels "
            f"(source {framework.get('source_file')})"
        )


@framework_app.command("map")
def framework_map(
    target: str = typer.Argument(...),
    framework: str = typer.Option(..., "--framework", help="Framework name."),
) -> None:
    """Map profile and target to framework codes (S-015)."""
    import json as _json

    from sartor.frameworks import FrameworkError, map_framework

    project = _project_or_exit()
    try:
        out = map_framework(project, target, framework)
    except FrameworkError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    mapping = _json.loads(out.read_text(encoding="utf-8"))
    counts = mapping["counts"]
    console.print(
        f"Mapped {target} to {framework}: matched {counts['matched']}, "
        f"target gaps {counts['target_gap']}, profile only {counts['profile_only']}, "
        f"neither {counts['neither']}"
    )
    suggested = sum(
        1 for row in mapping.get("skills", []) if row.get("level_status") == "suggested"
    )
    confirmed = sum(
        1 for row in mapping.get("skills", []) if row.get("level_status") == "confirmed"
    )
    if suggested or confirmed:
        console.print(
            f"Internal levels: {confirmed} confirmed, {suggested} suggested "
            "(suggested is not a formal assessment)"
        )
    console.print(f"Wrote {out}; run sartor report {target} to include it")
    console.print(
        f"Statement: sartor framework statement {target} --framework {framework}"
    )


@framework_app.command("confirm")
def framework_confirm(
    framework: str = typer.Option(..., "--framework", help="Framework name."),
    code: str = typer.Option(..., "--code", help="Framework skill code."),
    level: str = typer.Option(
        ..., "--level", help="Level you confirm you stand behind."
    ),
) -> None:
    """Confirm a framework level for one code (S-018)."""
    from sartor.frameworks import FrameworkError, confirm_framework_level

    project = _project_or_exit()
    try:
        out = confirm_framework_level(project, framework, code, level)
    except FrameworkError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(
        f"Confirmed {code} at level {level} in framework {framework} ({out.name})."
    )
    console.print("Re-run framework map or statement to refresh exported files.")


@framework_app.command("statement")
def framework_statement(
    target: str = typer.Argument(...),
    framework: str = typer.Option(..., "--framework", help="Framework name."),
    display: Annotated[
        str,
        typer.Option(
            "--display",
            help="none, code (default, no level), or code-level.",
        ),
    ] = "code",
) -> None:
    """Write a framework-voiced evidence statement (S-018)."""
    import json as _json

    from sartor.frameworks import FrameworkError, write_framework_statement

    project = _project_or_exit()
    try:
        md_path, json_path = write_framework_statement(
            project, target, framework, display=display
        )
    except FrameworkError as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    counts = _json.loads(json_path.read_text(encoding="utf-8"))["counts"]
    console.print(
        f"Framework statement for {target} ({framework}, display {display}): "
        f"{counts['statements']} statements across "
        f"{counts['skills_with_statements']} skills"
    )
    if display != "code-level":
        console.print("No level is printed in the statement.")
    console.print(f"Wrote {md_path.name} and {json_path.name} in exports/{target}/")


@app.command()
def research(
    name: str = typer.Argument(...),
    enable_search: Annotated[
        bool,
        typer.Option(
            "--enable-search",
            help="One-off opt-in if search_enabled is not set in config.",
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", help="Results per query.")] = 5,
) -> None:
    """Fetch cited company/role context for a target (S-016, opt-in)."""
    from sartor.config import ConfigurationError, load_config
    from sartor.search import SearchError, research_target

    project = _project_or_exit()
    try:
        config = load_config(start=project)
        out = research_target(project, name, config, enabled=enable_search, limit=limit)
    except (ConfigurationError, SearchError) as exc:
        err_console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"Wrote {out.name} and research.md in exports/{name}/ (context only)")
