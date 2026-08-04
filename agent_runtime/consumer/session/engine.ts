import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";

import { canonicalJson } from "../../shared/canonical.ts";
import {
  AUTHORSHIP_BASES,
  DECISION_STATUSES,
  SESSION_STATUSES,
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

const DIRECT_USER_AUTHORSHIP = new Set(["direct_unquoted_message", "manual_review"]);

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
      requireString(event.mission, "mission");
      requireString(event.mainline_topic_id, "mainline_topic_id");
      return;
    case "turn.recorded":
      requireString(event.turn_id, "turn_id");
      requireString(event.topic_id, "topic_id");
      requireString(event.content, "content");
      if (!includes(TURN_ROLES, event.role)) throw new Error("invalid turn role");
      if (!includes(SOURCE_ROLES, event.source_role)) throw new Error("invalid source_role");
      if (!includes(AUTHORSHIP_BASES, event.authorship_basis)) throw new Error("invalid authorship_basis");
      return;
    case "topic.opened":
      requireString(event.topic_id, "topic_id");
      requireString(event.title, "title");
      if (!includes(TOPIC_KINDS, event.kind)) throw new Error("invalid topic kind");
      if (event.parent_topic_id !== undefined) requireString(event.parent_topic_id, "parent_topic_id");
      return;
    case "topic.transitioned":
      requireString(event.topic_id, "topic_id");
      if (!includes(TOPIC_STATUSES, event.status)) throw new Error("invalid topic status");
      return;
    case "decision.recorded":
      requireString(event.decision_id, "decision_id");
      requireString(event.topic_id, "topic_id");
      requireString(event.decision_key, "decision_key");
      requireString(event.statement, "statement");
      requireStringArray(event.source_turn_refs, "source_turn_refs");
      if (event.source_turn_refs.length === 0) throw new Error("a decision needs source_turn_refs");
      if (!includes(DECISION_STATUSES, event.status)) throw new Error("invalid decision status");
      if (event.supersedes_decision_id !== undefined) requireString(event.supersedes_decision_id, "supersedes_decision_id");
      return;
    case "session.status_changed":
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
  };
}

function findTurn(view: SessionView, turnId: string): ConversationTurn {
  const turn = view.turns.find((item) => item.id === turnId);
  if (!turn) throw new Error(`decision references unknown turn: ${turnId}`);
  return turn;
}

function assertConfirmedByRider(view: SessionView, event: Extract<RiderSessionEvent, { type: "decision.recorded" }>): void {
  if (event.status === "proposed") return;
  const hasDirectRiderSource = event.source_turn_refs
    .map((turnId) => findTurn(view, turnId))
    .some((turn) => turn.source_role === "user" && DIRECT_USER_AUTHORSHIP.has(turn.authorship_basis));
  if (!hasDirectRiderSource) {
    throw new Error(`${event.status} decision requires a direct rider turn`);
  }
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

  const next: SessionView = structuredClone(view);
  next.revision += 1;
  next.last_event_id = event.event_id;
  next.last_occurred_at = event.occurred_at;

  switch (event.type) {
    case "turn.recorded": {
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
      topic.status = event.status;
      break;
    }
    case "decision.recorded": {
      if (!next.topics[event.topic_id]) throw new Error(`unknown topic: ${event.topic_id}`);
      if (next.decisions[event.decision_id]) throw new Error(`duplicate decision_id: ${event.decision_id}`);
      event.source_turn_refs.forEach((turnId) => findTurn(next, turnId));
      assertConfirmedByRider(next, event);
      const active = Object.values(next.decisions).find(
        (decision) => decision.decision_key === event.decision_key && !decision.superseded,
      );
      if (active && event.supersedes_decision_id !== active.id) {
        throw new Error(`decision_key already has an active decision: ${event.decision_key}`);
      }
      if (event.supersedes_decision_id) {
        const previous = next.decisions[event.supersedes_decision_id];
        if (!previous || previous.superseded) throw new Error("superseded decision is not active");
        if (previous.decision_key !== event.decision_key) throw new Error("cannot supersede a different decision_key");
        if (previous.status === "user_confirmed" && event.status !== "user_confirmed") {
          throw new Error("a confirmed rider decision can only be replaced by another confirmed rider decision");
        }
        previous.superseded = true;
      }
      const decision: SessionDecision = {
        id: event.decision_id,
        topic_id: event.topic_id,
        decision_key: event.decision_key,
        statement: event.statement,
        status: event.status,
        source_turn_refs: [...event.source_turn_refs],
        ...(event.supersedes_decision_id ? { supersedes_decision_id: event.supersedes_decision_id } : {}),
        superseded: false,
        recorded_at: event.occurred_at,
      };
      next.decisions[decision.id] = decision;
      break;
    }
    case "session.status_changed":
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

  async append(event: RiderSessionEvent): Promise<SessionView> {
    const path = this.pathFor(event.session_id);
    await mkdir(dirname(path), { recursive: true });
    const lockPath = `${path}.lock`;
    const lock = await open(lockPath, "wx").catch((error: NodeJS.ErrnoException) => {
      if (error.code === "EEXIST") throw new Error(`session is locked: ${event.session_id}`);
      throw error;
    });
    try {
      const current = await this.read(event.session_id);
      const identical = current.events.find((item) => item.event_id === event.event_id);
      if (identical) {
        if (canonicalJson(identical) !== canonicalJson(event)) throw new Error(`event_id content conflict: ${event.event_id}`);
        if (!current.view) throw new Error("stored event did not create a session");
        return current.view;
      }
      const next = applySessionEvent(current.view, event);
      const body = [...current.events, event].map(canonicalJson).join("\n") + "\n";
      const tempPath = `${path}.${process.pid}.tmp`;
      const temp = await open(tempPath, "wx");
      try {
        await temp.writeFile(body, "utf8");
        await temp.sync();
      } finally {
        await temp.close();
      }
      await rename(tempPath, path);
      return next;
    } finally {
      await lock.close();
      await unlink(lockPath).catch(() => undefined);
    }
  }
}
