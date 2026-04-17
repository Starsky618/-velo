"""
Strava 集成模块测试——"外交部的全面考核"。

测试三大类场景：
1. 适配器测试（纯函数）：Strava JSON → ParseResult 翻译是否正确
2. 路由测试（HTTP 层）：OAuth、Webhook、手动同步、导入进度的 API 端点
3. 调度器测试（业务逻辑）：第一层列表拉取、去重、僵尸检测

注意事项：
- Strava API 不能真调（需要真实 token），所以全部 mock
- 适配器是纯函数，直接调用、不需要 db
- 路由测试复用 conftest.py 的 db / client / auth_header fixture
- 调度器测试需要 strava_imports 表，用独立 fixture 建表
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, Float, Integer, BigInteger, String, DateTime, Text, Table, MetaData

from tests.conftest import _test_engine, _test_metadata

# SQLite 兼容的 trackpoints 表定义（save_parse_result 需要写入此表）
# Trackpoint ORM 模型使用了 PostGIS Geometry，SQLite 不支持，
# 所以这里用 Text 代替 geom 字段，和 conftest 里 activities 表的处理方式一致。
_strava_test_metadata = MetaData()
_trackpoints_table = Table(
    "trackpoints",
    _strava_test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("activity_id", Integer, nullable=False),
    Column("seq", Integer, nullable=False),
    Column("latitude", Float, nullable=False),
    Column("longitude", Float, nullable=False),
    Column("elevation", Float),
    Column("timestamp", DateTime),
    Column("heart_rate", Integer),
    Column("cadence", Integer),
    Column("power", Integer),
    Column("speed", Float),
    Column("distance", Float),
    Column("geom", Text),  # 替代 PostGIS Geometry
)


# ==================== 测试数据 ====================

# Strava Streams API 返回格式（key_by_type=true）
# 5 个轨迹点的最小有效 streams，用于适配器测试
MOCK_STREAMS = {
    "time": {"data": [0, 5, 10, 15, 20]},
    "distance": {"data": [0, 50, 120, 200, 300]},
    "latlng": {"data": [
        [30.1, 120.1], [30.2, 120.2], [30.3, 120.3],
        [30.4, 120.4], [30.5, 120.5],
    ]},
    "altitude": {"data": [100, 102, 105, 103, 101]},
    "velocity_smooth": {"data": [5.0, 6.0, 7.0, 6.5, 5.5]},
}

# Strava Activity Detail API 返回格式
MOCK_DETAIL = {
    "id": 12345678,
    "name": "Morning Ride",
    "type": "Ride",
    "distance": 50000.0,
    "elapsed_time": 7200,
    "start_date": "2024-06-15T08:00:00Z",
    "average_speed": 6.94,
    "max_speed": 12.5,
    "total_elevation_gain": 500.0,
    "average_heartrate": 145.0,
    "max_heartrate": 175,
    "average_watts": 200.0,
    "max_watts": 450,
    "average_cadence": 85.0,
    "calories": 1200.0,
    "weighted_average_watts": 220,
}


# ==================== Fixture ====================

@pytest.fixture()
def strava_db(db):
    """
    扩展 db fixture，额外建 strava_imports 表。

    调度器测试需要这张表，但其他测试不需要。
    用 checkfirst=True 防止重复建表。
    测试结束后清理，不影响其他测试。
    """
    from app.strava.models import StravaImport
    StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
    yield db
    StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)


@pytest.fixture()
def strava_user(db):
    """
    创建一个已绑定 Strava 的测试用户。

    比 test_user fixture 多了 Strava 相关字段：
    athlete_id、access_token、refresh_token、token_expires_at。
    """
    from app.user.models import User
    user = User(
        openid="strava_test_openid",
        is_admin=False,
        strava_athlete_id=99999,
        strava_access_token="fake_access_token",
        strava_refresh_token="fake_refresh_token",
        strava_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def strava_auth_header(strava_user):
    """为 strava_user 生成 JWT 认证头。"""
    from app.user.service import create_token
    token = create_token(strava_user.id)
    return {"Authorization": f"Bearer {token}"}


# ==================== 适配器测试（纯函数，不需要 mock） ====================


class TestStravaAdapter:
    """Strava 适配器（from_streams）的纯函数测试。"""

    def test_from_streams_basic(self):
        """正常的 streams + detail JSON 能正确转成 ParseResult。"""
        from app.parsing.strava_adapter import from_streams
        from app.parsing.types import DataSource, CoordSystem

        result = from_streams(MOCK_STREAMS, MOCK_DETAIL)

        # 验证 trackpoints 数量和基本字段
        assert len(result.trackpoints) == 5
        tp0 = result.trackpoints[0]
        assert tp0.lat == 30.1
        assert tp0.lon == 120.1
        assert tp0.ele == 100
        assert tp0.speed == 5.0
        assert tp0.distance == 0

        # 验证摘要字段（直接取 detail 里的值）
        assert result.summary.distance == 50000.0
        assert result.summary.duration == 7200
        assert result.summary.elevation_gain == 500.0
        assert result.summary.avg_speed == 6.94
        assert result.summary.max_speed == 12.5
        assert result.summary.avg_power == 200.0
        assert result.summary.max_power == 450
        assert result.summary.avg_hr == 145.0
        assert result.summary.max_hr == 175
        assert result.summary.avg_cadence == 85.0
        assert result.summary.calories == 1200.0
        assert result.summary.normalized_power == 220

        # 验证元数据
        assert result.metadata.source == DataSource.STRAVA
        assert result.metadata.coord_system == CoordSystem.WGS84
        assert result.metadata.title == "Morning Ride"
        assert result.metadata.file_hash is None

        # 验证简化轨迹存在
        assert result.simplified_track is not None

    def test_from_streams_missing_optional(self):
        """缺少 heartrate/cadence/watts 等可选流时仍能正常工作。"""
        from app.parsing.strava_adapter import from_streams

        # 只保留必需的三个流 + 海拔和速度（可选但常见）
        minimal_streams = {
            "time": {"data": [0, 5, 10]},
            "distance": {"data": [0, 50, 120]},
            "latlng": {"data": [[30.1, 120.1], [30.2, 120.2], [30.3, 120.3]]},
        }

        # detail 也去掉可选字段
        minimal_detail = {
            "id": 111,
            "name": "Minimal Ride",
            "type": "Ride",
            "distance": 120.0,
            "elapsed_time": 10,
            "start_date": "2024-01-01T00:00:00Z",
            "total_elevation_gain": 0.0,
        }

        result = from_streams(minimal_streams, minimal_detail)

        assert len(result.trackpoints) == 3
        # 可选字段应为 None
        tp0 = result.trackpoints[0]
        assert tp0.hr is None
        assert tp0.cad is None
        assert tp0.power is None
        assert tp0.ele is None
        assert tp0.speed is None

        # 摘要中可选字段也为 None
        assert result.summary.avg_hr is None
        assert result.summary.avg_power is None
        assert result.summary.avg_cadence is None
        assert result.summary.calories is None

    def test_from_streams_empty_latlng(self):
        """latlng 流为空列表时应抛出 StravaAdapterError。"""
        from app.parsing.strava_adapter import from_streams, StravaAdapterError

        empty_streams = {
            "time": {"data": [0, 5]},
            "distance": {"data": [0, 50]},
            "latlng": {"data": []},
        }
        detail = {
            "id": 222,
            "distance": 50.0,
            "elapsed_time": 5,
            "start_date": "2024-01-01T00:00:00Z",
            "total_elevation_gain": 0.0,
        }

        with pytest.raises(StravaAdapterError):
            from_streams(empty_streams, detail)

    def test_from_streams_elapsed_time_zero(self):
        """elapsed_time=0 是合法值，finished_at 应等于 started_at 而非 None。

        回归保护：Python 的 truthiness 陷阱——`if elapsed` 对 0 返回 False。
        代码中用 `if elapsed is not None` 才是正确的写法。
        """
        from app.parsing.strava_adapter import from_streams

        streams = {
            "time": {"data": [0]},
            "distance": {"data": [0]},
            "latlng": {"data": [[30.0, 120.0]]},
        }
        detail = {
            "id": 333,
            "distance": 0.0,
            "elapsed_time": 0,
            "start_date": "2024-06-15T08:00:00Z",
            "total_elevation_gain": 0.0,
        }

        result = from_streams(streams, detail)

        # elapsed_time=0 时 finished_at 应等于 started_at（不是 None）
        assert result.summary.finished_at is not None
        assert result.summary.finished_at == result.summary.started_at
        assert result.summary.duration == 0


# ==================== OAuth 路由测试 ====================


class TestOAuthRoutes:
    """Strava OAuth 相关路由的集成测试。"""

    @patch("app.strava.service.settings")
    def test_authorize_url(self, mock_settings, client, auth_header):
        """GET /api/strava/authorize 应返回包含 state 参数的授权 URL。"""
        # 配置 mock settings，让 generate_authorize_url 不因为空配置报错
        mock_settings.STRAVA_CLIENT_ID = "test_client_id"
        mock_settings.STRAVA_CLIENT_SECRET = "test_secret"
        mock_settings.STRAVA_REDIRECT_URI = "https://example.com/callback"
        mock_settings.JWT_SECRET = "change-me-to-a-random-secret"

        resp = client.get("/api/strava/authorize", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "authorize_url" in data
        url = data["authorize_url"]
        # URL 中应包含 Strava 授权地址和关键参数
        assert "strava.com/oauth/authorize" in url
        assert "client_id=test_client_id" in url
        assert "state=" in url

    def test_strava_status_not_connected(self, client, auth_header, db, test_user):
        """GET /api/strava/status 未绑定 Strava 时返回 connected=false。"""
        resp = client.get("/api/strava/status", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["athlete_id"] is None

    def test_strava_status_connected(self, client, strava_auth_header, db, strava_user):
        """GET /api/strava/status 已绑定 Strava 时返回 connected=true + athlete_id。"""
        resp = client.get("/api/strava/status", headers=strava_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["athlete_id"] == 99999


# ==================== Webhook 路由测试 ====================


class TestWebhookRoutes:
    """Strava Webhook 端点测试。"""

    @patch("app.strava.router.settings")
    def test_webhook_verify_success(self, mock_settings, client):
        """
        GET /api/strava/webhook 正确的 verify_token 应返回 hub.challenge。

        这是 Strava 注册 Webhook 时的验证流程：
        Strava 发过来一个 challenge 字符串，我们原样返回证明"这是我的端点"。
        """
        mock_settings.STRAVA_WEBHOOK_VERIFY_TOKEN = "my_secret_token"

        resp = client.get(
            "/api/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "abc123challenge",
                "hub.verify_token": "my_secret_token",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hub.challenge"] == "abc123challenge"

    @patch("app.strava.router.settings")
    def test_webhook_verify_wrong_token(self, mock_settings, client):
        """GET /api/strava/webhook 错误的 verify_token 应返回 403。"""
        mock_settings.STRAVA_WEBHOOK_VERIFY_TOKEN = "correct_token"

        resp = client.get(
            "/api/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "abc123",
                "hub.verify_token": "wrong_token",
            },
        )
        assert resp.status_code == 403


    @patch("app.strava.router.settings")
    def test_webhook_post_activity_create(self, mock_settings, client, db, test_user):
        """POST /api/strava/webhook activity create 应创建 importing Activity。"""
        from app.activity.models import Activity

        # v4 task-7.4：webhook 加了 subscription_id 校验
        mock_settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = "12345"

        # 给测试用户绑定 Strava
        test_user.strava_athlete_id = 88888
        test_user.strava_access_token = "test"
        db.commit()

        payload = {
            "subscription_id": 12345,
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 99999,
            "owner_id": 88888,
        }

        resp = client.post("/api/strava/webhook", json=payload)
        assert resp.status_code == 200

        # 验证创建了 importing 状态的 Activity
        activity = db.query(Activity).filter_by(strava_activity_id=99999).first()
        assert activity is not None
        assert activity.status == "importing"
        assert activity.user_id == test_user.id

    @patch("app.strava.router.settings")
    def test_webhook_post_unknown_owner(self, mock_settings, client, db):
        """POST /api/strava/webhook 未知 owner_id 应静默忽略（返回 200）。"""
        # v4 task-7.4：webhook 加了 subscription_id 校验
        mock_settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = "12345"

        payload = {
            "subscription_id": 12345,
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 11111,
            "owner_id": 99999999,  # 不存在的 owner
        }

        resp = client.post("/api/strava/webhook", json=payload)
        assert resp.status_code == 200  # Strava 要求始终返回 200

    @patch("app.strava.router.settings")
    def test_webhook_post_activity_delete(self, mock_settings, client, db, test_user):
        """POST /api/strava/webhook activity delete 应删除对应 Activity。"""
        from app.activity.models import Activity

        # v4 task-7.4：webhook 加了 subscription_id 校验
        mock_settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = "12345"

        # 准备：绑定 Strava + 创建一条活动
        test_user.strava_athlete_id = 88888
        db.commit()

        activity = Activity(
            user_id=test_user.id,
            status="completed",
            data_source="strava",
            strava_activity_id=77777,
        )
        db.add(activity)
        db.commit()
        activity_id = activity.id

        payload = {
            "subscription_id": 12345,
            "object_type": "activity",
            "aspect_type": "delete",
            "object_id": 77777,
            "owner_id": 88888,
        }

        resp = client.post("/api/strava/webhook", json=payload)
        assert resp.status_code == 200

        # 验证活动已被删除
        assert db.query(Activity).filter_by(id=activity_id).first() is None


# ==================== 手动同步测试 ====================


class TestManualSync:
    """手动同步（POST /api/strava/sync）测试。"""

    def test_manual_sync_not_connected(self, client, auth_header, db, test_user):
        """POST /api/strava/sync 未绑定 Strava 时应返回 400。"""
        resp = client.post("/api/strava/sync", headers=auth_header)
        assert resp.status_code == 400


# ==================== 导入进度测试 ====================


class TestImportProgress:
    """导入进度（GET /api/strava/import-progress）测试。"""

    def test_import_progress_none(self, client, auth_header, db, test_user, monkeypatch):
        """没有导入任务时应返回 view_status=none（v4 契约）。"""
        # 需要 strava_imports 表存在才能查询
        from app.strava.models import StravaImport
        from app.strava import router as strava_router
        StravaImport.__table__.create(bind=_test_engine, checkfirst=True)
        # mock 掉 router 层的 _redis，避免真连 Redis 导致限速串扰
        redis_mock = MagicMock()
        redis_mock.set.return_value = True
        monkeypatch.setattr(strava_router, "_redis", redis_mock)
        try:
            resp = client.get("/api/strava/import-progress", headers=auth_header)
            assert resp.status_code == 200
            data = resp.json()
            assert data["view_status"] == "none"
            assert data["db_status"] is None
        finally:
            StravaImport.__table__.drop(bind=_test_engine, checkfirst=True)

    def test_import_progress_active(self, client, strava_auth_header, strava_db,
                                     strava_user, monkeypatch):
        """有 active 导入任务时应返回正确的进度信息（v4 契约）。"""
        from app.strava.models import StravaImport
        from app.strava import router as strava_router

        # mock 掉 router 层的 _redis，避免真连 Redis 导致限速串扰
        redis_mock = MagicMock()
        redis_mock.set.return_value = True
        monkeypatch.setattr(strava_router, "_redis", redis_mock)

        # 创建一个正在进行的导入任务
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=99999,
            total_activities=100,
            tier1_completed=100,
            tier2_completed=40,
            tier2_skipped=5,
            status="active",
        )
        strava_db.add(import_task)
        strava_db.commit()

        resp = client.get("/api/strava/import-progress", headers=strava_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        # v4 契约：view_status + db_status + total/completed/tier1_completed
        assert data["view_status"] == "active"
        assert data["db_status"] == "active"
        assert data["total"] == 100
        assert data["tier1_completed"] == 100
        assert data["completed"] == 40


# ==================== 调度器逻辑测试 ====================


class TestImportScheduler:
    """
    导入调度器逻辑测试。

    调度器是后台定时任务，不在 FastAPI 请求上下文中运行，
    所以这里直接调用内部函数，mock StravaClient 的 API 调用。
    """

    @patch("app.strava.import_scheduler.StravaClient")
    def test_scheduler_tier1(self, MockClient, strava_db, strava_user):
        """
        第一层 tick：拉活动列表，为每条活动创建 importing 骨架。

        mock StravaClient.get_athlete_activities 返回 2 条活动，
        验证创建了 2 个 importing 状态的 Activity 记录。
        """
        from app.activity.models import Activity
        from app.strava.models import StravaImport
        from app.strava.import_scheduler import _do_tick

        # 创建导入任务
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=99999,
            status="active",
        )
        strava_db.add(import_task)
        strava_db.commit()

        # mock StravaClient 实例的方法
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.get_athlete_activities.return_value = [
            {"id": 1001, "name": "Ride A", "distance": 30000, "start_date": "2024-06-01T10:00:00Z"},
            {"id": 1002, "name": "Ride B", "distance": 45000, "start_date": "2024-05-15T08:00:00Z"},
        ]

        # 执行一次 tick
        _do_tick(strava_db)

        # 验证创建了 2 个 importing 骨架
        activities = strava_db.query(Activity).filter_by(
            user_id=strava_user.id, status="importing"
        ).all()
        assert len(activities) == 2

        # 验证 strava_activity_id 正确
        strava_ids = {a.strava_activity_id for a in activities}
        assert strava_ids == {1001, 1002}

        # 验证进度更新
        strava_db.refresh(import_task)
        assert import_task.tier1_completed == 2

    @patch("app.strava.import_scheduler.StravaClient")
    def test_scheduler_tier1_dedup(self, MockClient, strava_db, strava_user):
        """
        第一层去重：已存在的 strava_activity_id 应被跳过。

        先手动插入一条 strava_activity_id=2001 的 Activity，
        然后让调度器返回包含 2001 的列表，验证不会重复创建。
        """
        from app.activity.models import Activity
        from app.strava.models import StravaImport
        from app.strava.import_scheduler import _do_tick

        # 预先创建一条已存在的活动
        existing = Activity(
            user_id=strava_user.id,
            status="completed",
            data_source="strava",
            strava_activity_id=2001,
        )
        strava_db.add(existing)
        strava_db.commit()

        # 创建导入任务
        import_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=99999,
            status="active",
        )
        strava_db.add(import_task)
        strava_db.commit()

        # mock：返回一条已存在（2001）和一条新的（2002）
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        mock_instance.get_athlete_activities.return_value = [
            {"id": 2001, "name": "Old Ride", "distance": 10000, "start_date": "2024-01-01T00:00:00Z"},
            {"id": 2002, "name": "New Ride", "distance": 20000, "start_date": "2024-01-02T00:00:00Z"},
        ]

        _do_tick(strava_db)

        # 只创建了 1 条新的，旧的被跳过
        new_activities = strava_db.query(Activity).filter_by(
            strava_activity_id=2002
        ).all()
        assert len(new_activities) == 1

        # 进度只算新增的
        strava_db.refresh(import_task)
        assert import_task.tier1_completed == 1

    def test_scheduler_stale_detection(self, strava_db, strava_user):
        """
        僵尸检测：超过 24 小时未更新的 active 任务应被标记为 paused。

        调度器每次 tick 先检查僵尸任务，把卡住的标记为 paused，
        防止一个出问题的任务永远占着位置不让别人跑。
        """
        from app.strava.models import StravaImport
        from app.strava.import_scheduler import _check_stale_imports

        # 创建一个 25 小时前更新的任务
        stale_task = StravaImport(
            user_id=strava_user.id,
            strava_athlete_id=99999,
            status="active",
        )
        strava_db.add(stale_task)
        strava_db.commit()

        # 手动把 updated_at 改到 25 小时前
        stale_time = datetime.now(timezone.utc) - timedelta(hours=25)
        stale_task.updated_at = stale_time
        strava_db.commit()

        # 执行僵尸检测
        _check_stale_imports(strava_db)

        # 验证状态变为 paused
        strava_db.refresh(stale_task)
        assert stale_task.status == "paused"


# ==================== 集成写入测试 ====================


class TestSaveParseResult:
    """save_parse_result 共享写入函数的集成测试。"""

    def test_save_parse_result(self, db, test_user):
        """
        save_parse_result 应正确把 ParseResult 写入 Activity 统计字段。

        这是 Worker 和调度器共用的数据库写入逻辑，
        验证它能正确把翻译层的输出"归档"到 Activity 表。

        注意：save_parse_result 会写 trackpoints 表，但 conftest 没有建这张表，
        所以这里手动建一张 SQLite 兼容的 trackpoints 简化表。
        """
        from app.activity.models import Activity
        from app.activity.worker import save_parse_result
        from app.parsing.strava_adapter import from_streams

        # 建 trackpoints 表（SQLite 兼容版，用模块顶部定义的 _trackpoints_table）
        _strava_test_metadata.create_all(bind=_test_engine)

        try:
            # 创建一条空壳 Activity
            activity = Activity(
                user_id=test_user.id,
                status="importing",
                file_url=None,
                data_source="strava",
                strava_activity_id=88888,
            )
            db.add(activity)
            db.commit()
            db.refresh(activity)

            # 用适配器生成 ParseResult
            parse_result = from_streams(MOCK_STREAMS, MOCK_DETAIL)

            # 写入
            save_parse_result(db, activity, parse_result)
            db.commit()

            # 验证统计字段已写入
            db.refresh(activity)
            assert activity.distance == 50000.0
            assert activity.duration == 7200
            assert activity.elevation_gain == 500.0
            # avg_speed 应被 ×3.6 转为 km/h：6.94 * 3.6 = 24.984 → round(24.984, 1) = 25.0
            assert activity.avg_speed == 25.0
            # max_speed：12.5 * 3.6 = 45.0
            assert activity.max_speed == 45.0
            assert activity.avg_power == 200.0
            assert activity.max_power == 450
            assert activity.avg_hr == 145.0
            assert activity.max_hr == 175
            assert activity.avg_cadence == 85.0
            assert activity.calories == 1200.0
            assert activity.normalized_power == 220
            assert activity.data_source == "strava"
            # 标题：Activity 没有预设标题时，应取 ParseResult 的 metadata.title
            assert activity.title == "Morning Ride"
        finally:
            _strava_test_metadata.drop_all(bind=_test_engine)
