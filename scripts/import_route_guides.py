"""路线百科灌库脚本——把 content/routes 里的路线手册搬进数据库。

操作注意事项：先完整校验文件，再打开数据库；这样 guide.md 或 meta.json 有错时不会写半截数据。
输入是每条路线一个文件夹，输出是 route_guides 记录；有 track.gpx 时额外生成官方 route_book。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from geoalchemy2 import WKTElement

from app.activity.models import Activity  # noqa: F401
from app.database import SessionLocal
from app.elevation.dem_client import (
    GLO30_HORIZONTAL_RESOLUTION_M,
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_ACCURACY_M,
    query_elevations,
)
from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    build_route_elevation_result,
    route_elevation_metadata,
)
from app.parsing.geo_math import haversine
from app.parsing.gpx_parser import GPXParser
from app.parsing.types import Trackpoint
from app.route_book.elevation_workflow import write_route_elevation_result
from app.route_book.models import (
    RouteBook,
    RouteGuide,
    RouteVersion,
    _preview_points_from_wkt,
)  # noqa: F401
from app.route_book.service import (
    _elevation_points_snapshot_from_points,
    _line_hash,
    _point_count_from_wkt,
    create_initial_route_version,
)
from app.user.models import User  # noqa: F401


@dataclass(frozen=True)
class RouteInput:
    """单条待灌路线——像一张已经验过内容的入库单。"""

    route_dir: Path
    name: str
    city: str
    content_md: str
    source_ref: str | None
    highlights: str | None
    cover_url: str | None
    gallery_urls: str | None
    track_path: Path | None
    distance_override_m: float | None
    climb_override_m: float | None


@dataclass(frozen=True)
class ParsedTrack:
    """GPX 解析结果；原文件海拔只供校验，产品路线会重新生成统一 GLO 结果。"""

    distance: float
    climb: float | None
    reference_line: str
    elevation_profile: str | None
    elevation_points_snapshot: str | None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import official route guides into VELO database.")
    parser.add_argument("--content-dir", default="content/routes", help="route guide directory")
    parser.add_argument("--dry-run", action="store_true", help="print actions without DB writes")
    args = parser.parse_args(argv)

    routes = load_routes(Path(args.content_dir))
    if args.dry_run:
        print_dry_run(routes)
        return

    db = SessionLocal()
    try:
        for route in routes:
            upsert_route(db, route)
            db.commit()
    finally:
        db.close()


def load_routes(content_dir: Path) -> list[RouteInput]:
    """把路线文件夹读成入库单；任何一条坏了，都在进 DB 前拦住。"""
    if not content_dir.exists():
        _die(f"content directory not found: {content_dir}")

    routes: list[RouteInput] = []
    for route_dir in sorted(path for path in content_dir.iterdir() if path.is_dir()):
        guide_path = route_dir / "guide.md"
        meta_path = route_dir / "meta.json"
        if not guide_path.exists():
            _die(f"{route_dir}: guide.md missing")
        if not meta_path.exists():
            _die(f"{route_dir}: meta.json missing")

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _die(f"{route_dir}: meta.json invalid JSON: {exc}")

        name = meta.get("name")
        if not isinstance(name, str) or not name.strip():
            _die(f"{route_dir}: meta.json field 'name' is required")

        highlights = _load_highlights(route_dir, meta)
        cover_url = meta.get("cover_url")
        if cover_url is not None and not isinstance(cover_url, str):
            _die(f"{route_dir}: meta.json field 'cover_url' must be a string")
        source_ref = meta.get("source_ref")
        if source_ref is not None and not isinstance(source_ref, str):
            _die(f"{route_dir}: meta.json field 'source_ref' must be a string")
        gallery_urls = _load_gallery_urls(route_dir, meta)

        distance_km = _numeric_meta_value(meta, "distance_km")
        climb_m = _numeric_meta_value(meta, "climb_m")
        track_path = route_dir / "track.gpx"
        routes.append(
            RouteInput(
                route_dir=route_dir,
                name=name.strip(),
                city=meta.get("city") or "太原",  # spec §3.6：city 可选，默认太原
                content_md=guide_path.read_text(encoding="utf-8"),
                source_ref=source_ref.strip() if isinstance(source_ref, str) and source_ref.strip() else None,
                highlights=highlights,
                cover_url=cover_url,
                gallery_urls=gallery_urls,
                track_path=track_path if track_path.exists() else None,
                distance_override_m=distance_km * 1000 if distance_km is not None else None,
                climb_override_m=climb_m,
            )
        )
    return routes


def _numeric_meta_value(meta: dict, field: str) -> float | None:
    raw = meta.get(field)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _load_highlights(route_dir: Path, meta: dict) -> str | None:
    # highlights 是可选字段（spec §3.6：必填只有 name）——缺省返回 None 存 NULL，
    # 前端整块隐藏；只对"存在但不是合法 JSON 数组"报错退出（高危双审 C1 修正）。
    if "highlights" not in meta:
        return None

    raw = meta["highlights"]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            _die(f"{route_dir}: highlights must be a JSON array string: {exc}")
        highlights_text = raw
    elif isinstance(raw, list):
        parsed = raw
        highlights_text = json.dumps(raw, ensure_ascii=False)
    else:
        _die(f"{route_dir}: highlights must be a JSON array string")

    if not isinstance(parsed, list):
        _die(f"{route_dir}: highlights must json.loads() to a list")
    return highlights_text


def _load_gallery_urls(route_dir: Path, meta: dict) -> str | None:
    # 实景图也是可选字段——缺省返回 None 存 NULL（老路线没图不报错）。
    # 发布脚本写进 meta.json 的是真 JSON 数组，所以这里只认"字符串元素的 list"，
    # 与 highlights 同纪律：发现坏数据在打开数据库之前拦住。
    if "gallery_urls" not in meta:
        return None

    raw = meta["gallery_urls"]
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        _die(f"{route_dir}: gallery_urls must be a list of strings")
    return json.dumps(raw, ensure_ascii=False) if raw else None


def print_dry_run(routes: list[RouteInput]) -> None:
    print(f"DRY RUN: {len(routes)} route guide(s)")
    for route in routes:
        if route.track_path is None:
            print(f"- {route.name}: status=track_pending, would create/update guide only")
        else:
            print(f"- {route.name}: would create/update route_book from {route.track_path}")


def upsert_route(db, route: RouteInput) -> None:
    guide = db.query(RouteGuide).filter(RouteGuide.name == route.name).first()
    route_book_id = None
    route_book = None
    elevation_profile = None

    if route.track_path is not None:
        parsed = parse_track(
            route.track_path,
            distance_override_m=route.distance_override_m,
            climb_override_m=route.climb_override_m,
        )
        elevation_result = build_route_elevation_result(
            _preview_points_from_wkt(parsed.reference_line),
            query_func=query_elevations,
        )
        if guide is not None and guide.route_book_id is not None:
            route_book = db.query(RouteBook).filter(RouteBook.id == guide.route_book_id).first()
        if route_book is None:
            route_book = RouteBook()
            db.add(route_book)
        # 先把全部字段赋完再 flush：name/distance/reference_line/source 都是 NOT NULL 无默认，
        # 先 flush 会让 INSERT 带着一排 NULL 直接撞约束——SQLite 简化表测不出，生产 PG 必炸
        # （高危双审 C1：本地两层盾牌掩盖的生产事故位）。
        apply_route_book(route_book, route, parsed)
        db.flush()
        if route_book.current_version_id is None:
            version = create_initial_route_version(
                db,
                route_book,
                reference_line_wkt=parsed.reference_line,
                geometry_source="file_upload",
                created_by=None,
            )
        else:
            version = refresh_current_route_version(db, route_book, parsed)
        write_route_elevation_result(
            db,
            route=route_book,
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
        route_book_id = route_book.id
        elevation_profile = route_book.elevation_profile

    if guide is None:
        guide = RouteGuide(name=route.name)
        db.add(guide)

    guide.city = route.city
    guide.content_md = route.content_md
    guide.cover_url = route.cover_url
    guide.gallery_urls = route.gallery_urls
    guide.highlights = route.highlights
    guide.route_book_id = route_book_id
    guide.elevation_profile = elevation_profile
    guide.source_ref = route.source_ref
    guide.content_hash = content_hash(route.content_md)
    guide.imported_at = datetime.now(timezone.utc)
    guide.content_origin = "content_routes_import"
    guide.source_route_version_id = route_book.current_version_id if route_book is not None else None


def content_hash(content_md: str) -> str:
    """给导入后的正文算指纹；像快递单号一样，用来判断 DB 投影是否还是这份 guide.md。"""
    return hashlib.sha256(content_md.encode("utf-8")).hexdigest()


def parse_track(
    track_path: Path,
    distance_override_m: float | None = None,
    climb_override_m: float | None = None,
) -> ParsedTrack:
    result = GPXParser().parse(track_path.read_bytes())
    points = result.trackpoints
    cumulative = cumulative_distances(points)
    has_elevation = any(point.ele is not None for point in points)
    return ParsedTrack(
        distance=distance_override_m if distance_override_m is not None else (cumulative[-1] if cumulative else 0.0),
        climb=climb_override_m if climb_override_m is not None else calculate_climb(points),
        reference_line=build_linestring(points),
        elevation_profile=(
            json.dumps(downsample_elevation(points, cumulative), ensure_ascii=False) if has_elevation else None
        ),
        elevation_points_snapshot=build_elevation_points_snapshot(points),
    )


def refresh_current_route_version(db, route_book: RouteBook, parsed: ParsedTrack) -> RouteVersion:
    """
    重灌官方路线时刷新当前版本底片。

    路书像一本会被重新校对的官方手册：内容文件重跑后，route_book 和
    route_version 必须一起换成同一份轨迹底片，否则导出会继续拿旧数据。
    """
    version = (
        db.query(RouteVersion)
        .filter(RouteVersion.id == route_book.current_version_id, RouteVersion.route_book_id == route_book.id)
        .first()
    )
    if version is None:
        return create_initial_route_version(
            db,
            route_book,
            reference_line_wkt=parsed.reference_line,
            geometry_source="file_upload",
            created_by=None,
            elevation_profile=parsed.elevation_profile,
            elevation_points_snapshot=parsed.elevation_points_snapshot,
        )

    line_hash = _line_hash(parsed.reference_line)
    route_book.line_hash = line_hash
    route_book.elevation_profile = None
    version.geometry_source = "file_upload"
    version.navigation_status = "ready"
    version.reference_line_snapshot = WKTElement(parsed.reference_line, srid=4326)
    version.line_hash = line_hash
    version.distance = parsed.distance
    version.climb = None
    version.elevation_profile = None
    version.elevation_points_snapshot = None
    version.point_count = _point_count_from_wkt(parsed.reference_line)
    return version


def apply_route_book(route_book: RouteBook, route: RouteInput, parsed: ParsedTrack) -> None:
    route_book.creator_id = None
    route_book.name = route.name
    route_book.distance = parsed.distance
    route_book.climb = None
    # WKTElement 是项目既有惯例（route_book/service.py 三处同写法）——
    # 裸 EWKT 字符串靠 geoalchemy2 的隐式识别，非推荐路径且与惯例漂移（高危双审 I2）
    route_book.reference_line = WKTElement(parsed.reference_line, srid=4326)
    route_book.file_id = str(route.track_path)
    route_book.file_type = "gpx"
    route_book.source = "file_upload"
    route_book.source_activity_id = None
    route_book.city = "taiyuan"
    route_book.is_official = True
    route_book.visibility = "public"
    route_book.publish_status = "published"


def cumulative_distances(points: list[Trackpoint]) -> list[float]:
    if not points:
        return []
    distances = [0.0]
    total = 0.0
    for prev, curr in zip(points, points[1:]):
        total += haversine(prev.lat, prev.lon, curr.lat, curr.lon)
        distances.append(total)
    return distances


def calculate_climb(points: list[Trackpoint]) -> float | None:
    if not any(point.ele is not None for point in points):
        return None

    climb = 0.0
    for prev, curr in zip(points, points[1:]):
        if prev.ele is None or curr.ele is None:
            continue
        delta = curr.ele - prev.ele
        if delta > 0:
            climb += delta
    return climb


def build_linestring(points: list[Trackpoint]) -> str:
    pairs = ", ".join(f"{point.lon} {point.lat}" for point in points)
    return f"SRID=4326;LINESTRING({pairs})"


def build_elevation_points_snapshot(points: list[Trackpoint]) -> str | None:
    route_points = [
        {"lat": point.lat, "lon": point.lon, "ele": point.ele}
        for point in points
        if point.lat is not None and point.lon is not None
    ]
    return _elevation_points_snapshot_from_points(route_points)


def downsample_elevation(points: list[Trackpoint], cumulative: list[float], limit: int = 100) -> list[list[float | None]]:
    if not points:
        return []
    if len(points) <= limit:
        return [_profile_point(distance, point) for distance, point in zip(cumulative, points)]

    total = cumulative[-1]
    selected: list[int] = [0]
    cursor = 1
    for step in range(1, limit - 1):
        target = total * step / (limit - 1)
        while cursor < len(cumulative) - 1 and cumulative[cursor] < target:
            cursor += 1
        before = max(cursor - 1, 0)
        after = cursor
        chosen = before if abs(cumulative[before] - target) <= abs(cumulative[after] - target) else after
        if chosen != selected[-1]:
            selected.append(chosen)
    if selected[-1] != len(points) - 1:
        selected.append(len(points) - 1)

    return [_profile_point(cumulative[index], points[index]) for index in selected]


def _profile_point(distance_m: float, point: Trackpoint) -> list[float | None]:
    elevation = round(point.ele, 1) if point.ele is not None else None
    return [round(distance_m / 1000, 3), elevation]


def _die(message: str) -> None:
    print(f"ERROR: {message}")
    sys.exit(1)


if __name__ == "__main__":
    main()
