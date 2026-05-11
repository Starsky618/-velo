"""
Strava OAuth 流程子模块——"签证申请 + 批准"。

干啥用：
    用户点"绑定 Strava" → 生成授权链接 → Strava 回调 → 写 token 到 DB。

类比：
    OAuth 像"办签证"：
    1. build_authorize_url：填申请表（生成跳转 URL，附 state 防 CSRF）
    2. verify_state_and_consume：批文真伪核对（Redis GETDEL 一次性消费）
    3. handle_callback：大使馆贴签（换 token + 双层 scope 校验 + 写 DB）

操作注意：
    - state nonce 用 Redis 一次性，重放必失败
    - scope 双层校验（query string + token response）防篡改（2026-05-11 事故 / CLAUDE.md 陷阱 #20）
    - handle_callback 用 SELECT FOR UPDATE 行锁防并发竞态
    - 私有 _cleanup_old_athlete_activities 仅在换号场景由 handle_callback 内部调用

数据流：
    入：user_id（authorize 阶段）/ code + state + granted_scope（callback 阶段）
    出：跳转 URL（authorize）/ {bound, athlete_id}（callback）
    边界：直接读 settings + Redis + DB user/strava_import 表

不允许：
    - import service_token / service_sync（保持单向依赖）
    - 加新 OAuth provider（Strava 专属 / 别的 OAuth 走自己的子模块）

v5 task-strava-split-001：从 service.py 906 行拆出（commit TBD）。
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from redis import Redis
from sqlalchemy.orm import Session

from app.config import settings
from app.strava.exceptions import BoundByOtherUserError, InvalidStateError
from app.user.models import User

logger = logging.getLogger(__name__)

# JWT 算法——和 user/service.py 保持一致
JWT_ALGORITHM = "HS256"

# Strava OAuth 端点
# 这两个地址是 Strava 官方提供的，所有开发者都用同一套
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

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
    # scope=read,activity:read_all 表示请求读取权限，**含私密活动（Only You）+ privacy zone data**
    # 反例（**禁止改回**）：旧值 "activity:read"（不含 _all）会让 Strava API 默默过滤
    # 所有 visibility=Only You 活动 → 私密骑行永远同步不进来。
    # 重大事故实证：2026-05-11 用户私密活动同步事故 / 详 CLAUDE.md 陷阱清单 #20
    # response_type=code 表示用授权码模式（最标准的 OAuth2 流程）
    # 用 urlencode 确保 redirect_uri 等参数中的特殊字符被正确编码
    params = urlencode({
        "client_id": settings.STRAVA_CLIENT_ID,
        "redirect_uri": settings.STRAVA_REDIRECT_URI,
        "response_type": "code",
        "scope": "read,activity:read_all",
        "state": state,
    })
    url = f"{STRAVA_AUTHORIZE_URL}?{params}"

    logger.info("生成 Strava 授权链接 user_id=%d", user_id)
    return url


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
    # 24 字节随机 = 32 个 urlsafe base64 字符，碰撞概率 2^-192,安全余量足够
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
        # scope=read,activity:read_all：含私密活动（Only You）+ privacy zone data
        # 详 CLAUDE.md 陷阱清单 #20（2026-05-11 私密活动同步事故）
        f"&scope=read,activity:read_all"
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


def handle_callback(
    db: Session,
    code: str,
    state: str,
    redis: Redis,
    granted_scope: str = "",
) -> dict:
    """
    Strava OAuth 回调处理。v4 重构要点：

    1. state 一次性消费（verify_state_and_consume）
    2. scope 校验（必须含 activity:read_all，否则拒绝绑定 / 2026-05-11 加固）
    3. user 行锁（避免并发 callback 竞态）
    4. **UNIQUE 冲突检测必须在清理旧活动之前**（顺序不能换，否则会误伤自家数据）
    5. 换号清理（_cleanup_old_athlete_activities）
    6. StravaImport 防重复：覆盖 active + paused 两种未完成态

    Args:
        db: SQLAlchemy session
        code: Strava 回调带回的 authorization_code
        state: 本次授权的 state（nonce）
        redis: Redis 客户端
        granted_scope: Strava callback URL 带回的 `scope` 参数（逗号分隔字符串），
                       例如 "read,activity:read_all"。默认 ""（fail-secure：缺省视为
                       授权页用户取消勾选所有权限，必拒绝）。详 CLAUDE.md 陷阱清单 #20。

    Returns:
        {"bound": True, "athlete_id": int}

    Raises:
        InvalidStateError: state 失效
        InsufficientScopeError: granted_scope 缺少 activity:read_all（私密活动拉不到）
        ValueError: 用户不存在 / Strava 响应异常
        BoundByOtherUserError: 该 athlete 已被他人绑定
    """
    from app.strava.exceptions import InsufficientScopeError
    from app.strava.models import StravaImport

    # ---- Step 1：一次性消费 state ----
    user_id = verify_state_and_consume(state, redis)

    # ---- Step 1.5：scope 校验（fail-secure / 早拒绝 / 不换 token 不写 DB）----
    # Strava OAuth 授权页**允许用户手动取消勾选** activity:read_all 复选框。
    # 取消后 callback 返回的 scope 不含 activity:read_all → 私密活动永远拉不到。
    # 必须在换 token 之前拦截：避免持久化"半残绑定"状态让用户误以为绑定成功。
    granted_scopes = {s.strip() for s in granted_scope.split(",") if s.strip()}
    if "activity:read_all" not in granted_scopes:
        logger.warning(
            "Strava OAuth scope 不足 user_id=%d granted=%r 缺 activity:read_all",
            user_id, granted_scope,
        )
        raise InsufficientScopeError(
            "授权 scope 不足：缺少 activity:read_all 权限。"
            "请重新点击'绑定 Strava'，并在 Strava 授权页**保留所有权限勾选**"
            "（'View data about your private activities' 必须勾选）。"
        )

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

    # ---- Step 2.5：token response 二次校验 scope（防 callback query 篡改）----
    # 攻击场景：用户在 Strava 授权页取消勾选 read_all → Strava 跳回 callback URL（query 含
    # 真实 granted scope）→ 用户**手动修改** URL 加 "&scope=read,activity:read_all" → 我们
    # 第一道闸 Step 1.5 只看 query string 会被绕过。
    # 根本防御：Strava token exchange response 也含 `scope` 字段（**空格分隔**，granted 不是 requested），
    # 官方文档明确建议 "Apps should check which scopes a user has accepted."
    # 这里二次校验：token response 才是 Strava 真实表态，query string 不可信。
    # 详 CLAUDE.md 陷阱清单 #20 + 2026-05-11 事故 codex round-2 review。
    # 类型安全：Strava 返回畸形（key 存在但值为 null / 列表 / 缺失）时直接拒收
    # （codex round-3 抓：raw_scope.split 假设字符串会 None.split → 500 而非 clean 403）
    raw_scope = data.get("scope")
    if not isinstance(raw_scope, str) or not raw_scope:
        logger.warning(
            "Strava token response scope 字段畸形 user_id=%d type=%s value=%r",
            user_id, type(raw_scope).__name__, raw_scope,
        )
        raise InsufficientScopeError(
            "Strava 授权响应异常：缺少 scope 字段或格式错误。请重新点击'绑定 Strava'。"
        )
    response_scopes = {s for s in raw_scope.split(" ") if s}
    if "activity:read_all" not in response_scopes:
        logger.warning(
            "Strava token response scope 不足 user_id=%d response_scope=%r 缺 activity:read_all",
            user_id, raw_scope,
        )
        raise InsufficientScopeError(
            "Strava 返回的授权 scope 不足：缺少 activity:read_all 权限。"
            "请重新点击'绑定 Strava'，并在 Strava 授权页**保留所有权限勾选**"
            "（'View data about your private activities' 必须勾选）。"
        )

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
