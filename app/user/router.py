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

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.activity import schemas as activity_schemas
from app.activity.backfill_ftp import enqueue_backfill_ftp
from app.activity.ftp_estimator import estimate_ftp_for_user
from app.activity.models import BreakthroughEvent
from app.database import get_db
from app.dependencies import get_current_user
from app.user import schemas, service
from app.user.models import User

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

    Sprint 6 task-2：响应含 badges 字段（top 3 真实数据自动算的身份徽章 / 自他对称）。
    """
    try:
        user = service.get_user_by_id(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 自他对称（D-P08 红线 / Sprint 6 task-2）：自己看自己也返 badges 字段，
    # 与 GET /{user_id}/profile（看他人）字段集合完全一致。
    # 走 ORM → model_validate → 覆盖 badges 字段，避免改 service.get_user_by_id 返回类型。
    profile = schemas.UserProfile.model_validate(user)
    profile.badges = [
        schemas.Badge(**b) for b in service.get_user_badges(db, user_id)
    ]
    return profile


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

    Sprint 6 task-2 契约（写操作响应不计算 badges）：
    本 endpoint 返回 `UserProfile`，schema 含 `badges: list[Badge] = []` 默认值。
    PUT 是"我改了什么字段"的 echo，**不重新计算徽章**——前端在 PUT 成功后
    应单独发 GET /api/user/profile 刷新整页（含最新 badges）。
    理由：① 减少写路径上的 SQL 开销 ② 改 FTP 后徽章可能变 / 让前端显式 GET 拉
    比在 PUT 响应里偷偷塞进来更清晰。
    """
    # exclude_unset=True：只取前端实际传了的字段，没传的不动
    # mode="json"：确保枚举值（如 BikeType.road）被序列化为纯字符串 "road"，
    # 避免把枚举对象直接塞给数据库
    update_data = req.model_dump(exclude_unset=True, mode="json")
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的字段")

    # Sprint 9 task-4：首次填 ftp 触发回填——把该用户所有 snapshot_ftp=NULL 的
    # 历史活动批量补登 snapshot_ftp + 重算 IF/TSS。
    # 必须在 update_user_profile 之前读旧 user.ftp（commit 后 ORM 字段已被改写）。
    # 触发条件：旧 ftp 为 NULL + 新 ftp 是合法整数（schema 已守 50-500 范围）。
    try:
        existing_user = service.get_user_by_id(db, user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    old_ftp = existing_user.ftp
    new_ftp = update_data.get("ftp")
    is_first_time_fill = old_ftp is None and isinstance(new_ftp, int) and new_ftp > 0

    try:
        user = service.update_user_profile(db, user_id, update_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # commit 后才入队——保证 RQ worker 起跑时 DB 里 user.ftp 已是新值
    # （虽然 worker 不读 user.ftp / 用传入的 new_ftp，但语义上"先持久化再触发副作用"更稳）
    if is_first_time_fill:
        enqueue_backfill_ftp(user_id, new_ftp)

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
    q: str | None = None,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    探索 tab 骑友 section + 搜索（Sprint 5 task-3 / 真用回归加 q 参数）。

    返回最近活跃用户列表（按最近骑车时间倒序），排除：
    - admin 后台账号（is_admin=True）
    - 当前登录用户自己
    - 无任何 completed activity 的用户（INNER JOIN 自动过滤）
    - dedupe 重复的 activity（duplicate_of IS NOT NULL）

    q 参数（可选）：nickname 模糊搜索关键词（≥ 1 字 / ≤ 64 字 / 防注入 SQLAlchemy 参数化）。
    搜索时仍按活跃度排序（不按相关性 / MVP 简化）。

    路径用 /api/user/active 单数（跟 task-2.C.3 拍的 /api/user 单数前缀一致）。
    """
    if limit < 1 or limit > 50:
        limit = 10  # 防御性兜底（极端 query 参数）
    # q 长度防御：> 64 字直接当无搜索（防恶意大 string）
    search_keyword = q.strip() if q else None
    if search_keyword and (len(search_keyword) < 1 or len(search_keyword) > 64):
        search_keyword = None
    items = service.get_active_users(
        db,
        exclude_user_id=user_id,
        limit=limit,
        search=search_keyword,
    )
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


@router.get("/me/city-medals", response_model=schemas.CityMedalsResponse)
def get_my_city_medals(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    我的城市征服勋章墙（Sprint 6 task-3）。

    返回当前用户已点亮城市列表 + 全 6 城 medal 数组（含中文 label）。
    自他对称（D-P08 红线）：与 GET /api/user/{user_id}/city-medals 字段集合完全一致。

    "已点亮"定义：用户有至少一条 completed activity 起点落在该城内（排除 duplicate / unknown）。
    """
    return service.get_city_medals(db, user_id)


@router.patch("/me", response_model=schemas.UserProfile)
def patch_me(
    body: schemas.UserPatchRequest,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    修改当前用户的 settings 类字段（v5 city / Sprint 6 加 bio）。

    设计：与现有 `PUT /profile` 分开——profile 改 ftp/weight/bike_type/weekly_goal 主资料；
    PATCH /me 改 settings（city / bio 等"附加项"）。两套独立避免接口耦合。

    body.city：
    - 不传 → 不改（沿用现有 city）
    - 传 null → 清空（user.city = NULL，与 nullable=True 一致）
    - 传枚举值 → 更新 + 失效该用户所有 city 的 heatmap 缓存

    body.bio（Sprint 6 task-1）：
    - 不传 → 不改
    - 传 null → 清空（user.bio = NULL）
    - 传 "" 空串 → 等价 null（service_auth 层归一化）
    - 传字符串 → 更新（≤ 30 字符 + 单行，schema 层已 422 校验）

    Sprint 6 task-2 契约（写操作响应不计算 badges）：
    本 endpoint 返回 `UserProfile`，schema 含 `badges: list[Badge] = []` 默认值。
    PATCH 是 settings 类窄写操作，**不重新计算徽章**——前端 PATCH 后应单独发
    GET /api/user/profile 刷新整页（与 PUT /profile 同样契约 / 一致行为）。
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

    # Sprint 6 task-1：bio 写入走 update_user_profile（已内建空串转 NULL 逻辑）
    # 只挑 bio 字段传过去，避免把 city 误塞进 setattr 循环（city 已被上面 update_user_city 处理）
    if "bio" in update_data:
        try:
            service.update_user_profile(db, user_id, {"bio": update_data["bio"]})
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # 返回最新 user（含可能改过的 city / bio）
    return service.get_user_by_id(db, user_id)


# ========== Sprint 9 task-6：FTP 智能估算 endpoint ==========
#
# 给 settings 页"让系统估算"按钮用——跑 CP 3-param 模型算用户 FTP。
# 落在 /me/... 静态路径 / FastAPI 先匹配静态再匹配动态 /{user_id}/...
#
# 调用链：settings.js onEstimateFtp → GET /me/ftp-estimate → estimate_ftp_for_user
#        → 拉用户全 best efforts → fit_cp3_model → 返 (ftp, confidence, method, r2)
# 失败兜底：估算抛异常 → 500 / 前端 catch toast "估算失败 请手动填"
# insufficient 兜底：返 ftp=None / 前端弹窗显示"历史活动不够"


@router.get("/me/ftp-estimate", response_model=activity_schemas.EstimationResultResponse)
def get_ftp_estimate(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """task-6 (sprint9)：给前端 ftp 估算弹窗用 / 跑 CP 3-param 算用户 ftp。

    返回 EstimationResultResponse（ftp / confidence / method / r2）。
    confidence='insufficient' 时 ftp=None / 前端引导用户手动填。
    """
    result = estimate_ftp_for_user(db, user_id)
    return result


# ========== Sprint 9 task-8：FTP Breakthrough 事件 endpoints ==========
#
# 调用链：
#   1. worker 解析活动完成 → detect_breakthrough 写 pending event
#   2. settings.js onShow → GET /me/breakthroughs → 返 pending list
#   3. 前端弹窗 → PATCH /me/breakthroughs/:id { status: accepted/rejected }
#   4. accepted 同事务更新 user.ftp（不触发 task-4 backfill / 快照式纯粹）
#
# 自动过期（7 天）在 GET 内做：每次 onShow 时把 expires_at < now 的 pending 转 expired。
# 比 cron 简单且零运维成本（velo 用户量小 / 不需要专门 cleanup job）。


@router.get(
    "/me/breakthroughs",
    response_model=list[activity_schemas.BreakthroughEventResponse],
)
def list_pending_breakthroughs(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """task-8 (sprint9)：拉当前用户所有 pending breakthrough 事件。

    settings.js onShow 调一次 / 有 pending 则弹窗 / 没有静默。

    自动过期逻辑：每次调用先把 expires_at < now 的 pending 转 expired
    （懒清理 / 不依赖额外 cron 任务）。
    """
    now = datetime.now(timezone.utc)
    # 懒过期：把过期但仍是 pending 的事件改 expired / 一条 UPDATE 搞定
    db.query(BreakthroughEvent).filter(
        BreakthroughEvent.user_id == user_id,
        BreakthroughEvent.status == "pending",
        BreakthroughEvent.expires_at < now,
    ).update({"status": "expired"}, synchronize_session=False)
    db.commit()

    # 返当前仍 pending 的事件
    return (
        db.query(BreakthroughEvent)
        .filter(
            BreakthroughEvent.user_id == user_id,
            BreakthroughEvent.status == "pending",
        )
        .order_by(BreakthroughEvent.detected_at.desc())
        .all()
    )


@router.patch(
    "/me/breakthroughs/{event_id}",
    response_model=activity_schemas.BreakthroughEventResponse,
)
def update_breakthrough(
    event_id: int,
    payload: activity_schemas.BreakthroughUpdatePayload,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """task-8 (sprint9)：用户处理 breakthrough 事件（accept / reject）。

    accepted 语义（关键）：
      - 同事务更新 user.ftp = suggested_ftp
      - **不触发** task-4 历史活动回填 / 历史 snapshot_ftp 保持原值
      - 后续新活动 IF / TSS 用新 ftp 算（snapshot 时间点之后才生效）

    rejected 语义：只标状态 / 不动 user.ftp。

    权限：用户只能改自己的事件（filter user_id）。
    幂等：已 accepted / rejected / expired 的事件 → 400（防双击重复操作）。
    """
    # Codex 异源审 Important（2026-05-21 抓）：原子 UPDATE 防并发 race
    # 之前 .first() + 检查 + .commit 模式有两个 race：
    # (1) 两个并发 PATCH 同时通过 status=pending 检查 → last-write-wins
    # (2) GET 端懒过期跟 PATCH 之间 race / 已过期 pending 仍能 accepted
    # 修：UPDATE ... WHERE id + user_id + status='pending' + expires_at>now / rowcount 检查
    now = datetime.now(timezone.utc)
    rowcount = (
        db.query(BreakthroughEvent)
        .filter(
            BreakthroughEvent.id == event_id,
            BreakthroughEvent.user_id == user_id,
            BreakthroughEvent.status == "pending",
            BreakthroughEvent.expires_at > now,
        )
        .update({"status": payload.status}, synchronize_session=False)
    )

    if rowcount == 0:
        # 真存在但已处理 / 过期 / 越权 — 区分 404 vs 400
        existing = db.query(BreakthroughEvent).filter_by(id=event_id, user_id=user_id).first()
        if existing is None:
            db.commit()
            raise HTTPException(status_code=404, detail="Breakthrough 不存在")
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"该 Breakthrough 已处理（状态：{existing.status}）",
        )

    if payload.status == "accepted":
        # 同事务更新 user.ftp / 不触发 backfill（快照式 / 不动历史）
        event = db.query(BreakthroughEvent).filter_by(id=event_id).first()
        user = db.query(User).filter_by(id=user_id).first()
        if user is not None and event is not None:
            user.ftp = event.suggested_ftp

    db.commit()
    return db.query(BreakthroughEvent).filter_by(id=event_id).first()


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


@router.get("/{user_id}/city-medals", response_model=schemas.CityMedalsResponse)
def get_user_city_medals(
    user_id: int,
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    看他人城市征服勋章墙（Sprint 6 task-3 / D-P08 / 任意登录用户）。

    自他对称（D-P08 红线 / 与 GET /api/user/me/city-medals 字段集合完全一致）。
    user 不存在 → service.get_user_by_id 抛 ValueError → 翻译为 404
    （跟 L310-311 /{user_id}/power-curve 同 pattern）。
    """
    try:
        service.get_user_by_id(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return service.get_city_medals(db, user_id)
