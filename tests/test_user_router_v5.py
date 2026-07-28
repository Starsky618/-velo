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


def test_heatmap_passes_year_and_detail_to_service(client, auth_header):
    fake_result = {
        "city": None,
        "tracks": [[[116.4, 39.9], [116.41, 39.91]]],
        "activity_count": 1,
        "available_years": [2026, 2025],
        "selected_year": 2025,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get(
            "/api/user/me/heatmap?year=2025&detail=card",
            headers=auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["selected_year"] == 2025
        assert resp.json()["available_years"] == [2026, 2025]
        assert mock_svc.call_args.args[3:] == (2025, "card")


def test_heatmap_rejects_invalid_year_and_detail(client, auth_header):
    assert client.get(
        "/api/user/me/heatmap?year=1999",
        headers=auth_header,
    ).status_code == 422


def test_heatmap_viewport_requires_bounds_and_passes_visible_region(client, auth_header):
    assert client.get(
        "/api/user/me/heatmap?detail=viewport&zoom=10",
        headers=auth_header,
    ).status_code == 422

    fake_result = {
        "city": None,
        "tracks": [[[112.5, 37.7], [112.6, 37.8]]],
        "activity_count": 1,
    }
    with patch("app.user.router.service.get_user_heatmap", return_value=fake_result) as mock_svc:
        resp = client.get(
            "/api/user/me/heatmap?detail=viewport&west=112.3&south=37.5"
            "&east=112.8&north=38.1&zoom=10",
            headers=auth_header,
        )

    assert resp.status_code == 200
    assert mock_svc.call_args.args[4] == "viewport"
    assert mock_svc.call_args.kwargs == {
        "west": 112.3,
        "south": 37.5,
        "east": 112.8,
        "north": 38.1,
        "zoom": 10,
    }
    assert client.get(
        "/api/user/me/heatmap?detail=tile",
        headers=auth_header,
    ).status_code == 422


# ───────────────────────────────────────────────────────────────────────
# PATCH /api/user/me
# ───────────────────────────────────────────────────────────────────────


def test_patch_me_requires_auth(client):
    resp = client.patch("/api/user/me", json={"city": "beijing"})
    assert resp.status_code == 401


def test_patch_me_invalid_city_too_long_422(client, auth_header):
    """city 超长（> 32 字符）→ 422。

    Sprint 6 task-4 hotfix（Tim 2026-05-17）：city 放宽到任意中文 / 不再限 6 城
    所以 'guangzhou' 现在合法 / 测改成超长边界（> 32 char）→ schema max_length 拦。
    """
    long_city = "山西-太原-小店区" * 10  # > 32 字符
    resp = client.patch("/api/user/me", json={"city": long_city}, headers=auth_header)
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
        "bio": "测试签名",  # Sprint 6 task-1：bio 加入白名单
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
        # Sprint 6 task-2：badges 加入白名单（11 字段）
        "badges": [{"type": "ftp", "label": "FTP 200W"}],
        # ⚠ service 层应该已过滤这些；但即使漏，schema 层不应让它们出去
        "openid": "wx_secret",
        "strava_access_token": "TOKEN_LEAK",
    }
    with patch("app.user.router.service.get_user_profile_for_others", return_value=fake_result):
        resp = client.get("/api/user/42/profile", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()

        # 严格白名单（Sprint 4 codex 异源审 2026-05-06 砍 ftp / P1-4 / Sprint 6 task-1 加 bio / Sprint 6 task-2 加 badges）
        allowed = {"id", "nickname", "avatar_url", "city", "bio", "bike_type",
                   "total_distance_km", "total_elevation_m", "activity_count",
                   "current_month_summary", "badges"}
        assert set(body.keys()) == allowed

        # 敏感字段绝对不应出现（ftp 加入此列：Sprint 4 codex 拍砍 / FTP 是骑手生理数据）
        for forbidden in ("openid", "strava_access_token", "strava_refresh_token",
                          "mute_notifications", "weight", "ftp"):
            assert forbidden not in body, f"敏感字段 {forbidden} 泄漏！"

        # badges 字段透出验证（自他对称）
        assert body["badges"] == [{"type": "ftp", "label": "FTP 200W"}]


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


# ───────────────────────────────────────────────────────────────────────
# Sprint 6 task-1：User.bio 字段
#
# 测试覆盖 8 个关键场景 + 2 个回归断言：
#   1. PATCH /me 写 bio → 200 + DB.bio 写入 + GET /profile 能读出
#   2. PUT /profile 写 bio → 200 + DB.bio 写入 + GET /profile 能读出
#   3. PATCH /me bio 长度 31 → 422
#   4. PUT /profile bio 长度 31 → 422
#   5. PATCH /me bio = null → DB.bio IS NULL
#   6. PATCH /me bio = "" → DB.bio IS NULL（空串归一化）
#   7. PATCH /me bio 含换行 → 422
#   8. GET /api/user/{id}/profile 返 bio（看他人对称）
#   回归 A：GET /api/user/active 不返 bio（防白名单泄漏）
#   回归 B：_PROFILE_RESPONSE_KEYS 长度 = 10（既有 9 + bio）
# ───────────────────────────────────────────────────────────────────────


def test_patch_me_set_bio_success(client, auth_header, test_user, db):
    """PATCH /me 入 bio → 200 + DB 持久化 + GET /profile 能读回。"""
    bio_text = "成都老登 / 公路党 / FTP 220W"
    resp = client.patch("/api/user/me", json={"bio": bio_text}, headers=auth_header)
    assert resp.status_code == 200

    # DB 层验证（防 schema/router 漏接 service）
    db.refresh(test_user)
    assert test_user.bio == bio_text

    # GET /profile 端到端验证
    profile_resp = client.get("/api/user/profile", headers=auth_header)
    assert profile_resp.status_code == 200
    assert profile_resp.json()["bio"] == bio_text


def test_put_profile_set_bio_success(client, auth_header, test_user, db):
    """PUT /profile 入 bio → 200 + DB 持久化 + GET /profile 能读回。"""
    bio_text = "杭州 / 周末长距离"
    resp = client.put("/api/user/profile", json={"bio": bio_text}, headers=auth_header)
    assert resp.status_code == 200

    db.refresh(test_user)
    assert test_user.bio == bio_text

    profile_resp = client.get("/api/user/profile", headers=auth_header)
    assert profile_resp.status_code == 200
    assert profile_resp.json()["bio"] == bio_text


def test_patch_me_bio_too_long_422(client, auth_header):
    """PATCH /me bio = 31 字符 → 422（超过 max_length=30）。"""
    long_bio = "x" * 31
    resp = client.patch("/api/user/me", json={"bio": long_bio}, headers=auth_header)
    assert resp.status_code == 422


def test_put_profile_bio_too_long_422(client, auth_header):
    """PUT /profile bio = 31 字符 → 422。"""
    long_bio = "x" * 31
    resp = client.put("/api/user/profile", json={"bio": long_bio}, headers=auth_header)
    assert resp.status_code == 422


def test_patch_me_bio_null_clears(client, auth_header, test_user, db):
    """PATCH /me bio = null → DB.bio 置 NULL（即使原来有值）。"""
    # 先写一个 bio
    test_user.bio = "原签名"
    db.commit()

    resp = client.patch("/api/user/me", json={"bio": None}, headers=auth_header)
    assert resp.status_code == 200

    db.refresh(test_user)
    assert test_user.bio is None


def test_patch_me_bio_empty_string_normalized_to_null(client, auth_header, test_user, db):
    """PATCH /me bio = '' → DB.bio IS NULL（service_auth 空串归一化）。

    防御目的：避免 DB 同时存在 NULL 和 '' 两种"空"状态污染查询逻辑
    （陷阱 #1 Python truthiness：'' 在 if 判断时都是 False，等价但易混）。
    """
    test_user.bio = "原签名"
    db.commit()

    resp = client.patch("/api/user/me", json={"bio": ""}, headers=auth_header)
    assert resp.status_code == 200

    db.refresh(test_user)
    assert test_user.bio is None  # ← 关键：是 None 不是 ""


def test_patch_me_bio_with_newline_422(client, auth_header):
    """PATCH /me bio 含换行符 → 422（强制单行）。"""
    resp = client.patch(
        "/api/user/me",
        json={"bio": "line1\nline2"},
        headers=auth_header,
    )
    assert resp.status_code == 422


def test_put_profile_bio_with_newline_422(client, auth_header):
    """PUT /profile bio 含换行符 → 422（PUT 入口同 PATCH 守同一规则）。"""
    resp = client.put(
        "/api/user/profile",
        json={"bio": "a\nb"},
        headers=auth_header,
    )
    assert resp.status_code == 422


def test_get_user_profile_for_others_returns_bio(client, auth_header):
    """GET /api/user/{id}/profile 看他人 → bio 出现在响应里（白名单已加 bio）。"""
    fake_result = {
        "id": 42,
        "nickname": "test",
        "avatar_url": None,
        "city": "beijing",
        "bio": "公开签名展示",
        "bike_type": "road",
        "total_distance_km": 100.0,
        "total_elevation_m": 500.0,
        "activity_count": 5,
        "current_month_summary": {
            "distance_km": 30.0,
            "elevation_m": 100.0,
            "avg_power_w": 180.0,
        },
    }
    with patch(
        "app.user.router.service.get_user_profile_for_others",
        return_value=fake_result,
    ):
        resp = client.get("/api/user/42/profile", headers=auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["bio"] == "公开签名展示"
        # 同时验证白名单长度 = 11（task-1 加 bio + task-2 加 badges）
        # Sprint 6 task-2：UserProfileResponse schema 加 badges 默认 [] / 即使 service mock
        # 未塞 badges，Pydantic schema 也会补 [] 进响应——白名单期望必须含 badges。
        allowed = {"id", "nickname", "avatar_url", "city", "bio", "bike_type",
                   "total_distance_km", "total_elevation_m", "activity_count",
                   "current_month_summary", "badges"}
        assert set(body.keys()) == allowed


def test_self_and_others_badges_symmetry(client, auth_header, test_user):
    """Sprint 6 task-2 / D-P08 新增字段强制：self vs others 看到的 badges 字段完全一致。

    场景：CCF 点小明头像看 user 页 / 小明自己也看自己的 profile / 两边 badges 数组完全一样
    （包括顺序 + type + label）。如果有一边偷偷漏算 badges → 信任破裂"为什么我自己看是 3 个
    徽章 / 别人看我变成 0 个？"

    策略：mock get_user_badges 返同一组 fake badges → 断言 GET /profile（self）和
    GET /{id}/profile（others）响应里 badges 字段完全相等。
    """
    fake_badges = [
        {"type": "ftp", "label": "FTP 220W"},
        {"type": "regular_mountain", "label": "雀儿山常客"},
        {"type": "distance", "label": "累计 8000km"},
    ]

    # self 端：mock get_user_by_id + get_user_badges
    with patch("app.user.router.service.get_user_badges", return_value=fake_badges):
        resp_self = client.get("/api/user/profile", headers=auth_header)
        assert resp_self.status_code == 200
        self_badges = resp_self.json()["badges"]

    # others 端：mock get_user_profile_for_others 返含相同 badges 的完整 dict
    fake_others = {
        "id": 999,
        "nickname": "test",
        "avatar_url": None,
        "city": "chengdu",
        "bio": None,
        "bike_type": None,
        "total_distance_km": 0.0,
        "total_elevation_m": 0.0,
        "activity_count": 0,
        "current_month_summary": {"distance_km": 0.0, "elevation_m": 0.0, "avg_power_w": 0.0},
        "badges": fake_badges,
    }
    with patch(
        "app.user.router.service.get_user_profile_for_others",
        return_value=fake_others,
    ):
        resp_others = client.get("/api/user/999/profile", headers=auth_header)
        assert resp_others.status_code == 200
        others_badges = resp_others.json()["badges"]

    # 核心断言：两端 badges 完全相等（顺序 + 内容 / 字段集对称 D-P08 红线）
    assert self_badges == others_badges == fake_badges, (
        f"self vs others badges 不对称 / self={self_badges} / others={others_badges}"
    )


def test_active_users_does_not_leak_bio(client, auth_header):
    """回归 A：/api/user/active 列表项 schema 是 ActiveUserItem（不含 bio）/ 防白名单泄漏。

    bio 应只在 profile 详情（GET /api/user/{id}/profile）/ self profile 里返回，
    列表场景按精简字段返。

    防假阳性：必须 mock service 返非空列表 + 故意塞 bio key 进每个 item
    （模拟"service 不小心加了 bio"的失败场景）→ 确认 Pydantic ActiveUserItem
    schema 严格白名单 / Pydantic 默认 extra='ignore' 把 bio 滤掉。
    历史 v1 写法用真 service 跑 / fixture 空列表让 for 循环不执行 / 断言永不触发。
    """
    leaky_items = [
        {
            "id": 999,
            "nickname": "假泄漏骑友",
            "avatar_url": None,
            "city": "beijing",
            "total_distance_km": 12.3,
            "activity_count": 1,
            "last_activity_at": None,
            "bio": "如果 schema 漏 / 这条 bio 会被返出去",  # 故意塞
        }
    ]
    with patch("app.user.router.service.get_active_users", return_value=leaky_items):
        resp = client.get("/api/user/active", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1, "mock 应保留 1 条 item / 防 fixture 空列表假阳性"
    for item in body["items"]:
        assert "bio" not in item, "ActiveUserItem 不应泄漏 bio 字段！"


def test_profile_response_keys_whitelist_size():
    """回归 B：_PROFILE_RESPONSE_KEYS 长度严格 = 11（既有 9 + Sprint 6 task-1 bio + task-2 badges）。

    锁定 set 长度避免未来手滑用整体重写覆盖 `|=` 追加丢字段。
    """
    from app.user.service_social import _PROFILE_RESPONSE_KEYS
    assert len(_PROFILE_RESPONSE_KEYS) == 11
    assert "bio" in _PROFILE_RESPONSE_KEYS
    assert "badges" in _PROFILE_RESPONSE_KEYS
