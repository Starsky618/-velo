import { CapabilityGate } from "../shared/capability-gate.ts";

export const CREATOR_CAPABILITIES = [
  "source.ingest",
  "evidence.inspect_raw",
  "claim.propose",
  "world_change.propose",
  "eval.run",
] as const;

export type CreatorCapability = (typeof CREATOR_CAPABILITIES)[number];

/** Internal knowledge-construction privileges. It cannot serve rider plans or publish truth directly. */
export function createCreatorCapabilityGate(): CapabilityGate<CreatorCapability> {
  return new CapabilityGate(CREATOR_CAPABILITIES);
}
