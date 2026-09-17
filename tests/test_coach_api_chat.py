"""Tests for the chat-intake API routes."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import coach.db as coach_db
from coach.api.routes.plans import _end_date_from, _goal_text_from
from coach.models import Base, UserProfile


@pytest.fixture
def client(monkeypatch):
    # StaticPool: TestClient serves requests on a worker thread, and the
    # default sqlite pool hands a new thread a new (empty) :memory: database.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(coach_db, "_engine", engine)
    monkeypatch.setattr(coach_db, "_SessionLocal", SessionLocal)
    with SessionLocal() as s:
        s.add(UserProfile(id=1, name="Tzikos", recent_5k_seconds=1350,
                          enabled_sports=["running"]))
        s.commit()
    from coach.api.app import app

    return TestClient(app)


def test_chat_turn_returns_a_question(client, monkeypatch):
    payload = json.dumps({
        "note": "Nice.",
        "facts": {"goal_type": "race"},
        "question": {"id": "race_name", "text": "Which race?", "kind": "text"},
        "ready": False,
        "summary": "",
    })
    monkeypatch.setattr(
        "coach.llm.intake.chat",
        lambda messages, **kw: type("R", (), {"content": payload, "model_used": "m"})(),
    )
    r = client.post("/api/plans/chat", json={"history": [], "facts": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["question"]["text"] == "Which race?"
    assert body["ready"] is False


def test_chat_turn_surfaces_llm_failure_as_400(client, monkeypatch):
    def boom(messages, **kw):
        raise RuntimeError("No OpenRouter API key.")

    monkeypatch.setattr("coach.llm.intake.chat", boom)
    r = client.post("/api/plans/chat", json={"history": [], "facts": {}})
    assert r.status_code == 400
    assert "OpenRouter" in r.json()["detail"]


def test_generate_from_chat_stores_the_interview_on_the_plan(client, monkeypatch):
    plan_json = json.dumps({
        "name": "Athens Build",
        "weekly_structure": [{
            "week_number": 1,
            "theme": "Base",
            "workouts": [{
                "date": "2026-09-21", "sport": "running",
                "primitive_type": "easy_run", "title": "Easy 40",
                "primitive_params": {"duration_min": 40},
            }],
        }],
    })
    monkeypatch.setattr(
        "coach.llm.planner.chat",
        lambda messages, **kw: type("R", (), {"content": plan_json, "model_used": "m"})(),
    )
    facts = {"race_name": "Athens Marathon", "race_date": "2026-11-08",
             "race_research": {"profile": "hilly"}}
    r = client.post("/api/plans/chat/generate", json={
        "facts": facts, "start_date": "2026-09-21",
    })
    assert r.status_code == 200, r.text
    plan_id = r.json()["plan"]["id"]

    detail = client.get(f"/api/plans/{plan_id}").json()
    assert detail["structure"]["intake"]["race_name"] == "Athens Marathon"
    # End date came from the race, not the 12-week default.
    assert detail["end_date"] == "2026-11-08"


def test_generate_from_chat_rejects_an_inverted_window(client):
    r = client.post("/api/plans/chat/generate", json={
        "facts": {}, "start_date": "2026-09-21", "end_date": "2026-09-01",
    })
    assert r.status_code == 400


# --------------------------------------------------------- derivations


def test_goal_text_prefers_the_official_race_name():
    goal = _goal_text_from({
        "race_name": "athens",
        "race_date": "2026-11-08",
        "race_distance_km": 42.2,
        "race_target_seconds": 3 * 3600 + 30 * 60,
        "race_research": {"race_official_name": "Athens Marathon"},
    })
    assert "Athens Marathon" in goal
    assert "2026-11-08" in goal
    assert "3:30:00" in goal


def test_goal_text_without_a_race():
    assert _goal_text_from({"goal_type": "fitness"}) == "fitness"
    assert _goal_text_from({}) == "General fitness"


def test_end_date_falls_back_when_the_race_date_is_junk_or_past():
    start = date(2026, 9, 21)
    twelve_weeks = date(2026, 12, 14)
    assert _end_date_from({"race_date": "not-a-date"}, start) == twelve_weeks
    assert _end_date_from({"race_date": "2020-01-01"}, start) == twelve_weeks
    assert _end_date_from({}, start) == twelve_weeks
    assert _end_date_from({"race_date": "2026-11-08"}, start) == date(2026, 11, 8)


# ------------------------------------------------- conversation persistence


def _stub_turn(monkeypatch, **over):
    """Make the next chat turn return a fixed payload."""
    body = {
        "note": "Nice.",
        "facts": {"goal_type": "race", "race_name": "Athens Marathon"},
        "question": {"id": "race_date", "text": "When?", "kind": "text"},
        "ready": False,
        "summary": "",
    }
    body.update(over)
    monkeypatch.setattr(
        "coach.llm.intake.chat",
        lambda messages, **kw: type(
            "R", (), {"content": json.dumps(body), "model_used": "m"}
        )(),
    )
    monkeypatch.setattr("coach.llm.intake.websearch.search", lambda *a, **kw: [])


def test_a_turn_is_saved_and_can_be_read_back(client, monkeypatch):
    _stub_turn(monkeypatch)
    r = client.post("/api/plans/chat", json={"history": [], "facts": {}})
    conv_id = r.json()["conversation_id"]

    got = client.get(f"/api/plans/chat/conversations/{conv_id}").json()
    assert got["title"] == "Athens Marathon"  # named from the facts
    assert got["question"]["id"] == "race_date"  # resumes where it stopped
    assert got["facts"]["race_name"] == "Athens Marathon"
    assert got["history"][-1] == {"role": "assistant", "content": "Nice."}


def test_continuing_a_conversation_updates_it_instead_of_forking(
    client, monkeypatch
):
    _stub_turn(monkeypatch)
    first = client.post("/api/plans/chat", json={"history": [], "facts": {}}).json()

    _stub_turn(monkeypatch, note="Got it.", ready=True, question=None)
    second = client.post(
        "/api/plans/chat",
        json={
            "history": [
                {"role": "assistant", "content": "Nice."},
                {"role": "user", "content": "Athens Marathon"},
            ],
            "facts": first["facts"],
            "conversation_id": first["conversation_id"],
        },
    ).json()

    assert second["conversation_id"] == first["conversation_id"]
    assert len(client.get("/api/plans/chat/conversations").json()) == 1
    got = client.get(
        f"/api/plans/chat/conversations/{first['conversation_id']}"
    ).json()
    assert got["ready"] is True
    assert got["question"] is None
    assert len(got["history"]) == 3


def test_a_failed_turn_still_leaves_the_conversation_resumable(
    client, monkeypatch
):
    """The 400 that used to end the interview must not lose it."""
    _stub_turn(monkeypatch)
    first = client.post("/api/plans/chat", json={"history": [], "facts": {}}).json()

    def boom(messages, **kw):
        raise RuntimeError("OpenRouter refused the request (HTTP 402)")

    monkeypatch.setattr("coach.llm.intake.chat", boom)
    failed = client.post(
        "/api/plans/chat",
        json={
            "history": [{"role": "assistant", "content": "Nice."}],
            "facts": first["facts"],
            "conversation_id": first["conversation_id"],
        },
    )
    assert failed.status_code == 400

    got = client.get(
        f"/api/plans/chat/conversations/{first['conversation_id']}"
    ).json()
    assert got["facts"]["race_name"] == "Athens Marathon"
    assert got["question"]["id"] == "race_date"


def test_conversations_are_listed_newest_first_and_can_be_deleted(
    client, monkeypatch
):
    _stub_turn(monkeypatch)
    a = client.post("/api/plans/chat", json={"history": [], "facts": {}}).json()
    _stub_turn(monkeypatch, facts={"race_name": "Berlin Marathon"})
    b = client.post("/api/plans/chat", json={"history": [], "facts": {}}).json()

    listed = client.get("/api/plans/chat/conversations").json()
    assert [c["id"] for c in listed] == [b["conversation_id"], a["conversation_id"]]
    assert listed[0]["title"] == "Berlin Marathon"
    assert listed[0]["turns"] == 1

    assert client.delete(
        f"/api/plans/chat/conversations/{a['conversation_id']}"
    ).status_code == 204
    assert len(client.get("/api/plans/chat/conversations").json()) == 1
    assert client.get(
        f"/api/plans/chat/conversations/{a['conversation_id']}"
    ).status_code == 404


def test_generating_links_the_plan_back_to_its_interview(client, monkeypatch):
    _stub_turn(monkeypatch)
    conv_id = client.post(
        "/api/plans/chat", json={"history": [], "facts": {}}
    ).json()["conversation_id"]

    from coach.llm import planner

    def fake_generate(**kwargs):
        from coach.db import session as db_session
        from coach.models import Plan

        with db_session() as s:
            plan = Plan(
                name="P",
                goal_text="g",
                start_date=date(2026, 1, 5),
                end_date=date(2026, 3, 30),
            )
            s.add(plan)
            s.flush()
            pid = plan.id
        return type("R", (), {"plan_id": pid, "model_used": "m", "warnings": []})()

    monkeypatch.setattr("coach.api.routes.plans.generate_plan", fake_generate, raising=False)
    monkeypatch.setattr(planner, "generate_plan", fake_generate)
    monkeypatch.setattr("coach.llm.generate_plan", fake_generate)

    r = client.post(
        "/api/plans/chat/generate",
        json={
            "facts": {"race_name": "Athens Marathon"},
            "start_date": "2026-01-05",
            "conversation_id": conv_id,
        },
    )
    assert r.status_code == 200
    assert client.get(
        f"/api/plans/chat/conversations/{conv_id}"
    ).json()["plan_id"] is not None
