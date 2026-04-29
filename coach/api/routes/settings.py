"""Settings: secrets + primitive listing."""

from __future__ import annotations

import inspect

from fastapi import APIRouter

from coach import secrets
from coach.api.schemas import (
    PrimitiveDef,
    SetGarminPassword,
    SetOpenRouter,
    SettingsOut,
)
from coach.primitives import PRIMITIVES

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    return SettingsOut(
        has_garmin_password=bool(secrets.get(secrets.GARMIN_PASSWORD)),
        has_openrouter_key=bool(secrets.get(secrets.OPENROUTER_API_KEY)),
        openrouter_model=secrets.get(secrets.OPENROUTER_MODEL),
    )


@router.put("/garmin-password", status_code=204)
def set_garmin_password(body: SetGarminPassword) -> None:
    secrets.set_(secrets.GARMIN_PASSWORD, body.password)


@router.delete("/garmin-password", status_code=204)
def clear_garmin_password() -> None:
    secrets.delete(secrets.GARMIN_PASSWORD)


@router.put("/openrouter", status_code=204)
def set_openrouter(body: SetOpenRouter) -> None:
    secrets.set_(secrets.OPENROUTER_API_KEY, body.api_key)
    if body.model is not None:
        secrets.set_(secrets.OPENROUTER_MODEL, body.model)


@router.delete("/openrouter", status_code=204)
def clear_openrouter() -> None:
    secrets.delete(secrets.OPENROUTER_API_KEY)
    secrets.delete(secrets.OPENROUTER_MODEL)


@router.get("/primitives", response_model=list[PrimitiveDef])
def list_primitives() -> list[PrimitiveDef]:
    """Return registered primitives + their parameter names."""
    out = []
    for name, fn in sorted(PRIMITIVES.items()):
        params = list(inspect.signature(fn).parameters.keys())
        out.append(PrimitiveDef(name=name, params=params))
    return out
