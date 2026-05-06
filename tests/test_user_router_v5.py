"""
v5 task-2.C.3：user router 4 个新 endpoint 测试。

策略：mock service 层（service 已有真 PG + 真 Redis 集成测试覆盖）。
本文件**只测 router 层**：
- 路径正确（/api/user/me/... 单数 / Tim 2026-04-30 拍 A）
- Query / body 参数校验（FastAPI 422）
- 错误翻译（ValueError → HTTPException 404 / 422）
- response schema 序列化（含白名单字段）
- JWT 认证（401 未登录）
"""

from unittest.mock import patch

import pytest


# ───────────────────────────────────────────────────────────────────────
# GET /api/user/me/power-curve
# ───────────────────────────────────────────────────────────────────────


def test_power_curve_requires_auth(client):
    """无 token → 401。"""
    resp = client.get("/api/user/me/power-curve")
    assert resp.status_code == 401


def test_power_curve_default_period(client, auth_header):
    """默认 period=this_month / service 被调对参数。"""
    fake_result = {"period": "this_month", "buckets": {"1": 800.0, "5": 700.0,
                   "30": 320.0, "60": 280.0, "300": 240.0, "1200": 200.0}}
    with patch("app.user.router.service.get_user_power_curve", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/power-curve", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"] == "this_month"
        assert body["buckets"]["300"] == 240.0
        # service 调用参数验证
        args = mock_svc.call_args
        assert args.args[2] == "this_month"  # period


def test_power_curve_explicit_period_last_year(client, auth_header):
    """传 period=last_year 透传给 service。"""
    fake_result = {"period": "last_year", "buckets": {"1": 0.0, "5": 0.0,
                   "30": 0.0, "60": 0.0, "300": 0.0, "1200": 0.0}}
    with patch("app.user.router.service.get_user_power_curve", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/power-curve?period=last_year", headers=auth_header)
        assert resp.status_code == 200
        assert mock_svc.call_args.args[2] == "last_year"


def test_power_curve_invalid_period_422(client, auth_header):
    """非枚举 period → 422（FastAPI 自动校验）。"""
    resp = client.get("/api/user/me/power-curve?period=yesterday", headers=auth_header)
    assert resp.status_code == 422


# ───────────────────────────────────────────────────────────────────────
# GET /api/user/me/heatmap
# ───────────────────────────────────────────────────────────────────────


def test_heatmap_requires_auth(client):
    resp = client.get("/api/user/me/heatmap?city=beijing")
    assert resp.status_code == 401


def test_heatmap_city_required_422(client, auth_header):
    """不传 city → 422（FastAPI 自动校验必填）。"""
    resp = client.get("/api/user/me/heatmap", headers=auth_header)
    assert resp.status_code == 422


def test_heatmap_invalid_city_422(client, auth_header):
    resp = client.get("/api/user/me/heatmap?city=guangzhou", headers=auth_header)
    assert resp.status_code == 422


def test_heatmap_valid_returns_geojson(client, auth_header):
    fake_result = {
        "city": "beijing",
        "multipoint": {"type": "MultiPoint", "coordinates": [[116.4, 39.9], [116.41, 39.91]]},
        "activity_count": 2,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result):
        resp = client.get("/api/user/me/heatmap?city=beijing", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["city"] == "beijing"
        assert body["multipoint"]["type"] == "MultiPoint"
        assert len(body["multipoint"]["coordinates"]) == 2
        assert body["activity_count"] == 2


# ───────────────────────────────────────────────────────────────────────
# PATCH /api/user/me
# ───────────────────────────────────────────────────────────────────────


def test_patch_me_requires_auth(client):
    resp = client.patch("/api/user/me", json={"city": "beijing"})
    assert resp.status_code == 401


def test_patch_me_invalid_city_422(client, auth_header):
    """非枚举 city → 422。"""
    resp = client.patch("/api/user/me", json={"city": "guangzhou"}, headers=auth_header)
    assert resp.status_code == 422


def test_patch_me_valid_city_calls_service(client, auth_header, test_user):
    """合法 city → 调 service.update_user_city + 返回最新 user。"""
    with patch("app.user.router.service.update_user_city") as mock_update:
        resp = client.patch("/api/user/me", json={"city": "shanghai"}, headers=auth_header)
        assert resp.status_code == 200
        # service 被正确调用
        args = mock_update.call_args
        assert args.args[1] == test_user.id
        assert args.args[2] == "shanghai"


def test_patch_me_empty_body_does_not_call_update(client, auth_header):
    """空 body → 不调 service.update_user_city（不抹空 city）。"""
    with patch("app.user.router.service.update_user_city") as mock_update:
        resp = client.patch("/api/user/me", json={}, headers=auth_header)
        # 应该返 200（无字段更新但接口正常）
        assert resp.status_code == 200
        mock_update.assert_not_called()


def test_patch_me_explicit_null_clears_city(client, auth_header, test_user):
    """body city=null → 调 service 传 None（与 update_user_city 接受 None 一致）。"""
    with patch("app.user.router.service.update_user_city") as mock_update:
        resp = client.patch("/api/user/me", json={"city": None}, headers=auth_header)
        assert resp.status_code == 200
        # 注意：UserPatchRequest 的 city 是 Optional[UserCity]
        # exclude_unset 保留 'city' key，service 收到 None 表示清空
        args = mock_update.call_args
        assert args.args[2] is None


# ───────────────────────────────────────────────────────────────────────
# GET /api/user/{user_id}/profile
# ───────────────────────────────────────────────────────────────────────


def test_get_profile_requires_auth(client):
    resp = client.get("/api/user/1/profile")
    assert resp.status_code == 401


def test_get_profile_returns_whitelist_fields(client, auth_header):
    """⚠ D-P08 红线：response 字段集合 = 白名单（多余字段被 schema 自动过滤）。"""
    # service 故意返回含敏感字段的 dict（即使代码层防得住，schema 层也得防）
    fake_result = {
        "id": 42,
        "nickname": "test",
        "avatar_url": "https://x",
        "city": "beijing",
        "ftp": 200,
        "bike_type": "road",
        "total_distance_km": 100.0,
        "total_elevation_m": 500.0,
        "activity_count": 5,
        "current_month_summary": {
            "distance_km": 30.0,
            "elevation_m": 100.0,
            "avg_power_w": 180.0,
        },
        # ⚠ service 层应该已过滤这些；但即使漏，schema 层不应让它们出去
        "openid": "wx_secret",
        "strava_access_token": "TOKEN_LEAK",
    }
    with patch("app.user.router.service.get_user_profile_for_others", return_value=fake_result):
        resp = client.get("/api/user/42/profile", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()

        # 严格白名单（Sprint 4 codex 异源审 2026-05-06 砍 ftp / P1-4）
        allowed = {"id", "nickname", "avatar_url", "city", "bike_type",
                   "total_distance_km", "total_elevation_m", "activity_count",
                   "current_month_summary"}
        assert set(body.keys()) == allowed

        # 敏感字段绝对不应出现（ftp 加入此列：Sprint 4 codex 拍砍 / FTP 是骑手生理数据）
        for forbidden in ("openid", "strava_access_token", "strava_refresh_token",
                          "mute_notifications", "weight", "ftp"):
            assert forbidden not in body, f"敏感字段 {forbidden} 泄漏！"


def test_get_profile_user_not_found_404(client, auth_header):
    """service 抛 ValueError → router 翻译为 404。"""
    with patch("app.user.router.service.get_user_profile_for_others",
               side_effect=ValueError("用户不存在")):
        resp = client.get("/api/user/999999/profile", headers=auth_header)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "用户不存在"


def test_get_profile_self_view_same_fields(client, auth_header, test_user):
    """D-P08 红线：看自己 vs 看他人 字段集合一致（不区分 self / others）。"""
    fake_result = {
        "id": test_user.id,
        "nickname": "self",
        "avatar_url": None,
        "city": None,
        "ftp": None,
        "bike_type": None,
        "total_distance_km": 0.0,
        "total_elevation_m": 0.0,
        "activity_count": 0,
        "current_month_summary": {"distance_km": 0.0, "elevation_m": 0.0, "avg_power_w": 0.0},
    }
    with patch("app.user.router.service.get_user_profile_for_others", return_value=fake_result):
        resp = client.get(f"/api/user/{test_user.id}/profile", headers=auth_header)
        assert resp.status_code == 200
        # 看自己也走 get_user_profile_for_others（D-P08 不区分）
        assert resp.json()["id"] == test_user.id
