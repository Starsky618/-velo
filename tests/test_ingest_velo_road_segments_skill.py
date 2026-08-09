from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.route_cognition.geometry_hash import (
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / ".agents/skills/ingest-velo-road-segments/scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SKILL_SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load("ingest_velo_build_candidate", "build_candidate.py")
review = _load("ingest_velo_review_candidate", "review_candidate.py")


def _manifest():
    return {
        "schema_version": 1,
        "target_definition": {
            "physical_role": "测试山脚到山顶的完整盘山主路",
            "expected_direction": "山脚到山顶",
            "expected_distance_range_m": {"min": 2500, "max": 4000},
            "expected_start_wgs84": {"lat": 37.8, "lon": 112.5, "name": "山脚"},
            "expected_end_wgs84": {"lat": 37.82, "lon": 112.52, "name": "山顶"},
            "endpoint_tolerance_m": 50,
            "required_shape_features": ["中间经过岔口和发卡弯"],
            "acceptance_sources": [
                {
                    "type": "test_anchor",
                    "reference": "unit-test",
                    "note": "先定义目标再选择候选",
                }
            ],
        },
        "segment": {
            "name": "测试盘山赛段",
            "city": "taiyuan",
            "direction": "山脚到山顶",
        },
        "reconstruction": {
            "tencent_routing_profile": "bicycling",
            "profile_selection_reason": "测试普通骑行道路，使用骑行算路",
        },
        "selection": {
            "source_segment_name": "测试盘山赛段公开名称",
            "identity_check": {
                "boundary_match": "yes",
                "direction_match": "yes",
                "distance_match": "yes",
                "shape_match": "yes",
                "checked_against": "测试目标定义和固定地图锚点",
                "selection_basis": "四项身份均匹配，不是邻近局部赛段",
            },
            "rejected_candidates": [],
        },
        "discovery": {
            "source_type": "strava_public_page",
            "source_url": "https://www.strava.com/segments/12345",
            "observed_at": "2026-08-09T17:30:00+08:00",
            "coordinate_observation": {
                "acquisition_mode": "strava_visible_markers_aligned_to_tencent_map",
                "strava_start_marker_seen": True,
                "strava_end_marker_seen": True,
                "alignment_method": "把公开页面起终点标记与腾讯同一道路位置对齐",
                "estimated_accuracy_m": 20,
                "legacy_geometry_used": False,
                "note": "测试坐标来自公开 marker 对齐，不复制外部轨迹",
            },
            "start_wgs84": {"lat": 37.8, "lon": 112.5, "name": "山脚"},
            "end_wgs84": {"lat": 37.82, "lon": 112.52, "name": "山顶"},
            "anchors_wgs84": [{"lat": 37.81, "lon": 112.51, "name": "岔口"}],
            "route_shape_notes": "中间经过一个发卡弯",
            "observed_metrics": {
                "distance_m": 3200,
                "elevation_gain_m": 80,
                "average_gradient_pct": 2.5,
                "minimum_elevation_m": 700,
                "maximum_elevation_m": 780,
            },
            "popularity": {"athlete_count": 500, "effort_count": 1200, "star_count": 173},
            "comparison_scope": "测试山体公开骑行赛段",
            "nearby_comparisons": [
                {
                    "name": "测试盘山赛段反爬",
                    "source_url": "https://www.strava.com/segments/67890",
                    "relation": "同一山体反向局部爬坡",
                    "popularity": {"athlete_count": 700, "effort_count": 1800, "star_count": 91},
                }
            ],
        },
    }


def _reviewable_candidate(*, legacy_regression: bool = False):
    manifest = _manifest()
    if legacy_regression:
        observation = manifest["discovery"]["coordinate_observation"]
        observation["acquisition_mode"] = "legacy_verified_geometry_regression"
        observation["legacy_geometry_used"] = True

    def fake_planner(start, end):
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        return {
            "distance": 1500.0,
            "duration": 300.0,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": mid[0], "lon": mid[1]},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    def fake_elevation(points):
        snapshot = [[lon, lat, 700.0 + index * 20.0] for index, (lon, lat) in enumerate(points)]
        return SimpleNamespace(
            snapshot=snapshot,
            profile=[[0.0, 700.0], [3000.0, snapshot[-1][2]]],
            climb=80.0,
            descent=0.0,
            point_count=len(points),
        )

    return build.build_candidate(
        manifest,
        planner=fake_planner,
        elevation_builder=fake_elevation,
        wgs_to_gcj=lambda points: points,
        gcj_to_wgs=lambda points: points,
        elevation_method="glo30_meaningful_ascent_v1",
        elevation_metadata={"smoothing_sigma_m": 100.0, "processing_grid_m": 20.0},
        geometry_hasher=hash_segment_geometry_wkt,
        geometry_normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        delay_sec=0,
        now=datetime(2026, 8, 9, 9, 30, tzinfo=timezone.utc),
    )


def test_manifest_rejects_api_url_and_stale_unscoped_time():
    manifest = _manifest()
    manifest["discovery"]["source_url"] = "https://api.strava.com/api/v3/segments/12345"
    with pytest.raises(build.CandidateInputError, match="API"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["discovery"]["observed_at"] = "2026-08-09T17:30:00"
    with pytest.raises(build.CandidateInputError, match="时区"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["segment"]["city"] = "not-a-real-city"
    with pytest.raises(build.CandidateInputError, match="城市枚举"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["discovery"]["comparison_scope"] = None
    with pytest.raises(build.CandidateInputError, match="comparison_scope"):
        build.validate_manifest(manifest)


def test_manifest_rejects_wrong_target_identity_before_routing():
    manifest = _manifest()
    manifest["selection"]["identity_check"]["shape_match"] = "no"
    with pytest.raises(build.CandidateInputError, match="shape_match.*禁止进入腾讯算路"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["discovery"]["observed_metrics"]["distance_m"] = 11_690
    with pytest.raises(build.CandidateInputError, match="候选身份不成立"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["discovery"]["start_wgs84"] = {"lat": 37.7, "lon": 112.4}
    with pytest.raises(build.CandidateInputError, match="公开页面起点"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["reconstruction"]["tencent_routing_profile"] = "walking"
    with pytest.raises(build.CandidateInputError, match="只支持"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["discovery"]["coordinate_observation"]["legacy_geometry_used"] = True
    with pytest.raises(build.CandidateInputError, match="新收录模式不能"):
        build.validate_manifest(manifest)

    manifest = _manifest()
    manifest["discovery"]["coordinate_observation"]["acquisition_mode"] = (
        "legacy_verified_geometry_regression"
    )
    with pytest.raises(build.CandidateInputError, match="历史回归模式必须"):
        build.validate_manifest(manifest)


def test_manifest_accepts_negative_gradient_and_below_sea_level_elevation():
    manifest = _manifest()
    metrics = manifest["discovery"]["observed_metrics"]
    metrics["average_gradient_pct"] = -2.5
    metrics["minimum_elevation_m"] = -120
    metrics["maximum_elevation_m"] = -40

    validated = build.validate_manifest(manifest)

    assert validated["discovery"]["observed_metrics"]["average_gradient_pct"] == -2.5
    assert validated["discovery"]["observed_metrics"]["minimum_elevation_m"] == -120


def test_build_keeps_tencent_geometry_and_popularity_separate():
    def fake_planner(start, end):
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        return {
            "distance": 1500.0,
            "duration": 300.0,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": mid[0], "lon": mid[1]},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    def fake_elevation(points):
        snapshot = [[lon, lat, 700.0 + index * 20.0] for index, (lon, lat) in enumerate(points)]
        return SimpleNamespace(
            snapshot=snapshot,
            profile=[[0.0, 700.0], [3000.0, snapshot[-1][2]]],
            climb=80.0,
            descent=0.0,
            point_count=len(points),
        )

    result = build.build_candidate(
        _manifest(),
        planner=fake_planner,
        elevation_builder=fake_elevation,
        wgs_to_gcj=lambda points: points,
        gcj_to_wgs=lambda points: points,
        elevation_method="glo30_meaningful_ascent_v1",
        elevation_metadata={"smoothing_sigma_m": 100.0, "processing_grid_m": 20.0},
        geometry_hasher=lambda wkt: "test-geometry-hash",
        geometry_normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        delay_sec=0,
        now=datetime(2026, 8, 9, 9, 30, tzinfo=timezone.utc),
    )

    assert result["status"] == "needs_review"
    assert result["quality_gates"]["target_identity_match"] == "passed"
    assert result["quality_gates"]["gpx_independent_coordinates"] == "passed"
    assert result["identity_evidence"]["selection"]["source_segment_name"] == "测试盘山赛段公开名称"
    assert result["identity_evidence"]["source_observation"]["metrics"]["distance_m"] == 3200
    assert result["hard_knowledge"]["geometry"]["source"] == "tencent_directions"
    assert result["hard_knowledge"]["geometry"]["routing_profile"] == "bicycling"
    assert result["hard_knowledge"]["elevation"]["method"] == "glo30_meaningful_ascent_v1"
    assert result["hard_knowledge"]["elevation"]["metadata"]["smoothing_sigma_m"] == 100.0
    assert "athlete_count" not in result["hard_knowledge"]
    assert result["popularity_observation"]["athlete_count"] == 500
    assert result["popularity_observation"]["nearby_comparisons"][0]["effort_count"] == 1800
    assert "nearby_comparisons" not in result["hard_knowledge"]
    assert result["provenance"]["strava_api_used"] is False
    assert result["provenance"]["routing_points_gcj02"][0] == {"lon": 112.5, "lat": 37.8}
    assert result["provenance"]["tencent_leg_diagnostics"][0]["provider_duration_raw"] == 300.0
    assert result["quality_gates"]["tencent_distance_match"] == "passed"
    assert result["quality_gates"]["shape_match"] == "pending"
    assert result["derived_judgments"] == []


def test_build_rejects_wrong_tencent_distance_before_elevation():
    manifest = _manifest()
    manifest["target_definition"]["expected_distance_range_m"] = {"min": 9000, "max": 10000}
    manifest["discovery"]["observed_metrics"]["distance_m"] = 9500
    elevation_called = False

    def fake_planner(start, end):
        return {
            "distance": 1500.0,
            "duration": 300.0,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    def fake_elevation(points):
        nonlocal elevation_called
        elevation_called = True
        raise AssertionError("距离失败后不应调用海拔")

    with pytest.raises(RuntimeError, match="腾讯路线距离不在目标预期范围"):
        build.build_candidate(
            manifest,
            planner=fake_planner,
            elevation_builder=fake_elevation,
            wgs_to_gcj=lambda points: points,
            gcj_to_wgs=lambda points: points,
            elevation_method="glo30_meaningful_ascent_v1",
            geometry_hasher=lambda wkt: "should-not-be-called",
            geometry_normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
            delay_sec=0,
        )
    assert elevation_called is False


def test_cli_reports_dem_service_error_without_traceback(monkeypatch, tmp_path, capsys):
    from app.elevation.dem_client import DEMServiceError

    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    output_path = tmp_path / "candidate.json"
    monkeypatch.delenv("GLO30_CACHE_DIR", raising=False)
    monkeypatch.setattr(
        build,
        "build_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(DEMServiceError("测试 DEM 失败")),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["build_candidate.py", str(input_path), "--output", str(output_path)],
    )

    assert build.main() == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "ERROR: 测试 DEM 失败"
    assert "Traceback" not in captured.err
    assert "velo-road-segment-glo30-cache" in build.os.environ["GLO30_CACHE_DIR"]


def test_review_cannot_accept_without_all_real_world_checks():
    candidate = _reviewable_candidate()
    with pytest.raises(review.ReviewError, match="shape_match"):
        review.review_candidate(
            candidate,
            verdict="accept",
            reviewer="Tim",
            note="已对照",
            endpoint_match="yes",
            direction_match="yes",
            shape_match="no",
            warnings_reviewed="yes",
        )

    verified = review.review_candidate(
        candidate,
        verdict="accept",
        reviewer="Tim",
        note="逐段对照腾讯地图与公开赛段路形一致",
        endpoint_match="yes",
        direction_match="yes",
        shape_match="yes",
        warnings_reviewed="yes",
        now=datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc),
    )
    assert verified["status"] == "verified"
    assert verified["publication_eligible"] is True
    assert verified["review"]["reviewed_geometry_hash"] == candidate["hard_knowledge"]["geometry"]["geometry_hash"]
    assert all(
        verified["quality_gates"][key] == "passed"
        for key in ("endpoint_match", "direction_match", "shape_match", "warnings_reviewed")
    )


def test_rejection_distinguishes_failed_from_not_checked():
    candidate = _reviewable_candidate()
    rejected = review.review_candidate(
        candidate,
        verdict="reject",
        reviewer="Tim",
        note="腾讯在第二个发卡弯走错岔路",
        shape_match="no",
    )
    assert rejected["quality_gates"]["shape_match"] == "failed"
    assert rejected["quality_gates"]["endpoint_match"] == "not_checked"


def test_legacy_coordinate_regression_cannot_become_publishable_verified_data():
    candidate = _reviewable_candidate(legacy_regression=True)
    result = review.review_candidate(
        candidate,
        verdict="accept",
        reviewer="Codex",
        note="只确认腾讯重建与历史同轨一致",
        endpoint_match="yes",
        direction_match="yes",
        shape_match="yes",
        warnings_reviewed="yes",
    )
    assert result["status"] == "verified_regression"
    assert result["publication_eligible"] is False


def test_review_rejects_incomplete_or_tampered_candidate_contract():
    incomplete = _reviewable_candidate()
    del incomplete["hard_knowledge"]["elevation"]["metadata"]
    with pytest.raises(review.ReviewError, match="elevation.metadata"):
        review.review_candidate(
            incomplete,
            verdict="accept",
            reviewer="Codex",
            note="不应接受",
            endpoint_match="yes",
            direction_match="yes",
            shape_match="yes",
            warnings_reviewed="yes",
        )

    tampered = _reviewable_candidate(legacy_regression=True)
    tampered["quality_gates"]["gpx_independent_coordinates"] = "passed"
    with pytest.raises(review.ReviewError, match="来源门槛"):
        review.review_candidate(
            tampered,
            verdict="accept",
            reviewer="Codex",
            note="不应接受",
            endpoint_match="yes",
            direction_match="yes",
            shape_match="yes",
            warnings_reviewed="yes",
        )

    divergent_geometry = _reviewable_candidate()
    divergent_geometry["hard_knowledge"]["geometry"]["wkt"] = "LINESTRING(0 0, 1 1)"
    divergent_geometry["hard_knowledge"]["geometry"]["geometry_hash"] = (
        hash_segment_geometry_wkt("LINESTRING(0 0, 1 1)")
    )
    with pytest.raises(review.ReviewError, match="WKT 与腾讯 geometry.points"):
        review.review_candidate(
            divergent_geometry,
            verdict="accept",
            reviewer="Codex",
            note="不应接受",
            endpoint_match="yes",
            direction_match="yes",
            shape_match="yes",
            warnings_reviewed="yes",
        )


def test_tianlongshan_example_preserves_historical_and_current_algorithms():
    example_dir = ROOT / ".agents/skills/ingest-velo-road-segments/examples"
    manifest = json.loads(
        (example_dir / "tianlongshan-y7-public-observation-2026-08-09.json").read_text()
    )
    evidence = json.loads(
        (example_dir / "tianlongshan-y7-verification-2026-08-09.json").read_text()
    )

    assert build.validate_manifest(manifest)["reconstruction"]["tencent_routing_profile"] == "driving"
    assert evidence["historical_elevation_anchor"]["descent_sum_m"] == pytest.approx(561.4113779904653)
    assert evidence["current_verified_run"]["elevation_method"] == "glo30_meaningful_ascent_v1"
    assert evidence["current_verified_run"]["elevation_gain_m"] == 585.5
    assert evidence["status"] == "verified_regression"
    assert evidence["publication"] == {
        "eligible": False,
        "blocking_gate": "gpx_independent_coordinates=regression_only",
        "database_written": False,
        "production_deployed": False,
    }
