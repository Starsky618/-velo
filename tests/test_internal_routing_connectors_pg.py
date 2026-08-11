"""内部连接段的真 PostGIS 几何、端点和双向解析测试。"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.segment.internal_connectors import (
    create_internal_routing_connector,
    resolve_internal_connector,
)
from app.segment.models import InternalRoutingConnector, Segment
from app.user.models import User


@pytest.fixture(scope="module")
def pg_session_factory():
    database_url = os.getenv("VELO_TEST_DATABASE_URL")
    required = os.getenv("VELO_REQUIRE_POSTGRES_TESTS") == "1"
    if not database_url:
        if required:
            pytest.fail("CI 必须提供 VELO_TEST_DATABASE_URL", pytrace=False)
        pytest.skip("仅在显式隔离的 VELO_TEST_DATABASE_URL 上运行")
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, ImportError) as exc:
        if engine is not None:
            engine.dispose()
        if required:
            pytest.fail(f"CI 隔离 PostgreSQL 不可用: {exc}", pytrace=False)
        pytest.skip(f"隔离 PostgreSQL 不可用: {exc}")
    try:
        yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    finally:
        engine.dispose()


def _segment(name: str, start: tuple[float, float], end: tuple[float, float]) -> Segment:
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    return Segment(
        name=name,
        description="internal connector pg test",
        distance=1000.0,
        elevation_gain=50.0,
        elevation_loss=10.0,
        avg_gradient=4.0,
        elevation_profile="[100, 150]",
        start_lon=start[0],
        start_lat=start[1],
        end_lon=end[0],
        end_lat=end[1],
        reference_line=(
            f"SRID=4326;LINESTRING({start[0]} {start[1]},"
            f"{midpoint[0]} {midpoint[1]},{end[0]} {end[1]})"
        ),
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty="medium",
        max_gradient=6.0,
        city="taiyuan",
    )


def _gpx() -> bytes:
    return b"""<?xml version="1.0"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
<trkpt lat="37.987440" lon="112.413430"><ele>1400</ele></trkpt>
<trkpt lat="37.986900" lon="112.413350"><ele>1400</ele></trkpt>
<trkpt lat="37.986280" lon="112.413215"><ele>1400</ele></trkpt>
</trkseg></trk></gpx>"""


def test_postgis_connector_round_trip_and_reverse_traversal(pg_session_factory):
    db = pg_session_factory()
    suffix = uuid.uuid4().hex
    reviewer = User(
        openid=f"internal_connector_pg_{suffix}",
        nickname="internal connector pg",
        is_admin=True,
    )
    segment_a = _segment(
        f"马头水 PG {suffix}",
        (112.417932, 37.954498),
        (112.413208, 37.986264),
    )
    segment_b = _segment(
        f"横岭 PG {suffix}",
        (112.413419, 37.987454),
        (112.444517, 37.984123),
    )
    db.add_all([reviewer, segment_a, segment_b])
    db.commit()
    db.refresh(reviewer)
    db.refresh(segment_a)
    db.refresh(segment_b)
    connector_id = None
    try:
        result = create_internal_routing_connector(
            db,
            slug=f"matoushui-hengling-pg-{suffix}",
            name="马头水—横岭内部连接 PG",
            city="taiyuan",
            gpx_payload=_gpx(),
            source_name="pg-test.gpx",
            endpoint_a_segment_id=segment_a.id,
            endpoint_a_position="end",
            endpoint_b_segment_id=segment_b.id,
            endpoint_b_position="start",
            traversal_policy="bidirectional",
            blocked_provider="tencent",
            review_note="pg reviewed",
            reviewer_user_id=reviewer.id,
        )
        db.commit()
        connector_id = result.connector_id

        seam = db.execute(
            text(
                """
                SELECT
                    ST_DistanceSphere(ST_StartPoint(c.reference_line), ST_EndPoint(a.reference_line)),
                    ST_DistanceSphere(ST_EndPoint(c.reference_line), ST_StartPoint(b.reference_line))
                FROM internal_routing_connectors c
                JOIN segments a ON a.id = c.endpoint_a_segment_id
                JOIN segments b ON b.id = c.endpoint_b_segment_id
                WHERE c.id = :connector_id
                """
            ),
            {"connector_id": connector_id},
        ).one()
        assert seam[0] == pytest.approx(0.0, abs=0.01)
        assert seam[1] == pytest.approx(0.0, abs=0.01)

        forward = resolve_internal_connector(
            db,
            from_segment_id=segment_a.id,
            from_position="end",
            to_segment_id=segment_b.id,
            to_position="start",
        )
        backward = resolve_internal_connector(
            db,
            from_segment_id=segment_b.id,
            from_position="start",
            to_segment_id=segment_a.id,
            to_position="end",
        )
        assert forward is not None and backward is not None
        assert backward.coordinates == tuple(reversed(forward.coordinates))
    finally:
        db.rollback()
        if connector_id is not None:
            db.query(InternalRoutingConnector).filter(
                InternalRoutingConnector.id == connector_id
            ).delete(synchronize_session=False)
        db.query(Segment).filter(Segment.id.in_([segment_a.id, segment_b.id])).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == reviewer.id).delete(synchronize_session=False)
        db.commit()
        db.close()
