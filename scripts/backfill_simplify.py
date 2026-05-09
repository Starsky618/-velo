"""task-4.2 v3 polish hotfix v5 回填脚本：重新简化所有 activity 的 simplified_track。

背景：
- simplify_track 默认 target_count 800 → 1500（多保留 50% 跳点间 GPS 点）
- 老 activity 的 simplified_track 字段仍是 800 点版本 / 山区显示断点严重（截图 #18）
- 本脚本扫所有 status='completed' + simplified_track IS NOT NULL 的 activity / 重跑 simplify(target_count=1500) / UPDATE

跑法（生产环境）：
    sudo docker compose exec -T api python -m scripts.backfill_simplify

幂等语义：覆盖式幂等
- 每次重算 simplified_track 并覆盖（纯函数 / 同样 trackpoints + 同样 target_count = 同样输出）
- 重跑无副作用 / 但浪费时间 / 默认跳过 simplified_track 已有 ≥ 1200 点的 activity（说明已经是新版）

风险：
- 每个 activity ~10ms（拉 trackpoints + 跑 DP + UPDATE）/ 236 activity ~3 秒
- Redis heatmap 缓存需要在跑完后清一次（让前端拿新 simplified_track）

退出码：
- 0：所有 activity 处理完
- 1：有 activity 处理失败（log 详情）
"""

from __future__ import annotations

import logging
import sys

from app.activity.models import Activity, Trackpoint
from app.activity.simplify import simplify_track
from app.database import SessionLocal
from app.user.models import User  # noqa: F401  # 注册 ORM mapper / Activity.user_id FK 引用 users 表必须 import


logger = logging.getLogger(__name__)


# 跳过阈值：simplified_track 已有 ≥ 1200 点说明跑过新版（target_count 1500 ± 20% = 1200-1800）
ALREADY_NEW_THRESHOLD = 1200


def backfill_all_activities(db, *, dry_run: bool = False) -> tuple[int, int, list[int]]:
    """
    重新简化所有 completed + 有 simplified_track 的 activity。

    返回：(processed, skipped, failed_ids)
    """
    activities = (
        db.query(Activity)
        .filter(
            Activity.status == "completed",
            Activity.simplified_track.isnot(None),
        )
        .all()
    )

    total = len(activities)
    logger.info(f"找到 {total} 个 activity 待处理（completed + 有 simplified_track）")

    processed = 0
    skipped = 0
    failed: list[int] = []

    for idx, activity in enumerate(activities, 1):
        # 跳过已是新版（target_count=1500 ± 20% 的）
        existing = activity.simplified_track or []
        if len(existing) >= ALREADY_NEW_THRESHOLD:
            skipped += 1
            if idx % 50 == 0:
                logger.info(f"进度 {idx}/{total} / 跳过新版 {skipped} 个")
            continue

        try:
            # 拉 trackpoints（按 seq 升序）
            tps = (
                db.query(Trackpoint)
                .filter(Trackpoint.activity_id == activity.id)
                .order_by(Trackpoint.seq)
                .all()
            )

            if not tps:
                logger.warning(f"activity {activity.id}: 无 trackpoints / 跳过")
                skipped += 1
                continue

            # 重跑 simplify_track（默认 target_count=1500）
            tp_dicts = [
                {"lat": tp.latitude, "lon": tp.longitude, "ele": tp.elevation}
                for tp in tps
            ]
            new_simplified = simplify_track(tp_dicts)

            if dry_run:
                logger.info(
                    f"[dry-run] activity {activity.id}: "
                    f"{len(existing)} → {len(new_simplified)} 点"
                )
            else:
                activity.simplified_track = new_simplified
                # SQLAlchemy 默认不识别 JSONB 字段内部修改 / 显式标记 dirty
                from sqlalchemy.orm import attributes
                attributes.flag_modified(activity, "simplified_track")
                db.commit()

            processed += 1
            if idx % 50 == 0:
                logger.info(f"进度 {idx}/{total} / 已处理 {processed} 个")

        except Exception as e:
            logger.error(f"activity {activity.id} 失败: {e}")
            failed.append(activity.id)
            db.rollback()

    return processed, skipped, failed


def main():
    import argparse
    parser = argparse.ArgumentParser(description="回填所有 activity 的 simplified_track（target_count=1500）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不真改")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    db = SessionLocal()
    try:
        processed, skipped, failed = backfill_all_activities(db, dry_run=args.dry_run)
        logger.info(
            f"完成 / 处理 {processed} / 跳过 {skipped} / 失败 {len(failed)} 个"
        )
        if failed:
            logger.warning(f"失败 activity ids: {failed}")
            sys.exit(1)
        sys.exit(0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
