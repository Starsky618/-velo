"""
5 分钟功率进步检测器——"骑行进步广播员"。

这个文件是干什么的：
用户上传新骑行后，对比"这次骑行的 5 分钟最大平均功率"和"上月最佳"，
如果进步 ≥ 5W，写一条 progress_5min_power 通知到 notifications 表。
前端在通知中心展示："你 5 分钟功率比上月进步 15W"。

它和 detector.py（PR/KOM 检测器）的关系：
- detector.py 是同步路径：上传 → 解析 → 匹配赛段 → 发现 PR/KOM → 写通知
- progress_detector.py 是异步路径：上传 → 解析完成 → 整体进步检测（与赛段无关）
两者都写 notifications 表，但 event_type 不同（pr/kom vs progress_*）。

输入/输出与防火墙：
- 输入：DB session + user_id + activity_id（已 status='completed'）
- 内部：query Activity / Trackpoint / User，调 power_zones 算 power_curve
- 输出：写 notifications 表（payload JSONB 存 current/prev/delta/window/period）
- 禁止：调 segment 模块 / 写 segment_efforts / 跨进 admin 模块

操作注意事项：
- 必须在 worker 把 activity.status 置 'completed' 后调（前面调读不到完整 trackpoints）
- baseline_5min <= 0 守卫不可省（上月骑行无功率计 → baseline=0 → 否则推假阳性"涨 200W"）
- 月份按北京时间 UTC+8 划分，与 spec §3.6 / §3.3 看他人主页的 power_curve 划分逻辑一致
- mute_notifications=True 用户跳过（与 PR/KOM 通知静音规则一致）
- 幂等：(activity_id, event_type) 部分唯一索引在 DB 层兜底（task-0.6 落地）
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.power_zones import (
    calculate_power_curve,
    calculate_power_curve_from_activities,
)
from app.notification.models import Notification
from app.user.models import User

# 进步阈值（PRD Q6 路径 C / Tim 2026-04-29 拍）
# 5W 是"明显感知到的进步"——比训练日波动（1-2W）大 / 比单次心情好坏（3-4W）大
# 但又不至于高到几个月才碰一次（推送频率太低用户感知不到产品价值）
PROGRESS_5MIN_POWER_THRESHOLD_W = 5

# 北京时区（CLAUDE.md 时区约定 / spec R3-C3：跨模块统一 UTC+8 划月）
_BJ_TZ = timezone(timedelta(hours=8))


def detect_5min_power_progress(
    db: Session,
    user_id: int,
    current_activity_id: int,
) -> Notification | None:
    """
    检测用户上传新 activity 后的 5min 最大平均功率进步。

    判定路径（任一不满足返 None / 不推送）：
    1. 当前 activity 5min 最大功率 > 0（无功率数据 → 不推）
    2. 上月有 ≥ 1 次 activity（无 baseline → 不推）
    3. 上月 5min 最大功率 > 0（功率全 0 / 无功率计 → 不推假阳性）
    4. delta = 当前 - 上月 ≥ 5W（进步不够 / 退步 → 不推）
    5. 用户未开启 mute_notifications（静音 → 不推）
    6. 同 activity 未推过同类通知（幂等 → 不推）

    陷阱守卫：
    - power=0 是合法值（休息段）→ power_curve 计算用 `is not None`，不用 `or 0`
    - "上月" 用 BJ_TZ +8 划分（4 月 1 日 0:00 BJ = 3 月 31 日 16:00 UTC）

    参数：
        db: SQLAlchemy session
        user_id: 用户 id
        current_activity_id: 刚完成的 activity id（worker 已置 status='completed'）

    返回：
        Notification 对象（写入成功）/ None（任一守卫拦截）
    """
    # ───── 1. 当前 activity 5min 功率 ─────
    current_tps = (
        db.query(Trackpoint)
        .filter(Trackpoint.activity_id == current_activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )
    current_curve = calculate_power_curve(current_tps, windows_sec=[300])
    current_5min = current_curve[300]

    if current_5min <= 0:
        # 当前活动无功率数据（GPX 里没 power 流 / 没接功率计）→ 没法对比
        return None

    # ───── 2. 上月时间窗口（按北京时间划月）─────
    # 例：现在是 2026-05-15 北京时间 → 本月 1 号 = 2026-05-01 00:00 BJ → 上月 = 2026-04-01..05-01 BJ
    # 跨年特殊：1 月 1 日 0 点北京 → 上月 = 上一年 12 月
    now_bj = datetime.now(timezone.utc).astimezone(_BJ_TZ)
    first_this_month_bj = now_bj.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if first_this_month_bj.month == 1:
        last_month_start_bj = first_this_month_bj.replace(
            year=first_this_month_bj.year - 1, month=12
        )
    else:
        last_month_start_bj = first_this_month_bj.replace(
            month=first_this_month_bj.month - 1
        )
    # 转回 UTC 用于 DB 查询（Activity.started_at Sprint 0 task-0.1 后是 tz-aware UTC）
    first_this_month = first_this_month_bj.astimezone(timezone.utc)
    last_month_start = last_month_start_bj.astimezone(timezone.utc)

    # ───── 3. 上月 baseline（按 activity 分组算，禁止跨 activity 拼接 trackpoints）─────
    baseline_activities = (
        db.query(Activity.id)
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.duplicate_of.is_(None),  # Sprint 5 task-2 dedupe：跳过 duplicate 防进步双计
            Activity.activity_type == "cycling",  # Sprint 7 Fix 7：5min 功率进步只算骑行 baseline
            Activity.started_at >= last_month_start,
            Activity.started_at < first_this_month,
        )
        .all()
    )

    if not baseline_activities:
        # 上月没骑过 → 没 baseline 可对比
        return None

    baseline_acts_tps = []
    for act in baseline_activities:
        tps = (
            db.query(Trackpoint)
            .filter(Trackpoint.activity_id == act.id)
            .order_by(Trackpoint.seq)
            .all()
        )
        baseline_acts_tps.append(tps)

    baseline_curve = calculate_power_curve_from_activities(
        baseline_acts_tps, windows_sec=[300]
    )
    baseline_5min = baseline_curve[300]

    # 关键守卫：上月所有骑行无功率（如全在训练台 / 全无功率计）→ baseline=0
    # 若不挡，下面 delta = current - 0 = current 大概率 ≥ 5W → 推假阳性"涨 200W"
    # "从无到有"不算"进步 5W+"——必须要有可对比的过去
    if baseline_5min <= 0:
        return None

    # ───── 4. 阈值检测 ─────
    delta = current_5min - baseline_5min
    if delta < PROGRESS_5MIN_POWER_THRESHOLD_W:
        # delta < 5W：进步不够 / 退步（负数）—— 都不推
        return None

    # ───── 5. 静音用户跳过 ─────
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.mute_notifications:
        return None

    # ───── 6. 幂等检查（worker 重试 / 并发会重复进入这条路径）─────
    # 应用层先查一遍避免无意义的 INSERT；DB 层部分唯一索引兜底真并发
    existing = (
        db.query(Notification)
        .filter(
            Notification.activity_id == current_activity_id,
            Notification.event_type == "progress_5min_power",
        )
        .first()
    )
    if existing:
        return None

    # ───── 7. 写 notification（payload JSONB 存对比快照）─────
    # expires_at 沿用 PR/KOM 通知 60 天过期约定（与 detector.py 一致 / models.py 注释）
    expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    notification = Notification(
        user_id=user_id,
        event_type="progress_5min_power",
        activity_id=current_activity_id,
        expires_at=expires_at,
        payload={
            "current_value": round(current_5min, 1),
            "prev_value": round(baseline_5min, 1),
            "delta": round(delta, 1),
            "window_sec": 300,
            "baseline_period": "last_month",
        },
    )

    # ⚠ SAVEPOINT 隔离（CLAUDE.md 关键技术约定 + 陷阱 #8）
    #
    # 为什么不用 db.commit()/db.rollback()：
    #   spec §3.4 worker 集成顺序是 "activity.status='completed' → detector → invalidate → db.commit()"
    #   即 detector 调用时，worker 已经在当前 session 改了 activity.status 但**还没 commit**。
    #   若 detector 内部直接 db.commit() 成功 → 会把 activity.status 一起提交（语义 OK），
    #   但若 db.commit() 失败（部分唯一索引冲突）→ db.rollback() 会把 activity.status 一起回退！
    #   → activity 卡回 'processing' 状态，worker 的工作"白干了"。
    #
    # SAVEPOINT 让 notification 写入失败只回退到嵌套点，外层 activity.status 不受影响，
    # 由 worker 在 detector 返回后统一 db.commit() 提交（spec §3.4 行 1700 钦定路径）。
    nested = db.begin_nested()
    try:
        db.add(notification)
        db.flush()
        nested.commit()
    except IntegrityError:
        # 真并发场景：另一个 worker 同时写入同 (activity_id, event_type)
        # 部分唯一索引 uniq_progress_notification_per_activity 触发约束
        nested.rollback()
        return None

    return notification
