import { contentHash } from "../../shared/canonical.ts";
import type {
  ConversationTurnRecorded,
  CreatorBehaviorCalibrationRecorded,
  CreatorContradictionState,
  CreatorInterpretationState,
  CreatorJudgmentState,
  CreatorTaskState,
  CreatorView,
  EvidenceRecorded,
} from "../state/types.ts";

export const CREATOR_CONTEXT_COMPILER_VERSION = "creator-context-v1";

export interface CreatorContextRequest {
  task: string;
  /** Stable execution identity. Required to expose task-local interpretations and task state. */
  task_ref?: string;
  subject_refs: string[];
  /** Deterministic decision time. Standalone compilation defaults to the source View's last event time. */
  as_of?: string;
  max_pending_turns?: number;
  max_evidence?: number;
  max_interpretations?: number;
}

export interface NormalizedCreatorContextRequest {
  task: string;
  task_ref?: string;
  subject_refs: string[];
  as_of: string;
  max_pending_turns: number;
  max_evidence: number;
  max_interpretations?: number;
}

export interface CreatorContextOmission {
  category: "source" | "judgment" | "turn" | "evidence" | "contradiction" | "interpretation" | "task_state" | "calibration";
  reason: "superseded" | "rejected" | "already_processed" | "resolved" | "subject_mismatch" | "scope_mismatch" | "rights_not_allowed" | "review_due" | "budget";
  count: number;
  refs: string[];
}

export interface CreatorContextManifest {
  compiler_version: typeof CREATOR_CONTEXT_COMPILER_VERSION;
  workspace_id: string;
  workspace_revision: number;
  source_event_id: string;
  request: NormalizedCreatorContextRequest;
  request_hash: string;
  context_hash: string;
  included: {
    judgment_refs: string[];
    proposal_refs: string[];
    turn_refs: string[];
    judgment_source_turn_refs: string[];
    evidence_refs: string[];
    contradiction_refs: string[];
    task_state_refs: string[];
    interpretation_refs: string[];
    interpretation_source_turn_refs: string[];
    conflict_source_turn_refs: string[];
    conflict_interpretation_refs: string[];
    conflict_target_refs: string[];
    calibration_refs: string[];
    calibration_context_item_refs: string[];
    source_revisions: Array<{
      source_ref: string;
      source_event_id: string;
      source_event_revision: number;
      content_hash: string;
      immutable_ref: string;
      provenance_ref: string;
      rights_decision: "allowed";
      rights_check_id: string;
      rights_event_revision: number;
    }>;
  };
  omissions: CreatorContextOmission[];
}

export interface CreatorCompiledContext {
  mission: string;
  task: string;
  subject_refs: string[];
  as_of: string;
  current_judgments: CreatorJudgmentState[];
  pending_judgment_proposals: CreatorJudgmentState[];
  pending_input_turns: ConversationTurnRecorded[];
  /** Exact immutable turns behind current and pending judgments. */
  judgment_source_turns: ConversationTurnRecorded[];
  relevant_evidence: EvidenceRecorded[];
  unresolved_contradictions: CreatorContradictionState[];
  current_task_state?: CreatorTaskState;
  /** Model-authored candidates. Never equivalent to current_judgments. */
  local_interpretations: CreatorInterpretationState[];
  /** Exact immutable turns behind local_interpretations, including actor/authorship/source metadata. */
  interpretation_source_turns: ConversationTurnRecorded[];
  /** Exact old/new raw turns needed to inspect a conflict or lineage edge. */
  conflict_source_turns: ConversationTurnRecorded[];
  conflict_packet: Array<{
    interpretation_id: string;
    target_ref: string;
    relation: "contradicts" | "refines" | "supersedes";
    reason: string;
    source_turn_ref: string;
    review_when: string;
    alternatives: CreatorInterpretationState["alternatives"];
    counterevidence_refs: string[];
    calibration_refs: string[];
    calibrations: CreatorBehaviorCalibrationRecorded[];
  }>;
  unknowns: CreatorInterpretationState[];
}

export interface CreatorContextBundle {
  context: CreatorCompiledContext;
  manifest: CreatorContextManifest;
}

function sorted<T>(items: T[], identity: (item: T) => string): T[] {
  return items.sort((left, right) => identity(left).localeCompare(identity(right)));
}

function takeLast<T>(items: readonly T[], count: number): T[] {
  return count === 0 ? [] : items.slice(-count);
}

function sameStringSet(left: readonly string[], right: readonly string[]): boolean {
  const normalizedLeft = [...left].sort();
  const normalizedRight = [...right].sort();
  return normalizedLeft.length === normalizedRight.length
    && normalizedLeft.every((item, index) => item === normalizedRight[index]);
}

function isRelevant(subjectRef: string, requested: ReadonlySet<string>): boolean {
  return requested.has(subjectRef);
}

function requireUtcInstant(value: string, label: string): void {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString() !== value) throw new Error(`${label} must be a canonical UTC instant`);
}

export function normalizeCreatorContextRequest(
  request: CreatorContextRequest,
  defaultAsOf: string,
): NormalizedCreatorContextRequest {
  if (request.task.trim() === "") throw new Error("Creator context task must be non-empty");
  if (!Array.isArray(request.subject_refs) || request.subject_refs.length === 0
    || request.subject_refs.some((ref) => typeof ref !== "string" || ref.trim() === "")) {
    throw new Error("Creator context subject_refs must contain explicit non-empty privacy labels");
  }
  const asOf = request.as_of ?? defaultAsOf;
  requireUtcInstant(asOf, "as_of");
  const maxPendingTurns = request.max_pending_turns ?? 20;
  const maxEvidence = request.max_evidence ?? 30;
  const maxInterpretations = request.max_interpretations;
  if (!Number.isInteger(maxPendingTurns) || maxPendingTurns < 0) throw new Error("max_pending_turns must be non-negative");
  if (!Number.isInteger(maxEvidence) || maxEvidence < 0) throw new Error("max_evidence must be non-negative");
  if (request.task_ref !== undefined && request.task_ref.trim() === "") throw new Error("task_ref must be non-empty when provided");
  if (maxInterpretations !== undefined && (!Number.isSafeInteger(maxInterpretations) || maxInterpretations < 0)) {
    throw new Error("max_interpretations must be non-negative");
  }
  return {
    task: request.task,
    ...(request.task_ref === undefined ? {} : { task_ref: request.task_ref }),
    subject_refs: [...new Set(request.subject_refs)].sort(),
    as_of: asOf,
    max_pending_turns: maxPendingTurns,
    max_evidence: maxEvidence,
    ...(maxInterpretations === undefined ? {} : { max_interpretations: maxInterpretations }),
  };
}

function omission(
  category: CreatorContextOmission["category"],
  reason: CreatorContextOmission["reason"],
  refs: string[],
  redactRefs = false,
): CreatorContextOmission | undefined {
  return refs.length === 0 ? undefined : {
    category, reason, count: refs.length, refs: redactRefs ? [] : refs.slice(0, 20),
  };
}

export function compileCreatorContext(view: CreatorView, request: CreatorContextRequest): CreatorContextBundle {
  const normalized = normalizeCreatorContextRequest(request, view.last_occurred_at);
  const { max_pending_turns: maxPendingTurns, max_evidence: maxEvidence } = normalized;
  const subjectRefs = normalized.subject_refs;
  const requestedSubjects = new Set(subjectRefs);
  const turnSubjectsCovered = (turn: ConversationTurnRecorded) => (
    turn.subject_refs.length > 0 && turn.subject_refs.every((subjectRef) => requestedSubjects.has(subjectRef))
  );
  const allJudgments = Object.values(view.judgments);
  const relevantJudgments = allJudgments.filter((judgment) => isRelevant(judgment.subject_ref, requestedSubjects));

  const latestRightsFor = (sourceRef: string) => Object.values(view.rights_checks)
    .filter((check) => check.source_ref === sourceRef)
    .reduce((latest, check) => (
      latest === undefined || check.base_revision > latest.base_revision ? check : latest
    ), undefined as (typeof view.rights_checks)[string] | undefined);
  const sourceIsAllowed = (sourceRef: string) => latestRightsFor(sourceRef)?.decision === "allowed";

  const contextRefRightsAllowed = (ref: string, visited = new Set<string>()): boolean => {
    if (visited.has(ref)) return false;
    const nextVisited = new Set(visited).add(ref);
    const turn = view.conversation_turns[ref];
    if (turn) return sourceIsAllowed(turn.source_ref);
    const evidence = view.evidence[ref];
    if (evidence) return sourceIsAllowed(evidence.source_ref);
    const interpretation = view.interpretations[ref];
    if (interpretation) {
      const lineageRefs = [interpretation.turn_id, ...interpretation.supporting_refs, ...interpretation.counterevidence_refs];
      return lineageRefs.length > 0 && lineageRefs.every((itemRef) => contextRefRightsAllowed(itemRef, nextVisited));
    }
    const taskState = view.task_states[ref];
    if (taskState) return taskState.source_turn_refs.length > 0
      && taskState.source_turn_refs.every((itemRef) => contextRefRightsAllowed(itemRef, nextVisited));
    const judgment = view.judgments[ref];
    if (judgment) {
      const lineageRefs = [...new Set([
        ...judgment.source_turn_refs,
        ...judgment.evidence_refs,
        ...(judgment.source_interpretation_refs ?? []),
        ...(judgment.promotion_basis_refs ?? []),
      ])];
      return lineageRefs.length > 0 && lineageRefs.every((itemRef) => contextRefRightsAllowed(itemRef, nextVisited));
    }
    const contradiction = view.judgment_contradictions[ref];
    if (contradiction) return contextRefRightsAllowed(contradiction.judgment_id, nextVisited)
      && contextRefRightsAllowed(contradiction.contradicting_ref, nextVisited);
    const calibration = view.behavior_calibrations[ref];
    return calibration !== undefined && calibration.context_item_refs.length > 0
      && calibration.context_item_refs.every((itemRef) => contextRefRightsAllowed(itemRef, nextVisited));
  };

  const contextRefSubjectSet = (ref: string, visited = new Set<string>()): string[] | undefined => {
    if (visited.has(ref)) return undefined;
    const nextVisited = new Set(visited).add(ref);
    const turn = view.conversation_turns[ref];
    if (turn) return turn.subject_refs.length === 0 ? undefined : [...turn.subject_refs].sort();
    const evidence = view.evidence[ref];
    if (evidence) return evidence.subject_ref === "" ? undefined : [evidence.subject_ref];
    const interpretation = view.interpretations[ref];
    if (interpretation) {
      const declared = [...interpretation.subject_refs].sort();
      if (declared.length === 0) return undefined;
      const lineageRefs = [interpretation.turn_id, ...interpretation.supporting_refs, ...interpretation.counterevidence_refs];
      const lineageSubjects = lineageRefs.map((itemRef) => contextRefSubjectSet(itemRef, nextVisited));
      if (lineageSubjects.some((subjects) => !subjects || subjects.length === 0
        || subjects.some((subject) => !declared.includes(subject)))) return undefined;
      return declared;
    }
    const taskState = view.task_states[ref];
    if (taskState) {
      const subjectSets = taskState.source_turn_refs.map((itemRef) => contextRefSubjectSet(itemRef, nextVisited));
      if (subjectSets.length === 0 || subjectSets.some((subjects) => !subjects || subjects.length === 0)) return undefined;
      return [...new Set(subjectSets.flatMap((subjects) => subjects ?? []))].sort();
    }
    const judgment = view.judgments[ref];
    if (judgment) {
      const lineageRefs = [...new Set([
        ...judgment.source_turn_refs,
        ...judgment.evidence_refs,
        ...(judgment.source_interpretation_refs ?? []),
        ...(judgment.promotion_basis_refs ?? []),
      ])];
      const subjectSets = lineageRefs.map((itemRef) => contextRefSubjectSet(itemRef, nextVisited));
      if (subjectSets.length === 0 || subjectSets.some((subjects) => !subjects || subjects.length === 0)) return undefined;
      return [...new Set([judgment.subject_ref, ...subjectSets.flatMap((subjects) => subjects ?? [])])].sort();
    }
    const contradiction = view.judgment_contradictions[ref];
    if (contradiction) {
      const targetSubjects = contextRefSubjectSet(contradiction.judgment_id, nextVisited);
      const contradictingSubjects = contextRefSubjectSet(contradiction.contradicting_ref, nextVisited);
      return targetSubjects && contradictingSubjects && sameStringSet(targetSubjects, contradictingSubjects)
        ? targetSubjects : undefined;
    }
    const calibration = view.behavior_calibrations[ref];
    if (!calibration) return undefined;
    const subjectSets = calibration.context_item_refs.map((itemRef) => contextRefSubjectSet(itemRef, nextVisited));
    if (subjectSets.length === 0 || subjectSets.some((subjects) => !subjects || subjects.length === 0)) return undefined;
    const first = subjectSets[0]!;
    return subjectSets.every((subjects) => subjects !== undefined && sameStringSet(subjects, first))
      ? first : undefined;
  };
  const contextRefSubjectRelevant = (ref: string, visited = new Set<string>()) => {
    const subjects = contextRefSubjectSet(ref, visited);
    return subjects !== undefined && subjects.length > 0
      && subjects.every((subjectRef) => requestedSubjects.has(subjectRef));
  };

  const allTaskStates = Object.values(view.task_states);
  const taskStateRightsAllowed = (item: CreatorTaskState) => contextRefRightsAllowed(item.task_state_id);
  const taskStateSubjectRelevant = (item: CreatorTaskState) => contextRefSubjectRelevant(item.task_state_id);
  const currentTaskState = normalized.task_ref === undefined ? undefined : allTaskStates
    .filter((item) => item.task_ref === normalized.task_ref && !item.superseded
      && taskStateRightsAllowed(item) && taskStateSubjectRelevant(item))
    .at(-1);

  const allInterpretations = Object.values(view.interpretations);
  const activeInterpretations = allInterpretations.filter((item) => !item.superseded);
  const interpretationRightsAllowed = (item: CreatorInterpretationState) => (
    contextRefRightsAllowed(item.interpretation_id)
  );
  const interpretationSubjectRelevant = (item: CreatorInterpretationState) => (
    contextRefSubjectRelevant(item.interpretation_id)
  );
  const interpretationScopeRelevant = (item: CreatorInterpretationState) => {
    if (["turn", "task"].includes(item.scope_level) || ["ephemeral", "task_local"].includes(item.persistence_intent)) {
      return normalized.task_ref !== undefined && item.task_ref === normalized.task_ref;
    }
    if (item.scope_level === "project") {
      return currentTaskState !== undefined && item.scope_ref === currentTaskState.project_ref;
    }
    return ["cross_project", "global"].includes(item.scope_level);
  };
  const eligibleInterpretations = sorted(activeInterpretations.filter((item) => (
    interpretationRightsAllowed(item) && interpretationSubjectRelevant(item) && interpretationScopeRelevant(item)
  )), (item) => `${item.occurred_at}:${item.interpretation_id}`);
  const interpretationBudget = normalized.max_interpretations ?? 20;
  const localInterpretations = takeLast(eligibleInterpretations, interpretationBudget);
  const interpretationSourceTurns = sorted(
    localInterpretations.map((item) => view.conversation_turns[item.turn_id])
      .filter((item): item is ConversationTurnRecorded => item !== undefined),
    (item) => `${item.occurred_at}:${item.turn_id}`,
  );
  const judgmentSourceRefs = (judgment: CreatorJudgmentState) => [
    ...judgment.source_turn_refs.map((ref) => view.conversation_turns[ref]?.source_ref),
    ...judgment.evidence_refs.map((ref) => view.evidence[ref]?.source_ref),
  ].filter((ref): ref is string => ref !== undefined);
  const judgmentRightsAllowed = (judgment: CreatorJudgmentState) => contextRefRightsAllowed(judgment.id);
  const judgmentSubjectsCovered = (judgment: CreatorJudgmentState) => contextRefSubjectRelevant(judgment.id);
  const judgmentIsFresh = (judgment: CreatorJudgmentState) => judgment.review_at === undefined || judgment.review_at > normalized.as_of;

  const currentJudgments = sorted(
    relevantJudgments.filter((judgment) => (
      judgment.status === "tim_confirmed" && !judgment.superseded
      && judgmentRightsAllowed(judgment) && judgmentSubjectsCovered(judgment) && judgmentIsFresh(judgment)
    )),
    (judgment) => judgment.id,
  );
  const pendingProposals = sorted(
    relevantJudgments.filter((judgment) => (
      judgment.status === "proposed" && !judgment.superseded
      && judgmentRightsAllowed(judgment) && judgmentSubjectsCovered(judgment) && judgmentIsFresh(judgment)
    )),
    (judgment) => judgment.id,
  );

  const referencedTurnIds = new Set([
    ...allJudgments.flatMap((judgment) => judgment.source_turn_refs),
    ...allInterpretations.map((item) => item.turn_id),
  ]);
  const allTurns = Object.values(view.conversation_turns);
  const subjectTurns = allTurns.filter((turn) => (
      !turn.interaction && turnSubjectsCovered(turn)
  ));
  const relevantTurns = sorted(
    subjectTurns.filter((turn) => sourceIsAllowed(turn.source_ref)),
    (turn) => `${turn.occurred_at}:${turn.turn_id}`,
  );
  const pendingTurnsAll = relevantTurns.filter((turn) => !referencedTurnIds.has(turn.turn_id));
  const pendingInputTurns = takeLast(pendingTurnsAll, maxPendingTurns);

  const allContradictions = Object.values(view.judgment_contradictions);
  const contradictionSubjectMatches = (contradiction: CreatorContradictionState) => {
    const target = view.judgments[contradiction.judgment_id];
    const subjects = contextRefSubjectSet(contradiction.id);
    return target !== undefined && subjects !== undefined && sameStringSet(subjects, [target.subject_ref]);
  };
  const contradictionRightsAllowed = (contradiction: CreatorContradictionState) => (
    contextRefRightsAllowed(contradiction.id)
  );
  const currentJudgmentIds = new Set(currentJudgments.map((judgment) => judgment.id));
  const unresolvedContradictions = sorted(
    allContradictions.filter((contradiction) => {
      const judgment = view.judgments[contradiction.judgment_id];
      return !contradiction.resolved && judgment !== undefined
        && currentJudgmentIds.has(judgment.id) && contradictionSubjectMatches(contradiction)
        && contradictionRightsAllowed(contradiction);
    }),
    (contradiction) => contradiction.id,
  );

  const eligibleConflictTargetInterpretations = allInterpretations.filter((item) => (
    interpretationRightsAllowed(item) && interpretationSubjectRelevant(item) && interpretationScopeRelevant(item)
  ));
  const activeConflictTargetRefs = new Set([
    ...currentJudgments.map((item) => item.id),
    ...eligibleConflictTargetInterpretations.map((item) => item.interpretation_id),
  ]);
  const conflictEdges = localInterpretations.flatMap((item) => item.relations
    .filter((relation) => ["contradicts", "refines", "supersedes"].includes(relation.kind)
      && activeConflictTargetRefs.has(relation.target_ref))
    .map((relation) => ({ item, relation })));
  const conflictEndpointRefs = new Set(conflictEdges.flatMap(({ item, relation }) => (
    [item.interpretation_id, relation.target_ref]
  )));
  const allConflictCalibrationCandidates = Object.values(view.behavior_calibrations)
    .filter((calibration) => calibration.context_item_refs.some((ref) => conflictEndpointRefs.has(ref)));
  const contextRefScopeRelevant = (ref: string, visited = new Set<string>()): boolean => {
    if (visited.has(ref)) return false;
    const nextVisited = new Set(visited).add(ref);
    const interpretation = view.interpretations[ref];
    if (interpretation) return interpretationScopeRelevant(interpretation);
    const taskState = view.task_states[ref];
    if (taskState) return normalized.task_ref !== undefined && taskState.task_ref === normalized.task_ref && !taskState.superseded;
    const calibration = view.behavior_calibrations[ref];
    if (calibration) return normalized.task_ref !== undefined && calibration.task_ref === normalized.task_ref
      && calibration.context_item_refs.every((itemRef) => contextRefScopeRelevant(itemRef, nextVisited));
    return Boolean(
      view.conversation_turns[ref] || view.evidence[ref] || view.judgments[ref]
      || view.judgment_contradictions[ref],
    );
  };
  const calibrationVisible = (calibration: CreatorBehaviorCalibrationRecorded) => (
    normalized.task_ref !== undefined && calibration.task_ref === normalized.task_ref
    && calibration.context_item_refs.length > 0
    && calibration.context_item_refs.every((ref) => (
      contextRefRightsAllowed(ref) && contextRefSubjectRelevant(ref) && contextRefScopeRelevant(ref)
    ))
  );
  const visibleConflictCalibrations = sorted(
    allConflictCalibrationCandidates.filter(calibrationVisible),
    (calibration) => calibration.calibration_id,
  );
  const conflictPacket = conflictEdges.map(({ item, relation }) => {
    const calibrations = visibleConflictCalibrations.filter((calibration) => calibration.context_item_refs.some((ref) => (
      ref === item.interpretation_id || ref === relation.target_ref
    )));
    return {
      interpretation_id: item.interpretation_id,
      target_ref: relation.target_ref,
      relation: relation.kind as "contradicts" | "refines" | "supersedes",
      reason: relation.reason,
      source_turn_ref: item.turn_id,
      review_when: item.review_when,
      alternatives: structuredClone(item.alternatives),
      counterevidence_refs: [...item.counterevidence_refs],
      calibration_refs: calibrations.map((calibration) => calibration.calibration_id),
      calibrations: structuredClone(calibrations),
    };
  });
  const unknowns = localInterpretations.filter((item) => (
    ["ambiguous", "hypothetical", "unknown"].includes(item.epistemic_status)
    || item.action_effect === "request_clarification" || item.alternatives.length > 0
    || item.counterevidence_refs.length > 0
  ));

  const contextRefEvidenceRefs = (ref: string, visited = new Set<string>()): string[] => {
    if (visited.has(ref)) return [];
    const nextVisited = new Set(visited).add(ref);
    if (view.evidence[ref]) return [ref];
    const interpretation = view.interpretations[ref];
    if (interpretation) return [...interpretation.supporting_refs, ...interpretation.counterevidence_refs]
      .flatMap((itemRef) => contextRefEvidenceRefs(itemRef, nextVisited));
    const judgment = view.judgments[ref];
    if (judgment) return [...judgment.evidence_refs];
    const contradiction = view.judgment_contradictions[ref];
    if (contradiction) return [
      ...contextRefEvidenceRefs(contradiction.judgment_id, nextVisited),
      ...contextRefEvidenceRefs(contradiction.contradicting_ref, nextVisited),
    ];
    const calibration = view.behavior_calibrations[ref];
    return calibration ? calibration.context_item_refs.flatMap((itemRef) => (
      contextRefEvidenceRefs(itemRef, nextVisited)
    )) : [];
  };

  const requiredEvidenceIds = new Set([
    ...currentJudgments.flatMap((judgment) => judgment.evidence_refs),
    ...pendingProposals.flatMap((judgment) => judgment.evidence_refs),
    ...unresolvedContradictions.map((item) => item.contradicting_ref).filter((ref) => Boolean(view.evidence[ref])),
    ...visibleConflictCalibrations.flatMap((calibration) => calibration.context_item_refs
      .flatMap((ref) => contextRefEvidenceRefs(ref))),
  ]);
  const allEvidence = Object.values(view.evidence);
  const subjectEvidenceAll = allEvidence.filter((evidence) => isRelevant(evidence.subject_ref, requestedSubjects));
  const subjectEvidence = sorted(
    subjectEvidenceAll.filter((evidence) => sourceIsAllowed(evidence.source_ref)),
    (evidence) => `${evidence.observed_at}:${evidence.evidence_id}`,
  );
  const requiredEvidence = sorted(
    [...requiredEvidenceIds].map((ref) => view.evidence[ref]).filter((item): item is EvidenceRecorded => Boolean(item)),
    (evidence) => `${evidence.observed_at}:${evidence.evidence_id}`,
  );
  const optionalEvidence = subjectEvidence.filter((item) => !requiredEvidenceIds.has(item.evidence_id));
  const optionalBudget = Math.max(0, maxEvidence - requiredEvidence.length);
  const includedOptionalEvidence = takeLast(optionalEvidence, optionalBudget);
  // Evidence backing a current judgment or unresolved contradiction is never dropped by a token budget.
  const relevantEvidence = sorted([...requiredEvidence, ...includedOptionalEvidence], (item) => `${item.observed_at}:${item.evidence_id}`);

  const judgmentSourceTurnRefs = [...new Set([
    ...currentJudgments.flatMap((judgment) => judgment.source_turn_refs),
    ...pendingProposals.flatMap((judgment) => judgment.source_turn_refs),
  ])].sort();
  const judgmentSourceTurns = judgmentSourceTurnRefs
    .map((turnRef) => view.conversation_turns[turnRef])
    .filter((turn): turn is ConversationTurnRecorded => turn !== undefined && turnSubjectsCovered(turn));
  const contextRefSourceTurnRefs = (ref: string, visited = new Set<string>()): string[] => {
    if (visited.has(ref)) return [];
    const nextVisited = new Set(visited).add(ref);
    if (view.conversation_turns[ref]) return [ref];
    const interpretation = view.interpretations[ref];
    if (interpretation) return [interpretation.turn_id];
    const taskState = view.task_states[ref];
    if (taskState) return [...taskState.source_turn_refs];
    const judgment = view.judgments[ref];
    if (judgment) return [...judgment.source_turn_refs];
    const contradiction = view.judgment_contradictions[ref];
    if (contradiction) return [
      ...contextRefSourceTurnRefs(contradiction.judgment_id, nextVisited),
      ...contextRefSourceTurnRefs(contradiction.contradicting_ref, nextVisited),
    ];
    const calibration = view.behavior_calibrations[ref];
    return calibration ? calibration.context_item_refs.flatMap((itemRef) => (
      contextRefSourceTurnRefs(itemRef, nextVisited)
    )) : [];
  };
  const conflictSourceTurnRefs = [...new Set([
    ...conflictPacket.flatMap((item) => {
    const targetInterpretation = view.interpretations[item.target_ref];
    const targetJudgment = view.judgments[item.target_ref];
    return [
      item.source_turn_ref,
      ...(targetInterpretation ? [targetInterpretation.turn_id] : []),
      ...(targetJudgment?.source_turn_refs ?? []),
    ];
    }),
    ...visibleConflictCalibrations.flatMap((calibration) => calibration.context_item_refs
      .flatMap((ref) => contextRefSourceTurnRefs(ref))),
  ])].sort();
  const conflictSourceTurns = conflictSourceTurnRefs
    .map((turnRef) => view.conversation_turns[turnRef])
    .filter((turn): turn is ConversationTurnRecorded => turn !== undefined && turnSubjectsCovered(turn));
  const includedSourceRefs = new Set([
    ...pendingInputTurns.map((turn) => turn.source_ref),
    ...judgmentSourceTurnRefs.map((turnRef) => view.conversation_turns[turnRef]?.source_ref).filter((ref): ref is string => ref !== undefined),
    ...conflictSourceTurns.map((turn) => turn.source_ref),
    ...relevantEvidence.map((evidence) => evidence.source_ref),
    ...localInterpretations.map((item) => view.conversation_turns[item.turn_id]?.source_ref).filter((ref): ref is string => ref !== undefined),
    ...(currentTaskState?.source_turn_refs ?? []).map((ref) => view.conversation_turns[ref]?.source_ref).filter((ref): ref is string => ref !== undefined),
  ]);
  const sourceRevisions = sorted(
    [...includedSourceRefs].map((sourceRef) => view.sources[sourceRef]).filter((source) => source !== undefined),
    (source) => source.source_ref,
  ).map((source) => {
    const rights = latestRightsFor(source.source_ref);
    if (!rights || rights.decision !== "allowed") throw new Error(`included source lacks current allowed rights: ${source.source_ref}`);
    return {
      source_ref: source.source_ref,
      source_event_id: source.event_id,
      source_event_revision: source.base_revision + 1,
      content_hash: source.content_hash,
      immutable_ref: source.immutable_ref,
      provenance_ref: source.provenance_ref,
      rights_decision: "allowed" as const,
      rights_check_id: rights.rights_check_id,
      rights_event_revision: rights.base_revision + 1,
    };
  });

  const context: CreatorCompiledContext = {
    mission: view.mission,
    task: normalized.task,
    subject_refs: subjectRefs,
    as_of: normalized.as_of,
    current_judgments: currentJudgments,
    pending_judgment_proposals: pendingProposals,
    pending_input_turns: pendingInputTurns,
    judgment_source_turns: judgmentSourceTurns,
    relevant_evidence: relevantEvidence,
    unresolved_contradictions: unresolvedContradictions,
    ...(currentTaskState === undefined ? {} : { current_task_state: currentTaskState }),
    local_interpretations: localInterpretations,
    interpretation_source_turns: interpretationSourceTurns,
    conflict_source_turns: conflictSourceTurns,
    conflict_packet: conflictPacket,
    unknowns,
  };

  const omissions = [
    omission("judgment", "superseded", relevantJudgments.filter((item) => (
      item.superseded && judgmentRightsAllowed(item) && judgmentSubjectsCovered(item)
    )).map((item) => item.id)),
    omission("judgment", "rejected", relevantJudgments.filter((item) => (
      item.status === "rejected" && judgmentRightsAllowed(item) && judgmentSubjectsCovered(item)
    )).map((item) => item.id)),
    omission("judgment", "rights_not_allowed", relevantJudgments.filter((item) => !judgmentRightsAllowed(item)).map((item) => item.id), true),
    omission("judgment", "review_due", relevantJudgments.filter((item) => (
      !judgmentIsFresh(item) && judgmentRightsAllowed(item) && judgmentSubjectsCovered(item)
    )).map((item) => item.id)),
    omission("judgment", "subject_mismatch", allJudgments.filter((item) => (
      !isRelevant(item.subject_ref, requestedSubjects) || !judgmentSubjectsCovered(item)
    )).map((item) => item.id), true),
    omission("turn", "already_processed", relevantTurns.filter((turn) => referencedTurnIds.has(turn.turn_id)).map((turn) => turn.turn_id)),
    omission("turn", "budget", pendingTurnsAll.slice(0, Math.max(0, pendingTurnsAll.length - pendingInputTurns.length)).map((turn) => turn.turn_id)),
    omission("turn", "rights_not_allowed", subjectTurns.filter((turn) => !sourceIsAllowed(turn.source_ref)).map((turn) => turn.turn_id), true),
    omission("turn", "subject_mismatch", allTurns.filter((turn) => (
      !turn.interaction && !turnSubjectsCovered(turn)
    )).map((turn) => turn.turn_id), true),
    omission("evidence", "budget", optionalEvidence.slice(0, Math.max(0, optionalEvidence.length - includedOptionalEvidence.length)).map((item) => item.evidence_id)),
    omission("evidence", "rights_not_allowed", subjectEvidenceAll.filter((item) => !sourceIsAllowed(item.source_ref)).map((item) => item.evidence_id), true),
    omission("evidence", "subject_mismatch", allEvidence.filter((item) => !isRelevant(item.subject_ref, requestedSubjects)).map((item) => item.evidence_id), true),
    omission("contradiction", "resolved", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects)
        && judgmentRightsAllowed(judgment) && contradictionRightsAllowed(item) && contradictionSubjectMatches(item);
    }).map((item) => item.id)),
    omission("contradiction", "rights_not_allowed", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return !item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects)
        && (!judgmentRightsAllowed(judgment) || !contradictionRightsAllowed(item));
    }).map((item) => item.id), true),
    omission("contradiction", "review_due", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return !item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects)
        && !judgmentIsFresh(judgment) && judgmentRightsAllowed(judgment)
        && contradictionRightsAllowed(item) && contradictionSubjectMatches(item);
    }).map((item) => item.id)),
    omission("contradiction", "subject_mismatch", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return judgment !== undefined && (
        !isRelevant(judgment.subject_ref, requestedSubjects) || !contradictionSubjectMatches(item)
      );
    }).map((item) => item.id), true),
    omission("source", "rights_not_allowed", [...new Set([
      ...subjectTurns.filter((turn) => !sourceIsAllowed(turn.source_ref)).map((turn) => turn.source_ref),
      ...subjectEvidenceAll.filter((evidence) => !sourceIsAllowed(evidence.source_ref)).map((evidence) => evidence.source_ref),
      ...relevantJudgments.filter((judgment) => !judgmentRightsAllowed(judgment)).flatMap(judgmentSourceRefs)
        .filter((sourceRef) => !sourceIsAllowed(sourceRef)),
    ])].sort(), true),
    omission("interpretation", "superseded", allInterpretations.filter((item) => (
      item.superseded && interpretationRightsAllowed(item) && interpretationSubjectRelevant(item)
      && interpretationScopeRelevant(item)
    )).map((item) => item.interpretation_id)),
    omission("interpretation", "rights_not_allowed", activeInterpretations.filter((item) => !interpretationRightsAllowed(item)).map((item) => item.interpretation_id), true),
    omission("interpretation", "subject_mismatch", activeInterpretations.filter((item) => !interpretationSubjectRelevant(item)).map((item) => item.interpretation_id), true),
    omission("interpretation", "scope_mismatch", activeInterpretations.filter((item) => (
      interpretationRightsAllowed(item) && interpretationSubjectRelevant(item) && !interpretationScopeRelevant(item)
    )).map((item) => item.interpretation_id)),
    omission("interpretation", "budget", eligibleInterpretations.slice(0, Math.max(0, eligibleInterpretations.length - localInterpretations.length))
      .map((item) => item.interpretation_id)),
    omission("task_state", "superseded", allTaskStates.filter((item) => (
      item.superseded && taskStateRightsAllowed(item) && taskStateSubjectRelevant(item)
      && normalized.task_ref !== undefined && item.task_ref === normalized.task_ref
    )).map((item) => item.task_state_id)),
    omission("task_state", "rights_not_allowed", allTaskStates.filter((item) => !item.superseded && !taskStateRightsAllowed(item))
      .map((item) => item.task_state_id), true),
    omission("task_state", "subject_mismatch", allTaskStates.filter((item) => !item.superseded
      && taskStateRightsAllowed(item) && !taskStateSubjectRelevant(item)).map((item) => item.task_state_id), true),
    omission("calibration", "rights_not_allowed", allConflictCalibrationCandidates.filter((item) => (
      item.context_item_refs.some((ref) => !contextRefRightsAllowed(ref))
    )).map((item) => item.calibration_id), true),
    omission("calibration", "subject_mismatch", allConflictCalibrationCandidates.filter((item) => (
      item.context_item_refs.some((ref) => !contextRefSubjectRelevant(ref))
    )).map((item) => item.calibration_id), true),
    omission("calibration", "scope_mismatch", allConflictCalibrationCandidates.filter((item) => (
      item.context_item_refs.every((ref) => contextRefRightsAllowed(ref) && contextRefSubjectRelevant(ref))
      && (item.task_ref !== normalized.task_ref || item.context_item_refs.some((ref) => !contextRefScopeRelevant(ref)))
    )).map((item) => item.calibration_id)),
  ].filter((item): item is CreatorContextOmission => item !== undefined);

  return {
    context,
    manifest: {
      compiler_version: CREATOR_CONTEXT_COMPILER_VERSION,
      workspace_id: view.workspace_id,
      workspace_revision: view.revision,
      source_event_id: view.last_event_id,
      request: normalized,
      request_hash: contentHash(normalized),
      context_hash: contentHash(context),
      included: {
        judgment_refs: currentJudgments.map((item) => item.id),
        proposal_refs: pendingProposals.map((item) => item.id),
        turn_refs: pendingInputTurns.map((item) => item.turn_id),
        judgment_source_turn_refs: judgmentSourceTurnRefs,
        evidence_refs: relevantEvidence.map((item) => item.evidence_id),
        contradiction_refs: unresolvedContradictions.map((item) => item.id),
        task_state_refs: currentTaskState ? [currentTaskState.task_state_id] : [],
        interpretation_refs: localInterpretations.map((item) => item.interpretation_id),
        interpretation_source_turn_refs: interpretationSourceTurns.map((item) => item.turn_id),
        conflict_source_turn_refs: conflictSourceTurns.map((item) => item.turn_id),
        conflict_interpretation_refs: [...new Set(conflictPacket.map((item) => item.interpretation_id))].sort(),
        conflict_target_refs: [...new Set(conflictPacket.map((item) => item.target_ref))].sort(),
        calibration_refs: visibleConflictCalibrations.map((item) => item.calibration_id),
        calibration_context_item_refs: [...new Set(visibleConflictCalibrations.flatMap((item) => item.context_item_refs))].sort(),
        source_revisions: sourceRevisions,
      },
      omissions,
    },
  };
}
