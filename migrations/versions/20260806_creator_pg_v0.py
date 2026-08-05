"""Creator append-only event truth and rebuildable judgment projections.

Revision ID: 20260806_creator_pg_v0
Revises: 20260718_meetup_route_snap
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260806_creator_pg_v0"
down_revision = "20260718_meetup_route_snap"
branch_labels = None
depends_on = None


def _event_fk(*local_columns: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        list(local_columns),
        ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "creator_workspaces",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("current_revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'completed', 'archived')", name="ck_creator_ws_status"),
        sa.CheckConstraint("current_revision >= 0", name="ck_creator_ws_revision"),
        sa.CheckConstraint("id ~ '^[a-zA-Z0-9._-]+$'", name="ck_creator_ws_safe_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "creator_workspace_events",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("base_revision", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("principal_product", sa.String(length=16), nullable=False),
        sa.Column("principal_environment", sa.String(length=16), nullable=False),
        sa.Column("authorized_capability", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.String(length=71), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision > 0 AND base_revision = revision - 1", name="ck_creator_event_revision"),
        sa.CheckConstraint("schema_version = 1", name="ck_creator_event_schema"),
        sa.CheckConstraint("principal_product = 'creator'", name="ck_creator_event_product"),
        sa.CheckConstraint(
            "principal_environment IN ('test', 'shadow', 'production')", name="ck_creator_event_environment"
        ),
        sa.CheckConstraint("payload_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_creator_event_hash"),
        sa.ForeignKeyConstraint(["workspace_id"], ["creator_workspaces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("workspace_id", "revision"),
        sa.UniqueConstraint("workspace_id", "event_id", name="uq_creator_event_id"),
    )
    op.create_index(
        "idx_creator_events_committed", "creator_workspace_events", ["workspace_id", "committed_at"], unique=False
    )
    op.execute(sa.text("""
        CREATE FUNCTION creator_events_reject_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'creator_workspace_events is append-only';
        END;
        $$
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_creator_events_append_only
        BEFORE UPDATE OR DELETE ON creator_workspace_events
        FOR EACH ROW EXECUTE FUNCTION creator_events_reject_mutation()
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_creator_events_no_truncate
        BEFORE TRUNCATE ON creator_workspace_events
        FOR EACH STATEMENT EXECUTE FUNCTION creator_events_reject_mutation()
    """))
    op.create_table(
        "creator_sources",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("immutable_ref", sa.Text(), nullable=False),
        sa.Column("provenance_ref", sa.Text(), nullable=False),
        sa.Column("rights_check_id", sa.Text(), nullable=True),
        sa.Column("rights_decision", sa.String(length=16), nullable=True),
        sa.Column("rights_policy_ref", sa.Text(), nullable=True),
        sa.Column("rights_reason", sa.Text(), nullable=True),
        sa.Column("source_event_revision", sa.BigInteger(), nullable=False),
        sa.Column("rights_event_revision", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "rights_decision IS NULL OR rights_decision IN ('allowed', 'forbidden', 'needs_review')",
            name="ck_creator_source_rights",
        ),
        sa.CheckConstraint(
            "(rights_check_id IS NULL AND rights_decision IS NULL AND rights_policy_ref IS NULL "
            "AND rights_reason IS NULL AND rights_event_revision IS NULL) OR "
            "(rights_check_id IS NOT NULL AND rights_decision IS NOT NULL AND rights_policy_ref IS NOT NULL "
            "AND rights_reason IS NOT NULL AND rights_event_revision IS NOT NULL)",
            name="ck_creator_source_rights_bundle",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "rights_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "source_ref"),
    )
    op.create_table(
        "creator_rights_checks",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("rights_check_id", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("policy_ref", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('allowed', 'forbidden', 'needs_review')", name="ck_creator_rights_decision"
        ),
        _event_fk("workspace_id", "event_revision"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_ref"],
            ["creator_sources.workspace_id", "creator_sources.source_ref"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "rights_check_id"),
    )
    op.create_table(
        "creator_source_messages",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("source_message_ref", sa.Text(), nullable=False),
        sa.Column("source_role", sa.String(length=24), nullable=False),
        sa.Column("actor", sa.String(length=24), nullable=False),
        sa.Column("authorship_basis", sa.String(length=32), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("subject_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interaction_proposal_id", sa.Text(), nullable=True),
        sa.Column("interaction_statement_hash", sa.String(length=71), nullable=True),
        sa.Column("interaction_response", sa.String(length=16), nullable=True),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(subject_refs) = 'array'", name="ck_creator_turn_subjects"),
        sa.CheckConstraint(
            "(interaction_proposal_id IS NULL AND interaction_statement_hash IS NULL AND interaction_response IS NULL) OR "
            "(interaction_proposal_id IS NOT NULL AND interaction_statement_hash IS NOT NULL "
            "AND interaction_response IN ('tim_confirmed', 'rejected') AND source_role = 'user' AND actor = 'tim')",
            name="ck_creator_turn_interaction",
        ),
        _event_fk("workspace_id", "event_revision"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_ref"],
            ["creator_sources.workspace_id", "creator_sources.source_ref"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "turn_id"),
        sa.UniqueConstraint("workspace_id", "source_message_ref", name="uq_creator_source_msg"),
        sa.UniqueConstraint(
            "workspace_id", "turn_id", "interaction_proposal_id", "interaction_statement_hash",
            "interaction_response", name="uq_creator_turn_interaction"
        ),
    )
    op.create_table(
        "creator_source_message_subjects",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["creator_source_messages.workspace_id", "creator_source_messages.turn_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "turn_id", "subject_ref"),
    )
    op.create_table(
        "creator_evidence_items",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("raw_observation", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        _event_fk("workspace_id", "event_revision"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_ref"],
            ["creator_sources.workspace_id", "creator_sources.source_ref"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "evidence_id"),
        sa.UniqueConstraint("workspace_id", "evidence_id", "subject_ref", name="uq_creator_evidence_subject"),
    )
    op.create_table(
        "creator_judgments",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("judgment_key", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("statement_hash", sa.String(length=71), nullable=False),
        sa.Column("typed_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("temporality", sa.String(length=16), nullable=False),
        sa.Column("review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("supersedes_proposal_id", sa.Text(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_compiler_version", sa.Text(), nullable=False),
        sa.Column("context_request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_request_hash", sa.String(length=71), nullable=False),
        sa.Column("context_hash", sa.String(length=71), nullable=False),
        sa.Column("model_ref", sa.Text(), nullable=False),
        sa.Column("proposal_reason", sa.Text(), nullable=False),
        sa.Column("proposal_event_revision", sa.BigInteger(), nullable=False),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('proposed', 'tim_confirmed', 'rejected')", name="ck_creator_judgment_status"),
        sa.CheckConstraint(
            "temporality IN ('permanent', 'slow_changing', 'temporary')", name="ck_creator_judgment_temporality"
        ),
        sa.CheckConstraint("temporality = 'permanent' OR review_at IS NOT NULL", name="ck_creator_judgment_review"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supersedes_proposal_id", "judgment_key"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.judgment_key"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "proposal_id"),
        sa.UniqueConstraint("workspace_id", "proposal_id", "statement_hash", name="uq_creator_judgment_statement"),
        sa.UniqueConstraint("workspace_id", "proposal_id", "judgment_key", name="uq_creator_judgment_key_ref"),
        sa.UniqueConstraint("workspace_id", "proposal_id", "subject_ref", name="uq_creator_judgment_subject"),
    )
    op.create_index(
        "uq_creator_judgment_pending", "creator_judgments", ["workspace_id", "judgment_key"],
        unique=True, postgresql_where=sa.text("status = 'proposed' AND superseded_at IS NULL")
    )
    op.create_index(
        "uq_creator_judgment_current", "creator_judgments", ["workspace_id", "judgment_key"],
        unique=True, postgresql_where=sa.text("status = 'tim_confirmed' AND superseded_at IS NULL")
    )
    op.create_table(
        "creator_judgment_turns",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["creator_source_messages.workspace_id", "creator_source_messages.turn_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "proposal_id", "turn_id"),
    )
    op.create_table(
        "creator_judgment_evidence",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "evidence_id"],
            ["creator_evidence_items.workspace_id", "creator_evidence_items.evidence_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "proposal_id", "evidence_id"),
    )
    op.create_table(
        "creator_judgment_decisions",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("decision_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("response_turn_id", sa.Text(), nullable=False),
        sa.Column("response", sa.String(length=16), nullable=False),
        sa.Column("expected_statement_hash", sa.String(length=71), nullable=False),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.Column("reviewer_principal_id", sa.Text(), nullable=False),
        sa.CheckConstraint("response IN ('tim_confirmed', 'rejected')", name="ck_creator_decision_response"),
        _event_fk("workspace_id", "event_revision"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_id", "expected_statement_hash"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.statement_hash"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "response_turn_id", "proposal_id", "expected_statement_hash", "response"],
            [
                "creator_source_messages.workspace_id", "creator_source_messages.turn_id",
                "creator_source_messages.interaction_proposal_id",
                "creator_source_messages.interaction_statement_hash",
                "creator_source_messages.interaction_response",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "decision_id"),
        sa.UniqueConstraint("workspace_id", "proposal_id", name="uq_creator_decision_proposal"),
        sa.UniqueConstraint("workspace_id", "response_turn_id", name="uq_creator_decision_turn"),
    )
    op.create_table(
        "creator_judgment_contradictions",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("contradiction_id", sa.Text(), nullable=False),
        sa.Column("judgment_id", sa.Text(), nullable=False),
        sa.Column("subject_ref", sa.Text(), nullable=False),
        sa.Column("contradicting_evidence_id", sa.Text(), nullable=True),
        sa.Column("contradicting_turn_id", sa.Text(), nullable=True),
        sa.Column("contradicting_judgment_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=24), nullable=True),
        sa.Column("resolution_ref", sa.Text(), nullable=True),
        sa.Column("recorded_event_revision", sa.BigInteger(), nullable=False),
        sa.Column("resolved_event_revision", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "num_nonnulls(contradicting_evidence_id, contradicting_turn_id, contradicting_judgment_id) = 1",
            name="ck_creator_contradiction_ref",
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('dismissed', 'superseded', 'needs_more_evidence')",
            name="ck_creator_contradiction_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "judgment_id", "subject_ref"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.subject_ref"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "contradicting_evidence_id", "subject_ref"],
            ["creator_evidence_items.workspace_id", "creator_evidence_items.evidence_id", "creator_evidence_items.subject_ref"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "contradicting_turn_id", "subject_ref"],
            ["creator_source_message_subjects.workspace_id", "creator_source_message_subjects.turn_id", "creator_source_message_subjects.subject_ref"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "contradicting_judgment_id", "subject_ref"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.subject_ref"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "recorded_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "resolved_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "contradiction_id"),
    )
    op.create_index(
        "idx_creator_contradiction_open", "creator_judgment_contradictions", ["workspace_id", "subject_ref"],
        unique=False, postgresql_where=sa.text("resolved_at IS NULL")
    )
    op.create_table(
        "creator_judgment_contradiction_resolutions",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("resolution_id", sa.Text(), nullable=False),
        sa.Column("contradiction_id", sa.Text(), nullable=False),
        sa.Column("resolution", sa.String(length=24), nullable=False),
        sa.Column("resolution_ref", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "resolution IN ('dismissed', 'superseded', 'needs_more_evidence')", name="ck_creator_resolution_kind"
        ),
        _event_fk("workspace_id", "event_revision"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "contradiction_id"],
            ["creator_judgment_contradictions.workspace_id", "creator_judgment_contradictions.contradiction_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "resolution_id"),
    )


def downgrade() -> None:
    event_count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM creator_workspace_events")).scalar_one()
    if event_count:
        raise RuntimeError("Creator 事件真值已有数据，拒绝会丢失来源与 Tim 判断的 downgrade")
    op.drop_table("creator_judgment_contradiction_resolutions")
    op.drop_index("idx_creator_contradiction_open", table_name="creator_judgment_contradictions")
    op.drop_table("creator_judgment_contradictions")
    op.drop_table("creator_judgment_decisions")
    op.drop_table("creator_judgment_evidence")
    op.drop_table("creator_judgment_turns")
    op.drop_index("uq_creator_judgment_current", table_name="creator_judgments")
    op.drop_index("uq_creator_judgment_pending", table_name="creator_judgments")
    op.drop_table("creator_judgments")
    op.drop_table("creator_evidence_items")
    op.drop_table("creator_source_message_subjects")
    op.drop_table("creator_source_messages")
    op.drop_table("creator_rights_checks")
    op.drop_table("creator_sources")
    op.drop_index("idx_creator_events_committed", table_name="creator_workspace_events")
    op.drop_table("creator_workspace_events")
    op.execute(sa.text("DROP FUNCTION IF EXISTS creator_events_reject_mutation()"))
    op.drop_table("creator_workspaces")
