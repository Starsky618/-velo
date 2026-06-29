"""
路线百科服务——把官方路线手册整理成列表页和详情页能直接展示的数据。

干啥用：读取 route_guides，并在有 route_book_id 时把路线图纸上的距离、爬升和预览线补上。
操作注意事项：ready 必须由 route_book_id is not None 派生，不能用真假值混判。
输入输出：router 传入数据库 session 和可选 id，输出闭集 Pydantic schema，前端不再猜字段。
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.route_book.models import RouteBook, RouteGuide
from app.route_book import schemas


def _json_list(value: str | None) -> list[Any] | None:
    if value is None:
        return None
    # 防御坏数据：这三列（highlights/elevation_profile/gallery_urls）正常只由灌库脚本写入，
    # 但万一 DB 里混进空串/坏 JSON，详情页应该是"少一块内容"而不是整页 500
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _km(meters: float | None) -> float | None:
    if meters is None:
        return None
    return round(float(meters) / 1000, 2)


def _list_item(guide: RouteGuide, route: RouteBook | None) -> schemas.RouteGuideListItem:
    ready = guide.route_book_id is not None
    return schemas.RouteGuideListItem(
        id=guide.id,
        name=guide.name,
        city=guide.city,
        ready=ready,
        cover_url=guide.cover_url,
        highlights=_json_list(guide.highlights),
        distance=_km(route.distance) if ready and route is not None else None,
        climb=route.climb if ready and route is not None else None,
    )


def _detail(guide: RouteGuide, route: RouteBook | None) -> schemas.RouteGuideOut:
    ready = guide.route_book_id is not None
    return schemas.RouteGuideOut(
        id=guide.id,
        name=guide.name,
        city=guide.city,
        ready=ready,
        content_md=guide.content_md,
        cover_url=guide.cover_url,
        gallery_urls=_json_list(guide.gallery_urls),
        highlights=_json_list(guide.highlights),
        elevation_profile=_json_list(guide.elevation_profile) if ready else None,
        route_book_id=guide.route_book_id,
        distance=_km(route.distance) if ready and route is not None else None,
        climb=route.climb if ready and route is not None else None,
        preview_points=route.preview_points if ready and route is not None else None,
    )


def _query_guides_with_routes(db: Session):
    return db.query(RouteGuide, RouteBook).outerjoin(
        RouteBook,
        RouteGuide.route_book_id == RouteBook.id,
    )


def list_route_guides(db: Session) -> list[schemas.RouteGuideListItem]:
    """
    返回官方路线全集。

    这里不用分页，因为首批只有 13 条。排序用 id，像书架按入库顺序摆放，避免每次请求顺序抖动。
    """
    rows = _query_guides_with_routes(db).order_by(RouteGuide.id.asc()).all()
    return [_list_item(guide, route) for guide, route in rows]


def get_route_guide(db: Session, guide_id: int) -> schemas.RouteGuideOut:
    row = _query_guides_with_routes(db).filter(RouteGuide.id == guide_id).first()
    if row is None:
        raise LookupError("route guide not found")
    guide, route = row
    return _detail(guide, route)
