"""Persona Engine task-3：trigger_router + filters + cache + service 12+ pytest。

按 plan task-3 §测试要求覆盖 12 条 / 实施合并 1 个测试文件（router/filters/cache/service
各 section / 减少文件数 + 共享 fixture）。

覆盖：
1-3. route 7 种 event 路由（PR / 极端优先段位 / 普通段位 / 连骑 / 沉寂 / 错误 / 里程碑）
4-7. filter 检查（反例命中 / 长度 < 5 / 长度 > 25 / 长度合格 / emoji）
8-9. cache 7 天去重（最近用过 / 8 天前不算）
10. service 端到端（mock event → 返合法文案）
11. service 失败兜底（template_lib 抛错 → 返 None 不抛）
12. service 不传染（cache 抛错 → 主流仍返合法文案）

防火墙红线：
- 用独立 in-memory SQLite + 只建 persona_outputs + persona_templates 表
- mock 不打补丁业务 service / 只对 persona 内部模块打补丁
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.agent.persona import service, cache, filters, trigger_router
from app.agent.persona.models import PersonaTemplate, PersonaOutput
from app.agent.persona.trigger_router import PersonaEvent, route
# 显式 import 业务 ORM 让 Base.metadata 含 users / activities 表声明
# 否则 persona_outputs FK 引用解析时 NoReferencedTableError（Claude B 抓）
from app.user.models import User  # noqa: F401
from app.activity.models import Activity  # noqa: F401


# ─── fixture：独立 in-memory SQLite + seed 少量模板 ───


@pytest.fixture()
def persona_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    persona_tables = [
        Base.metadata.tables[t]
        for t in ("persona_outputs", "persona_templates")
    ]
    Base.metadata.create_all(bind=engine, tables=persona_tables)

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()

    # seed 几条文案（覆盖测试用到的 scene_type / PR 6 条对照 plan ≥ 5 红线 / Claude A 抓 I2）
    seeds = [
        ("pr", None, "今天嗑药了？"),
        ("pr", None, "今天你最猛。"),
        ("pr", None, "数据有点过分。"),
        ("pr", None, "前 1% 的一天。"),
        ("pr", None, "把自己拉爆了。"),
        ("pr", None, "8500km 里这一天。"),
        ("segment_distance", "veteran_normal", "40km。蹬两脚意思意思。"),
        ("extreme", "night", "又是夜骑党。"),
        ("consecutive_high", None, "把膝盖磨成粉了？"),
    ]
    for scene_type, segment, text in seeds:
        db.add(PersonaTemplate(
            scene_type=scene_type,
            segment=segment,
            template_text=text,
            weight=1,
            active=True,
        ))
    db.commit()

    yield db
    db.close()
    engine.dispose()


def _make_event(
    type_: str = "activity_uploaded",
    activity_data: dict = None,
    user_data: dict = None,
    error_code: str = None,
) -> PersonaEvent:
    return PersonaEvent(
        type=type_,
        activity_data=activity_data,
        user_data=user_data or {"user_id": 1, "total_distance_m": 8_500_000},
        timestamp=datetime.now(timezone.utc),
        error_code=error_code,
    )


# ════════════════════════════════════════════════════
# Section A：trigger_router 路由（test 1-3）
# ════════════════════════════════════════════════════


def test_route_pr_priority_over_extreme():
    """PR 且夜骑 → 走 'pr' 优先（plan 设计 / PR 优先级最高）。"""
    event = _make_event(
        activity_data={
            "id": 1,
            "is_pr": True,
            "distance": 40_000,
            "started_at": "2026-05-18T23:30:00+00:00",  # 夜骑 hour
        },
    )
    decision = route(event)
    assert decision is not None
    assert decision.scene_type == "pr"
    assert decision.segment is None


def test_route_extreme_priority_over_segment_distance():
    """非 PR / 夜骑 80km → 走 'extreme/night' 不走 'segment_distance'（极端优先段位）。"""
    event = _make_event(
        activity_data={
            "id": 2,
            "is_pr": False,
            "distance": 80_000,
            "started_at": "2026-05-18T23:30:00+00:00",
        },
    )
    decision = route(event)
    assert decision is not None
    assert decision.scene_type == "extreme"
    assert decision.segment == "night"


def test_route_segment_distance_normal_path():
    """普通 40km + veteran → 'segment_distance/veteran_normal'。"""
    event = _make_event(
        activity_data={
            "id": 3,
            "is_pr": False,
            "distance": 40_000,
            "started_at": "2026-05-18T10:00:00+00:00",
        },
        user_data={"user_id": 1, "total_distance_m": 8_500_000},
    )
    decision = route(event)
    assert decision is not None
    assert decision.scene_type == "segment_distance"
    assert decision.segment == "veteran_normal"


def test_route_consecutive_high():
    """weekly_count >= 5 → 'consecutive_high'。"""
    event = _make_event(
        type_="consecutive_high_detected",
        user_data={"user_id": 1, "weekly_count": 5},
    )
    decision = route(event)
    assert decision is not None
    assert decision.scene_type == "consecutive_high"


def test_route_silence_threshold():
    """last_activity_days >= 7 → 'silence' / < 7 返 None。"""
    e1 = _make_event(
        type_="silence_detected",
        user_data={"user_id": 1, "last_activity_days": 7},
    )
    assert route(e1).scene_type == "silence"

    e2 = _make_event(
        type_="silence_detected",
        user_data={"user_id": 1, "last_activity_days": 6},
    )
    assert route(e2) is None


def test_route_error_state_with_code():
    """error_state + error_code='network_down' → 'empty_error/network_down'。"""
    event = _make_event(
        type_="error_state",
        user_data={"user_id": 1},
        error_code="network_down",
    )
    decision = route(event)
    assert decision is not None
    assert decision.scene_type == "empty_error"
    assert decision.segment == "network_down"


def test_route_unknown_type_returns_none():
    """未识别 event type → 返 None / 不抛错。"""
    event = _make_event(
        type_="bogus_event_xyz",
        user_data={"user_id": 1},
    )
    assert route(event) is None


def test_route_milestone_reached_uses_user_data():
    """milestone_type 从 user_data 读 / 不是 activity_data（spec line 90 / Claude A 抓 C2）。"""
    event = _make_event(
        type_="milestone_reached",
        user_data={"user_id": 1, "milestone_type": "anniversary"},
    )
    decision = route(event)
    assert decision is not None
    assert decision.scene_type == "surprise"
    assert decision.segment == "anniversary"

    # milestone_type 缺失 → 返 None
    event2 = _make_event(
        type_="milestone_reached",
        user_data={"user_id": 1},
    )
    assert route(event2) is None


@pytest.mark.parametrize("hour, expected_segment", [
    (23, "night"),
    (0, "night"),
    (3, "night"),
    (4, "night"),   # 边界 / plan line 85 "23-04 点" / Claude B + Codex 抓
    (5, "early"),
    (6, None),      # 6 点后 40km 正常路径 / 走段位
])
def test_route_night_early_boundary(hour, expected_segment):
    """夜骑 23-04 边界 + early 仅 05:00-05:59 / spec line 85。"""
    event = _make_event(
        activity_data={
            "id": 1, "is_pr": False, "distance": 40_000,
            "started_at": f"2026-05-18T{hour:02d}:30:00+00:00",
        },
    )
    decision = route(event)
    if expected_segment is None:
        # 6 点正常时段 → 走 segment_distance（不是 extreme）
        assert decision.scene_type == "segment_distance"
    else:
        assert decision.scene_type == "extreme"
        assert decision.segment == expected_segment


# ════════════════════════════════════════════════════
# Section B：filters（test 4-7）
# ════════════════════════════════════════════════════


def test_filter_check_anti_pattern_hits():
    """命中宪法 §3 反例关键词 → check_anti_pattern 返 True（应 reject）。"""
    assert filters.check_anti_pattern("恭喜你完成 PR")
    assert filters.check_anti_pattern("今天棒棒哒！")
    assert filters.check_anti_pattern("您还没有上传活动")
    assert filters.check_anti_pattern("相当于绕地球 1/5 圈")
    assert filters.check_anti_pattern("yyds 这数据")
    # "亲"独立关键词 / 不止"亲爱的"（Claude A 抓 C1）
    assert filters.check_anti_pattern("亲~最近怎么没看到你呀")


@pytest.mark.parametrize("text, expected", [
    ("稳。", False),       # 2 字 < 5
    ("x" * 4, False),      # 4 字 < 5 边界
    ("x" * 5, True),       # 5 字 ✓ 边界
    ("今天嗑药了？", True), # 6 字 ✓
    ("x" * 25, True),      # 25 字 ✓ 上边界
    ("x" * 26, False),     # 26 字 > 25
])
def test_filter_check_length_boundaries(text, expected):
    """长度边界 4/5/25/26 全 parametrize（Codex I4）。"""
    assert filters.check_length(text) == expected


def test_filter_check_anti_pattern_safe():
    """金标尺文案不命中反例。"""
    assert not filters.check_anti_pattern("今天嗑药了？")
    assert not filters.check_anti_pattern("撒个尿就回了。")
    assert not filters.check_anti_pattern("8500km 里这一天。")


def test_filter_check_length_too_short():
    """< 5 字 → False (reject)。"""
    assert not filters.check_length("稳。")
    assert not filters.check_length("继续")


def test_filter_check_length_too_long():
    """> 25 字 → False (reject)。"""
    assert not filters.check_length("x" * 26)


def test_filter_check_length_in_sweet_spot():
    """5-25 字 → True (合格)。"""
    assert filters.check_length("今天嗑药了？")  # 6
    assert filters.check_length("撒个尿就回了。")  # 7
    assert filters.check_length("8500km 里这一天。")  # 13


def test_filter_emoji_detection():
    """emoji / 颜文字 → is_safe 返 False。"""
    assert not filters.is_safe("今天 80km 😄 不错")
    assert not filters.is_safe("今天 :) 80km。")
    assert not filters.is_safe("【高光】今天 80km。")


# ════════════════════════════════════════════════════
# Section C：cache（test 8-9）
# ════════════════════════════════════════════════════


def test_cache_record_and_get_recent(persona_db):
    """record_output 后 get_recent_outputs 返该 template_id。"""
    cache.record_output(
        persona_db, user_id=1, scene_type="pr", template_id=100,
        text_snapshot="今天嗑药了？",
    )
    persona_db.commit()

    recent = cache.get_recent_outputs(persona_db, user_id=1, scene_type="pr", days=7)
    assert 100 in recent


def test_cache_8_days_ago_not_recent(persona_db):
    """8 天前的 output / get_recent_outputs(days=7) 不返。"""
    old_output = PersonaOutput(
        user_id=1, scene_type="pr", template_id=200,
        text_snapshot="今天你最猛。",
        shown_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    persona_db.add(old_output)
    persona_db.commit()

    recent = cache.get_recent_outputs(persona_db, user_id=1, scene_type="pr", days=7)
    assert 200 not in recent


# ════════════════════════════════════════════════════
# Section D：service 端到端（test 10-12）
# ════════════════════════════════════════════════════


def test_service_end_to_end_pr(persona_db):
    """mock PR event → service 返 3 条 PR 模板之一（seed 里 3 条）。"""
    event = _make_event(
        activity_data={
            "id": 1, "is_pr": True, "distance": 40_000,
            "started_at": "2026-05-18T10:00:00+00:00",
        },
    )
    text = service.generate_persona_output(event, persona_db)
    assert text is not None
    # 6 条 PR 模板池（Claude A I2）
    assert text in {
        "今天嗑药了？", "今天你最猛。", "数据有点过分。",
        "前 1% 的一天。", "把自己拉爆了。", "8500km 里这一天。",
    }


def test_service_catches_template_lib_exception(persona_db):
    """template_lib 抛错 → service 顶层 catch 返 None / 不抛。"""
    event = _make_event(
        activity_data={
            "id": 1, "is_pr": True, "distance": 40_000,
            "started_at": "2026-05-18T10:00:00+00:00",
        },
    )
    with patch(
        "app.agent.persona.service.template_lib.get_templates_for_scene",
        side_effect=Exception("boom"),
    ):
        text = service.generate_persona_output(event, persona_db)
    assert text is None  # 不抛 / 顶层 catch 返 None


def test_service_cache_failure_does_not_taint_main_return(persona_db):
    """cache.record_output 抛错 → service 仍返合法文案（fire-and-forget）。"""
    event = _make_event(
        activity_data={
            "id": 1, "is_pr": True, "distance": 40_000,
            "started_at": "2026-05-18T10:00:00+00:00",
        },
    )
    with patch(
        "app.agent.persona.service.cache.record_output",
        side_effect=Exception("cache down"),
    ):
        text = service.generate_persona_output(event, persona_db)
    # 主流不受 cache 失败影响
    assert text is not None
    assert text in {
        "今天嗑药了？", "今天你最猛。", "数据有点过分。",
        "前 1% 的一天。", "把自己拉爆了。", "8500km 里这一天。",
    }


def test_service_filter_reject_returns_none(persona_db):
    """模板命中反例 / filter reject → 返 None / 防漂移最后闸生效。"""
    # 注入一条反例模板到 PR pool（mock filter 不放行）
    bad = PersonaTemplate(
        scene_type="pr", segment=None,
        template_text="恭喜你完成 PR！棒棒哒",
        weight=1, active=True,
    )
    persona_db.add(bad)
    persona_db.commit()

    event = _make_event(
        activity_data={
            "id": 1, "is_pr": True, "distance": 40_000,
            "started_at": "2026-05-18T10:00:00+00:00",
        },
    )
    # 强制 pick 选中坏模板
    with patch(
        "app.agent.persona.service.template_lib.pick_template",
        return_value=bad,
    ):
        text = service.generate_persona_output(event, persona_db)
    assert text is None  # filter 拒绝 / 返 None


# ════════════════════════════════════════════════════
# Section E：get_latest_output_for_scene endpoint 测试
# ════════════════════════════════════════════════════


def test_get_latest_output_within_24h(persona_db):
    """24h 内有记录 → 返最新一条。"""
    fresh = PersonaOutput(
        user_id=1, scene_type="pr", template_id=300,
        text_snapshot="今天你最猛。",
        shown_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    persona_db.add(fresh)
    persona_db.commit()

    result = service.get_latest_output_for_scene(persona_db, user_id=1, scene_type="pr")
    assert result is not None
    assert result.template_id == 300


def test_get_latest_output_24h_expired_returns_none(persona_db):
    """超过 24h → 返 None。"""
    stale = PersonaOutput(
        user_id=1, scene_type="pr", template_id=400,
        text_snapshot="今天嗑药了？",
        shown_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    persona_db.add(stale)
    persona_db.commit()

    result = service.get_latest_output_for_scene(persona_db, user_id=1, scene_type="pr")
    assert result is None


def test_get_latest_output_frontend_semantic_scene_degrades(persona_db):
    """scene_type='profile_open' → 退化为查最近 24h 任意场景。"""
    rec = PersonaOutput(
        user_id=1, scene_type="pr", template_id=500,
        text_snapshot="数据有点过分。",
        shown_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    persona_db.add(rec)
    persona_db.commit()

    # 用前端语义 scene_type / 应该退化拿到 pr 那条
    result = service.get_latest_output_for_scene(
        persona_db, user_id=1, scene_type="profile_open",
    )
    assert result is not None
    assert result.template_id == 500
