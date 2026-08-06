"""Single-transaction Creator event append and projection service.

The TypeScript runtime owns its reducer and model loop. This Python boundary
owns authentication receipts, PostgreSQL revision CAS and relational
constraints. It deliberately supports only the information/judgment slice;
Published World, Rider and other Creator event families remain closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import math
import re
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .canonical import canonical_json, content_hash
from .models import (
    CreatorEvidenceItem,
    CreatorBehaviorCalibration,
    CreatorJudgment,
    CreatorJudgmentContradiction,
    CreatorJudgmentContradictionResolution,
    CreatorJudgmentDecision,
    CreatorJudgmentEvidence,
    CreatorJudgmentInterpretation,
    CreatorJudgmentTurn,
    CreatorRightsCheck,
    CreatorSource,
    CreatorSourceMessage,
    CreatorSourceMessageSubject,
    CreatorTaskStateRecord,
    CreatorTurnInterpretation,
    CreatorWorkspace,
    CreatorWorkspaceEvent,
)


CAPABILITY_BY_EVENT_TYPE = {
    "creator.workspace_started": "workspace.create",
    "creator.source_ingested": "source.ingest",
    "creator.conversation_turn_recorded": "conversation.record",
    "creator.rights_checked": "rights.check",
    "creator.evidence_recorded": "evidence.inspect_raw",
    "creator.turn_interpretation_proposed": "interpretation.propose",
    "creator.task_state_changed": "task.update",
    "creator.behavior_calibration_recorded": "behavior.calibrate",
    "creator.judgment_proposed": "judgment.propose",
    "creator.judgment_promotion_proposed": "judgment.promote",
    "creator.judgment_responded": "judgment.decide",
    "creator.judgment_contradiction_recorded": "judgment.contradict",
    "creator.judgment_contradiction_resolved": "judgment.contradict",
}


def capability_for_event(event: dict[str, Any]) -> str:
    if event.get("type") == "creator.behavior_calibration_recorded":
        authority = event.get("authority")
        if authority not in {"agent_assessed", "mechanical", "tim_confirmed", "real_world"}:
            raise CreatorProjectionError("invalid Creator calibration authority capability")
        return f"behavior.calibrate.{authority}"
    return CAPABILITY_BY_EVENT_TYPE[event["type"]]

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
    "creator.turn_interpretation_proposed": BASE_FIELDS | {
        "interpretation_id", "turn_id", "task_ref", "subject_refs", "speech_acts", "epistemic_status",
        "scope_level", "scope_ref", "persistence_intent", "annotation_basis", "claim", "confidence",
        "alternatives", "supporting_refs", "counterevidence_refs", "relations", "action_effect", "review_when",
        "context_compiler_version", "context_request_hash", "context_task", "context_subject_refs",
        "context_as_of", "context_max_pending_turns", "context_max_evidence", "context_max_interpretations",
        "context_hash", "model_ref",
        "supersedes_interpretation_id",
    },
    "creator.task_state_changed": BASE_FIELDS | {
        "task_state_id", "task_ref", "project_ref", "status", "objective", "focus", "acceptance_criteria",
        "open_loops", "source_turn_refs", "supersedes_task_state_id", "source_interpretation_ref", "engine_ref",
    },
    "creator.behavior_calibration_recorded": BASE_FIELDS | {
        "calibration_id", "task_ref", "metric", "verdict", "authority", "prediction", "observed_result",
        "context_hash", "context_item_refs",
    },
    "creator.judgment_proposed": BASE_FIELDS | {
        "proposal_id", "judgment_key", "subject_ref", "statement", "statement_hash", "typed_value",
        "temporality", "context_compiler_version", "context_request_hash", "context_task",
        "context_subject_refs", "context_as_of", "context_max_pending_turns", "context_max_evidence",
        "context_hash", "model_ref", "review_at", "source_turn_refs", "evidence_refs",
        "supersedes_judgment_id", "reason",
    },
    "creator.judgment_promotion_proposed": BASE_FIELDS | {
        "proposal_id", "judgment_key", "subject_ref", "statement", "statement_hash", "typed_value",
        "temporality", "context_compiler_version", "context_request_hash", "context_task", "context_task_ref",
        "context_subject_refs", "context_as_of", "context_max_pending_turns", "context_max_evidence",
        "context_max_interpretations", "context_hash", "model_ref", "review_at", "source_turn_refs",
        "evidence_refs", "source_interpretation_refs", "promotion_basis", "promotion_basis_refs",
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
CREATOR_CONTEXT_COMPILER_VERSION = "creator-context-v1"
CREATOR_PROMOTION_ENGINE_VERSION = "creator-promotion-engine-v0"
CREATOR_TASK_STATE_ENGINE_VERSION = "creator-task-state-engine-v0"
CREATOR_DERIVATION_EVENT_TYPES = {
    "creator.turn_interpretation_proposed",
    "creator.task_state_changed",
    "creator.behavior_calibration_recorded",
    "creator.judgment_promotion_proposed",
}
DERIVATION_ATTESTATION_FIELDS = {
    "schema_version", "algorithm", "key_id", "workspace_id", "event_id", "base_revision",
    "event_payload_hash", "prior_records_hash", "principal_id", "principal_environment",
    "authorized_capability", "signature",
}


class CreatorPersistenceError(RuntimeError):
    """Base error with a stable API-facing code."""

    code = "creator_persistence_error"


class CreatorAppendConflictError(CreatorPersistenceError):
    code = "event_id_conflict"


class CreatorStaleRevisionError(CreatorPersistenceError):
    code = "stale_revision"


class CreatorProjectionError(CreatorPersistenceError):
    code = "projection_conflict"


class CreatorProjectionRevisionMismatchError(CreatorPersistenceError):
    code = "projection_revision_mismatch"


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


@dataclass(frozen=True)
class CreatorEd25519VerificationKey:
    public_key_pem: str | bytes
    allowed_principal_ids: tuple[str, ...]
    allowed_environments: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]


def _requires_derivation_attestation(event: dict[str, Any]) -> bool:
    return event["type"] in CREATOR_DERIVATION_EVENT_TYPES or (
        event["type"] == "creator.judgment_proposed" and event["schema_version"] == 2
    )


class CreatorEd25519DerivationVerifier:
    """Verify a TypeScript reducer proof without possessing any signing key."""

    def __init__(self, keys_by_key_id: dict[str, CreatorEd25519VerificationKey]):
        if not keys_by_key_id:
            raise ValueError("Creator derivation verifier requires at least one Ed25519 public key")
        parsed: dict[str, tuple[Ed25519PublicKey, CreatorEd25519VerificationKey]] = {}
        try:
            for key_id, descriptor in keys_by_key_id.items():
                if (
                    not isinstance(key_id, str) or not key_id.strip()
                    or not isinstance(descriptor, CreatorEd25519VerificationKey)
                    or not isinstance(descriptor.public_key_pem, (str, bytes))
                    or not descriptor.allowed_principal_ids or not descriptor.allowed_environments
                    or not descriptor.allowed_capabilities
                    or any(not isinstance(value, str) or not value.strip() for value in (
                        *descriptor.allowed_principal_ids,
                        *descriptor.allowed_environments,
                        *descriptor.allowed_capabilities,
                    ))
                ):
                    raise ValueError("Creator derivation verification keys require explicit principal, environment and capability scopes")
                encoded = descriptor.public_key_pem.encode("utf-8") \
                    if isinstance(descriptor.public_key_pem, str) else descriptor.public_key_pem
                key = load_pem_public_key(encoded)
                if not isinstance(key, Ed25519PublicKey):
                    raise ValueError("Creator derivation verifier accepts only Ed25519 public keys")
                parsed[key_id] = (key, descriptor)
        except (TypeError, ValueError) as exc:
            raise ValueError("Creator derivation verifier requires valid Ed25519 public keys") from exc
        self._keys_by_key_id = parsed

    def verify(
        self,
        attestation: Any,
        event: dict[str, Any],
        principal: CreatorPrincipal,
        prior_records: list[dict[str, Any]],
    ) -> None:
        if not isinstance(attestation, dict) or set(attestation) != DERIVATION_ATTESTATION_FIELDS:
            raise CreatorProjectionError("Creator derived append requires an exact reducer attestation")
        if attestation["schema_version"] != 1 or attestation["algorithm"] != "ed25519":
            raise CreatorProjectionError("unsupported Creator derivation attestation")
        key_id = _required_string(attestation["key_id"], "derivation key_id")
        key_entry = self._keys_by_key_id.get(key_id)
        if key_entry is None:
            raise CreatorProjectionError("unknown Creator derivation attestation key")
        public_key, key_policy = key_entry
        expected_core = {
            "schema_version": 1,
            "algorithm": "ed25519",
            "key_id": key_id,
            "workspace_id": event["workspace_id"],
            "event_id": event["event_id"],
            "base_revision": event["base_revision"],
            "event_payload_hash": content_hash(event),
            "prior_records_hash": content_hash(prior_records),
            "principal_id": principal.principal_id,
            "principal_environment": principal.environment,
            "authorized_capability": capability_for_event(event),
        }
        supplied_core = {key: attestation[key] for key in expected_core}
        if supplied_core != expected_core:
            raise CreatorProjectionError("Creator derivation attestation is not bound to the exact event prefix and principal")
        if (
            principal.principal_id not in key_policy.allowed_principal_ids
            or principal.environment not in key_policy.allowed_environments
            or expected_core["authorized_capability"] not in key_policy.allowed_capabilities
        ):
            raise CreatorProjectionError("Creator derivation verification key is outside its principal, environment or capability scope")
        signature = attestation["signature"]
        if not isinstance(signature, str) or not re.fullmatch(r"ed25519:[A-Za-z0-9_-]{86}", signature):
            raise CreatorProjectionError("invalid Creator derivation attestation signature")
        try:
            public_key.verify(
                base64.urlsafe_b64decode(signature.removeprefix("ed25519:") + "=="),
                canonical_json(expected_core).encode("utf-8"),
            )
        except (InvalidSignature, ValueError) as exc:
            raise CreatorProjectionError("invalid Creator derivation attestation signature") from exc


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


def _canonical_db_instant(value: Any, label: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CreatorProjectionError(f"{label} must be a timezone-aware database instant")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_event(event: dict[str, Any]) -> tuple[str, datetime]:
    if not isinstance(event, dict):
        raise CreatorProjectionError("Creator event must be an object")
    event_type = _required_string(event.get("type"), "type")
    allowed = EVENT_FIELDS.get(event_type)
    if allowed is None:
        raise CreatorProjectionError(f"event type is outside Creator persistence v0: {event_type}")
    extras = set(event) - allowed
    required = allowed - {
        "interaction", "review_at", "supersedes_judgment_id",
        "supersedes_interpretation_id", "supersedes_task_state_id",
        "source_interpretation_ref", "engine_ref",
    }
    missing = required - set(event)
    if extras or missing:
        raise CreatorProjectionError(
            f"invalid {event_type} fields; missing={sorted(missing)}, extra={sorted(extras)}"
        )
    if type(event.get("schema_version")) is not int or not (
        event["schema_version"] == 1
        or (event["schema_version"] == 2 and event_type == "creator.judgment_proposed")
    ):
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
        "interpretation_id", "task_ref", "scope_ref", "claim", "review_when", "task_state_id",
        "project_ref", "objective", "focus", "calibration_id", "prediction", "observed_result",
        "context_task_ref", "context_task",
    ):
        if field in event:
            _required_string(event[field], field)
    for key in ("content_hash", "statement_hash", "context_request_hash", "context_hash", "expected_statement_hash"):
        if key in event:
            _content_hash(event[key], key)
    if event_type == "creator.conversation_turn_recorded":
        subjects = _unique_strings(event["subject_refs"], "subject_refs")
        if not subjects:
            raise CreatorProjectionError("conversation turn requires at least one privacy subject")
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
    elif event_type == "creator.turn_interpretation_proposed":
        subjects = _unique_strings(event["subject_refs"], "subject_refs")
        if subjects != sorted(subjects, key=_javascript_utf16_sort_key) or not subjects:
            raise CreatorProjectionError("interpretation subject_refs must be non-empty and sorted")
        speech_acts = _unique_strings(event["speech_acts"], "speech_acts")
        if not speech_acts or any(item not in {
            "observation", "correction", "preference", "instruction", "decision", "question",
            "hypothesis", "emotion", "external_quote",
        } for item in speech_acts):
            raise CreatorProjectionError("invalid interpretation speech_acts")
        if event["epistemic_status"] not in {"explicit", "inferred", "ambiguous", "hypothetical", "unknown"}:
            raise CreatorProjectionError("invalid interpretation epistemic_status")
        if event["scope_level"] not in {"turn", "task", "project", "cross_project", "global"}:
            raise CreatorProjectionError("invalid interpretation scope_level")
        if event["persistence_intent"] not in {"ephemeral", "task_local", "provisional", "durable_explicit", "unknown"}:
            raise CreatorProjectionError("invalid interpretation persistence_intent")
        if event["annotation_basis"] not in {"direct_language", "agent_inference", "mechanical"}:
            raise CreatorProjectionError("invalid interpretation annotation_basis")
        if event["action_effect"] not in {
            "none", "inform_context", "change_current_task", "candidate_for_promotion", "request_clarification",
        }:
            raise CreatorProjectionError("invalid interpretation action_effect")
        if event["scope_level"] == "turn" and event["scope_ref"] != event["turn_id"]:
            raise CreatorProjectionError("turn interpretation scope_ref must equal turn_id")
        if event["scope_level"] == "task" and event["scope_ref"] != event["task_ref"]:
            raise CreatorProjectionError("task interpretation scope_ref must equal task_ref")
        confidence = _safe_json_number(event["confidence"], "confidence")
        if not 0 <= confidence <= 1:
            raise CreatorProjectionError("interpretation confidence must be between 0 and 1")
        for field in ("supporting_refs", "counterevidence_refs"):
            refs = _unique_strings(event[field], field)
            if refs != sorted(refs, key=_javascript_utf16_sort_key):
                raise CreatorProjectionError(f"{field} must be sorted")
        if not isinstance(event["alternatives"], list):
            raise CreatorProjectionError("interpretation alternatives must be an array")
        for item in event["alternatives"]:
            if not isinstance(item, dict) or set(item) != {"claim", "disconfirming_evidence"}:
                raise CreatorProjectionError("invalid interpretation alternative")
            _required_string(item["claim"], "alternative.claim")
            _required_string(item["disconfirming_evidence"], "alternative.disconfirming_evidence")
        if not isinstance(event["relations"], list):
            raise CreatorProjectionError("interpretation relations must be an array")
        relation_keys: set[tuple[str, str]] = set()
        for item in event["relations"]:
            if not isinstance(item, dict) or set(item) != {"target_ref", "kind", "reason"}:
                raise CreatorProjectionError("invalid interpretation relation")
            _required_string(item["target_ref"], "relation.target_ref")
            _required_string(item["reason"], "relation.reason")
            if item["kind"] not in {"supports", "contradicts", "refines", "supersedes"}:
                raise CreatorProjectionError("invalid interpretation relation kind")
            key = (item["kind"], item["target_ref"])
            if key in relation_keys:
                raise CreatorProjectionError("interpretation relations must be unique")
            relation_keys.add(key)
        if event.get("supersedes_interpretation_id") is not None:
            _required_string(event["supersedes_interpretation_id"], "supersedes_interpretation_id")
        context_subjects = _unique_strings(event["context_subject_refs"], "context_subject_refs")
        if not context_subjects or context_subjects != sorted(context_subjects, key=_javascript_utf16_sort_key):
            raise CreatorProjectionError("interpretation context_subject_refs must be sorted")
        if any(subject not in context_subjects for subject in subjects):
            raise CreatorProjectionError("interpretation subjects must be present in its context request")
        _instant(event["context_as_of"], "context_as_of")
        for field in ("context_max_pending_turns", "context_max_evidence", "context_max_interpretations"):
            if type(event[field]) is not int or event[field] < 0:
                raise CreatorProjectionError(f"{field} must be a non-negative integer")
            _safe_json_number(event[field], field)
        request = {
            "task": event["context_task"], "task_ref": event["task_ref"],
            "subject_refs": context_subjects, "as_of": event["context_as_of"],
            "max_pending_turns": event["context_max_pending_turns"],
            "max_evidence": event["context_max_evidence"],
            "max_interpretations": event["context_max_interpretations"],
        }
        if event["context_compiler_version"] != CREATOR_CONTEXT_COMPILER_VERSION:
            raise CreatorProjectionError("interpretation requires the current context compiler version")
        if event["context_request_hash"] != content_hash(request):
            raise CreatorProjectionError("interpretation context_request_hash mismatch")
    elif event_type == "creator.task_state_changed":
        if event["status"] not in {"active", "blocked", "completed"}:
            raise CreatorProjectionError("invalid Creator task status")
        for field in ("acceptance_criteria", "open_loops", "source_turn_refs"):
            refs = _unique_strings(event[field], field)
            if field == "source_turn_refs" and refs != sorted(refs, key=_javascript_utf16_sort_key):
                raise CreatorProjectionError("task source_turn_refs must be sorted")
        if not event["source_turn_refs"]:
            raise CreatorProjectionError("task state requires a source turn")
        if event.get("supersedes_task_state_id") is not None:
            _required_string(event["supersedes_task_state_id"], "supersedes_task_state_id")
        if event.get("source_interpretation_ref") is not None:
            _required_string(event["source_interpretation_ref"], "source_interpretation_ref")
        if event.get("engine_ref") is not None and event["engine_ref"] != CREATOR_TASK_STATE_ENGINE_VERSION:
            raise CreatorProjectionError("task state engine_ref must identify the mechanical task state engine")
        bundle = tuple(event.get(field) is not None for field in (
            "supersedes_task_state_id", "source_interpretation_ref", "engine_ref"
        ))
        if len(set(bundle)) != 1:
            raise CreatorProjectionError(
                "task state update bundle must contain supersedes_task_state_id, source_interpretation_ref and engine_ref together"
            )
    elif event_type == "creator.behavior_calibration_recorded":
        if event["metric"] not in {
            "first_understanding", "repeat_correction", "overpromotion", "missed_recall",
            "conflict_challenge", "context_usefulness",
        }:
            raise CreatorProjectionError("invalid Creator calibration metric")
        if event["verdict"] not in {"pass", "fail", "needs_more_evidence"}:
            raise CreatorProjectionError("invalid Creator calibration verdict")
        if event["authority"] not in {"agent_assessed", "tim_confirmed", "mechanical", "real_world"}:
            raise CreatorProjectionError("invalid Creator calibration authority")
        refs = _unique_strings(event["context_item_refs"], "context_item_refs")
        if refs != sorted(refs, key=_javascript_utf16_sort_key):
            raise CreatorProjectionError("calibration context_item_refs must be sorted")
    elif event_type in {"creator.judgment_proposed", "creator.judgment_promotion_proposed"}:
        turns = _unique_strings(event["source_turn_refs"], "source_turn_refs")
        evidence = _unique_strings(event["evidence_refs"], "evidence_refs")
        subjects = _unique_strings(event["context_subject_refs"], "context_subject_refs")
        if turns != sorted(turns, key=_javascript_utf16_sort_key):
            raise CreatorProjectionError("source_turn_refs must use JavaScript UTF-16 sort order")
        if evidence != sorted(evidence, key=_javascript_utf16_sort_key):
            raise CreatorProjectionError("evidence_refs must use JavaScript UTF-16 sort order")
        if not subjects or subjects != sorted(subjects, key=_javascript_utf16_sort_key):
            raise CreatorProjectionError("context_subject_refs must use JavaScript UTF-16 sort order")
        _instant(event["context_as_of"], "context_as_of")
        for field in ("context_max_pending_turns", "context_max_evidence"):
            if type(event[field]) is not int or event[field] < 0:
                raise CreatorProjectionError(f"{field} must be a non-negative integer")
            _safe_json_number(event[field], field)
        if not turns and not evidence:
            raise CreatorProjectionError("judgment proposal requires source turn or evidence")
        if event_type == "creator.judgment_proposed" and event["schema_version"] == 2 and turns:
            raise CreatorProjectionError(
                "schema v2 compatibility judgment cannot consume conversation turns; use interpretation and promotion"
            )
        if event_type == "creator.judgment_proposed" and event["schema_version"] == 2 and not evidence:
            raise CreatorProjectionError("schema v2 compatibility judgment requires route/domain evidence")
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
        if event_type == "creator.judgment_promotion_proposed":
            interpretations = _unique_strings(event["source_interpretation_refs"], "source_interpretation_refs")
            basis_refs = _unique_strings(event["promotion_basis_refs"], "promotion_basis_refs")
            if not interpretations or interpretations != sorted(interpretations, key=_javascript_utf16_sort_key):
                raise CreatorProjectionError("promotion source_interpretation_refs must be non-empty and sorted")
            if basis_refs != sorted(basis_refs, key=_javascript_utf16_sort_key):
                raise CreatorProjectionError("promotion_basis_refs must be sorted")
            if event["promotion_basis"] not in {
                "durable_explicit", "repeated_independent_tasks", "validated_outcome", "high_cost_failure",
            }:
                raise CreatorProjectionError("invalid judgment promotion basis")
            if type(event["context_max_interpretations"]) is not int or event["context_max_interpretations"] <= 0:
                raise CreatorProjectionError("context_max_interpretations must be a positive integer")
            _safe_json_number(event["context_max_interpretations"], "context_max_interpretations")
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
    def __init__(
        self,
        session_factory: Callable[[], Session],
        derivation_verifier: CreatorEd25519DerivationVerifier | None = None,
    ):
        self._session_factory = session_factory
        self._derivation_verifier = derivation_verifier

    @staticmethod
    def _records_prefix_in_session(
        db: Session,
        workspace_id: str,
        expected_revision: int,
    ) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(CreatorWorkspaceEvent)
            .where(
                CreatorWorkspaceEvent.workspace_id == workspace_id,
                CreatorWorkspaceEvent.revision <= expected_revision,
            )
            .order_by(CreatorWorkspaceEvent.revision)
        ).all()
        if len(rows) != expected_revision or any(row.revision != index for index, row in enumerate(rows, 1)):
            raise CreatorProjectionError("Creator derivation attestation requires the exact contiguous prior prefix")
        return [{
            "event": row.payload_json,
            "committed_by": {
                "principal_id": row.principal_id,
                "product": row.principal_product,
                "environment": row.principal_environment,
                "capability": row.authorized_capability,
            },
        } for row in rows]

    def append(
        self,
        event: dict[str, Any],
        principal: CreatorPrincipal,
        derivation_attestation: dict[str, Any] | None = None,
    ) -> CreatorAppendReceipt:
        event_type, occurred_at = _validate_event(event)
        capability = capability_for_event(event)
        principal.require("context.read_private")
        principal.require(capability)
        if event_type == "creator.judgment_proposed" and event["schema_version"] == 1:
            raise CreatorProjectionError(
                "schema v1 creator judgment is replay-only; new writes must use schema v2 evidence or interpretation promotion"
            )
        payload_hash = content_hash(event)

        try:
            with self._session_factory() as db:
                requires_attestation = _requires_derivation_attestation(event)
                if requires_attestation:
                    if self._derivation_verifier is None:
                        raise CreatorProjectionError("Creator derived append is disabled without a reducer attestation verifier")
                    prior_records = self._records_prefix_in_session(db, event["workspace_id"], event["base_revision"])
                    self._derivation_verifier.verify(derivation_attestation, event, principal, prior_records)
                elif derivation_attestation is not None:
                    raise CreatorProjectionError("non-derived Creator event must not carry a derivation attestation")
                existing = self._find_event(db, event["workspace_id"], event["event_id"])
                if existing is not None:
                    return self._idempotent_receipt(existing, payload_hash, principal, capability)
                if event_type == "creator.workspace_started":
                    revision = self._bootstrap(db, event)
                else:
                    revision = self._cas_revision(db, event, occurred_at)
                stored = CreatorWorkspaceEvent(
                    workspace_id=event["workspace_id"],
                    revision=revision,
                    event_id=event["event_id"],
                    event_type=event_type,
                    schema_version=event["schema_version"],
                    base_revision=event["base_revision"],
                    occurred_at=occurred_at,
                    principal_id=principal.principal_id,
                    principal_product="creator",
                    principal_environment=principal.environment,
                    authorized_capability=capability,
                    payload_json=event,
                    payload_sha256=payload_hash,
                    derivation_key_id=(derivation_attestation or {}).get("key_id"),
                    derivation_signature=(derivation_attestation or {}).get("signature"),
                    derivation_prior_records_hash=(derivation_attestation or {}).get("prior_records_hash"),
                )
                db.add(stored)
                db.flush()
                self._project(db, event, revision, occurred_at, principal)
                db.commit()
                return CreatorAppendReceipt(event["event_id"], revision, payload_hash)
        except CreatorAppendConflictError:
            raise
        except (CreatorStaleRevisionError, IntegrityError) as exc:
            reconciled = self._reconcile(event, payload_hash, principal, capability)
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

    def read_projection_records(
        self,
        workspace_id: str,
        expected_revision: int,
        principal: CreatorPrincipal,
    ) -> dict[str, Any]:
        """Reconstruct the persisted v0 event stream from relational projections.

        Event metadata and authenticated principal receipts come from the
        append-only event index, but event bodies deliberately never read its
        ``payload_json`` column. The TypeScript runtime can therefore compare
        this independently materialized stream with event truth at one exact
        revision before exposing Context to a model.
        """

        principal.require("context.read_private")
        if type(expected_revision) is not int or not 0 <= expected_revision <= MAX_SAFE_JSON_INTEGER:
            raise CreatorProjectionRevisionMismatchError("expected_revision must be a non-negative safe integer")

        with self._session_factory() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            workspace = db.get(CreatorWorkspace, workspace_id)
            first_revision = workspace.current_revision if workspace is not None else None
            observed_revision = 0 if first_revision is None else first_revision
            if observed_revision != expected_revision:
                raise CreatorProjectionRevisionMismatchError(
                    f"projection revision mismatch: expected {expected_revision}, observed {observed_revision}"
                )
            if workspace is None:
                return {
                    "revision": 0,
                    "records": [],
                    "digest": self._projection_digest_in_session(db, workspace_id, 0),
                }

            metadata_rows = db.execute(select(
                CreatorWorkspaceEvent.revision,
                CreatorWorkspaceEvent.event_id,
                CreatorWorkspaceEvent.event_type,
                CreatorWorkspaceEvent.schema_version,
                CreatorWorkspaceEvent.base_revision,
                CreatorWorkspaceEvent.occurred_at,
                CreatorWorkspaceEvent.principal_id,
                CreatorWorkspaceEvent.principal_product,
                CreatorWorkspaceEvent.principal_environment,
                CreatorWorkspaceEvent.authorized_capability,
            ).where(
                CreatorWorkspaceEvent.workspace_id == workspace_id,
                CreatorWorkspaceEvent.revision <= expected_revision,
            ).order_by(CreatorWorkspaceEvent.revision)).all()
            metadata = {row.revision: row for row in metadata_rows}
            expected_revisions = list(range(1, expected_revision + 1))
            if list(metadata) != expected_revisions:
                raise CreatorProjectionError("Creator event metadata is not a contiguous projection prefix")

            projected_events: dict[int, dict[str, Any]] = {}

            def add_event(revision: int, event_type: str, payload: dict[str, Any]) -> None:
                row = metadata.get(revision)
                if row is None:
                    raise CreatorProjectionError(f"projection references unknown event revision {revision}")
                if revision in projected_events:
                    raise CreatorProjectionError(f"multiple projection bodies claim event revision {revision}")
                if row.event_type != event_type or row.base_revision != revision - 1:
                    raise CreatorProjectionError(f"projection metadata does not match {event_type} at revision {revision}")
                try:
                    capability = capability_for_event({"type": event_type, **payload})
                except (KeyError, CreatorProjectionError):
                    capability = None
                if (
                    capability is None
                    or row.authorized_capability != capability
                    or row.principal_product != "creator"
                    or row.principal_environment not in {"test", "shadow", "production"}
                ):
                    raise CreatorProjectionError(f"invalid authenticated event metadata at revision {revision}")
                event = {
                    "schema_version": row.schema_version,
                    "event_id": row.event_id,
                    "workspace_id": workspace_id,
                    "base_revision": row.base_revision,
                    "occurred_at": _canonical_db_instant(row.occurred_at, "occurred_at"),
                    "type": event_type,
                    **payload,
                }
                _validate_event(event)
                projected_events[revision] = event

            add_event(1, "creator.workspace_started", {"mission": workspace.mission})

            for row in db.scalars(select(CreatorSource).where(
                CreatorSource.workspace_id == workspace_id
            ).order_by(CreatorSource.source_event_revision)).all():
                add_event(row.source_event_revision, "creator.source_ingested", {
                    "source_ref": row.source_ref,
                    "source_kind": row.source_kind,
                    "content_hash": row.content_hash,
                    "immutable_ref": row.immutable_ref,
                    "provenance_ref": row.provenance_ref,
                })

            for row in db.scalars(select(CreatorRightsCheck).where(
                CreatorRightsCheck.workspace_id == workspace_id
            ).order_by(CreatorRightsCheck.event_revision)).all():
                add_event(row.event_revision, "creator.rights_checked", {
                    "rights_check_id": row.rights_check_id,
                    "source_ref": row.source_ref,
                    "decision": row.decision,
                    "policy_ref": row.policy_ref,
                    "reason": row.reason,
                })

            for row in db.scalars(select(CreatorSourceMessage).where(
                CreatorSourceMessage.workspace_id == workspace_id
            ).order_by(CreatorSourceMessage.event_revision)).all():
                interaction = None
                if row.interaction_proposal_id is not None:
                    interaction = {
                        "kind": "judgment_response",
                        "proposal_id": row.interaction_proposal_id,
                        "statement_hash": row.interaction_statement_hash,
                        "response": row.interaction_response,
                    }
                add_event(row.event_revision, "creator.conversation_turn_recorded", {
                    "turn_id": row.turn_id,
                    "source_ref": row.source_ref,
                    "source_message_ref": row.source_message_ref,
                    "source_role": row.source_role,
                    "actor": row.actor,
                    "authorship_basis": row.authorship_basis,
                    "raw_text": row.raw_text,
                    "content_hash": row.content_hash,
                    "subject_refs": row.subject_refs,
                    **({"interaction": interaction} if interaction is not None else {}),
                })

            for row in db.scalars(select(CreatorEvidenceItem).where(
                CreatorEvidenceItem.workspace_id == workspace_id
            ).order_by(CreatorEvidenceItem.event_revision)).all():
                add_event(row.event_revision, "creator.evidence_recorded", {
                    "evidence_id": row.evidence_id,
                    "source_ref": row.source_ref,
                    "subject_ref": row.subject_ref,
                    "raw_observation": row.raw_observation,
                    "observed_at": _canonical_db_instant(row.observed_at, "observed_at"),
                })

            for row in db.scalars(select(CreatorTurnInterpretation).where(
                CreatorTurnInterpretation.workspace_id == workspace_id
            ).order_by(CreatorTurnInterpretation.event_revision)).all():
                payload = {
                    "interpretation_id": row.interpretation_id,
                    "turn_id": row.turn_id,
                    "task_ref": row.task_ref,
                    "subject_refs": row.subject_refs,
                    "speech_acts": row.speech_acts,
                    "epistemic_status": row.epistemic_status,
                    "scope_level": row.scope_level,
                    "scope_ref": row.scope_ref,
                    "persistence_intent": row.persistence_intent,
                    "annotation_basis": row.annotation_basis,
                    "claim": row.claim,
                    "confidence": row.confidence,
                    "alternatives": row.alternatives,
                    "supporting_refs": row.supporting_refs,
                    "counterevidence_refs": row.counterevidence_refs,
                    "relations": row.relations,
                    "action_effect": row.action_effect,
                    "review_when": row.review_when,
                    "context_compiler_version": row.context_compiler_version,
                    "context_request_hash": row.context_request_hash,
                    "context_task": row.context_task,
                    "context_subject_refs": row.context_subject_refs,
                    "context_as_of": _canonical_db_instant(row.context_as_of, "context_as_of"),
                    "context_max_pending_turns": row.context_max_pending_turns,
                    "context_max_evidence": row.context_max_evidence,
                    "context_max_interpretations": row.context_max_interpretations,
                    "context_hash": row.context_hash,
                    "model_ref": row.model_ref,
                }
                if row.supersedes_interpretation_id is not None:
                    payload["supersedes_interpretation_id"] = row.supersedes_interpretation_id
                add_event(row.event_revision, "creator.turn_interpretation_proposed", payload)

            for row in db.scalars(select(CreatorTaskStateRecord).where(
                CreatorTaskStateRecord.workspace_id == workspace_id
            ).order_by(CreatorTaskStateRecord.event_revision)).all():
                payload = {
                    "task_state_id": row.task_state_id,
                    "task_ref": row.task_ref,
                    "project_ref": row.project_ref,
                    "status": row.status,
                    "objective": row.objective,
                    "focus": row.focus,
                    "acceptance_criteria": row.acceptance_criteria,
                    "open_loops": row.open_loops,
                    "source_turn_refs": row.source_turn_refs,
                }
                if row.supersedes_task_state_id is not None:
                    payload["supersedes_task_state_id"] = row.supersedes_task_state_id
                if row.source_interpretation_ref is not None:
                    payload["source_interpretation_ref"] = row.source_interpretation_ref
                if row.engine_ref is not None:
                    payload["engine_ref"] = row.engine_ref
                add_event(row.event_revision, "creator.task_state_changed", payload)

            for row in db.scalars(select(CreatorBehaviorCalibration).where(
                CreatorBehaviorCalibration.workspace_id == workspace_id
            ).order_by(CreatorBehaviorCalibration.event_revision)).all():
                add_event(row.event_revision, "creator.behavior_calibration_recorded", {
                    "calibration_id": row.calibration_id,
                    "task_ref": row.task_ref,
                    "metric": row.metric,
                    "verdict": row.verdict,
                    "authority": row.authority,
                    "prediction": row.prediction,
                    "observed_result": row.observed_result,
                    "context_hash": row.context_hash,
                    "context_item_refs": row.context_item_refs,
                })

            turns_by_proposal: dict[str, list[str]] = {}
            for proposal_id, turn_id in db.execute(select(
                CreatorJudgmentTurn.proposal_id,
                CreatorJudgmentTurn.turn_id,
            ).join(
                CreatorJudgment,
                (CreatorJudgment.workspace_id == CreatorJudgmentTurn.workspace_id)
                & (CreatorJudgment.proposal_id == CreatorJudgmentTurn.proposal_id),
            ).join(
                CreatorSourceMessage,
                (CreatorSourceMessage.workspace_id == CreatorJudgmentTurn.workspace_id)
                & (CreatorSourceMessage.turn_id == CreatorJudgmentTurn.turn_id),
            ).where(
                CreatorJudgmentTurn.workspace_id == workspace_id,
                CreatorSourceMessage.event_revision < CreatorJudgment.proposal_event_revision,
            )).all():
                turns_by_proposal.setdefault(proposal_id, []).append(turn_id)
            evidence_by_proposal: dict[str, list[str]] = {}
            for proposal_id, evidence_id in db.execute(select(
                CreatorJudgmentEvidence.proposal_id,
                CreatorJudgmentEvidence.evidence_id,
            ).where(CreatorJudgmentEvidence.workspace_id == workspace_id)).all():
                evidence_by_proposal.setdefault(proposal_id, []).append(evidence_id)
            interpretations_by_proposal: dict[str, list[str]] = {}
            for proposal_id, interpretation_id in db.execute(select(
                CreatorJudgmentInterpretation.proposal_id,
                CreatorJudgmentInterpretation.interpretation_id,
            ).where(CreatorJudgmentInterpretation.workspace_id == workspace_id)).all():
                interpretations_by_proposal.setdefault(proposal_id, []).append(interpretation_id)

            for row in db.scalars(select(CreatorJudgment).where(
                CreatorJudgment.workspace_id == workspace_id
            ).order_by(CreatorJudgment.proposal_event_revision)).all():
                request = row.context_request_json
                expected_request_fields = {"task", "subject_refs", "as_of", "max_pending_turns", "max_evidence"}
                if row.proposal_event_type == "creator.judgment_promotion_proposed":
                    expected_request_fields |= {"task_ref", "max_interpretations"}
                if not isinstance(request, dict) or set(request) != expected_request_fields:
                    raise CreatorProjectionError("judgment context request projection is invalid")
                payload = {
                    "proposal_id": row.proposal_id,
                    "judgment_key": row.judgment_key,
                    "subject_ref": row.subject_ref,
                    "statement": row.statement,
                    "statement_hash": row.statement_hash,
                    "typed_value": row.typed_value,
                    "temporality": row.temporality,
                    "context_compiler_version": row.context_compiler_version,
                    "context_request_hash": row.context_request_hash,
                    "context_task": request["task"],
                    "context_subject_refs": request["subject_refs"],
                    "context_as_of": request["as_of"],
                    "context_max_pending_turns": request["max_pending_turns"],
                    "context_max_evidence": request["max_evidence"],
                    "context_hash": row.context_hash,
                    "model_ref": row.model_ref,
                    "source_turn_refs": sorted(
                        turns_by_proposal.get(row.proposal_id, []), key=_javascript_utf16_sort_key
                    ),
                    "evidence_refs": sorted(
                        evidence_by_proposal.get(row.proposal_id, []), key=_javascript_utf16_sort_key
                    ),
                    "reason": row.proposal_reason,
                }
                if row.review_at is not None:
                    payload["review_at"] = _canonical_db_instant(row.review_at, "review_at")
                if row.supersedes_proposal_id is not None:
                    payload["supersedes_judgment_id"] = row.supersedes_proposal_id
                if row.proposal_event_type == "creator.judgment_promotion_proposed":
                    payload.update({
                        "context_task_ref": request["task_ref"],
                        "context_max_interpretations": request["max_interpretations"],
                        "source_interpretation_refs": sorted(
                            interpretations_by_proposal.get(row.proposal_id, []), key=_javascript_utf16_sort_key
                        ),
                        "promotion_basis": row.promotion_basis,
                        "promotion_basis_refs": row.promotion_basis_refs,
                    })
                elif row.proposal_event_type != "creator.judgment_proposed":
                    raise CreatorProjectionError("unknown judgment proposal_event_type")
                add_event(row.proposal_event_revision, row.proposal_event_type, payload)

            for row in db.scalars(select(CreatorJudgmentDecision).where(
                CreatorJudgmentDecision.workspace_id == workspace_id
            ).order_by(CreatorJudgmentDecision.event_revision)).all():
                add_event(row.event_revision, "creator.judgment_responded", {
                    "decision_id": row.decision_id,
                    "proposal_id": row.proposal_id,
                    "response_turn_ref": row.response_turn_id,
                    "response": row.response,
                    "expected_statement_hash": row.expected_statement_hash,
                })

            for row in db.scalars(select(CreatorJudgmentContradiction).where(
                CreatorJudgmentContradiction.workspace_id == workspace_id
            ).order_by(CreatorJudgmentContradiction.recorded_event_revision)).all():
                refs = [
                    ref for ref in (
                        row.contradicting_evidence_id,
                        row.contradicting_turn_id,
                        row.contradicting_judgment_id,
                    ) if ref is not None
                ]
                if len(refs) != 1:
                    raise CreatorProjectionError("contradiction projection must contain exactly one contradicting ref")
                add_event(row.recorded_event_revision, "creator.judgment_contradiction_recorded", {
                    "contradiction_id": row.contradiction_id,
                    "judgment_id": row.judgment_id,
                    "contradicting_ref": refs[0],
                    "reason": row.reason,
                })

            for row in db.scalars(select(CreatorJudgmentContradictionResolution).where(
                CreatorJudgmentContradictionResolution.workspace_id == workspace_id
            ).order_by(CreatorJudgmentContradictionResolution.event_revision)).all():
                add_event(row.event_revision, "creator.judgment_contradiction_resolved", {
                    "resolution_id": row.resolution_id,
                    "contradiction_id": row.contradiction_id,
                    "resolution": row.resolution,
                    "resolution_ref": row.resolution_ref,
                    "reason": row.reason,
                })

            if sorted(projected_events) != expected_revisions:
                missing = sorted(set(expected_revisions) - set(projected_events))
                raise CreatorProjectionError(f"relational projections do not cover event revisions: {missing}")
            digest = self._projection_digest_in_session(db, workspace_id, expected_revision)
            last_revision = db.scalar(select(CreatorWorkspace.current_revision).where(
                CreatorWorkspace.id == workspace_id
            ))
            if last_revision != first_revision:
                raise CreatorProjectionRevisionMismatchError(
                    "workspace revision changed while reconstructing Creator projections"
                )
            return {
                "revision": expected_revision,
                "digest": digest,
                "records": [
                    {
                        "event": projected_events[revision],
                        "committed_by": {
                            "principal_id": metadata[revision].principal_id,
                            "product": metadata[revision].principal_product,
                            "environment": metadata[revision].principal_environment,
                            "capability": metadata[revision].authorized_capability,
                        },
                    }
                    for revision in expected_revisions
                ],
            }

    @staticmethod
    def _projection_digest_in_session(
        db: Session,
        workspace_id: str,
        revision: int,
    ) -> dict[str, Any]:
        source_rows = db.execute(select(
            CreatorSource.source_ref,
            CreatorSource.source_event_revision,
            CreatorSource.rights_decision,
            CreatorSource.rights_event_revision,
        ).where(CreatorSource.workspace_id == workspace_id)).all()
        current = db.scalars(select(CreatorJudgment.proposal_id).where(
            CreatorJudgment.workspace_id == workspace_id,
            CreatorJudgment.status == "tim_confirmed",
            CreatorJudgment.superseded_at.is_(None),
        )).all()
        pending = db.scalars(select(CreatorJudgment.proposal_id).where(
            CreatorJudgment.workspace_id == workspace_id,
            CreatorJudgment.status == "proposed",
            CreatorJudgment.superseded_at.is_(None),
        )).all()
        decisions = db.scalars(select(CreatorJudgmentDecision.decision_id).where(
            CreatorJudgmentDecision.workspace_id == workspace_id
        )).all()
        contradictions = db.scalars(select(CreatorJudgmentContradiction.contradiction_id).where(
            CreatorJudgmentContradiction.workspace_id == workspace_id,
            CreatorJudgmentContradiction.resolved_at.is_(None),
        )).all()
        return {
            "revision": revision,
            "source_rights": [
                {
                    "source_ref": row.source_ref,
                    "source_event_revision": row.source_event_revision,
                    "rights_decision": row.rights_decision,
                    "rights_event_revision": row.rights_event_revision,
                }
                for row in sorted(source_rows, key=lambda item: _javascript_utf16_sort_key(item.source_ref))
            ],
            "current_judgment_refs": sorted(current, key=_javascript_utf16_sort_key),
            "pending_judgment_refs": sorted(pending, key=_javascript_utf16_sort_key),
            "decision_refs": sorted(decisions, key=_javascript_utf16_sort_key),
            "unresolved_contradiction_refs": sorted(contradictions, key=_javascript_utf16_sort_key),
        }

    def read_projection_digest(self, workspace_id: str, principal: CreatorPrincipal) -> dict[str, Any]:
        """Read the rebuildable projection at one observed workspace revision.

        A REPEATABLE READ, read-only transaction supplies one database snapshot;
        the first/last revision fence also detects a revision mismatch visible
        at that snapshot. A drift checker can compare this digest with a cold
        TypeScript replay without exposing raw source text to a wider API.
        """

        principal.require("context.read_private")
        with self._session_factory() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            first_revision = db.scalar(select(CreatorWorkspace.current_revision).where(
                CreatorWorkspace.id == workspace_id
            ))
            if first_revision is None:
                return self._projection_digest_in_session(db, workspace_id, 0)
            digest = self._projection_digest_in_session(db, workspace_id, first_revision)
            last_revision = db.scalar(select(CreatorWorkspace.current_revision).where(
                CreatorWorkspace.id == workspace_id
            ))
            if last_revision != first_revision:
                raise CreatorProjectionError("workspace revision changed while reading Creator projections")
            return digest

    def _reconcile(
        self,
        event: dict[str, Any],
        payload_hash: str,
        principal: CreatorPrincipal,
        capability: str,
    ) -> CreatorAppendReceipt | None:
        with self._session_factory() as db:
            existing = self._find_event(db, event["workspace_id"], event["event_id"])
            if existing is None:
                return None
            return self._idempotent_receipt(existing, payload_hash, principal, capability)

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
    def _idempotent_receipt(
        existing: CreatorWorkspaceEvent,
        payload_hash: str,
        principal: CreatorPrincipal,
        capability: str,
    ) -> CreatorAppendReceipt:
        if existing.payload_sha256 != payload_hash:
            raise CreatorAppendConflictError(f"event_id content conflict: {existing.event_id}")
        if (
            existing.principal_id != principal.principal_id
            or existing.principal_product != principal.product
            or existing.principal_environment != principal.environment
            or existing.authorized_capability != capability
        ):
            raise CreatorAppendConflictError(f"event_id principal conflict: {existing.event_id}")
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
        elif event_type == "creator.turn_interpretation_proposed":
            self._project_interpretation(db, event, revision, occurred_at)
        elif event_type == "creator.task_state_changed":
            self._project_task_state(db, event, revision, occurred_at)
        elif event_type == "creator.behavior_calibration_recorded":
            self._project_calibration(db, event, revision)
        elif event_type in {"creator.judgment_proposed", "creator.judgment_promotion_proposed"}:
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
    def _known_context_ref(db: Session, workspace_id: str, reference: str) -> bool:
        return any((
            db.get(CreatorSourceMessage, (workspace_id, reference)) is not None,
            db.get(CreatorEvidenceItem, (workspace_id, reference)) is not None,
            db.get(CreatorTurnInterpretation, (workspace_id, reference)) is not None,
            db.get(CreatorTaskStateRecord, (workspace_id, reference)) is not None,
            db.get(CreatorBehaviorCalibration, (workspace_id, reference)) is not None,
            db.get(CreatorJudgment, (workspace_id, reference)) is not None,
            db.get(CreatorJudgmentContradiction, (workspace_id, reference)) is not None,
        ))

    def _project_interpretation(
        self, db: Session, event: dict[str, Any], revision: int, occurred_at: datetime
    ) -> None:
        turn = db.get(CreatorSourceMessage, (event["workspace_id"], event["turn_id"]))
        if turn is None or set(turn.subject_refs) != set(event["subject_refs"]):
            raise CreatorProjectionError("interpretation subjects must exactly preserve every source turn privacy label")
        self._require_allowed_source(db, event["workspace_id"], turn.source_ref)
        for reference in event["supporting_refs"] + event["counterevidence_refs"]:
            referenced_turn = db.get(CreatorSourceMessage, (event["workspace_id"], reference))
            referenced_evidence = db.get(CreatorEvidenceItem, (event["workspace_id"], reference))
            if sum(item is not None for item in (referenced_turn, referenced_evidence)) != 1:
                raise CreatorProjectionError("interpretation evidence must directly reference one turn or evidence item")
            if referenced_turn is not None:
                self._require_allowed_source(db, event["workspace_id"], referenced_turn.source_ref)
                if not set(referenced_turn.subject_refs).issubset(event["subject_refs"]):
                    raise CreatorProjectionError("interpretation evidence belongs to another subject")
            if referenced_evidence is not None:
                self._require_allowed_source(db, event["workspace_id"], referenced_evidence.source_ref)
                if referenced_evidence.subject_ref not in event["subject_refs"]:
                    raise CreatorProjectionError("interpretation evidence belongs to another subject")
        for relation in event["relations"]:
            target_judgment = db.get(CreatorJudgment, (event["workspace_id"], relation["target_ref"]))
            target_interpretation = db.get(CreatorTurnInterpretation, (
                event["workspace_id"], relation["target_ref"]
            ))
            if target_judgment is None and target_interpretation is None:
                raise CreatorProjectionError("interpretation relation target must be a judgment or interpretation")
            if (
                target_judgment is not None and target_judgment.subject_ref not in event["subject_refs"]
            ) or (
                target_interpretation is not None
                and set(target_interpretation.subject_refs) != set(event["subject_refs"])
            ):
                raise CreatorProjectionError("interpretation relation target belongs to another subject")
        if event["scope_level"] == "project":
            active_task = db.scalar(select(CreatorTaskStateRecord).where(
                CreatorTaskStateRecord.workspace_id == event["workspace_id"],
                CreatorTaskStateRecord.task_ref == event["task_ref"],
                CreatorTaskStateRecord.superseded_at.is_(None),
            ))
            if active_task is None or active_task.project_ref != event["scope_ref"]:
                raise CreatorProjectionError("project interpretation requires the matching active task project")
        if event["persistence_intent"] == "durable_explicit" and (
            turn.actor != "tim" or turn.source_role != "user"
            or turn.authorship_basis not in {"direct_unquoted_message", "manual_review"}
            or event["annotation_basis"] != "direct_language" or event["epistemic_status"] != "explicit"
            or event["scope_level"] not in {"project", "cross_project", "global"}
            or not any(item in {"instruction", "decision"} for item in event["speech_acts"])
            or event["action_effect"] != "candidate_for_promotion"
        ):
            raise CreatorProjectionError("durable interpretation requires an exact Tim instruction or decision")
        if "external_quote" in event["speech_acts"] and event["persistence_intent"] == "durable_explicit":
            raise CreatorProjectionError("quoted material cannot become Tim durable intent")
        previous = None
        if event.get("supersedes_interpretation_id"):
            previous = db.get(CreatorTurnInterpretation, (
                event["workspace_id"], event["supersedes_interpretation_id"]
            ))
            if (
                previous is None or previous.superseded_at is not None or previous.task_ref != event["task_ref"]
                or set(previous.subject_refs) != set(event["subject_refs"])
            ):
                raise CreatorProjectionError("superseded interpretation must be active in the same task and subject")
            previous.superseded_at = occurred_at
        db.add(CreatorTurnInterpretation(
            workspace_id=event["workspace_id"], interpretation_id=event["interpretation_id"],
            turn_id=event["turn_id"], task_ref=event["task_ref"], subject_refs=event["subject_refs"],
            speech_acts=event["speech_acts"], epistemic_status=event["epistemic_status"],
            scope_level=event["scope_level"], scope_ref=event["scope_ref"],
            persistence_intent=event["persistence_intent"], annotation_basis=event["annotation_basis"],
            claim=event["claim"], confidence=event["confidence"], alternatives=event["alternatives"],
            supporting_refs=event["supporting_refs"], counterevidence_refs=event["counterevidence_refs"],
            relations=event["relations"], action_effect=event["action_effect"], review_when=event["review_when"],
            context_compiler_version=event["context_compiler_version"],
            context_request_hash=event["context_request_hash"], context_task=event["context_task"],
            context_subject_refs=event["context_subject_refs"],
            context_as_of=_instant(event["context_as_of"], "context_as_of"),
            context_max_pending_turns=event["context_max_pending_turns"],
            context_max_evidence=event["context_max_evidence"],
            context_max_interpretations=event["context_max_interpretations"], context_hash=event["context_hash"],
            model_ref=event["model_ref"], supersedes_interpretation_id=event.get("supersedes_interpretation_id"),
            event_revision=revision,
        ))

    def _project_task_state(
        self, db: Session, event: dict[str, Any], revision: int, occurred_at: datetime
    ) -> None:
        turns = [db.get(CreatorSourceMessage, (event["workspace_id"], ref)) for ref in event["source_turn_refs"]]
        if any(turn is None for turn in turns):
            raise CreatorProjectionError("task state references an unknown turn")
        if not all(
            turn.actor == "tim" and turn.source_role == "user"
            and turn.authorship_basis in {"direct_unquoted_message", "manual_review"}
            for turn in turns if turn is not None
        ):
            raise CreatorProjectionError("every task state source must be an exact Tim turn")
        for turn in turns:
            self._require_allowed_source(db, event["workspace_id"], turn.source_ref)
        current = db.scalar(select(CreatorTaskStateRecord).where(
            CreatorTaskStateRecord.workspace_id == event["workspace_id"],
            CreatorTaskStateRecord.task_ref == event["task_ref"],
            CreatorTaskStateRecord.superseded_at.is_(None),
        ))
        if current is not None and event.get("supersedes_task_state_id") != current.task_state_id:
            raise CreatorProjectionError("task state must explicitly supersede the current state")
        if current is None and event.get("supersedes_task_state_id") is not None:
            raise CreatorProjectionError("task state cannot supersede a missing state")
        if current is not None:
            interpretation = db.get(CreatorTurnInterpretation, (
                event["workspace_id"], event.get("source_interpretation_ref")
            ))
            if (
                event.get("engine_ref") != CREATOR_TASK_STATE_ENGINE_VERSION
                or interpretation is None or interpretation.superseded_at is not None
                or interpretation.task_ref != current.task_ref
                or interpretation.action_effect != "change_current_task"
            ):
                raise CreatorProjectionError(
                    "task state update requires the mechanical engine and an active same-task change_current_task interpretation"
                )
            if interpretation.scope_level == "project" and interpretation.scope_ref != current.project_ref:
                raise CreatorProjectionError("task state update interpretation project does not match the active task")
            expected_source_refs = sorted(
                set(current.source_turn_refs + [interpretation.turn_id]), key=_javascript_utf16_sort_key
            )
            if (
                event["project_ref"] != current.project_ref or event["status"] != current.status
                or event["objective"] != current.objective or event["focus"] != interpretation.claim
                or event["acceptance_criteria"] != current.acceptance_criteria
                or event["open_loops"] != current.open_loops
                or event["source_turn_refs"] != expected_source_refs
            ):
                raise CreatorProjectionError(
                    "task state update may only copy stable task fields and replace focus from its interpretation"
                )
            current.superseded_at = occurred_at
            db.flush()
        elif event.get("source_interpretation_ref") is not None or event.get("engine_ref") is not None:
            raise CreatorProjectionError("initial task state cannot claim a derived interpretation update")
        db.add(CreatorTaskStateRecord(
            workspace_id=event["workspace_id"], task_state_id=event["task_state_id"], task_ref=event["task_ref"],
            project_ref=event["project_ref"], status=event["status"], objective=event["objective"], focus=event["focus"],
            acceptance_criteria=event["acceptance_criteria"], open_loops=event["open_loops"],
            source_turn_refs=event["source_turn_refs"], supersedes_task_state_id=event.get("supersedes_task_state_id"),
            source_interpretation_ref=event.get("source_interpretation_ref"), engine_ref=event.get("engine_ref"),
            event_revision=revision,
        ))

    @staticmethod
    def _require_calibration_allowed_source(db: Session, workspace_id: str, source_ref: str) -> None:
        source = db.get(CreatorSource, (workspace_id, source_ref))
        if source is None or source.rights_decision != "allowed":
            raise CreatorProjectionError(
                "calibration context_item_refs require currently allowed source rights"
            )

    def _context_ref_privacy_closure(
        self,
        db: Session,
        workspace_id: str,
        reference: str,
        visited: frozenset[str] = frozenset(),
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Resolve subjects and task bindings from relational source rows.

        This deliberately does not trust the TypeScript derivation attestation:
        the database boundary independently follows every source-bearing edge,
        checks current rights and fails closed on unknown or cyclic lineage.
        """

        if reference in visited:
            raise CreatorProjectionError("calibration context_item_refs contain cyclic lineage")
        next_visited = visited | {reference}

        turn = db.get(CreatorSourceMessage, (workspace_id, reference))
        if turn is not None:
            self._require_calibration_allowed_source(db, workspace_id, turn.source_ref)
            subjects = frozenset(turn.subject_refs)
            if not subjects:
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            return subjects, frozenset()

        evidence = db.get(CreatorEvidenceItem, (workspace_id, reference))
        if evidence is not None:
            self._require_calibration_allowed_source(db, workspace_id, evidence.source_ref)
            if not evidence.subject_ref:
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            return frozenset({evidence.subject_ref}), frozenset()

        interpretation = db.get(CreatorTurnInterpretation, (workspace_id, reference))
        if interpretation is not None:
            subjects = frozenset(interpretation.subject_refs)
            if not subjects:
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            tasks = {interpretation.task_ref}
            for item_ref in [
                interpretation.turn_id,
                *interpretation.supporting_refs,
                *interpretation.counterevidence_refs,
            ]:
                child_subjects, child_tasks = self._context_ref_privacy_closure(
                    db, workspace_id, item_ref, next_visited
                )
                if not child_subjects or not child_subjects.issubset(subjects):
                    raise CreatorProjectionError(
                        "calibration context_item_refs must share one exact privacy subject set"
                    )
                tasks.update(child_tasks)
            return subjects, frozenset(tasks)

        task_state = db.get(CreatorTaskStateRecord, (workspace_id, reference))
        if task_state is not None:
            subjects: set[str] = set()
            tasks = {task_state.task_ref}
            for item_ref in task_state.source_turn_refs:
                child_subjects, child_tasks = self._context_ref_privacy_closure(
                    db, workspace_id, item_ref, next_visited
                )
                subjects.update(child_subjects)
                tasks.update(child_tasks)
            if not subjects:
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            return frozenset(subjects), frozenset(tasks)

        judgment = db.get(CreatorJudgment, (workspace_id, reference))
        if judgment is not None:
            subjects = {judgment.subject_ref}
            tasks: set[str] = set()
            turn_refs = db.scalars(select(CreatorJudgmentTurn.turn_id).where(
                CreatorJudgmentTurn.workspace_id == workspace_id,
                CreatorJudgmentTurn.proposal_id == reference,
            )).all()
            evidence_refs = db.scalars(select(CreatorJudgmentEvidence.evidence_id).where(
                CreatorJudgmentEvidence.workspace_id == workspace_id,
                CreatorJudgmentEvidence.proposal_id == reference,
            )).all()
            interpretation_refs = db.scalars(select(CreatorJudgmentInterpretation.interpretation_id).where(
                CreatorJudgmentInterpretation.workspace_id == workspace_id,
                CreatorJudgmentInterpretation.proposal_id == reference,
            )).all()
            lineage_refs = [
                *turn_refs,
                *evidence_refs,
                *interpretation_refs,
                *(judgment.promotion_basis_refs or []),
            ]
            if not lineage_refs:
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            for item_ref in dict.fromkeys(lineage_refs):
                child_subjects, _ = self._context_ref_privacy_closure(
                    db, workspace_id, item_ref, next_visited
                )
                if not child_subjects:
                    raise CreatorProjectionError(
                        "calibration context_item_refs must share one exact privacy subject set"
                    )
                subjects.update(child_subjects)
            # A promoted judgment is durable knowledge, not task-local state.
            # Its lineage still contributes privacy subjects and rights, while
            # the originating interpretation/calibration task does not bind
            # future legitimate uses of that judgment to the old task.
            return frozenset(subjects), frozenset(tasks)

        contradiction = db.get(CreatorJudgmentContradiction, (workspace_id, reference))
        if contradiction is not None:
            contradicting_ref = (
                contradiction.contradicting_evidence_id
                or contradiction.contradicting_turn_id
                or contradiction.contradicting_judgment_id
            )
            if contradicting_ref is None:
                raise CreatorProjectionError("calibration contradiction lineage is incomplete")
            subject_sets: list[frozenset[str]] = []
            tasks: set[str] = set()
            for item_ref in [contradiction.judgment_id, contradicting_ref]:
                child_subjects, child_tasks = self._context_ref_privacy_closure(
                    db, workspace_id, item_ref, next_visited
                )
                subject_sets.append(child_subjects)
                tasks.update(child_tasks)
            if not subject_sets[0] or subject_sets[0] != subject_sets[1]:
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            return subject_sets[0], frozenset(tasks)

        calibration = db.get(CreatorBehaviorCalibration, (workspace_id, reference))
        if calibration is not None:
            subject_sets: list[frozenset[str]] = []
            tasks = {calibration.task_ref}
            for item_ref in calibration.context_item_refs:
                child_subjects, child_tasks = self._context_ref_privacy_closure(
                    db, workspace_id, item_ref, next_visited
                )
                subject_sets.append(child_subjects)
                tasks.update(child_tasks)
            if not subject_sets or not subject_sets[0] or any(
                subjects != subject_sets[0] for subjects in subject_sets
            ):
                raise CreatorProjectionError(
                    "calibration context_item_refs must share one exact privacy subject set"
                )
            return subject_sets[0], frozenset(tasks)

        raise CreatorProjectionError("calibration context_item_refs contain an unknown ref")

    def _project_calibration(self, db: Session, event: dict[str, Any], revision: int) -> None:
        if not event["context_item_refs"]:
            raise CreatorProjectionError("calibration requires at least one context item")
        closures = [
            self._context_ref_privacy_closure(db, event["workspace_id"], reference)
            for reference in event["context_item_refs"]
        ]
        first_subjects = closures[0][0]
        if not first_subjects or any(subjects != first_subjects for subjects, _ in closures):
            raise CreatorProjectionError(
                "calibration context_item_refs must share one exact privacy subject set"
            )
        if any(
            task_ref != event["task_ref"]
            for _, task_refs in closures
            for task_ref in task_refs
        ):
            raise CreatorProjectionError(
                "calibration context_item_refs must belong to the calibration task when task-bound"
            )
        db.add(CreatorBehaviorCalibration(
            workspace_id=event["workspace_id"], calibration_id=event["calibration_id"], task_ref=event["task_ref"],
            metric=event["metric"], verdict=event["verdict"], authority=event["authority"],
            prediction=event["prediction"], observed_result=event["observed_result"],
            context_hash=event["context_hash"], context_item_refs=event["context_item_refs"], event_revision=revision,
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

    def _validate_judgment_promotion(self, db: Session, event: dict[str, Any]) -> None:
        if event["model_ref"] != CREATOR_PROMOTION_ENGINE_VERSION:
            raise CreatorProjectionError("judgment promotion requires the mechanical promotion engine identity")
        if event["context_compiler_version"] != CREATOR_CONTEXT_COMPILER_VERSION:
            raise CreatorProjectionError("judgment promotion requires the current context compiler version")
        interpretations = [db.get(CreatorTurnInterpretation, (
            event["workspace_id"], reference
        )) for reference in event["source_interpretation_refs"]]
        if any(item is None or item.superseded_at is not None for item in interpretations):
            raise CreatorProjectionError("judgment promotion requires active interpretations")
        active = [item for item in interpretations if item is not None]
        for item in active:
            turn = db.get(CreatorSourceMessage, (event["workspace_id"], item.turn_id))
            if turn is None:
                raise CreatorProjectionError("judgment promotion interpretation lost its source turn")
            self._require_allowed_source(db, event["workspace_id"], turn.source_ref)
            if (
                turn.actor != "tim" or turn.source_role != "user"
                or turn.authorship_basis not in {"direct_unquoted_message", "manual_review"}
                or "external_quote" in item.speech_acts
            ):
                raise CreatorProjectionError(
                    "judgment promotion requires exact Tim-authored source turns and cannot promote external quotes"
                )
            for reference in item.supporting_refs + item.counterevidence_refs:
                referenced_turn = db.get(CreatorSourceMessage, (event["workspace_id"], reference))
                referenced_evidence = db.get(CreatorEvidenceItem, (event["workspace_id"], reference))
                if referenced_turn is not None:
                    self._require_allowed_source(db, event["workspace_id"], referenced_turn.source_ref)
                if referenced_evidence is not None:
                    self._require_allowed_source(db, event["workspace_id"], referenced_evidence.source_ref)
        if any(event["subject_ref"] not in item.subject_refs for item in active):
            raise CreatorProjectionError("judgment promotion interpretation belongs to another subject")
        if any(
            item.action_effect != "candidate_for_promotion"
            or item.epistemic_status in {"ambiguous", "hypothetical", "unknown"}
            or item.counterevidence_refs or item.alternatives
            for item in active
        ):
            raise CreatorProjectionError("judgment promotion requires resolved promotion candidates")
        expected_turns = sorted({item.turn_id for item in active}, key=_javascript_utf16_sort_key)
        if event["source_turn_refs"] != expected_turns:
            raise CreatorProjectionError("promotion source turns must exactly match interpretations")
        for item in active:
            if item.scope_level == "project":
                active_task = db.scalar(select(CreatorTaskStateRecord).where(
                    CreatorTaskStateRecord.workspace_id == event["workspace_id"],
                    CreatorTaskStateRecord.task_ref == event["context_task_ref"],
                    CreatorTaskStateRecord.project_ref == item.scope_ref,
                    CreatorTaskStateRecord.superseded_at.is_(None),
                ))
                if active_task is None:
                    raise CreatorProjectionError("project promotion is outside the active task project")
        basis = event["promotion_basis"]
        if basis == "durable_explicit":
            if event["promotion_basis_refs"] != event["source_interpretation_refs"] or any(
                item.persistence_intent != "durable_explicit" or item.annotation_basis != "direct_language"
                or item.epistemic_status != "explicit" or item.scope_level not in {"project", "cross_project", "global"}
                or not any(act in {"instruction", "decision"} for act in item.speech_acts)
                for item in active
            ):
                raise CreatorProjectionError("invalid durable explicit promotion basis")
        elif basis == "repeated_independent_tasks":
            turns = [db.get(CreatorSourceMessage, (event["workspace_id"], item.turn_id)) for item in active]
            grounded_tasks = all(db.scalar(select(CreatorTaskStateRecord.task_state_id).where(
                CreatorTaskStateRecord.workspace_id == event["workspace_id"],
                CreatorTaskStateRecord.task_ref == item.task_ref,
                CreatorTaskStateRecord.source_turn_refs.contains([item.turn_id]),
            )) is not None for item in active)
            if (
                len(active) < 2 or len({item.task_ref for item in active}) < 2
                or len({turn.source_message_ref for turn in turns if turn is not None}) < 2
                or event["promotion_basis_refs"] != event["source_interpretation_refs"]
                or any(item.persistence_intent not in {"provisional", "durable_explicit"} for item in active)
                or not grounded_tasks
            ):
                raise CreatorProjectionError("repeated promotion requires two grounded independent tasks and messages")
        else:
            calibrations = [db.get(CreatorBehaviorCalibration, (
                event["workspace_id"], reference
            )) for reference in event["promotion_basis_refs"]]
            if not calibrations or any(item is None for item in calibrations):
                raise CreatorProjectionError("outcome promotion requires exact calibration refs")
            exact = [item for item in calibrations if item is not None]
            def carries_real_world_evidence(item: CreatorBehaviorCalibration) -> bool:
                for reference in set(item.context_item_refs).intersection(event["evidence_refs"]):
                    evidence = db.get(CreatorEvidenceItem, (event["workspace_id"], reference))
                    if evidence is not None and evidence.subject_ref == event["subject_ref"]:
                        return True
                return False
            if basis == "validated_outcome" and any(
                item.verdict != "pass" or item.authority != "real_world"
                or not set(item.context_item_refs).intersection(event["source_interpretation_refs"])
                or not carries_real_world_evidence(item)
                for item in exact
            ):
                raise CreatorProjectionError("validated outcome promotion lacks passing real-world calibration evidence")
            if basis == "high_cost_failure" and any(
                item.verdict != "fail" or item.authority != "real_world"
                or not set(item.context_item_refs).intersection(event["source_interpretation_refs"])
                or not carries_real_world_evidence(item)
                for item in exact
            ):
                raise CreatorProjectionError("high-cost promotion lacks failed real-world calibration evidence")

    def _project_judgment(self, db: Session, event: dict[str, Any], revision: int) -> None:
        if event["statement_hash"] != content_hash(event["statement"]):
            raise CreatorProjectionError("judgment statement_hash mismatch")
        request = {
            "task": event["context_task"], "subject_refs": event["context_subject_refs"],
            "as_of": event["context_as_of"], "max_pending_turns": event["context_max_pending_turns"],
            "max_evidence": event["context_max_evidence"],
        }
        if event["type"] == "creator.judgment_promotion_proposed":
            request["task_ref"] = event["context_task_ref"]
            request["max_interpretations"] = event["context_max_interpretations"]
        if event["context_request_hash"] != content_hash(request):
            raise CreatorProjectionError("judgment context_request_hash mismatch")
        for turn_id in event["source_turn_refs"]:
            self._exact_subject_turn(db, event["workspace_id"], turn_id, event["subject_ref"])
        for evidence_id in event["evidence_refs"]:
            self._exact_subject_evidence(db, event["workspace_id"], evidence_id, event["subject_ref"])
        if event["type"] == "creator.judgment_promotion_proposed":
            self._validate_judgment_promotion(db, event)
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
            model_ref=event["model_ref"], proposal_event_type=event["type"],
            context_task_ref=event.get("context_task_ref"),
            context_max_interpretations=event.get("context_max_interpretations"),
            promotion_basis=event.get("promotion_basis"), promotion_basis_refs=event.get("promotion_basis_refs"),
            proposal_reason=event["reason"], proposal_event_revision=revision,
        )
        db.add(judgment)
        db.flush()
        db.add_all([
            CreatorJudgmentTurn(workspace_id=event["workspace_id"], proposal_id=event["proposal_id"], turn_id=turn_id)
            for turn_id in event["source_turn_refs"]
        ] + [
            CreatorJudgmentEvidence(workspace_id=event["workspace_id"], proposal_id=event["proposal_id"], evidence_id=evidence_id)
            for evidence_id in event["evidence_refs"]
        ] + [
            CreatorJudgmentInterpretation(
                workspace_id=event["workspace_id"], proposal_id=event["proposal_id"], interpretation_id=interpretation_id
            )
            for interpretation_id in event.get("source_interpretation_refs", [])
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
        turn = db.get(CreatorSourceMessage, (workspace_id, reference))
        judgment = db.get(CreatorJudgment, (workspace_id, reference))
        matches = [
            evidence is not None and evidence.subject_ref == subject_ref,
            turn is not None and set(turn.subject_refs) == {subject_ref},
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
