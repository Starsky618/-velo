import { contentHash } from "../../shared/canonical.ts";

export type RiderCapabilityConfidence = "insufficient" | "low" | "medium" | "high";
export type RiderCapabilityFreshness = "none" | "fresh" | "stale";
export type RiderCapabilityReasonCode =
  | "no_usable_activities"
  | "too_few_usable_activities"
  | "history_stale"
  | "insufficient_elevation_history";

export interface RiderCapabilitySnapshot {
  schema_version: "0.1.0";
  snapshot_id: string;
  generated_at: string;
  source_revision: string;
  window_days: number;
  source_activity_count: number;
  excluded_activity_count: number;
  elevation_activity_count: number;
  data_complete: boolean;
  confidence: RiderCapabilityConfidence;
  freshness: RiderCapabilityFreshness;
  latest_activity_at: string | null;
  typical_distance_km: number | null;
  upper_observed_distance_km: number | null;
  typical_duration_minutes: number | null;
  typical_climb_m_per_km: number | null;
  source_types: string[];
  reason_codes: RiderCapabilityReasonCode[];
  privacy: {
    exact_coordinates_included: false;
    raw_activity_tracks_included: false;
    health_metrics_included: false;
  };
}

export interface RiderRouteHistorySnapshot {
  source_revision: string;
  calculated_at: string;
  window_days: number;
  source_activity_count: number;
  excluded_activity_count: number;
  elevation_activity_count: number;
  data_complete: boolean;
  confidence: RiderCapabilityConfidence;
  freshness: RiderCapabilityFreshness;
  latest_activity_at?: string;
  typical_distance_km?: number;
  upper_observed_distance_km?: number;
  typical_duration_minutes?: number;
  typical_climb_m_per_km?: number;
  source_types: string[];
  reason_codes: RiderCapabilityReasonCode[];
}

export interface RiderTaskContextPacket {
  schema_version: "0.1.0";
  packet_id: string;
  packet_environment: "test" | "shadow" | "production";
  generated_at: string;
  source_revision: string;
  session_id: string;
  user_ref: string;
  authorization: {
    purpose: string;
    task_mode: "discover" | "understand" | "compare" | "revise" | "execute";
    allowed_sections: ["performance_context"];
    data_scope_refs: string[];
    sensitive_location_policy: "opaque_ref_only";
  };
  current_request: { request_summary: string };
  bike_profiles: [];
  performance_context: { route_history_snapshot: RiderRouteHistorySnapshot };
  saved_place_handles: [];
  familiarity: [];
  explicit_preferences: [];
  relevant_history_summaries: [];
  explicit_memory_items: [];
  unknowns: [];
  omitted_sections: Array<{ section: string; reason: "privacy" | "unavailable" }>;
  privacy: {
    exact_coordinates_included: false;
    raw_activity_tracks_included: false;
    full_chat_transcript_included: false;
  };
  metadata: { "x-runtime": "rider-capability-v0" };
}

export interface CompileRiderTaskContextInput {
  snapshot: RiderCapabilitySnapshot;
  packet_environment: RiderTaskContextPacket["packet_environment"];
  session_id: string;
  user_ref: string;
  purpose: string;
  task_mode: RiderTaskContextPacket["authorization"]["task_mode"];
  request_summary: string;
  data_scope_refs: string[];
}

const CONFIDENCE = new Set<RiderCapabilityConfidence>(["insufficient", "low", "medium", "high"]);
const FRESHNESS = new Set<RiderCapabilityFreshness>(["none", "fresh", "stale"]);
const REASON_CODES = new Set<RiderCapabilityReasonCode>([
  "no_usable_activities",
  "too_few_usable_activities",
  "history_stale",
  "insufficient_elevation_history",
]);

function requireText(value: string, label: string): void {
  if (value.trim() === "") throw new Error(`${label} must be non-empty`);
}

function requireTimestamp(value: string, label: string): void {
  if (Number.isNaN(new Date(value).valueOf())) throw new Error(`${label} must be a timestamp`);
}

function requireNonNegative(value: number | null, label: string): void {
  if (value !== null && (!Number.isFinite(value) || value < 0)) throw new Error(`${label} must be non-negative or null`);
}

export function assertRiderCapabilitySnapshot(snapshot: RiderCapabilitySnapshot): void {
  if (snapshot.schema_version !== "0.1.0") throw new Error("unsupported Rider capability snapshot version");
  requireText(snapshot.snapshot_id, "snapshot_id");
  requireText(snapshot.source_revision, "source_revision");
  if (!/^rider-capability:[A-Za-z0-9._:-]+$/.test(snapshot.snapshot_id)) {
    throw new Error("invalid Rider capability snapshot_id");
  }
  if (!/^activity-history:sha256:[a-f0-9]{64}$/.test(snapshot.source_revision)) {
    throw new Error("invalid Rider capability source_revision");
  }
  requireTimestamp(snapshot.generated_at, "generated_at");
  if (snapshot.latest_activity_at !== null) requireTimestamp(snapshot.latest_activity_at, "latest_activity_at");
  for (const [label, value] of Object.entries({
    window_days: snapshot.window_days,
    source_activity_count: snapshot.source_activity_count,
    excluded_activity_count: snapshot.excluded_activity_count,
    elevation_activity_count: snapshot.elevation_activity_count,
  })) {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${label} must be a non-negative integer`);
  }
  if (snapshot.window_days < 1) throw new Error("window_days must be positive");
  if (snapshot.elevation_activity_count > snapshot.source_activity_count) {
    throw new Error("elevation_activity_count cannot exceed source_activity_count");
  }
  if (!CONFIDENCE.has(snapshot.confidence)) throw new Error("invalid Rider capability confidence");
  if (!FRESHNESS.has(snapshot.freshness)) throw new Error("invalid Rider capability freshness");
  if (snapshot.reason_codes.some((code) => !REASON_CODES.has(code))) throw new Error("invalid Rider capability reason code");
  if (snapshot.source_types.some((source) => source.trim() === "")) throw new Error("source_types cannot contain blank values");
  requireNonNegative(snapshot.typical_distance_km, "typical_distance_km");
  requireNonNegative(snapshot.upper_observed_distance_km, "upper_observed_distance_km");
  requireNonNegative(snapshot.typical_duration_minutes, "typical_duration_minutes");
  requireNonNegative(snapshot.typical_climb_m_per_km, "typical_climb_m_per_km");
  if (snapshot.typical_distance_km !== null && snapshot.upper_observed_distance_km !== null
    && snapshot.upper_observed_distance_km < snapshot.typical_distance_km) {
    throw new Error("upper_observed_distance_km cannot be below typical_distance_km");
  }
  if (snapshot.data_complete !== ["medium", "high"].includes(snapshot.confidence)) {
    throw new Error("data_complete must match medium/high confidence");
  }
  if (snapshot.source_activity_count === 0 && (snapshot.confidence !== "insufficient" || snapshot.freshness !== "none")) {
    throw new Error("empty history must fail closed");
  }
  if (snapshot.source_activity_count === 0 && [
    snapshot.latest_activity_at,
    snapshot.typical_distance_km,
    snapshot.upper_observed_distance_km,
    snapshot.typical_duration_minutes,
    snapshot.typical_climb_m_per_km,
  ].some((value) => value !== null)) {
    throw new Error("empty history cannot contain observed capability metrics");
  }
  if (Object.values(snapshot.privacy).some((value) => value !== false)) {
    throw new Error("Rider capability snapshot exposed forbidden private data");
  }
}

export function compileRiderTaskContext(input: CompileRiderTaskContextInput): RiderTaskContextPacket {
  assertRiderCapabilitySnapshot(input.snapshot);
  requireText(input.session_id, "session_id");
  requireText(input.user_ref, "user_ref");
  requireText(input.purpose, "purpose");
  requireText(input.request_summary, "request_summary");
  if (input.data_scope_refs.length === 0 || input.data_scope_refs.some((ref) => ref.trim() === "")) {
    throw new Error("data_scope_refs must contain an explicit scope");
  }
  const snapshot = input.snapshot;
  const routeHistory: RiderRouteHistorySnapshot = {
    source_revision: snapshot.source_revision,
    calculated_at: snapshot.generated_at,
    window_days: snapshot.window_days,
    source_activity_count: snapshot.source_activity_count,
    excluded_activity_count: snapshot.excluded_activity_count,
    elevation_activity_count: snapshot.elevation_activity_count,
    data_complete: snapshot.data_complete,
    confidence: snapshot.confidence,
    freshness: snapshot.freshness,
    ...(snapshot.latest_activity_at === null ? {} : { latest_activity_at: snapshot.latest_activity_at }),
    ...(snapshot.typical_distance_km === null ? {} : { typical_distance_km: snapshot.typical_distance_km }),
    ...(snapshot.upper_observed_distance_km === null ? {} : { upper_observed_distance_km: snapshot.upper_observed_distance_km }),
    ...(snapshot.typical_duration_minutes === null ? {} : { typical_duration_minutes: snapshot.typical_duration_minutes }),
    ...(snapshot.typical_climb_m_per_km === null ? {} : { typical_climb_m_per_km: snapshot.typical_climb_m_per_km }),
    source_types: [...new Set(snapshot.source_types)].sort(),
    reason_codes: [...new Set(snapshot.reason_codes)],
  };
  const identity = {
    session_id: input.session_id,
    user_ref: input.user_ref,
    purpose: input.purpose,
    task_mode: input.task_mode,
    request_summary: input.request_summary,
    data_scope_refs: [...new Set(input.data_scope_refs)].sort(),
    source_revision: snapshot.source_revision,
  };
  return {
    schema_version: "0.1.0",
    packet_id: `rider-context:${contentHash(identity).slice(-24)}`,
    packet_environment: input.packet_environment,
    generated_at: snapshot.generated_at,
    source_revision: snapshot.source_revision,
    session_id: input.session_id,
    user_ref: input.user_ref,
    authorization: {
      purpose: input.purpose,
      task_mode: input.task_mode,
      allowed_sections: ["performance_context"],
      data_scope_refs: [...new Set(input.data_scope_refs)].sort(),
      sensitive_location_policy: "opaque_ref_only",
    },
    current_request: { request_summary: input.request_summary },
    bike_profiles: [],
    performance_context: { route_history_snapshot: routeHistory },
    saved_place_handles: [],
    familiarity: [],
    explicit_preferences: [],
    relevant_history_summaries: [],
    explicit_memory_items: [],
    unknowns: [],
    omitted_sections: [
      { section: "raw_activity_tracks", reason: "privacy" },
      ...(snapshot.typical_climb_m_per_km === null ? [{ section: "climb_history", reason: "unavailable" as const }] : []),
    ],
    privacy: {
      exact_coordinates_included: false,
      raw_activity_tracks_included: false,
      full_chat_transcript_included: false,
    },
    metadata: { "x-runtime": "rider-capability-v0" },
  };
}
