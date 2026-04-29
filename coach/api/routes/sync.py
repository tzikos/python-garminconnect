"""Push / unpush a plan to Garmin Connect."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coach.api.schemas import SyncResultOut, UnpushResultOut

router = APIRouter(prefix="/api/plans", tags=["sync"])


@router.post("/{plan_id}/push", response_model=SyncResultOut)
def push(plan_id: int) -> SyncResultOut:
    from coach.garmin_client import get_client
    from coach.sync import push_plan

    try:
        api = get_client()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    try:
        result = push_plan(plan_id, api)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    return SyncResultOut(
        plan_id=result.plan_id,
        uploaded=result.uploaded,
        skipped=result.skipped,
        failed=result.failed,
    )


@router.post("/{plan_id}/unpush", response_model=UnpushResultOut)
def unpush(plan_id: int) -> UnpushResultOut:
    from coach.garmin_client import get_client
    from coach.sync import unpush_plan

    try:
        api = get_client()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    try:
        result = unpush_plan(plan_id, api)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    return UnpushResultOut(
        plan_id=result.plan_id,
        removed=result.removed,
        skipped=result.skipped,
        failed=result.failed,
    )
