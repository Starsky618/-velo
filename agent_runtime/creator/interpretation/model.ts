import { assertNonEmptyString, assertRecord } from "../../shared/canonical.ts";
import type { CreatorContextBundle } from "../context/compiler.ts";
import {
  INTERPRETATION_ACTION_EFFECTS,
  INTERPRETATION_ANNOTATION_BASES,
  INTERPRETATION_EPISTEMIC_STATUSES,
  INTERPRETATION_PERSISTENCE_INTENTS,
  INTERPRETATION_RELATION_KINDS,
  INTERPRETATION_SCOPE_LEVELS,
  INTERPRETATION_SPEECH_ACTS,
  type InterpretationActionEffect,
  type InterpretationAlternative,
  type InterpretationAnnotationBasis,
  type InterpretationEpistemicStatus,
  type InterpretationPersistenceIntent,
  type InterpretationRelation,
  type InterpretationScopeLevel,
  type InterpretationSpeechAct,
} from "../state/types.ts";

export interface CreatorProposeInterpretationAction {
  type: "propose_interpretation";
  interpretation_id: string;
  source_turn_ref: string;
  subject_refs: string[];
  speech_acts: InterpretationSpeechAct[];
  epistemic_status: InterpretationEpistemicStatus;
  scope_level: InterpretationScopeLevel;
  scope_ref: string;
  persistence_intent: InterpretationPersistenceIntent;
  annotation_basis: InterpretationAnnotationBasis;
  claim: string;
  confidence: number;
  alternatives: InterpretationAlternative[];
  supporting_refs: string[];
  counterevidence_refs: string[];
  relations: InterpretationRelation[];
  action_effect: InterpretationActionEffect;
  review_when: string;
  supersedes_interpretation_id?: string;
}

export interface CreatorInterpretationNoAction {
  type: "no_action";
  reason: string;
}

export type CreatorInterpretationModelAction = CreatorProposeInterpretationAction | CreatorInterpretationNoAction;

export interface CreatorInterpretationModel {
  readonly model_ref: string;
  interpret(bundle: CreatorContextBundle, signal?: AbortSignal): Promise<CreatorInterpretationModelAction>;
}

function exactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) throw new Error(`${label} has unknown fields: ${unknown.join(", ")}`);
}

function stringArray(value: unknown, label: string, sorted = false): asserts value is string[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be a string array`);
  for (const item of value) assertNonEmptyString(item, label);
  if (new Set(value).size !== value.length) throw new Error(`${label} must be unique`);
  if (sorted && JSON.stringify(value) !== JSON.stringify([...value].sort())) throw new Error(`${label} must be sorted`);
}

export function validateCreatorInterpretationModelAction(value: unknown): asserts value is CreatorInterpretationModelAction {
  assertRecord(value, "Creator interpretation action");
  if (value.type === "no_action") {
    exactKeys(value, ["type", "reason"], "Creator interpretation no_action");
    assertNonEmptyString(value.reason, "reason");
    return;
  }
  if (value.type !== "propose_interpretation") throw new Error("unknown Creator interpretation action type");
  exactKeys(value, [
    "type", "interpretation_id", "source_turn_ref", "subject_refs", "speech_acts", "epistemic_status",
    "scope_level", "scope_ref", "persistence_intent", "annotation_basis", "claim", "confidence", "alternatives",
    "supporting_refs", "counterevidence_refs", "relations", "action_effect", "review_when",
    "supersedes_interpretation_id",
  ], "Creator propose_interpretation");
  for (const field of ["interpretation_id", "source_turn_ref", "scope_ref", "claim", "review_when"] as const) {
    assertNonEmptyString(value[field], field);
  }
  stringArray(value.subject_refs, "subject_refs", true);
  stringArray(value.speech_acts, "speech_acts");
  if (value.subject_refs.length === 0 || value.speech_acts.length === 0
    || value.speech_acts.some((item) => !INTERPRETATION_SPEECH_ACTS.includes(item as never))) {
    throw new Error("interpretation requires valid subjects and speech acts");
  }
  if (!INTERPRETATION_EPISTEMIC_STATUSES.includes(value.epistemic_status as never)) throw new Error("invalid epistemic_status");
  if (!INTERPRETATION_SCOPE_LEVELS.includes(value.scope_level as never)) throw new Error("invalid scope_level");
  if (!INTERPRETATION_PERSISTENCE_INTENTS.includes(value.persistence_intent as never)) throw new Error("invalid persistence_intent");
  if (!INTERPRETATION_ANNOTATION_BASES.includes(value.annotation_basis as never)) throw new Error("invalid annotation_basis");
  if (!INTERPRETATION_ACTION_EFFECTS.includes(value.action_effect as never)) throw new Error("invalid action_effect");
  if (typeof value.confidence !== "number" || !Number.isFinite(value.confidence) || value.confidence < 0 || value.confidence > 1) {
    throw new Error("confidence must be between 0 and 1");
  }
  if (!Array.isArray(value.alternatives)) throw new Error("alternatives must be an array");
  for (const alternative of value.alternatives) {
    assertRecord(alternative, "interpretation alternative");
    exactKeys(alternative, ["claim", "disconfirming_evidence"], "interpretation alternative");
    assertNonEmptyString(alternative.claim, "alternative.claim");
    assertNonEmptyString(alternative.disconfirming_evidence, "alternative.disconfirming_evidence");
  }
  stringArray(value.supporting_refs, "supporting_refs", true);
  stringArray(value.counterevidence_refs, "counterevidence_refs", true);
  if (!Array.isArray(value.relations)) throw new Error("relations must be an array");
  for (const relation of value.relations) {
    assertRecord(relation, "interpretation relation");
    exactKeys(relation, ["target_ref", "kind", "reason"], "interpretation relation");
    assertNonEmptyString(relation.target_ref, "relation.target_ref");
    assertNonEmptyString(relation.reason, "relation.reason");
    if (!INTERPRETATION_RELATION_KINDS.includes(relation.kind as never)) throw new Error("invalid relation kind");
  }
  if (value.supersedes_interpretation_id !== undefined) {
    assertNonEmptyString(value.supersedes_interpretation_id, "supersedes_interpretation_id");
  }
}

/** Deterministic test double. It proves gates and replay, not semantic model quality. */
export class DeterministicCreatorInterpretationModel implements CreatorInterpretationModel {
  readonly model_ref: string;
  readonly #actions: Readonly<Record<string, CreatorInterpretationModelAction>>;

  constructor(modelRef: string, actionsByTurnRef: Readonly<Record<string, CreatorInterpretationModelAction>>) {
    assertNonEmptyString(modelRef, "model_ref");
    this.model_ref = modelRef;
    this.#actions = actionsByTurnRef;
  }

  async interpret(bundle: CreatorContextBundle, signal?: AbortSignal): Promise<CreatorInterpretationModelAction> {
    signal?.throwIfAborted();
    for (const turn of bundle.context.pending_input_turns) {
      const action = this.#actions[turn.turn_id];
      if (action) {
        const copy: unknown = structuredClone(action);
        validateCreatorInterpretationModelAction(copy);
        return copy;
      }
    }
    return { type: "no_action", reason: "No deterministic interpretation rule matched a visible raw turn." };
  }
}
