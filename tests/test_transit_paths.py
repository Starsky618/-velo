from __future__ import annotations

import pytest

from app.route_cognition.transit_paths import (
    TransitEvidenceFact,
    TransitPort,
    TransitStep,
    build_transit_path,
)


def _fact() -> TransitEvidenceFact:
    return TransitEvidenceFact(
        source_observation_id=20,
        source_segment_id="25733595",
        source_name="柴化线爬坡",
        source_geometry_hash="a" * 64,
        source_length_m=1560.0,
        shared_length_m=780.0,
        transit_intervals_m=((0.0, 780.0),),
        transit_coverage_ratio=780.0 / 790.0,
        source_coverage_ratio=0.5,
        direction_relation="same_direction",
        extent_relation="a_contains_b",
        evidence_status="admitted_directional_evidence",
        reason_codes=("right_fully_embedded_in_left",),
        athlete_count=165,
        effort_count=427,
        star_count=20,
    )


def _run(**overrides):
    values = {
        "transit_key": "a-to-b",
        "from_port": TransitPort(
            "a:exit",
            112.4,
            37.9,
            "source_observation_candidate",
            source_observation_id=1,
            source_geometry_hash="d" * 64,
        ),
        "to_port": TransitPort(
            "b:entry",
            112.409,
            37.9,
            "source_observation_candidate",
            source_observation_id=2,
            source_geometry_hash="e" * 64,
        ),
        "provider": "tencent_driving_shadow",
        "provider_observed_at": "2026-08-13",
        "provider_status": "provider_path_not_bicycling_verified",
        "research_verdict": "connection_candidate",
        "provider_snapshot_sha256": "b" * 64,
        "evidence_snapshot_sha256": "c" * 64,
        "provider_distance_m": 790.0,
        "provider_duration_raw": None,
        "geometry_wgs84": [[112.4, 37.9], [112.409, 37.9]],
        "steps": [TransitStep("测试路", 790.0)],
        "elevation": {
            "algorithm_version": "glo30_meaningful_ascent_v1",
            "point_count": 2,
            "climb_m": 20.0,
            "descent_m": 10.0,
            "profile": [[0.0, 100.0], [0.79, 110.0]],
        },
        "evidence_facts": [_fact()],
    }
    values.update(overrides)
    return build_transit_path(**values)


def test_transit_path_keeps_destination_ports_and_ordered_roads() -> None:
    result = _run()
    assert result["from"]["port_key"] == "a:exit"
    assert result["to"]["port_key"] == "b:entry"
    assert result["ordered_road_steps"][0]["road_name"] == "测试路"
    assert result["evidence_facts"][0]["source_observation_id"] == 20
    assert result["evidence_coverage"]["covered_intervals_m"] == [[0.0, 780.0]]
    assert result["boundary"].startswith("provider 提出完整过境道路")


def test_transit_path_does_not_require_evidence_to_be_a_waypoint() -> None:
    result = _run(evidence_facts=[])
    assert result["evidence_facts"] == []
    assert result["evidence_coverage"]["coverage_lower_bound_ratio"] == 0
    assert result["evidence_coverage"]["uncovered_state"] == "unobserved_not_zero"


def test_transit_path_rejects_unaccounted_step_distance() -> None:
    with pytest.raises(ValueError, match="road steps"):
        _run(steps=[TransitStep("测试路", 100.0)])


def test_bicycling_profile_remains_connectivity_shadow() -> None:
    result = _run(
        provider="tencent_bicycling_shadow",
        provider_status="connectivity_shadow_not_access_verified",
    )

    assert result["provider"] == "tencent_bicycling_shadow"
    assert result["provider_status"] == "connectivity_shadow_not_access_verified"


def test_transit_path_rejects_duplicate_evidence_observation() -> None:
    with pytest.raises(ValueError, match="unique"):
        _run(evidence_facts=[_fact(), _fact()])


def test_transit_path_unions_overlapping_evidence_intervals() -> None:
    first = _fact()
    second = TransitEvidenceFact(
        source_observation_id=21,
        source_segment_id="25962995",
        source_name="另一条来源",
        source_geometry_hash="b" * 64,
        source_length_m=800.0,
        shared_length_m=400.0,
        transit_intervals_m=((390.0, 790.0),),
        transit_coverage_ratio=400.0 / 790.0,
        source_coverage_ratio=0.5,
        direction_relation="same_direction",
        extent_relation="partial_overlap",
        evidence_status="admitted_directional_evidence",
        reason_codes=("significant_partial_coverage",),
        athlete_count=200,
        effort_count=500,
        star_count=3,
    )
    result = _run(evidence_facts=[first, second])
    assert result["evidence_coverage"]["covered_length_lower_bound_m"] == 790.0


def test_transit_path_keeps_directional_coverage_separate() -> None:
    reverse = TransitEvidenceFact(
        **{
            **_fact().__dict__,
            "direction_relation": "reverse_direction",
        }
    )
    result = _run(evidence_facts=[reverse])
    coverage = result["evidence_coverage"]
    assert coverage["by_direction"]["same_direction"][
        "coverage_lower_bound_ratio"
    ] == 0
    assert coverage["by_direction"]["reverse_direction"][
        "coverage_lower_bound_ratio"
    ] == pytest.approx(780 / 790, abs=1e-6)
    assert coverage["semantic_role"] == (
        "geometry_coverage_qa_not_directional_heat_score"
    )


def test_short_transit_accepts_its_own_tenth_metre_interval_quantization() -> None:
    fact = TransitEvidenceFact(
        **{
            **_fact().__dict__,
            "shared_length_m": 78.29,
            "transit_intervals_m": ((6.551, 84.841),),
            "transit_coverage_ratio": 78.29 / 85.0,
        }
    )
    result = _run(
        from_port=TransitPort(
            "a:exit",
            112.4,
            37.9,
            "source_observation_candidate",
            source_observation_id=1,
            source_geometry_hash="d" * 64,
        ),
        to_port=TransitPort(
            "b:entry",
            112.40097,
            37.9,
            "source_observation_candidate",
            source_observation_id=2,
            source_geometry_hash="e" * 64,
        ),
        provider_distance_m=85.0,
        geometry_wgs84=[[112.4, 37.9], [112.40097, 37.9]],
        steps=[TransitStep("测试路", 85.0)],
        elevation={
            "algorithm_version": "glo30_meaningful_ascent_v1",
            "point_count": 2,
            "climb_m": 0.0,
            "descent_m": 0.0,
            "profile": [[0.0, 100.0], [0.085, 100.0]],
        },
        evidence_facts=[fact],
    )

    assert result["evidence_facts"][0]["transit_intervals_m"] == [[6.6, 84.8]]


def test_transit_path_keeps_indeterminate_fact_out_of_directional_coverage() -> None:
    gray = TransitEvidenceFact(
        **{
            **_fact().__dict__,
            "extent_relation": "indeterminate",
            "evidence_status": "diagnostic_indeterminate",
            "reason_codes": ("multiple_projection_measures",),
        }
    )
    result = _run(evidence_facts=[gray])
    assert result["evidence_coverage"]["coverage_lower_bound_ratio"] == 0
    assert result["evidence_coverage"]["diagnostic_indeterminate_fact_count"] == 1
    assert result["evidence_facts"][0]["reason_codes"] == [
        "multiple_projection_measures"
    ]


def test_transit_path_rejects_disjoint_fact_as_admitted_directional_evidence() -> None:
    invalid = TransitEvidenceFact(
        **{
            **_fact().__dict__,
            "extent_relation": "disjoint",
            "evidence_status": "admitted_directional_evidence",
        }
    )
    with pytest.raises(ValueError, match="contradicts extent"):
        _run(evidence_facts=[invalid])


def test_transit_path_rejects_geometry_endpoint_that_misses_port() -> None:
    with pytest.raises(ValueError, match="endpoint does not match"):
        _run(
            from_port=TransitPort(
                "far",
                112.0,
                37.0,
                "source_observation_candidate",
                source_observation_id=1,
                source_geometry_hash="d" * 64,
            )
        )


def test_transit_path_rejects_wrong_glo_algorithm() -> None:
    with pytest.raises(ValueError, match="glo30_meaningful_ascent_v1"):
        _run(
            elevation={
                "algorithm_version": "wrong",
                "point_count": 2,
                "climb_m": 20.0,
                "descent_m": 10.0,
                "profile": [[0.0, 100.0], [0.79, 110.0]],
            }
        )


def test_transit_path_rejects_fact_interval_drift() -> None:
    fact = _fact()
    invalid = TransitEvidenceFact(
        **{
            **fact.__dict__,
            "shared_length_m": 300.0,
        }
    )
    with pytest.raises(ValueError, match="shared length and intervals drift"):
        _run(evidence_facts=[invalid])
