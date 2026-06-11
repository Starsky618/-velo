"""
路线百科 API 路由——给小程序的路线书架和路线详情供数据。

干啥用：暴露 /api/route-guides 列表和 /api/route-guides/{id} 详情两个只读接口。
操作注意事项：独立前缀避开 /api/route-books/{id} 通配路由，不能加进旧 router 里。
输入输出：接收 HTTP GET 请求，调用 service_guides，把闭集 schema 返回给前端。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.route_book import schemas, service_guides


router = APIRouter(prefix="/api/route-guides", tags=["route_guides"])


@router.get("", response_model=schemas.RouteGuideListResponse)
def list_route_guides(db: Session = Depends(get_db)):
    items = service_guides.list_route_guides(db)
    return schemas.RouteGuideListResponse(items=items)


@router.get("/{guide_id}", response_model=schemas.RouteGuideOut)
def get_route_guide(guide_id: int, db: Session = Depends(get_db)):
    try:
        return service_guides.get_route_guide(db, guide_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
