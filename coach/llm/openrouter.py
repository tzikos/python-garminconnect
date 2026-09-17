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

# Only used when the model catalogue can't be fetched (offline, or OpenRouter
# down). Both are free models that existed when this was written; if the
# catalogue is reachable, what it says wins over these.
DEFAULT_PRIMARY = "google/gemma-4-31b-it:free"
DEFAULT_FALLBACK = "nvidia/nemotron-3-super-120b-a12b:free"

# Web-search results spliced into the prompt by OpenRouter's web plugin.
# 5 is enough to characterise a race course without blowing the context.
WEB_MAX_RESULTS = 5


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
    web: bool = False,
) -> ChatResult:
    """Send a chat completion request, falling back on rate-limit / 5xx.

    `max_tokens` is set high (16k) because plan JSON can run ~10k tokens
    for a 12-week multi-sport plan. Free models often default to a low
    output cap and silently truncate — we ask for more than we need.

    `web=True` enables OpenRouter's built-in web plugin, which runs the
    search and splices results into the prompt server-side. That keeps us
    on one API key and one dependency instead of adding a search provider.
    """
    models = _resolve_models()
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
        }
        if web:
            body["plugins"] = [{"id": "web", "max_results": WEB_MAX_RESULTS}]
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(OPENROUTER_URL, headers=headers, json=body)
            if resp.status_code == 404:
                last_err = RuntimeError(
                    f"{model} -> HTTP 404: no such model on OpenRouter. "
                    "It was probably retired — pick a current one in Settings."
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
