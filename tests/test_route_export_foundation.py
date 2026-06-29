"""路线导出底座测试——先把“谁能拿到哪一版路线文件”钉牢。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import CheckConstraint, ForeignKeyConstraint


def _check_sql(table, name: str) -> str:
    checks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    ]
    assert checks
    return str(checks[0].sqltext)


def _composite_fk(table, name: str) -> ForeignKeyConstraint:
    fks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]
    assert fks
    return fks[0]


def test_route_export_job_model_is_version_bound_and_v1_only():
    from app.route_book.models import RouteExportJob

    columns = RouteExportJob.__table__.c
    assert {
        "id",
        "route_book_id",
        "route_version_id",
        "requester_id",
        "target_platform",
        "export_format",
        "export_mode",
        "status",
        "simplification_strategy_json",
        "target_constraints_json",
        "include_course_points",
        "error_code",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    } <= set(columns.keys())
    assert columns.route_book_id.nullable is False
    assert columns.route_version_id.nullable is False
    assert str(columns.export_mode.server_default.arg) == "download_file"
    assert str(columns.status.server_default.arg) == "queued"
    assert str(columns.include_course_points.server_default.arg).lower() == "false"

    format_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_format")
    assert "gpx" in format_sql
    assert "tcx" in format_sql
    assert "fit" not in format_sql.lower()

    mode_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_mode")
    assert "download_file" in mode_sql
    assert "manual_upload" in mode_sql
    assert "platform_sync" not in mode_sql

    status_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_status")
    for status in ("queued", "running", "succeeded", "failed", "cancelled"):
        assert status in status_sql

    course_points_sql = _check_sql(RouteExportJob.__table__, "ck_route_export_jobs_no_course_points")
    assert "include_course_points" in course_points_sql
    assert "false" in course_points_sql.lower()

    fk = _composite_fk(RouteExportJob.__table__, "fk_route_export_jobs_route_version_book")
    assert {element.parent.name for element in fk.elements} == {"route_version_id", "route_book_id"}

    index_names = {index.name for index in RouteExportJob.__table__.indexes}
    assert {
        "idx_route_export_jobs_route_version",
        "idx_route_export_jobs_route_book",
        "idx_route_export_jobs_requester",
        "idx_route_export_jobs_status_created",
        "idx_route_export_jobs_format",
    } <= index_names


def test_route_export_artifact_model_keeps_internal_file_id_and_version_binding():
    from app.route_book.models import RouteExportArtifact

    columns = RouteExportArtifact.__table__.c
    assert {
        "id",
        "export_job_id",
        "route_book_id",
        "route_version_id",
        "format",
        "file_id",
        "file_size",
        "content_hash",
        "input_point_count",
        "output_point_count",
        "generated_at",
        "expires_at",
        "metadata_json",
    } <= set(columns.keys())
    assert columns.export_job_id.nullable is False
    assert columns.route_book_id.nullable is False
    assert columns.route_version_id.nullable is False
    assert columns.file_id.nullable is False

    format_sql = _check_sql(RouteExportArtifact.__table__, "ck_route_export_artifacts_format")
    assert "gpx" in format_sql
    assert "tcx" in format_sql
    assert "fit" not in format_sql.lower()

    fk = _composite_fk(RouteExportArtifact.__table__, "fk_route_export_artifacts_route_version_book")
    assert {element.parent.name for element in fk.elements} == {"route_version_id", "route_book_id"}

    index_names = {index.name for index in RouteExportArtifact.__table__.indexes}
    assert {
        "idx_route_export_artifacts_job",
        "idx_route_export_artifacts_route_version",
        "idx_route_export_artifacts_route_book",
        "idx_route_export_artifacts_content_hash",
        "idx_route_export_artifacts_expires",
    } <= index_names


def test_route_export_permissions_keep_private_and_unlisted_routes_closed():
    from app.route_book.export_service import can_export_route

    owner_id = 11
    stranger_id = 22
    private_route = SimpleNamespace(
        id=1,
        creator_id=owner_id,
        visibility="private",
        publish_status="draft",
    )
    public_route = SimpleNamespace(
        id=2,
        creator_id=owner_id,
        visibility="public",
        publish_status="published",
    )
    unlisted_route = SimpleNamespace(
        id=3,
        creator_id=owner_id,
        visibility="unlisted",
        publish_status="published",
    )

    assert can_export_route(private_route, current_user_id=owner_id)
    assert can_export_route(private_route, current_user_id=stranger_id, is_admin=True)
    assert not can_export_route(private_route, current_user_id=stranger_id)
    assert can_export_route(public_route, current_user_id=stranger_id)
    assert not can_export_route(public_route, current_user_id=None)
    assert not can_export_route(unlisted_route, current_user_id=stranger_id)

    valid_share = SimpleNamespace(
        route_book_id=unlisted_route.id,
        status="active",
        can_export=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    view_only_share = SimpleNamespace(
        route_book_id=unlisted_route.id,
        status="active",
        can_export=False,
        expires_at=None,
    )
    expired_share = SimpleNamespace(
        route_book_id=unlisted_route.id,
        status="active",
        can_export=True,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert can_export_route(unlisted_route, current_user_id=stranger_id, share_link=valid_share)
    assert not can_export_route(unlisted_route, current_user_id=None, share_link=valid_share)
    assert not can_export_route(unlisted_route, current_user_id=stranger_id, share_link=view_only_share)
    assert not can_export_route(unlisted_route, current_user_id=stranger_id, share_link=expired_share)


def test_artifact_download_permission_never_exposes_someone_elses_file_id():
    from app.route_book.export_service import can_download_export_artifact

    artifact = SimpleNamespace(
        id=101,
        route_book_id=7,
        route_version_id=9,
        file_id="exports/secret-route.gpx",
    )
    job = SimpleNamespace(requester_id=33)
    route = SimpleNamespace(id=7, creator_id=44)
    wrong_route = SimpleNamespace(id=8, creator_id=44)

    assert can_download_export_artifact(artifact, current_user_id=33, job=job, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=33, job=job, route=wrong_route)
    assert not can_download_export_artifact(artifact, current_user_id=44, job=job, route=route)
    assert can_download_export_artifact(artifact, current_user_id=55, job=job, route=route, is_admin=True)
    assert not can_download_export_artifact(artifact, current_user_id=55, job=job, route=route)
    assert not can_download_export_artifact(artifact, current_user_id=None, job=job, route=route)


def test_batch3_migration_creates_export_tables_without_share_or_fit_scope():
    migration = Path("migrations/versions/20260618_route_exports.py")
    assert migration.exists()
    text = migration.read_text(encoding="utf-8")

    assert "op.create_table" in text
    assert '"route_export_jobs"' in text
    assert '"route_export_artifacts"' in text
    assert "route_share_links" not in text
    assert "platform_sync" not in text
    assert "'fit'" not in text
