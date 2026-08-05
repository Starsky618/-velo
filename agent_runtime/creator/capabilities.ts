import { CapabilityGate, type RuntimePrincipal } from "../shared/capability-gate.ts";

export const CREATOR_CAPABILITIES = [
  "workspace.create",
  "source.ingest",
  "evidence.inspect_raw",
  "claim.propose",
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
