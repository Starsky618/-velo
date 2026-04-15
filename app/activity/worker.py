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

from sqlalchemy import update, func

from app.activity.models import Activity, Trackpoint
from app.database import SessionLocal
from app.parsing.coord_normalizer import normalize
from app.parsing.fit_parser import FITParser, FITParseError
from app.parsing.gpx_parser import GPXParser, GPXParseError
from app.storage.local import LocalStorage
from app.user.models import User

# 存储后端（与 service.py 共用同一类型，但 Worker 进程独立，各自创建实例）
_storage = LocalStorage()

# 批量插入轨迹点的批次大小
_BATCH_SIZE = 500

# 轨迹点数量硬上限（与 service.py 的 _MAX_TRACKPOINTS 一致）
# 这是格式无关的安全网——不管从 GPX/FIT/Strava 哪种来源解析出来，
# 超过此上限都拒绝。第一层（上传时）按格式做轻量预检，这里是第二层兜底。
_MAX_TRACKPOINTS = 50_000


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

    # ===== 步骤 6：将统计量写入 activity =====
    # 从 ParseResult 的 summary 和 metadata 中读取，字段映射如下：
    # - 速度：翻译层内部用 m/s，DB 存 km/h（兼容旧数据），写入时 ×3.6
    # - 其他字段直接写入，单位不变
    summary = result.summary
    activity.title = activity.title or result.metadata.title
    activity.distance = summary.distance
    activity.duration = summary.duration
    activity.elevation_gain = summary.elevation_gain
    activity.avg_speed = round(summary.avg_speed * 3.6, 1) if summary.avg_speed else None
    activity.max_speed = round(summary.max_speed * 3.6, 1) if summary.max_speed else None
    activity.avg_power = summary.avg_power
    activity.max_power = summary.max_power
    activity.avg_hr = summary.avg_hr
    activity.max_hr = summary.max_hr
    activity.avg_cadence = summary.avg_cadence
    activity.calories = summary.calories
    activity.normalized_power = summary.normalized_power
    activity.started_at = summary.started_at
    activity.finished_at = summary.finished_at
    activity.data_source = result.metadata.source.value  # "gpx" / "fit" / "strava"

    # ===== 步骤 7：写入 splits（分段统计）=====
    # splits 中的 avg_speed 也是 m/s，转为 km/h 后存入 JSONB
    activity.splits = _convert_splits_speed(summary.splits)

    # ===== 步骤 8：简化轨迹 + 功率区间 =====
    # 新版解析器内部已计算好，直接读取
    activity.simplified_track = result.simplified_track
    activity.power_zones = result.power_zones

    # ===== 步骤 9：批量插入 trackpoints =====
    # parser 输出 Trackpoint dataclass（缩写字段名），数据库列用全称
    # v2 新增 speed（m/s）和 distance（累计米）两列
    for batch_start in range(0, len(trackpoints), _BATCH_SIZE):
        batch = trackpoints[batch_start:batch_start + _BATCH_SIZE]
        tp_objects = []
        for tp in batch:
            tp_obj = Trackpoint(
                activity_id=activity_id,
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

    # ===== 步骤 10：标记完成 =====
    activity.status = "completed"
    db.commit()

    # ===== 步骤 11：触发 Segment 匹配 =====
    # 活动已标记 completed 并 commit，现在触发赛段自动匹配。
    # 匹配是"尽力而为"：失败不影响活动状态（status 已经是 completed）。
    # 单独 try/except 隔离，防止匹配异常被上层 _mark_failed 捕获而误改活动状态。
    try:
        from app.segment.auto_match import match_activity_against_segments
        match_activity_against_segments(activity_id, db)
    except Exception:
        # 赛段匹配失败静默跳过，活动状态不受影响
        db.rollback()


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
