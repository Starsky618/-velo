"""标准赛段几何替换：API 暂存合同与原子成绩切换。"""

from __future__ import annotations

import json
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
    activate_revision_core,
    mark_revision_failed,
)
from app.segment.models import Segment, SegmentEffort, SegmentGeometryRevision


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


def _segment(db, *, name="万亩生态园") -> Segment:
    segment = Segment(
        name=name,
        distance=1000.0,
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
    wkt = "LINESTRING(112.4 37.7,112.405 37.715,112.41 37.71)"
    return PreparedSegmentGeometry(
        reference_line_wkt=wkt,
        geometry_hash=stable_line_hash(wkt),
        distance=1200.0,
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


def test_admin_stages_driving_geometry_without_touching_live_segment(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        queue,
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
                {"lat": 37.72, "lon": 112.42},
            ],
            "source_url": "https://www.strava.com/segments/123",
            "coordinate_system": "gcj02",
            "routing_provider": "tencent",
            "routing_mode": "driving",
        },
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
    assert live_segment.distance == 1000.0
    assert live_segment.elevation_gain == 100.0
    revision = db.get(SegmentGeometryRevision, payload["id"])
    assert revision.distance == 1200.0
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
    revision = SegmentGeometryRevision(
        segment_id=segment.id,
        status="processing",
        previous_geometry_hash="old-hash",
        candidate_geometry_hash="new-hash",
        previous_reference_line_wkt="LINESTRING(112.4 37.7,112.41 37.71)",
        candidate_reference_line_wkt="LINESTRING(112.4 37.7,112.42 37.72)",
        previous_snapshot_json="{}",
        distance=2200.0,
        elevation_gain=220.0,
        elevation_loss=20.0,
        avg_gradient=8.5,
        elevation_profile="[100,180,320]",
        max_gradient=12.0,
        difficulty="hard",
        city="taiyuan",
        start_lat=37.7,
        start_lon=112.4,
        end_lat=37.72,
        end_lon=112.42,
        match_tolerance=50.0,
        min_match_ratio=0.8,
        source_url="https://www.strava.com/segments/123",
        routing_provider="tencent",
        routing_mode="driving",
        original_coordinate_system="gcj02",
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        started_at=datetime.now(timezone.utc),
    )
    db.add(revision)
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


def test_staged_revision_with_job_id_recovers_only_when_claim_expired_and_job_missing(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    first_queue = _Queue()
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        first_queue,
    )
    created = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.705, "lon": 112.405},
                {"lat": 37.71, "lon": 112.41},
            ],
            "source_url": "https://www.strava.com/segments/123",
        },
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


def test_admin_rejects_bicycling_geometry_before_any_write(client, db, admin_header):
    segment = _segment(db, name="狼坡")
    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
                {"lat": 37.72, "lon": 112.42},
            ],
            "source_url": "https://www.strava.com/segments/456",
            "routing_mode": "bicycling",
        },
    )
    assert response.status_code == 422
    assert db.query(SegmentGeometryRevision).count() == 0


def test_admin_rejects_endpoints_only_before_any_geometry_work(client, db, admin_header):
    segment = _segment(db, name="万亩生态园")

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.72, "lon": 112.42},
            ],
            "source_url": "https://www.strava.com/segments/123",
        },
    )

    assert response.status_code == 422
    assert db.query(SegmentGeometryRevision).count() == 0


@pytest.mark.parametrize("candidate_distance", [530.0, 1600.0])
def test_admin_rejects_implausible_length_change_for_same_segment_id(
    client,
    db,
    admin_header,
    monkeypatch,
    candidate_distance,
):
    segment = _segment(db)
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry",
        lambda *args, **kwargs: replace(_prepared(), distance=candidate_distance),
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
                {"lat": 37.72, "lon": 112.42},
            ],
            "source_url": "https://www.strava.com/segments/123",
        },
    )

    assert response.status_code == 409
    assert "长度差异过大" in response.json()["detail"]
    assert db.query(SegmentGeometryRevision).count() == 0


def test_admin_rejects_candidate_for_a_different_real_world_segment(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    wrong_segment = replace(
        _prepared(),
        reference_line_wkt="LINESTRING(112.4 37.7,112.42 37.72)",
        geometry_hash=stable_line_hash("LINESTRING(112.4 37.7,112.42 37.72)"),
        end_lat=37.72,
        end_lon=112.42,
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry",
        lambda *args, **kwargs: wrong_segment,
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
                {"lat": 37.72, "lon": 112.42},
            ],
            "source_url": "https://www.strava.com/segments/456",
        },
    )

    assert response.status_code == 409
    assert "同一个 segment_id" in response.json()["detail"]
    assert db.query(SegmentGeometryRevision).count() == 0


def test_dispatch_failure_marks_revision_failed_without_touching_live_segment(
    client,
    db,
    admin_header,
    monkeypatch,
):
    segment = _segment(db)
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.prepare_segment_geometry",
        lambda *args, **kwargs: _prepared(),
    )
    monkeypatch.setattr(
        "app.admin.segment_geometry_workflow.segment_rebuilds_queue",
        _FailQueue(),
    )

    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={
            "reference_points": [
                {"lat": 37.7, "lon": 112.4},
                {"lat": 37.71, "lon": 112.41},
                {"lat": 37.72, "lon": 112.42},
            ],
            "source_url": "https://www.strava.com/segments/123",
        },
    )

    assert response.status_code == 503
    revision = db.query(SegmentGeometryRevision).one()
    assert revision.status == "failed"
    assert "redis unavailable" in revision.error_message
    live_segment = db.get(Segment, segment.id)
    assert live_segment.distance == 1000.0
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
    ("points", "source_url"),
    [
        (
            [{"lat": True, "lon": 112.4}, {"lat": 37.72, "lon": 112.42}],
            "https://www.strava.com/segments/456",
        ),
        (
            [{"lat": 37.7, "lon": 112.4}, {"lat": 37.72, "lon": 112.42}],
            "https://example.com/segments/456",
        ),
        (
            [{"lat": 37.7, "lon": 112.4}, {"lat": 37.72, "lon": 112.42}],
            "https://www.strava.com/routes/456",
        ),
        (
            [{"lat": 37.7, "lon": 112.4}] * 2001,
            "https://www.strava.com/segments/456",
        ),
    ],
)
def test_admin_rejects_invalid_geometry_provenance_before_any_write(
    client,
    db,
    admin_header,
    points,
    source_url,
):
    segment = _segment(db, name="狼坡")
    response = client.post(
        f"/api/admin/segments/{segment.id}/geometry-revisions",
        headers=admin_header,
        json={"reference_points": points, "source_url": source_url},
    )

    assert response.status_code == 422
    assert db.query(SegmentGeometryRevision).count() == 0


def test_activation_keeps_segment_id_and_atomically_rebuilds_efforts(db):
    segment = _segment(db)
    previous_wkt = (
        db.query(func.ST_AsText(Segment.reference_line))
        .filter(Segment.id == segment.id)
        .scalar()
    )
    candidate_wkt = "LINESTRING(112.4 37.7,112.42 37.72)"
    revision = SegmentGeometryRevision(
        segment_id=segment.id,
        status="processing",
        previous_geometry_hash=stable_line_hash(previous_wkt),
        candidate_geometry_hash=stable_line_hash(candidate_wkt),
        previous_reference_line_wkt=previous_wkt,
        candidate_reference_line_wkt=candidate_wkt,
        previous_snapshot_json=json.dumps({"distance": 1000.0}),
        distance=2200.0,
        elevation_gain=220.0,
        elevation_loss=20.0,
        avg_gradient=8.5,
        elevation_profile="[100,180,320]",
        max_gradient=12.0,
        difficulty="hard",
        city="taiyuan",
        start_lat=37.7,
        start_lon=112.4,
        end_lat=37.72,
        end_lon=112.42,
        match_tolerance=50.0,
        min_match_ratio=0.8,
        source_url="https://www.strava.com/segments/123",
        routing_provider="tencent",
        routing_mode="driving",
        original_coordinate_system="gcj02",
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        job_id="segment-geometry-test-attempt",
    )
    db.add(revision)
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
    assert live_segment.distance == 2200.0
    assert live_segment.elevation_gain == 220.0
    assert live_segment.difficulty == "hard"
    assert db.get(SegmentGeometryRevision, revision.id).status == "active"
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


def test_migration_preserves_historical_hashes_and_guards_incompatible_downgrade():
    migration = Path("migrations/versions/20260809_segment_geom_rebuild.py").read_text(
        encoding="utf-8"
    )

    assert '"fk_route_segments_segment_hash"' in migration
    assert '"fk_collection_segments_segment_hash"' in migration
    assert "op.drop_constraint" in migration
    assert "historical membership hashes" in migration
