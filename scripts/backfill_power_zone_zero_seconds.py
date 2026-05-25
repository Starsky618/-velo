"""
Sprint 11 task-6：给历史 power_zones 补 Z1.zero_seconds。

操作注意事项：默认只 dry-run，不写库；只有显式传 `--apply` 才真正改 activities.power_zones。
输入/输出数据流：输入是 completed cycling 活动的 trackpoints 和已有 power_zones；
输出是复用 calculate_power_zones 重算后的 power_zones，其中 Z1 带 zero_seconds。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
import sys
import time

from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import calculate_power_zones
from app.database import SessionLocal
from app.training.distribution import normalize_power_zones
from app.user.models import User  # noqa: F401 — standalone 脚本必须显式 import 外键表


logger = logging.getLogger(__name__)

DEFAULT_USER_ID = 2
_SLEEP_SECONDS = 0.5


@dataclass(frozen=True)
class PowerZoneZeroPreview:
    """dry-run 展示的一条活动差异，像施工前给你看旧照片和新照片。"""

    activity_id: int
    user_id: int
    ftp: int
    before_zero_seconds: int | None
    after_zero_seconds: int
    before_z1_seconds: int
    after_z1_seconds: int


def _query_candidates(db: Session, user_id: int) -> list[Activity]:
    """查需要考虑的历史活动：完成态骑行 + 已有 power_zones。"""
    return (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.power_zones.isnot(None),
        )
        .order_by(Activity.id.asc())
        .all()
    )


def _load_user_ftp(db: Session, user_id: int) -> int | None:
    """读取用户当前 FTP，只有活动没有 snapshot_ftp 时才用它兜底。"""
    row = db.query(User.ftp).filter(User.id == user_id).first()
    if row is None:
        return None
    return row.ftp


def _effective_ftp(activity: Activity, fallback_user_ftp: int | None) -> int | None:
    """
    选择重算用的 FTP。

    优先用 activity.snapshot_ftp：它像活动当天贴上的能力标签，
    比用户后来改过的当前 FTP 更适合保护历史区间边界。
    """
    ftp = activity.snapshot_ftp if activity.snapshot_ftp is not None else fallback_user_ftp
    if ftp is None or ftp <= 0:
        return None
    return int(ftp)


def _z1_item(power_zones: list[dict]) -> dict | None:
    """从 power_zones 里找到 Z1；没有就返回 None。"""
    for item in power_zones:
        if item.get("zone") == "Z1":
            return item
    return None


def _has_zero_seconds(activity: Activity) -> bool:
    """判断活动是否已经补过 zero_seconds。"""
    z1 = _z1_item(normalize_power_zones(activity.power_zones))
    return z1 is not None and "zero_seconds" in z1


def _load_trackpoint_dicts(db: Session, activity_id: int) -> list[dict]:
    """按 seq 拉轨迹点，并翻译成 calculate_power_zones 需要的 dict。"""
    rows = (
        db.query(Trackpoint.power, Trackpoint.timestamp)
        .filter(Trackpoint.activity_id == activity_id)
        .order_by(Trackpoint.seq.asc())
        .all()
    )
    return [{"power": row.power, "time": row.timestamp} for row in rows]


def _build_preview(db: Session, activity: Activity, fallback_user_ftp: int | None) -> PowerZoneZeroPreview | str:
    """
    计算一条活动的预览。

    返回字符串表示跳过原因；返回 PowerZoneZeroPreview 表示这条可以更新。
    """
    if _has_zero_seconds(activity):
        return "skipped_existing"

    ftp = _effective_ftp(activity, fallback_user_ftp)
    if ftp is None:
        return "skipped_no_ftp"

    before_z1 = _z1_item(normalize_power_zones(activity.power_zones))
    before_z1_seconds = int(before_z1.get("seconds") or 0) if before_z1 else 0
    before_zero_seconds = before_z1.get("zero_seconds") if before_z1 else None

    trackpoints = _load_trackpoint_dicts(db, activity.id)
    if len(trackpoints) < 2:
        return "skipped_no_trackpoints"

    recalculated = calculate_power_zones(trackpoints, ftp)
    if recalculated is None:
        return "skipped_no_result"

    after_z1 = _z1_item(recalculated)
    if after_z1 is None:
        return "skipped_no_result"

    return PowerZoneZeroPreview(
        activity_id=activity.id,
        user_id=activity.user_id,
        ftp=ftp,
        before_zero_seconds=before_zero_seconds,
        after_zero_seconds=int(after_z1.get("zero_seconds") or 0),
        before_z1_seconds=before_z1_seconds,
        after_z1_seconds=int(after_z1.get("seconds") or 0),
    )


def preview_power_zone_zero_seconds_for_user(db: Session, user_id: int) -> list[PowerZoneZeroPreview]:
    """dry-run：只返回会更新的活动预览，不写数据库。"""
    fallback_user_ftp = _load_user_ftp(db, user_id)
    previews: list[PowerZoneZeroPreview] = []
    for activity in _query_candidates(db, user_id):
        result = _build_preview(db, activity, fallback_user_ftp)
        if isinstance(result, PowerZoneZeroPreview):
            previews.append(result)
    return previews


def backfill_power_zone_zero_seconds_for_user(db: Session, user_id: int) -> dict[str, int]:
    """
    写入一个用户历史活动的 Z1.zero_seconds。

    这个 helper 只 flush，不 commit。外层脚本或测试决定最后提交还是回滚。
    """
    fallback_user_ftp = _load_user_ftp(db, user_id)
    stats = {
        "total": 0,
        "updated": 0,
        "skipped_existing": 0,
        "skipped_no_ftp": 0,
        "skipped_no_trackpoints": 0,
        "skipped_no_result": 0,
        "failed": 0,
    }

    for activity in _query_candidates(db, user_id):
        stats["total"] += 1
        try:
            with db.begin_nested():
                result = _build_preview(db, activity, fallback_user_ftp)
                if isinstance(result, str):
                    stats[result] += 1
                    continue

                ftp = result.ftp
                trackpoints = _load_trackpoint_dicts(db, activity.id)
                recalculated = calculate_power_zones(trackpoints, ftp)
                if recalculated is None:
                    stats["skipped_no_result"] += 1
                    continue

                activity.power_zones = recalculated
                db.flush()
                stats["updated"] += 1
        except Exception:
            stats["failed"] += 1
            logger.exception("activity_id=%s zero_seconds 回填失败", activity.id)

    return stats


def _log_preview(user_id: int, previews: list[PowerZoneZeroPreview]) -> None:
    """打印 dry-run 摘要，前 3 条给人工核对。"""
    logger.info("user_id=%s dry-run：将更新 %d 条活动", user_id, len(previews))
    for preview in previews[:3]:
        logger.info(
            "activity_id=%s ftp=%s Z1 %ss -> %ss / zero %s -> %ss",
            preview.activity_id,
            preview.ftp,
            preview.before_z1_seconds,
            preview.after_z1_seconds,
            preview.before_zero_seconds,
            preview.after_zero_seconds,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sprint 11：给历史 power_zones 补 Z1.zero_seconds。默认 dry-run，不写 DB。"
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
                    stats = backfill_power_zone_zero_seconds_for_user(db, user_id)
                    db.commit()
                    logger.info("user_id=%s apply 完成：%s", user_id, stats)
                else:
                    previews = preview_power_zone_zero_seconds_for_user(db, user_id)
                    _log_preview(user_id, previews)
                    db.rollback()
            except Exception:
                db.rollback()
                failed.append(user_id)
                logger.exception("user_id=%s zero_seconds 回填失败", user_id)

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
