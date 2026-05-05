"""admin from-gpx endpoint 测试。"""

from datetime import datetime, timezone

from app.segment.exceptions import SegmentOverlapError
from app.segment.models import Segment


def _payload(**overrides):
    """构造合法 from-gpx 请求，单个测试只覆盖自己关心的字段。"""
    base = {
        "name": "太原 GPX 赛段",
        "description": "从 GPX 解析后的赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    base.update(overrides)
    return base


def _fake_segment(**overrides):
    """构造 service 返回的 Segment，endpoint 测试不重复跑赛段算法。"""
    base = {
        "id": 123,
        "name": "太原 GPX 赛段",
        "description": "从 GPX 解析后的赛段",
        "distance": 1200.0,
        "elevation_gain": None,
        "elevation_loss": None,
        "avg_gradient": None,
        "max_gradient": None,
        "difficulty": "medium",
        "city": "taiyuan",
        "start_lat": 37.87,
        "start_lon": 112.55,
        "end_lat": 37.875,
        "end_lon": 112.55,
        "reference_line": "SRID=4326;LINESTRING(112.55 37.87, 112.55 37.875)",
        "match_tolerance": 50.0,
        "min_match_ratio": 0.8,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return Segment(**base)


def test_admin_from_gpx_basic_create_201(client, admin_header, admin_user, monkeypatch):
    """合法请求应薄封装调用 segment service，并返回 admin 赛段响应。"""
    captured = {}

    def _fake_create(
        db,
        user_id,
        name,
        reference_points,
        description,
        match_tolerance,
        min_match_ratio,
        coordinate_system,
    ):
        captured.update(
            {
                "user_id": user_id,
                "name": name,
                "reference_points": reference_points,
                "description": description,
                "match_tolerance": match_tolerance,
                "min_match_ratio": min_match_ratio,
                "coordinate_system": coordinate_system,
            }
        )
        segment = _fake_segment(name=name, description=description)
        db.add(segment)
        db.flush()
        return segment

    monkeypatch.setattr("app.admin.router.segment_service.create_segment", _fake_create)

    res = client.post(
        "/api/admin/segments/from-gpx",
        json=_payload(match_tolerance=60.0, min_match_ratio=0.9),
        headers=admin_header,
    )

    assert res.status_code == 201
    assert captured == {
        "user_id": admin_user.id,
        "name": "太原 GPX 赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "description": "从 GPX 解析后的赛段",
        "match_tolerance": 60.0,
        "min_match_ratio": 0.9,
        "coordinate_system": "wgs84",
    }
    data = res.json()
    assert data["name"] == "太原 GPX 赛段"
    assert data["distance"] == 1.2
    assert data["city"] == "taiyuan"


def test_admin_from_gpx_normal_user_403(client, auth_header, monkeypatch):
    """router 层 require_admin 应挡住普通用户，不能触发 service。"""
    called = {"value": False}

    def _fake_create(*args, **kwargs):  # pragma: no cover - 被调用就是测试失败
        called["value"] = True

    monkeypatch.setattr("app.admin.router.segment_service.create_segment", _fake_create)

    res = client.post(
        "/api/admin/segments/from-gpx",
        json=_payload(),
        headers=auth_header,
    )

    assert res.status_code == 403
    assert called["value"] is False


def test_admin_from_gpx_invalid_coords_422(client, admin_header, monkeypatch):
    """lat/lon 越界属于请求格式错误，应由 schema 层 422 拦截。"""
    called = {"value": False}

    def _fake_create(*args, **kwargs):  # pragma: no cover - 被调用就是测试失败
        called["value"] = True

    monkeypatch.setattr("app.admin.router.segment_service.create_segment", _fake_create)

    res = client.post(
        "/api/admin/segments/from-gpx",
        json=_payload(reference_points=[{"lat": 999, "lon": 112.55}, {"lat": 37.87, "lon": 112.55}]),
        headers=admin_header,
    )

    assert res.status_code == 422
    assert called["value"] is False


def test_admin_from_gpx_too_short_400(client, admin_header, monkeypatch):
    """service 判定距离过短时，router 翻译为 400。"""

    def _fake_create(*args, **kwargs):
        raise ValueError("赛段距离过短，请检查坐标点")

    monkeypatch.setattr("app.admin.router.segment_service.create_segment", _fake_create)

    res = client.post(
        "/api/admin/segments/from-gpx",
        json=_payload(reference_points=[{"lat": 37.87, "lon": 112.55}, {"lat": 37.87, "lon": 112.55}]),
        headers=admin_header,
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "赛段距离过短，请检查坐标点"


def test_admin_from_gpx_extra_forbid_422(client, admin_header, monkeypatch):
    """admin schema extra='forbid'，误传未知字段时应 422。"""
    called = {"value": False}

    def _fake_create(*args, **kwargs):  # pragma: no cover - 被调用就是测试失败
        called["value"] = True

    monkeypatch.setattr("app.admin.router.segment_service.create_segment", _fake_create)

    res = client.post(
        "/api/admin/segments/from-gpx",
        json=_payload(unknown_field="foo"),
        headers=admin_header,
    )

    assert res.status_code == 422
    assert called["value"] is False


def test_old_endpoint_returns_deprecation_header(client, admin_header, monkeypatch):
    """老 POST /api/segments 仍工作，并返回弃用迁移 header。"""

    def _fake_create(db, user_id, name, reference_points, **kwargs):
        return _fake_segment(name=name, description=kwargs.get("description"))

    monkeypatch.setattr("app.segment.router.service.create_segment", _fake_create)

    res = client.post(
        "/api/segments",
        json=_payload(),
        headers=admin_header,
    )

    assert res.status_code == 200
    assert res.headers.get("Deprecation") == "true"
    assert res.headers.get("Sunset") == "Tue, 30 Jun 2026 00:00:00 GMT"


def test_admin_from_gpx_overlap_409(client, admin_header, monkeypatch):
    """service 判定赛段重叠时，admin from-gpx 应翻译为 409。"""

    def _fake_create(*args, **kwargs):
        raise SegmentOverlapError("新赛段与已有赛段高度重叠")

    monkeypatch.setattr("app.admin.router.segment_service.create_segment", _fake_create)

    res = client.post(
        "/api/admin/segments/from-gpx",
        json=_payload(),
        headers=admin_header,
    )

    assert res.status_code == 409
    assert "重叠" in res.json()["detail"]
