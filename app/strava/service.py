"""
Strava OAuth 业务逻辑层——"外交部的签证处"。

负责 Strava 授权的全部核心逻辑：
- 生成授权链接（用户点了就跳到 Strava 去登录授权）
- 处理授权回调（Strava 授权成功后把 token 存到我们的数据库）
- 查询绑定状态（用户有没有绑定 Strava）
- 自动刷新过期 token（access_token 过期时自动用 refresh_token 换新的）

整个 OAuth 流程可以类比为"办签证"：
1. generate_authorize_url：填签证申请表（生成授权链接）
2. handle_callback：大使馆批准签证、贴到护照上（把 token 写入数据库）
3. ensure_valid_token：签证过期了自动续签（刷新 access_token）

注意事项：
- state 参数用 JWT 签名，防止 CSRF 攻击（别人伪造回调请求）
- IntegrityError 捕获：一个 Strava 账号只能绑一个系统用户
- token 刷新失败时会清空所有 Strava 字段，用户需要重新绑定
"""

import html
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from redis import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.user.models import User

logger = logging.getLogger(__name__)

# JWT 算法——和 user/service.py 保持一致
JWT_ALGORITHM = "HS256"

# Strava OAuth 端点
# 这两个地址是 Strava 官方提供的，所有开发者都用同一套
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# token 刷新缓冲时间（5 分钟）
# 如果 token 还有不到 5 分钟过期，就提前刷新，避免请求到一半 token 过期
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)

# state 令牌有效期（10 分钟）
# 用户点击"绑定 Strava"后有 10 分钟完成授权，超时需要重新操作
STATE_EXPIRE_MINUTES = 10


def generate_authorize_url(user_id: int) -> str:
    """
    生成 Strava 授权链接。

    流程：
    1. 用 user_id 生成一个带签名的 state 令牌（10 分钟有效）
    2. 把 state 令牌、client_id、redirect_uri 等参数拼成完整的授权 URL
    3. 前端把用户导向这个 URL → 用户在 Strava 登录并授权 → Strava 带着 code 跳回我们的回调地址

    state 的作用就像"取号单"——你去银行办事先取号，办完后凭号确认是你。
    这里用 JWT 签名的 state 既能防伪造（CSRF），又能带上 user_id 信息。
    """
    # 前置检查：如果 Strava 配置未填，直接报错，避免生成无效的授权链接
    if not settings.STRAVA_CLIENT_ID:
        raise ValueError("Strava 集成未配置，请联系管理员")

    # 生成 state 令牌：JWT 里塞 user_id 和用途标识
    # purpose 字段用于验证时区分"这是 Strava OAuth 的 state"还是别的用途
    state_payload = {
        "sub": str(user_id),
        "purpose": "strava_oauth",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=STATE_EXPIRE_MINUTES),
    }
    state = jwt.encode(state_payload, settings.JWT_SECRET, algorithm=JWT_ALGORITHM)

    # 拼装 Strava 授权 URL
    # scope=read,activity:read 表示只请求读取权限（不修改用户的 Strava 数据）
    # response_type=code 表示用授权码模式（最标准的 OAuth2 流程）
    # 用 urlencode 确保 redirect_uri 等参数中的特殊字符被正确编码
    params = urlencode({
        "client_id": settings.STRAVA_CLIENT_ID,
        "redirect_uri": settings.STRAVA_REDIRECT_URI,
        "response_type": "code",
        "scope": "read,activity:read",
        "state": state,
    })
    url = f"{STRAVA_AUTHORIZE_URL}?{params}"

    logger.info("生成 Strava 授权链接 user_id=%d", user_id)
    return url


class InvalidStateError(Exception):
    """OAuth state 异常：已使用 / 过期 / 跨用户冲突等"""
    pass


class BoundByOtherUserError(Exception):
    """该 Strava 账号已被其他 VELO 账号绑定"""
    pass


def build_authorize_url(user_id: int, redis: Redis) -> str:
    """
    生成 Strava OAuth 授权 URL（v4 重构版）。

    设计要点：
    1. state 使用明文 nonce（24 字节随机），不套 JWT——
       因为 nonce 本身不可猜，加 JWT 是冗余的
    2. Redis 存储 {strava_state:{nonce}: user_id}，10 分钟 TTL
    3. callback 时用 GETDEL 原子取出并删除，保证一次性消费

    为什么这套组合能防 Login CSRF：
        攻击者拿到自己的 nonce 后，Redis 里 key 对应的是攻击者自己的 user_id，
        即使诱骗受害者点链接完成授权，Strava token 也会绑到攻击者账号（而不是受害者）
        —— 这样攻击者获得的就是自己的账号而已，没有受害者数据。

    Args:
        user_id: 当前登录用户的 ID
        redis: Redis 客户端（通常是 app.strava.client._redis）

    Returns:
        可直接跳转的 Strava 授权 URL
    """
    # 24 字节随机 = 32 个 urlsafe base64 字符，碰撞概率 2^-192，安全余量足够
    nonce = secrets.token_urlsafe(24)

    # 10 分钟 TTL：用户授权流程最长一般 5 分钟；给 2 倍余量防慢网速
    redis.setex(f"strava_state:{nonce}", 600, str(user_id))

    # 注意：state 直接用 nonce 明文，不套 JWT
    return (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={settings.STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={settings.STRAVA_REDIRECT_URI}"
        f"&approval_prompt=auto"
        f"&scope=read,activity:read"
        f"&state={nonce}"
    )


def verify_state_and_consume(state: str, redis: Redis) -> int:
    """
    验证 state 并一次性消费。

    核心机制：Redis GETDEL 原子取出并删除，保证重放必失败。

    Args:
        state: Strava 回调带回的 state 参数（即 nonce 明文）
        redis: Redis 客户端

    Returns:
        发起授权的 user_id

    Raises:
        InvalidStateError: state 不存在（过期 / 已使用 / 伪造）
    """
    # Redis 7+ 原生 getdel：读取并删除是原子操作
    stored = redis.getdel(f"strava_state:{state}")

    if stored is None:
        raise InvalidStateError("state 已使用或过期")

    # redis-py 默认 decode_responses=False 时返 bytes
    if isinstance(stored, bytes):
        stored = stored.decode()

    try:
        return int(stored)
    except ValueError:
        raise InvalidStateError(f"state 对应的 user_id 格式异常: {stored}")


def _cleanup_old_athlete_activities(db: Session, user_id: int, old_athlete_id: int) -> int:
    """
    换号场景：把旧 athlete 还在导入中的活动标为 failed。

    为什么这么做：
        用户从 Strava 账号 A 切到账号 B 时，调度器之前为账号 A 创建的
        "importing 骨架活动"（只有元信息、还没拉轨迹的占位）失去意义——
        再让调度器用账号 B 的 token 去拉账号 A 的活动，会 403 / 404。
        提前把它们置 failed 能避免生产环境一堆无意义的失败日志。

    注意：不删除历史已 completed 活动（用户可能还想看）。

    Args:
        db: SQLAlchemy session（调用方负责 commit）
        user_id: 当前用户 id
        old_athlete_id: 旧的 Strava athlete_id（传入用于日志）

    Returns:
        被标 failed 的活动数量
    """
    from app.activity.models import Activity  # 避免循环 import

    count = (
        db.query(Activity)
        .filter(
            Activity.user_id == user_id,
            Activity.data_source == "strava",
            Activity.status == "importing",  # Strava 活动的中间状态
        )
        .update(
            {
                Activity.status: "failed",
                Activity.error_message: f"换号绑定：旧 athlete {old_athlete_id} 的导入中断",
            },
            synchronize_session=False,
        )
    )
    logger.info(
        "换号清理 user_id=%d old_athlete_id=%d 清了 %d 条 importing 活动",
        user_id, old_athlete_id, count,
    )
    return count


def handle_callback(db: Session, code: str, state: str, redis: Redis) -> dict:
    """
    Strava OAuth 回调处理。v4 重构要点：

    1. state 一次性消费（verify_state_and_consume）
    2. user 行锁（避免并发 callback 竞态）
    3. **UNIQUE 冲突检测必须在清理旧活动之前**（顺序不能换，否则会误伤自家数据）
    4. 换号清理（_cleanup_old_athlete_activities）
    5. StravaImport 防重复：覆盖 active + paused 两种未完成态

    Args:
        db: SQLAlchemy session
        code: Strava 回调带回的 authorization_code
        state: 本次授权的 state（nonce）
        redis: Redis 客户端

    Returns:
        {"bound": True, "athlete_id": int}

    Raises:
        InvalidStateError: state 失效
        ValueError: 用户不存在 / Strava 响应异常
        BoundByOtherUserError: 该 athlete 已被他人绑定
    """
    from app.strava.models import StravaImport

    # ---- Step 1：一次性消费 state ----
    user_id = verify_state_and_consume(state, redis)

    # ---- Step 2：换 token（内联，不抽新函数——参考现有流程）----
    try:
        resp = httpx.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
    except httpx.HTTPError:
        logger.error("Strava token 请求网络错误 user_id=%d", user_id)
        raise ValueError("Strava 授权失败")

    if resp.status_code != 200:
        logger.error(
            "Strava token 请求失败 user_id=%d status=%d body=%s",
            user_id, resp.status_code, resp.text[:200],
        )
        raise ValueError("Strava 授权失败")

    try:
        data = resp.json()
    except Exception:
        raise ValueError("Strava 返回非 JSON 响应")

    athlete = data.get("athlete")
    if not athlete or "id" not in athlete:
        raise ValueError("Strava 返回数据缺少 athlete 字段")
    for key in ("access_token", "refresh_token", "expires_at"):
        if key not in data:
            raise ValueError(f"Strava 返回数据缺少 {key} 字段")

    new_athlete_id = athlete["id"]

    # ---- Step 3：user 行锁 + NoResultFound 兜底 ----
    # 为什么用 .first() 而不是 .one()：
    #   .one() 遇到用户不存在会抛 NoResultFound，前端收到 500；
    #   .first() + 显式 raise ValueError 更可控，前端收到 400
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .first()
    )
    if not user:
        raise ValueError(f"用户 {user_id} 不存在")

    # ---- Step 4：UNIQUE 冲突检测（必须在清理之前，顺序不可换）----
    # 如果该 Strava 账号已被其他 VELO 账号绑定，直接拒绝；
    # 不往下走，避免误清自家数据后再被 UNIQUE 挡下（造成数据损失）
    other = (
        db.query(User)
        .filter(
            User.strava_athlete_id == new_athlete_id,
            User.id != user_id,
        )
        .first()
    )
    if other:
        logger.warning(
            "Strava 账号占用 user_id=%d 试图绑定 athlete=%d 但被 user_id=%d 占用",
            user_id, new_athlete_id, other.id,
        )
        raise BoundByOtherUserError("该 Strava 账号已被其他 VELO 账号绑定")

    # ---- Step 5：换号时清理旧 athlete 的 importing 活动 ----
    if user.strava_athlete_id and user.strava_athlete_id != new_athlete_id:
        _cleanup_old_athlete_activities(db, user.id, user.strava_athlete_id)

    # ---- Step 6：写入新 token（expires_at 内联解析，不抽新函数）----
    user.strava_athlete_id = new_athlete_id
    user.strava_access_token = data["access_token"]
    user.strava_refresh_token = data["refresh_token"]
    user.strava_token_expires_at = datetime.fromtimestamp(
        data["expires_at"], tz=timezone.utc,
    )
    db.flush()

    # ---- Step 7：StravaImport 防重复（覆盖 active + paused 两种未完成态）----
    # 为什么检查 paused 而不只是 active：
    #   若上次导入因 token 失效被标 paused，新 callback 若只查 active
    #   会再建一条新 active 任务 → paused+active 并存，调度器混乱
    existing = (
        db.query(StravaImport)
        .filter(
            StravaImport.user_id == user_id,
            StravaImport.status.in_(["active", "paused"]),
        )
        .with_for_update()
        .first()
    )

    if existing:
        # 已有未完成任务 → 复用（若是 paused 重新置 active 让调度器接手）
        if existing.status == "paused":
            existing.status = "active"
            logger.info("复用并激活 paused 导入任务 user_id=%d import_id=%d", user_id, existing.id)
        else:
            logger.info("复用已有 active 导入任务 user_id=%d import_id=%d", user_id, existing.id)
    else:
        # 没有未完成任务 → 新建
        # strava_athlete_id 是 NOT NULL，必须带上
        db.add(StravaImport(
            user_id=user_id,
            strava_athlete_id=new_athlete_id,
            status="active",
        ))
        logger.info("创建新 Strava 导入任务 user_id=%d athlete_id=%d", user_id, new_athlete_id)

    db.commit()
    return {"bound": True, "athlete_id": new_athlete_id}


def get_strava_status(db: Session, user_id: int) -> dict:
    """
    查询用户的 Strava 绑定状态。

    前端用这个接口决定显示"绑定 Strava"还是"已绑定"。
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise ValueError("用户不存在")

    connected = user.strava_athlete_id is not None
    return {
        # 老字段保留——向后兼容现有调用方
        "connected": connected,
        "athlete_id": user.strava_athlete_id if connected else None,
        # 新增——task-7.10 前端要用 res.bound 做判断
        "bound": connected,
    }


def ensure_valid_token(db: Session, user: User, force: bool = False) -> str:
    """
    确保用户的 Strava access_token 有效，过期则自动刷新。

    所有需要调 Strava API 的函数都先调这个，确保手里的通行证没过期。
    StravaClient 和 service.py 都会调用此函数。

    参数：
        force: 强制刷新 token，即使 expires_at 还没到期也刷新。
               用于 Strava 返回 401 时——说明 token 在服务端已失效，
               但我们记录的过期时间还没到（Strava 可以提前作废 token）。

    就像出国前检查签证：
    - 还没过期 → 直接走
    - 快过期了 → 去大使馆续签（用 refresh_token 换新的 access_token）
    - 续签被拒（refresh_token 也失效了）→ 得重新办签证（用户需要重新授权）
    """
    now = datetime.now(timezone.utc)

    # 检查是否过期（留 5 分钟缓冲，避免"刚好在请求途中过期"）
    # force=True 时跳过此判断，直接走刷新逻辑
    if (
        not force
        and user.strava_token_expires_at is not None
        and user.strava_token_expires_at > now + TOKEN_REFRESH_BUFFER
    ):
        # 未过期，直接返回
        return user.strava_access_token

    # 过期了，用 refresh_token 换新 token
    logger.info("Strava token 过期，开始刷新 user_id=%d", user.id)

    try:
        resp = httpx.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": user.strava_refresh_token,
            },
            timeout=10,
        )
    except httpx.HTTPError:
        logger.error("Strava token 刷新网络错误 user_id=%d", user.id)
        raise ValueError("Strava 授权已失效，请重新绑定")

    # 401 表示 refresh_token 也失效了（用户在 Strava 端撤销了授权）
    if resp.status_code == 401:
        logger.warning("Strava refresh_token 失效 user_id=%d", user.id)
        # 清空所有 Strava 字段，让用户重新绑定
        user.strava_athlete_id = None
        user.strava_access_token = None
        user.strava_refresh_token = None
        user.strava_token_expires_at = None
        db.commit()
        raise ValueError("Strava 授权已失效，请重新绑定")

    if resp.status_code != 200:
        logger.error(
            "Strava token 刷新失败 user_id=%d status=%d", user.id, resp.status_code
        )
        raise ValueError("Strava 授权已失效，请重新绑定")

    try:
        data = resp.json()
    except Exception:
        logger.error("Strava 刷新返回非 JSON 响应 user_id=%d body=%s", user.id, resp.text[:200])
        raise ValueError("Strava 授权已失效，请重新绑定")

    # 更新数据库中的 token 信息
    # 防御性访问：缺少关键字段时给出明确错误
    for key in ("access_token", "refresh_token", "expires_at"):
        if key not in data:
            logger.error("Strava 刷新响应缺少 %s user_id=%d", key, user.id)
            raise ValueError("Strava 授权已失效，请重新绑定")

    user.strava_access_token = data["access_token"]
    user.strava_refresh_token = data["refresh_token"]
    user.strava_token_expires_at = datetime.fromtimestamp(
        data["expires_at"], tz=timezone.utc
    )
    db.commit()

    logger.info("Strava token 刷新成功 user_id=%d", user.id)
    return user.strava_access_token


# ==================== 6.5 Webhook + 手动同步 ====================


def handle_webhook_event(db: Session, payload: dict) -> None:
    """
    处理 Strava Webhook 事件——Strava 主动告诉我们"有新活动了"。

    好比快递通知：你订了个包裹，快递到了柜子里，菜鸟驿站发短信通知你去取。
    Strava 就是菜鸟驿站，这个函数就是处理短信的逻辑。

    事件类型：
    - activity create/update → 入 RQ 队列拉详情+轨迹
    - activity delete → 删除对应 Activity
    - athlete delete → 用户撤销授权，清除 Strava token
    """
    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")
    object_id = payload.get("object_id")
    owner_id = payload.get("owner_id")

    logger.info(
        "收到 Strava Webhook object_type=%s aspect_type=%s object_id=%s owner_id=%s",
        object_type, aspect_type, object_id, owner_id,
    )

    # 忽略非活动事件（athlete update 等）
    if object_type == "athlete":
        if aspect_type == "delete":
            # 用户在 Strava 端撤销了授权
            _handle_athlete_deauthorize(db, owner_id)
        return

    if object_type != "activity":
        return

    # 找到对应的系统用户
    user = db.query(User).filter_by(strava_athlete_id=owner_id).first()
    if user is None:
        logger.info("Webhook 找不到用户 owner_id=%s，忽略", owner_id)
        return

    if aspect_type == "delete":
        # 用户在 Strava 上删了这条活动
        # 安全校验：确认这条 Activity 属于 owner_id 对应的用户，防止伪造 delete 事件
        from app.activity.models import Activity
        activity = db.query(Activity).filter_by(
            strava_activity_id=object_id, user_id=user.id
        ).first()
        if activity:
            db.delete(activity)
            db.commit()
            logger.info("删除 Strava 活动 strava_id=%s activity_id=%d", object_id, activity.id)
        return

    if aspect_type in ("create", "update"):
        # 新活动或更新 → 创建 importing 骨架（由调度器异步处理详情+轨迹）
        _create_importing_activity(db, user, object_id)


def _handle_athlete_deauthorize(db: Session, owner_id) -> None:
    """
    用户在 Strava 端撤销授权——清空 token + 暂停导入任务。

    不清理 importing 状态的 Activity（保留骨架让用户看到不完整的记录），
    但暂停 strava_imports 任务，防止调度器继续尝试（token 已失效）。
    """
    user = db.query(User).filter_by(strava_athlete_id=owner_id).first()
    if user is None:
        return

    logger.warning("用户撤销 Strava 授权 user_id=%d owner_id=%s", user.id, owner_id)

    # 暂停该用户的所有 active 导入任务
    from app.strava.models import StravaImport
    active_imports = (
        db.query(StravaImport)
        .filter_by(user_id=user.id, status="active")
        .all()
    )
    for imp in active_imports:
        imp.status = "paused"

    # 清空 Strava 字段
    user.strava_athlete_id = None
    user.strava_access_token = None
    user.strava_refresh_token = None
    user.strava_token_expires_at = None
    db.commit()


def _create_importing_activity(db: Session, user: User, strava_activity_id) -> bool:
    """
    为单条 Strava 活动创建 importing 状态的骨架记录。

    实际的详情+轨迹拉取由调度器（import_scheduler）周期性处理，
    这里只创建骨架——让用户尽快在列表中看到"有新活动在导入"。

    去重：先查 strava_activity_id 是否已存在，已存在则跳过。
    返回 True 表示创建了新活动，False 表示跳过。
    """
    from app.activity.models import Activity

    # 去重检查
    existing = db.query(Activity).filter_by(strava_activity_id=strava_activity_id).first()
    if existing:
        logger.info("跳过已存在的 Strava 活动 strava_id=%s", strava_activity_id)
        return False

    # 创建骨架 Activity（详情由调度器或 Worker 异步填充）
    activity = Activity(
        user_id=user.id,
        status="importing",
        file_url=None,
        data_source="strava",
        strava_activity_id=strava_activity_id,
    )

    try:
        db.add(activity)
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("跳过已存在的 Strava 活动（并发） strava_id=%s", strava_activity_id)
        return False

    logger.info(
        "Webhook 创建 importing 活动 strava_id=%s activity_id=%d user_id=%d",
        strava_activity_id, activity.id, user.id,
    )
    return True


def handle_manual_sync(db: Session, user_id: int) -> dict:
    """
    手动同步——用户点"同步 Strava"按钮时调用。

    每次调用消耗 1 次 Strava API 额度（全 App 共享每天 1000 次），
    所以加了 5 分钟冷却时间，防止用户疯狂点同步按钮烧光额度。

    拉取最近 30 条活动，新的入库，已有的跳过。
    返回新发现了几条。
    """
    from app.strava.client import StravaClient
    from app.activity.models import Activity
    from redis import Redis

    user = db.query(User).filter_by(id=user_id).first()
    if not user or user.strava_athlete_id is None:
        raise ValueError("未绑定 Strava")

    # 冷却时间检查：每个用户 5 分钟内只能同步一次，防止烧光 API 额度
    # Redis SET NX + EX 原子操作：键不存在时设置成功（首次同步），键存在时设置失败（冷却中）
    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        cooldown_key = f"strava:sync_cooldown:{user_id}"
        if not redis_conn.set(cooldown_key, "1", ex=300, nx=True):
            raise ValueError("同步太频繁，请 5 分钟后再试")
    except ValueError:
        raise  # 冷却时间错误正常抛出
    except Exception:
        # Redis 不可用时降级放行（限流不应阻断功能）
        logger.warning("Redis 不可用，同步冷却检查跳过")

    client = StravaClient(db, user)
    activities = client.get_athlete_activities(per_page=30)

    new_count = 0
    for act in activities:
        strava_id = act.get("id")
        if strava_id is None:
            continue

        created = _create_importing_activity(db, user, strava_id)
        if created:
            # 补充骨架字段（列表 API 返回了名称和距离）
            activity = db.query(Activity).filter_by(strava_activity_id=strava_id).first()
            if activity:
                activity.title = act.get("name")
                activity.distance = act.get("distance")
                start_date_str = act.get("start_date")
                if start_date_str:
                    try:
                        activity.started_at = datetime.fromisoformat(
                            start_date_str.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass
                db.commit()
            new_count += 1

    logger.info("手动同步完成 user_id=%d new=%d", user_id, new_count)
    return {
        "new_activities": new_count,
        "message": f"发现 {new_count} 条新骑行，正在导入" if new_count > 0
                   else "没有新的骑行活动",
    }


# ==================== 6.6 导入进度 ====================


def get_import_progress(db: Session, user_id: int) -> dict:
    """
    查询当前用户的 Strava 导入进度。

    前端用这个接口显示"正在导入...已完成 120/500"的进度条。
    """
    from app.strava.models import StravaImport

    import_task = (
        db.query(StravaImport)
        .filter_by(user_id=user_id)
        .order_by(StravaImport.created_at.desc())
        .first()
    )

    if import_task is None:
        return {"status": "none", "message": "未开始导入"}

    total = import_task.total_activities or 0
    tier1 = import_task.tier1_completed or 0
    tier2 = import_task.tier2_completed or 0
    skipped = import_task.tier2_skipped or 0

    # 计算百分比：第一层完成算 30%，第二层按比例算剩余 70%
    if total == 0:
        percent = 0
    else:
        tier1_pct = min(30, int(tier1 / total * 30)) if total > 0 else 0
        tier2_done = tier2 + skipped
        tier2_pct = int(tier2_done / total * 70) if total > 0 else 0
        percent = tier1_pct + tier2_pct

    # 构造人类可读的进度消息
    if import_task.status == "completed":
        message = f"导入完成，共 {tier2} 条骑行"
    elif import_task.status == "paused":
        message = "导入暂停，请重新同步"
    elif tier1 < total or total == 0:
        message = f"正在扫描活动列表，已发现 {tier1} 条"
    else:
        message = f"正在导入详情+轨迹，已完成 {tier2}/{total}"

    return {
        "status": import_task.status,
        "total_activities": total,
        "tier1_completed": tier1,
        "tier2_completed": tier2,
        "tier2_skipped": skipped,
        "percent": min(percent, 100),
        "message": message,
    }
