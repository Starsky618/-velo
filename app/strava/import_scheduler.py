"""
Strava 历史导入调度器——"搬家调度中心"。

用户绑定 Strava 后，系统需要把历史骑行数据从 Strava 搬过来。
这个模块就是"搬家调度中心"：每 30 秒醒来一次，检查有没有要搬的箱子，
有的话搬一个，搬完记录进度，下次接着搬。

两层渐进策略：
- 第一层（列表）：先清点所有箱子的标签，用户立刻能看到"有哪些骑行"
- 第二层（详情+轨迹）：打开每个箱子，取出详细数据、匹配赛段

调度原则：
- 每次 tick 只做一个最小任务单元（第一层 = 1 次 API，第二层 = 2 次 API）
- 多用户轮转：不让一个人占满额度
- 断点续传：进度存在 strava_imports 表里，服务器重启不丢

注意事项：
- 这个函数由 rq-scheduler 每 30 秒调度一次，不在 FastAPI 请求上下文中
- 使用 SessionLocal 手动管理数据库连接（和 Worker 一样）
- 所有 Strava API 调用通过 StravaClient，限流由 client 统一管理
- StravaClient 是短命对象，每个用户创建新实例，tick 结束后释放
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.activity.models import Activity
from app.activity.worker import save_parse_result
from app.database import SessionLocal
from app.parsing.coord_normalizer import normalize
from app.parsing.strava_adapter import from_streams, StravaAdapterError
from app.strava.client import StravaClient, StravaRateLimitError
from app.strava.models import StravaImport
from app.user.models import User

logger = logging.getLogger(__name__)

# 第二层跳过条件
_MIN_DISTANCE_METERS = 5000     # 距离 < 5km 的活动跳过详情+轨迹导入
_CYCLING_TYPES = {"Ride", "VirtualRide", "EBikeRide", "Handcycle", "Velomobile"}


def run_import_tick() -> None:
    """
    调度器的心跳函数——每 30 秒被 rq-scheduler 调用一次。

    流程：
    1. 找到一个需要导入的用户（轮转选择）
    2. 根据进度决定跑第一层还是第二层
    3. 执行一个最小任务单元
    4. 更新进度
    5. 全部完成则标记 completed

    如果额度用完（StravaRateLimitError），静默退出等下一个窗口。
    """
    db = SessionLocal()
    try:
        _do_tick(db)
    except StravaRateLimitError:
        # 额度用完，正常退出，等下一个窗口
        logger.info("Strava API 额度用完，等待下一个窗口")
    except Exception:
        logger.exception("导入调度器 tick 异常")
        db.rollback()
    finally:
        db.close()


def _do_tick(db) -> None:
    """调度器核心逻辑，拆出来方便异常处理包裹。"""

    # ===== 1. 僵尸检测：超过 24 小时未更新的导入任务标记为 paused =====
    _check_stale_imports(db)

    # ===== 2. 轮转选择一个 active 的导入任务 =====
    import_task = _pick_next_task(db)
    if import_task is None:
        return  # 没有活跃的导入任务

    # ===== 3. 查找对应用户 =====
    user = db.query(User).filter_by(id=import_task.user_id).first()
    if user is None or user.strava_athlete_id is None:
        # 用户被删或已解绑 Strava，暂停导入
        logger.warning(
            "用户不存在或已解绑 Strava import_id=%d user_id=%d，标记 paused",
            import_task.id, import_task.user_id,
        )
        import_task.status = "paused"
        db.commit()
        return

    # ===== 4. 创建短命 StravaClient =====
    client = StravaClient(db, user)

    # ===== 5. 决定跑哪一层 =====
    if not _is_tier1_complete(import_task):
        _run_tier1(db, client, import_task)
    else:
        _run_tier2(db, client, import_task, user)

    # ===== 6. 更新时间戳（用于僵尸检测）=====
    import_task.updated_at = datetime.now(timezone.utc)
    db.commit()


def _check_stale_imports(db) -> None:
    """
    僵尸检测：超过 24 小时未更新的 active 导入任务标记为 paused。

    调度器自己负责检测（不扩展现有的 Activity 僵尸扫描），
    因为 importing 状态的生命周期由调度器管理。
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    stale_tasks = (
        db.query(StravaImport)
        .filter(
            StravaImport.status == "active",
            StravaImport.updated_at < cutoff,
        )
        .all()
    )

    for task in stale_tasks:
        logger.warning(
            "导入任务超时 import_id=%d user_id=%d，标记为 paused",
            task.id, task.user_id,
        )
        task.status = "paused"

    if stale_tasks:
        db.commit()


def _pick_next_task(db) -> StravaImport | None:
    """
    轮转选择下一个要处理的导入任务。

    策略：按 updated_at 升序排，选最久没更新的那个——
    这样多个用户同时导入时，每人轮一次，公平分配 API 额度。
    好比排队叫号：谁等得最久就先服务谁。
    """
    return (
        db.query(StravaImport)
        .filter(StravaImport.status == "active")
        .order_by(StravaImport.updated_at.asc())
        .first()
    )


def _is_tier1_complete(import_task: StravaImport) -> bool:
    """
    判断第一层（列表拉取）是否完成。

    两个条件满足任一即视为完成：
    - total_activities 不为 None 且 tier1_completed >= total_activities
    - total_activities 已设值（说明至少拉过一轮列表，遇到过空返回）
    """
    if import_task.total_activities is None:
        return False  # 还没拉过列表
    return import_task.tier1_completed >= import_task.total_activities


def _run_tier1(db, client: StravaClient, import_task: StravaImport) -> None:
    """
    第一层：拉活动列表，为每条活动创建 Activity(status=importing) 骨架记录。

    用户绑定后第一件看到的事就是"我的骑行列表"逐渐出现，
    虽然还没有详细数据，但至少知道"系统在搬"。
    """
    # 准备游标：首次为 None（从最新开始），后续用上次记录的时间戳
    before_ts = None
    if import_task.cursor_before is not None:
        before_ts = int(import_task.cursor_before.timestamp())

    # 调 Strava API
    activities = client.get_athlete_activities(before=before_ts, per_page=30)

    if not activities:
        # 列表返回空 → 第一层完成
        if import_task.total_activities is None:
            import_task.total_activities = import_task.tier1_completed
        logger.info(
            "第一层完成 import_id=%d total=%d",
            import_task.id, import_task.total_activities,
        )
        return

    # 逐条创建 Activity 骨架
    created_count = 0
    oldest_start_date = None

    for act in activities:
        strava_id = act.get("id")
        if strava_id is None:
            continue

        # 去重：先查有没有已导入的
        existing = (
            db.query(Activity)
            .filter_by(strava_activity_id=strava_id)
            .first()
        )
        if existing:
            continue

        # 解析 start_date
        start_date_str = act.get("start_date")
        started_at = _parse_iso_date(start_date_str)

        # 创建骨架 Activity
        activity = Activity(
            user_id=import_task.user_id,
            title=act.get("name"),
            status="importing",
            file_url=None,          # Strava 导入无文件
            distance=act.get("distance"),
            started_at=started_at,
            data_source="strava",
            strava_activity_id=strava_id,
        )

        # 用 SAVEPOINT 隔离每条 Activity 的插入：
        # 如果这条触发 IntegrityError（并发重复），只回滚这一条的 SAVEPOINT，
        # 已经 flush 成功的其他 Activity 不受影响。
        # 这和项目里赛段匹配的 SAVEPOINT 隔离是同一个模式。
        try:
            nested = db.begin_nested()  # SAVEPOINT
            db.add(activity)
            db.flush()
            created_count += 1
        except IntegrityError:
            nested.rollback()  # 只回滚这一条
            logger.info("跳过已存在的 Strava 活动 strava_id=%d", strava_id)
            continue

        # 记录最老的 start_date 作为下一次的游标
        if started_at and (oldest_start_date is None or started_at < oldest_start_date):
            oldest_start_date = started_at

    # 更新进度
    import_task.tier1_completed = (import_task.tier1_completed or 0) + created_count
    if oldest_start_date:
        import_task.cursor_before = oldest_start_date

    db.commit()

    logger.info(
        "第一层 tick import_id=%d created=%d total_so_far=%d",
        import_task.id, created_count, import_task.tier1_completed,
    )


def _run_tier2(
    db, client: StravaClient, import_task: StravaImport, user: User
) -> None:
    """
    第二层：拉详情+轨迹，写入完整数据，触发赛段匹配。

    每次只处理一条活动（2 次 API 调用），处理完更新进度。
    跳过条件：非骑行活动、距离 < 5km。
    """
    # 找下一条待处理的 importing 活动（最新的先）
    activity = (
        db.query(Activity)
        .filter_by(
            user_id=import_task.user_id,
            status="importing",
            data_source="strava",
        )
        .order_by(Activity.started_at.desc())
        .first()
    )

    if activity is None:
        # 所有 importing 活动都处理完了
        import_task.status = "completed"
        logger.info("导入全部完成 import_id=%d", import_task.id)
        return

    strava_id = activity.strava_activity_id

    # ---- 跳过条件检查 ----
    # 检查活动类型和距离（从第一层骨架数据判断）
    # 注意 truthiness 陷阱：distance=0 是合法值，用 is not None 判断
    if activity.distance is not None and activity.distance < _MIN_DISTANCE_METERS:
        logger.info(
            "跳过短距离活动 strava_id=%d distance=%.0f",
            strava_id, activity.distance,
        )
        activity.status = "completed"
        import_task.tier2_skipped = (import_task.tier2_skipped or 0) + 1
        db.commit()
        return

    # ---- 拉详情 + 轨迹（2 次 API 调用）----
    try:
        detail = client.get_activity_detail(strava_id)
    except ValueError as e:
        # 404 活动不存在、403 权限不足等
        logger.warning("拉详情失败 strava_id=%d: %s", strava_id, e)
        activity.status = "failed"
        activity.error_message = str(e)
        db.commit()
        return

    # 检查活动类型（detail 里有更准确的 type 字段）
    activity_type = detail.get("type", "")
    if activity_type not in _CYCLING_TYPES:
        logger.info("跳过非骑行活动 strava_id=%d type=%s", strava_id, activity_type)
        activity.status = "completed"
        import_task.tier2_skipped = (import_task.tier2_skipped or 0) + 1
        db.commit()
        return

    try:
        streams = client.get_activity_streams(strava_id)
    except ValueError as e:
        logger.warning("拉轨迹失败 strava_id=%d: %s", strava_id, e)
        activity.status = "failed"
        activity.error_message = str(e)
        db.commit()
        return

    # ---- 适配 + 写入 ----
    try:
        ftp = int(user.ftp) if user.ftp else None
        parse_result = from_streams(streams, detail, ftp=ftp)
        parse_result = normalize(parse_result)

        # 共享写入函数（不改 status、不 commit）
        save_parse_result(db, activity, parse_result)

        activity.status = "completed"
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Strava 数据处理失败 strava_id=%d: %s", strava_id, e)
        activity.status = "failed"
        activity.error_message = str(e)[:500]
        db.commit()
        return

    # ---- 赛段匹配（尽力而为）----
    try:
        from app.segment.auto_match import match_activity_against_segments
        match_activity_against_segments(activity.id, db)
    except Exception:
        db.rollback()
        logger.warning(
            "赛段匹配失败 activity_id=%d strava_id=%d import_id=%d",
            activity.id, strava_id, import_task.id,
        )

    # 更新进度
    import_task.tier2_completed = (import_task.tier2_completed or 0) + 1
    db.commit()

    logger.info(
        "第二层完成 strava_id=%d activity_id=%d import_id=%d",
        strava_id, activity.id, import_task.id,
    )


def _parse_iso_date(date_str: str | None) -> datetime | None:
    """解析 ISO 8601 时间字符串，与 strava_adapter.py 保持一致。"""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
