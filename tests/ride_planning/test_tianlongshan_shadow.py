from __future__ import annotations

import json
from pathlib import Path

from app.ride_planning.shadow import AgentAction, RideRequest, TianlongshanShadowAgent


FIXTURE = Path(__file__).parents[1] / "fixtures/ride_planning/tianlongshan_world.json"


def world() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def request(**overrides: object) -> RideRequest:
    values: dict[str, object] = {
        "origin": "太原站附近",
        "minutes": 240,
        "max_climb_m": 1200,
        "urban_exposure": "low",
    }
    values.update(overrides)
    return RideRequest(**values)  # type: ignore[arg-type]


def test_normal_request_presents_two_deterministically_valid_candidates() -> None:
    agent = TianlongshanShadowAgent(world())

    result = agent.run(request())

    assert result.action == AgentAction.PRESENT_CANDIDATES
    assert [candidate["name"] for candidate in result.candidates] == [
        "蒙山补给环线",
        "晋祠低城区暴露环线",
    ]
    assert result.model_turns == 3
    assert result.tool_calls == 4
    assert all(not candidate["unknowns"] for candidate in result.candidates)


def test_too_little_time_returns_no_result() -> None:
    result = TianlongshanShadowAgent(world()).run(request(minutes=180))

    assert result.action == AgentAction.NO_RESULT
    assert result.candidates == []
    assert any("预计时间超过硬限制" in reason for reason in result.rejection_reasons)


def test_ambiguous_origin_asks_exactly_one_question() -> None:
    result = TianlongshanShadowAgent(world()).run(request(origin="太原站"))

    assert result.action == AgentAction.ASK_ONE_QUESTION
    assert result.question == "你是从太原站附近的哪个出发点出发？请补充具体地点。"
    assert result.model_turns == 1
    assert result.tool_calls == 0


def test_candidate_over_hard_climb_limit_is_rejected() -> None:
    fixture = world()
    fixture["candidate_plans"] = [
        candidate
        for candidate in fixture["candidate_plans"]
        if candidate["name"] == "城区直达强度线"
    ]

    result = TianlongshanShadowAgent(fixture).run(request(max_climb_m=1200, urban_exposure="high", minutes=300))

    assert result.action == AgentAction.NO_RESULT
    assert result.candidates == []
    assert result.rejection_reasons == ["城区直达强度线：总爬升超过硬限制"]


def test_changed_origin_revision_invalidates_and_regenerates_old_candidates() -> None:
    fixture = world()
    agent = TianlongshanShadowAgent(fixture)

    def revise_origin() -> None:
        fixture["origins"]["太原站附近"]["revision"] = "origin-r2"

    result = agent.run(request(), before_present=revise_origin)

    assert result.action == AgentAction.PRESENT_CANDIDATES
    assert result.candidate_generation_count == 2
    assert result.tool_calls == 6
    assert {candidate["origin_revision"] for candidate in result.candidates} == {"origin-r2"}
