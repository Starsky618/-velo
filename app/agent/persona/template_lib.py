"""
NPC 模板池 + 渲染（task-2 实施）。

干啥用：
- 加载 persona_templates 表 ~168 条精金文案（按 scene_type / segment 分类）
- 段位算法：累计 km → 萌新 / 入门 / 进阶 / 老登
- 距离桶算法：单次 km → tiny / short / normal / long / extreme
- pick_template 选模板 + 防 7 天内重复 + pool 耗尽兜底返第一条

操作注意（ADR-009 + 宪法 § 7.2 硬约束）：
- 本模块**不反向 import** 业务 service（user / activity / segment / notification 都禁）
- 只读 persona_templates 表 / 不写 / 不查业务表
- 文案 ground truth = docs/agent-rules/persona-constitution.md / 任何字面漂移由 pytest 拦截

数据流：
- 入：scene_type + segment（可选）+ user_id + recent_template_ids
- 出：PersonaTemplate（或 None / 当 pool 真为空时）

阈值依据（v0.2 cycle 1 拍板 / 2026-05-17 / 宪法 § 2.2 + 2.5 实证）：
- 段位：宪法 § 2.2 顶部"萌新 < 500 / 入门 500-3000 / 进阶 3000-8000 / 老登 > 8000"
- 距离桶：velo 用户群周末甜区 30-60km / 80km 已 long / normal 中位 40km
"""

from typing import Optional
import random

from sqlalchemy.orm import Session

from app.agent.persona.models import PersonaTemplate


# ─── 段位阈值（米 / 宪法 § 2.2）───
_STAGE_THRESHOLDS = (
    (500_000, "rookie"),       # < 500 km
    (3_000_000, "entry"),      # 500 - 3000 km
    (8_000_000, "mid"),        # 3000 - 8000 km
    # > 8000 km → veteran
)

# ─── 距离桶阈值（米 / v0.2 cycle 1 拍 / 让 40km 真落 normal）───
_DISTANCE_BUCKETS = (
    (5_000, "tiny"),       # < 5 km
    (30_000, "short"),     # 5 - 30 km
    (60_000, "normal"),    # 30 - 60 km（中位 ~45）
    (150_000, "long"),     # 60 - 150 km（中位 ~100）
    # > 150 km → extreme
)


def compute_user_stage(total_distance_m: int) -> str:
    """累计距离（米）→ 段位（纯函数 / 不查 DB）。

    类比：游戏里"经验值满了升一级"——累计 km 是经验值，段位是等级。
    边界值归右桶（500_000 → 'entry' 不是 'rookie'）。

    宪法 § 2.2 阈值：
    - < 500 km → 'rookie' （萌新）
    - 500-3000 km → 'entry' （入门）
    - 3000-8000 km → 'mid' （进阶）
    - > 8000 km → 'veteran' （老登）

    防 NULL / 负数：< 0 归 rookie / None 由调用方过滤。
    """
    if total_distance_m < 0:
        return "rookie"
    for threshold, stage in _STAGE_THRESHOLDS:
        if total_distance_m < threshold:
            return stage
    return "veteran"


def compute_distance_bucket(distance_m: int) -> str:
    """单次活动距离（米）→ 桶（纯函数）。

    v0.2 cycle 1 修（2026-05-17 Tim 拍）：normal 中位从 80km 下调 40km
    （velo 用户群周末甜区 30-60km / 80km 已属 long 桶 / 不是日常）。

    - < 5 km → 'tiny'    （撒尿都不够距离）
    - 5-30 km → 'short'  （萌新起步 / 通勤）
    - 30-60 km → 'normal'（中位 ~45km / 周末日常甜区）
    - 60-150 km → 'long' （中位 ~100km / 进阶长距离）
    - > 150 km → 'extreme'（老登狂飙）

    边界值归右桶（5_000 → 'short' 不是 'tiny'）。
    """
    if distance_m < 0:
        return "tiny"
    for threshold, bucket in _DISTANCE_BUCKETS:
        if distance_m < threshold:
            return bucket
    return "extreme"


def get_templates_for_scene(
    db: Session,
    scene_type: str,
    segment: Optional[str] = None,
) -> list[PersonaTemplate]:
    """查匹配模板池。

    类比：从老登的"金句库"按场景类别（PR / 普通骑行 / 沉寂等）+ 细分段位
    （萌新 30km / 入门 40km 等）拿出候选 list。

    segment=None 时查该 scene_type 下所有 segment=NULL 的通用模板
    （场景如 PR / 连骑 / 沉寂 都不分段位）。

    只返 active=True 的（管理员临时下线某条 = active=false / 不删表）。
    """
    query = db.query(PersonaTemplate).filter(
        PersonaTemplate.scene_type == scene_type,
        PersonaTemplate.active == True,  # noqa: E712 / SQLAlchemy 不支持 is True
    )
    if segment is None:
        query = query.filter(PersonaTemplate.segment.is_(None))
    else:
        query = query.filter(PersonaTemplate.segment == segment)
    return query.all()


def pick_template(
    templates: list[PersonaTemplate],
    user_id: int,  # noqa: ARG001 / 保留参数让 task-3 调用方不用改签名 / v0.5+ 加权随机启用
    recent_template_ids: list[int],
) -> Optional[PersonaTemplate]:
    """从模板池选一条 / 优先避开最近用过的 / pool 耗尽兜底返第一条。

    类比：餐厅老板有 10 道菜 / 给同一桌客人不重复上 / 但 10 道都吃过就
    先上第一道兜底（不能让客人饿着）。

    user_id 接收但当前不用（v0.5+ 加权随机 / per-user 权重时启用）；
    保留参数让 task-3 调用方不用改签名。
    """
    if not templates:
        return None

    recent_set = set(recent_template_ids)
    fresh = [t for t in templates if t.id not in recent_set]

    if fresh:
        return random.choice(fresh)

    # pool 耗尽兜底：返第一条（不返 None / 不让用户看到 NPC 沉默）
    return templates[0]
