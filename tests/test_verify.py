"""S-007: deterministic verdicts, flag vs strict, entailment downgrade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seedkit import seed_project, span_id_containing

from sartor.providers import FakeProvider
from sartor.tailor import save_tailored
from sartor.verify import load_verify, verify_resume


def _write_tailored(project: Path) -> None:
    evidence = span_id_containing(project, "40 store managers")
    tailored = {
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
                    },
                    {
                        "text": "Tableau dashboard used by 40 store managers, with training and weekly reporting improvements.",
                        "evidence": [evidence],
                        "original": "x",
                    },
                    {
                        # The planted trap: 30% appears in no source.
                        "text": "Cut costs by 30% across the store network.",
                        "evidence": [evidence],
                        "original": "x",
                    },
                    {
                        "text": "Led a Kubernetes platform migration.",
                        "evidence": [],
                        "original": "x",
                    },
                ],
            }
        ],
        "skills": [{"name": "SQL"}, {"name": "Juggling"}],
        "meta": {"sartor": {"target": "acme"}},
    }
    save_tailored(project, "acme", tailored)


def test_verdicts_and_flagging(tmp_path: Path):
    project = seed_project(tmp_path)
    _write_tailored(project)
    out = verify_resume(project, "acme")
    data = json.loads(out.read_text(encoding="utf-8"))
    verdicts = [b["verdict"] for b in data["bullets"]]
    assert verdicts[0] == "supported"
    assert verdicts[1] in ("weak", "supported")
    assert verdicts[2] == "unsupported"  # invented 30%
    assert verdicts[3] == "unsupported"  # no evidence
    assert "30%" in " ".join(data["bullets"][2]["reasons"])
    assert data["unsupported_skills"] == ["Juggling"]
    tailored = json.loads(
        (project / "exports/acme/tailored.json").read_text(encoding="utf-8")
    )
    bullets = tailored["work"][0]["highlights"]
    assert bullets[2]["flagged"] is True
    assert "flagged" not in bullets[0]
    assert load_verify(project, "acme")["counts"]["unsupported"] == 2


def test_strict_drops_unsupported(tmp_path: Path):
    project = seed_project(tmp_path)
    _write_tailored(project)
    out = verify_resume(project, "acme", strict=True)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["dropped"] == 2
    tailored = json.loads(
        (project / "exports/acme/tailored.json").read_text(encoding="utf-8")
    )
    remaining = [b["text"] for b in tailored["work"][0]["highlights"]]
    assert not any("30%" in text or "Kubernetes" in text for text in remaining)


def test_llm_entailment_only_downgrades(tmp_path: Path):
    project = seed_project(tmp_path)
    _write_tailored(project)
    downgrader = FakeProvider({}, model="fake")

    def always_unsupported(system: str, prompt: str) -> str:
        return "UNSUPPORTED"

    downgrader.chat = always_unsupported  # type: ignore[method-assign]
    out = verify_resume(project, "acme", llm=True, provider=downgrader)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["bullets"][0]["verdict"] == "unsupported"


def test_verify_without_tailor_names_fix(tmp_path: Path):
    project = seed_project(tmp_path)
    from sartor.verify import VerifyError

    with pytest.raises(VerifyError, match="sartor tailor"):
        verify_resume(project, "acme")
