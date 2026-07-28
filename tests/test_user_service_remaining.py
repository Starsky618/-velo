"""
v5 task-2.C.2 余下 3 函数测试：heatmap / update_user_city / profile_for_others。
真 PG + 真 Redis（dev stack）。

测试约束：
- 每 case 自带前缀清理，不污染其他测试
- 严格 RESPONSE_KEYS 白名单测试是 D-P08 红线（看自己 = 看他人）防回退
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.activity.models import Activity, Trackpoint
from app.user.models import User
from app.user.service import (
    get_user_heatmap,
    get_user_profile_for_others,
    update_user_city,
)
from app.user.service_social import (
    _claim_heatmap_source_build,
    _heatmap_cache_generation,
    _decode_heatmap_cache,
    _encode_heatmap_cache,
    _build_heatmap_viewport_source,
    _build_heatmap_viewport_tracks,
    _build_heatmap_preview_track,
    _heatmap_points_per_activity,
    _heatmap_viewport_budget,
    _normalize_heatmap_viewport,
    _select_heatmap_key_points,
    _select_heatmap_preview_activities,
    _trim_heatmap_viewport_cache,
)


_PREFIX = "[task-2.C.2-rest]"
_BJ_TZ = timezone(timedelta(hours=8))


def _db_url() -> str:
    return (
        os.getenv("VELO_TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://velo:velo@localhost:5435/velo"
    )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"dev stack PostgreSQL 不可用: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def real_redis():
    from app.queue import redis_conn
    try:
        redis_conn.ping()
    except Exception as exc:
        pytest.skip(f"dev stack Redis 不可用: {exc}")
    yield redis_conn


def _cleanup_db(db):
    db.execute(text(
        "DELETE FROM trackpoints WHERE activity_id IN "
        "(SELECT id FROM activities WHERE title LIKE :prefix)"
    ), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM activities WHERE title LIKE :prefix"), {"prefix": f"{_PREFIX}%"})
    db.execute(text("DELETE FROM users WHERE openid LIKE :prefix"), {"prefix": "task_2c2_rest_%"})
    db.commit()


def _cleanup_redis(redis_client, user_id: int):
    redis_client.delete(f"heatmap:generation:user_{user_id}")
    for prefix in (
        "heatmap:v5:user_", "heatmap:v4:user_", "heatmap:v3:user_", "heatmap:v2:user_",
        "heatmap:user_", "power_curve:user_",
    ):
        redis_client.delete(f"{prefix}{user_id}")
        for key in redis_client.scan_iter(match=f"{prefix}{user_id}:*"):
            redis_client.delete(key)


def _make_user(db, suffix: str, city=None) -> User:
    user = User(
        openid=f"task_2c2_rest_{suffix}",
        nickname=f"task-2.C.2-rest {suffix}",
        city=city,
        ftp=200,
        bike_type="road",
        avatar_url="https://example.com/a.jpg",
    )
    db.add(user)
    db.flush()
    return user


def _make_activity_in_beijing(
    db, user: User, suffix: str, started_at: datetime, distance: float = 1000.0
) -> Activity:
    """构造一条 simplified_track 起点在北京的活动（39.9N / 116.4E 是天安门附近）。"""
    activity = Activity(
        user_id=user.id,
        title=f"{_PREFIX} {suffix}",
        status="completed",
        distance=distance,
        duration=1800,
        elevation_gain=50.0,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1800),
        data_source="gpx",
        activity_type="cycling",
        simplified_track=[
            {"lat": 39.9, "lon": 116.4, "ele": 50.0},
            {"lat": 39.91, "lon": 116.41, "ele": 52.0},
            {"lat": 39.92, "lon": 116.42, "ele": 53.0},
        ],
        avg_power=180.0,
    )
    db.add(activity)
    db.flush()
    return activity


def _this_month_utc() -> datetime:
    now_bj = datetime.now(timezone.utc).astimezone(_BJ_TZ)
    return now_bj.replace(day=15, hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _make_activity_in_shanghai(
    db, user: User, suffix: str, started_at: datetime, distance: float = 1000.0
) -> Activity:
    """构造一条 simplified_track 起点在上海的活动（31.2N / 121.5E 是上海市区核心圈）。
    用于 v3 polish 跨城市测试 —— city is None 时该活动也应入选。"""
    activity = Activity(
        user_id=user.id,
        title=f"{_PREFIX} {suffix}",
        status="completed",
        distance=distance,
        duration=1800,
        elevation_gain=30.0,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1800),
        data_source="gpx",
        activity_type="cycling",
        simplified_track=[
            {"lat": 31.20, "lon": 121.47, "ele": 5.0},
            {"lat": 31.21, "lon": 121.48, "ele": 5.5},
            {"lat": 31.22, "lon": 121.49, "ele": 6.0},
        ],
        avg_power=170.0,
    )
    db.add(activity)
    db.flush()
    return activity


# ───────────────────────────────────────────────────────────────────────
# get_user_heatmap
# ───────────────────────────────────────────────────────────────────────


class TestGetUserHeatmap:
    def test_preview_has_hard_pixel_budget_and_small_payload(self):
        """固定尺寸卡片只收显示精度数据；293 条活动响应不能再回到 6.7 MB。"""
        track = [
            {
                "lon": 116.1 + i * 0.0003,
                "lat": 39.8 + ((i % 37) - 18) * 0.0002,
                "ele": 50 + i % 20,
            }
            for i in range(1500)
        ]

        preview = _build_heatmap_preview_track(track)

        assert len(preview) == 64
        assert preview[0] == [round(track[0]["lon"], 5), round(track[0]["lat"], 5)]
        assert preview[-1] == [round(track[-1]["lon"], 5), round(track[-1]["lat"], 5)]
        source_indexes = [
            next(i for i, point in enumerate(track) if preview_point == [round(point["lon"], 5), round(point["lat"], 5)])
            for preview_point in preview
        ]
        assert source_indexes == sorted(set(source_indexes))
        simulated_response = {
            "city": None,
            "tracks": [preview] * 293,
            "activity_count": 293,
        }
        assert len(json.dumps(simulated_response).encode()) < 600_000

    def test_preview_has_global_budget_and_keeps_rare_regions(self):
        """活动数继续增长时总点数仍封顶，地理分桶不会把稀有城市截掉。"""
        beijing = [
            SimpleNamespace(simplified_track=[
                {"lon": 116.4, "lat": 39.9}, {"lon": 116.41, "lat": 39.91},
            ])
            for _ in range(12_000)
        ]
        shenzhen = SimpleNamespace(simplified_track=[
            {"lon": 114.0, "lat": 22.5}, {"lon": 114.01, "lat": 22.51},
        ])

        selected = _select_heatmap_preview_activities(beijing + [shenzhen], 4_500)
        point_limit = _heatmap_points_per_activity(len(selected))

        assert len(selected) == 4_500
        assert shenzhen in selected
        assert point_limit == 2
        assert len(selected) * point_limit <= 9_000

    def test_card_detail_uses_smaller_level_of_detail_budget(self):
        """个人页只取卡片精度，全屏仍保留更高精度，避免小视图重复卡顿。"""
        assert _heatmap_points_per_activity(
            293,
            per_activity_limit=24,
            total_point_budget=4_000,
        ) == 13
        assert _heatmap_points_per_activity(293) == 30

    @pytest.mark.parametrize(
        ("zoom", "per_segment_limit"),
        [(10, 128), (11, 192), (12, 192), (13, 320)],
    )
    def test_viewport_zoom_levels_share_the_same_render_budget(
        self,
        zoom,
        per_segment_limit,
    ):
        total_budget, actual_per_segment_limit = _heatmap_viewport_budget(zoom)

        assert total_budget == 18_000
        assert actual_per_segment_limit == per_segment_limit

    def test_viewport_detail_keeps_city_overview_crisp_without_large_payload(self):
        """293 条城市轨迹约 1.8 万点，兼顾弯道形状与微信渲染层上限。"""
        activities = []
        for track_index in range(293):
            track = [
                {
                    "lon": 112.45 + track_index * 0.00005 + point_index * 0.0002,
                    "lat": 37.70 + ((point_index % 41) - 20) * 0.0003,
                }
                for point_index in range(300)
            ]
            activities.append(SimpleNamespace(simplified_track=track))

        source_tracks = _build_heatmap_viewport_source(activities)
        viewport = _normalize_heatmap_viewport(112.3, 37.5, 112.8, 38.1, 10)
        tracks, visible_count = _build_heatmap_viewport_tracks(source_tracks, viewport)
        point_count = sum(len(track) for track in tracks)
        payload = json.dumps({"tracks": tracks}, separators=(",", ":")).encode()

        assert sum(len(track) for track in source_tracks) <= 72_000
        assert visible_count == 293
        assert len(tracks) == 293
        assert 16_000 <= point_count <= 18_000
        assert len(payload) < 600_000

    def test_viewport_clips_to_visible_area_and_rejects_unbounded_queries(self):
        viewport = _normalize_heatmap_viewport(112.4, 37.6, 112.7, 37.9, 13)
        activity = SimpleNamespace(simplified_track=[
            {"lon": 112.35, "lat": 37.55},
            {"lon": 112.45, "lat": 37.65},
            {"lon": 112.55, "lat": 37.75},
            {"lon": 112.65, "lat": 37.85},
            {"lon": 112.75, "lat": 37.95},
        ])

        tracks, visible_count = _build_heatmap_viewport_tracks([activity], viewport)

        assert visible_count == 1
        assert len(tracks) == 1
        assert tracks[0][0] == [112.35, 37.55]
        assert tracks[0][-1] == [112.75, 37.95]
        with pytest.raises(ValueError, match="too large"):
            _normalize_heatmap_viewport(70, 10, 120, 40, 8)

    def test_viewport_keeps_segment_that_crosses_screen_with_both_endpoints_outside(self):
        activity = SimpleNamespace(simplified_track=[
            {"lon": 116.30, "lat": 39.95},
            {"lon": 116.60, "lat": 39.95},
        ])

        tracks, visible_count = _build_heatmap_viewport_tracks(
            [activity],
            (116.40, 39.90, 116.50, 40.00, 10),
        )

        assert visible_count == 1
        assert tracks == [[[116.3, 39.95], [116.6, 39.95]]]

    def test_viewport_does_not_infer_gps_gaps_from_dp_point_density(self):
        mixed_density = SimpleNamespace(simplified_track=[
            {"lon": 116.000, "lat": 39.0},
            {"lon": 116.001, "lat": 39.0},
            {"lon": 116.002, "lat": 39.0},
            {"lon": 116.042, "lat": 39.0},
            {"lon": 116.043, "lat": 39.0},
            {"lon": 116.044, "lat": 39.0},
        ])
        viewport = (115.9, 38.9, 116.3, 39.2, 10)

        tracks, visible_count = _build_heatmap_viewport_tracks([mixed_density], viewport)

        assert visible_count == 1
        assert len(tracks) == 1
        assert len(tracks[0]) == 6

    def test_shape_selector_keeps_local_turns_and_strict_track_order(self):
        points = [
            {"lon": 0, "lat": 0},
            {"lon": 1, "lat": 0},
            {"lon": 2, "lat": 0},
            {"lon": 2, "lat": 3},
            {"lon": 3, "lat": 3},
            {"lon": 4, "lat": 3},
        ]

        reduced = _select_heatmap_key_points(points, 4)

        assert len(reduced) == 4
        assert reduced[0] is points[0]
        assert reduced[-1] is points[-1]
        assert points[3] in reduced
        assert [points.index(point) for point in reduced] == sorted(
            points.index(point) for point in reduced
        )

        for point_count in range(3, 50):
            indexed_points = [
                {
                    "lon": index + math.sin(index) * 0.2,
                    "lat": math.cos(index * 0.7),
                    "original_index": index,
                }
                for index in range(point_count)
            ]
            for limit in range(2, point_count):
                indexed_reduced = _select_heatmap_key_points(indexed_points, limit)
                indexes = [point["original_index"] for point in indexed_reduced]
                assert len(indexed_reduced) == limit
                assert indexed_reduced[0] is indexed_points[0]
                assert indexed_reduced[-1] is indexed_points[-1]
                assert indexes == sorted(set(indexes))

        continuous_turns = [
            {
                "lon": 112 + index * 0.0001,
                "lat": 37 + (0.0001 if index % 2 else 0),
                "original_index": index,
            }
            for index in range(100)
        ]
        continuous_reduced = _select_heatmap_key_points(continuous_turns, 10)
        continuous_indexes = [point["original_index"] for point in continuous_reduced]
        assert max(
            right - left
            for left, right in zip(continuous_indexes, continuous_indexes[1:])
        ) <= 14

        short_turn = [
            {
                "lon": 112 + index * 0.0001,
                "lat": 37 + (0.001 if index == 50 else 0),
                "original_index": index,
            }
            for index in range(100)
        ]
        assert 50 in {
            point["original_index"]
            for point in _select_heatmap_key_points(short_turn, 10)
        }

    def test_viewport_activity_count_matches_rendered_activities_after_budget_cutoff(self):
        activities = [
            SimpleNamespace(simplified_track=[
                {"lon": 116.41, "lat": 39.91},
                {"lon": 116.42, "lat": 39.92},
            ])
            for _ in range(1_001)
        ]

        tracks, visible_count = _build_heatmap_viewport_tracks(
            activities,
            (116.30, 39.80, 116.60, 40.10, 10),
        )

        assert len(tracks) == 1_000
        assert visible_count == 1_000

    def test_viewport_cache_is_capped_per_user_and_keeps_current_key(self):
        class FakeRedis:
            def __init__(self, keys):
                self.keys = list(keys)

            def scan_iter(self, match):
                assert match == "heatmap:v5:user_7:detail_viewport:*"
                return iter(self.keys)

            def delete(self, *keys):
                self.keys = [key for key in self.keys if key not in keys]

        current = "heatmap:v5:user_7:detail_viewport:current"
        redis = FakeRedis([
            f"heatmap:v5:user_7:detail_viewport:{index}".encode()
            for index in range(15)
        ] + [current.encode()])

        _trim_heatmap_viewport_cache(redis, 7, current)

        assert len(redis.keys) == 12
        assert current.encode() in redis.keys

    def test_stale_request_cache_envelope_is_rejected_after_invalidation_generation_changes(self):
        stale = _encode_heatmap_cache(
            {"tracks": [[[116.4, 39.9], [116.5, 40.0]]]},
            generation=4,
        )

        assert _decode_heatmap_cache(stale, expected_generation=4) is not None
        assert _decode_heatmap_cache(stale, expected_generation=5) is None

    def test_heatmap_cache_generation_decodes_redis_bytes(self):
        redis = SimpleNamespace(get=lambda _key: b"7")

        assert _heatmap_cache_generation(redis, 42) == 7

    def test_source_build_lock_makes_parallel_cold_request_reuse_finished_source(self):
        source = {"tracks": [[[116.4, 39.9], [116.5, 40.0]]], "available_years": [2026]}

        class FakeRedis:
            def __init__(self):
                self.claimed = False
                self.cached = None

            def set(self, _key, _value, **_kwargs):
                if not self.claimed:
                    self.claimed = True
                    return True
                return False

            def get(self, _key):
                return self.cached

        redis = FakeRedis()
        is_builder, waited = _claim_heatmap_source_build(redis, "source", 3)
        assert is_builder is True
        assert waited is None

        redis.cached = _encode_heatmap_cache(source, generation=3)
        is_builder, waited = _claim_heatmap_source_build(redis, "source", 3)
        assert is_builder is False
        assert waited == source

    def test_invalid_tracks_do_not_consume_global_preview_budget(self):
        invalid = [
            SimpleNamespace(simplified_track=[{"lon": float(i % 180), "lat": 20.0}])
            for i in range(12_000)
        ]
        valid = SimpleNamespace(simplified_track=[
            {"lon": 116.4, "lat": 39.9}, {"lon": 116.41, "lat": 39.91},
        ])

        selected = _select_heatmap_preview_activities(invalid + [valid], 10_000)

        assert selected == [valid]

    def test_global_budget_keeps_activity_covering_rare_destination(self):
        local = [
            SimpleNamespace(simplified_track=[
                {"lon": 116.4, "lat": 39.9}, {"lon": 116.41, "lat": 39.91},
            ])
            for _ in range(10_000)
        ]
        rare_destination = SimpleNamespace(simplified_track=[
            {"lon": 116.4, "lat": 39.9}, {"lon": 116.8, "lat": 39.9},
            {"lon": 117.2, "lat": 39.9},
        ])

        selected = _select_heatmap_preview_activities(local + [rare_destination], 10_000)

        assert len(selected) == 10_000
        assert rare_destination in selected

    def test_no_activities_returns_empty_tracks(self, pg_session_factory, real_redis):
        """无 activity → 返 tracks 空列表（D27 v2 polish）。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "no_act_heatmap")
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            result = get_user_heatmap(db, user_id, "beijing")
            assert result["city"] == "beijing"
            assert result["tracks"] == []
            assert result["activity_count"] == 0
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_aggregates_tracks_preserving_activity_boundary(self, pg_session_factory, real_redis):
        """北京 2 活动各自一条独立轨迹（D27 v2 polish / 保留 activity 边界）。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "bj_heatmap")
            _make_activity_in_beijing(db, user, "act1", _this_month_utc())
            _make_activity_in_beijing(db, user, "act2", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            result = get_user_heatmap(db, user_id, "beijing")
            # 2 活动 → 2 条独立轨迹（不再扁平合并）
            assert result["activity_count"] == 2
            assert len(result["tracks"]) == 2
            # 每条轨迹各 3 个点
            assert len(result["tracks"][0]) == 3
            assert len(result["tracks"][1]) == 3
            # 验证 GeoJSON 顺序 [lon, lat]
            first_point = result["tracks"][0][0]
            assert first_point[0] > 100  # lon 在中国是 73-135
            assert first_point[1] < 60   # lat 在中国是 18-54
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_filters_by_city(self, pg_session_factory, real_redis):
        """查 shanghai 不应返回 beijing 起点的活动（D27 v2 polish / tracks 字段）。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "city_filter")
            _make_activity_in_beijing(db, user, "bj1", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            result = get_user_heatmap(db, user_id, "shanghai")
            assert result["activity_count"] == 0
            assert result["tracks"] == []
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_cache_hit_returns_redis_data(self, pg_session_factory, real_redis):
        """第二次同 user / city 查走 Redis（不查 DB）。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "cache_heatmap")
            _make_activity_in_beijing(db, user, "act", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            first = get_user_heatmap(db, user_id, "beijing")
            cached_raw = real_redis.get(
                f"heatmap:v5:user_{user_id}:detail_full:city_beijing:year_all"
            )
            assert cached_raw is not None

            second = get_user_heatmap(db, user_id, "beijing")
            assert second == first
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_no_city_returns_all_tracks_across_cities(self, pg_session_factory, real_redis):
        """v3 polish：city=None → 返回该用户所有 completed activities 的轨迹（不按城市筛）。
        构造北京 + 上海 2 个 activity，期望都返回。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "no_city_all")
            _make_activity_in_beijing(db, user, "bj", _this_month_utc())
            _make_activity_in_shanghai(db, user, "sh", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            result = get_user_heatmap(db, user_id, None)
            # 不按城市筛 → 北京 + 上海 2 条都进来
            assert result["city"] is None
            assert result["activity_count"] == 2
            assert len(result["tracks"]) == 2
            # 顺序无保证 / 验证两组起点都出现（北京 lon~116 / 上海 lon~121）
            first_lons = [tr[0][0] for tr in result["tracks"]]
            assert any(115 < lon < 118 for lon in first_lons), "缺北京轨迹"
            assert any(120 < lon < 122 for lon in first_lons), "缺上海轨迹"
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_cache_key_separates_detail_year_and_city(self, pg_session_factory, real_redis):
        """v5 cache key 必须隔离卡片/全屏、年份和城市。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "no_city_key")
            _make_activity_in_beijing(db, user, "act", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            # 走无 city / 全年份 / full 路径
            get_user_heatmap(db, user_id, None)

            no_city_key = f"heatmap:v5:user_{user_id}:detail_full:year_all"
            assert real_redis.get(no_city_key) is not None, (
                f"期望 cache key {no_city_key} 存在"
            )

            get_user_heatmap(db, user_id, None, _this_month_utc().astimezone(_BJ_TZ).year, "card")
            card_year_key = (
                f"heatmap:v5:user_{user_id}:detail_card:"
                f"year_{_this_month_utc().astimezone(_BJ_TZ).year}"
            )
            assert real_redis.get(card_year_key) is not None
            assert card_year_key != no_city_key
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_viewport_detail_filters_tracks_and_uses_bucketed_cache(self, pg_session_factory, real_redis):
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "viewport_cache")
            _make_activity_in_beijing(db, user, "bj", _this_month_utc())
            _make_activity_in_shanghai(db, user, "sh", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            first = get_user_heatmap(
                db,
                user_id,
                None,
                None,
                "viewport",
                west=116.22,
                south=39.72,
                east=116.58,
                north=40.08,
                zoom=10,
            )

            assert first["activity_count"] == 1
            assert len(first["tracks"]) == 1
            assert 116 < first["tracks"][0][0][0] < 117
            cached_keys = list(real_redis.scan_iter(match=f"heatmap:v5:user_{user_id}:detail_viewport:*"))
            assert len(cached_keys) == 1

            source_key = f"heatmap:v5:user_{user_id}:detail_viewport_source:year_all"
            assert real_redis.get(source_key).startswith(b"z1:")

            with patch.object(db, "query", side_effect=AssertionError("source cache should avoid PostgreSQL")):
                second = get_user_heatmap(
                    db,
                    user_id,
                    None,
                    None,
                    "viewport",
                    west=116.32,
                    south=39.72,
                    east=116.68,
                    north=40.08,
                    zoom=10,
                )
            assert second["activity_count"] == 1
            assert len(list(real_redis.scan_iter(match=f"heatmap:v5:user_{user_id}:detail_viewport:*"))) == 2
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_year_filter_returns_available_years_and_selected_year(self, pg_session_factory, real_redis):
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "year_filter")
            _make_activity_in_beijing(db, user, "current", datetime(2026, 7, 1, tzinfo=timezone.utc))
            _make_activity_in_beijing(db, user, "older", datetime(2025, 7, 1, tzinfo=timezone.utc))
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            result = get_user_heatmap(db, user_id, None, 2025, "full")

            assert result["selected_year"] == 2025
            assert result["available_years"] == [2026, 2025]
            assert result["activity_count"] == 1
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()


# ───────────────────────────────────────────────────────────────────────
# update_user_city
# ───────────────────────────────────────────────────────────────────────


class TestUpdateUserCity:
    def test_valid_city_updates_field(self, pg_session_factory, real_redis):
        """合法 city 写入成功。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "valid_city")
            db.commit()
            user_id = user.id

            updated = update_user_city(db, user_id, "shanghai")
            assert updated.city == "shanghai"

            db.expire_all()
            loaded = db.query(User).filter(User.id == user_id).first()
            assert loaded.city == "shanghai"
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_none_clears_city(self, pg_session_factory, real_redis):
        """city=None 表示清空选择（与 nullable=True 一致）。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "clear_city", city="beijing")
            db.commit()
            user_id = user.id

            updated = update_user_city(db, user_id, None)
            assert updated.city is None
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()

    def test_too_long_city_raises_value_error(self, pg_session_factory, real_redis):
        """用户家乡可自定义，但超过 32 字符必须拒绝。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "bad_city")
            db.commit()
            user_id = user.id

            with pytest.raises(ValueError, match="city too long"):
                update_user_city(db, user_id, "城" * 33)
        finally:
            _cleanup_db(db)
            db.close()

    def test_user_not_found_raises(self, pg_session_factory, real_redis):
        """user 不存在抛 ValueError。"""
        db = pg_session_factory()
        try:
            _cleanup_db(db)
            with pytest.raises(ValueError, match="user not found"):
                update_user_city(db, 999_999_999, "beijing")
        finally:
            db.close()

    def test_invalidates_heatmap_cache(self, pg_session_factory, real_redis):
        """改 city 后清掉 v3/v2/legacy 的全部热图缓存。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "invalidate_heatmap", city="beijing")
            _make_activity_in_beijing(db, user, "act", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            generation_key = f"heatmap:generation:user_{user_id}"
            generation_before = int(real_redis.get(generation_key) or 0)
            keys = [
                f"heatmap:v5:user_{user_id}:detail_full:year_all",
                f"heatmap:v5:user_{user_id}:detail_card:year_2026",
                f"heatmap:v5:user_{user_id}:detail_viewport_source:year_all",
                f"heatmap:v5:user_{user_id}:detail_viewport:year_all:viewport_1",
                f"heatmap:v4:user_{user_id}:detail_full:year_all",
                f"heatmap:v3:user_{user_id}:detail_full:year_all",
                f"heatmap:v2:user_{user_id}",
                f"heatmap:v2:user_{user_id}:city_beijing",
                f"heatmap:user_{user_id}",
                f"heatmap:user_{user_id}:city_beijing",
            ]
            for key in keys:
                real_redis.set(key, "cached")
            assert all(real_redis.get(key) is not None for key in keys)

            # 改 city → 应清缓存
            update_user_city(db, user_id, "shanghai")
            assert all(real_redis.get(key) is None for key in keys)
            generation_after = generation_before + 1
            assert int(real_redis.get(generation_key)) == generation_after

            # generation 非零后 card/full/viewport 三条真实路径都能重建，且使用新代 key。
            card = get_user_heatmap(db, user_id, None, None, "card")
            full = get_user_heatmap(db, user_id, None, None, "full")
            viewport = get_user_heatmap(
                db,
                user_id,
                None,
                None,
                "viewport",
                west=116.2,
                south=39.7,
                east=116.7,
                north=40.2,
                zoom=10,
            )
            assert card["activity_count"] == 1
            assert full["activity_count"] == 1
            assert viewport["activity_count"] == 1
            new_keys = list(real_redis.scan_iter(match=f"heatmap:v5:user_{user_id}:*"))
            assert new_keys
            assert all(f"generation_{generation_after}".encode() in key for key in new_keys)
        finally:
            if user_id is not None:
                _cleanup_redis(real_redis, user_id)
            _cleanup_db(db)
            db.close()


# ───────────────────────────────────────────────────────────────────────
# get_user_profile_for_others
# ───────────────────────────────────────────────────────────────────────


class TestGetUserProfileForOthers:
    def test_returns_only_response_keys(self, pg_session_factory, real_redis):
        """⚠ 关键防回退（spec R3-I3）：只返 RESPONSE_KEYS 白名单字段。
        即使 raw_response 包含敏感字段（手动塞 strava_access_token）也不应泄漏。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "whitelist", city="beijing")
            db.commit()
            user_id = user.id

            result = get_user_profile_for_others(db, user_id, requester_user_id=user_id)
            # Sprint 4 codex 异源审 2026-05-06 砍 ftp（P1-4）
            # Sprint 6 task-1 加 bio / task-2 加 badges → 11 字段
            allowed_keys = {
                "id", "nickname", "avatar_url", "city", "bio", "bike_type",
                "total_distance_km", "total_elevation_m", "activity_count",
                "current_month_summary", "badges",
            }
            assert set(result.keys()) == allowed_keys
            # 严格不返这些（ftp 加入：codex 拍砍 / FTP 是骑手生理数据 / Strava 也允许独立隐私层）
            for forbidden in ("openid", "strava_access_token", "strava_refresh_token",
                              "mute_notifications", "weekly_goal", "weight", "ftp"):
                assert forbidden not in result
        finally:
            _cleanup_db(db)
            db.close()

    def test_filter_profile_keys_strips_sensitive_fields(self):
        """⚠ 真防回退（codex Important 修 / spec R3-I3）：
        直接测 _filter_profile_keys helper 接收**含敏感字段的 dict** 时过滤掉它们。

        why 这样测：原来 test_returns_only_response_keys 因 raw_response 字面只列白名单字段，
        删推导式不会让测试失败。本测试反向构造——故意塞敏感字段进 helper 输入，
        如果未来：
        - 删掉 dict 推导式（return raw_response 不过滤）
        - 改成黑名单（漏字段就泄漏）
        - 把 _PROFILE_RESPONSE_KEYS 加敏感字段（白名单本身污染）
        → 本测试立即抓。
        """
        from app.user.service_social import _filter_profile_keys, _PROFILE_RESPONSE_KEYS

        # 构造含 7 个敏感字段的 raw_response（Sprint 4 codex 拍砍 ftp / Sprint 6 task-1 加 bio / task-2 加 badges）
        raw_with_sensitive = {
            # 白名单内（应保留）
            "id": 42,
            "nickname": "test",
            "avatar_url": "https://x",
            "city": "beijing",
            "bio": "测试签名",  # Sprint 6 task-1：bio 加入白名单（公开 / 跟 city 同级）
            "bike_type": "road",
            "total_distance_km": 100.0,
            "total_elevation_m": 500.0,
            "activity_count": 5,
            "current_month_summary": {"distance_km": 30.0},
            # Sprint 6 task-2：badges 加入白名单（真实数据自动算 / 公开）
            "badges": [{"type": "ftp", "label": "FTP 200W"}],
            # ⚠ 敏感字段（应被过滤）
            "ftp": 200,  # Sprint 4 codex 异源审拍砍（P1-4 / FTP 是骑手生理数据）
            "openid": "wx_secret_openid_xxx",
            "strava_access_token": "STRAVA_TOKEN_LEAK_RISK",
            "strava_refresh_token": "REFRESH_TOKEN_LEAK",
            "strava_token_expires_at": "2099-01-01",
            "mute_notifications": True,
            "weight": 70.5,  # 用户隐私
        }

        result = _filter_profile_keys(raw_with_sensitive)

        # 敏感字段必须被过滤
        for forbidden in (
            "ftp",  # Sprint 4 codex 异源审拍加（P1-4）
            "openid", "strava_access_token", "strava_refresh_token",
            "strava_token_expires_at", "mute_notifications", "weight",
        ):
            assert forbidden not in result, (
                f"敏感字段 {forbidden} 出现在 result 里——白名单过滤被破坏了！"
            )

        # 白名单字段必须保留
        for allowed in _PROFILE_RESPONSE_KEYS:
            assert allowed in result, f"白名单字段 {allowed} 被错过滤"

        # result 字段集合 = 白名单（不多不少）
        assert set(result.keys()) == _PROFILE_RESPONSE_KEYS

    def test_response_keys_whitelist_does_not_contain_sensitive_names(self):
        """⚠ 元防回退：_PROFILE_RESPONSE_KEYS 集合本身**不应**包含敏感字段名。
        即使有人误把 'strava_access_token' 加到白名单，本测试也立即抓。"""
        from app.user.service_social import _PROFILE_RESPONSE_KEYS

        forbidden_in_whitelist = {
            "ftp",  # Sprint 4 codex 异源审 2026-05-06 拍加（P1-4 / FTP 是骑手生理数据）
            "openid", "strava_access_token", "strava_refresh_token",
            "strava_token_expires_at", "mute_notifications", "weight",
            "weekly_goal", "wechat_unionid",
        }
        intersection = _PROFILE_RESPONSE_KEYS & forbidden_in_whitelist
        assert not intersection, (
            f"白名单集合污染了！这些字段不应在 _PROFILE_RESPONSE_KEYS 里：{intersection}"
        )

    def test_self_vs_others_same_field_set(self, pg_session_factory, real_redis):
        """D-P08 红线：看自己 vs 看他人字段集合完全一致（v5 不区分）。"""
        db = pg_session_factory()
        try:
            _cleanup_db(db)
            user_a = _make_user(db, "self_user", city="beijing")
            user_b = _make_user(db, "other_user", city="shanghai")
            db.commit()

            self_view = get_user_profile_for_others(db, user_a.id, requester_user_id=user_a.id)
            others_view = get_user_profile_for_others(db, user_b.id, requester_user_id=user_a.id)

            assert set(self_view.keys()) == set(others_view.keys())
        finally:
            _cleanup_db(db)
            db.close()

    def test_user_not_found_raises(self, pg_session_factory, real_redis):
        db = pg_session_factory()
        try:
            _cleanup_db(db)
            with pytest.raises(ValueError, match="用户不存在"):
                get_user_profile_for_others(db, 999_999_999, requester_user_id=1)
        finally:
            db.close()

    def test_aggregates_totals(self, pg_session_factory, real_redis):
        """累计 distance / elevation / activity_count 聚合准确。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "totals", city="beijing")
            _make_activity_in_beijing(db, user, "a1", _this_month_utc(), distance=10000.0)
            _make_activity_in_beijing(db, user, "a2", _this_month_utc(), distance=20000.0)
            db.commit()
            user_id = user.id

            result = get_user_profile_for_others(db, user_id, requester_user_id=user_id)
            # 2 活动 × 1km elevation_gain=50m
            assert result["activity_count"] == 2
            # 10km + 20km = 30km，但函数用米 → 公里转换 = (10000+20000)/1000 = 30.0
            assert result["total_distance_km"] == 30.0
            assert result["total_elevation_m"] == 100.0
        finally:
            _cleanup_db(db)
            db.close()

    def test_current_month_summary_uses_bj_timezone(self, pg_session_factory, real_redis):
        """current_month_summary 按 BJ +8 划月。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "month_bj", city="beijing")
            # 本月活动
            _make_activity_in_beijing(db, user, "this", _this_month_utc())
            db.commit()
            user_id = user.id

            result = get_user_profile_for_others(db, user_id, requester_user_id=user_id)
            assert result["current_month_summary"]["distance_km"] > 0
            assert result["current_month_summary"]["elevation_m"] > 0
        finally:
            _cleanup_db(db)
            db.close()
