import { compileCreatorContext, type CreatorContextRequest } from "../context/compiler.ts";
import type { CreatorView } from "../state/types.ts";

export interface CreatorInterpretationReplayReport {
  pass: boolean;
  active_interpretation_refs: string[];
  current_judgment_refs: string[];
  overpromotion_refs: string[];
  scope_leak_refs: string[];
  superseded_leak_refs: string[];
  unconfirmed_current_refs: string[];
  conflict_packet_refs: string[];
  unknown_refs: string[];
  missing_unknown_refs: string[];
}

/**
 * Mechanical behavior replay. It evaluates state and context routing only; it
 * does not claim that a real LLM will classify unseen Tim language correctly.
 */
export function evaluateCreatorInterpretationReplay(
  view: CreatorView,
  request: CreatorContextRequest & { task_ref: string },
  unrelatedTaskRef: string,
): CreatorInterpretationReplayReport {
  const bundle = compileCreatorContext(view, request);
  const unrelated = compileCreatorContext(view, { ...request, task_ref: unrelatedTaskRef });
  const active = Object.values(view.interpretations).filter((item) => !item.superseded);
  const current = bundle.context.current_judgments;
  const overpromotionRefs = Object.values(view.judgments).filter((judgment) => (
    judgment.proposal_event_type === "creator.judgment_promotion_proposed"
    && (judgment.source_interpretation_refs ?? []).some((ref) => {
      const source = view.interpretations[ref];
      const turn = source ? view.conversation_turns[source.turn_id] : undefined;
      return source === undefined || source.superseded || source.persistence_intent === "task_local"
        || ["ambiguous", "hypothetical", "unknown"].includes(source.epistemic_status)
        || source.counterevidence_refs.length > 0 || source.alternatives.length > 0
        || turn?.actor !== "tim" || turn.source_role !== "user"
        || !["direct_unquoted_message", "manual_review"].includes(turn.authorship_basis)
        || source.speech_acts.includes("external_quote");
    })
  )).map((item) => item.id).sort();
  const scopeLeaks = unrelated.context.local_interpretations.filter((item) => (
    item.task_ref === request.task_ref
    && (["turn", "task"].includes(item.scope_level) || ["ephemeral", "task_local"].includes(item.persistence_intent))
  )).map((item) => item.interpretation_id).sort();
  const supersededLeaks = bundle.context.local_interpretations.filter((item) => item.superseded)
    .map((item) => item.interpretation_id).sort();
  const unconfirmedCurrent = current.filter((item) => item.status !== "tim_confirmed").map((item) => item.id).sort();
  const unknownRefs = bundle.context.unknowns.map((item) => item.interpretation_id).sort();
  const expectedUnknownRefs = bundle.context.local_interpretations.filter((item) => (
    ["ambiguous", "hypothetical", "unknown"].includes(item.epistemic_status)
    || item.action_effect === "request_clarification" || item.alternatives.length > 0
    || item.counterevidence_refs.length > 0
  )).map((item) => item.interpretation_id).sort();
  const missingUnknownRefs = expectedUnknownRefs.filter((ref) => !unknownRefs.includes(ref));
  return {
    pass: overpromotionRefs.length === 0 && scopeLeaks.length === 0
      && supersededLeaks.length === 0 && unconfirmedCurrent.length === 0 && missingUnknownRefs.length === 0,
    active_interpretation_refs: active.map((item) => item.interpretation_id).sort(),
    current_judgment_refs: current.map((item) => item.id).sort(),
    overpromotion_refs: overpromotionRefs,
    scope_leak_refs: scopeLeaks,
    superseded_leak_refs: supersededLeaks,
    unconfirmed_current_refs: unconfirmedCurrent,
    conflict_packet_refs: bundle.manifest.included.conflict_interpretation_refs,
    unknown_refs: unknownRefs,
    missing_unknown_refs: missingUnknownRefs,
  };
}
