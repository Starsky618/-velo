"""Append-only Creator event truth and same-transaction read projections.

These tables are private to the Creator/Domain Plane boundary. They do not
replace route cognition or any rider-facing table.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.database import Base


class CreatorWorkspace(Base):
    __tablename__ = "creator_workspaces"

    id = Column(Text, primary_key=True)
    mission = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default="active")
    current_revision = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active', 'completed', 'archived')", name="ck_creator_ws_status"),
        CheckConstraint("current_revision >= 0", name="ck_creator_ws_revision"),
        CheckConstraint("id ~ '^[a-zA-Z0-9._-]+$'", name="ck_creator_ws_safe_id"),
    )


class CreatorWorkspaceEvent(Base):
    __tablename__ = "creator_workspace_events"

    workspace_id = Column(Text, primary_key=True)
    revision = Column(BigInteger, primary_key=True)
    event_id = Column(Text, nullable=False)
    event_type = Column(String(64), nullable=False)
    schema_version = Column(SmallInteger, nullable=False)
    base_revision = Column(BigInteger, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    principal_id = Column(Text, nullable=False)
    principal_product = Column(String(16), nullable=False)
    principal_environment = Column(String(16), nullable=False)
    authorized_capability = Column(String(64), nullable=False)
    payload_json = Column(JSONB, nullable=False)
    payload_sha256 = Column(String(71), nullable=False)
    derivation_key_id = Column(Text, nullable=True)
    derivation_signature = Column(String(94), nullable=True)
    derivation_prior_records_hash = Column(String(71), nullable=True)
    committed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["workspace_id"], ["creator_workspaces.id"], ondelete="RESTRICT"),
        UniqueConstraint("workspace_id", "event_id", name="uq_creator_event_id"),
        CheckConstraint("revision > 0 AND base_revision = revision - 1", name="ck_creator_event_revision"),
        CheckConstraint(
            "schema_version = 1 OR (schema_version = 2 AND event_type = 'creator.judgment_proposed')",
            name="ck_creator_event_schema",
        ),
        CheckConstraint("principal_product = 'creator'", name="ck_creator_event_product"),
        CheckConstraint(
            "principal_environment IN ('test', 'shadow', 'production')",
            name="ck_creator_event_environment",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_creator_event_hash",
        ),
        CheckConstraint(
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
            name="ck_creator_event_derivation_proof",
        ),
        CheckConstraint(
            "derivation_signature IS NULL OR (derivation_key_id <> '' "
            "AND derivation_signature ~ '^ed25519:[A-Za-z0-9_-]{86}$' "
            "AND derivation_prior_records_hash ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_creator_event_derivation_format",
        ),
        Index("idx_creator_events_committed", "workspace_id", "committed_at"),
    )


class CreatorSource(Base):
    __tablename__ = "creator_sources"

    workspace_id = Column(Text, primary_key=True)
    source_ref = Column(Text, primary_key=True)
    source_kind = Column(String(32), nullable=False)
    content_hash = Column(String(71), nullable=False)
    immutable_ref = Column(Text, nullable=False)
    provenance_ref = Column(Text, nullable=False)
    rights_check_id = Column(Text, nullable=True)
    rights_decision = Column(String(16), nullable=True)
    rights_policy_ref = Column(Text, nullable=True)
    rights_reason = Column(Text, nullable=True)
    source_event_revision = Column(BigInteger, nullable=False)
    rights_event_revision = Column(BigInteger, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "rights_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "rights_decision IS NULL OR rights_decision IN ('allowed', 'forbidden', 'needs_review')",
            name="ck_creator_source_rights",
        ),
        CheckConstraint(
            "(rights_check_id IS NULL AND rights_decision IS NULL AND rights_policy_ref IS NULL "
            "AND rights_reason IS NULL AND rights_event_revision IS NULL) OR "
            "(rights_check_id IS NOT NULL AND rights_decision IS NOT NULL AND rights_policy_ref IS NOT NULL "
            "AND rights_reason IS NOT NULL AND rights_event_revision IS NOT NULL)",
            name="ck_creator_source_rights_bundle",
        ),
    )


class CreatorRightsCheck(Base):
    __tablename__ = "creator_rights_checks"

    workspace_id = Column(Text, primary_key=True)
    rights_check_id = Column(Text, primary_key=True)
    source_ref = Column(Text, nullable=False)
    decision = Column(String(16), nullable=False)
    policy_ref = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_ref"],
            ["creator_sources.workspace_id", "creator_sources.source_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('allowed', 'forbidden', 'needs_review')",
            name="ck_creator_rights_decision",
        ),
    )


class CreatorSourceMessage(Base):
    __tablename__ = "creator_source_messages"

    workspace_id = Column(Text, primary_key=True)
    turn_id = Column(Text, primary_key=True)
    source_ref = Column(Text, nullable=False)
    source_message_ref = Column(Text, nullable=False)
    source_role = Column(String(24), nullable=False)
    actor = Column(String(24), nullable=False)
    authorship_basis = Column(String(32), nullable=False)
    raw_text = Column(Text, nullable=False)
    content_hash = Column(String(71), nullable=False)
    subject_refs = Column(JSONB, nullable=False)
    interaction_proposal_id = Column(Text, nullable=True)
    interaction_statement_hash = Column(String(71), nullable=True)
    interaction_response = Column(String(16), nullable=True)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_ref"],
            ["creator_sources.workspace_id", "creator_sources.source_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "source_message_ref", name="uq_creator_source_msg"),
        UniqueConstraint(
            "workspace_id", "turn_id", "interaction_proposal_id",
            "interaction_statement_hash", "interaction_response",
            name="uq_creator_turn_interaction",
        ),
        CheckConstraint("jsonb_typeof(subject_refs) = 'array'", name="ck_creator_turn_subjects"),
        CheckConstraint(
            "(interaction_proposal_id IS NULL AND interaction_statement_hash IS NULL AND interaction_response IS NULL) OR "
            "(interaction_proposal_id IS NOT NULL AND interaction_statement_hash IS NOT NULL "
            "AND interaction_response IN ('tim_confirmed', 'rejected') AND source_role = 'user' AND actor = 'tim')",
            name="ck_creator_turn_interaction",
        ),
    )


class CreatorSourceMessageSubject(Base):
    __tablename__ = "creator_source_message_subjects"

    workspace_id = Column(Text, primary_key=True)
    turn_id = Column(Text, primary_key=True)
    subject_ref = Column(Text, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["creator_source_messages.workspace_id", "creator_source_messages.turn_id"],
            ondelete="RESTRICT",
        ),
    )


class CreatorEvidenceItem(Base):
    __tablename__ = "creator_evidence_items"

    workspace_id = Column(Text, primary_key=True)
    evidence_id = Column(Text, primary_key=True)
    source_ref = Column(Text, nullable=False)
    subject_ref = Column(Text, nullable=False)
    raw_observation = Column(Text, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_ref"],
            ["creator_sources.workspace_id", "creator_sources.source_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "evidence_id", "subject_ref", name="uq_creator_evidence_subject"),
    )


class CreatorTurnInterpretation(Base):
    __tablename__ = "creator_turn_interpretations"

    workspace_id = Column(Text, primary_key=True)
    interpretation_id = Column(Text, primary_key=True)
    turn_id = Column(Text, nullable=False)
    task_ref = Column(Text, nullable=False)
    subject_refs = Column(JSONB, nullable=False)
    speech_acts = Column(JSONB, nullable=False)
    epistemic_status = Column(String(16), nullable=False)
    scope_level = Column(String(16), nullable=False)
    scope_ref = Column(Text, nullable=False)
    persistence_intent = Column(String(24), nullable=False)
    annotation_basis = Column(String(24), nullable=False)
    claim = Column(Text, nullable=False)
    confidence = Column(JSONB, nullable=False)
    alternatives = Column(JSONB, nullable=False)
    supporting_refs = Column(JSONB, nullable=False)
    counterevidence_refs = Column(JSONB, nullable=False)
    relations = Column(JSONB, nullable=False)
    action_effect = Column(String(32), nullable=False)
    review_when = Column(Text, nullable=False)
    context_compiler_version = Column(Text, nullable=False)
    context_request_hash = Column(String(71), nullable=False)
    context_task = Column(Text, nullable=False)
    context_subject_refs = Column(JSONB, nullable=False)
    context_as_of = Column(DateTime(timezone=True), nullable=False)
    context_max_pending_turns = Column(BigInteger, nullable=False)
    context_max_evidence = Column(BigInteger, nullable=False)
    context_max_interpretations = Column(BigInteger, nullable=False)
    context_hash = Column(String(71), nullable=False)
    model_ref = Column(Text, nullable=False)
    supersedes_interpretation_id = Column(Text, nullable=True)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["creator_source_messages.workspace_id", "creator_source_messages.turn_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supersedes_interpretation_id"],
            ["creator_turn_interpretations.workspace_id", "creator_turn_interpretations.interpretation_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("jsonb_typeof(subject_refs) = 'array'", name="ck_creator_interp_subjects"),
        CheckConstraint("jsonb_typeof(speech_acts) = 'array'", name="ck_creator_interp_acts"),
        CheckConstraint("jsonb_typeof(alternatives) = 'array'", name="ck_creator_interp_alts"),
        CheckConstraint("jsonb_typeof(supporting_refs) = 'array'", name="ck_creator_interp_support"),
        CheckConstraint("jsonb_typeof(counterevidence_refs) = 'array'", name="ck_creator_interp_counter"),
        CheckConstraint("jsonb_typeof(relations) = 'array'", name="ck_creator_interp_relations"),
        CheckConstraint("jsonb_typeof(confidence) = 'number'", name="ck_creator_interp_conf_type"),
        CheckConstraint("((confidence #>> '{}')::numeric BETWEEN 0 AND 1)", name="ck_creator_interp_conf_range"),
        CheckConstraint("jsonb_typeof(context_subject_refs) = 'array'", name="ck_creator_interp_ctx_subjects"),
        CheckConstraint(
            "context_max_pending_turns >= 0 AND context_max_pending_turns <= 9007199254740991 "
            "AND context_max_evidence >= 0 AND context_max_evidence <= 9007199254740991 "
            "AND context_max_interpretations >= 0 AND context_max_interpretations <= 9007199254740991",
            name="ck_creator_interp_ctx_budgets",
        ),
        CheckConstraint(
            "epistemic_status IN ('explicit', 'inferred', 'ambiguous', 'hypothetical', 'unknown')",
            name="ck_creator_interp_epistemic",
        ),
        CheckConstraint(
            "scope_level IN ('turn', 'task', 'project', 'cross_project', 'global')",
            name="ck_creator_interp_scope",
        ),
        CheckConstraint(
            "persistence_intent IN ('ephemeral', 'task_local', 'provisional', 'durable_explicit', 'unknown')",
            name="ck_creator_interp_persistence",
        ),
        CheckConstraint(
            "annotation_basis IN ('direct_language', 'agent_inference', 'mechanical')",
            name="ck_creator_interp_annotation",
        ),
        CheckConstraint(
            "action_effect IN ('none', 'inform_context', 'change_current_task', 'candidate_for_promotion', 'request_clarification')",
            name="ck_creator_interp_action",
        ),
    )


class CreatorTaskStateRecord(Base):
    __tablename__ = "creator_task_states"

    workspace_id = Column(Text, primary_key=True)
    task_state_id = Column(Text, primary_key=True)
    task_ref = Column(Text, nullable=False)
    project_ref = Column(Text, nullable=False)
    status = Column(String(16), nullable=False)
    objective = Column(Text, nullable=False)
    focus = Column(Text, nullable=False)
    acceptance_criteria = Column(JSONB, nullable=False)
    open_loops = Column(JSONB, nullable=False)
    source_turn_refs = Column(JSONB, nullable=False)
    supersedes_task_state_id = Column(Text, nullable=True)
    source_interpretation_ref = Column(Text, nullable=True)
    engine_ref = Column(Text, nullable=True)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supersedes_task_state_id"],
            ["creator_task_states.workspace_id", "creator_task_states.task_state_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_interpretation_ref"],
            ["creator_turn_interpretations.workspace_id", "creator_turn_interpretations.interpretation_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('active', 'blocked', 'completed')", name="ck_creator_task_status"),
        CheckConstraint("jsonb_typeof(acceptance_criteria) = 'array'", name="ck_creator_task_acceptance"),
        CheckConstraint("jsonb_typeof(open_loops) = 'array'", name="ck_creator_task_loops"),
        CheckConstraint("jsonb_typeof(source_turn_refs) = 'array'", name="ck_creator_task_turns"),
        CheckConstraint(
            "(supersedes_task_state_id IS NULL AND source_interpretation_ref IS NULL AND engine_ref IS NULL) OR "
            "(supersedes_task_state_id IS NOT NULL AND source_interpretation_ref IS NOT NULL "
            "AND engine_ref = 'creator-task-state-engine-v0')",
            name="ck_creator_task_update_bundle",
        ),
        Index(
            "uq_creator_task_current", "workspace_id", "task_ref", unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )


class CreatorBehaviorCalibration(Base):
    __tablename__ = "creator_behavior_calibrations"

    workspace_id = Column(Text, primary_key=True)
    calibration_id = Column(Text, primary_key=True)
    task_ref = Column(Text, nullable=False)
    metric = Column(String(32), nullable=False)
    verdict = Column(String(24), nullable=False)
    authority = Column(String(24), nullable=False)
    prediction = Column(Text, nullable=False)
    observed_result = Column(Text, nullable=False)
    context_hash = Column(String(71), nullable=False)
    context_item_refs = Column(JSONB, nullable=False)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("verdict IN ('pass', 'fail', 'needs_more_evidence')", name="ck_creator_cal_verdict"),
        CheckConstraint(
            "metric IN ('first_understanding', 'repeat_correction', 'overpromotion', 'missed_recall', "
            "'conflict_challenge', 'context_usefulness')",
            name="ck_creator_cal_metric",
        ),
        CheckConstraint(
            "authority IN ('agent_assessed', 'tim_confirmed', 'mechanical', 'real_world')",
            name="ck_creator_cal_authority",
        ),
        CheckConstraint("jsonb_typeof(context_item_refs) = 'array'", name="ck_creator_cal_refs"),
    )


class CreatorJudgment(Base):
    __tablename__ = "creator_judgments"

    workspace_id = Column(Text, primary_key=True)
    proposal_id = Column(Text, primary_key=True)
    judgment_key = Column(Text, nullable=False)
    subject_ref = Column(Text, nullable=False)
    statement = Column(Text, nullable=False)
    statement_hash = Column(String(71), nullable=False)
    typed_value = Column(JSONB, nullable=False)
    temporality = Column(String(16), nullable=False)
    review_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False)
    supersedes_proposal_id = Column(Text, nullable=True)
    superseded_at = Column(DateTime(timezone=True), nullable=True)
    context_compiler_version = Column(Text, nullable=False)
    context_request_json = Column(JSONB, nullable=False)
    context_request_hash = Column(String(71), nullable=False)
    context_hash = Column(String(71), nullable=False)
    model_ref = Column(Text, nullable=False)
    proposal_event_type = Column(String(48), nullable=False, server_default="creator.judgment_proposed")
    context_task_ref = Column(Text, nullable=True)
    context_max_interpretations = Column(BigInteger, nullable=True)
    promotion_basis = Column(String(32), nullable=True)
    # SQL NULL means "not a promotion"; JSON null would violate the bundle CHECK.
    promotion_basis_refs = Column(JSONB(none_as_null=True), nullable=True)
    proposal_reason = Column(Text, nullable=False)
    proposal_event_revision = Column(BigInteger, nullable=False)
    decision_id = Column(Text, nullable=True)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "proposal_id", "statement_hash", name="uq_creator_judgment_statement"),
        UniqueConstraint("workspace_id", "proposal_id", "judgment_key", name="uq_creator_judgment_key_ref"),
        UniqueConstraint("workspace_id", "proposal_id", "subject_ref", name="uq_creator_judgment_subject"),
        ForeignKeyConstraint(
            ["workspace_id", "supersedes_proposal_id", "judgment_key"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.judgment_key"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('proposed', 'tim_confirmed', 'rejected')", name="ck_creator_judgment_status"),
        CheckConstraint("temporality IN ('permanent', 'slow_changing', 'temporary')", name="ck_creator_judgment_temporality"),
        CheckConstraint("temporality = 'permanent' OR review_at IS NOT NULL", name="ck_creator_judgment_review"),
        CheckConstraint(
            "(proposal_event_type = 'creator.judgment_proposed' AND context_task_ref IS NULL "
            "AND context_max_interpretations IS NULL AND promotion_basis IS NULL AND promotion_basis_refs IS NULL) OR "
            "(proposal_event_type = 'creator.judgment_promotion_proposed' AND context_task_ref IS NOT NULL "
            "AND context_max_interpretations > 0 AND context_max_interpretations <= 9007199254740991 "
            "AND promotion_basis IS NOT NULL AND promotion_basis_refs IS NOT NULL "
            "AND jsonb_typeof(promotion_basis_refs) = 'array')",
            name="ck_creator_judgment_promotion_bundle",
        ),
        Index(
            "uq_creator_judgment_pending",
            "workspace_id", "judgment_key",
            unique=True,
            postgresql_where=text("status = 'proposed' AND superseded_at IS NULL"),
        ),
        Index(
            "uq_creator_judgment_current",
            "workspace_id", "judgment_key",
            unique=True,
            postgresql_where=text("status = 'tim_confirmed' AND superseded_at IS NULL"),
        ),
    )


class CreatorJudgmentTurn(Base):
    __tablename__ = "creator_judgment_turns"

    workspace_id = Column(Text, primary_key=True)
    proposal_id = Column(Text, primary_key=True)
    turn_id = Column(Text, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "turn_id"],
            ["creator_source_messages.workspace_id", "creator_source_messages.turn_id"],
            ondelete="RESTRICT",
        ),
    )


class CreatorJudgmentEvidence(Base):
    __tablename__ = "creator_judgment_evidence"

    workspace_id = Column(Text, primary_key=True)
    proposal_id = Column(Text, primary_key=True)
    evidence_id = Column(Text, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "evidence_id"],
            ["creator_evidence_items.workspace_id", "creator_evidence_items.evidence_id"],
            ondelete="RESTRICT",
        ),
    )


class CreatorJudgmentInterpretation(Base):
    __tablename__ = "creator_judgment_interpretations"

    workspace_id = Column(Text, primary_key=True)
    proposal_id = Column(Text, primary_key=True)
    interpretation_id = Column(Text, primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "interpretation_id"],
            ["creator_turn_interpretations.workspace_id", "creator_turn_interpretations.interpretation_id"],
            ondelete="RESTRICT",
        ),
    )


class CreatorJudgmentDecision(Base):
    __tablename__ = "creator_judgment_decisions"

    workspace_id = Column(Text, primary_key=True)
    decision_id = Column(Text, primary_key=True)
    proposal_id = Column(Text, nullable=False)
    response_turn_id = Column(Text, nullable=False)
    response = Column(String(16), nullable=False)
    expected_statement_hash = Column(String(71), nullable=False)
    event_revision = Column(BigInteger, nullable=False)
    reviewer_principal_id = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "proposal_id", name="uq_creator_decision_proposal"),
        UniqueConstraint("workspace_id", "response_turn_id", name="uq_creator_decision_turn"),
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "proposal_id", "expected_statement_hash"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.statement_hash"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "response_turn_id", "proposal_id", "expected_statement_hash", "response"],
            [
                "creator_source_messages.workspace_id", "creator_source_messages.turn_id",
                "creator_source_messages.interaction_proposal_id",
                "creator_source_messages.interaction_statement_hash",
                "creator_source_messages.interaction_response",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("response IN ('tim_confirmed', 'rejected')", name="ck_creator_decision_response"),
    )


class CreatorJudgmentContradiction(Base):
    __tablename__ = "creator_judgment_contradictions"

    workspace_id = Column(Text, primary_key=True)
    contradiction_id = Column(Text, primary_key=True)
    judgment_id = Column(Text, nullable=False)
    subject_ref = Column(Text, nullable=False)
    contradicting_evidence_id = Column(Text, nullable=True)
    contradicting_turn_id = Column(Text, nullable=True)
    contradicting_judgment_id = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    resolution = Column(String(24), nullable=True)
    resolution_ref = Column(Text, nullable=True)
    recorded_event_revision = Column(BigInteger, nullable=False)
    resolved_event_revision = Column(BigInteger, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "judgment_id", "subject_ref"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.subject_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "contradicting_evidence_id", "subject_ref"],
            ["creator_evidence_items.workspace_id", "creator_evidence_items.evidence_id", "creator_evidence_items.subject_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "contradicting_turn_id", "subject_ref"],
            ["creator_source_message_subjects.workspace_id", "creator_source_message_subjects.turn_id", "creator_source_message_subjects.subject_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "contradicting_judgment_id", "subject_ref"],
            ["creator_judgments.workspace_id", "creator_judgments.proposal_id", "creator_judgments.subject_ref"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "recorded_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "resolved_event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(contradicting_evidence_id, contradicting_turn_id, contradicting_judgment_id) = 1",
            name="ck_creator_contradiction_ref",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('dismissed', 'superseded', 'needs_more_evidence')",
            name="ck_creator_contradiction_resolution",
        ),
        Index(
            "idx_creator_contradiction_open",
            "workspace_id", "subject_ref",
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )


class CreatorJudgmentContradictionResolution(Base):
    __tablename__ = "creator_judgment_contradiction_resolutions"

    workspace_id = Column(Text, primary_key=True)
    resolution_id = Column(Text, primary_key=True)
    contradiction_id = Column(Text, nullable=False)
    resolution = Column(String(24), nullable=False)
    resolution_ref = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    event_revision = Column(BigInteger, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "contradiction_id"],
            ["creator_judgment_contradictions.workspace_id", "creator_judgment_contradictions.contradiction_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "event_revision"],
            ["creator_workspace_events.workspace_id", "creator_workspace_events.revision"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "resolution IN ('dismissed', 'superseded', 'needs_more_evidence')",
            name="ck_creator_resolution_kind",
        ),
    )
