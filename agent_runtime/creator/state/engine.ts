import { canonicalJson } from "../../shared/canonical.ts";
import { createCreatorCapabilityGate } from "../capabilities.ts";
import { CLAIM_TEMPORALITIES, EVAL_VERDICTS, type CreatorEvent, type CreatorView } from "./types.ts";

const capabilities = createCreatorCapabilityGate();

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a non-empty string`);
}

function requireUtcInstant(value: unknown, label: string): asserts value is string {
  requireString(value, label);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString() !== value) throw new Error(`${label} must be a canonical UTC instant`);
}

function requireRefs(value: unknown, label: string): asserts value is string[] {
  if (!Array.isArray(value) || value.length === 0 || value.some((item) => typeof item !== "string" || item.trim() === "")) {
    throw new Error(`${label} must contain at least one ref`);
  }
}

export function validateCreatorEvent(value: unknown): asserts value is CreatorEvent {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("creator event must be an object");
  const event = value as Record<string, unknown>;
  if (event.schema_version !== 1) throw new Error("unsupported creator event schema_version");
  requireString(event.event_id, "event_id");
  requireString(event.workspace_id, "workspace_id");
  requireUtcInstant(event.occurred_at, "occurred_at");
  if (!Number.isInteger(event.base_revision) || (event.base_revision as number) < 0) throw new Error("base_revision must be non-negative");
  switch (event.type) {
    case "creator.workspace_started":
      requireString(event.mission, "mission");
      return;
    case "creator.source_ingested":
      requireString(event.source_ref, "source_ref");
      requireString(event.source_kind, "source_kind");
      requireString(event.content_hash, "content_hash");
      requireString(event.provenance_ref, "provenance_ref");
      if (!["rider_report", "provider", "manual_research", "repository"].includes(event.source_kind as string)) {
        throw new Error("invalid source_kind");
      }
      return;
    case "creator.evidence_recorded":
      requireString(event.evidence_id, "evidence_id");
      requireString(event.source_ref, "source_ref");
      requireString(event.subject_ref, "subject_ref");
      requireString(event.raw_observation, "raw_observation");
      requireUtcInstant(event.observed_at, "observed_at");
      return;
    case "creator.claim_proposed":
      requireString(event.claim_id, "claim_id");
      requireString(event.subject_ref, "subject_ref");
      requireString(event.predicate, "predicate");
      requireRefs(event.evidence_refs, "evidence_refs");
      if (!CLAIM_TEMPORALITIES.includes(event.temporality as (typeof CLAIM_TEMPORALITIES)[number])) throw new Error("invalid claim temporality");
      if (!["string", "number", "boolean"].includes(typeof event.proposed_value)) throw new Error("invalid proposed_value");
      return;
    case "creator.eval_recorded":
      requireString(event.eval_id, "eval_id");
      requireString(event.claim_id, "claim_id");
      requireString(event.grader_ref, "grader_ref");
      requireString(event.reason, "reason");
      if (!EVAL_VERDICTS.includes(event.verdict as (typeof EVAL_VERDICTS)[number])) throw new Error("invalid eval verdict");
      return;
    case "creator.world_change_proposed":
      requireString(event.proposal_id, "proposal_id");
      requireRefs(event.claim_refs, "claim_refs");
      requireString(event.target_world_revision, "target_world_revision");
      return;
    default:
      throw new Error(`unknown or forbidden creator event type: ${String(event.type)}`);
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
    evidence: {},
    claims: {},
    evaluations: {},
    world_change_proposals: {},
  };
}

export function applyCreatorEvent(view: CreatorView | undefined, event: CreatorEvent): CreatorView {
  validateCreatorEvent(event);
  if (!view) {
    if (event.type !== "creator.workspace_started" || event.base_revision !== 0) throw new Error("first creator event must start a workspace");
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
    case "creator.evidence_recorded":
      capabilities.require("evidence.inspect_raw");
      if (!next.sources[event.source_ref]) throw new Error("evidence requires an ingested source");
      if (next.evidence[event.evidence_id]) throw new Error("duplicate evidence_id");
      next.evidence[event.evidence_id] = event;
      break;
    case "creator.claim_proposed":
      capabilities.require("claim.propose");
      if (event.evidence_refs.some((ref) => !next.evidence[ref])) throw new Error("claim references unknown evidence");
      if (event.evidence_refs.some((ref) => next.evidence[ref]?.subject_ref !== event.subject_ref)) throw new Error("claim evidence belongs to another subject");
      if (next.claims[event.claim_id]) throw new Error("duplicate claim_id");
      next.claims[event.claim_id] = event;
      break;
    case "creator.eval_recorded":
      capabilities.require("eval.run");
      if (!next.claims[event.claim_id]) throw new Error("eval references unknown claim");
      if (next.evaluations[event.eval_id]) throw new Error("duplicate eval_id");
      next.evaluations[event.eval_id] = event;
      break;
    case "creator.world_change_proposed":
      capabilities.require("world_change.propose");
      for (const claimId of event.claim_refs) {
        if (!next.claims[claimId]) throw new Error("world change references unknown claim");
        const evals = Object.values(next.evaluations).filter((evaluation) => evaluation.claim_id === claimId);
        if (!evals.some((evaluation) => evaluation.verdict === "pass")) throw new Error("world change requires a passing eval for every claim");
        if (evals.some((evaluation) => evaluation.verdict === "fail")) throw new Error("world change cannot contain a failed claim");
      }
      if (next.world_change_proposals[event.proposal_id]) throw new Error("duplicate proposal_id");
      next.world_change_proposals[event.proposal_id] = event;
      break;
  }
  return next;
}

export function replayCreatorWorkspace(events: readonly CreatorEvent[]): CreatorView {
  let view: CreatorView | undefined;
  const eventIds = new Map<string, string>();
  for (const event of events) {
    const encoded = canonicalJson(event);
    const previous = eventIds.get(event.event_id);
    if (previous !== undefined) {
      if (previous !== encoded) throw new Error(`event_id content conflict: ${event.event_id}`);
      continue;
    }
    eventIds.set(event.event_id, encoded);
    view = applyCreatorEvent(view, event);
  }
  if (!view) throw new Error("creator workspace has no events");
  return view;
}
