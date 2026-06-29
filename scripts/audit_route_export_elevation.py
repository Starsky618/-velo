"""路线导出海拔审计工具——像验车表一样，逐条标出下载文件有没有海拔。

干啥用：批量检查 route_books 当前版本导出 GPX/TCX 时是否会带海拔点，
并提示是否还能从源活动或仓库原始 GPX 找到精确回填来源。

操作注意事项：这里只读数据库和仓库文件，不写库、不生成导出文件。
它不能证明某个外部 DEM 合法，只能证明 VELO 已经掌握的精确来源是否可用。

输入输出：输入可选 route_book_id 列表，输出 JSON 数组；每一行是一条路线的验货结果。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint  # noqa: F401
from app.database import SessionLocal
from app.route_book.export_generator import count_exportable_elevation_points
from app.route_book.models import RouteBook, RouteVersion
from app.user.models import User  # noqa: F401
from scripts.backfill_route_elevation import (
    project_precise_elevation,
    reference_points_from_version,
    source_points_from_activity,
    source_points_from_route_file,
)


MAX_BACKFILL_MATCH_DISTANCE_M = 35.0


@dataclass(frozen=True)
class RouteExportElevationAudit:
    """单条路线审计结果——给运营看这一条路线到底处在哪个状态。"""

    route_book_id: int
    name: str
    visibility: str
    publish_status: str
    current_version_id: int | None
    navigation_status: str | None
    public_export_ready: bool
    export_elevation_included: bool
    export_elevation_point_count: int
    route_point_count: int | None
    precise_source_candidates: list[str]
    action: str


def audit_route_export_elevation(
    db: Session,
    *,
    route_book_ids: list[int] | None = None,
    public_only: bool = False,
) -> list[RouteExportElevationAudit]:
    """
    扫描路线导出海拔状态。

    public_export_ready 像“游客能不能直接拿票入场”；export_elevation_included 像“票里有没有海拔附件”。
    两件事分开看，才能发现“能下载但只有二维轨迹”的路线。
    """
    query = db.query(RouteBook).order_by(RouteBook.id.asc())
    if route_book_ids:
        query = query.filter(RouteBook.id.in_(route_book_ids))
    if public_only:
        query = query.filter(RouteBook.visibility == "public", RouteBook.publish_status == "published")

    rows: list[RouteExportElevationAudit] = []
    for route in query.all():
        version = _current_version(db, route)
        elevation_count = _export_elevation_count(version)
        public_export_ready = _public_export_ready(route, version)
        candidates = _precise_source_candidates(db, route, version, elevation_count)
        rows.append(
            RouteExportElevationAudit(
                route_book_id=route.id,
                name=route.name,
                visibility=route.visibility,
                publish_status=route.publish_status,
                current_version_id=route.current_version_id,
                navigation_status=version.navigation_status if version is not None else None,
                public_export_ready=public_export_ready,
                export_elevation_included=elevation_count > 0,
                export_elevation_point_count=elevation_count,
                route_point_count=version.point_count if version is not None else None,
                precise_source_candidates=candidates,
                action=_recommended_action(route, version, public_export_ready, elevation_count, candidates),
            )
        )
    return rows


def _current_version(db: Session, route: RouteBook) -> RouteVersion | None:
    if route.current_version_id is None:
        return None
    return (
        db.query(RouteVersion)
        .filter(RouteVersion.id == route.current_version_id, RouteVersion.route_book_id == route.id)
        .first()
    )


def _public_export_ready(route: RouteBook, version: RouteVersion | None) -> bool:
    return (
        route.visibility == "public"
        and route.publish_status == "published"
        and version is not None
        and version.navigation_status == "ready"
    )


def _export_elevation_count(version: RouteVersion | None) -> int:
    if version is None or version.navigation_status != "ready":
        return 0
    return count_exportable_elevation_points(
        reference_line_snapshot=version.reference_line_snapshot,
        elevation_points_snapshot=version.elevation_points_snapshot,
    )


def _precise_source_candidates(
    db: Session,
    route: RouteBook,
    version: RouteVersion | None,
    elevation_count: int,
) -> list[str]:
    candidates: list[str] = []
    if elevation_count > 0:
        candidates.append("current_version")
        return candidates
    if version is None or version.navigation_status != "ready":
        return candidates
    if _source_activity_matches_current_version(db, route, version):
        candidates.append("source_activity")
    if _repo_route_file_matches_current_version(route, version):
        candidates.append("repo_route_file")
    return candidates


def _source_activity_matches_current_version(db: Session, route: RouteBook, version: RouteVersion) -> bool:
    if route.source_activity_id is None:
        return False
    try:
        source_points = source_points_from_activity(db, route.source_activity_id)
    except (LookupError, ValueError):
        return False
    return _source_points_match_current_version(version, source_points)


def _repo_route_file_matches_current_version(route: RouteBook, version: RouteVersion) -> bool:
    if not route.file_id:
        return False
    path = Path(route.file_id)
    if path.is_absolute():
        return False
    if not (ROOT_DIR / path).exists():
        return False
    try:
        source_points = source_points_from_route_file(str(path))
    except ValueError:
        return False
    return _source_points_match_current_version(version, source_points)


def _source_points_match_current_version(version: RouteVersion, source_points: list[list[float]]) -> bool:
    try:
        project_precise_elevation(
            reference_points_from_version(version),
            source_points,
            max_distance_m=MAX_BACKFILL_MATCH_DISTANCE_M,
        )
    except ValueError:
        return False
    return True


def _recommended_action(
    route: RouteBook,
    version: RouteVersion | None,
    public_export_ready: bool,
    elevation_count: int,
    candidates: list[str],
) -> str:
    if version is None:
        return "no_current_version"
    if version.navigation_status != "ready":
        return "version_not_ready"
    if elevation_count > 0:
        return "export_contains_elevation" if public_export_ready else "private_or_draft_contains_elevation"
    if public_export_ready:
        if "source_activity" in candidates or "repo_route_file" in candidates:
            return "download_is_2d_can_backfill_from_precise_source"
        return "download_is_2d_need_precise_source"
    if route.visibility != "public" or route.publish_status != "published":
        if "source_activity" in candidates or "repo_route_file" in candidates:
            return "private_or_draft_can_backfill_from_precise_source"
        return "private_or_draft_no_elevation"
    return "no_precise_elevation_source"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit route export elevation readiness.")
    parser.add_argument("--route-book-id", type=int, action="append", default=None)
    parser.add_argument("--public-only", action="store_true", help="only show public published routes")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        rows = audit_route_export_elevation(
            db,
            route_book_ids=args.route_book_id,
            public_only=args.public_only,
        )
        print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
