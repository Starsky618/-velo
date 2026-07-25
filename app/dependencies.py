"""
公共依赖函数——整栋大楼的"安检门"。

FastAPI 的依赖注入机制就像机场安检：
每个需要身份验证的接口，请求进来时先过这道安检门，
验证通行证（JWT）是否合法、是否过期，通过了才放行。

这个文件放的是所有模块共用的依赖函数。
目前只有身份验证（get_current_user），后续可以加权限检查等。

注意事项：
- 这里不写业务逻辑，只做"检查"和"提取"
- get_current_user 返回的是 user_id（整数），不是 User 对象
  需要 User 对象的路由自己去数据库查，保持这里轻量
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError, ExpiredSignatureError
from sqlalchemy.orm import Session

from app.database import get_db
from app.user.models import User
from app.user.service import decode_token

# auto_error=False：请求头没有 token 时不让 FastAPI 自动返回 403，
# 而是把 None 传进来，由我们自己返回 401 "未登录"（与 spec 一致）
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> int:
    """
    从请求头中提取并验证 JWT，返回当前用户的 user_id。

    用法：在路由参数中写 user_id: int = Depends(get_current_user)
    如果 token 无效或过期，自动返回 401 错误，路由函数不会被执行。
    """
    # 没有传 token → 未登录
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录")

    token = credentials.credentials
    try:
        user_id = decode_token(token)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期")
    except (JWTError, ValueError):
        # JWTError：token 格式非法或签名不对
        # ValueError：token 里的 user_id 不是合法整数（防御性）
        raise HTTPException(status_code=401, detail="无效凭证")

    if db.query(User.id).filter(User.id == user_id).first() is None:
        raise HTTPException(status_code=401, detail="用户不存在或已注销")
    return user_id


def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> int | None:
    """
    从请求头中提取并验证 JWT，返回 user_id；无 token 或 token 无效时返回 None。

    用法：公开接口需要"如果登录则识别用户"场景使用。
    e.g. leaderboard 公开（任何人能看 top）/ 但登录用户能多看到自己的 my_rank。

    与 get_current_user 区别：
    - get_current_user：必须登录 / 无 token 或 token 无效 → 401
    - get_optional_user：登录可选 / 无 token 或 token 无效 → 返回 None / 不抛 401
    """
    if credentials is None:
        return None
    try:
        user_id = decode_token(credentials.credentials)
    except (ExpiredSignatureError, JWTError, ValueError):
        return None
    if db.query(User.id).filter(User.id == user_id).first() is None:
        return None
    return user_id
