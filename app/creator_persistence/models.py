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
    committed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["workspace_id"], ["creator_workspaces.id"], ondelete="RESTRICT"),
        UniqueConstraint("workspace_id", "event_id", name="uq_creator_event_id"),
        CheckConstraint("revision > 0 AND base_revision = revision - 1", name="ck_creator_event_revision"),
        CheckConstraint("schema_version = 1", name="ck_creator_event_schema"),
        CheckConstraint("principal_product = 'creator'", name="ck_creator_event_product"),
        CheckConstraint(
            "principal_environment IN ('test', 'shadow', 'production')",
            name="ck_creator_event_environment",
        ),
        CheckConstraint(
            "payload_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_creator_event_hash",
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
