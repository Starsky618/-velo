"""路线逐点海拔回填工具。

三种使用：
1. --export-missing 导出缺海拔的路线点，交给国内合规授权的高程数据源处理。
2. --import-csv 导入供应商返回的逐点海拔，并强制记录 source/license。
3. --backfill-srtm 用项目统一的 SRTM3 公共地形源直接补齐缺海拔路书。

码表导出会信任 `<ele>`，所以数据来源必须可审计：每次写库都要留下
source_name / license_id / accuracy_m。
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func

from app.database import SessionLocal
from app.elevation.dem_client import query_elevations
from app.elevation.route_elevation import build_route_elevation_result_from_values
from app.route_book.elevation_workflow import backfill_route_version_elevation, write_route_elevation_result
from app.route_book.elevation_quality import has_trusted_route_elevation, parse_complete_elevation_snapshot
from app.route_book.models import RouteBook, RouteVersion, _preview_points_from_wkt

COORD_TOLERANCE_DEG = 0.00001
SRTM_SOURCE_NAME = "SRTM3 90m DEM"
SRTM_LICENSE_ID = "CGIAR-CSI SRTM public DEM"
SRTM_ACCURACY_M = 16.0


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
    group.add_argument("--backfill-srtm", action="store_true", help="fill missing route elevations from shared SRTM3 DEM")
    parser.add_argument("--source-name", help="authorized domestic elevation source name")
    parser.add_argument("--license-id", help="license/contract/order id proving legal use")
    parser.add_argument("--accuracy-m", type=float, help="declared vertical accuracy in meters")
    parser.add_argument("--route-book-id", type=int, action="append", help="only backfill selected route book id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.export_missing:
            count = export_missing_points(db, args.export_missing)
            print(f"exported {count} point(s) to {args.export_missing}")
            return

        if args.backfill_srtm:
            count = backfill_missing_with_srtm(
                db,
                source_name=args.source_name or SRTM_SOURCE_NAME,
                license_id=args.license_id or SRTM_LICENSE_ID,
                accuracy_m=args.accuracy_m if args.accuracy_m is not None else SRTM_ACCURACY_M,
                dry_run=args.dry_run,
                route_book_ids=args.route_book_id,
            )
            print(f"{'validated' if args.dry_run else 'updated'} {count} route version(s) from SRTM3")
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
            if has_trusted_route_elevation(
                version.elevation_points_snapshot,
                metadata_json=version.navigation_metadata_json,
                expected_count=len(points),
            ):
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


def backfill_missing_with_srtm(
    db,
    *,
    query_func=query_elevations,
    source_name: str = SRTM_SOURCE_NAME,
    license_id: str = SRTM_LICENSE_ID,
    accuracy_m: float = SRTM_ACCURACY_M,
    dry_run: bool,
    route_book_ids: list[int] | None = None,
) -> int:
    if accuracy_m <= 0:
        raise ValueError("accuracy_m must be positive")

    selected_route_ids = set(route_book_ids or [])
    updated = 0
    for route, version, reference_line_wkt in _current_route_versions(db):
        if selected_route_ids and route.id not in selected_route_ids:
            continue
        points = _points_from_wkt(reference_line_wkt)
        if has_trusted_route_elevation(
            version.elevation_points_snapshot,
            metadata_json=version.navigation_metadata_json,
            expected_count=len(points),
        ):
            continue
        backfill_route_version_elevation(
            db,
            version.id,
            query_func=query_func,
            source_name=source_name,
            license_id=license_id,
            accuracy_m=accuracy_m,
            dry_run=dry_run,
            commit=False,
        )
        updated += 1
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return updated


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

        result = build_route_elevation_result_from_values(
            route_points,
            [point.elevation_m for point in imported_points],
        )
        write_route_elevation_result(
            db,
            route=route,
            version=version,
            result=result,
            source_name=source_name,
            license_id=license_id,
            accuracy_m=accuracy_m,
            method="authorized_point_elevation_csv_v1",
            timestamp_field="imported_at",
        )
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


if __name__ == "__main__":
    main()
