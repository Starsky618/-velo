"""虚拟路书海拔实验——用假 GPX 批量验一遍“导入、补海拔、导出”是否连得上。

操作注意事项：这个脚本不碰生产数据库，也不读真实用户文件。它像一间实验室：随机造
100 条路线，走真实解析器和真实导出器，中间海拔查询默认走项目统一 GLO-30 入口和
VELO ``glo30_meaningful_ascent_v1`` 成品剖面算法。

输入输出：输入实验数量和随机种子，输出 JSON 报告；每条路线必须能从唯一参考线
派生 canonical 网格，并把网格与全部原始转弯顶点合并后等量导出 GPX <ele> 和
TCX AltitudeMeters，才算通过。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from math import asin, atan2, cos, degrees, radians, sin
import random
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from geoalchemy2 import WKTElement
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, Text, create_engine, event, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.elevation.dem_client import (
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_ACCURACY_M,
    query_elevations,
)
from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    ElevationQuery,
    route_elevation_metadata,
)
from app.parsing.geo_math import haversine
from app.parsing.gpx_parser import GPXParser
from app.route_book.export_generator import generate_route_export
from app.route_book.elevation_workflow import backfill_route_version_elevation
from app.route_book.models import RouteBook, RouteVersion
from app.route_book.service import create_initial_route_version


TAIYUAN_CENTER = (37.8706, 112.5489)
DEFAULT_COUNT = 100
DEFAULT_POINTS_PER_ROUTE = 48
DEFAULT_SEED = 20260630
GPX_NS = {"g": "http://www.topografix.com/GPX/1/1"}
TCX_NS = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
_EXPERIMENT_SESSION_MARKER_KEY = "velo_owned_experiment_session"
_EXPERIMENT_SESSION_MARKER = object()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run virtual GPX -> GLO-30 + VELO elevation -> route export experiment"
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--points-per-route", type=int, default=DEFAULT_POINTS_PER_ROUTE)
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args(argv)

    report = run_experiment(
        count=args.count,
        seed=args.seed,
        points_per_route=args.points_per_route,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    if report["failed"] > 0:
        raise SystemExit(1)


def run_experiment(
    *,
    count: int = DEFAULT_COUNT,
    seed: int = DEFAULT_SEED,
    points_per_route: int = DEFAULT_POINTS_PER_ROUTE,
    query_func: ElevationQuery = query_elevations,
) -> dict:
    if count <= 0:
        raise ValueError("count must be positive")
    if points_per_route < 2:
        raise ValueError("points_per_route must be at least 2")

    with _experiment_db_session() as session:
        return _run_experiment_with_db(
            session,
            count=count,
            seed=seed,
            points_per_route=points_per_route,
            query_func=query_func,
        )


def _run_experiment_with_db(
    db,
    *,
    count: int,
    seed: int,
    points_per_route: int,
    query_func: ElevationQuery,
) -> dict:
    _assert_owned_experiment_session(db)
    rng = random.Random(seed)
    items = []
    succeeded = 0
    failed = 0

    for index in range(count):
        route_name = f"virtual-route-{index + 1:03d}"
        expected_points = _random_route_points(rng, points_per_route)
        gpx_bytes = _build_virtual_gpx(route_name, expected_points)

        try:
            parsed = GPXParser().parse(gpx_bytes)
            points = [[point.lon, point.lat] for point in parsed.trackpoints]
            route, version = _import_virtual_route(db, route_name, points, parsed.summary.distance)
            backfill_route_version_elevation(
                db,
                version.id,
                query_func=query_func,
                source_name=GLO30_SOURCE_NAME,
                license_id=GLO30_LICENSE_ID,
                accuracy_m=GLO30_VERTICAL_ACCURACY_M,
                method=ROUTE_ELEVATION_METHOD,
                extra_metadata=route_elevation_metadata(),
                dry_run=False,
            )
            db.refresh(version)
            reference_line_wkt = (
                db.query(func.ST_AsText(RouteVersion.reference_line_snapshot))
                .filter(RouteVersion.id == version.id)
                .scalar()
            )
            snapshot_points = json.loads(version.elevation_points_snapshot)
            grid_points = json.loads(version.elevation_grid_snapshot)["points"]
            exported_gpx = generate_route_export(
                route_name=route.name,
                reference_line_snapshot=reference_line_wkt,
                elevation_points_snapshot=version.elevation_points_snapshot,
                elevation_grid_snapshot=version.elevation_grid_snapshot,
                reference_line_hash=version.line_hash,
                elevation_metadata_json=version.navigation_metadata_json,
                export_format="gpx",
            )
            exported_tcx = generate_route_export(
                route_name=route.name,
                reference_line_snapshot=reference_line_wkt,
                elevation_points_snapshot=version.elevation_points_snapshot,
                elevation_grid_snapshot=version.elevation_grid_snapshot,
                reference_line_hash=version.line_hash,
                elevation_metadata_json=version.navigation_metadata_json,
                export_format="tcx",
            )
            gpx_ele_count = _count_gpx_ele(exported_gpx.content)
            tcx_altitude_count = _count_tcx_altitude(exported_tcx.content)
            ok = (
                len(points) == len(expected_points)
                and len(snapshot_points) == len(points)
                and gpx_ele_count == exported_gpx.point_count
                and tcx_altitude_count == exported_tcx.point_count
                and gpx_ele_count == tcx_altitude_count
                and len(grid_points) <= gpx_ele_count <= len(grid_points) + len(points)
            )
            items.append(
                {
                    "route": route_name,
                    "point_count": len(points),
                    "distance_m": round(_distance(points), 1),
                    "climb_m": version.climb,
                    "gpx_ele_count": gpx_ele_count,
                    "tcx_altitude_count": tcx_altitude_count,
                    "canonical_point_count": len(grid_points),
                    "export_point_count": exported_gpx.point_count,
                    "ok": ok,
                }
            )
            succeeded += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception as exc:
            failed += 1
            items.append(
                {
                    "route": route_name,
                    "point_count": len(expected_points),
                    "ok": False,
                    "error": str(exc),
                }
            )

    return {
        "total": count,
        "succeeded": succeeded,
        "failed": failed,
        "seed": seed,
        "points_per_route": points_per_route,
        "elevation_contract": {
            "source": GLO30_SOURCE_NAME,
            "method": ROUTE_ELEVATION_METHOD,
            **route_elevation_metadata(),
        },
        "items": items,
    }


def _import_virtual_route(db, route_name: str, points: list[list[float]], distance_m: float):
    wkt = _wkt_from_points(points)
    route = RouteBook(
        name=route_name,
        distance=float(distance_m or _distance(points)),
        climb=None,
        reference_line=WKTElement(wkt, srid=4326),
        source="file_upload",
        file_id=f"virtual/{route_name}.gpx",
        file_type="gpx",
        city="taiyuan",
        visibility="public",
        publish_status="published",
    )
    db.add(route)
    db.flush()
    version = create_initial_route_version(
        db,
        route,
        reference_line_wkt=wkt,
        geometry_source="file_upload",
        created_by=None,
        elevation_points_snapshot=None,
    )
    db.commit()
    return route, version


def _random_route_points(rng: random.Random, count: int) -> list[tuple[float, float]]:
    start_lat = TAIYUAN_CENTER[0] + rng.uniform(-0.08, 0.08)
    start_lon = TAIYUAN_CENTER[1] + rng.uniform(-0.08, 0.08)
    heading = rng.uniform(0, 360)
    step_m = rng.uniform(80, 320)

    points: list[tuple[float, float]] = []
    lat = start_lat
    lon = start_lon
    for _index in range(count):
        points.append((lat, lon))
        heading += rng.uniform(-18, 18)
        lat, lon = _move_point(lat, lon, heading, step_m * rng.uniform(0.75, 1.25))
    return points


def _move_point(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    radius = 6_371_000.0
    bearing = radians(bearing_deg)
    lat1 = radians(lat)
    lon1 = radians(lon)
    angular = distance_m / radius

    lat2 = _asin_safe(sin(lat1) * cos(angular) + cos(lat1) * sin(angular) * cos(bearing))
    lon2 = lon1 + atan2(
        sin(bearing) * sin(angular) * cos(lat1),
        cos(angular) - sin(lat1) * sin(lat2),
    )
    return (degrees(lat2), degrees(lon2))


def _asin_safe(value: float) -> float:
    return asin(max(-1.0, min(1.0, value)))


def _build_virtual_gpx(route_name: str, points: list[tuple[float, float]]) -> bytes:
    start = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc)
    trackpoints = []
    for index, (lat, lon) in enumerate(points):
        timestamp = (start + timedelta(seconds=index * 10)).isoformat().replace("+00:00", "Z")
        trackpoints.append(
            f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}"><time>{timestamp}</time></trkpt>'
        )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="VELO virtual experiment" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>{route_name}</name>
    <trkseg>
{chr(10).join(trackpoints)}
    </trkseg>
  </trk>
</gpx>
"""
    return xml.encode("utf-8")


def _wkt_from_points(points: list[list[float]]) -> str:
    coords = ", ".join(f"{lon} {lat}" for lon, lat in points)
    return f"SRID=4326;LINESTRING({coords})"


def _count_gpx_ele(content: bytes) -> int:
    root = ET.fromstring(content)
    return len(root.findall(".//g:trkpt/g:ele", GPX_NS))


def _count_tcx_altitude(content: bytes) -> int:
    root = ET.fromstring(content)
    return len(root.findall(".//t:Trackpoint/t:AltitudeMeters", TCX_NS))


def _distance(points: list[list[float]]) -> float:
    total = 0.0
    for prev, curr in zip(points, points[1:]):
        total += haversine(prev[1], prev[0], curr[1], curr[0])
    return total


def _assert_owned_experiment_session(db) -> None:
    if getattr(db, "info", {}).get(_EXPERIMENT_SESSION_MARKER_KEY) is not _EXPERIMENT_SESSION_MARKER:
        raise RuntimeError("experiment runner only accepts its script-owned SQLite in-memory session")

    bind = db.get_bind()
    if (
        bind.dialect.name != "sqlite"
        or bind.url.database != ":memory:"
        or not isinstance(bind.pool, StaticPool)
    ):
        raise RuntimeError("experiment runner only accepts its script-owned SQLite in-memory session")


@contextmanager
def _experiment_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_fake_postgis(dbapi_conn, _connection_record):
        fake_ewkb = "0102000020E6100000020000003333333333235C408FC2F5285CEF42403333333333235C400000000000F04240"
        dbapi_conn.create_function("GeomFromEWKT", 1, lambda x: x)
        dbapi_conn.create_function("ST_GeomFromEWKT", 1, lambda x: x)
        dbapi_conn.create_function("AsEWKB", 1, lambda _x: fake_ewkb)
        dbapi_conn.create_function("ST_AsEWKB", 1, lambda _x: fake_ewkb)
        dbapi_conn.create_function("ST_AsText", 1, lambda x: x)

    metadata = MetaData()
    Table(
        "route_books",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("creator_id", Integer),
        Column("name", String(128), nullable=False),
        Column("distance", Float, nullable=False),
        Column("climb", Float),
        Column("reference_line", Text),
        Column("file_id", String(512)),
        Column("file_type", String(8)),
        Column("source", String(32), nullable=False),
        Column("source_activity_id", Integer),
        Column("city", String(32), nullable=False),
        Column("is_official", Integer),
        Column("created_at", DateTime(timezone=True)),
        Column("updated_at", DateTime(timezone=True)),
        Column("visibility", String(16), nullable=False),
        Column("publish_status", String(16), nullable=False),
        Column("line_hash", String(64)),
        Column("elevation_profile", Text),
        Column("current_version_id", Integer),
    )
    Table(
        "route_versions",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("route_book_id", Integer, nullable=False),
        Column("version_no", Integer, nullable=False),
        Column("status", String(16), nullable=False),
        Column("created_by", Integer),
        Column("geometry_source", String(32), nullable=False),
        Column("navigation_status", String(16), nullable=False),
        Column("reference_line_snapshot", Text, nullable=False),
        Column("line_hash", String(64), nullable=False),
        Column("distance", Float, nullable=False),
        Column("climb", Float),
        Column("elevation_profile", Text),
        Column("elevation_points_snapshot", Text),
        Column("elevation_grid_snapshot", Text),
        Column("point_count", Integer),
        Column("component_snapshot_hash", String(64)),
        Column("validation_warnings_json", Text),
        Column("navigation_metadata_json", Text),
        Column("created_at", DateTime(timezone=True)),
    )
    metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    session = Session()
    session.info[_EXPERIMENT_SESSION_MARKER_KEY] = _EXPERIMENT_SESSION_MARKER
    try:
        yield session
    finally:
        session.close()
        metadata.drop_all(bind=engine)


if __name__ == "__main__":
    main()
