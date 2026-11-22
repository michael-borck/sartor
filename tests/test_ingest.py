"""S-003: ingest every format to stable spans, partial failures, seed parity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sartor.cli import app
from sartor.ingest import IngestError, build_source, ingest_file, split_spans
from sartor.project import init_project

runner = CliRunner()
SEED = Path(__file__).resolve().parents[1] / "examples" / "jane-doe"


def test_split_spans_shape():
    text = "# Title\n\nFirst sentence. Second sentence.\n\n- A bullet\n- Another\n"
    assert split_spans(text) == [
        "Title",
        "First sentence.",
        "Second sentence.",
        "A bullet",
        "Another",
    ]


def test_ingest_txt_and_stability(tmp_path: Path):
    project = init_project(tmp_path / "p")
    src = tmp_path / "notes.txt"
    src.write_text("Jane led a team.\n\n- Did a thing in 2022.\n", encoding="utf-8")
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    out1 = ingest_file(src, project)
    first = out1.read_bytes()
    out2 = ingest_file(src, project)
    assert out2.read_bytes() == first  # byte-identical on re-ingest
    record = json.loads(first.decode())
    assert record["spans"][0]["id"] == "src://notes.txt#s1"
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before  # untouched


def test_ingest_html(tmp_path: Path):
    src = tmp_path / "page.html"
    src.write_text(
        "<html><body><h1>Jane Doe</h1><p>Analyst in Perth.</p></body></html>",
        encoding="utf-8",
    )
    texts = [span["text"] for span in build_source(src)["spans"]]
    assert "Jane Doe" in texts
    assert "Analyst in Perth." in texts


def test_ingest_unsupported_names_extensions(tmp_path: Path):
    src = tmp_path / "photo.png"
    src.write_bytes(b"\x89PNG")
    with pytest.raises(IngestError, match=r"\.pdf.*\.docx"):
        build_source(src)


def test_json_resume_is_lossless_candidate():
    record = build_source(SEED / "profile.json")
    assert record["profile_candidate"] is True
    original = json.loads((SEED / "profile.json").read_text(encoding="utf-8"))
    assert record["json_resume"] == original


def test_seed_format_parity():
    bullet = "40 store managers"
    for name in ("resume.md", "resume.pdf", "resume.docx"):
        texts = [span["text"] for span in build_source(SEED / name)["spans"]]
        assert any(bullet in text for text in texts), name
        assert any("Jane Doe" in text for text in texts), name


def test_ingest_cli_partial_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = init_project(tmp_path / "p")
    good = tmp_path / "good.md"
    good.write_text("# Jane\n\nAnalyst.\n", encoding="utf-8")
    bad = tmp_path / "bad.xyz"
    bad.write_text("nope", encoding="utf-8")
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["ingest", str(good), str(bad)])
    assert result.exit_code == 1
    assert "good.md:" in result.output
    assert "bad.xyz" in result.output
    assert (project / "sources" / "good.md.json").is_file()


def test_ingest_cli_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = init_project(tmp_path / "p")
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 2
    assert "No files given" in result.output


def test_ingest_cli_outside_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    src = tmp_path / "a.txt"
    src.write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["ingest", str(src)])
    assert result.exit_code == 2
    assert "sartor init" in result.output
