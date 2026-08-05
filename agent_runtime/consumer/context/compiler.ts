import { contentHash } from "../../shared/canonical.ts";
import type { ConversationTurn, SessionDecision, SessionView } from "../session/types.ts";

export interface RiderConversationContext {
  schema_version: 1;
  context_ref: string;
  session_id: string;
  source_revision: number;
  source_of_truth: false;
  recent_turns: ConversationTurn[];
  decision_source_turns: ConversationTurn[];
  confirmed_decisions: SessionDecision[];
  open_topics: Array<{ id: string; title: string; kind: "mainline" | "branch"; status: string }>;
  included_turn_refs: string[];
  omitted_turn_refs: string[];
  included_decision_refs: string[];
  context_hash: string;
}

export function compileRiderContext(view: SessionView, recentTurnLimit = 12): RiderConversationContext {
  if (!Number.isInteger(recentTurnLimit) || recentTurnLimit < 1) throw new Error("recentTurnLimit must be positive");
  const recentTurns = view.turns.slice(-recentTurnLimit);
  const confirmedDecisions = Object.values(view.decisions)
    .filter((decision) => decision.status === "user_confirmed" && !decision.superseded)
    .sort((left, right) => left.recorded_at.localeCompare(right.recorded_at));
  const decisionSourceRefs = [...new Set(confirmedDecisions.flatMap((decision) => decision.source_turn_refs))];
  const decisionSourceTurns = decisionSourceRefs.map((turnId) => {
    const turn = view.turns.find((item) => item.id === turnId);
    if (!turn) throw new Error(`confirmed decision references missing turn: ${turnId}`);
    return turn;
  });
  const includedTurnRefs = [...new Set([
    ...recentTurns.map((turn) => turn.id),
    ...decisionSourceRefs,
  ])];
  const omittedTurnRefs = view.turns.map((turn) => turn.id).filter((turnId) => !includedTurnRefs.includes(turnId));
  const openTopics = Object.values(view.topics)
    .filter((topic) => topic.status === "open" || topic.status === "in_progress" || topic.status === "deferred")
    .map(({ id, title, kind, status }) => ({ id, title, kind, status }));
  const manifest = {
    schema_version: 1 as const,
    session_id: view.session_id,
    source_revision: view.revision,
    source_of_truth: false as const,
    recent_turns: recentTurns,
    decision_source_turns: decisionSourceTurns,
    confirmed_decisions: confirmedDecisions,
    open_topics: openTopics,
    included_turn_refs: includedTurnRefs,
    omitted_turn_refs: omittedTurnRefs,
    included_decision_refs: confirmedDecisions.map((decision) => decision.id),
  };
  const contextHash = contentHash(manifest);
  return { ...manifest, context_ref: `rider-context:${view.session_id}:${view.revision}`, context_hash: contextHash };
}
