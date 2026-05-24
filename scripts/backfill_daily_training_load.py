"""
Sprint 10 task-3：把历史活动搬进 daily_training_load 每日训练账本。

操作注意事项：裸跑必须是 dry-run，只有显式传 `--apply` 才写库；核心 helper 只 flush 不 commit，
因为 Task 6 的 Strava 批量导入完成后也会复用它，提交或回滚必须由外层调用方决定。

输入/输出数据流：输入是 activities 里完成态骑行的 started_at 与 tss；输出是 daily_training_load
按用户、按北京时间自然日的一页页快照，供训练日历 API、worker 增量更新和 Sprint 12 教练总结读取。
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
import sys
import time

from sqlalchemy import func

from app.activity.models import Activity
from app.database import SessionLocal
from app.training.models import DailyTrainingLoad
from app.training.training_load import (
    calculate_daily_atl,
    calculate_daily_ctl,
    calculate_tsb,
    classify_tsb_status,
    round_1 as _round_1,
)
from app.training.service import _acquire_user_daily_load_lock
from app.user.models import User  # noqa: F401 — standalone 脚本必须显式 import 外键表


logger = logging.getLogger(__name__)

DEFAULT_USER_ID = 2
_BJ_TZ = timezone(timedelta(hours=8))
_SLEEP_SECONDS = 0.5


@dataclass(frozen=True)
class DailyLoadPreview:
    """dry-run 预览的一页账本，字段与 DailyTrainingLoad 写表字段保持同名。"""

    date: date
    ctl: float
    atl: float
    tsb: float
    tss_today: float
    weekly_tss: int
    status_band: str


def _today_bj() -> date:
    """返回北京时间今天的日期。"""
    return datetime.now(_BJ_TZ).date()


def _to_bj_date(value: datetime) -> date:
    """
    把活动开始时间归到北京时间自然日。

    PostgreSQL 会返回带时区的 datetime；SQLite 测试库有时会丢 tzinfo。
    如果遇到 naive 值，这里按 UTC 处理，因为 Activity.started_at 的项目合同就是 UTC。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_BJ_TZ).date()


def _get_start_date(db, user_id: int) -> date | None:
    """查该用户最早一条完成态骑行，用它决定账本从哪一天开始。"""
    row = (
        db.query(Activity.started_at)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.started_at.isnot(None),
        )
        .order_by(Activity.started_at.asc(), Activity.id.asc())
        .first()
    )
    if row is None or row.started_at is None:
        return None
    return _to_bj_date(row.started_at)


def _load_tss_by_date(db, user_id: int) -> dict[date, float]:
    """把完成态骑行按北京时间日期聚合成每日 TSS。"""
    rows = (
        db.query(Activity.started_at, Activity.tss)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.started_at.isnot(None),
            Activity.tss.isnot(None),
        )
        .order_by(Activity.started_at.asc(), Activity.id.asc())
        .all()
    )

    tss_by_date: dict[date, float] = defaultdict(float)
    for started_at, tss in rows:
        tss_by_date[_to_bj_date(started_at)] += float(tss)
    return dict(tss_by_date)


def preview_daily_training_load_for_user(db, user_id: int) -> list[DailyLoadPreview]:
    """
    只计算、不写表：给 dry-run 和测试查看将要写入的每日训练负荷。
    """
    start_date = _get_start_date(db, user_id)
    if start_date is None:
        return []

    end_date = _today_bj()
    tss_by_date = _load_tss_by_date(db, user_id)
    rows: list[DailyLoadPreview] = []
    rolling_tss: deque[float] = deque(maxlen=7)
    last_ctl: float | None = None
    last_atl: float | None = None

    day = start_date
    while day <= end_date:
        tss_today = tss_by_date.get(day, 0.0)
        ctl = calculate_daily_ctl(last_ctl, tss_today)
        atl = calculate_daily_atl(last_atl, tss_today)
        tsb = calculate_tsb(ctl, atl)
        rolling_tss.append(tss_today)

        rows.append(
            DailyLoadPreview(
                date=day,
                ctl=_round_1(ctl),
                atl=_round_1(atl),
                tsb=_round_1(tsb),
                tss_today=_round_1(tss_today),
                weekly_tss=int(round(sum(rolling_tss))),
                status_band=classify_tsb_status(tsb),
            )
        )

        last_ctl = ctl
        last_atl = atl
        day += timedelta(days=1)

    return rows


def _upsert_daily_load_row(db, user_id: int, row: DailyLoadPreview) -> None:
    """按 user_id + date 写入或更新同一页训练账本。"""
    existing = (
        db.query(DailyTrainingLoad)
        .filter(
            DailyTrainingLoad.user_id == user_id,
            DailyTrainingLoad.date == row.date,
        )
        .first()
    )

    if existing is None:
        db.add(
            DailyTrainingLoad(
                user_id=user_id,
                date=row.date,
                ctl=row.ctl,
                atl=row.atl,
                tsb=row.tsb,
                tss_today=row.tss_today,
                weekly_tss=row.weekly_tss,
                status_band=row.status_band,
            )
        )
        return

    existing.ctl = row.ctl
    existing.atl = row.atl
    existing.tsb = row.tsb
    existing.tss_today = row.tss_today
    existing.weekly_tss = row.weekly_tss
    existing.status_band = row.status_band
    existing.updated_at = func.now()


def backfill_daily_training_load_for_user(db, user_id: int) -> int:
    """
    写入一个用户的每日训练负荷，返回 upsert 行数。

    这个 helper 只 flush 不 commit。可以把它想象成把账本页写好但先不盖章，
    最终盖章还是撕掉，交给外层脚本或 worker 决定。
    """
    _acquire_user_daily_load_lock(db, user_id)
    rows = preview_daily_training_load_for_user(db, user_id)
    if not rows:
        logger.info("user_id=%s 无历史完成态骑行 / skip", user_id)
        return 0

    for row in rows:
        _upsert_daily_load_row(db, user_id, row)
        db.flush()

    return len(rows)


def backfill_daily_training_load_for_all_users(db) -> dict[int, int]:
    """写入所有用户的每日训练负荷，返回 user_id 到行数的映射。"""
    user_ids = [row.id for row in db.query(User.id).order_by(User.id).all()]
    result: dict[int, int] = {}
    for user_id in user_ids:
        result[user_id] = backfill_daily_training_load_for_user(db, user_id)
    return result


def _log_preview(user_id: int, rows: list[DailyLoadPreview]) -> None:
    """打印 dry-run 摘要：前 10 行、后 10 行和范围统计。"""
    if not rows:
        logger.info("user_id=%s dry-run：无历史完成态骑行 / skip", user_id)
        return

    logger.info("user_id=%s dry-run：将生成 %d 行 daily_training_load", user_id, len(rows))
    logger.info("前 10 行：%s", rows[:10])
    logger.info("后 10 行：%s", rows[-10:])
    logger.info(
        "summary: ctl %.1f~%.1f / atl %.1f~%.1f / tsb %.1f~%.1f / weekly_tss %d~%d",
        min(row.ctl for row in rows),
        max(row.ctl for row in rows),
        min(row.atl for row in rows),
        max(row.atl for row in rows),
        min(row.tsb for row in rows),
        max(row.tsb for row in rows),
        min(row.weekly_tss for row in rows),
        max(row.weekly_tss for row in rows),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sprint 10：回填 daily_training_load 历史训练负荷。默认 dry-run，不写 DB。"
    )
    parser.add_argument("--apply", action="store_true", help="真写 DB；不传则只 dry-run")
    parser.add_argument("--user-id", type=int, default=DEFAULT_USER_ID, help="限定单个用户，默认 2")
    parser.add_argument("--all-users", action="store_true", help="处理全部用户；会忽略 --user-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db = SessionLocal()
    failed: list[int] = []

    try:
        if args.all_users:
            user_ids = [row.id for row in db.query(User.id).order_by(User.id).all()]
        else:
            user_ids = [args.user_id]

        for index, user_id in enumerate(user_ids):
            try:
                if args.apply:
                    written = backfill_daily_training_load_for_user(db, user_id)
                    db.commit()
                    logger.info("user_id=%s apply 完成：upsert %d 行", user_id, written)
                else:
                    rows = preview_daily_training_load_for_user(db, user_id)
                    _log_preview(user_id, rows)
                    db.rollback()
            except Exception:
                db.rollback()
                failed.append(user_id)
                logger.exception("user_id=%s daily_training_load 回填失败", user_id)

            if index < len(user_ids) - 1:
                time.sleep(_SLEEP_SECONDS)

        return 0 if not failed else 1
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sys.exit(main())
