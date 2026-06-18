"""增加路线认知判断、证据和研究台账。

Revision ID: 20260618_route_cognition_batch4
Revises: 20260618_route_exports
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_route_cognition_batch4"
down_revision = "20260618_route_exports"
branch_labels = None
depends_on = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """建立 Batch 4 内部台账；路线正文和公开展示继续由后续批次处理。"""
    op.create_table(
        "judgment_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("route_version_id", sa.Integer(), nullable=True),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("engine_name", sa.String(length=64), nullable=True),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.Column("params_json", _jsonb(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("confidence_method", sa.String(length=64), nullable=True),
        sa.Column("confidence_state", sa.String(length=32), nullable=False),
        sa.Column("result_summary_json", _jsonb(), nullable=True),
        sa.Column("missing_data_json", _jsonb(), nullable=True),
        sa.Column("contradiction_json", _jsonb(), nullable=True),
        sa.Column("defensive_silence_recommended", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("parent_run_id", sa.Integer(), nullable=True),
        sa.Column("challenged_run_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_service", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "run_type IN ('spatial_algorithm', 'semantic_agent', 'adversarial_agent', "
            "'human_review', 'research_synthesis', 'hybrid')",
            name="ck_judgment_runs_run_type",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_judgment_runs_status",
        ),
        sa.CheckConstraint(
            "confidence_state IN ('raw', 'proposed', 'challenged', 'stable', "
            "'human_accepted', 'stale', 'inconclusive')",
            name="ck_judgment_runs_confidence_state",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_judgment_runs_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["challenged_run_id"],
            ["judgment_runs.id"],
            name="fk_judgment_runs_challenged_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_judgment_runs_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["judgment_runs.id"],
            name="fk_judgment_runs_parent_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_book_id"],
            ["route_books.id"],
            name="fk_judgment_runs_route_book",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id"],
            ["route_versions.id"],
            name="fk_judgment_runs_route_version",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_judgment_runs_route_version_book",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name="fk_judgment_runs_segment",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_judgment_runs_type_created", "judgment_runs", ["run_type", "created_at"])
    op.create_index("idx_judgment_runs_status_created", "judgment_runs", ["status", "created_at"])
    op.create_index("idx_judgment_runs_route_version", "judgment_runs", ["route_version_id"])
    op.create_index("idx_judgment_runs_route_book", "judgment_runs", ["route_book_id"])
    op.create_index("idx_judgment_runs_segment", "judgment_runs", ["segment_id"])
    op.create_index("idx_judgment_runs_parent", "judgment_runs", ["parent_run_id"])
    op.create_index("idx_judgment_runs_challenged", "judgment_runs", ["challenged_run_id"])

    op.add_column("route_guides", sa.Column("source_judgment_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_route_guides_source_judgment_run",
        "route_guides",
        "judgment_runs",
        ["source_judgment_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_route_guides_source_judgment_run", "route_guides", ["source_judgment_run_id"])

    op.create_table(
        "research_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_question_id", sa.Integer(), nullable=True),
        sa.Column("spawned_by_research_run_id", sa.Integer(), nullable=True),
        sa.Column("trigger_judgment_run_id", sa.Integer(), nullable=True),
        sa.Column("trigger_evidence_item_id", sa.Integer(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(length=64), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=True),
        sa.Column("expected_evidence_type", sa.String(length=64), nullable=True),
        sa.Column("stop_condition_json", _jsonb(), nullable=True),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("route_version_id", sa.Integer(), nullable=True),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=True),
        sa.Column("created_by_run_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "question_type IN ('event_association', 'route_family_membership', 'name_origin', "
            "'safety_condition', 'abnormal_popularity', 'foreign_rider_spike', "
            "'platform_metric_conflict', 'physical_semantic_gap', 'content_rights_check', 'other')",
            name="ck_research_questions_question_type",
        ),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_research_questions_priority"),
        sa.CheckConstraint(
            "status IN ('open', 'researching', 'answered', 'unknown', 'contradicted', 'dismissed')",
            name="ck_research_questions_status",
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('answered', 'unknown', 'contradicted', 'dismissed')",
            name="ck_research_questions_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"],
            ["judgment_runs.id"],
            name="fk_research_questions_created_by_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_research_questions_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_question_id"],
            ["research_questions.id"],
            name="fk_research_questions_parent",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_book_id"],
            ["route_books.id"],
            name="fk_research_questions_route_book",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id"],
            ["route_versions.id"],
            name="fk_research_questions_route_version",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_research_questions_route_version_book",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name="fk_research_questions_segment",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_research_questions_trigger_run",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_research_questions_status_priority", "research_questions", ["status", "priority"])
    op.create_index("idx_research_questions_route_version", "research_questions", ["route_version_id"])
    op.create_index("idx_research_questions_route_book", "research_questions", ["route_book_id"])
    op.create_index("idx_research_questions_trigger_run", "research_questions", ["trigger_judgment_run_id"])
    op.create_index("idx_research_questions_spawned_run", "research_questions", ["spawned_by_research_run_id"])
    op.create_index("idx_research_questions_trigger_evidence", "research_questions", ["trigger_evidence_item_id"])
    op.create_index("idx_research_questions_parent", "research_questions", ["parent_question_id"])

    op.create_table(
        "research_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("research_question_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("queries_json", _jsonb(), nullable=True),
        sa.Column("searched_sources_json", _jsonb(), nullable=True),
        sa.Column("engine_name", sa.String(length=64), nullable=True),
        sa.Column("engine_version", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("summary_json", _jsonb(), nullable=True),
        sa.Column("result_judgment_run_id", sa.Integer(), nullable=True),
        sa.Column("used_evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("contradicting_evidence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unknown_summary_json", _jsonb(), nullable=True),
        sa.Column("discarded_results_summary_json", _jsonb(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_research_runs_status",
        ),
        sa.CheckConstraint("used_evidence_count >= 0", name="ck_research_runs_used_evidence_count"),
        sa.CheckConstraint(
            "contradicting_evidence_count >= 0",
            name="ck_research_runs_contradicting_evidence_count",
        ),
        sa.ForeignKeyConstraint(
            ["research_question_id"],
            ["research_questions.id"],
            name="fk_research_runs_question",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["result_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_research_runs_result_judgment",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_research_runs_question", "research_runs", ["research_question_id"])
    op.create_index("idx_research_runs_status_created", "research_runs", ["status", "created_at"])
    op.create_index("idx_research_runs_result_judgment", "research_runs", ["result_judgment_run_id"])

    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("first_judgment_run_id", sa.Integer(), nullable=False),
        sa.Column("research_run_id", sa.Integer(), nullable=True),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("fidelity_tier", sa.Integer(), nullable=False),
        sa.Column("route_book_id", sa.Integer(), nullable=True),
        sa.Column("route_version_id", sa.Integer(), nullable=True),
        sa.Column("segment_id", sa.Integer(), nullable=True),
        sa.Column("source_platform", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_file_id", sa.String(length=512), nullable=True),
        sa.Column("file_id", sa.String(length=512), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("geometry_hash", sa.String(length=64), nullable=True),
        sa.Column("coordinate_system", sa.String(length=32), nullable=True),
        sa.Column("normalization_version", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metrics_json", _jsonb(), nullable=True),
        sa.Column("text_excerpt", sa.Text(), nullable=True),
        sa.Column("text_summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", _jsonb(), nullable=True),
        sa.Column("access_level", sa.String(length=32), server_default="internal_only", nullable=False),
        sa.Column("display_policy", sa.String(length=32), server_default="internal_only", nullable=False),
        sa.Column("rights_status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("contains_sensitive_media", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("contains_watermark", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("contains_identifiable_person", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("contains_identifiable_vehicle", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN ('route_version_geometry', 'verified_segment_geometry', "
            "'internal_structured_metric', 'platform_metric', 'elevation_profile_image', "
            "'ugc_text', 'web_page_text', 'model_inference', 'human_observation', "
            "'human_review_decision')",
            name="ck_evidence_items_evidence_type",
        ),
        sa.CheckConstraint("fidelity_tier BETWEEN 1 AND 5", name="ck_evidence_items_fidelity_tier"),
        sa.CheckConstraint(
            "access_level IN ('internal_only', 'reviewer', 'admin')",
            name="ck_evidence_items_access_level",
        ),
        sa.CheckConstraint(
            "display_policy IN ('internal_only', 'summarize_only', 'display_allowed')",
            name="ck_evidence_items_display_policy",
        ),
        sa.CheckConstraint(
            "rights_status IN ('unknown', 'allowed', 'forbidden', 'licensed', 'self_owned')",
            name="ck_evidence_items_rights_status",
        ),
        sa.ForeignKeyConstraint(
            ["first_judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_evidence_items_first_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
            name="fk_evidence_items_research_run",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_book_id"],
            ["route_books.id"],
            name="fk_evidence_items_route_book",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id"],
            ["route_versions.id"],
            name="fk_evidence_items_route_version",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["route_version_id", "route_book_id"],
            ["route_versions.id", "route_versions.route_book_id"],
            name="fk_evidence_items_route_version_book",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name="fk_evidence_items_segment",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_evidence_items_first_run", "evidence_items", ["first_judgment_run_id"])
    op.create_index("idx_evidence_items_research_run", "evidence_items", ["research_run_id"])
    op.create_index("idx_evidence_items_type", "evidence_items", ["evidence_type"])
    op.create_index("idx_evidence_items_fidelity", "evidence_items", ["fidelity_tier"])
    op.create_index("idx_evidence_items_route_version", "evidence_items", ["route_version_id"])
    op.create_index("idx_evidence_items_route_book", "evidence_items", ["route_book_id"])
    op.create_index("idx_evidence_items_segment", "evidence_items", ["segment_id"])
    op.create_index("idx_evidence_items_content_hash", "evidence_items", ["content_hash"])
    op.create_index("idx_evidence_items_display_policy", "evidence_items", ["display_policy"])
    op.create_index("idx_evidence_items_rights_status", "evidence_items", ["rights_status"])

    op.create_table(
        "judgment_run_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("judgment_run_id", sa.Integer(), nullable=False),
        sa.Column("evidence_item_id", sa.Integer(), nullable=False),
        sa.Column("evidence_role", sa.String(length=32), nullable=False),
        sa.Column("assessment_result", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Numeric(5, 4), nullable=True),
        sa.Column("anchor_evidence_item_id", sa.Integer(), nullable=True),
        sa.Column("assessment_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "evidence_role IN ('primary_input', 'primary_physical_basis', 'supporting', "
            "'contradicting', 'background', 'weak_signal', 'comparison_target')",
            name="ck_judgment_run_evidence_role",
        ),
        sa.CheckConstraint(
            "assessment_result IN ('input', 'supports', 'contradicts', 'neutral', "
            "'unverifiable', 'insufficient')",
            name="ck_judgment_run_evidence_result",
        ),
        sa.CheckConstraint(
            "weight IS NULL OR (weight >= 0 AND weight <= 1)",
            name="ck_judgment_run_evidence_weight_range",
        ),
        sa.ForeignKeyConstraint(
            ["anchor_evidence_item_id"],
            ["evidence_items.id"],
            name="fk_judgment_run_evidence_anchor",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name="fk_judgment_run_evidence_item",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judgment_run_id"],
            ["judgment_runs.id"],
            name="fk_judgment_run_evidence_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "judgment_run_id",
            "evidence_item_id",
            "evidence_role",
            name="uq_judgment_run_evidence_role",
        ),
    )
    op.create_index("idx_judgment_run_evidence_run", "judgment_run_evidence", ["judgment_run_id"])
    op.create_index("idx_judgment_run_evidence_item", "judgment_run_evidence", ["evidence_item_id"])
    op.create_index("idx_judgment_run_evidence_result", "judgment_run_evidence", ["assessment_result"])
    op.create_index("idx_judgment_run_evidence_anchor", "judgment_run_evidence", ["anchor_evidence_item_id"])

    op.create_foreign_key(
        "fk_research_questions_spawned_run",
        "research_questions",
        "research_runs",
        ["spawned_by_research_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_research_questions_trigger_evidence",
        "research_questions",
        "evidence_items",
        ["trigger_evidence_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """移除 Batch 4 内部台账，不触碰路线身份、版本和导览正文。"""
    op.drop_constraint("fk_research_questions_trigger_evidence", "research_questions", type_="foreignkey")
    op.drop_constraint("fk_research_questions_spawned_run", "research_questions", type_="foreignkey")
    op.drop_index("idx_route_guides_source_judgment_run", table_name="route_guides")
    op.drop_constraint("fk_route_guides_source_judgment_run", "route_guides", type_="foreignkey")
    op.drop_column("route_guides", "source_judgment_run_id")
    op.drop_table("judgment_run_evidence")
    op.drop_table("evidence_items")
    op.drop_table("research_runs")
    op.drop_table("research_questions")
    op.drop_table("judgment_runs")
