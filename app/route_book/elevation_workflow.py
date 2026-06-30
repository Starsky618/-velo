"""
路书海拔写回流程——把公共海拔工厂的成品分发到路书自己的表里。

操作注意事项：这里不要直接依赖 segments。赛段可以用同一套海拔工厂，但路书导出必须
拥有自己的逐点海拔快照，否则未来赛段删改会影响已发布路书。

输入输出：输入 route_version_id，读取这一版路线的二维线条，生成海拔结果后写回
route_versions / route_books / route_guides。
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy import func, inspect

from app.elevation.dem_client import SRTM_HORIZONTAL_RESOLUTION_M
from app.elevation.route_elevation import ElevationQuery, RouteElevationResult, build_route_elevation_result
from app.route_book.models import RouteBook, RouteGuide, RouteVersion, _preview_points_from_wkt


def backfill_route_version_elevation(
    db,
    route_version_id: int,
    *,
    query_func: ElevationQuery,
    source_name: str,
    license_id: str,
    accuracy_m: float,
    dry_run: bool,
    commit: bool = True,
) -> bool:
    """
    给一版路书路线补齐逐点海拔。

    类比：公共海拔模块负责“做菜”，这个函数负责“把菜端到路书自己的盘子里”。它只写
    路书相关表，不去改赛段表。
    """
    if accuracy_m <= 0:
        raise ValueError("accuracy_m must be positive")

    row = (
        db.query(RouteBook, RouteVersion, func.ST_AsText(RouteVersion.reference_line_snapshot))
        .join(RouteVersion, RouteBook.current_version_id == RouteVersion.id)
        .filter(RouteVersion.id == route_version_id, RouteVersion.route_book_id == RouteBook.id)
        .first()
    )
    if row is None:
        raise LookupError(f"route version not found or not current: {route_version_id}")

    route, version, reference_line_wkt = row
    points = _points_from_wkt(reference_line_wkt)
    result = build_route_elevation_result(points, query_func=query_func)
    write_route_elevation_result(
        db,
        route=route,
        version=version,
        result=result,
        source_name=source_name,
        license_id=license_id,
        accuracy_m=accuracy_m,
        method="shared_route_elevation_v1",
        timestamp_field="generated_at",
        extra_metadata={"horizontal_resolution_m": SRTM_HORIZONTAL_RESOLUTION_M},
    )

    if commit:
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return True


def write_route_elevation_result(
    db,
    *,
    route: RouteBook,
    version: RouteVersion,
    result: RouteElevationResult,
    source_name: str,
    license_id: str,
    accuracy_m: float,
    method: str,
    timestamp_field: str,
    extra_metadata: dict | None = None,
) -> None:
    profile_json = json.dumps(result.profile, ensure_ascii=False)
    version.elevation_points_snapshot = json.dumps(result.snapshot, ensure_ascii=False)
    version.elevation_profile = profile_json
    version.climb = result.climb
    version.point_count = result.point_count
    version.navigation_metadata_json = json.dumps(
        _merged_navigation_metadata(
            version.navigation_metadata_json,
            source_name=source_name,
            license_id=license_id,
            accuracy_m=accuracy_m,
            point_count=result.point_count,
            method=method,
            timestamp_field=timestamp_field,
            extra_metadata=extra_metadata,
        ),
        ensure_ascii=False,
    )
    route.elevation_profile = profile_json
    route.climb = result.climb
    _update_route_guides(db, route.id, profile_json)


def _points_from_wkt(reference_line_wkt: str) -> list[list[float]]:
    points = _preview_points_from_wkt(reference_line_wkt)
    if len(points) < 2:
        raise ValueError("route version line must have at least 2 points")
    return points


def _update_route_guides(db, route_book_id: int, elevation_profile: str) -> None:
    # 查表也走当前 session 的连接，不能绕到 engine 上另开入口。
    # SQLite 测试库会复用同一条底层连接，engine 旁路检查可能冲掉尚未提交的新路线。
    if not inspect(db.connection()).has_table("route_guides"):
        return
    guides = db.query(RouteGuide).filter(RouteGuide.route_book_id == route_book_id).all()
    for guide in guides:
        guide.elevation_profile = elevation_profile


def _merged_navigation_metadata(
    value: str | None,
    *,
    source_name: str,
    license_id: str,
    accuracy_m: float,
    point_count: int,
    method: str,
    timestamp_field: str,
    extra_metadata: dict | None,
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
        "point_count": point_count,
        "method": method,
    }
    if extra_metadata:
        metadata["elevation"].update(extra_metadata)
    metadata["elevation"][timestamp_field] = datetime.now(timezone.utc).isoformat()
    return metadata
