"""
NPC 文案系统顶层入口（task-3 实施）。

干啥用：
- 业务模块（worker / endpoint）调用 NPC 的唯一入口
- 编排：trigger_router → template_lib → filters → cache → 写 persona_outputs → 返 str
- 顶层 catch any Exception → 返 None / 不传染调用方事务（宪法 § 7.2 失败隔离 CRITICAL）

类比：老登 NPC 的"嘴巴" + 防御套——
- generate_persona_output：嘴巴说一句话给前端
- get_latest_output_for_scene：endpoint 查"该用户最近说过啥"（profile / 详情页打开）
- get_recent_outputs：拿用户最近 N 条 NPC 输出历史

操作注意（ADR-009 + 宪法 § 7.2 + CLAUDE.md 陷阱 #13）：
- 顶层必须 try/except 兜底 / **绝对 critical / 违反 = REJECT**
- 不抛错给调用方 / 失败静默返 None
- 内层 cache.record_output 用 SAVEPOINT 隔离 / 失败也不影响主返
- 不反向 import 业务 service / 只 import app.agent.persona 内 + app.agent.persona.models

公开 API：
- generate_persona_output(event, db) → Optional[str]：生成新文案 + 写台账
- get_latest_output_for_scene(db, user_id, scene_type, activity_id) → Optional[PersonaOutput]：endpoint 查最近
- get_recent_outputs(db, user_id, limit) → list[PersonaOutput]：拿历史
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.agent.persona import trigger_router, template_lib, filters, cache
from app.agent.persona.models import PersonaOutput


logger = logging.getLogger(__name__)


# 前端语义 scene_type 集合（v0.3 / Claude A 抓 C1 / endpoint 退化用）
# 这些不是宪法 § 2 的 7 种文案场景 / 是前端打开页面的语义标签
# endpoint 查询时 scene_type ∈ FRONTEND_SEMANTIC_SCENES → 退化为查最近 24h 任意文案
FRONTEND_SEMANTIC_SCENES: frozenset[str] = frozenset({
    "profile_open",
    "user_page_open",
    "activity_upload",
})


def get_latest_output_for_scene(
    db: Session,
    user_id: int,
    scene_type: str,
    activity_id: Optional[int] = None,
) -> Optional[PersonaOutput]:
    """endpoint 查询函数 / 拿"该用户最近某场景"NPC 文案（24h 内）。

    scene_type 语义：
    - ∈ FRONTEND_SEMANTIC_SCENES（profile_open 等）→ 退化为查最近 24h **任意**
      宪法场景最新一条（让 profile 一打开就有文案 / 不限定特定场景）
    - ∈ 宪法 7 种场景（pr / segment_distance / 等）→ 按 scene_type 精确过滤
    - activity_id != None → 加 WHERE activity_id IN (X, NULL) 过滤（让"某次活动详情页"
      既能拿该活动专属文案 / 又能 fallback 拿无关联活动的通用文案）

    返 None 表示 24h 内没有匹配记录。
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        query = db.query(PersonaOutput).filter(
            PersonaOutput.user_id == user_id,
            PersonaOutput.shown_at >= since,
        )
        if scene_type not in FRONTEND_SEMANTIC_SCENES:
            query = query.filter(PersonaOutput.scene_type == scene_type)
        if activity_id is not None:
            query = query.filter(
                (PersonaOutput.activity_id == activity_id)
                | (PersonaOutput.activity_id.is_(None))
            )
        return query.order_by(PersonaOutput.shown_at.desc()).first()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona get_latest_output_for_scene failed: {exc}")
        return None


def get_recent_outputs(
    db: Session,
    user_id: int,
    limit: int = 10,
) -> list[PersonaOutput]:
    """拿用户最近 N 条 NPC 输出历史 / 给"我的 NPC 历史"列表 endpoint 用。

    倒序按 shown_at / 失败返空 list（不抛错）。
    """
    try:
        return (
            db.query(PersonaOutput)
            .filter(PersonaOutput.user_id == user_id)
            .order_by(PersonaOutput.shown_at.desc())
            .limit(limit)
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona get_recent_outputs failed: {exc}")
        return []


def generate_persona_output(
    event: trigger_router.PersonaEvent,
    db: Session,
) -> Optional[str]:
    """NPC 文案生成主入口 / 一站式流水线。

    流水线（6 步）：
    1. route：判断该不该说话 + 哪个场景
    2. get_templates_for_scene：查模板池
    3. get_recent_outputs：查最近用过的（防 7 天重复）
    4. pick_template：选一条（避开 recent）
    5. filters.is_safe：防漂移最后闸（命中反例 reject 返 None）
    6. record_output：写台账（fire-and-forget / 失败不影响返）

    任何一步失败 → 顶层 catch Exception 返 None / **不传染调用方事务**
    （宪法 § 7.2 CRITICAL）。
    """
    try:
        # 1. 路由决策
        decision = trigger_router.route(event)
        if decision is None:
            return None

        # 2. 查模板池
        templates = template_lib.get_templates_for_scene(
            db, decision.scene_type, decision.segment,
        )
        if not templates:
            logger.info(
                f"persona templates empty: scene={decision.scene_type} "
                f"segment={decision.segment}"
            )
            return None

        # 3. 查最近用过的 template_id
        user_id = event.user_data.get("user_id")
        if user_id is None:
            logger.warning("persona event missing user_id / skip")
            return None

        recent_ids = cache.get_recent_outputs(
            db, user_id, decision.scene_type, days=7,
        )

        # 4. 选一条（避开 recent / pool 耗尽返 list[0] 兜底）
        picked = template_lib.pick_template(templates, user_id, recent_ids)
        if picked is None:
            return None

        # 5. 防漂移 filter（命中反例 = reject）
        if not filters.is_safe(picked.template_text):
            logger.warning(
                f"persona filter reject: scene={decision.scene_type} "
                f"template_id={picked.id} text={picked.template_text!r}"
            )
            return None

        # 6. 写历史台账（fire-and-forget / 双层兜底：cache 内部 SAVEPOINT + 此处 try/except）
        # 即使 cache.record_output 内部 catch 失败 / 这里再兜一层 / 保证主返不被污染
        activity_id = None
        if event.activity_data:
            activity_id = event.activity_data.get("id")
        try:
            cache.record_output(
                db, user_id, decision.scene_type, picked.id,
                text_snapshot=picked.template_text,
                activity_id=activity_id,
            )
        except Exception as cache_exc:  # noqa: BLE001
            logger.warning(
                f"persona cache write failed (ignored / 主返不受影响): {cache_exc}"
            )

        return picked.template_text

    except Exception as exc:  # noqa: BLE001 / 顶层兜底 CRITICAL
        # 宪法 § 7.2 "不传染失败" 顶层兜底
        logger.exception(
            f"persona service unexpected error (returned None): {exc}"
        )
        return None
