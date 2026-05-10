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


@router.get("/{activity_id}", response_model=schemas.ActivityDetail)
def get_activity(
    activity_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取单个活动的完整详情。
    包含简化轨迹、分段数据、功率区间。
    只能查看自己的活动。
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
    points: int = Query(500, ge=50, le=2000, description="采样点数"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取骑行时序数据（供前端画速度/功率/心率曲线）。

    从原始轨迹点中等间隔采样，返回等长数组。
    points 参数控制采样密度，默认 500（手机屏幕够用）。
    """
    try:
        data = service.get_activity_timeseries(db, activity_id, user_id, points)
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
