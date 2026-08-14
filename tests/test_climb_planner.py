"""VELO ClimbPlan v1 纯算法合同与西山代表坡型回归。"""

from __future__ import annotations

import pytest

from app.elevation.climb_planner import (
    ClimbPlanInputError,
    build_climb_plan,
    build_rider_climb_plan,
    classify_climb_score,
)


def _piecewise_profile(controls, step_m=20.0):
    controls = [(float(distance), float(elevation)) for distance, elevation in controls]
    total = controls[-1][0]
    distances = []
    cursor = 0.0
    while cursor < total:
        distances.append(cursor)
        cursor += step_m
    distances.append(total)
    elevations = []
    for distance in distances:
        for (left_d, left_e), (right_d, right_e) in zip(controls, controls[1:]):
            if left_d <= distance <= right_d:
                ratio = (distance - left_d) / (right_d - left_d)
                elevations.append(left_e + (right_e - left_e) * ratio)
                break
    return distances, elevations


def _plan(controls):
    distances, elevations = _piecewise_profile(controls)
    return build_climb_plan(
        distances,
        elevations,
        source_method="glo30_meaningful_ascent_v1",
        horizontal_resolution_m=30.0,
    )


@pytest.mark.parametrize(
    ("score", "category"),
    [
        (1_500, "uncategorized"),
        (8_000, "uncategorized"),
        (8_001, "4"),
        (16_001, "3"),
        (32_001, "2"),
        (64_001, "1"),
        (80_001, "HC"),
    ],
)
def test_climb_categories_use_published_strict_thresholds(score, category):
    assert classify_climb_score(score) == category


def test_climb_plan_rejects_non_monotonic_or_non_finite_profile():
    with pytest.raises(ClimbPlanInputError, match="strictly increasing"):
        build_climb_plan(
            [0, 100, 100],
            [500, 505, 510],
            source_method="test",
            horizontal_resolution_m=30,
        )
    with pytest.raises(ClimbPlanInputError, match="residual MAD"):
        build_climb_plan(
            [0, 500],
            [500, 520],
            source_method="test",
            horizontal_resolution_m=30,
            residual_mad_m=-1,
        )
    with pytest.raises(ClimbPlanInputError, match="finite"):
        build_climb_plan(
            [0, 100],
            [500, float("nan")],
            source_method="test",
            horizontal_resolution_m=30,
        )


def test_flat_route_has_no_significant_climb():
    plan = _plan([(0, 700), (10_000, 710)])
    assert plan["climbs"] == []
    assert plan["composition"]["sequence_label"] == "无显著爬坡"
    assert plan["composition"]["boundary_status"] == "not_assessed"


def test_short_steep_ramp_below_500m_is_not_mislabelled_as_climb():
    plan = _plan([(0, 700), (400, 760), (420, 750), (1_000, 750)])
    assert plan["climbs"] == []


def test_flats_and_small_descent_remain_one_climb_when_combined_grade_qualifies():
    plan = _plan(
        [
            (0, 600),
            (2_500, 750),
            (3_000, 740),
            (5_500, 900),
        ]
    )
    assert len(plan["climbs"]) == 1
    climb = plan["climbs"][0]
    assert climb["start_distance_m"] == pytest.approx(0)
    assert climb["end_distance_m"] == pytest.approx(5_500)
    assert climb["elevation_loss_m"] == pytest.approx(10, abs=0.2)


def test_route_composition_keeps_separated_climbs_ordered_and_non_overlapping():
    plan = _plan(
        [
            (0, 500),
            (3_000, 740),
            (4_000, 590),
            (10_000, 990),
            (11_000, 900),
        ]
    )
    assert [item["category"] for item in plan["climbs"]] == ["3", "2"]
    assert plan["composition"]["sequence_label"] == "Cat 3 + Cat 2"
    assert plan["climbs"][0]["recovery_after_m"] == pytest.approx(1_000)
    assert plan["climbs"][0]["end_distance_m"] < plan["climbs"][1]["start_distance_m"]
    assert plan["climbs"][1]["distance_from_previous_climb_m"] == pytest.approx(1_000)
    assert plan["climbs"][1]["descent_from_previous_climb_m"] == pytest.approx(150)
    assert plan["composition"]["finish_type"] == "descent"
    assert plan["composition"]["categorized_ascent_m"] > 0
    assert plan["composition"]["unobserved_profile_distance_m"] == 0
    assert plan["climbs"][1]["cumulative_ascent_before_m"] > 0


def test_profile_noise_mad_raises_turning_and_hard_split_thresholds():
    distances, elevations = _piecewise_profile([(0, 600), (3_000, 780)])
    plan = build_climb_plan(
        distances,
        elevations,
        source_method="glo30_meaningful_ascent_v1",
        horizontal_resolution_m=30,
        residual_mad_m=9,
    )
    assert plan["source"]["residual_mad_m"] == 9
    assert plan["parameters"]["turning_prominence_m"] == 27
    assert plan["parameters"]["hard_split_descent_m"] == 27


def test_data_authorization_does_not_masquerade_as_high_resolution_quality():
    distances, elevations = _piecewise_profile([(0, 600), (3_000, 780)])
    plan = build_climb_plan(
        distances,
        elevations,
        source_method="authorized_point_elevation_csv_v1",
        horizontal_resolution_m=None,
    )
    assert plan["source"]["confidence"] == "terrain_estimate"
    assert plan["climbs"][0]["category_status"] == "candidate"


def test_aoshen_regression_is_cat2_late_wall_not_steady():
    # active-81 GLO 总量：5,225.4m / 净爬升 343.3m；末 1km 约 12% 是 curated 坡型证据。
    plan = _plan([(0, 700), (4_225.4, 923.3), (5_225.4, 1_043.3)])
    climb = plan["climbs"][0]
    assert climb["category"] == "2"
    assert climb["shape"] == "late_wall"
    assert climb["average_grade_pct"] == pytest.approx(6.57, abs=0.02)
    assert climb["max_sustained_grade_pct"]["1000m"] == pytest.approx(12.0, abs=0.1)
    assert climb["max_sustained_grade_windows"]["1000m"]["position_fraction"] > 0.85
    assert climb["rolling_grade_1000m"]["p90"] is not None
    assert climb["category_system"] == "garmin_public_2026"
    assert climb["category_version"] == "2026-08-14"
    ramps = [item for item in climb["child_sections"] if item["section_role"] == "ramp"]
    assert ramps
    assert max(item["position_fraction"] for item in ramps) >= 0.75


def test_langpo_regression_is_cat3_short_early_wall():
    # active-81 GLO 总量：3,414.9m / 净爬升 271.7m；开头约 15% 是 curated 坡型证据。
    plan = _plan([(0, 700), (500, 775), (3_414.9, 971.7)])
    climb = plan["climbs"][0]
    assert climb["category"] == "3"
    assert climb["shape"] in {"early_wall", "short_wall"}
    assert climb["shape"] != "steady"
    assert climb["average_grade_pct"] == pytest.approx(7.96, abs=0.02)


def test_wall_position_uses_the_hardest_500m_not_the_first_ramp():
    plan = _plan(
        [
            (0, 600),
            (500, 655),
            (4_500, 775),
            (5_000, 850),
        ]
    )
    climb = plan["climbs"][0]

    assert climb["max_sustained_grade_windows"]["500m"]["position_fraction"] == pytest.approx(0.95)
    assert climb["shape"] == "late_wall"
    assert "early_wall" not in climb["shape_tags"]


def test_classic_duguan_regression_is_cat2_and_reverse_recomputes_climbs():
    # o23 冻结总量：9,286.2m / +551.2m / -12.6m，净爬升 538.6m。
    distances, elevations = _piecewise_profile(
        [(0, 600), (4_000, 820), (4_500, 807.4), (9_286.2, 1_138.6)]
    )
    forward = build_climb_plan(
        distances,
        elevations,
        source_method="glo30_meaningful_ascent_v1",
        horizontal_resolution_m=30,
        traversal_direction="forward",
    )
    total = distances[-1]
    reverse_distances = [total - distance for distance in reversed(distances)]
    reverse_elevations = list(reversed(elevations))
    reverse = build_climb_plan(
        reverse_distances,
        reverse_elevations,
        source_method="glo30_meaningful_ascent_v1",
        horizontal_resolution_m=30,
        traversal_direction="reverse",
    )

    assert forward["climbs"][0]["category"] == "2"
    assert forward["climbs"][0]["average_grade_pct"] == pytest.approx(5.80, abs=0.02)
    assert reverse["climbs"] == []


def test_staircase_keeps_one_parent_and_explains_two_recoveries():
    plan = _plan(
        [
            (0, 600),
            (1_000, 680),
            (1_200, 675),
            (2_000, 740),
            (2_200, 735),
            (3_000, 820),
        ]
    )
    assert len(plan["climbs"]) == 1
    climb = plan["climbs"][0]
    recoveries = [
        item
        for item in climb["child_sections"]
        if item["section_role"] in {"recovery", "descent_inside_climb"}
    ]
    assert len(recoveries) >= 2
    assert "staircase" in climb["shape_tags"]
    assert all("elevation_gain_m" in item and "elevation_loss_m" in item for item in recoveries)
    assert all("rolling_grade_500m" in item for item in climb["child_sections"])


def test_smoothing_variants_crossing_category_threshold_mark_candidate():
    distances, elevations = _piecewise_profile([(0, 600), (5_000, 920)])
    _same_distances, higher = _piecewise_profile([(0, 600), (5_000, 922)])
    plan = build_climb_plan(
        distances,
        elevations,
        source_method="authorized_barometric_profile_v1",
        horizontal_resolution_m=5,
        smoothing_variants={"80m": elevations, "150m": higher},
    )
    climb = plan["climbs"][0]
    assert climb["category"] == "3"  # score 正好 32,000，不越严格阈值。
    assert climb["category_stability"] == 0.5
    assert climb["category_status"] == "candidate"
    assert climb["boundary_status"] == "ambiguous"
    assert plan["partition_alternatives"]["80m"][0]["category"] == "3"
    assert plan["partition_alternatives"]["150m"][0]["category"] == "2"


def test_high_quality_profile_without_multi_scale_replay_stays_candidate():
    distances, elevations = _piecewise_profile([(0, 600), (5_000, 900)])
    plan = build_climb_plan(
        distances,
        elevations,
        source_method="authorized_barometric_profile_v1",
        horizontal_resolution_m=5,
    )

    assert plan["source"]["confidence"] == "high"
    assert plan["composition"]["boundary_status"] == "not_assessed"
    assert plan["climbs"][0]["boundary_status"] == "not_assessed"
    assert plan["climbs"][0]["category_status"] == "candidate"


def test_rider_plan_requires_ftp_and_weight_instead_of_inventing_level():
    plan = _plan([(0, 700), (5_000, 1_000)])
    missing = build_rider_climb_plan(
        plan,
        ftp_w=250,
        rider_mass_kg=None,
    )
    assert missing["status"] == "needs_profile"
    assert missing["missing_fields"] == ["weight"]
    assert missing["scenarios"] == []


def test_rider_plan_uses_route_profile_and_orders_effort_scenarios():
    plan = _plan([(0, 700), (4_000, 900), (5_000, 1_020)])
    rider = build_rider_climb_plan(
        plan,
        ftp_w=280,
        rider_mass_kg=70,
        bike_type="road",
        power_curve_w={"300": 340, "1200": 295, "3600": 255},
    )
    assert rider["status"] == "estimated"
    assert rider["basis"] == "ftp_weight_power_curve"
    assert rider["physiology_model"] == "pdc_only"
    assert rider["confidence_dimensions"]["physiology_quality"] == "power_duration_curve"
    assert rider["power_curve_coverage"]["coverage_fraction"] == 1.0
    assert rider["ftp_w_per_kg"] == 4.0
    finish, steady, hard = rider["scenarios"]
    assert finish["estimated_climbing_time_min"] > steady["estimated_climbing_time_min"]
    assert steady["estimated_climbing_time_min"] > hard["estimated_climbing_time_min"]
    assert finish["target_power_w"] < steady["target_power_w"] < hard["target_power_w"]
    assert "只估已识别爬坡时间" in rider["assumptions"][-1]


def test_power_curve_outside_target_duration_is_not_silently_extrapolated():
    plan = _plan([(0, 700), (12_000, 1_300)])
    rider = build_rider_climb_plan(
        plan,
        ftp_w=280,
        rider_mass_kg=70,
        bike_type="road",
        power_curve_w={"60": 420, "300": 340},
    )
    assert rider["basis"] == "ftp_weight"
    assert rider["physiology_model"] == "ftp_only"
    assert rider["power_curve_coverage"]["coverage_fraction"] == 0.0
    assert rider["confidence_dimensions"]["physiology_quality"] == "ftp_only"


def test_power_curve_cap_is_the_power_shown_at_scenario_level():
    plan = _plan([(0, 700), (5_000, 1_050)])
    rider = build_rider_climb_plan(
        plan,
        ftp_w=400,
        rider_mass_kg=70,
        bike_type="road",
        power_curve_w={"300": 310, "1200": 260, "3600": 230},
    )

    hard = next(item for item in rider["scenarios"] if item["key"] == "hard")
    actual = hard["climbs"][0]["target_power_w"]
    assert actual < round(400 * 0.98)
    assert hard["target_power_w"] == actual
    assert hard["target_power_range_w"] == [actual, actual]
    assert hard["target_w_per_kg"] == hard["climbs"][0]["target_w_per_kg"]


def test_multi_climb_pdc_carries_prior_climbing_time_without_fake_recovery():
    route = _plan(
        [
            (0, 600),
            (5_000, 900),
            (6_000, 700),
            (11_000, 1_000),
            (12_000, 900),
        ]
    )
    standalone_second = _plan([(0, 700), (5_000, 1_000), (6_000, 900)])
    curve = {"300": 350, "1200": 300, "2400": 250, "4800": 220}
    multi = build_rider_climb_plan(
        route,
        ftp_w=350,
        rider_mass_kg=70,
        bike_type="road",
        power_curve_w=curve,
    )
    single = build_rider_climb_plan(
        standalone_second,
        ftp_w=350,
        rider_mass_kg=70,
        bike_type="road",
        power_curve_w=curve,
    )

    multi_steady = next(item for item in multi["scenarios"] if item["key"] == "steady")
    single_steady = next(item for item in single["scenarios"] if item["key"] == "steady")
    first, second = multi_steady["climbs"]
    assert second["cumulative_climbing_time_before_min"] > 0
    assert second["pdc_effective_duration_min"] > first["pdc_effective_duration_min"]
    assert second["pdc_effective_duration_min"] == pytest.approx(
        second["cumulative_climbing_time_before_min"] + second["estimated_time_min"],
        abs=0.2,
    )
    assert second["target_power_w"] < single_steady["climbs"][0]["target_power_w"]
    assert second["estimated_time_min"] > single_steady["climbs"][0]["estimated_time_min"]
    assert second["recovery_credit_status"] == "not_modeled_without_cp_wprime"
    assert multi["multi_climb_context"] == {
        "status": "pdc_cumulative_duration_no_recovery_credit",
        "ordered_climb_count": 2,
        "recovery_credit_modeled": False,
        "cp_wprime_used": False,
    }


def test_multi_climb_ftp_only_marks_fatigue_and_recovery_pending():
    route = _plan(
        [(0, 600), (3_000, 780), (4_000, 650), (8_000, 930), (9_000, 850)]
    )
    rider = build_rider_climb_plan(
        route,
        ftp_w=280,
        rider_mass_kg=70,
        power_curve_w=None,
    )

    assert rider["multi_climb_context"]["status"] == "pending_without_cp_wprime"
    assert rider["physiology_model"] == "ftp_only"
