"""
GPX dedupe service 集成测试（Sprint 5 task-2 / Day 1）。

跑真 SQLite session / 测 service 层 DB 查询 + 标记逻辑。
覆盖：
- 没找到 candidate → 不标
- 找到重复 / new score 高 → existing 标 duplicate
- 找到重复 / new score 低 → new 标 duplicate
- 已标 duplicate 的 candidate 不参与（链式判断防御）
- 时间窗外的 candidate 不参与（性能 + 正确性）
- 不同 user 的 candidate 不参与（防跨用户误判）
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.activity.dedupe_service import find_and_mark_duplicate
from app.activity.models import Activity
from tests.conftest import _activities_table


def _insert_activity(
    db,
    user_id: int,
    *,
    started_at: datetime,
    distance: float = 8000,
    duration: int = 1500,
    status: str = "completed",
    avg_power: float | None = None,
    avg_hr: float | None = None,
    avg_cadence: float | None = None,
    track_first_lat: float = 37.85,
    track_first_lon: float = 112.55,
    track_count: int = 100,
    duplicate_of: int | None = None,
) -> int:
    """fixture helper：插一条 activity 返回 id。"""
    # 模拟 simplified_track（首点决定起点 / 长度决定 score）
    track = [{"lat": track_first_lat, "lon": track_first_lon, "ele": 800}] + [
        {"lat": track_first_lat + 0.001 * i, "lon": track_first_lon + 0.001 * i, "ele": 810 + i}
        for i in range(track_count - 1)
    ]
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            status=status,
            distance=distance,
            duration=duration,
            avg_power=avg_power,
            avg_hr=avg_hr,
            avg_cadence=avg_cadence,
            started_at=started_at,
            simplified_track=json.dumps(track),
            duplicate_of=duplicate_of,
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _get_activity_via_orm(db, activity_id: int) -> Activity:
    """用 ORM 查 / 注意 conftest 把 simplified_track 存为 Text，需要解析为 list。"""
    a = db.query(Activity).filter_by(id=activity_id).first()
    # SQLite fixture 把 JSONB 存为 Text → 手动 json.loads
    if a and isinstance(a.simplified_track, str):
        a.simplified_track = json.loads(a.simplified_track)
    return a


def test_no_candidates_returns_none(db, test_user):
    """user 只有一条 activity → 没 candidate → 不标。"""
    new_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    new_id = _insert_activity(db, test_user.id, started_at=new_at)
    new = _get_activity_via_orm(db, new_id)

    result = find_and_mark_duplicate(db, new)

    assert result is None
    assert new.duplicate_of is None


def test_existing_higher_score_marks_new(db, test_user):
    """
    existing 数据全（带功率心率）/ new 只轨迹 → new 标 duplicate_of=existing。
    模拟真实场景：先 Strava 同步了带传感器版本，用户后传 GPX 简化版。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    # existing：Strava 同步 / 带功率心率 / 4000 点
    existing_id = _insert_activity(
        db, test_user.id,
        started_at=base_at,
        avg_power=200, avg_hr=150, avg_cadence=88,
        track_count=400,  # SQLite Text 存 4000 点会大 / 100 量级足够分高低
    )
    # new：纯 GPX / 无传感器 / 100 点 / 4 维全在容差内（同时间 / 同距离 / 同时长 / 同起点）
    new_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=15),
        track_count=100,
    )
    new = _get_activity_via_orm(db, new_id)

    result = find_and_mark_duplicate(db, new)

    # new 标 duplicate（new 数据 < existing）
    assert new.duplicate_of == existing_id
    assert result == new_id


def test_new_higher_score_marks_existing(db, test_user):
    """
    new 数据全 / existing 旧的简化版 → existing 标 duplicate_of=new。
    模拟：先用户传简化 GPX，后 Strava 同步带传感器全数据。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    existing_id = _insert_activity(db, test_user.id, started_at=base_at, track_count=100)
    new_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=15),
        avg_power=200, avg_hr=150, avg_cadence=88,
        track_count=400,
    )
    new = _get_activity_via_orm(db, new_id)

    result = find_and_mark_duplicate(db, new)

    # existing 标 duplicate（new 数据 > existing）
    assert result == existing_id
    existing = _get_activity_via_orm(db, existing_id)
    assert existing.duplicate_of == new_id
    assert new.duplicate_of is None


def test_already_duplicate_candidate_skipped(db, test_user):
    """
    DB 里有 A / B / C：B 已标 duplicate_of=A → 新来的 D 跟 B 时空匹配但不应跟 B 比 / 应跟 A 比。
    防链式判断：避免 "A↔B↔C" 三方互标的复杂关系。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    a_id = _insert_activity(db, test_user.id, started_at=base_at)
    # B 已标 duplicate_of=A
    b_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=20),
        duplicate_of=a_id,
    )
    d_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=30),
    )
    d = _get_activity_via_orm(db, d_id)

    result = find_and_mark_duplicate(db, d)

    # D 应跟 A 比（B 被过滤掉）/ 标 duplicate_of=A
    assert d.duplicate_of == a_id
    assert result == d_id


def test_outside_time_window_no_match(db, test_user):
    """
    candidate 起骑时间超 ± 5min 窗 → 不参与 dedupe。
    防性能：100 用户 × N 历史活动 / 时间窗预筛是关键 index。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    # existing 10 分钟前（超出 ± 5min 窗）
    _insert_activity(db, test_user.id, started_at=base_at - timedelta(minutes=10))
    new_id = _insert_activity(db, test_user.id, started_at=base_at)
    new = _get_activity_via_orm(db, new_id)

    result = find_and_mark_duplicate(db, new)

    # 时间窗外 / 不匹配 / new 不被标
    assert result is None
    assert new.duplicate_of is None


def test_different_user_not_match(db, test_user, admin_user):
    """
    两 user 同时间起骑同地点 → 不同人 / 不应误判。
    防跨用户：两朋友同时太原市区起骑 / 后端不应认为其中一个是另一个的 duplicate。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    _insert_activity(db, admin_user.id, started_at=base_at)  # 别的 user
    new_id = _insert_activity(db, test_user.id, started_at=base_at + timedelta(seconds=15))
    new = _get_activity_via_orm(db, new_id)

    result = find_and_mark_duplicate(db, new)

    # 不同 user / 不参与 dedupe / new 不被标
    assert result is None
    assert new.duplicate_of is None


def test_new_higher_score_migrates_efforts_to_new(db, test_user):
    """
    new 胜出场景 + existing 已有 SegmentEffort → 应迁移到 new（防 segment 排行榜双计 / Critical 修）。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    existing_id = _insert_activity(db, test_user.id, started_at=base_at, track_count=100)
    new_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=15),
        avg_power=200, avg_hr=150, avg_cadence=88,
        track_count=400,
    )
    # 给 existing 插一条 SegmentEffort（模拟 v0 期已 segment 匹配）
    from tests.conftest import _segment_efforts_table
    db.execute(
        _segment_efforts_table.insert().values(
            segment_id=1,
            activity_id=existing_id,
            user_id=test_user.id,
            elapsed_time=600,
            avg_speed=20.0,
            start_index=0,
            end_index=50,
        )
    )
    db.commit()

    new = _get_activity_via_orm(db, new_id)
    find_and_mark_duplicate(db, new)
    db.commit()

    # SegmentEffort.activity_id 应迁移到 new（不再属于 existing / 防排行榜双计）
    from app.segment.models import SegmentEffort
    effort = db.query(SegmentEffort).filter_by(segment_id=1).first()
    assert effort is not None
    assert effort.activity_id == new_id, "效率 effort 应迁移到 new / 防排行榜双计"


def test_new_higher_score_migrates_notifications_to_new(db, test_user):
    """
    new 胜出 + existing 已有 Notification → 迁移到 new（防通知跳转链指向已隐藏的 existing）。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    existing_id = _insert_activity(db, test_user.id, started_at=base_at, track_count=100)
    new_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=15),
        avg_power=200, avg_hr=150, avg_cadence=88,
        track_count=400,
    )
    # 给 existing 插一条 Notification（模拟 v3 期已 PR 触发）
    from tests.conftest import _notifications_table
    db.execute(
        _notifications_table.insert().values(
            user_id=test_user.id,
            event_type="pr",
            segment_id=1,
            activity_id=existing_id,
            elapsed_time=600,
            rank=1,
            expires_at=base_at + timedelta(days=30),
            created_at=base_at,
        )
    )
    db.commit()

    new = _get_activity_via_orm(db, new_id)
    find_and_mark_duplicate(db, new)
    db.commit()

    from app.notification.models import Notification
    notif = db.query(Notification).filter_by(event_type="pr").first()
    assert notif is not None
    assert notif.activity_id == new_id, "通知应迁移到 new / 防跳转链指向已隐藏 existing"


def test_advisory_lock_skipped_on_sqlite(db, test_user):
    """
    SQLite fixture 不支持 pg_advisory_xact_lock → dedupe_service 内 dialect 守卫应跳过 / 不报 OperationalError。
    生产 PG 环境下会真加锁（无法在单测里直接验证 / 留 prod verify）。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    new_id = _insert_activity(db, test_user.id, started_at=base_at)
    new = _get_activity_via_orm(db, new_id)
    # 不应抛 OperationalError（如果 dialect 守卫漏写 / SQLite 跑 pg_advisory_xact_lock 会爆）
    result = find_and_mark_duplicate(db, new)
    assert result is None  # 没 candidate / 正常返 None / dialect 守卫真生效


def test_missing_simplified_track_returns_none(db, test_user):
    """new 缺 simplified_track（解析失败 / 早期数据）→ 跳过 dedupe / 不报错。"""
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    # 直接插入 / 不通过 helper（避开 simplified_track 默认）
    result_insert = db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            status="completed",
            distance=8000,
            duration=1500,
            started_at=base_at,
            simplified_track=None,
        )
    )
    db.commit()
    new_id = result_insert.inserted_primary_key[0]
    new = db.query(Activity).filter_by(id=new_id).first()

    result = find_and_mark_duplicate(db, new)

    assert result is None
    assert new.duplicate_of is None
