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

export type TurnRole = (typeof TURN_ROLES)[number];
export type SourceRole = (typeof SOURCE_ROLES)[number];
export type AuthorshipBasis = (typeof AUTHORSHIP_BASES)[number];
export type TopicKind = (typeof TOPIC_KINDS)[number];
export type TopicStatus = (typeof TOPIC_STATUSES)[number];
export type DecisionStatus = (typeof DECISION_STATUSES)[number];
export type SessionStatus = (typeof SESSION_STATUSES)[number];

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

export interface DecisionRecordedEvent extends BaseSessionEvent {
  type: "decision.recorded";
  decision_id: string;
  decision_key: string;
  topic_id: string;
  statement: string;
  status: DecisionStatus;
  source_turn_refs: string[];
  supersedes_decision_id?: string;
}

export interface SessionStatusChangedEvent extends BaseSessionEvent {
  type: "session.status_changed";
  status: SessionStatus;
}

export type RiderSessionEvent =
  | SessionStartedEvent
  | TurnRecordedEvent
  | TopicOpenedEvent
  | TopicTransitionedEvent
  | DecisionRecordedEvent
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
}

export interface SessionDecision {
  id: string;
  topic_id: string;
  decision_key: string;
  statement: string;
  status: DecisionStatus;
  source_turn_refs: string[];
  supersedes_decision_id?: string;
  superseded: boolean;
  recorded_at: string;
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
}
