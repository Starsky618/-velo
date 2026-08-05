"""Single-transaction Creator event append and projection service.

The TypeScript runtime owns its reducer and model loop. This Python boundary
owns authentication receipts, PostgreSQL revision CAS and relational
constraints. It deliberately supports only the information/judgment slice;
Published World, Rider and other Creator event families remain closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any, Callable

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .canonical import content_hash
from .models import (
    CreatorEvidenceItem,
    CreatorJudgment,
    CreatorJudgmentContradiction,
    CreatorJudgmentContradictionResolution,
    CreatorJudgmentDecision,
    CreatorJudgmentEvidence,
    CreatorJudgmentTurn,
    CreatorRightsCheck,
    CreatorSource,
    CreatorSourceMessage,
    CreatorSourceMessageSubject,
    CreatorWorkspace,
    CreatorWorkspaceEvent,
)


CAPABILITY_BY_EVENT_TYPE = {
    "creator.workspace_started": "workspace.create",
    "creator.source_ingested": "source.ingest",
    "creator.conversation_turn_recorded": "conversation.record",
    "creator.rights_checked": "rights.check",
    "creator.evidence_recorded": "evidence.inspect_raw",
    "creator.judgment_proposed": "judgment.propose",
    "creator.judgment_responded": "judgment.decide",
    "creator.judgment_contradiction_recorded": "judgment.contradict",
    "creator.judgment_contradiction_resolved": "judgment.contradict",
}

BASE_FIELDS = {"schema_version", "event_id", "workspace_id", "base_revision", "occurred_at", "type"}
EVENT_FIELDS = {
    "creator.workspace_started": BASE_FIELDS | {"mission"},
    "creator.source_ingested": BASE_FIELDS | {"source_ref", "source_kind", "content_hash", "immutable_ref", "provenance_ref"},
    "creator.conversation_turn_recorded": BASE_FIELDS | {
        "turn_id", "source_ref", "source_message_ref", "source_role", "actor", "authorship_basis",
        "raw_text", "content_hash", "subject_refs", "interaction",
    },
    "creator.rights_checked": BASE_FIELDS | {"rights_check_id", "source_ref", "decision", "policy_ref", "reason"},
    "creator.evidence_recorded": BASE_FIELDS | {"evidence_id", "source_ref", "subject_ref", "raw_observation", "observed_at"},
    "creator.judgment_proposed": BASE_FIELDS | {
        "proposal_id", "judgment_key", "subject_ref", "statement", "statement_hash", "typed_value",
        "temporality", "context_compiler_version", "context_request_hash", "context_task",
        "context_subject_refs", "context_as_of", "context_max_pending_turns", "context_max_evidence",
        "context_hash", "model_ref", "review_at", "source_turn_refs", "evidence_refs",
        "supersedes_judgment_id", "reason",
    },
    "creator.judgment_responded": BASE_FIELDS | {
        "decision_id", "proposal_id", "response_turn_ref", "response", "expected_statement_hash",
    },
    "creator.judgment_contradiction_recorded": BASE_FIELDS | {
        "contradiction_id", "judgment_id", "contradicting_ref", "reason",
    },
    "creator.judgment_contradiction_resolved": BASE_FIELDS | {
        "resolution_id", "contradiction_id", "resolution", "resolution_ref", "reason",
    },
}

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_SAFE_JSON_INTEGER = 2**53 - 1


class CreatorPersistenceError(RuntimeError):
    """Base error with a stable API-facing code."""

    code = "creator_persistence_error"


class CreatorAppendConflictError(CreatorPersistenceError):
    code = "event_id_conflict"


class CreatorStaleRevisionError(CreatorPersistenceError):
    code = "stale_revision"


class CreatorProjectionError(CreatorPersistenceError):
    code = "projection_conflict"


class CreatorAuthorizationError(CreatorPersistenceError):
    code = "capability_denied"


@dataclass(frozen=True)
class CreatorPrincipal:
    principal_id: str
    product: str
    environment: str
    scopes: tuple[str, ...]

    def require(self, capability: str) -> None:
        if not isinstance(self.principal_id, str) or not self.principal_id.strip():
            raise CreatorAuthorizationError("Creator principal_id must be non-empty")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in self.principal_id):
            raise CreatorAuthorizationError("Creator principal_id must contain only Unicode scalar values")
        if self.product != "creator" or capability not in self.scopes:
            raise CreatorAuthorizationError(f"capability denied for {self.principal_id}: {capability}")
        if self.environment not in {"test", "shadow", "production"}:
            raise CreatorAuthorizationError("invalid Creator principal environment")


@dataclass(frozen=True)
class CreatorAppendReceipt:
    event_id: str
    committed_revision: int
    payload_sha256: str


def _unicode_scalar_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise CreatorProjectionError(f"{label} must be a string")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise CreatorProjectionError(f"{label} must contain only Unicode scalar values")
    return value


def _required_string(value: Any, label: str) -> str:
    result = _unicode_scalar_string(value, label)
    if not result.strip():
        raise CreatorProjectionError(f"{label} must be a non-empty string")
    return result


def _content_hash(value: Any, label: str) -> str:
    result = _required_string(value, label)
    if not HASH_RE.fullmatch(result):
        raise CreatorProjectionError(f"{label} must be a sha256 content hash")
    return result


def _instant(value: Any, label: str) -> datetime:
    text_value = _required_string(value, label)
    if not text_value.endswith("Z"):
        raise CreatorProjectionError(f"{label} must be a canonical UTC instant")
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CreatorProjectionError(f"{label} must be a canonical UTC instant") from exc
    if parsed.tzinfo is None:
        raise CreatorProjectionError(f"{label} must include timezone")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if canonical != text_value:
        raise CreatorProjectionError(f"{label} must be a canonical UTC instant")
    return parsed


def _unique_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise CreatorProjectionError(f"{label} must be a string array")
    for item in value:
        _required_string(item, label)
    if len(set(value)) != len(value):
        raise CreatorProjectionError(f"{label} must not contain duplicates")
    return value


def _safe_json_number(value: Any, label: str) -> int | float:
    if type(value) not in {int, float}:
        raise CreatorProjectionError(f"{label} must be a JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise CreatorProjectionError(f"{label} must be finite")
    if (isinstance(value, int) or value.is_integer()) and abs(value) > MAX_SAFE_JSON_INTEGER:
        raise CreatorProjectionError(f"{label} must be within the JavaScript safe integer range")
    return value


def _javascript_utf16_sort_key(value: str) -> bytes:
    """Match JavaScript Array.sort() string ordering across the HTTP boundary."""
    return value.encode("utf-16-be")


def _validate_event(event: dict[str, Any]) -> tuple[str, datetime]:
    if not isinstance(event, dict):
        raise CreatorProjectionError("Creator event must be an object")
    event_type = _required_string(event.get("type"), "type")
    allowed = EVENT_FIELDS.get(event_type)
    if allowed is None:
        raise CreatorProjectionError(f"event type is outside Creator persistence v0: {event_type}")
    extras = set(event) - allowed
    required = allowed - {"interaction", "review_at", "supersedes_judgment_id"}
    missing = required - set(event)
    if extras or missing:
        raise CreatorProjectionError(
            f"invalid {event_type} fields; missing={sorted(missing)}, extra={sorted(extras)}"
        )
    if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        raise CreatorProjectionError("unsupported Creator event schema_version")
    _required_string(event.get("event_id"), "event_id")
    workspace_id = _required_string(event.get("workspace_id"), "workspace_id")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", workspace_id):
        raise CreatorProjectionError("workspace_id contains unsafe characters")
    if type(event.get("base_revision")) is not int or event["base_revision"] < 0:
        raise CreatorProjectionError("base_revision must be a non-negative integer")
    _safe_json_number(event["base_revision"], "base_revision")
    occurred_at = _instant(event.get("occurred_at"), "occurred_at")

    for field in (
        "mission", "source_ref", "source_kind", "immutable_ref", "provenance_ref", "rights_check_id",
        "policy_ref", "reason", "turn_id", "source_message_ref", "raw_text", "evidence_id", "subject_ref",
        "raw_observation", "proposal_id", "judgment_key", "statement", "context_compiler_version",
        "context_task", "model_ref", "decision_id", "response_turn_ref", "contradiction_id", "judgment_id",
        "contradicting_ref", "resolution_id", "resolution_ref",
    ):
        if field in event:
            _required_string(event[field], field)
    for key in ("content_hash", "statement_hash", "context_request_hash", "context_hash", "expected_statement_hash"):
        if key in event:
            _content_hash(event[key], key)
    if event_type == "creator.conversation_turn_recorded":
        subjects = _unique_strings(event["subject_refs"], "subject_refs")
        interaction = event.get("interaction")
        if interaction is not None:
            expected = {"kind", "proposal_id", "statement_hash", "response"}
            if not isinstance(interaction, dict) or set(interaction) != expected:
                raise CreatorProjectionError("invalid judgment response interaction")
            if interaction["kind"] != "judgment_response" or interaction["response"] not in {"tim_confirmed", "rejected"}:
                raise CreatorProjectionError("invalid judgment response interaction")
            _required_string(interaction["proposal_id"], "interaction.proposal_id")
            _content_hash(interaction["statement_hash"], "interaction.statement_hash")
            if event["actor"] != "tim" or event["source_role"] != "user":
                raise CreatorProjectionError("judgment response interaction requires a Tim user turn")
        if event["actor"] == "tim" and (
            event["source_role"] != "user"
            or event["authorship_basis"] not in {"direct_unquoted_message", "manual_review"}
        ):
            raise CreatorProjectionError("Tim authorship requires direct or manually reviewed user evidence")
        if not subjects and interaction is not None:
            raise CreatorProjectionError("judgment response turn requires a subject")
        if event["source_role"] not in {"user", "assistant", "tool", "system", "external_material"}:
            raise CreatorProjectionError("invalid source_role")
        if event["actor"] not in {"tim", "creator_agent", "rider", "external", "mixed", "unknown"}:
            raise CreatorProjectionError("invalid actor")
        if event["authorship_basis"] not in {
            "direct_unquoted_message", "manual_review", "system_generated", "external_attribution", "unknown"
        }:
            raise CreatorProjectionError("invalid authorship_basis")
        if event["content_hash"] != content_hash(event["raw_text"]):
            raise CreatorProjectionError("conversation turn content_hash mismatch")
    elif event_type == "creator.judgment_proposed":
        turns = _unique_strings(event["source_turn_refs"], "source_turn_refs")
        evidence = _unique_strings(event["evidence_refs"], "evidence_refs")
        subjects = _unique_strings(event["context_subject_refs"], "context_subject_refs")
        if subjects != sorted(subjects, key=_javascript_utf16_sort_key):
            raise CreatorProjectionError("context_subject_refs must use JavaScript UTF-16 sort order")
        _instant(event["context_as_of"], "context_as_of")
        for field in ("context_max_pending_turns", "context_max_evidence"):
            if type(event[field]) is not int or event[field] < 0:
                raise CreatorProjectionError(f"{field} must be a non-negative integer")
            _safe_json_number(event[field], field)
        if not turns and not evidence:
            raise CreatorProjectionError("judgment proposal requires source turn or evidence")
        if event["temporality"] not in {"permanent", "slow_changing", "temporary"}:
            raise CreatorProjectionError("invalid judgment temporality")
        if event["temporality"] != "permanent" and "review_at" not in event:
            raise CreatorProjectionError("non-permanent judgment requires review_at")
        if "review_at" in event:
            review_at = _instant(event["review_at"], "review_at")
            if review_at <= occurred_at:
                raise CreatorProjectionError("review_at must follow proposal")
        if not isinstance(event["typed_value"], (str, int, float, bool)) or event["typed_value"] is None:
            raise CreatorProjectionError("typed_value must be a Creator scalar")
        if isinstance(event["typed_value"], str):
            _unicode_scalar_string(event["typed_value"], "typed_value")
        if type(event["typed_value"]) in {int, float}:
            _safe_json_number(event["typed_value"], "typed_value")
    elif event_type == "creator.rights_checked" and event["decision"] not in {"allowed", "forbidden", "needs_review"}:
        raise CreatorProjectionError("invalid rights decision")
    elif event_type == "creator.judgment_responded" and event["response"] not in {"tim_confirmed", "rejected"}:
        raise CreatorProjectionError("invalid judgment response")
    elif event_type == "creator.judgment_contradiction_resolved" and event["resolution"] not in {
        "dismissed", "superseded", "needs_more_evidence"
    }:
        raise CreatorProjectionError("invalid contradiction resolution")
    if event_type == "creator.source_ingested":
        if event["source_kind"] not in {"conversation", "rider_report", "provider", "manual_research", "repository"}:
            raise CreatorProjectionError("invalid source_kind")
        if event["source_kind"] == "repository" and not re.fullmatch(r"git-blob:[0-9a-f]{40}", event["immutable_ref"]):
            raise CreatorProjectionError("repository immutable_ref must be a Git blob id")
    if "observed_at" in event:
        _instant(event["observed_at"], "observed_at")
    return event_type, occurred_at


class CreatorPersistenceService:
    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def append(self, event: dict[str, Any], principal: CreatorPrincipal) -> CreatorAppendReceipt:
        event_type, occurred_at = _validate_event(event)
        capability = CAPABILITY_BY_EVENT_TYPE[event_type]
        principal.require("context.read_private")
        principal.require(capability)
        payload_hash = content_hash(event)

        try:
            with self._session_factory() as db:
                existing = self._find_event(db, event["workspace_id"], event["event_id"])
                if existing is not None:
                    return self._idempotent_receipt(existing, payload_hash)
                if event_type == "creator.workspace_started":
                    revision = self._bootstrap(db, event)
                else:
                    revision = self._cas_revision(db, event, occurred_at)
                stored = CreatorWorkspaceEvent(
                    workspace_id=event["workspace_id"],
                    revision=revision,
                    event_id=event["event_id"],
                    event_type=event_type,
                    schema_version=1,
                    base_revision=event["base_revision"],
                    occurred_at=occurred_at,
                    principal_id=principal.principal_id,
                    principal_product="creator",
                    principal_environment=principal.environment,
                    authorized_capability=capability,
                    payload_json=event,
                    payload_sha256=payload_hash,
                )
                db.add(stored)
                db.flush()
                self._project(db, event, revision, occurred_at, principal)
                db.commit()
                return CreatorAppendReceipt(event["event_id"], revision, payload_hash)
        except CreatorAppendConflictError:
            raise
        except (CreatorStaleRevisionError, IntegrityError) as exc:
            reconciled = self._reconcile(event, payload_hash)
            if reconciled is not None:
                return reconciled
            if isinstance(exc, CreatorStaleRevisionError):
                raise
            if event_type == "creator.workspace_started" and self._workspace_exists(event["workspace_id"]):
                raise CreatorStaleRevisionError("creator workspace already exists") from exc
            raise CreatorProjectionError(f"Creator append violated a database invariant: {exc.orig}") from exc

    def read_records(self, workspace_id: str, principal: CreatorPrincipal) -> list[dict[str, Any]]:
        principal.require("context.read_private")
        with self._session_factory() as db:
            rows = db.scalars(
                select(CreatorWorkspaceEvent)
                .where(CreatorWorkspaceEvent.workspace_id == workspace_id)
                .order_by(CreatorWorkspaceEvent.revision)
            ).all()
            return [
                {
                    "event": row.payload_json,
                    "committed_by": {
                        "principal_id": row.principal_id,
                        "product": row.principal_product,
                        "environment": row.principal_environment,
                        "capability": row.authorized_capability,
                    },
                }
                for row in rows
            ]

    def read_projection_digest(self, workspace_id: str, principal: CreatorPrincipal) -> dict[str, Any]:
        """Read the rebuildable projection at one observed workspace revision.

        The first/last revision fence prevents a READ COMMITTED caller from
        combining projections from two committed appends. A drift checker can
        compare this digest with a cold TypeScript replay without exposing raw
        source text to a wider API.
        """

        principal.require("context.read_private")
        with self._session_factory() as db:
            first_revision = db.scalar(select(CreatorWorkspace.current_revision).where(
                CreatorWorkspace.id == workspace_id
            ))
            if first_revision is None:
                return {
                    "revision": 0,
                    "source_rights": [],
                    "current_judgment_refs": [],
                    "pending_judgment_refs": [],
                    "decision_refs": [],
                    "unresolved_contradiction_refs": [],
                }
            source_rows = db.execute(select(
                CreatorSource.source_ref,
                CreatorSource.source_event_revision,
                CreatorSource.rights_decision,
                CreatorSource.rights_event_revision,
            ).where(CreatorSource.workspace_id == workspace_id).order_by(CreatorSource.source_ref)).all()
            current = db.scalars(select(CreatorJudgment.proposal_id).where(
                CreatorJudgment.workspace_id == workspace_id,
                CreatorJudgment.status == "tim_confirmed",
                CreatorJudgment.superseded_at.is_(None),
            ).order_by(CreatorJudgment.proposal_id)).all()
            pending = db.scalars(select(CreatorJudgment.proposal_id).where(
                CreatorJudgment.workspace_id == workspace_id,
                CreatorJudgment.status == "proposed",
                CreatorJudgment.superseded_at.is_(None),
            ).order_by(CreatorJudgment.proposal_id)).all()
            decisions = db.scalars(select(CreatorJudgmentDecision.decision_id).where(
                CreatorJudgmentDecision.workspace_id == workspace_id
            ).order_by(CreatorJudgmentDecision.decision_id)).all()
            contradictions = db.scalars(select(CreatorJudgmentContradiction.contradiction_id).where(
                CreatorJudgmentContradiction.workspace_id == workspace_id,
                CreatorJudgmentContradiction.resolved_at.is_(None),
            ).order_by(CreatorJudgmentContradiction.contradiction_id)).all()
            last_revision = db.scalar(select(CreatorWorkspace.current_revision).where(
                CreatorWorkspace.id == workspace_id
            ))
            if last_revision != first_revision:
                raise CreatorProjectionError("workspace revision changed while reading Creator projections")
            return {
                "revision": first_revision,
                "source_rights": [
                    {
                        "source_ref": row.source_ref,
                        "source_event_revision": row.source_event_revision,
                        "rights_decision": row.rights_decision,
                        "rights_event_revision": row.rights_event_revision,
                    }
                    for row in source_rows
                ],
                "current_judgment_refs": list(current),
                "pending_judgment_refs": list(pending),
                "decision_refs": list(decisions),
                "unresolved_contradiction_refs": list(contradictions),
            }

    def _reconcile(self, event: dict[str, Any], payload_hash: str) -> CreatorAppendReceipt | None:
        with self._session_factory() as db:
            existing = self._find_event(db, event["workspace_id"], event["event_id"])
            if existing is None:
                return None
            return self._idempotent_receipt(existing, payload_hash)

    def _workspace_exists(self, workspace_id: str) -> bool:
        with self._session_factory() as db:
            return db.scalar(select(CreatorWorkspace.id).where(CreatorWorkspace.id == workspace_id)) is not None

    @staticmethod
    def _find_event(db: Session, workspace_id: str, event_id: str) -> CreatorWorkspaceEvent | None:
        return db.scalar(
            select(CreatorWorkspaceEvent).where(
                CreatorWorkspaceEvent.workspace_id == workspace_id,
                CreatorWorkspaceEvent.event_id == event_id,
            )
        )

    @staticmethod
    def _idempotent_receipt(existing: CreatorWorkspaceEvent, payload_hash: str) -> CreatorAppendReceipt:
        if existing.payload_sha256 != payload_hash:
            raise CreatorAppendConflictError(f"event_id content conflict: {existing.event_id}")
        return CreatorAppendReceipt(existing.event_id, existing.revision, existing.payload_sha256)

    @staticmethod
    def _bootstrap(db: Session, event: dict[str, Any]) -> int:
        if event["base_revision"] != 0:
            raise CreatorStaleRevisionError("workspace_started requires base_revision 0")
        db.add(CreatorWorkspace(
            id=event["workspace_id"],
            mission=_required_string(event["mission"], "mission"),
            status="active",
            current_revision=1,
        ))
        db.flush()
        return 1

    @staticmethod
    def _cas_revision(db: Session, event: dict[str, Any], occurred_at: datetime) -> int:
        previous = db.scalar(
            select(CreatorWorkspaceEvent).where(
                CreatorWorkspaceEvent.workspace_id == event["workspace_id"],
                CreatorWorkspaceEvent.revision == event["base_revision"],
            )
        )
        if previous is None:
            raise CreatorStaleRevisionError("workspace does not exist or base_revision is stale")
        if occurred_at < previous.occurred_at:
            raise CreatorProjectionError("occurred_at must be monotonic within a workspace")
        revision = db.execute(
            update(CreatorWorkspace)
            .where(
                CreatorWorkspace.id == event["workspace_id"],
                CreatorWorkspace.current_revision == event["base_revision"],
            )
            .values(current_revision=CreatorWorkspace.current_revision + 1, updated_at=func.now())
            .returning(CreatorWorkspace.current_revision)
        ).scalar_one_or_none()
        if revision is None:
            raise CreatorStaleRevisionError(
                f"stale base_revision: {event['base_revision']}"
            )
        return revision

    def _project(
        self,
        db: Session,
        event: dict[str, Any],
        revision: int,
        occurred_at: datetime,
        principal: CreatorPrincipal,
    ) -> None:
        event_type = event["type"]
        if event_type == "creator.workspace_started":
            return
        if event_type == "creator.source_ingested":
            self._project_source(db, event, revision)
        elif event_type == "creator.rights_checked":
            self._project_rights(db, event, revision)
        elif event_type == "creator.conversation_turn_recorded":
            self._project_turn(db, event, revision)
        elif event_type == "creator.evidence_recorded":
            self._project_evidence(db, event, revision)
        elif event_type == "creator.judgment_proposed":
            self._project_judgment(db, event, revision)
        elif event_type == "creator.judgment_responded":
            self._project_decision(db, event, revision, occurred_at, principal)
        elif event_type == "creator.judgment_contradiction_recorded":
            self._project_contradiction(db, event, revision)
        elif event_type == "creator.judgment_contradiction_resolved":
            self._project_resolution(db, event, revision, occurred_at)

    @staticmethod
    def _project_source(db: Session, event: dict[str, Any], revision: int) -> None:
        db.add(CreatorSource(
            workspace_id=event["workspace_id"], source_ref=_required_string(event["source_ref"], "source_ref"),
            source_kind=_required_string(event["source_kind"], "source_kind"),
            content_hash=_content_hash(event["content_hash"], "content_hash"),
            immutable_ref=_required_string(event["immutable_ref"], "immutable_ref"),
            provenance_ref=_required_string(event["provenance_ref"], "provenance_ref"),
            source_event_revision=revision,
        ))

    @staticmethod
    def _project_rights(db: Session, event: dict[str, Any], revision: int) -> None:
        source = db.get(CreatorSource, (event["workspace_id"], event["source_ref"]))
        if source is None:
            raise CreatorProjectionError("rights check requires an ingested source")
        db.add(CreatorRightsCheck(
            workspace_id=event["workspace_id"], rights_check_id=event["rights_check_id"],
            source_ref=event["source_ref"], decision=event["decision"],
            policy_ref=event["policy_ref"], reason=event["reason"], event_revision=revision,
        ))
        source.rights_check_id = _required_string(event["rights_check_id"], "rights_check_id")
        source.rights_decision = event["decision"]
        source.rights_policy_ref = _required_string(event["policy_ref"], "policy_ref")
        source.rights_reason = _required_string(event["reason"], "reason")
        source.rights_event_revision = revision

    @staticmethod
    def _require_allowed_source(db: Session, workspace_id: str, source_ref: str) -> CreatorSource:
        source = db.get(CreatorSource, (workspace_id, source_ref))
        if source is None:
            raise CreatorProjectionError("event requires an ingested source")
        if source.rights_decision != "allowed":
            raise CreatorProjectionError("event requires an allowed source rights check")
        return source

    def _project_turn(self, db: Session, event: dict[str, Any], revision: int) -> None:
        self._require_allowed_source(db, event["workspace_id"], event["source_ref"])
        interaction = event.get("interaction")
        if interaction is not None:
            proposal = db.get(CreatorJudgment, (event["workspace_id"], interaction["proposal_id"]))
            if (
                proposal is None or proposal.status != "proposed" or proposal.superseded_at is not None
                or proposal.statement_hash != interaction["statement_hash"]
                or proposal.subject_ref not in event["subject_refs"]
            ):
                raise CreatorProjectionError("interaction requires the exact active proposal and subject")
        message = CreatorSourceMessage(
            workspace_id=event["workspace_id"], turn_id=_required_string(event["turn_id"], "turn_id"),
            source_ref=event["source_ref"], source_message_ref=_required_string(event["source_message_ref"], "source_message_ref"),
            source_role=_required_string(event["source_role"], "source_role"), actor=_required_string(event["actor"], "actor"),
            authorship_basis=_required_string(event["authorship_basis"], "authorship_basis"),
            raw_text=_required_string(event["raw_text"], "raw_text"), content_hash=_content_hash(event["content_hash"], "content_hash"),
            subject_refs=event["subject_refs"],
            interaction_proposal_id=interaction["proposal_id"] if interaction else None,
            interaction_statement_hash=interaction["statement_hash"] if interaction else None,
            interaction_response=interaction["response"] if interaction else None,
            event_revision=revision,
        )
        db.add(message)
        db.flush()
        db.add_all([
            CreatorSourceMessageSubject(workspace_id=event["workspace_id"], turn_id=event["turn_id"], subject_ref=subject)
            for subject in event["subject_refs"]
        ])

    def _project_evidence(self, db: Session, event: dict[str, Any], revision: int) -> None:
        self._require_allowed_source(db, event["workspace_id"], event["source_ref"])
        db.add(CreatorEvidenceItem(
            workspace_id=event["workspace_id"], evidence_id=_required_string(event["evidence_id"], "evidence_id"),
            source_ref=event["source_ref"], subject_ref=_required_string(event["subject_ref"], "subject_ref"),
            raw_observation=_required_string(event["raw_observation"], "raw_observation"),
            observed_at=_instant(event["observed_at"], "observed_at"), event_revision=revision,
        ))

    @staticmethod
    def _exact_subject_turn(db: Session, workspace_id: str, turn_id: str, subject_ref: str) -> None:
        if db.get(CreatorSourceMessageSubject, (workspace_id, turn_id, subject_ref)) is None:
            raise CreatorProjectionError("judgment turn ref is unknown or belongs to another subject")

    @staticmethod
    def _exact_subject_evidence(db: Session, workspace_id: str, evidence_id: str, subject_ref: str) -> None:
        evidence = db.get(CreatorEvidenceItem, (workspace_id, evidence_id))
        if evidence is None or evidence.subject_ref != subject_ref:
            raise CreatorProjectionError("judgment evidence ref is unknown or belongs to another subject")

    def _project_judgment(self, db: Session, event: dict[str, Any], revision: int) -> None:
        if event["statement_hash"] != content_hash(event["statement"]):
            raise CreatorProjectionError("judgment statement_hash mismatch")
        request = {
            "task": event["context_task"], "subject_refs": event["context_subject_refs"],
            "as_of": event["context_as_of"], "max_pending_turns": event["context_max_pending_turns"],
            "max_evidence": event["context_max_evidence"],
        }
        if event["context_request_hash"] != content_hash(request):
            raise CreatorProjectionError("judgment context_request_hash mismatch")
        for turn_id in event["source_turn_refs"]:
            self._exact_subject_turn(db, event["workspace_id"], turn_id, event["subject_ref"])
        for evidence_id in event["evidence_refs"]:
            self._exact_subject_evidence(db, event["workspace_id"], evidence_id, event["subject_ref"])
        supersedes = None
        if event.get("supersedes_judgment_id"):
            supersedes = db.get(CreatorJudgment, (event["workspace_id"], event["supersedes_judgment_id"]))
            if (
                supersedes is None or supersedes.status != "tim_confirmed" or supersedes.superseded_at is not None
                or supersedes.judgment_key != event["judgment_key"] or supersedes.subject_ref != event["subject_ref"]
            ):
                raise CreatorProjectionError("supersedes must reference the active same-key same-subject judgment")
        else:
            current = db.scalar(select(CreatorJudgment).where(
                CreatorJudgment.workspace_id == event["workspace_id"],
                CreatorJudgment.judgment_key == event["judgment_key"],
                CreatorJudgment.status == "tim_confirmed",
                CreatorJudgment.superseded_at.is_(None),
            ))
            if current is not None:
                raise CreatorProjectionError("active judgment requires an explicit supersedes_judgment_id")
        judgment = CreatorJudgment(
            workspace_id=event["workspace_id"], proposal_id=event["proposal_id"], judgment_key=event["judgment_key"],
            subject_ref=event["subject_ref"], statement=event["statement"], statement_hash=event["statement_hash"],
            typed_value=event["typed_value"], temporality=event["temporality"],
            review_at=_instant(event["review_at"], "review_at") if event.get("review_at") else None,
            status="proposed", supersedes_proposal_id=event.get("supersedes_judgment_id"),
            context_compiler_version=event["context_compiler_version"], context_request_json=request,
            context_request_hash=event["context_request_hash"], context_hash=event["context_hash"],
            model_ref=event["model_ref"], proposal_reason=event["reason"], proposal_event_revision=revision,
        )
        db.add(judgment)
        db.flush()
        db.add_all([
            CreatorJudgmentTurn(workspace_id=event["workspace_id"], proposal_id=event["proposal_id"], turn_id=turn_id)
            for turn_id in event["source_turn_refs"]
        ] + [
            CreatorJudgmentEvidence(workspace_id=event["workspace_id"], proposal_id=event["proposal_id"], evidence_id=evidence_id)
            for evidence_id in event["evidence_refs"]
        ])

    def _project_decision(
        self, db: Session, event: dict[str, Any], revision: int, occurred_at: datetime, principal: CreatorPrincipal
    ) -> None:
        judgment = db.get(CreatorJudgment, (event["workspace_id"], event["proposal_id"]))
        turn = db.get(CreatorSourceMessage, (event["workspace_id"], event["response_turn_ref"]))
        if judgment is None or judgment.status != "proposed" or judgment.superseded_at is not None:
            raise CreatorProjectionError("decision requires an unanswered active proposal")
        if (
            event["expected_statement_hash"] != judgment.statement_hash or turn is None
            or turn.actor != "tim" or turn.source_role != "user"
            or turn.interaction_proposal_id != judgment.proposal_id
            or turn.interaction_statement_hash != judgment.statement_hash
            or turn.interaction_response != event["response"]
        ):
            raise CreatorProjectionError("decision is not bound to the exact proposal and Tim turn")
        if event["response"] == "tim_confirmed" and judgment.supersedes_proposal_id:
            previous = db.get(CreatorJudgment, (event["workspace_id"], judgment.supersedes_proposal_id))
            if previous is None or previous.status != "tim_confirmed" or previous.superseded_at is not None:
                raise CreatorProjectionError("replacement no longer points to the active confirmed judgment")
            previous.superseded_at = occurred_at
            db.flush()
        judgment.status = event["response"]
        judgment.responded_at = occurred_at
        judgment.decision_id = event["decision_id"]
        if db.get(CreatorJudgmentTurn, (event["workspace_id"], judgment.proposal_id, turn.turn_id)) is None:
            db.add(CreatorJudgmentTurn(
                workspace_id=event["workspace_id"], proposal_id=judgment.proposal_id, turn_id=turn.turn_id
            ))
        db.add(CreatorJudgmentDecision(
            workspace_id=event["workspace_id"], decision_id=event["decision_id"], proposal_id=judgment.proposal_id,
            response_turn_id=turn.turn_id, response=event["response"],
            expected_statement_hash=event["expected_statement_hash"], event_revision=revision,
            reviewer_principal_id=principal.principal_id,
        ))

    def _resolve_contradicting_ref(
        self, db: Session, workspace_id: str, reference: str, subject_ref: str
    ) -> tuple[str | None, str | None, str | None]:
        evidence = db.get(CreatorEvidenceItem, (workspace_id, reference))
        turn_subject = db.get(CreatorSourceMessageSubject, (workspace_id, reference, subject_ref))
        judgment = db.get(CreatorJudgment, (workspace_id, reference))
        matches = [
            evidence is not None and evidence.subject_ref == subject_ref,
            turn_subject is not None,
            judgment is not None and judgment.subject_ref == subject_ref,
        ]
        if sum(matches) != 1:
            raise CreatorProjectionError("contradiction requires exactly one same-subject evidence, turn or judgment ref")
        return (reference if matches[0] else None, reference if matches[1] else None, reference if matches[2] else None)

    def _project_contradiction(self, db: Session, event: dict[str, Any], revision: int) -> None:
        judgment = db.get(CreatorJudgment, (event["workspace_id"], event["judgment_id"]))
        if judgment is None or judgment.status != "tim_confirmed" or judgment.superseded_at is not None:
            raise CreatorProjectionError("contradiction requires an active Tim-confirmed judgment")
        evidence_id, turn_id, judgment_id = self._resolve_contradicting_ref(
            db, event["workspace_id"], event["contradicting_ref"], judgment.subject_ref
        )
        db.add(CreatorJudgmentContradiction(
            workspace_id=event["workspace_id"], contradiction_id=event["contradiction_id"],
            judgment_id=event["judgment_id"], subject_ref=judgment.subject_ref,
            contradicting_evidence_id=evidence_id, contradicting_turn_id=turn_id,
            contradicting_judgment_id=judgment_id, reason=event["reason"], recorded_event_revision=revision,
        ))

    def _project_resolution(
        self, db: Session, event: dict[str, Any], revision: int, occurred_at: datetime
    ) -> None:
        contradiction = db.get(CreatorJudgmentContradiction, (event["workspace_id"], event["contradiction_id"]))
        if contradiction is None or contradiction.resolved_at is not None:
            raise CreatorProjectionError("resolution requires an unresolved contradiction")
        if event["resolution"] == "superseded":
            replacement = db.get(CreatorJudgment, (event["workspace_id"], event["resolution_ref"]))
            if (
                replacement is None or replacement.status != "tim_confirmed"
                or replacement.supersedes_proposal_id != contradiction.judgment_id
            ):
                raise CreatorProjectionError("superseded resolution requires the confirmed replacement")
            original = db.get(CreatorJudgment, (event["workspace_id"], contradiction.judgment_id))
            if original is None or original.superseded_at is None:
                raise CreatorProjectionError("original judgment has not been superseded")
        else:
            self._resolve_contradicting_ref(
                db, event["workspace_id"], event["resolution_ref"], contradiction.subject_ref
            )
        contradiction.resolution = event["resolution"]
        contradiction.resolution_ref = event["resolution_ref"]
        contradiction.resolved_event_revision = revision
        if event["resolution"] != "needs_more_evidence":
            contradiction.resolved_at = occurred_at
        db.add(CreatorJudgmentContradictionResolution(
            workspace_id=event["workspace_id"], resolution_id=event["resolution_id"],
            contradiction_id=event["contradiction_id"], resolution=event["resolution"],
            resolution_ref=event["resolution_ref"], reason=event["reason"], event_revision=revision,
        ))
