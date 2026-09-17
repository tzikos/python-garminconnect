"""Tests for the conversational plan intake, with stubbed chat responses."""

from __future__ import annotations

import json

import pytest

from coach.llm.intake import MAX_QUESTIONS, next_turn, research_race
from coach.llm.openrouter import ChatResult
from coach.llm.prompts import build_intake_prompt, render_intake_facts

PROFILE = {
    "name": "Tzikos",
    "recent_5k_seconds": 1350,
    "enabled_sports": ["running", "strength"],
}


def _turn_json(**over):
    body = {
        "note": "Got it.",
        "facts": {"goal_type": "race"},
        "question": {
            "id": "race_name",
            "text": "Which race?",
            "kind": "text",
            "options": [],
        },
        "ready": False,
        "summary": "",
    }
    body.update(over)
    return json.dumps(body)


def _stub(*payloads):
    """Return a chat_fn that yields each payload in order, recording calls."""
    calls = []

    def chat_fn(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        payload = payloads[min(len(calls) - 1, len(payloads) - 1)]
        return ChatResult(content=payload, model_used="stub/model")

    chat_fn.calls = calls
    return chat_fn


# ----------------------------------------------------------- interviewing


def test_first_turn_returns_a_question():
    turn = next_turn(history=[], profile=PROFILE, chat_fn=_stub(_turn_json()))
    assert turn.ready is False
    assert turn.question["id"] == "race_name"
    assert turn.facts["goal_type"] == "race"
    assert turn.model_used == "stub/model"


def test_known_facts_survive_a_turn_that_omits_them():
    """The model returns the merged dict, but a lossy one must not erase history."""
    turn = next_turn(
        history=[{"role": "assistant", "content": "Goal?"}],
        facts={"current_weekly_km": 40, "injuries": "none"},
        profile=PROFILE,
        chat_fn=_stub(_turn_json(facts={"goal_type": "race"})),
    )
    assert turn.facts["current_weekly_km"] == 40
    assert turn.facts["injuries"] == "none"
    assert turn.facts["goal_type"] == "race"


def test_ready_turn_drops_the_question_and_keeps_the_summary():
    turn = next_turn(
        history=[],
        profile=PROFILE,
        chat_fn=_stub(_turn_json(ready=True, summary="Hilly HM in 12 weeks.")),
    )
    assert turn.ready is True
    assert turn.question is None
    assert turn.facts["_summary"] == "Hilly HM in 12 weeks."


def test_question_cap_forces_ready():
    history = [{"role": "assistant", "content": f"q{i}"} for i in range(MAX_QUESTIONS)]
    turn = next_turn(history=history, profile=PROFILE, chat_fn=_stub(_turn_json()))
    assert turn.ready is True
    assert turn.question is None
    assert turn.warnings


def test_unknown_question_kind_falls_back_to_text():
    """The UI renders `kind` directly, so an invented kind must not reach it."""
    turn = next_turn(
        history=[],
        profile=PROFILE,
        chat_fn=_stub(_turn_json(question={
            "id": "x", "text": "How?", "kind": "slider", "options": "nope",
        })),
    )
    assert turn.question["kind"] == "text"
    assert turn.question["options"] == []


def test_textless_question_is_dropped():
    turn = next_turn(
        history=[],
        profile=PROFILE,
        chat_fn=_stub(_turn_json(question={"id": "x", "kind": "text"})),
    )
    assert turn.question is None


def test_fenced_json_is_parsed():
    turn = next_turn(
        history=[],
        profile=PROFILE,
        chat_fn=_stub(f"Sure!\n```json\n{_turn_json()}\n```"),
    )
    assert turn.question["id"] == "race_name"


# -------------------------------------------------------- race research


RESEARCH = json.dumps({
    "race_official_name": "Athens Marathon",
    "distance_km": 42.2,
    "elevation_gain_m": 300,
    "profile": "hilly",
    "surface": "road",
    "course_notes": "Long climb from km 17 to km 31.",
    "training_implications": ["Train sustained climbs at km 17-31."],
    "confidence": "high",
    "sources": ["https://example.com"],
})


def test_naming_a_race_triggers_a_web_backed_lookup():
    chat_fn = _stub(_turn_json(facts={"race_name": "Athens Marathon"}), RESEARCH)
    turn = next_turn(history=[], profile=PROFILE, chat_fn=chat_fn)

    assert turn.researched is True
    assert turn.facts["race_research"]["profile"] == "hilly"
    # The interview turn must not search; only the research call may.
    assert chat_fn.calls[0].get("web") is not True
    assert chat_fn.calls[1]["web"] is True


def test_race_is_researched_only_once():
    chat_fn = _stub(_turn_json(facts={"race_name": "Athens Marathon"}))
    turn = next_turn(
        history=[],
        facts={"race_name": "Athens Marathon", "race_research": {"profile": "flat"}},
        profile=PROFILE,
        chat_fn=chat_fn,
    )
    assert turn.researched is False
    assert len(chat_fn.calls) == 1
    assert turn.facts["race_research"]["profile"] == "flat"


def test_failed_research_warns_instead_of_raising():
    def chat_fn(messages, **kwargs):
        if kwargs.get("web"):
            raise RuntimeError("all models failed")
        return ChatResult(
            content=_turn_json(facts={"race_name": "Nowhere 10k"}),
            model_used="stub/model",
        )

    turn = next_turn(history=[], profile=PROFILE, chat_fn=chat_fn)
    assert turn.researched is False
    assert "race_research" not in turn.facts
    assert any("Nowhere 10k" in w for w in turn.warnings)
    assert turn.question is not None  # interview continues


def test_research_race_defaults_the_name_when_the_model_omits_it():
    research, warning = research_race(
        "Some Half", "2026-11-08", chat_fn=_stub('{"profile": "flat"}')
    )
    assert warning is None
    assert research["race_official_name"] == "Some Half"


# --------------------------------------------------------------- prompts


def test_intake_prompt_hides_research_from_the_facts_dump():
    """Research gets its own labelled section so the model actually uses it."""
    prompt = build_intake_prompt(
        history=[],
        facts={"race_name": "Athens", "race_research": {"profile": "hilly"}},
        profile=PROFILE,
        questions_asked=1,
        max_questions=MAX_QUESTIONS,
    )
    assert "RACE COURSE RESEARCH" in prompt
    assert prompt.index("KNOWN FACTS") < prompt.index("RACE COURSE RESEARCH")
    assert "Tzikos" in prompt  # profile is shown so it isn't re-asked


def test_intake_prompt_pushes_to_wrap_up_near_the_cap():
    prompt = build_intake_prompt(
        history=[], facts={}, profile=PROFILE,
        questions_asked=MAX_QUESTIONS - 1, max_questions=MAX_QUESTIONS,
    )
    assert "ready=true" in prompt


def test_render_intake_facts_is_empty_when_nothing_was_learned():
    assert render_intake_facts({}) == ""
    assert render_intake_facts({"a": None, "b": [], "c": ""}) == ""


def test_render_intake_facts_surfaces_course_research():
    block = render_intake_facts({
        "current_weekly_km": 45,
        "_summary": "Hilly marathon.",
        "race_research": {"profile": "hilly", "elevation_gain_m": 300},
    })
    assert "RACE COURSE RESEARCH" in block
    assert "Hilly marathon." in block
    assert "45" in block


@pytest.mark.parametrize("kind", ["single", "multi", "text", "number", "date"])
def test_all_documented_question_kinds_pass_through(kind):
    turn = next_turn(
        history=[],
        profile=PROFILE,
        chat_fn=_stub(_turn_json(question={
            "id": "x", "text": "?", "kind": kind, "options": ["a", "b"],
        })),
    )
    assert turn.question["kind"] == kind
