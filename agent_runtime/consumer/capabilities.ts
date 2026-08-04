import { CapabilityGate } from "../shared/capability-gate.ts";

export const RIDER_CAPABILITIES = [
  "world.read_published",
  "plan.generate",
  "plan.validate",
  "plan.compare",
  "plan.revise",
  "export.prepare",
  "feedback.propose",
] as const;

export type RiderCapability = (typeof RIDER_CAPABILITIES)[number];

/** Rider-facing privileges. It cannot inspect raw evidence or mutate canonical knowledge. */
export function createRiderCapabilityGate(): CapabilityGate<RiderCapability> {
  return new CapabilityGate(RIDER_CAPABILITIES);
}
