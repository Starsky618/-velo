"""完整坡、半坡和普通走廊不能在 ClimbPro 入口混为一谈。"""

from __future__ import annotations

import pytest

from app.elevation.climb_profile_contract import (
    ClimbProfileContract,
    ClimbProfileContractError,
    build_climb_plan_from_contract,
)


def _contract(**overrides):
    values = {
        "scope_key": "taiyuan_xishan_test",
        "scope_kind": "named_climb",
        "extent_status": "full_candidate",
        "traversal_direction": "forward",
        "geometry_source": "strava_full_segment_projection",
        "start_anchor": "axis_start:test_base",
        "end_anchor": "axis_end:test_upper",
        "source_observation_ids": (27,),
        "source_geometry_hashes": ("a" * 64,),
    }
    values.update(overrides)
    return ClimbProfileContract(**values)


def test_full_candidate_keeps_profile_complete_but_not_verified_identity():
    result = build_climb_plan_from_contract(
        [[112.30, 37.70], [112.31, 37.70]],
        [700.0, 760.0],
        contract=_contract(),
        source_method="glo30_meaningful_ascent_v1_snapshot_replay_v1",
    )

    checks = result.climb_plan["source"]["quality_checks"]
    assert checks["profile_complete_for_input_extent"] is True
    assert checks["profile_complete_for_named_climb_candidate"] is True
    assert checks["profile_complete_for_named_climb"] is False
    assert checks["profile_complete_for_route"] is False
    assert result.climb_plan["composition"]["input_extent_status"] == "full_candidate"
    from app.route_book.schemas import RouteClimbPlanResponse

    response = RouteClimbPlanResponse.model_validate(result.climb_plan)
    assert response.input_contract is not None
    assert response.input_contract.scope_key == "taiyuan_xishan_test"
    assert response.composition.input_scope_kind == "named_climb"
    assert response.composition.input_extent_status == "full_candidate"


def test_full_verified_requires_canonical_anchor_evidence():
    with pytest.raises(ClimbProfileContractError, match="anchor evidence"):
        _contract(extent_status="full_verified").validate()
    _contract(
        extent_status="full_verified",
        anchor_evidence_refs=("curated-climb-boundary-ledger:1",),
    ).validate()


def test_partial_cannot_enter_without_parent_identity():
    with pytest.raises(ClimbProfileContractError, match="parent_scope_key"):
        _contract(extent_status="partial").validate()


def test_partial_requires_valid_parent_axis_offsets():
    with pytest.raises(ClimbProfileContractError, match="start_offset_m"):
        _contract(extent_status="partial", parent_scope_key="full").validate()
    with pytest.raises(ClimbProfileContractError, match="offsets are invalid"):
        _contract(
            extent_status="partial",
            parent_scope_key="full",
            start_offset_m=1200.0,
            end_offset_m=800.0,
        ).validate()
    _contract(
        extent_status="partial",
        parent_scope_key="full",
        start_offset_m=800.0,
        end_offset_m=1200.0,
    ).validate()


def test_corridor_cannot_claim_full_named_climb():
    with pytest.raises(ClimbProfileContractError, match="corridor"):
        _contract(scope_kind="road_corridor").validate()


def test_incomplete_geometry_or_profile_coverage_is_rejected():
    with pytest.raises(ClimbProfileContractError, match="geometry coverage"):
        _contract(geometry_coverage_ratio=0.8).validate()
    with pytest.raises(ClimbProfileContractError, match="elevation profile coverage"):
        _contract(elevation_profile_coverage_ratio=0.9).validate()


def test_geometry_and_elevation_must_cover_same_input():
    with pytest.raises(ClimbProfileContractError, match="same complete input"):
        build_climb_plan_from_contract(
            [[112.30, 37.70], [112.31, 37.70]],
            [700.0],
            contract=_contract(),
            source_method="glo30_meaningful_ascent_v1_snapshot_replay_v1",
        )


def test_complete_route_composition_is_not_a_named_climb():
    contract = _contract(
        scope_kind="route_composition",
        extent_status="complete_route_composition",
        source_observation_ids=(27, 38),
        source_geometry_hashes=("a" * 64, "b" * 64),
        start_anchor="route_start",
        end_anchor="route_end",
    )
    result = build_climb_plan_from_contract(
        [[112.30, 37.70], [112.31, 37.70]],
        [700.0, 760.0],
        contract=contract,
        source_method="frozen_component_profile_composition_v1",
    )
    checks = result.climb_plan["source"]["quality_checks"]
    assert checks["profile_complete_for_route"] is True
    assert checks["profile_complete_for_named_climb"] is False
