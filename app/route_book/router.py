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

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.middleware.rate_limit import check_rate_limit_by_ip, check_rate_limit_by_user
from app.route_book import export_workflow, schemas, service
from app.route_book.tencent_direction import TencentMapConfigError, TencentMapError


router = APIRouter(prefix="/api/route-books", tags=["route_book"])


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
    except TencentMapConfigError as e:
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
            points=payload.points,
        )
        return schemas.route_book_response(route, current_user_id, include_elevation_profile=True)
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
