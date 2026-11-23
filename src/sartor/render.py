"""Rendering: one tailored model, five files (S-009).

``resume.md``, ``resume.html``, ``resume.pdf`` (WeasyPrint from the
HTML, so the two never diverge), ``resume.docx`` (python-docx) and
``resume.json`` (plain JSON Resume: internal bullet objects flatten
to strings, evidence moves under ``meta.sartor.bullet_evidence``).

Themes (S-010): ``ats-plain`` (default, ATS-parseable), ``modern``
and ``academic`` change HTML/PDF presentation only — Markdown and
JSON outputs are theme-invariant. Flagged bullets (S-007) carry an
HTML-comment marker in Markdown only and are omitted from the
``pitch.md``/``deck.md`` handoffs (S-011). Every bundle ends with a
``manifest.json`` describing its inputs and outputs (S-012).

If WeasyPrint or python-docx is unavailable, the formats that can be
rendered are written first; ``RenderError.written`` lists them and
the CLI exits 1 naming the install fix.
"""

from __future__ import annotations

import copy
import hashlib
import html as html_lib
import json
from pathlib import Path
from typing import Any

from sartor import __version__
from sartor.config import load_config
from sartor.profile import validate_profile
from sartor.tailor import BULLET_SECTIONS, TailorError, load_tailored

THEMES = ("ats-plain", "modern", "academic")

_CSS_ATS_PLAIN = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt;
  line-height: 1.45; color: #111; margin: 2.2cm; }
h1 { font-size: 20pt; margin: 0 0 2pt 0; }
h2 { font-size: 12pt; text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid #999; padding-bottom: 2pt; margin: 16pt 0 6pt 0; }
h3 { font-size: 11pt; margin: 10pt 0 2pt 0; }
p { margin: 3pt 0; }
ul { margin: 3pt 0 6pt 0; padding-left: 16pt; }
li { margin: 2pt 0; }
.label { font-size: 12pt; color: #333; margin: 0 0 6pt 0; }
.contact { color: #333; font-size: 10pt; }
.dates { color: #444; font-size: 10pt; }
"""

_CSS_MODERN = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt;
  line-height: 1.5; color: #1a2332; margin: 2cm 2.2cm;
  border-top: 6pt solid #2563eb; padding-top: 14pt; }
h1 { font-size: 22pt; margin: 0 0 2pt 0; color: #1e3a5f; }
h2 { font-size: 11pt; text-transform: uppercase; letter-spacing: 0.12em;
  color: #2563eb; margin: 18pt 0 6pt 0; }
h3 { font-size: 11pt; margin: 10pt 0 2pt 0; color: #1e3a5f; }
p { margin: 3pt 0; }
ul { margin: 3pt 0 6pt 0; padding-left: 15pt; }
li { margin: 2pt 0; }
.label { font-size: 12pt; color: #2563eb; margin: 0 0 6pt 0; }
.contact { color: #475569; font-size: 10pt; }
.dates { color: #64748b; font-size: 9.5pt; font-weight: normal; }
"""

_CSS_ACADEMIC = """
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt;
  line-height: 1.55; color: #111; margin: 2.5cm; }
h1 { font-size: 20pt; text-align: center; margin: 0 0 4pt 0; font-weight: normal; }
h2 { font-size: 12pt; text-align: center; text-transform: uppercase;
  letter-spacing: 0.14em; margin: 20pt 0 8pt 0; font-weight: normal; }
h3 { font-size: 11pt; margin: 12pt 0 2pt 0; font-style: italic; font-weight: normal; }
p { margin: 4pt 0; text-align: justify; }
ul { margin: 4pt 0 8pt 0; padding-left: 18pt; }
li { margin: 3pt 0; text-align: justify; }
.label { font-size: 12pt; text-align: center; color: #333; margin: 0 0 4pt 0; }
.contact { text-align: center; color: #333; font-size: 10pt; }
.dates { color: #444; font-size: 10pt; font-style: normal; }
"""

_THEME_CSS = {
    "ats-plain": _CSS_ATS_PLAIN,
    "modern": _CSS_MODERN,
    "academic": _CSS_ACADEMIC,
}


def require_theme(theme: str) -> str:
    if theme not in THEMES:
        raise RenderError(
            f"Unknown theme {theme!r}; expected one of: {', '.join(THEMES)}"
        )
    return theme


class RenderError(Exception):
    """Raised when a format cannot be rendered."""

    def __init__(self, message: str, written: list[Path] | None = None):
        super().__init__(message)
        self.written = written or []


def _bullet_text(bullet: Any) -> str:
    if isinstance(bullet, dict):
        return str(bullet.get("text", ""))
    return str(bullet)


def _is_flagged(bullet: Any) -> bool:
    return isinstance(bullet, dict) and bool(bullet.get("flagged"))


def to_json_resume(tailored: dict[str, Any]) -> dict[str, Any]:
    """Flatten internal bullet objects to valid JSON Resume."""
    plain = copy.deepcopy(tailored)
    evidence_map: dict[str, list[str]] = {}
    flagged: list[str] = []
    for section in BULLET_SECTIONS:
        for e_index, entry in enumerate(plain.get(section, []) or []):
            if not isinstance(entry, dict):
                continue
            texts: list[str] = []
            for b_index, bullet in enumerate(entry.get("highlights", []) or []):
                path = f"{section}[{e_index}].highlights[{b_index}]"
                if isinstance(bullet, dict):
                    if bullet.get("evidence"):
                        evidence_map[path] = [str(e) for e in bullet["evidence"]]
                    if bullet.get("flagged"):
                        flagged.append(path)
                texts.append(_bullet_text(bullet))
            entry["highlights"] = texts
    meta = dict(plain.get("meta") or {})
    sartor_meta = dict(meta.get("sartor") or {})
    sartor_meta["bullet_evidence"] = evidence_map
    if flagged:
        sartor_meta["flagged"] = flagged
    meta["sartor"] = sartor_meta
    plain["meta"] = meta
    return plain


def _dates(entry: dict[str, Any]) -> str:
    start = str(entry.get("startDate", "")).strip()
    end = str(entry.get("endDate", "")).strip()
    if start and end:
        return f"{start} to {end}"
    if start:
        return f"{start} to present"
    if end:
        return end
    return str(entry.get("date") or entry.get("releaseDate") or "").strip()


def _entry_title(entry: dict[str, Any]) -> str:
    parts = [
        str(entry.get(key, "")).strip()
        for key in ("position", "name", "title", "institution", "publisher")
    ]
    parts = [p for p in parts if p]
    area = str(entry.get("area", "")).strip()
    study = str(entry.get("studyType", "")).strip()
    if study or area:
        parts.append(", ".join(p for p in (study, area) if p))
    return ", ".join(dict.fromkeys(parts))


_SECTION_TITLES = (
    ("work", "Experience"),
    ("education", "Education"),
    ("skills", "Skills"),
    ("projects", "Projects"),
    ("publications", "Publications"),
    ("volunteer", "Volunteering"),
    ("certificates", "Certificates"),
    ("awards", "Awards"),
    ("languages", "Languages"),
    ("interests", "Interests"),
    ("references", "References"),
)


def render_markdown(tailored: dict[str, Any]) -> str:
    basics = tailored.get("basics") or {}
    lines = [f"# {basics.get('name', 'Resume')}", ""]
    if basics.get("label"):
        lines.append(str(basics["label"]))
    contact = [
        str(basics.get(key)) for key in ("email", "phone", "url") if basics.get(key)
    ]
    location = basics.get("location") or {}
    if isinstance(location, dict) and location.get("city"):
        contact.append(str(location["city"]))
    if contact:
        lines.append(" · ".join(contact))
    if basics.get("summary"):
        lines.extend(["", "## Summary", "", str(basics["summary"])])
    for section, title in _SECTION_TITLES:
        entries = tailored.get(section) or []
        if not entries:
            continue
        lines.extend(["", f"## {title}", ""])
        if section == "skills":
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                keywords = ", ".join(str(k) for k in entry.get("keywords", []) or [])
                name = str(entry.get("name", ""))
                lines.append(
                    f"- **{name}**: {keywords}" if keywords else f"- **{name}**"
                )
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            heading = _entry_title(entry) or title
            dates = _dates(entry)
            lines.append(f"### {heading} — {dates}" if dates else f"### {heading}")
            if entry.get("summary") or entry.get("description"):
                lines.append(str(entry.get("summary") or entry.get("description")))
            for bullet in entry.get("highlights", []) or []:
                marker = " <!-- flagged: unsupported -->" if _is_flagged(bullet) else ""
                lines.append(f"- {_bullet_text(bullet)}{marker}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_html(tailored: dict[str, Any], theme: str = "ats-plain") -> str:
    require_theme(theme)
    basics = tailored.get("basics") or {}
    esc = html_lib.escape
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{esc(str(basics.get('name', 'Resume')))} — Resume</title>",
        f"<style>{_THEME_CSS[theme]}</style>",
        "</head>",
        "<body>",
        f"<h1>{esc(str(basics.get('name', 'Resume')))}</h1>",
    ]
    if basics.get("label"):
        out.append(f'<p class="label">{esc(str(basics["label"]))}</p>')
    contact = [
        str(basics.get(key)) for key in ("email", "phone", "url") if basics.get(key)
    ]
    location = basics.get("location") or {}
    if isinstance(location, dict) and location.get("city"):
        contact.append(str(location["city"]))
    if contact:
        out.append(f'<p class="contact">{esc(" · ".join(contact))}</p>')
    if basics.get("summary"):
        out.extend(["<h2>Summary</h2>", f"<p>{esc(str(basics['summary']))}</p>"])
    for section, title in _SECTION_TITLES:
        entries = tailored.get(section) or []
        if not entries:
            continue
        out.append(f"<h2>{title}</h2>")
        if section == "skills":
            out.append("<ul>")
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                keywords = ", ".join(str(k) for k in entry.get("keywords", []) or [])
                name = esc(str(entry.get("name", "")))
                out.append(
                    f"<li><strong>{name}:</strong> {esc(keywords)}</li>"
                    if keywords
                    else f"<li><strong>{name}</strong></li>"
                )
            out.append("</ul>")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            heading = esc(_entry_title(entry) or title)
            dates = _dates(entry)
            if dates:
                out.append(
                    f'<h3>{heading} <span class="dates">— {esc(dates)}</span></h3>'
                )
            else:
                out.append(f"<h3>{heading}</h3>")
            summary = entry.get("summary") or entry.get("description")
            if summary:
                out.append(f"<p>{esc(str(summary))}</p>")
            highlights = entry.get("highlights", []) or []
            if highlights:
                out.append("<ul>")
                for bullet in highlights:
                    out.append(f"<li>{esc(_bullet_text(bullet))}</li>")
                out.append("</ul>")
    out.extend(["</body>", "</html>", ""])
    return "\n".join(out)


def _flagged_count(tailored: dict[str, Any]) -> int:
    total = 0
    for section in BULLET_SECTIONS:
        for entry in tailored.get(section, []) or []:
            if isinstance(entry, dict):
                total += sum(
                    1 for b in entry.get("highlights", []) or [] if _is_flagged(b)
                )
    return total


def _clean_bullets(entry: dict[str, Any]) -> list[str]:
    return [
        _bullet_text(b)
        for b in entry.get("highlights", []) or []
        if not _is_flagged(b) and _bullet_text(b)
    ]


def _first_person(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    if text.startswith(("I ", "I'm", "I've", "My ")):
        return text
    return "I " + text[0].lower() + text[1:]


def render_pitch(tailored: dict[str, Any]) -> str:
    """First-person narrative script for Narra (S-011), flagged-free."""
    basics = tailored.get("basics") or {}
    name = str(basics.get("name", "Resume"))
    label = str(basics.get("label", "")).strip()
    location = basics.get("location") or {}
    city = str(location.get("city", "")).strip() if isinstance(location, dict) else ""
    lines = [
        f"<!-- flagged bullets omitted: {_flagged_count(tailored)} -->",
        f"# Pitch — {name}",
        "",
    ]
    opener = f"Hi, I'm {name}"
    if label:
        opener += f", a {label}"
    if city:
        opener += f" based in {city}"
    lines.append(opener + ".")
    if basics.get("summary"):
        lines.extend(["", str(basics["summary"])])
    for section in ("work", "projects", "volunteer"):
        for entry in tailored.get(section, []) or []:
            if not isinstance(entry, dict):
                continue
            bullets = _clean_bullets(entry)
            if not bullets:
                continue
            org = str(entry.get("name") or entry.get("organization") or "")
            role = str(entry.get("position") or "")
            start = str(entry.get("startDate", "")).strip()
            end = str(entry.get("endDate", "")).strip()
            intro_bits = []
            if start and end:
                intro_bits.append(f"From {start} to {end}")
            elif start:
                intro_bits.append(f"Since {start}")
            if role and org:
                verb = "I worked" if end else "I've worked"
                intro_bits.append(f"{verb} as {role} at {org}")
            elif org:
                intro_bits.append(f"At {org}")
            elif role:
                intro_bits.append(f"As {role}")
            sentences = []
            if intro_bits:
                sentences.append(", ".join(intro_bits) + ".")
            sentences.extend(_first_person(b) for b in bullets)
            lines.extend(["", " ".join(sentences)])
    skills = []
    for entry in tailored.get("skills", []) or []:
        if isinstance(entry, dict) and entry.get("name"):
            keywords = ", ".join(str(k) for k in entry.get("keywords", []) or [])
            skills.append(
                f"{entry['name']} ({keywords})" if keywords else str(entry["name"])
            )
    if skills:
        lines.extend(["", f"My skills include {', '.join(skills)}."])
    lines.extend(["", "That's the experience I bring to this role.", ""])
    return "\n".join(lines)


def render_deck(tailored: dict[str, Any]) -> str:
    """SlideStream deck: each ``#`` heading starts a slide (S-011)."""
    basics = tailored.get("basics") or {}
    name = str(basics.get("name", "Resume"))
    lines = [
        f"<!-- flagged bullets omitted: {_flagged_count(tailored)} -->",
        f"# {name}",
        "",
    ]
    if basics.get("label"):
        lines.append(str(basics["label"]))
    if basics.get("summary"):
        lines.append(str(basics["summary"]))
    for section, title in _SECTION_TITLES:
        entries = tailored.get(section) or []
        if not entries:
            continue
        if section == "skills":
            lines.extend(["", "# Skills", ""])
            for entry in entries:
                if isinstance(entry, dict):
                    keywords = ", ".join(
                        str(k) for k in entry.get("keywords", []) or []
                    )
                    skill = str(entry.get("name", ""))
                    lines.append(f"- {skill}: {keywords}" if keywords else f"- {skill}")
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            bullets = _clean_bullets(entry) if section in BULLET_SECTIONS else []
            heading = _entry_title(entry) or title
            if section in BULLET_SECTIONS and not bullets:
                continue
            lines.extend(["", f"# {heading}", ""])
            dates = _dates(entry)
            if dates:
                lines.append(dates)
            summary = entry.get("summary") or entry.get("description")
            if summary:
                lines.append(str(summary))
            lines.extend(f"- {text}" for text in bullets)
            if section not in BULLET_SECTIONS and not summary and not dates:
                lines.append(f"- {heading}")
    lines.append("")
    return "\n".join(lines)


def _render_pdf(html_text: str, out: Path) -> None:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise RenderError(
            "PDF needs WeasyPrint and its system libraries: "
            'pip install "sartor[pdf]" (macOS also: brew install pango, '
            "and DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib)"
        ) from exc
    HTML(string=html_text).write_pdf(str(out))


def _render_docx(tailored: dict[str, Any], out: Path) -> None:
    try:
        import docx
    except ImportError as exc:
        raise RenderError(
            'DOCX needs python-docx: pip install "sartor[import]"'
        ) from exc
    basics = tailored.get("basics") or {}
    document = docx.Document()  # type: ignore[attr-defined]
    document.add_heading(str(basics.get("name", "Resume")), level=0)
    if basics.get("label"):
        document.add_paragraph(str(basics["label"]))
    if basics.get("summary"):
        document.add_heading("Summary", level=1)
        document.add_paragraph(str(basics["summary"]))
    for section, title in _SECTION_TITLES:
        entries = tailored.get(section) or []
        if not entries:
            continue
        document.add_heading(title, level=1)
        if section == "skills":
            for entry in entries:
                if isinstance(entry, dict):
                    keywords = ", ".join(
                        str(k) for k in entry.get("keywords", []) or []
                    )
                    document.add_paragraph(
                        f"{entry.get('name', '')}: {keywords}".rstrip(": "),
                        style="List Bullet",
                    )
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            heading = _entry_title(entry) or title
            dates = _dates(entry)
            document.add_heading(f"{heading} — {dates}" if dates else heading, level=2)
            summary = entry.get("summary") or entry.get("description")
            if summary:
                document.add_paragraph(str(summary))
            for bullet in entry.get("highlights", []) or []:
                document.add_paragraph(_bullet_text(bullet), style="List Bullet")
    document.save(str(out))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_entry(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _optional_file_entry(path: Path) -> dict[str, Any] | None:
    return _file_entry(path) if path.is_file() else None


def build_manifest(
    project: Path,
    target: str,
    theme: str,
    written: list[Path],
) -> dict[str, Any]:
    """Describe one rendered bundle (S-012), without any secrets."""
    try:
        config = load_config(start=project)
    except Exception:  # invalid config must not block rendering records
        config = {}
    sources: list[dict[str, Any]] = []
    sources_dir = project / "sources"
    if sources_dir.is_dir():
        for path in sorted(sources_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sources.append(
                {
                    "source": record.get("source", path.name),
                    "record": path.name,
                    "kind": record.get("kind"),
                    "sha256": record.get("sha256"),
                    "span_count": len(record.get("spans", []) or []),
                }
            )
    verify: dict[str, Any] | None = None
    verify_path = project / "exports" / target / "verify.json"
    if verify_path.is_file():
        try:
            verify_data = json.loads(verify_path.read_text(encoding="utf-8"))
            verify = {
                "counts": verify_data.get("counts"),
                "strict": verify_data.get("strict"),
                "llm": verify_data.get("llm"),
                "unsupported_skills": verify_data.get("unsupported_skills", []),
            }
        except (OSError, json.JSONDecodeError):
            verify = None
    inputs = {
        "profile": _optional_file_entry(project / "profile.json"),
        "target": _optional_file_entry(project / "targets" / f"{target}.json"),
        "target_text": _optional_file_entry(project / "targets" / f"{target}.txt"),
        "tailored": _optional_file_entry(
            project / "exports" / target / "tailored.json"
        ),
        "sources": sources,
        "frameworks": [
            _file_entry(path)
            for mapping in sorted(
                (project / "exports" / target).glob("framework-*.json")
            )
            if (
                path := project
                / "frameworks"
                / (mapping.name.removeprefix("framework-"))
            ).is_file()
        ],
        "framework_mappings": [
            _file_entry(path)
            for path in sorted((project / "exports" / target).glob("framework-*.json"))
            if path.is_file()
        ],
        "research": _optional_file_entry(
            project / "exports" / target / "research.json"
        ),
    }
    return {
        "sartor_version": __version__,
        "target": target,
        "theme": theme,
        "provider": {
            "name": config.get("provider"),
            "model": config.get("model"),
            "base_url": config.get("base_url"),
        },
        "inputs": inputs,
        "verify": verify,
        "outputs": [_file_entry(path) for path in written],
    }


def render_bundle(project: Path, target: str, theme: str = "ats-plain") -> list[Path]:
    """Render every format into ``exports/<target>/``; return the paths."""
    require_theme(theme)
    try:
        tailored = load_tailored(project, target)
    except TailorError as exc:
        raise RenderError(str(exc)) from exc
    out_dir = project / "exports" / target
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    md = out_dir / "resume.md"
    md.write_text(render_markdown(tailored), encoding="utf-8")
    written.append(md)

    pitch = out_dir / "pitch.md"
    pitch.write_text(render_pitch(tailored), encoding="utf-8")
    written.append(pitch)

    deck = out_dir / "deck.md"
    deck.write_text(render_deck(tailored), encoding="utf-8")
    written.append(deck)

    html_text = render_html(tailored, theme=theme)
    html = out_dir / "resume.html"
    html.write_text(html_text, encoding="utf-8")
    written.append(html)

    plain = to_json_resume(tailored)
    validate_profile(plain)
    js = out_dir / "resume.json"
    js.write_text(
        json.dumps(plain, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    written.append(js)

    error: RenderError | None = None
    try:
        docx_out = out_dir / "resume.docx"
        _render_docx(tailored, docx_out)
        written.append(docx_out)
        pdf = out_dir / "resume.pdf"
        _render_pdf(html_text, pdf)
        written.append(pdf)
    except RenderError as exc:
        error = exc

    manifest = out_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            build_manifest(project, target, theme, written),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(manifest)

    if error is not None:
        raise RenderError(str(error), written=written) from error
    return written
