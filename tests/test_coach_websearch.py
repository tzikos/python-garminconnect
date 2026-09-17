"""Tests for the local (Wikipedia-backed) web search."""

from __future__ import annotations

import httpx
import pytest

import coach.llm.websearch as ws


def _client(monkeypatch, handler):
    """Route every websearch HTTP GET through `handler(params) -> body`."""
    seen = []

    class _Resp:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self): ...

        def json(self):
            if isinstance(self._body, Exception):
                raise self._body
            return self._body

    class _Client:
        def __init__(self, **kw): ...
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            seen.append(params)
            body = handler(params)
            if isinstance(body, Exception) and not isinstance(body, ValueError):
                raise body
            return _Resp(body)

    monkeypatch.setattr(ws.httpx, "Client", _Client)
    return seen


def _hits(*titles):
    return {"query": {"search": [{"title": t} for t in titles]}}


def _page(text):
    return {"query": {"pages": {"1": {"extract": text}}}}


def _wiki(monkeypatch, *, titles=("Athens Classic Marathon",), text="Long climb."):
    def handler(params):
        return _hits(*titles) if params.get("list") == "search" else _page(text)

    return _client(monkeypatch, handler)


def test_a_hit_comes_back_as_text_with_a_reachable_url(monkeypatch):
    _wiki(monkeypatch)
    (source,) = ws.search("Athens Marathon")
    assert source.title == "Athens Classic Marathon"
    assert source.url == "https://en.wikipedia.org/wiki/Athens_Classic_Marathon"
    assert source.text == "Long climb."


def test_full_articles_are_requested_one_at_a_time(monkeypatch):
    """exlimit>1 silently downgrades every extract to its intro."""
    seen = _wiki(monkeypatch, titles=("A", "B"))
    assert len(ws.search("x", limit=2)) == 2
    extracts = [p for p in seen if p.get("prop") == "extracts"]
    assert len(extracts) == 2
    assert all(p["exlimit"] == 1 and p["explaintext"] == 1 for p in extracts)


def test_long_articles_are_truncated(monkeypatch):
    _wiki(monkeypatch, text="x" * 10_000)
    assert len(ws.search("x", chars=500)[0].text) == 500


def test_an_empty_article_is_dropped_rather_than_passed_on(monkeypatch):
    _wiki(monkeypatch, text="   ")
    assert ws.search("x") == []


@pytest.mark.parametrize(
    "boom", [httpx.ConnectError("offline"), ValueError("not json")]
)
def test_a_broken_backend_returns_nothing_instead_of_raising(monkeypatch, boom):
    _client(monkeypatch, lambda params: boom)
    assert ws.search("x") == []


def test_no_hits_means_no_sources_and_no_article_fetch(monkeypatch):
    seen = _client(monkeypatch, lambda params: _hits())
    assert ws.search("nothing here") == []
    assert len(seen) == 1


def test_the_prompt_block_carries_title_url_and_text(monkeypatch):
    _wiki(monkeypatch)
    block = ws.as_prompt_block(ws.search("Athens Marathon"))
    assert "Athens Classic Marathon" in block
    assert "https://en.wikipedia.org/wiki/Athens_Classic_Marathon" in block
    assert "Long climb." in block
