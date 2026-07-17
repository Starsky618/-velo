"""
v5 task-1.A.2：赛段 service 扩展的单元测试。

这些测试尽量用 mock / 假查询对象隔离数据库，像用纸面沙盘推演 service 逻辑：
只验证过滤条件、排序意图、异常分支和返回结构，不依赖真 PostgreSQL。
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.elevation.route_elevation import build_route_elevation_result
from app.segment import service
from app.segment._geo_utils import _sample_elevation_profile
from app.segment.exceptions import InvalidSegmentRangeError, SegmentOverlapError


@pytest.fixture(autouse=True)
def mock_dem(monkeypatch):
    """不下载瓦片，但按固定 20m 查询网格返回确定的 GLO 测试剖面。"""
    def _fake_query(points, dem_url=None):
        if not points:
            return []
        denominator = max(len(points) - 1, 1)
        elevations = []
        for index in range(len(points)):
            ratio = index / denominator
            if ratio <= 0.65:
                elevation = 100.0 + 80.0 * ratio / 0.65
            else:
                elevation = 180.0 - 35.0 * (ratio - 0.65) / 0.35
            elevations.append(elevation)
        return elevations

    monkeypatch.setattr("app.segment.service_create.query_elevations", _fake_query)
    return _fake_query


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
        # v5 task-1.A.3：service 返 dict 含 4 新字段，mock 也要带
        "avg_gradient": 3.2,
        "max_gradient": 7.5,
        "difficulty": "medium",
        "city": "taiyuan",
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
    """用户没在该赛段留 effort 时，6 字段进入"首次访问"兜底状态。"""
    efforts_query = _FakeQuery(all_value=[])
    pr_query = _FakeQuery(scalar_value=None)
    db = MagicMock()
    db.query.side_effect = [efforts_query, pr_query]

    result = service.get_my_effort_with_compare(db, segment_id=1, user_id=2)

    assert result == {
        "current_attempt_elapsed_time": None,
        "last_attempt_elapsed_time": None,
        "pr_elapsed_time": None,
        "current_attempt_diff_to_last": None,
        "current_attempt_is_pr": False,
        "is_first_attempt": True,
    }


def test_get_my_effort_with_compare_pr_attempt():
    """current 是历史最佳时 is_pr=True / diff 反映这次比上次快了多少。"""
    early_started = datetime(2026, 4, 10, 9, 0, tzinfo=timezone.utc)
    late_started = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
    # spec §3.2.1：efforts 已按 Activity.started_at DESC 排序，limit(2)
    # 第一条 = current（最新一次骑）/ 第二条 = last（上一次）
    late_effort = SimpleNamespace(elapsed_time=1100)   # 后骑（current）
    early_effort = SimpleNamespace(elapsed_time=1300)  # 早骑（last）

    efforts_query = _FakeQuery(all_value=[late_effort, early_effort])
    pr_query = _FakeQuery(scalar_value=1100)  # PR 是 1100，等于 current → is_pr
    db = MagicMock()
    db.query.side_effect = [efforts_query, pr_query]

    result = service.get_my_effort_with_compare(db, segment_id=1, user_id=2)

    # 验证按 Activity.started_at DESC 排序写进了 SQL
    assert "activities.started_at DESC" in " ".join(str(a) for a in efforts_query.order_args)
    assert result["current_attempt_elapsed_time"] == 1100
    assert result["last_attempt_elapsed_time"] == 1300
    assert result["pr_elapsed_time"] == 1100
    assert result["current_attempt_diff_to_last"] == 200  # last - current = 1300 - 1100
    assert result["current_attempt_is_pr"] is True
    assert result["is_first_attempt"] is False


def test_get_my_effort_with_compare_first_attempt():
    """只骑过 1 次时 last/diff 为 None / is_first=True / is_pr 看 current 是否 == pr。"""
    only_effort = SimpleNamespace(elapsed_time=1500)
    efforts_query = _FakeQuery(all_value=[only_effort])
    pr_query = _FakeQuery(scalar_value=1500)
    db = MagicMock()
    db.query.side_effect = [efforts_query, pr_query]

    result = service.get_my_effort_with_compare(db, segment_id=1, user_id=2)

    assert result["current_attempt_elapsed_time"] == 1500
    assert result["last_attempt_elapsed_time"] is None
    assert result["pr_elapsed_time"] == 1500
    assert result["current_attempt_diff_to_last"] is None
    assert result["current_attempt_is_pr"] is True  # 唯一一次 = PR
    assert result["is_first_attempt"] is True


def test_create_segment_invalid_range():
    """start_index >= end_index 时立即拒绝，advisory lock 推迟到 DEM 之后所以这里 0 调用。"""
    db = MagicMock()

    with pytest.raises(InvalidSegmentRangeError):
        service.create_segment_from_activity(db, 1, "非法赛段", 3, 3)

    # v3 改动：advisory lock 推迟到 DEM 调用之后才拿（Codex 审 I1 修）
    # 早 raise（invalid range / too short）不持锁 → 避免锁内发慢请求
    assert db.execute.call_count == 0


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

    # v3 改动：advisory lock 推迟（同 invalid_range case）—— too short 早 raise 不持锁
    assert db.execute.call_count == 0


def test_create_segment_overlap():
    """Hausdorff 查重命中时抛 SegmentOverlapError。"""
    db = MagicMock()
    db.bind.dialect.name = "postgresql"  # task-3.A.6 N1：dialect 守卫只在 PG 真跑 Hausdorff
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


def test_create_segment_success(mock_dem):
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
    expected = build_route_elevation_result(
        [[tp.longitude, tp.latitude] for tp in trackpoints],
        query_func=mock_dem,
    )
    assert segment.elevation_gain == expected.climb
    assert segment.elevation_loss == expected.descent
    assert segment.avg_gradient == pytest.approx(
        (expected.snapshot[-1][2] - expected.snapshot[0][2])
        / segment.distance
        * 100
    )
    assert segment.elevation_profile is not None
    profile = json.loads(segment.elevation_profile)
    assert profile == _sample_elevation_profile(
        [{"ele": point[1]} for point in expected.profile],
        target_count=80,
    )
    db.add.assert_called_once_with(segment)
    db.flush.assert_called_once()


def test_create_segment_from_activity_without_uploaded_elevation_uses_glo(mock_dem):
    """FIT/GPX 没有海拔也不留空：统一 GLO 成品链仍生成全部派生字段。"""
    db = MagicMock()
    activity_query = _FakeQuery(first_value=SimpleNamespace(id=1))
    # 全部 elevation=None
    trackpoints = [
        SimpleNamespace(
            seq=i,
            latitude=37.0 + i * 0.001,
            longitude=112.0,
            elevation=None,
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
        name="无海拔赛段",
        start_index=0,
        end_index=29,
        city="taiyuan",
        difficulty="easy",
    )

    expected = build_route_elevation_result(
        [[tp.longitude, tp.latitude] for tp in trackpoints],
        query_func=mock_dem,
    )
    assert segment is not None
    assert segment.elevation_gain == expected.climb
    assert segment.elevation_loss == expected.descent
    assert segment.avg_gradient == pytest.approx(
        (expected.snapshot[-1][2] - expected.snapshot[0][2])
        / segment.distance
        * 100
    )
    assert json.loads(segment.elevation_profile) == _sample_elevation_profile(
        [{"ele": point[1]} for point in expected.profile],
        target_count=80,
    )
    db.add.assert_called_once_with(segment)
    db.flush.assert_called_once()
