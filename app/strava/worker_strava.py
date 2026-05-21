"""
Strava webhook 异步处理 worker——"门铃响后的取件流程"。

干啥用：Strava 用户上传新活动 → webhook 打电话给 velo → api 容器接到电话扔到 RQ 队列 →
worker 容器跑这个文件里的函数 → 拉详情 + 轨迹 + 跑赛段匹配 + 触发 6 套 hook → 用户秒级看到。

操作注意事项：
- 这个文件被 RQ worker 通过字符串路径动态 importlib 调用（worker.py 不需要预先 import）
- 主流程严格对照 `app/strava/import_scheduler.py:_run_tier2`（同源 pattern 不复制粘贴逻辑）
- save_parse_result + hooks 严格对照 `app/activity/worker.py`（GPX 路径同源）

输入输出数据流：
- 输入：webhook 推送的 user_id + strava_activity_id（来自 service_sync.handle_webhook_event）
- 处理：拉 Strava API → 写 DB → 触发 hooks
- 输出：activity.status='completed' + 6 套 hook 副作用（city / heatmap / progress / persona）

拆 create / update 两条独立路径：
- create：抢 importing 锁 → 拉详情 → save → hooks
- update：清派生数据 → 重置 status='processing' → 走 create 主流程
  （不复用 _try_lock_importing 因状态已 processing / spec 审 Critical 修正）
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import update as sql_update
from sqlalchemy.sql import func

from app.database import SessionLocal
from app.activity.models import Activity, Trackpoint
from app.user.models import User
from app.strava.client import StravaClient
from app.strava.import_scheduler import _is_cycling  # Fix 3 抽好的 helper / 同源不复制粘贴
from app.parsing.strava_adapter import from_streams
from app.parsing.coord_normalizer import normalize
from app.activity.worker import save_parse_result, _set_activity_city
from app.segment.models import SegmentEffort
from app.notification.models import Notification

logger = logging.getLogger(__name__)


def process_strava_webhook_create(user_id: int, strava_activity_id: int) -> None:
    """
    webhook create 事件入口——Strava 通知"有新活动"时调用。

    流程：
    1. 原子抢锁 importing → processing（防 scheduler tier2 并发处理同一条）
    2. 抢不到 = 已被处理 / 静默退出
    3. 抢到 = 跑主流程拉详情 + 轨迹 + hooks
    """
    db = SessionLocal()
    try:
        # 原子抢锁：状态从 importing → processing
        # 用 UPDATE WHERE status='importing' 保证并发只有一个 worker 成功
        result = db.execute(
            sql_update(Activity)
            .where(
                Activity.strava_activity_id == strava_activity_id,
                Activity.status == "importing",
            )
            .values(status="processing", updated_at=func.now())
            .returning(Activity.id)
        )
        row = result.fetchone()
        db.commit()
        if row is None:
            logger.info(
                "webhook create 抢锁失败（已被处理）strava_id=%d",
                strava_activity_id,
            )
            return
        _process_strava_main(db, user_id, strava_activity_id)
    except Exception:
        logger.exception(
            "webhook create 异常 strava_id=%d user_id=%d",
            strava_activity_id, user_id,
        )
        db.rollback()
    finally:
        db.close()


def process_strava_webhook_update(user_id: int, strava_activity_id: int) -> None:
    """
    webhook update 事件入口——Strava 通知"活动被改了"时调用（改标题 / 改类型 / 改可见性等）。

    分支：
    - activity 不存在 → 当 create 处理（兜底 / 防漏接 create）
    - importing / processing → create worker 已在处理 / 跳过（避免并发）
    - completed → 清派生数据 + 重置 status → 走主流程
    - 其他状态（failed / paused）→ 跳过不动
    """
    db = SessionLocal()
    try:
        activity = db.query(Activity).filter_by(
            strava_activity_id=strava_activity_id
        ).first()

        # 路径 A：activity 不存在 → 当 create 处理
        if activity is None:
            user = db.query(User).filter_by(id=user_id).first()
            if user and user.strava_athlete_id is not None:
                from app.strava.service_sync import _create_importing_activity
                _create_importing_activity(db, user, strava_activity_id)
                # 重入抢锁主流程
                process_strava_webhook_create(user_id, strava_activity_id)
            return

        # 路径 B：activity 已在处理中 → 跳过（5min cleanup 兜底）
        if activity.status in ("importing", "processing"):
            logger.info(
                "update 跳过：activity 已在处理中 strava_id=%d status=%s",
                strava_activity_id, activity.status,
            )
            return

        # 路径 C：非 completed 状态（failed / paused）跳过
        if activity.status != "completed":
            logger.info(
                "update 跳过：activity 状态 %s 不处理 strava_id=%d",
                activity.status, strava_activity_id,
            )
            return

        # 路径 D：completed 路径 → 清派生 + 重置 → 主流程
        _wipe_activity_derived_data(db, activity)
        activity.status = "processing"
        activity.updated_at = datetime.now(timezone.utc)
        db.commit()
        _process_strava_main(db, user_id, strava_activity_id)
    except Exception:
        logger.exception(
            "webhook update 异常 strava_id=%d user_id=%d",
            strava_activity_id, user_id,
        )
        db.rollback()
    finally:
        db.close()


def _process_strava_main(db, user_id: int, strava_activity_id: int) -> None:
    """
    主流程：拉详情 + 守卫 + 拉轨迹 + save + 6 套 hook。

    严格对照 import_scheduler.py:_run_tier2 同源 pattern（同样的 SAVEPOINT 隔离 + hook 顺序）。
    """
    activity = db.query(Activity).filter_by(
        strava_activity_id=strava_activity_id
    ).first()
    user = db.query(User).filter_by(id=user_id).first()
    if activity is None or user is None or user.strava_athlete_id is None:
        logger.warning(
            "主流程 abort：activity 或 user 不存在 strava_id=%d user_id=%d",
            strava_activity_id, user_id,
        )
        return

    client = StravaClient(db, user)

    # ---- 拉详情 ----
    # 异常分流（Codex 异源审 Critical / 防 429 限流 + httpx 网络抖动永久失败）：
    # - StravaRateLimitError / httpx.HTTPError / httpx.TransportError → 让 RQ 重试（不标 failed）
    # - 其他业务异常（ValueError 404 / 403 等）→ 标 failed + 写 error_message
    from app.strava.client import StravaRateLimitError
    import httpx
    try:
        detail = client.get_activity_detail(strava_activity_id)
    except (StravaRateLimitError, httpx.HTTPError, httpx.TransportError) as e:
        # 可恢复异常 / 不改 status / 让 RQ retry（活动留在 processing / 5min cleanup 兜底）
        logger.warning(
            "拉详情可恢复异常 strava_id=%d type=%s msg=%s",
            strava_activity_id, type(e).__name__, e,
        )
        raise  # 让 RQ 框架 retry
    except Exception as e:
        # 业务级异常 / 标 failed（用 logger.exception 留完整 traceback / 防 memory feedback_logger_warning_error_narrative_trap）
        logger.exception(
            "拉详情业务异常 strava_id=%d type=%s",
            strava_activity_id, type(e).__name__,
        )
        activity.status = "failed"
        activity.error_message = f"detail:{type(e).__name__}:{str(e)[:180]}"
        db.commit()
        return

    # ---- 非骑行守卫：保留骨架 + 回填真实 activity_type ----
    # Fix 5/7 数据层 11 处过滤会拦住列表/统计/勋章不显示
    if not _is_cycling(detail):
        strava_type = detail.get("type", "")
        _type_lower = strava_type.lower()
        if "run" in _type_lower:
            activity.activity_type = "running"
        elif "hike" in _type_lower or "walk" in _type_lower:
            activity.activity_type = "hiking"
        else:
            activity.activity_type = "other"
        activity.status = "completed"
        db.commit()
        logger.info(
            "非骑行保留骨架 strava_id=%d type=%s mapped=%s",
            strava_activity_id, strava_type, activity.activity_type,
        )
        return

    # v5+ 修订（Tim 拍）：所有骑行走完整流程拉详情+轨迹+赛段。
    # 取消 _MIN_DISTANCE_METERS 距离阈值——velo 1 用户量级 Strava 配额充裕。

    # ---- 拉轨迹 ----
    # 同详情异常分流（可恢复 → RQ retry / 业务级 → failed）
    try:
        streams = client.get_activity_streams(strava_activity_id)
    except (StravaRateLimitError, httpx.HTTPError, httpx.TransportError) as e:
        logger.warning(
            "拉轨迹可恢复异常 strava_id=%d type=%s msg=%s",
            strava_activity_id, type(e).__name__, e,
        )
        raise  # RQ retry
    except Exception as e:
        logger.exception(
            "拉轨迹业务异常 strava_id=%d type=%s",
            strava_activity_id, type(e).__name__,
        )
        activity.status = "failed"
        activity.error_message = f"streams:{type(e).__name__}:{str(e)[:180]}"
        db.commit()
        return

    # ---- 解析 + 写 DB ----
    # logger.exception 留 traceback（防错误措辞盖根因）
    try:
        ftp = int(user.ftp) if user.ftp else None
        parse_result = normalize(from_streams(streams, detail, ftp=ftp))
        save_parse_result(db, activity, parse_result, user=user)
        activity.status = "completed"
    except Exception as e:
        logger.exception(
            "解析/写入业务异常 strava_id=%d type=%s",
            strava_activity_id, type(e).__name__,
        )
        db.rollback()
        activity.status = "failed"
        activity.error_message = f"parse_save:{type(e).__name__}:{str(e)[:180]}"
        db.commit()
        return

    # ---- dedupe（GPX vs Strava 同骑行查重 / SAVEPOINT 隔离）----
    # 严格对照 import_scheduler.py:438-446
    is_duplicate = False
    try:
        from app.activity.dedupe_service import find_and_mark_duplicate
        nested_dup = db.begin_nested()
        try:
            marked_id = find_and_mark_duplicate(db, activity)
            is_duplicate = marked_id is not None
            db.flush()
            nested_dup.commit()
        except Exception:
            nested_dup.rollback()
    except Exception:
        pass

    # ---- 6 套 hook（is_duplicate=True 跳过 / 与 GPX worker 同 pattern）----
    if not is_duplicate:
        _strava_post_parse_hooks(db, activity)

    db.commit()

    # ---- 赛段匹配（commit 之后 / auto_match 内部自管事务）----
    # 严格对照 import_scheduler.py:461-470
    if not is_duplicate:
        try:
            from app.segment.auto_match import match_activity_against_segments
            match_activity_against_segments(activity.id, db)
        except Exception:
            logger.exception(
                "赛段匹配失败 activity_id=%d strava_id=%d",
                activity.id, strava_activity_id,
            )


def _strava_post_parse_hooks(db, activity) -> None:
    """
    完整复制 GPX worker (app/activity/worker.py:313-460) 6 套 hook + 每个 SAVEPOINT。

    顺序严格对照 GPX worker（5 段 / 任一失败不阻断 status='completed'）：
    1. detect_5min_power_progress（5min 功率进步通知）
    2. invalidate caches（heatmap + power_curve Redis 缓存）
    3. _set_activity_city（activity.city / 起点城市）
    4. user.city 推断（仅 user.city 为 None 时）
    5. persona engine NPC（activity_uploaded + consecutive_high_detected 双路）
    """
    # 1. detect_5min_power_progress
    try:
        from app.notification.progress_detector import detect_5min_power_progress
        nested = db.begin_nested()
        try:
            detect_5min_power_progress(db, activity.user_id, activity.id)
            db.flush()
            nested.commit()
        except Exception:
            nested.rollback()
    except Exception:
        pass

    # 2. invalidate Redis caches（spec 草稿写的 import 路径错 / 这里修正）
    try:
        from app.user.service_stats import invalidate_power_curve_cache
        from app.user.service_social import invalidate_heatmap_cache
        invalidate_power_curve_cache(activity.user_id)
        invalidate_heatmap_cache(activity.user_id)
    except Exception:
        pass

    # 3. activity.city（起点城市 / SAVEPOINT 隔离）
    try:
        nested = db.begin_nested()
        try:
            _set_activity_city(activity, activity.simplified_track)
            db.flush()
            nested.commit()
        except Exception:
            nested.rollback()
    except Exception:
        pass

    # 4. user.city 推断（GPX worker.py:350-390 完整对照）
    try:
        from app.common.geo import infer_city_from_coords
        nested_user_city = db.begin_nested()
        try:
            user = (
                db.query(User)
                .filter(User.id == activity.user_id)
                .with_for_update()
                .populate_existing()
                .first()
            )
            if user is not None and user.city is None and activity.simplified_track:
                track = activity.simplified_track
                if len(track) > 0:
                    first_pt = track[0]
                    lat = first_pt.get("lat")
                    lon = first_pt.get("lon")
                    if lat is not None and lon is not None:
                        user.city = infer_city_from_coords(lat, lon)
            db.flush()
            nested_user_city.commit()
        except Exception:
            nested_user_city.rollback()
    except Exception:
        pass

    # 5. persona NPC（手工构造 PersonaEvent / 不是 .from_activity_upload）
    # 严格对照 GPX worker.py:402-470：含 activity_uploaded + consecutive_high_detected 双路
    try:
        from app.agent.persona import service as persona_service
        from app.agent.persona.trigger_router import PersonaEvent
        from app.activity.worker import _query_weekly_count, _detect_pr, _query_total_distance

        nested_persona = db.begin_nested()
        try:
            db.flush()  # 让本 activity 进 session 可见 / 影响 weekly_count
            weekly_count = _query_weekly_count(activity.user_id, db)
            is_pr = _detect_pr(activity, activity.user_id, db)
            total_distance_m = _query_total_distance(activity.user_id, db)

            upload_event = PersonaEvent(
                type="activity_uploaded",
                activity_data={
                    "id": activity.id,
                    "distance": activity.distance,
                    "elevation_gain": activity.elevation_gain,
                    "duration": activity.duration,
                    "moving_time": activity.moving_time,
                    "started_at": activity.started_at,
                    # activity.avg_speed 已是 km/h（save_parse_result 写入时已乘 3.6 转换，见 worker.py:518）
                    # 严禁再乘 3.6 / 否则 NPC 路由会错走 high_speed extreme 分支
                    "avg_speed_kmh": activity.avg_speed,
                    "avg_power": activity.avg_power,
                    "normalized_power": activity.normalized_power,
                    "is_pr": is_pr,
                    "is_rain": False,
                },
                user_data={
                    "user_id": activity.user_id,
                    "total_distance_m": total_distance_m,
                    "weekly_count": weekly_count,
                    "last_activity_days": 0,
                },
                timestamp=datetime.now(timezone.utc),
            )
            persona_service.generate_persona_output(upload_event, db)

            if weekly_count >= 5:
                ch_event = PersonaEvent(
                    type="consecutive_high_detected",
                    user_data={
                        "user_id": activity.user_id,
                        "weekly_count": weekly_count,
                    },
                    timestamp=datetime.now(timezone.utc),
                )
                persona_service.generate_persona_output(ch_event, db)

            db.flush()
            nested_persona.commit()
        except Exception:
            nested_persona.rollback()
    except Exception:
        pass

    # 6. FTP Breakthrough 检测（Sprint 9 task-8 / 与 GPX worker.py 步骤 10.8 同源）
    #    用户骑出超过预估 ftp 时写 pending event / settings 页 onShow 弹窗。
    #    SAVEPOINT 隔离 / 不传染 activity.status='completed'。
    try:
        from app.activity.breakthrough_detector import detect_breakthrough

        nested_bt = db.begin_nested()
        try:
            # 重新拉 user（hook 入参没传 / 与 user.city hook 同 pattern）
            user = db.query(User).filter_by(id=activity.user_id).first()
            if user is not None:
                db.flush()  # 让 estimator 查 status='completed' 时看到本条
                detect_breakthrough(db, user, activity)
            nested_bt.commit()
        except Exception:
            nested_bt.rollback()
    except Exception:
        pass


def _wipe_activity_derived_data(db, activity) -> None:
    """
    update 路径清派生数据（防 save_parse_result 重复插 trackpoints / segment_efforts 残留）。

    清理：trackpoints / segment_efforts / notifications + activity 派生字段
    保留：user.city（用户级数据）/ persona_outputs（历史台账）/ Redis cache（hook 会重 invalidate）
    """
    db.query(Trackpoint).filter_by(activity_id=activity.id).delete(synchronize_session=False)
    db.query(SegmentEffort).filter_by(activity_id=activity.id).delete(synchronize_session=False)
    db.query(Notification).filter_by(activity_id=activity.id).delete(synchronize_session=False)
    activity.simplified_track = None
    activity.splits = None
    activity.power_zones = None
    db.flush()
