"""Local web search: we run the lookup, OpenRouter just reads the results.

OpenRouter's web plugin is billed per search (~$4/1k results) even when
the model itself is free, which defeats the point of running free models.
So the search happens here and the text is spliced into the prompt.

Wikipedia is the backend because it is the only keyless source that
actually answers a plain HTTP client: DuckDuckGo's html and lite
endpoints, searx.be and Mojeek all hand back challenge pages or 403.
For race courses it is also the corpus we would have chosen anyway.

ponytail: one backend, no key, no config. If you need the open web
(shoe reviews, race reports), add a Brave Search API key and a second
`_titles`-shaped function — the Source/as_prompt_block seam stays.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

WIKI_API = "https://en.wikipedia.org/w/api.php"
PAGE_URL = "https://en.wikipedia.org/wiki/"

# Wikipedia's API policy asks clients to identify themselves.
USER_AGENT = "garmin-coach (https://github.com/tzikos/python-garminconnect)"

# Two articles of ~4k chars each is plenty of context for a course
# question and leaves room for the rest of the prompt on a free model.
DEFAULT_LIMIT = 2
DEFAULT_CHARS = 4000


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    text: str


def search(
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
    chars: int = DEFAULT_CHARS,
    timeout: float = 15.0,
) -> list[Source]:
    """Top articles for `query` as plain text. Returns [] on any failure.

    Callers treat an empty list as "found nothing" — never as "answer it
    from memory", which is how invented elevation profiles get in.
    """
    with httpx.Client(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        sources = []
        for title in _titles(client, query, limit):
            text = _extract(client, title, chars)
            if text:
                sources.append(
                    Source(
                        title=title,
                        url=PAGE_URL + title.replace(" ", "_"),
                        text=text,
                    )
                )
        return sources


def as_prompt_block(sources: list[Source]) -> str:
    """Render sources as the "search results" block a prompt can carry."""
    return "\n\n".join(
        f"--- SOURCE: {s.title} ({s.url}) ---\n{s.text}" for s in sources
    )


def _get(client: httpx.Client, params: dict[str, str | int]) -> dict:
    try:
        resp = client.get(WIKI_API, params={**params, "format": "json"})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _titles(client: httpx.Client, query: str, limit: int) -> list[str]:
    data = _get(
        client,
        {"action": "query", "list": "search", "srsearch": query, "srlimit": limit},
    )
    hits = (data.get("query") or {}).get("search") or []
    return [h["title"] for h in hits if h.get("title")]


def _extract(client: httpx.Client, title: str, chars: int) -> str:
    """Full plain-text article, truncated.

    `exlimit=1` is deliberate: MediaWiki only serves full (non-intro)
    extracts one page at a time, so batching titles here silently
    downgrades every article to its first paragraph.
    """
    data = _get(
        client,
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exlimit": 1,
            "redirects": 1,
            "titles": title,
        },
    )
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        text = (page.get("extract") or "").strip()
        if text:
            return text[:chars]
    return ""
