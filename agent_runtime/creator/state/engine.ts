import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";

import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import { compileCreatorContext, CREATOR_CONTEXT_COMPILER_VERSION } from "../context/compiler.ts";
import { withJsonlLock } from "../../shared/jsonl-lock.ts";
import {
  createCreatorCapabilityGate,
  creatorCalibrationAuthorityCapability,
  creatorCapabilityForEvent,
} from "../capabilities.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import type { CreatorWorkspaceStore } from "./store-port.ts";
import {
  AUTHORSHIP_BASES,
  CLAIM_TEMPORALITIES,
  CONTRADICTION_RESOLUTIONS,
  CONFLICT_RESULTS,
  CREATOR_ACTORS,
  CREATOR_CALIBRATION_AUTHORITIES,
  CREATOR_CALIBRATION_METRICS,
  CREATOR_SOURCE_ROLES,
  CREATOR_TASK_STATE_ENGINE_VERSION,
  CREATOR_TASK_STATUSES,
  EVAL_VERDICTS,
  INTERPRETATION_ACTION_EFFECTS,
  INTERPRETATION_ANNOTATION_BASES,
  INTERPRETATION_EPISTEMIC_STATUSES,
  INTERPRETATION_PERSISTENCE_INTENTS,
  INTERPRETATION_RELATION_KINDS,
  INTERPRETATION_SCOPE_LEVELS,
  INTERPRETATION_SPEECH_ACTS,
  JUDGMENT_PROMOTION_BASES,
  JUDGMENT_RESPONSES,
  RIGHTS_DECISIONS,
  type CreatorEvent,
  type CreatorInterpretationState,
  type CreatorStoredEvent,
  type CreatorView,
} from "./types.ts";


function containsUnpairedSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      return true;
    }
  }
  return false;
}

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a non-empty string`);
  if (containsUnpairedSurrogate(value)) throw new Error(`${label} must contain only Unicode scalar values`);
}

function requireUtcInstant(value: unknown, label: string): asserts value is string {
  requireString(value, label);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString() !== value) throw new Error(`${label} must be a canonical UTC instant`);
}

function requireContentHash(value: unknown, label: string): asserts value is string {
  requireString(value, label);
  if (!/^sha256:[0-9a-f]{64}$/.test(value)) throw new Error(`${label} must be a sha256 content hash`);
}

function requireRefs(value: unknown, label: string): asserts value is string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${label} must contain at least one ref`);
  }
  for (const item of value) requireString(item, label);
}

function requireStringArray(value: unknown, label: string): asserts value is string[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be a string array`);
  for (const item of value) requireString(item, label);
}

function requireUniqueStringArray(value: unknown, label: string): asserts value is string[] {
  requireStringArray(value, label);
  if (new Set(value).size !== value.length) throw new Error(`${label} must not contain duplicate refs`);
}

function requireSortedUniqueStringArray(value: unknown, label: string): asserts value is string[] {
  requireUniqueStringArray(value, label);
  if (canonicalJson(value) !== canonicalJson([...value].sort())) throw new Error(`${label} must be sorted`);
}

function requireExactJsonNumber(value: unknown, label: string): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${label} must be finite`);
  if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
    throw new Error(`${label} must be within the JavaScript safe integer range`);
  }
}

function requireExactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const allowedSet = new Set(allowed);
  const extras = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (extras.length) throw new Error(`${label} has unknown fields: ${extras.join(", ")}`);
}

const BASE_EVENT_KEYS = ["schema_version", "event_id", "workspace_id", "base_revision", "occurred_at", "type"] as const;

export function validateCreatorEvent(value: unknown): asserts value is CreatorEvent {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("creator event must be an object");
  const event = value as Record<string, unknown>;
  if (event.schema_version !== 1 && !(event.schema_version === 2 && event.type === "creator.judgment_proposed")) {
    throw new Error("unsupported creator event schema_version");
  }
  requireString(event.event_id, "event_id");
  requireString(event.workspace_id, "workspace_id");
  if (!/^[a-zA-Z0-9._-]+$/.test(event.workspace_id)) throw new Error("workspace_id contains unsafe characters");
  requireUtcInstant(event.occurred_at, "occurred_at");
  if (!Number.isSafeInteger(event.base_revision) || (event.base_revision as number) < 0) throw new Error("base_revision must be a non-negative safe integer");
  switch (event.type) {
    case "creator.workspace_started":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "mission"], event.type);
      requireString(event.mission, "mission");
      return;
    case "creator.source_ingested":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "source_ref", "source_kind", "content_hash", "immutable_ref", "provenance_ref"], event.type);
      requireString(event.source_ref, "source_ref");
      requireString(event.source_kind, "source_kind");
      requireContentHash(event.content_hash, "content_hash");
      requireString(event.immutable_ref, "immutable_ref");
      requireString(event.provenance_ref, "provenance_ref");
      if (!["conversation", "rider_report", "provider", "manual_research", "repository"].includes(event.source_kind as string)) {
        throw new Error("invalid source_kind");
      }
      if (event.source_kind === "repository" && !/^git-blob:[0-9a-f]{40}$/.test(event.immutable_ref as string)) {
        throw new Error("repository source immutable_ref must be a Git blob id");
      }
      return;
    case "creator.conversation_turn_recorded": {
      requireExactKeys(event, [...BASE_EVENT_KEYS, "turn_id", "source_ref", "source_message_ref", "source_role", "actor", "authorship_basis", "raw_text", "content_hash", "subject_refs", "interaction"], event.type);
      requireString(event.turn_id, "turn_id");
      requireString(event.source_ref, "source_ref");
      requireString(event.source_message_ref, "source_message_ref");
      requireString(event.raw_text, "raw_text");
      requireContentHash(event.content_hash, "content_hash");
      requireUniqueStringArray(event.subject_refs, "subject_refs");
      if (event.subject_refs.length === 0) throw new Error("conversation turn requires at least one privacy subject");
      if (!CREATOR_SOURCE_ROLES.includes(event.source_role as never)) throw new Error("invalid creator source_role");
      if (!CREATOR_ACTORS.includes(event.actor as never)) throw new Error("invalid creator actor");
      if (!AUTHORSHIP_BASES.includes(event.authorship_basis as never)) throw new Error("invalid authorship_basis");
      if (event.actor === "tim"
        && (event.source_role !== "user" || !["direct_unquoted_message", "manual_review"].includes(event.authorship_basis as string))) {
        throw new Error("Tim authorship requires a user source role and direct or reviewed evidence");
      }
      if (event.interaction !== undefined) {
        if (event.interaction === null || typeof event.interaction !== "object" || Array.isArray(event.interaction)) {
          throw new Error("interaction must be an object");
        }
        const interaction = event.interaction as unknown as Record<string, unknown>;
        requireExactKeys(interaction, ["kind", "proposal_id", "statement_hash", "response"], "judgment response interaction");
        if (interaction.kind !== "judgment_response") throw new Error("invalid conversation interaction kind");
        requireString(interaction.proposal_id, "interaction.proposal_id");
        requireString(interaction.statement_hash, "interaction.statement_hash");
        if (!JUDGMENT_RESPONSES.includes(interaction.response as never)) throw new Error("invalid judgment interaction response");
        if (event.actor !== "tim" || event.source_role !== "user") {
          throw new Error("judgment response interaction requires a Tim user turn");
        }
      }
      return;
    }
    case "creator.rights_checked":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "rights_check_id", "source_ref", "decision", "policy_ref", "reason"], event.type);
      requireString(event.rights_check_id, "rights_check_id");
      requireString(event.source_ref, "source_ref");
      requireString(event.policy_ref, "policy_ref");
      requireString(event.reason, "reason");
      if (!RIGHTS_DECISIONS.includes(event.decision as never)) throw new Error("invalid rights decision");
      return;
    case "creator.evidence_recorded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "evidence_id", "source_ref", "subject_ref", "raw_observation", "observed_at"], event.type);
      requireString(event.evidence_id, "evidence_id");
      requireString(event.source_ref, "source_ref");
      requireString(event.subject_ref, "subject_ref");
      requireString(event.raw_observation, "raw_observation");
      requireUtcInstant(event.observed_at, "observed_at");
      return;
    case "creator.turn_interpretation_proposed": {
      requireExactKeys(event, [
        ...BASE_EVENT_KEYS, "interpretation_id", "turn_id", "task_ref", "subject_refs", "speech_acts",
        "epistemic_status", "scope_level", "scope_ref", "persistence_intent", "annotation_basis", "claim",
        "confidence", "alternatives", "supporting_refs", "counterevidence_refs", "relations", "action_effect",
        "review_when", "context_compiler_version", "context_request_hash", "context_task", "context_subject_refs",
        "context_as_of", "context_max_pending_turns", "context_max_evidence", "context_max_interpretations",
        "context_hash", "model_ref",
        "supersedes_interpretation_id",
      ], event.type);
      for (const field of [
        "interpretation_id", "turn_id", "task_ref", "scope_ref", "claim", "review_when",
        "context_compiler_version", "context_task", "model_ref",
      ] as const) requireString(event[field], field);
      requireContentHash(event.context_request_hash, "context_request_hash");
      requireContentHash(event.context_hash, "context_hash");
      requireUtcInstant(event.context_as_of, "context_as_of");
      requireSortedUniqueStringArray(event.context_subject_refs, "context_subject_refs");
      for (const field of ["context_max_pending_turns", "context_max_evidence", "context_max_interpretations"] as const) {
        if (!Number.isSafeInteger(event[field]) || (event[field] as number) < 0) {
          throw new Error(`${field} must be a non-negative safe integer`);
        }
      }
      requireSortedUniqueStringArray(event.subject_refs, "subject_refs");
      requireUniqueStringArray(event.speech_acts, "speech_acts");
      if (event.speech_acts.length === 0 || event.speech_acts.some((item) => !INTERPRETATION_SPEECH_ACTS.includes(item as never))) {
        throw new Error("invalid interpretation speech_acts");
      }
      if (!INTERPRETATION_EPISTEMIC_STATUSES.includes(event.epistemic_status as never)) throw new Error("invalid interpretation epistemic_status");
      if (!INTERPRETATION_SCOPE_LEVELS.includes(event.scope_level as never)) throw new Error("invalid interpretation scope_level");
      if (!INTERPRETATION_PERSISTENCE_INTENTS.includes(event.persistence_intent as never)) throw new Error("invalid interpretation persistence_intent");
      if (!INTERPRETATION_ANNOTATION_BASES.includes(event.annotation_basis as never)) throw new Error("invalid interpretation annotation_basis");
      if (!INTERPRETATION_ACTION_EFFECTS.includes(event.action_effect as never)) throw new Error("invalid interpretation action_effect");
      if (event.scope_level === "turn" && event.scope_ref !== event.turn_id) throw new Error("turn interpretation scope_ref must equal turn_id");
      if (event.scope_level === "task" && event.scope_ref !== event.task_ref) throw new Error("task interpretation scope_ref must equal task_ref");
      requireExactJsonNumber(event.confidence, "confidence");
      if ((event.confidence as number) < 0 || (event.confidence as number) > 1) throw new Error("confidence must be between 0 and 1");
      if (!Array.isArray(event.alternatives)) throw new Error("alternatives must be an array");
      for (const alternative of event.alternatives) {
        if (alternative === null || typeof alternative !== "object" || Array.isArray(alternative)) throw new Error("interpretation alternative must be an object");
        const item = alternative as Record<string, unknown>;
        requireExactKeys(item, ["claim", "disconfirming_evidence"], "interpretation alternative");
        requireString(item.claim, "alternative.claim");
        requireString(item.disconfirming_evidence, "alternative.disconfirming_evidence");
      }
      requireSortedUniqueStringArray(event.supporting_refs, "supporting_refs");
      requireSortedUniqueStringArray(event.counterevidence_refs, "counterevidence_refs");
      if (!Array.isArray(event.relations)) throw new Error("relations must be an array");
      const relationKeys = new Set<string>();
      for (const relation of event.relations) {
        if (relation === null || typeof relation !== "object" || Array.isArray(relation)) throw new Error("interpretation relation must be an object");
        const item = relation as Record<string, unknown>;
        requireExactKeys(item, ["target_ref", "kind", "reason"], "interpretation relation");
        requireString(item.target_ref, "relation.target_ref");
        requireString(item.reason, "relation.reason");
        if (!INTERPRETATION_RELATION_KINDS.includes(item.kind as never)) throw new Error("invalid interpretation relation kind");
        const key = `${String(item.kind)}:${String(item.target_ref)}`;
        if (relationKeys.has(key)) throw new Error("interpretation relations must be unique");
        relationKeys.add(key);
      }
      if (event.supersedes_interpretation_id !== undefined) requireString(event.supersedes_interpretation_id, "supersedes_interpretation_id");
      return;
    }
    case "creator.task_state_changed":
      requireExactKeys(event, [
        ...BASE_EVENT_KEYS, "task_state_id", "task_ref", "project_ref", "status", "objective", "focus",
        "acceptance_criteria", "open_loops", "source_turn_refs", "supersedes_task_state_id",
        "source_interpretation_ref", "engine_ref",
      ], event.type);
      for (const field of ["task_state_id", "task_ref", "project_ref", "objective", "focus"] as const) requireString(event[field], field);
      if (!CREATOR_TASK_STATUSES.includes(event.status as never)) throw new Error("invalid Creator task status");
      requireUniqueStringArray(event.acceptance_criteria, "acceptance_criteria");
      requireUniqueStringArray(event.open_loops, "open_loops");
      requireSortedUniqueStringArray(event.source_turn_refs, "source_turn_refs");
      if (event.source_turn_refs.length === 0) throw new Error("task state requires at least one source turn");
      if (event.supersedes_task_state_id !== undefined) requireString(event.supersedes_task_state_id, "supersedes_task_state_id");
      if (event.source_interpretation_ref !== undefined) requireString(event.source_interpretation_ref, "source_interpretation_ref");
      if (event.engine_ref !== undefined && event.engine_ref !== CREATOR_TASK_STATE_ENGINE_VERSION) {
        throw new Error("task state engine_ref must identify the mechanical task state engine");
      }
      if ((event.supersedes_task_state_id === undefined) !== (event.source_interpretation_ref === undefined)
        || (event.supersedes_task_state_id === undefined) !== (event.engine_ref === undefined)) {
        throw new Error("task state update bundle must contain supersedes_task_state_id, source_interpretation_ref and engine_ref together");
      }
      return;
    case "creator.behavior_calibration_recorded":
      requireExactKeys(event, [
        ...BASE_EVENT_KEYS, "calibration_id", "task_ref", "metric", "verdict", "authority", "prediction",
        "observed_result", "context_hash", "context_item_refs",
      ], event.type);
      for (const field of ["calibration_id", "task_ref", "prediction", "observed_result"] as const) requireString(event[field], field);
      requireContentHash(event.context_hash, "context_hash");
      requireSortedUniqueStringArray(event.context_item_refs, "context_item_refs");
      if (!CREATOR_CALIBRATION_METRICS.includes(event.metric as never)) throw new Error("invalid Creator calibration metric");
      if (!CREATOR_CALIBRATION_AUTHORITIES.includes(event.authority as never)) throw new Error("invalid Creator calibration authority");
      if (!EVAL_VERDICTS.includes(event.verdict as never)) throw new Error("invalid Creator calibration verdict");
      return;
    case "creator.claim_proposed":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "claim_id", "subject_ref", "predicate", "proposed_value", "temporality", "valid_from", "valid_to", "review_at", "evidence_refs"], event.type);
      requireString(event.claim_id, "claim_id");
      requireString(event.subject_ref, "subject_ref");
      requireString(event.predicate, "predicate");
      requireRefs(event.evidence_refs, "evidence_refs");
      if (!CLAIM_TEMPORALITIES.includes(event.temporality as (typeof CLAIM_TEMPORALITIES)[number])) throw new Error("invalid claim temporality");
      if (!["string", "number", "boolean"].includes(typeof event.proposed_value)) throw new Error("invalid proposed_value");
      if (typeof event.proposed_value === "string" && containsUnpairedSurrogate(event.proposed_value)) throw new Error("proposed_value must contain only Unicode scalar values");
      if (typeof event.proposed_value === "number") requireExactJsonNumber(event.proposed_value, "proposed_value");
      for (const field of ["valid_from", "valid_to", "review_at"] as const) {
        if (event[field] !== undefined) requireUtcInstant(event[field], field);
      }
      if (event.temporality === "temporary") {
        if (!event.valid_from || !event.valid_to || !event.review_at) throw new Error("temporary claim requires valid_from, valid_to and review_at");
        if (event.valid_from >= event.valid_to) throw new Error("temporary claim valid_from must precede valid_to");
        if (event.review_at > event.valid_to) throw new Error("temporary claim review_at cannot follow valid_to");
      }
      if (event.temporality === "slow_changing" && !event.review_at) throw new Error("slow_changing claim requires review_at");
      if (event.temporality === "permanent" && event.valid_to) throw new Error("permanent claim cannot have valid_to");
      if (event.review_at && event.review_at <= event.occurred_at) throw new Error("review_at must be after the claim proposal");
      return;
    case "creator.judgment_proposed":
    case "creator.judgment_promotion_proposed":
      requireExactKeys(event, [
        ...BASE_EVENT_KEYS, "proposal_id", "judgment_key", "subject_ref", "statement", "statement_hash", "typed_value",
        "temporality", "context_compiler_version", "context_request_hash", "context_task", "context_subject_refs",
        "context_as_of", "context_max_pending_turns", "context_max_evidence", "context_hash", "model_ref", "review_at",
        "source_turn_refs", "evidence_refs", "supersedes_judgment_id", "reason",
        ...(event.type === "creator.judgment_promotion_proposed"
          ? ["context_task_ref", "context_max_interpretations", "source_interpretation_refs", "promotion_basis", "promotion_basis_refs"] : []),
      ], event.type);
      requireString(event.proposal_id, "proposal_id");
      requireString(event.judgment_key, "judgment_key");
      requireString(event.subject_ref, "subject_ref");
      requireString(event.statement, "statement");
      requireString(event.statement_hash, "statement_hash");
      requireString(event.context_compiler_version, "context_compiler_version");
      requireString(event.context_request_hash, "context_request_hash");
      requireString(event.context_task, "context_task");
      requireUniqueStringArray(event.context_subject_refs, "context_subject_refs");
      requireUtcInstant(event.context_as_of, "context_as_of");
      if (canonicalJson(event.context_subject_refs) !== canonicalJson([...event.context_subject_refs].sort())) {
        throw new Error("context_subject_refs must be sorted");
      }
      if (!Number.isSafeInteger(event.context_max_pending_turns) || (event.context_max_pending_turns as number) < 0) throw new Error("context_max_pending_turns must be a non-negative safe integer");
      if (!Number.isSafeInteger(event.context_max_evidence) || (event.context_max_evidence as number) < 0) throw new Error("context_max_evidence must be a non-negative safe integer");
      requireString(event.context_hash, "context_hash");
      requireString(event.model_ref, "model_ref");
      requireString(event.reason, "reason");
      requireUniqueStringArray(event.source_turn_refs, "source_turn_refs");
      requireUniqueStringArray(event.evidence_refs, "evidence_refs");
      if (canonicalJson(event.source_turn_refs) !== canonicalJson([...event.source_turn_refs].sort())) {
        throw new Error("source_turn_refs must be sorted");
      }
      if (canonicalJson(event.evidence_refs) !== canonicalJson([...event.evidence_refs].sort())) {
        throw new Error("evidence_refs must be sorted");
      }
      if (event.source_turn_refs.length + event.evidence_refs.length === 0) throw new Error("judgment proposal requires at least one source turn or evidence ref");
      if (event.type === "creator.judgment_proposed" && event.schema_version === 2 && event.source_turn_refs.length > 0) {
        throw new Error("schema v2 compatibility judgment cannot consume conversation turns; use interpretation and promotion");
      }
      if (event.type === "creator.judgment_proposed" && event.schema_version === 2 && event.evidence_refs.length === 0) {
        throw new Error("schema v2 compatibility judgment requires route/domain evidence");
      }
      if (!["string", "number", "boolean"].includes(typeof event.typed_value)) throw new Error("invalid judgment typed_value");
      if (typeof event.typed_value === "string" && containsUnpairedSurrogate(event.typed_value)) throw new Error("judgment typed_value must contain only Unicode scalar values");
      if (typeof event.typed_value === "number") requireExactJsonNumber(event.typed_value, "judgment typed_value");
      if (!CLAIM_TEMPORALITIES.includes(event.temporality as never)) throw new Error("invalid judgment temporality");
      if (event.review_at !== undefined) requireUtcInstant(event.review_at, "review_at");
      if (event.temporality !== "permanent" && !event.review_at) throw new Error("non-permanent judgment requires review_at");
      if (event.review_at && event.review_at <= event.occurred_at) throw new Error("review_at must be after the judgment proposal");
      if (event.supersedes_judgment_id !== undefined) requireString(event.supersedes_judgment_id, "supersedes_judgment_id");
      if (event.type === "creator.judgment_promotion_proposed") {
        requireString(event.context_task_ref, "context_task_ref");
        if (!Number.isSafeInteger(event.context_max_interpretations) || (event.context_max_interpretations as number) <= 0) {
          throw new Error("context_max_interpretations must be a positive safe integer");
        }
        requireSortedUniqueStringArray(event.source_interpretation_refs, "source_interpretation_refs");
        requireSortedUniqueStringArray(event.promotion_basis_refs, "promotion_basis_refs");
        if (event.source_interpretation_refs.length === 0) throw new Error("judgment promotion requires an interpretation");
        if (!JUDGMENT_PROMOTION_BASES.includes(event.promotion_basis as never)) throw new Error("invalid judgment promotion basis");
      }
      return;
    case "creator.judgment_responded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "decision_id", "proposal_id", "response_turn_ref", "response", "expected_statement_hash"], event.type);
      requireString(event.decision_id, "decision_id");
      requireString(event.proposal_id, "proposal_id");
      requireString(event.response_turn_ref, "response_turn_ref");
      requireString(event.expected_statement_hash, "expected_statement_hash");
      if (!JUDGMENT_RESPONSES.includes(event.response as never)) throw new Error("invalid judgment response");
      return;
    case "creator.judgment_contradiction_recorded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "contradiction_id", "judgment_id", "contradicting_ref", "reason"], event.type);
      requireString(event.contradiction_id, "contradiction_id");
      requireString(event.judgment_id, "judgment_id");
      requireString(event.contradicting_ref, "contradicting_ref");
      requireString(event.reason, "reason");
      return;
    case "creator.judgment_contradiction_resolved":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "resolution_id", "contradiction_id", "resolution", "resolution_ref", "reason"], event.type);
      requireString(event.resolution_id, "resolution_id");
      requireString(event.contradiction_id, "contradiction_id");
      requireString(event.resolution_ref, "resolution_ref");
      requireString(event.reason, "reason");
      if (!CONTRADICTION_RESOLUTIONS.includes(event.resolution as never)) throw new Error("invalid contradiction resolution");
      return;
    case "creator.conflict_analyzed":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "analysis_id", "claim_id", "result", "conflicting_claim_refs", "reason"], event.type);
      requireString(event.analysis_id, "analysis_id");
      requireString(event.claim_id, "claim_id");
      requireStringArray(event.conflicting_claim_refs, "conflicting_claim_refs");
      requireString(event.reason, "reason");
      if (!CONFLICT_RESULTS.includes(event.result as never)) throw new Error("invalid conflict result");
      if (event.result === "conflicting" && event.conflicting_claim_refs.length === 0) throw new Error("conflicting analysis needs claim refs");
      return;
    case "creator.eval_recorded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "eval_id", "claim_id", "verdict", "grader_ref", "reason"], event.type);
      requireString(event.eval_id, "eval_id");
      requireString(event.claim_id, "claim_id");
      requireString(event.grader_ref, "grader_ref");
      requireString(event.reason, "reason");
      if (!EVAL_VERDICTS.includes(event.verdict as (typeof EVAL_VERDICTS)[number])) throw new Error("invalid eval verdict");
      return;
    case "creator.human_review_requested":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "review_id", "target_ref", "request_kind", "reason"], event.type);
      requireString(event.review_id, "review_id");
      requireString(event.target_ref, "target_ref");
      requireString(event.reason, "reason");
      if (!["rights_review", "conflict_review", "request_more_evidence"].includes(event.request_kind as string)) throw new Error("invalid human review request_kind");
      return;
    case "creator.world_change_proposed":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "proposal_id", "claim_refs", "target_world_revision"], event.type);
      requireString(event.proposal_id, "proposal_id");
      requireRefs(event.claim_refs, "claim_refs");
      requireString(event.target_world_revision, "target_world_revision");
      return;
    default:
      throw new Error(`unknown or forbidden creator event type: ${String(event.type)}`);
  }
}

/**
 * Online append contract. Historical schema-v1 conversation judgments remain
 * readable by validateCreatorEvent/replayCreatorWorkspace, but can never be
 * appended after the interpretation/promotion boundary exists.
 */
export function validateCreatorAppendEvent(value: unknown): asserts value is CreatorEvent {
  validateCreatorEvent(value);
  if (value.type === "creator.judgment_proposed" && value.schema_version !== 2) {
    throw new Error("schema v1 creator judgment is replay-only; new writes must use schema v2 evidence or interpretation promotion");
  }
}

function initial(event: Extract<CreatorEvent, { type: "creator.workspace_started" }>): CreatorView {
  return {
    schema_version: 1,
    workspace_id: event.workspace_id,
    mission: event.mission,
    revision: 1,
    last_event_id: event.event_id,
    last_occurred_at: event.occurred_at,
    sources: {},
    conversation_turns: {},
    rights_checks: {},
    evidence: {},
    interpretations: {},
    task_states: {},
    behavior_calibrations: {},
    claims: {},
    judgments: {},
    judgment_decisions: {},
    judgment_contradictions: {},
    judgment_contradiction_resolutions: {},
    conflict_analyses: {},
    evaluations: {},
    human_review_requests: {},
    world_change_proposals: {},
  };
}

function sameStringSet(left: readonly string[], right: readonly string[]): boolean {
  return canonicalJson([...left].sort()) === canonicalJson([...right].sort());
}

function knownContextItem(view: CreatorView, ref: string): boolean {
  return Boolean(
    view.interpretations[ref] || view.task_states[ref] || view.behavior_calibrations[ref]
    || view.judgments[ref] || view.judgment_contradictions[ref] || view.evidence[ref]
    || view.conversation_turns[ref],
  );
}

function sourceRightsAllowed(view: CreatorView, sourceRef: string): boolean {
  return Object.values(view.rights_checks).filter((check) => check.source_ref === sourceRef).at(-1)?.decision === "allowed";
}

function directContextRefRightsAllowed(view: CreatorView, ref: string): boolean {
  const turn = view.conversation_turns[ref];
  const evidence = view.evidence[ref];
  return turn ? sourceRightsAllowed(view, turn.source_ref)
    : evidence ? sourceRightsAllowed(view, evidence.source_ref)
      : false;
}

function interpretationRightsAllowed(view: CreatorView, item: CreatorInterpretationState): boolean {
  const turn = view.conversation_turns[item.turn_id];
  return turn !== undefined && sourceRightsAllowed(view, turn.source_ref)
    && [...item.supporting_refs, ...item.counterevidence_refs].every((ref) => directContextRefRightsAllowed(view, ref));
}

function contextItemSubjectRefs(view: CreatorView, ref: string, visited = new Set<string>()): string[] | undefined {
  if (visited.has(ref)) return undefined;
  const nextVisited = new Set(visited).add(ref);
  const turn = view.conversation_turns[ref];
  if (turn) return turn.subject_refs.length === 0 ? undefined : [...turn.subject_refs].sort();
  const evidence = view.evidence[ref];
  if (evidence) return evidence.subject_ref === "" ? undefined : [evidence.subject_ref];
  const interpretation = view.interpretations[ref];
  if (interpretation) {
    const declared = [...interpretation.subject_refs].sort();
    if (declared.length === 0) return undefined;
    const lineageRefs = [interpretation.turn_id, ...interpretation.supporting_refs, ...interpretation.counterevidence_refs];
    const lineageSubjects = lineageRefs.map((itemRef) => contextItemSubjectRefs(view, itemRef, nextVisited));
    if (lineageSubjects.some((subjects) => !subjects || subjects.length === 0
      || subjects.some((subject) => !declared.includes(subject)))) return undefined;
    return declared;
  }
  const task = view.task_states[ref];
  if (task) {
    const subjectSets = task.source_turn_refs.map((turnRef) => contextItemSubjectRefs(view, turnRef, nextVisited));
    if (subjectSets.length === 0 || subjectSets.some((subjects) => !subjects || subjects.length === 0)) return undefined;
    return [...new Set(subjectSets.flatMap((subjects) => subjects ?? []))].sort();
  }
  const judgment = view.judgments[ref];
  if (judgment) {
    const lineageRefs = [...new Set([
      ...judgment.source_turn_refs,
      ...judgment.evidence_refs,
      ...(judgment.source_interpretation_refs ?? []),
      ...(judgment.promotion_basis_refs ?? []),
    ])];
    const lineageSubjects = lineageRefs.map((itemRef) => contextItemSubjectRefs(view, itemRef, nextVisited));
    if (lineageSubjects.length === 0 || lineageSubjects.some((subjects) => !subjects || subjects.length === 0)) {
      return undefined;
    }
    return [...new Set([judgment.subject_ref, ...lineageSubjects.flatMap((subjects) => subjects ?? [])])].sort();
  }
  const contradiction = view.judgment_contradictions[ref];
  if (contradiction) {
    const targetSubjects = contextItemSubjectRefs(view, contradiction.judgment_id, nextVisited);
    const contradictingSubjects = contextItemSubjectRefs(view, contradiction.contradicting_ref, nextVisited);
    if (!targetSubjects || !contradictingSubjects || !sameStringSet(targetSubjects, contradictingSubjects)) {
      return undefined;
    }
    return targetSubjects;
  }
  const calibration = view.behavior_calibrations[ref];
  if (calibration) {
    const subjectSets = calibration.context_item_refs.map((itemRef) => contextItemSubjectRefs(view, itemRef, nextVisited));
    if (subjectSets.length === 0 || subjectSets.some((subjects) => subjects === undefined)) return undefined;
    const first = subjectSets[0]!;
    return first.length > 0 && subjectSets.every((subjects) => (
      subjects !== undefined && subjects.length > 0 && sameStringSet(subjects, first)
    )) ? first : undefined;
  }
  return undefined;
}

function contextItemRightsAllowed(view: CreatorView, ref: string, visited = new Set<string>()): boolean {
  if (visited.has(ref)) return false;
  const nextVisited = new Set(visited).add(ref);
  const turn = view.conversation_turns[ref];
  if (turn) return sourceRightsAllowed(view, turn.source_ref);
  const evidence = view.evidence[ref];
  if (evidence) return sourceRightsAllowed(view, evidence.source_ref);
  const interpretation = view.interpretations[ref];
  if (interpretation) return interpretationRightsAllowed(view, interpretation);
  const task = view.task_states[ref];
  if (task) return task.source_turn_refs.length > 0
    && task.source_turn_refs.every((turnRef) => contextItemRightsAllowed(view, turnRef, nextVisited));
  const judgment = view.judgments[ref];
  if (judgment) {
    const lineageRefs = [...new Set([
      ...judgment.source_turn_refs,
      ...judgment.evidence_refs,
      ...(judgment.source_interpretation_refs ?? []),
      ...(judgment.promotion_basis_refs ?? []),
    ])];
    return lineageRefs.length > 0
      && lineageRefs.every((itemRef) => contextItemRightsAllowed(view, itemRef, nextVisited));
  }
  const contradiction = view.judgment_contradictions[ref];
  if (contradiction) return contextItemRightsAllowed(view, contradiction.judgment_id, nextVisited)
    && contextItemRightsAllowed(view, contradiction.contradicting_ref, nextVisited);
  const calibration = view.behavior_calibrations[ref];
  return calibration !== undefined && calibration.context_item_refs.length > 0
    && calibration.context_item_refs.every((itemRef) => contextItemRightsAllowed(view, itemRef, nextVisited));
}

function contextItemTaskMatches(view: CreatorView, ref: string, taskRef: string): boolean {
  const interpretation = view.interpretations[ref];
  const task = view.task_states[ref];
  const calibration = view.behavior_calibrations[ref];
  return interpretation ? interpretation.task_ref === taskRef
    : task ? task.task_ref === taskRef
      : calibration ? calibration.task_ref === taskRef
        : true;
}

function interpretationSourceIsTimAuthored(view: CreatorView, item: CreatorInterpretationState): boolean {
  const turn = view.conversation_turns[item.turn_id];
  return turn !== undefined && turn.actor === "tim" && turn.source_role === "user"
    && ["direct_unquoted_message", "manual_review"].includes(turn.authorship_basis)
    && !item.speech_acts.includes("external_quote");
}

function validatePromotionGate(
  view: CreatorView,
  event: Extract<CreatorEvent, { type: "creator.judgment_promotion_proposed" }>,
): void {
  if (event.model_ref !== "creator-promotion-engine-v0") {
    throw new Error("judgment promotion requires the mechanical promotion engine identity");
  }
  if (event.context_compiler_version !== CREATOR_CONTEXT_COMPILER_VERSION) {
    throw new Error("judgment promotion requires the current context compiler version");
  }
  const bundle = compileCreatorContext(view, {
    task: event.context_task,
    task_ref: event.context_task_ref,
    subject_refs: event.context_subject_refs,
    as_of: event.context_as_of,
    max_pending_turns: event.context_max_pending_turns,
    max_evidence: event.context_max_evidence,
    max_interpretations: event.context_max_interpretations,
  });
  if (event.context_request_hash !== bundle.manifest.request_hash
    || event.context_hash !== bundle.manifest.context_hash
    || !sameStringSet(event.context_subject_refs, bundle.context.subject_refs)
    || event.source_interpretation_refs.some((ref) => !bundle.manifest.included.interpretation_refs.includes(ref))) {
    throw new Error("judgment promotion context does not replay to the exact visible interpretation set");
  }
  const interpretations = event.source_interpretation_refs.map((ref) => view.interpretations[ref]);
  if (interpretations.some((item) => item === undefined || item.superseded)) {
    throw new Error("judgment promotion requires active interpretation refs");
  }
  const active = interpretations.filter((item) => item !== undefined);
  if (active.some((item) => !interpretationRightsAllowed(view, item))) {
    throw new Error("judgment promotion requires currently allowed source rights");
  }
  if (active.some((item) => !interpretationSourceIsTimAuthored(view, item))) {
    throw new Error("judgment promotion requires exact Tim-authored source turns and cannot promote external quotes");
  }
  if (active.some((item) => !item.subject_refs.includes(event.subject_ref))) {
    throw new Error("judgment promotion interpretation belongs to another subject");
  }
  if (active.some((item) => (
    item.action_effect !== "candidate_for_promotion"
    || ["ambiguous", "hypothetical", "unknown"].includes(item.epistemic_status)
    || item.counterevidence_refs.length > 0
    || item.alternatives.length > 0
  ))) {
    throw new Error("judgment promotion requires resolved promotion candidates");
  }
  if (!sameStringSet(event.source_turn_refs, active.map((item) => item.turn_id))) {
    throw new Error("judgment promotion source turns must exactly match its interpretations");
  }
  const basisSet = new Set(event.promotion_basis_refs);
  if (event.promotion_basis === "durable_explicit") {
    if (!sameStringSet(event.promotion_basis_refs, event.source_interpretation_refs)) {
      throw new Error("durable explicit promotion basis must name the exact interpretations");
    }
    if (active.some((item) => (
      item.persistence_intent !== "durable_explicit" || item.annotation_basis !== "direct_language"
      || item.epistemic_status !== "explicit" || !["project", "cross_project", "global"].includes(item.scope_level)
      || !item.speech_acts.some((act) => act === "instruction" || act === "decision")
    ))) {
      throw new Error("durable explicit promotion requires an explicit durable Tim instruction or decision");
    }
  } else if (event.promotion_basis === "repeated_independent_tasks") {
    const taskRefs = new Set(active.map((item) => item.task_ref));
    const messageRefs = new Set(active.map((item) => view.conversation_turns[item.turn_id]?.source_message_ref));
    const taskStateGrounded = active.every((item) => Object.values(view.task_states).some((taskState) => (
      taskState.task_ref === item.task_ref && taskState.source_turn_refs.includes(item.turn_id)
    )));
    if (active.length < 2 || taskRefs.size < 2 || messageRefs.size < 2
      || !sameStringSet(event.promotion_basis_refs, event.source_interpretation_refs)
      || active.some((item) => !["provisional", "durable_explicit"].includes(item.persistence_intent))
      || !taskStateGrounded) {
      throw new Error("repeated promotion requires exact evidence from two grounded independent tasks and messages");
    }
  } else {
    const calibrations = event.promotion_basis_refs.map((ref) => view.behavior_calibrations[ref]);
    if (calibrations.length === 0 || calibrations.some((item) => item === undefined || !basisSet.has(item.calibration_id))) {
      throw new Error("outcome promotion requires exact calibration refs");
    }
    const exactCalibrations = calibrations.filter((item) => item !== undefined);
    const carriesRealWorldEvidence = (item: (typeof exactCalibrations)[number]) => item.context_item_refs.some((ref) => (
      view.evidence[ref]?.subject_ref === event.subject_ref && event.evidence_refs.includes(ref)
    ));
    if (event.promotion_basis === "validated_outcome" && exactCalibrations.some((item) => (
      item.verdict !== "pass" || item.authority !== "real_world"
      || !item.context_item_refs.some((ref) => event.source_interpretation_refs.includes(ref))
      || !carriesRealWorldEvidence(item)
    ))) {
      throw new Error("validated outcome promotion requires passing real-world calibration with exact evidence");
    }
    if (event.promotion_basis === "high_cost_failure" && exactCalibrations.some((item) => (
      item.verdict !== "fail" || item.authority !== "real_world"
      || !item.context_item_refs.some((ref) => event.source_interpretation_refs.includes(ref))
      || !carriesRealWorldEvidence(item)
    ))) {
      throw new Error("high-cost promotion requires failed real-world calibration with exact evidence");
    }
  }
}

export function applyCreatorEvent(view: CreatorView | undefined, event: CreatorEvent, principal: RuntimePrincipal): CreatorView {
  validateCreatorEvent(event);
  const capabilities = createCreatorCapabilityGate(principal);
  if (!view) {
    if (event.type !== "creator.workspace_started" || event.base_revision !== 0) throw new Error("first creator event must start a workspace");
    capabilities.require("workspace.create");
    return initial(event);
  }
  if (event.type === "creator.workspace_started") throw new Error("creator workspace already started");
  if (event.workspace_id !== view.workspace_id) throw new Error("workspace_id mismatch");
  if (event.base_revision !== view.revision) throw new Error(`stale base_revision: expected ${view.revision}`);
  if (event.occurred_at < view.last_occurred_at) throw new Error("occurred_at must be monotonic");
  const next = structuredClone(view);
  next.revision += 1;
  next.last_event_id = event.event_id;
  next.last_occurred_at = event.occurred_at;

  switch (event.type) {
    case "creator.source_ingested":
      capabilities.require("source.ingest");
      if (next.sources[event.source_ref]) throw new Error("duplicate source_ref");
      next.sources[event.source_ref] = event;
      break;
    case "creator.conversation_turn_recorded": {
      capabilities.require("conversation.record");
      if (!next.sources[event.source_ref]) throw new Error("conversation turn requires an ingested source");
      if (Object.values(next.rights_checks).filter((check) => check.source_ref === event.source_ref).at(-1)?.decision !== "allowed") {
        throw new Error("conversation turn requires an allowed rights check");
      }
      if (event.content_hash !== contentHash(event.raw_text)) throw new Error("conversation turn content_hash mismatch");
      if (event.interaction) {
        const proposal = next.judgments[event.interaction.proposal_id];
        if (!proposal || proposal.status !== "proposed" || proposal.superseded
          || proposal.statement_hash !== event.interaction.statement_hash
          || !event.subject_refs.includes(proposal.subject_ref)) {
          throw new Error("judgment response interaction requires an existing exact active proposal");
        }
      }
      if (next.conversation_turns[event.turn_id]) throw new Error("duplicate creator turn_id");
      if (Object.values(next.conversation_turns).some((turn) => turn.source_message_ref === event.source_message_ref)) {
        throw new Error("duplicate source_message_ref");
      }
      next.conversation_turns[event.turn_id] = event;
      break;
    }
    case "creator.rights_checked":
      capabilities.require("rights.check");
      if (!next.sources[event.source_ref]) throw new Error("rights check requires an ingested source");
      if (next.rights_checks[event.rights_check_id]) throw new Error("duplicate rights_check_id");
      next.rights_checks[event.rights_check_id] = event;
      break;
    case "creator.evidence_recorded":
      capabilities.require("evidence.inspect_raw");
      if (!next.sources[event.source_ref]) throw new Error("evidence requires an ingested source");
      if (Object.values(next.rights_checks).filter((check) => check.source_ref === event.source_ref).at(-1)?.decision !== "allowed") {
        throw new Error("evidence requires an allowed rights check");
      }
      if (next.evidence[event.evidence_id]) throw new Error("duplicate evidence_id");
      next.evidence[event.evidence_id] = event;
      break;
    case "creator.turn_interpretation_proposed": {
      capabilities.require("interpretation.propose");
      if (next.interpretations[event.interpretation_id]) throw new Error("duplicate interpretation_id");
      const turn = next.conversation_turns[event.turn_id];
      if (!turn) throw new Error("interpretation requires an immutable source turn");
      if (!sourceRightsAllowed(next, turn.source_ref)) throw new Error("interpretation requires currently allowed source rights");
      if (event.subject_refs.length === 0 || !sameStringSet(event.subject_refs, turn.subject_refs)) {
        throw new Error("interpretation subjects must exactly preserve every source turn privacy label");
      }
      const referenced = [...event.supporting_refs, ...event.counterevidence_refs];
      if (referenced.some((ref) => !next.conversation_turns[ref] && !next.evidence[ref])) {
        throw new Error("interpretation evidence must directly reference an immutable turn or evidence item");
      }
      if (referenced.some((ref) => !directContextRefRightsAllowed(next, ref))) {
        throw new Error("interpretation evidence requires currently allowed source rights");
      }
      if (referenced.some((ref) => {
        const referencedTurn = next.conversation_turns[ref];
        const referencedEvidence = next.evidence[ref];
        return referencedTurn ? !referencedTurn.subject_refs.every((subject) => event.subject_refs.includes(subject))
          : referencedEvidence ? !event.subject_refs.includes(referencedEvidence.subject_ref) : true;
      })) {
        throw new Error("interpretation evidence belongs to another subject");
      }
      for (const relation of event.relations) {
        const targetJudgment = next.judgments[relation.target_ref];
        const targetInterpretation = next.interpretations[relation.target_ref];
        if (!targetJudgment && !targetInterpretation) {
          throw new Error("interpretation relation target must be a known judgment or interpretation");
        }
        if ((targetJudgment && !event.subject_refs.includes(targetJudgment.subject_ref))
          || (targetInterpretation && !sameStringSet(event.subject_refs, targetInterpretation.subject_refs))) {
          throw new Error("interpretation relation target belongs to another subject");
        }
      }
      const replayedContext = compileCreatorContext(view, {
        task: event.context_task,
        task_ref: event.task_ref,
        subject_refs: event.context_subject_refs,
        as_of: event.context_as_of,
        max_pending_turns: event.context_max_pending_turns,
        max_evidence: event.context_max_evidence,
        max_interpretations: event.context_max_interpretations,
      });
      if (event.context_compiler_version !== CREATOR_CONTEXT_COMPILER_VERSION
        || event.context_request_hash !== replayedContext.manifest.request_hash
        || event.context_hash !== replayedContext.manifest.context_hash
        || !replayedContext.manifest.included.turn_refs.includes(event.turn_id)) {
        throw new Error("interpretation context does not replay to the exact source turn");
      }
      if (event.persistence_intent === "durable_explicit") {
        if (turn.actor !== "tim" || turn.source_role !== "user"
          || !["direct_unquoted_message", "manual_review"].includes(turn.authorship_basis)
          || event.annotation_basis !== "direct_language" || event.epistemic_status !== "explicit"
          || !["project", "cross_project", "global"].includes(event.scope_level)
          || !event.speech_acts.some((act) => act === "instruction" || act === "decision")
          || event.action_effect !== "candidate_for_promotion") {
          throw new Error("durable interpretation requires an exact Tim instruction or decision");
        }
      }
      if (event.speech_acts.includes("external_quote") && event.persistence_intent === "durable_explicit") {
        throw new Error("quoted external material cannot become Tim's durable intent");
      }
      if (event.scope_level === "project") {
        const activeTask = Object.values(next.task_states).find((item) => (
          item.task_ref === event.task_ref && !item.superseded
        ));
        if (!activeTask || activeTask.project_ref !== event.scope_ref) {
          throw new Error("project interpretation requires the matching active task project");
        }
      }
      if (event.supersedes_interpretation_id) {
        const previous = next.interpretations[event.supersedes_interpretation_id];
        if (!previous || previous.superseded || previous.task_ref !== event.task_ref
          || !sameStringSet(previous.subject_refs, event.subject_refs)) {
          throw new Error("superseded interpretation must be active in the same task and subject");
        }
        previous.superseded = true;
      }
      next.interpretations[event.interpretation_id] = { ...event, superseded: false };
      break;
    }
    case "creator.task_state_changed": {
      capabilities.require("task.update");
      if (next.task_states[event.task_state_id]) throw new Error("duplicate task_state_id");
      const turns = event.source_turn_refs.map((ref) => next.conversation_turns[ref]);
      if (turns.some((turn) => turn === undefined)) throw new Error("task state references an unknown turn");
      if (!turns.every((turn) => turn?.actor === "tim" && turn.source_role === "user"
        && ["direct_unquoted_message", "manual_review"].includes(turn.authorship_basis))) {
        throw new Error("every task state source must be an exact Tim turn");
      }
      if (turns.some((turn) => !turn || !sourceRightsAllowed(next, turn.source_ref))) {
        throw new Error("task state requires currently allowed source rights");
      }
      const active = Object.values(next.task_states).find((item) => item.task_ref === event.task_ref && !item.superseded);
      if (active && event.supersedes_task_state_id !== active.task_state_id) {
        throw new Error("task state change must explicitly supersede the current state");
      }
      if (!active && event.supersedes_task_state_id) throw new Error("task state cannot supersede a missing state");
      if (active) {
        const interpretation = event.source_interpretation_ref
          ? next.interpretations[event.source_interpretation_ref]
          : undefined;
        if (event.engine_ref !== CREATOR_TASK_STATE_ENGINE_VERSION || !interpretation || interpretation.superseded
          || interpretation.task_ref !== active.task_ref || interpretation.action_effect !== "change_current_task") {
          throw new Error("task state update requires the mechanical engine and an active same-task change_current_task interpretation");
        }
        if (interpretation.scope_level === "project" && interpretation.scope_ref !== active.project_ref) {
          throw new Error("task state update interpretation project does not match the active task");
        }
        const expectedSourceRefs = [...new Set([...active.source_turn_refs, interpretation.turn_id])].sort();
        if (event.project_ref !== active.project_ref || event.status !== active.status
          || event.objective !== active.objective || event.focus !== interpretation.claim
          || canonicalJson(event.acceptance_criteria) !== canonicalJson(active.acceptance_criteria)
          || canonicalJson(event.open_loops) !== canonicalJson(active.open_loops)
          || canonicalJson(event.source_turn_refs) !== canonicalJson(expectedSourceRefs)) {
          throw new Error("task state update may only copy stable task fields and replace focus from its interpretation");
        }
      } else if (event.source_interpretation_ref !== undefined || event.engine_ref !== undefined) {
        throw new Error("initial task state cannot claim a derived interpretation update");
      }
      if (active) active.superseded = true;
      next.task_states[event.task_state_id] = { ...event, superseded: false };
      break;
    }
    case "creator.behavior_calibration_recorded":
      capabilities.require(creatorCalibrationAuthorityCapability(event.authority));
      if (next.behavior_calibrations[event.calibration_id]) throw new Error("duplicate calibration_id");
      if (event.context_item_refs.some((ref) => !knownContextItem(next, ref))) {
        throw new Error("calibration context_item_refs contain an unknown ref");
      }
      if (event.context_item_refs.length === 0) throw new Error("calibration requires at least one context item");
      const calibrationSubjectSets = event.context_item_refs.map((ref) => contextItemSubjectRefs(next, ref));
      const firstCalibrationSubjects = calibrationSubjectSets[0];
      if (!firstCalibrationSubjects || firstCalibrationSubjects.length === 0 || calibrationSubjectSets.some((subjects) => (
        subjects === undefined || !sameStringSet(subjects, firstCalibrationSubjects)
      ))) {
        throw new Error("calibration context_item_refs must share one exact privacy subject set");
      }
      if (event.context_item_refs.some((ref) => !contextItemRightsAllowed(next, ref))) {
        throw new Error("calibration context_item_refs require currently allowed source rights");
      }
      if (event.context_item_refs.some((ref) => !contextItemTaskMatches(next, ref, event.task_ref))) {
        throw new Error("calibration context_item_refs must belong to the calibration task when task-bound");
      }
      next.behavior_calibrations[event.calibration_id] = event;
      break;
    case "creator.claim_proposed":
      capabilities.require("claim.propose");
      if (event.evidence_refs.some((ref) => !next.evidence[ref])) throw new Error("claim references unknown evidence");
      if (event.evidence_refs.some((ref) => next.evidence[ref]?.subject_ref !== event.subject_ref)) throw new Error("claim evidence belongs to another subject");
      if (next.claims[event.claim_id]) throw new Error("duplicate claim_id");
      next.claims[event.claim_id] = event;
      break;
    case "creator.judgment_proposed":
    case "creator.judgment_promotion_proposed": {
      capabilities.require(event.type === "creator.judgment_proposed" ? "judgment.propose" : "judgment.promote");
      if (event.type === "creator.judgment_promotion_proposed") validatePromotionGate(next, event);
      if (event.type === "creator.judgment_proposed" && event.schema_version === 2) {
        if (event.context_compiler_version !== CREATOR_CONTEXT_COMPILER_VERSION) {
          throw new Error("schema v2 evidence judgment requires the current context compiler version");
        }
        const bundle = compileCreatorContext(next, {
          task: event.context_task,
          subject_refs: event.context_subject_refs,
          as_of: event.context_as_of,
          max_pending_turns: event.context_max_pending_turns,
          max_evidence: event.context_max_evidence,
        });
        if (event.context_request_hash !== bundle.manifest.request_hash
          || event.context_hash !== bundle.manifest.context_hash
          || event.evidence_refs.some((ref) => !bundle.manifest.included.evidence_refs.includes(ref))) {
          throw new Error("schema v2 evidence judgment context does not replay to its exact visible evidence");
        }
      }
      if (next.judgments[event.proposal_id]) throw new Error("duplicate judgment proposal_id");
      if (event.statement_hash !== contentHash(event.statement)) throw new Error("judgment statement_hash mismatch");
      if (event.context_request_hash !== contentHash({
        task: event.context_task,
        ...(event.type === "creator.judgment_promotion_proposed" ? { task_ref: event.context_task_ref } : {}),
        subject_refs: event.context_subject_refs,
        as_of: event.context_as_of,
        max_pending_turns: event.context_max_pending_turns,
        max_evidence: event.context_max_evidence,
        ...(event.type === "creator.judgment_promotion_proposed"
          ? { max_interpretations: event.context_max_interpretations } : {}),
      })) throw new Error("judgment context_request_hash mismatch");
      for (const turnRef of event.source_turn_refs) {
        const turn = next.conversation_turns[turnRef];
        if (!turn) throw new Error("judgment references unknown source turn");
        if (!turn.subject_refs.includes(event.subject_ref)) throw new Error("judgment source turn belongs to another subject");
      }
      for (const evidenceRef of event.evidence_refs) {
        const evidence = next.evidence[evidenceRef];
        if (!evidence) throw new Error("judgment references unknown evidence");
        if (evidence.subject_ref !== event.subject_ref) throw new Error("judgment evidence belongs to another subject");
      }
      const pending = Object.values(next.judgments).find(
        (judgment) => judgment.judgment_key === event.judgment_key && !judgment.superseded && judgment.status === "proposed",
      );
      if (pending) throw new Error(`judgment_key already has a pending proposal: ${event.judgment_key}`);
      const active = Object.values(next.judgments).find(
        (judgment) => judgment.judgment_key === event.judgment_key && !judgment.superseded && judgment.status === "tim_confirmed",
      );
      if (active && event.supersedes_judgment_id !== active.id) {
        throw new Error(`judgment_key already has an active judgment: ${event.judgment_key}`);
      }
      if (event.supersedes_judgment_id) {
        const previous = next.judgments[event.supersedes_judgment_id];
        if (!previous || previous.superseded || previous.status !== "tim_confirmed") {
          throw new Error("superseded judgment is not active and Tim-confirmed");
        }
        if (previous.judgment_key !== event.judgment_key) throw new Error("cannot supersede a different judgment_key");
        if (previous.subject_ref !== event.subject_ref) throw new Error("cannot supersede a judgment from another subject");
      }
      next.judgments[event.proposal_id] = {
        id: event.proposal_id,
        judgment_key: event.judgment_key,
        subject_ref: event.subject_ref,
        statement: event.statement,
        statement_hash: event.statement_hash,
        typed_value: event.typed_value,
        temporality: event.temporality,
        context_compiler_version: event.context_compiler_version,
        context_request_hash: event.context_request_hash,
        context_task: event.context_task,
        context_subject_refs: [...event.context_subject_refs],
        context_as_of: event.context_as_of,
        context_max_pending_turns: event.context_max_pending_turns,
        context_max_evidence: event.context_max_evidence,
        ...(event.type === "creator.judgment_promotion_proposed" ? {
          context_task_ref: event.context_task_ref,
          context_max_interpretations: event.context_max_interpretations,
        } : {}),
        context_hash: event.context_hash,
        model_ref: event.model_ref,
        proposal_event_type: event.type,
        ...(event.type === "creator.judgment_promotion_proposed" ? {
          source_interpretation_refs: [...event.source_interpretation_refs],
          promotion_basis: event.promotion_basis,
          promotion_basis_refs: [...event.promotion_basis_refs],
        } : {}),
        ...(event.review_at ? { review_at: event.review_at } : {}),
        status: "proposed",
        source_turn_refs: [...event.source_turn_refs],
        evidence_refs: [...event.evidence_refs],
        ...(event.supersedes_judgment_id ? { supersedes_judgment_id: event.supersedes_judgment_id } : {}),
        reason: event.reason,
        superseded: false,
        proposed_at: event.occurred_at,
      };
      break;
    }
    case "creator.judgment_responded": {
      capabilities.require("judgment.decide");
      if (next.judgment_decisions[event.decision_id]) throw new Error("duplicate judgment decision_id");
      const judgment = next.judgments[event.proposal_id];
      if (!judgment || judgment.superseded || judgment.status !== "proposed") {
        throw new Error("judgment response requires an unanswered active proposal");
      }
      const responseTurn = next.conversation_turns[event.response_turn_ref];
      const interaction = responseTurn?.interaction;
      if (!responseTurn || responseTurn.actor !== "tim" || responseTurn.source_role !== "user"
        || !interaction || interaction.proposal_id !== judgment.id
        || interaction.statement_hash !== judgment.statement_hash
        || interaction.response !== event.response
        || event.expected_statement_hash !== judgment.statement_hash) {
        throw new Error("judgment response is not bound to this exact proposal and Tim turn");
      }
      judgment.status = event.response;
      judgment.source_turn_refs = [...new Set([...judgment.source_turn_refs, responseTurn.turn_id])];
      judgment.responded_at = event.occurred_at;
      judgment.decision_id = event.decision_id;
      if (event.response === "tim_confirmed" && judgment.supersedes_judgment_id) {
        next.judgments[judgment.supersedes_judgment_id]!.superseded = true;
      }
      next.judgment_decisions[event.decision_id] = event;
      break;
    }
    case "creator.judgment_contradiction_recorded":
      capabilities.require("judgment.contradict");
      if (next.judgment_contradictions[event.contradiction_id]) throw new Error("duplicate judgment contradiction_id");
      const contradicted = next.judgments[event.judgment_id];
      if (!contradicted || contradicted.status !== "tim_confirmed" || contradicted.superseded) {
        throw new Error("contradiction requires an active Tim-confirmed judgment");
      }
      const contradictingEvidence = next.evidence[event.contradicting_ref];
      const contradictingTurn = next.conversation_turns[event.contradicting_ref];
      const contradictingJudgment = next.judgments[event.contradicting_ref];
      if ([contradictingEvidence, contradictingTurn, contradictingJudgment].filter(Boolean).length !== 1) {
        throw new Error("contradiction requires exactly one known evidence, turn or judgment ref");
      }
      if ((contradictingEvidence && contradictingEvidence.subject_ref !== contradicted.subject_ref)
        || (contradictingTurn && !sameStringSet(contradictingTurn.subject_refs, [contradicted.subject_ref]))
        || (contradictingJudgment && contradictingJudgment.subject_ref !== contradicted.subject_ref)) {
        throw new Error("contradiction ref belongs to another subject");
      }
      next.judgment_contradictions[event.contradiction_id] = {
        id: event.contradiction_id,
        judgment_id: event.judgment_id,
        contradicting_ref: event.contradicting_ref,
        reason: event.reason,
        recorded_at: event.occurred_at,
        resolved: false,
      };
      break;
    case "creator.judgment_contradiction_resolved": {
      capabilities.require("judgment.contradict");
      if (next.judgment_contradiction_resolutions[event.resolution_id]) throw new Error("duplicate contradiction resolution_id");
      const contradiction = next.judgment_contradictions[event.contradiction_id];
      if (!contradiction || contradiction.resolved) throw new Error("contradiction resolution requires an unresolved contradiction");
      if (event.resolution === "superseded") {
        const replacement = next.judgments[event.resolution_ref];
        const original = next.judgments[contradiction.judgment_id];
        if (!original || !replacement || replacement.status !== "tim_confirmed"
          || replacement.supersedes_judgment_id !== original.id || !original.superseded) {
          throw new Error("superseded contradiction resolution requires the confirmed replacement judgment");
        }
      } else {
        const original = next.judgments[contradiction.judgment_id];
        const resolutionEvidence = next.evidence[event.resolution_ref];
        const resolutionTurn = next.conversation_turns[event.resolution_ref];
        const resolutionJudgment = next.judgments[event.resolution_ref];
        const resolutionReview = next.human_review_requests[event.resolution_ref];
        if (!original || [resolutionEvidence, resolutionTurn, resolutionJudgment, resolutionReview].filter(Boolean).length !== 1) {
          throw new Error("contradiction resolution requires exactly one known resolution ref");
        }
        if ((resolutionEvidence && resolutionEvidence.subject_ref !== original.subject_ref)
          || (resolutionTurn && !sameStringSet(resolutionTurn.subject_refs, [original.subject_ref]))
          || (resolutionJudgment && resolutionJudgment.subject_ref !== original.subject_ref)
          || (resolutionReview && ![contradiction.id, original.id].includes(resolutionReview.target_ref))) {
          throw new Error("contradiction resolution ref belongs to another subject");
        }
      }
      contradiction.resolved = event.resolution !== "needs_more_evidence";
      contradiction.resolution = event.resolution;
      contradiction.resolution_ref = event.resolution_ref;
      if (contradiction.resolved) contradiction.resolved_at = event.occurred_at;
      next.judgment_contradiction_resolutions[event.resolution_id] = event;
      break;
    }
    case "creator.conflict_analyzed":
      capabilities.require("conflict.analyze");
      if (!next.claims[event.claim_id]) throw new Error("conflict analysis references unknown claim");
      if (event.conflicting_claim_refs.some((ref) => !next.claims[ref])) throw new Error("conflict analysis references unknown conflicting claim");
      if (next.conflict_analyses[event.analysis_id]) throw new Error("duplicate conflict analysis_id");
      next.conflict_analyses[event.analysis_id] = event;
      break;
    case "creator.eval_recorded":
      capabilities.require("eval.run");
      if (!next.claims[event.claim_id]) throw new Error("eval references unknown claim");
      if (next.evaluations[event.eval_id]) throw new Error("duplicate eval_id");
      next.evaluations[event.eval_id] = event;
      break;
    case "creator.human_review_requested":
      capabilities.require("human_review.request");
      if (next.human_review_requests[event.review_id]) throw new Error("duplicate human review_id");
      next.human_review_requests[event.review_id] = event;
      break;
    case "creator.world_change_proposed":
      capabilities.require("world_change.propose");
      for (const claimId of event.claim_refs) {
        if (!next.claims[claimId]) throw new Error("world change references unknown claim");
        const latestEval = Object.values(next.evaluations).filter((evaluation) => evaluation.claim_id === claimId).at(-1);
        if (latestEval?.verdict !== "pass") throw new Error("world change requires the latest eval to pass for every claim");
        const analysis = Object.values(next.conflict_analyses).filter((item) => item.claim_id === claimId).at(-1);
        if (analysis?.result !== "clear") throw new Error("world change requires a clear conflict analysis for every claim");
        for (const evidenceRef of next.claims[claimId]!.evidence_refs) {
          const sourceRef = next.evidence[evidenceRef]!.source_ref;
          if (Object.values(next.rights_checks).filter((check) => check.source_ref === sourceRef).at(-1)?.decision !== "allowed") {
            throw new Error("world change requires allowed source rights");
          }
        }
      }
      if (next.world_change_proposals[event.proposal_id]) throw new Error("duplicate proposal_id");
      next.world_change_proposals[event.proposal_id] = event;
      break;
  }
  return next;
}

function recordCreatorEvent(event: CreatorEvent, principal: RuntimePrincipal): CreatorStoredEvent {
  const capability = creatorCapabilityForEvent(event);
  createCreatorCapabilityGate(principal).require(capability);
  return {
    event: structuredClone(event),
    committed_by: {
      principal_id: principal.principal_id,
      product: "creator",
      environment: principal.environment,
      capability,
    },
  };
}

export function validateCreatorStoredEvent(value: unknown): asserts value is CreatorStoredEvent {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("creator stored event must be an object");
  const record = value as Record<string, unknown>;
  requireExactKeys(record, ["event", "committed_by"], "creator stored event");
  validateCreatorEvent(record.event);
  if (record.committed_by === null || typeof record.committed_by !== "object" || Array.isArray(record.committed_by)) {
    throw new Error("creator principal receipt must be an object");
  }
  const receipt = record.committed_by as Record<string, unknown>;
  requireExactKeys(receipt, ["principal_id", "product", "environment", "capability"], "creator principal receipt");
  requireString(receipt.principal_id, "committed_by.principal_id");
  requireString(receipt.capability, "committed_by.capability");
  if (receipt.product !== "creator") throw new Error("creator receipt product must be creator");
  if (!["test", "shadow", "production"].includes(receipt.environment as string)) throw new Error("invalid creator receipt environment");
  if (receipt.capability !== creatorCapabilityForEvent(record.event as CreatorEvent)) {
    throw new Error("creator receipt capability does not match event type");
  }
}

export function replayCreatorWorkspace(
  recordsOrEvents: readonly CreatorStoredEvent[] | readonly CreatorEvent[],
  testPrincipal?: RuntimePrincipal,
): CreatorView {
  const records = testPrincipal
    ? (recordsOrEvents as readonly CreatorEvent[]).map((event) => recordCreatorEvent(event, testPrincipal))
    : recordsOrEvents as readonly CreatorStoredEvent[];
  let view: CreatorView | undefined;
  const eventIds = new Map<string, string>();
  for (const record of records) {
    validateCreatorStoredEvent(record);
    const encoded = canonicalJson(record);
    const previous = eventIds.get(record.event.event_id);
    if (previous !== undefined) {
      if (previous !== encoded) throw new Error(`event_id content conflict: ${record.event.event_id}`);
      continue;
    }
    eventIds.set(record.event.event_id, encoded);
    const principal: RuntimePrincipal = {
      principal_id: record.committed_by.principal_id,
      product: record.committed_by.product,
      environment: record.committed_by.environment,
      scopes: [record.committed_by.capability],
    };
    view = applyCreatorEvent(view, record.event, principal);
  }
  if (!view) throw new Error("creator workspace has no events");
  return view;
}

export class JsonlCreatorStore implements CreatorWorkspaceStore {
  readonly rootDirectory: string;
  readonly principal: RuntimePrincipal;

  constructor(rootDirectory: string, principal: RuntimePrincipal) {
    this.rootDirectory = rootDirectory;
    this.principal = principal;
  }

  pathFor(workspaceId: string): string {
    if (!/^[a-zA-Z0-9._-]+$/.test(workspaceId)) throw new Error("unsafe workspace_id");
    return join(this.rootDirectory, `${workspaceId}.jsonl`);
  }

  async #readRecords(workspaceId: string): Promise<{ records: CreatorStoredEvent[]; events: CreatorEvent[]; view?: CreatorView }> {
    let text: string;
    try {
      text = await readFile(this.pathFor(workspaceId), "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { records: [], events: [] };
      throw error;
    }
    const records = text.split("\n").filter(Boolean).map((line) => {
      const record: unknown = JSON.parse(line);
      validateCreatorStoredEvent(record);
      return record;
    });
    const events = records.map((record) => record.event);
    return records.length ? { records, events, view: replayCreatorWorkspace(records) } : { records, events };
  }

  async readAs(workspaceId: string, principal: RuntimePrincipal): Promise<{ records: CreatorStoredEvent[]; events: CreatorEvent[]; view?: CreatorView }> {
    createCreatorCapabilityGate(principal).require("context.read_private");
    return this.#readRecords(workspaceId);
  }

  async read(workspaceId: string): Promise<{ records: CreatorStoredEvent[]; events: CreatorEvent[]; view?: CreatorView }> {
    return this.readAs(workspaceId, this.principal);
  }

  async append(event: CreatorEvent): Promise<CreatorView> {
    return this.appendAs(event, this.principal);
  }

  async appendAs(event: CreatorEvent, principal: RuntimePrincipal): Promise<CreatorView> {
    validateCreatorAppendEvent(event);
    const capability = creatorCapabilityForEvent(event);
    const gate = createCreatorCapabilityGate(principal);
    gate.require("context.read_private");
    gate.require(capability);
    const path = this.pathFor(event.workspace_id);
    await mkdir(dirname(path), { recursive: true });
    return withJsonlLock(path, `creator workspace ${event.workspace_id}`, async () => {
      const current = await this.#readRecords(event.workspace_id);
      const identicalIndex = current.events.findIndex((item) => item.event_id === event.event_id);
      const identical = identicalIndex === -1 ? undefined : current.events[identicalIndex];
      if (identical) {
        if (canonicalJson(identical) !== canonicalJson(event)) throw new Error(`event_id content conflict: ${event.event_id}`);
        const committedBy = current.records[identicalIndex]?.committed_by;
        if (!committedBy
          || committedBy.principal_id !== principal.principal_id
          || committedBy.product !== principal.product
          || committedBy.environment !== principal.environment
          || committedBy.capability !== capability) {
          throw new Error(`event_id principal conflict: ${event.event_id}`);
        }
        if (!current.view) throw new Error("stored event did not create a creator workspace");
        return current.view;
      }
      const next = applyCreatorEvent(current.view, event, principal);
      const record = recordCreatorEvent(event, principal);
      const body = [...current.records, record].map(canonicalJson).join("\n") + "\n";
      const tempPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
      const temp = await open(tempPath, "wx");
      try {
        try {
          await temp.writeFile(body, "utf8");
          await temp.sync();
        } finally {
          await temp.close();
        }
        await rename(tempPath, path);
      } catch (error) {
        await unlink(tempPath).catch(() => undefined);
        throw error;
      }
      const directory = await open(dirname(path), "r");
      try { await directory.sync(); } finally { await directory.close(); }
      return next;
    });
  }
}
