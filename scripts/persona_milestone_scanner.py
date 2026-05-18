"""扫累计里程碑 / 周年 / 节气 → 发 milestone_reached event 给 persona service。

干啥用：
- 每日 cron 跑一次（由 persona-scanner 容器 sleep 86400 循环调用）
- 3 类 milestone 触发：
  1. **累计跨阈值**：用户累计 cycling km 刚跨 1万 / 5万 / 10万等关键数字
  2. **周年**：用户注册或首次 cycling 满整年（今天 = 注册日 + N 年）
  3. **节气**：今天是节气日（立春 / 清明 / 夏至 / 立秋 / 霜降 / 立冬 / 冬至 / 大暑 等）
- 触发后写一条 surprise 场景文案

类比：物业每天看下日历 / 谁周年 / 谁达成里程碑 / 谁碰上节气 → 发个甜点祝贺。

操作注意：
- 同 silence scanner / 顶级 import 所有 ORM
- 节气日历用固定字典（每年节气日略浮动 ±1 天 / 这里按 2026 实证）
- 单用户失败 continue / 整批失败 logger.exception 不抛
"""

import logging
import sys
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo  # 北京时间日期 / 防容器 TZ=UTC 让节气偏一天

from sqlalchemy import func

from app.user.models import User
from app.activity.models import Activity
from app.agent.persona.models import PersonaOutput, PersonaTemplate  # noqa: F401
from app.database import SessionLocal
from app.agent.persona import service as persona_service
from app.agent.persona.trigger_router import PersonaEvent


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [persona_milestone_scanner] %(message)s",
)
logger = logging.getLogger(__name__)


# 累计里程碑阈值（米 / 跨阈值才触发）
_MILESTONE_THRESHOLDS_M: tuple[int, ...] = (
    10_000_000,    # 1 万 km / "老登正式入会"
    50_000_000,    # 5 万 km
    100_000_000,   # 10 万 km
)

# 节气日历（2026 / 月-日 → 节气名 / 用于查"今天是不是节气"）
# 节气日每年浮动 ±1 天 / 维护这张表即可
# TODO（v1.0+）：每年更新节气表 / 或接 lunardate 库动态算 / 当前 2026 实证 2027 起须刷新
_SOLAR_TERMS_2026: dict[tuple[int, int], str] = {
    (2, 4): "立春", (3, 6): "惊蛰", (3, 20): "春分", (4, 5): "清明",
    (5, 5): "立夏", (6, 21): "夏至", (7, 7): "小暑", (7, 23): "大暑",
    (8, 8): "立秋", (9, 23): "秋分", (10, 8): "寒露", (10, 23): "霜降",
    (11, 7): "立冬", (12, 22): "冬至",
}


def _check_milestone_distance(user_id: int, db) -> bool:
    """累计 km 是否刚跨阈值（今天的累计 ≥ 阈值 / 但减去最近一次活动距离 < 阈值）。"""
    total = db.query(func.sum(Activity.distance)).filter(
        Activity.user_id == user_id,
        Activity.activity_type == "cycling",
    ).scalar() or 0
    # 找最近一条 cycling
    last = db.query(Activity.distance).filter(
        Activity.user_id == user_id,
        Activity.activity_type == "cycling",
    ).order_by(Activity.started_at.desc()).first()
    if last is None or last[0] is None:
        return False
    before_last = total - last[0]
    for threshold in _MILESTONE_THRESHOLDS_M:
        if before_last < threshold <= total:
            return True
    return False


def _check_anniversary(user: User, today: date) -> bool:
    """用户注册日整年（生日类）/ today.month == created_at.month + today.day == created_at.day。

    注意：2/29 注册的用户在平年永远不触发（小概率边界 / 100 用户级可接受 / 未来用 3/1 fallback）。
    """
    if user.created_at is None:
        return False
    created = user.created_at
    if created.month == today.month and created.day == today.day:
        # 不是同一年（注册当天不触发 / 满 1 年才触发）
        if created.year < today.year:
            return True
    return False


def _check_solar_term(today: date) -> str | None:
    """今天是否节气 / 返节气名 / 否则 None。"""
    return _SOLAR_TERMS_2026.get((today.month, today.day))


def scan() -> None:
    """跑一遍：扫 3 类 milestone 触发 surprise event。

    幂等：本次 scan 前查 persona_outputs 当日已有的 surprise 记录 / 同用户同类型同日跳过
    （防服务器重启 / cron 重复跑导致同一节气 / 周年 / 里程碑写多条 / Codex+Claude 抓）。
    """
    db = SessionLocal()
    try:
        # 用北京时间日期判节气 / 防容器 TZ=UTC 让节气偏一天（Critical / Claude A+B 抓）
        bj_tz = ZoneInfo("Asia/Shanghai")
        today_bj = datetime.now(bj_tz).date()
        solar_term_name = _check_solar_term(today_bj)

        # 拿所有有 cycling 活动的用户
        users = db.query(User).join(
            Activity, Activity.user_id == User.id,
        ).distinct().all()
        logger.info(
            f"milestone scanner: scanning {len(users)} users / today={today_bj} "
            f"solar_term={solar_term_name}"
        )

        # 幂等查表：查今日（北京时间）已写入的 surprise 输出
        # 防 cron 重复跑 / 服务器重启重复触发（Codex+Claude Important）
        day_start_utc = datetime.combine(today_bj, datetime.min.time()).replace(
            tzinfo=bj_tz,
        ).astimezone(timezone.utc)
        already_written_rows = db.query(
            PersonaOutput.user_id, PersonaOutput.scene_type,
        ).filter(
            PersonaOutput.scene_type == "surprise",
            PersonaOutput.shown_at >= day_start_utc,
        ).all()
        already_written_users: set[int] = {row.user_id for row in already_written_rows}

        success_count = 0
        for user in users:
            # 同日已写过该用户 surprise → 跳过（幂等 / 防重复）
            if user.id in already_written_users:
                continue
            try:
                triggers: list[str] = []
                # 1. 累计里程碑
                if _check_milestone_distance(user.id, db):
                    triggers.append("milestone")
                # 2. 周年
                if _check_anniversary(user, today_bj):
                    triggers.append("anniversary")
                # 3. 节气（全用户都触发）
                if solar_term_name:
                    triggers.append("solar_term")

                for milestone_type in triggers:
                    event = PersonaEvent(
                        type="milestone_reached",
                        user_data={
                            "user_id": user.id,
                            "milestone_type": milestone_type,
                        },
                        timestamp=datetime.now(timezone.utc),
                    )
                    text = persona_service.generate_persona_output(event, db)
                    if text:
                        success_count += 1
                        logger.info(
                            f"milestone: user={user.id} type={milestone_type} text={text!r}"
                        )
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"milestone scanner skip user={user.id}: {exc}")
                db.rollback()
                continue
        logger.info(f"milestone scanner done: {success_count} triggers fired")
    finally:
        db.close()


if __name__ == "__main__":
    try:
        scan()
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"milestone scanner fatal: {exc}")
        sys.exit(1)
