"""标准赛段几何替换：API 暂存合同与原子成绩切换。"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func

from app.common.geometry_hash import SEGMENT_GEOMETRY_NORMALIZATION_VERSION, stable_line_hash
from app.segment.geometry_rebuild import (
    EffortCandidate,
    ObsoleteSegmentGeometryAttempt,
    PreparedSegmentGeometry,
    SEGMENT_GEOMETRY_GATE_VERSION,
    SegmentGeometryGateError,
    SegmentGeometryGateMetrics,
    activate_revision_core,
    candidate_payload_hash,
    build_segment_geometry_gate_metrics,
    enforce_segment_geometry_gate_metrics,
    mark_revision_failed,
    parse_linestring_wkt,
    prepare_segment_geometry,
)
from app.segment._geo_utils import _haversine
from app.segment.models import (
    Segment,
    SegmentEffort,
    SegmentGeometryRevision,
    SegmentRoutingCandidate,
)
from app.segment.routing_candidates import routing_candidate_record_hash
from app.segment.source_observations import (
    SegmentSourceObservation,
    SegmentSourceObservationError,
    parse_strava_segment_id,
)


class _Job:
    def __init__(self, job_id):
        self.id = job_id


class _Queue:
    def __init__(self):
        self.calls = []

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _Job(kwargs["job_id"])


class _FailQueue:
    def enqueue(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


@pytest.fixture(autouse=True)
def _use_fixed_test_source_observation(monkeypatch):
    def resolve(observation_id, **_kwargs):
        return _source_observation(observation_id=observation_id)

    monkeypatch.setattr("app.segment.geometry_rebuild.resolve_source_observation", resolve)


def _source_observation(
    *,
    observation_id: str = "test-source-observation",
    distance_m: float = 1418.0,
) -> SegmentSourceObservation:
    return SegmentSourceObservation(
        observation_id=observation_id,
        source_segment_id="123",
        source_url="https://www.strava.com/segments/123",
        observed_distance_m=distance_m,
        observed_at="2026-08-09T00:00:00+08:00",
        target_segment_id=1,
        target_segment_names=("测试赛段",),
        expected_start_lat=37.7,
        expected_start_lon=112.4,
        expected_end_lat=37.71,
        expected_end_lon=112.41,
        endpoint_tolerance_m=100.0,
        trusted_baseline_geometry_hash="0" * 64,
    )


def _segment(db, *, name="测试赛段") -> Segment:
    segment = Segment(
        name=name,
        distance=1417.0,
        elevation_gain=100.0,
        elevation_loss=10.0,
        avg_gradient=5.0,
        elevation_profile="[100,200]",
        max_gradient=8.0,
        difficulty="medium",
        city="taiyuan",
        start_lat=37.7,
        start_lon=112.4,
        end_lat=37.71,
        end_lon=112.41,
        reference_line="SRID=4326;LINESTRING(112.4 37.7,112.41 37.71)",
        match_tolerance=50.0,
        min_match_ratio=0.8,
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _prepared() -> PreparedSegmentGeometry:
    wkt = "LINESTRING(112.4 37.7,112.405 37.70505,112.41 37.71)"
    return PreparedSegmentGeometry(
        reference_line_wkt=wkt,
        geometry_hash=stable_line_hash(wkt),
        distance=1418.0,
        elevation_gain=220.0,
        elevation_loss=20.0,
        avg_gradient=8.5,
        elevation_profile_json="[100,180,320]",
        max_gradient=12.0,
        difficulty="hard",
        city="taiyuan",
        start_lat=37.7,
        start_lon=112.4,
        end_lat=37.71,
        end_lon=112.41,
    )


def _prepared_for_wkt(wkt: str) -> PreparedSegmentGeometry:
    coordinates = parse_linestring_wkt(wkt)
    distance = sum(
        _haversine(*coordinates[index - 1], *coordinates[index])
        for index in range(1, len(coordinates))
    )
    return replace(
        _prepared(),
        reference_line_wkt=wkt,
        geometry_hash=stable_line_hash(wkt),
        distance=distance,
        start_lat=coordinates[0][0],
        start_lon=coordinates[0][1],
        end_lat=coordinates[-1][0],
        end_lon=coordinates[-1][1],
    )


def _routing_candidate(
    db,
    segment: Segment,
    prepared: PreparedSegmentGeometry | None = None,
) -> SegmentRoutingCandidate:
    prepared = prepared or _prepared()
    candidate = SegmentRoutingCandidate(
        segment_id=segment.id,
        status="ready",
        routing_provider="tencent",
        routing_mode="driving",
        control_points_json='[{"lat":37.7,"lon":112.4},{"lat":37.71,"lon":112.41}]',
        reference_line_wkt=prepared.reference_line_wkt,
        geometry_hash=prepared.geometry_hash,
        provider_distance_m=prepared.distance,
        measured_distance_m=prepared.distance,
        record_hash="pending",
    )
    candidate.record_hash = routing_candidate_record_hash(candidate)
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


def _evidence_payload(candidate: SegmentRoutingCandidate) -> dict:
    return {
        "source_observation_id": "test-source-observation",
        "routing_candidate_id": candidate.id,
    }


def _processing_revision(
    db,
    segment: Segment,
    *,
    prepared: PreparedSegmentGeometry | None = None,
    source_distance_m: float = 1418.0,
    candidate_wkt: str | None = None,
    candidate_geometry_hash: str | None = None,
    candidate_payload_hash_value: str | None = None,
    job_id: str = "segment-geometry-test-attempt",
) -> SegmentGeometryRevision:
    prepared = prepared or _prepared()
    routing_candidate = _routing_candidate(db, segment, prepared)
    routing_candidate.status = "consumed"
    previous_wkt = (
        db.query(func.ST_AsText(Segment.reference_line))
        .filter(Segment.id == segment.id)
        .scalar()
    )
    revision = SegmentGeometryRevision(
        segment_id=segment.id,
        status="processing",
        previous_geometry_hash=stable_line_hash(previous_wkt),
        candidate_geometry_hash=candidate_geometry_hash or prepared.geometry_hash,
        previous_reference_line_wkt=previous_wkt,
        candidate_reference_line_wkt=candidate_wkt or prepared.reference_line_wkt,
        previous_snapshot_json=json.dumps({"distance": segment.distance}),
        distance=prepared.distance,
        elevation_gain=prepared.elevation_gain,
        elevation_loss=prepared.elevation_loss,
        avg_gradient=prepared.avg_gradient,
        elevation_profile=prepared.elevation_profile_json,
        max_gradient=prepared.max_gradient,
        difficulty=prepared.difficulty,
        city=prepared.city,
        start_lat=prepared.start_lat,
        start_lon=prepared.start_lon,
        end_lat=prepared.end_lat,
        end_lon=prepared.end_lon,
        match_tolerance=50.0,
        min_match_ratio=0.8,
        source_url="https://www.strava.com/segments/123",
        source_segment_id="123",
        source_distance_m=source_distance_m,
        source_observation_id="test-source-observation",
        routing_candidate_id=routing_candidate.id,
        candidate_payload_hash=(
            candidate_payload_hash_value
            if candidate_payload_hash_value is not None
            else candidate_payload_hash(prepared)
        ),
        validation_version=SEGMENT_GEOMETRY_GATE_VERSION,
        validation_metrics_json="{}",
        routing_provider="tencent",
        routing_mode="driving",
        original_coordinate_system="wgs84",
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        job_id=job_id,
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return revision


def test_admin_stages_driving_geometry_without_touching_live_segment(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    candidate = _routing_candidate(db, segment)
    queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry_from_evidence",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        queue,
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json=_evidence_payload(candidate),
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["segment_id"] == segment.id
    assert payload["status"] == "staged"
    assert payload["routing_provider"] == "tencent"
    assert payload["routing_mode"] == "driving"
    assert payload["job_id"] == queue.calls[0][1]["job_id"]
    assert queue.calls[0][0][1] == payload["id"]
    assert queue.calls[0][0][2] == payload["job_id"]

    live_segment = db.get(Segment, segment.id)
    assert live_segment.distance == 1417.0
    assert live_segment.elevation_gain == 100.0
    revision = db.get(SegmentGeometryRevision, payload["id"])
    assert revision.distance == 1418.0
    assert revision.source_segment_id == "123"
    assert revision.source_observation_id == "test-source-observation"
    assert revision.routing_candidate_id == candidate.id
    assert revision.candidate_payload_hash
    assert revision.validation_version == SEGMENT_GEOMETRY_GATE_VERSION
    assert revision.previous_reference_line_wkt != revision.candidate_reference_line_wkt

    status = client.get(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}",
        headers=admin_header,
    )
    assert status.status_code == 200
    assert status.json()["job_id"] == payload["job_id"]


def test_processing_revision_requires_expired_lease_before_retry(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    revision = _processing_revision(db, segment)
    revision.started_at = datetime.now(timezone.utc)
    db.commit()

    fresh = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}/retry",
        headers=admin_header,
    )
    assert fresh.status_code == 409

    revision.started_at = datetime.now(timezone.utc) - timedelta(minutes=80)
    db.commit()
    queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        queue,
    )
    stale = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}/retry",
        headers=admin_header,
    )
    assert stale.status_code == 202, stale.text
    assert stale.json()["status"] == "processing"
    assert stale.json()["job_id"] == queue.calls[0][1]["job_id"]

    mark_revision_failed(
        db,
        revision.id,
        "late old attempt",
        attempt_job_id="obsolete-attempt",
    )
    assert db.get(SegmentGeometryRevision, revision.id).status == "processing"
    with pytest.raises(ObsoleteSegmentGeometryAttempt):
        activate_revision_core(
            db,
            revision_id=revision.id,
            attempt_job_id="obsolete-attempt",
            precomputed_efforts={},
        )


def test_historical_revision_without_current_gate_evidence_is_not_retried(
    client,
    db,
    admin_header,
):
    segment = _segment(db)
    revision = _processing_revision(db, segment)
    revision.status = "failed"
    revision.source_observation_id = None
    revision.routing_candidate_id = None
    revision.candidate_payload_hash = None
    db.commit()

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}/retry",
        headers=admin_header,
    )

    assert response.status_code == 409
    assert "历史几何任务" in response.json()["detail"]


def test_staged_revision_with_job_id_recovers_only_when_claim_expired_and_job_missing(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    candidate = _routing_candidate(db, segment)
    first_queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry_from_evidence",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        first_queue,
    )
    created = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json=_evidence_payload(candidate),
    )
    assert created.status_code == 202
    revision = db.get(SegmentGeometryRevision, created.json()["id"])
    old_job_id = revision.job_id
    revision.dispatch_claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()

    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow._rq_job_is_live",
        lambda job_id: True,
    )
    live = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}/retry",
        headers=admin_header,
    )
    assert live.status_code == 409

    second_queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow._rq_job_is_live",
        lambda job_id: False,
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        second_queue,
    )
    missing = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}/retry",
        headers=admin_header,
    )
    assert missing.status_code == 202, missing.text
    assert missing.json()["job_id"] != old_job_id
    assert second_queue.calls[0][1]["job_id"] == missing.json()["job_id"]


def test_rebuild_request_rejects_raw_points_and_bicycling_claims(client, db, admin_header):
    segment = _segment(db)
    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "source_observation_id": "test-source-observation",
            "routing_candidate_id": 1,
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
            ],
            "routing_mode": "bicycling",
        },
    )
    assert response.status_code == 422
    assert db.query(SegmentGeometryRevision).count() == 0


def test_routing_candidate_requires_at_least_two_control_points(client, db, admin_header):
    segment = _segment(db)

    response = client.post(
        f"/api/admin/segments/{segment.id}/routing-candidates",
        headers=admin_header,
        json={
            "control_points": [{"lat": 37.7, "lon": 112.4}],
            "coordinate_system": "wgs84",
        },
    )

    assert response.status_code == 422
    assert db.query(SegmentGeometryRevision).count() == 0


def test_routing_candidate_is_generated_by_server_side_tencent_driving(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    calls = []

    def fake_driving(start, end):
        calls.append((start, end))
        return {
            "distance": 1418.0,
            "duration": 300,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": 37.705, "lon": 112.405},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr(
        "app.admin.segment_routing_candidate_workflow.plan_tencent_driving_route",
        fake_driving,
    )
    response = client.post(
        f"/api/admin/segments/{segment.id}/routing-candidates",
        headers=admin_header,
        json={
            "control_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
            ],
            "coordinate_system": "gcj02",
        },
    )

    assert response.status_code == 201, response.text
    assert len(calls) == 1
    candidate = db.get(SegmentRoutingCandidate, response.json()["id"])
    assert candidate.routing_provider == "tencent"
    assert candidate.routing_mode == "driving"
    assert candidate.status == "ready"
    assert candidate.record_hash == routing_candidate_record_hash(candidate)


def test_routing_candidate_rejects_discontinuous_tencent_legs(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    calls = []

    def discontinuous_driving(start, end):
        calls.append((start, end))
        first = {"lat": start[0], "lon": start[1]}
        if len(calls) == 2:
            first = {"lat": start[0] + 0.0003, "lon": start[1]}
        return {
            "distance": 800.0,
            "duration": 180,
            "points": [
                first,
                {"lat": (start[0] + end[0]) / 2, "lon": (start[1] + end[1]) / 2},
                {"lat": end[0], "lon": end[1]},
            ],
        }

    monkeypatch.setattr(
        "app.admin.segment_routing_candidate_workflow.plan_tencent_driving_route",
        discontinuous_driving,
    )
    response = client.post(
        f"/api/admin/segments/{segment.id}/routing-candidates",
        headers=admin_header,
        json={
            "control_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.705, "lon": 112.405},
                {"lat": 37.71, "lon": 112.41},
            ],
            "coordinate_system": "gcj02",
        },
    )

    assert response.status_code == 422
    assert len(calls) == 2
    assert db.query(SegmentRoutingCandidate).count() == 0


@pytest.mark.parametrize(
    "candidate_wkt",
    [
        "LINESTRING(112.4 37.7,112.4035 37.7035,112.407 37.707)",
        "LINESTRING(112.4 37.7,112.4065 37.7065,112.413 37.713)",
    ],
)
def test_admin_rejects_implausible_length_change_for_same_segment_id(
    client,
    db,
    admin_header,
    monkeypatch,
    candidate_wkt,
):
    segment = _segment(db)
    prepared = _prepared_for_wkt(candidate_wkt)
    candidate = _routing_candidate(db, segment, prepared)
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry_from_evidence",
        lambda *args, **kwargs: prepared,
    )
    monkeypatch.setattr(
        "app.segment.geometry_rebuild.resolve_source_observation",
        lambda observation_id, **kwargs: _source_observation(
            observation_id=observation_id,
            distance_m=prepared.distance,
        ),
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json=_evidence_payload(candidate),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "segment_geometry_gate_failed"
    assert detail["gate"] == "geometry"
    assert "current_distance_mismatch" in {
        violation["code"] for violation in detail["violations"]
    }
    assert db.query(SegmentGeometryRevision).count() == 0


def test_admin_rejects_candidate_for_a_different_real_world_segment(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    wrong_segment = _prepared_for_wkt(
        "LINESTRING(112.4 37.7,112.41 37.705,112.42 37.71)"
    )
    candidate = _routing_candidate(db, segment, wrong_segment)
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry_from_evidence",
        lambda *args, **kwargs: wrong_segment,
    )
    monkeypatch.setattr(
        "app.segment.geometry_rebuild.resolve_source_observation",
        lambda observation_id, **kwargs: _source_observation(
            observation_id=observation_id,
            distance_m=wrong_segment.distance,
        ),
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json=_evidence_payload(candidate),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["gate"] == "geometry"
    assert {item["code"] for item in detail["violations"]} & {
        "end_endpoint_shift",
        "hausdorff_distance",
    }
    assert db.query(SegmentGeometryRevision).count() == 0


def test_admin_rejects_strava_distance_mismatch_without_staging(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    candidate = _routing_candidate(db, segment)
    queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry_from_evidence",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.segment.geometry_rebuild.resolve_source_observation",
        lambda observation_id, **kwargs: _source_observation(
            observation_id=observation_id,
            distance_m=1470.0,
        ),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        queue,
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json=_evidence_payload(candidate),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["gate"] == "source"
    assert detail["violations"][0]["code"] == "source_distance_mismatch"
    assert db.query(SegmentGeometryRevision).count() == 0
    assert queue.calls == []


def test_source_distance_gate_runs_before_elevation_query(monkeypatch):
    elevation_called = False

    def fail_if_called(_points):
        nonlocal elevation_called
        elevation_called = True
        raise AssertionError("来源门失败后不应查询海拔")

    monkeypatch.setattr(
        "app.segment.geometry_rebuild._build_segment_elevation_result",
        fail_if_called,
    )

    with pytest.raises(SegmentGeometryGateError) as raised:
        prepare_segment_geometry(
            [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.705, "lon": 112.405},
                {"lat": 37.71, "lon": 112.41},
            ],
            coordinate_system="wgs84",
            source_distance_m=1000.0,
        )

    assert raised.value.gate == "source"
    assert elevation_called is False


def test_dispatch_failure_marks_revision_failed_without_touching_live_segment(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    candidate = _routing_candidate(db, segment)
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry_from_evidence",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        _FailQueue(),
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json=_evidence_payload(candidate),
    )

    assert response.status_code == 503
    revision = db.query(SegmentGeometryRevision).one()
    assert revision.status == "failed"
    assert "redis unavailable" in revision.error_message
    live_segment = db.get(Segment, segment.id)
    assert live_segment.distance == 1417.0
    assert live_segment.elevation_gain == 100.0

    queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        queue,
    )
    retry = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions/{revision.id}/retry",
        headers=admin_header,
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["status"] == "staged"
    assert retry.json()["job_id"] == queue.calls[0][1]["job_id"]


@pytest.mark.parametrize(
    "points",
    [
        [{"lat": True, "lon": 112.4}, {"lat": 37.72, "lon": 112.42}],
        [{"lat": 91.0, "lon": 112.4}, {"lat": 37.72, "lon": 112.42}],
        [{"lat": 37.7, "lon": 112.4}] * 21,
    ],
)
def test_admin_rejects_invalid_routing_control_points_before_tencent_call(
    client,
    db,
    admin_header,
    points,
):
    segment = _segment(db)
    response = client.post(
        f"/api/admin/segments/{segment.id}/routing-candidates",
        headers=admin_header,
        json={
            "control_points": points,
            "coordinate_system": "wgs84",
        },
    )

    assert response.status_code == 422
    assert db.query(SegmentRoutingCandidate).count() == 0


@pytest.mark.parametrize(
    "source_url",
    [
        "http://www.strava.com/segments/456",
        "https://www.strava.com/segments/456?source=agent",
        "https://www.strava.com/segments/456#summary",
    ],
)
def test_admin_requires_exact_https_strava_segment_url(
    source_url,
):
    with pytest.raises(SegmentSourceObservationError):
        parse_strava_segment_id(source_url)


def test_activation_keeps_segment_id_and_atomically_rebuilds_efforts(db):
    segment = _segment(db)
    revision = _processing_revision(db, segment)
    db.add_all(
        [
            SegmentEffort(
                segment_id=segment.id,
                activity_id=1,
                user_id=11,
                elapsed_time=600,
                avg_speed=6.0,
                start_index=1,
                end_index=10,
            ),
            SegmentEffort(
                segment_id=segment.id,
                activity_id=2,
                user_id=12,
                elapsed_time=700,
                avg_speed=5.1,
                start_index=1,
                end_index=10,
            ),
        ]
    )
    db.commit()

    summary = activate_revision_core(
        db,
        revision_id=revision.id,
        attempt_job_id=revision.job_id,
        precomputed_efforts={
            1: EffortCandidate(1, 11, 500, 15.8, 210.0, 3, 20),
            3: EffortCandidate(3, 13, 550, 14.4, None, 5, 25),
        },
    )
    db.commit()

    assert summary.segment_id == segment.id
    assert (summary.updated_efforts, summary.inserted_efforts, summary.deleted_efforts) == (1, 1, 1)
    live_segment = db.get(Segment, segment.id)
    assert live_segment.distance == 1418.0
    assert live_segment.elevation_gain == 220.0
    assert live_segment.difficulty == "hard"
    active_revision = db.get(SegmentGeometryRevision, revision.id)
    assert active_revision.status == "active"
    assert active_revision.validation_metrics_json != "{}"
    efforts = db.query(SegmentEffort).filter_by(segment_id=segment.id).order_by(SegmentEffort.activity_id).all()
    assert [(effort.activity_id, effort.elapsed_time) for effort in efforts] == [(1, 500), (3, 550)]
    assert efforts[0].avg_speed == 15.8
    assert db.query(func.count(SegmentEffort.id)).scalar() == 2

    mark_revision_failed(
        db,
        revision.id,
        "late duplicate worker failure",
        attempt_job_id=revision.job_id,
    )
    assert db.get(SegmentGeometryRevision, revision.id).status == "active"
    assert db.get(SegmentGeometryRevision, revision.id).error_message is None


def test_write_gate_rechecks_revision_and_leaves_live_data_untouched(db):
    segment = _segment(db)
    revision = _processing_revision(
        db,
        segment,
        source_distance_m=2000.0,
        job_id="segment-geometry-write-gate-test",
    )

    with pytest.raises(SegmentGeometryGateError) as raised:
        activate_revision_core(
            db,
            revision_id=revision.id,
            attempt_job_id=revision.job_id,
            precomputed_efforts={},
        )
    assert raised.value.violations[0]["code"] == "source_observation_changed"
    db.rollback()

    live_segment = db.get(Segment, segment.id)
    assert live_segment.distance == 1417.0
    assert stable_line_hash(
        db.query(func.ST_AsText(Segment.reference_line))
        .filter(Segment.id == segment.id)
        .scalar()
    ) == revision.previous_geometry_hash


def test_write_gate_rejects_candidate_geometry_changed_after_staging(db):
    segment = _segment(db)
    tampered_wkt = "LINESTRING(112.4 37.7,112.405 37.7051,112.41 37.71)"
    revision = _processing_revision(
        db,
        segment,
        candidate_wkt=tampered_wkt,
        job_id="segment-geometry-hash-gate-test",
    )

    with pytest.raises(SegmentGeometryGateError) as raised:
        activate_revision_core(
            db,
            revision_id=revision.id,
            attempt_job_id=revision.job_id,
            precomputed_efforts={},
    )
    assert raised.value.gate == "write"
    assert raised.value.violations[0]["code"] == "candidate_geometry_hash_changed"
    db.rollback()

    live_segment = db.get(Segment, segment.id)
    assert live_segment.distance == 1417.0
    assert stable_line_hash(
        db.query(func.ST_AsText(Segment.reference_line))
        .filter(Segment.id == segment.id)
        .scalar()
    ) == revision.previous_geometry_hash


def test_gate_rejects_non_finite_metrics_and_revision_fields(db):
    metrics = SegmentGeometryGateMetrics(
        validation_version=SEGMENT_GEOMETRY_GATE_VERSION,
        source_segment_id="123",
        source_distance_m=math.nan,
        candidate_distance_m=math.nan,
        source_distance_delta_ratio=math.nan,
        current_distance_m=math.nan,
        current_distance_delta_ratio=math.nan,
        start_shift_m=math.nan,
        end_shift_m=math.nan,
        hausdorff_m=math.nan,
        previous_to_candidate_p95_m=math.nan,
        candidate_to_previous_p95_m=math.nan,
        discrete_frechet_m=math.nan,
    )
    with pytest.raises(SegmentGeometryGateError) as metrics_error:
        enforce_segment_geometry_gate_metrics(metrics)
    assert metrics_error.value.violations[0]["code"] == "non_finite_gate_metrics"

    segment = _segment(db)
    revision = _processing_revision(db, segment, job_id="segment-nan-write-gate")
    # SQLite 会把 NaN 绑定成 NULL，因此用可真实持久化的 +Inf 验证：即使行锁
    # 强制从存储层刷新坏值，激活代码也必须 fail closed。
    revision.elevation_gain = math.inf
    db.commit()

    with pytest.raises(SegmentGeometryGateError) as revision_error:
        activate_revision_core(
            db,
            revision_id=revision.id,
            attempt_job_id=revision.job_id,
            precomputed_efforts={},
        )
    assert revision_error.value.violations[0]["code"] == (
        "non_finite_or_invalid_candidate_fields"
    )
    db.rollback()
    assert db.get(Segment, segment.id).elevation_gain == 100.0


def test_shape_gate_never_silently_relaxes_twenty_meter_sampling():
    previous_wkt = "LINESTRING(112 37,112.4 37)"
    candidate_wkt = "LINESTRING(112 37,112.2 37.0001,112.4 37)"
    previous_points = parse_linestring_wkt(previous_wkt)
    prepared = _prepared_for_wkt(candidate_wkt)

    with pytest.raises(SegmentGeometryGateError) as raised:
        build_segment_geometry_gate_metrics(
            previous_wkt=previous_wkt,
            current_distance_m=prepared.distance,
            current_start_lat=previous_points[0][0],
            current_start_lon=previous_points[0][1],
            current_end_lat=previous_points[-1][0],
            current_end_lon=previous_points[-1][1],
            prepared=prepared,
            source_url="https://www.strava.com/segments/123",
            source_distance_m=prepared.distance,
        )

    assert raised.value.violations[0]["code"] == "shape_analysis_distance_limit"


def test_gate_migration_adds_auditable_source_and_validation_fields():
    migration = Path("migrations/versions/20260809_segment_geom_gates.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "20260809_seg_geom_gates"' in migration
    assert 'down_revision = "20260809_seg_geom_rebuild"' in migration
    assert '"source_segment_id"' in migration
    assert '"source_distance_m"' in migration
    assert '"source_observation_id"' in migration
    assert '"routing_candidate_id"' in migration
    assert '"candidate_payload_hash"' in migration
    assert '"segment_routing_candidates"' in migration
    assert '"validation_version"' in migration
    assert '"validation_metrics_json"' in migration


def test_migration_preserves_historical_hashes_and_guards_incompatible_downgrade():
    migration = Path("migrations/versions/20260809_segment_geom_rebuild.py").read_text(
        encoding="utf-8"
    )

    assert '"fk_route_segments_segment_hash"' in migration
    assert '"fk_collection_segments_segment_hash"' in migration
    assert "op.drop_constraint" in migration
    assert "historical membership hashes" in migration
