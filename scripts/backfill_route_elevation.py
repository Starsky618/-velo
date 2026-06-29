"""路线精确海拔回填工具——像验货员一样，只给同一条路线补高度。

干啥用：当我们拿到 iGPSPORT 等外部来源的逐点海拔时，先确认它和 VELO 当前路线是同一条线，
再创建一个新的 route_versions 版本，把高度贴到 VELO 自己的坐标点上。

操作注意事项：默认 dry-run，不写数据库；只有加 `--apply` 才会真正创建新版。
禁止用它把“看起来差不多”的路线硬补进库，匹配距离超阈值会直接拒绝。

输入输出：输入 route_book_id + 外部轨迹 JSON/分享 routeId；输出回填摘要。
写库时只更新 route_books.current_version_id / elevation_profile / climb，并新增一条 RouteVersion。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.activity.models import Activity  # noqa: F401
from app.database import SessionLocal
from app.route_book.models import RouteBook, RouteVersion, _preview_points_from_wkb, _preview_points_from_wkt
from app.user.models import User  # noqa: F401


IGPSPORT_SHARE_API = "https://prod.zh.igpsport.com/service/mobile/api/Routes/DetailsRoutesShare?routeId={route_id}"


@dataclass(frozen=True)
class ProjectionResult:
    """投影结果——VELO 坐标不动，只补从外部来源找到的高度。"""

    elevation_points: list[list[float | None]]
    matched_point_count: int
    max_match_distance_m: float


@dataclass(frozen=True)
class BackfillResult:
    """回填结果——给命令行和测试看，不暴露内部实现细节。"""

    changed: bool
    route_book_id: int
    old_version_id: int
    new_version_id: int | None
    matched_point_count: int
    max_match_distance_m: float
    climb_m: float | None
    message: str


def parse_igpsport_share_payload(payload: dict) -> list[list[float]]:
    """读取 iGPSPORT 分享接口里的轨迹点；字段 longitute 是对方接口里的真实拼写。"""
    route_info = payload.get("routeInfo")
    if not isinstance(route_info, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            route_info = data.get("routeInfo")
    if not isinstance(route_info, dict):
        raise ValueError("iGPSPORT 响应缺少 routeInfo")

    tracks = route_info.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("iGPSPORT 响应缺少 tracks")

    points: list[list[float]] = []
    for raw in tracks:
        if not isinstance(raw, dict):
            continue
        lon = _finite_float(raw.get("longitute", raw.get("longitude")))
        lat = _finite_float(raw.get("latitude"))
        ele = _finite_float(raw.get("alt", raw.get("elevation")))
        if lon is None or lat is None or ele is None:
            continue
        points.append([lon, lat, ele])

    if len(points) < 2:
        raise ValueError("iGPSPORT 轨迹至少需要 2 个带海拔的点")
    return points


def project_precise_elevation(
    target_points: list[list[float]],
    source_points: list[list[float]],
    *,
    max_distance_m: float,
) -> ProjectionResult:
    """
    把外部海拔投影到 VELO 路线点。

    可以把 source_points 想象成“带高度标签的参考尺”。我们只拿标签，不拿尺子的刻度；
    最终写回的坐标仍然是 target_points，也就是 VELO 自己的路线。
    """
    if len(target_points) < 2:
        raise ValueError("VELO 当前路线至少需要 2 个点")
    if len(source_points) < 2:
        raise ValueError("外部轨迹至少需要 2 个点")
    if max_distance_m <= 0:
        raise ValueError("max_distance_m 必须大于 0")

    projected: list[list[float | None]] = []
    worst_target_to_source_distance = 0.0
    for target in target_points:
        if len(target) < 2:
            raise ValueError("VELO 路线点格式错误")
        target_lon = float(target[0])
        target_lat = float(target[1])
        nearest = _nearest_source_point(target_lon, target_lat, source_points)
        if nearest is None:
            raise ValueError("外部轨迹没有可用海拔点")
        source_lon, source_lat, ele, distance_m = nearest
        worst_target_to_source_distance = max(worst_target_to_source_distance, distance_m)
        if distance_m > max_distance_m:
            raise ValueError(
                f"外部轨迹不是同一条路线：最大允许 {max_distance_m:.1f}m，"
                f"实际最近点距离 {distance_m:.1f}m"
            )
        projected.append([target_lon, target_lat, ele])

    worst_source_to_target_distance = max_source_distance_to_target_line(
        source_points,
        target_points,
    )
    if worst_source_to_target_distance > max_distance_m:
        raise ValueError(
            f"外部轨迹不是同一条路线：外部轨迹偏离 VELO 路线 "
            f"{worst_source_to_target_distance:.1f}m，最大允许 {max_distance_m:.1f}m"
        )

    return ProjectionResult(
        elevation_points=projected,
        matched_point_count=len(projected),
        max_match_distance_m=max(worst_target_to_source_distance, worst_source_to_target_distance),
    )


def apply_elevation_backfill(
    db: Session,
    *,
    route_book_id: int,
    source_points: list[list[float]],
    max_distance_m: float,
    commit: bool = False,
    source_license_note: str | None = None,
) -> BackfillResult:
    """
    给一条 route_book 的当前版本补逐点海拔。

    commit=False 时只验货不写库；commit=True 时只把新版准备在当前事务里，
    最终提交或回滚由调用方负责，避免工具函数偷偷提交调用方手里的其他改动。
    """
    if commit and not source_license_note:
        raise ValueError("写库前必须提供 source_license_note")
    route = (
        db.query(RouteBook)
        .filter(RouteBook.id == route_book_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if route is None:
        raise LookupError("route_book not found")
    if route.current_version_id is None:
        raise ValueError("route_book 没有 current_version_id")

    version = (
        db.query(RouteVersion)
        .filter(RouteVersion.id == route.current_version_id, RouteVersion.route_book_id == route.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if version is None:
        raise LookupError("current route_version not found")

    target_points = reference_points_from_version(version)
    projection = project_precise_elevation(target_points, source_points, max_distance_m=max_distance_m)
    elevation_snapshot = _compact_json(projection.elevation_points)
    climb_m = calculate_climb_from_elevations(projection.elevation_points)
    profile = _compact_json(
        build_elevation_profile(
            target_points,
            projection.elevation_points,
            total_distance_m=version.distance,
        )
    )

    if version.elevation_points_snapshot == elevation_snapshot:
        return BackfillResult(
            changed=False,
            route_book_id=route.id,
            old_version_id=version.id,
            new_version_id=None,
            matched_point_count=projection.matched_point_count,
            max_match_distance_m=projection.max_match_distance_m,
            climb_m=climb_m,
            message="当前版本已经有相同逐点海拔，无需回填",
        )

    if not commit:
        return BackfillResult(
            changed=True,
            route_book_id=route.id,
            old_version_id=version.id,
            new_version_id=None,
            matched_point_count=projection.matched_point_count,
            max_match_distance_m=projection.max_match_distance_m,
            climb_m=climb_m,
            message="dry-run 通过：加 --apply 才会创建新版",
        )

    version.status = "archived"
    new_version = RouteVersion(
        route_book_id=route.id,
        version_no=_next_route_version_no(db, route.id),
        status="current",
        created_by=version.created_by,
        geometry_source=version.geometry_source,
        navigation_status=version.navigation_status,
        reference_line_snapshot=_reference_line_from_points(target_points),
        line_hash=version.line_hash,
        distance=version.distance,
        climb=climb_m,
        elevation_profile=profile,
        elevation_points_snapshot=elevation_snapshot,
        point_count=version.point_count or len(target_points),
        component_snapshot_hash=version.component_snapshot_hash,
        validation_warnings_json=version.validation_warnings_json,
        navigation_metadata_json=_backfill_metadata(version.navigation_metadata_json, source_license_note),
    )
    db.add(new_version)
    db.flush()

    route.current_version_id = new_version.id
    route.climb = climb_m
    route.elevation_profile = profile
    db.flush()

    return BackfillResult(
        changed=True,
        route_book_id=route.id,
        old_version_id=version.id,
        new_version_id=new_version.id,
        matched_point_count=projection.matched_point_count,
        max_match_distance_m=projection.max_match_distance_m,
        climb_m=climb_m,
        message="已创建带精确海拔的新路线版本",
    )


def reference_points_from_version(version: RouteVersion) -> list[list[float]]:
    """从路线版本底片取 VELO 自己的坐标线。"""
    value = version.reference_line_snapshot
    if value is None:
        return []
    if isinstance(value, str):
        return _preview_points_from_wkt(value)
    data = getattr(value, "data", value)
    if isinstance(data, str):
        points = _preview_points_from_wkt(data)
        if points:
            return points
    return _preview_points_from_wkb(data)


def calculate_climb_from_elevations(elevation_points: list[list[float | None]]) -> float | None:
    climb = 0.0
    has_delta = False
    previous: float | None = None
    for point in elevation_points:
        ele = _finite_float(point[2] if len(point) > 2 else None)
        if ele is None:
            previous = None
            continue
        if previous is not None:
            delta = ele - previous
            if delta > 0:
                climb += delta
                has_delta = True
        previous = ele
    return round(climb, 1) if has_delta else 0.0


def build_elevation_profile(
    target_points: list[list[float]],
    elevation_points: list[list[float | None]],
    *,
    total_distance_m: float | None,
    limit: int = 100,
) -> list[list[float | None]]:
    if len(elevation_points) <= limit:
        selected = list(range(len(elevation_points)))
    else:
        step = (len(elevation_points) - 1) / (limit - 1)
        selected = sorted({round(i * step) for i in range(limit)})

    cumulative = _cumulative_distances(target_points)
    profile: list[list[float | None]] = []
    for index in selected:
        raw_distance = cumulative[index] if index < len(cumulative) else 0.0
        distance_m = _scale_distance(raw_distance, cumulative[-1] if cumulative else 0.0, total_distance_m)
        ele = _finite_float(elevation_points[index][2] if len(elevation_points[index]) > 2 else None)
        profile.append([round(distance_m / 1000, 3), round(ele, 1) if ele is not None else None])
    return profile


def load_source_points(args: argparse.Namespace) -> list[list[float]]:
    if args.source_json:
        return parse_igpsport_share_payload(json.loads(Path(args.source_json).read_text(encoding="utf-8")))

    route_id = args.igpsport_route_id
    if args.igpsport_share_url:
        route_id = _route_id_from_share_url(args.igpsport_share_url)
    if route_id:
        return parse_igpsport_share_payload(fetch_igpsport_share_payload(route_id))

    raise ValueError("必须提供 --source-json、--igpsport-route-id 或 --igpsport-share-url")


def fetch_igpsport_share_payload(route_id: str) -> dict:
    url = IGPSPORT_SHARE_API.format(route_id=route_id)
    request = Request(
        url,
        headers={
            "User-Agent": "VELO route elevation backfill/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError(f"iGPSPORT 分享接口读取失败：{exc}") from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill precise elevation points for a VELO route version.")
    parser.add_argument("--route-book-id", type=int, required=True)
    parser.add_argument("--source-json", help="saved iGPSPORT share JSON payload")
    parser.add_argument("--igpsport-route-id", help="iGPSPORT public share routeId")
    parser.add_argument("--igpsport-share-url", help="iGPSPORT public share URL")
    parser.add_argument("--max-distance-m", type=float, default=35.0)
    parser.add_argument("--source-license-note", help="写库前必须说明来源、授权或用户自有数据依据")
    parser.add_argument("--apply", action="store_true", help="write a new route version; default is dry-run")
    args = parser.parse_args(argv)
    if args.apply and not args.source_license_note:
        parser.error("--apply 写库前必须提供 --source-license-note")

    db = SessionLocal()
    try:
        source_points = load_source_points(args)
        result = apply_elevation_backfill(
            db,
            route_book_id=args.route_book_id,
            source_points=source_points,
            max_distance_m=args.max_distance_m,
            commit=args.apply,
            source_license_note=args.source_license_note,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
    except (LookupError, ValueError) as exc:
        db.rollback()
        print(_compact_json({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(
        json.dumps(
            {
                "changed": result.changed,
                "route_book_id": result.route_book_id,
                "old_version_id": result.old_version_id,
                "new_version_id": result.new_version_id,
                "matched_point_count": result.matched_point_count,
                "max_match_distance_m": round(result.max_match_distance_m, 3),
                "climb_m": result.climb_m,
                "message": result.message,
            },
            ensure_ascii=False,
        )
    )


def _nearest_source_point(
    target_lon: float,
    target_lat: float,
    source_points: list[list[float]],
) -> tuple[float, float, float, float] | None:
    nearest: tuple[float, float, float, float] | None = None
    for source in source_points:
        if len(source) < 3:
            continue
        source_lon = _finite_float(source[0])
        source_lat = _finite_float(source[1])
        ele = _finite_float(source[2])
        if source_lon is None or source_lat is None or ele is None:
            continue
        distance_m = haversine_m(target_lon, target_lat, source_lon, source_lat)
        if nearest is None or distance_m < nearest[3]:
            nearest = (source_lon, source_lat, ele, distance_m)
    return nearest


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def max_source_distance_to_target_line(
    source_points: list[list[float]],
    target_points: list[list[float]],
) -> float:
    """反向检查外部轨迹有没有大段绕远，防止只靠起终点蒙混过关。"""
    worst = 0.0
    for source in source_points:
        if len(source) < 2:
            continue
        source_lon = _finite_float(source[0])
        source_lat = _finite_float(source[1])
        if source_lon is None or source_lat is None:
            continue
        worst = max(worst, _point_to_polyline_distance_m(source_lon, source_lat, target_points))
    return worst


def _point_to_polyline_distance_m(lon: float, lat: float, line: list[list[float]]) -> float:
    if not line:
        return math.inf
    if len(line) == 1:
        return haversine_m(lon, lat, float(line[0][0]), float(line[0][1]))

    origin_lat = lat
    origin_lon = lon
    point_xy = _local_xy_m(lon, lat, origin_lon=origin_lon, origin_lat=origin_lat)
    return min(
        _point_to_segment_distance_m(
            point_xy,
            _local_xy_m(float(start[0]), float(start[1]), origin_lon=origin_lon, origin_lat=origin_lat),
            _local_xy_m(float(end[0]), float(end[1]), origin_lon=origin_lon, origin_lat=origin_lat),
        )
        for start, end in zip(line, line[1:])
    )


def _local_xy_m(
    lon: float,
    lat: float,
    *,
    origin_lon: float,
    origin_lat: float,
) -> tuple[float, float]:
    radius_m = 6371000.0
    x = math.radians(lon - origin_lon) * radius_m * math.cos(math.radians(origin_lat))
    y = math.radians(lat - origin_lat) * radius_m
    return x, y


def _point_to_segment_distance_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def _cumulative_distances(points: list[list[float]]) -> list[float]:
    if not points:
        return []
    cumulative = [0.0]
    for prev, curr in zip(points, points[1:]):
        cumulative.append(
            cumulative[-1]
            + haversine_m(float(prev[0]), float(prev[1]), float(curr[0]), float(curr[1]))
        )
    return cumulative


def _scale_distance(raw_distance_m: float, raw_total_m: float, stored_total_m: float | None) -> float:
    stored = _finite_float(stored_total_m)
    if stored is None or stored <= 0 or raw_total_m <= 0:
        return raw_distance_m
    return raw_distance_m / raw_total_m * stored


def _next_route_version_no(db: Session, route_book_id: int) -> int:
    latest = (
        db.query(RouteVersion.version_no)
        .filter(RouteVersion.route_book_id == route_book_id)
        .order_by(RouteVersion.version_no.desc())
        .first()
    )
    return int(latest[0]) + 1 if latest else 1


def _backfill_metadata(existing_json: str | None, source_license_note: str | None) -> str:
    existing: dict = {}
    if existing_json:
        try:
            parsed = json.loads(existing_json)
            if isinstance(parsed, dict):
                existing = parsed
        except json.JSONDecodeError:
            existing = {"previous_navigation_metadata_json": existing_json}
    existing["elevation_backfill"] = {
        "source_license_note": source_license_note,
        "source_policy": "operator_asserted_authorized_precise_source",
    }
    return _compact_json(existing)


def _reference_line_from_points(points: list[list[float]]) -> WKTElement:
    coords = ", ".join(f"{point[0]} {point[1]}" for point in points)
    return WKTElement(f"SRID=4326;LINESTRING({coords})", srid=4326)


def _route_id_from_share_url(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    values = query.get("routeId")
    if not values or not values[0]:
        raise ValueError("iGPSPORT 分享链接缺少 routeId")
    return values[0]


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
