"""S-016: derived queries, opt-in gate, providers/fallback, citations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seedkit import seed_project

from sartor.search import (
    FakeSearch,
    SearchError,
    build_queries,
    get_search_chain,
    research_target,
    run_search,
)
from sartor.target import load_target
from sartor.verify import verify_resume


def test_queries_come_from_target_only(tmp_path: Path):
    project = seed_project(tmp_path)
    target = load_target(project, "acme")
    queries = build_queries(target)
    assert queries
    joined = " ".join(queries).lower()
    # Nothing from Jane's profile may appear in a query.
    for private in ("jane", "doe", "shopfront", "quickfreight", "perth", "curtin"):
        assert private not in joined
    assert "acme" in joined or "senior data analyst" in joined


def test_research_refuses_without_optin(tmp_path: Path):
    project = seed_project(tmp_path)
    fake = FakeSearch({})
    with pytest.raises(SearchError, match="opt-in"):
        research_target(project, "acme", {}, chain=[fake])
    assert fake.queries == []  # nothing was sent


def test_research_writes_cited_context(tmp_path: Path):
    project = seed_project(tmp_path)
    target = load_target(project, "acme")
    queries = build_queries(target)
    fake = FakeSearch(
        {
            query: [
                {
                    "title": f"Result for {query}",
                    "url": "https://example.com/result",
                    "snippet": "Public context snippet.",
                }
            ]
            for query in queries
        }
    )
    out = research_target(project, "acme", {"search_enabled": True}, chain=[fake])
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["providers"] == ["fake"]
    assert record["queries"][0]["results"][0]["url"] == "https://example.com/result"
    markdown = (project / "exports/acme/research.md").read_text(encoding="utf-8")
    assert "Context only — never evidence" in markdown
    assert "https://example.com/result" in markdown
    assert fake.queries == queries


def test_search_chain_config_errors():
    with pytest.raises(SearchError, match="unknown search provider"):
        get_search_chain({"search_provider": "altavista"})
    with pytest.raises(SearchError, match="search_api_key"):
        get_search_chain({"search_provider": "brave"})
    with pytest.raises(SearchError, match="search_base_url"):
        get_search_chain({"search_provider": "searxng"})
    chain = get_search_chain({"search_provider": "auto"})
    assert [provider.name for provider in chain] == ["duckduckgo"]


def test_auto_fallback_first_nonempty_wins():
    empty = FakeSearch({})
    good = FakeSearch(
        {"q": [{"title": "T", "url": "https://example.com", "snippet": "s"}]}
    )
    name, results = run_search("q", [empty, good])
    assert name == "fake"
    assert results[0]["title"] == "T"
    with pytest.raises(SearchError, match="All search providers failed"):
        run_search("q", [FakeSearch({})])


def test_research_cannot_change_verdict(tmp_path: Path):
    from sartor.tailor import save_tailored

    project = seed_project(tmp_path)
    from seedkit import span_id_containing

    evidence = span_id_containing(project, "40 store managers")
    save_tailored(
        project,
        "acme",
        {
            "basics": {"name": "Jane Doe"},
            "work": [
                {
                    "name": "ShopFront Retail",
                    "position": "Senior Data Analyst",
                    "highlights": [
                        {
                            "text": "Cut costs by 30% across the store network.",
                            "evidence": [evidence],
                            "original": "x",
                        }
                    ],
                }
            ],
            "meta": {"sartor": {"target": "acme"}},
        },
    )
    target = load_target(project, "acme")
    fake = FakeSearch(
        {
            query: [
                {
                    "title": "Cost cutting",
                    "url": "https://example.com/costs",
                    "snippet": "Retailers cut costs by 30% with dashboards.",
                }
            ]
            for query in build_queries(target)
        }
    )
    research_target(project, "acme", {"search_enabled": True}, chain=[fake])
    verify = verify_resume(project, "acme")
    data = json.loads(verify.read_text(encoding="utf-8"))
    assert data["bullets"][0]["verdict"] == "unsupported"


def test_parse_duckduckgo_lite_unwraps_redirects():
    from sartor.search import parse_duckduckgo_lite

    html = """
    <a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Facme" class='result-link'>Acme Overview</a>
    <td class='result-snippet'>Public snippet.</td>
    """
    results = parse_duckduckgo_lite(html, 5)
    assert results == [
        {
            "title": "Acme Overview",
            "url": "https://example.com/acme",
            "snippet": "Public snippet.",
        }
    ]


def test_fake_search_filters_malformed_redirect_urls():
    fake = FakeSearch(
        {
            "q": [
                {"title": "Bad redirect", "url": "http:///go/v1/abc", "snippet": "x"},
                {"title": "Good", "url": "https://example.com/ok", "snippet": "y"},
            ]
        }
    )
    assert [r["title"] for r in fake.search("q")] == ["Good"]
