"""admin 模块 API 路由骨架。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.admin.dependencies import require_admin
from app.admin import schemas, service as admin_service
from app.database import get_db
from app.segment.exceptions import InvalidSegmentRangeError, SegmentOverlapError
from app.segment import service as segment_service
from app.user.models import User


router = APIRouter(prefix="/api/admin", tags=["admin"])

# 3.A.2 追加：候选池 endpoints (GET /curation-pool, PATCH /curation-pool/{id})
# 3.A.3 追加：AI 草稿审核 endpoints
# 3.A.4 追加：批量管理 endpoints (GET /segments, PATCH /segments/{id})
# 3.A.5 追加：from-activity endpoint (POST /segments/from-activity)
# 路由顺序约定：精确路径必须放在 /{id} 之前，避免 GET /segments/from-activity
# 被未来的 GET /segments/{id} 吞掉后返回 422。


@router.get("/curation-pool", response_model=schemas.CurationPoolListResponse)
def list_curation_pool(
    selected: bool | None = Query(None),
    city: str | None = Query(
        None,
        pattern="^(beijing|shanghai|hangzhou|shenzhen|chengdu|taiyuan|unknown)$",
    ),
    difficulty: str | None = Query(
        None,
        pattern="^(easy|medium|hard|extreme)$",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """列出候选池。"""
    return admin_service.list_curation_pool(
        db,
        selected,
        city,
        difficulty,
        page,
        page_size,
    )


@router.patch("/curation-pool/{pool_id}", response_model=schemas.CurationPoolItem)
def update_curation_pool(
    pool_id: int,
    body: schemas.CurationPoolPatchRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """更新候选池勾选状态。"""
    return admin_service.update_curation_pool(
        db,
        pool_id,
        body.selected_for_v5,
        admin.id,
    )


@router.post("/ai/segment-drafts/{segment_id}/generate", status_code=202)
def generate_ai_draft(
    segment_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """手动触发 AI 草稿生成任务。"""
    return admin_service.generate_ai_draft(db, segment_id)


@router.get("/ai/segment-drafts", response_model=schemas.AiDraftListResponse)
def list_ai_drafts(
    status: str = Query(
        "pending",
        pattern="^(pending|human_edited|approved|rejected)$",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """列出 AI 草稿审核台。"""
    return admin_service.list_ai_drafts(db, status, page, page_size)


@router.patch("/ai/segment-drafts/{draft_id}", response_model=schemas.AiDraftResponse)
def update_ai_draft(
    draft_id: int,
    body: schemas.AiDraftPatchRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """编辑 AI 草稿或更新审核状态。"""
    return admin_service.update_ai_draft(db, draft_id, body, admin.id)


@router.post(
    "/segments/from-activity",
    response_model=schemas.AdminSegmentResponse,
    status_code=201,
)
def create_segment_from_activity_admin(
    body: schemas.FromActivityRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """从 activity 轨迹子序列创建赛段。"""
    try:
        segment = segment_service.create_segment_from_activity(
            db,
            activity_id=body.activity_id,
            name=body.name,
            start_index=body.start_index,
            end_index=body.end_index,
            city=body.city,
            difficulty=body.difficulty,
        )
        db.commit()
        db.refresh(segment)
        return admin_service.admin_segment_response(segment)
    except InvalidSegmentRangeError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except SegmentOverlapError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/segments", response_model=schemas.AdminSegmentListResponse)
def list_segments_admin(
    city: str | None = Query(
        None,
        pattern="^(beijing|shanghai|hangzhou|shenzhen|chengdu|taiyuan|unknown)$",
    ),
    difficulty: str | None = Query(
        None,
        pattern="^(easy|medium|hard|extreme)$",
    ),
    has_draft: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """列出 admin 批量管理赛段。"""
    return admin_service.list_segments_admin(
        db,
        city,
        difficulty,
        has_draft,
        page,
        page_size,
    )


@router.patch("/segments/{segment_id}", response_model=schemas.AdminSegmentResponse)
def update_segment_admin(
    segment_id: int,
    body: schemas.AdminSegmentPatchRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """更新 admin 允许修正的赛段元数据字段。"""
    return admin_service.update_segment_admin(db, segment_id, body)


@router.delete("/segments/{segment_id}", status_code=204)
def delete_segment_admin(
    segment_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """admin 删 segment。"""
    try:
        segment_service.delete_segment(db, segment_id, admin.id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
