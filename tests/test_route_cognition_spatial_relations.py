from __future__ import annotations

import json
import math

import pytest

from app.route_cognition.spatial_relations import (
    RAW_SPATIAL_RELATION_CONFIG_V1,
    SpatialRelationConfig,
    analyze_spatial_relation,
    canonical_result_sha256,
)


ORIGIN_LON = 112.4
ORIGIN_LAT = 37.7
METRES_PER_DEGREE = 111_194.9


def _point(x_m: float, y_m: float = 0.0) -> list[float]:
    return [
        ORIGIN_LON
        + x_m / (METRES_PER_DEGREE * math.cos(math.radians(ORIGIN_LAT))),
        ORIGIN_LAT + y_m / METRES_PER_DEGREE,
    ]


def _line(xs_m: list[float], y_m: float = 0.0) -> list[list[float]]:
    return [_point(x_m, y_m) for x_m in xs_m]


def _analyze(left, right, *, left_id="left", right_id="right"):
    return analyze_spatial_relation(
        left_id,
        left,
        right_id,
        right,
        config=RAW_SPATIAL_RELATION_CONFIG_V1,
    )


def test_identical_full_sequence_is_explicit_source_geometry_identical():
    points = _line([0, 100, 200, 300])

    result = _analyze(points, points)

    assert result.extent_relation == "source_geometry_identical"
    assert result.direction_relation == "same_direction"
    assert result.left_coverage_ratio == 1.0
    assert result.right_coverage_ratio == 1.0
    assert "exact_same_sequence" in result.reason_codes
    assert result.evidence_scope == "raw_full_polyline_not_road_truth"


def test_complete_reversed_sequence_is_identical_extent_and_reverse_direction():
    points = _line([0, 100, 200, 300])

    result = _analyze(points, list(reversed(points)))

    assert result.extent_relation == "source_geometry_identical"
    assert result.direction_relation == "reverse_direction"
    assert "exact_reverse_sequence" in result.reason_codes
    assert result.components[0].right_start_m > result.components[0].right_end_m


def test_same_extent_with_different_sampling_is_equivalent_not_exact():
    sparse = _line([0, 200, 400])
    dense = _line([0, 80, 160, 240, 320, 400])

    result = _analyze(sparse, dense)

    assert result.extent_relation == "equivalent"
    assert result.direction_relation == "same_direction"
    assert result.left_coverage_ratio >= 0.99
    assert result.right_coverage_ratio >= 0.99
    assert not any(code.startswith("exact_") for code in result.reason_codes)


@pytest.mark.parametrize(
    ("short_points", "expected_direction"),
    [
        (_line([100, 200, 300]), "same_direction"),
        (list(reversed(_line([100, 200, 300]))), "reverse_direction"),
    ],
)
def test_containment_supports_forward_and_reverse_monotone_embedding(
    short_points, expected_direction
):
    long_points = _line([0, 100, 200, 300, 400])

    result = _analyze(long_points, short_points)

    assert result.extent_relation == "a_contains_b"
    assert result.direction_relation == expected_direction
    assert result.right_coverage_ratio >= 0.99
    assert result.left_coverage_ratio < 0.9


def test_partial_overlap_keeps_intervals_exclusive_lengths_and_quantiles():
    left = _line([0, 100, 200, 300])
    right = _line([200, 300, 400, 500])

    result = _analyze(left, right)
    payload = result.to_dict()

    assert result.extent_relation == "partial_overlap"
    assert result.direction_relation == "same_direction"
    assert 0.1 < result.left_coverage_ratio < 0.8
    assert 0.1 < result.right_coverage_ratio < 0.8
    assert result.left_exclusive_length_m > 0
    assert result.right_exclusive_length_m > 0
    assert payload["components"][0]["left_interval_m"][0] > 0
    assert set(payload["distance_quantiles_m"]) == {"p50", "p95", "max"}


def test_single_perpendicular_crossing_has_no_significant_overlap_component():
    horizontal = _line([-200, 0, 200])
    vertical = [_point(0, -200), _point(0, 0), _point(0, 200)]

    result = _analyze(horizontal, vertical)

    assert result.extent_relation == "disjoint"
    assert result.direction_relation == "indeterminate"
    assert result.components == ()
    assert "no_significant_overlap_component" in result.reason_codes


def test_far_pair_uses_exact_bbox_rejection_without_polyline_matching():
    result = _analyze(_line([0, 100]), _line([500, 600], 500))

    assert result.extent_relation == "disjoint"
    assert result.direction_relation == "indeterminate"
    assert "expanded_polyline_bbox_disjoint" in result.reason_codes


def test_close_parallel_lines_stay_indeterminate_without_road_topology():
    left = _line([0, 200, 400], 0)
    right = _line([0, 200, 400], 8)

    result = _analyze(left, right)

    assert result.extent_relation == "indeterminate"
    assert result.direction_relation == "same_direction"
    assert "parallel_near_line_ambiguous" in result.reason_codes


def test_two_separated_overlap_occurrences_are_not_collapsed_to_a_set():
    reference = _line([0, 250, 500, 750, 1000])
    two_visits = [
        _point(0, 0),
        _point(300, 0),
        _point(300, 100),
        _point(700, 100),
        _point(700, 0),
        _point(1000, 0),
    ]

    result = _analyze(two_visits, reference)

    assert result.extent_relation == "partial_overlap"
    assert len(result.components) == 2
    assert result.components[0].left_end_m < result.components[1].left_start_m


def test_same_and_reverse_components_are_reported_as_mixed_and_stay_gray():
    reference = _line([0, 250, 500, 750, 1000])
    mixed_route = [
        _point(0, 0),
        _point(300, 0),
        _point(300, 100),
        _point(1000, 100),
        _point(1000, 0),
        _point(700, 0),
    ]

    result = _analyze(mixed_route, reference)

    assert result.extent_relation == "indeterminate"
    assert result.direction_relation == "mixed_direction"
    assert {component.orientation for component in result.components} == {
        "same",
        "reverse",
    }
    assert "mixed_orientation_components" in result.reason_codes


def test_repeated_out_and_back_geometry_stays_gray_and_reports_ambiguity():
    repeated_sparse = _line([0, 200, 400]) + _line([200, 0])
    repeated_dense = _line([0, 100, 200, 300, 400]) + _line([300, 200, 100, 0])

    result = _analyze(repeated_sparse, repeated_dense)

    assert result.extent_relation == "indeterminate"
    assert any(
        code in result.reason_codes
        for code in (
            "self_overlap_requires_topology_review",
            "multiple_projection_measures",
            "mixed_orientation_components",
        )
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (_line([0, 100, 200, 300, 400]), _line([100, 200, 300])),
        (_line([0, 100, 200, 300]), _line([200, 300, 400, 500])),
        (_line([0, 200, 400]), _line([0, 200, 400], 8)),
        (_line([0, 100, 200]), list(reversed(_line([0, 100, 200])))),
    ],
)
def test_swapping_inputs_swaps_extent_roles_but_preserves_direction_and_hash(
    left, right
):
    forward = _analyze(left, right, left_id="z", right_id="a")
    swapped = _analyze(right, left, left_id="a", right_id="z")
    inverse = {
        "a_contains_b": "b_contains_a",
        "b_contains_a": "a_contains_b",
    }.get(forward.extent_relation, forward.extent_relation)

    assert swapped.extent_relation == inverse
    assert swapped.direction_relation == forward.direction_relation
    assert swapped.left_coverage_ratio == forward.right_coverage_ratio
    assert swapped.right_coverage_ratio == forward.left_coverage_ratio
    assert canonical_result_sha256(forward) == canonical_result_sha256(swapped)
    assert forward.to_dict()["result_sha256"] == swapped.to_dict()["result_sha256"]


def test_swapping_containment_keeps_extent_coverage_and_reason_roles_consistent():
    long_line = _line([0, 100, 200, 300, 400])
    short_line = _line([100, 200, 300])

    long_first = _analyze(long_line, short_line, left_id="z", right_id="a")
    short_first = _analyze(short_line, long_line, left_id="a", right_id="z")

    assert long_first.extent_relation == "a_contains_b"
    assert "right_fully_embedded_in_left" in long_first.reason_codes
    assert "left_fully_embedded_in_right" not in long_first.reason_codes
    assert long_first.right_coverage_ratio >= 0.99
    assert long_first.left_coverage_ratio < 0.9

    assert short_first.extent_relation == "b_contains_a"
    assert "left_fully_embedded_in_right" in short_first.reason_codes
    assert "right_fully_embedded_in_left" not in short_first.reason_codes
    assert short_first.left_coverage_ratio >= 0.99
    assert short_first.right_coverage_ratio < 0.9

    assert long_first.to_dict()["result_sha256"] == short_first.to_dict()[
        "result_sha256"
    ]
    assert canonical_result_sha256(long_first.to_dict()) == canonical_result_sha256(
        short_first.to_dict()
    )


def test_serialization_and_hash_are_deterministic():
    left = _line([0, 100, 200, 300])
    right = _line([200, 300, 400, 500])

    first = _analyze(left, right).to_dict()
    second = _analyze(left, right).to_dict()

    assert first == second
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    assert first["result_sha256"] == canonical_result_sha256(first)
    assert first["config_sha256"]


def test_invalid_config_cannot_hide_an_unversioned_threshold_policy():
    payload = RAW_SPATIAL_RELATION_CONFIG_V1.to_dict()
    payload["version"] = ""

    with pytest.raises(ValueError, match="version"):
        SpatialRelationConfig(**payload)
