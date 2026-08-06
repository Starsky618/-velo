import { CapabilityGate, type RuntimePrincipal } from "../shared/capability-gate.ts";

export const CREATOR_CAPABILITIES = [
  "workspace.create",
  "context.read_private",
  "source.ingest",
  "conversation.record",
  "interpretation.propose",
  "task.update",
  "evidence.inspect_raw",
  "claim.propose",
  "judgment.propose",
  "judgment.promote",
  "judgment.decide",
  "judgment.contradict",
  "world_change.propose",
  "eval.run",
  "behavior.calibrate",
  "behavior.calibrate.agent_assessed",
  "behavior.calibrate.mechanical",
  "behavior.calibrate.tim_confirmed",
  "behavior.calibrate.real_world",
  "rights.check",
  "conflict.analyze",
  "human_review.request",
] as const;

export type CreatorCapability = (typeof CREATOR_CAPABILITIES)[number];

export function creatorCalibrationAuthorityCapability(
  authority: "agent_assessed" | "mechanical" | "tim_confirmed" | "real_world",
): CreatorCapability {
  return `behavior.calibrate.${authority}`;
}

export function creatorCapabilityForEventType(eventType: string): CreatorCapability {
  switch (eventType) {
    case "creator.workspace_started": return "workspace.create";
    case "creator.source_ingested": return "source.ingest";
    case "creator.conversation_turn_recorded": return "conversation.record";
    case "creator.turn_interpretation_proposed": return "interpretation.propose";
    case "creator.task_state_changed": return "task.update";
    case "creator.behavior_calibration_recorded": return "behavior.calibrate";
    case "creator.evidence_recorded": return "evidence.inspect_raw";
    case "creator.claim_proposed": return "claim.propose";
    case "creator.judgment_proposed": return "judgment.propose";
    case "creator.judgment_promotion_proposed": return "judgment.promote";
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

export function creatorCapabilityForEvent(event: { type: string; authority?: unknown }): CreatorCapability {
  if (event.type === "creator.behavior_calibration_recorded") {
    if (!["agent_assessed", "mechanical", "tim_confirmed", "real_world"].includes(event.authority as string)) {
      throw new Error("invalid Creator calibration authority capability");
    }
    return creatorCalibrationAuthorityCapability(event.authority as Parameters<typeof creatorCalibrationAuthorityCapability>[0]);
  }
  return creatorCapabilityForEventType(event.type);
}

/** Internal knowledge-construction privileges. It cannot serve rider plans or publish truth directly. */
export function createCreatorCapabilityGate(principal: RuntimePrincipal): CapabilityGate<CreatorCapability> {
  return new CapabilityGate(CREATOR_CAPABILITIES, "creator", principal);
}

/** Only for tests. Production must inject an authenticated internal service principal. */
export function createTestCreatorPrincipal(): RuntimePrincipal {
  return { principal_id: "test:creator-runtime", product: "creator", environment: "test", scopes: CREATOR_CAPABILITIES };
}

/** Test-only interpretation runtime principal. It cannot promote, calibrate or decide a judgment. */
export function createTestCreatorAgentPrincipal(): RuntimePrincipal {
  return {
    principal_id: "test:creator-agent",
    product: "creator",
    environment: "test",
    scopes: ["context.read_private", "conversation.record", "interpretation.propose", "task.update"],
  };
}

/** Test-only compatibility runtime for evidence-backed domain judgments. Never use it for conversation interpretation. */
export function createTestCreatorLegacyAgentPrincipal(): RuntimePrincipal {
  return {
    principal_id: "test:creator-legacy-evidence-agent",
    product: "creator",
    environment: "test",
    scopes: CREATOR_CAPABILITIES.filter((capability) => (
      !["judgment.promote", "judgment.decide"].includes(capability)
      && !capability.startsWith("behavior.calibrate")
    )),
  };
}

/** Test-only deterministic promotion service; the interpretation model never receives this capability. */
export function createTestCreatorPromotionPrincipal(): RuntimePrincipal {
  return {
    principal_id: "test:creator-promotion-engine",
    product: "creator",
    environment: "test",
    scopes: ["context.read_private", "judgment.promote"],
  };
}

/** Test-only outcome/calibration adapter; the interpretation model never receives this capability. */
export function createTestCreatorCalibrationPrincipal(): RuntimePrincipal {
  return {
    principal_id: "test:creator-calibration-adapter",
    product: "creator",
    environment: "test",
    scopes: [
      "context.read_private",
      "behavior.calibrate.agent_assessed", "behavior.calibrate.mechanical",
    ],
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
