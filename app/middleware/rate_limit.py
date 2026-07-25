"""
限流工具模块——"小区门口的保安"。

干啥用：
    给 API 端点加"同一个用户/IP 在 N 秒内最多 M 次"的访问门槛。
    超过就拦下来返 429，挡住脚本撞码 / 刷上传 / 暴力破解 OAuth state。

类比：
    小区门禁。同一张脸 5 分钟来 100 次必拦下，让保安挡在电梯口（API 大门）外。

操作注意（关键设计）：
    - **抽象层稳定**：调用方只用 check_rate_limit_by_user / check_rate_limit_by_ip 两个公开函数，
      未来内部实现从 Redis fixed window 换成 token bucket / slowapi 时调用方 0 改动
      （architect 信条 9 骨架终态 + memory feedback_future_proof_three_layer_eval）
    - **Redis 不可用降级放行**：限流是防御机制不是核心业务，Redis 挂了不应阻断登录/上传
      （沿用 app/strava/router.py:275 import-progress 的成熟 pattern）
    - **飞书告警**：每天首次触发推一条，重复不刷（复用 app/monitor/processing_health.py pattern）
    - **IP 识别走 X-Forwarded-For**：Caddy/nginx 反代后 request.client.host = 127.0.0.1 会让所有
      真实攻击者共享同一 key，限流失效——必须读反代填的 X-Forwarded-For 才是真客户端 IP

数据流：
    入：user_id 或 Request 对象 + 限流配置（key_prefix / limit / window_sec）
    中：拼 Redis key → INCR 计数 → 首次 EXPIRE 设窗口 → 比阈值
    出：超阈值抛 HTTPException(429) / 未超返 None

新端点接入方法：
    1. router 函数签名加 `request: Request` 参数（IP 限流必须 / user 限流可选）
    2. 函数体首行调：
       check_rate_limit_by_user(user_id, "<prefix>", limit=N, window_sec=M)
       或 check_rate_limit_by_ip(request, "<prefix>", limit=N, window_sec=M)
    3. key_prefix 用业务名（"login" / "upload" / "strava-callback"），不同端点别冲突
"""
import logging
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, Request

from app.config import settings
from app.queue import redis_conn

logger = logging.getLogger(__name__)


def check_rate_limit_by_user(
    user_id: int,
    key_prefix: str,
    limit: int,
    window_sec: int,
) -> None:
    """按 user_id 限流——已登录用户的高频接口用。

    参数：
        user_id: 当前登录用户 ID（已过 JWT 验证，由 Depends(get_current_user) 注入）
        key_prefix: Redis key 命名前缀（如 "upload"）—— 不同端点用不同前缀避免互相干扰
        limit: 窗口内最多请求次数
        window_sec: 窗口长度（秒）

    异常：
        HTTPException(429): 超阈值

    Redis 不可用：放行 + 记 warning（沿用 import-progress pattern，限流不阻断核心功能）
    """
    key = f"rl:{key_prefix}:u:{user_id}"
    _check_or_raise(key, limit, window_sec)


def check_rate_limit_by_ip(
    request: Request,
    key_prefix: str,
    limit: int,
    window_sec: int,
) -> None:
    """按 IP 限流——未登录端点（login / oauth callback）必用。

    为什么不用 request.client.host：
        反向代理（Caddy / nginx）后 client.host 是反代节点 IP（127.0.0.1），
        所有真实攻击者共用同一个 key → 限流形同虚设。
        X-Forwarded-For 是反代填的真实客户端 IP，是正确做法。

    参数：
        request: FastAPI Request 对象（端点函数签名加 `request: Request` 才能拿到）
        key_prefix: Redis key 命名前缀
        limit / window_sec: 同上

    异常：
        HTTPException(429): 超阈值
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # X-Forwarded-For 格式：client_ip, proxy1_ip, proxy2_ip — 取第一个（最原始的客户端 IP）
        ip = forwarded.split(",")[0].strip()
    else:
        # 没经过反代时（本地直连 / dev 环境）才走 client.host
        ip = request.client.host if request.client else "unknown"

    key = f"rl:{key_prefix}:ip:{ip}"
    _check_or_raise(key, limit, window_sec)


def _check_or_raise(key: str, limit: int, window_sec: int) -> None:
    """内部实现——INCR 计数 + EXPIRE 设窗口 + 超阈值抛 429。

    设计（Fixed window 算法）：
        - INCR + EXPIRE 是 O(1) + 原子的
        - 与 token bucket / sliding window 比缺点：窗口边界突发可达 2 倍 limit
        - 当前 100 用户量级攻防场景足够；未来若需平滑可替换内部实现（调用方不动）

    Redis 不可用降级：catch 所有非 HTTPException 异常 → logger.warning + 放行
        理由：限流是防御机制非核心业务，Redis 挂了不应阻断登录/上传等正常请求。
    """
    try:
        count = redis_conn.incr(key)
        # 首次创建 key 时设过期：INCR 创建的 key 默认无 TTL，必须主动 EXPIRE
        # 否则 key 永驻 Redis，第二次窗口内的请求都被算进去 → 限流误杀
        if count == 1:
            redis_conn.expire(key, window_sec)
        if count > limit:
            # 边界：刚好超过的那一刻推飞书告警（每天首次），重复触发不刷
            if count == limit + 1:
                _alert_feishu_throttled(key, count, limit, window_sec)
            raise HTTPException(
                status_code=429,
                detail="请求过于频繁，请稍后再试",
            )
    except HTTPException:
        raise  # 限流 429 正常透传
    except Exception as exc:
        # Redis 异常 / 网络问题 → 降级放行 + 记日志
        logger.warning(
            "rate limit check failed for key=%s, allowing: %s", key, exc
        )


def _alert_feishu_throttled(
    key: str, count: int, limit: int, window_sec: int
) -> None:
    """飞书告警（每天首次触发推一条，避免告警风暴）。

    设计：
        - 用 daily marker key（rl:alerted:YYYY-MM-DD:<key>）记录"今天该 key 是否告警过"
        - SET NX + EX 86400 原子操作，重复触发不再推
        - webhook 异常不阻断业务（catch 后 logger.error）—— 沿用 monitor/processing_health pattern
        - dev/CI 未配 FEISHU_BOT_WEBHOOK 跳过推送
    """
    if not settings.FEISHU_BOT_WEBHOOK:
        return  # dev / CI 没配 webhook，跳过

    try:
        # 每天首次告警标记（UTC 日期与 DB tz-aware 一致）
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        alerted_key = f"rl:alerted:{today}:{key}"
        # SET NX：只在 key 不存在时设置成功 / 已存在则失败
        first_time = redis_conn.set(alerted_key, "1", ex=86400, nx=True)
        if not first_time:
            return  # 今天已告警过，不重复推

        msg = (
            f"⚠️ velo 限流告警\n"
            f"key={key} 触发限流（{count}/{limit} per {window_sec}s）\n"
            f"今日首次触发，重复不再推送"
        )
        response = httpx.post(
            settings.FEISHU_BOT_WEBHOOK,
            json={"msg_type": "text", "content": {"text": msg}},
            timeout=5,
        )
        response.raise_for_status()
    except Exception as exc:
        # 飞书挂了不阻断限流本身（429 仍正常返）
        # HTTPStatusError 文本会包含带签名的 webhook URL，只记异常类型和状态码。
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error(
            "rate limit feishu alert failed key=%s error_type=%s status_code=%s",
            key,
            type(exc).__name__,
            status_code,
        )
