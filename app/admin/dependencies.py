"""admin 模块依赖函数。"""

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
