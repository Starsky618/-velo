"""
Strava 集成的 API 路由——"外交部的前台"。

负责接收前端和 Strava 发来的请求，转交给 service 层处理。
自己不做任何业务逻辑，只做三件事：接请求、转交、回结果。

三个端点各有特点：
- /authorize：需要 JWT 登录，返回 JSON（给小程序用）
- /callback：不需要 JWT（靠 state 识别用户），返回 HTML（浏览器直接看）
- /status：需要 JWT 登录，返回 JSON（给小程序用）

注意事项：
- callback 端点是 Strava 服务器直接重定向过来的，用户看到的是浏览器页面，
  所以返回 HTML 而不是 JSON
- 所有路由函数用 def（同步），禁止 async def
"""

import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.strava import service
from app.strava.client import _redis
from app.strava.exceptions import UnboundStravaError
from app.strava.service import (
    BoundByOtherUserError,
    InvalidStateError,
    handle_callback,
)

logger = logging.getLogger(__name__)

# 创建路由器，所有 Strava 相关接口都挂在 /api/strava 下
router = APIRouter(prefix="/api/strava", tags=["strava"])

# ---- 授权成功/失败的 HTML 模板 ----
# 用户在浏览器里完成 Strava 授权后会看到这个页面
# 极简设计：一句话告诉用户结果，不需要复杂界面
_SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权成功</title>
<style>body{display:flex;justify-content:center;align-items:center;min-height:100vh;
font-family:-apple-system,sans-serif;background:#f5f5f5;margin:0}
.card{text-align:center;padding:40px;background:#fff;border-radius:12px;
box-shadow:0 2px 8px rgba(0,0,0,0.1)}
h1{color:#2d8cf0;font-size:24px}p{color:#666;margin-top:12px}</style>
</head>
<body><div class="card"><h1>✓ 授权成功</h1><p>请返回小程序继续使用</p></div></body>
</html>
"""

_ERROR_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权失败</title>
<style>body{{display:flex;justify-content:center;align-items:center;min-height:100vh;
font-family:-apple-system,sans-serif;background:#f5f5f5;margin:0}}
.card{{text-align:center;padding:40px;background:#fff;border-radius:12px;
box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
h1{{color:#e74c3c;font-size:24px}}p{{color:#666;margin-top:12px}}</style>
</head>
<body><div class="card"><h1>✗ 授权失败</h1><p>{message}</p></div></body>
</html>
"""


@router.get("/authorize")
def get_authorize_url(user_id: int = Depends(get_current_user)):
    """
    获取 Strava 授权链接。

    前端调这个接口拿到一个 URL，然后用浏览器打开它，
    用户在 Strava 登录授权后，Strava 会跳回我们的 /callback。

    需要登录（请求头带 JWT）。

    v4 重构：state 改为 Redis 存储的一次性 nonce（见 service.build_authorize_url）。
    """
    url = service.build_authorize_url(user_id, _redis)
    return {"authorize_url": url}


@router.get("/callback", response_class=HTMLResponse)
def strava_callback(
    code: str = Query(...),
    state: str = Query(...),
    scope: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """
    Strava 授权回调——Strava 授权成功后会把用户重定向到这个地址。

    这个端点不需要 JWT 登录，因为用户是从浏览器跳过来的（不是从小程序发请求），
    身份识别靠 state 参数里的 JWT 签名。

    返回 HTML 页面而不是 JSON，因为用户在浏览器里直接看到这个页面。
    """
    try:
        handle_callback(db, code, state, _redis)
    except InvalidStateError as e:
        logger.warning("OAuth state 验证失败: %s", e)
        return HTMLResponse(
            content=_ERROR_HTML_TEMPLATE.format(message=html.escape(str(e))),
            status_code=400,
        )
    except BoundByOtherUserError as e:
        logger.warning("Strava 账号已被占用: %s", e)
        return HTMLResponse(
            content=_ERROR_HTML_TEMPLATE.format(message=html.escape(str(e))),
            status_code=409,
        )
    except ValueError as e:
        # 授权失败：显示错误页面
        # html.escape 防止错误消息中的特殊字符被当成 HTML 执行（XSS 防护）
        logger.error("handle_callback ValueError: %s", e)
        return HTMLResponse(
            content=_ERROR_HTML_TEMPLATE.format(message=html.escape(str(e))),
            status_code=400,
        )

    # 授权成功：显示成功页面
    return HTMLResponse(content=_SUCCESS_HTML)


@router.get("/status")
def get_strava_status(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询当前用户的 Strava 绑定状态。

    前端用这个接口判断显示"绑定 Strava"按钮还是"已绑定"标识。
    需要登录（请求头带 JWT）。
    """
    return service.get_strava_status(db, user_id)


# ==================== 6.5 Webhook ====================


@router.get("/webhook")
def webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    Webhook 订阅验证——Strava 注册 Webhook 时会先发一个 GET 请求确认。

    就像快递柜验证手机号：你注册取件码时，系统先给你发一条验证短信，
    你回复收到的验证码证明"这个号是我的"。

    这个端点只在注册 Webhook 时被调用一次，之后不再调用。
    不需要 JWT 登录（Strava 服务器直接访问）。
    """
    if hub_mode != "subscribe" or hub_verify_token != settings.STRAVA_WEBHOOK_VERIFY_TOKEN:
        return JSONResponse(status_code=403, content={"error": "验证失败"})

    return {"hub.challenge": hub_challenge}


@router.post("/webhook")
def webhook_receive(
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    Webhook 事件接收——Strava 有新活动时主动推送到这里。

    v4 加固：用 payload.subscription_id 校验来源真实性。
    Strava 不提供 HMAC 签名（官方文档已确认），所以靠两点联合防伪：
    1. subscription_id：初次订阅时 Strava 返回的唯一 id（伪造者不知道）
    2. HTTPS：Caddy 强制 TLS，传输层防中间人

    为什么不用 IP 白名单：
        Strava 官方不承诺 Webhook 发送方 IP 稳定，维护 IP 表会误杀合法回调。
    为什么不用自定义 header 密钥：
        Strava 不支持在 Webhook 里加自定义 header。

    状态码约定：
    - 未配置 SUBSCRIPTION_ID: 503（系统未就绪，应由运维修 env）
    - subscription_id 不匹配: 403（伪造，拒收）
    - 正常: 200（Strava 要求 2 秒内响应，业务处理走 service 内部队列）
    """
    # ---- 第 1 道门：配置兜底 ----
    # getattr 兜底防止 AttributeError（万一未来 Settings 没声明这字段）
    expected_sub_id_str = getattr(settings, "STRAVA_WEBHOOK_SUBSCRIPTION_ID", "")
    if not expected_sub_id_str:
        # 注意：判空用 `not`，因为环境变量默认值是 "" 空串——空串是合法未配置态
        logger.error("Webhook 未配置 STRAVA_WEBHOOK_SUBSCRIPTION_ID")
        raise HTTPException(status_code=503, detail="Webhook 订阅未配置")

    try:
        expected_sub_id = int(expected_sub_id_str)
    except ValueError:
        # 配置了但格式不对（比如被填了非数字）——同样视为未配置
        logger.error(
            "STRAVA_WEBHOOK_SUBSCRIPTION_ID 格式非法: %r", expected_sub_id_str
        )
        raise HTTPException(status_code=503, detail="Webhook 订阅配置格式错误")

    # ---- 第 2 道门：payload 校验 ----
    incoming_sub_id = payload.get("subscription_id")
    if incoming_sub_id != expected_sub_id:
        logger.warning(
            "Webhook subscription_id 不匹配: 收到=%r 期望=%d",
            incoming_sub_id, expected_sub_id,
        )
        raise HTTPException(status_code=403, detail="Forbidden")

    # ---- 真实事件：走原有处理逻辑 ----
    service.handle_webhook_event(db, payload)

    # Strava 要求 Webhook 端点始终返回 200
    return {"status": "ok"}


# ==================== 6.5 手动同步 ====================


@router.post("/sync")
def manual_sync(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    手动同步 Strava 骑行——用户点"同步"按钮时调用。

    拉取最近 30 条活动，新的入库、旧的跳过。
    需要登录（请求头带 JWT）。
    """
    try:
        return service.handle_manual_sync(db, user_id)
    except UnboundStravaError:
        # v5 task-0.3：未绑定 Strava 翻译成 400 + 友好提示，
        # 避免底层"NULL refresh_token"错误透传给前端
        raise HTTPException(status_code=400, detail="未绑定 Strava 账号，请先去设置页绑定")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 6.6 导入进度 ====================


@router.get("/import-progress")
def get_import_progress(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询 Strava 导入进度——前端显示进度条用。

    限速：1 秒 1 次/用户。
    理由：前端正常轮询是 3s 一次，1s 限速只挡住误开发或恶意刷屏，
    正常业务完全在阈值内。触发返 429。

    Redis 不可用时：降级放行（限速不应阻断核心功能）。

    需要登录（请求头带 JWT）。
    """
    # ---- Redis 限速（1s/user）----
    # 用 SET NX + EX 原子操作：key 不存在时设置成功（放行），已存在则失败（限速）
    try:
        rl_key = f"rl:imp-prog:{user_id}"
        allowed = _redis.set(rl_key, "1", ex=1, nx=True)
        if not allowed:
            raise HTTPException(status_code=429, detail="请求过于频繁，请 1 秒后再试")
    except HTTPException:
        raise  # 限流触发正常抛
    except Exception:
        # Redis 不可用 → 降级放行（日志记录即可）
        logger.warning("Redis 限速失败，放行 user_id=%d", user_id)

    return service.get_import_progress(db, user_id)
