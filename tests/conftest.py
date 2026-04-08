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
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


# 简化版 activities 表——只包含统计测试需要的字段
# 完整版模型在 Task 3.1 中定义，这里是临时替代品
from sqlalchemy import Table, MetaData

_test_metadata = MetaData()
_activities_table = Table(
    "activities",
    _test_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False),
    Column("title", String(128)),
    Column("status", String(20), default="pending"),
    Column("file_url", Text, default=""),
    Column("distance", Float),
    Column("duration", Integer),
    Column("elevation_gain", Float),
    Column("started_at", DateTime),
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
    User.__table__.create(bind=_test_engine, checkfirst=True)
    _test_metadata.create_all(bind=_test_engine)

    session = _TestSession()
    try:
        yield session
    finally:
        session.close()
        # 删表：测试结束后把所有表清掉，下次重建
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
    user = User(openid="test_openid_123")
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
    today_utc = today_start.astimezone(timezone.utc).replace(tzinfo=None)

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
    last_month_utc = last_month.astimezone(timezone.utc).replace(tzinfo=None)

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
