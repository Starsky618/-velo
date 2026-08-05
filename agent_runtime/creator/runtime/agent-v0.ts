import { contentHash } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { compileCreatorContext, type CreatorContextManifest, type CreatorContextRequest } from "../context/compiler.ts";
import type { CreatorWorkspaceStore } from "../state/store-port.ts";
import type { CreatorEvent } from "../state/types.ts";
import { validateCreatorModelAction, type CreatorDecisionModel, type CreatorModelAction } from "./model.ts";

export interface CreatorRunRequest extends CreatorContextRequest {
  workspace_id: string;
  event_id: string;
  occurred_at: string;
  signal?: AbortSignal;
}

export interface CreatorRunResult {
  action: CreatorModelAction;
  context_manifest: CreatorContextManifest;
  committed_event_id?: string;
  committed_revision: number;
}

export class CreatorAgentV0 {
  readonly #store: CreatorWorkspaceStore;
  readonly #principal: RuntimePrincipal;
  readonly #model: CreatorDecisionModel;

  constructor(store: CreatorWorkspaceStore, principal: RuntimePrincipal, model: CreatorDecisionModel) {
    this.#store = store;
    this.#principal = principal;
    this.#model = model;
  }

  async run(request: CreatorRunRequest): Promise<CreatorRunResult> {
    request.signal?.throwIfAborted();
    const current = await this.#store.read(request.workspace_id);
    if (!current.view) throw new Error("Creator run requires an existing workspace");
    const bundle = compileCreatorContext(current.view, request);
    const action: unknown = await this.#model.decide(bundle, request.signal);
    validateCreatorModelAction(action);
    request.signal?.throwIfAborted();
    if (action.type === "no_action") {
      return { action, context_manifest: bundle.manifest, committed_revision: current.view.revision };
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
    const committed = await this.#store.appendAs(event, this.#principal);
    return {
      action,
      context_manifest: bundle.manifest,
      committed_event_id: event.event_id,
      committed_revision: committed.revision,
    };
  }
}
