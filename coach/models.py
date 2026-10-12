"""SQLAlchemy ORM models for the coach app.

Design notes:
- UserProfile is effectively a singleton for the local-script phase (id=1).
- A ScheduledWorkout stores a primitive_type + primitive_params JSON envelope.
  The actual conversion to a Garmin workout happens at sync time via the
  registry in coach.primitives. This keeps the DB sport-agnostic and makes
  manual editing (json.dumps -> edit -> reload) straightforward.
- Strength sessions live inside primitive_params for now; a separate movement
  library / progression tracker will be added once we have a real use case.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class UserProfile(Base):
    """The local user. Singleton row (id=1) for now."""

    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    garmin_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Fitness benchmarks (all optional; populated via `coach profile set`)
    recent_5k_seconds: Mapped[int | None] = mapped_column(nullable=True)
    threshold_hr: Mapped[int | None] = mapped_column(nullable=True)
    max_hr: Mapped[int | None] = mapped_column(nullable=True)

    # Scheduling preferences (JSON: e.g. {"running": [1, 3, 5], "strength": [2, 4]}
    # where 0 = Monday)
    preferred_days: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    weekly_hours_target: Mapped[float | None] = mapped_column(nullable=True)

    # Sports the user actively trains; drives prompt sections + UI tiles.
    # e.g. ["running", "strength", "calisthenics"]
    enabled_sports: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Per-sport benchmarks. Schema deliberately loose so we can extend
    # without migrations. Top-level keys match values in enabled_sports.
    # See coach.sports for the canonical field names.
    sport_profiles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Free-form context the LLM gets verbatim (injuries, equipment, etc.)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Plan(Base):
    """A training plan over a date range, targeting a goal."""

    __tablename__ = "plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    goal_text: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(default=1)

    # Free-form structure the LLM produces (week-level themes, weekly volume
    # targets per sport). Schema deliberately loose.
    structure: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    workouts: Mapped[list[ScheduledWorkout]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[ActivityReview]] = relationship(cascade="all, delete-orphan")


class ScheduledWorkout(Base):
    """One workout placed on a date, ready for review and Garmin upload."""

    __tablename__ = "scheduled_workout"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id"))
    date: Mapped[date] = mapped_column(Date, index=True)
    week_number: Mapped[int] = mapped_column(default=1)
    sport: Mapped[str] = mapped_column(String(32))  # "running", "strength", ...
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The primitive registry key (e.g. "easy_run") + its kwargs.
    # primitives.PRIMITIVES[primitive_type](**primitive_params) -> Garmin workout.
    primitive_type: Mapped[str] = mapped_column(String(64))
    primitive_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Set after upload to Garmin.
    garmin_workout_id: Mapped[int | None] = mapped_column(nullable=True)
    garmin_schedule_id: Mapped[int | None] = mapped_column(nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="planned")
    # planned -> uploaded -> completed (phase 2)

    plan: Mapped[Plan] = relationship(back_populates="workouts")


class IntakeConversation(Base):
    """A plan-intake interview, saved after every turn so it can be resumed.

    The interview is otherwise pure browser state: a refresh, a crash or one
    failed LLM call used to lose the whole conversation. `history` is the
    transcript exactly as the client replays it, so resuming is just handing
    it back.
    """

    __tablename__ = "intake_conversation"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="New plan")

    history: Mapped[list[Any]] = mapped_column(JSON, default=list)
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # The question left on screen, so a resume reopens where it stopped.
    question: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ready: Mapped[bool] = mapped_column(default=False)
    summary: Mapped[str] = mapped_column(Text, default="")

    # Set once the interview has produced a plan.
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ActivityReview(Base):
    """Cached Garmin evidence and a durable, plan-scoped coaching evaluation.

    Activity IDs survive plan edits. Planned workout context is a snapshot,
    not a foreign key to a row that a later import might replace.
    """

    __tablename__ = "activity_review"

    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id"), primary_key=True)
    activity_id: Mapped[int] = mapped_column(primary_key=True)
    activity_date: Mapped[date] = mapped_column(Date)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Activity(Base):
    """Every Garmin activity with its full recording, independent of plans.

    `details` is the zlib-compressed `/details` response (all sample streams
    at full resolution). `metrics` is derived from it by coach.analysis and
    can be rebuilt any time with `coach analysis recompute`.
    """

    __tablename__ = "activity"

    activity_id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    sport: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    laps: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    weather: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    details: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_version: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WellnessDay(Base):
    """One day of recovery signals (resting HR, HRV, sleep, stress, body battery)."""

    __tablename__ = "wellness_day"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
