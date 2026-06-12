"""
骑行活动模块的 API 路由——"前台接待员"。

和 User 模块的 router.py 一样的角色：
接收前端请求 → 转交 service 层处理 → 把结果返回给前端。

注意事项：
- 所有路由函数用 def（同步），禁止 async def
- 不直接操作数据库，所有数据库操作交给 service 层
- 后续任务（3.7 查询接口）会在这里追加更多路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.activity import schemas, service
from app.activity.models import Activity

# 创建路由器，所有骑行活动相关接口都挂在 /api/activities 下
router = APIRouter(prefix="/api/activities", tags=["activity"])


# ========== 任务 3.5：GPX 上传 ==========

@router.post("/upload", response_model=schemas.UploadResponse)
def upload_ride(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    骑行文件上传接口（支持 .gpx 和 .fit）。

    前端以 multipart form-data 格式上传骑行文件，
    后端校验 → 存储 → 建档 → 入队列，立即返回 activity_id。
    不需要等解析完成，前端可以用 activity_id 轮询进度。
    """
    # 读取文件内容
    file_bytes = file.file.read()

    # 校验文件合法性（后缀、大小、内容格式）
    try:
        service.validate_ride_file(file.filename or "", file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 执行上传流程（存储 + 建档 + 入队列）
    try:
        activity = service.upload_ride(db, user_id, file.filename or "upload.gpx", file_bytes)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return schemas.UploadResponse(
        activity_id=activity.id,
        status=activity.status,
    )


# ========== 任务 3.7：活动查询 ==========

@router.get("", response_model=schemas.ActivityListResponse)
def list_activities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的活动列表（分页）。
    按创建时间倒序排列，不含轨迹等大数据。
    """
    items, total = service.get_activity_list(db, user_id, page, page_size)
    return schemas.ActivityListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ========== 轨迹缩略图批量端点（"我的"页/首页活动列表加路线小图）==========
# ⚠ 必须声明在 /{activity_id} 之前：FastAPI 按声明顺序匹配，
#   放后面的话 "track-thumbs" 会被当成 activity_id 解析成 422。

def _downsample_track(track, max_points: int = 60) -> list[list[float]]:
    """把 simplified_track（[{lat, lon, ele}, ...]）抽稀成 ≤max_points 的 [[lon, lat], ...]。

    画"路线形状小图"不需要全部轨迹点——均匀跳点取样 + 终点必保，
    既让一页 20 条活动的响应体保持轻量，又不丢路线的整体形状。
    """
    if not isinstance(track, list) or len(track) < 2:
        return []
    n = len(track)
    step = max(1, -(-n // max_points))  # ceil(n / max_points)，不引入 math
    indexes = list(range(0, n, step))
    if indexes[-1] != n - 1:
        indexes.append(n - 1)  # 终点必保，否则环线/折返路线尾巴会被截掉
    points: list[list[float]] = []
    for i in indexes:
        p = track[i]
        if isinstance(p, dict) and p.get("lat") is not None and p.get("lon") is not None:
            points.append([float(p["lon"]), float(p["lat"])])
    return points if len(points) >= 2 else []


@router.get("/track-thumbs", response_model=schemas.TrackThumbsResponse)
def get_track_thumbs(
    ids: str = Query(..., description="逗号分隔的活动 id，最多取前 20 个"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    批量获取活动的抽稀轨迹（owner-only）。

    隐私边界：只返回请求者本人的活动；别人的 id、不存在的 id、
    没有轨迹的 id 一律静默缺席——不报错也不泄露"这条活动存在与否"。
    非法 id 片段（非数字）直接跳过，保证前端拼接出错也不会 500。
    """
    parsed_ids: list[int] = []
    for part in ids.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            value = int(part)
            if value > 0:
                parsed_ids.append(value)
    parsed_ids = parsed_ids[:20]
    if not parsed_ids:
        return schemas.TrackThumbsResponse(items=[])

    rows = (
        db.query(Activity.id, Activity.simplified_track)
        .filter(Activity.id.in_(parsed_ids), Activity.user_id == user_id)
        .all()
    )
    items = []
    for row in rows:
        points = _downsample_track(row.simplified_track)
        if points:
            items.append(schemas.TrackThumbItem(activity_id=row.id, points=points))
    return schemas.TrackThumbsResponse(items=items)


@router.get("/{activity_id}", response_model=schemas.ActivityDetail)
def get_activity(
    activity_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取单个活动的完整详情。
    包含简化轨迹、分段数据、功率区间。

    需登录。本人始终可看；他人活动按 visibility 判定（public 可看 / private 返 404）。
    """
    try:
        activity = service.get_activity_detail(db, activity_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return activity


@router.patch("/{activity_id}", response_model=schemas.ActivitySummary)
def update_activity(
    activity_id: int,
    req: schemas.ActivityUpdateRequest,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    编辑活动信息（目前只支持修改标题）。
    只能编辑自己的活动。
    """
    try:
        activity = service.update_activity(db, activity_id, user_id, req.title)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return activity


@router.patch("/{activity_id}/privacy", response_model=schemas.ActivityPrivacyResponse)
def update_activity_privacy(
    activity_id: int,
    req: schemas.ActivityPrivacyUpdate,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新一条骑行的隐私设置（task-4.6）。

    3 个开关：visibility（公开/私密）/ hide_power / hide_heartrate
    仅 owner 可改自己的活动。schema 限制 extra="forbid" 防误改其他字段。
    """
    try:
        privacy = service.update_activity_privacy(
            db, activity_id, user_id,
            visibility=req.visibility,
            hide_power=req.hide_power,
            hide_heartrate=req.hide_heartrate,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return schemas.ActivityPrivacyResponse(
        visibility=privacy.visibility,
        hide_power=privacy.hide_power,
        hide_heartrate=privacy.hide_heartrate,
    )


@router.delete("/{activity_id}", status_code=204)
def delete_activity(
    activity_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除活动。
    级联删除轨迹点 + 删除存储的 GPX 文件。
    只能删除自己的活动。
    """
    try:
        service.delete_activity(db, activity_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{activity_id}/timeseries", response_model=schemas.TimeseriesResponse)
def get_activity_timeseries(
    activity_id: int,
    points: int = Query(1200, ge=50, le=2000, description="采样点数上限"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取骑行时序数据（供前端画速度/功率/心率曲线）。

    从原始轨迹点中按距离采样，返回等长数组。
    points 参数只做上限保护；真正的读数间距由骑行总距离自动决定。
    """
    try:
        data = service.get_activity_timeseries(db, activity_id, user_id, points)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return data


@router.get("/{activity_id}/power-curve", response_model=schemas.ActivityPowerCurveResponse)
def get_activity_power_curve(
    activity_id: int,
    points: int = Query(1000, ge=50, le=2000, description="功率曲线画图点数上限"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取单次骑行的功率曲线分析数据。

    这张图回答的是：“这次骑行里，任意持续时长下最强的一段是多少 W？”
    points 只控制画图点数；用户拖动停住后的精确读数走 effort 接口。
    """
    try:
        data = service.get_activity_power_curve(db, activity_id, user_id, points)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return data


@router.get(
    "/{activity_id}/power-curve/effort",
    response_model=schemas.ActivityPowerCurveEffortResponse,
)
def get_activity_power_curve_effort(
    activity_id: int,
    duration_sec: int = Query(..., ge=1, description="要精确查询的持续时长（秒）"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    精确查询某个持续时长下的最佳平均功率。

    前端手指停住后调用这里，气泡就能显示精确到秒的功率和发生位置。
    """
    try:
        data = service.get_activity_power_curve_effort(
            db, activity_id, user_id, duration_sec
        )
    except service.DurationOutOfRange as e:
        # duration_sec 不合法（≤0 或超出活动长度）是参数错，按 400 返回；
        # 走自定义异常类型避免靠中文文案路由——未来文案改了不会静默挂
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return data


@router.get("/{activity_id}/status", response_model=schemas.ActivityStatusResponse)
def get_activity_status(
    activity_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    轮询活动解析状态。
    前端上传后每 2 秒调一次，直到 status 变为 completed 或 failed。
    """
    try:
        activity = service.get_activity_status(db, activity_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return schemas.ActivityStatusResponse(
        status=activity.status,
        error_message=activity.error_message,
        duplicate_of=activity.duplicate_of,  # Sprint 5 task-2 dedupe：前端轮询看到非 None → 跳合并目标 + toast
    )
