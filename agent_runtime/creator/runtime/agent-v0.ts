import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { creatorCapabilityForEventType } from "../capabilities.ts";
import { compileCreatorContext, type CreatorContextManifest, type CreatorContextRequest } from "../context/compiler.ts";
import {
  EventTruthCreatorContextCompiler,
  type CreatorContextCompilerPort,
} from "../context/projection-guard.ts";
import { replayCreatorWorkspace } from "../state/engine.ts";
import type { CreatorWorkspaceStore } from "../state/store-port.ts";
import type { CreatorEvent, CreatorStoredEvent, JudgmentProposed } from "../state/types.ts";
import { validateCreatorModelAction, type CreatorDecisionModel, type CreatorModelAction } from "./model.ts";

export interface CreatorRunRequest extends CreatorContextRequest {
  workspace_id: string;
  event_id: string;
  occurred_at: string;
  signal?: AbortSignal;
}

export interface CreatorRunResult {
  commit_status: "no_action" | "committed" | "reconciled";
  action: CreatorModelAction;
  context_manifest: CreatorContextManifest;
  committed_event_id?: string;
  committed_revision: number;
}

export class CreatorCommitReconciliationRequiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CreatorCommitReconciliationRequiredError";
  }
}

function actionFromProposal(event: JudgmentProposed): CreatorModelAction {
  return {
    type: "propose_judgment",
    proposal_id: event.proposal_id,
    judgment_key: event.judgment_key,
    subject_ref: event.subject_ref,
    statement: event.statement,
    typed_value: event.typed_value,
    temporality: event.temporality,
    ...(event.review_at ? { review_at: event.review_at } : {}),
    source_turn_refs: [...event.source_turn_refs],
    evidence_refs: [...event.evidence_refs],
    ...(event.supersedes_judgment_id ? { supersedes_judgment_id: event.supersedes_judgment_id } : {}),
    reason: event.reason,
  };
}

function receiptMatchesPrincipal(
  record: CreatorStoredEvent | undefined,
  event: CreatorEvent,
  principal: RuntimePrincipal,
): boolean {
  return record !== undefined
    && canonicalJson(record.event) === canonicalJson(event)
    && record.committed_by.principal_id === principal.principal_id
    && record.committed_by.product === principal.product
    && record.committed_by.environment === principal.environment
    && record.committed_by.capability === creatorCapabilityForEventType(event.type);
}

export class CreatorAgentV0 {
  readonly #store: CreatorWorkspaceStore;
  readonly #principal: RuntimePrincipal;
  readonly #model: CreatorDecisionModel;
  readonly #contextCompiler: CreatorContextCompilerPort;

  constructor(
    store: CreatorWorkspaceStore,
    principal: RuntimePrincipal,
    model: CreatorDecisionModel,
    contextCompiler: CreatorContextCompilerPort = new EventTruthCreatorContextCompiler(),
  ) {
    this.#store = store;
    this.#principal = principal;
    this.#model = model;
    this.#contextCompiler = contextCompiler;
  }

  async run(request: CreatorRunRequest): Promise<CreatorRunResult> {
    request.signal?.throwIfAborted();
    const current = await this.#store.readAs(request.workspace_id, this.#principal);
    if (!current.view) throw new Error("Creator run requires an existing workspace");
    const contextRequest: CreatorContextRequest = {
      task: request.task,
      subject_refs: request.subject_refs,
      as_of: request.occurred_at,
      ...(request.max_pending_turns === undefined ? {} : { max_pending_turns: request.max_pending_turns }),
      ...(request.max_evidence === undefined ? {} : { max_evidence: request.max_evidence }),
    };
    const existingIndex = current.events.findIndex((event) => event.event_id === request.event_id);
    if (existingIndex >= 0) {
      const existing = current.events[existingIndex];
      if (!existing || existing.type !== "creator.judgment_proposed" || existing.workspace_id !== request.workspace_id
        || existing.occurred_at !== request.occurred_at || existing.model_ref !== this.#model.model_ref) {
        throw new Error(`Creator run event_id content conflict: ${request.event_id}`);
      }
      if (!receiptMatchesPrincipal(current.records[existingIndex], existing, this.#principal)) {
        throw new CreatorCommitReconciliationRequiredError(
          `Creator run event ${request.event_id} was committed by a different authenticated principal`,
        );
      }
      const priorView = replayCreatorWorkspace(current.records.slice(0, existingIndex));
      const priorBundle = compileCreatorContext(priorView, contextRequest);
      if (existing.context_request_hash !== priorBundle.manifest.request_hash
        || existing.context_hash !== priorBundle.manifest.context_hash
        || existing.context_compiler_version !== priorBundle.manifest.compiler_version) {
        throw new Error(`Creator run event_id context conflict: ${request.event_id}`);
      }
      return {
        commit_status: "reconciled",
        action: actionFromProposal(existing),
        context_manifest: priorBundle.manifest,
        committed_event_id: existing.event_id,
        committed_revision: existing.base_revision + 1,
      };
    }
    const bundle = await this.#contextCompiler.compile(current, contextRequest, this.#principal, this.#store);
    const action: unknown = await this.#model.decide(bundle, request.signal);
    validateCreatorModelAction(action);
    request.signal?.throwIfAborted();
    if (action.type === "no_action") {
      return { commit_status: "no_action", action, context_manifest: bundle.manifest, committed_revision: current.view.revision };
    }
    const visibleTurnRefs = new Set([
      ...bundle.manifest.included.turn_refs,
      ...bundle.manifest.included.judgment_source_turn_refs,
    ]);
    const visibleEvidenceRefs = new Set(bundle.manifest.included.evidence_refs);
    if (action.source_turn_refs.some((ref) => !visibleTurnRefs.has(ref))) {
      throw new Error("Creator model referenced a source turn outside the compiled context");
    }
    if (action.evidence_refs.some((ref) => !visibleEvidenceRefs.has(ref))) {
      throw new Error("Creator model referenced evidence outside the compiled context");
    }
    const visibleSubjects = new Set([
      ...bundle.context.subject_refs,
      ...bundle.context.pending_input_turns.flatMap((turn) => turn.subject_refs),
      ...bundle.context.relevant_evidence.map((evidence) => evidence.subject_ref),
      ...bundle.context.current_judgments.map((judgment) => judgment.subject_ref),
      ...bundle.context.pending_judgment_proposals.map((judgment) => judgment.subject_ref),
    ]);
    if (!visibleSubjects.has(action.subject_ref)) {
      throw new Error("Creator model referenced a subject outside the compiled context");
    }
    if (action.supersedes_judgment_id
      && !bundle.context.current_judgments.some((judgment) => judgment.id === action.supersedes_judgment_id)) {
      throw new Error("Creator model supersedes a judgment outside the compiled context");
    }
    const event: CreatorEvent = {
      schema_version: 1,
      event_id: request.event_id,
      workspace_id: request.workspace_id,
      base_revision: current.view.revision,
      occurred_at: request.occurred_at,
      type: "creator.judgment_proposed",
      proposal_id: action.proposal_id,
      judgment_key: action.judgment_key,
      subject_ref: action.subject_ref,
      statement: action.statement,
      statement_hash: contentHash(action.statement),
      typed_value: action.typed_value,
      temporality: action.temporality,
      context_compiler_version: bundle.manifest.compiler_version,
      context_request_hash: bundle.manifest.request_hash,
      context_task: request.task,
      context_subject_refs: [...bundle.context.subject_refs],
      context_as_of: bundle.manifest.request.as_of,
      context_max_pending_turns: bundle.manifest.request.max_pending_turns,
      context_max_evidence: bundle.manifest.request.max_evidence,
      context_hash: bundle.manifest.context_hash,
      model_ref: this.#model.model_ref,
      ...(action.review_at ? { review_at: action.review_at } : {}),
      source_turn_refs: [...action.source_turn_refs],
      evidence_refs: [...action.evidence_refs],
      ...(action.supersedes_judgment_id ? { supersedes_judgment_id: action.supersedes_judgment_id } : {}),
      reason: action.reason,
    };
    let committedRevision: number;
    let commitStatus: "committed" | "reconciled" = "committed";
    try {
      const committed = await this.#store.appendAs(event, this.#principal);
      committedRevision = committed.revision;
    } catch (error) {
      let recovered;
      try {
        recovered = await this.#store.readAs(request.workspace_id, this.#principal);
      } catch (reconciliationError) {
        throw new CreatorCommitReconciliationRequiredError(
          `Creator commit failed and read-after-error reconciliation also failed: ${reconciliationError instanceof Error ? reconciliationError.message : String(reconciliationError)}`,
        );
      }
      const persistedRecords = recovered.records.filter((item) => item.event.event_id === event.event_id);
      if (persistedRecords.length === 0) throw error;
      if (persistedRecords.length !== 1 || !receiptMatchesPrincipal(persistedRecords[0], event, this.#principal) || !recovered.view) {
        throw new CreatorCommitReconciliationRequiredError(`Creator event ${event.event_id} has conflicting persisted content`);
      }
      committedRevision = event.base_revision + 1;
      commitStatus = "reconciled";
    }
    return {
      commit_status: commitStatus,
      action,
      context_manifest: bundle.manifest,
      committed_event_id: event.event_id,
      committed_revision: committedRevision,
    };
  }
}
