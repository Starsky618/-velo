"""给 route_guides 增加导入来源字段。

Revision ID: 20260618_route_guides_provenance
Revises: 20260618_route_versions
Create Date: 2026-06-18
"""

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "20260618_route_guides_provenance"
down_revision = "20260618_route_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给 route_guides 加最小来源标签；正文仍然只来自 content/routes/guide.md。"""
    op.add_column("route_guides", sa.Column("source_ref", sa.Text(), nullable=True))
    op.add_column("route_guides", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.add_column("route_guides", sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("route_guides", sa.Column("source_route_version_id", sa.Integer(), nullable=True))
    op.add_column(
        "route_guides",
        sa.Column("content_origin", sa.String(length=32), server_default="legacy_import", nullable=False),
    )
    op.create_check_constraint(
        "ck_route_guides_content_origin",
        "route_guides",
        "content_origin IN ('content_routes_import', 'legacy_import')",
    )

    bind = op.get_bind()
    for row in bind.execute(
        sa.text("SELECT id, content_md FROM route_guides WHERE content_md IS NOT NULL")
    ).mappings():
        bind.execute(
            sa.text("UPDATE route_guides SET content_hash = :content_hash WHERE id = :id"),
            {
                "id": row["id"],
                "content_hash": hashlib.sha256(row["content_md"].encode("utf-8")).hexdigest(),
            },
        )

    op.execute(
        sa.text(
            """
            UPDATE route_guides AS rg
            SET source_route_version_id = rb.current_version_id
            FROM route_books AS rb
            WHERE rg.route_book_id = rb.id
              AND rb.current_version_id IS NOT NULL
            """
        )
    )
    op.create_foreign_key(
        "fk_route_guides_source_route_version",
        "route_guides",
        "route_versions",
        ["source_route_version_id", "route_book_id"],
        ["id", "route_book_id"],
    )


def downgrade() -> None:
    """回滚 Batch 2 provenance；不会尝试还原已重新导入的 guide 投影。"""
    op.drop_constraint("fk_route_guides_source_route_version", "route_guides", type_="foreignkey")
    op.drop_constraint("ck_route_guides_content_origin", "route_guides", type_="check")
    op.drop_column("route_guides", "content_origin")
    op.drop_column("route_guides", "source_route_version_id")
    op.drop_column("route_guides", "imported_at")
    op.drop_column("route_guides", "content_hash")
    op.drop_column("route_guides", "source_ref")
