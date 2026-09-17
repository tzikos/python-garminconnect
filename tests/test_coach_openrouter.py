"""Tests for OpenRouter model-chain resolution."""

from __future__ import annotations

import httpx
import pytest

import coach.llm.openrouter as orouter
from coach.llm.openrouter import (
    DEFAULT_FALLBACK,
    DEFAULT_PRIMARY,
    _is_free,
    _is_text_chat,
    _resolve_models,
    free_models,
)


def _model(mid, *, prompt="0", completion="0", ctx=1000, out=("text",), inp=("text",)):
    return {
        "id": mid,
        "context_length": ctx,
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {"input_modalities": list(inp), "output_modalities": list(out)},
    }


@pytest.fixture(autouse=True)
def _no_config(monkeypatch):
    """Ignore whatever is in the real keyring / environment."""
    free_models.cache_clear()
    monkeypatch.setattr(orouter.secrets, "get", lambda _k: None)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_FALLBACK_MODEL", raising=False)
    yield
    free_models.cache_clear()


def _catalogue(monkeypatch, models):
    class _Resp:
        def raise_for_status(self): ...
        def json(self): return {"data": models}

    monkeypatch.setattr(orouter.httpx, "get", lambda *a, **kw: _Resp())


# ------------------------------------------------------------- predicates


def test_free_is_decided_by_price_not_by_the_name():
    assert _is_free(_model("a:free")) is True
    assert _is_free(_model("b", prompt="0", completion="0")) is True
    assert _is_free(_model("c:free", prompt="0.000001")) is False
    assert _is_free({"id": "d"}) is False
    assert _is_free(_model("e", prompt="free")) is False


def test_audio_and_image_generators_are_not_text_chat():
    assert _is_text_chat(_model("chat")) is True
    assert _is_text_chat(_model("music", out=("text", "audio"))) is False
    assert _is_text_chat(_model("draw", out=("image",))) is False
    assert _is_text_chat({"id": "bare"}) is False


# ------------------------------------------------------------- the chain


def test_every_free_text_model_joins_the_chain_widest_context_first(monkeypatch):
    _catalogue(monkeypatch, [
        _model("small:free", ctx=8_000),
        _model("huge:free", ctx=1_000_000),
        _model("paid", prompt="0.5", ctx=999_999),
        _model("medium:free", ctx=100_000),
        _model("music:free", ctx=999_999, out=("text", "audio")),
    ])
    chain = _resolve_models()
    assert chain[0] == DEFAULT_PRIMARY
    assert chain[1] == DEFAULT_FALLBACK
    assert chain[2:] == ["huge:free", "medium:free", "small:free"]
    assert "paid" not in chain
    assert "music:free" not in chain


def test_configured_model_leads_and_is_not_repeated(monkeypatch):
    monkeypatch.setattr(orouter.secrets, "get", lambda _k: "mine:free")
    _catalogue(monkeypatch, [_model("mine:free", ctx=9), _model("other:free", ctx=1)])
    chain = _resolve_models()
    assert chain[0] == "mine:free"
    assert chain.count("mine:free") == 1
    assert "other:free" in chain


def test_fallback_override_takes_second_place(monkeypatch):
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "backup:free")
    _catalogue(monkeypatch, [_model("x:free")])
    chain = _resolve_models()
    assert chain[1] == "backup:free"
    assert DEFAULT_FALLBACK not in chain


def test_unreachable_catalogue_leaves_the_hardcoded_pair(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(orouter.httpx, "get", boom)
    assert free_models() == ()
    assert _resolve_models() == [DEFAULT_PRIMARY, DEFAULT_FALLBACK]


def test_malformed_catalogue_does_not_raise(monkeypatch):
    class _Resp:
        def raise_for_status(self): ...
        def json(self): return {"nope": []}

    monkeypatch.setattr(orouter.httpx, "get", lambda *a, **kw: _Resp())
    assert free_models() == ()


def test_catalogue_is_fetched_once_per_process(monkeypatch):
    calls = []

    class _Resp:
        def raise_for_status(self): ...
        def json(self): return {"data": [_model("a:free")]}

    monkeypatch.setattr(
        orouter.httpx, "get", lambda *a, **kw: (calls.append(1), _Resp())[1]
    )
    free_models()
    free_models()
    assert len(calls) == 1


# -------------------------------------------------------- the chat loop


def _chat_with(monkeypatch, responses):
    """Run chat() against a scripted sequence of (status, body) per model."""
    class _Seen(list):
        """The models tried, with the request bodies hanging off it."""
        bodies: list = []

    seen = _Seen()
    bodies = seen.bodies = []

    class _Resp:
        def __init__(self, status, body):
            self.status_code, self._body = status, body
            self.text = str(body)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("x", request=None, response=None)

        def json(self):
            return self._body

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def post(self, url, headers=None, json=None, **kw):
            seen.append(json["model"])
            bodies.append(json)
            status, body = responses[min(len(seen) - 1, len(responses) - 1)]
            return _Resp(status, body)

    monkeypatch.setattr(
        orouter.secrets,
        "get",
        lambda k: "key" if k == orouter.secrets.OPENROUTER_API_KEY else None,
    )
    monkeypatch.setattr(orouter.httpx, "Client", lambda **kw: _Client())
    seen.bodies = bodies
    return seen


OK = (200, {"choices": [{"message": {"content": "hi"}}]})


def test_a_retired_model_404s_and_the_next_one_is_tried(monkeypatch):
    _catalogue(monkeypatch, [_model("live:free")])
    seen = _chat_with(monkeypatch, [(404, "no such model"), OK])
    result = orouter.chat([{"role": "user", "content": "x"}])
    assert result.model_used == seen[1]
    assert len(seen) == 2


def test_the_whole_free_list_is_walked_before_giving_up(monkeypatch):
    _catalogue(monkeypatch, [_model(f"m{i}:free", ctx=i) for i in range(5)])
    seen = _chat_with(monkeypatch, [(429, "rate limited")])
    with pytest.raises(RuntimeError, match="All 7 models failed"):
        orouter.chat([{"role": "user", "content": "x"}])
    assert len(seen) == 7  # 2 defaults + 5 free


def test_empty_content_is_treated_as_a_failure(monkeypatch):
    """A reasoning model can burn its budget and return nothing usable."""
    _catalogue(monkeypatch, [_model("live:free")])
    empty = (200, {"choices": [{"message": {"content": "   "}}]})
    seen = _chat_with(monkeypatch, [empty, OK])
    result = orouter.chat([{"role": "user", "content": "x"}])
    assert result.model_used == seen[1]
    assert result.content == "hi"


def test_a_200_carrying_an_error_body_moves_on(monkeypatch):
    _catalogue(monkeypatch, [_model("live:free")])
    seen = _chat_with(monkeypatch, [(200, {"error": {"message": "nope"}}), OK])
    assert orouter.chat([{"role": "user", "content": "x"}]).model_used == seen[1]


def test_payment_required_stops_the_chain_instead_of_retrying_every_model(monkeypatch):
    """402 is about the account, not the model — retrying 20 more is noise."""
    _catalogue(monkeypatch, [_model(f"m{i}:free", ctx=i) for i in range(5)])
    seen = _chat_with(monkeypatch, [(402, "Payment Required")])
    with pytest.raises(RuntimeError, match="OpenRouter refused"):
        orouter.chat([{"role": "user", "content": "x"}])
    assert len(seen) == 1


def test_a_model_gated_to_other_apps_403s_and_the_next_one_is_tried(monkeypatch):
    """403 here is about the model ("agentic harnesses only"), not the key."""
    _catalogue(monkeypatch, [_model("live:free")])
    seen = _chat_with(monkeypatch, [(403, "only available on agentic harnesses"), OK])
    assert orouter.chat([{"role": "user", "content": "x"}]).model_used == seen[1]
    assert len(seen) == 2


def test_every_request_turns_reasoning_off_and_asks_for_json(monkeypatch):
    """Reasoning models otherwise burn ~30s and leak the thinking into content."""
    _catalogue(monkeypatch, [_model("live:free")])
    seen = _chat_with(monkeypatch, [OK])
    orouter.chat([{"role": "user", "content": "x"}])
    (body,) = seen.bodies
    assert body["reasoning"] == {"enabled": False}
    assert body["response_format"] == {"type": "json_object"}


def test_the_shared_daily_quota_stops_the_chain_at_the_first_429(monkeypatch):
    """free-models-per-day is account-wide: the other 22 are out too."""
    _catalogue(monkeypatch, [_model(f"m{i}:free", ctx=i) for i in range(5)])
    quota = (429, {"error": {"message": "Rate limit exceeded: free-models-per-day"}})
    seen = _chat_with(monkeypatch, [quota])
    with pytest.raises(RuntimeError, match="free daily quota"):
        orouter.chat([{"role": "user", "content": "x"}])
    assert len(seen) == 1


def test_an_ordinary_429_still_walks_on(monkeypatch):
    """A provider being busy says nothing about the next model."""
    _catalogue(monkeypatch, [_model("live:free")])
    seen = _chat_with(monkeypatch, [(429, "temporarily rate-limited upstream"), OK])
    assert orouter.chat([{"role": "user", "content": "x"}]).model_used == seen[1]


def test_a_model_that_demands_reasoning_is_retried_with_it_on(monkeypatch):
    _catalogue(monkeypatch, [_model("live:free")])
    refusal = (400, {"error": {"message": "Reasoning is mandatory for this endpoint"}})
    seen = _chat_with(monkeypatch, [refusal, OK])
    result = orouter.chat([{"role": "user", "content": "x"}])
    assert seen == [seen[0], seen[0]]  # same model, retried
    assert "reasoning" not in seen.bodies[1]
    assert result.content == "hi"


def test_a_local_endpoint_replaces_openrouter_entirely(monkeypatch):
    """No key, no catalogue, no chain — just the one server you pointed at."""
    monkeypatch.setenv("LOCAL_LLM_URL", "http://localhost:11434/v1/chat/completions")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "gemma3:12b")

    def no_catalogue(*a, **kw):
        raise AssertionError("the OpenRouter catalogue must not be fetched")

    monkeypatch.setattr(orouter.httpx, "get", no_catalogue)
    monkeypatch.setattr(
        orouter, "_api_key", lambda: pytest.fail("no key should be needed")
    )
    seen = _chat_with(monkeypatch, [OK])
    assert orouter.chat([{"role": "user", "content": "x"}]).model_used == "gemma3:12b"
    assert seen == ["gemma3:12b"]
    # `reasoning` is an OpenRouter extension; a local server would choke.
    assert "reasoning" not in seen.bodies[0]
    assert seen.bodies[0]["response_format"] == {"type": "json_object"}


def test_a_local_endpoint_sends_a_key_only_when_one_is_set(monkeypatch):
    """Ollama needs no auth; Groq and friends, on the same vars, do."""
    monkeypatch.setenv("LOCAL_LLM_URL", "https://api.groq.com/openai/v1/chat/completions")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("LOCAL_LLM_KEY", "gsk_test")
    captured = {}

    class _Client:
        def __init__(self, **kw): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def post(self, url, headers=None, json=None, **kw):
            captured["url"], captured["headers"] = url, headers
            return type(
                "R",
                (),
                {
                    "status_code": 200,
                    "text": "",
                    "raise_for_status": lambda self: None,
                    "json": lambda self: OK[1],
                },
            )()

    monkeypatch.setattr(orouter.httpx, "Client", lambda **kw: _Client())
    orouter.chat([{"role": "user", "content": "x"}])
    assert captured["url"].startswith("https://api.groq.com/")
    assert captured["headers"]["Authorization"] == "Bearer gsk_test"
