"""S-008: coverage statuses, ATS keywords, gap wording, verify counts."""

from __future__ import annotations

import json
from pathlib import Path

from seedkit import seed_project, span_id_containing

from sartor.report import BANNED_PHRASES, GAP_PHRASE, build_report
from sartor.tailor import save_tailored


def _seeded_tailored(project: Path) -> None:
    evidence = span_id_containing(project, "40 store managers")
    save_tailored(
        project,
        "acme",
        {
            "basics": {
                "name": "Jane Doe",
                "label": "Data Analyst",
                "summary": "SQL and Python data analyst.",
            },
            "work": [
                {
                    "name": "ShopFront Retail",
                    "position": "Senior Data Analyst",
                    "highlights": [
                        {
                            "text": "Shipped a Tableau dashboard used by 40 store managers every Monday.",
                            "evidence": [evidence],
                            "original": "x",
                        }
                    ],
                }
            ],
            "skills": [
                {"name": "SQL", "keywords": ["PostgreSQL"]},
                {"name": "Python", "keywords": ["pandas"]},
            ],
            "meta": {"sartor": {"target": "acme"}},
        },
    )


def test_report_coverage_keywords_and_wording(tmp_path: Path):
    project = seed_project(tmp_path)
    _seeded_tailored(project)
    out = build_report(project, "acme")  # auto-runs deterministic verify
    markdown = out.read_text(encoding="utf-8")
    coverage = json.loads(
        (project / "exports/acme/coverage.json").read_text(encoding="utf-8")
    )
    rows = {r["requirement"]: r for r in coverage["requirements"]["must_haves"]}
    assert rows["Expert SQL"]["status"] in ("evidenced", "weak")
    assert rows["Kubernetes"]["status"] == "gap"
    keywords = {k["keyword"]: k["present"] for k in coverage["keywords"]}
    assert keywords["SQL"] is True
    assert keywords["Kubernetes"] is False
    assert "| Kubernetes | no |" in markdown
    assert GAP_PHRASE in markdown
    assert not any(phrase in markdown.lower() for phrase in BANNED_PHRASES)
    verify = json.loads(
        (project / "exports/acme/verify.json").read_text(encoding="utf-8")
    )
    assert coverage["verify_counts"] == verify["counts"]
    assert f"Bullets: {verify['counts']['supported']} supported" in markdown
