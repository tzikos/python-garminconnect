"""Pydantic request/response models for the FastAPI layer.

We import `datetime` qualified rather than `from datetime import date`
because some fields are named `date` and that creates a shadowing
collision when pydantic v2 evaluates the `date | None` annotation.
"""

import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ProfileOut(BaseModel):
    name: str
    garmin_email: Optional[str] = None
    recent_5k_seconds: Optional[int] = None
    threshold_hr: Optional[int] = None
    max_hr: Optional[int] = None
    preferred_days: dict[str, list[int]] = {}
    weekly_hours_target: Optional[float] = None
    notes: Optional[str] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    garmin_email: Optional[str] = None
    recent_5k_seconds: Optional[int] = None
    threshold_hr: Optional[int] = None
    max_hr: Optional[int] = None
    preferred_days: Optional[dict[str, list[int]]] = None
    weekly_hours_target: Optional[float] = None
    notes: Optional[str] = None


class PlanSummary(BaseModel):
    id: int
    name: str
    goal_text: str
    start_date: datetime.date
    end_date: datetime.date
    status: str
    version: int
    workout_count: int
    uploaded_count: int


class WorkoutOut(BaseModel):
    id: int
    plan_id: int
    date: datetime.date
    week_number: int
    sport: str
    title: str
    description: Optional[str] = None
    primitive_type: str
    primitive_params: dict[str, Any]
    garmin_workout_id: Optional[int] = None
    garmin_schedule_id: Optional[int] = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class WarningOut(BaseModel):
    severity: str
    message: str
    dates: list[datetime.date]


class PlanDetail(BaseModel):
    id: int
    name: str
    goal_text: str
    start_date: datetime.date
    end_date: datetime.date
    status: str
    version: int
    structure: dict[str, Any]
    workouts: list[WorkoutOut]
    warnings: list[WarningOut]


class GenerateRequest(BaseModel):
    goal_text: str
    start_date: datetime.date
    end_date: datetime.date
    start_volume_km: float = 25.0
    peak_volume_km: Optional[float] = None
    taper_weeks: int = 2


class GenerateResponse(BaseModel):
    plan: PlanDetail
    model_used: str


class WorkoutCreate(BaseModel):
    plan_id: int
    date: datetime.date
    week_number: int = 1
    sport: str
    title: Optional[str] = None
    description: Optional[str] = None
    primitive_type: str
    primitive_params: dict[str, Any] = {}


class WorkoutUpdate(BaseModel):
    date: Optional[datetime.date] = None
    week_number: Optional[int] = None
    sport: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    primitive_type: Optional[str] = None
    primitive_params: Optional[dict[str, Any]] = None


class PlanCreate(BaseModel):
    name: str
    goal_text: str
    start_date: datetime.date
    end_date: datetime.date


class SyncResultOut(BaseModel):
    plan_id: int
    uploaded: int
    skipped: int
    failed: list[tuple[int, str]]


class UnpushResultOut(BaseModel):
    plan_id: int
    removed: int
    skipped: int
    failed: list[tuple[int, str]]


class SettingsOut(BaseModel):
    has_garmin_password: bool
    has_openrouter_key: bool
    openrouter_model: Optional[str] = None


class SetGarminPassword(BaseModel):
    password: str


class SetOpenRouter(BaseModel):
    api_key: str
    model: Optional[str] = None


class PrimitiveDef(BaseModel):
    name: str
    params: list[str]
