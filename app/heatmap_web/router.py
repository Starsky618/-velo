from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.heatmap_web import service as heatmap_web
from app.user import service as user_service


router = APIRouter(tags=["heatmap-web"])
_STATIC_ROOT = Path(__file__).resolve().parent / "static"
_SESSION_COOKIE = "velo_heatmap_session"
_TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNgYGBgAAAA"
    "BQABeqhXUAAAAABJRU5ErkJggg=="
)


class HeatmapWebSessionRequest(BaseModel):
    target_user_id: int | None = Field(default=None, ge=1)


class HeatmapWebSessionResponse(BaseModel):
    url: str


def _session(request: Request) -> dict[str, int | str]:
    try:
        return heatmap_web.decode_session_token(request.cookies.get(_SESSION_COOKIE))
    except heatmap_web.HeatmapWebSessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _is_secure_cookie(request: Request) -> bool:
    # 生产由 Caddy 容器转发，Uvicorn 未必信任该容器 IP 的 X-Forwarded-Proto。
    # 正式入口一律 Secure；仅显式本机 HTTP QA 允许非 Secure cookie。
    return request.url.hostname not in {"127.0.0.1", "localhost"}


def _translate_web_error(exc: Exception) -> HTTPException:
    if isinstance(exc, heatmap_web.HeatmapWebSessionError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, heatmap_web.HeatmapWebUnavailable):
        return HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "1"})
    if isinstance(exc, user_service.HeatmapSnapshotChanged):
        return HTTPException(
            status_code=503,
            detail="热图数据正在更新，请稍后重试",
            headers={"Retry-After": "1"},
        )
    if isinstance(exc, user_service.InvalidHeatmapTile):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, heatmap_web.HeatmapTileNotCovered):
        return HTTPException(status_code=404, detail="热图瓦片不存在")
    return HTTPException(status_code=500, detail="热图服务暂时不可用")


@router.post(
    "/api/user/me/heatmap/web-session",
    response_model=HeatmapWebSessionResponse,
)
def create_heatmap_web_session(
    body: HeatmapWebSessionRequest,
    viewer_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bearer JWT 只用于换一次性票据，永远不进入 web-view URL。"""
    target_user_id = body.target_user_id or viewer_user_id
    try:
        user_service.get_user_by_id(db, target_user_id)
        ticket = heatmap_web.create_web_ticket(viewer_user_id, target_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="用户不存在") from exc
    except heatmap_web.HeatmapWebUnavailable as exc:
        raise _translate_web_error(exc) from exc
    return {"url": f"/heatmap/session?{urlencode({'ticket': ticket})}"}


@router.get("/heatmap/session")
def start_heatmap_web_session(request: Request, ticket: str = Query(min_length=20, max_length=128)):
    try:
        identity = heatmap_web.consume_web_ticket(ticket)
    except (heatmap_web.HeatmapWebSessionError, heatmap_web.HeatmapWebUnavailable) as exc:
        raise _translate_web_error(exc) from exc
    token = heatmap_web.create_session_token(
        identity["viewer_user_id"], identity["target_user_id"]
    )
    response = RedirectResponse(url="/heatmap/app", status_code=303)
    response.set_cookie(
        _SESSION_COOKIE,
        token,
        max_age=heatmap_web.session_ttl_seconds(),
        path="/heatmap",
        secure=_is_secure_cookie(request),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/heatmap/app", response_class=HTMLResponse)
def heatmap_app(_: dict[str, int | str] = Depends(_session)):
    if not settings.TENCENT_MAP_KEY:
        raise HTTPException(status_code=503, detail="腾讯地图暂未配置")
    source = (_STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    script_url = "https://map.qq.com/api/gljs?v=1.exp&key=" + quote(
        settings.TENCENT_MAP_KEY, safe=""
    )
    source = source.replace(
        "<!-- TENCENT_MAP_SCRIPT -->",
        f'<script src="{script_url}"></script>',
    )
    return HTMLResponse(
        source,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'self' data: blob: https://*.qq.com https://*.map.qq.com https://*.qpic.cn https://*.gtimg.com; "
                "script-src 'self' 'unsafe-eval' https://map.qq.com https://*.map.qq.com; "
                "worker-src 'self' blob:; "
                "style-src 'self' 'unsafe-inline' https://*.qq.com https://*.map.qq.com https://*.qpic.cn; "
                "img-src 'self' data: blob: https://*.qq.com https://*.map.qq.com https://*.qpic.cn https://*.gtimg.com; "
                "connect-src 'self' https://*.qq.com https://*.map.qq.com https://*.qpic.cn https://*.gtimg.com; "
                "object-src 'none'; base-uri 'self'; form-action 'none'"
            ),
        },
    )


@router.get("/heatmap/assets/{name}")
def heatmap_asset(name: str):
    if name not in {"app.js", "styles.css"}:
        raise HTTPException(status_code=404, detail="资源不存在")
    media_type = "application/javascript" if name.endswith(".js") else "text/css"
    return FileResponse(
        _STATIC_ROOT / name,
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/heatmap/blank.png")
def heatmap_blank_tile():
    return Response(
        _TRANSPARENT_PNG,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/heatmap/manifest")
def heatmap_manifest(
    year: int | None = Query(default=None, ge=2000, le=2100),
    session: dict[str, int | str] = Depends(_session),
    db: Session = Depends(get_db),
):
    viewer_user_id = int(session["viewer_user_id"])
    target_user_id = int(session["target_user_id"])
    audience = "owner" if viewer_user_id == target_user_id else "public"
    try:
        manifest = user_service.get_user_heatmap_tile_manifest(
            db,
            target_user_id,
            year=year,
            include_private=audience == "owner",
            # “全部足迹”可能跨城市、跨国，视野会落到 z3-z10。地图与栅格金字塔
            # 必须共享同一个全球最小级别，否则 fitBounds 会被 z11 下限卡成白屏。
            min_zoom=3,
            max_zoom=18,
        )
        heatmap_web.remember_session_coverage(
            str(session["session_id"]),
            year,
            str(manifest["cache_version"]),
            manifest["tiles"],
        )
        # coverage 成功落 Redis 后才授权 version；中途失败不能让新版本复用旧清单。
        heatmap_web.remember_session_version(
            str(session["session_id"]), year, str(manifest["cache_version"])
        )
        heatmap_web.enqueue_stale_artifact_prune(
            target_user_id,
            audience,
            str(manifest["cache_version"]),
        )
    except Exception as exc:
        raise _translate_web_error(exc) from exc

    base_tiles = [
        (int(zoom), int(x), int(y))
        for zoom, coordinates in manifest["tiles"].items()
        if int(zoom) <= 15
        for x, y in coordinates
    ]
    queued_chunks = 0
    if audience == "owner" and base_tiles:
        queued_chunks = heatmap_web.enqueue_base_tile_prewarm(
            target_user_id,
            int(manifest["generation"]),
            str(manifest["cache_version"]),
            year,
            base_tiles,
        )

    # 完整 coverage 只留在服务端 Redis 会话中。客户端只拿 z3-z15 基础覆盖；
    # z16-z18 由 z15 父格判断是否值得请求，既避免解析数万项，也不请求大片空白区。
    payload = {key: value for key, value in manifest.items() if key != "tiles"}
    payload["tiles"] = {
        zoom: coordinates
        for zoom, coordinates in manifest["tiles"].items()
        if int(zoom) <= 15
    }
    payload.update(
        {
            "selected_year": year,
            "initial_zoom": 13,
            "fallback_max_zoom": 15,
            "audience": audience,
            "prewarm_queued_chunks": queued_chunks,
            "coverage_mode": "parent",
            "coverage_max_zoom": 15,
        }
    )
    return Response(
        content=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        media_type="application/json",
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
    )


def _serve_versioned_tile(
    layer: str,
    version: str,
    zoom: int,
    x: int,
    y: int,
    year: int | None,
    session: dict[str, int | str],
    db: Session,
) -> Response:
    try:
        heatmap_web.validate_session_version(str(session["session_id"]), year, version)
        try:
            heatmap_web.validate_session_tile(
                str(session["session_id"]),
                year,
                version,
                zoom,
                x,
                y,
            )
        except heatmap_web.HeatmapTileNotCovered:
            # 客户端不再下载数万项 coverage；空块由服务端内存/Redis 集合 O(1)
            # 判定后直接给透明图，不校验 DB 指纹、不触发磁盘或 PG 渲染。
            return Response(
                _TRANSPARENT_PNG,
                media_type="image/png",
                headers={
                    "Cache-Control": "private, no-store",
                    "Vary": "Cookie",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        viewer_user_id = int(session["viewer_user_id"])
        target_user_id = int(session["target_user_id"])
        audience = "owner" if viewer_user_id == target_user_id else "public"
        heatmap_web.validate_current_artifact_version(
            db,
            target_user_id,
            audience,
            version,
        )
        if layer == "fallback":
            payload = heatmap_web.get_fallback_tile_artifact(
                db, target_user_id, audience, version, year, zoom, x, y
            )
        else:
            payload = heatmap_web.get_live_tile_artifact(
                db, target_user_id, audience, version, year, zoom, x, y
            )
        # 防 TOCTOU：隐私/删除可能恰在首次校验与磁盘读取之间提交。
        # 响应前再读一次 DB 指纹，live/fallback/父级裁切统一 fail closed。
        heatmap_web.validate_current_artifact_version(
            db,
            target_user_id,
            audience,
            version,
        )
    except (ValueError, heatmap_web.HeatmapWebSessionError, heatmap_web.HeatmapWebUnavailable, heatmap_web.HeatmapTileNotCovered, user_service.InvalidHeatmapTile, user_service.HeatmapSnapshotChanged) as exc:
        raise _translate_web_error(exc) from exc
    return Response(
        payload,
        media_type="image/png",
        headers={
            # 版本 URL 已保证性能侧稳定；浏览器仍必须每次经过服务端隐私围栏，
            # 不能把已转私密/已删除的 public PNG 离线缓存 24 小时。
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/heatmap/fallback-tiles/{version}/{zoom}/{x}/{y}.png")
def fallback_tile(
    version: str,
    zoom: int,
    x: int,
    y: int,
    year: int | None = Query(default=None, ge=2000, le=2100),
    session: dict[str, int | str] = Depends(_session),
    db: Session = Depends(get_db),
):
    return _serve_versioned_tile("fallback", version, zoom, x, y, year, session, db)


@router.get("/heatmap/live-tiles/{version}/{zoom}/{x}/{y}.png")
def live_tile(
    version: str,
    zoom: int,
    x: int,
    y: int,
    year: int | None = Query(default=None, ge=2000, le=2100),
    session: dict[str, int | str] = Depends(_session),
    db: Session = Depends(get_db),
):
    return _serve_versioned_tile("live", version, zoom, x, y, year, session, db)
