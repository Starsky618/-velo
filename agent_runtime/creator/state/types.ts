export const CLAIM_TEMPORALITIES = ["permanent", "slow_changing", "temporary"] as const;
export const EVAL_VERDICTS = ["pass", "fail", "needs_more_evidence"] as const;
export const RIGHTS_DECISIONS = ["allowed", "forbidden", "needs_review"] as const;
export const CONFLICT_RESULTS = ["clear", "conflicting", "needs_more_evidence"] as const;
export const CREATOR_SOURCE_ROLES = ["user", "assistant", "tool", "system", "external_material"] as const;
export const CREATOR_ACTORS = ["tim", "creator_agent", "rider", "external", "mixed", "unknown"] as const;
export const AUTHORSHIP_BASES = ["direct_unquoted_message", "manual_review", "system_generated", "external_attribution", "unknown"] as const;
export const JUDGMENT_RESPONSES = ["tim_confirmed", "rejected"] as const;
export const CONTRADICTION_RESOLUTIONS = ["dismissed", "superseded", "needs_more_evidence"] as const;
export type ClaimTemporality = (typeof CLAIM_TEMPORALITIES)[number];
export type EvalVerdict = (typeof EVAL_VERDICTS)[number];
export type RightsDecision = (typeof RIGHTS_DECISIONS)[number];
export type ConflictResult = (typeof CONFLICT_RESULTS)[number];
export type CreatorSourceRole = (typeof CREATOR_SOURCE_ROLES)[number];
export type CreatorActor = (typeof CREATOR_ACTORS)[number];
export type AuthorshipBasis = (typeof AUTHORSHIP_BASES)[number];
export type JudgmentResponse = (typeof JUDGMENT_RESPONSES)[number];
export type ContradictionResolution = (typeof CONTRADICTION_RESOLUTIONS)[number];
export type CreatorScalar = string | number | boolean;

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
  source_kind: "conversation" | "rider_report" | "provider" | "manual_research" | "repository";
  content_hash: string;
  /** Content-addressed blob, provider revision, or immutable upstream message-stream revision. */
  immutable_ref: string;
  provenance_ref: string;
}

export interface JudgmentResponseInteraction {
  kind: "judgment_response";
  proposal_id: string;
  statement_hash: string;
  response: JudgmentResponse;
}

export interface ConversationTurnRecorded extends BaseCreatorEvent {
  type: "creator.conversation_turn_recorded";
  turn_id: string;
  source_ref: string;
  source_message_ref: string;
  source_role: CreatorSourceRole;
  actor: CreatorActor;
  authorship_basis: AuthorshipBasis;
  raw_text: string;
  content_hash: string;
  subject_refs: string[];
  interaction?: JudgmentResponseInteraction;
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

export interface JudgmentProposed extends BaseCreatorEvent {
  type: "creator.judgment_proposed";
  proposal_id: string;
  judgment_key: string;
  subject_ref: string;
  statement: string;
  statement_hash: string;
  typed_value: CreatorScalar;
  temporality: ClaimTemporality;
  context_compiler_version: string;
  context_request_hash: string;
  context_task: string;
  context_subject_refs: string[];
  context_as_of: string;
  context_max_pending_turns: number;
  context_max_evidence: number;
  context_hash: string;
  model_ref: string;
  review_at?: string;
  source_turn_refs: string[];
  evidence_refs: string[];
  supersedes_judgment_id?: string;
  reason: string;
}

export interface JudgmentResponded extends BaseCreatorEvent {
  type: "creator.judgment_responded";
  decision_id: string;
  proposal_id: string;
  response_turn_ref: string;
  response: JudgmentResponse;
  expected_statement_hash: string;
}

export interface JudgmentContradictionRecorded extends BaseCreatorEvent {
  type: "creator.judgment_contradiction_recorded";
  contradiction_id: string;
  judgment_id: string;
  contradicting_ref: string;
  reason: string;
}

export interface JudgmentContradictionResolved extends BaseCreatorEvent {
  type: "creator.judgment_contradiction_resolved";
  resolution_id: string;
  contradiction_id: string;
  resolution: ContradictionResolution;
  resolution_ref: string;
  reason: string;
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
  | ConversationTurnRecorded
  | RightsChecked
  | EvidenceRecorded
  | ClaimProposed
  | JudgmentProposed
  | JudgmentResponded
  | JudgmentContradictionRecorded
  | JudgmentContradictionResolved
  | ConflictAnalyzed
  | EvalRecorded
  | HumanReviewRequested
  | WorldChangeProposed;

export interface CreatorJudgmentState {
  id: string;
  judgment_key: string;
  subject_ref: string;
  statement: string;
  statement_hash: string;
  typed_value: CreatorScalar;
  temporality: ClaimTemporality;
  context_compiler_version: string;
  context_request_hash: string;
  context_task: string;
  context_subject_refs: string[];
  context_as_of: string;
  context_max_pending_turns: number;
  context_max_evidence: number;
  context_hash: string;
  model_ref: string;
  review_at?: string;
  status: "proposed" | JudgmentResponse;
  source_turn_refs: string[];
  evidence_refs: string[];
  supersedes_judgment_id?: string;
  reason: string;
  superseded: boolean;
  proposed_at: string;
  responded_at?: string;
  decision_id?: string;
}

export interface CreatorContradictionState {
  id: string;
  judgment_id: string;
  contradicting_ref: string;
  reason: string;
  recorded_at: string;
  resolved: boolean;
  resolution?: ContradictionResolution;
  resolution_ref?: string;
  resolved_at?: string;
}

export interface CreatorView {
  schema_version: 1;
  workspace_id: string;
  mission: string;
  revision: number;
  last_event_id: string;
  last_occurred_at: string;
  sources: Record<string, SourceIngested>;
  conversation_turns: Record<string, ConversationTurnRecorded>;
  rights_checks: Record<string, RightsChecked>;
  evidence: Record<string, EvidenceRecorded>;
  claims: Record<string, ClaimProposed>;
  judgments: Record<string, CreatorJudgmentState>;
  judgment_decisions: Record<string, JudgmentResponded>;
  judgment_contradictions: Record<string, CreatorContradictionState>;
  judgment_contradiction_resolutions: Record<string, JudgmentContradictionResolved>;
  conflict_analyses: Record<string, ConflictAnalyzed>;
  evaluations: Record<string, EvalRecorded>;
  human_review_requests: Record<string, HumanReviewRequested>;
  world_change_proposals: Record<string, WorldChangeProposed>;
}

export interface CreatorPrincipalReceipt {
  principal_id: string;
  product: "creator";
  environment: "test" | "shadow" | "production";
  capability: string;
}

/**
 * Storage-owned envelope. Callers submit an event plus an authenticated
 * principal; the store creates this receipt after capability authorization.
 */
export interface CreatorStoredEvent {
  event: CreatorEvent;
  committed_by: CreatorPrincipalReceipt;
}
