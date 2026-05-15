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
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.notification.models import Notification
from app.notification.detector import classify
from app.segment.models import SegmentEffort, Segment
from app.segment.service import get_effort_rank
from app.activity.models import Activity, ActivityPrivacy
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
            and activity.started_at < datetime.now(timezone.utc) - timedelta(days=_STRAVA_HISTORY_DAYS)):
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
    expires_at = datetime.now(timezone.utc) + timedelta(days=_NOTIFICATION_TTL_DAYS)

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
    unread_only: bool = False,
) -> dict:
    """
    查询用户的通知列表，按时间倒序分页——"翻看公告栏上的便签"。

    JOIN 查出赛段名和对手昵称，前端无需二次请求。
    过滤掉已过期的通知（expires_at < now()）。

    v4 扩展（task-7.8）：
    1. 加 unread_only 参数——前端可按需只取未读（默认 False 保持向后兼容）
    2. 响应永远带 unread_count 字段——首页红点 + 通知页共用这个数字
    3. Segment 从 inner join 改 outer join——配合 task-7.1 把 segment_id 外键改成
       ON DELETE SET NULL。赛段被删后通知的 segment_id 会变 NULL，
       inner join 会把这类通知过滤掉，outerjoin 才能保留（segment_name=None，
       前端按 spec §3.1 兜底显示"该记录已失效"）。

    为什么 unread_count 独立查询（不从 items 里数）：
        items 受 page_size 限制——数出来的未读数 ≤ 实际未读数。
        独立跑一条 COUNT 查询，走 task-7.1 建立的部分索引
        idx_notifications_user_unread WHERE is_read=FALSE，极快。

    使用索引：idx_notif_user_created + idx_notifications_user_unread
    """
    now = datetime.now(timezone.utc)

    # 基础查询：JOIN 赛段名和对手昵称
    query = (
        db.query(
            Notification,
            Segment.name.label("segment_name"),
            User.nickname.label("rival_nickname"),
        )
        # ⚠ outer join：task-7.1 外键 SET NULL 后 segment_id 可能为 NULL，
        # 不能用 inner join，否则这类通知会被静默过滤掉
        .outerjoin(Segment, Segment.id == Notification.segment_id)
        .outerjoin(User, User.id == Notification.rival_user_id)
        .filter(
            Notification.user_id == user_id,
            Notification.expires_at > now,
        )
    )

    if unread_only:
        # 显式 == False——Python truthiness 陷阱：SQLAlchemy 表达式里用 not is_read
        # 会被当成 Python bool，生成的 SQL 不正确
        query = query.filter(Notification.is_read == False)  # noqa: E712

    query = query.order_by(Notification.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for notif, segment_name, rival_nickname in rows:
        items.append({
            "id": notif.id,
            "event_type": notif.event_type,
            "segment_id": notif.segment_id,
            "segment_name": segment_name,  # 可能为 None（外键 SET NULL 后）
            "activity_id": notif.activity_id,
            "elapsed_time": notif.elapsed_time,
            "rank": notif.rank,
            "rival_user_id": notif.rival_user_id,
            "rival_nickname": rival_nickname,
            "is_read": notif.is_read,
            "created_at": notif.created_at.isoformat() if notif.created_at else None,  # task-0.1 Codex: tz-aware 后 isoformat 自带 +00:00，禁止再加 Z 否则成 ...+00:00Z 畸形
        })

    # ---- unread_count 独立查询 ----
    # 无论 unread_only 为何值都返回：首页红点调 unread_only=True&page_size=1
    # 时只关心这个数字；通知页列表也要同一个数字显示红点
    unread_count = (
        db.query(sa.func.count(Notification.id))
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
            Notification.expires_at > now,
        )
        .scalar()
    )

    return {
        "items": items,
        "total": total,
        "unread_count": unread_count,
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

    # task-4.2：荣誉墙 rank 跟主排行榜（每人一行）一致——
    # 第一层：ROW_NUMBER per (segment_id, user_id) 选每人在每赛段的最佳 effort（rn=1）
    # 第二层：RANK() per segment_id 按"每人最佳"排名
    # 否则 Alice 30s/35s + Bob 40s → 老逻辑里 Bob rank=3，主榜显示 rank=2，数字对不上。
    #
    # task-4.1 延伸：过滤他人私密 effort（保留 owner 自己的 / 跟主榜行为一致）。
    # Codex 异源审 I3：双层窗口都用 (elapsed_time, id) tiebreaker，跟主榜 helper 一致
    # （否则双重并列时跨 dialect 行为不一致 / 跟主榜数字分叉）
    row_number_per_user = (
        sa.func.row_number().over(
            partition_by=[SegmentEffort.segment_id, SegmentEffort.user_id],
            order_by=[SegmentEffort.elapsed_time, SegmentEffort.id],
        )
    ).label("rn")

    best_per_user = (
        db.query(
            SegmentEffort.id.label("effort_id"),
            SegmentEffort.segment_id,
            SegmentEffort.user_id,
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.created_at,
            row_number_per_user,
        )
        .outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
        .filter(SegmentEffort.segment_id.in_(sa.select(user_segments.c.segment_id)))
        .filter(
            sa.or_(
                ActivityPrivacy.visibility == "public",
                ActivityPrivacy.visibility.is_(None),
                SegmentEffort.user_id == user_id,
            )
        )
        .subquery()
    )

    # 第二层窗口：按"每人最佳"在赛段内排名（用 effort_id tiebreaker 跟主榜对齐）
    rank_col = (
        sa.func.rank().over(
            partition_by=best_per_user.c.segment_id,
            order_by=[best_per_user.c.elapsed_time, best_per_user.c.effort_id],
        )
    ).label("rank")

    ranked_query = (
        db.query(
            best_per_user.c.segment_id,
            Segment.name.label("segment_name"),
            best_per_user.c.user_id,
            best_per_user.c.elapsed_time,
            best_per_user.c.avg_speed,
            best_per_user.c.created_at,
            rank_col,
        )
        .select_from(best_per_user)
        .join(Segment, Segment.id == best_per_user.c.segment_id)
        .filter(best_per_user.c.rn == 1)
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
            "achieved_at": row.created_at.isoformat() if row.created_at else None,  # task-0.1 Codex: tz-aware 后 isoformat 自带 +00:00
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
    now = datetime.now(timezone.utc)
    count = (
        db.query(Notification)
        .filter(Notification.expires_at < now)
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info("清理过期通知 %d 条", count)
    return count


def mark_all_read(db: Session, user_id: int) -> int:
    """
    把当前用户所有未读通知标为已读——"广播室一键盖章：所有便签标为已看过"。

    幂等性保障（无需额外去重逻辑）：
        SQL 层自带 `WHERE is_read == False` 过滤——已读的不会被重复计数。
        重复调用返回 0，前端可以放心"进页即标读"。

    为什么用 == False 而不用 not is_read：
        Python truthiness 陷阱——SQLAlchemy 表达式里 not 作用在 Column 对象上
        会当成 Python bool，生成的 SQL 不对。必须用显式 == False。

    索引支撑：
        task-7.1 建立的部分索引 idx_notifications_user_unread（user_id, expires_at）
        WHERE is_read=FALSE，此 UPDATE 走这个部分索引，即使全表有百万通知也只扫未读行。

    崩溃恢复：
        .update(...) 是单条 SQL，PostgreSQL 保证原子性——要么全标要么都不标。
        事务崩溃回滚到调用前状态，不会出现"标了一半"的半态。

    Args:
        db: SQLAlchemy Session
        user_id: 当前用户 ID

    Returns:
        本次标读的数量（0 表示本来就全读了）
    """
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712 — SQLAlchemy 需要显式 == False
        )
        .update(
            {Notification.is_read: True},
            synchronize_session=False,
        )
    )
    db.commit()
    logger.info("mark_all_read user_id=%d 标读 %d 条", user_id, count)
    return count
