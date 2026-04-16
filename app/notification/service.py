# app/notification/service.py
"""
通知业务逻辑——"广播室的工作人员"。

这个文件包含四个函数，对应广播室的四项日常工作：
1. detect_events() — 检测事件并写通知（裁判登记完成绩后，广播室判断要不要广播）
2. get_notifications() — 查询通知列表（选手查看公告栏上的便签）
3. get_user_honors() — 查询用户荣誉表（选手查看自己的奖杯柜）
4. cleanup_expired() — 清理过期通知（60 天后撕掉旧便签）

操作注意事项：
- detect_events 必须用 try/except + SAVEPOINT 隔离，任何异常只记日志，绝不向上抛
- 不要在这里 import auto_match 或 import_scheduler（方向反了，是它们调用我们）
- 排名计算复用 segment/service.get_effort_rank，不要重复实现
"""
import logging
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.notification.models import Notification
from app.notification.detector import classify
from app.segment.models import SegmentEffort, Segment
from app.segment.service import get_effort_rank
from app.activity.models import Activity
from app.user.models import User

logger = logging.getLogger(__name__)

# 通知保留天数——60 天后由 cleanup_expired 清理
_NOTIFICATION_TTL_DAYS = 60
# Strava 历史导入跳过阈值——超过 7 天的 Strava 活动不触发通知
_STRAVA_HISTORY_DAYS = 7


def detect_events(db: Session, effort: SegmentEffort) -> None:
    """
    检测 PR/KOM 事件并写入通知表。

    这是 notification 模块暴露给外部的唯一写入接口。
    auto_match.py 和 import_scheduler.py 在赛段成绩 commit 后调用此函数。

    故障隔离策略：
    - 整个函数用 try/except 包裹，任何异常只记日志，不向上抛
    - 数据库写入用 db.begin_nested()（SAVEPOINT）隔离
    - 幂等：effort_id + event_type 的 UNIQUE 约束防重复，IntegrityError 静默跳过
    """
    try:
        _detect_events_inner(db, effort)
    except Exception:
        logger.warning(
            "通知检测失败 effort_id=%s segment_id=%s",
            effort.id, effort.segment_id, exc_info=True,
        )
        # 回滚通知事务，不影响已 commit 的成绩
        db.rollback()


def _detect_events_inner(db: Session, effort: SegmentEffort) -> None:
    """detect_events 的内部实现，异常向上抛由外层 try/except 捕获。"""
    # ---- 前置过滤：跳过 Strava 历史导入 ----
    # 好比广播室有条规矩：从档案馆搬来的旧成绩不播报，只播实时成绩
    activity = db.get(Activity, effort.activity_id)
    if activity is None:
        return

    if (activity.data_source == "strava"
            and activity.started_at is not None
            and activity.started_at < datetime.utcnow() - timedelta(days=_STRAVA_HISTORY_DAYS)):
        logger.debug(
            "跳过 Strava 历史活动通知 effort_id=%s activity_id=%s",
            effort.id, effort.activity_id,
        )
        return

    # ---- 查排名（共享函数）----
    rank = get_effort_rank(db, effort)

    # ---- 查 PR ----
    # 当前 effort 已 commit 入库，MIN 结果包含 effort 自身
    # 所以用 <=：best_time == effort.elapsed_time 时就是 PR
    # （要么是第一条成绩，要么打平了历史最佳，两者都算 PR）
    best_time = (
        db.query(sa.func.min(SegmentEffort.elapsed_time))
        .filter(
            SegmentEffort.segment_id == effort.segment_id,
            SegmentEffort.user_id == effort.user_id,
        )
        .scalar()
    )
    is_pr = (effort.elapsed_time <= best_time) if best_time is not None else True

    # ---- 查原 KOM 持有者（仅 rank==1 时需要）----
    # 当前用户的 effort 已 commit，此时查排行榜当前用户就是第一名
    # 原来的 KOM 持有者现在排第二 → 查 OFFSET 1 就是原 KOM 持有者
    previous_kom_user_id = None
    if rank == 1:
        second_place = (
            db.query(SegmentEffort.user_id)
            .filter(SegmentEffort.segment_id == effort.segment_id)
            .order_by(SegmentEffort.elapsed_time, SegmentEffort.created_at)
            .offset(1)
            .limit(1)
            .first()
        )
        if second_place is not None:
            previous_kom_user_id = second_place[0]

    # ---- 纯函数判定 ----
    event_result, kom_lost_result = classify(
        elapsed_time=effort.elapsed_time,
        rank=rank,
        is_pr=is_pr,
        previous_kom_user_id=previous_kom_user_id,
        current_user_id=effort.user_id,
    )

    if event_result is None:
        return  # 不是 PR，不生成通知

    # ---- 写入通知（SAVEPOINT 隔离）----
    expires_at = datetime.utcnow() + timedelta(days=_NOTIFICATION_TTL_DAYS)

    with db.begin_nested():
        # 当前用户的通知（PR 或 KOM）
        notif = Notification(
            user_id=effort.user_id,
            event_type=event_result.event_type,
            segment_id=effort.segment_id,
            activity_id=effort.activity_id,
            effort_id=effort.id,
            elapsed_time=effort.elapsed_time,
            rank=event_result.rank,
            expires_at=expires_at,
        )
        db.add(notif)

        try:
            db.flush()
        except IntegrityError:
            # 幂等：重复通知被 UNIQUE 约束拦住，静默跳过
            db.rollback()
            return

    db.commit()

    # KOM 被夺通知（独立 SAVEPOINT，一条失败不影响另一条）
    if kom_lost_result is not None:
        with db.begin_nested():
            lost_notif = Notification(
                user_id=kom_lost_result.previous_holder_user_id,
                event_type="kom_lost",
                segment_id=effort.segment_id,
                activity_id=effort.activity_id,
                effort_id=effort.id,
                elapsed_time=None,
                rank=kom_lost_result.new_rank,
                rival_user_id=effort.user_id,
                expires_at=expires_at,
            )
            db.add(lost_notif)

            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return

        db.commit()


def get_notifications(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    查询用户的通知列表，按时间倒序分页——"翻看公告栏上的便签"。

    JOIN 查出赛段名和对手昵称，前端无需二次请求。
    过滤掉已过期的通知（expires_at < now()）。

    使用索引：idx_notif_user_created
    """
    now = datetime.utcnow()

    # 基础查询：JOIN 赛段名和对手昵称
    query = (
        db.query(
            Notification,
            Segment.name.label("segment_name"),
            User.nickname.label("rival_nickname"),
        )
        .join(Segment, Segment.id == Notification.segment_id)
        .outerjoin(User, User.id == Notification.rival_user_id)
        .filter(
            Notification.user_id == user_id,
            Notification.expires_at > now,
        )
        .order_by(Notification.created_at.desc())
    )

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for notif, segment_name, rival_nickname in rows:
        items.append({
            "id": notif.id,
            "event_type": notif.event_type,
            "segment_id": notif.segment_id,
            "segment_name": segment_name,
            "activity_id": notif.activity_id,
            "elapsed_time": notif.elapsed_time,
            "rank": notif.rank,
            "rival_user_id": notif.rival_user_id,
            "rival_nickname": rival_nickname,
            "created_at": notif.created_at.isoformat() + "Z" if notif.created_at else None,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_user_honors(db: Session, user_id: int) -> dict:
    """
    查询用户的 KOM 和前十名成绩——"打开奖杯柜"。

    实时查询（不走 notifications 表），直接从 segment_efforts 用窗口函数算排名。
    一次查出所有赛段排名，零 N+1。

    好比体育馆的荣誉墙：不看公告栏（那是临时便签），而是去成绩档案室查真实排名。
    """
    # 子查询：该用户有成绩的赛段 ID 列表
    user_segments = (
        db.query(SegmentEffort.segment_id)
        .filter(SegmentEffort.user_id == user_id)
        .distinct()
        .subquery()
    )

    # 窗口函数：所有成绩 + 排名
    # RANK() OVER (PARTITION BY segment_id ORDER BY elapsed_time, created_at)
    # 好比把每条赛道的成绩单独排名，同时间先到先得
    rank_col = (
        sa.func.rank().over(
            partition_by=SegmentEffort.segment_id,
            order_by=[SegmentEffort.elapsed_time, SegmentEffort.created_at],
        )
    ).label("rank")

    ranked_query = (
        db.query(
            SegmentEffort.segment_id,
            Segment.name.label("segment_name"),
            SegmentEffort.user_id,
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.created_at,
            rank_col,
        )
        .join(Segment, Segment.id == SegmentEffort.segment_id)
        .filter(SegmentEffort.segment_id.in_(sa.select(user_segments.c.segment_id)))
        .subquery()
    )

    # 筛选：该用户 + 排名 <= 10
    results = (
        db.query(ranked_query)
        .filter(
            ranked_query.c.user_id == user_id,
            ranked_query.c.rank <= 10,
        )
        .order_by(ranked_query.c.rank, ranked_query.c.segment_name)
        .all()
    )

    koms = []
    top10s = []
    for row in results:
        entry = {
            "segment_id": row.segment_id,
            "segment_name": row.segment_name,
            "elapsed_time": row.elapsed_time,
            "avg_speed": row.avg_speed,
            "rank": row.rank,
            "achieved_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        }
        if row.rank == 1:
            koms.append(entry)
        else:
            top10s.append(entry)

    return {
        "koms": koms,
        "top10s": top10s,
        "kom_count": len(koms),
        "top10_count": len(top10s),
    }


def cleanup_expired(db: Session) -> int:
    """
    删除过期通知——"撕掉 60 天前的旧便签"。

    由定时任务每天调用一次。返回删除的条数，供日志记录。
    使用索引：idx_notif_expires
    """
    now = datetime.utcnow()
    count = (
        db.query(Notification)
        .filter(Notification.expires_at < now)
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info("清理过期通知 %d 条", count)
    return count
