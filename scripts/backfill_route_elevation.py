"""路线逐点海拔回填工具。

两步使用：
1. --export-missing 导出缺海拔的路线点，交给国内合规授权的高程数据源处理。
2. --import-csv 导入供应商返回的逐点海拔，并强制记录 source/license。

这个脚本故意不内置国外 DEM 或未授权 API。码表导出会信任 `<ele>`，所以数据
来源必须可审计：每次写库都要留下 source_name / license_id / accuracy_m。
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, inspect

from app.database import SessionLocal
from app.parsing.geo_math import haversine
from app.route_book.elevation_quality import parse_complete_elevation_snapshot
from app.route_book.models import RouteBook, RouteGuide, RouteVersion, _preview_points_from_wkt

COORD_TOLERANCE_DEG = 0.00001
PROFILE_LIMIT = 100


@dataclass(frozen=True)
class ElevationPoint:
    route_version_id: int
    seq: int
    lon: float
    lat: float
    elevation_m: float


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill route_versions.elevation_points_snapshot")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export-missing", type=Path, help="write missing route points CSV")
    group.add_argument("--import-csv", type=Path, help="read authorized elevation CSV")
    parser.add_argument("--source-name", help="authorized domestic elevation source name")
    parser.add_argument("--license-id", help="license/contract/order id proving legal use")
    parser.add_argument("--accuracy-m", type=float, help="declared vertical accuracy in meters")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.export_missing:
            count = export_missing_points(db, args.export_missing)
            print(f"exported {count} point(s) to {args.export_missing}")
            return

        if not args.source_name or not args.license_id or args.accuracy_m is None:
            raise SystemExit("--import-csv requires --source-name, --license-id and --accuracy-m")
        count = import_elevation_csv(
            db,
            args.import_csv,
            source_name=args.source_name,
            license_id=args.license_id,
            accuracy_m=args.accuracy_m,
            dry_run=args.dry_run,
        )
        print(f"{'validated' if args.dry_run else 'updated'} {count} route version(s)")
    finally:
        db.close()


def export_missing_points(db, output_path: Path) -> int:
    rows = _current_route_versions(db)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["route_book_id", "route_version_id", "seq", "lon", "lat"])
        writer.writeheader()
        for route, version, reference_line_wkt in rows:
            points = _points_from_wkt(reference_line_wkt)
            if parse_complete_elevation_snapshot(version.elevation_points_snapshot, expected_count=len(points)):
                continue
            for seq, (lon, lat) in enumerate(points):
                writer.writerow(
                    {
                        "route_book_id": route.id,
                        "route_version_id": version.id,
                        "seq": seq,
                        "lon": lon,
                        "lat": lat,
                    }
                )
                count += 1
    return count


def import_elevation_csv(
    db,
    input_path: Path,
    *,
    source_name: str,
    license_id: str,
    accuracy_m: float,
    dry_run: bool,
) -> int:
    if accuracy_m <= 0:
        raise ValueError("accuracy_m must be positive")
    grouped = _read_elevation_csv(input_path)
    updated = 0
    now = datetime.now(timezone.utc)

    for version_id, imported_points in grouped.items():
        row = (
            db.query(RouteBook, RouteVersion, func.ST_AsText(RouteVersion.reference_line_snapshot))
            .join(RouteVersion, RouteBook.current_version_id == RouteVersion.id)
            .filter(RouteVersion.id == version_id, RouteVersion.route_book_id == RouteBook.id)
            .first()
        )
        if row is None:
            raise LookupError(f"route version not found or not current: {version_id}")
        route, version, reference_line_wkt = row
        route_points = _points_from_wkt(reference_line_wkt)
        _assert_points_match(version.id, route_points, imported_points)

        snapshot = [[lon, lat, point.elevation_m] for (lon, lat), point in zip(route_points, imported_points)]
        profile = _downsample_profile(route_points, [point.elevation_m for point in imported_points])
        climb = _calculate_climb([point.elevation_m for point in imported_points])
        metadata = _merged_navigation_metadata(
            version.navigation_metadata_json,
            source_name=source_name,
            license_id=license_id,
            accuracy_m=accuracy_m,
            imported_at=now,
            point_count=len(snapshot),
        )

        version.elevation_points_snapshot = json.dumps(snapshot, ensure_ascii=False)
        version.elevation_profile = json.dumps(profile, ensure_ascii=False)
        version.climb = climb
        version.navigation_metadata_json = json.dumps(metadata, ensure_ascii=False)
        route.elevation_profile = version.elevation_profile
        route.climb = climb
        _update_route_guides(db, route.id, version.elevation_profile)
        updated += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return updated


def _current_route_versions(db):
    return (
        db.query(RouteBook, RouteVersion, func.ST_AsText(RouteVersion.reference_line_snapshot))
        .join(RouteVersion, RouteBook.current_version_id == RouteVersion.id)
        .filter(RouteVersion.route_book_id == RouteBook.id)
        .order_by(RouteBook.id.asc())
        .all()
    )


def _update_route_guides(db, route_book_id: int, elevation_profile: str) -> None:
    if not inspect(db.bind).has_table("route_guides"):
        return
    guides = db.query(RouteGuide).filter(RouteGuide.route_book_id == route_book_id).all()
    for guide in guides:
        guide.elevation_profile = elevation_profile


def _read_elevation_csv(input_path: Path) -> dict[int, list[ElevationPoint]]:
    grouped: dict[int, list[ElevationPoint]] = {}
    with input_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            point = ElevationPoint(
                route_version_id=int(row["route_version_id"]),
                seq=int(row["seq"]),
                lon=float(row["lon"]),
                lat=float(row["lat"]),
                elevation_m=float(row["elevation_m"]),
            )
            grouped.setdefault(point.route_version_id, []).append(point)
    for points in grouped.values():
        points.sort(key=lambda point: point.seq)
    return grouped


def _points_from_wkt(reference_line_wkt: str) -> list[list[float]]:
    points = _preview_points_from_wkt(reference_line_wkt)
    if len(points) < 2:
        raise ValueError("route version line must have at least 2 points")
    return points


def _assert_points_match(
    version_id: int,
    route_points: list[list[float]],
    imported_points: list[ElevationPoint],
) -> None:
    if len(route_points) != len(imported_points):
        raise ValueError(f"route version {version_id}: point count mismatch")
    expected_seq = list(range(len(route_points)))
    actual_seq = [point.seq for point in imported_points]
    if actual_seq != expected_seq:
        raise ValueError(f"route version {version_id}: seq must be continuous from 0")
    for (lon, lat), point in zip(route_points, imported_points):
        if abs(lon - point.lon) > COORD_TOLERANCE_DEG or abs(lat - point.lat) > COORD_TOLERANCE_DEG:
            raise ValueError(f"route version {version_id}: coordinate mismatch at seq {point.seq}")
    snapshot = [[point.lon, point.lat, point.elevation_m] for point in imported_points]
    if parse_complete_elevation_snapshot(json.dumps(snapshot), expected_count=len(snapshot)) is None:
        raise ValueError(f"route version {version_id}: invalid elevation values")


def _calculate_climb(elevations: list[float]) -> float:
    climb = 0.0
    for prev, curr in zip(elevations, elevations[1:]):
        delta = curr - prev
        if delta > 0:
            climb += delta
    return round(climb, 1)


def _downsample_profile(points: list[list[float]], elevations: list[float]) -> list[list[float]]:
    cumulative = _cumulative_distances(points)
    if len(points) <= PROFILE_LIMIT:
        return [[round(distance / 1000, 3), round(ele, 1)] for distance, ele in zip(cumulative, elevations)]

    total = cumulative[-1]
    selected: list[int] = [0]
    cursor = 1
    for step in range(1, PROFILE_LIMIT - 1):
        target = total * step / (PROFILE_LIMIT - 1)
        while cursor < len(cumulative) - 1 and cumulative[cursor] < target:
            cursor += 1
        before = max(cursor - 1, 0)
        after = cursor
        chosen = before if abs(cumulative[before] - target) <= abs(cumulative[after] - target) else after
        if chosen != selected[-1]:
            selected.append(chosen)
    if selected[-1] != len(points) - 1:
        selected.append(len(points) - 1)
    return [[round(cumulative[index] / 1000, 3), round(elevations[index], 1)] for index in selected]


def _cumulative_distances(points: list[list[float]]) -> list[float]:
    distances = [0.0]
    total = 0.0
    for prev, curr in zip(points, points[1:]):
        total += haversine(prev[1], prev[0], curr[1], curr[0])
        distances.append(total)
    return distances


def _merged_navigation_metadata(
    value: str | None,
    *,
    source_name: str,
    license_id: str,
    accuracy_m: float,
    imported_at: datetime,
    point_count: int,
) -> dict:
    try:
        metadata = json.loads(value) if value else {}
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["elevation"] = {
        "source_name": source_name,
        "license_id": license_id,
        "accuracy_m": accuracy_m,
        "imported_at": imported_at.isoformat(),
        "point_count": point_count,
        "method": "authorized_point_elevation_csv_v1",
    }
    return metadata


if __name__ == "__main__":
    main()
