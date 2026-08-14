"""
路书 API 路由——前端创建 / 浏览 / 删除路线图纸的服务台。

干啥用：暴露 /api/route-books 的增（上传文件或从活动衍生）、查（列表 / 详情 / 可选活动）、删（仅创建者）。
操作注意事项：
- 路由顺序敏感：/activity-candidates 必须定义在 /{route_book_id} 之前，否则 "activity-candidates"
  会被当成 route_book_id 去解析成整数而 422。
- service 层抛业务异常（ValueError / LookupError / PermissionError），这里统一翻译成 HTTP 状态码（422/404/403）。
- 本 task 不挂进 app.main（task 4 统一挂载所有 router）；测试里临时 include。
输入输出：接 multipart/form 表单（含可选上传文件）→ 调 service → 返回 schemas 定义的 JSON。
"""

import logging
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.middleware.rate_limit import check_rate_limit_by_ip, check_rate_limit_by_user
from app.route_book import draw_snap_service, export_workflow, schemas, service
from app.route_book.tencent_direction import (
    TencentMapConfigError,
    TencentMapError,
    TencentMapServiceUnavailableError,
)


router = APIRouter(prefix="/api/route-books", tags=["route_book"])
logger = logging.getLogger(__name__)


@router.get("", response_model=schemas.RouteBookListResponse)
def list_route_books(
    mine: bool = Query(False),
    official: bool | None = Query(None),
    city: schemas.City | None = None,
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        items = service.list_route_books(db, current_user_id, mine=mine, city=city, official=official)
        return schemas.RouteBookListResponse(
            items=[schemas.route_book_response(route, current_user_id) for route in items]
        )
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("", response_model=schemas.RouteBookResponse)
def create_route_book(
    name: str = Form(..., min_length=1, max_length=128),
    source: schemas.RouteBookCreateSource = Form(...),
    source_activity_id: int | None = Form(None),
    file: UploadFile | None = File(None),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload_bytes = file.file.read() if file is not None else None
    upload_filename = file.filename if file is not None else None
    try:
        route = service.create_route_book(
            db=db,
            current_user_id=current_user_id,
            name=name,
            source=source,
            source_activity_id=source_activity_id,
            upload_filename=upload_filename,
            upload_bytes=upload_bytes,
        )
        return schemas.route_book_response(route, current_user_id, include_elevation_profile=True)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/tencent-direction", response_model=schemas.RouteBookResponse)
def create_route_book_from_tencent_direction(
    payload: schemas.TencentDirectionRouteBookRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_rate_limit_by_user(
        current_user_id,
        "route-book-tencent-direction",
        limit=10,
        window_sec=300,
    )
    try:
        route = service.create_route_book_from_tencent_direction(
            db=db,
            current_user_id=current_user_id,
            name=payload.name,
            start=(payload.from_lat, payload.from_lon),
            end=(payload.to_lat, payload.to_lon),
        )
        return schemas.route_book_response(route, current_user_id, include_elevation_profile=True)
    except (TencentMapConfigError, TencentMapServiceUnavailableError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (TencentMapError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/manual-drawn", response_model=schemas.RouteBookResponse)
def create_route_book_from_manual_drawn(
    payload: schemas.ManualDrawnRouteBookRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_rate_limit_by_user(
        current_user_id,
        "route-book-manual-drawn",
        limit=20,
        window_sec=300,
    )
    try:
        route = service.create_route_book_from_manual_drawn(
            db=db,
            current_user_id=current_user_id,
            name=payload.name,
            client_request_id=payload.client_request_id,
            points=payload.points,
            coordinate_system=payload.coordinate_system,
            draw_metadata=(
                payload.draw_metadata.model_dump(mode="json", exclude_none=True)
                if payload.draw_metadata is not None
                else None
            ),
        )
        return schemas.route_book_response(route, current_user_id, include_elevation_profile=True)
    except service.ManualDrawIdempotencyGoneError as e:
        raise HTTPException(status_code=410, detail=str(e))
    except service.ManualDrawIdempotencyConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/manual-drawn/snap-preview", response_model=schemas.ManualDrawnSnapPreviewResponse)
def preview_manual_drawn_snap(
    payload: schemas.ManualDrawnSnapPreviewRequest,
    detour_confirmation: str | None = Header(None, alias="X-VELO-Detour-Confirmation"),
    current_user_id: int = Depends(get_current_user),
):
    started_at = time.perf_counter()
    raw_point_count = len(payload.points)
    check_rate_limit_by_user(
        current_user_id,
        "route-book-draw-snap-preview",
        # 一次正常长路线会连续新增二三十个锚点；20/5min 会误伤真实画线。
        # 60 仍能挡住持续脚本刷接口。
        limit=60,
        window_sec=300,
    )
    try:
        result = draw_snap_service.build_snap_preview(
            mode=payload.mode,
            coordinate_system=payload.coordinate_system,
            points=payload.points,
            supports_detour_confirmation=detour_confirmation == "1",
        )
        logger.info(
            "route_draw_snap_preview status=ready raw_point_count=%d "
            "provider_point_count=%d snapped_point_count=%d display_point_count=%d segment_count=%d "
            "requires_confirmation=%d duration_ms=%.1f",
            raw_point_count,
            int(result.get("provider_point_count") or len(result.get("snapped_points") or [])),
            len(result.get("snapped_points") or []),
            len(result.get("display_points") or []),
            int(result.get("segment_count") or 0),
            int(bool(result.get("requires_confirmation"))),
            (time.perf_counter() - started_at) * 1000,
        )
        return result
    except (TencentMapConfigError, TencentMapServiceUnavailableError) as e:
        logger.info(
            "route_draw_snap_preview status=unavailable raw_point_count=%d duration_ms=%.1f",
            raw_point_count,
            (time.perf_counter() - started_at) * 1000,
        )
        raise HTTPException(status_code=503, detail=str(e))
    except draw_snap_service.DrawSnapSegmentError as e:
        logger.info(
            "route_draw_snap_preview status=input_error raw_point_count=%d duration_ms=%.1f",
            raw_point_count,
            (time.perf_counter() - started_at) * 1000,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(e),
                "failed_segment": e.segment_index,
                "reason": e.reason,
            },
        )
    except TencentMapError as e:
        logger.info(
            "route_draw_snap_preview status=input_error raw_point_count=%d duration_ms=%.1f",
            raw_point_count,
            (time.perf_counter() - started_at) * 1000,
        )
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        logger.info(
            "route_draw_snap_preview status=input_error raw_point_count=%d duration_ms=%.1f",
            raw_point_count,
            (time.perf_counter() - started_at) * 1000,
        )
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/manual-drawn/elevation-preview",
    response_model=schemas.ManualDrawnElevationPreviewResponse,
)
def preview_manual_drawn_elevation(
    payload: schemas.ManualDrawnElevationPreviewRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_rate_limit_by_user(
        current_user_id,
        "route-book-draw-elevation-preview",
        limit=30,
        window_sec=300,
    )
    try:
        return service.preview_manual_drawn_elevation(
            points=payload.points,
            coordinate_system=payload.coordinate_system,
            db=db,
            current_user_id=current_user_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/activity-candidates", response_model=schemas.ActivityCandidateResponse)
def list_activity_candidates(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = service.list_activity_candidates(db, current_user_id)
    return schemas.ActivityCandidateResponse(items=items)


@router.post("/{route_book_id}/exports", response_model=schemas.RouteExportResponse)
def create_route_export(
    request: Request,
    route_book_id: int,
    payload: schemas.RouteExportCreateRequest,
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    check_rate_limit_by_ip(request, "route-book-export", limit=30, window_sec=300)
    if current_user_id is not None:
        check_rate_limit_by_user(current_user_id, "route-book-export", limit=30, window_sec=300)
    try:
        created = export_workflow.create_route_export(
            db,
            route_book_id=route_book_id,
            export_format=payload.format,
            target_platform=payload.target_platform,
            current_user_id=current_user_id,
        )
        return schemas.RouteExportResponse(**created.__dict__)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/{route_book_id}/exports/{artifact_id}/download")
def download_route_export(
    route_book_id: int,
    artifact_id: int,
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        download = export_workflow.get_route_export_download(
            db,
            route_book_id=route_book_id,
            artifact_id=artifact_id,
            current_user_id=current_user_id,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    fallback = _ascii_filename(download.filename)
    disposition = (
        f'attachment; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(download.filename)}"
    )
    return Response(
        content=download.content,
        media_type=download.content_type,
        headers={"Content-Disposition": disposition},
    )


@router.get("/{route_book_id}/detail", response_model=schemas.RouteBookDetailResponse)
def get_route_book_detail(
    route_book_id: int,
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        route, export_ready, export_formats, export_block_reason = service.get_route_book_detail(
            db,
            route_book_id,
            current_user_id,
        )
        return schemas.route_book_detail_response(
            route,
            current_user_id,
            export_ready=export_ready,
            export_formats=export_formats,
            export_block_reason=export_block_reason,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{route_book_id}", response_model=schemas.RouteBookResponse)
def get_route_book(
    route_book_id: int,
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        route = service.get_route_book(db, route_book_id, current_user_id)
        return schemas.route_book_response(route, current_user_id, include_elevation_profile=True)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{route_book_id}", status_code=204)
def delete_route_book(
    route_book_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        service.delete_route_book(db, route_book_id, current_user_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


def _ascii_filename(filename: str) -> str:
    safe = "".join(ch if ord(ch) < 128 and ch not in {'"', "\\", ";"} else "-" for ch in filename)
    safe = safe.strip(" .-_")
    return safe or "route-export"
