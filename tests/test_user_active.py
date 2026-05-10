"""
探索 tab 骑友 section endpoint 单测（Sprint 5 task-3）。

跑真 SQLite session / 测 service 层 SQL + endpoint 行为。
覆盖：
- 默认 limit + 排序
- 排除自己 / 排除 admin / 排除无活动用户 / 排除 duplicate
- limit 参数边界（>50 / <1 兜底）
- endpoint auth + response shape
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.user.service import get_active_users, create_token
from app.user.models import User
from tests.conftest import _activities_table


def _insert_activity(
    db, user_id: int, *,
    started_at: datetime,
    distance: float = 8000,
    duration: int = 1500,
    status: str = "completed",
    duplicate_of: int | None = None,
):
    """fixture helper：插一条 activity / 不带 simplified_track（不影响 active 查询）。"""
    db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status=status,
            distance=distance,
            duration=duration,
            started_at=started_at,
            duplicate_of=duplicate_of,
        )
    )
    db.commit()


def test_active_users_returns_users_with_activity(db, test_user):
    """user 有 completed activity → 出现在 active 列表。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    # 别的 user（这个 user 才会被列）
    other = User(openid="other1", is_admin=False, nickname="OtherRider")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_activity(db, other.id, started_at=base)

    result = get_active_users(db, exclude_user_id=test_user.id, limit=10)

    assert len(result) == 1
    assert result[0]["id"] == other.id
    assert result[0]["nickname"] == "OtherRider"
    assert result[0]["activity_count"] == 1
    assert result[0]["total_distance_km"] == 8.0  # 8000m / 1000


def test_excludes_self(db, test_user):
    """当前登录用户自己不出现在自己的 active 列表。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    _insert_activity(db, test_user.id, started_at=base)

    result = get_active_users(db, exclude_user_id=test_user.id, limit=10)

    assert len(result) == 0  # 自己被排除


def test_excludes_admin(db, test_user, admin_user):
    """admin 用户不出现在 active 列表（即使有活动）。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    _insert_activity(db, admin_user.id, started_at=base)

    result = get_active_users(db, exclude_user_id=test_user.id, limit=10)

    assert len(result) == 0  # admin 被排除


def test_excludes_users_without_activity(db, test_user):
    """无任何 completed activity 的用户不出现（INNER JOIN 自动过滤）。"""
    no_activity_user = User(openid="no_act", is_admin=False, nickname="NoActivityUser")
    db.add(no_activity_user)
    db.commit()

    result = get_active_users(db, exclude_user_id=test_user.id, limit=10)

    assert len(result) == 0


def test_excludes_duplicate_activities_from_count(db, test_user):
    """duplicate 活动不计入 activity_count / 跟其他列表查询一致（task-2 dedupe）。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    other = User(openid="other2", is_admin=False, nickname="DupRider")
    db.add(other)
    db.commit()
    db.refresh(other)

    # 插 1 主活动 + 1 duplicate
    _insert_activity(db, other.id, started_at=base, distance=10000)
    _insert_activity(
        db, other.id,
        started_at=base + timedelta(seconds=15),
        distance=10000,
        duplicate_of=1,  # 标 duplicate
    )

    result = get_active_users(db, exclude_user_id=test_user.id, limit=10)

    assert len(result) == 1
    assert result[0]["activity_count"] == 1, "duplicate 不计入"
    assert result[0]["total_distance_km"] == 10.0, "distance 也不双计"


def test_orders_by_last_activity_desc(db, test_user):
    """多个活跃 user → 按最近骑车时间倒序。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    # 3 个用户 / 不同最近骑车时间
    u1 = User(openid="u1", is_admin=False, nickname="OldestRider")
    u2 = User(openid="u2", is_admin=False, nickname="MiddleRider")
    u3 = User(openid="u3", is_admin=False, nickname="NewestRider")
    db.add_all([u1, u2, u3])
    db.commit()
    db.refresh(u1); db.refresh(u2); db.refresh(u3)

    _insert_activity(db, u1.id, started_at=base - timedelta(days=10))  # 最早
    _insert_activity(db, u2.id, started_at=base - timedelta(days=3))
    _insert_activity(db, u3.id, started_at=base)  # 最近

    result = get_active_users(db, exclude_user_id=test_user.id, limit=10)

    assert [r["nickname"] for r in result] == ["NewestRider", "MiddleRider", "OldestRider"]


def test_limit_parameter_respected(db, test_user):
    """limit=2 → 最多返 2 个 user。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        u = User(openid=f"u{i}", is_admin=False, nickname=f"Rider{i}")
        db.add(u)
        db.commit()
        db.refresh(u)
        _insert_activity(db, u.id, started_at=base - timedelta(days=i))

    result = get_active_users(db, exclude_user_id=test_user.id, limit=2)

    assert len(result) == 2


def test_endpoint_returns_response(client, auth_header, db, test_user):
    """endpoint /api/user/active 真返回 200 + items 字段。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    other = User(openid="endpoint_other", is_admin=False, nickname="EndpointRider")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_activity(db, other.id, started_at=base)

    r = client.get("/api/user/active", headers=auth_header)

    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert len(body["items"]) == 1
    assert body["items"][0]["nickname"] == "EndpointRider"


def test_endpoint_requires_auth(client):
    """无 token → 401。"""
    r = client.get("/api/user/active")
    assert r.status_code == 401


def test_endpoint_limit_zero_falls_back_to_default(client, auth_header, db, test_user):
    """?limit=0 → endpoint 兜底 reset 为 default 10（防御性）/ 仍返 200 不 422（codex Nice 抓的边界）。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    other = User(openid="limit_zero_other", is_admin=False, nickname="Rider")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_activity(db, other.id, started_at=base)

    r = client.get("/api/user/active?limit=0", headers=auth_header)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1  # 默认 10 / 这里只有 1 条数据 / 1 个返回


def test_search_filters_by_nickname(db, test_user):
    """search 参数按 nickname ILIKE 过滤 / 不区分大小写。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    u1 = User(openid="u1_search", is_admin=False, nickname="Alice")
    u2 = User(openid="u2_search", is_admin=False, nickname="Bob")
    u3 = User(openid="u3_search", is_admin=False, nickname="aliceWonder")
    db.add_all([u1, u2, u3])
    db.commit()
    db.refresh(u1); db.refresh(u2); db.refresh(u3)
    _insert_activity(db, u1.id, started_at=base)
    _insert_activity(db, u2.id, started_at=base)
    _insert_activity(db, u3.id, started_at=base)

    # 大小写不敏感 / 模糊匹配
    result = get_active_users(db, exclude_user_id=test_user.id, search="alice")

    nicknames = sorted(r["nickname"] for r in result)
    assert nicknames == ["Alice", "aliceWonder"]


def test_search_empty_returns_all(db, test_user):
    """search=None 或空字符串 → 不过滤 / 返全部活跃用户。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    other = User(openid="other_empty_search", is_admin=False, nickname="Xyz")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_activity(db, other.id, started_at=base)

    # search=None
    assert len(get_active_users(db, exclude_user_id=test_user.id, search=None)) == 1
    # search="" (空字符串 / 走 falsy 分支)
    assert len(get_active_users(db, exclude_user_id=test_user.id, search="")) == 1


def test_endpoint_q_param_returns_filtered(client, auth_header, db, test_user):
    """endpoint /api/user/active?q=xxx 真过滤 + 200。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    matched = User(openid="ep_match", is_admin=False, nickname="MatchedUser")
    not_matched = User(openid="ep_no_match", is_admin=False, nickname="OtherName")
    db.add_all([matched, not_matched])
    db.commit()
    db.refresh(matched); db.refresh(not_matched)
    _insert_activity(db, matched.id, started_at=base)
    _insert_activity(db, not_matched.id, started_at=base)

    r = client.get("/api/user/active?q=match", headers=auth_header)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["nickname"] == "MatchedUser"


def test_endpoint_q_too_long_falls_back_to_no_filter(client, auth_header, db, test_user):
    """?q=<65 字以上> → 当无搜索（防恶意大 string）/ 返全部。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    other = User(openid="long_q_other", is_admin=False, nickname="ShortName")
    db.add(other)
    db.commit()
    db.refresh(other)
    _insert_activity(db, other.id, started_at=base)

    long_q = "x" * 100  # 100 字超过 64 字上限
    r = client.get(f"/api/user/active?q={long_q}", headers=auth_header)
    assert r.status_code == 200
    # 长 q 被 reset 为 None / 返所有活跃用户（这里 1 个）
    assert len(r.json()["items"]) == 1


def test_endpoint_limit_above_50_falls_back_to_default(client, auth_header, db, test_user):
    """?limit=51 → endpoint 兜底 reset 为 default 10（防恶意大 limit 拖 DB）。"""
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    # 插 12 个用户每个 1 活动
    for i in range(12):
        u = User(openid=f"big_u{i}", is_admin=False, nickname=f"Rider{i}")
        db.add(u)
        db.commit()
        db.refresh(u)
        _insert_activity(db, u.id, started_at=base - timedelta(days=i))

    r = client.get("/api/user/active?limit=51", headers=auth_header)
    assert r.status_code == 200
    # 51 > 50 → reset 10 / 12 候选只返 10
    assert len(r.json()["items"]) == 10
