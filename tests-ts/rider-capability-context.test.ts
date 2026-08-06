import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { Ajv2020 } from "ajv/dist/2020.js";
import type { FormatsPlugin } from "ajv-formats";

import { createRiderCapabilityGate, createShadowRiderPrincipal } from "../agent_runtime/consumer/capabilities.ts";
import {
  compileRiderTaskContext,
  type RiderCapabilitySnapshot,
} from "../agent_runtime/consumer/context/rider-task-context.ts";
import { AgentV0RuntimeController } from "../agent_runtime/consumer/runtime/agent-v0.ts";
import { createCreatorCapabilityGate, createTestCreatorPrincipal } from "../agent_runtime/creator/capabilities.ts";

const snapshot: RiderCapabilitySnapshot = {
  schema_version: "0.1.0",
  snapshot_id: "rider-capability:fixture-r1",
  generated_at: "2026-08-06T12:00:00.000Z",
  source_revision: `activity-history:sha256:${"a".repeat(64)}`,
  window_days: 42,
  source_activity_count: 4,
  excluded_activity_count: 1,
  elevation_activity_count: 4,
  data_complete: true,
  confidence: "medium",
  freshness: "fresh",
  latest_activity_at: "2026-08-05T12:00:00.000Z",
  typical_distance_km: 25,
  upper_observed_distance_km: 32.5,
  typical_duration_minutes: 150,
  typical_climb_m_per_km: 10,
  source_types: ["fit", "gpx"],
  reason_codes: [],
  privacy: {
    exact_coordinates_included: false,
    raw_activity_tracks_included: false,
    health_metrics_included: false,
  },
};

const addFormats = createRequire(import.meta.url)("ajv-formats") as FormatsPlugin;

async function assertValidRiderPacket(packet: unknown): Promise<void> {
  const contractDirectory = new URL("../contracts/agent_v0/", import.meta.url);
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  for (const filename of ["common.schema.json", "rider_context_packet.schema.json"]) {
    const schema = JSON.parse(await readFile(new URL(filename, contractDirectory), "utf8")) as Record<string, unknown>;
    ajv.addSchema(schema);
  }
  const validate = ajv.getSchema("https://schemas.velo.invalid/agent_v0/rider_context_packet.schema.json");
  assert.ok(validate);
  assert.equal(validate(packet), true, JSON.stringify(validate.errors, null, 2));
}

test("consumer compiles the domain snapshot into a purpose-bounded rider context packet", async () => {
  const packet = compileRiderTaskContext({
    snapshot,
    packet_environment: "test",
    session_id: "session:rider-context-test",
    user_ref: "user:rider-context-test",
    purpose: "Bound route candidates for the current planning request.",
    task_mode: "compare",
    request_summary: "周末轻松公路骑行",
    data_scope_refs: ["scope:current-rider-route-planning"],
  });

  assert.equal(packet.performance_context.route_history_snapshot?.typical_distance_km, 25);
  assert.equal(packet.performance_context.route_history_snapshot?.source_revision, snapshot.source_revision);
  assert.deepEqual(packet.authorization.allowed_sections, ["performance_context"]);
  assert.deepEqual(packet.relevant_history_summaries, []);
  assert.equal(packet.privacy.exact_coordinates_included, false);
  assert.equal(packet.privacy.raw_activity_tracks_included, false);
  assert.equal("health_metrics" in packet.performance_context, false);
  await assertValidRiderPacket(packet);
});

test("real rider packet enters every model context with its exact revision and hash", () => {
  const packet = compileRiderTaskContext({
    snapshot,
    packet_environment: "test",
    session_id: "session:rider-context-runtime",
    user_ref: "user:rider-context-runtime",
    purpose: "Use authorized ride history for route comparison.",
    task_mode: "compare",
    request_summary: "比较两条候选路线",
    data_scope_refs: ["scope:route-comparison"],
  });
  const runtime = new AgentV0RuntimeController({
    session_id: packet.session_id,
    session_revision: 1,
    request_ref: "request:rider-context-runtime",
    world_revision: "world:test-r1",
    rider_task_context: packet,
    now_ms: () => Date.parse("2026-08-06T12:01:00.000Z"),
  });

  runtime.beginTurn("compare");

  const manifest = runtime.trace.context_manifests[0]!;
  const packetRefs = manifest.source_packet_refs as Array<Record<string, unknown>>;
  const riderRef = packetRefs.find((item) => item.packet_type === "rider_context_packet");
  assert.equal(riderRef?.packet_id, packet.packet_id);
  assert.equal(riderRef?.source_revision, snapshot.source_revision);
  assert.equal((manifest.included_sections as string[]).includes("authorized_rider_route_history"), true);
});

test("rider can read its authorized context while Creator remains denied", () => {
  const rider = createRiderCapabilityGate(createShadowRiderPrincipal());
  const creator = createCreatorCapabilityGate(createTestCreatorPrincipal());

  assert.equal(rider.allows("user_context.read_authorized"), true);
  assert.equal(creator.allows("user_context.read_authorized"), false);
  assert.equal(createRiderCapabilityGate(createTestCreatorPrincipal()).allows("user_context.read_authorized"), false);
});

test("consumer rejects a contradictory empty-history snapshot before model context", () => {
  const contradictory = {
    ...snapshot,
    source_activity_count: 0,
    elevation_activity_count: 0,
    data_complete: false,
    confidence: "insufficient" as const,
    freshness: "none" as const,
    latest_activity_at: null,
  };

  assert.throws(
    () => compileRiderTaskContext({
      snapshot: contradictory,
      packet_environment: "test",
      session_id: "session:contradictory-history",
      user_ref: "user:contradictory-history",
      purpose: "Reject invalid route history before model use.",
      task_mode: "compare",
      request_summary: "比较路线",
      data_scope_refs: ["scope:route-comparison"],
    }),
    /empty history cannot contain observed capability metrics/,
  );
});
