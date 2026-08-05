import { contentHash } from "../../shared/canonical.ts";
import { applySessionEvent } from "./engine.ts";
import type { SessionUnknown, SessionView } from "./types.ts";

export type SessionCommitResult =
  | { commit_status: "committed"; expected_base_revision: number; committed_revision: number }
  | { commit_status: "rejected_stale" | "reconciliation_required"; expected_base_revision: number };

export type SessionPreparationResult =
  | { preparation_status: "available"; expected_base_revision: number; current_revision: number; created: boolean }
  | { preparation_status: "rejected_stale"; expected_base_revision: number };

export interface SessionCommitGuard {
  signal: AbortSignal;
  /** Must be called at the last reversible point before the reducer/store mutation. */
  assertCanCommit: () => void;
}

export interface SessionRuntimePort {
  readView(): Promise<SessionView>;
  ensureUnknown(unknown: SessionUnknown, expectedBaseRevision: number, guard: SessionCommitGuard): Promise<SessionPreparationResult>;
  commitAgentTurn(content: string, expectedBaseRevision: number, guard: SessionCommitGuard): Promise<SessionCommitResult>;
}

export class SessionCommitReconciliationRequiredError extends Error {
  constructor(message = "session commit outcome requires reconciliation") {
    super(message);
    this.name = "SessionCommitReconciliationRequiredError";
  }
}

function nextOccurredAt(view: SessionView): string {
  return new Date(Math.max(Date.now(), new Date(view.last_occurred_at).valueOf())).toISOString();
}

/** Real reducer-backed, in-memory Session port for isolated Shadow tests and emitters. */
export function createInMemorySessionRuntimePort(initialView: SessionView): SessionRuntimePort {
  let view = structuredClone(initialView);
  const guardMutation = (guard: SessionCommitGuard): void => {
    guard.signal.throwIfAborted();
    guard.assertCanCommit();
  };
  return {
    async readView() {
      return structuredClone(view);
    },
    async ensureUnknown(unknown, expectedBaseRevision, guard) {
      if (view.revision !== expectedBaseRevision) {
        return { preparation_status: "rejected_stale", expected_base_revision: expectedBaseRevision };
      }
      const existing = view.unknowns.find((item) => item.unknown_id === unknown.unknown_id);
      if (existing) {
        if (contentHash(existing) !== contentHash(unknown)) throw new Error(`unknown_id content conflict: ${unknown.unknown_id}`);
        return {
          preparation_status: "available", expected_base_revision: expectedBaseRevision,
          current_revision: view.revision, created: false,
        };
      }
      guardMutation(guard);
      view = applySessionEvent(view, {
        schema_version: 1,
        event_id: `shadow-unknown-${contentHash({ unknown, expectedBaseRevision }).slice(-24)}`,
        session_id: view.session_id,
        base_revision: expectedBaseRevision,
        occurred_at: nextOccurredAt(view),
        type: "unknown.recorded",
        ...structuredClone(unknown),
      });
      return {
        preparation_status: "available",
        expected_base_revision: expectedBaseRevision,
        current_revision: view.revision,
        created: true,
      };
    },
    async commitAgentTurn(content, expectedBaseRevision, guard) {
      if (view.revision !== expectedBaseRevision) {
        return { commit_status: "rejected_stale", expected_base_revision: expectedBaseRevision };
      }
      guardMutation(guard);
      view = applySessionEvent(view, {
        schema_version: 1,
        event_id: `shadow-commit-${contentHash({ content, expectedBaseRevision }).slice(-24)}`,
        session_id: view.session_id,
        base_revision: expectedBaseRevision,
        occurred_at: nextOccurredAt(view),
        type: "turn.recorded",
        turn_id: `shadow-turn-${contentHash({ content, expectedBaseRevision }).slice(-24)}`,
        topic_id: view.mainline_topic_id,
        role: "agent",
        source_role: "agent",
        authorship_basis: "agent_generated",
        content,
      });
      return {
        commit_status: "committed",
        expected_base_revision: expectedBaseRevision,
        committed_revision: view.revision,
      };
    },
  };
}
