"""
Sprint 9 task-4：用户首次填 ftp 触发回填该用户所有 snapshot_ftp=NULL 活动。

—— "用户档案补登工"。

故事场景：用户在 velo 里骑了一个月（每条活动 snapshot_ftp 都是 NULL，因为
当时没填 ftp），今天他终于在 profile 页填了 ftp=220。我们应该回头把他
那一个月的活动都补上 snapshot_ftp=220，并且重新算 IF / TSS——这样训练
分析页一打开就有数据，不用让用户"等新骑行才看到训练强度"。

好比物业的"住户档案补登工"：新住户入住后某天补交了身份证号，物业把
他过去的所有报修记录、缴费记录都贴上身份证标签，方便统一查询。

幂等语义（跳过式 / 不是覆盖式）：
- 只动 snapshot_ftp IS NULL 的活动
- 已有 snapshot_ftp 值的活动 不动——这是历史训练数据的时间一致性保护
  （Strava 同步过来的活动 worker 已经填了 snapshot_ftp / 不该被用户改 ftp 后污染）

调用方：app/user/router.py update_profile / 检测旧 ftp NULL + 新 ftp 非 NULL 时入队

注意事项：
- 异步跑 / 不阻塞用户 PUT /profile 请求
- 走 RQ default_queue（与 GPX parse_activity 同队列）
- enqueue 在 router 层做（service 层只暴露 enqueue helper / 真函数）
- standalone job 入口 backfill_user_snapshot_ftp_job 自己拿 db session
  （RQ worker 进程独立 / 不走 FastAPI 依赖注入）
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import calculate_power_zones
from app.activity.worker import calculate_intensity_metrics
from app.database import SessionLocal
from app.queue import default_queue
from app.user.models import User  # noqa: F401 — standalone 进程防 ORM 外键找不到 users 表

logger = logging.getLogger(__name__)

# RQ job 超时 30 分钟（用户可能有几百条历史活动 / 每条要查 trackpoints 重算 zones）
# 与 GPX parse_activity 的 120s 相比量级大很多——backfill 是批量补登 / 慢工细活
_BACKFILL_JOB_TIMEOUT = 1800


def backfill_user_snapshot_ftp(db: Session, user_id: int, new_ftp: int) -> dict:
    """
    回填该用户所有 snapshot_ftp=NULL 活动。

    流程（每条活动）：
    1. snapshot_ftp = new_ftp（锁定）
    2. 如果活动有 normalized_power → 算 IF/TSS 写入
    3. 如果活动 power_zones 是 NULL → 查 trackpoints 重算 zones 写入

    幂等：跳过式 —— 已有 snapshot_ftp 值的活动 完全不动（不进 query 结果）。
    SAVEPOINT 隔离：每条活动用 db.begin_nested() —— 单条失败不影响其他活动
    （陷阱 #13 / 循环里 flush 失败不该炸整批）。

    参数：
        db: SQLAlchemy session（调用者负责生命周期）
        user_id: 用户 ID
        new_ftp: 新填的 ftp（W）

    返：
        统计 dict：{ total, zones_filled, if_tss_filled, failed }
    """
    activities = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.snapshot_ftp.is_(None),
            Activity.status == "completed",
            Activity.activity_type == "cycling",
        )
        .all()
    )

    stats = {"total": len(activities), "zones_filled": 0, "if_tss_filled": 0, "failed": 0}

    for activity in activities:
        try:
            # SAVEPOINT 隔离（陷阱 #13）：单条失败回退到 savepoint / 不影响其他活动
            with db.begin_nested():
                activity.snapshot_ftp = new_ftp

                # 1) 算 IF/TSS（共享 worker.calculate_intensity_metrics 真相源）
                if_val, tss = calculate_intensity_metrics(
                    np=activity.normalized_power,
                    ftp=new_ftp,
                    duration_seconds=activity.duration,
                )
                activity.intensity_factor = if_val
                activity.tss = tss
                if if_val is not None:
                    stats["if_tss_filled"] += 1

                # 2) 如果 power_zones 缺 → 查 trackpoints 重算
                # 注：power_zones 已有值的活动跳过（之前 worker 算过的不重算 / 省 trackpoints 查询）
                if activity.power_zones is None:
                    tps = (
                        db.query(Trackpoint.power, Trackpoint.timestamp)
                        .filter(Trackpoint.activity_id == activity.id)
                        .order_by(Trackpoint.seq)
                        .all()
                    )
                    if tps:
                        # calculate_power_zones 入参格式：[{"power", "time"}, ...]
                        tp_dicts = [
                            {"power": tp.power, "time": tp.timestamp} for tp in tps
                        ]
                        result = calculate_power_zones(tp_dicts, new_ftp)
                        if result is not None:
                            activity.power_zones = result
                            stats["zones_filled"] += 1
        except Exception:
            logger.exception("backfill activity id=%s failed", activity.id)
            stats["failed"] += 1

    db.commit()
    logger.info(
        "backfill_user_snapshot_ftp user_id=%s new_ftp=%s stats=%s",
        user_id, new_ftp, stats,
    )
    return stats


def backfill_user_snapshot_ftp_job(user_id: int, new_ftp: int) -> None:
    """
    RQ worker 入口——独立进程跑 / 自己拿 db session。

    被 enqueue_backfill_ftp 入队后由 RQ worker 实际执行。
    """
    db = SessionLocal()
    try:
        backfill_user_snapshot_ftp(db, user_id, new_ftp)
    finally:
        db.close()


def enqueue_backfill_ftp(user_id: int, new_ftp: int) -> None:
    """
    enqueue 一个 RQ 任务异步跑 backfill。

    用户 PUT /profile 改 ftp 立刻返 200 / 后台慢慢补登历史活动 / 不阻塞请求。
    走 default_queue（与 GPX parse_activity / Strava webhook 同队列）。

    陷阱 #14 防护（Codex 异源审 + Claude quality 双审独立抓 / 2026-05-20）：
    Redis 挂时 enqueue 抛异常 → 如果让异常上传到 router / DB ftp 已 commit 但 PUT 返 500
    → 用户重试 PUT / 因 old_ftp 已是新值 / first-fill guard 永久 False → 历史活动死局不再回填。
    修法：try/except 包 enqueue / 失败 logger.exception / 不抛 / PUT 仍返 200。
    代价：用户历史回填丢失 / 但 ftp 状态正确 / 新活动 worker 仍正常算 snapshot_ftp。
    后续：admin 手动触发 / 或下次新活动 worker 解析顺手补登（待 sprint 9.5 实现）。
    """
    try:
        default_queue.enqueue(
            "app.activity.backfill_ftp.backfill_user_snapshot_ftp_job",
            user_id,
            new_ftp,
            job_timeout=_BACKFILL_JOB_TIMEOUT,
        )
    except Exception:
        logger.exception(
            "enqueue_backfill_ftp 失败 user_id=%s new_ftp=%s / DB ftp 已 commit / "
            "历史活动需 admin 手动触发回填",
            user_id, new_ftp,
        )
