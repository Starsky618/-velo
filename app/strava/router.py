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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.strava import service

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
    """
    url = service.generate_authorize_url(user_id)
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
        service.handle_callback(db, code, state)
    except ValueError as e:
        # 授权失败：显示错误页面
        # html.escape 防止错误消息中的特殊字符被当成 HTML 执行（XSS 防护）
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

    就像快递到了柜子里，菜鸟驿站发短信通知你。
    这个端点不需要 JWT（Strava 服务器直接 POST）。
    必须快速返回 200（Strava 要求 2 秒内响应），实际处理异步完成。

    FastAPI 自动将 JSON body 解析为 dict（同步模式兼容）。
    """
    service.handle_webhook_event(db, payload)

    # Strava 要求 Webhook 端点始终返回 200，无论内部处理是否成功
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
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 6.6 导入进度 ====================


@router.get("/import-progress")
def get_import_progress(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询 Strava 导入进度——前端显示进度条用。

    需要登录（请求头带 JWT）。
    """
    return service.get_import_progress(db, user_id)
