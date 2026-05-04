"""admin from-activity endpoint 测试。"""

from datetime import datetime, timezone

from app.segment.exceptions import InvalidSegmentRangeError, SegmentOverlapError
from app.segment.models import Segment


def _fake_segment(**overrides):
    """构造 service 返回的 Segment，避免 endpoint 测试重复跑 PostGIS 算法。"""
    base = {
        "name": "from activity 赛段",
        "description": None,
        "distance": 2200.0,
        "elevation_gain": 80.0,
        "elevation_loss": 10.0,
        "avg_gradient": 3.2,
        "max_gradient": 7.5,
        "difficulty": "hard",
        "city": "taiyuan",
        "start_lat": 37.87,
        "start_lon": 112.55,
        "end_lat": 37.89,
        "end_lon": 112.57,
        "reference_line": "SRID=4326;LINESTRING(112.55 37.87, 112.57 37.89)",
        "match_tolerance": 50.0,
        "min_match_ratio": 0.8,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return Segment(**base)


def test_from_activity_admin_only(client, auth_header, monkeypatch):
    """from-activity 是 admin 工具，普通用户不能触发 service。"""
    called = {"value": False}

    def _fake_create(*args, **kwargs):  # pragma: no cover - 被调用就是测试失败
        called["value"] = True

    monkeypatch.setattr(
        "app.admin.router.segment_service.create_segment_from_activity",
        _fake_create,
    )

    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 1,
            "name": "太原 from activity",
            "start_index": 0,
            "end_index": 20,
        },
        headers=auth_header,
    )

    assert res.status_code == 403
    assert called["value"] is False


def test_from_activity_basic_create_201(client, admin_header, monkeypatch):
    """合法请求应调用 service，commit 后返回 km 单位和自动推断字段。"""
    captured = {}

    def _fake_create(db, activity_id, name, start_index, end_index, city, difficulty):
        captured.update(
            {
                "activity_id": activity_id,
                "name": name,
                "start_index": start_index,
                "end_index": end_index,
                "city": city,
                "difficulty": difficulty,
            }
        )
        segment = _fake_segment(name=name, city=city, difficulty=difficulty)
        db.add(segment)
        db.flush()
        return segment

    monkeypatch.setattr(
        "app.admin.router.segment_service.create_segment_from_activity",
        _fake_create,
    )

    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 42,
            "name": "太原 from activity",
            "start_index": 0,
            "end_index": 20,
            "city": "taiyuan",
            "difficulty": "hard",
        },
        headers=admin_header,
    )

    assert res.status_code == 201
    assert captured == {
        "activity_id": 42,
        "name": "太原 from activity",
        "start_index": 0,
        "end_index": 20,
        "city": "taiyuan",
        "difficulty": "hard",
    }
    data = res.json()
    assert data["name"] == "太原 from activity"
    assert data["distance"] == 2.2
    assert data["city"] == "taiyuan"
    assert data["difficulty"] == "hard"
    assert data["draft_status"] is None
    assert data["pool_status"] is None


def test_from_activity_schema_invalid_range_422(client, admin_header, monkeypatch):
    """start_index >= end_index 属于请求格式错误，应在 schema 层 422。"""
    called = {"value": False}

    def _fake_create(*args, **kwargs):  # pragma: no cover - 被调用就是测试失败
        called["value"] = True

    monkeypatch.setattr(
        "app.admin.router.segment_service.create_segment_from_activity",
        _fake_create,
    )

    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 42,
            "name": "太原 from activity",
            "start_index": 20,
            "end_index": 20,
        },
        headers=admin_header,
    )

    assert res.status_code == 422
    assert called["value"] is False


def test_from_activity_service_invalid_range_400(client, admin_header, monkeypatch):
    """service 判定子序列点数不足 / 太短时，router 翻译为 400。"""

    def _fake_create(*args, **kwargs):
        raise InvalidSegmentRangeError("赛段太短，至少 1 公里")

    monkeypatch.setattr(
        "app.admin.router.segment_service.create_segment_from_activity",
        _fake_create,
    )

    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 42,
            "name": "太原 from activity",
            "start_index": 0,
            "end_index": 20,
        },
        headers=admin_header,
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "赛段太短，至少 1 公里"


def test_from_activity_overlap_409(client, admin_header, monkeypatch):
    """Hausdorff 查重命中时，router 翻译为 409。"""

    def _fake_create(*args, **kwargs):
        raise SegmentOverlapError("新赛段与已有赛段高度重叠")

    monkeypatch.setattr(
        "app.admin.router.segment_service.create_segment_from_activity",
        _fake_create,
    )

    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 42,
            "name": "太原 from activity",
            "start_index": 0,
            "end_index": 20,
        },
        headers=admin_header,
    )

    assert res.status_code == 409
    assert res.json()["detail"] == "新赛段与已有赛段高度重叠"


def test_from_activity_activity_not_exist_404(client, admin_header, monkeypatch):
    """activity 不存在时，service 的 ValueError 应翻译为 404。"""

    def _fake_create(*args, **kwargs):
        raise ValueError("活动不存在")

    monkeypatch.setattr(
        "app.admin.router.segment_service.create_segment_from_activity",
        _fake_create,
    )

    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 999999,
            "name": "太原 from activity",
            "start_index": 0,
            "end_index": 20,
        },
        headers=admin_header,
    )

    assert res.status_code == 404
    assert res.json()["detail"] == "活动不存在"


def test_from_activity_invalid_city_422(client, admin_header):
    """city 只能是 v5 枚举值，拼错应由 schema 422 拦截。"""
    res = client.post(
        "/api/admin/segments/from-activity",
        json={
            "activity_id": 42,
            "name": "太原 from activity",
            "start_index": 0,
            "end_index": 20,
            "city": "nanjing",
        },
        headers=admin_header,
    )

    assert res.status_code == 422
