"""Persona Engine 回填脚本测试（2026-05-20 Tim 拍按当时还原后）。

测试 3 条：
1. _is_pr_from_row 第一条活动算 PR（max_*_before 全 NULL）
2. _is_pr_from_row 后续活动按 4 字段任一打破历史 max 判 PR
3. service.get_latest_output_for_scene 带 activity_id 不限 24h（便利贴语义）
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.user.models import User  # noqa: F401
from app.activity.models import Activity  # noqa: F401
from app.agent.persona.models import PersonaOutput
from app.agent.persona import service as persona_service

from scripts.persona_backfill import _is_pr_from_row


# ─── Section A：_is_pr_from_row PR 判定 ───


def test_is_pr_first_activity_returns_true():
    """第一条活动 / max_*_before 全 NULL → PR。"""
    row = MagicMock(
        distance=50_000, elevation_gain=500, duration=7200, normalized_power=200,
        max_distance_before=None,
        max_elev_before=None,
        max_duration_before=None,
        max_np_before=None,
    )
    assert _is_pr_from_row(row) is True


def test_is_pr_distance_breaks_max():
    """距离打破历史 max → PR。"""
    row = MagicMock(
        distance=80_000,
        elevation_gain=500, duration=7200, normalized_power=200,
        max_distance_before=70_000,  # 本次 80 > 历史 70 = PR
        max_elev_before=600,
        max_duration_before=8000,
        max_np_before=250,
    )
    assert _is_pr_from_row(row) is True


def test_is_pr_not_breaking_any_field():
    """4 字段都没打破历史 max → 非 PR。"""
    row = MagicMock(
        distance=40_000,
        elevation_gain=300,
        duration=5000,
        normalized_power=180,
        max_distance_before=80_000,
        max_elev_before=600,
        max_duration_before=8000,
        max_np_before=250,
    )
    assert _is_pr_from_row(row) is False


def test_is_pr_elevation_breaks_max():
    """爬升打破历史 max（距离没打破）→ PR。"""
    row = MagicMock(
        distance=40_000,
        elevation_gain=900,  # 本次 900 > 历史 600 = PR
        duration=5000, normalized_power=180,
        max_distance_before=80_000,
        max_elev_before=600,
        max_duration_before=8000,
        max_np_before=250,
    )
    assert _is_pr_from_row(row) is True


# ─── Section B：endpoint activity_id 不限 24h（便利贴）vs 不带 activity_id 限 24h（朋友圈）───


@pytest.fixture()
def isolated_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    persona_tables = [
        Base.metadata.tables[t]
        for t in ("users", "persona_outputs", "persona_templates")
    ]
    Base.metadata.create_all(bind=engine, tables=persona_tables)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    yield db
    db.close()
    engine.dispose()


def test_endpoint_with_activity_id_ignores_24h_window(isolated_db):
    """便利贴语义：带 activity_id 时不限 24h / 拿到 30 天前的记录。"""
    old_record = PersonaOutput(
        user_id=1, scene_type="pr", template_id=100,
        text_snapshot="今天嗑药了？",
        activity_id=42,
        shown_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    isolated_db.add(old_record)
    isolated_db.commit()

    # 带 activity_id → 不限时间 → 拿到 30 天前的
    result = persona_service.get_latest_output_for_scene(
        isolated_db, user_id=1, scene_type="pr", activity_id=42,
    )
    assert result is not None
    assert result.text_snapshot == "今天嗑药了？"


def test_endpoint_without_activity_id_still_limited_to_24h(isolated_db):
    """朋友圈语义：不带 activity_id 时仍限 24h / 30 天前的记录返 None。"""
    old_record = PersonaOutput(
        user_id=1, scene_type="pr", template_id=100,
        text_snapshot="今天嗑药了？",
        activity_id=None,
        shown_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    isolated_db.add(old_record)
    isolated_db.commit()

    # 不带 activity_id → 限 24h → 30 天前返 None
    result = persona_service.get_latest_output_for_scene(
        isolated_db, user_id=1, scene_type="pr",
    )
    assert result is None


def test_endpoint_activity_id_match_not_overridden_by_recent_null(isolated_db):
    """便利贴 prefer activity_id 命中 / 不被更晚的通用 NPC 覆盖（Codex C2 回归）。

    场景：活动 #42 回填了一条 30 天前的精确 NPC / 上周通用 profile_open NPC 也写了一条
    用户打开活动 #42 详情页 / 应拿回填的精确 NPC / 不是 7 天前的通用 NPC。
    """
    exact = PersonaOutput(
        user_id=1, scene_type="pr", template_id=100,
        text_snapshot="今天嗑药了？",
        activity_id=42,
        shown_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    later_generic = PersonaOutput(
        user_id=1, scene_type="pr", template_id=200,
        text_snapshot="数据有点过分。",
        activity_id=None,
        shown_at=datetime.now(timezone.utc) - timedelta(days=7),
    )
    isolated_db.add_all([exact, later_generic])
    isolated_db.commit()

    result = persona_service.get_latest_output_for_scene(
        isolated_db, user_id=1, scene_type="pr", activity_id=42,
    )
    assert result is not None
    assert result.text_snapshot == "今天嗑药了？"  # 精确命中 / 不是更晚的通用
