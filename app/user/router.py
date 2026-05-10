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


# ========== 任务 2.5：骑行统计 ==========

@router.get("/stats", response_model=schemas.StatsResponse)
def get_stats(
    period: schemas.StatsPeriod = schemas.StatsPeriod.week,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的骑行统计。

    period 参数控制统计时间范围：week / month / year / all，默认 week。
    需要登录（请求头带 JWT）。
    """
    return service.get_user_stats(db, user_id, period.value)


# ========== task-2.C.3：v5 4 个新 endpoint ==========
#
# 路径全部用单数 /api/user/...（CLAUDE.md 命名规则 / Tim 2026-04-30 拍 A）
# 4 个 endpoint：
# - GET /api/user/me/power-curve  — 我的功率曲线（period 切片 + Redis 缓存）
# - GET /api/user/me/heatmap      — 我的城市热图（city 筛选 + Redis 缓存）
# - PATCH /api/user/me            — 改 settings（v5 只 city / 未来加 settings 类字段也走这里）
# - GET /api/user/{user_id}/profile — 看他人主页（D-P08 红线 / 严格白名单）
#
# 静态路径（/me/...）vs 动态路径（/{user_id}/...）共存：FastAPI 优先匹配静态


@router.get("/active", response_model=schemas.ActiveUsersResponse)
def get_active_users(
    limit: int = 10,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    探索 tab 骑友 section（Sprint 5 task-3）。

    返回最近活跃用户列表（按最近骑车时间倒序），排除：
    - admin 后台账号（is_admin=True）
    - 当前登录用户自己
    - 无任何 completed activity 的用户（INNER JOIN 自动过滤）
    - dedupe 重复的 activity（duplicate_of IS NOT NULL）

    路径用 /api/user/active 单数（跟 task-2.C.3 拍的 /api/user 单数前缀一致）。
    limit 默认 10 / 前端横向 scroll 用 6-10 个就够。
    """
    if limit < 1 or limit > 50:
        limit = 10  # 防御性兜底（极端 query 参数）
    items = service.get_active_users(db, exclude_user_id=user_id, limit=limit)
    return {"items": items}


@router.get("/me/power-curve", response_model=schemas.PowerCurveResponse)
def get_my_power_curve(
    period: schemas.PowerCurvePeriod = schemas.PowerCurvePeriod.last_30_days,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的功率曲线（按 period 切片）。

    period 5 档（滚动窗口型 / D16 v0.3）：
    last_30_days / last_90_days / last_180_days / last_365_days / all_time
    （default last_30_days）。

    Redis 缓存 1h，cache miss 时 100k trackpoints × 6 windows ≈ 32ms。
    """
    return service.get_user_power_curve(db, user_id, period.value)


@router.get("/me/heatmap", response_model=schemas.HeatmapResponse)
def get_my_heatmap(
    city: schemas.UserCity | None = None,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的骑行热图（D27 v2 polish / v3 polish city 改可选）。

    city 参数：
    - 不传 → 返回该用户所有 completed activities 的轨迹（不按起点城市筛 / response.city = None）。
      前端"全部"视图走这条路径——一次性看用户在所有城市的足迹。
    - 传枚举值（6 主城 + unknown）→ 保留旧行为：按 simplified_track 起点城市筛。

    返回 tracks: list[list[[lon, lat]]]（保留 activity 边界 / 每个 activity 一条独立轨迹 / 前端画 polyline）
    + activity_count（与 tracks 长度一致 / 单点 activity 自动跳过不计数）。

    Redis 缓存 1h，无 city 与按 city 走两套独立 cache key（前者 `heatmap:user_{id}`，
    后者 `heatmap:user_{id}:city_{city}`），互不干扰。
    """
    return service.get_user_heatmap(db, user_id, city.value if city else None)


@router.patch("/me", response_model=schemas.UserProfile)
def patch_me(
    body: schemas.UserPatchRequest,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    修改当前用户的 settings 类字段（v5 只 city / 未来扩）。

    设计：与现有 `PUT /profile` 分开——profile 改 ftp/weight/bike_type/weekly_goal 主资料；
    PATCH /me 改 settings（city 等"附加项"）。两套独立避免接口耦合。

    body.city：
    - 不传 → 不改（沿用现有 city）
    - 传 null → 清空（user.city = NULL，与 nullable=True 一致）
    - 传枚举值 → 更新 + 失效该用户所有 city 的 heatmap 缓存
    """
    # exclude_unset=True：区分"没传 city"vs"传了 city=null"——
    # 前者是 'city' not in update_data，后者是 update_data['city'] is None
    update_data = body.model_dump(exclude_unset=True, mode="json")

    if "city" in update_data:
        try:
            service.update_user_city(db, user_id, update_data["city"])
        except ValueError as e:
            # service 抛 "invalid city" / "user not found"
            msg = str(e)
            if "user not found" in msg:
                raise HTTPException(status_code=404, detail="用户不存在")
            # invalid city 在 schema 层已被 422 拦掉，到这里说明 service 层自己的兜底
            raise HTTPException(status_code=422, detail=msg)

    # 返回最新 user（含可能改过的 city）
    return service.get_user_by_id(db, user_id)


@router.get("/{user_id}/profile", response_model=schemas.UserProfileResponse)
def get_user_profile(
    user_id: int,
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    看他人主页（PRD 5.A.2 / D-P08 红线）。

    返回严格白名单字段（与 service._PROFILE_RESPONSE_KEYS 一致）：
    - id / nickname / avatar_url / city / bike_type
    - total_distance_km / total_elevation_m / activity_count
    - current_month_summary（distance_km / elevation_m / avg_power_w）

    严格不返：efforts / activities / heatmap / strava_* / openid / mute_notifications / 任何 token /
    **ftp**（Sprint 4 codex 异源审 P1-4 砍 / FTP 是骑手生理数据 / 跟 weight 一起属敏感）/ weight / W·kg。
    "看自己 ID 跟看他人字段一致"——不区分 self/others。
    """
    try:
        return service.get_user_profile_for_others(db, user_id, requester_user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")


# ========== task-4.3.0：看他人 power-curve / heatmap ==========
#
# Sprint 4 task-4.3 前置后端补：用户详情页要展示 ta 的功率曲线 + 热力图。
# 复用现有 service.get_user_power_curve / get_user_heatmap（已支持任意 user_id 参数）。
#
# 路由匹配：静态 /me/... 在本文件上方 / 动态 /{user_id}/... 后置。
# FastAPI 优先匹配静态路径 → 这两个新动态 endpoint 不会跟 /me/... 撞车。
#
# 权限（D-P08 / 看他人主页默认公开）：任意登录用户即可。


@router.get("/{user_id}/power-curve", response_model=schemas.PowerCurveResponse)
def get_user_power_curve_for_others(
    user_id: int,
    period: schemas.PowerCurvePeriod = schemas.PowerCurvePeriod.last_30_days,
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    看他人功率曲线（D-P08 / 任意登录用户）。

    period 5 档（滚动窗口型 / D16 v0.3 / 同 /me/power-curve）：
    last_30_days / last_90_days / last_180_days / last_365_days / all_time。

    user 不存在 → service.get_user_by_id 抛 ValueError → 翻译为 404
    （跟 L220-223 /{user_id}/profile 同 pattern / Claude 综合审 Critical-1 验证后修）。
    """
    try:
        service.get_user_by_id(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return service.get_user_power_curve(db, user_id, period.value)


@router.get("/{user_id}/heatmap", response_model=schemas.HeatmapResponse)
def get_user_heatmap_for_others(
    user_id: int,
    city: schemas.UserCity | None = None,
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    看他人骑行热图（D-P08 / 任意登录用户）。

    city 可选（D30 v3 polish / 同 /me/heatmap）：
    - 不传 → 看 ta 全部足迹（不按起点城市筛 / response.city = None）。
    - 传枚举值 → 按 simplified_track 起点城市筛。

    user 不存在 → service.get_user_by_id 抛 ValueError → 翻译为 404
    （跟 L220-223 /{user_id}/profile 同 pattern / Claude 综合审 Critical-1 验证后修）。
    Redis 缓存 1h（同 /me/heatmap / cache key 跟 user_id 走 / 不区分 self/others）。
    """
    try:
        service.get_user_by_id(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return service.get_user_heatmap(db, user_id, city.value if city else None)
