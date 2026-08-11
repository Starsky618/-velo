"""内部路线连接段：把人工确认的路网断点固化为可双向遍历的固定几何。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import xml.etree.ElementTree as ET

from geoalchemy2 import WKTElement
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.route_cognition.geometry_hash import hash_segment_geometry_wkt
from app.segment._geo_utils import _haversine
from app.segment.models import InternalRoutingConnector, Segment
from app.user.models import User


MAX_CONNECTOR_DISTANCE_M = 5000.0
MAX_CONNECTOR_POINT_GAP_M = 250.0
MAX_ACTIVE_ANCHOR_DRIFT_M = 1.0


class InternalRoutingConnectorError(ValueError):
    """输入不能安全地成为内部连接段。"""


@dataclass(frozen=True)
class GpxPoint:
    lon: float
    lat: float
    ele: float | None = None


@dataclass(frozen=True)
class PreparedConnectorGeometry:
    coordinates: tuple[tuple[float, float], ...]
    geometry_wkt: str
    geometry_hash: str
    distance_m: float
    source_point_count: int
    input_was_reversed: bool
    endpoint_a_snap_m: float
    endpoint_b_snap_m: float


@dataclass(frozen=True)
class InternalConnectorWriteResult:
    status: str
    connector_id: int
    slug: str
    geometry_hash: str
    distance_m: float
    traversal_policy: str
    input_was_reversed: bool
    endpoint_a_snap_m: float
    endpoint_b_snap_m: float


@dataclass(frozen=True)
class ResolvedInternalConnector:
    connector_id: int
    slug: str
    direction: str
    coordinates: tuple[tuple[float, float], ...]


def parse_gpx_track(payload: bytes) -> tuple[GpxPoint, ...]:
    """读取 GPX 唯一 trkseg 中的轨迹点，不访问网络。"""
    if not payload:
        raise InternalRoutingConnectorError("GPX 不能为空")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise InternalRoutingConnectorError(f"GPX XML 无法解析：{exc}") from exc

    segments = [
        segment
        for segment in root.findall(".//{*}trkseg")
        if segment.findall("{*}trkpt")
    ]
    if len(segments) != 1:
        raise InternalRoutingConnectorError("内部连接段 GPX 必须且只能包含一个 trkseg")

    points: list[GpxPoint] = []
    for node in segments[0].findall("{*}trkpt"):
        try:
            lat = float(node.attrib["lat"])
            lon = float(node.attrib["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InternalRoutingConnectorError("GPX trkpt 缺少合法经纬度") from exc
        if not math.isfinite(lat) or not math.isfinite(lon):
            raise InternalRoutingConnectorError("GPX 包含非有限经纬度")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise InternalRoutingConnectorError("GPX 经纬度越界")
        ele_node = node.find("{*}ele")
        ele: float | None = None
        if ele_node is not None and ele_node.text is not None:
            try:
                ele = float(ele_node.text)
            except ValueError as exc:
                raise InternalRoutingConnectorError("GPX ele 不是数字") from exc
            if not math.isfinite(ele):
                raise InternalRoutingConnectorError("GPX 包含非有限海拔")
        points.append(GpxPoint(lon=lon, lat=lat, ele=ele))

    if len(points) < 3:
        raise InternalRoutingConnectorError("GPX 至少需要 3 个轨迹点")
    return tuple(points)


def canonical_line_wkt(coordinates: tuple[tuple[float, float], ...]) -> str:
    if len(coordinates) < 3:
        raise InternalRoutingConnectorError("连接段至少需要 3 个坐标点")
    return "LINESTRING(" + ",".join(
        f"{lon:.8f} {lat:.8f}" for lon, lat in coordinates
    ) + ")"


def parse_line_wkt(reference_line_wkt: str) -> tuple[tuple[float, float], ...]:
    raw = reference_line_wkt.strip()
    if raw.upper().startswith("SRID="):
        raw = raw.split(";", 1)[1]
    if not raw.upper().startswith("LINESTRING(") or not raw.endswith(")"):
        raise InternalRoutingConnectorError("reference_line 不是 LINESTRING")
    body = raw[raw.index("(") + 1 : -1]
    coordinates: list[tuple[float, float]] = []
    try:
        for pair in body.split(","):
            lon_text, lat_text, *_rest = pair.strip().split()
            coordinates.append((float(lon_text), float(lat_text)))
    except (TypeError, ValueError) as exc:
        raise InternalRoutingConnectorError("LINESTRING 坐标无法解析") from exc
    if len(coordinates) < 3:
        raise InternalRoutingConnectorError("LINESTRING 至少需要 3 个坐标点")
    return tuple(coordinates)


def coordinates_for_traversal(
    reference_line_wkt: str,
    direction: str,
    *,
    traversal_policy: str = "bidirectional",
) -> tuple[tuple[float, float], ...]:
    """从一份物理几何派生正反两个 Traversal。"""
    coordinates = parse_line_wkt(reference_line_wkt)
    if direction == "a_to_b":
        return coordinates
    if direction == "b_to_a":
        if traversal_policy != "bidirectional":
            raise InternalRoutingConnectorError("该内部连接段不允许 b_to_a 遍历")
        return tuple(reversed(coordinates))
    raise InternalRoutingConnectorError("direction 必须是 a_to_b 或 b_to_a")


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return _haversine(a[1], a[0], b[1], b[0])


def _append_if_distinct(
    result: list[tuple[float, float]],
    point: tuple[float, float],
) -> None:
    if not result or _distance(result[-1], point) >= 0.05:
        result.append(point)


def prepare_connector_geometry(
    gpx_points: tuple[GpxPoint, ...],
    *,
    endpoint_a: tuple[float, float],
    endpoint_b: tuple[float, float],
    max_snap_distance_m: float = 100.0,
) -> PreparedConnectorGeometry:
    """自动选择 GPX 方向，并把两端精确钉到已知赛段锚点。"""
    if len(gpx_points) < 3:
        raise InternalRoutingConnectorError("GPX 至少需要 3 个轨迹点")
    if not math.isfinite(max_snap_distance_m) or max_snap_distance_m <= 0:
        raise InternalRoutingConnectorError("max_snap_distance_m 必须大于 0")

    raw = tuple((point.lon, point.lat) for point in gpx_points)
    forward_cost = _distance(endpoint_a, raw[0]) + _distance(raw[-1], endpoint_b)
    reversed_cost = _distance(endpoint_a, raw[-1]) + _distance(raw[0], endpoint_b)
    if abs(forward_cost - reversed_cost) < 1.0:
        raise InternalRoutingConnectorError("GPX 方向不明确，无法可靠绑定 endpoint_a/endpoint_b")
    input_was_reversed = reversed_cost < forward_cost
    oriented = tuple(reversed(raw)) if input_was_reversed else raw
    endpoint_a_snap_m = _distance(endpoint_a, oriented[0])
    endpoint_b_snap_m = _distance(oriented[-1], endpoint_b)
    if endpoint_a_snap_m > max_snap_distance_m:
        raise InternalRoutingConnectorError(
            f"GPX 与 endpoint_a 相差 {endpoint_a_snap_m:.1f}m，超过 {max_snap_distance_m:.1f}m"
        )
    if endpoint_b_snap_m > max_snap_distance_m:
        raise InternalRoutingConnectorError(
            f"GPX 与 endpoint_b 相差 {endpoint_b_snap_m:.1f}m，超过 {max_snap_distance_m:.1f}m"
        )

    coordinates: list[tuple[float, float]] = []
    _append_if_distinct(coordinates, endpoint_a)
    for point in oriented:
        _append_if_distinct(coordinates, point)
    _append_if_distinct(coordinates, endpoint_b)
    coordinate_tuple = tuple(coordinates)
    step_distances = [
        _distance(previous, current)
        for previous, current in zip(coordinate_tuple, coordinate_tuple[1:])
    ]
    largest_gap_m = max(step_distances)
    if largest_gap_m > MAX_CONNECTOR_POINT_GAP_M:
        raise InternalRoutingConnectorError(
            f"GPX 内部相邻点相差 {largest_gap_m:.1f}m，不能作为固定连接段"
        )
    distance_m = sum(step_distances)
    if distance_m > MAX_CONNECTOR_DISTANCE_M:
        raise InternalRoutingConnectorError(
            f"内部连接段长 {distance_m:.1f}m，超过 {MAX_CONNECTOR_DISTANCE_M:.0f}m 上限"
        )
    geometry_wkt = canonical_line_wkt(coordinate_tuple)
    return PreparedConnectorGeometry(
        coordinates=coordinate_tuple,
        geometry_wkt=geometry_wkt,
        geometry_hash=hash_segment_geometry_wkt(geometry_wkt),
        distance_m=distance_m,
        source_point_count=len(gpx_points),
        input_was_reversed=input_was_reversed,
        endpoint_a_snap_m=endpoint_a_snap_m,
        endpoint_b_snap_m=endpoint_b_snap_m,
    )


def _segment_endpoint(segment: Segment, position: str) -> tuple[float, float]:
    if position == "start":
        return (float(segment.start_lon), float(segment.start_lat))
    if position == "end":
        return (float(segment.end_lon), float(segment.end_lat))
    raise InternalRoutingConnectorError("endpoint position 必须是 start 或 end")


def prepare_internal_routing_connector(
    db: Session,
    *,
    gpx_payload: bytes,
    city: str,
    endpoint_a_segment_id: int,
    endpoint_a_position: str,
    endpoint_b_segment_id: int,
    endpoint_b_position: str,
    max_snap_distance_m: float = 100.0,
) -> PreparedConnectorGeometry:
    if endpoint_a_segment_id == endpoint_b_segment_id:
        raise InternalRoutingConnectorError("连接段两端不能绑定同一个 Segment")
    segment_a = db.get(Segment, endpoint_a_segment_id)
    segment_b = db.get(Segment, endpoint_b_segment_id)
    if segment_a is None or segment_b is None:
        raise InternalRoutingConnectorError("连接段绑定的 Segment 不存在")
    if segment_a.city != city or segment_b.city != city:
        raise InternalRoutingConnectorError("连接段 city 必须与两端 Segment 一致")
    return prepare_connector_geometry(
        parse_gpx_track(gpx_payload),
        endpoint_a=_segment_endpoint(segment_a, endpoint_a_position),
        endpoint_b=_segment_endpoint(segment_b, endpoint_b_position),
        max_snap_distance_m=max_snap_distance_m,
    )


def create_internal_routing_connector(
    db: Session,
    *,
    slug: str,
    name: str,
    city: str,
    gpx_payload: bytes,
    source_name: str,
    endpoint_a_segment_id: int,
    endpoint_a_position: str,
    endpoint_b_segment_id: int,
    endpoint_b_position: str,
    traversal_policy: str,
    blocked_provider: str | None,
    review_note: str,
    reviewer_user_id: int,
    max_snap_distance_m: float = 100.0,
) -> InternalConnectorWriteResult:
    if traversal_policy not in {"bidirectional", "a_to_b_only"}:
        raise InternalRoutingConnectorError("traversal_policy 无效")
    if max_snap_distance_m > 100:
        raise InternalRoutingConnectorError("内部连接段端点吸附上限不能超过 100m")
    if (
        not slug.strip()
        or not name.strip()
        or not source_name.strip()
        or not review_note.strip()
    ):
        raise InternalRoutingConnectorError("slug/name/source_name/review_note 不能为空")
    if len(slug.strip()) > 128 or len(name.strip()) > 128 or len(source_name.strip()) > 255:
        raise InternalRoutingConnectorError("slug/name/source_name 超过数据库长度上限")
    reviewer = db.get(User, reviewer_user_id)
    if reviewer is None or reviewer.is_admin is not True:
        raise InternalRoutingConnectorError("reviewer_user_id 必须是现有管理员")

    prepared = prepare_internal_routing_connector(
        db,
        gpx_payload=gpx_payload,
        city=city,
        endpoint_a_segment_id=endpoint_a_segment_id,
        endpoint_a_position=endpoint_a_position,
        endpoint_b_segment_id=endpoint_b_segment_id,
        endpoint_b_position=endpoint_b_position,
        max_snap_distance_m=max_snap_distance_m,
    )
    source_sha256 = hashlib.sha256(gpx_payload).hexdigest()

    existing = (
        db.query(InternalRoutingConnector)
        .filter(InternalRoutingConnector.slug == slug.strip())
        .one_or_none()
    )
    if existing is not None:
        identity = (
            existing.geometry_hash == prepared.geometry_hash
            and existing.endpoint_a_segment_id == endpoint_a_segment_id
            and existing.endpoint_a_position == endpoint_a_position
            and existing.endpoint_b_segment_id == endpoint_b_segment_id
            and existing.endpoint_b_position == endpoint_b_position
            and existing.traversal_policy == traversal_policy
            and existing.source_sha256 == source_sha256
        )
        if not identity:
            raise InternalRoutingConnectorError("同 slug 的内部连接段已经存在但内容不同")
        return InternalConnectorWriteResult(
            status="already_exists",
            connector_id=existing.id,
            slug=existing.slug,
            geometry_hash=existing.geometry_hash,
            distance_m=existing.distance,
            traversal_policy=existing.traversal_policy,
            input_was_reversed=existing.input_was_reversed,
            endpoint_a_snap_m=existing.endpoint_a_snap_m,
            endpoint_b_snap_m=existing.endpoint_b_snap_m,
        )

    duplicate = (
        db.query(InternalRoutingConnector.id)
        .filter(InternalRoutingConnector.geometry_hash == prepared.geometry_hash)
        .scalar()
    )
    if duplicate is not None:
        raise InternalRoutingConnectorError(
            f"相同几何已由内部连接段 id={duplicate} 保存"
        )

    connector = InternalRoutingConnector(
        slug=slug.strip(),
        name=name.strip(),
        city=city,
        status="active",
        traversal_policy=traversal_policy,
        endpoint_a_segment_id=endpoint_a_segment_id,
        endpoint_a_position=endpoint_a_position,
        endpoint_b_segment_id=endpoint_b_segment_id,
        endpoint_b_position=endpoint_b_position,
        start_lon=prepared.coordinates[0][0],
        start_lat=prepared.coordinates[0][1],
        end_lon=prepared.coordinates[-1][0],
        end_lat=prepared.coordinates[-1][1],
        reference_line=WKTElement(prepared.geometry_wkt, srid=4326),
        geometry_hash=prepared.geometry_hash,
        distance=prepared.distance_m,
        source_type="hand_drawn_gpx",
        source_name=source_name.strip(),
        source_sha256=source_sha256,
        source_point_count=prepared.source_point_count,
        input_was_reversed=prepared.input_was_reversed,
        endpoint_a_snap_m=prepared.endpoint_a_snap_m,
        endpoint_b_snap_m=prepared.endpoint_b_snap_m,
        blocked_provider=blocked_provider.strip() if blocked_provider else None,
        review_note=review_note.strip(),
        reviewed_by=reviewer_user_id,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(connector)
    db.flush()

    stored_wkt = (
        db.query(func.ST_AsText(InternalRoutingConnector.reference_line))
        .filter(InternalRoutingConnector.id == connector.id)
        .scalar()
    )
    if not stored_wkt:
        raise InternalRoutingConnectorError("内部连接段写入后无法回读几何")
    stored_canonical = canonical_line_wkt(parse_line_wkt(stored_wkt))
    if hash_segment_geometry_wkt(stored_canonical) != prepared.geometry_hash:
        raise InternalRoutingConnectorError("内部连接段写入后几何 hash 漂移")

    return InternalConnectorWriteResult(
        status="created",
        connector_id=connector.id,
        slug=connector.slug,
        geometry_hash=connector.geometry_hash,
        distance_m=connector.distance,
        traversal_policy=connector.traversal_policy,
        input_was_reversed=connector.input_was_reversed,
        endpoint_a_snap_m=connector.endpoint_a_snap_m,
        endpoint_b_snap_m=connector.endpoint_b_snap_m,
    )


def resolve_internal_connector(
    db: Session,
    *,
    from_segment_id: int,
    from_position: str,
    to_segment_id: int,
    to_position: str,
) -> ResolvedInternalConnector | None:
    """按两端 Segment 锚点查找内部连接段，并返回正确方向的坐标。"""
    if from_position not in {"start", "end"} or to_position not in {"start", "end"}:
        raise InternalRoutingConnectorError("endpoint position 必须是 start 或 end")

    rows = (
        db.query(
            InternalRoutingConnector,
            func.ST_AsText(InternalRoutingConnector.reference_line).label("reference_line_wkt"),
        )
        .filter(InternalRoutingConnector.status == "active")
        .filter(
            (
                (InternalRoutingConnector.endpoint_a_segment_id == from_segment_id)
                & (InternalRoutingConnector.endpoint_a_position == from_position)
                & (InternalRoutingConnector.endpoint_b_segment_id == to_segment_id)
                & (InternalRoutingConnector.endpoint_b_position == to_position)
            )
            |
            (
                (InternalRoutingConnector.traversal_policy == "bidirectional")
                & (InternalRoutingConnector.endpoint_b_segment_id == from_segment_id)
                & (InternalRoutingConnector.endpoint_b_position == from_position)
                & (InternalRoutingConnector.endpoint_a_segment_id == to_segment_id)
                & (InternalRoutingConnector.endpoint_a_position == to_position)
            )
        )
        .all()
    )
    if not rows:
        return None
    if len(rows) > 1:
        raise InternalRoutingConnectorError("同一对锚点存在多条 active 内部连接段")

    connector, reference_line_wkt = rows[0]
    segment_a = db.get(Segment, connector.endpoint_a_segment_id)
    segment_b = db.get(Segment, connector.endpoint_b_segment_id)
    if segment_a is None or segment_b is None:
        raise InternalRoutingConnectorError("内部连接段绑定的 Segment 已不存在")
    current_a = _segment_endpoint(segment_a, connector.endpoint_a_position)
    current_b = _segment_endpoint(segment_b, connector.endpoint_b_position)
    stored_a = (float(connector.start_lon), float(connector.start_lat))
    stored_b = (float(connector.end_lon), float(connector.end_lat))
    if (
        _distance(current_a, stored_a) > MAX_ACTIVE_ANCHOR_DRIFT_M
        or _distance(current_b, stored_b) > MAX_ACTIVE_ANCHOR_DRIFT_M
    ):
        raise InternalRoutingConnectorError("内部连接段绑定锚点已经漂移，必须重新复核")
    forward = (
        connector.endpoint_a_segment_id == from_segment_id
        and connector.endpoint_a_position == from_position
    )
    direction = "a_to_b" if forward else "b_to_a"
    return ResolvedInternalConnector(
        connector_id=connector.id,
        slug=connector.slug,
        direction=direction,
        coordinates=coordinates_for_traversal(
            reference_line_wkt,
            direction,
            traversal_policy=connector.traversal_policy,
        ),
    )
