import { canonicalJson } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { replayCreatorWorkspace } from "../state/engine.ts";
import type { CreatorWorkspaceStore } from "../state/store-port.ts";
import {
  CREATOR_TASK_STATE_ENGINE_VERSION,
  type CreatorStoredEvent,
  type CreatorTaskStateChanged,
  type CreatorView,
} from "../state/types.ts";

export { CREATOR_TASK_STATE_ENGINE_VERSION } from "../state/types.ts";

export interface CreatorTaskStateUpdateRequest {
  workspace_id: string;
  event_id: string;
  occurred_at: string;
  task_ref: string;
  interpretation_id: string;
}

export interface CreatorTaskStateUpdateResult {
  commit_status: "committed" | "reconciled";
  event: CreatorTaskStateChanged;
  committed_revision: number;
}

function exactReceipt(
  record: CreatorStoredEvent | undefined,
  event: CreatorTaskStateChanged,
  principal: RuntimePrincipal,
): boolean {
  return record !== undefined && canonicalJson(record.event) === canonicalJson(event)
    && record.committed_by.principal_id === principal.principal_id
    && record.committed_by.product === principal.product
    && record.committed_by.environment === principal.environment
    && record.committed_by.capability === "task.update";
}

function buildTaskStateEvent(
  view: CreatorView,
  request: CreatorTaskStateUpdateRequest,
): CreatorTaskStateChanged {
  const interpretation = view.interpretations[request.interpretation_id];
  if (!interpretation || interpretation.superseded || interpretation.task_ref !== request.task_ref
    || interpretation.action_effect !== "change_current_task") {
    throw new Error("Creator task update requires an active change_current_task interpretation in the same task");
  }
  const active = Object.values(view.task_states).find((item) => (
    item.task_ref === request.task_ref && !item.superseded
  ));
  if (!active) throw new Error("Creator task update cannot invent a missing task state");
  if (interpretation.scope_level === "project" && interpretation.scope_ref !== active.project_ref) {
    throw new Error("Creator task update project scope does not match the active task");
  }
  if (["turn", "task"].includes(interpretation.scope_level)
    && interpretation.task_ref !== active.task_ref) {
    throw new Error("Creator task update scope does not match the active task");
  }
  return {
    schema_version: 1,
    event_id: request.event_id,
    workspace_id: request.workspace_id,
    base_revision: view.revision,
    occurred_at: request.occurred_at,
    type: "creator.task_state_changed",
    task_state_id: `task-state:${request.event_id}`,
    task_ref: active.task_ref,
    project_ref: active.project_ref,
    status: active.status,
    objective: active.objective,
    focus: interpretation.claim,
    acceptance_criteria: [...active.acceptance_criteria],
    open_loops: [...active.open_loops],
    source_turn_refs: [...new Set([...active.source_turn_refs, interpretation.turn_id])].sort(),
    supersedes_task_state_id: active.task_state_id,
    source_interpretation_ref: interpretation.interpretation_id,
    engine_ref: CREATOR_TASK_STATE_ENGINE_VERSION,
  };
}

/**
 * Mechanical executor for a model-authored `change_current_task` candidate.
 * It changes only the active task focus; it cannot invent a task, project,
 * acceptance criteria, status, or durable judgment.
 */
export class CreatorTaskStateEngineV0 {
  readonly #store: CreatorWorkspaceStore;
  readonly #principal: RuntimePrincipal;

  constructor(store: CreatorWorkspaceStore, principal: RuntimePrincipal) {
    this.#store = store;
    this.#principal = principal;
  }

  async apply(request: CreatorTaskStateUpdateRequest): Promise<CreatorTaskStateUpdateResult> {
    const current = await this.#store.readAs(request.workspace_id, this.#principal);
    if (!current.view) throw new Error("Creator task update requires an existing workspace");
    const existingIndex = current.events.findIndex((item) => item.event_id === request.event_id);
    if (existingIndex >= 0) {
      const existing = current.events[existingIndex];
      const priorView = replayCreatorWorkspace(current.records.slice(0, existingIndex));
      const expected = buildTaskStateEvent(priorView, request);
      if (!existing || existing.type !== "creator.task_state_changed"
        || !exactReceipt(current.records[existingIndex], expected, this.#principal)) {
        throw new Error(`Creator task update event_id conflict: ${request.event_id}`);
      }
      return {
        commit_status: "reconciled",
        event: existing,
        committed_revision: existing.base_revision + 1,
      };
    }
    const event = buildTaskStateEvent(current.view, request);
    try {
      const receipt = await this.#store.appendAs(event, this.#principal);
      return { commit_status: "committed", event, committed_revision: receipt.revision };
    } catch (error) {
      const recovered = await this.#store.readAs(request.workspace_id, this.#principal);
      const index = recovered.events.findIndex((item) => item.event_id === event.event_id);
      if (index < 0) throw error;
      if (!exactReceipt(recovered.records[index], event, this.#principal)) {
        throw new Error(`Creator task update event ${event.event_id} has conflicting persisted content`);
      }
      return { commit_status: "reconciled", event, committed_revision: event.base_revision + 1 };
    }
  }
}
