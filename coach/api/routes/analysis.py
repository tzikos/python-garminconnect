"""Read-only performance analysis over the local activity store."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from coach.analysis import activity_streams, list_activities, list_wellness

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ponytail: returns everything and the page filters client-side; a few
# thousand rows is fine, add date params when it is not.
@router.get("/activities")
def activities() -> list[dict[str, Any]]:
    return list_activities()


@router.get("/wellness")
def wellness() -> list[dict[str, Any]]:
    return list_wellness()


@router.get("/activities/{activity_id}/streams")
def streams(activity_id: int) -> dict[str, Any]:
    result = activity_streams(activity_id)
    if result is None:
        raise HTTPException(404, f"Activity {activity_id} not stored")
    return result
