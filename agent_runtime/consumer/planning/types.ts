export const AGENT_ACTIONS = ["ASK_ONE_QUESTION", "CALL_TOOL", "PRESENT_CANDIDATES", "NO_RESULT"] as const;
export type AgentAction = (typeof AGENT_ACTIONS)[number];
export const LEG_ROLES = ["access", "connector", "core", "exit", "return"] as const;
export type LegRole = (typeof LEG_ROLES)[number];
export const PATH_SOURCES = ["canonical_traversal", "tencent_bicycling"] as const;
export type PathSource = (typeof PATH_SOURCES)[number];
export type UrbanExposure = "low" | "medium" | "high";

export interface RideRequest {
  origin: string;
  minutes: number;
  max_climb_m: number;
  urban_exposure: UrbanExposure;
}

export interface OriginVersion {
  ref: string;
  revision: string;
}

export interface CoreTraversal {
  traversal_ref: string;
  revision: string;
  geometry_hash: string;
  start_ref: string;
  end_ref: string;
}

export interface PlanLeg {
  role: LegRole;
  source_adapter: PathSource;
  from_ref: string;
  to_ref: string;
  path_ref: string;
  path_revision: string;
  geometry_hash: string;
  summary: string;
  locked: boolean;
}

export interface CandidatePlanTemplate {
  plan_id: string;
  name: string;
  legs: PlanLeg[];
  total_distance_km: number;
  total_climb_m: number;
  estimated_minutes: number;
  urban_exposure: UrbanExposure;
  risk: string;
  unknowns: string[];
}

export interface CandidatePlan extends CandidatePlanTemplate {
  plan_revision: string;
  origin_ref: string;
  origin_revision: string;
  request_hash: string;
  world_revision: string;
  recommendation_reason?: string;
  tradeoff?: string;
}

export interface RejectedCandidate extends CandidatePlan {
  rejection_reasons: string[];
}

export interface PlanningWorld {
  fixture_version: string;
  world_revision: string;
  origins: Record<string, OriginVersion>;
  core_traversals: Record<string, CoreTraversal>;
  candidate_plans: CandidatePlanTemplate[];
}

export interface ShadowResult {
  action: AgentAction;
  candidates: CandidatePlan[];
  rejected_candidates: RejectedCandidate[];
  question?: string;
  rejection_reasons: string[];
  model_turns: number;
  tool_calls: number;
  candidate_generation_count: number;
  runtime_trace: AgentV0RuntimeTrace;
}

export interface AgentV0RuntimeTrace {
  registry_id: string;
  registry_version: string;
  context_manifests: Record<string, unknown>[];
  actions: Record<string, unknown>[];
  tool_calls: Record<string, unknown>[];
  tool_results: Record<string, unknown>[];
  agent_run: Record<string, unknown>;
}
