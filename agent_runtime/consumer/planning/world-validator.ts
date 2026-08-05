import { assertNonEmptyString, assertRecord } from "../../shared/canonical.ts";
import { LEG_ROLES, PATH_SOURCES, type PlanningWorld, type UrbanExposure } from "./types.ts";

const WORLD_KEYS = new Set(["fixture_version", "world_revision", "origins", "core_traversals", "candidate_plans"]);
const EXPOSURES = new Set<UrbanExposure>(["low", "medium", "high"]);

function exactKeys(value: Record<string, unknown>, allowed: ReadonlySet<string>, label: string): void {
  const unknown = Object.keys(value).filter((key) => !allowed.has(key));
  if (unknown.length > 0) throw new Error(`${label} has unknown fields: ${unknown.join(", ")}`);
}

function finiteNonNegative(value: unknown, label: string): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new Error(`${label} must be finite and non-negative`);
}

export function assertPlanningWorld(value: unknown): asserts value is PlanningWorld {
  assertRecord(value, "planning world");
  exactKeys(value, WORLD_KEYS, "planning world");
  assertNonEmptyString(value.fixture_version, "fixture_version");
  assertNonEmptyString(value.world_revision, "world_revision");
  assertRecord(value.origins, "origins");
  assertRecord(value.core_traversals, "core_traversals");
  if (!Array.isArray(value.candidate_plans)) throw new Error("candidate_plans must be an array");

  const originRefs = new Set<string>();
  for (const [key, raw] of Object.entries(value.origins)) {
    assertNonEmptyString(key, "origin key");
    assertRecord(raw, `origin ${key}`);
    exactKeys(raw, new Set(["ref", "revision"]), `origin ${key}`);
    assertNonEmptyString(raw.ref, `origin ${key}.ref`);
    assertNonEmptyString(raw.revision, `origin ${key}.revision`);
    if (originRefs.has(raw.ref)) throw new Error(`duplicate origin ref: ${raw.ref}`);
    originRefs.add(raw.ref);
  }

  for (const [key, raw] of Object.entries(value.core_traversals)) {
    assertRecord(raw, `core traversal ${key}`);
    exactKeys(raw, new Set(["traversal_ref", "revision", "geometry_hash", "start_ref", "end_ref"]), `core traversal ${key}`);
    for (const field of ["traversal_ref", "revision", "geometry_hash", "start_ref", "end_ref"] as const) {
      assertNonEmptyString(raw[field], `core traversal ${key}.${field}`);
    }
    if (raw.traversal_ref !== key) throw new Error(`core traversal registry key/ref mismatch: ${key}`);
  }

  const planIds = new Set<string>();
  for (const [index, raw] of value.candidate_plans.entries()) {
    assertRecord(raw, `candidate_plans[${index}]`);
    exactKeys(raw, new Set(["plan_id", "name", "legs", "total_distance_km", "total_climb_m", "estimated_minutes", "urban_exposure", "risk", "unknowns"]), `candidate_plans[${index}]`);
    for (const field of ["plan_id", "name", "risk"] as const) assertNonEmptyString(raw[field], `candidate_plans[${index}].${field}`);
    const planId = raw.plan_id as string;
    if (planIds.has(planId)) throw new Error(`duplicate plan_id: ${planId}`);
    planIds.add(planId);
    finiteNonNegative(raw.total_distance_km, `candidate_plans[${index}].total_distance_km`);
    finiteNonNegative(raw.total_climb_m, `candidate_plans[${index}].total_climb_m`);
    finiteNonNegative(raw.estimated_minutes, `candidate_plans[${index}].estimated_minutes`);
    if (!EXPOSURES.has(raw.urban_exposure as UrbanExposure)) throw new Error(`invalid urban_exposure in candidate_plans[${index}]`);
    if (!Array.isArray(raw.unknowns) || raw.unknowns.some((item) => typeof item !== "string")) throw new Error(`candidate_plans[${index}].unknowns must be strings`);
    if (!Array.isArray(raw.legs) || raw.legs.length === 0) throw new Error(`candidate_plans[${index}].legs must not be empty`);
    for (const [legIndex, legRaw] of raw.legs.entries()) {
      assertRecord(legRaw, `candidate_plans[${index}].legs[${legIndex}]`);
      exactKeys(legRaw, new Set(["role", "source_adapter", "from_ref", "to_ref", "path_ref", "path_revision", "geometry_hash", "summary", "locked"]), `candidate_plans[${index}].legs[${legIndex}]`);
      if (!(LEG_ROLES as readonly unknown[]).includes(legRaw.role)) throw new Error(`invalid leg role at plan ${index}, leg ${legIndex}`);
      if (!(PATH_SOURCES as readonly unknown[]).includes(legRaw.source_adapter)) throw new Error(`invalid path source at plan ${index}, leg ${legIndex}`);
      for (const field of ["from_ref", "to_ref", "path_ref", "path_revision", "geometry_hash", "summary"] as const) assertNonEmptyString(legRaw[field], `plan ${index} leg ${legIndex}.${field}`);
      if (typeof legRaw.locked !== "boolean") throw new Error(`plan ${index} leg ${legIndex}.locked must be boolean`);
    }
  }
}

export function parsePlanningWorld(value: unknown): PlanningWorld {
  assertPlanningWorld(value);
  return value;
}
