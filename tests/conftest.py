"""
测试基础设施——"模拟考场"。

真实的后端需要 PostgreSQL、Redis、微信服务器才能跑。
但跑测试时不可能每次都连真数据库、真微信，所以这里搭建一个"模拟环境"：
- 用 SQLite 内存数据库替代 PostgreSQL（轻量、快速、用完即扔）
- 用 mock 函数替代微信登录接口
- 用 FastAPI 的 TestClient 替代真正的 HTTP 请求

好比消防演习：不用真着火，但流程和真救火一模一样。

注意事项：
- conftest.py 是 pytest 的"公共配置文件"，里面的 fixture 所有测试文件自动可用
- 这里创建的 activities 表是简化版（只包含统计测试需要的字段），
  完整版在 Task 3.1 的 Activity 模型里
- 每个测试函数都会拿到一个全新的数据库，互不干扰
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, JSON, MetaData, String, Table,
    Text, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sqlalchemy import event

from app.database import Base, get_db
from app.main import app
from app.user.models import User
from app.user.service import create_token


# ==================== 数据库 fixture ====================

# 用 SQLite 内存数据库做测试：速度快、不需要装任何数据库软件、测试完自动消失
# "check_same_thread=False" 是 SQLite 的特殊要求，允许多线程访问同一个连接
# StaticPool：强制所有连接复用同一个底层连接。
# SQLite 内存数据库的特点是"每个连接独立"，不用 StaticPool 的话，
# 建表的连接和查询的连接可能是两个不同的数据库，导致"表不存在"。
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_test_engine, autocommit=False, autoflush=False)


# 注册假的 PostGIS 函数——让 SQLite 能运行 geoalchemy2 生成的 SQL。
# geoalchemy2 在 INSERT 时会调 GeomFromEWKT()，在 SELECT 时会调 ST_AsEWKB()。
# 这些都是 PostgreSQL/PostGIS 专有函数，SQLite 没有。
# 这里注册"假函数"：原样传递参数，不做任何转换。
# 这样 geoalchemy2 生成的 SQL 能在 SQLite 上跑通，虽然不做真正的空间计算。
#
# 特别注意 ST_AsEWKB / AsEWKB：
# geoalchemy2 在读取 Geometry 列时，会用 ST_AsEWKB() 包住字段，
# 然后尝试把返回值当成十六进制 EWKB 字符串解析（binascii.unhexlify）。
# 如果原样返回 WKT 字符串（如 "SRID=4326;LINESTRING(..."），
# unhexlify 遇到非十六进制字符就会抛 "Non-hexadecimal digit found"。
# 解决方案：返回一个固定的合法 EWKB 十六进制字符串（2 点 LINESTRING，SRID=4326）。
# geoalchemy2 能解析它，不报错，测试中也不需要读取真实的几何坐标。
_FAKE_EWKB = "0102000020E6100000020000003333333333235C408FC2F5285CEF42403333333333235C400000000000F04240"


@event.listens_for(_test_engine, "connect")
def _register_fake_postgis(dbapi_conn, connection_record):
    dbapi_conn.create_function("GeomFromEWKT", 1, lambda x: x)
    dbapi_conn.create_function("ST_GeomFromEWKT", 1, lambda x: x)
    # AsEWKB / ST_AsEWKB 必须返回合法十六进制 EWKB，不能原样返回 WKT
    dbapi_conn.create_function("AsEWKB", 1, lambda x: _FAKE_EWKB)
    dbapi_conn.create_function("ST_AsEWKB", 1, lambda x: _FAKE_EWKB)
    dbapi_conn.create_function("AsText", 1, lambda x: x)
    dbapi_conn.create_function("ST_AsText", 1, lambda x: x)


# 简化版 activities 表——只包含统计测试需要的字段
# 完整版模型在 Task 3.1 中定义，这里是临时替代品
from sqlalchemy import Table, MetaData

_test_metadata = MetaData()

# 完整版 activities 表（SQLite 兼容）
# Activity 模型用了 JSONB 和 Geometry（PostgreSQL 专有），SQLite 不支持，
# 所以这里用 Text 代替 JSONB、省略 Geometry 相关列。
# 字段必须覆盖 Activity ORM 模型的所有列，否则 db.query(Activity) 会报错。
_activities_table = Table(
    "activities",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False),
    Column("title", String(128)),
    Column("status", String(20), default="pending"),
    Column("file_url", Text),              # nullable：Strava 导入的活动无本地文件
    Column("file_hash", String(64)),           # SHA-256 去重哈希
    Column("error_message", Text),
    Column("distance", Float),
    Column("duration", Integer),
    Column("moving_time", Integer),       # Sprint 5 polish：移动时间（去停车）
    Column("elevation_gain", Float),
    Column("avg_speed", Float),
    Column("max_speed", Float),
    Column("avg_power", Float),
    Column("max_power", Float),
    Column("avg_hr", Float),
    Column("max_hr", Float),
    Column("avg_cadence", Float),
    Column("max_cadence", Float),         # Sprint 8 task-1.1：最大踏频
    Column("snapshot_ftp", Integer),      # Sprint 9 task-1：活动锁定的 FTP（W）
    Column("intensity_factor", Float),    # Sprint 9 task-1：IF = NP / snapshot_ftp
    Column("tss", Float),                 # Sprint 9 task-1：TSS 训练分数
    Column("calories", Float),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("simplified_track", Text),   # 替代 JSONB
    Column("splits", Text),             # 替代 JSONB
    Column("power_zones", Text),        # 替代 JSONB
    Column("normalized_power", Float),    # 第 1 期新增：标准化功率
    Column("data_source", String(20)),     # 第 1 期新增：数据来源标记
    Column("activity_type", String(20), default="cycling"),  # 第 4 期新增：活动类型
    Column("strava_activity_id", Integer), # 第 2 期新增：Strava 活动去重 ID
    Column("duplicate_of", Integer),         # Sprint 5 task-2：语义级 dedupe 自引用 FK
    # Sprint 6 task-3：activities.city 起点城市（6 城 + unknown 或 NULL）
    # SQLite 不模拟 CHECK 约束 / CHECK 测试走真 PG（test_activity_city_field.py）
    Column("city", String(32), nullable=True),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

# activity_privacy 表（SQLite 简化版）
# 这里像给每条骑行配一张“门禁卡”：
# 没有卡 = 老数据默认公开；有卡时再看 visibility 决定别人能不能进。
_activity_privacy_table = Table(
    "activity_privacy",
    _test_metadata,
    Column("activity_id", Integer, primary_key=True),
    Column("visibility", String(16), nullable=False, default="public"),
    Column("hide_power", Boolean, nullable=False, default=False),
    Column("hide_heartrate", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)


# 简化版 segments 表（SQLite 兼容）
# Segment 模型用了 PostGIS Geometry（LINESTRING），SQLite 不支持，
# 这里用 Text 代替，并设为 nullable 方便测试插入。
_segments_table = Table(
    "segments",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(128), nullable=False),
    Column("description", Text),
    Column("distance", Float, nullable=False),
    Column("elevation_gain", Float),
    Column("elevation_loss", Float),                   # 新增：累计海拔下降
    Column("avg_gradient", Float),                     # 新增：平均坡度
    Column("elevation_profile", Text),                 # 新增：海拔采样 JSON 数组
    Column("start_lat", Float, nullable=False),
    Column("start_lon", Float, nullable=False),
    Column("end_lat", Float, nullable=False),
    Column("end_lon", Float, nullable=False),
    Column("reference_line", Text),          # 替代 Geometry
    Column("match_tolerance", Float, default=50.0),
    Column("min_match_ratio", Float, default=0.8),
    Column("difficulty", String(16), default="medium"),
    Column("max_gradient", Float),
    Column("city", String(32), default="unknown"),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

# segment_efforts 表
_segment_efforts_table = Table(
    "segment_efforts",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("segment_id", Integer, nullable=False),
    Column("activity_id", Integer, nullable=False),
    Column("user_id", Integer, nullable=False),
    Column("elapsed_time", Integer, nullable=False),
    Column("avg_speed", Float),
    Column("avg_power", Float),
    Column("start_index", Integer, nullable=False),
    Column("end_index", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

# segment_curation_pool 表（SQLite 简化版）
# 3.A.2 admin 候选池 endpoint 会通过真实 ORM 模型查询这张表。
# 测试环境只需要字段形状一致，不启用 PostgreSQL 外键 / 索引细节。
_segment_curation_pool_table = Table(
    "segment_curation_pool",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("segment_id", Integer, nullable=False),
    Column("pool_score", Float, nullable=False),
    Column("pool_reason", String(64)),
    Column("selected_for_v5", Boolean, nullable=False, default=False),
    Column("selected_by_user_id", Integer),
    Column("selected_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    UniqueConstraint("segment_id", name="uq_curation_pool_segment_id"),
)

# segment_ai_drafts 表（SQLite 简化版）
# 3.A.3 admin AI 草稿审核 endpoint 会通过 SegmentAiDraft ORM 查询这张表。
# 测试环境只保留字段形状，CHECK / UNIQUE / FK 约束交给真 PG 集成测试覆盖。
_segment_ai_drafts_table = Table(
    "segment_ai_drafts",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("segment_id", Integer, nullable=False),
    Column("ai_draft_text", Text, nullable=False),
    Column("human_edited_text", Text),
    Column("status", String(16), nullable=False, default="pending"),
    Column("editor_user_id", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

# 通知表（SQLite 简化版，省略外键和 CHECK 约束以避免 SQLite 兼容性问题）
# 注意：必须保留 UniqueConstraint，否则幂等测试（IntegrityError 防重复）无法验证
_notifications_table = Table(
    "notifications",
    _test_metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, nullable=False),
    # event_type v5 task-0.6：扩长 String(20) → String(32) 容下 'progress_monthly_summary'(24)
    Column("event_type", String(32), nullable=False),
    # 第 4 期（task-7.1）外键改成 SET NULL 后 segment_id 允许 NULL
    Column("segment_id", Integer, nullable=True),
    Column("activity_id", Integer, nullable=True),
    Column("effort_id", Integer, nullable=True),
    Column("elapsed_time", Integer, nullable=True),
    Column("rank", Integer, nullable=True),
    Column("rival_user_id", Integer, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True)),
    # 第 4 期（task-7.1）新增：已读状态。SQLite 用 Integer 代替 Boolean
    # 注意必须给 server_default，否则 test_notification fixture 不传 is_read 时 NOT NULL 违反
    Column("is_read", Integer, nullable=False, server_default="0"),
    # v5 task-0.6 新增：progress 类通知 payload（PG 用 JSONB，SQLite 用 sa.JSON 抽象）
    Column("payload", JSON, nullable=True),
    UniqueConstraint("effort_id", "event_type", name="uq_notif_effort_type"),
)


@pytest.fixture()
def db():
    """
    提供一个干净的测试数据库 session。

    每个测试函数调用前：建表 → 开 session
    测试结束后：关 session → 删表
    这样每个测试都在"白纸"上跑，互不干扰。
    """
    # 建表：只建 users 表（Activity 模型用了 PostgreSQL 专有的 JSONB 和 Geometry，
    # SQLite 不支持，所以 activities 表用下面的手动简化版 _activities_table 代替）
    from app.user.models import User
    # Sprint 9 task-8：BreakthroughEvent ORM 字段都是 SQLite 兼容（Integer/String/DateTime）
    # 直接建表 / 让 ORM 测试能跑（不需要简化版 _breakthrough_events_table）
    from app.activity.models import BreakthroughEvent
    User.__table__.create(bind=_test_engine, checkfirst=True)
    _test_metadata.create_all(bind=_test_engine)
    BreakthroughEvent.__table__.create(bind=_test_engine, checkfirst=True)

    session = _TestSession()
    try:
        yield session
    finally:
        session.close()
        # 删表：测试结束后把所有表清掉，下次重建
        BreakthroughEvent.__table__.drop(bind=_test_engine, checkfirst=True)
        _test_metadata.drop_all(bind=_test_engine)
        User.__table__.drop(bind=_test_engine, checkfirst=True)


@pytest.fixture()
def client(db):
    """
    提供一个 FastAPI 测试客户端。

    TestClient 可以直接发 HTTP 请求给 FastAPI 应用，
    不需要启动真正的服务器，就像在本地模拟打电话。

    关键：用 dependency_overrides 把真实数据库替换成测试数据库，
    这样所有请求都操作内存中的 SQLite，不碰真数据库。
    """

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ==================== 用户 fixture ====================

@pytest.fixture()
def test_user(db):
    """
    创建一个测试用户并返回。
    大多数测试都需要一个已存在的用户，这个 fixture 省去重复创建。
    """
    user = User(openid="test_openid_123", is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def auth_header(test_user):
    """
    生成一个带 JWT 的请求头。
    需要登录才能访问的接口（profile、stats）都要用这个。
    """
    token = create_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_user(db):
    """
    创建一个管理员测试用户。
    3.A.x admin 系列任务共用，避免每个测试文件重复造管理员。
    """
    user = User(openid="test_admin", is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_header(admin_user):
    """生成管理员 JWT 请求头。"""
    token = create_token(admin_user.id)
    return {"Authorization": f"Bearer {token}"}


# ==================== 统计测试数据 fixture ====================

@pytest.fixture()
def activities_data(db, test_user):
    """
    往 activities 表插入测试骑行数据，用于统计接口的测试。

    插入 3 条记录：
    - 2 条 completed 状态（今天之内）：用于验证聚合正确性
    - 1 条 pending 状态：应该被统计忽略（只统计 completed）

    时间基准用"今天零点"而不是"本周一"，避免月初几天运行时
    本周一落在上个月导致 period=month 测试失败。
    """
    beijing_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(beijing_tz)
    # 用今天零点做基准：保证数据一定在"本周"和"本月"范围内
    today_start = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    # 保留 tzinfo（第 5 期 task-0.1）：DB 列已 tz-aware，写入也用 aware datetime
    today_utc = today_start.astimezone(timezone.utc)

    # 第 1 条：已完成，今天上午，距离 50km，爬升 500m，时间 1h
    db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            title="晨骑",
            status="completed",
            file_url="test1.gpx",
            distance=50000.0,       # 50km = 50000m
            duration=3600,          # 1小时 = 3600秒
            elevation_gain=500.0,   # 500m
            started_at=today_utc + timedelta(hours=2),  # 今天凌晨2点UTC
        )
    )

    # 第 2 条：已完成，今天稍晚，距离 30km，爬升 300m，时间 45min
    db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            title="夜骑",
            status="completed",
            file_url="test2.gpx",
            distance=30000.0,       # 30km
            duration=2700,          # 45分钟
            elevation_gain=300.0,
            started_at=today_utc + timedelta(hours=6),  # 今天早上6点UTC
        )
    )

    # 第 3 条：pending 状态，应该被忽略
    db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            title="上传中",
            status="pending",
            file_url="test3.gpx",
            distance=20000.0,
            duration=1800,
            elevation_gain=200.0,
            started_at=today_utc + timedelta(hours=8),
        )
    )

    db.commit()

    # 返回预期的聚合结果（只算 completed 的两条）
    return {
        "total_distance_m": 80000.0,    # 50000 + 30000
        "total_distance_km": 80.0,       # 80000 / 1000
        "total_rides": 2,
        "total_elevation": 800.0,        # 500 + 300
        "total_duration": 6300,          # 3600 + 2700
    }


@pytest.fixture()
def last_month_activity(db, test_user):
    """
    插入一条上个月的已完成骑行记录。
    用于测试 period=month 只统计本月数据（上个月的不应该被包含）。
    """
    beijing_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(beijing_tz)

    # 上个月 15 号
    if now_bj.month == 1:
        last_month = now_bj.replace(year=now_bj.year - 1, month=12, day=15,
                                     hour=12, minute=0, second=0, microsecond=0)
    else:
        last_month = now_bj.replace(month=now_bj.month - 1, day=15,
                                     hour=12, minute=0, second=0, microsecond=0)
    # 保留 tzinfo（第 5 期 task-0.1）：DB 列已 tz-aware，写入也用 aware datetime
    last_month_utc = last_month.astimezone(timezone.utc)

    db.execute(
        _activities_table.insert().values(
            user_id=test_user.id,
            title="上月骑行",
            status="completed",
            file_url="old.gpx",
            distance=100000.0,      # 100km
            duration=14400,         # 4小时
            elevation_gain=1000.0,
            started_at=last_month_utc,
        )
    )
    db.commit()
