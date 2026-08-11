"""内部路线连接段的方向、写入幂等与用户不可见性。"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func

from app.segment.internal_connectors import (
    GpxPoint,
    InternalRoutingConnectorError,
    coordinates_for_traversal,
    create_internal_routing_connector,
    prepare_connector_geometry,
    resolve_internal_connector,
)
from app.segment.models import InternalRoutingConnector, Segment


def _segment(name: str, start: tuple[float, float], end: tuple[float, float]) -> Segment:
    return Segment(
        name=name,
        description="internal connector test",
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
            f"{(start[0] + end[0]) / 2} {(start[1] + end[1]) / 2},"
            f"{end[0]} {end[1]})"
        ),
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty="medium",
        max_gradient=6.0,
        city="taiyuan",
        created_at=datetime.now(timezone.utc),
    )


def _gpx(points: list[tuple[float, float]]) -> bytes:
    body = "".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>1400</ele></trkpt>'
        for lon, lat in points
    )
    return (
        '<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{body}</trkseg></trk></gpx>"
    ).encode()


def test_one_geometry_supports_both_directions_and_auto_reverses_input():
    endpoint_a = (112.413208, 37.986264)
    endpoint_b = (112.413419, 37.987454)
    # 用户从 B 画向 A；规范存储必须自动反成 A -> B。
    raw = (
        GpxPoint(112.413430, 37.987440),
        GpxPoint(112.413350, 37.986900),
        GpxPoint(112.413215, 37.986280),
    )
    prepared = prepare_connector_geometry(
        raw,
        endpoint_a=endpoint_a,
        endpoint_b=endpoint_b,
        max_snap_distance_m=100,
    )

    assert prepared.input_was_reversed is True
    assert prepared.coordinates[0] == endpoint_a
    assert prepared.coordinates[-1] == endpoint_b
    forward = coordinates_for_traversal(prepared.geometry_wkt, "a_to_b")
    backward = coordinates_for_traversal(prepared.geometry_wkt, "b_to_a")
    assert backward == tuple(reversed(forward))
    assert backward[0] == endpoint_b
    assert backward[-1] == endpoint_a


def test_connector_rejects_a_hand_drawn_line_too_far_from_anchor():
    raw = (
        GpxPoint(112.50, 37.90),
        GpxPoint(112.51, 37.91),
        GpxPoint(112.52, 37.92),
    )
    with pytest.raises(InternalRoutingConnectorError, match="超过"):
        prepare_connector_geometry(
            raw,
            endpoint_a=(112.41, 37.98),
            endpoint_b=(112.42, 37.99),
            max_snap_distance_m=100,
        )


def test_connector_rejects_a_hidden_long_route_disguised_as_a_gap():
    raw = (
        GpxPoint(112.4100, 37.9800),
        GpxPoint(112.4110, 37.9810),
        GpxPoint(112.4200, 37.9900),
    )
    with pytest.raises(InternalRoutingConnectorError, match="相邻点"):
        prepare_connector_geometry(
            raw,
            endpoint_a=(112.4100, 37.9800),
            endpoint_b=(112.4200, 37.9900),
            max_snap_distance_m=100,
        )


def test_created_connector_is_idempotent_and_absent_from_public_segment_list(
    db, client, admin_user
):
    segment_a = _segment(
        "马头水测试段",
        (112.417932, 37.954498),
        (112.413208, 37.986264),
    )
    segment_b = _segment(
        "横岭测试段",
        (112.413419, 37.987454),
        (112.444517, 37.984123),
    )
    db.add_all([segment_a, segment_b])
    db.commit()
    db.refresh(segment_a)
    db.refresh(segment_b)
    payload = _gpx(
        [
            (112.413430, 37.987440),
            (112.413350, 37.986900),
            (112.413215, 37.986280),
        ]
    )

    kwargs = dict(
        slug="matoushui-hengling-test-gap",
        name="马头水—横岭内部连接测试",
        city="taiyuan",
        gpx_payload=payload,
        source_name="hand-drawn-test.gpx",
        endpoint_a_segment_id=segment_a.id,
        endpoint_a_position="end",
        endpoint_b_segment_id=segment_b.id,
        endpoint_b_position="start",
        traversal_policy="bidirectional",
        blocked_provider="tencent",
        review_note="test reviewed",
        reviewer_user_id=admin_user.id,
        max_snap_distance_m=100,
    )
    first = create_internal_routing_connector(db, **kwargs)
    db.commit()
    second = create_internal_routing_connector(db, **kwargs)

    assert first.status == "created"
    assert second.status == "already_exists"
    assert first.connector_id == second.connector_id
    assert first.traversal_policy == "bidirectional"
    assert first.input_was_reversed is True
    assert db.query(func.count(InternalRoutingConnector.id)).scalar() == 1

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
    assert forward.direction == "a_to_b"
    assert backward.direction == "b_to_a"
    assert backward.coordinates == tuple(reversed(forward.coordinates))

    original_start_lat = segment_b.start_lat
    segment_b.start_lat = original_start_lat + 0.001
    db.flush()
    with pytest.raises(InternalRoutingConnectorError, match="锚点已经漂移"):
        resolve_internal_connector(
            db,
            from_segment_id=segment_a.id,
            from_position="end",
            to_segment_id=segment_b.id,
            to_position="start",
        )
    segment_b.start_lat = original_start_lat
    db.flush()

    response = client.get("/api/segments?city=taiyuan&page_size=100")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {
        "马头水测试段",
        "横岭测试段",
    }
    assert all("内部连接" not in item["name"] for item in body["items"])
