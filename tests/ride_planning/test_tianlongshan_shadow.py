from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.ride_planning.shadow import (
    AgentAction,
    CandidatePlan,
    RideRequest,
    TianlongshanShadowAgent,
    render_result,
)


FIXTURE = Path(__file__).parents[1] / "fixtures/ride_planning/tianlongshan_world.json"


def recorded_world() -> dict:
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


def traversal_record(
    *,
    role: str,
    source_object_ref: str,
    revision_ref: str,
    start_anchor_ref: str,
    end_anchor_ref: str,
    distance_km: float,
    climb_m: float,
    estimated_minutes: float,
) -> dict:
    traversal_ref = f"traversal:{role}:recorded"
    return {
        "traversal_ref": traversal_ref,
        "role": role,
        "composition_ref": "composition:tianlongshan-door-to-door:r7",
        "display_name": "天龙山已核验门到门路线",
        "path_ref": f"path-ref:{source_object_ref}",
        "start_anchor_ref": start_anchor_ref,
        "end_anchor_ref": end_anchor_ref,
        "source_object_ref": source_object_ref,
        "revision_ref": revision_ref,
        "bicycle_access": "permitted",
        "bicycle_access_evidence_ref": f"evidence:{role}:bicycle-access",
        "closure_status": "clear",
        "closure_evidence_ref": f"evidence:{role}:closure",
        "urban_exposure": "low",
        "evidence": [
            {
                "evidence_ref": f"evidence:{role}:geometry",
                "status": "accepted",
                "source_object_ref": source_object_ref,
            },
            {
                "evidence_ref": f"evidence:{role}:bicycle-access",
                "status": "accepted",
                "source_object_ref": source_object_ref,
            },
            {
                "evidence_ref": f"evidence:{role}:closure",
                "status": "accepted",
                "source_object_ref": source_object_ref,
            },
        ],
        "metrics": {
            "distance_km": {
                "value": distance_km,
                "calculation_source_ref": f"calculation:{role}:distance:r1",
            },
            "climb_m": {
                "value": climb_m,
                "calculation_source_ref": f"calculation:{role}:climb:r1",
            },
            "estimated_minutes": {
                "value": estimated_minutes,
                "calculation_source_ref": f"calculation:{role}:time:r1",
            },
        },
        "risk": f"{role} recorded risk",
    }


def grounded_world() -> dict:
    world = recorded_world()
    world["current_revisions"] = {
        "route-version:access:17": "revision:access:17",
        "route-version:tianlongshan:42": "revision:tianlongshan:42",
        "route-version:return:18": "revision:return:18",
    }
    world["traversals"] = [
        traversal_record(
            role="access",
            source_object_ref="route-version:access:17",
            revision_ref="revision:access:17",
            start_anchor_ref="anchor:ty-rail-neighborhood",
            end_anchor_ref="anchor:tianlongshan-bottom",
            distance_km=18.0,
            climb_m=80,
            estimated_minutes=45,
        ),
        traversal_record(
            role="core",
            source_object_ref="route-version:tianlongshan:42",
            revision_ref="revision:tianlongshan:42",
            start_anchor_ref="anchor:tianlongshan-bottom",
            end_anchor_ref="anchor:tianlongshan-top",
            distance_km=10.05,
            climb_m=561,
            estimated_minutes=55,
        ),
        traversal_record(
            role="return",
            source_object_ref="route-version:return:18",
            revision_ref="revision:return:18",
            start_anchor_ref="anchor:tianlongshan-top",
            end_anchor_ref="anchor:ty-rail-neighborhood",
            distance_km=22.0,
            climb_m=40,
            estimated_minutes=50,
        ),
    ]
    return world


def test_recorded_repository_scan_has_no_prebuilt_candidates_and_returns_no_result() -> None:
    world = recorded_world()

    result = TianlongshanShadowAgent(world).run(request())

    assert "candidate_plans" not in world
    assert world["traversals"] == []
    assert result.action == AgentAction.NO_RESULT
    assert render_result(request(), result).startswith("NO_RESULT：")


def test_ambiguous_origin_asks_exactly_one_question() -> None:
    result = TianlongshanShadowAgent(recorded_world()).run(request(origin="太原站"))

    assert result.action == AgentAction.ASK_ONE_QUESTION
    assert result.question == "你是从太原站附近的哪个出发点出发？请补充具体地点。"
    assert result.model_turns == 1
    assert result.tool_calls == 0


def test_handwritten_candidate_cannot_enter_validation() -> None:
    agent = TianlongshanShadowAgent(grounded_world())

    valid, rejected = agent.validate_plan(
        request(),
        [{"name": "手写候选", "access": "invented", "core": "invented"}],
    )

    assert valid == []
    assert rejected == ["手写 candidate 未经 grounded generator，拒绝进入系统"]


def test_generator_ignores_traversal_injected_outside_repository() -> None:
    agent = TianlongshanShadowAgent(recorded_world())
    injected = TianlongshanShadowAgent(grounded_world()).repository.list_traversals()
    context = agent.retrieve_world_context(request())
    context["traversals"] = injected

    candidates = agent.generate_candidate_plans(request(), context)

    assert candidates == []


@pytest.mark.parametrize(
    ("mutation", "expected_diagnostic"),
    [
        (lambda record: record.update(evidence=[]), "accepted evidence is required"),
        (
            lambda record: record.update(bicycle_access="unknown"),
            "bicycle access is not permitted",
        ),
        (
            lambda record: record["metrics"]["climb_m"].update(
                calculation_source_ref=""
            ),
            "climb_m calculation source is required",
        ),
    ],
)
def test_traversal_missing_grounding_cannot_generate_candidate(
    mutation, expected_diagnostic: str
) -> None:
    world = grounded_world()
    mutation(world["traversals"][0])
    agent = TianlongshanShadowAgent(world)

    result = agent.run(request())

    assert result.action == AgentAction.NO_RESULT
    assert any(
        expected_diagnostic in errors
        for errors in agent.repository.diagnostics.values()
    )


@pytest.mark.parametrize("access_status", ["prohibited", "unknown"])
def test_prohibited_or_unknown_bicycle_access_cannot_be_displayed(
    access_status: str,
) -> None:
    world = grounded_world()
    world["traversals"][1]["bicycle_access"] = access_status

    result = TianlongshanShadowAgent(world).run(request())

    assert result.action == AgentAction.NO_RESULT
    assert result.candidates == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda world: world["traversals"][1].update(closure_status="closed"),
        lambda world: world["current_revisions"].update(
            {"route-version:tianlongshan:42": "revision:tianlongshan:43"}
        ),
    ],
)
def test_closure_or_stale_revision_cannot_be_displayed(mutation) -> None:
    world = grounded_world()
    mutation(world)

    result = TianlongshanShadowAgent(world).run(request())

    assert result.action == AgentAction.NO_RESULT
    assert result.candidates == []


def test_generator_requires_continuous_legs() -> None:
    world = grounded_world()
    world["traversals"][0]["end_anchor_ref"] = "anchor:wrong"

    result = TianlongshanShadowAgent(world).run(request())

    assert result.action == AgentAction.NO_RESULT
    assert result.candidates == []


def test_validator_rechecks_continuity_after_generation() -> None:
    world = grounded_world()
    agent = TianlongshanShadowAgent(world)
    context = agent.retrieve_world_context(request())
    generated = agent.generate_candidate_plans(request(), context)[0]
    broken = replace(
        generated,
        return_leg=replace(
            generated.return_leg,
            start_anchor_ref="anchor:not-the-core-end",
        ),
    )

    valid, rejected = agent.validate_plan(request(), [broken])

    assert valid == []
    assert any("legs 不连续" in reason for reason in rejected)


def test_every_displayed_leg_resolves_back_to_grounded_source_objects() -> None:
    world = grounded_world()
    agent = TianlongshanShadowAgent(world)

    result = agent.run(request())

    assert result.action == AgentAction.PRESENT_CANDIDATES
    assert len(result.candidates) == 1
    for candidate in result.candidates:
        for role in ("access", "core", "return"):
            leg = candidate[role]
            source = agent.repository.get_traversal(leg["traversal_ref"])
            assert source is not None
            assert source.source_object_ref == leg["source_object_ref"]
            assert source.revision_ref == leg["revision_ref"]
            assert all(item.status == "accepted" for item in source.evidence)
            assert leg["evidence_refs"]
        assert len(candidate["metrics_provenance_refs"]) == 9


def test_candidate_values_are_computed_only_from_source_traversals() -> None:
    world = grounded_world()
    result = TianlongshanShadowAgent(world).run(request())
    candidate = result.candidates[0]

    assert candidate["name"] == world["traversals"][1]["display_name"]
    assert candidate["access"]["path_ref"] == world["traversals"][0]["path_ref"]
    assert candidate["core"]["path_ref"] == world["traversals"][1]["path_ref"]
    assert candidate["return"]["path_ref"] == world["traversals"][2]["path_ref"]
    assert candidate["total_distance_km"] == pytest.approx(50.05)
    assert candidate["total_climb_m"] == 681
    assert candidate["estimated_minutes"] == 150


def test_old_mengshan_synthetic_candidate_disappears_without_name_blacklist() -> None:
    source_text = FIXTURE.read_text(encoding="utf-8")
    implementation = Path(
        "app/ride_planning/shadow/__init__.py"
    ).read_text(encoding="utf-8")

    assert "蒙山补给环线" not in source_text
    assert "蒙山补给环线" not in implementation
    assert TianlongshanShadowAgent(recorded_world()).run(request()).candidates == []
