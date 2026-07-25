"""
User 模块测试——12 道质检工序。

对应 spec 任务 2.6 的 12 个测试用例，覆盖：
- 微信登录（用例 1-3）
- JWT 认证（用例 4）
- 用户资料（用例 5-8）
- 骑行统计（用例 9-12）

微信接口通过 monkeypatch 模拟，不会真的调用微信服务器。
统计测试通过 activities_data fixture 提前插入测试数据。

注意事项：
- 每个测试函数命名为 test_XX_描述，XX 对应 spec 中的用例编号
- 测试之间互不依赖，顺序无关
- fixture（db、client、auth_header 等）在 conftest.py 中定义
"""


# ==================== 1-3：微信登录 ====================

def test_01_login_new_user(client, monkeypatch):
    """用例 1：合法 code 登录 → token + user_id + is_new_user=true"""

    # 模拟微信接口：收到任何 code 都返回一个固定的 openid
    # monkeypatch 会在测试结束后自动恢复原函数，不影响其他测试
    monkeypatch.setattr(
        "app.user.service.wx_code_to_openid",
        lambda code: "mock_openid_new",
    )

    resp = client.post("/api/user/login", json={"code": "valid_code"})
    assert resp.status_code == 200

    data = resp.json()
    assert "token" in data
    assert "user_id" in data
    assert data["is_new_user"] is True


def test_02_login_existing_user(client, monkeypatch):
    """用例 2：同一 openid 再次登录 → 相同 user_id + is_new_user=false"""

    monkeypatch.setattr(
        "app.user.service.wx_code_to_openid",
        lambda code: "mock_openid_same",
    )

    # 第一次登录：新用户
    resp1 = client.post("/api/user/login", json={"code": "code1"})
    data1 = resp1.json()
    assert data1["is_new_user"] is True

    # 第二次登录：同一个 openid，应该识别为老用户
    resp2 = client.post("/api/user/login", json={"code": "code2"})
    data2 = resp2.json()
    assert data2["is_new_user"] is False
    assert data2["user_id"] == data1["user_id"]


def test_03_login_invalid_code(client, monkeypatch):
    """用例 3：非法 code → 401"""

    # 模拟微信接口返回错误
    def _raise_error(code):
        raise ValueError("code已过期，请重新授权")

    monkeypatch.setattr("app.user.service.wx_code_to_openid", _raise_error)

    resp = client.post("/api/user/login", json={"code": "bad_code"})
    assert resp.status_code == 401


# ==================== 4：JWT 认证 ====================

def test_04_profile_no_token(client):
    """用例 4：无 token 访问 profile → 401"""

    resp = client.get("/api/user/profile")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "未登录"


def test_04_deleted_user_token_is_rejected_by_shared_auth(client, db, auth_header, test_user):
    user_id = test_user.id
    db.delete(test_user)
    db.commit()

    resp = client.get("/api/user/profile", headers=auth_header)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "用户不存在或已注销"
    assert db.query(type(test_user)).filter(type(test_user).id == user_id).first() is None


def test_04_optional_auth_treats_deleted_user_as_anonymous(db, auth_header, test_user):
    from fastapi.security import HTTPAuthorizationCredentials

    from app.dependencies import get_optional_user

    token = auth_header["Authorization"].split(" ", 1)[1]
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    db.delete(test_user)
    db.commit()

    assert get_optional_user(credentials=credentials, db=db) is None


# ==================== 5-8：用户资料 ====================

def test_05_get_profile(client, auth_header):
    """用例 5：合法 token 获取 profile → 200"""

    resp = client.get("/api/user/profile", headers=auth_header)
    assert resp.status_code == 200

    data = resp.json()
    # 新用户的默认值
    assert data["weekly_goal"] == 200.0
    assert data["nickname"] is None
    assert data["ftp"] is None
    assert data["birth_year"] is None
    assert data["max_hr"] is None


def test_06_update_ftp_out_of_range(client, auth_header):
    """用例 6：更新 ftp=600（越界）→ 422"""

    # spec 规定 ftp 范围 50-500，600 超出上限
    resp = client.put(
        "/api/user/profile",
        json={"ftp": 600},
        headers=auth_header,
    )
    assert resp.status_code == 422


def test_07_update_invalid_bike_type(client, auth_header):
    """用例 7：更新 bike_type="car" → 422"""

    # spec 只允许 road / gravel / mtb，car 不合法
    resp = client.put(
        "/api/user/profile",
        json={"bike_type": "car"},
        headers=auth_header,
    )
    assert resp.status_code == 422


def test_08_update_profile_success(client, auth_header, monkeypatch):
    """用例 8：正常更新 profile → 200

    Sprint 9 task-4：首次填 ftp 会触发 enqueue_backfill_ftp（默认 user.ftp=NULL）。
    测试环境没起 Redis / 必须 mock 掉 enqueue 调用 / 避免 ConnectionError 401。
    """
    # Sprint 9 task-4：mock 掉 RQ enqueue（router 直接 import enqueue_backfill_ftp）
    monkeypatch.setattr(
        "app.user.router.enqueue_backfill_ftp", lambda *a, **kw: None
    )

    resp = client.put(
        "/api/user/profile",
        json={
            "nickname": "骑行者Tim",
            "ftp": 200,
            "weight": 70.5,
            "birth_year": 1994,
            "max_hr": 190,
            "bike_type": "road",
            "weekly_goal": 300.0,
        },
        headers=auth_header,
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["nickname"] == "骑行者Tim"
    assert data["ftp"] == 200
    assert data["weight"] == 70.5
    assert data["birth_year"] == 1994
    assert data["max_hr"] == 190
    assert data["bike_type"] == "road"
    assert data["weekly_goal"] == 300.0


def test_08b_update_profile_rejects_future_birth_year(client, auth_header):
    """补充用例：出生年份不能写未来年份。"""

    resp = client.put(
        "/api/user/profile",
        json={"birth_year": 2999},
        headers=auth_header,
    )
    assert resp.status_code == 422


def test_08c_update_profile_rejects_invalid_max_hr(client, auth_header):
    """补充用例：最大心率只接受成人骑行常见安全区间。"""

    resp = client.put(
        "/api/user/profile",
        json={"max_hr": 260},
        headers=auth_header,
    )
    assert resp.status_code == 422


# ==================== 9-12：骑行统计 ====================

def test_09_stats_no_rides(client, auth_header):
    """用例 9：获取统计（无骑行记录）→ 全部为 0"""

    resp = client.get("/api/user/stats", headers=auth_header)
    assert resp.status_code == 200

    data = resp.json()
    assert data["period"] == "week"
    assert data["distance"] == 0.0
    assert data["rides"] == 0
    assert data["elevation_gain"] == 0.0
    assert data["duration"] == 0
    assert data["weekly_goal"] == 200.0
    assert data["goal_percent"] == 0


def test_10_stats_with_rides(client, auth_header, activities_data):
    """用例 10：获取统计（有记录）→ 正确聚合值"""

    resp = client.get("/api/user/stats?period=week", headers=auth_header)
    assert resp.status_code == 200

    data = resp.json()
    expected = activities_data

    assert data["period"] == "week"
    assert data["distance"] == expected["total_distance_km"]    # 80.0 km
    assert data["rides"] == expected["total_rides"]              # 2 次
    assert data["elevation_gain"] == expected["total_elevation"]  # 800.0 m
    assert data["duration"] == expected["total_duration"]         # 6300 秒

    # goal_percent = 80.0 / 200.0 * 100 = 40
    assert data["goal_percent"] == 40


def test_11_stats_period_month(client, auth_header, activities_data, last_month_activity):
    """用例 11：period=month → 只统计本月数据"""

    # activities_data 插入的记录都在本周（也在本月）
    # last_month_activity 插入的记录在上个月
    # period=month 应该只算本月的，不算上个月的
    resp = client.get("/api/user/stats?period=month", headers=auth_header)
    assert resp.status_code == 200

    data = resp.json()
    expected = activities_data

    assert data["period"] == "month"
    # 应该只有本月的 2 条 completed 记录（和本周相同，因为本周在本月内）
    assert data["distance"] == expected["total_distance_km"]
    assert data["rides"] == expected["total_rides"]


def test_12_stats_invalid_period(client, auth_header):
    """用例 12：period 参数非法 → 422"""

    resp = client.get("/api/user/stats?period=decade", headers=auth_header)
    assert resp.status_code == 422
