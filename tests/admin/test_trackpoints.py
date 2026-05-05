"""admin GET /api/admin/activities/{id}/trackpoints endpoint 测试。

不连真 PG（PostGIS Geometry 列 SQLite 不支持），用 monkeypatch mock service 函数，
跟 test_from_gpx / test_from_activity 同风格。service 真行为由 dev stack 集成测试覆盖。
"""

from datetime import datetime, timezone


def test_admin_trackpoints_basic_200(client, admin_header, monkeypatch):
    """admin 拉到 trackpoints，返回 lat/lon/elevation/timestamp 列表。"""
    captured = {}

    def _fake_list(db, activity_id):
        captured["activity_id"] = activity_id
        return {
            "activity_id": activity_id,
            "total": 2,
            "trackpoints": [
                {
                    "seq": 0,
                    "lat": 37.87,
                    "lon": 112.55,
                    "elevation": 800.0,
                    "timestamp": datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc),
                },
                {
                    "seq": 1,
                    "lat": 37.875,
                    "lon": 112.555,
                    "elevation": 805.0,
                    "timestamp": datetime(2026, 5, 1, 8, 0, 5, tzinfo=timezone.utc),
                },
            ],
        }

    monkeypatch.setattr(
        "app.admin.router.admin_service.list_activity_trackpoints_admin",
        _fake_list,
    )

    res = client.get("/api/admin/activities/42/trackpoints", headers=admin_header)

    assert res.status_code == 200
    assert captured == {"activity_id": 42}
    data = res.json()
    assert data["activity_id"] == 42
    assert data["total"] == 2
    assert len(data["trackpoints"]) == 2
    assert data["trackpoints"][0]["seq"] == 0
    assert data["trackpoints"][0]["lat"] == 37.87
    assert data["trackpoints"][0]["lon"] == 112.55
    assert data["trackpoints"][0]["elevation"] == 800.0


def test_admin_trackpoints_normal_user_403(client, auth_header, monkeypatch):
    """普通用户访问应被 require_admin 挡住，service 不应被调到。"""
    called = {"value": False}

    def _fake_list(*args, **kwargs):  # pragma: no cover - 被调用就是测试失败
        called["value"] = True

    monkeypatch.setattr(
        "app.admin.router.admin_service.list_activity_trackpoints_admin",
        _fake_list,
    )

    res = client.get("/api/admin/activities/1/trackpoints", headers=auth_header)

    assert res.status_code == 403
    assert called["value"] is False


def test_admin_trackpoints_not_found_404(client, admin_header, monkeypatch):
    """activity 不存在时 service 抛 ValueError，router 翻译为 404。"""

    def _fake_list(db, activity_id):
        raise ValueError("activity not found")

    monkeypatch.setattr(
        "app.admin.router.admin_service.list_activity_trackpoints_admin",
        _fake_list,
    )

    res = client.get("/api/admin/activities/99999/trackpoints", headers=admin_header)

    assert res.status_code == 404
    assert res.json()["detail"] == "activity not found"


def test_admin_trackpoints_unauthenticated_401(client):
    """无 JWT 完全裸访问应 401，不应到 require_admin。"""
    res = client.get("/api/admin/activities/1/trackpoints")
    assert res.status_code == 401


def test_admin_trackpoints_empty_list_200(client, admin_header, monkeypatch):
    """activity 存在但 trackpoints 表为空（极少见，比如解析失败）应返 200 + 空列表。"""

    def _fake_list(db, activity_id):
        return {"activity_id": activity_id, "total": 0, "trackpoints": []}

    monkeypatch.setattr(
        "app.admin.router.admin_service.list_activity_trackpoints_admin",
        _fake_list,
    )

    res = client.get("/api/admin/activities/7/trackpoints", headers=admin_header)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["trackpoints"] == []
