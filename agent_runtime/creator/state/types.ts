export const CLAIM_TEMPORALITIES = ["permanent", "slow_changing", "temporary"] as const;
export const EVAL_VERDICTS = ["pass", "fail", "needs_more_evidence"] as const;
export type ClaimTemporality = (typeof CLAIM_TEMPORALITIES)[number];
export type EvalVerdict = (typeof EVAL_VERDICTS)[number];

interface BaseCreatorEvent {
  schema_version: 1;
  event_id: string;
  workspace_id: string;
  base_revision: number;
  occurred_at: string;
}

export interface CreatorWorkspaceStarted extends BaseCreatorEvent {
  type: "creator.workspace_started";
  mission: string;
}

export interface SourceIngested extends BaseCreatorEvent {
  type: "creator.source_ingested";
  source_ref: string;
  source_kind: "rider_report" | "provider" | "manual_research" | "repository";
  content_hash: string;
  provenance_ref: string;
}

export interface EvidenceRecorded extends BaseCreatorEvent {
  type: "creator.evidence_recorded";
  evidence_id: string;
  source_ref: string;
  subject_ref: string;
  /** Internal exact observation. Never included in the rider context compiler. */
  raw_observation: string;
  observed_at: string;
}

export interface ClaimProposed extends BaseCreatorEvent {
  type: "creator.claim_proposed";
  claim_id: string;
  subject_ref: string;
  predicate: string;
  proposed_value: string | number | boolean;
  temporality: ClaimTemporality;
  evidence_refs: string[];
}

export interface EvalRecorded extends BaseCreatorEvent {
  type: "creator.eval_recorded";
  eval_id: string;
  claim_id: string;
  verdict: EvalVerdict;
  grader_ref: string;
  reason: string;
}

export interface WorldChangeProposed extends BaseCreatorEvent {
  type: "creator.world_change_proposed";
  proposal_id: string;
  claim_refs: string[];
  target_world_revision: string;
}

export type CreatorEvent =
  | CreatorWorkspaceStarted
  | SourceIngested
  | EvidenceRecorded
  | ClaimProposed
  | EvalRecorded
  | WorldChangeProposed;

export interface CreatorView {
  schema_version: 1;
  workspace_id: string;
  mission: string;
  revision: number;
  last_event_id: string;
  last_occurred_at: string;
  sources: Record<string, SourceIngested>;
  evidence: Record<string, EvidenceRecorded>;
  claims: Record<string, ClaimProposed>;
  evaluations: Record<string, EvalRecorded>;
  world_change_proposals: Record<string, WorldChangeProposed>;
}
