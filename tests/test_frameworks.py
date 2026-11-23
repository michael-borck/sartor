"""S-014/S-015: user-supplied frameworks, deterministic mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seedkit import SEED, seed_project

from sartor.frameworks import (
    FrameworkError,
    add_framework,
    confirm_framework_level,
    list_frameworks,
    load_framework,
    map_framework,
    parse_framework,
    write_framework_statement,
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


def _levelled_framework(tmp_path: Path) -> Path:
    source = tmp_path / "levels.csv"
    source.write_text(
        "code,name,level,descriptor,keywords\n"
        "DBM,SQL and data modelling,3,Writes guided reporting queries,SQL\n"
        "DBM,SQL and data modelling,4,Built SQL pipeline consolidating stores daily model,SQL;pipeline\n"
        "DBM,SQL and data modelling,5,Sets organisation-wide architecture strategy,SQL;strategy\n"
        "KUBE,Kubernetes operations,3,Operates container platforms,Kubernetes\n",
        encoding="utf-8",
    )
    return source


def test_level_rows_group_suggest_and_confirm(tmp_path: Path):
    project = seed_project(tmp_path / "project")
    source = _levelled_framework(tmp_path)
    record = parse_framework(source, "levels", "custom")
    assert [skill["level"] for skill in record["skills"][:3]] == [3, 4, 5]
    assert record["skills"][1]["descriptor"].startswith("Built SQL pipeline")
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(
        "code,name,level\nDBM,One,4\ndbm,Two,4\n", encoding="utf-8"
    )
    with pytest.raises(FrameworkError, match="duplicate code and level"):
        parse_framework(duplicate, "duplicate", "custom")

    add_framework(project, source, "levels", "custom")
    out = map_framework(project, "acme", "levels")
    mapping = json.loads(out.read_text(encoding="utf-8"))
    rows = {row["code"]: row for row in mapping["skills"]}
    assert set(rows) == {"DBM", "KUBE"}, "level rows collapse to one mapping code"
    assert [level["level"] for level in rows["DBM"]["levels"]] == [3, 4, 5]
    assert rows["DBM"]["suggested_level"] == 4
    assert rows["DBM"]["suggested_level"] != 5, "SQL alone cannot suggest level 5"
    assert rows["DBM"]["confirmed_level"] is None
    assert rows["DBM"]["level_status"] == "suggested"
    assert rows["KUBE"]["descriptor"] == "", (
        "an unconfirmed/unsuggested level must not lend its descriptor voice"
    )

    before = (project / "frameworks/levels.json").read_text(encoding="utf-8")
    with pytest.raises(FrameworkError, match="unknown code"):
        confirm_framework_level(project, "levels", "NOPE", 4)
    with pytest.raises(FrameworkError, match="unknown level"):
        confirm_framework_level(project, "levels", "DBM", 9)
    assert (project / "frameworks/levels.json").read_text(encoding="utf-8") == before

    confirm_framework_level(project, "levels", "dbm", 4)
    mapping = json.loads(map_framework(project, "acme", "levels").read_text())
    row = {item["code"]: item for item in mapping["skills"]}["DBM"]
    assert row["confirmed_level"] == 4
    assert row["level_status"] == "confirmed"


def test_statement_display_modes_keep_level_hidden_by_default(tmp_path: Path):
    project = seed_project(tmp_path / "project")
    add_framework(project, _levelled_framework(tmp_path), "levels", "custom")

    md_path, json_path = write_framework_statement(project, "acme", "levels")
    statement = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    dbm = {row["code"]: row for row in statement["skills"]}["DBM"]
    assert statement["display"] == "code"
    assert dbm["statements"], "profile bullets should form evidence statements"
    assert all(item["evidence"] for item in dbm["statements"])
    assert "## DBM — SQL and data modelling" in markdown
    assert "Level 4" not in markdown
    assert "Suggested level" not in markdown

    md_path, _ = write_framework_statement(
        project, "acme", "levels", display="none"
    )
    markdown = md_path.read_text(encoding="utf-8")
    assert "DBM" not in markdown
    assert "Level 4" not in markdown

    md_path, _ = write_framework_statement(
        project, "acme", "levels", display="code-level"
    )
    assert "Suggested level 4 (not confirmed" in md_path.read_text(encoding="utf-8")

    confirm_framework_level(project, "levels", "DBM", 4)
    md_path, json_path = write_framework_statement(
        project, "acme", "levels", display="code-level"
    )
    assert "Level 4 (confirmed by you)" in md_path.read_text(encoding="utf-8")
    statement = json.loads(json_path.read_text(encoding="utf-8"))
    dbm = {row["code"]: row for row in statement["skills"]}["DBM"]
    assert dbm["display_level"] == 4
    assert dbm["level_status"] == "confirmed"

    with pytest.raises(FrameworkError, match="display"):
        write_framework_statement(project, "acme", "levels", display="level")


def test_statement_uses_tailored_and_skips_flagged_bullets(tmp_path: Path):
    from seedkit import span_id_containing

    from sartor.tailor import save_tailored

    project = seed_project(tmp_path / "project")
    add_framework(project, _levelled_framework(tmp_path), "levels", "custom")
    evidence = span_id_containing(project, "SQL pipeline")
    save_tailored(
        project,
        "acme",
        {
            "basics": {"name": "Jane Doe"},
            "work": [
                {
                    "name": "ShopFront Retail",
                    "highlights": [
                        {
                            "text": "Built a SQL pipeline consolidating 14 stores into one daily model.",
                            "evidence": [evidence],
                            "original": "x",
                        },
                        {
                            "text": "Built a SQL pipeline for an unsupported claim.",
                            "evidence": [evidence],
                            "original": "y",
                            "flagged": True,
                        },
                    ],
                }
            ],
            "meta": {"sartor": {"target": "acme"}},
        },
    )
    md_path, json_path = write_framework_statement(project, "acme", "levels")
    statement = json.loads(json_path.read_text(encoding="utf-8"))
    dbm = {row["code"]: row for row in statement["skills"]}["DBM"]
    assert [item["source"] for item in dbm["statements"]] == ["tailored"]
    assert "unsupported claim" not in md_path.read_text(encoding="utf-8")


def test_report_includes_statement_without_level(tmp_path: Path):
    from seedkit import span_id_containing

    from sartor.report import build_report
    from sartor.tailor import save_tailored

    project = seed_project(tmp_path / "project")
    add_framework(project, _levelled_framework(tmp_path), "levels", "custom")
    evidence = span_id_containing(project, "SQL pipeline")
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
                            "text": "Built a SQL pipeline consolidating 14 stores into one daily model.",
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
    write_framework_statement(project, "acme", "levels")
    out = build_report(project, "acme")
    markdown = out.read_text(encoding="utf-8")
    assert "## Framework statements — levels" in markdown
    assert "Built a SQL pipeline" in markdown
    assert "Level 4" not in markdown
    coverage = json.loads(
        (project / "exports/acme/coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["framework_statements"][0]["framework"] == "levels"


def test_manifest_records_framework_statement(tmp_path: Path):
    from sartor.render import build_manifest

    project = seed_project(tmp_path / "project")
    add_framework(project, _levelled_framework(tmp_path), "levels", "custom")
    write_framework_statement(project, "acme", "levels")
    manifest = build_manifest(project, "acme", "ats-plain", [])
    names = [entry["name"] for entry in manifest["inputs"]["framework_statements"]]
    assert names == ["statement-levels.json", "statement-levels.md"]


def test_framework_statement_and_confirm_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from typer.testing import CliRunner

    from sartor.cli import app

    project = seed_project(tmp_path / "project")
    source = _levelled_framework(tmp_path)
    monkeypatch.chdir(project)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "framework",
            "add",
            str(source),
            "--name",
            "levels",
            "--kind",
            "custom",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app, ["framework", "map", "acme", "--framework", "levels"]
    )
    assert result.exit_code == 0, result.output
    assert "Internal levels:" in result.output
    result = runner.invoke(
        app,
        ["framework", "statement", "acme", "--framework", "levels"],
    )
    assert result.exit_code == 0, result.output
    assert "No level is printed" in result.output
    assert "Level 4" not in (
        project / "exports/acme/statement-levels.md"
    ).read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "framework",
            "confirm",
            "--framework",
            "levels",
            "--code",
            "DBM",
            "--level",
            "9",
        ],
    )
    assert result.exit_code == 1
    assert "unknown level" in result.output
    result = runner.invoke(
        app,
        [
            "framework",
            "confirm",
            "--framework",
            "levels",
            "--code",
            "DBM",
            "--level",
            "4",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "framework",
            "statement",
            "acme",
            "--framework",
            "levels",
            "--display",
            "code-level",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Level 4 (confirmed by you)" in (
        project / "exports/acme/statement-levels.md"
    ).read_text(encoding="utf-8")


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
