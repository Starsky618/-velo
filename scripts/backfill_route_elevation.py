"""路线逐点海拔回填工具。

三种使用：
1. --export-missing 导出缺海拔的路线点，交给国内合规授权的高程数据源处理。
2. --import-csv 导入供应商返回的逐点海拔，并强制记录 source/license。
3. --backfill-glo 用项目统一的 Copernicus GLO-30 底座补齐或替换旧海拔路书。

码表导出会信任 `<ele>`，所以数据来源必须可审计：每次写库都要留下
source_name / license_id / accuracy_m。
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, inspect

from app.database import SessionLocal
from app.elevation.dem_client import (
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_ACCURACY_M,
    query_elevations,
)
from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    build_route_elevation_result_from_values,
    route_distance_m,
)
from app.meetup.models import Meetup
from app.route_book.elevation_workflow import backfill_route_version_elevation, write_route_elevation_result
from app.route_book.elevation_quality import (
    has_elevation_metadata_method,
    has_trusted_route_elevation,
    parse_complete_elevation_grid,
    parse_complete_elevation_snapshot,
)
from app.route_book.models import RouteBook, RouteVersion, _preview_points_from_wkt

COORD_TOLERANCE_DEG = 0.00001
logger = logging.getLogger(__name__)


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
    group.add_argument(
        "--backfill-glo",
        action="store_true",
        help="fill missing or legacy route elevations from Copernicus GLO-30",
    )
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

        if args.backfill_glo:
            if any(
                value is not None
                for value in (args.source_name, args.license_id, args.accuracy_m)
            ):
                parser.error(
                    "--backfill-glo 使用固定 GLO-30 来源元数据；"
                    "--source-name/--license-id/--accuracy-m 仅用于 --import-csv"
                )
            count = backfill_missing_with_glo(
                db,
                dry_run=args.dry_run,
                route_book_ids=args.route_book_id,
            )
            print(
                f"{'validated' if args.dry_run else 'updated'} "
                f"{count} route version(s) from GLO-30"
            )
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


def backfill_missing_with_glo(
    db,
    *,
    query_func=query_elevations,
    source_name: str = GLO30_SOURCE_NAME,
    license_id: str = GLO30_LICENSE_ID,
    accuracy_m: float = GLO30_VERTICAL_ACCURACY_M,
    dry_run: bool,
    route_book_ids: list[int] | None = None,
) -> int:
    if (
        source_name != GLO30_SOURCE_NAME
        or license_id != GLO30_LICENSE_ID
        or accuracy_m != GLO30_VERTICAL_ACCURACY_M
    ):
        raise ValueError("GLO-30 回填不允许覆盖固定 source/license/accuracy 元数据")

    selected_route_ids = set(route_book_ids or [])
    refreshed_route_climbs: dict[int, float | None] = {}
    failed_route_ids: list[int] = []
    updated = 0
    for route, version, reference_line_wkt in _current_route_versions(db):
        if selected_route_ids and route.id not in selected_route_ids:
            continue
        try:
            points = _points_from_wkt(reference_line_wkt)
            trusted_elevation = has_trusted_route_elevation(
                version.elevation_points_snapshot,
                metadata_json=version.navigation_metadata_json,
                expected_count=len(points),
            )
            trusted_glo = has_elevation_metadata_method(
                version.navigation_metadata_json,
                methods=frozenset({ROUTE_ELEVATION_METHOD}),
                expected_count=len(points),
            )
            complete_grid = parse_complete_elevation_grid(
                version.elevation_grid_snapshot,
                expected_line_hash=version.line_hash,
                expected_distance_m=route_distance_m(points),
                metadata_json=version.navigation_metadata_json,
            )
            if trusted_elevation and (not trusted_glo or complete_grid is not None):
                # 路线已经是可信 GLO 结果时也要修复可能遗留的旧约骑快照；
                # 这不会计入本次 route version 的 updated 数量。
                refreshed_route_climbs[route.id] = route.climb
                continue

            def fill_current_route() -> None:
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
                db.flush()

            if dry_run:
                # SQLite 的 SAVEPOINT 释放在部分驱动模式下会逃逸外层 rollback；
                # 干跑本来就不保留任何成功项，因此直接留在整批事务中。
                fill_current_route()
            else:
                # 单条路线用 SAVEPOINT 隔离；一张坏瓦片或一条坏几何不能把此前
                # 已成功的全国批次全部回滚。失败仍在批次末尾以非零退出显式暴露。
                with db.begin_nested():
                    fill_current_route()
        except Exception:
            logger.exception(
                "GLO-30 路书回填失败 route_book_id=%s route_version_id=%s",
                route.id,
                version.id,
            )
            failed_route_ids.append(route.id)
            continue
        refreshed_route_climbs[route.id] = route.climb
        updated += 1
    if dry_run:
        db.rollback()
    else:
        _refresh_linked_route_meetup_snapshots(db, refreshed_route_climbs)
        db.commit()
    if failed_route_ids:
        outcome = "干跑已整体回滚" if dry_run else "成功项已保留"
        raise RuntimeError(
            f"GLO-30 路书回填存在失败，{outcome}；失败 route_book_id="
            + ",".join(str(route_id) for route_id in failed_route_ids)
        )
    return updated


def _refresh_linked_route_meetup_snapshots(
    db,
    route_climbs: dict[int, float | None],
) -> int:
    """同步所有仍可被产品 API 读取的约骑，彻底移除旧海拔结果。"""
    if not route_climbs or not inspect(db.connection()).has_table("meetups"):
        return 0

    refreshed = 0
    for route_book_id, climb in route_climbs.items():
        refreshed += (
            db.query(Meetup)
            .filter(Meetup.route_book_id == route_book_id)
            .update({Meetup.snapshot_climb: climb}, synchronize_session=False)
        )
    return refreshed


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
