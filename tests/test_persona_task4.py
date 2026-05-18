"""Persona Engine task-4：worker hook helper + endpoint + scheduler 测试。

按 plan task-4 §测试要求 9 条覆盖：
1-3. worker hook helper（_query_weekly_count / _detect_pr / _query_total_distance）
4. worker hook 失败兜底（CRITICAL / 故意让 persona 抛错 → activity 不挂）
5-7. endpoint /output 真 / null / /recent
8-9. scheduler silence + milestone 函数

防火墙红线：
- 用独立 in-memory SQLite + 只建 persona 表 + 必要业务表
- mock persona_service 不打补丁业务 service / 防意外影响
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.user.models import User
from app.user.service import create_token
from app.activity.models import Activity  # noqa: F401
from app.agent.persona.models import PersonaOutput, PersonaTemplate
from app.agent.persona.trigger_router import PersonaEvent
from app.activity.worker import (
    _query_weekly_count,
    _detect_pr,
    _query_total_distance,
)


# ─── 独立 persona DB fixture ───


@pytest.fixture()
def persona_db():
    """独立 in-memory SQLite + 建 persona + users 表（防 endpoint 未来加 JOIN 时炸 / Claude B I3）。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 建 users + persona 2 表（不依赖 PostGIS / JSONB / 加 users 防 FK 解析 NoReferencedTableError）
    persona_tables = [
        Base.metadata.tables[t]
        for t in ("users", "persona_outputs", "persona_templates")
    ]
    Base.metadata.create_all(bind=engine, tables=persona_tables)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()

    # seed 几条 PR 模板
    for text in ["今天嗑药了？", "今天你最猛。", "数据有点过分。",
                 "前 1% 的一天。", "把自己拉爆了。", "8500km 里这一天。"]:
        db.add(PersonaTemplate(scene_type="pr", segment=None, template_text=text, weight=1, active=True))
    # silence + surprise 模板
    db.add(PersonaTemplate(scene_type="silence", segment=None, template_text="最近去哪儿了。", weight=1, active=True))
    db.add(PersonaTemplate(scene_type="surprise", segment="milestone", template_text="破万的人不多。", weight=1, active=True))
    db.add(PersonaTemplate(scene_type="surprise", segment="solar_term", template_text="立秋了，凉快下来了。", weight=1, active=True))
    db.commit()

    yield db
    db.close()
    engine.dispose()


# ════════════════════════════════════════════════════
# Section A：worker hook helper（test 1-3 / 用 conftest.db）
# ════════════════════════════════════════════════════


@pytest.fixture()
def worker_db_with_user(db):
    """conftest.db + 1 个测试用户 + 几条 activity。"""
    user = User(openid="hook_test_user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, user


def test_query_weekly_count(worker_db_with_user):
    """本周内 cycling 活动计数（防 weekly_count helper 回退）。

    插 3 条今天 cycling + 1 条 30 天前 → 本周计数 ≥ 1（取决于今天是周几）。
    精确数字依赖"今天周几" / 用 >= 1 + < 4 防回退 / 不卡死 weekday 边界。
    """
    from sqlalchemy import text as sql_text
    db, user = worker_db_with_user
    now = datetime.now(timezone.utc)
    # 今天 3 条
    for i in range(3):
        db.execute(sql_text(
            "INSERT INTO activities (user_id, started_at, activity_type, status) "
            "VALUES (:uid, :st, 'cycling', 'completed')"
        ), {"uid": user.id, "st": now})
    # 30 天前 1 条（不可能在本周）
    db.execute(sql_text(
        "INSERT INTO activities (user_id, started_at, activity_type, status) "
        "VALUES (:uid, :st, 'cycling', 'completed')"
    ), {"uid": user.id, "st": now - timedelta(days=30)})
    db.commit()

    count = _query_weekly_count(user.id, db)
    # 防回退断言：今天 3 条都在本周 + 30 天前那条不算
    assert count == 3


def test_query_total_distance(worker_db_with_user):
    """累计 cycling 距离 sum。"""
    from sqlalchemy import text as sql_text
    db, user = worker_db_with_user
    now = datetime.now(timezone.utc)
    for d in [10000, 20000, 30000]:
        db.execute(sql_text(
            "INSERT INTO activities (user_id, started_at, distance, activity_type, status) "
            "VALUES (:uid, :st, :d, 'cycling', 'completed')"
        ), {"uid": user.id, "st": now, "d": d})
    db.commit()

    total = _query_total_distance(user.id, db)
    assert total == 60_000


def test_detect_pr_first_activity(worker_db_with_user):
    """用户第一条活动 = PR（无历史可比）。"""
    db, user = worker_db_with_user
    fake_activity = MagicMock()
    fake_activity.id = 999
    fake_activity.distance = 50_000
    fake_activity.elevation_gain = 500
    fake_activity.duration = 7200
    fake_activity.normalized_power = 200

    assert _detect_pr(fake_activity, user.id, db) is True


# ════════════════════════════════════════════════════
# Section B：worker hook 失败兜底（CRITICAL / test 4）
# ════════════════════════════════════════════════════


def test_worker_hook_persona_failure_does_not_break_activity(persona_db):
    """persona service 抛错 → service 顶层 catch 返 None / worker 不应被传染。

    模拟：直接调 service.generate_persona_output / mock template_lib 抛 Exception
    验证：返 None 不抛 / 调用方（worker）即可继续 db.commit()。
    """
    from app.agent.persona import service

    event = PersonaEvent(
        type="activity_uploaded",
        activity_data={"id": 1, "is_pr": True, "distance": 40_000, "started_at": "2026-05-18T10:00:00+00:00"},
        user_data={"user_id": 1, "total_distance_m": 8_500_000},
        timestamp=datetime.now(timezone.utc),
    )
    with patch(
        "app.agent.persona.service.template_lib.get_templates_for_scene",
        side_effect=Exception("boom"),
    ):
        result = service.generate_persona_output(event, persona_db)
    assert result is None  # 失败兜底返 None / 不抛


# ════════════════════════════════════════════════════
# Section C：endpoint /output + /recent（test 5-7 / 用独立 SQLite + dependency_overrides）
# ════════════════════════════════════════════════════


@pytest.fixture()
def endpoint_client_with_persona(persona_db):
    """独立 SQLite engine + 自建 TestClient + dependency_overrides 注入 persona_db。"""
    # persona_db 已建 persona_outputs + persona_templates 表
    # 但 endpoint 用 get_current_user → 需要 token / 我们 mock get_current_user 替代

    from app.dependencies import get_current_user

    def _override_db():
        yield persona_db

    def _override_user():
        return 1  # 固定 user_id=1

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_endpoint_output_returns_recent_text(persona_db, endpoint_client_with_persona):
    """GET /api/persona/output?scene_type=pr → 返最近一条 pr 文案。"""
    out = PersonaOutput(
        user_id=1, scene_type="pr", template_id=100,
        text_snapshot="今天嗑药了？",
        shown_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    persona_db.add(out)
    persona_db.commit()

    resp = endpoint_client_with_persona.get("/api/persona/output?scene_type=pr")
    assert resp.status_code == 200
    data = resp.json()
    assert data["template_text"] == "今天嗑药了？"
    assert data["scene_type"] == "pr"


def test_endpoint_output_returns_null_when_empty(endpoint_client_with_persona):
    """用户无 persona_outputs → 返 200 + template_text=null（不返 404）。"""
    resp = endpoint_client_with_persona.get("/api/persona/output?scene_type=pr")
    assert resp.status_code == 200
    data = resp.json()
    assert data["template_text"] is None
    assert data["scene_type"] == "pr"


def test_endpoint_recent_returns_list(persona_db, endpoint_client_with_persona):
    """GET /api/persona/recent?limit=5 → 返 list 5 条以内。"""
    for i in range(7):
        persona_db.add(PersonaOutput(
            user_id=1, scene_type="pr", template_id=i,
            text_snapshot=f"text_{i}",
            shown_at=datetime.now(timezone.utc) - timedelta(hours=i),
        ))
    persona_db.commit()

    resp = endpoint_client_with_persona.get("/api/persona/recent?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 5


# ════════════════════════════════════════════════════
# Section D：scheduler silence + milestone（test 8-9）
# ════════════════════════════════════════════════════


def test_silence_scanner_query_silent_users(worker_db_with_user):
    """silence scanner _query_silent_users 找 >= 7 天没骑的用户。"""
    from scripts.persona_silence_scanner import _query_silent_users
    from sqlalchemy import text as sql_text

    db, user = worker_db_with_user
    # 插一条 10 天前的 cycling
    db.execute(sql_text(
        "INSERT INTO activities (user_id, started_at, activity_type, status) "
        "VALUES (:uid, :st, 'cycling', 'completed')"
    ), {"uid": user.id, "st": datetime.now(timezone.utc) - timedelta(days=10)})
    db.commit()

    silent = _query_silent_users(db)
    assert len(silent) == 1
    silent_user_id, days = silent[0]
    assert silent_user_id == user.id
    assert days >= 7


def test_milestone_scanner_check_solar_term():
    """milestone scanner _check_solar_term 节气日历正确。"""
    from datetime import date
    from scripts.persona_milestone_scanner import _check_solar_term

    # 2026 立秋 8 月 8 日
    assert _check_solar_term(date(2026, 8, 8)) == "立秋"
    # 非节气日返 None
    assert _check_solar_term(date(2026, 6, 15)) is None
