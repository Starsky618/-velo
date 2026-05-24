"""
训练负荷 API 路由像训练日历页的"取号窗口"：前端来取曲线和状态卡数据。

操作注意事项：路由只负责鉴权、接参数、转交 service；不要在这里查表或重算公式。
输入/输出数据流：输入是当前登录用户和 range；输出是 `TrainingLoadResponse`。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.training import schemas, service


router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/load", response_model=schemas.TrainingLoadResponse)
def get_training_load(
    range: schemas.TrainingLoadRange = Query("30d"),
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户的训练负荷曲线。"""
    return service.get_training_load_response(db, user_id, range)
