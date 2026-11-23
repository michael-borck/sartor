"""Opt-in search grounding (S-016): cited context, never evidence.

Queries are derived from target fields only (title, organisation,
keywords) — profile and source text are never inputs to this module's
query builder, so resume text cannot leave the machine via search.
Providers follow the Study Buddy -> Career Compass chain: DuckDuckGo
(no key), Brave, Serper (keys via ``${ENV_VAR}`` config), SearXNG
(configured instance), with ``auto`` falling through in that order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlparse

import requests

from sartor.target import TargetError, load_target

SEARCH_PROVIDERS = ("duckduckgo", "brave", "serper", "searxng", "auto")
CONTEXT_HEADING = "Context only — never evidence for a resume claim."


class SearchError(Exception):
    """Raised when search is not enabled or every provider fails."""

    def __init__(self, message: str, kind: str = "http"):
        super().__init__(message)
        self.kind = kind


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return results with title, url, snippet."""
        ...


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 15,
) -> Any:
    try:
        response = session.request(
            method,
            url,
            headers=headers or {},
            params=params,
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SearchError(
            f"Cannot reach {url} ({exc.__class__.__name__})", kind="unreachable"
        ) from exc
    if response.status_code in (401, 403):
        raise SearchError(f"Search authentication failed at {url}", kind="auth")
    if response.status_code >= 400:
        raise SearchError(
            f"HTTP {response.status_code} from {url}: {response.text[:160]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise SearchError(f"Reply from {url} is not JSON", kind="bad-response") from exc


def _request_text(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any],
    timeout: float,
) -> str:
    try:
        response = session.request(
            "GET", url, headers=headers, params=params, timeout=timeout
        )
    except requests.RequestException as exc:
        raise SearchError(
            f"Cannot reach {url} ({exc.__class__.__name__})", kind="unreachable"
        ) from exc
    if response.status_code in (401, 403):
        raise SearchError(f"Search authentication failed at {url}", kind="auth")
    if response.status_code >= 400:
        raise SearchError(
            f"HTTP {response.status_code} from {url}: {response.text[:160]}"
        )
    return response.text


def parse_duckduckgo_lite(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Parse DuckDuckGo Lite results, unwrapping uddg redirects."""
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.links: list[tuple[str, str]] = []
            self.snippets: list[str] = []
            self._href: str | None = None
            self._in_link = False
            self._in_snippet = False
            self._text: list[str] = []

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            attr = dict(attrs)
            classes = (attr.get("class") or "").split()
            if tag == "a" and "result-link" in classes:
                self._in_link = True
                self._href = attr.get("href") or ""
                self._text = []
            elif "result-snippet" in classes:
                self._in_snippet = True
                self._text = []

        def handle_data(self, data: str) -> None:
            if self._in_link or self._in_snippet:
                self._text.append(data)

        def handle_endtag(self, tag: str) -> None:
            if self._in_link and tag == "a":
                self.links.append((self._href or "", "".join(self._text).strip()))
                self._in_link = False
                self._href = None
            elif self._in_snippet and tag in ("td", "div", "span"):
                self.snippets.append("".join(self._text).strip())
                self._in_snippet = False

    parser = Parser()
    parser.feed(html_text)
    raw: list[dict[str, Any]] = []
    for index, (url, title) in enumerate(parser.links):
        parsed = urlparse(url)
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            url = unquote(uddg[0])
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith(("http://", "https://")) or len(title) <= 3:
            continue
        if "duckduckgo" in title.lower() or "next page" in title.lower():
            continue
        snippet = parser.snippets[index] if index < len(parser.snippets) else ""
        raw.append({"title": title[:200], "url": url, "snippet": snippet})
        if len(raw) >= limit:
            break
    return _clean(raw, limit)


def _clean(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out = []
    for item in results:
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "snippet": str(
                    item.get("snippet")
                    or item.get("description")
                    or item.get("content")
                    or ""
                ).strip(),
            }
        )
        if len(out) >= limit:
            break
    return out


class DuckDuckGoSearch:
    name = "duckduckgo"

    def __init__(self, timeout: float = 15, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        try:
            html_text = _request_text(
                self.session,
                "https://lite.duckduckgo.com/lite/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "DNT": "1",
                },
                params={"q": query, "t": "h_", "ia": "web"},
                timeout=self.timeout,
            )
            lite = parse_duckduckgo_lite(html_text, limit)
            if lite:
                return lite
        except SearchError:
            pass
        data = _request_json(
            self.session,
            "GET",
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=self.timeout,
        )
        raw: list[dict[str, Any]] = []
        if isinstance(data, dict) and data.get("AbstractText"):
            raw.append(
                {
                    "title": data.get("Heading") or query,
                    "url": data.get("AbstractURL") or "",
                    "snippet": data.get("AbstractText"),
                }
            )

        def walk(topics: Any) -> None:
            if not isinstance(topics, list):
                return
            for topic in topics:
                if not isinstance(topic, dict):
                    continue
                if topic.get("FirstURL"):
                    raw.append(
                        {
                            "title": str(topic.get("Text", "")).split(" - ")[0],
                            "url": topic.get("FirstURL"),
                            "snippet": topic.get("Text", ""),
                        }
                    )
                walk(topic.get("Topics"))

        if isinstance(data, dict):
            walk(data.get("RelatedTopics"))
        return _clean(raw, limit)


class BraveSearch:
    name = "brave"

    def __init__(
        self, api_key: str, timeout: float = 15, session: requests.Session | None = None
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        data = _request_json(
            self.session,
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            },
            params={
                "q": query,
                "count": max(1, min(limit, 20)),
                "text_decorations": "false",
                "search_lang": "en",
                "safesearch": "moderate",
            },
            timeout=self.timeout,
        )
        results = ((data or {}).get("web") or {}).get("results") or []
        return _clean(results, limit)


class SerperSearch:
    name = "serper"

    def __init__(
        self, api_key: str, timeout: float = 15, session: requests.Session | None = None
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        data = _request_json(
            self.session,
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            payload={"q": query, "num": max(1, min(limit, 20))},
            timeout=self.timeout,
        )
        return _clean((data or {}).get("organic") or [], limit)


class SearXNGSearch:
    name = "searxng"

    def __init__(
        self,
        base_url: str,
        timeout: float = 15,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        data = _request_json(
            self.session,
            "GET",
            f"{self.base_url}/search",
            params={"q": query, "format": "json"},
            timeout=self.timeout,
        )
        return _clean((data or {}).get("results") or [], limit)


class FakeSearch:
    """Recorded search results for tests, keyed by query text."""

    name = "fake"

    def __init__(self, results: dict[str, list[dict[str, Any]]]):
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        self.queries.append(query)
        return _clean(list(self.results.get(query, [])), limit)


def search_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("search_enabled"))


def _make_provider(
    name: str, config: dict[str, Any], timeout: float
) -> SearchProvider | None:
    key = config.get("search_api_key") or ""
    if name == "duckduckgo":
        return DuckDuckGoSearch(timeout=timeout)
    if name == "brave":
        return BraveSearch(str(key), timeout=timeout) if key else None
    if name == "serper":
        return SerperSearch(str(key), timeout=timeout) if key else None
    if name == "searxng":
        base = config.get("search_base_url")
        return SearXNGSearch(str(base), timeout=timeout) if base else None
    return None


def get_search_chain(config: dict[str, Any]) -> list[SearchProvider]:
    """Configured provider(s); `auto` falls through in chain order."""
    requested = str(config.get("search_provider") or "duckduckgo").lower()
    if requested not in SEARCH_PROVIDERS:
        raise SearchError(
            f"unknown search provider {requested!r}; expected one of: {', '.join(SEARCH_PROVIDERS)}",
            kind="config",
        )
    timeout = float(config.get("search_timeout") or 15)
    if requested == "auto":
        chain = [
            provider
            for name in ("duckduckgo", "brave", "serper", "searxng")
            if (provider := _make_provider(name, config, timeout)) is not None
        ]
        return chain
    provider = _make_provider(requested, config, timeout)
    if provider is None:
        missing = (
            "search_api_key" if requested in ("brave", "serper") else "search_base_url"
        )
        env = config.get("search_api_key_env") or "SEARCH_API_KEY"
        raise SearchError(
            f"search provider {requested!r} needs {missing} in sartor.yaml "
            f"(keys by reference, e.g. search_api_key: ${{{env}}})",
            kind="config",
        )
    return [provider]


def run_search(
    query: str, chain: list[SearchProvider], limit: int = 5
) -> tuple[str, list[dict[str, Any]]]:
    """First non-empty provider wins; returns (provider name, results)."""
    errors: list[str] = []
    for provider in chain:
        try:
            results = provider.search(query, limit=limit)
        except SearchError as exc:
            errors.append(f"{provider.name}: {exc}")
            continue
        if results:
            return provider.name, results
        errors.append(f"{provider.name}: no results")
    raise SearchError("All search providers failed — " + "; ".join(errors))


def build_queries(target: dict[str, Any]) -> list[str]:
    """Derived queries from target fields ONLY (never profile text)."""
    title = str(target.get("title") or "").strip()
    org = str(target.get("organisation") or "").strip()
    keywords = [
        str(k).strip() for k in target.get("keywords", []) or [] if str(k).strip()
    ]
    queries: list[str] = []
    if org and title:
        queries.append(f"{org} {title}")
    if org:
        queries.append(f"{org} company overview")
    if title:
        queries.append(f"{title} role responsibilities")
    for start in range(0, min(len(keywords), 6), 3):
        group = " ".join(keywords[start : start + 3])
        if group:
            queries.append(f"{group} terminology" if not title else f"{title} {group}")
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique.append(query)
    return unique[:5]


def research_target(
    project: Path,
    target_name: str,
    config: dict[str, Any],
    *,
    enabled: bool = False,
    limit: int = 5,
    chain: list[SearchProvider] | None = None,
) -> Path:
    """Write ``research.json`` + ``research.md`` for one target."""
    if not (enabled or search_enabled(config)):
        raise SearchError(
            "Search grounding is opt-in: set `search_enabled: true` in "
            "sartor.yaml or pass --enable-search. Nothing was sent.",
            kind="config",
        )
    try:
        target = load_target(project, target_name)
    except TargetError as exc:
        raise SearchError(str(exc), kind="config") from exc
    active_chain = chain if chain is not None else get_search_chain(config)
    queries = build_queries(target)
    if not queries:
        raise SearchError(
            "Target has no title, organisation, or keywords to search", kind="config"
        )

    blocks: list[dict[str, Any]] = []
    providers_used: list[str] = []
    for query in queries:
        provider_name, results = run_search(query, active_chain, limit=limit)
        if provider_name not in providers_used:
            providers_used.append(provider_name)
        blocks.append({"query": query, "provider": provider_name, "results": results})

    record = {
        "target": target_name,
        "note": CONTEXT_HEADING,
        "providers": providers_used,
        "queries": blocks,
    }
    out_dir = project / "exports" / target_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "research.json"
    out.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        f"# Research — {target.get('title') or target_name}",
        "",
        f"> {CONTEXT_HEADING}",
        "",
    ]
    number = 0
    for block in blocks:
        lines.extend([f"## {block['query']}", "", f"Provider: {block['provider']}", ""])
        for result in block["results"]:
            number += 1
            lines.append(f"{number}. [{result['title']}]({result['url']})")
            if result.get("snippet"):
                lines.append(f"   {result['snippet']}")
        lines.append("")
    (out_dir / "research.md").write_text("\n".join(lines), encoding="utf-8")
    return out
