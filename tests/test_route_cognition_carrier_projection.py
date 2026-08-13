from __future__ import annotations

from dataclasses import replace
import math

import pytest

from app.route_cognition.carrier_projection import (
    CARRIER_PROJECTION_CONFIG_V1,
    RESEARCH_EVIDENCE_STATUS,
    DirectedTraversal,
    EvidencePosting,
    EvidenceSnapshotIncomparableError,
    arrange_directed_evidence,
    canonical_evidence_result_sha256,
    canonical_projection_result_sha256,
    integrate_directed_reach_bounds,
    project_polyline_to_carrier,
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


def _posting(
    fact_id: str,
    start_m: float,
    end_m: float,
    *,
    direction: str = "forward",
    athlete_count: int | None = 10,
    effort_count: int | None = 15,
    star_count: int | None = 2,
    quality: float = 0.9,
) -> EvidencePosting:
    return EvidencePosting(
        source_fact_id=fact_id,
        cohort="2026-08-13",
        direction=direction,
        start_measure_m=start_m,
        end_measure_m=end_m,
        athlete_count=athlete_count,
        effort_count=effort_count,
        star_count=star_count,
        projection_quality=quality,
    )


def test_forward_and_reverse_source_produce_directional_measure_witnesses():
    carrier = _line([0, 100, 200, 300, 400])

    forward = project_polyline_to_carrier(
        "carrier", carrier, "forward", _line([100, 200, 300])
    )
    reverse = project_polyline_to_carrier(
        "carrier", carrier, "reverse", list(reversed(_line([100, 200, 300])))
    )

    assert forward.status == reverse.status == "research_projected"
    assert forward.evidence_status == RESEARCH_EVIDENCE_STATUS
    assert forward.direction == "forward"
    assert reverse.direction == "reverse"
    assert forward.source_coverage_ratio == pytest.approx(1.0)
    assert reverse.source_coverage_ratio == pytest.approx(1.0)
    assert [item.carrier_measure_m for item in forward.witnesses] == sorted(
        item.carrier_measure_m for item in forward.witnesses
    )
    assert [item.carrier_measure_m for item in reverse.witnesses] == sorted(
        (item.carrier_measure_m for item in reverse.witnesses), reverse=True
    )
    assert forward.carrier_interval_envelope_m == pytest.approx((100, 300), abs=1)
    assert forward.completion_status == "complete"
    assert forward.failure_code is None
    assert len(forward.matched_runs) == 1
    assert forward.matched_runs[0].orientation == "forward"
    assert reverse.matched_runs[0].orientation == "reverse"
    assert (
        reverse.matched_runs[0].carrier_traversal_start_m
        > reverse.matched_runs[0].carrier_traversal_end_m
    )
    assert set(forward.to_dict()["distance_quantiles_m"]) == {"p50", "p95", "max"}
    assert forward.unmatched_source_intervals_m == ()
    assert "heat_score" not in forward.to_dict()


def test_monotone_projection_prevents_nearest_branch_measure_backtracking():
    # The return arm runs only 12 m from the outbound arm.  A pointwise-nearest
    # matcher can alternate between measures around 300 and 500.  The witness
    # must instead remain monotone (within the explicit 3 m tolerance).
    carrier = [
        _point(0, 0),
        _point(400, 0),
        _point(400, 12),
        _point(200, 12),
    ]
    noisy_source = [
        _point(0, 3),
        _point(100, 3),
        _point(200, 3),
        _point(300, 8),
        _point(400, 3),
    ]

    result = project_polyline_to_carrier(
        "hairpin", carrier, "source", noisy_source
    )
    measures = [item.carrier_measure_m for item in result.witnesses]

    assert result.status == "research_projected"
    assert result.direction == "forward"
    assert result.source_coverage_ratio >= 0.99
    assert all(
        right >= left - CARRIER_PROJECTION_CONFIG_V1.measure_backtrack_tolerance_m
        for left, right in zip(measures, measures[1:])
    )


def test_projection_hash_is_stable_and_config_is_in_result_contract():
    args = ("carrier", _line([0, 100, 200]), "source", _line([25, 100, 175]))

    first = project_polyline_to_carrier(*args)
    second = project_polyline_to_carrier(*args)

    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["config"]["version"] == (
        CARRIER_PROJECTION_CONFIG_V1.version
    )
    assert first.to_dict()["result_sha256"] == canonical_projection_result_sha256(
        first
    )


def test_projection_reports_unmatched_source_intervals_from_fixed_samples():
    result = project_polyline_to_carrier(
        "short-carrier",
        _line([0, 40, 80]),
        "long-source",
        _line([0, 100, 200]),
    )

    assert 0.4 < result.source_coverage_ratio < 0.7
    assert result.unmatched_source_intervals_m
    unmatched_length = sum(
        end - start for start, end in result.unmatched_source_intervals_m
    )
    assert unmatched_length + result.matched_source_length_m == pytest.approx(
        result.source_length_m
    )
    assert "fixed_sample_source_coverage_gap" in result.reason_codes
    assert result.to_dict()["unmatched_source_intervals_m"]


@pytest.mark.parametrize(
    ("reverse_source", "expected_direction"),
    [(False, "forward"), (True, "reverse")],
)
def test_internal_source_gap_splits_orientation_aware_matched_runs(
    reverse_source: bool, expected_direction: str
):
    carrier = _line([0, 100, 200])
    source = [
        _point(0),
        _point(90),
        _point(100, 30),
        _point(110),
        _point(200),
    ]
    if reverse_source:
        source.reverse()

    result = project_polyline_to_carrier("c", carrier, "s", source)

    assert result.direction == expected_direction
    assert len(result.matched_runs) >= 2
    assert "matched_runs_split_at_source_coverage_gap" in result.reason_codes
    gap_start, gap_end = result.unmatched_source_intervals_m[0]
    assert result.matched_runs[0].source_interval_m[1] <= gap_start
    assert result.matched_runs[1].source_interval_m[0] >= gap_end
    assert not any(
        run.source_interval_m[0] < gap_start
        and run.source_interval_m[1] > gap_end
        for run in result.matched_runs
    )
    if expected_direction == "forward":
        assert all(
            run.carrier_traversal_start_m <= run.carrier_traversal_end_m
            for run in result.matched_runs
        )
        assert (
            result.matched_runs[0].carrier_interval_m[1]
            < result.matched_runs[1].carrier_interval_m[0]
        )
    else:
        assert all(
            run.carrier_traversal_start_m >= run.carrier_traversal_end_m
            for run in result.matched_runs
        )
        assert (
            result.matched_runs[1].carrier_interval_m[1]
            < result.matched_runs[0].carrier_interval_m[0]
        )
    carrier_run_length = sum(
        run.carrier_interval_m[1] - run.carrier_interval_m[0]
        for run in result.matched_runs
    )
    envelope_length = (
        result.carrier_interval_envelope_m[1]
        - result.carrier_interval_envelope_m[0]
    )
    assert carrier_run_length < envelope_length
    assert result.carrier_coverage_ratio == pytest.approx(
        carrier_run_length / result.carrier_length_m
    )
    payload = result.to_dict()
    assert "carrier_interval_m" not in payload
    assert payload["carrier_interval_envelope_m"]
    assert len(payload["matched_runs"]) == len(result.matched_runs)
    assert all("matched_run_sha256" in run for run in payload["matched_runs"])
    assert all(
        result.carrier_interval_envelope_m[0] <= run.carrier_interval_m[0]
        and run.carrier_interval_m[1] <= result.carrier_interval_envelope_m[1]
        for run in result.matched_runs
    )


def test_projection_completion_and_typed_failure_codes_are_separate_from_status():
    no_candidate = project_polyline_to_carrier(
        "c", _line([0, 100]), "far", _line([0, 100], y_m=100)
    )
    geometry_insufficient = project_polyline_to_carrier(
        "c",
        _line([0, 80]),
        "long",
        _line([0, 100, 200]),
        config=replace(
            CARRIER_PROJECTION_CONFIG_V1,
            version="high_coverage_test",
            min_source_coverage_ratio=0.8,
        ),
    )
    multimodal = project_polyline_to_carrier(
        "c",
        _line([0, 100, 200]),
        "crossing",
        [_point(100, -5), _point(100, 5)],
    )

    assert (no_candidate.completion_status, no_candidate.failure_code) == (
        "incomplete",
        "projection_no_candidate",
    )
    assert (
        geometry_insufficient.completion_status,
        geometry_insufficient.failure_code,
    ) == ("incomplete", "projection_geometry_insufficient")
    assert (multimodal.completion_status, multimodal.failure_code) == (
        "incomplete",
        "projection_multimodal",
    )
    assert all(
        result.evidence_status == RESEARCH_EVIDENCE_STATUS
        for result in (no_candidate, geometry_insufficient, multimodal)
    )


def test_evidence_input_permutation_is_stable_and_lower_never_exceeds_upper():
    postings = [
        _posting("a", 0, 100, athlete_count=30, effort_count=45, star_count=8),
        _posting("b", 0, 100, athlete_count=20, effort_count=50, star_count=4),
        _posting("c", 25, 75, athlete_count=60, effort_count=80, star_count=9),
    ]

    first = arrange_directed_evidence("c", 100, postings)
    second = arrange_directed_evidence("c", 100, list(reversed(postings)))

    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["result_sha256"] == canonical_evidence_result_sha256(
        first
    )
    assert all(
        cell.reach_union_lower_bound is None
        or cell.reach_union_lower_bound <= cell.reach_union_upper_bound
        for cell in first.cells
    )
    middle = next(
        cell
        for cell in first.cells
        if cell.start_measure_m == pytest.approx(25)
        and cell.end_measure_m == pytest.approx(75)
    )
    assert middle.reach_union_lower_bound == 60
    assert middle.reach_union_upper_bound == 110
    assert middle.supporting_fact_ids == ("a", "b", "c")
    assert middle.snapshot_comparability == "same_cohort"
    assert middle.repeat_proxy_range.minimum == pytest.approx(1 / 3)
    assert middle.repeat_proxy_range.maximum == pytest.approx(1.5)
    assert middle.star_proxy_range.minimum == pytest.approx(math.log1p(4))
    assert middle.star_proxy_range.maximum == pytest.approx(math.log1p(9))


def test_forward_and_reverse_evidence_are_separate_accounts():
    result = arrange_directed_evidence(
        "c",
        100,
        [
            _posting("forward", 0, 100, athlete_count=70),
            _posting("reverse", 0, 100, direction="reverse", athlete_count=90),
        ],
    )

    assert [(cell.direction, cell.reach_union_lower_bound) for cell in result.cells] == [
        ("forward", 70),
        ("reverse", 90),
    ]
    assert result.cells[0].supporting_fact_ids == ("forward",)
    assert result.cells[1].supporting_fact_ids == ("reverse",)


def test_duplicate_fact_postings_are_idempotent_per_directed_cell():
    single = [_posting("same-fact", 0, 100, athlete_count=40)]
    repeated = single + [_posting("same-fact", 0, 100, athlete_count=40)]

    baseline = arrange_directed_evidence("c", 100, single)
    duplicate = arrange_directed_evidence("c", 100, repeated)

    assert baseline.cells == duplicate.cells
    assert duplicate.cells[0].reach_union_lower_bound == 40
    assert duplicate.cells[0].reach_union_upper_bound == 40
    assert duplicate.cells[0].raw_support_count == 1
    assert "duplicate_source_fact_postings_collapsed_per_cell" in (
        duplicate.reason_codes
    )


def test_contained_and_partial_postings_create_atomic_cells():
    result = arrange_directed_evidence(
        "c",
        150,
        [
            _posting("long", 0, 100, athlete_count=20),
            _posting("contained", 25, 75, athlete_count=40),
            _posting("partial", 50, 125, athlete_count=10),
        ],
    )

    assert [
        (cell.start_measure_m, cell.end_measure_m, cell.supporting_fact_ids)
        for cell in result.cells
    ] == [
        (0, 25, ("long",)),
        (25, 50, ("contained", "long")),
        (50, 75, ("contained", "long", "partial")),
        (75, 100, ("long", "partial")),
        (100, 125, ("partial",)),
        (125, 150, ()),
        (0, 150, ()),
    ]


def test_atomic_refinement_does_not_change_bound_integral():
    postings = [
        _posting("a", 0, 100, athlete_count=30),
        _posting("b", 25, 75, athlete_count=50),
    ]
    traversals = [DirectedTraversal("forward", 0, 100)]

    baseline = arrange_directed_evidence("c", 100, postings)
    refined = arrange_directed_evidence(
        "c", 100, postings, refinement_boundaries_m=[10, 20, 40, 80, 90]
    )
    baseline_integral = integrate_directed_reach_bounds(
        baseline.cells, traversals
    )
    refined_integral = integrate_directed_reach_bounds(refined.cells, traversals)

    assert refined_integral.covered_length_m == pytest.approx(
        baseline_integral.covered_length_m
    )
    assert refined_integral.lower_person_metres == pytest.approx(
        baseline_integral.lower_person_metres
    )
    assert refined_integral.upper_person_metres == pytest.approx(
        baseline_integral.upper_person_metres
    )


def test_repeated_route_pass_does_not_repeat_directed_evidence_credit():
    arrangement = arrange_directed_evidence(
        "c",
        100,
        [_posting("a", 0, 100, athlete_count=30)],
    )
    once = integrate_directed_reach_bounds(
        arrangement.cells, [DirectedTraversal("forward", 0, 100)]
    )
    repeated = integrate_directed_reach_bounds(
        arrangement.cells,
        [
            DirectedTraversal("forward", 0, 100),
            DirectedTraversal("forward", 0, 100),
            DirectedTraversal("forward", 25, 75),
        ],
    )

    assert repeated == once
    assert once.lower_person_metres == pytest.approx(3_000)
    assert once.lower_person_metres == once.upper_person_metres
    assert "heat" not in once.__dataclass_fields__


def test_conflicting_payload_for_same_source_fact_is_rejected():
    with pytest.raises(ValueError, match="conflicting metric payloads"):
        arrange_directed_evidence(
            "c",
            100,
            [
                _posting("same", 0, 50, athlete_count=10),
                _posting("same", 50, 100, athlete_count=11),
            ],
        )


def test_mixed_cohorts_fail_closed_instead_of_combining_bounds():
    other_cohort = EvidencePosting(
        source_fact_id="other",
        cohort="2026-08-14",
        direction="forward",
        start_measure_m=0,
        end_measure_m=100,
        athlete_count=20,
        effort_count=30,
        star_count=2,
        projection_quality=0.9,
    )

    with pytest.raises(
        EvidenceSnapshotIncomparableError, match="mixed cohorts"
    ) as error:
        arrange_directed_evidence(
            "c", 100, [_posting("first", 0, 100), other_cohort]
        )
    assert error.value.failure_code == "heat_snapshot_incomparable"


def test_empty_evidence_emits_two_full_length_unobserved_direction_cells():
    result = arrange_directed_evidence(
        "c", 100, [], refinement_boundaries_m=[25, 75]
    )

    assert len(result.cells) == 2
    assert [
        (cell.direction, cell.start_measure_m, cell.end_measure_m)
        for cell in result.cells
    ] == [
        ("forward", 0, 100),
        ("reverse", 0, 100),
    ]
    for cell in result.cells:
        assert cell.support_state == "unobserved"
        assert cell.snapshot_comparability == "not_applicable_unobserved"
        assert cell.supporting_fact_ids == ()
        assert cell.reach_union_lower_bound is None
        assert cell.reach_union_upper_bound is None
        assert cell.projection_quality_floor is None
        assert cell.bound_width is None
        assert cell.repeat_proxy_range.minimum is None
        assert cell.star_proxy_range.maximum is None
        assert cell.reason_codes == ("no_source_fact_coverage",)


def test_partial_coverage_keeps_unobserved_gap_explicit_and_out_of_integral():
    result = arrange_directed_evidence(
        "c", 100, [_posting("middle", 25, 75, athlete_count=20)]
    )
    forward = [cell for cell in result.cells if cell.direction == "forward"]

    assert [cell.support_state for cell in forward] == [
        "unobserved",
        "observed",
        "unobserved",
    ]
    integral = integrate_directed_reach_bounds(
        result.cells, [DirectedTraversal("forward", 0, 100)]
    )
    assert integral.covered_length_m == pytest.approx(50)
    assert integral.lower_person_metres == pytest.approx(1_000)
    assert integral.upper_person_metres == pytest.approx(1_000)


def test_missing_metrics_stay_unknown_and_proxies_use_only_complete_fields():
    all_missing = arrange_directed_evidence(
        "c",
        100,
        [
            _posting(
                "missing",
                0,
                100,
                athlete_count=None,
                effort_count=None,
                star_count=None,
            )
        ],
    )
    cell = all_missing.cells[0]
    assert cell.support_state == "observed"
    assert cell.reach_union_lower_bound is None
    assert cell.reach_union_upper_bound is None
    assert cell.repeat_proxy_range.minimum is None
    assert cell.star_proxy_range.maximum is None

    partial_metrics = arrange_directed_evidence(
        "c",
        100,
        [
            _posting("athlete-star", 0, 100, athlete_count=10, effort_count=None),
            _posting(
                "effort-only",
                0,
                100,
                athlete_count=None,
                effort_count=50,
                star_count=None,
            ),
        ],
    ).cells[0]
    assert partial_metrics.reach_union_lower_bound == 10
    assert partial_metrics.reach_union_upper_bound == 10
    assert partial_metrics.repeat_proxy_range.minimum is None
    assert partial_metrics.star_proxy_range.minimum == pytest.approx(math.log1p(2))

    integral = integrate_directed_reach_bounds(
        all_missing.cells, [DirectedTraversal("forward", 0, 100)]
    )
    assert integral.covered_length_m == pytest.approx(100)
    assert integral.lower_person_metres is None
    assert integral.upper_person_metres is None
    assert "observed_cell_reach_metric_missing" in integral.reason_codes
