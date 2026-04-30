"""
v5 task-1.A.3：segment router 扩展 + 即时反馈 endpoint 的 HTTP 层测试。

这一层验证 router 自己的契约（Query 校验 / 公开访问 / 401 / 404 / response 字段），
不重复测 service 层逻辑（已在 test_segment_service_v5.py + test_segment_concurrency.py）。

类比：service 层是后厨，router 层是前台；这里只验前台分单/校验/翻译错误码做对了，
菜本身味道由后厨测试负责。
"""

from datetime import datetime, timezone

import pytest

from app.segment.models import Segment, SegmentEffort
from app.activity.models import Activity


UTC = timezone.utc


# ========== GET /api/segments：Query 校验 + 公开访问 ==========

def test_list_segments_anonymous_access(client):
    """
    赛段目录公开（PRD §B-P02 / 第二轮双审 B1-B3）——不带 token 也能访问 200。
    """
    res = client.get("/api/segments")
    assert res.status_code == 200
    body = res.json()
    assert "items" in body and "total" in body


def test_list_segments_search_too_short_returns_422(client):
    """search 必须 ≥ 2 字（防 a/b 单字误触发模糊搜索全表扫）。"""
    res = client.get("/api/segments?search=a")
    assert res.status_code == 422


def test_list_segments_invalid_city_returns_422(client):
    """city 必须是 7 枚举之一（脏值挡在 router 层防进入 SQL）。"""
    res = client.get("/api/segments?city=unknown_city")
    assert res.status_code == 422


def test_list_segments_invalid_difficulty_returns_422(client):
    """difficulty 必须是 4 枚举之一。"""
    res = client.get("/api/segments?difficulty=hellish")
    assert res.status_code == 422


def test_list_segments_valid_filters_returns_200(client):
    """合法的 search + city + difficulty 三筛选叠加应通过校验进入 service。"""
    res = client.get(
        "/api/segments?search=测试&city=beijing&difficulty=hard"
    )
    assert res.status_code == 200


def test_list_segments_paired_near_coords_required(client):
    """near_lat / near_lon 必须成对（沿用现有契约）。"""
    res = client.get("/api/segments?near_lat=39.9")
    assert res.status_code == 400


# ========== GET /api/segments/{id}：v5 字段补全 ==========

def test_get_segment_detail_includes_v5_fields(client, db):
    """
    详情 endpoint 响应应含 task-1.A.3 新增 4 字段（max_gradient/city/difficulty/avg_gradient）。

    SQLite 不支持 PostGIS，conftest.py 已 mock 了 reference_line 列；
    本测试用最小化 segment 行验字段路径打通即可，service 内部 SQL 由真 PG 集成测试覆盖。
    """
    seg = Segment(
        name="v5 字段测试段",
        distance=3000.0,
        elevation_gain=120.0,
        avg_gradient=4.0,
        max_gradient=8.5,
        difficulty="hard",
        city="beijing",
        start_lat=39.9, start_lon=116.4,
        end_lat=39.95, end_lon=116.42,
        reference_line="SRID=4326;LINESTRING(116.4 39.9, 116.42 39.95)",
        match_tolerance=50.0,
        min_match_ratio=0.8,
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    res = client.get(f"/api/segments/{seg.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["max_gradient"] == 8.5
    assert body["city"] == "beijing"
    assert body["difficulty"] == "hard"
    assert body["avg_gradient"] == 4.0


def test_get_segment_detail_404(client):
    """不存在的 segment_id → 404。"""
    res = client.get("/api/segments/99999")
    assert res.status_code == 404


# ========== GET /api/segments/{id}/efforts/me：即时反馈 ==========

def test_get_my_effort_compare_no_auth_returns_401(client):
    """未登录 → 401（即时反馈是看自己的，必须登录）。"""
    res = client.get("/api/segments/1/efforts/me")
    assert res.status_code == 401


def test_get_my_effort_compare_segment_not_exist_returns_404(client, auth_header):
    """登录用户访问不存在的 segment → router 层显式 404（spec §3.2.1 第二轮双审 B1-B4）。"""
    res = client.get("/api/segments/99999/efforts/me", headers=auth_header)
    assert res.status_code == 404


def test_get_my_effort_compare_first_attempt_returns_six_field_fallback(
    client, db, auth_header, test_user,
):
    """
    用户在某赛段没留 effort（首次访问该赛段）→ 6 字段兜底。

    spec §3.2.1：service 不抛 404，无 effort 时返 is_first_attempt=True / 其他 None。
    """
    seg = Segment(
        name="首次访问测试段",
        distance=2000.0,
        elevation_gain=50.0,
        avg_gradient=2.5,
        difficulty="medium",
        city="beijing",
        start_lat=39.9, start_lon=116.4,
        end_lat=39.92, end_lon=116.41,
        reference_line="SRID=4326;LINESTRING(116.4 39.9, 116.41 39.92)",
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    res = client.get(f"/api/segments/{seg.id}/efforts/me", headers=auth_header)
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "current_attempt_elapsed_time": None,
        "last_attempt_elapsed_time": None,
        "pr_elapsed_time": None,
        "current_attempt_diff_to_last": None,
        "current_attempt_is_pr": False,
        "is_first_attempt": True,
    }


def test_get_my_effort_compare_pr_attempt_returns_six_fields(
    client, db, auth_header, test_user,
):
    """
    用户在赛段留过 2 条 effort（按 Activity.started_at 排序：current=后骑 / last=早骑）→
    6 字段都有值，is_pr=True（current.elapsed_time == MIN）/ diff = last - current = +200。
    """
    seg = Segment(
        name="PR 对比测试段",
        distance=2500.0,
        elevation_gain=80.0,
        avg_gradient=3.2,
        difficulty="hard",
        city="beijing",
        start_lat=39.9, start_lon=116.4,
        end_lat=39.95, end_lon=116.43,
        reference_line="SRID=4326;LINESTRING(116.4 39.9, 116.43 39.95)",
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    early_started = datetime(2026, 4, 10, 9, 0, tzinfo=UTC)
    late_started = datetime(2026, 4, 20, 9, 0, tzinfo=UTC)
    early_act = Activity(
        user_id=test_user.id, status="completed",
        distance=3000.0, duration=1500,
        started_at=early_started, finished_at=early_started,
        data_source="gpx", activity_type="cycling",
    )
    late_act = Activity(
        user_id=test_user.id, status="completed",
        distance=3000.0, duration=1500,
        started_at=late_started, finished_at=late_started,
        data_source="gpx", activity_type="cycling",
    )
    db.add_all([early_act, late_act])
    db.commit()
    db.refresh(early_act)
    db.refresh(late_act)

    db.add_all([
        SegmentEffort(
            segment_id=seg.id, activity_id=early_act.id, user_id=test_user.id,
            elapsed_time=1300, start_index=0, end_index=10,
        ),
        SegmentEffort(
            segment_id=seg.id, activity_id=late_act.id, user_id=test_user.id,
            elapsed_time=1100, start_index=0, end_index=10,
        ),
    ])
    db.commit()

    res = client.get(f"/api/segments/{seg.id}/efforts/me", headers=auth_header)
    assert res.status_code == 200
    body = res.json()
    assert body["current_attempt_elapsed_time"] == 1100   # 后骑（started_at 最新）
    assert body["last_attempt_elapsed_time"] == 1300      # 早骑
    assert body["pr_elapsed_time"] == 1100                # MIN
    assert body["current_attempt_diff_to_last"] == 200    # 1300 - 1100
    assert body["current_attempt_is_pr"] is True
    assert body["is_first_attempt"] is False
