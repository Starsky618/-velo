"""Persona Engine 回填脚本（task-6 后补 / 2026-05-20 Tim 拍）。

干啥用：
- 给所有历史 cycling 活动**按当时段位还原**写一条 NPC 文案
- 详情页"便利贴永远在"语义的数据准备
- 一次性跑 / 跑完每条历史活动都有 persona_outputs 记录

类比：
新装好的老登 NPC 才上岗 / 让他回头给每条历史活动都贴一张便利贴 / 但便利贴上的话要按"那次骑行当时你是什么段位"算 / 不是按"现在你是什么段位"。

按"当时还原"算法：
- 用 SQL window function 一次算出每条活动的"当时累计 km" / 那时段位 = compute_user_stage(累计 km)
- 当时 is_pr = 看这条活动距离 / 爬升 / 时长 / 标准化功率 是不是历史前面任一字段的 max
- 当时距离桶 = compute_distance_bucket(activity.distance)
- 把"那一刻的 total_distance_m"传进 PersonaEvent.user_data → trigger_router 自动按当时段位选模板

幂等：跳过已有 persona_outputs.activity_id 的活动（重跑安全）。

单进程独立 import：显式 import 所有 FK 关联 ORM 防 SQLAlchemy 'could not find table'
（见 memory feedback_standalone_script_orm_loading）。
"""

import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import text as sql_text

# 显式 import 所有外键关联 ORM
from app.user.models import User  # noqa: F401
from app.activity.models import Activity  # noqa: F401
from app.agent.persona.models import PersonaOutput, PersonaTemplate  # noqa: F401
from app.database import SessionLocal
from app.agent.persona import service as persona_service
from app.agent.persona.trigger_router import PersonaEvent


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [persona_backfill] %(message)s",
)
logger = logging.getLogger(__name__)


# SQL：一次拿所有 cycling completed 活动 + 算出每条的"当时累计 km" + "当时是不是 PR"
# 用 window function：
#   cum_distance = SUM(distance) OVER (PARTITION BY user 按 started_at 顺序累加 ROWS UNBOUNDED PRECEDING)
#                = 截至本活动（含）的累计 km
#   max_*_before = MAX(*) OVER (PARTITION BY user 按 started_at 顺序 ROWS UNBOUNDED PRECEDING) - {本条}
#                = 本活动**之前**（不含本条）该字段的历史最大值 / 用来判断 is_pr
# 注意：PG window function ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING = 严格本行前所有行
# 但 1 PRECEDING 在第一行返 NULL（无 row 之前）→ 第一行 max_before = NULL → 第一条 = PR ✓
_BACKFILL_SQL = """
SELECT
    a.id,
    a.user_id,
    a.distance,
    a.elevation_gain,
    a.duration,
    a.normalized_power,
    a.started_at,
    a.avg_speed,
    a.avg_power,
    a.moving_time,
    -- 截至本活动（含）的累计距离
    SUM(a.distance) OVER w_inclusive AS cum_distance_m,
    -- 本活动之前的历史 max（4 字段 / 用于 PR 判定 / 第一行返 NULL = 第一条算 PR）
    MAX(a.distance) OVER w_before AS max_distance_before,
    MAX(a.elevation_gain) OVER w_before AS max_elev_before,
    MAX(a.duration) OVER w_before AS max_duration_before,
    MAX(a.normalized_power) OVER w_before AS max_np_before
FROM activities a
WHERE a.activity_type = 'cycling'
  AND a.status = 'completed'
  AND (a.duplicate_of IS NULL)  -- 跳过 dedupe 的 duplicate
WINDOW
    w_inclusive AS (
        PARTITION BY a.user_id ORDER BY a.started_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ),
    w_before AS (
        PARTITION BY a.user_id ORDER BY a.started_at
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )
ORDER BY a.user_id, a.started_at
"""


def _is_pr_from_row(row) -> bool:
    """根据 SQL 返回的"当时之前的 max"判定本条活动是不是 PR。

    PR = 4 字段任一打破历史 max（distance / elevation_gain / duration / normalized_power）
    第一条活动（max_*_before 全 NULL）= PR
    """
    if row.max_distance_before is None and row.max_elev_before is None \
            and row.max_duration_before is None and row.max_np_before is None:
        return True  # 第一条
    if row.distance and row.max_distance_before is not None \
            and row.distance > row.max_distance_before:
        return True
    if row.elevation_gain and row.max_elev_before is not None \
            and row.elevation_gain > row.max_elev_before:
        return True
    if row.duration and row.max_duration_before is not None \
            and row.duration > row.max_duration_before:
        return True
    if row.normalized_power and row.max_np_before is not None \
            and row.normalized_power > row.max_np_before:
        return True
    return False


def backfill() -> dict:
    """跑一遍回填 / 返统计 dict。"""
    db = SessionLocal()
    stats = {"total": 0, "skipped": 0, "wrote": 0, "failed": 0, "no_output": 0}
    try:
        # 拿已有 persona_outputs.activity_id 做幂等 guard
        existing_activity_ids = set(
            row[0] for row in db.execute(
                sql_text("SELECT DISTINCT activity_id FROM persona_outputs "
                         "WHERE activity_id IS NOT NULL")
            ).fetchall()
        )
        logger.info(
            f"backfill start / 已有 persona_outputs activity_id: {len(existing_activity_ids)} 条 / 跳过"
        )

        # 跑大 SQL 拿所有活动 + 当时累计 km + 当时之前的 max
        rows = db.execute(sql_text(_BACKFILL_SQL)).fetchall()
        logger.info(f"backfill scan / 共 {len(rows)} 条 cycling completed 活动")

        for row in rows:
            stats["total"] += 1
            if row.id in existing_activity_ids:
                stats["skipped"] += 1
                continue

            try:
                # 当时累计 km（含本次）
                cum_distance_m = int(row.cum_distance_m or 0)
                # 当时是不是 PR
                is_pr = _is_pr_from_row(row)

                # 打包 PersonaEvent / total_distance_m 用"当时累计"让 trigger_router 算当时段位
                event = PersonaEvent(
                    type="activity_uploaded",
                    activity_data={
                        "id": row.id,
                        "distance": float(row.distance) if row.distance else 0,
                        "elevation_gain": float(row.elevation_gain) if row.elevation_gain else None,
                        "duration": row.duration,
                        "moving_time": row.moving_time,
                        "started_at": row.started_at,
                        # avg_speed 已是 km/h（worker save_parse_result 转过 / Codex C1）
                        "avg_speed_kmh": row.avg_speed,
                        "avg_power": row.avg_power,
                        "normalized_power": row.normalized_power,
                        "is_pr": is_pr,
                        "is_rain": False,
                    },
                    user_data={
                        "user_id": row.user_id,
                        "total_distance_m": cum_distance_m,  # 当时累计 / 不是现在累计
                        "weekly_count": 1,  # 回填不补连骑（历史时刻状态难还原）
                        "last_activity_days": 0,
                    },
                    timestamp=datetime.now(timezone.utc),
                )

                text = persona_service.generate_persona_output(event, db)
                db.commit()  # 让 cache.record_output 的 SAVEPOINT 真落盘

                if text:
                    stats["wrote"] += 1
                    logger.info(
                        f"backfill OK / activity={row.id} user={row.user_id} "
                        f"cum_km={cum_distance_m // 1000} is_pr={is_pr} text={text!r}"
                    )
                else:
                    stats["no_output"] += 1
                    logger.warning(
                        f"backfill no output / activity={row.id} "
                        f"（service 返 None / 可能 filter 拒绝 / pool 空）"
                    )
            except Exception as exc:  # noqa: BLE001
                stats["failed"] += 1
                logger.warning(
                    f"backfill fail / activity={row.id}: {exc}"
                )
                db.rollback()
                continue

        # Codex C3：record_output 是 fire-and-forget / wrote 统计可能虚高
        # 末尾 SELECT count 真验证 persona_outputs 实际写入数（防统计虚高 / 防静默 fail）
        actual_count = db.execute(sql_text(
            "SELECT count(*) FROM persona_outputs WHERE activity_id IS NOT NULL"
        )).scalar()
        stats["actual_persona_outputs_with_activity_id"] = actual_count
        logger.info(f"backfill done / {stats}")
        logger.info(f"DB verify / persona_outputs activity_id IS NOT NULL count = {actual_count}")
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    try:
        stats = backfill()
        sys.exit(0 if stats["failed"] == 0 else 1)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"backfill fatal: {exc}")
        sys.exit(2)
