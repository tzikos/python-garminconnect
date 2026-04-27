"""Build an authenticated Garmin client using the local profile + keychain.

Tokens are persisted to ``~/.garmin-coach/garth/`` so subsequent runs skip
the password login. The keyring stores the password for token refresh.
"""

from __future__ import annotations

from coach import secrets
from coach.config import app_dir
from coach.db import session
from coach.models import UserProfile
from garminconnect import Garmin


def _token_dir() -> str:
    """Return the garth tokenstore path, ensuring the dir exists."""
    p = app_dir() / "garth"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def get_client() -> Garmin:
    """Return a logged-in Garmin client.

    Resolution order:
    1. Reuse persisted tokens from ``~/.garmin-coach/garth/`` if present.
    2. Otherwise log in with the profile email + keyring password.

    Raises if no profile exists, no email set, or no password in keyring
    when a fresh login is needed.
    """
    with session() as s:
        prof = s.get(UserProfile, 1)

    if prof is None:
        raise RuntimeError("No profile. Run `coach profile set --name ...` first.")
    if not prof.garmin_email:
        raise RuntimeError(
            "Profile has no Garmin email. "
            "Set with `coach profile set --garmin-email you@example.com`."
        )

    password = secrets.get(secrets.GARMIN_PASSWORD)

    api = Garmin(email=prof.garmin_email, password=password)
    api.login(tokenstore=_token_dir())
    return api
