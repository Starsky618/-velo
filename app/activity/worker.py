"""
异步解析 Worker 的任务函数——"快递分拣工人的操作手册"。

当用户上传 GPX 文件后，API（Task 3.5）会把一个"解析任务"扔进 Redis 队列。
rq Worker（根目录的 worker.py）从队列中取出任务，调用这里的 parse_activity() 执行。

完整流程：
1. 从数据库取出 Activity 记录和用户信息
2. 从文件存储下载 GPX 文件
3. 调 gpx_parser 解析 → 得到轨迹点 + 统计数据
4. 调 simplify 简化轨迹 → 供前端画地图
5. 调 calculate_power_zones 算功率区间 → 训练分析
6. 把所有结果写回数据库
7. 批量插入轨迹点（每 500 条一批）

好比快递分拣中心的拆包流程：
拆包（下载GPX）→ 翻译内容（parser）→ 压缩照片（simplify）
→ 分类评分（power_zones）→ 写入档案 → 标记完成。

注意事项：
- 这个函数由 rq Worker 在独立进程中执行，不在 FastAPI 请求上下文中
- 使用 SessionLocal 手动管理数据库连接（不经过 get_db 依赖注入）
- 无论成功失败都必须 close db，避免连接泄漏
- Segment 匹配（步骤 11）在 Task 4 中实现，当前留空跳过
"""

from app.activity.gpx_parser import GPXParseError, parse_gpx
from app.activity.power_zones import calculate_power_zones
from app.activity.models import Activity, Trackpoint
from app.activity.simplify import simplify_track
from app.database import SessionLocal
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
    except GPXParseError as e:
        # GPX 格式问题（用户上传了损坏的文件等）
        _mark_failed(db, activity_id, str(e))
    except Exception:
        # 未预期的系统错误
        _mark_failed(db, activity_id, "系统内部错误")
    finally:
        db.close()


def _do_parse(db, activity_id: int) -> None:
    """
    解析的核心流程（12 步），拆成独立函数方便异常处理包裹。
    """
    # ===== 步骤 1-2：取记录 =====
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError(f"Activity {activity_id} 不存在")

    user = db.query(User).filter_by(id=activity.user_id).first()
    if user is None:
        raise ValueError(f"User {activity.user_id} 不存在")

    # ===== 步骤 3：下载 GPX 文件 =====
    gpx_content = _storage.download(activity.file_url)

    # ===== 步骤 4：更新状态为 processing =====
    activity.status = "processing"
    db.commit()

    # ===== 步骤 5：解析 GPX =====
    # weight 用于无功率时的卡路里估算，默认 70kg
    weight = float(user.weight) if user.weight else 70.0
    result = parse_gpx(gpx_content, weight=weight)

    # ===== 步骤 5.5：轨迹点数量安全网 =====
    # 第二层防御：解析后检查实际点数。
    # 即使第一层（上传时的标签计数）漏掉了异常格式，这里也能拦住。
    trackpoints = result["trackpoints"]
    if len(trackpoints) > _MAX_TRACKPOINTS:
        raise GPXParseError(
            f"轨迹点过多（{len(trackpoints)} 个，上限 {_MAX_TRACKPOINTS}），请裁剪后重新上传"
        )

    # ===== 步骤 6：将统计量写入 activity =====
    activity.title = activity.title or result["title"]  # 用户没起名则用 GPX 里的
    activity.distance = result["distance"]
    activity.duration = result["duration"]
    activity.elevation_gain = result["elevation_gain"]
    activity.avg_speed = result["avg_speed"]
    activity.max_speed = result["max_speed"]
    activity.avg_power = result["avg_power"]
    activity.max_power = result["max_power"]
    activity.avg_hr = result["avg_hr"]
    activity.max_hr = result["max_hr"]
    activity.avg_cadence = result["avg_cadence"]
    activity.calories = result["calories"]
    activity.started_at = result["started_at"]
    activity.finished_at = result["finished_at"]
    activity.splits = result["splits"]

    # ===== 步骤 7：生成简化轨迹 =====
    activity.simplified_track = simplify_track(result["trackpoints"])

    # ===== 步骤 8：功率区间计算 =====
    if user.ftp is not None and result["avg_power"] is not None:
        activity.power_zones = calculate_power_zones(result["trackpoints"], user.ftp)
    else:
        activity.power_zones = None

    # ===== 步骤 9：批量插入 trackpoints =====
    # parser 输出用缩写（lat/lon/ele/time/hr/cad），数据库列用全称
    # 这里做字段映射
    # trackpoints 已在步骤 5.5 中定义
    for batch_start in range(0, len(trackpoints), _BATCH_SIZE):
        batch = trackpoints[batch_start:batch_start + _BATCH_SIZE]
        tp_objects = []
        for tp in batch:
            tp_obj = Trackpoint(
                activity_id=activity_id,
                seq=tp["seq"],
                latitude=tp["lat"],
                longitude=tp["lon"],
                elevation=tp["ele"],
                timestamp=tp["time"],
                heart_rate=tp["hr"],
                cadence=tp["cad"],
                power=tp["power"],
                # geom：用 PostGIS 函数从经纬度生成空间点
                # WKT 格式："POINT(经度 纬度)"（注意顺序：先经度后纬度）
                geom=f"SRID=4326;POINT({tp['lon']} {tp['lat']})",
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
