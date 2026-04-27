"""OS-keychain wrapper for credentials.

Stored under service "garmin-coach" with three known keys:
- garmin_password: the user's Garmin Connect password
- openrouter_api_key: API key for OpenRouter (LLM)
- openrouter_model: optional model override (e.g. "google/gemma-3-27b-it:free")

We use `keyring` so secrets don't end up in the SQLite DB or env files.
"""

from __future__ import annotations

import keyring

SERVICE = "garmin-coach"

GARMIN_PASSWORD = "garmin_password"
OPENROUTER_API_KEY = "openrouter_api_key"
OPENROUTER_MODEL = "openrouter_model"


def get(key: str) -> str | None:
    """Read a secret from the keychain."""
    return keyring.get_password(SERVICE, key)


def set_(key: str, value: str) -> None:
    """Write a secret to the keychain."""
    keyring.set_password(SERVICE, key, value)


def delete(key: str) -> None:
    """Remove a secret if present (no-op if missing)."""
    try:
        keyring.delete_password(SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass
