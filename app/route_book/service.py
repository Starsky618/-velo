"""
路书业务逻辑——把 GPX/FIT 文件或一条已有骑行，翻译成可复用的"路线图纸"。

干啥用：用户上传路线文件 / 或选自己骑过的活动 → 生成 route_books 记录（含起点城市、距离、参考线）。
操作注意事项：
- activity_derived 必须是【当前用户自己的】【已完成的】【骑行类】活动，否则拒绝（IDOR 防护 + 业务校验）。
- 源活动以后被删，route_book 仍有效（source_activity_id 变 NULL 是合法孤儿态 / 路书复利原则）。
- 本模块只写 route_books，不创建约骑、不参与 KOM 排行（单向依赖：route_book 读 activity，反之不可）。
输入输出：router 传入文件字节 / 活动 id → 返回 RouteBook ORM 对象；删除时先删 DB 再删 storage 文件。
"""

import logging

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.service import validate_ride_file
from app.common.geo import infer_city_from_coords
from app.parsing.fit_parser import FITParser, FITParseError
from app.parsing.gpx_parser import GPXParser, GPXParseError
from app.route_book.models import RouteBook
from app.storage.local import LocalStorage


logger = logging.getLogger(__name__)
_storage = LocalStorage()


def _file_type(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"gpx", "fit"}:
        raise ValueError("只接受 .gpx 或 .fit 文件")
    return suffix


def _parse_route_file(filename: str, file_bytes: bytes) -> dict:
    validate_ride_file(filename, file_bytes)
    parser = GPXParser() if _file_type(filename) == "gpx" else FITParser()
    try:
        result = parser.parse(file_bytes)
    except (GPXParseError, FITParseError) as e:
        # GPXParseError / FITParseError 直接继承 Exception（不是 ValueError），
        # 不转译就会穿透 router 成 500。用户上传损坏文件应得 422（坏请求），不是 500（内部错误）。
        raise ValueError(f"路线文件解析失败：{e}")
    points = [
        {"lat": p.lat, "lon": p.lon, "ele": p.ele}
        for p in result.trackpoints
        if p.lat is not None and p.lon is not None
    ]
    return _route_payload_from_points(points, result.summary.distance, result.summary.elevation_gain)


def _route_payload_from_points(points: list[dict], distance: float | None, climb: float | None) -> dict:
    if len(points) < 2:
        raise ValueError("路线至少需要 2 个有效轨迹点")
    coords = ", ".join(f"{p['lon']} {p['lat']}" for p in points)
    first = points[0]
    return {
        "distance": float(distance or 0),
        "climb": climb,
        "city": infer_city_from_coords(first.get("lat"), first.get("lon")),
        "wkt": f"SRID=4326;LINESTRING({coords})",
    }


def create_route_book(
    db: Session,
    current_user_id: int,
    name: str,
    source: str,
    source_activity_id: int | None = None,
    upload_filename: str | None = None,
    upload_bytes: bytes | None = None,
) -> RouteBook:
    if source == "activity_derived":
        if source_activity_id is None:
            raise ValueError("activity_derived 必须提供 source_activity_id")
        activity = db.query(Activity).filter(Activity.id == source_activity_id).first()
        if activity is None:
            raise LookupError("activity not found")
        if activity.user_id != current_user_id:
            raise PermissionError("not owner")
        if activity.status != "completed" or activity.activity_type != "cycling":
            raise ValueError("activity is not a completed cycling ride")
        trackpoints = (
            db.query(Trackpoint)
            .filter(Trackpoint.activity_id == activity.id)
            .order_by(Trackpoint.seq.asc())
            .all()
        )
        points = [
            {"lat": p.latitude, "lon": p.longitude, "ele": p.elevation}
            for p in trackpoints
            if p.latitude is not None and p.longitude is not None
        ]
        payload = _route_payload_from_points(points, activity.distance, activity.elevation_gain)
        route = RouteBook(
            creator_id=current_user_id,
            name=name,
            distance=payload["distance"],
            climb=payload["climb"],
            reference_line=WKTElement(payload["wkt"], srid=4326),
            file_id=None,
            file_type=None,
            source="activity_derived",
            source_activity_id=source_activity_id,
            city=activity.city or payload["city"],
        )
    elif source == "file_upload":
        if not upload_filename or upload_bytes is None:
            raise ValueError("file_upload 必须上传路线文件")
        payload = _parse_route_file(upload_filename, upload_bytes)
        file_id = _storage.upload(upload_bytes, upload_filename)
        route = RouteBook(
            creator_id=current_user_id,
            name=name,
            distance=payload["distance"],
            climb=payload["climb"],
            reference_line=WKTElement(payload["wkt"], srid=4326),
            file_id=file_id,
            file_type=_file_type(upload_filename),
            source="file_upload",
            source_activity_id=None,
            city=payload["city"],
        )
    else:
        raise ValueError("invalid source")

    # file_upload 分支已经先把文件写进了 storage；万一接下来 db.commit() 失败，
    # storage 里就会留下一个没有 DB 记录指向的孤儿文件。这里做补偿删除——
    # "凡创建了资源就必须有清理路径"（CLAUDE.md 强制检查清单）。
    # activity_derived 分支没上传文件（file_id 恒为 None），不需要补偿。
    uploaded_file_id = route.file_id if source == "file_upload" else None
    db.add(route)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if uploaded_file_id:
            try:
                _storage.delete(uploaded_file_id)
            except OSError as e:
                logger.warning("补偿删除孤儿文件失败 file_id=%s: %s", uploaded_file_id, e)
        raise
    db.refresh(route)
    return route


def list_route_books(
    db: Session,
    current_user_id: int | None,
    *,
    mine: bool = False,
    city: str | None = None,
) -> list[RouteBook]:
    query = db.query(RouteBook)
    if mine:
        if current_user_id is None:
            raise PermissionError("login required")
        query = query.filter(RouteBook.creator_id == current_user_id)
    if city:
        query = query.filter(RouteBook.city == city)
    return query.order_by(RouteBook.created_at.desc()).all()


def get_route_book(db: Session, route_book_id: int) -> RouteBook:
    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise LookupError("route_book not found")
    return route


def delete_route_book(db: Session, route_book_id: int, current_user_id: int) -> None:
    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise LookupError("route_book not found")
    if route.creator_id != current_user_id:
        raise PermissionError("not owner")
    file_id = route.file_id
    db.delete(route)
    db.commit()
    if file_id:
        # storage 删文件失败不阻塞用户：DB 是 source of truth，记录已删即算成功。
        # 文件本来不存在时 LocalStorage.delete 返回 False（不抛）；但权限/IO 异常会抛 OSError，
        # 这里吞掉并记日志，孤儿文件留待定期清理（v2）——与 meetup_media 删除策略一致（spec §4.3）。
        try:
            _storage.delete(file_id)
        except OSError as e:
            logger.warning("route_book 文件删除失败 file_id=%s: %s", file_id, e)


def list_activity_candidates(db: Session, current_user_id: int) -> list[Activity]:
    return (
        db.query(Activity)
        .filter(
            Activity.user_id == current_user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.duplicate_of.is_(None),
        )
        .order_by(Activity.started_at.desc())
        .limit(50)
        .all()
    )
