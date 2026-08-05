import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename } from "node:fs/promises";
import { dirname, join } from "node:path";

import { canonicalJson } from "../../shared/canonical.ts";
import { withJsonlLock } from "../../shared/jsonl-lock.ts";
import { createCreatorCapabilityGate } from "../capabilities.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { CLAIM_TEMPORALITIES, CONFLICT_RESULTS, EVAL_VERDICTS, RIGHTS_DECISIONS, type CreatorEvent, type CreatorView } from "./types.ts";


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

function requireStringArray(value: unknown, label: string): asserts value is string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) throw new Error(`${label} must be a string array`);
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
  if (event.schema_version !== 1) throw new Error("unsupported creator event schema_version");
  requireString(event.event_id, "event_id");
  requireString(event.workspace_id, "workspace_id");
  requireUtcInstant(event.occurred_at, "occurred_at");
  if (!Number.isInteger(event.base_revision) || (event.base_revision as number) < 0) throw new Error("base_revision must be non-negative");
  switch (event.type) {
    case "creator.workspace_started":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "mission"], event.type);
      requireString(event.mission, "mission");
      return;
    case "creator.source_ingested":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "source_ref", "source_kind", "content_hash", "provenance_ref"], event.type);
      requireString(event.source_ref, "source_ref");
      requireString(event.source_kind, "source_kind");
      requireString(event.content_hash, "content_hash");
      requireString(event.provenance_ref, "provenance_ref");
      if (!["rider_report", "provider", "manual_research", "repository"].includes(event.source_kind as string)) {
        throw new Error("invalid source_kind");
      }
      return;
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
    case "creator.claim_proposed":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "claim_id", "subject_ref", "predicate", "proposed_value", "temporality", "valid_from", "valid_to", "review_at", "evidence_refs"], event.type);
      requireString(event.claim_id, "claim_id");
      requireString(event.subject_ref, "subject_ref");
      requireString(event.predicate, "predicate");
      requireRefs(event.evidence_refs, "evidence_refs");
      if (!CLAIM_TEMPORALITIES.includes(event.temporality as (typeof CLAIM_TEMPORALITIES)[number])) throw new Error("invalid claim temporality");
      if (!["string", "number", "boolean"].includes(typeof event.proposed_value)) throw new Error("invalid proposed_value");
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

function initial(event: Extract<CreatorEvent, { type: "creator.workspace_started" }>): CreatorView {
  return {
    schema_version: 1,
    workspace_id: event.workspace_id,
    mission: event.mission,
    revision: 1,
    last_event_id: event.event_id,
    last_occurred_at: event.occurred_at,
    sources: {},
    rights_checks: {},
    evidence: {},
    claims: {},
    conflict_analyses: {},
    evaluations: {},
    human_review_requests: {},
    world_change_proposals: {},
  };
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
    case "creator.claim_proposed":
      capabilities.require("claim.propose");
      if (event.evidence_refs.some((ref) => !next.evidence[ref])) throw new Error("claim references unknown evidence");
      if (event.evidence_refs.some((ref) => next.evidence[ref]?.subject_ref !== event.subject_ref)) throw new Error("claim evidence belongs to another subject");
      if (next.claims[event.claim_id]) throw new Error("duplicate claim_id");
      next.claims[event.claim_id] = event;
      break;
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

export function replayCreatorWorkspace(events: readonly CreatorEvent[], principal: RuntimePrincipal): CreatorView {
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
    view = applyCreatorEvent(view, event, principal);
  }
  if (!view) throw new Error("creator workspace has no events");
  return view;
}

export class JsonlCreatorStore {
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

  async read(workspaceId: string): Promise<{ events: CreatorEvent[]; view?: CreatorView }> {
    let text: string;
    try {
      text = await readFile(this.pathFor(workspaceId), "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { events: [] };
      throw error;
    }
    const events = text.split("\n").filter(Boolean).map((line) => {
      const event: unknown = JSON.parse(line);
      validateCreatorEvent(event);
      return event;
    });
    return events.length ? { events, view: replayCreatorWorkspace(events, this.principal) } : { events };
  }

  async append(event: CreatorEvent): Promise<CreatorView> {
    const path = this.pathFor(event.workspace_id);
    await mkdir(dirname(path), { recursive: true });
    return withJsonlLock(path, `creator workspace ${event.workspace_id}`, async () => {
      const current = await this.read(event.workspace_id);
      const identical = current.events.find((item) => item.event_id === event.event_id);
      if (identical) {
        if (canonicalJson(identical) !== canonicalJson(event)) throw new Error(`event_id content conflict: ${event.event_id}`);
        if (!current.view) throw new Error("stored event did not create a creator workspace");
        return current.view;
      }
      const next = applyCreatorEvent(current.view, event, this.principal);
      const body = [...current.events, event].map(canonicalJson).join("\n") + "\n";
      const tempPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
      const temp = await open(tempPath, "wx");
      try {
        await temp.writeFile(body, "utf8");
        await temp.sync();
      } finally {
        await temp.close();
      }
      await rename(tempPath, path);
      const directory = await open(dirname(path), "r");
      try { await directory.sync(); } finally { await directory.close(); }
      return next;
    });
  }
}
