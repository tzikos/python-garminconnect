"""Offline behavior checks for activity reviews and history-preserving refinement."""

from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

import coach.db as coach_db
from coach.cli import app
from coach.models import ActivityReview, Base, Plan, ScheduledWorkout
from coach.plan_io import export_plan, import_plan
from coach.refine import refine_plan
from coach.review import fetch_pending, list_reviews, save_evaluations
from coach.sync import push_plan, unpush_plan

TODAY = date(2026, 9, 28)
CUTOFF = date(2026, 9, 29)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(coach_db, "_engine", engine)
    monkeypatch.setattr(coach_db, "_SessionLocal", factory)
    return factory


@pytest.fixture
def plan_id(db):
    return import_plan(
        {
            "name": "Autumn",
            "goal_text": "Build endurance",
            "start_date": "2026-09-21",
            "end_date": "2026-10-04",
            "weekly_structure": [
                {
                    "week_number": 1,
                    "theme": "Base",
                    "target_volume_km": 20,
                    "workouts": [
                        {
                            "date": day,
                            "sport": "running",
                            "title": "Easy 30",
                            "primitive_type": "easy_run",
                            "primitive_params": {"duration_min": 30},
                        }
                        for day in (
                            "2026-09-21",
                            "2026-09-28",
                            "2026-09-29",
                            "2026-10-02",
                        )
                    ],
                }
            ],
        }
    )[0]


class FakeGarmin:
    def __init__(self):
        self.activities = [
            {
                "activityId": 101,
                "startTimeLocal": "2026-09-21 09:00:00",
                "distance": 5000,
            },
            {
                "activityId": 102,
                "startTimeLocal": "2026-09-28 09:00:00",
                "distance": 5000,
            },
        ]
        self.detail_calls = []
        self.deleted = []
        self.scheduled = []
        self.fail_splits = False

    def get_activities_by_date(self, start, end):
        self.range = (start, end)
        return self.activities

    def get_activity(self, activity_id):
        self.detail_calls.append(activity_id)
        return {"summaryDTO": {"duration": 1800}}

    def get_activity_splits(self, activity_id):
        if self.fail_splits:
            raise RuntimeError("temporarily unavailable")
        return {"lapDTOs": []}

    def unschedule_workout(self, schedule_id):
        pass

    def delete_workout(self, workout_id):
        self.deleted.append(workout_id)

    def upload_workout(self, payload):
        return {"workoutId": 900 + len(self.scheduled)}

    def schedule_workout(self, workout_id, when):
        self.scheduled.append(when)
        return {"workoutScheduleId": 1900 + len(self.scheduled)}


def assessment(activity_id=101, **kwargs):
    return {
        "activity_id": activity_id,
        "assessment": "Controlled easy effort.",
        "recommendation": "Keep current load.",
        **kwargs,
    }


def proposal(plan_id):
    out = export_plan(plan_id)
    out["refinement_reason"] = (
        "Activity 101 supports a small increase in easy duration."
    )
    out["weekly_structure"][0]["workouts"][-1]["primitive_params"]["duration_min"] = 35
    return out


def test_evaluate_skips_saved_ids_but_discovers_late_uploads(db, plan_id):
    api = FakeGarmin()
    first = fetch_pending(plan_id, api, today=TODAY)
    assert api.range == ("2026-09-21", "2026-09-28")
    assert len(first["pending"]) == 2
    wid = export_plan(plan_id)["weekly_structure"][0]["workouts"][0]["workout_id"]
    assert save_evaluations(plan_id, [assessment(workout_id=wid)]) == {
        "saved": 1,
        "skipped": 0,
    }
    api.activities += [
        {"activityId": 103, "startTimeLocal": "2026-09-22 10:00:00"},
        api.activities[0],
        {"activityId": 104, "startTimeLocal": "2026-09-29 10:00:00"},
        {"activityId": 105, "startTimeLocal": "2026-09-20 10:00:00"},
    ]
    api.detail_calls.clear()
    second = fetch_pending(plan_id, api, today=TODAY)
    assert second["skipped"] == 1
    assert {r["activity_id"] for r in second["pending"]} == {102, 103}
    assert "101" not in api.detail_calls
    assert save_evaluations(plan_id, [assessment()]) == {"saved": 0, "skipped": 1}
    saved = list_reviews(plan_id)[0]
    assert saved["evaluation"]["planned_workout"]["workout_id"] == wid
    assert saved["evaluated_at"]


def test_fetch_failure_does_not_mark_reviewed_and_retry_recovers(db, plan_id):
    api = FakeGarmin()
    api.fail_splits = True
    first = fetch_pending(plan_id, api, today=TODAY)
    assert first["pending"][0]["evidence"]["errors"]
    assert all(r["evaluation"] is None for r in list_reviews(plan_id))
    api.fail_splits = False
    retry = fetch_pending(plan_id, api, today=TODAY)
    assert not retry["pending"][0]["evidence"]["errors"]
    with db() as s:
        assert s.query(ActivityReview).count() == 2


def test_future_and_finished_plan_bounds(db, plan_id):
    api = FakeGarmin()
    assert fetch_pending(plan_id, api, today=date(2026, 9, 1))["pending"] == []
    assert not hasattr(api, "range")
    fetch_pending(plan_id, api, today=date(2026, 11, 1))
    assert api.range == ("2026-09-21", "2026-10-04")


def test_record_batch_rolls_back_if_one_review_is_invalid(db, plan_id):
    fetch_pending(plan_id, FakeGarmin(), today=TODAY)
    with pytest.raises(ValueError, match="non-empty"):
        save_evaluations(plan_id, [assessment(), assessment(102, assessment="")])
    assert all(r["evaluation"] is None for r in list_reviews(plan_id))
    with pytest.raises(ValueError, match="not been fetched"):
        save_evaluations(plan_id, [assessment(999)])


def test_plan_deletion_cleans_up_reviews_before_id_can_be_reused(db, plan_id):
    fetch_pending(plan_id, FakeGarmin(), today=TODAY)
    save_evaluations(plan_id, [assessment()])
    with db() as s:
        s.delete(s.get(Plan, plan_id))
        s.commit()
        assert s.query(ActivityReview).count() == 0


def test_existing_database_adds_review_table_without_losing_plans(db, plan_id):
    ActivityReview.__table__.drop(coach_db.engine())
    coach_db.init_db()
    fetch_pending(plan_id, FakeGarmin(), today=TODAY)
    assert len(list_reviews(plan_id)) == 2
    assert export_plan(plan_id)["name"] == "Autumn"


def test_refine_keeps_past_and_unchanged_rows_and_archives_prior_plan(db, plan_id):
    before = export_plan(plan_id)
    old_ids = [w["workout_id"] for w in before["weekly_structure"][0]["workouts"]]
    with db() as s:
        past = s.get(ScheduledWorkout, old_ids[0])
        past.status, past.garmin_workout_id = "uploaded", 100
        s.commit()
    fetch_pending(plan_id, FakeGarmin(), today=TODAY)
    save_evaluations(plan_id, [assessment(workout_id=old_ids[0])])
    proposed = proposal(plan_id)
    preview = refine_plan(plan_id, proposed, CUTOFF, dry_run=True, today=TODAY)
    assert len(preview["add"]) == len(preview["remove"]) == 1
    assert not preview["applied"]
    assert export_plan(plan_id)["version"] == 1
    result = refine_plan(plan_id, proposed, CUTOFF, today=TODAY)
    assert result["applied"] and result["version"] == 2
    with db() as s:
        for wid in old_ids[:3]:
            assert s.get(ScheduledWorkout, wid).primitive_params == {"duration_min": 30}
        assert s.get(ScheduledWorkout, old_ids[0]).garmin_workout_id == 100
        history = s.get(Plan, plan_id).structure["refinements"]
        assert history[0]["before"][-1]["primitive_params"] == {"duration_min": 30}
    assert list_reviews(plan_id)[0]["evaluation"]["plan_version"] == 1
    with pytest.raises(ValueError, match="Stale"):
        refine_plan(plan_id, proposed, CUTOFF, today=TODAY)


@pytest.mark.parametrize(
    "change", ["past", "today", "goal", "outside", "uploaded", "completed"]
)
def test_refinement_guards_leave_plan_untouched(db, plan_id, change):
    proposed = proposal(plan_id)
    workouts = proposed["weekly_structure"][0]["workouts"]
    if change in ("past", "today"):
        workouts[0 if change == "past" else 1]["title"] = "Altered history"
    elif change == "goal":
        proposed["goal_text"] = "Different goal"
    elif change == "outside":
        workouts[-1]["date"] = "2026-12-01"
    else:
        with db() as s:
            row = s.get(ScheduledWorkout, workouts[-1]["workout_id"])
            row.status = change
            if change == "uploaded":
                row.garmin_workout_id = 200
            s.commit()
    before = deepcopy(export_plan(plan_id))
    with pytest.raises(ValueError):
        refine_plan(plan_id, proposed, CUTOFF, today=TODAY)
    assert export_plan(plan_id) == before


def test_noop_refinement_and_invalid_cutoff(db, plan_id):
    proposed = export_plan(plan_id)
    proposed["refinement_reason"] = "No change warranted"
    assert not refine_plan(plan_id, proposed, CUTOFF, today=TODAY)["applied"]
    assert export_plan(plan_id)["version"] == 1
    with pytest.raises(ValueError, match="after today"):
        refine_plan(plan_id, proposed, TODAY, today=TODAY)


def test_date_scoped_sync_preserves_history_and_completed_rows(db, plan_id):
    api = FakeGarmin()
    with db() as s:
        rows = s.query(ScheduledWorkout).order_by(ScheduledWorkout.date).all()
        for i, row in enumerate(rows):
            row.status, row.garmin_workout_id = "uploaded", i + 100
        s.commit()
    result = unpush_plan(plan_id, api, from_date=CUTOFF)
    assert result.removed == 2
    assert api.deleted == [102, 103]
    with db() as s:
        # Completed rows must never be uploaded even when after the cutoff.
        row = s.query(ScheduledWorkout).filter_by(date=date(2026, 10, 2)).one()
        row.status = "completed"
        s.commit()
    pushed = push_plan(plan_id, api, from_date=CUTOFF)
    assert pushed.uploaded == 1
    assert api.scheduled == ["2026-09-29"]


def test_cli_review_record_and_unpush_dry_run(db, plan_id, tmp_path, monkeypatch):
    import json

    import coach.garmin_client

    monkeypatch.setattr(
        coach.garmin_client, "get_client", lambda: pytest.fail("Unexpected network")
    )
    runner = CliRunner()
    fetch_pending(plan_id, FakeGarmin(), today=TODAY)
    file = tmp_path / "evaluations.json"
    file.write_text(json.dumps([assessment()]))
    recorded = runner.invoke(
        app, ["review", "record", str(file), "--plan-id", str(plan_id)]
    )
    assert recorded.exit_code == 0, recorded.output
    assert json.loads(recorded.output)["saved"] == 1
    listed = runner.invoke(app, ["review", "list", "--plan-id", str(plan_id)])
    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["evaluation"]
    with db() as s:
        for row in s.query(ScheduledWorkout).all():
            row.status, row.garmin_workout_id = "uploaded", row.id + 100
        s.commit()
    preview = runner.invoke(
        app,
        [
            "sync",
            "unpush",
            "--plan-id",
            str(plan_id),
            "--from-date",
            "2026-09-29",
            "--dry-run",
        ],
    )
    assert preview.exit_code == 0, preview.output
    assert "2026-09-21" not in preview.output
    assert "2026-09-29" in preview.output
