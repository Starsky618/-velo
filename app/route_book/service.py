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
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.service import validate_ride_file
from app.common.geo import infer_city_from_coords
from app.elevation.dem_client import (
    DEMServiceError,
    GLO30_HORIZONTAL_RESOLUTION_M,
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_ACCURACY_M,
    query_elevations,
)
from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    RouteElevationInputError,
    build_route_elevation_result,
    route_elevation_metadata,
)
from app.parsing.fit_parser import FITParser, FITParseError
from app.parsing.geo_math import haversine
from app.parsing.gpx_parser import GPXParser, GPXParseError
from app.route_book.elevation_quality import has_trusted_route_elevation
from app.route_book.elevation_workflow import write_route_elevation_result
from app.route_book.export_service import can_export_route
from app.route_book.models import (
    RouteBook,
    RouteExportArtifact,
    RouteBookSaveRequest,
    RouteVersion,
    _preview_points_from_wkb,
    _preview_points_from_wkt,
)
from app.route_book.tencent_direction import plan_tencent_bicycling_route
from app.segment.coord_convert import convert_points_to_wgs84
from app.storage.local import LocalStorage
from app.user.models import User


logger = logging.getLogger(__name__)

MIN_TENCENT_ROUTE_DISTANCE_METERS = 100.0
MIN_MANUAL_ROUTE_DISTANCE_METERS = 20.0
MANUAL_ROUTE_MAX_POINTS = 500
MAX_DRAW_METADATA_BYTES = 8 * 1024
MAX_DRAW_METADATA_WARNINGS = 20
MAX_DRAW_METADATA_SAMPLE_POINTS = 20
MANUAL_DRAW_IDEMPOTENCY_CONSTRAINT = "uq_route_save_req_creator_key"
_storage = LocalStorage()


class ManualDrawIdempotencyConflictError(ValueError):
    """同一保存请求号被复用于不同路线意图。"""


class ManualDrawIdempotencyGoneError(ValueError):
    """同一保存请求曾成功，但对应路线后来已被用户删除。"""


def _manual_draw_user_exists(db: Session, current_user_id: int) -> bool:
    return db.query(User.id).filter(User.id == current_user_id).first() is not None


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


def _manual_route_payload_from_points(points: list[tuple[float, float]]) -> dict:
    if len(points) > MANUAL_ROUTE_MAX_POINTS:
        raise ValueError(f"手画路线最多支持 {MANUAL_ROUTE_MAX_POINTS} 个点，请先简化路线")
    route_points: list[dict] = []
    for index, (lon, lat) in enumerate(points):
        lon = float(lon)
        lat = float(lat)
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError(f"第 {index + 1} 个路线点不是有效数字")
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise ValueError(f"第 {index + 1} 个路线点超出经纬度范围")
        route_points.append({"lon": lon, "lat": lat, "ele": None})

    distance = _distance_from_lonlat_points(route_points)
    if distance < MIN_MANUAL_ROUTE_DISTANCE_METERS:
        raise ValueError("路线太短，至少画出一小段真实路径")
    return _route_payload_from_points(route_points, distance, None)


def _manual_points_for_storage(
    points: list[tuple[float, float]],
    coordinate_system: str,
) -> list[tuple[float, float]]:
    if coordinate_system == "wgs84":
        return [(float(lon), float(lat)) for lon, lat in points]
    if coordinate_system != "gcj02":
        raise ValueError("coordinate_system 只支持 wgs84 或 gcj02")

    gcj02_points = _manual_point_dicts(points)
    converted = convert_points_to_wgs84(gcj02_points, "gcj02")
    return _manual_lonlat_tuples_from_dicts(converted)


def _manual_point_dicts(points: list[tuple[float, float]]) -> list[dict]:
    result: list[dict] = []
    for index, (lon, lat) in enumerate(points):
        lon = float(lon)
        lat = float(lat)
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError(f"第 {index + 1} 个路线点不是有效数字")
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise ValueError(f"第 {index + 1} 个路线点超出经纬度范围")
        result.append({"lon": lon, "lat": lat})
    return result


def _manual_lonlat_tuples_from_dicts(points: list[dict]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        try:
            lon = float(point["lon"])
            lat = float(point["lat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"第 {index + 1} 个坐标转换结果缺少经纬度") from exc
        result.append((lon, lat))
    return result


def _distance_from_lonlat_points(points: list[dict]) -> float:
    total = 0.0
    for prev, curr in zip(points, points[1:]):
        total += haversine(prev["lat"], prev["lon"], curr["lat"], curr["lon"])
    return total


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


def _navigation_metadata_json_from_draw_metadata(draw_metadata: dict | None) -> str | None:
    if draw_metadata is None:
        return None
    if not isinstance(draw_metadata, dict):
        raise ValueError("draw_metadata 必须是对象")

    cleaned = _drop_empty_metadata_values(draw_metadata)
    if not cleaned:
        return None
    _validate_draw_metadata_limits(cleaned)
    encoded = json.dumps({"draw": cleaned}, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_DRAW_METADATA_BYTES:
        raise ValueError("draw_metadata 序列化后不能超过 8KB")
    return encoded


def _manual_draw_request_hash(
    *,
    name: str,
    coordinate_system: str,
    points: list[tuple[float, float]],
    draw_metadata: dict | None,
) -> str:
    canonical = json.dumps(
        {
            "schema_version": 1,
            "name": name,
            "coordinate_system": coordinate_system,
            "points": [[float(lon), float(lat)] for lon, lat in points],
            "draw_metadata": draw_metadata,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _existing_manual_draw_request(
    db: Session,
    *,
    current_user_id: int,
    client_request_id: str,
    request_hash: str,
) -> RouteBook | None:
    save_request = (
        db.query(RouteBookSaveRequest)
        .filter(
            RouteBookSaveRequest.creator_id == current_user_id,
            RouteBookSaveRequest.client_request_id == client_request_id,
        )
        .one_or_none()
    )
    if save_request is None:
        return None
    if save_request.request_hash != request_hash:
        raise ManualDrawIdempotencyConflictError("保存记录冲突，请重新确认路线")
    if save_request.route_book_id is None:
        raise ManualDrawIdempotencyGoneError("上次保存的路线已删除，请重新保存")
    route = (
        db.query(RouteBook)
        .filter(
            RouteBook.id == save_request.route_book_id,
            RouteBook.creator_id == current_user_id,
        )
        .one_or_none()
    )
    if route is None:
        raise ManualDrawIdempotencyGoneError("上次保存的路线已失效，请重新保存")
    return route


def _drop_empty_metadata_values(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            cleaned = _drop_empty_metadata_values(item)
            if cleaned not in (None, [], {}):
                result[key] = cleaned
        return result
    if isinstance(value, list):
        return value
    return value


def _validate_draw_metadata_limits(draw_metadata: dict) -> None:
    warnings = draw_metadata.get("warnings") or []
    if not isinstance(warnings, list):
        raise ValueError("draw_metadata.warnings 必须是数组")
    if len(warnings) > MAX_DRAW_METADATA_WARNINGS:
        raise ValueError("draw_metadata.warnings 最多保留 20 条")

    raw_summary = draw_metadata.get("raw_points_summary") or {}
    if raw_summary and not isinstance(raw_summary, dict):
        raise ValueError("draw_metadata.raw_points_summary 必须是对象")
    sample = raw_summary.get("sample") if isinstance(raw_summary, dict) else None
    if sample is None:
        return
    if not isinstance(sample, list):
        raise ValueError("draw_metadata.raw_points_summary.sample 必须是数组")
    if len(sample) > MAX_DRAW_METADATA_SAMPLE_POINTS:
        raise ValueError("draw_metadata.raw_points_summary.sample 最多保留 20 个点")
    _manual_point_dicts([tuple(point) for point in sample])


def create_initial_route_version(
    db: Session,
    route: RouteBook,
    *,
    reference_line_wkt: str,
    geometry_source: str,
    created_by: int | None,
    elevation_profile: str | None = None,
    elevation_points_snapshot: str | None = None,
    navigation_metadata_json: str | None = None,
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
        navigation_metadata_json=navigation_metadata_json,
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

    # Activity 自身继续保留并展示码表海拔；一旦转成“规划路线”，就必须和手绘、
    # 腾讯规划共用稳定的 GLO + VELO 成品链，不能把不同设备的原始高度写进路线底座。
    uploaded_file_id = route.file_id if source == "file_upload" else None
    preview_points = _preview_points_from_wkt(payload["wkt"])
    try:
        elevation_result = build_route_elevation_result(
            preview_points,
            query_func=query_elevations,
        )
    except RouteElevationInputError:
        _delete_uploaded_route_file(uploaded_file_id)
        raise
    except (DEMServiceError, ValueError) as exc:
        _delete_uploaded_route_file(uploaded_file_id)
        raise RuntimeError(f"路线海拔查询失败：{exc}") from exc
    route.climb = elevation_result.climb

    # file_upload 分支已经先把文件写进了 storage；万一接下来 db.commit() 失败，
    # storage 里就会留下一个没有 DB 记录指向的孤儿文件。这里做补偿删除——
    # "凡创建了资源就必须有清理路径"（CLAUDE.md 强制检查清单）。
    # activity_derived 分支没上传文件（file_id 恒为 None），不需要补偿。
    db.add(route)
    try:
        db.flush()
        version = create_initial_route_version(
            db,
            route,
            reference_line_wkt=payload["wkt"],
            geometry_source=source,
            created_by=current_user_id,
        )
        write_route_elevation_result(
            db,
            route=route,
            version=version,
            result=elevation_result,
            source_name=GLO30_SOURCE_NAME,
            license_id=GLO30_LICENSE_ID,
            accuracy_m=GLO30_VERTICAL_ACCURACY_M,
            method=ROUTE_ELEVATION_METHOD,
            timestamp_field="generated_at",
            extra_metadata={
                "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
                **route_elevation_metadata(),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        _delete_uploaded_route_file(uploaded_file_id)
        raise
    db.refresh(route)
    return route


def _delete_uploaded_route_file(file_id: str | None) -> None:
    """保存路线失败时尽力清掉已上传文件，但不能遮住原始失败。"""
    if not file_id:
        return
    try:
        _storage.delete(file_id)
    except Exception:
        logger.exception("补偿删除孤儿文件失败 file_id=%s", file_id)


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
    preview_points = [[float(point["lon"]), float(point["lat"])] for point in points_wgs84]
    try:
        elevation_result = build_route_elevation_result(
            preview_points,
            query_func=query_elevations,
        )
    except RouteElevationInputError:
        raise
    except (DEMServiceError, ValueError) as exc:
        raise RuntimeError(f"路线海拔查询失败：{exc}") from exc
    route = RouteBook(
        creator_id=current_user_id,
        name=name,
        distance=payload["distance"],
        climb=elevation_result.climb,
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
        version = create_initial_route_version(
            db,
            route,
            reference_line_wkt=payload["wkt"],
            geometry_source="tencent_direction",
            created_by=current_user_id,
            elevation_points_snapshot=payload.get("elevation_points_snapshot"),
        )
        write_route_elevation_result(
            db,
            route=route,
            version=version,
            result=elevation_result,
            source_name=GLO30_SOURCE_NAME,
            license_id=GLO30_LICENSE_ID,
            accuracy_m=GLO30_VERTICAL_ACCURACY_M,
            method=ROUTE_ELEVATION_METHOD,
            timestamp_field="generated_at",
            extra_metadata={
                "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
                **route_elevation_metadata(),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(route)
    route._preview_points_override = preview_points
    return route


def create_route_book_from_manual_drawn(
    db: Session,
    current_user_id: int,
    name: str,
    client_request_id: str,
    points: list[tuple[float, float]],
    coordinate_system: str = "wgs84",
    draw_metadata: dict | None = None,
) -> RouteBook:
    """
    保存用户在地图上手画的路书，并立刻补齐同一版路线的逐点海拔。

    类比：用户只是在纸上画了一条线；这里负责把这条线归档成正式图纸，
    再拿公共地形尺量出每个点的高度，后面详情页和码表导出都读这张定稿图。
    """
    if not _manual_draw_user_exists(db, current_user_id):
        raise PermissionError("用户不存在或已注销")
    request_hash = _manual_draw_request_hash(
        name=name,
        coordinate_system=coordinate_system,
        points=points,
        draw_metadata=draw_metadata,
    )
    existing = _existing_manual_draw_request(
        db,
        current_user_id=current_user_id,
        client_request_id=client_request_id,
        request_hash=request_hash,
    )
    if existing is not None:
        return existing

    # 上面的用户/幂等查询会隐式开启数据库事务。GLO 冷瓦片属于外部网络 I/O，
    # 不能让这段不可控等待占着连接和事务；下载完成后再重新核验用户和幂等键。
    db.rollback()

    points_wgs84 = _manual_points_for_storage(points, coordinate_system)
    payload = _manual_route_payload_from_points(points_wgs84)
    navigation_metadata_json = _navigation_metadata_json_from_draw_metadata(draw_metadata)
    preview_points = [[float(lon), float(lat)] for lon, lat in points_wgs84]
    try:
        elevation_result = build_route_elevation_result(preview_points, query_func=query_elevations)
    except RouteElevationInputError:
        raise
    except DEMServiceError as e:
        raise RuntimeError(f"路线海拔查询失败：{e}") from e
    except ValueError as e:
        raise RuntimeError(f"路线海拔查询失败：{e}") from e

    if not _manual_draw_user_exists(db, current_user_id):
        raise PermissionError("用户不存在或已注销")
    existing = _existing_manual_draw_request(
        db,
        current_user_id=current_user_id,
        client_request_id=client_request_id,
        request_hash=request_hash,
    )
    if existing is not None:
        return existing

    route = RouteBook(
        creator_id=current_user_id,
        name=name,
        distance=payload["distance"],
        climb=payload["climb"],
        reference_line=WKTElement(payload["wkt"], srid=4326),
        file_id=None,
        file_type=None,
        source="manual_drawn",
        source_activity_id=None,
        city=payload["city"],
    )
    db.add(route)
    try:
        db.flush()
        version = create_initial_route_version(
            db,
            route,
            reference_line_wkt=payload["wkt"],
            geometry_source="manual_drawn",
            created_by=current_user_id,
            elevation_points_snapshot=payload.get("elevation_points_snapshot"),
            navigation_metadata_json=navigation_metadata_json,
        )
        write_route_elevation_result(
            db,
            route=route,
            version=version,
            result=elevation_result,
            source_name=GLO30_SOURCE_NAME,
            license_id=GLO30_LICENSE_ID,
            accuracy_m=GLO30_VERTICAL_ACCURACY_M,
            method=ROUTE_ELEVATION_METHOD,
            timestamp_field="generated_at",
            extra_metadata={
                "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
                **route_elevation_metadata(),
            },
        )
        db.add(
            RouteBookSaveRequest(
                creator_id=current_user_id,
                client_request_id=client_request_id,
                request_hash=request_hash,
                route_book_id=route.id,
            )
        )
        db.flush()
        db.commit()
    except IntegrityError as error:
        db.rollback()
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint_name != MANUAL_DRAW_IDEMPOTENCY_CONSTRAINT:
            if not _manual_draw_user_exists(db, current_user_id):
                raise PermissionError("用户不存在或已注销") from error
            raise
        existing = _existing_manual_draw_request(
            db,
            current_user_id=current_user_id,
            client_request_id=client_request_id,
            request_hash=request_hash,
        )
        if existing is not None:
            return existing
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(route)
    route._preview_points_override = preview_points
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


def get_route_book_detail(
    db: Session,
    route_book_id: int,
    current_user_id: int | None = None,
) -> tuple[RouteBook, bool, list[str], str | None]:
    route = get_route_book(db, route_book_id, current_user_id)
    _ensure_route_preview_points_for_detail(db, route)
    export_ready, export_formats, export_block_reason = _route_book_export_state(
        db,
        route,
        current_user_id=current_user_id,
    )
    return route, export_ready, export_formats, export_block_reason


def _ensure_route_preview_points_for_detail(db: Session, route: RouteBook) -> None:
    if route.current_version_id is None:
        return
    row = (
        db.query(RouteVersion, func.ST_AsText(RouteVersion.reference_line_snapshot))
        .filter(
            RouteVersion.id == route.current_version_id,
            RouteVersion.route_book_id == route.id,
        )
        .first()
    )
    if row is None:
        return
    version, reference_line_wkt = row
    preview_points = _preview_points_from_wkt(reference_line_wkt) if reference_line_wkt else []
    if not preview_points:
        preview_points = _preview_points_from_geometry(version.reference_line_snapshot)
    if preview_points:
        route._preview_points_override = preview_points


def _preview_points_from_geometry(value: object) -> list[list[float]]:
    if value is None:
        return []
    if isinstance(value, str):
        points = _preview_points_from_wkt(value)
        return points or _preview_points_from_wkb(value)
    data = getattr(value, "data", value)
    if isinstance(data, str):
        points = _preview_points_from_wkt(data)
        return points or _preview_points_from_wkb(data)
    return _preview_points_from_wkb(data)


def _route_book_export_state(
    db: Session,
    route: RouteBook,
    *,
    current_user_id: int | None,
) -> tuple[bool, list[str], str | None]:
    if not can_export_route(route, current_user_id=current_user_id):
        return False, [], "not_public"

    if route.current_version_id is None:
        return False, [], "no_current_version"
    version = (
        db.query(RouteVersion)
        .filter(
            RouteVersion.id == route.current_version_id,
            RouteVersion.route_book_id == route.id,
        )
        .first()
    )
    if version is None or version.navigation_status != "ready":
        return False, [], "no_current_version"
    if not has_trusted_route_elevation(
        version.elevation_points_snapshot,
        metadata_json=version.navigation_metadata_json,
        expected_count=version.point_count or 0,
    ):
        return False, [], "no_elevation"
    return True, ["gpx", "tcx"], None


def delete_route_book(db: Session, route_book_id: int, current_user_id: int) -> None:
    # 与 create_route_export 的 SELECT FOR UPDATE 成对，避免删除扫描完 artifact 后
    # 另一个请求又为同一路线提交新的导出文件。
    route = (
        db.query(RouteBook)
        .filter(RouteBook.id == route_book_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if route is None:
        raise LookupError("route_book not found")
    if route.creator_id != current_user_id:
        raise PermissionError("not owner")
    file_ids = {
        row.file_id
        for row in db.query(RouteExportArtifact.file_id)
        .filter(RouteExportArtifact.route_book_id == route.id)
        .all()
        if row.file_id
    }
    if route.file_id:
        file_ids.add(route.file_id)
    # 保存凭据必须比路线活得久；先断开关联再删除，SQLite 测试与真实 PostgreSQL
    # 都会留下同一个 tombstone，迟到重放只会收到冲突，不会把路线重新创建。
    db.query(RouteBookSaveRequest).filter(
        RouteBookSaveRequest.route_book_id == route.id
    ).update({RouteBookSaveRequest.route_book_id: None}, synchronize_session=False)
    db.delete(route)
    db.commit()
    for file_id in file_ids:
        # DB 是 source of truth；commit 后再删原文件和所有 GPX/TCX 导出物。
        # 失败不把已删路线复活，但必须留完整 traceback 便于清理孤儿私密轨迹。
        try:
            _storage.delete(file_id)
        except Exception:
            logger.exception("route_book 文件删除失败 file_id=%s", file_id)


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
