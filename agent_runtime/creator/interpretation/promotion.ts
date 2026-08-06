import { canonicalJson, contentHash } from "../../shared/canonical.ts";
import type { RuntimePrincipal } from "../../shared/capability-gate.ts";
import { compileCreatorContext, type CreatorContextManifest } from "../context/compiler.ts";
import { replayCreatorWorkspace } from "../state/engine.ts";
import type { CreatorWorkspaceStore } from "../state/store-port.ts";
import type {
  ClaimTemporality,
  CreatorScalar,
  CreatorStoredEvent,
  CreatorView,
  JudgmentPromotionBasis,
  JudgmentPromotionProposed,
} from "../state/types.ts";

export const CREATOR_PROMOTION_ENGINE_VERSION = "creator-promotion-engine-v0";

export interface CreatorPromotionRequest {
  workspace_id: string;
  event_id: string;
  occurred_at: string;
  task: string;
  task_ref: string;
  subject_refs: string[];
  max_pending_turns?: number;
  max_evidence?: number;
  max_interpretations?: number;
  proposal_id: string;
  judgment_key: string;
  subject_ref: string;
  statement: string;
  typed_value: CreatorScalar;
  temporality: ClaimTemporality;
  review_at?: string;
  evidence_refs: string[];
  source_interpretation_refs: string[];
  promotion_basis: JudgmentPromotionBasis;
  promotion_basis_refs: string[];
  supersedes_judgment_id?: string;
  reason: string;
}

function buildPromotionEvent(
  view: CreatorView,
  request: CreatorPromotionRequest,
): { event: JudgmentPromotionProposed; manifest: CreatorContextManifest } {
  const maxInterpretations = request.max_interpretations ?? 20;
  const bundle = compileCreatorContext(view, {
    task: request.task,
    task_ref: request.task_ref,
    subject_refs: request.subject_refs,
    as_of: request.occurred_at,
    max_pending_turns: request.max_pending_turns ?? 20,
    max_evidence: request.max_evidence ?? 30,
    max_interpretations: maxInterpretations,
  });
  const interpretationRefs = [...new Set(request.source_interpretation_refs)].sort();
  if (interpretationRefs.length === 0
    || interpretationRefs.some((ref) => !bundle.manifest.included.interpretation_refs.includes(ref))) {
    throw new Error("Creator promotion requires visible active interpretations from this exact context");
  }
  const sourceTurnRefs = [...new Set(interpretationRefs.map((ref) => view.interpretations[ref]?.turn_id)
    .filter((ref): ref is string => ref !== undefined))].sort();
  return {
    manifest: bundle.manifest,
    event: {
      schema_version: 1,
      event_id: request.event_id,
      workspace_id: request.workspace_id,
      base_revision: view.revision,
      occurred_at: request.occurred_at,
      type: "creator.judgment_promotion_proposed",
      proposal_id: request.proposal_id,
      judgment_key: request.judgment_key,
      subject_ref: request.subject_ref,
      statement: request.statement,
      statement_hash: contentHash(request.statement),
      typed_value: request.typed_value,
      temporality: request.temporality,
      context_compiler_version: bundle.manifest.compiler_version,
      context_request_hash: bundle.manifest.request_hash,
      context_task: request.task,
      context_task_ref: request.task_ref,
      context_subject_refs: [...bundle.context.subject_refs],
      context_as_of: bundle.manifest.request.as_of,
      context_max_pending_turns: bundle.manifest.request.max_pending_turns,
      context_max_evidence: bundle.manifest.request.max_evidence,
      context_max_interpretations: maxInterpretations,
      context_hash: bundle.manifest.context_hash,
      model_ref: CREATOR_PROMOTION_ENGINE_VERSION,
      ...(request.review_at ? { review_at: request.review_at } : {}),
      source_turn_refs: sourceTurnRefs,
      evidence_refs: [...new Set(request.evidence_refs)].sort(),
      source_interpretation_refs: interpretationRefs,
      promotion_basis: request.promotion_basis,
      promotion_basis_refs: [...new Set(request.promotion_basis_refs)].sort(),
      ...(request.supersedes_judgment_id ? { supersedes_judgment_id: request.supersedes_judgment_id } : {}),
      reason: request.reason,
    },
  };
}

export interface CreatorPromotionResult {
  commit_status: "committed" | "reconciled";
  event: JudgmentPromotionProposed;
  context_manifest: CreatorContextManifest;
  committed_revision: number;
}

function exactReceipt(
  record: CreatorStoredEvent | undefined,
  event: JudgmentPromotionProposed,
  principal: RuntimePrincipal,
): boolean {
  return record !== undefined && canonicalJson(record.event) === canonicalJson(event)
    && record.committed_by.principal_id === principal.principal_id
    && record.committed_by.product === principal.product
    && record.committed_by.environment === principal.environment
    && record.committed_by.capability === "judgment.promote";
}

/**
 * Mechanical firewall between model-authored interpretations and Tim-reviewable
 * durable judgments. The reducer independently rechecks every gate.
 */
export class CreatorPromotionEngineV0 {
  readonly #store: CreatorWorkspaceStore;
  readonly #principal: RuntimePrincipal;

  constructor(store: CreatorWorkspaceStore, principal: RuntimePrincipal) {
    this.#store = store;
    this.#principal = principal;
  }

  async propose(request: CreatorPromotionRequest): Promise<CreatorPromotionResult> {
    const current = await this.#store.readAs(request.workspace_id, this.#principal);
    if (!current.view) throw new Error("Creator promotion requires an existing workspace");
    const existingIndex = current.events.findIndex((item) => item.event_id === request.event_id);
    if (existingIndex >= 0) {
      const existing = current.events[existingIndex];
      const priorView = replayCreatorWorkspace(current.records.slice(0, existingIndex));
      const expected = buildPromotionEvent(priorView, request);
      if (!existing || existing.type !== "creator.judgment_promotion_proposed"
        || !exactReceipt(current.records[existingIndex], expected.event, this.#principal)) {
        throw new Error(`Creator promotion event_id conflict: ${request.event_id}`);
      }
      return {
        commit_status: "reconciled", event: existing, context_manifest: expected.manifest,
        committed_revision: existing.base_revision + 1,
      };
    }
    const built = buildPromotionEvent(current.view, request);
    const { event } = built;
    try {
      const receipt = await this.#store.appendAs(event, this.#principal);
      return { commit_status: "committed", event, context_manifest: built.manifest, committed_revision: receipt.revision };
    } catch (error) {
      const recovered = await this.#store.readAs(request.workspace_id, this.#principal);
      const index = recovered.events.findIndex((item) => item.event_id === event.event_id);
      if (index < 0) throw error;
      if (!exactReceipt(recovered.records[index], event, this.#principal)) {
        throw new Error(`Creator promotion event ${event.event_id} has conflicting persisted content`);
      }
      return {
        commit_status: "reconciled", event, context_manifest: built.manifest,
        committed_revision: event.base_revision + 1,
      };
    }
  }
}
