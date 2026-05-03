"""admin 模块 API 路由骨架。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin.dependencies import require_admin
from app.database import get_db
from app.segment import service as segment_service
from app.user.models import User


router = APIRouter(prefix="/api/admin", tags=["admin"])

# 3.A.2 追加：候选池 endpoints (GET /curation-pool, PATCH /curation-pool/{id})
# 3.A.3 追加：AI 草稿审核 endpoints
# 3.A.4 追加：批量管理 endpoints (GET /segments, PATCH /segments/{id})
# 3.A.5 追加：from-activity endpoint (POST /segments/from-activity)
# 路由顺序约定：精确路径必须放在 /{id} 之前，避免 GET /segments/from-activity
# 被未来的 GET /segments/{id} 吞掉后返回 422。


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
