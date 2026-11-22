"""S-009/S-010..S-012: golden MD/HTML, bundle formats, handoffs, manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seedkit import seed_project, span_id_containing

from sartor.profile import validate_profile
from sartor.render import (
    RenderError,
    render_bundle,
    render_html,
    render_markdown,
    to_json_resume,
)
from sartor.tailor import save_tailored

SNAP = Path(__file__).parent / "snapshots" / "render" / "ats-plain"


def _tailored(project: Path) -> dict:
    evidence = span_id_containing(project, "40 store managers")
    return {
        "basics": {
            "name": "Jane Doe",
            "label": "Data Analyst",
            "email": "jane.doe@example.com",
            "summary": "Data analyst with 6 years of experience.",
            "location": {"city": "Perth", "countryCode": "AU"},
        },
        "work": [
            {
                "name": "ShopFront Retail",
                "position": "Senior Data Analyst",
                "startDate": "2021-03-01",
                "highlights": [
                    {
                        "text": "Shipped a Tableau dashboard used by 40 store managers every Monday.",
                        "evidence": [evidence],
                        "original": "x",
                    },
                    {
                        "text": "Cut costs by 30% across the store network.",
                        "evidence": [evidence],
                        "original": "x",
                        "flagged": True,
                    },
                ],
            }
        ],
        "education": [
            {
                "institution": "Curtin University",
                "area": "Business Information Systems",
                "studyType": "Bachelor of Commerce",
                "endDate": "2018-12-01",
            }
        ],
        "skills": [{"name": "SQL", "keywords": ["PostgreSQL", "BigQuery"]}],
        "meta": {"sartor": {"target": "acme"}},
    }


def _pdf_available() -> bool:
    import importlib

    try:
        importlib.import_module("weasyprint")
    except Exception:
        return False
    return True


def test_golden_markdown_and_html(tmp_path: Path):
    tailored = _tailored(seed_project(tmp_path))
    assert render_markdown(tailored) == (SNAP / "resume.md").read_text(encoding="utf-8")
    assert render_html(tailored) == (SNAP / "resume.html").read_text(encoding="utf-8")


def test_flagged_marker_only_in_markdown(tmp_path: Path):
    tailored = _tailored(seed_project(tmp_path))
    assert "<!-- flagged: unsupported -->" in render_markdown(tailored)
    assert "flagged" not in render_html(tailored)
    plain = to_json_resume(tailored)
    assert plain["work"][0]["highlights"][1].startswith("Cut costs")
    assert plain["meta"]["sartor"]["flagged"] == ["work[0].highlights[1]"]
    validate_profile(plain)


def test_render_bundle(tmp_path: Path):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    if not _pdf_available():
        with pytest.raises(RenderError) as exc_info:
            render_bundle(project, "acme")
        names = [p.name for p in exc_info.value.written]
        assert names == [
            "resume.md",
            "pitch.md",
            "deck.md",
            "resume.html",
            "resume.json",
            "resume.docx",
            "manifest.json",
        ]
        assert (project / "exports" / "acme" / "pitch.md").is_file()
        return
    written = render_bundle(project, "acme")
    assert [p.name for p in written] == [
        "resume.md",
        "pitch.md",
        "deck.md",
        "resume.html",
        "resume.json",
        "resume.docx",
        "resume.pdf",
        "manifest.json",
    ]
    out = project / "exports" / "acme"
    md_text = (out / "resume.md").read_text(encoding="utf-8")
    from pypdf import PdfReader

    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(str(out / "resume.pdf")).pages
    )
    assert "40 store managers" in pdf_text
    assert "Jane Doe" in pdf_text
    import docx

    document = docx.Document(str(out / "resume.docx"))
    docx_text = [p.text for p in document.paragraphs if p.text]
    assert any("Jane Doe" in t for t in docx_text)
    assert any("40 store managers" in t for t in docx_text)
    resume_json = json.loads((out / "resume.json").read_text(encoding="utf-8"))
    validate_profile(resume_json)
    assert "Cut costs by 30%" in md_text


def test_render_unknown_theme(tmp_path: Path):
    project = seed_project(tmp_path)
    save_tailored(project, "acme", _tailored(project))
    with pytest.raises(RenderError, match="ats-plain"):
        render_bundle(project, "acme", theme="fancy")


def test_render_without_tailor(tmp_path: Path):
    project = seed_project(tmp_path)
    with pytest.raises(RenderError, match="sartor tailor"):
        render_bundle(project, "acme")
