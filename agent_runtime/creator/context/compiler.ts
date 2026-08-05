import { contentHash } from "../../shared/canonical.ts";
import type {
  ConversationTurnRecorded,
  CreatorContradictionState,
  CreatorJudgmentState,
  CreatorView,
  EvidenceRecorded,
} from "../state/types.ts";

export const CREATOR_CONTEXT_COMPILER_VERSION = "creator-context-v0";

export interface CreatorContextRequest {
  task: string;
  subject_refs: string[];
  /** Deterministic decision time. Standalone compilation defaults to the source View's last event time. */
  as_of?: string;
  max_pending_turns?: number;
  max_evidence?: number;
}

export interface CreatorContextOmission {
  category: "source" | "judgment" | "turn" | "evidence" | "contradiction";
  reason: "superseded" | "rejected" | "already_processed" | "resolved" | "subject_mismatch" | "rights_not_allowed" | "review_due" | "budget";
  count: number;
  refs: string[];
}

export interface CreatorContextManifest {
  compiler_version: typeof CREATOR_CONTEXT_COMPILER_VERSION;
  workspace_id: string;
  workspace_revision: number;
  source_event_id: string;
  request: Required<CreatorContextRequest>;
  request_hash: string;
  context_hash: string;
  included: {
    judgment_refs: string[];
    proposal_refs: string[];
    turn_refs: string[];
    judgment_source_turn_refs: string[];
    evidence_refs: string[];
    contradiction_refs: string[];
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
  relevant_evidence: EvidenceRecorded[];
  unresolved_contradictions: CreatorContradictionState[];
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

function isRelevant(subjectRef: string, requested: ReadonlySet<string>): boolean {
  return requested.size === 0 || requested.has(subjectRef);
}

function requireUtcInstant(value: string, label: string): void {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString() !== value) throw new Error(`${label} must be a canonical UTC instant`);
}

export function normalizeCreatorContextRequest(
  request: CreatorContextRequest,
  defaultAsOf: string,
): Required<CreatorContextRequest> {
  if (request.task.trim() === "") throw new Error("Creator context task must be non-empty");
  const asOf = request.as_of ?? defaultAsOf;
  requireUtcInstant(asOf, "as_of");
  const maxPendingTurns = request.max_pending_turns ?? 20;
  const maxEvidence = request.max_evidence ?? 30;
  if (!Number.isInteger(maxPendingTurns) || maxPendingTurns < 0) throw new Error("max_pending_turns must be non-negative");
  if (!Number.isInteger(maxEvidence) || maxEvidence < 0) throw new Error("max_evidence must be non-negative");
  return {
    task: request.task,
    subject_refs: [...new Set(request.subject_refs)].sort(),
    as_of: asOf,
    max_pending_turns: maxPendingTurns,
    max_evidence: maxEvidence,
  };
}

function omission(
  category: CreatorContextOmission["category"],
  reason: CreatorContextOmission["reason"],
  refs: string[],
): CreatorContextOmission | undefined {
  return refs.length === 0 ? undefined : { category, reason, count: refs.length, refs: refs.slice(0, 20) };
}

export function compileCreatorContext(view: CreatorView, request: CreatorContextRequest): CreatorContextBundle {
  const normalized = normalizeCreatorContextRequest(request, view.last_occurred_at);
  const { max_pending_turns: maxPendingTurns, max_evidence: maxEvidence } = normalized;
  const subjectRefs = normalized.subject_refs;
  const requestedSubjects = new Set(subjectRefs);
  const allJudgments = Object.values(view.judgments);
  const relevantJudgments = allJudgments.filter((judgment) => isRelevant(judgment.subject_ref, requestedSubjects));

  const latestRightsFor = (sourceRef: string) => Object.values(view.rights_checks)
    .filter((check) => check.source_ref === sourceRef)
    .reduce((latest, check) => (
      latest === undefined || check.base_revision > latest.base_revision ? check : latest
    ), undefined as (typeof view.rights_checks)[string] | undefined);
  const sourceIsAllowed = (sourceRef: string) => latestRightsFor(sourceRef)?.decision === "allowed";
  const judgmentSourceRefs = (judgment: CreatorJudgmentState) => [
    ...judgment.source_turn_refs.map((ref) => view.conversation_turns[ref]?.source_ref),
    ...judgment.evidence_refs.map((ref) => view.evidence[ref]?.source_ref),
  ].filter((ref): ref is string => ref !== undefined);
  const judgmentRightsAllowed = (judgment: CreatorJudgmentState) => judgmentSourceRefs(judgment).every(sourceIsAllowed);
  const judgmentIsFresh = (judgment: CreatorJudgmentState) => judgment.review_at === undefined || judgment.review_at > normalized.as_of;

  const currentJudgments = sorted(
    relevantJudgments.filter((judgment) => (
      judgment.status === "tim_confirmed" && !judgment.superseded
      && judgmentRightsAllowed(judgment) && judgmentIsFresh(judgment)
    )),
    (judgment) => judgment.id,
  );
  const pendingProposals = sorted(
    relevantJudgments.filter((judgment) => (
      judgment.status === "proposed" && !judgment.superseded
      && judgmentRightsAllowed(judgment) && judgmentIsFresh(judgment)
    )),
    (judgment) => judgment.id,
  );

  const referencedTurnIds = new Set(allJudgments.flatMap((judgment) => judgment.source_turn_refs));
  const allTurns = Object.values(view.conversation_turns);
  const subjectTurns = allTurns.filter((turn) => (
      !turn.interaction
      && (requestedSubjects.size === 0 || turn.subject_refs.some((subjectRef) => isRelevant(subjectRef, requestedSubjects)))
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
    if (!target) return false;
    const evidence = view.evidence[contradiction.contradicting_ref];
    const turn = view.conversation_turns[contradiction.contradicting_ref];
    const judgment = view.judgments[contradiction.contradicting_ref];
    return evidence ? evidence.subject_ref === target.subject_ref
      : turn ? turn.subject_refs.includes(target.subject_ref)
        : judgment ? judgment.subject_ref === target.subject_ref
          : false;
  };
  const contradictionRightsAllowed = (contradiction: CreatorContradictionState) => {
    const evidence = view.evidence[contradiction.contradicting_ref];
    const turn = view.conversation_turns[contradiction.contradicting_ref];
    const judgment = view.judgments[contradiction.contradicting_ref];
    return evidence ? sourceIsAllowed(evidence.source_ref)
      : turn ? sourceIsAllowed(turn.source_ref)
        : judgment ? judgmentRightsAllowed(judgment)
          : false;
  };
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

  const requiredEvidenceIds = new Set([
    ...currentJudgments.flatMap((judgment) => judgment.evidence_refs),
    ...pendingProposals.flatMap((judgment) => judgment.evidence_refs),
    ...unresolvedContradictions.map((item) => item.contradicting_ref).filter((ref) => Boolean(view.evidence[ref])),
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
  const includedSourceRefs = new Set([
    ...pendingInputTurns.map((turn) => turn.source_ref),
    ...judgmentSourceTurnRefs.map((turnRef) => view.conversation_turns[turnRef]?.source_ref).filter((ref): ref is string => ref !== undefined),
    ...relevantEvidence.map((evidence) => evidence.source_ref),
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
    relevant_evidence: relevantEvidence,
    unresolved_contradictions: unresolvedContradictions,
  };

  const omissions = [
    omission("judgment", "superseded", relevantJudgments.filter((item) => item.superseded).map((item) => item.id)),
    omission("judgment", "rejected", relevantJudgments.filter((item) => item.status === "rejected").map((item) => item.id)),
    omission("judgment", "rights_not_allowed", relevantJudgments.filter((item) => !judgmentRightsAllowed(item)).map((item) => item.id)),
    omission("judgment", "review_due", relevantJudgments.filter((item) => !judgmentIsFresh(item)).map((item) => item.id)),
    omission("judgment", "subject_mismatch", allJudgments.filter((item) => !isRelevant(item.subject_ref, requestedSubjects)).map((item) => item.id)),
    omission("turn", "already_processed", relevantTurns.filter((turn) => referencedTurnIds.has(turn.turn_id)).map((turn) => turn.turn_id)),
    omission("turn", "budget", pendingTurnsAll.slice(0, Math.max(0, pendingTurnsAll.length - pendingInputTurns.length)).map((turn) => turn.turn_id)),
    omission("turn", "rights_not_allowed", subjectTurns.filter((turn) => !sourceIsAllowed(turn.source_ref)).map((turn) => turn.turn_id)),
    omission("turn", "subject_mismatch", allTurns.filter((turn) => (
      !turn.interaction && requestedSubjects.size > 0 && !turn.subject_refs.some((ref) => requestedSubjects.has(ref))
    )).map((turn) => turn.turn_id)),
    omission("evidence", "budget", optionalEvidence.slice(0, Math.max(0, optionalEvidence.length - includedOptionalEvidence.length)).map((item) => item.evidence_id)),
    omission("evidence", "rights_not_allowed", subjectEvidenceAll.filter((item) => !sourceIsAllowed(item.source_ref)).map((item) => item.evidence_id)),
    omission("evidence", "subject_mismatch", allEvidence.filter((item) => !isRelevant(item.subject_ref, requestedSubjects)).map((item) => item.evidence_id)),
    omission("contradiction", "resolved", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects);
    }).map((item) => item.id)),
    omission("contradiction", "rights_not_allowed", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return !item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects)
        && (!judgmentRightsAllowed(judgment) || !contradictionRightsAllowed(item));
    }).map((item) => item.id)),
    omission("contradiction", "review_due", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return !item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects)
        && !judgmentIsFresh(judgment);
    }).map((item) => item.id)),
    omission("contradiction", "subject_mismatch", allContradictions.filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return judgment !== undefined && (
        !isRelevant(judgment.subject_ref, requestedSubjects) || !contradictionSubjectMatches(item)
      );
    }).map((item) => item.id)),
    omission("source", "rights_not_allowed", [...new Set([
      ...subjectTurns.filter((turn) => !sourceIsAllowed(turn.source_ref)).map((turn) => turn.source_ref),
      ...subjectEvidenceAll.filter((evidence) => !sourceIsAllowed(evidence.source_ref)).map((evidence) => evidence.source_ref),
      ...relevantJudgments.filter((judgment) => !judgmentRightsAllowed(judgment)).flatMap(judgmentSourceRefs)
        .filter((sourceRef) => !sourceIsAllowed(sourceRef)),
    ])].sort()),
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
        source_revisions: sourceRevisions,
      },
      omissions,
    },
  };
}
