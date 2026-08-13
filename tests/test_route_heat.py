from __future__ import annotations

import pytest

from app.route_cognition.route_heat import (
    component_from_directed_cells,
    compose_route_heat,
    rank_heat_candidates,
    unobserved_component,
)


def _cells() -> list[dict]:
    return [
        {
            "direction": "forward",
            "start_measure_m": 0.0,
            "end_measure_m": 1000.0,
            "support_state": "observed",
            "cohorts": ["same"],
            "reach_union_lower_bound": 100,
            "reach_union_upper_bound": 140,
            "projection_quality_floor": 0.9,
            "repeat_proxy_range": {"min": 1.0, "max": 2.0},
            "star_proxy_range": {"min": 3.0, "max": 4.0},
        }
    ]


def test_route_heat_keeps_unobserved_connector_out_of_popularity() -> None:
    observed = component_from_directed_cells(
        component_key="destination",
        distance_m=1000,
        climb_m=100,
        descent_m=0,
        cells=_cells(),
        direction="forward",
    )
    connector = unobserved_component(
        component_key="connector", distance_m=1000, climb_m=10, descent_m=20
    )
    result = compose_route_heat("candidate", (observed, connector))
    assert result["distance_km"] == 2.0
    assert result["evidence_coverage"] == 0.5
    assert result["connector_ratio"] == 0.5
    assert result["reach_lower_person_km"] == 100.0
    assert result["climb_m"] == 110.0


def test_route_heat_rejects_duplicate_component_occurrence() -> None:
    connector = unobserved_component(
        component_key="same", distance_m=1000, climb_m=0, descent_m=0
    )
    with pytest.raises(ValueError, match="counted twice"):
        compose_route_heat("candidate", (connector, connector))


def test_hard_fail_never_enters_pareto_ranking() -> None:
    good = compose_route_heat(
        "good",
        (
            component_from_directed_cells(
                component_key="good-component",
                distance_m=1000,
                climb_m=0,
                descent_m=0,
                cells=_cells(),
                direction="forward",
            ),
        ),
    )
    bad = dict(good, candidate_id="bad")
    result = rank_heat_candidates(
        [
            {"candidate_id": "good", "hard_failure_codes": [], "heat_vector": good},
            {
                "candidate_id": "bad",
                "hard_failure_codes": ["topology_break"],
                "heat_vector": bad,
            },
        ]
    )
    assert result["ranked_candidate_ids"] == ["good"]
    assert result["hard_rejected"][0]["candidate_id"] == "bad"
