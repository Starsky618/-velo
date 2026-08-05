export const TURN_ROLES = ["user", "agent", "system", "tool", "map"] as const;
export const SOURCE_ROLES = ["user", "agent", "system", "tool", "map"] as const;
export const AUTHORSHIP_BASES = [
  "direct_unquoted_message",
  "manual_review",
  "agent_generated",
  "system_generated",
  "tool_observation",
  "map_interaction",
] as const;
export const TOPIC_KINDS = ["mainline", "branch"] as const;
export const TOPIC_STATUSES = ["open", "in_progress", "deferred", "resolved", "dropped"] as const;
export const DECISION_STATUSES = ["proposed", "user_confirmed", "rejected"] as const;
export const SESSION_STATUSES = ["open", "resolved", "expired", "cancelled"] as const;
export const SESSION_UNKNOWN_KINDS = ["intent", "location", "world_data", "plan_feasibility", "user_choice", "session_consistency"] as const;

export type TurnRole = (typeof TURN_ROLES)[number];
export type SourceRole = (typeof SOURCE_ROLES)[number];
export type AuthorshipBasis = (typeof AUTHORSHIP_BASES)[number];
export type TopicKind = (typeof TOPIC_KINDS)[number];
export type TopicStatus = (typeof TOPIC_STATUSES)[number];
export type DecisionStatus = (typeof DECISION_STATUSES)[number];
export type SessionStatus = (typeof SESSION_STATUSES)[number];
export type SessionUnknownKind = (typeof SESSION_UNKNOWN_KINDS)[number];

interface BaseSessionEvent {
  schema_version: 1;
  event_id: string;
  session_id: string;
  base_revision: number;
  occurred_at: string;
}

export interface SessionStartedEvent extends BaseSessionEvent {
  type: "session.started";
  mission: string;
  mainline_topic_id: string;
}

export interface TurnRecordedEvent extends BaseSessionEvent {
  type: "turn.recorded";
  turn_id: string;
  topic_id: string;
  role: TurnRole;
  source_role: SourceRole;
  authorship_basis: AuthorshipBasis;
  /** Exact text, never a model-generated paraphrase of the rider's statement. */
  content: string;
  /** A typed UI action. Free-form prose is never interpreted as a decision response. */
  interaction?: {
    kind: "decision_response";
    decision_id: string;
    statement_hash: string;
    response: "user_confirmed" | "rejected";
  };
}

export interface TopicOpenedEvent extends BaseSessionEvent {
  type: "topic.opened";
  topic_id: string;
  parent_topic_id?: string;
  title: string;
  kind: TopicKind;
}

export interface TopicTransitionedEvent extends BaseSessionEvent {
  type: "topic.transitioned";
  topic_id: string;
  status: TopicStatus;
}

export interface DecisionProposedEvent extends BaseSessionEvent {
  type: "decision.proposed";
  decision_id: string;
  decision_key: string;
  topic_id: string;
  statement: string;
  typed_value: string | number | boolean;
  source_turn_refs: string[];
  supersedes_decision_id?: string;
}

export interface DecisionRespondedEvent extends BaseSessionEvent {
  type: "decision.responded";
  decision_id: string;
  response_turn_id: string;
  response: "user_confirmed" | "rejected";
  expected_statement_hash: string;
}

export interface SessionStatusChangedEvent extends BaseSessionEvent {
  type: "session.status_changed";
  status: SessionStatus;
}

export interface SessionUnknownRecordedEvent extends BaseSessionEvent {
  type: "unknown.recorded";
  unknown_id: string;
  unknown_kind: SessionUnknownKind;
  blocking: boolean;
  user_safe_summary: string;
  related_ref?: string;
}

export type RiderSessionEvent =
  | SessionStartedEvent
  | TurnRecordedEvent
  | TopicOpenedEvent
  | TopicTransitionedEvent
  | DecisionProposedEvent
  | DecisionRespondedEvent
  | SessionUnknownRecordedEvent
  | SessionStatusChangedEvent;

export interface DiscussionTopic {
  id: string;
  title: string;
  kind: TopicKind;
  status: TopicStatus;
  parent_topic_id?: string;
  opened_at: string;
}

export interface ConversationTurn {
  id: string;
  topic_id: string;
  role: TurnRole;
  source_role: SourceRole;
  authorship_basis: AuthorshipBasis;
  content: string;
  occurred_at: string;
  interaction?: TurnRecordedEvent["interaction"];
}

export interface SessionDecision {
  id: string;
  topic_id: string;
  decision_key: string;
  statement: string;
  typed_value: string | number | boolean;
  status: DecisionStatus;
  source_turn_refs: string[];
  supersedes_decision_id?: string;
  superseded: boolean;
  recorded_at: string;
  responded_at?: string;
}

export interface SessionUnknown {
  unknown_id: string;
  unknown_kind: SessionUnknownKind;
  blocking: boolean;
  user_safe_summary: string;
  related_ref?: string;
}

export interface SessionView {
  schema_version: 1;
  session_id: string;
  mission: string;
  status: SessionStatus;
  revision: number;
  last_event_id: string;
  last_occurred_at: string;
  mainline_topic_id: string;
  topics: Record<string, DiscussionTopic>;
  turns: ConversationTurn[];
  decisions: Record<string, SessionDecision>;
  unknowns: SessionUnknown[];
}
