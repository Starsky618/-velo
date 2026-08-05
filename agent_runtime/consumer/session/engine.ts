import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";

import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import { withJsonlLock } from "../../shared/jsonl-lock.ts";
import {
  AUTHORSHIP_BASES,
  SESSION_STATUSES,
  SESSION_UNKNOWN_KINDS,
  SOURCE_ROLES,
  TOPIC_KINDS,
  TOPIC_STATUSES,
  TURN_ROLES,
  type ConversationTurn,
  type DiscussionTopic,
  type RiderSessionEvent,
  type SessionDecision,
  type SessionView,
} from "./types.ts";

const LEGAL_TURN_PROVENANCE = {
  user: { source_role: "user", authorship: new Set(["direct_unquoted_message", "manual_review"]) },
  agent: { source_role: "agent", authorship: new Set(["agent_generated"]) },
  system: { source_role: "system", authorship: new Set(["system_generated"]) },
  tool: { source_role: "tool", authorship: new Set(["tool_observation"]) },
  map: { source_role: "map", authorship: new Set(["map_interaction"]) },
} as const;
const TOPIC_TRANSITIONS: Readonly<Record<string, ReadonlySet<string>>> = {
  open: new Set(["in_progress", "deferred", "resolved", "dropped"]),
  in_progress: new Set(["deferred", "resolved", "dropped"]),
  deferred: new Set(["in_progress", "resolved", "dropped"]),
  resolved: new Set(),
  dropped: new Set(),
};
const SESSION_TRANSITIONS: Readonly<Record<string, ReadonlySet<string>>> = {
  open: new Set(["resolved", "expired", "cancelled"]),
  resolved: new Set(),
  expired: new Set(),
  cancelled: new Set(),
};

function includes<const T extends readonly string[]>(values: T, value: unknown): value is T[number] {
  return typeof value === "string" && values.includes(value as T[number]);
}

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} must be a non-empty string`);
}

function requireUtcInstant(value: unknown, label: string): asserts value is string {
  requireString(value, label);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString() !== value) {
    throw new Error(`${label} must be a canonical UTC instant`);
  }
}

function requireStringArray(value: unknown, label: string): asserts value is string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) {
    throw new Error(`${label} must be a string array`);
  }
}

function requireExactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const allowedSet = new Set(allowed);
  const extras = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (extras.length) throw new Error(`${label} has unknown fields: ${extras.join(", ")}`);
}

const BASE_EVENT_KEYS = ["schema_version", "event_id", "session_id", "base_revision", "occurred_at", "type"] as const;

export function validateSessionEvent(value: unknown): asserts value is RiderSessionEvent {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("event must be an object");
  const event = value as Record<string, unknown>;
  if (event.schema_version !== 1) throw new Error("unsupported session event schema_version");
  requireString(event.event_id, "event_id");
  requireString(event.session_id, "session_id");
  requireUtcInstant(event.occurred_at, "occurred_at");
  if (!Number.isInteger(event.base_revision) || (event.base_revision as number) < 0) throw new Error("base_revision must be a non-negative integer");
  requireString(event.type, "type");

  switch (event.type) {
    case "session.started":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "mission", "mainline_topic_id"], event.type);
      requireString(event.mission, "mission");
      requireString(event.mainline_topic_id, "mainline_topic_id");
      return;
    case "turn.recorded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "turn_id", "topic_id", "role", "source_role", "authorship_basis", "content", "interaction"], event.type);
      requireString(event.turn_id, "turn_id");
      requireString(event.topic_id, "topic_id");
      requireString(event.content, "content");
      if (!includes(TURN_ROLES, event.role)) throw new Error("invalid turn role");
      if (!includes(SOURCE_ROLES, event.source_role)) throw new Error("invalid source_role");
      if (!includes(AUTHORSHIP_BASES, event.authorship_basis)) throw new Error("invalid authorship_basis");
      if (event.interaction !== undefined) {
        const interaction = event.interaction as Record<string, unknown>;
        requireExactKeys(interaction, ["kind", "decision_id", "statement_hash", "response"], "turn interaction");
        if (interaction.kind !== "decision_response") throw new Error("invalid turn interaction kind");
        requireString(interaction.decision_id, "interaction.decision_id");
        requireString(interaction.statement_hash, "interaction.statement_hash");
        if (!includes(["user_confirmed", "rejected"] as const, interaction.response)) throw new Error("invalid decision response");
      }
      return;
    case "topic.opened":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "topic_id", "parent_topic_id", "title", "kind"], event.type);
      requireString(event.topic_id, "topic_id");
      requireString(event.title, "title");
      if (!includes(TOPIC_KINDS, event.kind)) throw new Error("invalid topic kind");
      if (event.parent_topic_id !== undefined) requireString(event.parent_topic_id, "parent_topic_id");
      return;
    case "topic.transitioned":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "topic_id", "status"], event.type);
      requireString(event.topic_id, "topic_id");
      if (!includes(TOPIC_STATUSES, event.status)) throw new Error("invalid topic status");
      return;
    case "decision.proposed":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "decision_id", "decision_key", "topic_id", "statement", "typed_value", "source_turn_refs", "supersedes_decision_id"], event.type);
      requireString(event.decision_id, "decision_id");
      requireString(event.topic_id, "topic_id");
      requireString(event.decision_key, "decision_key");
      requireString(event.statement, "statement");
      if (!['string', 'number', 'boolean'].includes(typeof event.typed_value)) throw new Error("invalid typed_value");
      requireStringArray(event.source_turn_refs, "source_turn_refs");
      if (event.source_turn_refs.length === 0) throw new Error("a decision needs source_turn_refs");
      if (event.supersedes_decision_id !== undefined) requireString(event.supersedes_decision_id, "supersedes_decision_id");
      return;
    case "decision.responded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "decision_id", "response_turn_id", "response", "expected_statement_hash"], event.type);
      requireString(event.decision_id, "decision_id");
      requireString(event.response_turn_id, "response_turn_id");
      requireString(event.expected_statement_hash, "expected_statement_hash");
      if (!includes(["user_confirmed", "rejected"] as const, event.response)) throw new Error("invalid decision response");
      return;
    case "unknown.recorded":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "unknown_id", "unknown_kind", "blocking", "user_safe_summary", "related_ref"], event.type);
      requireString(event.unknown_id, "unknown_id");
      if (!includes(SESSION_UNKNOWN_KINDS, event.unknown_kind)) throw new Error("invalid unknown_kind");
      if (typeof event.blocking !== "boolean") throw new Error("blocking must be boolean");
      requireString(event.user_safe_summary, "user_safe_summary");
      if (event.related_ref !== undefined) requireString(event.related_ref, "related_ref");
      return;
    case "session.status_changed":
      requireExactKeys(event, [...BASE_EVENT_KEYS, "status"], event.type);
      if (!includes(SESSION_STATUSES, event.status)) throw new Error("invalid session status");
      return;
    default:
      throw new Error(`unknown session event type: ${String(event.type)}`);
  }
}

function blankView(event: Extract<RiderSessionEvent, { type: "session.started" }>): SessionView {
  const mainline: DiscussionTopic = {
    id: event.mainline_topic_id,
    title: event.mission,
    kind: "mainline",
    status: "in_progress",
    opened_at: event.occurred_at,
  };
  return {
    schema_version: 1,
    session_id: event.session_id,
    mission: event.mission,
    status: "open",
    revision: 1,
    last_event_id: event.event_id,
    last_occurred_at: event.occurred_at,
    mainline_topic_id: event.mainline_topic_id,
    topics: { [mainline.id]: mainline },
    turns: [],
    decisions: {},
    unknowns: [],
  };
}

function findTurn(view: SessionView, turnId: string): ConversationTurn {
  const turn = view.turns.find((item) => item.id === turnId);
  if (!turn) throw new Error(`decision references unknown turn: ${turnId}`);
  return turn;
}

function assertLegalTurnProvenance(event: Extract<RiderSessionEvent, { type: "turn.recorded" }>): void {
  const legal = LEGAL_TURN_PROVENANCE[event.role];
  if (event.source_role !== legal.source_role || !legal.authorship.has(event.authorship_basis as never)) {
    throw new Error(`illegal turn provenance for role ${event.role}`);
  }
  if (event.interaction && event.role !== "user") throw new Error("only a direct rider turn may carry a decision response");
}

export function applySessionEvent(view: SessionView | undefined, event: RiderSessionEvent): SessionView {
  validateSessionEvent(event);
  if (view === undefined) {
    if (event.type !== "session.started" || event.base_revision !== 0) {
      throw new Error("the first event must start the session at revision 0");
    }
    return blankView(event);
  }
  if (event.type === "session.started") throw new Error("session already started");
  if (event.session_id !== view.session_id) throw new Error("session_id mismatch");
  if (event.base_revision !== view.revision) throw new Error(`stale base_revision: expected ${view.revision}`);
  if (event.occurred_at < view.last_occurred_at) throw new Error("occurred_at must be monotonic");
  if (view.status !== "open") throw new Error(`session is terminal: ${view.status}`);

  const next: SessionView = structuredClone(view);
  next.revision += 1;
  next.last_event_id = event.event_id;
  next.last_occurred_at = event.occurred_at;

  switch (event.type) {
    case "turn.recorded": {
      assertLegalTurnProvenance(event);
      if (!next.topics[event.topic_id]) throw new Error(`unknown topic: ${event.topic_id}`);
      if (next.turns.some((turn) => turn.id === event.turn_id)) throw new Error(`duplicate turn_id: ${event.turn_id}`);
      next.turns.push({
        id: event.turn_id,
        topic_id: event.topic_id,
        role: event.role,
        source_role: event.source_role,
        authorship_basis: event.authorship_basis,
        content: event.content,
        occurred_at: event.occurred_at,
        ...(event.interaction ? { interaction: structuredClone(event.interaction) } : {}),
      });
      break;
    }
    case "topic.opened": {
      if (next.topics[event.topic_id]) throw new Error(`duplicate topic_id: ${event.topic_id}`);
      if (event.kind === "mainline") throw new Error("a session can only have one mainline");
      if (!event.parent_topic_id || !next.topics[event.parent_topic_id]) throw new Error("a branch needs an existing parent topic");
      next.topics[event.topic_id] = {
        id: event.topic_id,
        title: event.title,
        kind: event.kind,
        status: "open",
        parent_topic_id: event.parent_topic_id,
        opened_at: event.occurred_at,
      };
      break;
    }
    case "topic.transitioned": {
      const topic = next.topics[event.topic_id];
      if (!topic) throw new Error(`unknown topic: ${event.topic_id}`);
      if (!TOPIC_TRANSITIONS[topic.status]?.has(event.status)) {
        throw new Error(`invalid topic transition: ${topic.status} -> ${event.status}`);
      }
      topic.status = event.status;
      break;
    }
    case "decision.proposed": {
      if (!next.topics[event.topic_id]) throw new Error(`unknown topic: ${event.topic_id}`);
      if (next.decisions[event.decision_id]) throw new Error(`duplicate decision_id: ${event.decision_id}`);
      event.source_turn_refs.forEach((turnId) => findTurn(next, turnId));
      const pending = Object.values(next.decisions).find(
        (decision) => decision.decision_key === event.decision_key && !decision.superseded && decision.status === "proposed",
      );
      if (pending) throw new Error(`decision_key already has a pending proposal: ${event.decision_key}`);
      const active = Object.values(next.decisions).find(
        (decision) => decision.decision_key === event.decision_key && !decision.superseded && decision.status === "user_confirmed",
      );
      if (active && event.supersedes_decision_id !== active.id) {
        throw new Error(`decision_key already has an active decision: ${event.decision_key}`);
      }
      if (event.supersedes_decision_id) {
        const previous = next.decisions[event.supersedes_decision_id];
        if (!previous || previous.superseded) throw new Error("superseded decision is not active");
        if (previous.decision_key !== event.decision_key) throw new Error("cannot supersede a different decision_key");
      }
      const decision: SessionDecision = {
        id: event.decision_id,
        topic_id: event.topic_id,
        decision_key: event.decision_key,
        statement: event.statement,
        typed_value: event.typed_value,
        status: "proposed",
        source_turn_refs: [...event.source_turn_refs],
        ...(event.supersedes_decision_id ? { supersedes_decision_id: event.supersedes_decision_id } : {}),
        superseded: false,
        recorded_at: event.occurred_at,
      };
      next.decisions[decision.id] = decision;
      break;
    }
    case "decision.responded": {
      const decision = next.decisions[event.decision_id];
      if (!decision || decision.superseded) throw new Error("decision response requires an active proposal");
      if (decision.status !== "proposed") throw new Error("decision has already been answered");
      const responseTurn = findTurn(next, event.response_turn_id);
      const interaction = responseTurn.interaction;
      const expectedHash = contentHash(decision.statement);
      if (responseTurn.role !== "user" || responseTurn.source_role !== "user"
        || !interaction || interaction.decision_id !== decision.id
        || interaction.statement_hash !== expectedHash
        || interaction.response !== event.response
        || event.expected_statement_hash !== expectedHash) {
        throw new Error("decision response is not bound to this exact proposal and rider turn");
      }
      decision.status = event.response;
      decision.source_turn_refs = [...new Set([...decision.source_turn_refs, responseTurn.id])];
      decision.responded_at = event.occurred_at;
      if (event.response === "user_confirmed" && decision.supersedes_decision_id) {
        next.decisions[decision.supersedes_decision_id]!.superseded = true;
      }
      if (event.response === "rejected") decision.superseded = true;
      break;
    }
    case "unknown.recorded":
      if (next.unknowns.some((unknown) => unknown.unknown_id === event.unknown_id)) {
        throw new Error(`duplicate unknown_id: ${event.unknown_id}`);
      }
      next.unknowns.push({
        unknown_id: event.unknown_id,
        unknown_kind: event.unknown_kind,
        blocking: event.blocking,
        user_safe_summary: event.user_safe_summary,
        ...(event.related_ref ? { related_ref: event.related_ref } : {}),
      });
      break;
    case "session.status_changed":
      if (!SESSION_TRANSITIONS[next.status]?.has(event.status)) {
        throw new Error(`invalid session transition: ${next.status} -> ${event.status}`);
      }
      next.status = event.status;
      break;
  }
  return next;
}

export function replaySession(events: readonly RiderSessionEvent[]): SessionView {
  let view: SessionView | undefined;
  const eventIds = new Map<string, string>();
  for (const event of events) {
    const encoded = canonicalJson(event);
    const previous = eventIds.get(event.event_id);
    if (previous !== undefined) {
      if (previous !== encoded) throw new Error(`event_id content conflict: ${event.event_id}`);
      continue;
    }
    eventIds.set(event.event_id, encoded);
    view = applySessionEvent(view, event);
  }
  if (!view) throw new Error("session has no events");
  return view;
}

export class JsonlSessionStore {
  readonly rootDirectory: string;

  constructor(rootDirectory: string) {
    this.rootDirectory = rootDirectory;
  }

  pathFor(sessionId: string): string {
    if (!/^[a-zA-Z0-9._-]+$/.test(sessionId)) throw new Error("unsafe session_id");
    return join(this.rootDirectory, `${sessionId}.jsonl`);
  }

  async read(sessionId: string): Promise<{ events: RiderSessionEvent[]; view?: SessionView }> {
    const path = this.pathFor(sessionId);
    let text: string;
    try {
      text = await readFile(path, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { events: [] };
      throw error;
    }
    const events = text.split("\n").filter(Boolean).map((line) => {
      const event: unknown = JSON.parse(line);
      validateSessionEvent(event);
      return event;
    });
    return events.length > 0 ? { events, view: replaySession(events) } : { events };
  }

  async append(event: RiderSessionEvent, beforeCommit?: () => void): Promise<SessionView> {
    const path = this.pathFor(event.session_id);
    await mkdir(dirname(path), { recursive: true });
    return withJsonlLock(path, `session ${event.session_id}`, async () => {
      const current = await this.read(event.session_id);
      const identical = current.events.find((item) => item.event_id === event.event_id);
      if (identical) {
        if (canonicalJson(identical) !== canonicalJson(event)) throw new Error(`event_id content conflict: ${event.event_id}`);
        if (!current.view) throw new Error("stored event did not create a session");
        return current.view;
      }
      const next = applySessionEvent(current.view, event);
      const body = [...current.events, event].map(canonicalJson).join("\n") + "\n";
      const tempPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
      const temp = await open(tempPath, "wx");
      try {
        await temp.writeFile(body, "utf8");
        await temp.sync();
      } finally {
        await temp.close();
      }
      try {
        beforeCommit?.();
        await rename(tempPath, path);
      } catch (error) {
        await unlink(tempPath).catch(() => undefined);
        throw error;
      }
      const directory = await open(dirname(path), "r");
      try {
        await directory.sync();
      } finally {
        await directory.close();
      }
      return next;
    });
  }
}
