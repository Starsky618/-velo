"""标准几何替换的真 PostgreSQL/PostGIS 原子链路。"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

import app.admin.segment_geometry_workflow as geometry_workflow
import app.segment.geometry_rebuild as geometry_rebuild
from app.activity.models import Activity, Trackpoint
from app.common.geometry_hash import SEGMENT_GEOMETRY_NORMALIZATION_VERSION, stable_line_hash
from app.route_book.models import RouteBook, RouteVersion
from app.route_cognition.models import JudgmentRun, RouteCognitionSegment, SegmentGeometrySource
from app.route_cognition.services.segment_geometry_change import record_geometry_change
from app.route_cognition.services.segment_eligibility import (
    reactivate_provenance_verified_segment,
)
from app.segment.geometry_rebuild import (
    PreparedSegmentGeometry,
    SEGMENT_GEOMETRY_GATE_VERSION,
    SegmentGeometryRevisionError,
    acquire_geometry_activation_lock,
    acquire_geometry_match_read_lock,
    activate_revision_core,
    collect_effort_candidates,
    parse_linestring_wkt,
    stage_geometry_revision,
)
from app.segment._geo_utils import _haversine
from app.segment.models import (
    Segment,
    SegmentEffort,
    SegmentGeometryRevision,
    SegmentRoutingCandidate,
)
from app.segment.routing_candidates import routing_candidate_record_hash
from app.user.models import User


def _db_url() -> str:
    url = os.getenv("VELO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 VELO_TEST_DATABASE_URL 后才运行赛段几何替换真 PG 测试")
    return url


def _wkt_distance(wkt: str) -> float:
    points = parse_linestring_wkt(wkt)
    return sum(
        _haversine(*points[index - 1], *points[index])
        for index in range(1, len(points))
    )


def _install_source_observation(monkeypatch, *, observed_distance_m: float):
    observation = SimpleNamespace(
        observation_id="pg-source-observation",
        source_segment_id="123",
        source_url="https://www.strava.com/segments/123",
        observed_distance_m=observed_distance_m,
    )
    monkeypatch.setattr(
        geometry_rebuild,
        "resolve_source_observation",
        lambda *args, **kwargs: observation,
    )
    return observation


def _routing_candidate(db, *, segment_id: int, prepared: PreparedSegmentGeometry):
    candidate = SegmentRoutingCandidate(
        segment_id=segment_id,
        status="ready",
        routing_provider="tencent",
        routing_mode="driving",
        control_points_json=json.dumps(
            [
                {"lat": prepared.start_lat, "lon": prepared.start_lon},
                {"lat": prepared.end_lat, "lon": prepared.end_lon},
            ],
            sort_keys=True,
            separators=(",", ":"),
        ),
        reference_line_wkt=prepared.reference_line_wkt,
        geometry_hash=prepared.geometry_hash,
        provider_distance_m=prepared.distance,
        measured_distance_m=prepared.distance,
        record_hash="pending",
    )
    candidate.record_hash = routing_candidate_record_hash(candidate)
    db.add(candidate)
    db.flush()
    return candidate


@pytest.fixture()
def pg_engine():
    base_engine = create_engine(_db_url(), pool_pre_ping=True)
    schema_name = f"segment_geom_rebuild_{uuid.uuid4().hex}"
    try:
        with base_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            connection.execute(text(f"CREATE SCHEMA {schema_name}"))
    except SQLAlchemyError as exc:
        base_engine.dispose()
        pytest.skip(f"PostgreSQL/PostGIS 不可用: {exc}")

    engine = create_engine(
        _db_url(),
        connect_args={"options": f"-csearch_path={schema_name},public"},
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        engine.dispose()
        try:
            with base_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
        finally:
            base_engine.dispose()


def _create_tables(engine) -> None:
    for table in (
        User.__table__,
        Activity.__table__,
        Segment.__table__,
        SegmentEffort.__table__,
        SegmentRoutingCandidate.__table__,
        SegmentGeometryRevision.__table__,
        RouteBook.__table__,
        RouteVersion.__table__,
        JudgmentRun.__table__,
        SegmentGeometrySource.__table__,
        RouteCognitionSegment.__table__,
    ):
        table.create(bind=engine, checkfirst=False)
    # Trackpoint.geom 的模型同时声明 GeoAlchemy 自动空间索引和显式同名索引，
    # 单表 create 会重复建 idx_trackpoints_geom；迁移链没有这个问题。此处只建
    # 本测试需要的真实列，空间行为仍由 PostGIS geometry/ST_DWithin 验证。
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE trackpoints (
                    id SERIAL PRIMARY KEY,
                    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    elevation DOUBLE PRECISION,
                    timestamp TIMESTAMPTZ,
                    heart_rate INTEGER,
                    cadence INTEGER,
                    power INTEGER,
                    speed DOUBLE PRECISION,
                    distance DOUBLE PRECISION,
                    geom geometry(POINT, 4326)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE route_segments (
                    id SERIAL PRIMARY KEY,
                    segment_id INTEGER NOT NULL,
                    segment_geometry_hash VARCHAR(64),
                    membership_status VARCHAR(16) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE collection_segments (
                    id SERIAL PRIMARY KEY,
                    segment_id INTEGER NOT NULL,
                    segment_geometry_hash VARCHAR(64) NOT NULL,
                    membership_status VARCHAR(16) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE segment_concept_links (
                    id SERIAL PRIMARY KEY,
                    segment_id INTEGER NOT NULL,
                    segment_geometry_hash VARCHAR(64) NOT NULL,
                    link_status VARCHAR(16) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE segment_concept_candidates (
                    id SERIAL PRIMARY KEY,
                    segment_id INTEGER NOT NULL,
                    segment_geometry_hash VARCHAR(64) NOT NULL,
                    candidate_status VARCHAR(16) NOT NULL,
                    latest_confidence_state VARCHAR(32) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )


def test_geometry_epoch_read_lock_blocks_activation_until_match_commits(pg_engine):
    match_db = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)()
    activation_acquired = threading.Event()

    def run_activation():
        activation_db = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)()
        try:
            acquire_geometry_activation_lock(activation_db)
            activation_acquired.set()
            activation_db.commit()
        finally:
            activation_db.close()

    try:
        acquire_geometry_match_read_lock(match_db)
        thread = threading.Thread(target=run_activation)
        thread.start()
        assert not activation_acquired.wait(0.2)
        match_db.commit()
        assert activation_acquired.wait(2.0)
        thread.join(timeout=2.0)
        assert not thread.is_alive()
    finally:
        match_db.rollback()
        match_db.close()


def test_concurrent_stage_serializes_on_segment_parent_lock(pg_engine, monkeypatch):
    _create_tables(pg_engine)
    Session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    first_db = Session()
    second_finished = threading.Event()
    second_errors: list[Exception] = []
    try:
        user = User(openid=f"stage_lock_{uuid.uuid4().hex}", nickname="stage lock")
        first_db.add(user)
        first_db.flush()
        segment = Segment(
            name="并发锁测试赛段",
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
            reference_line=WKTElement(
                "LINESTRING(112.4 37.7,112.41 37.71)", srid=4326
            ),
            match_tolerance=50.0,
            min_match_ratio=0.8,
        )
        first_db.add(segment)
        first_db.commit()
        segment_id = segment.id
        user_id = user.id
        prepared = PreparedSegmentGeometry(
            reference_line_wkt="LINESTRING(112.4 37.7,112.405 37.70505,112.41 37.71)",
            geometry_hash=stable_line_hash(
                "LINESTRING(112.4 37.7,112.405 37.70505,112.41 37.71)"
            ),
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
        observation = _install_source_observation(
            monkeypatch,
            observed_distance_m=prepared.distance,
        )
        routing_candidate = _routing_candidate(
            first_db,
            segment_id=segment_id,
            prepared=prepared,
        )
        first_revision = stage_geometry_revision(
            first_db,
            segment_id=segment_id,
            prepared=prepared,
            source_observation_id=observation.observation_id,
            routing_candidate_id=routing_candidate.id,
            created_by=user_id,
        )

        def stage_second():
            second_db = Session()
            try:
                stage_geometry_revision(
                    second_db,
                    segment_id=segment_id,
                    prepared=prepared,
                    source_observation_id=observation.observation_id,
                    routing_candidate_id=routing_candidate.id,
                    created_by=user_id,
                )
            except Exception as exc:
                second_errors.append(exc)
                second_db.rollback()
            finally:
                second_db.close()
                second_finished.set()

        thread = threading.Thread(target=stage_second)
        thread.start()
        assert not second_finished.wait(0.2)
        first_db.commit()
        assert second_finished.wait(2.0)
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert len(second_errors) == 1
        assert isinstance(second_errors[0], SegmentGeometryRevisionError)
        assert "已有正在处理" in str(second_errors[0])
        assert first_revision.id is not None
    finally:
        first_db.rollback()
        first_db.close()


def test_segment_delete_cascades_gate_revision_and_candidate(pg_engine, monkeypatch):
    _create_tables(pg_engine)
    db = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)()
    try:
        user = User(openid=f"delete_gate_{uuid.uuid4().hex}", nickname="delete gate")
        db.add(user)
        db.flush()
        old_wkt = "LINESTRING(112.4 37.7,112.41 37.71)"
        old_distance = _wkt_distance(old_wkt)
        segment = Segment(
            name="删除级联测试赛段",
            distance=old_distance,
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
            reference_line=WKTElement(old_wkt, srid=4326),
            match_tolerance=50.0,
            min_match_ratio=0.8,
        )
        db.add(segment)
        db.flush()
        candidate_wkt = (
            "LINESTRING(112.4 37.7,112.405 37.70505,112.41 37.71)"
        )
        prepared = PreparedSegmentGeometry(
            reference_line_wkt=candidate_wkt,
            geometry_hash=stable_line_hash(candidate_wkt),
            distance=_wkt_distance(candidate_wkt),
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
        observation = _install_source_observation(
            monkeypatch,
            observed_distance_m=prepared.distance,
        )
        routing_candidate = _routing_candidate(
            db,
            segment_id=segment.id,
            prepared=prepared,
        )
        revision = stage_geometry_revision(
            db,
            segment_id=segment.id,
            prepared=prepared,
            source_observation_id=observation.observation_id,
            routing_candidate_id=routing_candidate.id,
            created_by=user.id,
        )
        db.commit()
        segment_id = segment.id
        candidate_id = routing_candidate.id
        revision_id = revision.id

        db.delete(segment)
        db.commit()

        assert db.get(Segment, segment_id) is None
        assert db.get(SegmentRoutingCandidate, candidate_id) is None
        assert db.get(SegmentGeometryRevision, revision_id) is None
    finally:
        db.rollback()
        db.close()


def test_concurrent_retry_claim_enqueues_only_one_job(pg_engine, monkeypatch):
    _create_tables(pg_engine)
    Session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    setup_db = Session()
    try:
        user = User(openid=f"retry_claim_{uuid.uuid4().hex}", nickname="retry claim")
        setup_db.add(user)
        setup_db.flush()
        segment = Segment(
            name="重试并发测试赛段",
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
            reference_line=WKTElement(
                "LINESTRING(112.4 37.7,112.41 37.71)", srid=4326
            ),
            match_tolerance=50.0,
            min_match_ratio=0.8,
        )
        setup_db.add(segment)
        setup_db.flush()
        candidate_wkt = "LINESTRING(112.4 37.7,112.405 37.70505,112.41 37.71)"
        candidate_distance = _wkt_distance(candidate_wkt)
        prepared = PreparedSegmentGeometry(
            reference_line_wkt=candidate_wkt,
            geometry_hash=stable_line_hash(candidate_wkt),
            distance=candidate_distance,
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
        observation = _install_source_observation(
            monkeypatch,
            observed_distance_m=candidate_distance,
        )
        routing_candidate = _routing_candidate(
            setup_db,
            segment_id=segment.id,
            prepared=prepared,
        )
        revision = stage_geometry_revision(
            setup_db,
            segment_id=segment.id,
            prepared=prepared,
            source_observation_id=observation.observation_id,
            routing_candidate_id=routing_candidate.id,
            created_by=user.id,
        )
        revision.status = "failed"
        revision.error_message = "worker died"
        setup_db.commit()
        segment_id = segment.id
        revision_id = revision.id
    finally:
        setup_db.close()

    entered_enqueue = threading.Event()
    release_enqueue = threading.Event()

    class BlockingQueue:
        connection = None

        def __init__(self):
            self.calls = []

        def enqueue(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            entered_enqueue.set()
            assert release_enqueue.wait(2.0)
            return SimpleNamespace(id=kwargs["job_id"])

    queue = BlockingQueue()
    monkeypatch.setattr(geometry_workflow, "segment_rebuilds_queue", queue)
    first_errors: list[Exception] = []
    second_errors: list[Exception] = []

    def retry_once(errors):
        retry_db = Session()
        try:
            geometry_workflow.retry_segment_geometry_revision(
                retry_db,
                segment_id=segment_id,
                revision_id=revision_id,
            )
        except Exception as exc:
            errors.append(exc)
            retry_db.rollback()
        finally:
            retry_db.close()

    first = threading.Thread(target=retry_once, args=(first_errors,))
    first.start()
    assert entered_enqueue.wait(2.0)
    second = threading.Thread(target=retry_once, args=(second_errors,))
    second.start()
    second.join(timeout=2.0)
    assert not second.is_alive()
    release_enqueue.set()
    first.join(timeout=2.0)
    assert not first.is_alive()

    assert first_errors == []
    assert len(second_errors) == 1
    assert isinstance(second_errors[0], SegmentGeometryRevisionError)
    assert len(queue.calls) == 1


def test_rebuild_swaps_geometry_efforts_and_cognition_in_one_transaction(
    pg_engine,
    monkeypatch,
):
    _create_tables(pg_engine)
    db = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)()
    try:
        user = User(openid=f"segment_rebuild_{uuid.uuid4().hex}", nickname="segment rebuild")
        db.add(user)
        db.flush()

        old_wkt = "LINESTRING(112.4 37.7,112.41 37.71)"
        segment = Segment(
            name="事务重建测试赛段",
            distance=1417.0,
            elevation_gain=120.0,
            elevation_loss=5.0,
            avg_gradient=7.0,
            elevation_profile="[100,220]",
            max_gradient=10.0,
            difficulty="medium",
            city="taiyuan",
            start_lat=37.7,
            start_lon=112.4,
            end_lat=37.71,
            end_lon=112.41,
            reference_line=WKTElement(old_wkt, srid=4326),
            match_tolerance=50.0,
            min_match_ratio=0.8,
        )
        db.add(segment)
        db.flush()

        activity = Activity(
            user_id=user.id,
            title="候选线骑行",
            status="completed",
            activity_type="cycling",
            data_source="fit",
            started_at=datetime.now(timezone.utc),
        )
        db.add(activity)
        db.flush()
        started_at = datetime.now(timezone.utc)
        points = []
        for index in range(11):
            ratio = index / 10
            lat = 37.7 + 0.01 * ratio
            lon = 112.4 + 0.01 * ratio
            points.append(
                Trackpoint(
                    activity_id=activity.id,
                    seq=index,
                    latitude=lat,
                    longitude=lon,
                    timestamp=started_at + timedelta(seconds=index * 10),
                    power=200 + index,
                    geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
                )
            )
        db.add_all(points)
        old_effort = SegmentEffort(
            segment_id=segment.id,
            activity_id=activity.id,
            user_id=user.id,
            elapsed_time=999,
            avg_speed=4.7,
            start_index=0,
            end_index=10,
        )
        db.add(old_effort)

        old_wkt = db.query(func.ST_AsText(Segment.reference_line)).filter(Segment.id == segment.id).scalar()
        candidate_wkt = db.execute(
            text("SELECT ST_AsText(ST_GeomFromText(:wkt, 4326))"),
            {"wkt": "LINESTRING(112.4 37.7,112.405 37.705,112.41 37.71)"},
        ).scalar_one()
        candidate_distance = _wkt_distance(candidate_wkt)
        prepared = PreparedSegmentGeometry(
            reference_line_wkt=candidate_wkt,
            geometry_hash=stable_line_hash(candidate_wkt),
            distance=candidate_distance,
            elevation_gain=180.0,
            elevation_loss=8.0,
            avg_gradient=9.0,
            elevation_profile_json="[100,180,280]",
            max_gradient=14.0,
            difficulty="hard",
            city="taiyuan",
            start_lat=37.7,
            start_lon=112.4,
            end_lat=37.71,
            end_lon=112.41,
        )
        observation = _install_source_observation(
            monkeypatch,
            observed_distance_m=candidate_distance,
        )
        routing_candidate = _routing_candidate(
            db,
            segment_id=segment.id,
            prepared=prepared,
        )
        revision = stage_geometry_revision(
            db,
            segment_id=segment.id,
            prepared=prepared,
            source_observation_id=observation.observation_id,
            routing_candidate_id=routing_candidate.id,
            created_by=user.id,
        )
        revision.status = "processing"
        revision.job_id = "segment-geometry-pg-attempt"
        judgment = JudgmentRun(
            run_type="human_review",
            status="succeeded",
            trigger_type="test",
            segment_id=segment.id,
            confidence_state="stable",
            created_by_user_id=user.id,
        )
        db.add(judgment)
        db.flush()
        cognition = RouteCognitionSegment(
            segment_id=segment.id,
            primary_geometry_source_id=None,
            review_basis="legacy_reviewed",
            eligibility_status="active",
            geometry_hash=stable_line_hash(old_wkt),
            normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
            accepted_judgment_run_id=judgment.id,
            reviewed_by=user.id,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(cognition)
        db.execute(
            text(
                """
                INSERT INTO route_segments
                    (segment_id, segment_geometry_hash, membership_status)
                VALUES (:segment_id, :old_hash, 'active');
                INSERT INTO collection_segments
                    (segment_id, segment_geometry_hash, membership_status)
                VALUES (:segment_id, :old_hash, 'active');
                INSERT INTO segment_concept_links
                    (segment_id, segment_geometry_hash, link_status)
                VALUES (:segment_id, :old_hash, 'active');
                INSERT INTO segment_concept_candidates
                    (segment_id, segment_geometry_hash, candidate_status, latest_confidence_state)
                VALUES (:segment_id, :old_hash, 'proposed', 'proposed')
                """
            ),
            {"segment_id": segment.id, "old_hash": stable_line_hash(old_wkt)},
        )
        db.commit()
        old_effort_id = old_effort.id

        revision = db.get(SegmentGeometryRevision, revision.id)
        candidates = collect_effort_candidates(db, revision)
        assert list(candidates) == [activity.id]
        assert candidates[activity.id].elapsed_time == 100

        summary = activate_revision_core(
            db,
            revision_id=revision.id,
            attempt_job_id=revision.job_id,
            precomputed_efforts=candidates,
        )
        active_revision = db.get(SegmentGeometryRevision, revision.id)
        record_geometry_change(db, revision=active_revision, matched_efforts=summary.matched_efforts)

        assert db.get(Segment, segment.id).id == segment.id
        assert db.get(Segment, segment.id).distance == pytest.approx(candidate_distance)
        rebuilt_effort = db.query(SegmentEffort).filter_by(segment_id=segment.id).one()
        assert rebuilt_effort.id == old_effort_id
        assert rebuilt_effort.elapsed_time == 100
        assert rebuilt_effort.avg_power == 205.0
        assert db.get(SegmentGeometryRevision, revision.id).status == "active"
        assert db.get(RouteCognitionSegment, segment.id).eligibility_status == "suspended"
        source = db.query(SegmentGeometrySource).filter_by(segment_id=segment.id).one()
        assert source.source_type == "map_reconstruction"
        assert source.geometry_hash == revision.candidate_geometry_hash
        assert source.quality_metrics_json["routing_mode"] == "driving"
        assert source.quality_metrics_json["source_observation_id"] == (
            observation.observation_id
        )
        assert source.quality_metrics_json["routing_candidate_id"] == (
            routing_candidate.id
        )
        assert db.execute(text("SELECT membership_status FROM route_segments")).scalar_one() == "deprecated"
        assert db.execute(text("SELECT membership_status FROM collection_segments")).scalar_one() == "deprecated"
        assert db.execute(text("SELECT link_status FROM segment_concept_links")).scalar_one() == "deprecated"
        assert db.execute(
            text(
                "SELECT candidate_status, latest_confidence_state "
                "FROM segment_concept_candidates"
            )
        ).one() == ("stale", "stale")
        assert db.execute(text("SELECT segment_geometry_hash FROM route_segments")).scalar_one() == (
            revision.previous_geometry_hash
        )

        rereview = JudgmentRun(
            run_type="human_review",
            status="succeeded",
            trigger_type="test",
            segment_id=segment.id,
            confidence_state="stable",
            created_by_user_id=user.id,
        )
        db.add(rereview)
        db.flush()
        reactivated = reactivate_provenance_verified_segment(
            db,
            segment_id=segment.id,
            primary_geometry_source_id=source.id,
            accepted_judgment_run_id=rereview.id,
            reviewer_id=user.id,
            review_note="新腾讯驾车线已人工复核",
        )
        db.commit()

        assert reactivated.eligibility_status == "active"
        assert reactivated.geometry_hash == revision.candidate_geometry_hash
        assert reactivated.primary_geometry_source_id == source.id
        assert db.execute(text("SELECT membership_status FROM route_segments")).scalar_one() == "deprecated"
        assert db.execute(text("SELECT segment_geometry_hash FROM route_segments")).scalar_one() == (
            revision.previous_geometry_hash
        )
    finally:
        db.rollback()
        db.close()
