"""
Strava Token 管理子模块——"签证续签 + 查状态"。

干啥用：
    - 查用户有没有绑定 Strava（前端决定显示"绑定"还是"已绑定"）
    - access_token 过期前自动用 refresh_token 换新的
    - refresh_token 也失效时清空所有 Strava 字段，让用户重新绑

类比：
    签证管理处。出国前自动检查签证有效期：
    - 还没过期 → 直接走
    - 快过期了 → 去大使馆续签（refresh）
    - 续签被拒（refresh_token 也失效）→ 让用户重新办签证

操作注意：
    - **行锁 + populate_existing 双护栏**：并发请求同时刷 token 会让 refresh_token 互相顶掉
      → 用户被踢出。SELECT FOR UPDATE 拿锁 + populate_existing 强制刷新 identity map
      避免拿到 stale 字段（v5 task-0.2 codex 异源审抓的 Important / CLAUDE.md 陷阱 #12）
    - **未绑定明确化**：refresh_token IS NULL → 抛 UnboundStravaError 让 caller 转 400
      不要让函数继续走到 refresh API 误报底层错误
    - **401 分支同步 pause 导入任务**：先 pause 再清 token（顺序保证）

数据流：
    入：db + user_id (+ force flag 强制刷新)
    出：(User, access_token) 元组——返回行锁后最新 user 实例避免 caller 用 stale 数据
    边界：直接读写 user 表 + 401 时同步 update strava_imports（同事务）

不允许：
    - import service_oauth / service_sync（保持单向依赖）
    - 入口不再加新参数（保持 caller 调用契约稳定）

v5 task-strava-split-001：从 service.py 906 行拆出（commit TBD）。
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.strava.exceptions import UnboundStravaError
from app.user.models import User

logger = logging.getLogger(__name__)

# Strava OAuth token 端点
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

# token 刷新缓冲时间（5 分钟）
# 如果 token 还有不到 5 分钟过期，就提前刷新，避免请求到一半 token 过期
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


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


def ensure_valid_token(
    db: Session, user_id: int, force: bool = False
) -> tuple[User, str]:
    """
    确保用户的 Strava access_token 有效，过期则自动刷新。

    所有需要调 Strava API 的函数都先调这个，确保手里的通行证没过期。
    StravaClient 和 service.py 都会调用此函数。

    参数：
        user_id: 用户 id（不传 user 对象，函数内部行锁查最新行）
        force: 强制刷新 token，即使 expires_at 还没到期也刷新。
               用于 Strava 返回 401 时——说明 token 在服务端已失效，
               但我们记录的过期时间还没到（Strava 可以提前作废 token）。

    返回：
        (User, access_token) 元组——User 是行锁后的最新实例，调用方应用
        它替换自己持有的旧 user 引用，避免后续读到过时字段。

    就像出国前检查签证：
    - 还没过期 → 直接走
    - 快过期了 → 去大使馆续签（用 refresh_token 换新的 access_token）
    - 续签被拒（refresh_token 也失效了）→ 得重新办签证（用户需要重新授权)

    v4 改动：
    - 入口加行锁（SELECT FOR UPDATE），防并发请求同时进到刷新逻辑
      导致两个 Python 进程都向 Strava 发 refresh 请求（refresh_token
      使用后会变新，两者会互相顶掉对方的新 token → 用户账户被踢出）
    - 401 分支同步 pause 该用户的 active 导入任务（I7）

    v5 task-0.2 签名改造：
    - 入参 User 对象 → user_id：函数内部完整封装"行锁 + 查询"，调用方
      不必先 query user。打个比方：以前是"客户先去派出所拿户口本再交给我办事"，
      现在是"客户报身份证号即可，我自己去派出所拿最新户口本"。
    - 返回 str → tuple[User, str]：调用方拿到行锁后的 user 实例，
      避免在外部用过时 user 对象触发并发数据 drift。
    """
    # v4 I8：入口行锁——把 user 行锁住，避免并发刷 token 竞态
    # 注意：必须在事务内才能锁住；caller（StravaClient._request）已在隐式事务内
    #
    # v5 task-0.2 codex 异源审抓到的 Important：行锁 SQL 拿到了，但 SQLAlchemy
    # 在同一 session 内会优先返回 identity map 里的旧 ORM 实例（缓存），字段
    # 值不会被锁后从 DB 读到的最新值覆盖。结果：caller 持有的 self.user 拿到的
    # 仍是 stale 字段（如 strava_token_expires_at），可能误判"未过期"返回旧
    # access_token——task-0.2 改造的"返回锁后最新 user"契约失效。
    # 加 .populate_existing() 强制刷新 identity map 里已有对象的 attributes，
    # 让 query 返回的对象字段一定是 DB 里加锁后看到的最新值。
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if user is None:
        raise ValueError(f"user_id={user_id} 不存在")

    # v5 task-0.3：未绑定路径明确化——避免函数继续走到 refresh API 误报
    # "NULL refresh_token" 之类底层错误。caller 应 catch UnboundStravaError 转
    # 400 给前端，提示用户先去绑定。
    # 注意用 `is None` 不用 truthiness：空串语义虽等价未绑定但项目约定 NULL 是
    # 未绑定的唯一标准（陷阱清单 #1），这里保守显式比较。
    if user.strava_refresh_token is None:
        raise UnboundStravaError(f"user_id={user_id} 未绑定 Strava")

    now = datetime.now(timezone.utc)

    # 检查是否过期（留 5 分钟缓冲，避免"刚好在请求途中过期"）
    # force=True 时跳过此判断，直接走刷新逻辑
    if (
        not force
        and user.strava_token_expires_at is not None
        and user.strava_token_expires_at > now + TOKEN_REFRESH_BUFFER
    ):
        # 未过期，直接返回
        return user, user.strava_access_token

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

        # v4 I7：先把该用户 active 导入任务置 paused，再清 token
        # 顺序理由：先 pause 让 scheduler 不再继续空跑调它的 API（空跑会持续失败）；
        # 清 token 放后面——先标 paused 保证即使下面清 token 失败，scheduler 也已被喊停
        from app.strava.models import StravaImport
        paused_count = (
            db.query(StravaImport)
            .filter(
                StravaImport.user_id == user.id,
                StravaImport.status == "active",
            )
            .update({StravaImport.status: "paused"}, synchronize_session=False)
        )
        if paused_count > 0:
            logger.info(
                "token 失效 自动 pause %d 个 active 导入任务 user_id=%d",
                paused_count, user.id,
            )

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
    return user, user.strava_access_token
