"""
骑行活动模块的 API 路由——"前台接待员"。

和 User 模块的 router.py 一样的角色：
接收前端请求 → 转交 service 层处理 → 把结果返回给前端。

注意事项：
- 所有路由函数用 def（同步），禁止 async def
- 不直接操作数据库，所有数据库操作交给 service 层
- 后续任务（3.7 查询接口）会在这里追加更多路由
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.activity import schemas, service

# 创建路由器，所有骑行活动相关接口都挂在 /api/activities 下
router = APIRouter(prefix="/api/activities", tags=["activity"])


# ========== 任务 3.5：GPX 上传 ==========

@router.post("/upload", response_model=schemas.UploadResponse)
def upload_gpx(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    GPX 文件上传接口。

    前端以 multipart form-data 格式上传 .gpx 文件，
    后端校验 → 存储 → 建档 → 入队列，立即返回 activity_id。
    不需要等解析完成，前端可以用 activity_id 轮询进度。
    """
    # 读取文件内容
    file_bytes = file.file.read()

    # 校验文件合法性（后缀、大小、内容格式）
    try:
        service.validate_gpx_file(file.filename or "", file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 执行上传流程（存储 + 建档 + 入队列）
    try:
        activity = service.upload_gpx(db, user_id, file.filename or "upload.gpx", file_bytes)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return schemas.UploadResponse(
        activity_id=activity.id,
        status=activity.status,
    )
