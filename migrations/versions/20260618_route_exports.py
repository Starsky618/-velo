"""增加路线导出任务和导出产物表。

Revision ID: 20260618_route_exports
Revises: 20260618_route_guides_provenance
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260618_route_exports"
down_revision = "20260618_route_guides_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """建立 Batch 3 导出底座；真实文件生成和分享链接继续后置。"""
    op.create_table(
        "route_export_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("route_version_id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=True),
        sa.Column("target_platform", sa.String(length=32), nullable=True),
        sa.Column("export_format", sa.String(length=8), nullable=False),
        sa.Column("export_mode", sa.String(length=24), server_default="download_file", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("simplification_strategy_json", sa.Text(), nullable=True),
        sa.Column("target_constraints_json", sa.Text(), nullable=True),
        sa.Column("include_course_points", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("export_format IN ('gpx', 'tcx')", name="ck_route_export_jobs_format"),
        sa.CheckConstraint(
            "export_mode IN ('download_file', 'manual_upload')",
            name="ck_route_export_jobs_mode",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_route_export_jobs_status",
        ),
        sa.CheckConstraint("include_course_points = false", name="ck_route_export_jobs_no_course_points"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], ondelete="CASCADE"),
        # route_version_id 不再单独建 FK：下面的组合 FK 已把它和 route_book_id 一起约束到
        # route_versions(id, route_book_id)，单列 FK 是重复约束，去掉。
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_export_jobs_route_version_book",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_route_export_jobs_route_version", "route_export_jobs", ["route_version_id"])
    op.create_index("idx_route_export_jobs_route_book", "route_export_jobs", ["route_book_id"])
    op.create_index("idx_route_export_jobs_requester", "route_export_jobs", ["requester_id"])
    op.create_index("idx_route_export_jobs_status_created", "route_export_jobs", ["status", "created_at"])
    op.create_index("idx_route_export_jobs_format", "route_export_jobs", ["export_format"])

    op.create_table(
        "route_export_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("export_job_id", sa.Integer(), nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=False),
        sa.Column("route_version_id", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("input_point_count", sa.Integer(), nullable=True),
        sa.Column("output_point_count", sa.Integer(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.CheckConstraint("format IN ('gpx', 'tcx')", name="ck_route_export_artifacts_format"),
        sa.ForeignKeyConstraint(["export_job_id"], ["route_export_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["route_book_id"], ["route_books.id"], ondelete="CASCADE"),
        # 同 route_export_jobs：route_version_id 由组合 FK 统一约束，不再单独建 FK。
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_route_export_artifacts_route_version_book",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_route_export_artifacts_job", "route_export_artifacts", ["export_job_id"])
    op.create_index("idx_route_export_artifacts_route_version", "route_export_artifacts", ["route_version_id"])
    op.create_index("idx_route_export_artifacts_route_book", "route_export_artifacts", ["route_book_id"])
    op.create_index("idx_route_export_artifacts_content_hash", "route_export_artifacts", ["content_hash"])
    op.create_index("idx_route_export_artifacts_expires", "route_export_artifacts", ["expires_at"])


def downgrade() -> None:
    """移除 Batch 3 导出底座，不触碰路线正文和路线版本。"""
    op.drop_table("route_export_artifacts")
    op.drop_table("route_export_jobs")
