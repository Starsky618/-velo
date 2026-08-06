import { CapabilityGate, type RuntimePrincipal } from "../shared/capability-gate.ts";

export const RIDER_CAPABILITIES = [
  "user_context.read_authorized",
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
export function createRiderCapabilityGate(principal: RuntimePrincipal): CapabilityGate<RiderCapability> {
  return new CapabilityGate(RIDER_CAPABILITIES, "rider", principal);
}

/** Only for the non-networked fixture/shadow adapter. Production must inject an authenticated service principal. */
export function createShadowRiderPrincipal(): RuntimePrincipal {
  return { principal_id: "shadow:rider-runtime", product: "rider", environment: "shadow", scopes: RIDER_CAPABILITIES };
}
