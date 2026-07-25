"""腾讯道路证据：opaque receipt、服务端重建和 RouteVersion 绑定。"""

import json

import pytest

from app.parsing.geo_math import haversine
from app.route_book.routing_evidence import (
    RoutingEvidenceError,
    RoutingEvidenceQuotaError,
    build_tencent_evidence,
    load_snap_receipt,
    reconstruct_route_from_segments,
    routing_metadata_for_direct_route,
    routing_metadata_for_reconstructed_route,
    store_snap_receipt,
)


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.get_calls = 0

    def setex(self, key, _ttl, value):
        self.values[key] = value
        return True

    def get(self, key):
        self.get_calls += 1
        return self.values.get(key)

    def clear(self):
        self.values.clear()


class _QuotaRedis:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def eval(self, *args):
        self.calls.append(args)
        return self.result


def _planned(points):
    return {
        "distance": 1200.0,
        "duration": 8,
        "mode": "BICYCLING",
        "direction": "西南",
        "ferry_count": 0,
        "request_id": "request-123",
        "points": [{"lon": point[0], "lat": point[1]} for point in points],
        "steps": [
            {
                "instruction": "沿天清隧道骑行",
                "polyline_idx": [0, 3],
                "point_start": 0,
                "point_end": 1,
                "road_name": "天清隧道",
                "dir_desc": "西南",
                "distance": 700.0,
                "act_desc": "直行",
                "road_class": 0,
            },
            {
                "instruction": "沿西山旅游公路骑行",
                "polyline_idx": [2, 5],
                "point_start": 1,
                "point_end": 2,
                "road_name": "西山旅游公路",
                "dir_desc": "南",
                "distance": 500.0,
                "act_desc": "",
                "road_class": 0,
            },
        ],
    }


def test_opaque_receipt_keeps_geometry_server_side_and_is_user_bound(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.route_book.routing_evidence.settings.JWT_SECRET", "receipt-test-secret")
    points = [[112.5, 37.8], [112.54, 37.86], [112.6, 37.9]]
    evidence = build_tencent_evidence(_planned(points), points, observed_at="2026-07-19T00:00:00+00:00")

    receipt = store_snap_receipt(evidence, current_user_id=7, redis_client=redis)

    assert len(receipt) < 128
    assert str(points[1][0]) not in receipt
    assert load_snap_receipt(receipt, current_user_id=7, redis_client=redis)["geometry_gcj02"] == points
    with pytest.raises(RoutingEvidenceError, match="不属于当前用户"):
        load_snap_receipt(receipt, current_user_id=8, redis_client=redis)
    version, receipt_id, signature = receipt.split(".")
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(RoutingEvidenceError, match="已失效"):
        load_snap_receipt(
            f"{version}.{receipt_id}.{tampered_signature}",
            current_user_id=7,
            redis_client=redis,
        )
    redis.clear()
    with pytest.raises(RoutingEvidenceError, match="已过期"):
        load_snap_receipt(receipt, current_user_id=7, redis_client=redis)
    with pytest.raises(RoutingEvidenceError, match="格式异常"):
        load_snap_receipt("r1.汉.AA", current_user_id=7, redis_client=redis)


def test_receipt_store_uses_atomic_per_user_quota(monkeypatch):
    redis = _QuotaRedis(0)
    monkeypatch.setattr("app.route_book.routing_evidence.settings.JWT_SECRET", "receipt-test-secret")
    points = [[112.5, 37.8], [112.54, 37.86], [112.6, 37.9]]
    evidence = build_tencent_evidence(_planned(points), points)

    with pytest.raises(RoutingEvidenceQuotaError, match="草稿过多"):
        store_snap_receipt(evidence, current_user_id=7, redis_client=redis)

    assert len(redis.calls) == 1
    assert redis.calls[0][1] == 2
    assert "route_snap_receipt:v1:" in redis.calls[0][2]
    assert "route_snap_receipt_quota:v1:7:" in redis.calls[0][3]


def test_snap_and_freehand_parts_reconstruct_exact_provider_geometry(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.route_book.routing_evidence.settings.JWT_SECRET", "receipt-test-secret")
    provider_points = [[112.5, 37.8], [112.54, 37.86], [112.6, 37.9]]
    evidence = build_tencent_evidence(_planned(provider_points), provider_points)
    receipt = store_snap_receipt(evidence, current_user_id=9, redis_client=redis)
    monkeypatch.setattr("app.route_book.routing_evidence._get_redis_client", lambda: redis)

    reconstructed, bindings = reconstruct_route_from_segments(
        [
            {"mode": "snap", "routing_receipt": receipt, "points": []},
            {"mode": "freehand", "points": [[112.6, 37.9], [112.62, 37.92]]},
        ],
        current_user_id=9,
    )

    assert reconstructed == provider_points + [[112.62, 37.92]]
    assert bindings[0]["point_offset"] == 0
    metadata = routing_metadata_for_reconstructed_route(
        bindings,
        route_points_lonlat=reconstructed,
        line_hash="line-hash-1",
    )
    assert metadata["route_line_hash"] == "line-hash-1"
    assert metadata["steps"][0]["route_point_start"] == 0
    assert metadata["steps"][0]["route_point_end"] == 1
    assert metadata["steps"][-1]["route_point_end"] == 2
    assert metadata["segments"][0]["route_point_end"] == 2
    assert "geometry_gcj02" not in metadata["segments"][0]
    assert metadata["coverage_complete"] is False
    assert metadata["duration_min"] is None
    assert metadata["ferry_count"] is None


def test_direct_route_uses_exact_converted_point_indices_not_whole_route_ratio():
    provider_points = [[112.5, 37.8], [112.5005, 37.86], [112.6, 37.9]]
    route_points = [[112.4936, 37.7994], [112.4941, 37.8594], [112.5936, 37.8994]]

    metadata = routing_metadata_for_direct_route(
        _planned(provider_points),
        provider_points_lonlat=provider_points,
        route_points_lonlat=route_points,
        line_hash="direct-line-hash",
    )

    expected_middle_chainage = haversine(
        route_points[0][1], route_points[0][0], route_points[1][1], route_points[1][0]
    )
    assert metadata["steps"][0]["chainage_end_m"] == pytest.approx(expected_middle_chainage, abs=0.001)
    assert metadata["steps"][1]["chainage_start_m"] == pytest.approx(expected_middle_chainage, abs=0.001)
    assert metadata["coverage_complete"] is True
    assert metadata["duration_min"] == 8
    assert metadata["ferry_count"] == 0


def test_repeated_receipt_is_cached_but_counts_toward_total_evidence_limit(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr("app.route_book.routing_evidence.settings.JWT_SECRET", "receipt-test-secret")
    monkeypatch.setattr("app.route_book.routing_evidence.MAX_TOTAL_EVIDENCE_BYTES", 1)
    points = [[112.5, 37.8], [112.6, 37.9]]
    receipt = store_snap_receipt(
        build_tencent_evidence({**_planned(points), "steps": []}, points),
        current_user_id=7,
        redis_client=redis,
    )
    monkeypatch.setattr("app.route_book.routing_evidence._get_redis_client", lambda: redis)

    with pytest.raises(RoutingEvidenceError, match="证据总量过大"):
        reconstruct_route_from_segments(
            [{"mode": "snap", "routing_receipt": receipt, "points": []}],
            current_user_id=7,
        )
    assert redis.get_calls == 1


def test_legacy_manual_draw_hash_remains_byte_compatible():
    from app.route_book.service import _manual_draw_request_hash

    legacy_hash = _manual_draw_request_hash(
        name="旧客户端路线",
        coordinate_system="gcj02",
        points=[(112.5, 37.8), (112.6, 37.9)],
        draw_metadata={"tool": "route_draw_v0"},
        route_parts=None,
    )
    assert legacy_hash == "16aa721298f0510d20c70b7ade033cd1ca76b76bfbf0ce77ed119589bae35e42"

    v2_hash = _manual_draw_request_hash(
        name="旧客户端路线",
        coordinate_system="gcj02",
        points=[(112.5, 37.8), (112.6, 37.9)],
        draw_metadata={"tool": "route_draw_v0"},
        route_parts=[{"mode": "freehand", "points": [[112.5, 37.8], [112.6, 37.9]]}],
    )
    assert v2_hash != legacy_hash


def test_manual_save_ignores_client_shortcut_and_uses_receipt_geometry(
    client,
    db,
    auth_header,
    test_user,
    monkeypatch,
):
    from app.route_book.models import RouteBook, RouteVersion

    redis = _FakeRedis()
    monkeypatch.setattr("app.route_book.routing_evidence._get_redis_client", lambda: redis)
    provider_points = [[112.5, 37.8], [112.54, 37.86], [112.6, 37.9]]
    receipt = store_snap_receipt(
        build_tencent_evidence(_planned(provider_points), provider_points),
        current_user_id=test_user.id,
        redis_client=redis,
    )
    convert_calls = []
    elevation_calls = []

    def fake_convert(points, coordinate_system):
        convert_calls.append((points, coordinate_system))
        return [{"lon": point["lon"], "lat": point["lat"]} for point in points]

    def fake_query(coords):
        elevation_calls.append(coords)
        return [700.0 + index for index, _coord in enumerate(coords)]

    monkeypatch.setattr("app.route_book.service.convert_points_to_wgs84", fake_convert)
    monkeypatch.setattr("app.route_book.service.query_elevations", fake_query)
    payload = {
        "name": "receipt 重建路线",
        "client_request_id": "test-routing-receipt-save-001",
        "coordinate_system": "gcj02",
        # 客户端故意只交起终点直线；服务端必须忽略它，用 receipt 内完整腾讯曲线。
        "points": [provider_points[0], provider_points[-1]],
        "route_parts": [{"mode": "snap", "routing_receipt": receipt, "points": []}],
        "draw_metadata": {
            "tool": "route_draw_v0",
            "snap_provider": "tencent_bicycling",
            "segment_count": 1,
            "freehand_segment_count": 0,
        },
    }

    created = client.post("/api/route-books/manual-drawn", json=payload, headers=auth_header)

    assert created.status_code == 200, created.text
    body = created.json()
    assert body["preview_points"] == provider_points
    assert len(convert_calls) == 1
    assert [
        [point["lon"], point["lat"]] for point in convert_calls[0][0]
    ] == provider_points
    route = db.query(RouteBook).filter(RouteBook.id == body["id"]).one()
    version = db.query(RouteVersion).filter(RouteVersion.id == body["current_version_id"]).one()
    metadata = json.loads(version.navigation_metadata_json)
    assert metadata["routing"]["route_line_hash"] == version.line_hash == route.line_hash
    assert metadata["routing"]["steps"][0]["road_name"] == "天清隧道"
    assert metadata["routing"]["steps"][0]["route_point_end"] == 1
    assert metadata["routing"]["steps"][1]["route_point_end"] == 2
    assert metadata["elevation"]["method"] == "glo30_meaningful_ascent_v1"

    # receipt 过期后，同一 client_request_id 的未知结果重试仍先命中 DB 幂等记录。
    redis.clear()
    elevation_call_count = len(elevation_calls)
    retried = client.post("/api/route-books/manual-drawn", json=payload, headers=auth_header)
    assert retried.status_code == 200
    assert retried.json()["id"] == body["id"]
    assert len(elevation_calls) == elevation_call_count


def test_manual_save_rejects_non_ascii_receipt_as_structured_422(client, auth_header):
    response = client.post(
        "/api/route-books/manual-drawn",
        json={
            "name": "坏 receipt",
            "client_request_id": "test-routing-bad-receipt-001",
            "coordinate_system": "gcj02",
            "points": [[112.5, 37.8], [112.6, 37.9]],
            "route_parts": [{"mode": "snap", "routing_receipt": "r1.汉.AA", "points": []}],
        },
        headers=auth_header,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "routing_receipt_invalid"
    assert "第 1 个贴路片段" in response.json()["detail"]["message"]


def test_direct_tencent_route_persists_steps_poi_and_route_version_hash(
    client,
    db,
    auth_header,
    monkeypatch,
):
    from app.route_book.models import RouteVersion

    provider_points = [[112.5, 37.8], [112.54, 37.86], [112.6, 37.9]]
    calls = []

    def fake_plan(start, end, **kwargs):
        calls.append((start, end, kwargs))
        return _planned(provider_points)

    monkeypatch.setattr("app.route_book.service.plan_tencent_bicycling_route", fake_plan)
    monkeypatch.setattr(
        "app.route_book.service.convert_points_to_wgs84",
        lambda points, _coordinate_system: [
            {"lon": point["lon"], "lat": point["lat"]} for point in points
        ],
    )
    monkeypatch.setattr(
        "app.route_book.service.query_elevations",
        lambda coords: [700.0 + index for index, _coord in enumerate(coords)],
    )

    created = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "腾讯 POI 路线",
            "coordinate_system": "gcj02",
            "from_lat": 37.8,
            "from_lon": 112.5,
            "to_lat": 37.9,
            "to_lon": 112.6,
            "from_poi": "poi-start",
            "to_poi": "poi-end",
            "from_poi_context": {
                "provider_poi_id": "poi-start",
                "title": "万亩生态园",
                "category": "旅游景点",
                "category_code": "110000",
                "district": "晋源区",
                "gcj_lat": 37.8,
                "gcj_lon": 112.5,
            },
            "to_poi_context": {
                "provider_poi_id": "poi-end",
                "title": "狼坡",
                "district": "万柏林区",
                "gcj_lat": 37.9,
                "gcj_lon": 112.6,
            },
        },
        headers=auth_header,
    )

    assert created.status_code == 200, created.text
    assert calls == [((37.8, 112.5), (37.9, 112.6), {"from_poi": "poi-start", "to_poi": "poi-end"})]
    version = db.query(RouteVersion).filter(RouteVersion.id == created.json()["current_version_id"]).one()
    metadata = json.loads(version.navigation_metadata_json)
    assert metadata["routing"]["route_line_hash"] == version.line_hash
    assert metadata["routing"]["segments"][0]["from_poi"] == "poi-start"
    assert metadata["routing"]["segments"][0]["to_poi"] == "poi-end"
    assert metadata["routing"]["segments"][0]["from_poi_context"] == {
        "source": "client_echo",
        "verified": False,
        "data": {
            "provider_poi_id": "poi-start",
            "title": "万亩生态园",
            "category": "旅游景点",
            "category_code": "110000",
            "district": "晋源区",
            "gcj_lat": 37.8,
            "gcj_lon": 112.5,
        },
    }
    assert metadata["routing"]["segments"][0]["request_id"] == "request-123"
    assert metadata["routing"]["steps"][0]["road_name"] == "天清隧道"
    assert metadata["routing"]["steps"][1]["route_point_end"] == 2

    rejected = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "错误坐标系",
            "coordinate_system": "wgs84",
            "from_lat": 37.8,
            "from_lon": 112.5,
            "to_lat": 37.9,
            "to_lon": 112.6,
        },
        headers=auth_header,
    )
    assert rejected.status_code == 422

    mismatched_context = client.post(
        "/api/route-books/tencent-direction",
        json={
            "name": "POI 身份错配",
            "coordinate_system": "gcj02",
            "from_lat": 37.8,
            "from_lon": 112.5,
            "to_lat": 37.9,
            "to_lon": 112.6,
            "from_poi": "poi-start",
            "from_poi_context": {"provider_poi_id": "another-poi"},
        },
        headers=auth_header,
    )
    assert mismatched_context.status_code == 422
