"""
v5 task-1.A.2：赛段 service 扩展的单元测试。

这些测试尽量用 mock / 假查询对象隔离数据库，像用纸面沙盘推演 service 逻辑：
只验证过滤条件、排序意图、异常分支和返回结构，不依赖真 PostgreSQL。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.segment import service
from app.segment.exceptions import InvalidSegmentRangeError, SegmentOverlapError


class _FakeQuery:
    """极简 SQLAlchemy Query 替身：记录调用链，返回预置 scalar/all/first。"""

    def __init__(self, scalar_value=None, all_value=None, first_value=None):
        self.scalar_value = scalar_value
        self.all_value = all_value if all_value is not None else []
        self.first_value = first_value
        self.filters = []
        self.order_args = []

    def filter(self, *args):
        self.filters.extend(args)
        return self

    def filter_by(self, **kwargs):
        self.filters.append(kwargs)
        return self

    def outerjoin(self, *args):
        return self

    def join(self, *args):
        return self

    def group_by(self, *args):
        return self

    def order_by(self, *args):
        self.order_args.extend(args)
        return self

    def offset(self, *args):
        return self

    def limit(self, *args):
        return self

    def scalar(self):
        return self.scalar_value

    def all(self):
        return self.all_value

    def first(self):
        return self.first_value


def _fake_segment(**overrides):
    base = {
        "id": 1,
        "name": "太行测试坡",
        "distance": 1234.0,
        "elevation_gain": 88.0,
        "start_lat": 37.8,
        "start_lon": 112.5,
        "end_lat": 37.9,
        "end_lon": 112.6,
        "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _run_segment_list(**kwargs):
    count_query = _FakeQuery(scalar_value=1)
    list_query = _FakeQuery(all_value=[(_fake_segment(), 3)])
    db = MagicMock()
    db.query.side_effect = [count_query, list_query]

    result = service.get_segment_list(db, **kwargs)
    return result, count_query, list_query


def test_get_segment_list_search_filter():
    """search 应转成 Segment.name.ilike 模糊搜索条件。"""
    _, count_query, list_query = _run_segment_list(search="太行")

    rendered = " ".join(str(f) for f in count_query.filters + list_query.filters)
    assert "lower(segments.name)" in rendered
    assert "LIKE" in rendered


def test_get_segment_list_city_filter():
    """city 应作为精确等值过滤条件叠到 count/list 两条查询上。"""
    _, count_query, list_query = _run_segment_list(city="taiyuan")

    rendered = " ".join(str(f) for f in count_query.filters + list_query.filters)
    assert "segments.city" in rendered


def test_get_segment_list_difficulty_filter():
    """difficulty 应作为精确等值过滤条件叠到 count/list 两条查询上。"""
    _, count_query, list_query = _run_segment_list(difficulty="hard")

    rendered = " ".join(str(f) for f in count_query.filters + list_query.filters)
    assert "segments.difficulty" in rendered


def test_get_segment_list_returns_tuple_with_entries():
    """列表仍返回 tuple[list[dict], int]，且每个 item 保留 entries 字段。"""
    result, _, _ = _run_segment_list()

    items, total = result
    assert isinstance(items, list)
    assert total == 1
    assert items[0]["entries"] == 3
    assert items[0]["distance"] == 1.23


def test_get_my_effort_with_compare_no_effort():
    """用户没骑过该赛段时，个人字段为 None，但 total_riders 仍返回真实人数。"""
    total_query = _FakeQuery(scalar_value=2)
    my_query = _FakeQuery(all_value=[])
    db = MagicMock()
    db.query.side_effect = [total_query, my_query]

    result = service.get_my_effort_with_compare(db, segment_id=1, user_id=2)

    assert result == {
        "my_best": None,
        "my_latest": None,
        "rank": None,
        "total_riders": 2,
    }


def test_get_my_effort_with_compare_ordering():
    """my_latest 必须按 Activity.started_at，my_best 必须按 elapsed_time。"""
    early_started = datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc)
    late_started = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
    early_effort = SimpleNamespace(
        id=10, segment_id=1, activity_id=100, user_id=2,
        elapsed_time=1300, avg_speed=20.0, avg_power=180.0,
        start_index=0, end_index=10, created_at=late_started,
    )
    late_effort = SimpleNamespace(
        id=9, segment_id=1, activity_id=101, user_id=2,
        elapsed_time=1100, avg_speed=22.0, avg_power=190.0,
        start_index=0, end_index=10, created_at=early_started,
    )
    early_activity = SimpleNamespace(started_at=early_started)
    late_activity = SimpleNamespace(started_at=late_started)

    total_query = _FakeQuery(scalar_value=2)
    my_query = _FakeQuery(all_value=[
        (late_effort, late_activity),
        (early_effort, early_activity),
    ])
    rank_query = _FakeQuery(all_value=[
        SimpleNamespace(user_id=2, best_time=1100),
        SimpleNamespace(user_id=3, best_time=1000),
    ])
    db = MagicMock()
    db.query.side_effect = [total_query, my_query, rank_query]

    result = service.get_my_effort_with_compare(db, segment_id=1, user_id=2)

    assert "activities.started_at DESC" in " ".join(str(arg) for arg in my_query.order_args)
    assert result["my_best"]["elapsed_time"] == 1100
    assert result["my_latest"]["activity_started_at"] == late_started
    assert result["rank"] == 2
    assert result["total_riders"] == 2


def test_create_segment_invalid_range():
    """start_index >= end_index 时，拿锁后立即拒绝，避免继续读轨迹。"""
    db = MagicMock()

    with pytest.raises(InvalidSegmentRangeError):
        service.create_segment_from_activity(db, 1, "非法赛段", 3, 3)

    assert db.execute.call_count == 1


def test_create_segment_too_short():
    """距离不足 1 公里时抛 InvalidSegmentRangeError。"""
    db = MagicMock()
    activity_query = _FakeQuery(first_value=SimpleNamespace(id=1))
    tp_query = _FakeQuery(all_value=[
        SimpleNamespace(seq=0, latitude=37.0, longitude=112.0, elevation=10.0),
        SimpleNamespace(seq=1, latitude=37.0001, longitude=112.0, elevation=11.0),
    ])
    db.query.side_effect = [activity_query, tp_query]

    with pytest.raises(InvalidSegmentRangeError):
        service.create_segment_from_activity(db, 1, "太短赛段", 0, 1)

    assert db.execute.call_count == 1


def test_create_segment_overlap():
    """Hausdorff 查重命中时抛 SegmentOverlapError。"""
    db = MagicMock()
    activity_query = _FakeQuery(first_value=SimpleNamespace(id=1))
    tp_query = _FakeQuery(all_value=[
        SimpleNamespace(seq=0, latitude=37.0, longitude=112.0, elevation=10.0),
        SimpleNamespace(seq=1, latitude=37.01, longitude=112.0, elevation=30.0),
    ])
    overlap_result = MagicMock()
    overlap_result.first.return_value = (1,)
    db.query.side_effect = [activity_query, tp_query]
    db.execute.side_effect = [MagicMock(), overlap_result]

    with pytest.raises(SegmentOverlapError):
        service.create_segment_from_activity(db, 1, "重复赛段", 0, 1)


def test_create_segment_success():
    """轨迹合法且不重叠时，应创建赛段并写入派生字段。"""
    db = MagicMock()
    activity_query = _FakeQuery(first_value=SimpleNamespace(id=1))
    trackpoints = [
        SimpleNamespace(
            seq=i,
            latitude=37.0 + i * 0.001,
            longitude=112.0,
            elevation=100.0 + i if i <= 15 else 115.0 - (i - 15),
        )
        for i in range(30)
    ]
    tp_query = _FakeQuery(all_value=trackpoints)
    overlap_result = MagicMock()
    overlap_result.first.return_value = None
    db.query.side_effect = [activity_query, tp_query]
    db.execute.side_effect = [MagicMock(), overlap_result]

    segment = service.create_segment_from_activity(
        db,
        activity_id=1,
        name="成功赛段",
        start_index=0,
        end_index=29,
        city="taiyuan",
        difficulty="easy",
    )

    rendered_filters = " ".join(str(f) for f in tp_query.filters)
    assert "trackpoints.seq" in rendered_filters
    assert segment is not None
    assert segment.elevation_gain == 15.0
    assert segment.elevation_loss == 14.0
    assert segment.avg_gradient == pytest.approx((15.0 - 14.0) / segment.distance * 100)
    db.add.assert_called_once_with(segment)
    db.flush.assert_called_once()
