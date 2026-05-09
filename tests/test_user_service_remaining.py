"""
v5 task-2.C.2 余下 3 函数测试：heatmap / update_user_city / profile_for_others。
真 PG + 真 Redis（dev stack）。

测试约束：
- 每 case 自带前缀清理，不污染其他测试
- 严格 RESPONSE_KEYS 白名单测试是 D-P08 红线（看自己 = 看他人）防回退
"""

import json
import os
from datetime import datetime, timedelta, timezone

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
    for prefix in ("heatmap:user_", "power_curve:user_"):
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


# ───────────────────────────────────────────────────────────────────────
# get_user_heatmap
# ───────────────────────────────────────────────────────────────────────


class TestGetUserHeatmap:
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
            cached_raw = real_redis.get(f"heatmap:user_{user_id}:city_beijing")
            assert cached_raw is not None

            second = get_user_heatmap(db, user_id, "beijing")
            assert second == first
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

    def test_invalid_city_raises_value_error(self, pg_session_factory, real_redis):
        """非 7 主城枚举抛 ValueError（不应到 DB CheckConstraint 才被拦）。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "bad_city")
            db.commit()
            user_id = user.id

            with pytest.raises(ValueError, match="invalid city"):
                update_user_city(db, user_id, "guangzhou")
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
        """改 city 后清掉所有 heatmap:user_{id}:* 缓存。"""
        db = pg_session_factory()
        user_id = None
        try:
            _cleanup_db(db)
            user = _make_user(db, "invalidate_heatmap", city="beijing")
            _make_activity_in_beijing(db, user, "act", _this_month_utc())
            db.commit()
            user_id = user.id
            _cleanup_redis(real_redis, user_id)

            # 先建立缓存
            get_user_heatmap(db, user_id, "beijing")
            assert real_redis.get(f"heatmap:user_{user_id}:city_beijing") is not None

            # 改 city → 应清缓存
            update_user_city(db, user_id, "shanghai")
            assert real_redis.get(f"heatmap:user_{user_id}:city_beijing") is None
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
            allowed_keys = {
                "id", "nickname", "avatar_url", "city", "bike_type",
                "total_distance_km", "total_elevation_m", "activity_count",
                "current_month_summary",
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
        from app.user.service import _filter_profile_keys, _PROFILE_RESPONSE_KEYS

        # 构造含 7 个敏感字段的 raw_response（Sprint 4 codex 拍砍 ftp / +1）
        raw_with_sensitive = {
            # 白名单内（应保留）
            "id": 42,
            "nickname": "test",
            "avatar_url": "https://x",
            "city": "beijing",
            "bike_type": "road",
            "total_distance_km": 100.0,
            "total_elevation_m": 500.0,
            "activity_count": 5,
            "current_month_summary": {"distance_km": 30.0},
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
        from app.user.service import _PROFILE_RESPONSE_KEYS

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
