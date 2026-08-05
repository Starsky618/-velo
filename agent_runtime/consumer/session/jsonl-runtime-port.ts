import { randomUUID } from "node:crypto";

import { canonicalJson } from "../../shared/canonical.ts";
import {
  SessionCommitReconciliationRequiredError,
  type SessionCommitGuard,
  type SessionRuntimePort,
} from "./committer.ts";
import type { RiderSessionEvent, SessionUnknown, SessionView } from "./types.ts";

export interface SessionEventStore {
  read(sessionId: string): Promise<{ events: RiderSessionEvent[]; view?: SessionView }>;
  append(event: RiderSessionEvent, beforeCommit?: () => void): Promise<SessionView>;
}

/**
 * JSONL adapter with exact-event read-after-error reconciliation. A failure
 * after atomic rename is reported as committed when the exact event is
 * visible; an unreadable or conflicting outcome is explicitly escalated.
 */
export class JsonlSessionRuntimePort implements SessionRuntimePort {
  readonly #store: SessionEventStore;
  readonly #sessionId: string;
  readonly #mainlineTopicId: string;

  constructor(store: SessionEventStore, sessionId: string, mainlineTopicId: string) {
    this.#store = store;
    this.#sessionId = sessionId;
    this.#mainlineTopicId = mainlineTopicId;
  }

  async readView(): Promise<SessionView> {
    const latest = await this.#store.read(this.#sessionId);
    if (!latest.view) throw new Error(`session ${this.#sessionId} disappeared`);
    return structuredClone(latest.view);
  }

  async ensureUnknown(unknown: SessionUnknown, expectedBaseRevision: number, guard: SessionCommitGuard) {
    const view = await this.readView();
    if (view.revision !== expectedBaseRevision) {
      return { preparation_status: "rejected_stale" as const, expected_base_revision: expectedBaseRevision };
    }
    const existing = view.unknowns.find((item) => item.unknown_id === unknown.unknown_id);
    if (existing) {
      if (canonicalJson(existing) !== canonicalJson(unknown)) throw new Error(`unknown_id content conflict: ${unknown.unknown_id}`);
      return {
        preparation_status: "available" as const, expected_base_revision: expectedBaseRevision,
        current_revision: view.revision, created: false,
      };
    }
    const committed = await this.#appendWithReconciliation({
      schema_version: 1,
      event_id: randomUUID(),
      session_id: this.#sessionId,
      base_revision: expectedBaseRevision,
      occurred_at: new Date().toISOString(),
      type: "unknown.recorded",
      ...structuredClone(unknown),
    }, guard);
    return {
      preparation_status: "available" as const, expected_base_revision: expectedBaseRevision,
      current_revision: committed.committedRevision, created: true,
    };
  }

  async commitAgentTurn(content: string, expectedBaseRevision: number, guard: SessionCommitGuard) {
    const event: RiderSessionEvent = {
      schema_version: 1,
      event_id: randomUUID(),
      session_id: this.#sessionId,
      base_revision: expectedBaseRevision,
      occurred_at: new Date().toISOString(),
      type: "turn.recorded",
      turn_id: randomUUID(),
      topic_id: this.#mainlineTopicId,
      role: "agent",
      source_role: "agent",
      authorship_basis: "agent_generated",
      content,
    };
    try {
      const committed = await this.#appendWithReconciliation(event, guard);
      return {
        commit_status: "committed" as const, expected_base_revision: expectedBaseRevision,
        committed_revision: committed.committedRevision,
      };
    } catch (error) {
      if (error instanceof Error && error.message.includes("stale base_revision")) {
        return { commit_status: "rejected_stale" as const, expected_base_revision: expectedBaseRevision };
      }
      throw error;
    }
  }

  async #appendWithReconciliation(
    event: RiderSessionEvent,
    guard: SessionCommitGuard,
  ): Promise<{ view: SessionView; committedRevision: number }> {
    try {
      const view = await this.#store.append(event, () => {
        guard.signal.throwIfAborted();
        guard.assertCanCommit();
      });
      return { view, committedRevision: event.base_revision + 1 };
    } catch (error) {
      let recovered: { events: RiderSessionEvent[]; view?: SessionView };
      try {
        recovered = await this.#store.read(this.#sessionId);
      } catch (reconciliationError) {
        throw new SessionCommitReconciliationRequiredError(
          `commit failed and read-after-error reconciliation also failed: ${reconciliationError instanceof Error ? reconciliationError.message : String(reconciliationError)}`,
        );
      }
      const persisted = recovered.events.find((item) => item.event_id === event.event_id);
      if (!persisted) throw error;
      if (canonicalJson(persisted) !== canonicalJson(event) || !recovered.view) {
        throw new SessionCommitReconciliationRequiredError(`event ${event.event_id} has conflicting persisted content`);
      }
      return { view: recovered.view, committedRevision: event.base_revision + 1 };
    }
  }
}
