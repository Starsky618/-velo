"""
路书业务逻辑——把 GPX/FIT 文件或一条已有骑行，翻译成可复用的"路线图纸"。

干啥用：用户上传路线文件 / 选自己骑过的活动 / 用腾讯地图规划 → 生成 route_books 记录（含起点城市、距离、参考线）。
操作注意事项：
- activity_derived 必须是【当前用户自己的】【已完成的】【骑行类】活动，否则拒绝（IDOR 防护 + 业务校验）。
- 源活动以后被删，route_book 仍有效（source_activity_id 变 NULL 是合法孤儿态 / 路书复利原则）。
- 本模块只写 route_books，不创建约骑、不参与 KOM 排行（单向依赖：route_book 读 activity，反之不可）。
输入输出：router 传入文件字节 / 活动 id → 返回 RouteBook ORM 对象；删除时先删 DB 再删 storage 文件。
"""

import logging
import hashlib
import json
import math

from geoalchemy2 import WKTElement
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.service import validate_ride_file
from app.common.geo import infer_city_from_coords
from app.parsing.fit_parser import FITParser, FITParseError
from app.parsing.gpx_parser import GPXParser, GPXParseError
from app.route_book.models import RouteBook, RouteVersion
from app.route_book.tencent_direction import plan_tencent_bicycling_route
from app.segment.coord_convert import convert_points_to_wgs84
from app.storage.local import LocalStorage


logger = logging.getLogger(__name__)

MIN_TENCENT_ROUTE_DISTANCE_METERS = 100.0
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
        "elevation_points_snapshot": _elevation_points_snapshot_from_points(points),
    }


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _elevation_points_snapshot_from_points(points: list[dict]) -> str | None:
    """
    保存和路线点一一对应的海拔底片。

    elevation_profile 是给前端画图的缩略图；这里像保存原图一样保留每个点，
    导出 GPX/TCX 时才能把海拔交给码表，而不是让目标 App 自己猜。
    """
    snapshot: list[list[float | None]] = []
    has_elevation = False
    for point in points:
        lon = _finite_float(point.get("lon"))
        lat = _finite_float(point.get("lat"))
        if lon is None or lat is None:
            continue
        ele = _finite_float(point.get("ele"))
        if ele is not None:
            has_elevation = True
        snapshot.append([lon, lat, ele])
    if len(snapshot) < 2 or not has_elevation:
        return None
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


def _line_hash(reference_line_wkt: str) -> str:
    """给路线线条算指纹；像文件校验码一样，用来判断两版路线是不是同一条线。"""
    normalized = " ".join(reference_line_wkt.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _point_count_from_wkt(reference_line_wkt: str) -> int:
    body = reference_line_wkt.split("LINESTRING(", 1)[-1].rstrip(")")
    return len([pair for pair in body.split(",") if pair.strip()])


def create_initial_route_version(
    db: Session,
    route: RouteBook,
    *,
    reference_line_wkt: str,
    geometry_source: str,
    created_by: int | None,
    elevation_profile: str | None = None,
    elevation_points_snapshot: str | None = None,
) -> RouteVersion:
    """
    给新路书创建 v1 快照。

    route_books 像用户书架上那本路线图纸，route_versions 像每次定稿时拍下的照片。
    之后用户编辑图纸，旧照片仍然能证明当时导出/导航用的是哪一版。
    """
    line_hash = _line_hash(reference_line_wkt)
    route.line_hash = line_hash
    route.elevation_profile = elevation_profile
    version = RouteVersion(
        route_book_id=route.id,
        version_no=1,
        status="current",
        created_by=created_by,
        geometry_source=geometry_source,
        navigation_status="ready",
        reference_line_snapshot=WKTElement(reference_line_wkt, srid=4326),
        line_hash=line_hash,
        distance=route.distance,
        climb=route.climb,
        elevation_profile=elevation_profile,
        elevation_points_snapshot=elevation_points_snapshot,
        point_count=_point_count_from_wkt(reference_line_wkt),
    )
    db.add(version)
    db.flush()
    route.current_version_id = version.id
    return version


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
        db.flush()
        create_initial_route_version(
            db,
            route,
            reference_line_wkt=payload["wkt"],
            geometry_source=source,
            created_by=current_user_id,
            elevation_points_snapshot=payload.get("elevation_points_snapshot"),
        )
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


def create_route_book_from_tencent_direction(
    db: Session,
    current_user_id: int,
    name: str,
    start: tuple[float, float],
    end: tuple[float, float],
) -> RouteBook:
    """
    用腾讯地图骑行路线规划生成路书。

    腾讯返回的是 GCJ-02（适合地图展示），Velo 入库必须是 WGS-84（适合 PostGIS 和赛段匹配）。
    所以这里先让腾讯画路线，再把点串翻译成 Velo 的内部坐标语言后保存。
    """
    planned = plan_tencent_bicycling_route(start, end)
    if planned["distance"] < MIN_TENCENT_ROUTE_DISTANCE_METERS:
        raise ValueError("路线太短，换一个终点再试")
    points_wgs84 = convert_points_to_wgs84(planned["points"], "gcj02")
    payload = _route_payload_from_points(points_wgs84, planned.get("distance"), None)
    route = RouteBook(
        creator_id=current_user_id,
        name=name,
        distance=payload["distance"],
        climb=payload["climb"],
        reference_line=WKTElement(payload["wkt"], srid=4326),
        file_id=None,
        file_type=None,
        source="tencent_direction",
        source_activity_id=None,
        city=payload["city"],
    )
    db.add(route)
    try:
        db.flush()
        create_initial_route_version(
            db,
            route,
            reference_line_wkt=payload["wkt"],
            geometry_source="tencent_direction",
            created_by=current_user_id,
            elevation_points_snapshot=payload.get("elevation_points_snapshot"),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(route)
    route._preview_points_override = [[p["lon"], p["lat"]] for p in points_wgs84]
    return route


def list_route_books(
    db: Session,
    current_user_id: int | None,
    *,
    mine: bool = False,
    city: str | None = None,
    official: bool | None = None,
) -> list[RouteBook]:
    query = db.query(RouteBook)
    if mine:
        if current_user_id is None:
            raise PermissionError("login required")
        query = query.filter(RouteBook.creator_id == current_user_id)
    elif current_user_id is None:
        query = query.filter(RouteBook.visibility == "public", RouteBook.publish_status == "published")
    else:
        query = query.filter(
            or_(
                RouteBook.creator_id == current_user_id,
                (RouteBook.visibility == "public") & (RouteBook.publish_status == "published"),
            )
        )
    if official is True:
        query = query.filter(RouteBook.is_official.is_(True))
    elif official is False:
        query = query.filter(RouteBook.is_official.is_(False))
    if city:
        query = query.filter(RouteBook.city == city)
    return query.order_by(RouteBook.created_at.desc()).all()


def get_route_book(db: Session, route_book_id: int, current_user_id: int | None = None) -> RouteBook:
    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise LookupError("route_book not found")
    if current_user_id is not None and route.creator_id == current_user_id:
        return route
    if route.visibility == "public" and route.publish_status == "published":
        return route
    # 私人 / 未发布路线对非本人表现为不存在，避免泄露“这条路线确实存在”。
    raise LookupError("route_book not found")


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
