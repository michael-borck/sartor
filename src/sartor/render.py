"""Rendering: one tailored model, five files (S-009).

``resume.md``, ``resume.html``, ``resume.pdf`` (WeasyPrint from the
HTML, so the two never diverge), ``resume.docx`` (python-docx) and
``resume.json`` (plain JSON Resume: internal bullet objects flatten
to strings, evidence moves under ``meta.sartor.bullet_evidence``).

M1 ships one theme, ``ats-plain``: single column, real headings, no
tables or text boxes, selectable PDF text. Flagged bullets (S-007)
carry an HTML-comment marker in Markdown only.

If WeasyPrint or python-docx is unavailable, the formats that can be
rendered are written first; ``RenderError.written`` lists them and
the CLI exits 1 naming the install fix.
"""

from __future__ import annotations

import copy
import html as html_lib
import json
from pathlib import Path
from typing import Any

from sartor.profile import validate_profile
from sartor.tailor import BULLET_SECTIONS, TailorError, load_tailored

THEMES = ("ats-plain",)

_CSS = """
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


def render_html(tailored: dict[str, Any]) -> str:
    basics = tailored.get("basics") or {}
    esc = html_lib.escape
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{esc(str(basics.get('name', 'Resume')))} — Resume</title>",
        f"<style>{_CSS}</style>",
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


def render_bundle(project: Path, target: str, theme: str = "ats-plain") -> list[Path]:
    """Render every format into ``exports/<target>/``; return the paths."""
    if theme not in THEMES:
        raise RenderError(f"Unknown theme {theme!r}; M1 ships: {', '.join(THEMES)}")
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

    html_text = render_html(tailored)
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

    try:
        docx_out = out_dir / "resume.docx"
        _render_docx(tailored, docx_out)
        written.append(docx_out)
        pdf = out_dir / "resume.pdf"
        _render_pdf(html_text, pdf)
        written.append(pdf)
    except RenderError as exc:
        raise RenderError(str(exc), written=written) from exc
    return written
