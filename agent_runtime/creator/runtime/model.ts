import type { CreatorContextBundle } from "../context/compiler.ts";
import { assertNonEmptyString, assertRecord } from "../../shared/canonical.ts";
import { CLAIM_TEMPORALITIES, type ClaimTemporality, type CreatorScalar } from "../state/types.ts";

export interface CreatorProposeJudgmentAction {
  type: "propose_judgment";
  proposal_id: string;
  judgment_key: string;
  subject_ref: string;
  statement: string;
  typed_value: CreatorScalar;
  temporality: ClaimTemporality;
  review_at?: string;
  source_turn_refs: string[];
  evidence_refs: string[];
  supersedes_judgment_id?: string;
  reason: string;
}

export interface CreatorNoAction {
  type: "no_action";
  reason: string;
}

export type CreatorModelAction = CreatorProposeJudgmentAction | CreatorNoAction;

export interface CreatorDecisionModel {
  readonly model_ref: string;
  decide(bundle: CreatorContextBundle, signal?: AbortSignal): Promise<CreatorModelAction>;
}

function exactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) throw new Error(`${label} has unknown fields: ${unknown.join(", ")}`);
}

function assertUnicodeScalarString(value: unknown, label: string): asserts value is string {
  assertNonEmptyString(value, label);
  assertUnicodeScalarValue(value, label);
}

function assertUnicodeScalarValue(value: string, label: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error(`${label} must contain only Unicode scalar values`);
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new Error(`${label} must contain only Unicode scalar values`);
    }
  }
}

function stringArray(value: unknown, label: string): asserts value is string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be a string array`);
  }
  for (const item of value) assertUnicodeScalarString(item, label);
}

function exactJsonNumber(value: number, label: string): void {
  if (!Number.isFinite(value)) throw new Error(`${label} must be finite`);
  if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
    throw new Error(`${label} must be within the JavaScript safe integer range`);
  }
}

export function validateCreatorModelAction(value: unknown): asserts value is CreatorModelAction {
  assertRecord(value, "Creator model action");
  if (value.type === "no_action") {
    exactKeys(value, ["type", "reason"], "Creator no_action");
    assertUnicodeScalarString(value.reason, "reason");
    return;
  }
  if (value.type !== "propose_judgment") throw new Error("unknown Creator model action type");
  exactKeys(value, ["type", "proposal_id", "judgment_key", "subject_ref", "statement", "typed_value", "temporality", "review_at", "source_turn_refs", "evidence_refs", "supersedes_judgment_id", "reason"], "Creator propose_judgment");
  for (const field of ["proposal_id", "judgment_key", "subject_ref", "statement", "reason"] as const) {
    assertUnicodeScalarString(value[field], field);
  }
  if (!["string", "number", "boolean"].includes(typeof value.typed_value)) throw new Error("invalid Creator typed_value");
  if (typeof value.typed_value === "string") assertUnicodeScalarValue(value.typed_value, "Creator typed_value");
  if (typeof value.typed_value === "number") exactJsonNumber(value.typed_value, "Creator typed_value");
  if (!CLAIM_TEMPORALITIES.includes(value.temporality as never)) throw new Error("invalid Creator judgment temporality");
  stringArray(value.source_turn_refs, "source_turn_refs");
  stringArray(value.evidence_refs, "evidence_refs");
  if (new Set(value.source_turn_refs).size !== value.source_turn_refs.length) throw new Error("source_turn_refs must be unique");
  if (new Set(value.evidence_refs).size !== value.evidence_refs.length) throw new Error("evidence_refs must be unique");
  if (value.source_turn_refs.length + value.evidence_refs.length === 0) throw new Error("Creator judgment needs a source turn or evidence");
  if (value.review_at !== undefined) assertUnicodeScalarString(value.review_at, "review_at");
  if (value.supersedes_judgment_id !== undefined) assertUnicodeScalarString(value.supersedes_judgment_id, "supersedes_judgment_id");
}

export interface CreatorShadowRule {
  when: {
    evidence_ref?: string;
    active_judgment_id?: string;
    no_active_judgment_key?: string;
  };
  action: CreatorModelAction;
}

/**
 * Deterministic fake model for the local Creator loop. Rules inspect only the
 * compiled context, so a fresh process with the same event log chooses the same
 * typed action. Replacing this port with an LLM must not change reducer gates.
 */
export class DeterministicCreatorShadowModel implements CreatorDecisionModel {
  readonly model_ref: string;
  readonly #rules: readonly CreatorShadowRule[];

  constructor(modelRef: string, rules: readonly CreatorShadowRule[]) {
    if (modelRef.trim() === "") throw new Error("model_ref must be non-empty");
    this.model_ref = modelRef;
    this.#rules = rules;
  }

  async decide(bundle: CreatorContextBundle, signal?: AbortSignal): Promise<CreatorModelAction> {
    signal?.throwIfAborted();
    const context = bundle.context;
    for (const rule of this.#rules) {
      const matchesEvidence = rule.when.evidence_ref === undefined
        || context.relevant_evidence.some((item) => item.evidence_id === rule.when.evidence_ref);
      const matchesActive = rule.when.active_judgment_id === undefined
        || context.current_judgments.some((item) => item.id === rule.when.active_judgment_id);
      const matchesMissingKey = rule.when.no_active_judgment_key === undefined
        || !context.current_judgments.some((item) => item.judgment_key === rule.when.no_active_judgment_key);
      if (matchesEvidence && matchesActive && matchesMissingKey) {
        const action: unknown = structuredClone(rule.action);
        validateCreatorModelAction(action);
        return action;
      }
    }
    return { type: "no_action", reason: "No deterministic Creator shadow rule matched the compiled context." };
  }
}
