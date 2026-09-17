"""Conversational plan intake: interview the athlete, then research the race.

One turn = one LLM call that returns the merged fact dict plus the single
most useful next question. The transcript lives with the caller (the
browser) and is posted back whole each turn, so there is no server-side
session to expire or clean up.

The one server-side side effect is race research: as soon as the interview
learns a race name, we search locally (see coach.llm.websearch) and spend
one LLM call turning the results into a course characterisation, folded
into `facts["race_research"]`. From then on the
interviewer sees the course and can ask about its actual demands, and the
plan generator is told to train for them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from coach.llm import websearch
from coach.llm.openrouter import ChatResult, chat
from coach.llm.prompts import (
    INTAKE_SYSTEM_PROMPT,
    RACE_RESEARCH_SYSTEM_PROMPT,
    build_intake_prompt,
    build_race_research_prompt,
)

ChatFn = Callable[..., ChatResult]

# The interview is capped so a confused model can't loop forever. Reaching
# the cap forces ready=true — a plan from partial answers beats no plan.
MAX_QUESTIONS = 16


@dataclass
class IntakeTurn:
    """One step of the interview."""

    note: str
    facts: dict[str, Any]
    question: dict[str, Any] | None
    ready: bool
    summary: str
    model_used: str
    researched: bool = False
    warnings: list[str] = field(default_factory=list)


def next_turn(
    *,
    history: list[dict[str, str]],
    facts: dict[str, Any] | None = None,
    profile: dict[str, Any],
    chat_fn: ChatFn | None = None,
) -> IntakeTurn:
    """Run one interview turn. `history` is the full transcript so far.

    `chat_fn` is injectable for tests; defaults to the real OpenRouter call.
    """
    chat_fn = chat_fn or chat
    facts = dict(facts or {})
    warnings: list[str] = []

    asked = sum(1 for m in history if m.get("role") == "assistant")

    result = chat_fn(
        [
            {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_intake_prompt(
                    history=history,
                    facts=facts,
                    profile=profile,
                    questions_asked=asked,
                    max_questions=MAX_QUESTIONS,
                ),
            },
        ],
        temperature=0.5,
        max_tokens=2000,
    )

    parsed = _parse_json(result.content)

    # Never let the model drop facts we already hold: merge over, don't replace.
    merged = {**facts, **_drop_profile_echo(parsed.get("facts") or {})}
    question = parsed.get("question") or None
    ready = bool(parsed.get("ready"))

    if asked >= MAX_QUESTIONS and not ready:
        ready, question = True, None
        warnings.append("Interview hit the question cap; planning with what we have.")

    # Research the course the first time we learn which race this is.
    researched = False
    if not ready and _should_research(merged):
        research, research_warning = research_race(
            str(merged["race_name"]),
            merged.get("race_date"),
            chat_fn=chat_fn,
        )
        if research is not None:
            merged["race_research"] = research
            researched = True
        if research_warning:
            warnings.append(research_warning)

    question = _clean_question(question) if not ready else None

    # A turn with neither a question nor `ready` dead-ends the UI: nothing to
    # answer, nothing to build. Weaker free models do this. Keep the
    # conversation alive with an open question rather than stranding the user.
    if not ready and question is None:
        question = dict(_OPEN_QUESTION)

    if ready:
        merged["_summary"] = parsed.get("summary") or ""

    return IntakeTurn(
        note=str(parsed.get("note") or ""),
        facts=merged,
        question=question,
        ready=ready,
        summary=str(parsed.get("summary") or ""),
        model_used=result.model_used,
        researched=researched,
        warnings=warnings,
    )


def research_race(
    race_name: str,
    race_date: Any = None,
    *,
    chat_fn: ChatFn | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Characterise a race course from local search. Returns (research, warning).

    Best-effort: a failed lookup must not sink the interview, so failures
    come back as a warning string and a None result rather than an
    exception.
    """
    chat_fn = chat_fn or chat
    sources = websearch.search(race_name)
    if not sources:
        # No sources means no research. Letting the model answer from
        # memory here is how invented elevation profiles reach a plan.
        return None, f"Found no sources describing '{race_name}'."
    try:
        result = chat_fn(
            [
                {"role": "system", "content": RACE_RESEARCH_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_race_research_prompt(
                        race_name,
                        str(race_date) if race_date else None,
                        websearch.as_prompt_block(sources),
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        research = _parse_json(result.content)
    except (RuntimeError, ValueError, TypeError) as e:
        return None, f"Could not research '{race_name}': {e}"

    if not research:
        return None, f"Found nothing usable about '{race_name}'."
    research.setdefault("race_official_name", race_name)
    return research, None


# The profile is shown to the interviewer as context, and models tend to
# copy it straight back into `facts`. These live in the profile, so echoing
# them clutters the UI's fact panel and grows the prompt every turn.
_PROFILE_ECHO = frozenset({
    "name",
    "recent_5k",
    "recent_5k_seconds",
    "threshold_hr",
    "max_hr",
    "enabled_sports",
    "sport_profiles",
    "preferred_days",
    "weekly_hours_target",
    "notes",
})


def _drop_profile_echo(facts: dict[str, Any]) -> dict[str, Any]:
    """Strip profile fields the model copied back into the fact dict."""
    return {k: v for k, v in facts.items() if k not in _PROFILE_ECHO}


def _should_research(facts: dict[str, Any]) -> bool:
    """True once we know the race name and haven't looked it up yet."""
    return bool(facts.get("race_name")) and "race_research" not in facts


# Used when a turn comes back with nothing to ask and no "ready" flag.
_OPEN_QUESTION = {
    "id": "anything_else",
    "text": "Anything else about your training, your week or your body that I should know?",
    "kind": "text",
}


def _clean_question(q: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reduce the model's question to the text the athlete answers.

    Every answer is free text now, so anything the model says about
    widgets — kind, options, units — is dropped. `kind` is kept, always
    "text", because saved conversations carry it.
    """
    if not isinstance(q, dict) or not q.get("text"):
        return None
    return {
        "id": str(q.get("id") or "answer"),
        "text": str(q["text"]),
        "kind": "text",
    }


def _parse_json(content: str) -> dict[str, Any]:
    """Reuse the planner's tolerant JSON extraction (fences, prose, truncation)."""
    from coach.llm.planner import _parse_plan_json

    return _parse_plan_json(content)
