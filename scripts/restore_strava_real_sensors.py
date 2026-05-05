"""
一次性恢复脚本 — 找回错被清的真功率/踏频数据。

干啥用：
  2026-05-06 PROD-4 hotfix 时，agent 基于 3 条 sample 推断 user_id=2 全部
  Strava 活动都是手表估算（device_watts=False），用 SQL WHERE user_id=X 全清
  power/cadence/calories/normalized_power 字段。
  实际：Tim 历史用过多种设备（Forerunner 手表 + Edge 840 + iGPSPORT BSC300 等），
  约 50% 是真功率器具数据。
  本脚本扫所有 status='completed' 的 strava 活动，调 Strava detail 判设备真假，
  真器具的从 Strava 重拉 streams + 重写字段，假的留空。

操作注意（教训沉淀）：
  - 跑脚本前先**暂停 scheduler**（避免共享 Strava API quota 撞限速）：
      UPDATE strava_imports SET status='paused' WHERE user_id={user_id};
  - 跑完后恢复 scheduler：
      UPDATE strava_imports SET status='active' WHERE user_id={user_id};
  - 脚本本身限速：每条间隔 ≥18s（保守，留 buffer 给其他进程）

输入/输出/接口：
  - 入：USER_ID（默认 2 / 命令行参数 --user-id）
  - 中：调 Strava API（每活动 2 calls）+ 写 DB（activity 字段 + trackpoints power/cadence）
  - 出：日志统计「真器具恢复 N 条 / 假估算跳过 M 条 / 错误 K 条」
"""
import argparse
import logging
import sys
import time

from app.activity.models import Activity, Trackpoint
from app.database import SessionLocal
from app.parsing.coord_normalizer import normalize
from app.parsing.strava_adapter import _has_real_cycling_sensors, from_streams
from app.strava.client import StravaClient
from app.user.models import User


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [restore] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# 限速节流：Strava 100 calls/15min = 9s/call。每条活动 2 calls = 18s/条。
# 保守 20s 留 buffer 给可能存在的其他后台进程。
_THROTTLE_SECONDS_PER_ACTIVITY = 20


def restore_user(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if user is None or user.strava_athlete_id is None:
            logger.error(f"User {user_id} not found or not bound to Strava")
            return

        client = StravaClient(db, user)

        activities = (
            db.query(Activity)
            .filter_by(user_id=user_id, data_source="strava", status="completed")
            .order_by(Activity.started_at.desc())
            .all()
        )

        logger.info(f"Total completed strava activities for user {user_id}: {len(activities)}")

        restored = 0
        skipped_fake = 0
        skipped_error = 0

        for idx, act in enumerate(activities, 1):
            try:
                detail = client.get_activity_detail(act.strava_activity_id)
                has_sensors = _has_real_cycling_sensors(detail)
                device_name = detail.get("device_name", "")

                if not has_sensors:
                    skipped_fake += 1
                    logger.info(
                        f"[{idx}/{len(activities)}] skip fake id={act.id} "
                        f"device='{device_name}' device_watts={detail.get('device_watts')}"
                    )
                    time.sleep(_THROTTLE_SECONDS_PER_ACTIVITY / 2)  # 只调了 1 call
                    continue

                # 真功率器具 → 重拉 streams 重新解析
                streams = client.get_activity_streams(act.strava_activity_id)
                ftp = int(user.ftp) if user.ftp else None
                parse = from_streams(streams, detail, ftp=ftp)
                parse = normalize(parse)

                # 写回 activity 摘要字段
                act.avg_power = parse.summary.avg_power
                act.max_power = parse.summary.max_power
                act.avg_cadence = parse.summary.avg_cadence
                act.calories = parse.summary.calories
                act.normalized_power = parse.summary.normalized_power
                # power_zones 也重新计算（如果 user 有 ftp）
                if parse.power_zones is not None:
                    act.power_zones = parse.power_zones

                # 写回 trackpoints power / cadence（按 seq 对齐 / 只写非 NULL）
                tps = (
                    db.query(Trackpoint)
                    .filter_by(activity_id=act.id)
                    .order_by(Trackpoint.seq)
                    .all()
                )
                # parse.trackpoints 是按 seq 重排的（dedupe 无效坐标后重新编号）
                # 直接按索引匹配是不严谨的（DB 里某些点可能被 dedupe 跳过）
                # 最稳：按 seq 字段匹配
                parse_by_seq = {tp.seq: tp for tp in parse.trackpoints}
                updated_tp_count = 0
                for tp in tps:
                    if tp.seq in parse_by_seq:
                        src = parse_by_seq[tp.seq]
                        if src.power is not None:
                            tp.power = src.power
                            updated_tp_count += 1
                        if src.cad is not None:
                            tp.cadence = src.cad

                db.commit()
                restored += 1
                logger.info(
                    f"[{idx}/{len(activities)}] restored id={act.id} title='{act.title}' "
                    f"device='{device_name}' tp_updated={updated_tp_count} avg_power={act.avg_power}"
                )

            except Exception as e:
                skipped_error += 1
                logger.warning(f"[{idx}/{len(activities)}] error id={act.id}: {e}")
                db.rollback()

            # 限速节流
            time.sleep(_THROTTLE_SECONDS_PER_ACTIVITY)

        logger.info(
            f"Done. Restored: {restored}  Skipped fake: {skipped_fake}  "
            f"Skipped error: {skipped_error}  Total: {len(activities)}"
        )

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="恢复 Strava 真功率/踏频数据")
    parser.add_argument("--user-id", type=int, default=2, help="目标 user_id（默认 2）")
    args = parser.parse_args()
    restore_user(args.user_id)


if __name__ == "__main__":
    main()
