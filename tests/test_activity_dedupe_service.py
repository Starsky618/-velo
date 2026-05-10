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


def test_finds_duplicate_marks_new(db, test_user):
    """
    new 跟 existing 4 维匹配 → 永远 new 标 duplicate_of=existing（修法 A：旧的为主 / 不比 score）。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    existing_id = _insert_activity(db, test_user.id, started_at=base_at)
    new_id = _insert_activity(db, test_user.id, started_at=base_at + timedelta(seconds=15))
    new = _get_activity_via_orm(db, new_id)

    result = find_and_mark_duplicate(db, new)

    # new 标 duplicate / 不管 new 数据是否更全 / existing 始终是主
    assert new.duplicate_of == existing_id
    assert result == new_id


def test_new_with_more_data_still_marked_as_duplicate(db, test_user):
    """
    new 数据更全（带功率心率）也标 new duplicate / 旧的不让位（修法 A 关键 trade-off / 验证语义）。
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

    find_and_mark_duplicate(db, new)

    # 即使 new 带功率心率 / 仍标 new duplicate / existing 不让位
    assert new.duplicate_of == existing_id
    existing = _get_activity_via_orm(db, existing_id)
    assert existing.duplicate_of is None  # existing 不被标


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


def test_existing_efforts_not_migrated(db, test_user):
    """
    修法 A 验证：existing 已有 efforts → new 标 duplicate 时 efforts 仍属于 existing（不迁移 / 不动）。
    防误改：避免未来有人重新引入"new 胜出迁移"的复杂路径。
    """
    base_at = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    existing_id = _insert_activity(db, test_user.id, started_at=base_at)
    # 即使 new 数据更全
    new_id = _insert_activity(
        db, test_user.id,
        started_at=base_at + timedelta(seconds=15),
        avg_power=200, avg_hr=150, track_count=400,
    )
    from tests.conftest import _segment_efforts_table
    db.execute(
        _segment_efforts_table.insert().values(
            segment_id=1, activity_id=existing_id, user_id=test_user.id,
            elapsed_time=600, avg_speed=20.0, start_index=0, end_index=50,
        )
    )
    db.commit()

    new = _get_activity_via_orm(db, new_id)
    find_and_mark_duplicate(db, new)
    db.commit()

    # effort 仍属 existing / 没被迁移
    from app.segment.models import SegmentEffort
    effort = db.query(SegmentEffort).filter_by(segment_id=1).first()
    assert effort.activity_id == existing_id, "修法 A 不迁移 efforts / 跟 worker.py 守卫一致"


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
