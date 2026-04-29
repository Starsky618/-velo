"""第 5 期老数据回填脚本（一次性，幂等）。

跑这个的前置：
1. alembic upgrade 已跑到 task 0.6 的 v5 主迁移
2. task 1.A.1 的算法函数已经实现并可 import

跑法：
    python -m scripts.backfill_phase5
    python -m scripts.backfill_phase5 --segments
    python -m scripts.backfill_phase5 --users

幂等语义（两个函数不一样，故意的）：
- backfill_segments：**覆盖式幂等**——每次重算 max_gradient/difficulty/city 并覆盖，
  因为这些字段是从 trackpoints 推导的纯函数结果，重算无副作用
- backfill_users_city：**跳过式幂等**——只动 city IS NULL 的用户，已有 city 的不动。
  原因：未来 admin 工具 / 用户主页可能会让用户手工设置 city，
  自动回填脚本不该覆盖人工值。所以这是"首次推断"语义，不是"每次刷新"
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import logging
import sys

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select

from app.activity.models import Activity, Trackpoint
from app.common.geo import infer_city_from_coords
from app.database import SessionLocal
from app.segment.models import Segment
from app.segment.service import calculate_difficulty, calculate_max_gradient
from app.user.models import User


logger = logging.getLogger(__name__)


def backfill_segments(db) -> list[int]:
    """给现有 segments 回填 difficulty / max_gradient / city。"""
    segments = db.query(Segment).all()
    success = 0
    failed: list[int] = []

    for seg in segments:
        try:
            with db.begin_nested():
                # reference_line 是 PostGIS Geometry 列。如果用 cast(seg.reference_line, Geography)
                # 会把 ORM 实例属性（Python 端 EWKB hex 字符串）当 bind param，SQLAlchemy
                # 自动包 ST_GeogFromText 期望 WKT 格式 → PG parse error - invalid geometry。
                # 正解：用 scalar_subquery 让 SQL 渲染成列引用 segments.reference_line，
                # PG 自然 cast Geometry → Geography，不走 Python 字符串路径。
                ref_line_subq = (
                    select(Segment.reference_line)
                    .where(Segment.id == seg.id)
                    .scalar_subquery()
                )
                tps = (
                    db.query(Trackpoint)
                    .filter(
                        Trackpoint.geom.isnot(None),
                        func.ST_DWithin(
                            cast(Trackpoint.geom, Geography),
                            cast(ref_line_subq, Geography),
                            50,
                        ),
                    )
                    .order_by(Trackpoint.activity_id, Trackpoint.seq)
                    .all()
                )

                seg.max_gradient = calculate_max_gradient(tps) if tps else None
                seg.difficulty = calculate_difficulty(
                    seg.distance,
                    seg.elevation_gain if seg.elevation_gain is not None else 0.0,
                    seg.max_gradient if seg.max_gradient is not None else 0.0,
                )
                seg.city = infer_city_from_coords(seg.start_lat, seg.start_lon)

            success += 1
        except Exception:
            logger.exception("backfill segment id=%s failed", seg.id)
            failed.append(seg.id)

    db.commit()
    logger.info(
        "backfill segments: success=%d, failed=%d: %s",
        success,
        len(failed),
        failed,
    )
    return failed


def _infer_activity_city(activity: Activity) -> str:
    track = activity.simplified_track
    if not isinstance(track, list) or len(track) == 0:
        return "unknown"

    first = track[0]
    if not isinstance(first, dict):
        return "unknown"

    return infer_city_from_coords(first.get("lat"), first.get("lon"))


def _most_common_known_city(activities: list[Activity]) -> str | None:
    cities = [_infer_activity_city(activity) for activity in activities]
    known_cities = [city for city in cities if city != "unknown"]
    if not known_cities:
        return None
    return Counter(known_cities).most_common(1)[0][0]


def backfill_users_city(db) -> dict[str, int]:
    """按 30 天活动 → 全量活动 → 保持 NULL 的 fallback 链回填 users.city。"""
    all_users = db.query(User).all()
    users = [user for user in all_users if user.city is None]
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    stats = {
        "updated": 0,
        "unchanged_null": 0,
        "failed": 0,
        "skipped_existing": len(all_users) - len(users),
    }

    for user in users:
        try:
            with db.begin_nested():
                recent = (
                    db.query(Activity)
                    .filter(
                        Activity.user_id == user.id,
                        Activity.started_at >= cutoff_30d,
                        Activity.status == "completed",
                    )
                    .all()
                )
                city = _most_common_known_city(recent)

                if city is None:
                    all_activities = (
                        db.query(Activity)
                        .filter(
                            Activity.user_id == user.id,
                            Activity.status == "completed",
                        )
                        .all()
                    )
                    city = _most_common_known_city(all_activities)

                if city is None:
                    stats["unchanged_null"] += 1
                    continue

                user.city = city
                stats["updated"] += 1
        except Exception:
            logger.exception("backfill user.city user_id=%s failed", user.id)
            stats["failed"] += 1

    db.commit()
    logger.info("backfill users.city: %s", stats)
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill phase 5 segment/user fields.")
    parser.add_argument("--segments", action="store_true", help="只回填 segments")
    parser.add_argument("--users", action="store_true", help="只回填 users.city")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_segments = args.segments or not args.users
    run_users = args.users or not args.segments

    db = SessionLocal()
    try:
        seg_failed: list[int] = []
        if run_segments:
            logger.info("=== 阶段 1：回填 segments ===")
            seg_failed = backfill_segments(db)

        if run_users:
            logger.info("=== 阶段 2：回填 users.city ===")
            backfill_users_city(db)

        return 0 if not seg_failed else 1
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
