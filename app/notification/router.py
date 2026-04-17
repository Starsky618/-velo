# app/notification/router.py
"""
通知模块 API 路由——"广播室的服务窗口"。

三个窗口：
1. GET  /api/notifications — 通知列表（"最近有什么消息？"）
2. POST /api/notifications/mark-all-read — 一键标全读（进页即标读）
3. GET  /api/user/honors — 荣誉表（"我有哪些 KOM 和前十？"）

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
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """
    查询当前用户的通知列表，按时间倒序分页。

    参数：
        unread_only: True 只查未读；False 查所有（默认，向后兼容）

    响应永远带 unread_count 字段——首页红点调用时传 page_size=1 即可只拿数字。
    """
    return service.get_notifications(
        db, user_id, page, page_size, unread_only=unread_only,
    )


@notification_router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """
    把当前用户所有未读通知标为已读。

    幂等：重复调用返 {"marked": 0}。
    前端使用场景：用户进通知中心页时立即调用，实现"进页即标读"。
    """
    marked = service.mark_all_read(db, user_id)
    return {"marked": marked}


@honor_router.get("/honors")
def get_user_honors(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user),
):
    """查询当前用户的 KOM 和前十名荣誉表。"""
    return service.get_user_honors(db, user_id)
