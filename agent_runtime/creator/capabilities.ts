import { CapabilityGate, type RuntimePrincipal } from "../shared/capability-gate.ts";

export const CREATOR_CAPABILITIES = [
  "workspace.create",
  "context.read_private",
  "source.ingest",
  "conversation.record",
  "evidence.inspect_raw",
  "claim.propose",
  "judgment.propose",
  "judgment.decide",
  "judgment.contradict",
  "world_change.propose",
  "eval.run",
  "rights.check",
  "conflict.analyze",
  "human_review.request",
] as const;

export type CreatorCapability = (typeof CREATOR_CAPABILITIES)[number];

export function creatorCapabilityForEventType(eventType: string): CreatorCapability {
  switch (eventType) {
    case "creator.workspace_started": return "workspace.create";
    case "creator.source_ingested": return "source.ingest";
    case "creator.conversation_turn_recorded": return "conversation.record";
    case "creator.evidence_recorded": return "evidence.inspect_raw";
    case "creator.claim_proposed": return "claim.propose";
    case "creator.judgment_proposed": return "judgment.propose";
    case "creator.judgment_responded": return "judgment.decide";
    case "creator.judgment_contradiction_recorded":
    case "creator.judgment_contradiction_resolved": return "judgment.contradict";
    case "creator.world_change_proposed": return "world_change.propose";
    case "creator.eval_recorded": return "eval.run";
    case "creator.rights_checked": return "rights.check";
    case "creator.conflict_analyzed": return "conflict.analyze";
    case "creator.human_review_requested": return "human_review.request";
    default: throw new Error(`unknown Creator event capability: ${eventType}`);
  }
}

/** Internal knowledge-construction privileges. It cannot serve rider plans or publish truth directly. */
export function createCreatorCapabilityGate(principal: RuntimePrincipal): CapabilityGate<CreatorCapability> {
  return new CapabilityGate(CREATOR_CAPABILITIES, "creator", principal);
}

/** Only for tests. Production must inject an authenticated internal service principal. */
export function createTestCreatorPrincipal(): RuntimePrincipal {
  return { principal_id: "test:creator-runtime", product: "creator", environment: "test", scopes: CREATOR_CAPABILITIES };
}

/** Test-only model/runtime principal. It may propose judgments but can never confirm Tim's judgment. */
export function createTestCreatorAgentPrincipal(): RuntimePrincipal {
  return {
    principal_id: "test:creator-agent",
    product: "creator",
    environment: "test",
    scopes: CREATOR_CAPABILITIES.filter((capability) => capability !== "judgment.decide"),
  };
}

/** Test-only explicit review principal. A real adapter must bind this to authenticated Tim UI action. */
export function createTestCreatorReviewerPrincipal(): RuntimePrincipal {
  return {
    principal_id: "test:tim-reviewer",
    product: "creator",
    environment: "test",
    scopes: ["context.read_private", "conversation.record", "judgment.decide"],
  };
}
