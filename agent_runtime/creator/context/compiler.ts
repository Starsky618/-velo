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
  max_pending_turns?: number;
  max_evidence?: number;
}

export interface CreatorContextOmission {
  category: "judgment" | "turn" | "evidence" | "contradiction";
  reason: "superseded" | "rejected" | "already_processed" | "resolved" | "subject_mismatch" | "budget";
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
    source_revisions: Array<{ source_ref: string; content_hash: string; provenance_ref: string }>;
  };
  omissions: CreatorContextOmission[];
}

export interface CreatorCompiledContext {
  mission: string;
  task: string;
  subject_refs: string[];
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

function omission(
  category: CreatorContextOmission["category"],
  reason: CreatorContextOmission["reason"],
  refs: string[],
): CreatorContextOmission | undefined {
  return refs.length === 0 ? undefined : { category, reason, count: refs.length, refs: refs.slice(0, 20) };
}

export function compileCreatorContext(view: CreatorView, request: CreatorContextRequest): CreatorContextBundle {
  if (request.task.trim() === "") throw new Error("Creator context task must be non-empty");
  const maxPendingTurns = request.max_pending_turns ?? 20;
  const maxEvidence = request.max_evidence ?? 30;
  if (!Number.isInteger(maxPendingTurns) || maxPendingTurns < 0) throw new Error("max_pending_turns must be non-negative");
  if (!Number.isInteger(maxEvidence) || maxEvidence < 0) throw new Error("max_evidence must be non-negative");

  const subjectRefs = [...new Set(request.subject_refs)].sort();
  const requestedSubjects = new Set(subjectRefs);
  const allJudgments = Object.values(view.judgments);
  const relevantJudgments = allJudgments.filter((judgment) => isRelevant(judgment.subject_ref, requestedSubjects));
  const currentJudgments = sorted(
    relevantJudgments.filter((judgment) => judgment.status === "tim_confirmed" && !judgment.superseded),
    (judgment) => judgment.id,
  );
  const pendingProposals = sorted(
    relevantJudgments.filter((judgment) => judgment.status === "proposed" && !judgment.superseded),
    (judgment) => judgment.id,
  );

  const referencedTurnIds = new Set(allJudgments.flatMap((judgment) => judgment.source_turn_refs));
  const relevantTurns = sorted(
    Object.values(view.conversation_turns).filter((turn) => (
      !turn.interaction
      && (requestedSubjects.size === 0 || turn.subject_refs.some((subjectRef) => isRelevant(subjectRef, requestedSubjects)))
    )),
    (turn) => `${turn.occurred_at}:${turn.turn_id}`,
  );
  const pendingTurnsAll = relevantTurns.filter((turn) => !referencedTurnIds.has(turn.turn_id));
  const pendingInputTurns = takeLast(pendingTurnsAll, maxPendingTurns);

  const unresolvedContradictions = sorted(
    Object.values(view.judgment_contradictions).filter((contradiction) => {
      const judgment = view.judgments[contradiction.judgment_id];
      return !contradiction.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects);
    }),
    (contradiction) => contradiction.id,
  );

  const requiredEvidenceIds = new Set([
    ...currentJudgments.flatMap((judgment) => judgment.evidence_refs),
    ...pendingProposals.flatMap((judgment) => judgment.evidence_refs),
    ...unresolvedContradictions.map((item) => item.contradicting_ref).filter((ref) => Boolean(view.evidence[ref])),
  ]);
  const subjectEvidence = sorted(
    Object.values(view.evidence).filter((evidence) => isRelevant(evidence.subject_ref, requestedSubjects)),
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
  ).map((source) => ({
    source_ref: source.source_ref,
    content_hash: source.content_hash,
    provenance_ref: source.provenance_ref,
  }));

  const context: CreatorCompiledContext = {
    mission: view.mission,
    task: request.task,
    subject_refs: subjectRefs,
    current_judgments: currentJudgments,
    pending_judgment_proposals: pendingProposals,
    pending_input_turns: pendingInputTurns,
    relevant_evidence: relevantEvidence,
    unresolved_contradictions: unresolvedContradictions,
  };

  const omissions = [
    omission("judgment", "superseded", relevantJudgments.filter((item) => item.superseded).map((item) => item.id)),
    omission("judgment", "rejected", relevantJudgments.filter((item) => item.status === "rejected").map((item) => item.id)),
    omission("judgment", "subject_mismatch", allJudgments.filter((item) => !isRelevant(item.subject_ref, requestedSubjects)).map((item) => item.id)),
    omission("turn", "already_processed", relevantTurns.filter((turn) => referencedTurnIds.has(turn.turn_id)).map((turn) => turn.turn_id)),
    omission("turn", "budget", pendingTurnsAll.slice(0, Math.max(0, pendingTurnsAll.length - pendingInputTurns.length)).map((turn) => turn.turn_id)),
    omission("evidence", "budget", optionalEvidence.slice(0, Math.max(0, optionalEvidence.length - includedOptionalEvidence.length)).map((item) => item.evidence_id)),
    omission("contradiction", "resolved", Object.values(view.judgment_contradictions).filter((item) => {
      const judgment = view.judgments[item.judgment_id];
      return item.resolved && judgment !== undefined && isRelevant(judgment.subject_ref, requestedSubjects);
    }).map((item) => item.id)),
  ].filter((item): item is CreatorContextOmission => item !== undefined);

  return {
    context,
    manifest: {
      compiler_version: CREATOR_CONTEXT_COMPILER_VERSION,
      workspace_id: view.workspace_id,
      workspace_revision: view.revision,
      source_event_id: view.last_event_id,
      request: { task: request.task, subject_refs: subjectRefs, max_pending_turns: maxPendingTurns, max_evidence: maxEvidence },
      request_hash: contentHash({ task: request.task, subject_refs: subjectRefs, max_pending_turns: maxPendingTurns, max_evidence: maxEvidence }),
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
