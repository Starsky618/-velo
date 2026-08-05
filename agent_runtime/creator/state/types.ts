export const CLAIM_TEMPORALITIES = ["permanent", "slow_changing", "temporary"] as const;
export const EVAL_VERDICTS = ["pass", "fail", "needs_more_evidence"] as const;
export const RIGHTS_DECISIONS = ["allowed", "forbidden", "needs_review"] as const;
export const CONFLICT_RESULTS = ["clear", "conflicting", "needs_more_evidence"] as const;
export type ClaimTemporality = (typeof CLAIM_TEMPORALITIES)[number];
export type EvalVerdict = (typeof EVAL_VERDICTS)[number];
export type RightsDecision = (typeof RIGHTS_DECISIONS)[number];
export type ConflictResult = (typeof CONFLICT_RESULTS)[number];

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

export interface RightsChecked extends BaseCreatorEvent {
  type: "creator.rights_checked";
  rights_check_id: string;
  source_ref: string;
  decision: RightsDecision;
  policy_ref: string;
  reason: string;
}

export interface ClaimProposed extends BaseCreatorEvent {
  type: "creator.claim_proposed";
  claim_id: string;
  subject_ref: string;
  predicate: string;
  proposed_value: string | number | boolean;
  temporality: ClaimTemporality;
  valid_from?: string;
  valid_to?: string;
  review_at?: string;
  evidence_refs: string[];
}

export interface ConflictAnalyzed extends BaseCreatorEvent {
  type: "creator.conflict_analyzed";
  analysis_id: string;
  claim_id: string;
  result: ConflictResult;
  conflicting_claim_refs: string[];
  reason: string;
}

export interface HumanReviewRequested extends BaseCreatorEvent {
  type: "creator.human_review_requested";
  review_id: string;
  target_ref: string;
  request_kind: "rights_review" | "conflict_review" | "request_more_evidence";
  reason: string;
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
  | RightsChecked
  | EvidenceRecorded
  | ClaimProposed
  | ConflictAnalyzed
  | EvalRecorded
  | HumanReviewRequested
  | WorldChangeProposed;

export interface CreatorView {
  schema_version: 1;
  workspace_id: string;
  mission: string;
  revision: number;
  last_event_id: string;
  last_occurred_at: string;
  sources: Record<string, SourceIngested>;
  rights_checks: Record<string, RightsChecked>;
  evidence: Record<string, EvidenceRecorded>;
  claims: Record<string, ClaimProposed>;
  conflict_analyses: Record<string, ConflictAnalyzed>;
  evaluations: Record<string, EvalRecorded>;
  human_review_requests: Record<string, HumanReviewRequested>;
  world_change_proposals: Record<string, WorldChangeProposed>;
}
