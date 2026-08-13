from __future__ import annotations

from copy import deepcopy

import pytest

from app.route_cognition.route_pattern_assembly import (
    assemble_candidate,
    assemble_choice_set,
    RoutePatternAssemblyError,
    _validate_declared_reverse_pairs,
    _physically_same_boundary,
    _Endpoint,
    _transit_component,
)
from app.route_cognition.transit_paths import canonical_sha256


def _transit_run() -> dict:
    run = {
        "transit_key": "a-to-b",
        "research_verdict": "connection_candidate",
        "relation_input": {"selection_snapshot_sha256": "s" * 64},
        "provider_distance_m": 1000.0,
        "geometry_wgs84": [[112.0, 37.0], [112.01, 37.0]],
        "elevation": {"climb_m": 100.0, "descent_m": 40.0},
        "from": {
            "binding_type": "source_observation_candidate",
            "lonlat": [112.0, 37.0],
            "source_observation_id": 1,
            "source_geometry_hash": "a" * 64,
        },
        "to": {
            "binding_type": "source_observation_candidate",
            "lonlat": [112.01, 37.0],
            "source_observation_id": 2,
            "source_geometry_hash": "b" * 64,
        },
        "evidence_facts": [
            {
                "source_observation_id": 3,
                "source_segment_id": "3",
                "source_geometry_hash": "c" * 64,
                "direction_relation": "reverse_direction",
                "evidence_status": "admitted_directional_evidence",
                "transit_intervals_m": [[0.0, 500.0]],
                "source_coverage_ratio": 1.0,
                "athlete_count": 100,
                "effort_count": 200,
                "star_count": 10,
            }
        ],
    }
    run["result_sha256"] = canonical_sha256(run)
    return run


def _sources() -> dict[int, dict]:
    return {
        1: {
            "source_observation_id": 1,
            "source_segment_id": "1",
            "source_geometry_hash": "a" * 64,
        },
        2: {
            "source_observation_id": 2,
            "source_segment_id": "2",
            "source_geometry_hash": "b" * 64,
        },
        3: {
            "source_observation_id": 3,
            "source_segment_id": "3",
            "source_geometry_hash": "c" * 64,
            "athlete_count": 100,
            "effort_count": 200,
            "star_count": 10,
        },
    }


def test_reverse_transit_reuses_one_geometry_and_swaps_directional_facts() -> None:
    run = _transit_run()
    component = _transit_component(
        {
            "occurrence_id": "reverse-occurrence",
            "transit_key": "a-to-b",
            "result_sha256": run["result_sha256"],
            "selection_snapshot_sha256": "s" * 64,
            "traversal_direction": "reverse",
        },
        _sources(),
        {"a-to-b": run},
        {},
        cohort="same",
    )
    assert component.public_facts["physical_geometry_reuse"] == (
        "same_geometry_reversed"
    )
    assert component.public_facts["climb_m"] == 40.0
    assert component.public_facts["descent_m"] == 100.0
    assert component.entry.source_observation_id == 2
    assert component.exit.source_observation_id == 1
    assert component.heat.observed_length_m == 500.0


def test_transit_rejects_another_active_selection() -> None:
    run = _transit_run()
    spec = {
        "occurrence_id": "stored-occurrence",
        "transit_key": "a-to-b",
        "result_sha256": run["result_sha256"],
        "selection_snapshot_sha256": "x" * 64,
        "traversal_direction": "stored",
    }
    with pytest.raises(Exception) as exc:
        _transit_component(spec, _sources(), {"a-to-b": run}, {}, cohort="same")
    assert getattr(exc.value, "code") == "transit_selection_binding_mismatch"


def test_rehashed_transit_cannot_silently_change_connection_verdict() -> None:
    run = deepcopy(_transit_run())
    run["research_verdict"] = "portal_pair_control"
    run.pop("result_sha256")
    run["result_sha256"] = canonical_sha256(run)
    spec = {
        "occurrence_id": "stored-occurrence",
        "transit_key": "a-to-b",
        "result_sha256": run["result_sha256"],
        "selection_snapshot_sha256": "s" * 64,
        "traversal_direction": "stored",
    }
    with pytest.raises(Exception) as exc:
        _transit_component(spec, _sources(), {"a-to-b": run}, {}, cohort="same")
    assert getattr(exc.value, "code") == "transit_not_connection_candidate"


def test_component_join_requires_same_bound_identity_not_nearby_coordinate() -> None:
    left = _Endpoint(
        112.0,
        37.0,
        "source_observation_boundary",
        source_observation_id=1,
        source_geometry_hash="a" * 64,
    )
    wrong = _Endpoint(
        112.0,
        37.0,
        "source_observation_boundary",
        source_observation_id=2,
        source_geometry_hash="b" * 64,
    )
    assert not _physically_same_boundary(left, wrong)


def test_unrelated_heat_anchor_hard_rejects_only_that_candidate() -> None:
    candidate = assemble_candidate(
        {
            "candidate_id": "bad-anchor",
            "choice_name": "错误锚点",
            "comparison_scope": "regional_chain",
            "anchor_observation_ids": [999999],
            "outing_boundary": "test",
            "components": [
                {
                    "kind": "transit_path",
                    "occurrence_id": "stored-occurrence",
                    "transit_key": "a-to-b",
                    "result_sha256": _transit_run()["result_sha256"],
                    "selection_snapshot_sha256": "s" * 64,
                    "traversal_direction": "stored",
                }
            ],
        },
        source_by_id=_sources(),
        module_runs={},
        transit_runs={"a-to-b": _transit_run()},
        cohort="same",
    )
    assert candidate["assembly_status"] == "hard_rejected"
    assert candidate["hard_failure_codes"] == ["anchor_not_route_evidence"]


def test_choice_set_rejects_duplicate_candidate_ids_before_assembly() -> None:
    source_slice = {"observations": []}
    source_slice["slice_sha256"] = canonical_sha256(source_slice)
    selection = {
        "source_slice_sha256": source_slice["slice_sha256"],
        "included_bindings": [],
        "included_count": 0,
        "included_binding_sha256": canonical_sha256([]),
    }
    selection["snapshot_sha256"] = canonical_sha256(selection)
    with pytest.raises(RoutePatternAssemblyError) as exc:
        assemble_choice_set(
            {
                "choice_set_key": "duplicate",
                "source_slice_sha256": source_slice["slice_sha256"],
                "selection_snapshot_sha256": selection["snapshot_sha256"],
                "heat_snapshot_cohort": "same",
                "candidates": [
                    {"candidate_id": "same"},
                    {"candidate_id": "same"},
                ],
            },
            source_slice=source_slice,
            selection_snapshot=selection,
            module_runs={},
            transit_runs={},
        )
    assert exc.value.code == "duplicate_candidate_id"


def test_declared_reverse_pair_cannot_switch_frozen_geometry() -> None:
    forward = {
        "candidate_id": "forward",
        "hard_failure_codes": [],
        "ordered_components": [
            {
                "component_geometry_sha256": "geometry:one",
                "component_extent_m": [0.0, 1000.0],
                "traversal_orientation": "forward",
                "distance_km": 1.0,
                "climb_m": 100.0,
                "descent_m": 10.0,
            }
        ],
    }
    reverse = {
        "candidate_id": "reverse",
        "hard_failure_codes": [],
        "ordered_components": [
            {
                "component_geometry_sha256": "geometry:another",
                "component_extent_m": [0.0, 1000.0],
                "traversal_orientation": "reverse",
                "distance_km": 1.0,
                "climb_m": 10.0,
                "descent_m": 100.0,
            }
        ],
    }
    specs = [
        {"candidate_id": "forward"},
        {"candidate_id": "reverse", "reverse_of_candidate_id": "forward"},
    ]
    with pytest.raises(RoutePatternAssemblyError) as exc:
        _validate_declared_reverse_pairs(specs, [forward, reverse])
    assert exc.value.code == "reverse_component_geometry_mismatch"


def test_declared_reverse_pair_must_invert_traversal_orientation() -> None:
    component = {
        "component_geometry_sha256": "same-geometry",
        "component_extent_m": [0.0, 1000.0],
        "traversal_orientation": "forward",
        "distance_km": 1.0,
        "climb_m": 0.0,
        "descent_m": 0.0,
    }
    candidates = [
        {
            "candidate_id": "forward",
            "hard_failure_codes": [],
            "ordered_components": [component],
        },
        {
            "candidate_id": "reverse",
            "hard_failure_codes": [],
            "ordered_components": [component],
        },
    ]
    specs = [
        {"candidate_id": "forward"},
        {"candidate_id": "reverse", "reverse_of_candidate_id": "forward"},
    ]
    with pytest.raises(RoutePatternAssemblyError) as exc:
        _validate_declared_reverse_pairs(specs, candidates)
    assert exc.value.code == "reverse_traversal_orientation_mismatch"


def test_declared_reverse_pair_must_reuse_same_geometry_extent() -> None:
    def candidate(candidate_id: str, orientation: str, extent: list[float]) -> dict:
        return {
            "candidate_id": candidate_id,
            "hard_failure_codes": [],
            "ordered_components": [
                {
                    "component_geometry_sha256": "same-geometry",
                    "component_extent_m": extent,
                    "traversal_orientation": orientation,
                    "distance_km": 1.0,
                    "climb_m": 0.0,
                    "descent_m": 0.0,
                }
            ],
        }

    specs = [
        {"candidate_id": "forward"},
        {"candidate_id": "reverse", "reverse_of_candidate_id": "forward"},
    ]
    with pytest.raises(RoutePatternAssemblyError) as exc:
        _validate_declared_reverse_pairs(
            specs,
            [
                candidate("forward", "forward", [0.0, 1000.0]),
                candidate("reverse", "reverse", [1000.0, 2000.0]),
            ],
        )
    assert exc.value.code == "reverse_component_extent_mismatch"
