"""
NPC 去重 + 缓存（task-3 实施）。

干啥用：
- 查用户最近 N 天该 scene_type 用过的 template_id（防 7 天内重复同一文案）
- record_output：写 persona_outputs 历史台账（含 text_snapshot 文案快照）

类比：餐厅老板的"客人最近吃过啥"小本子——
- 张三这周吃过宫保鸡丁了 / 这周再来就上别的
- 老板把今天给张三上的"红烧肉"记一笔 / 含菜名快照（防菜单改字后历史看不懂）

操作注意（CLAUDE.md 陷阱 #2 + #13）：
- DateTime 永远 tz-aware（datetime.now(timezone.utc)）防 naive 比较 TypeError
- record_output 失败 → fire-and-forget / 不抛错（service 顶层 catch / 但内层也 logger.warning）
- 不反向 import 业务 service / 只读写 PersonaOutput ORM

输入输出：
- get_recent_outputs：入 user_id + scene_type + days → 出 list[template_id]
- record_output：入完整字段 → 写 persona_outputs / 失败静默
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.agent.persona.models import PersonaOutput


logger = logging.getLogger(__name__)


def get_recent_outputs(
    db: Session,
    user_id: int,
    scene_type: str,
    days: int = 7,
) -> list[int]:
    """查最近 N 天该 user_id × scene_type 用过的 template_id 列表。

    返 list 给 pick_template 当 recent_template_ids 排除集 / 防 7 天内
    NPC 在同一场景重复说同一句话（broken record）。

    tz-aware datetime 防比较踩坑（CLAUDE.md 陷阱 #2）。
    查询失败返空 list（不抛错 / 让 pick_template 当作"没有最近记录"）。
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = (
            db.query(PersonaOutput.template_id)
            .filter(
                PersonaOutput.user_id == user_id,
                PersonaOutput.scene_type == scene_type,
                PersonaOutput.shown_at >= since,
            )
            .all()
        )
        return [row.template_id for row in rows]
    except Exception as exc:  # noqa: BLE001 / fire-and-forget
        logger.warning(f"persona cache get_recent_outputs failed: {exc}")
        return []


def record_output(
    db: Session,
    user_id: int,
    scene_type: str,
    template_id: int,
    text_snapshot: str,
    activity_id: Optional[int] = None,
) -> None:
    """写 persona_outputs 历史台账 / fire-and-forget。

    text_snapshot（v0.4 修 / Claude A+B 共识 C1）：写入时 freeze 渲染后文案 /
    未来即使 persona_templates 改字或删行 / 历史台账仍可读 / 防 endpoint JOIN。

    用 db.begin_nested() SAVEPOINT 隔离失败（CLAUDE.md 陷阱 #13）：
    内层写失败只回退到 SAVEPOINT / 不污染外层 worker / endpoint 事务。
    """
    try:
        nested = db.begin_nested()
        try:
            output = PersonaOutput(
                user_id=user_id,
                scene_type=scene_type,
                template_id=template_id,
                text_snapshot=text_snapshot,
                shown_at=datetime.now(timezone.utc),
                activity_id=activity_id,
            )
            db.add(output)
            db.flush()
            nested.commit()
        except Exception as inner_exc:
            nested.rollback()
            raise inner_exc
    except Exception as exc:  # noqa: BLE001 / fire-and-forget
        logger.warning(
            f"persona cache record_output failed (ignored): "
            f"user_id={user_id} scene={scene_type} template_id={template_id} "
            f"err={exc}"
        )
