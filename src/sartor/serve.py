"""Local web UI for reviewing a Sartor project (S-013).

FastAPI app served on localhost: project home, profile review,
per-target review with verify verdicts beside every bullet, bundle
downloads, and form actions for the M1 pipeline (ingest, profile
build/check, target add, tailor, verify, report, render).

Privacy rules: provider keys are read from the project config on the
server and never sent to the browser; review pages make no provider
calls — only explicit action buttons do. Downloads are limited to a
filename whitelist inside ``exports/<target>/``.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from sartor import __version__
from sartor.config import load_config

if TYPE_CHECKING:  # runtime names are injected by create_app below
    from fastapi import Request, UploadFile
    from fastapi.responses import FileResponse, RedirectResponse
from sartor.ingest import SUPPORTED_SUFFIXES
from sartor.profile import load_sources
from sartor.providers import get_provider

DOWNLOAD_FILES = {
    "resume.md": "text/markdown",
    "resume.html": "text/html",
    "resume.json": "application/json",
    "resume.docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "resume.pdf": "application/pdf",
    "pitch.md": "text/markdown",
    "deck.md": "text/markdown",
    "manifest.json": "application/json",
    "tailored.json": "application/json",
    "verify.json": "application/json",
    "coverage.json": "application/json",
    "report.md": "text/markdown",
    "research.md": "text/markdown",
    "research.json": "application/json",
}
_FRAMEWORK_FILE_RE = re.compile(r"^framework-[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
_STATEMENT_FILE_RE = re.compile(
    r"^statement-[A-Za-z0-9][A-Za-z0-9._-]*\.(?:json|md)$"
)


def download_media_type(filename: str) -> str | None:
    if filename in DOWNLOAD_FILES:
        return DOWNLOAD_FILES[filename]
    if _FRAMEWORK_FILE_RE.match(filename):
        return "application/json"
    if _STATEMENT_FILE_RE.match(filename):
        return "application/json" if filename.endswith(".json") else "text/markdown"
    return None


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def safe_target_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(f"Invalid target name {name!r}")
    return name


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def sanitized_config(config: dict[str, Any]) -> dict[str, Any]:
    """Config fields safe to show in the browser (never the key)."""
    return {
        "provider": config.get("provider"),
        "model": config.get("model"),
        "base_url": config.get("base_url"),
        "theme": config.get("theme") or "ats-plain",
        "api_key_set": bool(config.get("api_key")),
        "search_enabled": bool(config.get("search_enabled")),
        "search_provider": config.get("search_provider") or "duckduckgo",
        "search_api_key_set": bool(config.get("search_api_key")),
    }


def export_files(project: Path, target: str) -> list[dict[str, Any]]:
    out = project / "exports" / target
    files: list[dict[str, Any]] = []
    names = list(DOWNLOAD_FILES)
    if out.is_dir():
        names.extend(p.name for p in sorted(out.glob("framework-*.json")))
        names.extend(
            p.name
            for p in sorted([*out.glob("statement-*.json"), *out.glob("statement-*.md")])
        )
    for name in names:
        path = out / name
        if path.is_file():
            files.append({"name": name, "bytes": path.stat().st_size})
    return files


def project_summary(project: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Everything the home page shows, as plain JSON-able data."""
    sources = [
        {
            "source": record.get("source"),
            "kind": record.get("kind"),
            "spans": len(record.get("spans", []) or []),
            "profile_candidate": bool(record.get("profile_candidate")),
        }
        for record in load_sources(project)
    ]
    profile_data = _read_json(project / "profile.json")
    profile: dict[str, Any] = {"present": profile_data is not None}
    if profile_data:
        from sartor.profile import ProfileError, validate_profile

        try:
            validate_profile(profile_data)
            profile["valid"] = True
            profile["error"] = None
        except ProfileError as exc:
            profile["valid"] = False
            profile["error"] = str(exc)
        basics = profile_data.get("basics") or {}
        profile["name"] = basics.get("name")
        profile["label"] = basics.get("label")
        profile["sections"] = {
            key: len(value)
            for key, value in profile_data.items()
            if isinstance(value, list)
        }
    targets: list[dict[str, Any]] = []
    targets_dir = project / "targets"
    if targets_dir.is_dir():
        for path in sorted(targets_dir.glob("*.json")):
            data = _read_json(path)
            if data is None:
                continue
            name = str(data.get("name") or path.stem)
            verify = _read_json(project / "exports" / name / "verify.json")
            targets.append(
                {
                    "name": name,
                    "title": data.get("title", ""),
                    "organisation": data.get("organisation", ""),
                    "must_haves": len(data.get("must_haves", []) or []),
                    "nice_to_haves": len(data.get("nice_to_haves", []) or []),
                    "tailored": (
                        project / "exports" / name / "tailored.json"
                    ).is_file(),
                    "verify_counts": (verify or {}).get("counts"),
                    "files": export_files(project, name),
                }
            )
    from sartor.frameworks import list_frameworks

    framework_summaries: list[dict[str, Any]] = []
    for item in list_frameworks(project):
        skills = [row for row in item.get("skills", []) or [] if isinstance(row, dict)]
        framework_summaries.append(
            {
                "name": item.get("name"),
                "kind": item.get("kind"),
                "skills": len(skills),
                "codes": len(
                    {
                        str(row.get("code", "")).lower()
                        for row in skills
                        if row.get("code")
                    }
                ),
                "level_rows": sum(1 for row in skills if row.get("level") is not None),
                "confirmed_levels": len(item.get("confirmed_levels", {}) or {}),
                "source_file": item.get("source_file"),
            }
        )
    return {
        "version": __version__,
        "project": str(project),
        "config": sanitized_config(config),
        "sources": sources,
        "profile": profile,
        "targets": targets,
        "frameworks": framework_summaries,
        "search_enabled": bool(config.get("search_enabled")),
    }


def target_detail(project: Path, name: str) -> dict[str, Any] | None:
    """Target + tailored bullets with verdicts + coverage, for review."""
    safe_target_name(name)
    target = _read_json(project / "targets" / f"{name}.json")
    if target is None:
        return None
    tailored = _read_json(project / "exports" / name / "tailored.json")
    verify = _read_json(project / "exports" / name / "verify.json")
    coverage = _read_json(project / "exports" / name / "coverage.json")
    verdicts = {
        str(bullet.get("path")): bullet
        for bullet in (verify or {}).get("bullets", []) or []
        if isinstance(bullet, dict)
    }
    bullets: list[dict[str, Any]] = []
    if tailored:
        from sartor.tailor import bullet_entries

        for path, bullet in bullet_entries(tailored):
            verdict = verdicts.get(path, {})
            bullets.append(
                {
                    "path": path,
                    "text": bullet.get("text", ""),
                    "evidence": bullet.get("evidence", []),
                    "flagged": bool(bullet.get("flagged")),
                    "verdict": verdict.get("verdict"),
                    "reasons": verdict.get("reasons", []),
                }
            )
    framework_mappings: list[dict[str, Any]] = []
    framework_statements: list[dict[str, Any]] = []
    out_dir = project / "exports" / name
    if out_dir.is_dir():
        for mapping_path in sorted(out_dir.glob("framework-*.json")):
            mapping = _read_json(mapping_path)
            if mapping is not None:
                framework_mappings.append(mapping)
        for statement_path in sorted(out_dir.glob("statement-*.json")):
            statement = _read_json(statement_path)
            if statement is not None:
                framework_statements.append(statement)
    return {
        "target": target,
        "tailored": tailored,
        "bullets": bullets,
        "verify_counts": (verify or {}).get("counts"),
        "coverage": coverage,
        "frameworks": framework_mappings,
        "framework_statements": framework_statements,
        "research": _read_json(out_dir / "research.json"),
        "files": export_files(project, name),
    }


_CSS = """
:root { color-scheme: light; --ink:#17202b; --muted:#5b6774; --line:#d8dee6;
  --accent:#205a8a; --accent-dark:#174468; --bg:#f3f5f7; --panel:#fff;
  --ok:#18794e; --weak:#9a6700; --bad:#b42318; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
header { background:#162433; color:#fff; padding:14px 22px;
  display:flex; gap:22px; align-items:baseline; flex-wrap:wrap; }
header .brand { font-family:Georgia,serif; font-size:24px; }
header nav a { color:#dce8f3; margin-right:16px; text-decoration:none; }
header nav a:hover, a { color:var(--accent); }
main { max-width:1040px; margin:0 auto; padding:24px 20px 48px; }
h1 { font-family:Georgia,serif; font-weight:500; font-size:30px; margin:8px 0 6px; }
h2 { font-size:19px; margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px; }
h3 { font-size:16px; margin:18px 0 6px; }
p.muted, .muted { color:var(--muted); }
section.panel { background:var(--panel); border:1px solid var(--line); padding:18px 20px; margin:14px 0; }
table { width:100%; border-collapse:collapse; margin:8px 0; }
th,td { text-align:left; vertical-align:top; padding:7px 9px; border-bottom:1px solid var(--line); }
th { font-size:13px; color:var(--muted); }
button, .button { background:var(--accent); color:#fff; border:1px solid var(--accent);
  padding:7px 13px; border-radius:4px; cursor:pointer; font:inherit; text-decoration:none; display:inline-block; }
button:hover, .button:hover { background:var(--accent-dark); }
button.secondary { background:#fff; color:var(--accent); }
label { display:block; font-weight:600; margin:12px 0 5px; }
input[type=text], textarea, select { width:100%; padding:8px 10px; border:1px solid #aeb9c5; border-radius:4px; font:inherit; background:#fff; }
textarea { min-height:150px; }
input[type=file] { margin:6px 0; }
.check { display:flex; gap:8px; align-items:center; font-weight:400; }
.check input { width:auto; }
.actions { display:flex; flex-wrap:wrap; gap:8px; margin:14px 0; }
.actions form { margin:0; }
.notice { border:1px solid #8db4d2; background:#e8f1f8; padding:10px 14px; margin:14px 0; }
.error { border:1px solid #e4a49e; background:#fff0ef; padding:10px 14px; margin:14px 0; }
.verdict { font-weight:700; white-space:nowrap; }
.supported { color:var(--ok); } .weak { color:var(--weak); } .unsupported { color:var(--bad); }
.evidence { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.flag { color:var(--bad); font-weight:700; }
pre { white-space:pre-wrap; background:#f7f9fb; border:1px solid var(--line); padding:14px; overflow:auto; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.small { font-size:13px; }
@media (max-width:680px) { main{padding:16px 12px 36px} th,td{padding:6px} }
"""


def _page(
    title: str,
    body: str,
    ok: str | None = None,
    error: str | None = None,
    token_suffix: str = "",
) -> str:
    esc = html_lib.escape
    notice = f'<div class="notice" role="status">{esc(ok)}</div>' if ok else ""
    problem = f'<div class="error" role="alert">{esc(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Sartor</title><style>{_CSS}</style></head>
<body><header><span class="brand">Sartor</span>
<nav><a href="/{token_suffix}">Project</a><a href="/profile{token_suffix}">Profile</a></nav>
<span class="small">Local review only · keys stay on this computer</span></header>
<main>{notice}{problem}{body}</main></body></html>"""


def _target_rows(summary: dict[str, Any], token_suffix: str) -> str:
    esc = html_lib.escape
    if not summary["targets"]:
        return "<p class='muted'>No targets yet. Paste a job advertisement below.</p>"
    rows = []
    for target in summary["targets"]:
        counts = target.get("verify_counts") or {}
        verify_text = (
            ", ".join(f"{key} {value}" for key, value in counts.items())
            if counts
            else "not verified"
        )
        rows.append(
            "<tr>"
            f"<td><a href='/targets/{quote(str(target['name']))}{token_suffix}'>"
            f"{esc(str(target['name']))}</a></td>"
            f"<td>{esc(str(target.get('title') or ''))}</td>"
            f"<td>{esc(str(target.get('organisation') or ''))}</td>"
            f"<td>{target['must_haves']} / {target['nice_to_haves']}</td>"
            f"<td>{'yes' if target['tailored'] else 'no'}</td>"
            f"<td>{esc(verify_text)}</td>"
            f"<td>{len(target['files'])}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Name</th><th>Title</th><th>Organisation</th>"
        "<th>Must / nice</th><th>Tailored</th><th>Verify</th><th>Files</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _home_html(
    summary: dict[str, Any],
    ok: str | None,
    error: str | None,
    token_suffix: str,
) -> str:
    esc = html_lib.escape
    profile = summary["profile"]
    if profile.get("present"):
        status = "valid" if profile.get("valid") else f"invalid: {profile.get('error')}"
        profile_text = (
            f"Present and {status}. {esc(str(profile.get('name') or ''))} — "
            f"{esc(str(profile.get('label') or ''))}"
        )
    else:
        profile_text = "Not built yet. Ingest sources, then build the profile."
    source_rows = "".join(
        f"<tr><td>{esc(str(s['source']))}</td><td>{esc(str(s['kind']))}</td>"
        f"<td>{s['spans']}</td><td>{'yes' if s['profile_candidate'] else 'no'}</td></tr>"
        for s in summary["sources"]
    )
    sources_table = (
        "<table><thead><tr><th>Source</th><th>Kind</th><th>Spans</th>"
        "<th>Profile candidate</th></tr></thead><tbody>"
        + source_rows
        + "</tbody></table>"
        if source_rows
        else "<p class='muted'>No sources yet.</p>"
    )
    framework_rows = "".join(
        f"<tr><td>{esc(str(f['name']))}</td><td>{esc(str(f['kind']))}</td>"
        f"<td>{f.get('codes', f['skills'])} codes ({f.get('level_rows', 0)} level rows)</td>"
        f"<td>{f.get('confirmed_levels', 0)}</td>"
        f"<td>{esc(str(f.get('source_file') or ''))}</td></tr>"
        for f in summary.get("frameworks", [])
    )
    framework_rows = (
        "<table><thead><tr><th>Name</th><th>Kind</th><th>Skills</th><th>Confirmed levels</th><th>Source</th></tr></thead><tbody>"
        + framework_rows
        + "</tbody></table>"
        if framework_rows
        else "<p class='muted'>No frameworks yet.</p>"
    )
    token_field = ""
    body = f"""
<h1>Project review</h1>
<p class="muted">Project: <code>{esc(summary["project"])}</code> · Sartor {esc(summary["version"])}</p>
<section class="panel"><h2>Provider</h2>
<p>{esc(str(summary["config"].get("provider") or "not configured"))} · model: {esc(str(summary["config"].get("model") or "unset"))}<br>
<span class="muted">Base URL: {esc(str(summary["config"].get("base_url") or ""))} · key configured: {"yes" if summary["config"]["api_key_set"] else "no"} · theme: {esc(str(summary["config"]["theme"]))}</span></p></section>
<section class="panel"><h2>Profile</h2><p>{profile_text}</p>
<p><a href="/profile{token_suffix}">Review profile</a></p>
<div class="actions"><form method="post" action="/actions/profile/build{token_suffix}">
<label class="check"><input type="checkbox" name="force" value="true"> replace existing profile</label>
<button type="submit">Build profile</button></form>
<form method="post" action="/actions/profile/check{token_suffix}"><button class="secondary" type="submit">Check profile</button></form></div></section>
<section class="panel"><h2>Sources</h2>{sources_table}
<form method="post" action="/actions/ingest{token_suffix}" enctype="multipart/form-data">
<label for="files">Add source files ({esc(", ".join(SUPPORTED_SUFFIXES))})</label>
<input id="files" type="file" name="files" multiple required>
<button type="submit">Ingest sources</button></form></section>
<section class="panel"><h2>Frameworks</h2>
<p class="muted">Framework data is user-supplied (CSV/JSON with code,name columns; a code may repeat at different levels); nothing is bundled or fetched.</p>
{framework_rows}
<form method="post" action="/actions/frameworks{token_suffix}" enctype="multipart/form-data">
<label for="fw-name">Framework name</label><input id="fw-name" type="text" name="name" required pattern="[A-Za-z0-9][A-Za-z0-9._-]*">
<label for="fw-kind">Kind</label><select id="fw-kind" name="kind">
<option value="sfia">sfia</option><option value="onet">onet</option><option value="esco">esco</option>
<option value="aqf">aqf</option><option value="custom" selected>custom</option></select>
<label for="fw-file">Framework file (.csv or .json)</label>
<input id="fw-file" type="file" name="file" accept=".csv,.json" required>
<label class="check"><input type="checkbox" name="force" value="true"> replace existing framework</label>
<button type="submit">Add framework</button></form></section>
<section class="panel"><h2>Targets</h2>{_target_rows(summary, token_suffix)}
<form method="post" action="/actions/targets{token_suffix}">
<label for="target-name">New target name</label><input id="target-name" type="text" name="name" required pattern="[A-Za-z0-9][A-Za-z0-9._-]*">
<label for="ad-text">Paste job advertisement</label><textarea id="ad-text" name="ad_text" required></textarea>
<label class="check"><input type="checkbox" name="force" value="true"> replace existing target</label>
<button type="submit">Parse job ad</button></form></section>
{token_field}"""
    return _page("Project review", body, ok, error, token_suffix)


def _profile_html(
    summary: dict[str, Any],
    profile: dict[str, Any] | None,
    ok: str | None,
    error: str | None,
    token_suffix: str,
) -> str:
    if profile is None:
        body = """
<h1>Profile</h1><section class="panel"><p>No profile yet.</p>
<form method="post" action="/actions/profile/build">
<button type="submit">Build profile from sources</button></form></section>"""
        if token_suffix:
            body = body.replace(
                "/actions/profile/build", "/actions/profile/build" + token_suffix
            )
        return _page("Profile", body, ok, error, token_suffix)
    details = json.dumps(profile, indent=2, ensure_ascii=False)
    status = summary["profile"]
    body = f"""
<h1>Profile review</h1>
<p class="muted">Status: {"valid" if status.get("valid") else "invalid"}.
This page is read-only; edit <code>profile.json</code> in your editor, then run Check profile.</p>
<section class="panel"><h2>{html_lib.escape(str(status.get("name") or "Profile"))}</h2>
<p>{html_lib.escape(str(status.get("label") or ""))}</p>
<div class="actions"><form method="post" action="/actions/profile/check{token_suffix}">
<button type="submit">Check profile</button></form></div>
<pre>{html_lib.escape(details)}</pre></section>"""
    return _page("Profile", body, ok, error, token_suffix)


def _target_html(
    name: str,
    detail: dict[str, Any],
    summary: dict[str, Any],
    ok: str | None,
    error: str | None,
    token_suffix: str,
) -> str:
    esc = html_lib.escape
    target = detail["target"]
    title = str(target.get("title") or name)
    requirements = []
    for key, label in (
        ("must_haves", "Must-haves"),
        ("nice_to_haves", "Nice-to-haves"),
        ("selection_criteria", "Selection criteria"),
    ):
        items = target.get(key) or []
        if not items:
            continue
        req_rows = "".join(
            f"<tr><td>{esc(str(item.get('text', '')))}</td>"
            f"<td class='evidence'>{esc(str(item.get('quote', '')))}</td></tr>"
            for item in items
            if isinstance(item, dict)
        )
        requirements.append(
            f"<h3>{label}</h3><table><thead><tr><th>Requirement</th>"
            f"<th>Advertisement text</th></tr></thead><tbody>{req_rows}</tbody></table>"
        )
    bullets = []
    for bullet in detail["bullets"]:
        verdict = str(bullet.get("verdict") or "not checked")
        flagged = " <span class='flag'>flagged</span>" if bullet.get("flagged") else ""
        evidence = ", ".join(str(e) for e in bullet.get("evidence", []))
        reasons = "; ".join(str(r) for r in bullet.get("reasons", []))
        bullets.append(
            "<tr>"
            f"<td><span class='verdict {esc(verdict)}'>{esc(verdict)}</span>{flagged}</td>"
            f"<td>{esc(str(bullet.get('text', '')))}"
            f"<div class='evidence'>{esc(evidence)}</div>"
            f"<div class='small muted'>{esc(reasons)}</div></td></tr>"
        )
    bullet_table = (
        "<table><thead><tr><th>Verdict</th><th>Bullet and evidence</th></tr></thead>"
        "<tbody>" + "".join(bullets) + "</tbody></table>"
        if bullets
        else "<p class='muted'>Not tailored yet.</p>"
    )
    coverage_rows = []
    coverage = detail.get("coverage") or {}
    for key in ("must_haves", "nice_to_haves", "selection_criteria"):
        for row in (coverage.get("requirements") or {}).get(key, []) or []:
            status = str(row.get("status", ""))
            css = {"evidenced": "supported", "weak": "weak", "gap": "unsupported"}.get(
                status, ""
            )
            coverage_rows.append(
                f"<tr><td>{esc(str(row.get('requirement', '')))}</td>"
                f"<td><span class='verdict {css}'>{esc(status)}</span></td>"
                f"<td class='evidence'>{esc(str(row.get('bullet') or '—'))}</td></tr>"
            )
    coverage_html = (
        "<table><thead><tr><th>Requirement</th><th>Status</th><th>Bullet</th>"
        "</tr></thead><tbody>" + "".join(coverage_rows) + "</tbody></table>"
        if coverage_rows
        else "<p class='muted'>No coverage report yet.</p>"
    )
    files = "".join(
        f"<tr><td><a href='/targets/{quote(name)}/files/{quote(str(f['name']))}{token_suffix}' download>{esc(str(f['name']))}</a></td>"
        f"<td>{int(f['bytes'])} bytes</td></tr>"
        for f in detail["files"]
    )
    files_html = (
        "<table><thead><tr><th>File</th><th>Size</th></tr></thead><tbody>"
        + files
        + "</tbody></table>"
        if files
        else "<p class='muted'>No bundle files yet. Run Render.</p>"
    )
    counts = detail.get("verify_counts") or {}
    verify_text = (
        ", ".join(f"{k} {v}" for k, v in counts.items()) if counts else "not verified"
    )
    default_theme = summary["config"].get("theme") or "ats-plain"
    framework_blocks: list[str] = []
    for mapping in detail.get("frameworks", []) or []:
        framework_name = str(mapping.get("framework") or "")
        row_bits: list[str] = []
        for row in mapping.get("skills", []) or []:
            if row.get("confirmed_level") is not None:
                level_text = f"confirmed {row.get('confirmed_level')}"
            elif row.get("suggested_level") is not None:
                level_text = (
                    f"suggested {row.get('suggested_level')} (not confirmed)"
                )
            else:
                level_text = "none"
            level_values: list[Any] = []
            for level_row in row.get("levels", []) or []:
                value = (
                    level_row.get("level")
                    if isinstance(level_row, dict)
                    else None
                )
                if value is not None and value not in level_values:
                    level_values.append(value)
            if not level_values and row.get("level") is not None:
                level_values = [row.get("level")]
            selected_level = row.get("confirmed_level")
            if selected_level is None:
                selected_level = row.get("suggested_level")
            if level_values:
                options = "".join(
                    f'<option value="{esc(str(value))}"'
                    f'{" selected" if str(value) == str(selected_level) else ""}>'
                    f"{esc(str(value))}</option>"
                    for value in level_values
                )
                confirm_html = (
                    f"<form method='post' action='/targets/{quote(name)}"
                    f"/actions/framework-confirm{token_suffix}'>"
                    f"<input type='hidden' name='framework' value='{esc(framework_name)}'>"
                    f"<input type='hidden' name='code' value='{esc(str(row.get('code')))}'>"
                    f"<select name='level' aria-label='Level for {esc(str(row.get('code')))}'>"
                    f"{options}</select> "
                    "<button class='secondary' type='submit'>Confirm</button></form>"
                )
            else:
                confirm_html = "<span class='muted'>No level rows</span>"
            row_bits.append(
                f"<tr><td>{esc(str(row.get('code')))}</td>"
                f"<td>{esc(str(row.get('name')))}</td>"
                f"<td><span class='verdict {'supported' if row.get('profile_status') == 'evidenced' else ('weak' if row.get('profile_status') == 'weak' else 'unsupported')}'>{esc(str(row.get('profile_status')))}</span></td>"
                f"<td><span class='verdict {'supported' if row.get('alignment') == 'matched' else ('weak' if row.get('alignment') == 'profile_only' else 'unsupported')}'>{esc(str(row.get('alignment')))}</span></td>"
                f"<td>{esc(level_text)}</td><td>{confirm_html}</td></tr>"
            )
        framework_blocks.append(
            f"<h3>{esc(framework_name)} ({esc(str(mapping.get('kind')))})</h3>"
            "<table><thead><tr><th>Code</th><th>Skill</th><th>Profile</th>"
            "<th>Alignment</th><th>Internal level</th><th>Confirm level</th>"
            "</tr></thead><tbody>"
            + "".join(row_bits)
            + "</tbody></table>"
        )
    frameworks_html = (
        "".join(framework_blocks) or "<p class='muted'>Not mapped yet.</p>"
    )
    available = summary.get("frameworks", []) or []
    framework_options = (
        "".join(
            f'<option value="{esc(str(item.get("name")))}">{esc(str(item.get("name")))}</option>'
            for item in available
        )
        or '<option value="">(add a framework first)</option>'
    )
    tailor_framework_options = '<option value="">(none)</option>' + "".join(
        f'<option value="{esc(str(item.get("name")))}">{esc(str(item.get("name")))}</option>'
        for item in available
    )
    statement_blocks: list[str] = []
    for statement in detail.get("framework_statements", []) or []:
        counts = statement.get("counts") or {}
        bits = [
            f"<h3>{esc(str(statement.get('framework')))} "
            f"({esc(str(statement.get('kind')))})</h3>",
            (
                f"<p class='muted'>Display {esc(str(statement.get('display')))} · "
                f"{counts.get('statements', 0)} statements · source "
                f"{esc(str(statement.get('bullet_source')))}.</p>"
            ),
        ]
        for row in statement.get("skills", []) or []:
            statements = row.get("statements", []) or []
            if not statements:
                continue
            if statement.get("display") != "none":
                heading = f"{row.get('code')} — {row.get('name')}"
                if (
                    statement.get("display") == "code-level"
                    and row.get("display_level") is not None
                ):
                    if row.get("level_status") == "confirmed":
                        heading += f" — Level {row.get('display_level')} (confirmed by you)"
                    else:
                        heading += (
                            f" — Suggested level {row.get('display_level')} "
                            "(not confirmed)"
                        )
                bits.append(f"<h4>{esc(heading)}</h4>")
            bits.append("<ul>")
            for item in statements:
                evidence = ", ".join(
                    str(value) for value in item.get("evidence", []) or []
                )
                bits.append(
                    f"<li>{esc(str(item.get('text') or ''))}"
                    f"<br><span class='evidence'>{esc(evidence)}</span></li>"
                )
            bits.append("</ul>")
        statement_blocks.append("".join(bits))
    statements_html = (
        "".join(statement_blocks) or "<p class='muted'>No framework statement yet.</p>"
    )
    research = detail.get("research") or {}
    research_bits: list[str] = []
    for block in research.get("queries", []) or []:
        research_bits.append(f"<h3>{esc(str(block.get('query')))}</h3><ul>")
        for result in block.get("results", []) or []:
            research_bits.append(
                f"<li><a href='{esc(str(result.get('url')))}' rel='noreferrer'>{esc(str(result.get('title')))}</a> — {esc(str(result.get('snippet') or ''))}</li>"
            )
        research_bits.append("</ul>")
    research_html = "".join(research_bits) or "<p class='muted'>No research yet.</p>"
    detail = {
        **detail,
        "_search_enabled": bool(summary["config"].get("search_enabled")),
    }
    body = f"""
<h1>{esc(title)}</h1>
<p class="muted">Target <code>{esc(name)}</code> · {esc(str(target.get("organisation") or ""))} · verify: {esc(verify_text)}</p>
<section class="panel"><h2>Run pipeline</h2><div class="actions">
<form method="post" action="/targets/{quote(name)}/actions/tailor{token_suffix}">
<label>Voice <select name="voice"><option value="standard" selected>standard</option><option value="framework">framework (voice-only, no level)</option></select></label>
<label>Framework <select name="framework">{tailor_framework_options}</select></label>
<button type="submit">Tailor</button></form>
<form method="post" action="/targets/{quote(name)}/actions/verify{token_suffix}">
<label class="check"><input type="checkbox" name="strict" value="true"> strict</label>
<label class="check"><input type="checkbox" name="llm" value="true"> entailment</label>
<button type="submit">Verify</button></form>
<form method="post" action="/targets/{quote(name)}/actions/report{token_suffix}"><button type="submit">Report</button></form>
<form method="post" action="/targets/{quote(name)}/actions/render{token_suffix}">
<label>Theme <select name="theme">
<option value="ats-plain"{" selected" if default_theme == "ats-plain" else ""}>ats-plain</option>
<option value="modern"{" selected" if default_theme == "modern" else ""}>modern</option>
<option value="academic"{" selected" if default_theme == "academic" else ""}>academic</option>
</select></label><button type="submit">Render bundle</button></form>
</div></section>
<section class="panel"><h2>Requirements</h2>{"".join(requirements)}</section>
<section class="panel"><h2>Tailored bullets</h2>{bullet_table}</section>
<section class="panel"><h2>Coverage</h2>{coverage_html}</section>
<section class="panel"><h2>Frameworks</h2>
<p class="muted">Internal only: a suggested level comes from descriptor-specific evidence and is not a formal assessment. Resumes use framework voice only and print no level.</p>
{frameworks_html}
<form method="post" action="/targets/{quote(name)}/actions/framework{token_suffix}">
<label>Map to framework <select name="framework">{framework_options}</select></label>
<button type="submit">Map framework</button></form>
<form method="post" action="/targets/{quote(name)}/actions/framework-statement{token_suffix}">
<label>Statement framework <select name="framework">{framework_options}</select></label>
<label>Display <select name="display"><option value="none">none (evidence only)</option><option value="code" selected>code (no level)</option><option value="code-level">code-level</option></select></label>
<button type="submit">Build framework statement</button></form></section>
<section class="panel"><h2>Framework statements</h2>{statements_html}</section>
<section class="panel"><h2>Research (grounding)</h2>
<p class="muted">Context only — never evidence for a resume claim. Provider: {esc(str(summary["config"].get("search_provider")))}; search enabled: {"yes" if detail.get("_search_enabled") else "no"}.</p>
{research_html}
<form method="post" action="/targets/{quote(name)}/actions/research{token_suffix}">
<label class="check"><input type="checkbox" name="enable_search" value="true"> enable search for this run (opt-in)</label>
<button type="submit">Run research</button></form></section>
<section class="panel"><h2>Download bundle</h2>{files_html}</section>"""
    return _page(f"Target {name}", body, ok, error, token_suffix)


def create_app(
    project: Path,
    config: dict[str, Any] | None = None,
    provider: Any = None,
    token: str | None = None,
):
    """Build the FastAPI app. ``provider`` is injectable for tests."""
    try:
        from fastapi import (
            Depends,
            FastAPI,
            File,
            Form,
            Header,
            HTTPException,
            Request,
            UploadFile,
        )
        from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

        # FastAPI resolves endpoint annotations via module globals.
        globals().update(
            Request=Request,
            UploadFile=UploadFile,
            RedirectResponse=RedirectResponse,
            FileResponse=FileResponse,
        )
    except ImportError as exc:
        raise RuntimeError('Serve needs FastAPI: pip install "sartor[serve]"') from exc

    project = project.resolve()
    active_config = dict(config) if config is not None else load_config(start=project)
    auth_token = token or os.environ.get("SARTOR_SERVE_TOKEN") or ""

    def provider_now() -> Any:
        return provider if provider is not None else get_provider(active_config)

    async def guard(
        request: Request, x_sartor_token: str | None = Header(default=None)
    ) -> None:
        if not auth_token:
            return
        supplied = x_sartor_token or request.query_params.get("token")
        if supplied != auth_token:
            raise HTTPException(status_code=401, detail="missing or invalid token")

    def suffix(request: Request) -> str:
        if auth_token and request.query_params.get("token"):
            return "?token=" + quote(str(request.query_params["token"]))
        return ""

    def redirect(
        path: str, request: Request, ok: str | None = None, error: str | None = None
    ) -> RedirectResponse:
        params: list[str] = []
        if ok:
            params.append("ok=" + quote(ok))
        if error:
            params.append("error=" + quote(error))
        if auth_token and request.query_params.get("token"):
            params.append("token=" + quote(str(request.query_params["token"])))
        location = path + ("?" + "&".join(params) if params else "")
        return RedirectResponse(location, status_code=303)

    app = FastAPI(title="Sartor", version=__version__)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    @app.get("/api/project", dependencies=[Depends(guard)])
    def api_project() -> dict[str, Any]:
        return project_summary(project, active_config)

    @app.get("/api/targets/{name}", dependencies=[Depends(guard)])
    def api_target(name: str) -> dict[str, Any]:
        detail = target_detail(project, name)
        if detail is None:
            raise HTTPException(status_code=404, detail="target not found")
        return detail

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(guard)])
    def home(request: Request, ok: str | None = None, error: str | None = None) -> str:
        return _home_html(
            project_summary(project, active_config), ok, error, suffix(request)
        )

    @app.get("/profile", response_class=HTMLResponse, dependencies=[Depends(guard)])
    def profile_page(
        request: Request, ok: str | None = None, error: str | None = None
    ) -> str:
        return _profile_html(
            project_summary(project, active_config),
            _read_json(project / "profile.json"),
            ok,
            error,
            suffix(request),
        )

    @app.get(
        "/targets/{name}", response_class=HTMLResponse, dependencies=[Depends(guard)]
    )
    def target_page(
        name: str, request: Request, ok: str | None = None, error: str | None = None
    ) -> str:
        try:
            detail = target_detail(project, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if detail is None:
            raise HTTPException(status_code=404, detail="target not found")
        return _target_html(
            name,
            detail,
            project_summary(project, active_config),
            ok,
            error,
            suffix(request),
        )

    @app.get("/targets/{name}/files/{filename}", dependencies=[Depends(guard)])
    def download(name: str, filename: str) -> FileResponse:
        try:
            safe_target_name(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        media = download_media_type(filename)
        if media is None:
            raise HTTPException(status_code=404, detail="file not available")
        path = project / "exports" / name / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(str(path), media_type=media, filename=filename)

    @app.post("/actions/ingest", dependencies=[Depends(guard)])
    async def action_ingest(
        request: Request, files: list[UploadFile] = File(...)
    ) -> RedirectResponse:
        from sartor.ingest import IngestError, ingest_file, span_count

        upload_dir = project / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        done: list[str] = []
        failures: list[str] = []
        for upload in files:
            filename = Path(upload.filename or "").name
            if not filename:
                failures.append("unnamed upload skipped")
                continue
            data = await upload.read()
            if len(data) > MAX_UPLOAD_BYTES:
                failures.append(f"{filename}: larger than 25 MB")
                continue
            saved = upload_dir / filename
            saved.write_bytes(data)
            try:
                out = ingest_file(saved, project)
                done.append(f"{filename}: {span_count(out)} spans")
            except IngestError as exc:
                failures.append(str(exc))
        if failures:
            return redirect("/", request, error="; ".join([*done, *failures]))
        return redirect("/", request, ok="Ingested " + ", ".join(done))

    @app.post("/actions/profile/check", dependencies=[Depends(guard)])
    def action_profile_check(request: Request) -> RedirectResponse:
        from sartor.profile import check_profile

        try:
            check_profile(project)
        except Exception as exc:
            return redirect("/profile", request, error=str(exc))
        return redirect("/profile", request, ok="profile.json: ok")

    @app.post("/actions/profile/build", dependencies=[Depends(guard)])
    def action_profile_build(
        request: Request, force: bool = Form(False)
    ) -> RedirectResponse:
        from sartor.profile import ProfileError, build_profile

        try:
            out = build_profile(project, provider_now(), force=force)
        except ProfileError as exc:
            return redirect("/profile", request, error=str(exc))
        except Exception as exc:
            return redirect("/profile", request, error=str(exc))
        return redirect(
            "/profile", request, ok=f"Wrote {out.name}; review it, then Check profile."
        )

    @app.post("/actions/targets", dependencies=[Depends(guard)])
    def action_target_add(
        request: Request,
        name: str = Form(...),
        ad_text: str = Form(...),
        force: bool = Form(False),
    ) -> RedirectResponse:
        from sartor.target import TargetError, add_target

        try:
            add_target(
                project,
                name,
                ad_text,
                provider_now(),
                force=force,
                source_label="pasted advertisement",
            )
        except (TargetError, Exception) as exc:  # provider errors land here too
            return redirect("/", request, error=str(exc))
        return redirect(f"/targets/{quote(name)}", request, ok=f"Target {name} parsed.")

    def _action_redirect(
        name: str, request: Request, work: Any, ok: str
    ) -> RedirectResponse:
        try:
            work()
        except Exception as exc:
            return redirect(f"/targets/{quote(name)}", request, error=str(exc))
        return redirect(f"/targets/{quote(name)}", request, ok=ok)

    @app.post("/targets/{name}/actions/tailor", dependencies=[Depends(guard)])
    def action_tailor(
        name: str,
        request: Request,
        voice: str = Form("standard"),
        framework: str = Form(""),
    ) -> RedirectResponse:
        from sartor.tailor import tailor_resume

        return _action_redirect(
            name,
            request,
            lambda: tailor_resume(
                project,
                name,
                provider_now(),
                framework_name=framework or None,
                voice=voice or "standard",
            ),
            "Tailoring complete. Run Verify next.",
        )

    @app.post("/targets/{name}/actions/verify", dependencies=[Depends(guard)])
    def action_verify(
        name: str, request: Request, strict: bool = Form(False), llm: bool = Form(False)
    ) -> RedirectResponse:
        import json as _json

        from sartor.verify import verify_resume

        path_holder: list[Path] = []

        def run() -> None:
            path_holder.append(
                verify_resume(
                    project,
                    name,
                    strict=strict,
                    llm=llm,
                    provider=provider_now() if llm else None,
                )
            )

        response = _action_redirect(name, request, run, "Verification complete.")
        if path_holder:
            counts = _json.loads(path_holder[0].read_text(encoding="utf-8"))["counts"]
            message = "Verified: " + ", ".join(f"{k} {v}" for k, v in counts.items())
            return redirect(f"/targets/{quote(name)}", request, ok=message)
        return response

    @app.post("/targets/{name}/actions/report", dependencies=[Depends(guard)])
    def action_report(name: str, request: Request) -> RedirectResponse:
        from sartor.report import build_report

        return _action_redirect(
            name,
            request,
            lambda: build_report(project, name),
            "Coverage report written.",
        )

    @app.post("/targets/{name}/actions/render", dependencies=[Depends(guard)])
    def action_render(
        name: str, request: Request, theme: str = Form("ats-plain")
    ) -> RedirectResponse:
        from sartor.render import RenderError, render_bundle

        try:
            written = render_bundle(project, name, theme=theme)
        except RenderError as exc:
            names = ", ".join(path.name for path in exc.written)
            return redirect(
                f"/targets/{quote(name)}",
                request,
                error=f"{exc} Written: {names}" if names else str(exc),
            )
        return redirect(
            f"/targets/{quote(name)}",
            request,
            ok="Rendered: " + ", ".join(path.name for path in written),
        )

    @app.post("/actions/frameworks", dependencies=[Depends(guard)])
    async def action_framework_add(
        request: Request,
        name: str = Form(...),
        kind: str = Form("custom"),
        file: UploadFile = File(...),
        force: bool = Form(False),
    ) -> RedirectResponse:
        from sartor.frameworks import FrameworkError, add_framework

        filename = Path(file.filename or "").name
        if not filename:
            return redirect("/", request, error="Framework upload needs a file")
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            return redirect("/", request, error=f"{filename}: larger than 25 MB")
        upload_dir = project / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved = upload_dir / filename
        saved.write_bytes(data)
        try:
            add_framework(project, saved, name, kind, force=force)
        except FrameworkError as exc:
            return redirect("/", request, error=str(exc))
        except Exception as exc:
            return redirect("/", request, error=str(exc))
        return redirect("/", request, ok=f"Framework {name} added.")

    @app.post("/targets/{name}/actions/framework", dependencies=[Depends(guard)])
    def action_framework_map(
        name: str, request: Request, framework: str = Form("")
    ) -> RedirectResponse:
        from sartor.frameworks import map_framework

        if not framework:
            return redirect(
                f"/targets/{quote(name)}",
                request,
                error="Add a framework first (home page).",
            )
        return _action_redirect(
            name,
            request,
            lambda: map_framework(project, name, framework),
            f"Mapped to {framework}.",
        )

    @app.post(
        "/targets/{name}/actions/framework-confirm", dependencies=[Depends(guard)]
    )
    def action_framework_confirm(
        name: str,
        request: Request,
        framework: str = Form(""),
        code: str = Form(""),
        level: str = Form(""),
    ) -> RedirectResponse:
        from sartor.frameworks import (
            confirm_framework_level,
            load_framework_statement,
            map_framework,
            write_framework_statement,
        )

        if not framework or not code or not level:
            return redirect(
                f"/targets/{quote(name)}",
                request,
                error="Choose a framework, code, and level to confirm.",
            )

        def run() -> None:
            confirm_framework_level(project, framework, code, level)
            map_framework(project, name, framework)
            existing = load_framework_statement(project, name, framework)
            if existing is not None:
                write_framework_statement(
                    project,
                    name,
                    framework,
                    display=str(existing.get("display") or "code"),
                )

        return _action_redirect(
            name,
            request,
            run,
            f"Confirmed {code} at level {level} in {framework}.",
        )

    @app.post(
        "/targets/{name}/actions/framework-statement", dependencies=[Depends(guard)]
    )
    def action_framework_statement(
        name: str,
        request: Request,
        framework: str = Form(""),
        display: str = Form("code"),
    ) -> RedirectResponse:
        from sartor.frameworks import write_framework_statement

        if not framework:
            return redirect(
                f"/targets/{quote(name)}",
                request,
                error="Add a framework first (home page).",
            )
        return _action_redirect(
            name,
            request,
            lambda: write_framework_statement(
                project, name, framework, display=display or "code"
            ),
            f"Framework statement written for {framework} (display {display}).",
        )

    @app.post("/targets/{name}/actions/research", dependencies=[Depends(guard)])
    def action_research(
        name: str, request: Request, enable_search: bool = Form(False)
    ) -> RedirectResponse:
        from sartor.search import SearchError, research_target

        try:
            research_target(project, name, active_config, enabled=enable_search)
        except SearchError as exc:
            return redirect(f"/targets/{quote(name)}", request, error=str(exc))
        except Exception as exc:
            return redirect(f"/targets/{quote(name)}", request, error=str(exc))
        return redirect(
            f"/targets/{quote(name)}", request, ok="Research written (context only)."
        )

    return app


def serve(
    project: Path, host: str = "127.0.0.1", port: int = 5384, token: str | None = None
) -> None:
    """Run the local UI. Refuses non-loopback binds without a token."""
    if host not in _LOCAL_HOSTS and not (token or os.environ.get("SARTOR_SERVE_TOKEN")):
        raise RuntimeError(
            "Refusing to bind beyond localhost without a token: set "
            "SARTOR_SERVE_TOKEN or keep --host 127.0.0.1"
        )
    config = load_config(start=project)
    app = create_app(project, config=config, token=token)
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError('Serve needs uvicorn: pip install "sartor[serve]"') from exc

    uvicorn.run(app, host=host, port=port)
