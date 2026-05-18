"""扫所有 ≥ 7 天没骑的用户 → 发 silence_detected event 给 persona service。

干啥用：
- 每日 cron 跑一次（由 persona-scanner 容器 sleep 86400 循环调用）
- 找出 user.last_activity_at 距今 ≥ 7 天的用户
- 给每个用户触发一次 silence event / persona 写一条沉寂场景文案
- 单用户失败不阻塞批次（continue）/ 整批失败也不抛错出进程

类比：物业管家每天扫一遍住户名单 / 7 天没出门的发个关怀短信。

操作注意：
- 独立 Python 进程 / 不在 FastAPI 请求上下文里
- 用 SessionLocal 手动管理 db / 不走 get_db 依赖
- 顶级 import 所有 ORM 类（防 SQLAlchemy 'could not find table' 跨进程陷阱 / 见 memory standalone_script_orm_loading）
"""

import logging
import sys
from datetime import datetime, timezone, timedelta

from sqlalchemy import func

# 独立进程必须显式 import 所有外键关联 ORM（让 SQLAlchemy metadata 全注册）
# 否则 PersonaOutput → User / Activity FK 解析失败 / 见 memory feedback_standalone_script_orm_loading
from app.user.models import User  # noqa: F401
from app.activity.models import Activity  # noqa: F401
from app.agent.persona.models import PersonaOutput, PersonaTemplate  # noqa: F401
from app.database import SessionLocal
from app.agent.persona import service as persona_service
from app.agent.persona.trigger_router import PersonaEvent


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [persona_silence_scanner] %(message)s",
)
logger = logging.getLogger(__name__)


SILENCE_THRESHOLD_DAYS = 7


def _query_silent_users(db):
    """查所有 ≥ 7 天没 cycling 活动的用户。

    返 list[(user_id, days_since_last)]。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=SILENCE_THRESHOLD_DAYS)
    # 每个 user 的最近一条 cycling started_at
    sub = (
        db.query(
            Activity.user_id.label("user_id"),
            func.max(Activity.started_at).label("last_at"),
        )
        .filter(Activity.activity_type == "cycling")
        .group_by(Activity.user_id)
        .subquery()
    )
    rows = (
        db.query(sub.c.user_id, sub.c.last_at)
        .filter(sub.c.last_at < cutoff)
        .all()
    )
    now = datetime.now(timezone.utc)
    results = []
    for user_id, last_at in rows:
        # last_at 可能为 None（极端 / 跳过）
        if last_at is None:
            continue
        # 防 naive vs aware 踩坑（CLAUDE.md 陷阱 #2）
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        days_since = (now - last_at).days
        results.append((user_id, days_since))
    return results


def scan() -> None:
    """跑一遍：找沉寂用户 + 触发 silence event。"""
    db = SessionLocal()
    try:
        silent_users = _query_silent_users(db)
        logger.info(f"silence scanner: found {len(silent_users)} silent users")

        success_count = 0
        for user_id, days_since in silent_users:
            try:
                event = PersonaEvent(
                    type="silence_detected",
                    user_data={
                        "user_id": user_id,
                        "last_activity_days": days_since,
                    },
                    timestamp=datetime.now(timezone.utc),
                )
                text = persona_service.generate_persona_output(event, db)
                if text:
                    success_count += 1
                    logger.info(
                        f"silence: user={user_id} days={days_since} text={text!r}"
                    )
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"silence scanner skip user={user_id}: {exc}"
                )
                db.rollback()
                continue
        logger.info(
            f"silence scanner done: {success_count}/{len(silent_users)} success"
        )
    finally:
        db.close()


if __name__ == "__main__":
    try:
        scan()
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"silence scanner fatal: {exc}")
        sys.exit(1)
