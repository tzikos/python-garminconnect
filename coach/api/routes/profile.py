"""GET / PUT /api/profile."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coach.api.schemas import ProfileOut, ProfileUpdate
from coach.db import session
from coach.models import UserProfile

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _to_out(p: UserProfile) -> ProfileOut:
    return ProfileOut(
        name=p.name,
        garmin_email=p.garmin_email,
        recent_5k_seconds=p.recent_5k_seconds,
        threshold_hr=p.threshold_hr,
        max_hr=p.max_hr,
        preferred_days=p.preferred_days or {},
        weekly_hours_target=p.weekly_hours_target,
        notes=p.notes,
    )


@router.get("", response_model=ProfileOut)
def get_profile() -> ProfileOut:
    with session() as s:
        prof = s.get(UserProfile, 1)
        if prof is None:
            raise HTTPException(status_code=404, detail="No profile yet")
        return _to_out(prof)


@router.put("", response_model=ProfileOut)
def update_profile(update: ProfileUpdate) -> ProfileOut:
    with session() as s:
        prof = s.get(UserProfile, 1)
        if prof is None:
            if not update.name:
                raise HTTPException(400, "First-time setup requires a name")
            prof = UserProfile(id=1, name=update.name)
            s.add(prof)

        for field, value in update.model_dump(exclude_unset=True).items():
            setattr(prof, field, value)
        s.flush()
        return _to_out(prof)
