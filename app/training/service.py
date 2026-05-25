"""
训练负荷服务层像训练日历的"服务台"：从每日账本里取数据，整理成前端能直接画的曲线。

操作注意事项：读取接口只整理已有快照；写入 helper 只 flush 不 commit，让外层 worker 决定最终提交或回滚。

输入/输出数据流：读取时输入当前用户 id 与 range，输出 `points + summary`；写入时输入已完成 activity，
输出 daily_training_load 当天快照，给训练日历页、worker 和 scheduler 共用。
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
import logging

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.training.models import DailyTrainingLoad
from app.training.schemas import (
    TrainingLoadPoint,
    TrainingLoadRange,
    TrainingLoadResponse,
    TrainingLoadSummary,
)
from app.training.training_load import (
    calculate_daily_atl,
    calculate_daily_ctl,
    calculate_tsb,
    classify_tsb_status,
    format_status_label,
    round_1 as _round_1,
)
from app.user.models import User


logger = logging.getLogger(__name__)
_BJ_TZ = timezone(timedelta(hours=8))
_RANGE_DAYS: dict[TrainingLoadRange, int] = {
    "30d": 30,
    "90d": 90,
    "1y": 365,
}
_MIN_COMPLETE_DAYS = 14
# TSS 覆盖率门槛：30d 仍看 CTL 关心的最近 42 天；90d/1y 按用户正在看的时间窗判断。
# 这样最近几周无功率不会一刀切挡住全年历史曲线，但 30d 当前状态卡仍不会展示失真的 CTL。
_COVERAGE_WINDOW_DAYS_BY_RANGE: dict[TrainingLoadRange, int] = {
    "30d": 42,
    "90d": 90,
    "1y": 365,
}
_MIN_TSS_COVERAGE = 0.5


def _today_bj() -> date:
    """返回北京时间今天，和回填脚本使用同一套自然日口径。"""
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


def _bj_day_start_utc(target_day: date) -> datetime:
    """把北京时间某天 00:00 翻译成 UTC，像给查询画一条清楚的日历起跑线。"""
    return datetime(target_day.year, target_day.month, target_day.day, tzinfo=_BJ_TZ).astimezone(timezone.utc)


def _zero_summary() -> TrainingLoadSummary:
    """完全没有账本时的空状态卡。"""
    return TrainingLoadSummary(
        current_ctl=0.0,
        current_atl=0.0,
        current_tsb=0.0,
        current_status_band="ok",
        current_status_label=format_status_label("ok"),
        tss_today=0.0,
        weekly_tss=0,
        data_complete=False,
        insufficient_power_data=False,
    )


def _range_tss_coverage(db: Session, user_id: int, load_range: TrainingLoadRange) -> float:
    """
    当前 range 对应窗口内 completed cycling 活动的 TSS 覆盖率（有功率算出 TSS 的占比）。

    为什么要这道门槛：CTL 是 42 天滑窗，最近活动大量无功率（无 TSS）时
    CTL 会失真偏低（如严肃骑手真实 CTL 50+ 但因最近多无功率骑行被算成 5）。
    覆盖率 < 50% 时不展示 PMC，避免误导用户（跟砍 max_gradient 同一判断：
    数据达不到精度就别显示）。

    但 90d / 1y 是用户回看历史趋势，不应该被最近 42 天一刀切挡住；
    所以覆盖率窗口跟 range 联动，30d 仍用 42 天保护当前状态卡。
    无活动返 0.0（让 < 14 天历史那条逻辑接管）。
    """
    window_days = _COVERAGE_WINDOW_DAYS_BY_RANGE[load_range]
    today = _today_bj()
    start_day = today - timedelta(days=window_days - 1)
    end_day = today + timedelta(days=1)
    start_utc = _bj_day_start_utc(start_day)
    end_utc = _bj_day_start_utc(end_day)
    row = (
        db.query(
            func.count(Activity.id).label("total"),
            func.count(Activity.tss).label("has_tss"),
        )
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.started_at >= start_utc,
            Activity.started_at < end_utc,
        )
        .first()
    )
    total = int(row.total or 0) if row is not None else 0
    if total == 0:
        return 0.0
    return int(row.has_tss or 0) / total


def _row_to_point(row: DailyTrainingLoad) -> TrainingLoadPoint:
    """把 DB 行翻译成前端曲线点。"""
    return TrainingLoadPoint(
        date=row.date.isoformat(),
        ctl=row.ctl,
        atl=row.atl,
        tsb=row.tsb,
        tss_today=row.tss_today,
        status_band=row.status_band,
    )


def _make_summary(
    point: TrainingLoadPoint,
    weekly_tss: int,
    data_complete: bool,
    insufficient_power_data: bool = False,
) -> TrainingLoadSummary:
    """用最后一个曲线点生成顶部状态卡。"""
    return TrainingLoadSummary(
        current_ctl=point.ctl,
        current_atl=point.atl,
        current_tsb=point.tsb,
        current_status_band=point.status_band,
        current_status_label=format_status_label(point.status_band),
        tss_today=point.tss_today,
        weekly_tss=weekly_tss,
        data_complete=data_complete,
        insufficient_power_data=insufficient_power_data,
    )


def _latest_before(records: list[DailyTrainingLoad], target_day: date) -> DailyTrainingLoad | None:
    """找 target_day 之前最近的一页账本，用来给缺日自然衰减做起点。"""
    previous = [row for row in records if row.date < target_day]
    if not previous:
        return None
    return previous[-1]


def _query_latest_before(db: Session, user_id: int, target_day: date) -> DailyTrainingLoad | None:
    """用索引找窗口开始前最近一页账本，作为自然衰减的起点。"""
    return (
        db.query(DailyTrainingLoad)
        .filter(
            DailyTrainingLoad.user_id == user_id,
            DailyTrainingLoad.date < target_day,
        )
        .order_by(DailyTrainingLoad.date.desc())
        .first()
    )


def _sum_completed_cycling_tss_for_day(db: Session, user_id: int, target_day: date) -> float:
    """汇总北京时间某一天内所有完成态骑行的 TSS。"""
    day_start_bj = datetime(target_day.year, target_day.month, target_day.day, tzinfo=_BJ_TZ)
    day_start_utc = day_start_bj.astimezone(timezone.utc)
    day_end_utc = (day_start_bj + timedelta(days=1)).astimezone(timezone.utc)
    total = (
        db.query(func.coalesce(func.sum(Activity.tss), 0.0))
        .filter(
            Activity.user_id == user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.tss.isnot(None),
            Activity.started_at >= day_start_utc,
            Activity.started_at < day_end_utc,
        )
        .scalar()
    )
    return float(total or 0.0)


def _acquire_user_daily_load_lock(db: Session, user_id: int) -> None:
    """
    在 PostgreSQL 上锁住“某个用户的整本训练账本”。

    这像两个人同时改同一本账本前先拿钥匙：单活动 hook 和历史 backfill
    都排队进入，避免一个人刚写完今天，另一个人用旧预览把它覆盖掉。
    SQLite 测试库没有 advisory lock，直接跳过。

    ⚠ 锁作用域：pg_advisory_xact_lock 是事务级锁。在 worker hook 的 SAVEPOINT
    内获取后，nested.rollback() **不会**提前释放它——锁一直持有到外层 db.commit()。
    这是预期行为（锁保护窗口覆盖整个外层事务），但 worker 并发扩容时同用户其他
    活动会等到外层 commit 而非 nested.commit，未来排查串行延迟时注意这点。
    namespace 用 hashtext('daily-training-load') 跟项目既有 advisory lock 惯例
    （dedupe_service / service_create 都用 hashtext 自描述字符串）一致，防裸整数碰撞。
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return

    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('daily-training-load'), :user_id)"),
        {"user_id": int(user_id)},
    )


def _upsert_activity_day_row(
    db: Session,
    user_id: int,
    target_day: date,
    *,
    ctl: float,
    atl: float,
    tsb: float,
    tss_today: float,
    status_band: str,
) -> DailyTrainingLoad:
    """按 user_id + date 写入或更新当天训练账本。"""
    existing = (
        db.query(DailyTrainingLoad)
        .filter(
            DailyTrainingLoad.user_id == user_id,
            DailyTrainingLoad.date == target_day,
        )
        .first()
    )

    if existing is None:
        row = DailyTrainingLoad(
            user_id=user_id,
            date=target_day,
            ctl=_round_1(ctl),
            atl=_round_1(atl),
            tsb=_round_1(tsb),
            tss_today=_round_1(tss_today),
            weekly_tss=0,
            status_band=status_band,
        )
        db.add(row)
        return row

    existing.ctl = _round_1(ctl)
    existing.atl = _round_1(atl)
    existing.tsb = _round_1(tsb)
    existing.tss_today = _round_1(tss_today)
    existing.status_band = status_band
    existing.updated_at = func.now()
    return existing


def _calculate_target_day_load(
    db: Session,
    user_id: int,
    target_day: date,
    previous: DailyTrainingLoad | None,
) -> tuple[float, float, float, float, str]:
    """从最近一页账本逐日推到目标日，保证休息多天时自然衰减完整发生。"""
    last_ctl = previous.ctl if previous is not None else None
    last_atl = previous.atl if previous is not None else None
    day = previous.date + timedelta(days=1) if previous is not None else target_day
    target_values: tuple[float, float, float, float, str] | None = None

    while day <= target_day:
        tss_today = _sum_completed_cycling_tss_for_day(db, user_id, day)
        ctl = calculate_daily_ctl(last_ctl, tss_today)
        atl = calculate_daily_atl(last_atl, tss_today)
        tsb = calculate_tsb(ctl, atl)
        target_values = (ctl, atl, tsb, tss_today, classify_tsb_status(tsb))
        last_ctl = ctl
        last_atl = atl
        day += timedelta(days=1)

    # target_day 一定会跑到；兜底只为类型检查器看懂。
    if target_values is None:
        tss_today = _sum_completed_cycling_tss_for_day(db, user_id, target_day)
        ctl = calculate_daily_ctl(last_ctl, tss_today)
        atl = calculate_daily_atl(last_atl, tss_today)
        tsb = calculate_tsb(ctl, atl)
        target_values = (ctl, atl, tsb, tss_today, classify_tsb_status(tsb))
    return target_values


def update_daily_load_for_activity(db: Session, user: User, activity: Activity) -> int:
    """
    用一条刚完成的 activity 更新它所属当天的训练负荷，返回写入/更新行数。

    这个 helper 只 flush，不 commit。可以把它想象成把账本页写好但先不盖章；
    最终盖章还是撕掉，交给外层 worker 的事务决定。
    """
    if activity.started_at is None:
        logger.warning(
            "update_daily_load_for_activity skipped because started_at is NULL activity_id=%s user_id=%s",
            activity.id,
            activity.user_id,
        )
        return 0

    # 先 flush，让调用方刚设的 activity.status='completed' 和 tss 能被下面聚合查询看到。
    db.flush()
    target_day = _to_bj_date(activity.started_at)
    _acquire_user_daily_load_lock(db, user.id)
    previous = _query_latest_before(db, user.id, target_day)
    ctl, atl, tsb, tss_today, status_band = _calculate_target_day_load(
        db,
        user.id,
        target_day,
        previous,
    )
    row = _upsert_activity_day_row(
        db,
        user.id,
        target_day,
        ctl=ctl,
        atl=atl,
        tsb=tsb,
        tss_today=tss_today,
        status_band=status_band,
    )
    db.flush()

    weekly_total = (
        db.query(func.coalesce(func.sum(DailyTrainingLoad.tss_today), 0.0))
        .filter(
            DailyTrainingLoad.user_id == user.id,
            DailyTrainingLoad.date >= target_day - timedelta(days=6),
            DailyTrainingLoad.date <= target_day,
        )
        .scalar()
    )
    row.weekly_tss = int(round(float(weekly_total or 0.0)))
    row.updated_at = func.now()
    db.flush()
    return 1


def _fill_window_points(
    records: list[DailyTrainingLoad],
    start_day: date,
    end_day: date,
) -> tuple[list[TrainingLoadPoint], int]:
    """
    把窗口内缺的日期补出来。

    补点不是直接写 0：CTL/ATL 像体能和疲劳的惯性，会在没训练的日子自然下降。
    """
    rows_by_date = {row.date: row for row in records if start_day <= row.date <= end_day}
    seed = _latest_before(records, start_day)
    last_ctl = seed.ctl if seed is not None else None
    last_atl = seed.atl if seed is not None else None
    rolling_tss = deque(
        [
            row.tss_today
            for row in records
            if start_day - timedelta(days=6) <= row.date < start_day
        ],
        maxlen=7,
    )
    points: list[TrainingLoadPoint] = []
    latest_weekly_tss = 0

    day = start_day
    while day <= end_day:
        row = rows_by_date.get(day)
        if row is not None:
            point = _row_to_point(row)
            last_ctl = row.ctl
            last_atl = row.atl
            rolling_tss.append(row.tss_today)
            latest_weekly_tss = row.weekly_tss
        else:
            ctl = calculate_daily_ctl(last_ctl, 0.0)
            atl = calculate_daily_atl(last_atl, 0.0)
            tsb = calculate_tsb(ctl, atl)
            rolling_tss.append(0.0)
            latest_weekly_tss = int(round(sum(rolling_tss)))
            point = TrainingLoadPoint(
                date=day.isoformat(),
                ctl=ctl,
                atl=atl,
                tsb=tsb,
                tss_today=0.0,
                status_band=classify_tsb_status(tsb),
            )
            last_ctl = ctl
            last_atl = atl
        points.append(point)
        day += timedelta(days=1)

    return points, latest_weekly_tss


def get_training_load_response(
    db: Session,
    user_id: int,
    load_range: TrainingLoadRange,
) -> TrainingLoadResponse:
    """读取当前用户训练负荷曲线。"""
    end_day = _today_bj()
    days = _RANGE_DAYS[load_range]
    start_day = end_day - timedelta(days=days - 1)

    stats = (
        db.query(
            func.min(DailyTrainingLoad.date).label("first_date"),
            func.max(DailyTrainingLoad.date).label("last_date"),
        )
        .filter(DailyTrainingLoad.user_id == user_id)
        .first()
    )

    if stats is None or stats.first_date is None or stats.last_date is None:
        return TrainingLoadResponse(
            range=load_range,
            points=[],
            summary=_zero_summary(),
        )

    history_days = (stats.last_date - stats.first_date).days + 1
    has_history = history_days >= _MIN_COMPLETE_DAYS
    # 覆盖率门槛：历史够长但当前 range 的功率数据不足 → 不展示（防 CTL/历史趋势失真误导）
    insufficient_power_data = has_history and _range_tss_coverage(db, user_id, load_range) < _MIN_TSS_COVERAGE
    data_complete = has_history and not insufficient_power_data
    window_rows = (
        db.query(DailyTrainingLoad)
        .filter(
            DailyTrainingLoad.user_id == user_id,
            DailyTrainingLoad.date >= start_day,
            DailyTrainingLoad.date <= end_day,
        )
        .order_by(DailyTrainingLoad.date.asc())
        .all()
    )

    if not data_complete:
        actual_points = [_row_to_point(row) for row in window_rows]
        if not actual_points:
            return TrainingLoadResponse(range=load_range, points=[], summary=_zero_summary())
        latest_row = window_rows[-1]
        summary = _make_summary(
            actual_points[-1],
            latest_row.weekly_tss,
            data_complete=False,
            insufficient_power_data=insufficient_power_data,
        )
        return TrainingLoadResponse(range=load_range, points=actual_points, summary=summary)

    seed = _query_latest_before(db, user_id, start_day)
    prior_rows = (
        db.query(DailyTrainingLoad)
        .filter(
            DailyTrainingLoad.user_id == user_id,
            DailyTrainingLoad.date >= start_day - timedelta(days=6),
            DailyTrainingLoad.date < start_day,
        )
        .order_by(DailyTrainingLoad.date.asc())
        .all()
    )
    records = [row for row in [seed] if row is not None] + prior_rows + window_rows
    points, weekly_tss = _fill_window_points(records, start_day, end_day)
    summary = _make_summary(points[-1], weekly_tss, data_complete=True)
    return TrainingLoadResponse(range=load_range, points=points, summary=summary)
