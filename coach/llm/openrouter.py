"""Minimal OpenRouter chat client with model fallback.

Free OpenRouter models hit rate limits constantly and get retired without
notice, so one hardcoded fallback is not enough — and a hardcoded list
goes stale the same way. Instead we ask OpenRouter which models are free
right now and walk the whole list: the configured model first, then every
zero-cost model, widest context first. On 404 / 429 / 5xx, try the next.

Larger errors / outages aren't this layer's problem — propagate them and
let the caller decide.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from coach import secrets

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS_URL = "https://openrouter.ai/api/v1/models"

# Point these at any OpenAI-compatible server to bypass OpenRouter entirely:
#   LOCAL_LLM_URL=http://localhost:11434/v1/chat/completions  (Ollama)
#   LOCAL_LLM_URL=http://localhost:1234/v1/chat/completions   (LM Studio)
#   LOCAL_LLM_MODEL=gemma3:12b
# Useful when the free daily quota is gone; slower and less accurate at
# normalising answers, so it is opt-in rather than an automatic fallback.
# LOCAL_LLM_KEY is optional: Ollama and LM Studio need no auth, but the
# same three vars also point at any OpenAI-compatible cloud free tier
# (Groq, Cerebras, Google AI Studio), which do.
LOCAL_URL_ENV = "LOCAL_LLM_URL"
LOCAL_MODEL_ENV = "LOCAL_LLM_MODEL"
LOCAL_KEY_ENV = "LOCAL_LLM_KEY"

# A 12-week plan is ~10k tokens, which a laptop model emits at a crawl.
LOCAL_TIMEOUT = 900.0

# Substrings OpenRouter puts in error bodies that change what we do next.
DAILY_QUOTA_EXHAUSTED = "free-models-per-day"
REASONING_MANDATORY = "Reasoning is mandatory"

# Tried first, ahead of the catalogue. Both were measured fast on the
# intake prompt (~2-3s) and return valid JSON; the free tier is full of
# models that take 25s or answer in prose, and the catalogue gives no way
# to tell them apart. These rot — when they 404 or crawl, re-measure and
# swap them. Ordering past these two is the catalogue's, widest first.
DEFAULT_PRIMARY = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_FALLBACK = "dots-studio/dots-3-note-preview:free"

@dataclass
class ChatResult:
    content: str
    model_used: str


def _api_key() -> str:
    key = secrets.get(secrets.OPENROUTER_API_KEY) or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "No OpenRouter API key. "
            "Run `coach secrets set-openrouter` or export OPENROUTER_API_KEY."
        )
    return key


def _local_endpoint() -> tuple[str, str] | None:
    """(url, model) when a local server is configured, else None."""
    url = os.environ.get(LOCAL_URL_ENV)
    model = os.environ.get(LOCAL_MODEL_ENV)
    return (url, model) if url and model else None


def _is_free(model: dict[str, Any]) -> bool:
    """True when both prompt and completion cost nothing.

    Checks the price rather than the `:free` id suffix — some zero-cost
    models don't carry the suffix, and the suffix is not a contract.
    """
    pricing = model.get("pricing") or {}
    try:
        return (
            float(pricing.get("prompt", 1)) == 0
            and float(pricing.get("completion", 1)) == 0
        )
    except (TypeError, ValueError):
        return False


def _is_text_chat(model: dict[str, Any]) -> bool:
    """True for plain text-in/text-out models.

    The free tier also carries image and audio generators (Lyria and
    friends) which accept a chat request and return something we can't
    parse. Requiring text as the ONLY output modality filters them out.
    """
    arch = model.get("architecture") or {}
    return (
        "text" in (arch.get("input_modalities") or [])
        and list(arch.get("output_modalities") or []) == ["text"]
    )


@lru_cache(maxsize=1)
def free_models() -> tuple[str, ...]:
    """Every zero-cost model OpenRouter currently lists, widest context first.

    Context width is a rough proxy for "can hold a 12-week plan without
    truncating", which is the failure mode that actually bites here.

    Cached for the life of the process: the catalogue changes on the order
    of days, and this app is a locally-run script. Restart to refresh.
    Returns () on any fetch problem so callers fall back to the constants.
    """
    try:
        resp = httpx.get(MODELS_URL, timeout=20)
        resp.raise_for_status()
        models = resp.json()["data"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return ()

    free = [m for m in models if m.get("id") and _is_free(m) and _is_text_chat(m)]
    free.sort(key=lambda m: m.get("context_length") or 0, reverse=True)
    return tuple(str(m["id"]) for m in free)


def _resolve_models() -> list[str]:
    """The full ordered chain of models to try, best guess first.

    Configured model, then the explicit fallback override, then every free
    model on OpenRouter. Duplicates are dropped, so a configured model that
    is also free is still only tried once.
    """
    configured = (
        secrets.get(secrets.OPENROUTER_MODEL)
        or os.environ.get("OPENROUTER_MODEL")
        or DEFAULT_PRIMARY
    )
    override = os.environ.get("OPENROUTER_FALLBACK_MODEL")
    chain = [configured, override or DEFAULT_FALLBACK, *free_models()]
    return _unique_in_order(c for c in chain if c)


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.4,
    timeout: float = 120.0,
    max_tokens: int = 16000,
) -> ChatResult:
    """Send a chat completion request, falling back on rate-limit / 5xx.

    `max_tokens` is set high (16k) because plan JSON can run ~10k tokens
    for a 12-week multi-sport plan. Free models often default to a low
    output cap and silently truncate — we ask for more than we need.

    JSON mode and no reasoning are unconditional: every caller parses the
    reply as JSON. A model that rejects either fails like any other and
    the chain moves on.

    Web search is not done here: OpenRouter's plugin bills per search even
    on free models, so `coach.llm.websearch` runs it locally and the
    results arrive as ordinary prompt text.
    """
    local = _local_endpoint()
    if local:
        url, models = local[0], [local[1]]
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(LOCAL_KEY_ENV)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        timeout = max(timeout, LOCAL_TIMEOUT)
    else:
        url, models = OPENROUTER_URL, _resolve_models()
        headers = {
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/tzikos/python-garminconnect",
            "X-OpenRouter-Title": "garmin-coach",
        }

    last_err: Exception | None = None
    for model in models:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if not local:
            # Every caller here parses JSON, and the free tier is mostly
            # reasoning models. Left on, they spend 30s thinking and then
            # leak the thinking into `content`, which parses as nothing.
            # Off, the same model answers in under a second. Not an
            # OpenAI-standard field, so local servers never see it.
            body["reasoning"] = {"enabled": False}
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code == 400 and REASONING_MANDATORY in resp.text:
                    # A few endpoints refuse to have reasoning switched off.
                    # Slower and chattier, but a served answer beats none —
                    # and this model may be the last one under the quota.
                    body.pop("reasoning", None)
                    resp = client.post(url, headers=headers, json=body)
            if resp.status_code == 429 and DAILY_QUOTA_EXHAUSTED in resp.text:
                # Account-wide and shared by every free model, so the rest
                # of the chain would just burn more of a quota that is
                # already gone.
                raise RuntimeError(
                    "OpenRouter's free daily quota is used up "
                    "(free-models-per-day). Every free model shares it, so "
                    "there is nothing to fall back to. It resets at 00:00 "
                    "UTC; adding 10 credits raises the cap to 1000 "
                    "requests/day."
                )
            if resp.status_code == 404:
                last_err = RuntimeError(
                    f"{model} -> HTTP 404: no such model on OpenRouter. "
                    "It was probably retired — pick a current one in Settings."
                )
                continue
            if resp.status_code in (401, 402):
                # Account-level, not model-level: a bad key, or a paid
                # feature on an account with no credits. Walking 20 more
                # models just repeats the same refusal 20 times.
                raise RuntimeError(
                    f"OpenRouter refused the request "
                    f"(HTTP {resp.status_code}): {resp.text[:200]}"
                )
            if resp.status_code == 403:
                # Model-level gate, e.g. "only available on agentic
                # harnesses" — someone else's model may still serve us.
                last_err = RuntimeError(
                    f"{model} -> HTTP 403: {resp.text[:200]}"
                )
                continue
            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                last_err = RuntimeError(
                    f"{model} -> HTTP {resp.status_code}: {resp.text[:200]}"
                )
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if not (content or "").strip():
                # Reasoning models sometimes spend the whole output budget in
                # `reasoning` and hand back empty content. That parses as a
                # successful call but is useless downstream, so treat it as a
                # failure and let the next model have a go.
                last_err = RuntimeError(f"{model} -> empty content")
                continue
            return ChatResult(content=content, model_used=model)
        except (httpx.HTTPError, KeyError, IndexError) as e:
            last_err = e
            continue

    raise RuntimeError(
        f"All {len(models)} models failed. Last error: {last_err}"
    )


def _unique_in_order(items: Iterable[str]) -> list[str]:
    """Preserve order, drop duplicates (so primary == fallback only tries once)."""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out
