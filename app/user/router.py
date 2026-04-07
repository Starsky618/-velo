"""
用户模块的 API 路由——"前台接待员"。

负责接收前端发来的请求、调用 service 层处理、把结果返回给前端。
自己不做任何业务逻辑，只做三件事：接请求、转交、回结果。

好比餐厅服务员：客人点菜（请求）→ 传给厨房（service）→ 端菜上桌（响应）。

注意事项：
- 所有路由函数用 def（同步），禁止 async def
- 不直接操作数据库，所有数据库操作交给 service 层
- 错误处理统一用 HTTPException
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.user import schemas, service

# 创建路由器，所有用户相关接口都挂在 /api/user 下
router = APIRouter(prefix="/api/user", tags=["user"])


@router.post("/login", response_model=schemas.LoginResponse)
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
    """
    微信登录接口。

    前端用 wx.login() 拿到一个临时 code，发到这里，
    后端拿 code 去微信服务器验证身份，然后发一张通行证（JWT）。
    新用户会自动注册。
    """
    # 第一步：拿 code 去微信换 openid
    try:
        openid = service.wx_code_to_openid(req.code)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    # 第二步：查找或创建用户
    user, is_new = service.get_or_create_user(db, openid)

    # 第三步：签发通行证
    token = service.create_token(user.id)

    return schemas.LoginResponse(
        token=token,
        user_id=user.id,
        is_new_user=is_new,
    )


# ========== 任务 2.4：用户资料 ==========

@router.get("/profile", response_model=schemas.UserProfile)
def get_profile(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的资料。
    需要登录（请求头带 JWT）。
    """
    try:
        user = service.get_user_by_id(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return user


@router.put("/profile", response_model=schemas.UserProfile)
def update_profile(
    req: schemas.UserProfileUpdate,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新当前用户的资料。
    只传想改的字段，没传的保持不变。
    需要登录（请求头带 JWT）。
    """
    # exclude_unset=True：只取前端实际传了的字段，没传的不动
    # mode="json"：确保枚举值（如 BikeType.road）被序列化为纯字符串 "road"，
    # 避免把枚举对象直接塞给数据库
    update_data = req.model_dump(exclude_unset=True, mode="json")
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")

    try:
        user = service.update_user_profile(db, user_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return user
