from __future__ import annotations

import math

import pytest

from app.route_cognition.mountain_modules import (
    MountainModuleSpec,
    MountainObservation,
    analyze_mountain_module,
    heat_evidence_explanation,
    summarize_route_block,
)
from app.route_cognition.carrier_projection import DirectedTraversal


ORIGIN_LON = 112.4
ORIGIN_LAT = 37.98
METRES_PER_DEGREE = 111_194.9


def _point(x_m: float) -> tuple[float, float]:
    return (
        ORIGIN_LON
        + x_m / (METRES_PER_DEGREE * math.cos(math.radians(ORIGIN_LAT))),
        ORIGIN_LAT,
    )


def _observation(
    observation_id: int,
    xs: list[float],
    *,
    athletes: int,
) -> MountainObservation:
    return MountainObservation(
        source_observation_id=observation_id,
        source_segment_id=str(10_000 + observation_id),
        source_name=f"segment-{observation_id}",
        source_geometry_hash=f"{observation_id:064x}",
        source_geometry_lonlat=tuple(_point(x) for x in xs),
        source_fact_id=f"fact-{observation_id}",
        derived_distance_m=abs(xs[-1] - xs[0]),
        climb_m=100.0 if xs[-1] > xs[0] else 0.0,
        descent_m=0.0 if xs[-1] > xs[0] else 100.0,
        elevation_profile=((0.0, 100.0), (1.0, 200.0)),
        athlete_count=athletes,
        effort_count=athletes * 2,
        star_count=athletes // 10,
    )


def test_module_projects_forward_reverse_and_subsegments_without_heat_sum():
    observations = (
        _observation(1, [0, 500, 1000], athletes=100),
        _observation(2, [1000, 500, 0], athletes=80),
        _observation(3, [200, 400], athletes=120),
        _observation(4, [350, 600], athletes=110),
    )
    spec = MountainModuleSpec(
        module_key="fixture",
        reference_observation_id=1,
        heat_snapshot_cohort="cohort-v1",
        observation_ids=(1, 2, 3, 4),
    )

    result = analyze_mountain_module(spec, observations)

    directions = {
        item["source_observation_id"]: item["result"]["direction"]
        for item in result["projections"]
    }
    assert directions == {1: "forward", 2: "reverse", 3: "forward", 4: "forward"}
    forward_cells = [
        item
        for item in result["directed_evidence"]["cells"]
        if item["direction"] == "forward" and item["support_state"] == "observed"
    ]
    overlapping = [
        item
        for item in forward_cells
        if item["raw_support_count"] == 3
    ]
    assert overlapping
    # Lower=max rather than sum: the overlapping short segments have more
    # athletes than the full reference observation.
    assert overlapping[0]["reach_union_lower_bound"] == 120
    assert overlapping[0]["reach_union_upper_bound"] == 330
    explanation = heat_evidence_explanation(result)
    assert explanation["ranking_mode"] == "pareto_vector_unweighted"
    assert explanation["observed_cell_count"] == len(forward_cells) + 1


def test_module_rejects_exact_set_drift_and_excluded_source():
    observation = _observation(1, [0, 100], athletes=10)
    wrong_set = MountainModuleSpec(
        module_key="fixture",
        reference_observation_id=1,
        heat_snapshot_cohort="cohort-v1",
        observation_ids=(1, 2),
    )
    with pytest.raises(ValueError, match="exact set"):
        analyze_mountain_module(wrong_set, (observation,))

    excluded = MountainModuleSpec(
        module_key="fixture",
        reference_observation_id=1,
        heat_snapshot_cohort="cohort-v1",
        observation_ids=(1,),
        excluded_source_segment_ids=(observation.source_segment_id,),
    )
    with pytest.raises(ValueError, match="excluded"):
        analyze_mountain_module(excluded, (observation,))


def test_route_block_state_machine_and_reverse_ports():
    observations = (
        _observation(1, [0, 500, 1000], athletes=100),
        _observation(2, [1000, 500, 0], athletes=80),
    )
    analysis = analyze_mountain_module(
        MountainModuleSpec(
            module_key="fixture",
            reference_observation_id=1,
            heat_snapshot_cohort="cohort-v1",
            observation_ids=(1, 2),
        ),
        observations,
    )
    block = summarize_route_block(
        analysis,
        block_key="fixture:reverse",
        block_name="reverse",
        traversals=(DirectedTraversal("reverse", 0.0, 1000.0),),
        traversal_port_keys=(("summit", "base"),),
        distance_m=1000.0,
        climb_m=0.0,
        descent_m=100.0,
        recommendation_status="evidence_candidate",
        recommendation_reasons=("reverse evidence",),
    )
    ports = block["traversal_ports"][0]
    assert ports["entry"]["axis_measure_m"] == 1000.0
    assert ports["exit"]["axis_measure_m"] == 0.0
    assert ports["entry"]["port_sha256"]

    with pytest.raises(ValueError, match="requires typed blockers"):
        summarize_route_block(
            analysis,
            block_key="fixture:blocked",
            block_name="blocked",
            traversals=(DirectedTraversal("forward", 0.0, 1000.0),),
            distance_m=1000.0,
            climb_m=100.0,
            descent_m=0.0,
            recommendation_status="blocked_unknown_connection",
            recommendation_reasons=("candidate",),
        )
