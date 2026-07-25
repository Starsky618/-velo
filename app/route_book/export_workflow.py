"""
路书导出工作流——把“点下载”变成可取回的 GPX/TCX 文件。

这个文件像下载窗口的登记员：先确认路线和身份，再请生成器打印文件，
最后把内部 file_id 锁在后端，只给前端一个受控下载地址。
"""

import hashlib
import hmac
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.route_book.export_generator import generate_route_export, has_exportable_route_elevation
from app.route_book.export_service import (
    assert_can_download_export_artifact,
    assert_can_export_route,
)
from app.route_book.models import RouteBook, RouteExportArtifact, RouteExportJob, RouteVersion
from app.route_book.schemas import RouteExportFormat, RouteExportTargetPlatform
from app.storage.local import LocalStorage
from app.user.models import User


_storage = LocalStorage()


@dataclass(frozen=True)
class RouteExportCreated:
    """创建导出后的外部合同——给前端看的，不含内部 file_id。"""

    job_id: int
    artifact_id: int
    route_book_id: int
    route_version_id: int
    format: RouteExportFormat
    filename: str
    download_url: str


@dataclass(frozen=True)
class RouteExportDownload:
    """下载接口需要的二进制文件和响应头信息。"""

    content: bytes
    filename: str
    content_type: str


def create_route_export(
    db: Session,
    *,
    route_book_id: int,
    export_format: RouteExportFormat,
    target_platform: RouteExportTargetPlatform | None,
    current_user_id: int | None,
) -> RouteExportCreated:
    route = _get_route(db, route_book_id)
    is_admin = _is_admin(db, current_user_id)
    assert_can_export_route(route, current_user_id=current_user_id, is_admin=is_admin)

    version = _get_current_version(db, route)
    if not has_exportable_route_elevation(
        reference_line_snapshot=version.reference_line_snapshot,
        elevation_points_snapshot=version.elevation_points_snapshot,
        elevation_grid_snapshot=version.elevation_grid_snapshot,
        reference_line_hash=version.line_hash,
        elevation_metadata_json=version.navigation_metadata_json,
    ):
        raise ValueError("这条路线还没有用 VELO 统一海拔源生成可导出的逐点海拔")
    generated = generate_route_export(
        route_name=route.name,
        reference_line_snapshot=version.reference_line_snapshot,
        elevation_points_snapshot=version.elevation_points_snapshot,
        elevation_grid_snapshot=version.elevation_grid_snapshot,
        reference_line_hash=version.line_hash,
        elevation_metadata_json=version.navigation_metadata_json,
        export_format=export_format,
    )
    filename = safe_export_filename(route.name, route.id, version.id, export_format)
    file_id = _storage.upload(generated.content, filename, subdir="route_exports")

    now = datetime.now(timezone.utc)
    content_hash = hashlib.sha256(generated.content).hexdigest()
    job = RouteExportJob(
        route_book_id=route.id,
        route_version_id=version.id,
        requester_id=current_user_id,
        target_platform=target_platform or "generic",
        export_format=export_format,
        export_mode="download_file",
        status="succeeded",
        include_course_points=False,
        started_at=now,
        finished_at=now,
        target_constraints_json=json.dumps({"target_platform": target_platform or "generic"}, ensure_ascii=False),
    )
    db.add(job)
    try:
        db.flush()
        artifact = RouteExportArtifact(
            export_job_id=job.id,
            route_book_id=route.id,
            route_version_id=version.id,
            format=export_format,
            file_id=file_id,
            file_size=len(generated.content),
            content_hash=content_hash,
            input_point_count=version.point_count or 0,
            output_point_count=generated.point_count,
            generated_at=now,
            metadata_json=json.dumps(
                {
                    "filename": filename,
                    "content_type": generated.content_type,
                    "elevation_included": generated.elevation_point_count > 0,
                    "elevation_point_count": generated.elevation_point_count,
                    "elevation_snapshot_sha256": _elevation_snapshot_sha256(
                        version.elevation_points_snapshot
                    ),
                    "elevation_export_source_sha256": _elevation_export_source_sha256(
                        version.elevation_points_snapshot,
                        version.elevation_grid_snapshot,
                        version.line_hash,
                    ),
                },
                ensure_ascii=False,
            ),
        )
        db.add(artifact)
        db.commit()
    except Exception:
        db.rollback()
        _delete_quietly(file_id)
        raise

    db.refresh(job)
    db.refresh(artifact)
    return RouteExportCreated(
        job_id=job.id,
        artifact_id=artifact.id,
        route_book_id=route.id,
        route_version_id=version.id,
        format=export_format,
        filename=filename,
        download_url=f"/api/route-books/{route.id}/exports/{artifact.id}/download",
    )


def get_route_export_download(
    db: Session,
    *,
    route_book_id: int,
    artifact_id: int,
    current_user_id: int | None,
) -> RouteExportDownload:
    route = _get_route(db, route_book_id)
    artifact = db.query(RouteExportArtifact).filter(RouteExportArtifact.id == artifact_id).first()
    if artifact is None:
        raise LookupError("route export artifact not found")
    job = db.query(RouteExportJob).filter(RouteExportJob.id == artifact.export_job_id).first()
    is_admin = _is_admin(db, current_user_id)
    assert_can_download_export_artifact(
        artifact,
        current_user_id=current_user_id,
        job=job,
        route=route,
        is_admin=is_admin,
    )

    metadata = _artifact_metadata(artifact)
    version = (
        db.query(RouteVersion)
        .filter(
            RouteVersion.id == artifact.route_version_id,
            RouteVersion.route_book_id == artifact.route_book_id,
        )
        .first()
    )
    if version is None or not has_exportable_route_elevation(
        reference_line_snapshot=version.reference_line_snapshot,
        elevation_points_snapshot=version.elevation_points_snapshot,
        elevation_grid_snapshot=version.elevation_grid_snapshot,
        reference_line_hash=version.line_hash,
        elevation_metadata_json=version.navigation_metadata_json,
    ):
        raise LookupError("route export artifact elevation is no longer trusted")
    artifact_snapshot_hash = metadata.get("elevation_snapshot_sha256")
    current_snapshot_hash = _elevation_snapshot_sha256(version.elevation_points_snapshot)
    if not isinstance(artifact_snapshot_hash, str) or not hmac.compare_digest(
        artifact_snapshot_hash,
        current_snapshot_hash,
    ):
        # 回填会原地更新 RouteVersion；没有这道指纹门，旧底图生成的 GPX/TCX
        # 仍可在新版海拔写入后继续下载。
        raise LookupError("route export artifact elevation is stale")
    artifact_export_source_hash = metadata.get("elevation_export_source_sha256")
    if version.elevation_grid_snapshot is not None or isinstance(artifact_export_source_hash, str):
        current_export_source_hash = _elevation_export_source_sha256(
            version.elevation_points_snapshot,
            version.elevation_grid_snapshot,
            version.line_hash,
        )
        if not isinstance(artifact_export_source_hash, str) or not hmac.compare_digest(
            artifact_export_source_hash,
            current_export_source_hash,
        ):
            raise LookupError("route export artifact canonical elevation is stale")
    filename = metadata.get("filename") or safe_export_filename(
        route.name,
        route.id,
        artifact.route_version_id,
        artifact.format,
    )
    content_type = metadata.get("content_type") or _content_type_for_format(artifact.format)
    try:
        content = _storage.download(artifact.file_id)
    except (FileNotFoundError, KeyError, OSError) as exc:
        raise LookupError("route export file not found") from exc
    return RouteExportDownload(
        content=content,
        filename=filename,
        content_type=content_type,
    )


def safe_export_filename(route_name: str, route_book_id: int, route_version_id: int, export_format: str) -> str:
    normalized = unicodedata.normalize("NFKC", route_name or "route")
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", normalized)
    cleaned = re.sub(r"\s+", "-", cleaned).strip(" .-_")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        cleaned = "route"
    cleaned = cleaned[:80].rstrip(" .-_") or "route"
    return f"{cleaned}-{route_book_id}-v{route_version_id}.{export_format}"


def _get_route(db: Session, route_book_id: int) -> RouteBook:
    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise LookupError("route book not found")
    return route


def _get_current_version(db: Session, route: RouteBook) -> RouteVersion:
    if route.current_version_id is None:
        raise ValueError("这条路线还没有可下载轨迹")
    version = (
        db.query(RouteVersion)
        .filter(
            RouteVersion.id == route.current_version_id,
            RouteVersion.route_book_id == route.id,
        )
        .first()
    )
    if version is None:
        raise ValueError("这条路线还没有可下载轨迹")
    if version.navigation_status != "ready":
        raise ValueError("这条路线还没有可下载轨迹")
    return version


def _is_admin(db: Session, current_user_id: int | None) -> bool:
    if current_user_id is None:
        return False
    user = db.query(User).filter(User.id == current_user_id).first()
    return bool(user and user.is_admin)


def _artifact_metadata(artifact: RouteExportArtifact) -> dict[str, str]:
    if not artifact.metadata_json:
        return {}
    try:
        parsed = json.loads(artifact.metadata_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _content_type_for_format(export_format: str) -> str:
    if export_format == "tcx":
        return "application/vnd.garmin.tcx+xml"
    return "application/gpx+xml"


def _elevation_snapshot_sha256(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _elevation_export_source_sha256(
    elevation_points_snapshot: str | None,
    elevation_grid_snapshot: str | None,
    line_hash: str | None,
) -> str:
    payload = "\n".join(
        [
            line_hash or "",
            elevation_points_snapshot or "",
            elevation_grid_snapshot or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _delete_quietly(file_id: str) -> None:
    delete = getattr(_storage, "delete", None)
    if delete is None:
        return
    try:
        delete(file_id)
    except Exception:
        return
