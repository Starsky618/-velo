export const CLAIM_TEMPORALITIES = ["permanent", "slow_changing", "temporary"] as const;
export const EVAL_VERDICTS = ["pass", "fail", "needs_more_evidence"] as const;
export const RIGHTS_DECISIONS = ["allowed", "forbidden", "needs_review"] as const;
export const CONFLICT_RESULTS = ["clear", "conflicting", "needs_more_evidence"] as const;
export const CREATOR_SOURCE_ROLES = ["user", "assistant", "tool", "system", "external_material"] as const;
export const CREATOR_ACTORS = ["tim", "creator_agent", "rider", "external", "mixed", "unknown"] as const;
export const AUTHORSHIP_BASES = ["direct_unquoted_message", "manual_review", "system_generated", "external_attribution", "unknown"] as const;
export const JUDGMENT_RESPONSES = ["tim_confirmed", "rejected"] as const;
export const CONTRADICTION_RESOLUTIONS = ["dismissed", "superseded", "needs_more_evidence"] as const;
export const INTERPRETATION_SPEECH_ACTS = [
  "observation", "correction", "preference", "instruction", "decision", "question",
  "hypothesis", "emotion", "external_quote",
] as const;
export const INTERPRETATION_EPISTEMIC_STATUSES = ["explicit", "inferred", "ambiguous", "hypothetical", "unknown"] as const;
export const INTERPRETATION_SCOPE_LEVELS = ["turn", "task", "project", "cross_project", "global"] as const;
export const INTERPRETATION_PERSISTENCE_INTENTS = ["ephemeral", "task_local", "provisional", "durable_explicit", "unknown"] as const;
export const INTERPRETATION_ANNOTATION_BASES = ["direct_language", "agent_inference", "mechanical"] as const;
export const INTERPRETATION_ACTION_EFFECTS = [
  "none", "inform_context", "change_current_task", "candidate_for_promotion", "request_clarification",
] as const;
export const INTERPRETATION_RELATION_KINDS = ["supports", "contradicts", "refines", "supersedes"] as const;
export const JUDGMENT_PROMOTION_BASES = [
  "durable_explicit", "repeated_independent_tasks", "validated_outcome", "high_cost_failure",
] as const;
export const CREATOR_TASK_STATUSES = ["active", "blocked", "completed"] as const;
export const CREATOR_TASK_STATE_ENGINE_VERSION = "creator-task-state-engine-v0" as const;
export const CREATOR_CALIBRATION_METRICS = [
  "first_understanding", "repeat_correction", "overpromotion", "missed_recall", "conflict_challenge", "context_usefulness",
] as const;
export const CREATOR_CALIBRATION_AUTHORITIES = ["agent_assessed", "tim_confirmed", "mechanical", "real_world"] as const;
export type ClaimTemporality = (typeof CLAIM_TEMPORALITIES)[number];
export type EvalVerdict = (typeof EVAL_VERDICTS)[number];
export type RightsDecision = (typeof RIGHTS_DECISIONS)[number];
export type ConflictResult = (typeof CONFLICT_RESULTS)[number];
export type CreatorSourceRole = (typeof CREATOR_SOURCE_ROLES)[number];
export type CreatorActor = (typeof CREATOR_ACTORS)[number];
export type AuthorshipBasis = (typeof AUTHORSHIP_BASES)[number];
export type JudgmentResponse = (typeof JUDGMENT_RESPONSES)[number];
export type ContradictionResolution = (typeof CONTRADICTION_RESOLUTIONS)[number];
export type InterpretationSpeechAct = (typeof INTERPRETATION_SPEECH_ACTS)[number];
export type InterpretationEpistemicStatus = (typeof INTERPRETATION_EPISTEMIC_STATUSES)[number];
export type InterpretationScopeLevel = (typeof INTERPRETATION_SCOPE_LEVELS)[number];
export type InterpretationPersistenceIntent = (typeof INTERPRETATION_PERSISTENCE_INTENTS)[number];
export type InterpretationAnnotationBasis = (typeof INTERPRETATION_ANNOTATION_BASES)[number];
export type InterpretationActionEffect = (typeof INTERPRETATION_ACTION_EFFECTS)[number];
export type InterpretationRelationKind = (typeof INTERPRETATION_RELATION_KINDS)[number];
export type JudgmentPromotionBasis = (typeof JUDGMENT_PROMOTION_BASES)[number];
export type CreatorTaskStatus = (typeof CREATOR_TASK_STATUSES)[number];
export type CreatorCalibrationMetric = (typeof CREATOR_CALIBRATION_METRICS)[number];
export type CreatorCalibrationAuthority = (typeof CREATOR_CALIBRATION_AUTHORITIES)[number];
export type CreatorScalar = string | number | boolean;

interface BaseCreatorEvent {
  schema_version: 1 | 2;
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

export interface InterpretationAlternative {
  claim: string;
  disconfirming_evidence: string;
}

export interface InterpretationRelation {
  target_ref: string;
  kind: InterpretationRelationKind;
  reason: string;
}

/**
 * A model-authored reading of one immutable turn. It is deliberately not a
 * fact, instruction, judgment, or Tim-authored statement.
 */
export interface TurnInterpretationProposed extends BaseCreatorEvent {
  type: "creator.turn_interpretation_proposed";
  interpretation_id: string;
  turn_id: string;
  task_ref: string;
  subject_refs: string[];
  speech_acts: InterpretationSpeechAct[];
  epistemic_status: InterpretationEpistemicStatus;
  scope_level: InterpretationScopeLevel;
  scope_ref: string;
  persistence_intent: InterpretationPersistenceIntent;
  annotation_basis: InterpretationAnnotationBasis;
  claim: string;
  confidence: number;
  alternatives: InterpretationAlternative[];
  supporting_refs: string[];
  counterevidence_refs: string[];
  relations: InterpretationRelation[];
  action_effect: InterpretationActionEffect;
  review_when: string;
  context_compiler_version: string;
  context_request_hash: string;
  context_task: string;
  context_subject_refs: string[];
  context_as_of: string;
  context_max_pending_turns: number;
  context_max_evidence: number;
  context_max_interpretations: number;
  context_hash: string;
  model_ref: string;
  supersedes_interpretation_id?: string;
}

/** Task-local execution truth. This can steer the active run but is not a durable belief about Tim. */
export interface CreatorTaskStateChanged extends BaseCreatorEvent {
  type: "creator.task_state_changed";
  task_state_id: string;
  task_ref: string;
  project_ref: string;
  status: CreatorTaskStatus;
  objective: string;
  focus: string;
  acceptance_criteria: string[];
  open_loops: string[];
  source_turn_refs: string[];
  supersedes_task_state_id?: string;
  /** Present only for a mechanical focus update; absent on the initial Tim-grounded task state. */
  source_interpretation_ref?: string;
  /** Fixed identity lets every reducer/storage boundary re-run the mechanical update contract. */
  engine_ref?: typeof CREATOR_TASK_STATE_ENGINE_VERSION;
}

export interface CreatorBehaviorCalibrationRecorded extends BaseCreatorEvent {
  type: "creator.behavior_calibration_recorded";
  calibration_id: string;
  task_ref: string;
  metric: CreatorCalibrationMetric;
  verdict: EvalVerdict;
  authority: CreatorCalibrationAuthority;
  prediction: string;
  observed_result: string;
  context_hash: string;
  context_item_refs: string[];
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

/** New guarded path. schema v1 judgments remain replayable; schema v2 compatibility judgments are evidence-only. */
export type JudgmentPromotionProposed = Omit<JudgmentProposed, "type"> & {
  type: "creator.judgment_promotion_proposed";
  context_task_ref: string;
  context_max_interpretations: number;
  source_interpretation_refs: string[];
  promotion_basis: JudgmentPromotionBasis;
  promotion_basis_refs: string[];
};

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
  | TurnInterpretationProposed
  | CreatorTaskStateChanged
  | CreatorBehaviorCalibrationRecorded
  | ClaimProposed
  | JudgmentProposed
  | JudgmentPromotionProposed
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
  context_task_ref?: string;
  context_max_interpretations?: number;
  context_hash: string;
  model_ref: string;
  proposal_event_type: "creator.judgment_proposed" | "creator.judgment_promotion_proposed";
  source_interpretation_refs?: string[];
  promotion_basis?: JudgmentPromotionBasis;
  promotion_basis_refs?: string[];
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

export interface CreatorInterpretationState extends TurnInterpretationProposed {
  superseded: boolean;
}

export interface CreatorTaskState extends CreatorTaskStateChanged {
  superseded: boolean;
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
  interpretations: Record<string, CreatorInterpretationState>;
  task_states: Record<string, CreatorTaskState>;
  behavior_calibrations: Record<string, CreatorBehaviorCalibrationRecorded>;
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
