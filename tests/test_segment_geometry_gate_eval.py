"""固定 Eval：第一例真实走完天龙山完整正爬，再挡真实万亩截短和错序线。"""

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

import app.segment.geometry_rebuild as geometry_rebuild
from app.common.geometry_hash import SEGMENT_GEOMETRY_NORMALIZATION_VERSION, stable_line_hash
from app.elevation.route_elevation import RouteElevationResult
from app.segment._geo_utils import _haversine
from app.segment.geometry_rebuild import (
    PreparedSegmentGeometry,
    SegmentGeometryGateError,
    activate_revision_core,
    build_segment_geometry_gate_metrics,
    enforce_segment_geometry_gate_metrics,
    parse_linestring_wkt,
    prepare_segment_geometry_from_evidence,
    stage_geometry_revision,
)
from app.segment.models import Segment, SegmentGeometryRevision, SegmentRoutingCandidate
from app.segment.routing_candidates import routing_candidate_record_hash
from app.segment.source_observations import (
    SegmentSourceObservationError,
    resolve_source_observation,
    source_observation_catalog,
)


FIXTURES = Path("tests/fixtures/segment_geometry_gates")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _gpx_wkt(path: str) -> str:
    root = ET.parse(path).getroot()
    points = [
        (float(point.attrib["lon"]), float(point.attrib["lat"]))
        for point in root.iter()
        if point.tag.endswith("trkpt")
    ]
    return "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in points) + ")"


def _distance(wkt: str) -> float:
    points = parse_linestring_wkt(wkt)
    return sum(
        _haversine(*points[index - 1], *points[index])
        for index in range(1, len(points))
    )


def _prepared_from_fixture(fixture: dict) -> PreparedSegmentGeometry:
    points = parse_linestring_wkt(fixture["wkt"])
    return PreparedSegmentGeometry(
        reference_line_wkt=fixture["wkt"],
        geometry_hash=stable_line_hash(fixture["wkt"]),
        distance=_distance(fixture["wkt"]),
        elevation_gain=float(fixture.get("elevation_gain_m", 1.0)),
        elevation_loss=float(fixture.get("elevation_loss_m", 0.0)),
        avg_gradient=float(fixture.get("average_gradient_pct", 0.1)),
        elevation_profile_json="[830.0,1000.0,1356.0]",
        max_gradient=float(fixture.get("maximum_gradient_pct", 1.0)),
        difficulty="hard",
        city="taiyuan",
        start_lat=points[0][0],
        start_lon=points[0][1],
        end_lat=points[-1][0],
        end_lon=points[-1][1],
    )


def test_first_eval_is_real_tianlongshan_full_climb_through_final_write_gate(
    db,
    monkeypatch,
):
    fixture = _fixture("tianlongshan_y7_driving_v1.json")
    assert fixture["case_id"] == "tianlongshan-y7-full-climb-positive"
    assert fixture["role"] == "first_eval_canonical_positive"
    assert fixture["routing_provider"] == "tencent"
    assert fixture["routing_mode"] == "driving"

    previous_wkt = _gpx_wkt("content/routes/tianlongshan/track.gpx")
    previous_points = parse_linestring_wkt(previous_wkt)
    candidate_points = parse_linestring_wkt(fixture["wkt"])
    assert len(candidate_points) == 505

    segment = Segment(
        id=21,
        name="天龙山网红公路爬坡",
        distance=_distance(previous_wkt),
        elevation_gain=561.0,
        elevation_loss=0.0,
        avg_gradient=5.6,
        elevation_profile="[830.0,1356.0]",
        max_gradient=11.0,
        difficulty="hard",
        city="taiyuan",
        start_lat=previous_points[0][0],
        start_lon=previous_points[0][1],
        end_lat=previous_points[-1][0],
        end_lon=previous_points[-1][1],
        reference_line=f"SRID=4326;{previous_wkt}",
        match_tolerance=50.0,
        min_match_ratio=0.8,
    )
    db.add(segment)
    db.commit()
    observation = resolve_source_observation(
        fixture["source_observation_id"],
        segment_id=segment.id,
        segment_name=segment.name,
        current_wkt=previous_wkt,
        current_start_lat=previous_points[0][0],
        current_start_lon=previous_points[0][1],
        current_end_lat=previous_points[-1][0],
        current_end_lon=previous_points[-1][1],
    )
    routing_candidate = SegmentRoutingCandidate(
        segment_id=segment.id,
        status="ready",
        routing_provider="tencent",
        routing_mode="driving",
        control_points_json=json.dumps(
            [
                {"lat": candidate_points[0][0], "lon": candidate_points[0][1]},
                {"lat": candidate_points[-1][0], "lon": candidate_points[-1][1]},
            ],
            sort_keys=True,
            separators=(",", ":"),
        ),
        reference_line_wkt=fixture["wkt"],
        geometry_hash=fixture["geometry_hash"],
        provider_distance_m=fixture["provider_distance_m"],
        measured_distance_m=_distance(fixture["wkt"]),
        record_hash="pending",
    )
    routing_candidate.record_hash = routing_candidate_record_hash(routing_candidate)
    db.add(routing_candidate)
    db.commit()

    frozen_elevation = RouteElevationResult(
        snapshot=fixture["elevation_snapshot"],
        profile=fixture["elevation_profile"],
        climb=fixture["elevation_gain_m"],
        descent=fixture["elevation_loss_m"],
        point_count=len(fixture["elevation_snapshot"]),
    )

    def fixed_tianlongshan_elevation(points):
        assert len(points) == 505
        assert points[0] == {
            "lat": pytest.approx(candidate_points[0][0]),
            "lon": pytest.approx(candidate_points[0][1]),
        }
        return frozen_elevation

    monkeypatch.setattr(
        geometry_rebuild,
        "_build_segment_elevation_result",
        fixed_tianlongshan_elevation,
    )
    prepared = prepare_segment_geometry_from_evidence(
        db,
        segment_id=segment.id,
        source_observation_id=observation.observation_id,
        routing_candidate_id=routing_candidate.id,
    )
    assert prepared.geometry_hash == fixture["geometry_hash"]
    assert prepared.distance == pytest.approx(fixture["distance_m"], abs=0.01)
    assert prepared.elevation_gain == fixture["elevation_gain_m"]
    assert prepared.elevation_loss == fixture["elevation_loss_m"]

    revision = stage_geometry_revision(
        db,
        segment_id=segment.id,
        prepared=prepared,
        source_observation_id=observation.observation_id,
        routing_candidate_id=routing_candidate.id,
        created_by=1,
    )
    revision.status = "processing"
    revision.job_id = "eval-tianlongshan-full-climb"
    db.commit()
    summary = activate_revision_core(
        db,
        revision_id=revision.id,
        attempt_job_id=revision.job_id,
        precomputed_efforts={},
    )
    db.commit()

    assert summary.segment_id == segment.id
    assert db.get(SegmentGeometryRevision, revision.id).status == "active"
    assert db.get(Segment, segment.id).distance == pytest.approx(9956.42, abs=1.0)


def test_source_catalog_starts_with_tianlongshan_and_binds_exact_segment_id():
    catalog = source_observation_catalog()
    assert list(catalog)[:2] == [
        "strava-33134150-2026-08-09",
        "strava-13019992-2026-08-09",
    ]
    tianlongshan = catalog["strava-33134150-2026-08-09"]
    assert tianlongshan.target_segment_id == 21
    with pytest.raises(SegmentSourceObservationError, match="segment id"):
        resolve_source_observation(
            tianlongshan.observation_id,
            segment_id=22,
            segment_name="天龙山网红公路爬坡",
            current_wkt="LINESTRING(112 37,112.1 37.1)",
            current_start_lat=37.0,
            current_start_lon=112.0,
            current_end_lat=37.1,
            current_end_lon=112.1,
        )


def test_real_wanmu_3749_truncation_is_a_permanent_negative():
    fixture = _fixture("wanmu_truncated_3749_v1.json")
    observation = source_observation_catalog()["strava-13019992-2026-08-09"]
    assert observation.target_segment_id == 22
    assert observation.observed_distance_m == 4250.0
    previous_wkt = _gpx_wkt("content/routes/wanmu/track.gpx")
    previous_points = parse_linestring_wkt(previous_wkt)
    prepared = _prepared_from_fixture(fixture)
    metrics = build_segment_geometry_gate_metrics(
        previous_wkt=previous_wkt,
        current_distance_m=_distance(previous_wkt),
        current_start_lat=previous_points[0][0],
        current_start_lon=previous_points[0][1],
        current_end_lat=previous_points[-1][0],
        current_end_lon=previous_points[-1][1],
        prepared=prepared,
        source_url=observation.source_url,
        source_distance_m=observation.observed_distance_m,
    )

    with pytest.raises(SegmentGeometryGateError) as raised:
        enforce_segment_geometry_gate_metrics(metrics)

    assert raised.value.gate == "source"
    assert raised.value.violations[0]["code"] == "source_distance_mismatch"
    assert metrics.discrete_frechet_m > 50.0


def test_same_vertices_in_wrong_order_fail_the_order_sensitive_geometry_gate():
    previous_wkt = (
        "LINESTRING(112 37,112.001 37.001,112.001 36.999,112.002 37)"
    )
    candidate_wkt = (
        "LINESTRING(112 37,112.001 36.999,112.001 37.001,112.002 37)"
    )
    previous_points = parse_linestring_wkt(previous_wkt)
    prepared = _prepared_from_fixture(
        {
            "wkt": candidate_wkt,
            "elevation_gain_m": 1.0,
            "elevation_loss_m": 0.0,
            "average_gradient_pct": 0.1,
            "maximum_gradient_pct": 1.0,
        }
    )
    metrics = build_segment_geometry_gate_metrics(
        previous_wkt=previous_wkt,
        current_distance_m=_distance(previous_wkt),
        current_start_lat=previous_points[0][0],
        current_start_lon=previous_points[0][1],
        current_end_lat=previous_points[-1][0],
        current_end_lon=previous_points[-1][1],
        prepared=prepared,
        source_url="https://www.strava.com/segments/123",
        source_distance_m=prepared.distance,
    )

    with pytest.raises(SegmentGeometryGateError) as raised:
        enforce_segment_geometry_gate_metrics(metrics)

    assert {item["code"] for item in raised.value.violations} & {
        "hausdorff_distance",
        "discrete_frechet_distance",
    }
