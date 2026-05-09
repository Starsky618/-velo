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
    """默认 period=last_30_days / service 被调对参数 / 7 档 buckets（D26 v2 polish）。"""
    fake_result = {"period": "last_30_days", "buckets": {"0": 1000.0, "3": 850.0,
                   "30": 320.0, "60": 280.0, "300": 240.0, "1200": 200.0, "3600": 180.0}}
    with patch("app.user.router.service.get_user_power_curve", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/power-curve", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"] == "last_30_days"
        assert body["buckets"]["300"] == 240.0
        assert body["buckets"]["3600"] == 180.0  # 1h 档（D26 新增）
        assert body["buckets"]["0"] == 1000.0    # 瞬时最大档（D26 新增）
        # service 调用参数验证
        args = mock_svc.call_args
        assert args.args[2] == "last_30_days"  # period


def test_power_curve_explicit_period_last_365_days(client, auth_header):
    """传 period=last_365_days 透传给 service（D16 v0.3 / 滚动窗口 + D26 v2 polish 7 档）。"""
    fake_result = {"period": "last_365_days", "buckets": {"0": 0.0, "3": 0.0,
                   "30": 0.0, "60": 0.0, "300": 0.0, "1200": 0.0, "3600": 0.0}}
    with patch("app.user.router.service.get_user_power_curve", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/power-curve?period=last_365_days", headers=auth_header)
        assert resp.status_code == 200
        assert mock_svc.call_args.args[2] == "last_365_days"


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


def test_heatmap_city_optional_returns_200(client, auth_header):
    """v3 polish：不传 city → 200（不再是 422 必填）+ service 收到 None。"""
    fake_result = {
        "city": None,
        "tracks": [
            [[116.4, 39.9], [116.41, 39.91]],
        ],
        "activity_count": 1,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/heatmap", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        # response.city 透传 None
        assert body["city"] is None
        assert len(body["tracks"]) == 1
        # service 第三个位置参数（city）应为 None
        assert mock_svc.call_args.args[2] is None


def test_heatmap_invalid_city_422(client, auth_header):
    """传非枚举 city 仍 422（保留旧行为 / 防误传 'guangzhou' 等无效值）。"""
    resp = client.get("/api/user/me/heatmap?city=guangzhou", headers=auth_header)
    assert resp.status_code == 422


def test_heatmap_valid_returns_tracks(client, auth_header):
    """heatmap 返回 tracks 列表（每个 activity 一条轨迹 / D27 v2 polish）。"""
    fake_result = {
        "city": "beijing",
        "tracks": [
            [[116.4, 39.9], [116.41, 39.91], [116.42, 39.92]],   # activity 1
            [[116.45, 39.95], [116.46, 39.96]],                   # activity 2
        ],
        "activity_count": 2,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/heatmap?city=beijing", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["city"] == "beijing"
        assert len(body["tracks"]) == 2
        assert len(body["tracks"][0]) == 3  # activity 1 有 3 个点
        assert len(body["tracks"][1]) == 2  # activity 2 有 2 个点
        assert body["activity_count"] == 2
        # 走旧路径 / service 收到 "beijing" 字符串（不是 None）
        assert mock_svc.call_args.args[2] == "beijing"


def test_heatmap_no_city_returns_all_tracks(client, auth_header):
    """v3 polish：不传 city → service 透传 None / 返回多 city 混合 tracks。
    本测试 mock service 返"跨北京/上海"混合数据，验证 router 不做城市筛。"""
    fake_result = {
        "city": None,
        "tracks": [
            [[116.4, 39.9], [116.41, 39.91]],     # 北京起点
            [[121.47, 31.23], [121.48, 31.24]],   # 上海起点
            [[120.15, 30.27], [120.16, 30.28]],   # 杭州起点
        ],
        "activity_count": 3,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/me/heatmap", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["city"] is None
        assert body["activity_count"] == 3
        assert len(body["tracks"]) == 3
        # 关键：router 必须把 None 透传给 service（不是 'unknown' 不是空串）
        assert mock_svc.call_args.args[2] is None


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


# ───────────────────────────────────────────────────────────────────────
# task-4.3.0：GET /api/user/{user_id}/power-curve（看他人功率曲线）
# ───────────────────────────────────────────────────────────────────────


def test_user_power_curve_requires_auth(client):
    """未登录看他人 power-curve → 401。"""
    resp = client.get("/api/user/42/power-curve")
    assert resp.status_code == 401


def test_user_power_curve_returns_buckets(client, auth_header):
    """看他人 power-curve 200 / service 调对参数（user_id + period）。

    同时**隐式覆盖动态路由匹配**：user_id=42 走 /{user_id}/power-curve 不被 /me/... 截胡
    （Claude 综合审 Important-2）。
    """
    fake_user = object()  # get_user_by_id 真路径返 ORM User / 这里只占位（不抛 ValueError 即可）
    fake_result = {"period": "last_90_days", "buckets": {"0": 900.0, "3": 750.0,
                   "30": 300.0, "60": 260.0, "300": 220.0, "1200": 180.0, "3600": 160.0}}
    with patch("app.user.router.service.get_user_by_id", return_value=fake_user), \
         patch("app.user.router.service.get_user_power_curve", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/42/power-curve?period=last_90_days", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"] == "last_90_days"
        assert body["buckets"]["3600"] == 160.0
        # service 调用参数：(db, user_id=42, period="last_90_days")
        args = mock_svc.call_args.args
        assert args[1] == 42
        assert args[2] == "last_90_days"


def test_user_power_curve_user_not_found_404(client, auth_header):
    """user 不存在 → service.get_user_by_id 抛 ValueError → router 翻 404 + service.get_user_power_curve 不被调用。

    注意：mock 用 side_effect=ValueError 跟 service.get_user_by_id 真契约一致
    （service.py L140 抛 ValueError，不返 None / Claude 审 Critical-2 验证后修）。
    """
    with patch("app.user.router.service.get_user_by_id",
               side_effect=ValueError("用户不存在")), \
         patch("app.user.router.service.get_user_power_curve") as mock_svc:
        resp = client.get("/api/user/999999/power-curve", headers=auth_header)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "用户不存在"
        mock_svc.assert_not_called()


def test_user_power_curve_route_not_collide_with_me(client, auth_header):
    """路由匹配验证：/me/power-curve 静态优先 / 不会被 /{user_id}/... 截胡。

    场景：尝试 GET /api/user/me/power-curve（非 user_id）应该走 me 路由不抛 422
    （如果路由匹配错把 'me' 当 user_id 解析 → 422 string→int 失败）。
    """
    fake_result = {"period": "last_30_days", "buckets": {"0": 0.0, "3": 0.0,
                   "30": 0.0, "60": 0.0, "300": 0.0, "1200": 0.0, "3600": 0.0}}
    with patch("app.user.router.service.get_user_power_curve", return_value=fake_result):
        resp = client.get("/api/user/me/power-curve", headers=auth_header)
        # 静态优先匹配成功 → 200，不是 422（'me' 没被当成 user_id 解析）
        assert resp.status_code == 200


def test_user_power_curve_unexpected_exception_not_swallowed_as_404(client, auth_header):
    """防御性测试（Codex 异源审 Important-1）：service.get_user_by_id 抛**非 ValueError** 异常时
    不应被误翻译成 404 / 必须 propagate（FastAPI 翻 500）。

    锁住未来如果 endpoint 改成 broad except / except Exception:，OperationalError /
    TimeoutError 等真实故障会被静默吞成"用户不存在"的语义错误。

    实现：TestClient 默认 raise_server_exceptions=True / 服务端未 catch 的异常会 propagate
    到测试帧 → pytest.raises 抓住即证明 endpoint 没吞异常。如果 endpoint 错误吞了，
    response 会正常返回（404 detail="用户不存在"）→ pytest.raises 不触发 → 测试 fail。
    """
    with patch("app.user.router.service.get_user_by_id",
               side_effect=RuntimeError("database connection lost")):
        with pytest.raises(RuntimeError):
            client.get("/api/user/42/power-curve", headers=auth_header)


# ───────────────────────────────────────────────────────────────────────
# task-4.3.0：GET /api/user/{user_id}/heatmap（看他人热图）
# ───────────────────────────────────────────────────────────────────────


def test_user_heatmap_requires_auth(client):
    """未登录 → 401。"""
    resp = client.get("/api/user/42/heatmap")
    assert resp.status_code == 401


def test_user_heatmap_no_city_returns_all_tracks(client, auth_header):
    """D30 v3 polish：不传 city → 200 / service 收到 None / 看 ta 全部足迹。"""
    fake_user = object()
    fake_result = {
        "city": None,
        "tracks": [[[116.4, 39.9], [116.41, 39.91]]],
        "activity_count": 1,
    }
    with patch("app.user.router.service.get_user_by_id", return_value=fake_user), \
         patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/42/heatmap", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["city"] is None
        assert body["activity_count"] == 1
        # service 第 3 参数 = None
        assert mock_svc.call_args.args[1] == 42
        assert mock_svc.call_args.args[2] is None


def test_user_heatmap_with_city_filter(client, auth_header):
    """传 city=beijing → service 收到 'beijing' / 按城市筛。

    注：city=非法值（如 guangzhou）→ 422 已被 schemas.UserCity 枚举层拦下（同 me/heatmap 覆盖于 L92
    `test_heatmap_invalid_city_422`）/ 看他人走同 schema 同处理 / 不重复补 case
    （Claude 综合审 Important-3）。
    """
    fake_user = object()
    fake_result = {
        "city": "beijing",
        "tracks": [[[116.4, 39.9], [116.41, 39.91]]],
        "activity_count": 1,
    }
    with patch("app.user.router.service.get_user_by_id", return_value=fake_user), \
         patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get("/api/user/42/heatmap?city=beijing", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["city"] == "beijing"
        assert mock_svc.call_args.args[2] == "beijing"


def test_user_heatmap_user_not_found_404(client, auth_header):
    """user 不存在 → service.get_user_by_id 抛 ValueError → router 翻 404 + service.get_user_heatmap 不被调用。

    side_effect=ValueError 跟 service.get_user_by_id 真契约一致（同 power-curve 404 case）。
    """
    with patch("app.user.router.service.get_user_by_id",
               side_effect=ValueError("用户不存在")), \
         patch("app.user.router.service.get_user_heatmap") as mock_svc:
        resp = client.get("/api/user/999999/heatmap?city=beijing", headers=auth_header)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "用户不存在"
        mock_svc.assert_not_called()


def test_user_heatmap_route_not_collide_with_me(client, auth_header):
    """对称性测试（Codex 异源审 Important-2 / 跟 power-curve 路由测试对称）：
    /me/heatmap 静态路径优先 / 不会被 /{user_id}/... 截胡。

    场景：GET /api/user/me/heatmap 应该走 me 路由 / 不抛 422（'me' 不被当 user_id）。
    """
    fake_result = {
        "city": None,
        "tracks": [],
        "activity_count": 0,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result):
        resp = client.get("/api/user/me/heatmap", headers=auth_header)
        assert resp.status_code == 200


def test_user_heatmap_unexpected_exception_not_swallowed_as_404(client, auth_header):
    """防御性测试（Codex 异源审 Important-1 / 跟 power-curve 对称）：
    service.get_user_by_id 抛**非 ValueError** 异常 → 不应被误翻 404 / 必须 propagate。

    详 test_user_power_curve_unexpected_exception_not_swallowed_as_404 注释。
    """
    with patch("app.user.router.service.get_user_by_id",
               side_effect=RuntimeError("database connection lost")):
        with pytest.raises(RuntimeError):
            client.get("/api/user/42/heatmap", headers=auth_header)
