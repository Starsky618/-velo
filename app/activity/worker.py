"""
异步解析 Worker 的任务函数——"快递分拣工人的操作手册"。

当用户上传 GPX 文件后，API（Task 3.5）会把一个"解析任务"扔进 Redis 队列。
rq Worker（根目录的 worker.py）从队列中取出任务，调用这里的 parse_activity() 执行。

完整流程（v2 翻译层改造后）：
1. 从数据库取出 Activity 记录和用户信息
2. 从文件存储下载文件
3. 调用翻译层解析器（GPXParser/FITParser）→ 得到 ParseResult
4. 坐标归一化（GCJ-02 → WGS84，大多数直接通过）
5. 把统计摘要、简化轨迹、功率区间写回 Activity 表
6. 批量插入轨迹点（每 500 条一批，含新增的 speed/distance 列）
7. 触发赛段自动匹配

好比快递分拣中心的拆包流程：
拆包（下载文件）→ 送进国际翻译中心（parsing/）→ 海关纠偏（coord_normalizer）
→ 写入档案 → 标记完成。

注意事项：
- 这个函数由 rq Worker 在独立进程中执行，不在 FastAPI 请求上下文中
- 使用 SessionLocal 手动管理数据库连接（不经过 get_db 依赖注入）
- 无论成功失败都必须 close db，避免连接泄漏
- Segment 匹配（步骤 11）在 Task 4 中实现，当前留空跳过
"""

import logging

from sqlalchemy import update, func

from app.activity.models import Activity, Trackpoint
from app.database import SessionLocal
from app.parsing.coord_normalizer import normalize
from app.parsing.fit_parser import FITParser, FITParseError
from app.parsing.gpx_parser import GPXParser, GPXParseError
from app.storage.local import LocalStorage
from app.user.models import User

logger = logging.getLogger(__name__)

# 存储后端（与 service.py 共用同一类型，但 Worker 进程独立，各自创建实例）
_storage = LocalStorage()

# 批量插入轨迹点的批次大小
_BATCH_SIZE = 500

# 轨迹点数量硬上限（与 service.py 的 _MAX_TRACKPOINTS 一致）
# 这是格式无关的安全网——不管从 GPX/FIT/Strava 哪种来源解析出来，
# 超过此上限都拒绝。第一层（上传时）按格式做轻量预检，这里是第二层兜底。
_MAX_TRACKPOINTS = 50_000


def calculate_intensity_metrics(
    np: float | None,
    ftp: int | None,
    duration_seconds: int | None,
) -> tuple[float | None, float | None]:
    """
    算 IF（强度系数）+ TSS（训练分数）。

    精度规则单一真相源在此函数（models.py 注释 + 迁移 comment 是简述版本）：
    - IF round 3 位小数
    - TSS round 1 位小数

    入参：
      np: 标准化功率（W）/ GPX 路径无功率为 None
      ftp: 用户当前 ftp（W）/ 用户没填为 None
      duration_seconds: 活动时长（秒）/ 防除零必须 > 0

    返：
      (if, tss) 或 (None, None)

    任一缺失 / 0 值 → 返 (None, None) / 前端整块隐藏（按永久规则不显示 -）
    """
    if np is None or not ftp or not duration_seconds:
        return (None, None)
    if_val = round(np / ftp, 3)
    tss = round((duration_seconds * np * if_val) / (ftp * 3600) * 100, 1)
    return (if_val, tss)


def _set_activity_city(activity, simplified_track) -> None:
    """从轨迹起点经纬度推断 activity.city（Sprint 6 task-3）。

    干啥：worker 解析完成时把活动起点落在哪个城市写回 activity.city，
    让"我的"页"城市征服墙"能自动聚合用户骑过的城市。

    语义（红线 / 与 PRD § 3.3 异常情况对齐）：
        - simplified_track 为空 / 起点 lat lon 缺失 → **不写值**（DB 保持 NULL）
        - 坐标在 6 城内 → 写 6 城之一（infer_city_from_coords 返）
        - 坐标在中国但不在 6 城 → 写 'unknown'（infer_city_from_coords 返 'unknown'）
        - 异常 → **不写值**（容错：worker 不能因 city 推断失败炸活动创建）

    NULL vs 'unknown' 语义区分（不可混淆 / city-medals 业务层依赖）：
        - NULL    = "从未推断过"（旧数据 / 空 track / 坐标缺失 / 异常）
        - 'unknown' = "推断过但不在 6 城"（用户骑老家小县城）

    设计为 helper：让 GPX/FIT（worker.py）和 Strava（import_scheduler.py）
    两条路径调同一个 helper，未来扩 7-N 城时只改 helper 不改三处接入点。

    参数：
        activity: Activity ORM 对象（直接修改 .city 字段）
        simplified_track: 简化轨迹 list[{lat, lon, ele}] 或 None
    """
    try:
        if not simplified_track:
            return  # 空轨迹 → DB 保持 NULL
        first_pt = simplified_track[0]
        lat = first_pt.get("lat")
        lon = first_pt.get("lon")
        # truthiness 陷阱 #1：0.0 是合法纬度（赤道）/ 必须 `is None` 不能 truthy
        if lat is None or lon is None:
            return  # 起点坐标缺失 → DB 保持 NULL
        from app.common.geo import infer_city_from_coords

        activity.city = infer_city_from_coords(lat, lon)  # 6 城之一 或 'unknown'
    except Exception:
        # 容错：worker 不能因 city 推断失败而炸 activity 创建 / 保持 NULL
        return




def parse_activity(activity_id: int) -> None:
    """
    解析一条骑行活动的 GPX 文件，把结果写入数据库。

    这是 rq 队列的任务入口函数。
    由 service.py 的 upload_gpx() 通过 queue.enqueue() 调用。

    参数：
        activity_id: 要解析的 Activity 记录 ID
    """
    db = SessionLocal()
    try:
        _do_parse(db, activity_id)
    except (GPXParseError, FITParseError) as e:
        # GPX 格式问题（用户上传了损坏的文件等）
        _mark_failed(db, activity_id, str(e))
    except Exception:
        # 未预期的系统错误
        _mark_failed(db, activity_id, "系统内部错误")
    finally:
        db.close()


def _do_parse(db, activity_id: int) -> None:
    """
    解析的核心流程，拆成独立函数方便异常处理包裹。
    """
    # ===== 步骤 1：原子抢锁 =====
    # 一条 SQL 同时完成"检查状态是 pending + 改为 processing"，
    # 由 PostgreSQL 保证原子性。如果另一个 Worker 已经抢到了这条任务，
    # WHERE status='pending' 不匹配 → 返回空 → 当前 Worker 直接退出。
    # 这就像自动售货机的"投币锁"：第一个硬币锁住商品，第二个硬币退回。
    result = db.execute(
        update(Activity)
        .where(Activity.id == activity_id, Activity.status == "pending")
        .values(status="processing", updated_at=func.now())
        .returning(Activity.id)
    )
    locked_row = result.fetchone()
    db.commit()  # 提交状态变更，让其他进程能看到

    if locked_row is None:
        # 任务已被其他 Worker 抢走，或状态不是 pending（已处理/已失败）
        return

    # ===== 步骤 2：取完整记录 =====
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        return

    # ===== 步骤 2.5：🌱 运动类型分流（种子 3）=====
    # 本期只支持 cycling。未来加运动类型时，在这里加 elif 分支：
    #   elif activity.activity_type == 'running':
    #       _parse_running(db, activity)
    #       return
    # 结构设计理由：
    #   - 分流点在"锁后、文件下载前"：非 cycling 活动连文件下载 I/O 都省了
    #   - 用不等式判断（!= "cycling"）而不是枚举所有不支持类型：
    #     对 NULL 也返回 True（NULL 和任何值不等），安全兜底
    #   - 每种运动的解析未来分到独立函数（_parse_cycling / _parse_running 等），
    #     彼此互不干扰。本期只有一个分支，不抽出 _parse_cycling（纯粹改名不增价值）
    if activity.activity_type != "cycling":
        activity.status = "failed"
        activity.error_message = f"暂不支持的运动类型: {activity.activity_type}"
        db.commit()
        logger.warning(
            "活动 %d 运动类型 %s 暂不支持，置 failed",
            activity_id, activity.activity_type,
        )
        return

    user = db.query(User).filter_by(id=activity.user_id).first()
    if user is None:
        raise ValueError(f"User {activity.user_id} 不存在")

    # ===== 步骤 3：下载文件 =====
    file_content = _storage.download(activity.file_url)

    # ===== 步骤 4：解析 + 坐标归一化 =====
    # 根据文件扩展名选择解析器（GPX 用 XML 翻译官，FIT 用二进制翻译官）
    # normalize 确保坐标全部是 WGS84（码表数据直接通过，中国 App 数据做纠偏）
    weight = float(user.weight) if user.weight else 70.0
    ftp = int(user.ftp) if user.ftp else None
    file_ext = _get_file_extension(activity.file_url)
    if file_ext == ".fit":
        parser = FITParser()
    else:
        parser = GPXParser()

    result = parser.parse(
        file_content,
        weight=weight,
        ftp=ftp,
        file_hash=activity.file_hash,
    )
    result = normalize(result)

    # ===== 步骤 5.5：轨迹点数量安全网 =====
    # 第二层防御：GPX 解析器内部已有上限检查，这里是兜底
    trackpoints = result.trackpoints
    if len(trackpoints) > _MAX_TRACKPOINTS:
        raise GPXParseError(
            f"轨迹点过多（{len(trackpoints)} 个，上限 {_MAX_TRACKPOINTS}），请裁剪后重新上传"
        )

    # ===== 步骤 6-9：统计量 + 轨迹点写入（共享函数）=====
    save_parse_result(db, activity, result, user=user)

    # ===== 步骤 10：标记完成 =====
    activity.status = "completed"

    # ===== 步骤 10.4：GPX 语义 dedupe（Sprint 5 task-2 / Day 1）=====
    # Why 在这一步：要在 detector / city hook / segment 匹配之前跑
    #   - detector 跑在 duplicate 上 = 重复发 PR/KOM 通知（用户体验差）
    #   - segment 匹配跑在 duplicate 上 = segment_efforts 重复行
    #   - cache invalidate 跑在 duplicate 上无副作用（重新计算时 WHERE duplicate_of IS NULL 自动过滤）
    # SAVEPOINT 隔离（CLAUDE.md 陷阱 #13 / 与 city hook 同 pattern）：
    #   dedupe 内部 db.flush() 失败不阻断外层 activity 已 set 的 status='completed'
    is_duplicate = False
    try:
        from app.activity.dedupe_service import find_and_mark_duplicate

        nested_dedup = db.begin_nested()
        try:
            marked_id = find_and_mark_duplicate(db, activity)
            db.flush()  # SAVEPOINT 内 flush 让 duplicate_of 字段写到 DB
            nested_dedup.commit()
            # 缓存到本地变量供后续 step 守卫
            # marked_id 可能是 new 也可能是 existing；这里只关心"new 是否被标"
            is_duplicate = activity.duplicate_of is not None
        except Exception:
            nested_dedup.rollback()  # SAVEPOINT 回退 / 不影响外层 activity.status
    except Exception:
        # 最外层兜底：begin_nested / 模块 import 极端失败
        pass

    # ===== 步骤 10.5：5min 功率进步检测（v5 task-2.A.1 / spec §3.4）=====
    # hook 落在 status='completed' 赋值后、db.commit 前——这样 detector 写的
    # notification 与 activity.status 在同一 transaction 提交（一致性 OK）。
    # detector 内部用 SAVEPOINT 隔离，写失败不会回退 activity.status。
    # try/except 兜底：detector 任何异常都不影响 activity 已经 completed 的事实。
    # Sprint 5 task-2 守卫：activity 是 duplicate 时跳过（避免重复发 PR/KOM 通知）。
    if not is_duplicate:
        try:
            from app.notification.progress_detector import detect_5min_power_progress
            from app.user.service import invalidate_power_curve_cache

            detect_5min_power_progress(db, activity.user_id, activity.id)
            # invalidate_power_curve_cache 是 task-2.A.1 stub / task-2.C.2 已替换为真实现
            # 上传新 activity 后清缓存让下次查 power_curve 走真实计算
            invalidate_power_curve_cache(activity.user_id)
        except Exception:
            # 进步检测失败静默跳过，不影响 activity 已经 completed 的事实
            # 失败场景：power_curve / heatmap 算法异常 / DB 临时网络抖动 / Redis 不可用
            pass

    # ===== 步骤 10.55：写 activity.city 起点城市（Sprint 6 task-3）=====
    # 与下方 user.city hook 是独立两件事——
    #   - activity.city：每条活动的起点城市（每次都推断 / 多次骑入不同城市都正确分别记录）
    #   - user.city：用户的主城（只在 user.city 为 NULL 时首次推断 / 之后用户改 settings 自己改）
    # 两者用独立 SAVEPOINT，互不污染。activity.city 写失败不影响 user.city 流程，反之亦然。
    # Sprint 5 task-2 dedupe 守卫：duplicate 跳过（避免给 duplicate 重复写）。
    if not is_duplicate:
        try:
            nested_act_city = db.begin_nested()
            try:
                _set_activity_city(activity, activity.simplified_track)
                db.flush()  # SAVEPOINT 内 flush 让 city 字段写到 DB
                nested_act_city.commit()
            except Exception:
                nested_act_city.rollback()  # SAVEPOINT 回退 / 不影响外层 activity.status
        except Exception:
            # 最外层兜底：begin_nested 失败 / 极端场景
            pass

    # ===== 步骤 10.6：首次上传自动推断主城市（v5 task-2.C.2 / spec §3.5）=====
    # 用户没填 city 时，从首条骑行起点反推主城市（北京/上海/...等 6 主城 / 'unknown'）。
    # 用 SELECT FOR UPDATE 行锁防并发：多 activity 同时进 worker 时只有一次 city 推断 commit。
    #
    # ⚠ SAVEPOINT 隔离（CLAUDE.md 陷阱 #13 / 与 task-2.A.1 detector 同一 pattern）：
    # city hook 内任何 DB 异常（如 SELECT FOR UPDATE 死锁 / 事务 rollback-only）会让外层
    # session 进入 invalid 状态，导致 worker 后续 db.commit() 一起失败 → activity 卡 processing。
    # 用 begin_nested() 让失败只回退 SAVEPOINT，外层 activity.status / notification 不受影响。
    # Sprint 5 task-2 守卫：duplicate 跳过（city hook 设计上幂等无副作用，但跳过更省事）。
    if not is_duplicate:
        try:
            # User 已在文件顶部 import（line 37）—— 这里不能再 import：
            # Python 函数作用域规则下，函数内任何位置 `from ... import User`
            # 会让整个函数内 User 视为局部变量，导致前面 step 2.5 之后第 124 行
            # `db.query(User)` 触发 UnboundLocalError（实测踩过 / 2026-04-30）
            from app.common.geo import infer_city_from_coords

            nested_city = db.begin_nested()
            try:
                user = (
                    db.query(User)
                    .filter(User.id == activity.user_id)
                    .with_for_update()  # 行锁，并发请求串行（spec R3-Minor 修）
                    .populate_existing()  # CLAUDE.md 陷阱 #12：刷新 identity map 避免读到 stale city
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
                db.flush()  # 强制把 user.city 改动 flush 到 DB（SAVEPOINT 内）
                nested_city.commit()
            except Exception:
                nested_city.rollback()  # SAVEPOINT 回退 / 不影响外层 activity.status
        except Exception:
            # 最外层兜底：begin_nested 失败 / 模块 import 失败等极端场景
            pass

    # ===== 步骤 10.8：FTP Breakthrough 自动检测（Sprint 9 task-8）=====
    # 用户骑出超过预估 ftp 时写 pending 事件 / 让 settings 页 onShow 弹窗提示更新 ftp。
    # SAVEPOINT 隔离（与 task-2.A.1 detector 同 pattern）：
    #   detect_breakthrough 内任何异常都被吞 / 但兜底再加一层 SAVEPOINT 防 session invalid。
    # Sprint 5 task-2 守卫：duplicate 跳过（避免给重复活动重复发 breakthrough 弹窗）。
    # 函数内 import 避免模块顶部循环依赖（breakthrough_detector → activity.models 已 import）。
    if not is_duplicate:
        try:
            from app.activity.breakthrough_detector import detect_breakthrough

            nested_bt = db.begin_nested()
            try:
                # 此时 activity.status='completed' 已 set；先 flush 让 estimator
                # 查 status='completed' 时能看到本条活动（autoflush=False）。
                db.flush()
                detect_breakthrough(db, user, activity)
                nested_bt.commit()
            except Exception:
                nested_bt.rollback()  # 不影响外层 activity.status='completed'
        except Exception:
            # 最外层兜底：begin_nested 失败 / 模块 import 极端失败
            logger.exception(
                "breakthrough hook outer SAVEPOINT failed activity_id=%s",
                activity.id,
            )

    # ===== 步骤 10.9：增量更新每日训练负荷（Sprint 10 task-6）=====
    # 这一步像给训练日历补当天账本：activity 已经 completed，但还没 commit，
    # 所以 daily_training_load 和 activity.status 会在同一个外层事务里一起落库。
    # SAVEPOINT 只保护这个 hook 自己，避免训练负荷写入失败把主活动卡在 processing。
    if not is_duplicate:
        try:
            from app.training.service import update_daily_load_for_activity

            nested_dtl = db.begin_nested()
            try:
                update_daily_load_for_activity(db, user, activity)
                nested_dtl.commit()
            except Exception:
                nested_dtl.rollback()
        except Exception:
            logger.exception(
                "update_daily_load hook outer SAVEPOINT failed activity_id=%s",
                activity.id,
            )

    db.commit()

    # 热图缓存必须在 activity 真正提交后失效。若在 commit 前删除，并发个人页请求
    # 会从旧 DB 重建缓存，导致新骑行仍要等 1h；提交后再删可关闭这个 race。
    if not is_duplicate:
        try:
            from app.user.service_social import invalidate_heatmap_cache
            invalidate_heatmap_cache(activity.user_id)
        except Exception:
            logger.exception("heatmap cache invalidation failed activity_id=%s", activity.id)

    # ===== 步骤 11：触发 Segment 匹配 =====
    # 活动已标记 completed 并 commit，现在触发赛段自动匹配。
    # 匹配是"尽力而为"：失败不影响活动状态（status 已经是 completed）。
    # 单独 try/except 隔离，防止匹配异常被上层 _mark_failed 捕获而误改活动状态。
    # Sprint 5 task-2 守卫：duplicate 跳过（避免 segment_efforts 重复行）。
    if not is_duplicate:
        try:
            from app.segment.auto_match import match_activity_against_segments
            match_activity_against_segments(activity_id, db)
        except Exception:
            # 赛段匹配失败静默跳过，活动状态不受影响
            db.rollback()


def save_parse_result(db, activity, result, user) -> None:
    """
    文件上传和 Strava 导入共用的 DB 写入逻辑——"档案管理员"。

    从 ParseResult 中读取数据，写入 Activity 表的统计字段和 Trackpoint 表。
    好比收到一份翻译好的"标准文件袋"（ParseResult），把里面的内容分别归档到
    "成绩单"（Activity 统计字段）和"GPS 足迹簿"（Trackpoint 表）。

    职责边界（铁律）：
    - 写 Activity 的统计字段（distance/speed/power 等）
    - 写 Activity 的 simplified_track/power_zones/splits
    - 批量插入 Trackpoint 记录（每 500 条一批）
    - 不改 status（由 caller 控制）
    - 不调 db.commit()（由 caller 控制事务边界）
    - 不触发赛段匹配（由 caller 在 commit 后单独触发）

    task-2 (sprint9): 加 user 参数 / 写 activity.snapshot_ftp + 算 IF/TSS。
        把"当时用户的 ftp"锁到这条活动上（snapshot 语义）——后续用户改 ftp 也
        不会回头改这条历史活动的 IF/TSS，保证训练数据的时间一致性。

    参数：
        db: SQLAlchemy Session，由调用方管理生命周期
        activity: Activity ORM 对象，统计字段会被直接修改
        result: ParseResult，翻译层输出的标准数据包
        user: User ORM 对象 / 取 user.ftp 锁到 activity.snapshot_ftp
    """
    # ---- 统计量写入 activity ----
    # 速度：翻译层内部用 m/s，DB 存 km/h（兼容旧数据），写入时 ×3.6
    # 其他字段直接写入，单位不变
    summary = result.summary
    activity.title = activity.title or result.metadata.title
    activity.distance = summary.distance
    activity.duration = summary.duration
    activity.moving_time = summary.moving_time
    activity.elevation_gain = summary.elevation_gain
    activity.avg_speed = round(summary.avg_speed * 3.6, 1) if summary.avg_speed else None
    activity.max_speed = round(summary.max_speed * 3.6, 1) if summary.max_speed else None
    activity.avg_power = summary.avg_power
    activity.max_power = summary.max_power
    activity.avg_hr = summary.avg_hr
    activity.max_hr = summary.max_hr
    activity.avg_cadence = summary.avg_cadence
    activity.max_cadence = summary.max_cadence
    # task-2 (sprint9): 锁定当时 ftp 到这条活动 / 算 IF/TSS
    # snapshot 语义：用户改 ftp 也不回头改历史活动的 IF/TSS（训练数据时间一致性）
    activity.snapshot_ftp = user.ftp  # 可能为 None（用户没填）
    if_val, tss = calculate_intensity_metrics(
        np=summary.normalized_power,
        ftp=activity.snapshot_ftp,
        duration_seconds=activity.duration,
    )
    activity.intensity_factor = if_val
    activity.tss = tss
    activity.calories = summary.calories
    activity.normalized_power = summary.normalized_power
    activity.started_at = summary.started_at
    activity.finished_at = summary.finished_at
    activity.data_source = result.metadata.source.value  # "gpx" / "fit" / "strava"

    # ---- splits（分段统计）----
    # splits 中的 avg_speed 也是 m/s，转为 km/h 后存入 JSONB
    activity.splits = _convert_splits_speed(summary.splits)

    # ---- 简化轨迹 + 功率区间 ----
    # 新版解析器内部已计算好，直接读取
    activity.simplified_track = result.simplified_track
    activity.power_zones = result.power_zones

    # ---- 批量插入 trackpoints ----
    # parser 输出 Trackpoint dataclass（缩写字段名），数据库列用全称
    # v2 新增 speed（m/s）和 distance（累计米）两列
    trackpoints = result.trackpoints
    for batch_start in range(0, len(trackpoints), _BATCH_SIZE):
        batch = trackpoints[batch_start:batch_start + _BATCH_SIZE]
        tp_objects = []
        for tp in batch:
            tp_obj = Trackpoint(
                activity_id=activity.id,
                seq=tp.seq,
                latitude=tp.lat,
                longitude=tp.lon,
                elevation=tp.ele,
                timestamp=tp.time,
                heart_rate=tp.hr,
                cadence=tp.cad,
                power=tp.power,
                speed=tp.speed,          # v2 新增：m/s
                distance=tp.distance,    # v2 新增：累计米
                # geom：用 PostGIS 函数从经纬度生成空间点
                # WKT 格式："POINT(经度 纬度)"（注意顺序：先经度后纬度）
                geom=f"SRID=4326;POINT({tp.lon} {tp.lat})",
            )
            tp_objects.append(tp_obj)
        db.bulk_save_objects(tp_objects)
        db.flush()  # 每批次刷入数据库，释放内存


def _convert_splits_speed(splits: list[dict] | None) -> list[dict] | None:
    """
    将 splits 中的 avg_speed 从 m/s 转为 km/h。

    翻译层内部统一 m/s，但 DB 和 API 返回 km/h。
    splits 存在 JSONB 里直接返回前端，必须在写入前转换。
    """
    if not splits:
        return splits

    converted = []
    for s in splits:
        new_split = dict(s)  # 浅拷贝，不改原始数据
        if new_split.get("avg_speed") is not None:
            new_split["avg_speed"] = round(new_split["avg_speed"] * 3.6, 1)
        converted.append(new_split)
    return converted


def _mark_failed(db, activity_id: int, error_message: str) -> None:
    """
    解析失败时，更新 Activity 状态为 failed 并记录错误信息。

    关键：先 rollback 清掉可能残留的脏数据（比如插了一半的 trackpoints），
    再做失败标记。否则 commit 会把不完整的数据也一起提交。
    """
    try:
        db.rollback()  # 先回滚脏数据
        activity = db.query(Activity).filter_by(id=activity_id).first()
        if activity:
            activity.status = "failed"
            activity.error_message = error_message
            db.commit()
    except Exception:
        # 连数据库都挂了，只能放弃，Worker 日志会记录原始异常
        db.rollback()


def _get_file_extension(file_url: str) -> str:
    """从文件路径中提取扩展名（小写）。"""
    if not file_url:
        return ""
    dot_idx = file_url.rfind(".")
    if dot_idx < 0:
        return ""
    return file_url[dot_idx:].lower()
