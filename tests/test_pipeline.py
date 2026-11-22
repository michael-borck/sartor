"""M1 end-to-end: ingest -> profile -> target -> tailor -> verify ->
report -> render, all offline with the FakeProvider and Jane Doe seed.
"""

from __future__ import annotations

import json
from pathlib import Path

from seedkit import seed_project, span_id_containing

from sartor.profile import all_spans, check_profile, load_sources
from sartor.providers import FakeProvider
from sartor.render import RenderError, render_bundle
from sartor.report import build_report
from sartor.tailor import build_tailor_prompt, tailor_resume
from sartor.target import load_target
from sartor.verify import verify_resume


def test_m1_pipeline(tmp_path: Path):
    project = seed_project(tmp_path)
    evidence = span_id_containing(project, "40 store managers")
    sql_evidence = span_id_containing(project, "14 stores")
    plan = {
        "summary": None,
        "sections": [
            {
                "section": "work",
                "index": 0,
                "highlights": [
                    {
                        "index": 0,
                        "text": "Consolidated 14 stores of sales data into one daily SQL model.",
                        "evidence": [sql_evidence],
                    },
                    {
                        "index": 1,
                        "text": "Delivered a Tableau dashboard used by 40 store managers weekly.",
                        "evidence": [evidence],
                    },
                ],
            },
            {"section": "education", "index": 0},
            {"section": "skills", "index": 0},
            {"section": "skills", "index": 1},
        ],
    }
    prompt = build_tailor_prompt(
        check_profile(project),
        load_target(project, "acme"),
        all_spans(load_sources(project)),
    )
    tailor_resume(project, "acme", FakeProvider({prompt: json.dumps(plan)}))

    verify = verify_resume(project, "acme")
    verify_data = json.loads(verify.read_text(encoding="utf-8"))
    assert verify_data["counts"]["unsupported"] == 0

    report_path = build_report(project, "acme")
    markdown_report = report_path.read_text(encoding="utf-8")
    assert "Kubernetes" in markdown_report  # the deliberate seed gap

    out_dir = project / "exports" / "acme"
    try:
        written = render_bundle(project, "acme")
        assert (out_dir / "resume.pdf").is_file()
        assert len(written) == 5
    except RenderError as exc:  # WeasyPrint system libs unavailable
        assert (out_dir / "resume.docx").is_file()
        assert len(exc.written) == 4
    for name in (
        "resume.md",
        "resume.html",
        "resume.json",
        "resume.docx",
        "tailored.json",
        "verify.json",
        "report.md",
        "coverage.json",
    ):
        assert (out_dir / name).is_file(), name
    md = (out_dir / "resume.md").read_text(encoding="utf-8")
    assert "Jane Doe" in md
    assert "40 store managers" in md
