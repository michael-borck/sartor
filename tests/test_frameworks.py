"""S-014/S-015: user-supplied frameworks, deterministic mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seedkit import SEED, seed_project

from sartor.frameworks import (
    FrameworkError,
    add_framework,
    list_frameworks,
    load_framework,
    map_framework,
    parse_framework,
)


def test_add_csv_framework(tmp_path: Path):
    project = seed_project(tmp_path)
    out = add_framework(project, SEED / "framework-demo.csv", "demo", "custom")
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["kind"] == "custom"
    assert record["source_file"] == "framework-demo.csv"
    assert len(record["source_sha256"]) == 64
    assert record["skills"][0]["code"] == "SQL"
    assert record["skills"][0]["level"] == 4
    assert record["skills"][0]["keywords"] == ["SQL", "PostgreSQL", "BigQuery"]
    assert [f["name"] for f in list_frameworks(project)] == ["demo"]
    assert load_framework(project, "demo")["skills"][1]["code"] == "DASH"
    with pytest.raises(FrameworkError, match="--force"):
        add_framework(project, SEED / "framework-demo.csv", "demo", "custom")


def test_add_json_framework(tmp_path: Path):
    project = seed_project(tmp_path)
    source = tmp_path / "fw.json"
    source.write_text(
        json.dumps(
            {"skills": [{"code": "A1", "name": "Analysis", "keywords": ["SQL"]}]}
        ),
        encoding="utf-8",
    )
    record = parse_framework(source, "tiny", "sfia")
    assert record["skills"][0]["name"] == "Analysis"
    assert add_framework(project, source, "tiny", "sfia").is_file()


@pytest.mark.parametrize(
    "content,match",
    [
        ("code,name\nX,\n", "row 1 needs both code and name"),
        ("code,name\nX,One\nx,Two\n", "duplicate code"),
        ("foo,bar\n1,2\n", "needs code,name columns"),
        ("code,name\n", "no framework skills found"),
    ],
)
def test_bad_framework_files(tmp_path: Path, content: str, match: str):
    source = tmp_path / "bad.csv"
    source.write_text(content, encoding="utf-8")
    with pytest.raises(FrameworkError, match=match):
        parse_framework(source, "bad", "custom")


def test_unknown_kind_and_missing_framework(tmp_path: Path):
    project = seed_project(tmp_path)
    with pytest.raises(FrameworkError, match="unknown framework kind"):
        parse_framework(SEED / "framework-demo.csv", "demo", "nasa")
    with pytest.raises(FrameworkError, match="user-supplied, never bundled"):
        load_framework(project, "sfia")


def test_map_alignments_and_evidence(tmp_path: Path):
    project = seed_project(tmp_path)
    add_framework(project, SEED / "framework-demo.csv", "demo", "custom")
    out = map_framework(project, "acme", "demo")
    mapping = json.loads(out.read_text(encoding="utf-8"))
    rows = {row["code"]: row for row in mapping["skills"]}
    assert rows["SQL"]["alignment"] == "matched"
    assert rows["SQL"]["profile_evidence"], "profile match needs span evidence"
    assert rows["KUBE"]["alignment"] == "target_gap"
    assert rows["PUB"]["alignment"] == "profile_only"
    assert rows["RUST"]["alignment"] == "neither"
    assert mapping["counts"]["matched"] >= 1
    assert "Kubernetes" in (rows["KUBE"]["target_requirement"] or "")


def test_package_bundles_no_framework_data():
    import sartor

    package_dir = Path(sartor.__file__).parent
    framework_files = [
        path
        for path in package_dir.rglob("*")
        if path.is_file()
        and "framework" in path.name.lower()
        and path.suffix in (".csv", ".json")
    ]
    assert framework_files == []


def test_report_includes_framework_section(tmp_path: Path):
    from sartor.report import build_report
    from sartor.tailor import save_tailored

    project = seed_project(tmp_path)
    add_framework(project, SEED / "framework-demo.csv", "demo", "custom")
    map_framework(project, "acme", "demo")
    from seedkit import span_id_containing

    evidence = span_id_containing(project, "40 store managers")
    save_tailored(
        project,
        "acme",
        {
            "basics": {"name": "Jane Doe", "label": "Data Analyst"},
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
            "skills": [{"name": "SQL", "keywords": ["PostgreSQL"]}],
            "meta": {"sartor": {"target": "acme"}},
        },
    )
    out = build_report(project, "acme")
    markdown = out.read_text(encoding="utf-8")
    assert "## Framework — demo (custom)" in markdown
    assert "| SQL | SQL and data modelling |" in markdown
    assert "| KUBE | Kubernetes operations |" in markdown
    coverage = json.loads(
        (project / "exports/acme/coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["frameworks"][0]["framework"] == "demo"
