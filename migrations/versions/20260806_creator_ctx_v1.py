"""Creator interpretation, task state, promotion lineage and calibration.

Revision ID: 20260806_creator_ctx_v1
Revises: 20260806_creator_pg_v0
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260806_creator_ctx_v1"
down_revision = "20260806_creator_pg_v0"
branch_labels = None
depends_on = None


def _event_fk(revision_column: str = "event_revision") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["workspace_id", revision_column],
        ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.drop_constraint("ck_creator_event_schema", "creator_workspace_events", type_="check")
    op.create_check_constraint(
        "ck_creator_event_schema",
        "creator_workspace_events",
        "schema_version = 1 OR (schema_version = 2 AND event_type = 'creator.judgment_proposed')",
    )
    op.add_column("creator_workspace_events", sa.Column("derivation_key_id", sa.Text(), nullable=True))
    op.add_column(
        "creator_workspace_events", sa.Column("derivation_signature", sa.String(length=94), nullable=True)
    )
    op.add_column(
        "creator_workspace_events", sa.Column("derivation_prior_records_hash", sa.String(length=71), nullable=True)
    )
    op.create_check_constraint(
        "ck_creator_event_derivation_proof",
        "creator_workspace_events",
        "(((event_type IN ('creator.turn_interpretation_proposed', 'creator.task_state_changed', "
        "'creator.behavior_calibration_recorded', "
        "'creator.judgment_promotion_proposed')) OR "
        "(event_type = 'creator.judgment_proposed' AND schema_version = 2)) "
        "AND derivation_key_id IS NOT NULL AND derivation_signature IS NOT NULL "
        "AND derivation_prior_records_hash IS NOT NULL) OR "
        "((NOT ((event_type IN ('creator.turn_interpretation_proposed', 'creator.task_state_changed', "
        "'creator.behavior_calibration_recorded', "
        "'creator.judgment_promotion_proposed')) OR "
        "(event_type = 'creator.judgment_proposed' AND schema_version = 2))) "
        "AND derivation_key_id IS NULL AND derivation_signature IS NULL "
        "AND derivation_prior_records_hash IS NULL)",
    )
    op.create_check_constraint(
        "ck_creator_event_derivation_format",
        "creator_workspace_events",
        "derivation_signature IS NULL OR (derivation_key_id <> '' "
        "AND derivation_signature ~ '^ed25519:[A-Za-z0-9_-]{86}$' "
        "AND derivation_prior_records_hash ~ '^sha256:[0-9a-f]{64}$')",
    )
    op.create_table(
        "creator_turn_interpretations",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("interpretation_id", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("subject_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("speech_acts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("epistemic_status", sa.String(length=16), nullable=False),
        sa.Column("scope_level", sa.String(length=16), nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("persistence_intent", sa.String(length=24), nullable=False),
        sa.Column("annotation_basis", sa.String(length=24), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("confidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("alternatives", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supporting_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("counterevidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action_effect", sa.String(length=32), nullable=False),
        sa.Column("review_when", sa.Text(), nullable=False),
        sa.Column("context_compiler_version", sa.Text(), nullable=False),
        sa.Column("context_request_hash", sa.String(length=71), nullable=False),
        sa.Column("context_task", sa.Text(), nullable=False),
        sa.Column("context_subject_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_max_pending_turns", sa.BigInteger(), nullable=False),
        sa.Column("context_max_evidence", sa.BigInteger(), nullable=False),
        sa.Column("context_max_interpretations", sa.BigInteger(), nullable=False),
        sa.Column("context_hash", sa.String(length=71), nullable=False),
        sa.Column("model_ref", sa.Text(), nullable=False),
        sa.Column("supersedes_interpretation_id", sa.Text(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(subject_refs) = 'array'", name="ck_creator_interp_subjects"),
        sa.CheckConstraint("jsonb_typeof(speech_acts) = 'array'", name="ck_creator_interp_acts"),
        sa.CheckConstraint("jsonb_typeof(alternatives) = 'array'", name="ck_creator_interp_alts"),
        sa.CheckConstraint("jsonb_typeof(supporting_refs) = 'array'", name="ck_creator_interp_support"),
        sa.CheckConstraint("jsonb_typeof(counterevidence_refs) = 'array'", name="ck_creator_interp_counter"),
        sa.CheckConstraint("jsonb_typeof(relations) = 'array'", name="ck_creator_interp_relations"),
        sa.CheckConstraint("jsonb_typeof(confidence) = 'number'", name="ck_creator_interp_conf_type"),
        sa.CheckConstraint("((confidence #>> '{}')::numeric BETWEEN 0 AND 1)", name="ck_creator_interp_conf_range"),
        sa.CheckConstraint("jsonb_typeof(context_subject_refs) = 'array'", name="ck_creator_interp_ctx_subjects"),
        sa.CheckConstraint(
            "context_max_pending_turns >= 0 AND context_max_pending_turns <= 9007199254740991 "
            "AND context_max_evidence >= 0 AND context_max_evidence <= 9007199254740991 "
            "AND context_max_interpretations >= 0 AND context_max_interpretations <= 9007199254740991",
            name="ck_creator_interp_ctx_budgets",
        ),
        sa.CheckConstraint(
            "epistemic_status IN ('explicit', 'inferred', 'ambiguous', 'hypothetical', 'unknown')",
            name="ck_creator_interp_epistemic",
        ),
        sa.CheckConstraint(
            "scope_level IN ('turn', 'task', 'project', 'cross_project', 'global')",
            name="ck_creator_interp_scope",
        ),
        sa.CheckConstraint(
            "persistence_intent IN ('ephemeral', 'task_local', 'provisional', 'durable_explicit', 'unknown')",
            name="ck_creator_interp_persistence",
        ),
        sa.CheckConstraint(
            "annotation_basis IN ('direct_language', 'agent_inference', 'mechanical')",
            name="ck_creator_interp_annotation",
        ),
        sa.CheckConstraint(
            "action_effect IN ('none', 'inform_context', 'change_current_task', 'candidate_for_promotion', 'request_clarification')",
            name="ck_creator_interp_action",
        ),
        _event_fk(),
        sa.ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["creator_source_messages.workspace_id", "creator_source_messages.turn_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supersedes_interpretation_id"],
            ["creator_turn_interpretations.workspace_id", "creator_turn_interpretations.interpretation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "interpretation_id"),
    )
    op.create_table(
        "creator_task_states",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("task_state_id", sa.Text(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("project_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("open_loops", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_turn_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("supersedes_task_state_id", sa.Text(), nullable=True),
        sa.Column("source_interpretation_ref", sa.Text(), nullable=True),
        sa.Column("engine_ref", sa.Text(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'blocked', 'completed')", name="ck_creator_task_status"),
        sa.CheckConstraint("jsonb_typeof(acceptance_criteria) = 'array'", name="ck_creator_task_acceptance"),
        sa.CheckConstraint("jsonb_typeof(open_loops) = 'array'", name="ck_creator_task_loops"),
        sa.CheckConstraint("jsonb_typeof(source_turn_refs) = 'array'", name="ck_creator_task_turns"),
        sa.CheckConstraint(
            "(supersedes_task_state_id IS NULL AND source_interpretation_ref IS NULL AND engine_ref IS NULL) OR "
            "(supersedes_task_state_id IS NOT NULL AND source_interpretation_ref IS NOT NULL "
            "AND engine_ref = 'creator-task-state-engine-v0')",
            name="ck_creator_task_update_bundle",
        ),
        _event_fk(),
        sa.ForeignKeyConstraint(
            ["workspace_id", "supersedes_task_state_id"],
            ["creator_task_states.workspace_id", "creator_task_states.task_state_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_interpretation_ref"],
            ["creator_turn_interpretations.workspace_id", "creator_turn_interpretations.interpretation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "task_state_id"),
    )
    op.create_index(
        "uq_creator_task_current", "creator_task_states", ["workspace_id", "task_ref"], unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_table(
        "creator_behavior_calibrations",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("calibration_id", sa.Text(), nullable=False),
        sa.Column("task_ref", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("authority", sa.String(length=24), nullable=False),
        sa.Column("prediction", sa.Text(), nullable=False),
        sa.Column("observed_result", sa.Text(), nullable=False),
        sa.Column("context_hash", sa.String(length=71), nullable=False),
        sa.Column("context_item_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("verdict IN ('pass', 'fail', 'needs_more_evidence')", name="ck_creator_cal_verdict"),
        sa.CheckConstraint(
            "metric IN ('first_understanding', 'repeat_correction', 'overpromotion', 'missed_recall', "
            "'conflict_challenge', 'context_usefulness')",
            name="ck_creator_cal_metric",
        ),
        sa.CheckConstraint(
            "authority IN ('agent_assessed', 'tim_confirmed', 'mechanical', 'real_world')",
            name="ck_creator_cal_authority",
        ),
        sa.CheckConstraint("jsonb_typeof(context_item_refs) = 'array'", name="ck_creator_cal_refs"),
        _event_fk(),
        sa.PrimaryKeyConstraint("workspace_id", "calibration_id"),
    )

    op.add_column(
        "creator_judgments",
        sa.Column(
            "proposal_event_type", sa.String(length=48), nullable=False,
            server_default=sa.text("'creator.judgment_proposed'"),
        ),
    )
    op.add_column("creator_judgments", sa.Column("context_task_ref", sa.Text(), nullable=True))
    op.add_column("creator_judgments", sa.Column("context_max_interpretations", sa.BigInteger(), nullable=True))
    op.add_column("creator_judgments", sa.Column("promotion_basis", sa.String(length=32), nullable=True))
    op.add_column(
        "creator_judgments",
        sa.Column("promotion_basis_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_creator_judgment_promotion_bundle",
        "creator_judgments",
        "(proposal_event_type = 'creator.judgment_proposed' AND context_task_ref IS NULL "
        "AND context_max_interpretations IS NULL AND promotion_basis IS NULL AND promotion_basis_refs IS NULL) OR "
        "(proposal_event_type = 'creator.judgment_promotion_proposed' AND context_task_ref IS NOT NULL "
        "AND context_max_interpretations > 0 AND context_max_interpretations <= 9007199254740991 "
        "AND promotion_basis IS NOT NULL AND promotion_basis_refs IS NOT NULL "
        "AND jsonb_typeof(promotion_basis_refs) = 'array')",
    )
    op.create_table(
        "creator_judgment_interpretations",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("interpretation_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "interpretation_id"],
            ["creator_turn_interpretations.workspace_id", "creator_turn_interpretations.interpretation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "proposal_id", "interpretation_id"),
    )


def downgrade() -> None:
    new_event_count = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM creator_workspace_events WHERE event_type IN ("
        "'creator.turn_interpretation_proposed', 'creator.task_state_changed', "
        "'creator.behavior_calibration_recorded', 'creator.judgment_promotion_proposed') "
        "OR schema_version = 2"
    )).scalar_one()
    if new_event_count:
        raise RuntimeError("Creator 解释与升格事件已有数据，拒绝丢失原话谱系和行为评测的 downgrade")
    op.drop_table("creator_judgment_interpretations")
    op.drop_constraint("ck_creator_judgment_promotion_bundle", "creator_judgments", type_="check")
    op.drop_column("creator_judgments", "promotion_basis_refs")
    op.drop_column("creator_judgments", "promotion_basis")
    op.drop_column("creator_judgments", "context_max_interpretations")
    op.drop_column("creator_judgments", "context_task_ref")
    op.drop_column("creator_judgments", "proposal_event_type")
    op.drop_table("creator_behavior_calibrations")
    op.drop_index("uq_creator_task_current", table_name="creator_task_states")
    op.drop_table("creator_task_states")
    op.drop_table("creator_turn_interpretations")
    op.drop_constraint("ck_creator_event_derivation_format", "creator_workspace_events", type_="check")
    op.drop_constraint("ck_creator_event_derivation_proof", "creator_workspace_events", type_="check")
    op.drop_column("creator_workspace_events", "derivation_prior_records_hash")
    op.drop_column("creator_workspace_events", "derivation_signature")
    op.drop_column("creator_workspace_events", "derivation_key_id")
    op.drop_constraint("ck_creator_event_schema", "creator_workspace_events", type_="check")
    op.create_check_constraint("ck_creator_event_schema", "creator_workspace_events", "schema_version = 1")
