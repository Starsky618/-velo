# app/notification/router.py
"""
通知模块 API 路由——"广播室的服务窗口"。

两个窗口：
1. /api/notifications — 通知列表（"最近有什么消息？"）
2. /api/user/honors — 荣誉表（"我有哪些 KOM 和前十？"）

操作注意事项：
- 两个路由前缀不同（/api/notifications 和 /api/user），所以需要两个 router 实例
- 和 segment 模块的 /api/user/efforts 是同一个挂载模式
- get_current_user 返回 int（user_id），不是 User 对象
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.notification import service

# 通知列表路由
notification_router = APIRouter(prefix="/api/notifications", tags=["notification"])

# 荣誉表路由（挂在 /api/user 下）
honor_router = APIRouter(prefix="/api/user", tags=["notification"])


@notification_router.get("")
def get_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """查询当前用户的通知列表，按时间倒序分页。"""
    return service.get_notifications(db, user_id, page, page_size)


@honor_router.get("/honors")
def get_user_honors(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """查询当前用户的 KOM 和前十名荣誉表。"""
    return service.get_user_honors(db, user_id)
