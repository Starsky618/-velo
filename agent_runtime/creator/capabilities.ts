import { CapabilityGate, type RuntimePrincipal } from "../shared/capability-gate.ts";

export const CREATOR_CAPABILITIES = [
  "workspace.create",
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
    scopes: ["conversation.record", "judgment.decide"],
  };
}
