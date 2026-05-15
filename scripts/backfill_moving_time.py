"""Sprint 5 polish 老活动 moving_time 回填脚本（一次性，幂等）。

为什么需要：
    `feat(activity): 加 moving_time 字段` 部署后，新解析的 Strava 活动会
    写入 moving_time。但**老活动**（Sprint 5 polish 之前同步进来的）
    数据库行 moving_time 列是 NULL —— 前端详情页"移动时间"显示 "-"。

    本脚本：对所有 strava_activity_id IS NOT NULL 且 moving_time IS NULL
    的 completed 活动，重新调一次 Strava API GET /activities/{id}，
    把返回的 moving_time 字段写回 DB。

幂等语义：
    跳过式幂等 —— 只动 moving_time IS NULL 的行。已有值的不动
    （即使 Strava 那边数字改了，也信任本地记录，避免破坏统计稳定性）。

跑法：
    # 干跑：只统计待回填条数 + 按用户分组打印，不调 API、不改 DB
    python3 -m scripts.backfill_moving_time --dry-run

    # 真跑：调 Strava API + 写 DB
    python3 -m scripts.backfill_moving_time

    # 限定单个用户（小批量验证用）
    python3 -m scripts.backfill_moving_time --user-id 1

限流保护：
    1. Strava 限流：100 req / 15 min → 平均 9 秒/req。默认 sleep 9s/条保守
       跑（一气呵成 / 不会被限流踢出）。
    2. --fast 模式 sleep 0.25s/条（4 req/s）：约 25s 就会触碰 100 上限，
       StravaClient 抛 StravaRateLimitError → 脚本 commit 当前进度退出，
       等 15 分钟再重跑下一批 ~100 条。适合赶时间手动分批跑。
    3. 单个用户 token 失效（refresh 过期等）→ 跳过该用户全部活动，继续下一个。

进度：
    每 20 条 db.commit() + 打印进度。中途崩溃最多损失最后 20 条进度。
"""

from __future__ import annotations

import argparse
from collections import Counter
import logging
import sys
import time

from app.activity.models import Activity
from app.database import SessionLocal
from app.strava.client import StravaClient, StravaRateLimitError
from app.strava.service_token import ensure_valid_token


logger = logging.getLogger(__name__)


# 节流：每条 API 调用之间 sleep 时长（秒）
# Strava 限流 100 req / 15 min → 平均 9 秒/req。默认保守 9s，一气呵成不被踢出。
# --fast 改 0.25s（4 req/s）会快速触发限流 → 脚本 commit 当前进度退出，
# Tim 等 15 分钟再重跑下一批（每批 ~95-100 条）。
_SLEEP_SEC_SAFE = 9.0
_SLEEP_SEC_FAST = 0.25

# 每 N 条 commit 一次 + 打印进度
_COMMIT_EVERY = 20


def _query_pending(db, user_id_filter: int | None) -> list[Activity]:
    """查所有待回填的活动：strava 来源 + moving_time NULL + completed。"""
    q = db.query(Activity).filter(
        Activity.strava_activity_id.isnot(None),
        Activity.moving_time.is_(None),
        Activity.status == "completed",
    )
    if user_id_filter is not None:
        q = q.filter(Activity.user_id == user_id_filter)
    return q.order_by(Activity.user_id, Activity.id).all()


def _print_dry_run_stats(activities: list[Activity]) -> None:
    """干跑模式：打印待回填条数 + 按用户分组明细 + 两种模式预估时间。"""
    total = len(activities)
    by_user = Counter(a.user_id for a in activities)
    logger.info("=== 干跑模式（不调 API / 不改 DB） ===")
    logger.info("待回填活动总数：%d 条", total)
    logger.info("按用户分组：")
    for uid, count in by_user.most_common():
        logger.info("  user_id=%d: %d 条", uid, count)
    # 两种模式预估
    safe_sec = total * (_SLEEP_SEC_SAFE + 0.3)
    # fast 模式：先跑 ~100 条触发限流，等 15min，再跑 ~100 条，循环
    batches = max(1, (total + 99) // 100)
    fast_sec = batches * (100 * 0.55 + 15 * 60)  # 0.25s sleep + 0.3s API
    logger.info(
        "默认（安全）跑预估：≈ %d 分钟一气呵成", int(safe_sec / 60),
    )
    logger.info(
        "--fast 跑预估：≈ %d 批 × 15 分钟限流等待 ≈ %d 分钟（人工分批）",
        batches, int(fast_sec / 60),
    )


def backfill_moving_time(
    db,
    user_id_filter: int | None = None,
    fast: bool = False,
) -> dict:
    """真跑回填。返回 stats dict。"""
    activities = _query_pending(db, user_id_filter)
    total = len(activities)
    sleep_sec = _SLEEP_SEC_FAST if fast else _SLEEP_SEC_SAFE
    logger.info(
        "=== 真跑模式：待回填 %d 条 / sleep %.2fs/条（%s）===",
        total, sleep_sec, "fast" if fast else "safe",
    )

    stats = {
        "success": 0,        # 成功写入 moving_time
        "no_field": 0,       # Strava API 返回里没 moving_time（极少）
        "api_error": 0,      # 单条 Strava API 调用失败
        "token_invalid": 0,  # 该用户 token 刷新失败（跳过其全部活动）
        "skipped_users": 0,
        "total": total,
    }

    current_user_id: int | None = None
    client: StravaClient | None = None
    skip_user_ids: set[int] = set()

    for idx, activity in enumerate(activities, start=1):
        # 该用户 token 已知失效 → 跳过
        if activity.user_id in skip_user_ids:
            stats["token_invalid"] += 1
            continue

        # 切换用户：刷新 token + 重建 client
        if activity.user_id != current_user_id:
            try:
                user, _ = ensure_valid_token(db, activity.user_id)
                client = StravaClient(user)
                current_user_id = activity.user_id
                logger.info("切换 user_id=%d", user.id)
            except Exception:
                # token 失效 / refresh 失败 → 该用户所有活动跳过
                logger.warning(
                    "user_id=%d token 无效，跳过该用户全部活动",
                    activity.user_id,
                )
                skip_user_ids.add(activity.user_id)
                stats["skipped_users"] += 1
                stats["token_invalid"] += 1
                continue

        # 调 Strava API 拿 moving_time
        assert client is not None
        try:
            with db.begin_nested():
                detail = client.get_activity_detail(activity.strava_activity_id)
                moving_time = detail.get("moving_time")
                if moving_time is None:
                    stats["no_field"] += 1
                    logger.warning(
                        "activity_id=%d strava 未返回 moving_time",
                        activity.id,
                    )
                else:
                    activity.moving_time = int(moving_time)
                    stats["success"] += 1
        except StravaRateLimitError:
            # 限流：保存进度退出
            db.commit()
            logger.error(
                "Strava 限流触发，已 commit 当前进度 %s。等 15 分钟后重跑。",
                stats,
            )
            return stats
        except Exception:
            logger.exception("activity_id=%d 回填失败", activity.id)
            stats["api_error"] += 1

        # 节流
        time.sleep(sleep_sec)

        # 进度 + commit
        if idx % _COMMIT_EVERY == 0:
            db.commit()
            logger.info("进度 %d/%d：%s", idx, total, stats)

    db.commit()
    logger.info("=== 完成：%s ===", stats)
    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="回填 Strava 来源老活动的 moving_time（一次性，幂等）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑：只统计待回填条数 + 按用户分组，不调 API / 不改 DB",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="只回填指定 user_id 的活动（小批量验证用）",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="激进节流 0.25s/条（默认 9s/条）。会触发限流退出 / 等 15min 重跑",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    db = SessionLocal()
    try:
        if args.dry_run:
            activities = _query_pending(db, args.user_id)
            _print_dry_run_stats(activities)
            return 0
        backfill_moving_time(db, user_id_filter=args.user_id, fast=args.fast)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
