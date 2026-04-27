"""Minimal OpenRouter chat client with model fallback.

Free OpenRouter models hit rate limits often and have unreliable JSON
output, so this is intentionally simple: one primary model, one fallback.
On 429 or 5xx from the primary, fall back. On fallback failure, raise.

Larger errors / outages aren't this layer's problem — propagate them and
let the caller decide.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from coach import secrets

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_PRIMARY = "google/gemma-3-27b-it:free"
DEFAULT_FALLBACK = "openai/gpt-oss-120b:free"


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


def _resolve_models() -> tuple[str, str]:
    """Return (primary, fallback) model ids, honoring overrides."""
    primary = (
        secrets.get(secrets.OPENROUTER_MODEL)
        or os.environ.get("OPENROUTER_MODEL")
        or DEFAULT_PRIMARY
    )
    fallback = os.environ.get("OPENROUTER_FALLBACK_MODEL", DEFAULT_FALLBACK)
    return primary, fallback


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.4,
    timeout: float = 60.0,
) -> ChatResult:
    """Send a chat completion request, falling back on rate-limit / 5xx."""
    primary, fallback = _resolve_models()
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/tzikos/python-garminconnect",
        "X-OpenRouter-Title": "garmin-coach",
    }

    last_err: Exception | None = None
    for model in _unique_in_order((primary, fallback)):
        body = {"model": model, "messages": messages, "temperature": temperature}
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(OPENROUTER_URL, headers=headers, json=body)
            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                last_err = RuntimeError(
                    f"{model} -> HTTP {resp.status_code}: {resp.text[:200]}"
                )
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return ChatResult(content=content, model_used=model)
        except (httpx.HTTPError, KeyError, IndexError) as e:
            last_err = e
            continue

    raise RuntimeError(f"All models failed. Last error: {last_err}")


def _unique_in_order(items: Iterable[str]) -> list[str]:
    """Preserve order, drop duplicates (so primary == fallback only tries once)."""
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out
