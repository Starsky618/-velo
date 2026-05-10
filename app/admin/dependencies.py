"""
admin 模块依赖函数——"管理后台门口的保安"。

干啥用：
    所有 /api/admin/* 路由的入口必须过这道安检——
    确认请求方是 admin 用户（User.is_admin=True），不是普通登录用户。
    把"是不是 admin"这个判断**集中在一处**而不是每个 endpoint 自己判，
    避免漏判 = 普通用户能调 admin endpoint = 严重安全漏洞。

    类比：办公楼前台的保安——
    每个想进 admin 区域的人都要刷门禁卡（JWT），保安先验"卡有效吗"
    （get_current_user 已做），再验"权限对吗"（require_admin 加一道）。
    刷错卡的人在大门口就拦下，不会让他进电梯按楼层（endpoint）。

操作注意：
    1. require_admin **必须**用 Depends(...) 注入到所有 admin endpoint
       不能写"我这个 endpoint 简单不用加"——漏一个 = 一个未授权访问漏洞
    2. 返回的是 User 对象（不是 user_id 整数 / 跟 get_current_user 不同）
       因为 admin 业务经常要拿 admin 自己的昵称 / role 等字段
    3. 非 admin → 抛 403（不是 401）/ 401 = 没登录 / 403 = 登录了但无权限
    4. is_admin 字段在 users 表 / 由 alembic 迁移加（v5 task-3.A.1 引入）
       通过直接 UPDATE users SET is_admin=true WHERE id=... 提升 admin
    5. 用户找不到 → 也抛 403（不暴露 user_id 是否存在 / 安全细节）
    6. is_admin is not True 是显式判断（避开 truthiness 陷阱 #1 / 防 NULL）

输入输出：
    输入：HTTP 请求带 Authorization: Bearer <JWT>
    输出：User 对象（is_admin=True 才返）/ 否则抛 403
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.user.models import User


def require_admin(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """确认当前登录用户是 admin，否则抛 403。

    项目里的 `get_current_user` 像门卫先看工牌，只告诉我们用户编号。
    这里再去住户登记簿（users 表）核对他是不是管理员。
    """
    user = db.query(User).filter_by(id=user_id).first()
    # 找不到用户也返回 403，避免把 user_id 是否存在暴露给调用方。
    # `is not True` 是为了避开 None/0/"" 的 truthiness 陷阱（CLAUDE.md 陷阱 #1）。
    if not user or user.is_admin is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user
