import { canonicalJson } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { compileCreatorContext, type CreatorContextManifest, type CreatorContextRequest } from "../context/compiler.ts";
import { EventTruthCreatorContextCompiler, type CreatorContextCompilerPort } from "../context/projection-guard.ts";
import { replayCreatorWorkspace } from "../state/engine.ts";
import type { CreatorWorkspaceStore } from "../state/store-port.ts";
import type { CreatorEvent, CreatorStoredEvent, TurnInterpretationProposed } from "../state/types.ts";
import {
  validateCreatorInterpretationModelAction,
  type CreatorInterpretationModel,
  type CreatorInterpretationModelAction,
} from "./model.ts";

export interface CreatorInterpretationRunRequest extends CreatorContextRequest {
  workspace_id: string;
  task_ref: string;
  event_id: string;
  occurred_at: string;
  signal?: AbortSignal;
}

export interface CreatorInterpretationRunResult {
  commit_status: "no_action" | "committed" | "reconciled";
  action: CreatorInterpretationModelAction;
  context_manifest: CreatorContextManifest;
  committed_event_id?: string;
  committed_revision: number;
}

function actionFromEvent(event: TurnInterpretationProposed): CreatorInterpretationModelAction {
  return {
    type: "propose_interpretation",
    interpretation_id: event.interpretation_id,
    source_turn_ref: event.turn_id,
    subject_refs: [...event.subject_refs],
    speech_acts: [...event.speech_acts],
    epistemic_status: event.epistemic_status,
    scope_level: event.scope_level,
    scope_ref: event.scope_ref,
    persistence_intent: event.persistence_intent,
    annotation_basis: event.annotation_basis,
    claim: event.claim,
    confidence: event.confidence,
    alternatives: structuredClone(event.alternatives),
    supporting_refs: [...event.supporting_refs],
    counterevidence_refs: [...event.counterevidence_refs],
    relations: structuredClone(event.relations),
    action_effect: event.action_effect,
    review_when: event.review_when,
    ...(event.supersedes_interpretation_id ? { supersedes_interpretation_id: event.supersedes_interpretation_id } : {}),
  };
}

function exactReceipt(record: CreatorStoredEvent | undefined, event: CreatorEvent, principal: RuntimePrincipal): boolean {
  return record !== undefined && canonicalJson(record.event) === canonicalJson(event)
    && record.committed_by.principal_id === principal.principal_id
    && record.committed_by.product === principal.product
    && record.committed_by.environment === principal.environment
    && record.committed_by.capability === "interpretation.propose";
}

export class CreatorInterpretationAgentV0 {
  readonly #store: CreatorWorkspaceStore;
  readonly #principal: RuntimePrincipal;
  readonly #model: CreatorInterpretationModel;
  readonly #contextCompiler: CreatorContextCompilerPort;

  constructor(
    store: CreatorWorkspaceStore,
    principal: RuntimePrincipal,
    model: CreatorInterpretationModel,
    contextCompiler: CreatorContextCompilerPort = new EventTruthCreatorContextCompiler(),
  ) {
    if (contextCompiler instanceof EventTruthCreatorContextCompiler
      && "readProjectionRecordsAs" in store && typeof store.readProjectionRecordsAs === "function") {
      throw new Error("projection-capable Creator store requires an explicit ProjectionVerifiedCreatorContextCompiler");
    }
    this.#store = store;
    this.#principal = principal;
    this.#model = model;
    this.#contextCompiler = contextCompiler;
  }

  async run(request: CreatorInterpretationRunRequest): Promise<CreatorInterpretationRunResult> {
    request.signal?.throwIfAborted();
    if (request.task_ref.trim() === "") throw new Error("Creator interpretation run requires task_ref");
    const current = await this.#store.readAs(request.workspace_id, this.#principal);
    if (!current.view) throw new Error("Creator interpretation run requires an existing workspace");
    const contextRequest: CreatorContextRequest = {
      task: request.task,
      task_ref: request.task_ref,
      subject_refs: request.subject_refs,
      as_of: request.occurred_at,
      ...(request.max_pending_turns === undefined ? {} : { max_pending_turns: request.max_pending_turns }),
      ...(request.max_evidence === undefined ? {} : { max_evidence: request.max_evidence }),
      max_interpretations: request.max_interpretations ?? 20,
    };
    const existingIndex = current.events.findIndex((item) => item.event_id === request.event_id);
    if (existingIndex >= 0) {
      const existing = current.events[existingIndex];
      if (!existing || existing.type !== "creator.turn_interpretation_proposed"
        || existing.task_ref !== request.task_ref || existing.model_ref !== this.#model.model_ref
        || !exactReceipt(current.records[existingIndex], existing, this.#principal)) {
        throw new Error(`Creator interpretation event_id conflict: ${request.event_id}`);
      }
      const priorView = current.records.slice(0, existingIndex);
      const priorBundle = compileCreatorContext(replayCreatorWorkspace(priorView), contextRequest);
      if (priorBundle.manifest.request_hash !== existing.context_request_hash
        || priorBundle.manifest.context_hash !== existing.context_hash) {
        throw new Error(`Creator interpretation event_id context conflict: ${request.event_id}`);
      }
      return {
        commit_status: "reconciled",
        action: actionFromEvent(existing),
        context_manifest: priorBundle.manifest,
        committed_event_id: existing.event_id,
        committed_revision: existing.base_revision + 1,
      };
    }
    const bundle = await this.#contextCompiler.compile(current, contextRequest, this.#principal, this.#store);
    const action: unknown = await this.#model.interpret(bundle, request.signal);
    validateCreatorInterpretationModelAction(action);
    request.signal?.throwIfAborted();
    if (action.type === "no_action") {
      return { commit_status: "no_action", action, context_manifest: bundle.manifest, committed_revision: current.view.revision };
    }
    if (!bundle.manifest.included.turn_refs.includes(action.source_turn_ref)) {
      throw new Error("Creator interpretation referenced a raw turn outside the compiled context");
    }
    const sourceTurn = current.view.conversation_turns[action.source_turn_ref];
    if (!sourceTurn || canonicalJson([...action.subject_refs].sort()) !== canonicalJson([...sourceTurn.subject_refs].sort())) {
      throw new Error("Creator interpretation must preserve every source turn privacy label");
    }
    const visibleRefs = new Set([
      ...bundle.manifest.included.turn_refs,
      ...bundle.manifest.included.interpretation_source_turn_refs,
      ...bundle.manifest.included.judgment_source_turn_refs,
      ...bundle.manifest.included.evidence_refs,
      ...bundle.manifest.included.judgment_refs,
      ...bundle.manifest.included.proposal_refs,
      ...bundle.manifest.included.interpretation_refs,
    ]);
    if ([...action.supporting_refs, ...action.counterevidence_refs].some((ref) => !visibleRefs.has(ref))) {
      throw new Error("Creator interpretation used evidence outside the compiled context");
    }
    if (action.relations.some((relation) => !visibleRefs.has(relation.target_ref))) {
      throw new Error("Creator interpretation related an item outside the compiled context");
    }
    const event: TurnInterpretationProposed = {
      schema_version: 1,
      event_id: request.event_id,
      workspace_id: request.workspace_id,
      base_revision: current.view.revision,
      occurred_at: request.occurred_at,
      type: "creator.turn_interpretation_proposed",
      interpretation_id: action.interpretation_id,
      turn_id: action.source_turn_ref,
      task_ref: request.task_ref,
      subject_refs: [...action.subject_refs],
      speech_acts: [...action.speech_acts],
      epistemic_status: action.epistemic_status,
      scope_level: action.scope_level,
      scope_ref: action.scope_ref,
      persistence_intent: action.persistence_intent,
      annotation_basis: action.annotation_basis,
      claim: action.claim,
      confidence: action.confidence,
      alternatives: structuredClone(action.alternatives),
      supporting_refs: [...action.supporting_refs],
      counterevidence_refs: [...action.counterevidence_refs],
      relations: structuredClone(action.relations),
      action_effect: action.action_effect,
      review_when: action.review_when,
      context_compiler_version: bundle.manifest.compiler_version,
      context_request_hash: bundle.manifest.request_hash,
      context_task: bundle.manifest.request.task,
      context_subject_refs: [...bundle.manifest.request.subject_refs],
      context_as_of: bundle.manifest.request.as_of,
      context_max_pending_turns: bundle.manifest.request.max_pending_turns,
      context_max_evidence: bundle.manifest.request.max_evidence,
      context_max_interpretations: bundle.manifest.request.max_interpretations ?? 20,
      context_hash: bundle.manifest.context_hash,
      model_ref: this.#model.model_ref,
      ...(action.supersedes_interpretation_id ? { supersedes_interpretation_id: action.supersedes_interpretation_id } : {}),
    };
    try {
      const receipt = await this.#store.appendAs(event, this.#principal);
      return {
        commit_status: "committed", action, context_manifest: bundle.manifest,
        committed_event_id: event.event_id, committed_revision: receipt.revision,
      };
    } catch (error) {
      const recovered = await this.#store.readAs(request.workspace_id, this.#principal);
      const index = recovered.events.findIndex((item) => item.event_id === event.event_id);
      if (index < 0) throw error;
      if (!exactReceipt(recovered.records[index], event, this.#principal)) {
        throw new Error(`Creator interpretation event ${event.event_id} has conflicting persisted content`);
      }
      return {
        commit_status: "reconciled", action, context_manifest: bundle.manifest,
        committed_event_id: event.event_id, committed_revision: event.base_revision + 1,
      };
    }
  }
}
