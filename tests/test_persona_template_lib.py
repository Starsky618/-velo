"""Persona Engine task-2：template_lib 4 函数 + seed 163 条字面漂移检测。

测试 10 项：
1. seed TEMPLATES list 长度 >= 150（防回退 / 当前 163）
2. seed 字面漂移：抽样 6 条 vs hardcoded（宪法 § 2 ground truth）
3. compute_user_stage 4 边界（rookie / entry / mid / veteran）
4. compute_distance_bucket 5 边界（tiny / short / normal / long / extreme / 新阈值 5/30/60/150）
5. compute_user_stage 边界值归右（500_000 → entry / 3_000_000 → mid / 8_000_000 → veteran）
6. compute_distance_bucket 边界值归右（5_000 → short / 30_000 → normal / 60_000 → long / 150_000 → extreme）
7. get_templates_for_scene('pr') 返 16 条（segment=None 通用模板）
8. get_templates_for_scene('segment_distance', 'veteran_normal') 返 7 条
9. pick_template 防重复（recent=[id1] → 不返 id1）
10. pick_template pool 耗尽兜底（recent 含全部 → 返 list[0] 不返 None）

防火墙红线（plan handoff § 1 / § 2.4）：
- 只 import app.agent.persona 内 / 不反向 import 业务 service
- 测试用独立 in-memory SQLite engine / 不污染 conftest 全局 fixture
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.agent.persona.models import PersonaTemplate
from app.agent.persona.template_lib import (
    compute_user_stage,
    compute_distance_bucket,
    get_templates_for_scene,
    pick_template,
)
from migrations.versions.persona_engine_seed import TEMPLATES


# ─── 测试 1：seed list 长度 ───


def test_seed_templates_count_above_150():
    """seed TEMPLATES 至少 150 条（v0.2 cycle 完结实证 168 条 / 防未来误删）。"""
    assert len(TEMPLATES) >= 150


def test_seed_segment_quota_each_at_least_5():
    """v0.2 红线：每个 (scene_type, segment) ≥ 5 条防 broken record（Tim 拍板 / Codex Critical 抓）。

    loading 段豁免（§2.6 过拟合裁定 / 戏剧化候选全砍 / 仅留 v0.1 1 条）。
    """
    from collections import Counter
    counter = Counter((t[0], t[1]) for t in TEMPLATES)
    LOADING_EXEMPT = ("empty_error", "loading")

    for (scene_type, segment), count in counter.items():
        if (scene_type, segment) == LOADING_EXEMPT:
            assert count == 1, f"loading 应 1 条豁免 / 实际 {count}"
            continue
        assert count >= 5, (
            f"段位 ({scene_type}, {segment}) 只 {count} 条 / 违反 ≥ 5 红线"
        )


# ─── 测试 2：字面漂移检测（宪法 § 2 ground truth） ───


def test_seed_literal_drift_sample():
    """抽样 6 条文案对照宪法 § 2 字面 byte-by-byte（任何字符改动 fail）。"""
    expected_in_seed = [
        # § 2.1 PR
        ("pr", None, "今天嗑药了？"),
        # § 2.2 老登 40km（v0.2 cycle 1 锚改后）
        ("segment_distance", "veteran_normal", "40km。蹬两脚意思意思。"),
        # § 2.5 极端高密度金标尺
        ("extreme", "tiny", "5 公里？撒尿都不够。"),
        ("extreme", "high_speed", "这功率是人类吗？"),
        # § 2.6 错误页
        ("empty_error", "loading", "算你的高光中…"),
        # § 2.8 错峰惊喜
        ("surprise", "milestone", "1 万了。老登正式入会。"),
    ]
    seed_set = set(TEMPLATES)
    for triple in expected_in_seed:
        assert triple in seed_set, f"seed 漂移 / 缺：{triple}"


# ─── 测试 3：段位算法 4 段位 ───


@pytest.mark.parametrize(
    "total_km, expected",
    [
        (0, "rookie"),
        (499_000, "rookie"),
        (500_000, "entry"),
        (2_999_999, "entry"),
        (3_000_000, "mid"),
        (7_999_999, "mid"),
        (8_000_000, "veteran"),
        (8_500_000, "veteran"),
        (50_000_000, "veteran"),
    ],
)
def test_compute_user_stage_boundaries(total_km, expected):
    """段位边界值归右桶（500_000 → entry 不是 rookie）。"""
    assert compute_user_stage(total_km) == expected


def test_compute_user_stage_negative_to_rookie():
    """负数 / 异常值归 rookie 兜底（防 NULL 通过算法）。"""
    assert compute_user_stage(-1) == "rookie"


# ─── 测试 4：距离桶算法 5 桶（新阈值 5/30/60/150）───


@pytest.mark.parametrize(
    "dist_m, expected",
    [
        (0, "tiny"),
        (4_999, "tiny"),
        (5_000, "short"),       # 边界归右
        (29_999, "short"),
        (30_000, "normal"),     # 边界归右
        (40_000, "normal"),     # 中位锚（v0.2 cycle 1 拍）
        (59_999, "normal"),
        (60_000, "long"),       # 边界归右
        (149_999, "long"),
        (150_000, "extreme"),   # 边界归右
        (200_000, "extreme"),
    ],
)
def test_compute_distance_bucket_boundaries(dist_m, expected):
    """距离桶边界 / v0.2 cycle 1 新阈值 5/30/60/150（防回退到旧 5/50/100/150）。"""
    assert compute_distance_bucket(dist_m) == expected


# ─── 测试 5：get_templates_for_scene + pick_template / 真 DB ───


@pytest.fixture()
def persona_db():
    """独立 in-memory SQLite + 只建 persona_templates 表 + seed 测试数据。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 只建 persona_templates 表（不依赖业务表 / 避免 PostGIS / JSONB 编译错）
    persona_table = Base.metadata.tables["persona_templates"]
    Base.metadata.create_all(bind=engine, tables=[persona_table])

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()

    # seed 真实 163 条
    for scene_type, segment, template_text in TEMPLATES:
        db.add(PersonaTemplate(
            scene_type=scene_type,
            segment=segment,
            template_text=template_text,
            weight=1,
            active=True,
        ))
    db.commit()

    yield db
    db.close()
    engine.dispose()


def test_get_templates_for_scene_pr_returns_16(persona_db):
    """PR 场景（segment=None 通用模板）返 16 条。"""
    templates = get_templates_for_scene(persona_db, "pr")
    assert len(templates) == 16


def test_get_templates_for_scene_with_segment(persona_db):
    """段位 + 距离桶过滤 / 老登 40km 返 7 条（v0.1 1 + cycle 1 6）。"""
    templates = get_templates_for_scene(
        persona_db, "segment_distance", "veteran_normal",
    )
    assert len(templates) == 7
    texts = {t.template_text for t in templates}
    assert "40km。蹬两脚意思意思。" in texts
    assert "撒个尿就回了。" in texts


def test_get_templates_excludes_inactive(persona_db):
    """active=False 的模板不返（管理员临时下线某条不删表 / 不返）。"""
    one = persona_db.query(PersonaTemplate).filter_by(scene_type="pr").first()
    one.active = False
    persona_db.commit()

    templates = get_templates_for_scene(persona_db, "pr")
    assert len(templates) == 15  # 16 - 1 下线
    assert one.id not in {t.id for t in templates}


# ─── 测试 6：pick_template 防重复 + 兜底 ───


def test_pick_template_avoids_recent(persona_db):
    """pick 优先避开 recent_template_ids。"""
    pool = get_templates_for_scene(persona_db, "pr")
    assert len(pool) == 16

    # 把前 15 条都标"最近用过" / pick 应返第 16 条
    recent_ids = [t.id for t in pool[:15]]
    only_left = pool[15]

    picked = pick_template(pool, user_id=1, recent_template_ids=recent_ids)
    assert picked is not None
    assert picked.id == only_left.id


def test_pick_template_pool_exhausted_fallback(persona_db):
    """pool 耗尽（全在 recent）→ 返 list[0]（不返 None / 不让 NPC 沉默）。"""
    pool = get_templates_for_scene(persona_db, "pr")
    recent_ids = [t.id for t in pool]  # 全部都用过

    picked = pick_template(pool, user_id=1, recent_template_ids=recent_ids)
    assert picked is not None
    assert picked.id == pool[0].id


def test_pick_template_empty_pool_returns_none(persona_db):
    """空 pool 返 None（不是兜底 / 调用方应自行处理）。"""
    picked = pick_template([], user_id=1, recent_template_ids=[])
    assert picked is None
