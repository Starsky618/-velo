"""Sprint 8 polish：max_cadence + power_zones 一次性回填脚本（幂等）。

为什么需要：
    Sprint 8 加了 max_cadence 字段（commit 5e40984）+ 三路 parser 解析新活动时算 max_cadence
    （commit 7dd2f3b）+ 详情页显示最大踏频（commit b6d4544）。
    但**老活动 295 条 max_cadence 是 NULL** + **186 条 power_zones 历史漏挖**
    → 详情页打开看不到"最大踏频"行 + "功率区间分布"卡。

    本脚本：一次循环扫每条活动 trackpoints，同时算 max_cadence + power_zones 写回 DB。
    不调外部 API（cadence 走 Trackpoint.cadence / power_zones 走 Trackpoint.power + user.ftp）。

幂等语义：
    跳过式幂等 —— 只动 max_cadence IS NULL OR power_zones IS NULL 的行。已有值的不动。
    （未来 Sprint 9 加 snapshot_ftp 字段时另跑 baseline 同步，本脚本不动 snapshot_ftp）

跑法：
    # 干跑：只统计 + 按用户分组打印，不改 DB
    python -m scripts.backfill_max_cadence_and_power_zones --dry-run

    # 真跑（所有用户所有待回填活动）
    python -m scripts.backfill_max_cadence_and_power_zones

    # 限定单用户（小批量验证）
    python -m scripts.backfill_max_cadence_and_power_zones --user-id 2

性能：
    每条活动一次 Trackpoint 查询 / 内存里同时算两个字段 / 不重复 IO。
    295 条预期几秒跑完。无外部 API 调用 / 无限流问题。
"""

from __future__ import annotations

import argparse
from collections import Counter
import logging
import sys

from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import calculate_power_zones
from app.database import SessionLocal
from app.user.models import User  # noqa: F401 — standalone 脚本必须显式 import 防外键 ORM 找不到


logger = logging.getLogger(__name__)

# 每 N 条 commit 一次 + 打印进度
_COMMIT_EVERY = 20


def _query_pending(db, user_id_filter: int | None) -> list[Activity]:
    """查所有待回填的活动：completed cycling + (max_cadence NULL 或 power_zones NULL)。"""
    q = db.query(Activity).filter(
        Activity.status == "completed",
        Activity.activity_type == "cycling",
        # 任一字段 NULL 都算待回填（最终是否真写入还要看 trackpoints 有没有对应数据）
        (Activity.max_cadence.is_(None)) | (Activity.power_zones.is_(None)),
    )
    if user_id_filter is not None:
        q = q.filter(Activity.user_id == user_id_filter)
    return q.order_by(Activity.user_id, Activity.id).all()


def _print_dry_run_stats(db, activities: list[Activity]) -> None:
    """干跑：打印影响范围 + 按用户分组（含 ftp 标记）。"""
    total = len(activities)
    if total == 0:
        logger.info("没有待回填的活动。")
        return

    by_user = Counter(a.user_id for a in activities)
    needs_cadence = sum(1 for a in activities if a.max_cadence is None)
    needs_zones = sum(1 for a in activities if a.power_zones is None)

    logger.info("=== 待回填统计 ===")
    logger.info("总数: %d", total)
    logger.info("缺 max_cadence: %d", needs_cadence)
    logger.info("缺 power_zones: %d", needs_zones)
    logger.info("按用户分组:")
    for user_id, count in by_user.most_common():
        user = db.query(User).filter_by(id=user_id).first()
        if user and user.ftp:
            ftp_info = f"ftp={user.ftp}"
        else:
            ftp_info = "ftp=NULL（power_zones 无法算 / 只回 max_cadence）"
        logger.info("  user_id=%d (%s): %d 条", user_id, ftp_info, count)


def backfill_one(db, activity: Activity, user_ftp: int | None) -> tuple[bool, bool]:
    """
    回填单条活动的 max_cadence + power_zones。

    返回 (cadence_updated, zones_updated)：
    - cadence_updated: max_cadence 是否真写入新值（之前是 NULL 且 trackpoints 有踏频）
    - zones_updated: power_zones 是否真写入新值（之前是 NULL 且 trackpoints 有功率 + 用户有 ftp）
    """
    cadence_updated = False
    zones_updated = False

    # 拉 trackpoints —— 只取需要的列省内存
    # ORDER BY seq 保证按时间顺序（seq 跟 timestamp 同向）/ power_zones 算需要相邻点时间差
    tps = (
        db.query(
            Trackpoint.cadence,
            Trackpoint.power,
            Trackpoint.timestamp,
        )
        .filter(Trackpoint.activity_id == activity.id)
        .order_by(Trackpoint.seq)
        .all()
    )

    if not tps:
        return False, False

    # 算 max_cadence（如果之前 NULL）
    if activity.max_cadence is None:
        cad_values = [tp.cadence for tp in tps if tp.cadence is not None]
        if cad_values:
            activity.max_cadence = float(max(cad_values))
            cadence_updated = True

    # 算 power_zones（如果之前 NULL 且有 ftp）
    if activity.power_zones is None and user_ftp is not None and user_ftp > 0:
        # calculate_power_zones 入参格式：list[dict] 含 "power" + "time" 字段
        # Trackpoint.timestamp → dict["time"]（对照 strava_adapter.py:200-203 同 pattern）
        tp_dicts = [
            {"power": tp.power, "time": tp.timestamp}
            for tp in tps
        ]
        result = calculate_power_zones(tp_dicts, user_ftp)
        if result is not None:
            activity.power_zones = result
            zones_updated = True

    return cadence_updated, zones_updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill max_cadence + power_zones for historical activities.")
    parser.add_argument("--dry-run", action="store_true", help="只统计影响范围不改 DB")
    parser.add_argument("--user-id", type=int, default=None, help="限定单个用户（小批量验证用）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        activities = _query_pending(db, args.user_id)

        if args.dry_run:
            _print_dry_run_stats(db, activities)
            return 0

        if not activities:
            logger.info("没有待回填的活动。")
            return 0

        # 预先按 user_id 取 ftp 一次性 join / 避免循环里反复查
        user_ids = set(a.user_id for a in activities)
        ftp_map = {
            u.id: u.ftp for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }

        cadence_success = 0
        zones_success = 0
        skipped_no_data = 0  # 既没 cadence 也没 power_zones 能更新（trackpoints 都没数据）
        failed: list[int] = []
        total = len(activities)

        logger.info("=== 开始回填 %d 条活动 ===", total)

        for i, activity in enumerate(activities, 1):
            try:
                # SAVEPOINT 隔离：一条失败不污染整批
                with db.begin_nested():
                    user_ftp = ftp_map.get(activity.user_id)
                    c_upd, z_upd = backfill_one(db, activity, user_ftp)
                    if c_upd:
                        cadence_success += 1
                    if z_upd:
                        zones_success += 1
                    if not c_upd and not z_upd:
                        skipped_no_data += 1
            except Exception:
                logger.exception("backfill activity id=%s failed", activity.id)
                failed.append(activity.id)

            if i % _COMMIT_EVERY == 0:
                db.commit()
                logger.info(
                    "进度: %d/%d 已处理 / cadence %d / zones %d / skip %d / fail %d",
                    i, total, cadence_success, zones_success, skipped_no_data, len(failed),
                )

        db.commit()
        logger.info(
            "=== 完成 ===\n  total=%d\n  cadence 回填=%d\n  power_zones 回填=%d\n  skip（无数据/无 ftp）=%d\n  failed=%d: %s",
            total, cadence_success, zones_success, skipped_no_data, len(failed), failed,
        )
        return 0 if not failed else 1

    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
