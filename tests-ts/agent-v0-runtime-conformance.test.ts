import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { Ajv2020 } from "ajv/dist/2020.js";
import type { FormatsPlugin } from "ajv-formats";

import { TianlongshanShadowAgent, type ShadowDecisionModel } from "../agent_runtime/consumer/planning/shadow.ts";
import type { PlanningWorld } from "../agent_runtime/consumer/planning/types.ts";
import { compileRiderContext } from "../agent_runtime/consumer/context/compiler.ts";
import {
  createInMemorySessionRuntimePort,
  SessionCommitReconciliationRequiredError,
  type SessionRuntimePort,
} from "../agent_runtime/consumer/session/committer.ts";
import { replaySession } from "../agent_runtime/consumer/session/engine.ts";
import type { RiderSessionEvent } from "../agent_runtime/consumer/session/types.ts";
import { contentHash } from "../agent_runtime/shared/canonical.ts";
import { AgentDeadlineExceededError, AgentV0RuntimeController } from "../agent_runtime/consumer/runtime/agent-v0.ts";

const contractDirectory = new URL("../contracts/agent_v0/", import.meta.url);
const addFormats = createRequire(import.meta.url)("ajv-formats") as FormatsPlugin;
const fixtureUrl = new URL("../tests/fixtures/ride_planning/tianlongshan_world.json", import.meta.url);
const schemaFiles = [
  "common.schema.json",
  "session_state.schema.json",
  "map_action.schema.json",
  "context_manifest.schema.json",
  "agent_action.schema.json",
  "agent_run.schema.json",
  "tool_call.schema.json",
  "tool_result.schema.json",
] as const;

async function validator() {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  for (const filename of schemaFiles) {
    const schema = JSON.parse(await readFile(new URL(filename, contractDirectory), "utf8")) as Record<string, unknown>;
    ajv.addSchema(schema);
  }
  return (filename: (typeof schemaFiles)[number], value: unknown): void => {
    const schemaId = `https://schemas.velo.invalid/agent_v0/${filename}`;
    const validate = ajv.getSchema(schemaId);
    assert.ok(validate, `missing validator for ${filename}`);
    assert.equal(validate(value), true, JSON.stringify(validate.errors, null, 2));
  };
}

test("TypeScript shadow emits schema-valid Agent v0 runtime artifacts from the checked-in registry", async () => {
  const validate = await validator();
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  const result = await new TianlongshanShadowAgent(world).run({
    origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low",
  });

  assert.equal(result.runtime_trace.registry_id, "tool-registry.agent-v0");
  assert.deepEqual(result.runtime_trace.tool_calls.map((call) => call.tool_name), [
    "planning.retrieve_world_context", "planning.generate_candidate_plans",
  ]);
  assert.equal(result.runtime_trace.context_manifests.length, result.model_turns);
  assert.equal(result.runtime_trace.actions.length, result.model_turns);
  for (const manifest of result.runtime_trace.context_manifests) validate("context_manifest.schema.json", manifest);
  for (const action of result.runtime_trace.actions) validate("agent_action.schema.json", action);
  for (const call of result.runtime_trace.tool_calls) validate("tool_call.schema.json", call);
  for (const observation of result.runtime_trace.tool_results) validate("tool_result.schema.json", observation);
  validate("agent_run.schema.json", result.runtime_trace.agent_run);

  const run = result.runtime_trace.agent_run;
  assert.ok(new Date(run.started_at as string) < new Date((run.budget as { limits: { wall_clock_deadline: string } }).limits.wall_clock_deadline));
  assert.deepEqual(run.session_commit, { commit_status: "committed", expected_base_revision: 1, committed_revision: 2 });
  const presentationManifest = result.runtime_trace.context_manifests.at(-1)!;
  const presentationAction = result.runtime_trace.actions.at(-1)!;
  assert.deepEqual(presentationManifest.plan_revision_refs, (presentationAction.payload as { candidates: Array<{ plan_revision_ref: unknown }> }).candidates.map((candidate) => candidate.plan_revision_ref));
  assert.equal(["tool.observation.candidate_plan_set", "plan.candidate_summaries", "plan.validation_summaries"].every(
    (section) => (presentationManifest.included_sections as string[]).includes(section),
  ), true);
  const worldPacketRefs = [
    ...result.runtime_trace.context_manifests.flatMap((manifest) => manifest.source_packet_refs as Array<Record<string, unknown>>),
    ...result.runtime_trace.tool_results.flatMap((observation) => observation.result_refs as Array<Record<string, unknown>>),
  ].filter((ref) => ref.packet_type === "world_fact_packet");
  const hashesByPacket = new Map<string, Set<string>>();
  for (const ref of worldPacketRefs) {
    const hashes = hashesByPacket.get(ref.packet_id as string) ?? new Set<string>();
    hashes.add(ref.content_hash as string);
    hashesByPacket.set(ref.packet_id as string, hashes);
  }
  assert.equal([...hashesByPacket.values()].every((hashes) => hashes.size === 1), true);
});

test("replayed rider decisions are included in every runtime ContextManifest", async () => {
  const statement = "城区暴露必须为 low";
  const events: RiderSessionEvent[] = [
    { schema_version: 1, event_id: "s1", session_id: "session:context", base_revision: 0, occurred_at: "2026-08-04T08:00:00.000Z", type: "session.started", mission: "规划骑行", mainline_topic_id: "mainline" },
    { schema_version: 1, event_id: "s2", session_id: "session:context", base_revision: 1, occurred_at: "2026-08-04T08:01:00.000Z", type: "turn.recorded", turn_id: "turn:preference", topic_id: "mainline", role: "user", source_role: "user", authorship_basis: "direct_unquoted_message", content: "我不要城区主干道" },
    { schema_version: 1, event_id: "s3", session_id: "session:context", base_revision: 2, occurred_at: "2026-08-04T08:02:00.000Z", type: "decision.proposed", decision_id: "decision:urban", decision_key: "urban_exposure", topic_id: "mainline", statement, typed_value: "low", source_turn_refs: ["turn:preference"] },
    { schema_version: 1, event_id: "s4", session_id: "session:context", base_revision: 3, occurred_at: "2026-08-04T08:03:00.000Z", type: "turn.recorded", turn_id: "turn:confirm", topic_id: "mainline", role: "user", source_role: "user", authorship_basis: "manual_review", content: "确认", interaction: { kind: "decision_response", decision_id: "decision:urban", statement_hash: contentHash(statement), response: "user_confirmed" } },
    { schema_version: 1, event_id: "s5", session_id: "session:context", base_revision: 4, occurred_at: "2026-08-04T08:04:00.000Z", type: "decision.responded", decision_id: "decision:urban", response_turn_id: "turn:confirm", response: "user_confirmed", expected_statement_hash: contentHash(statement) },
  ];
  const sessionView = replaySession(events);
  const riderContext = compileRiderContext(sessionView);
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  const result = await new TianlongshanShadowAgent(world).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low" },
    {
      session_id: "session:context", session_revision: 5, request_ref: "turn:current", rider_context: riderContext,
      session_port: createInMemorySessionRuntimePort(sessionView),
    },
  );
  for (const manifest of result.runtime_trace.context_manifests) {
    assert.equal((manifest.memory_item_refs as string[]).includes("decision:urban"), true);
    assert.equal((manifest.source_packet_refs as Array<{ packet_type: string }>).some((ref) => ref.packet_type === "rider_context_packet"), false);
  }
  const conflictPort = createInMemorySessionRuntimePort(sessionView);
  const conflict = await new TianlongshanShadowAgent(world).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "high" },
    {
      session_id: "session:context", session_revision: 5, request_ref: "turn:conflict", rider_context: riderContext,
      session_port: conflictPort,
    },
  );
  assert.equal(conflict.action, "ASK_ONE_QUESTION");
  assert.match(conflict.question ?? "", /之前确认城区暴露为 low/);
  assert.equal(conflict.tool_calls, 0);
  const questionPayload = conflict.runtime_trace.actions[0]!.payload as Record<string, unknown>;
  assert.equal(questionPayload.question_kind, "route_preference");
  assert.equal(questionPayload.answer_mode, "yes_no");
  assert.deepEqual(questionPayload.blocking_unknown_refs, ["unknown:preference-conflict:decision:urban"]);
  const preparedView = await conflictPort.readView();
  assert.deepEqual(preparedView.unknowns, [{
    unknown_id: "unknown:preference-conflict:decision:urban",
    unknown_kind: "session_consistency",
    blocking: true,
    user_safe_summary: "本次城区暴露偏好与骑手已确认的长期偏好冲突。",
    related_ref: "decision:urban",
  }]);
});

test("stale session commit cannot produce a completed result or expose old candidates", async () => {
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  const basePort = createInMemorySessionRuntimePort(replaySession([{
    schema_version: 1, event_id: "stale-start", session_id: "session:tianlongshan-shadow", base_revision: 0,
    occurred_at: "2026-08-05T08:00:00.000Z", type: "session.started", mission: "stale test", mainline_topic_id: "mainline",
  }]));
  const rejectStale: SessionRuntimePort = {
    readView: () => basePort.readView(),
    ensureUnknown: (...args) => basePort.ensureUnknown(...args),
    async commitAgentTurn(_content, expectedBaseRevision) {
      return { commit_status: "rejected_stale", expected_base_revision: expectedBaseRevision };
    },
  };
  const result = await new TianlongshanShadowAgent(world).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low" },
    { session_port: rejectStale },
  );
  assert.equal(result.action, "NO_RESULT");
  assert.equal(result.candidates.length, 0);
  assert.match(result.rejection_reasons[0] ?? "", /旧结果未提交/);
  assert.equal(result.runtime_trace.agent_run.stop_reason, "deterministic_error");
  assert.deepEqual(result.runtime_trace.agent_run.session_commit, {
    commit_status: "rejected_stale", expected_base_revision: 1,
  });
});

test("a model that crosses the wall-clock deadline cannot complete or commit", async () => {
  const validate = await validator();
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  let now = Date.parse("2026-08-05T08:00:00.000Z");
  const crossingModel: ShadowDecisionModel = {
    decide(input) {
      if (input.phase === "retrieve_world") return { action_type: "propose_tool_call", tool_name: "planning.retrieve_world_context" };
      if (input.phase === "generate_candidates") return { action_type: "propose_tool_call", tool_name: "planning.generate_candidate_plans" };
      if (input.phase === "present") {
        now += 31_000;
        return { action_type: "present_valid_candidates", message: "这个超时结果不应被采用。" };
      }
      return {
        action_type: "ask_clarifying_question", question: "请补充起点。", question_kind: "location",
        answer_mode: "free_text", blocking_unknown_refs: ["unknown:exact-origin"],
      };
    },
  };
  const result = await new TianlongshanShadowAgent(world, crossingModel).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low" },
    { now_ms: () => now },
  );
  assert.equal(result.action, "NO_RESULT");
  assert.equal(result.candidates.length, 0);
  assert.equal(result.runtime_trace.agent_run.stop_reason, "budget_exceeded");
  assert.deepEqual(result.runtime_trace.agent_run.session_commit, {
    commit_status: "not_attempted", expected_base_revision: 1,
  });
  assert.equal(result.runtime_trace.actions.length, result.model_turns);
  assert.equal(result.runtime_trace.context_manifests.length, result.model_turns);
  validate("agent_action.schema.json", result.runtime_trace.actions.at(-1));
  validate("agent_run.schema.json", result.runtime_trace.agent_run);
});

test("a tool that crosses the run deadline emits one terminal timeout observation", async () => {
  const validate = await validator();
  let now = Date.parse("2026-08-05T09:00:00.000Z");
  const runtime = new AgentV0RuntimeController({
    session_id: "session:tool-timeout", session_revision: 1, request_ref: "turn:tool-timeout",
    world_revision: "world:tianlongshan-r1", now_ms: () => now,
  });
  const turn = runtime.beginTurn("understand");
  await assert.rejects(
    runtime.invokeTool(turn, "planning.retrieve_world_context", "world-request:timeout", () => {
      now += 31_000;
      return { world_revision: "world:tianlongshan-r1" };
    }),
    AgentDeadlineExceededError,
  );
  runtime.finish("deterministic_error", undefined);
  assert.equal(runtime.trace.tool_calls.length, 1);
  assert.equal(runtime.trace.tool_results.length, 1);
  assert.deepEqual({
    status: runtime.trace.tool_results[0]!.result_status,
    code: runtime.trace.tool_results[0]!.result_code,
    reason: runtime.trace.tool_results[0]!.domain_reason_code,
    finality: runtime.trace.tool_results[0]!.result_finality,
  }, {
    status: "timed_out", code: "TOOL_TIMEOUT", reason: "RUN_DEADLINE_EXCEEDED", finality: "TERMINAL",
  });
  validate("context_manifest.schema.json", runtime.trace.context_manifests[0]);
  validate("agent_action.schema.json", runtime.trace.actions[0]);
  validate("tool_call.schema.json", runtime.trace.tool_calls[0]);
  validate("tool_result.schema.json", runtime.trace.tool_results[0]);
  validate("agent_run.schema.json", runtime.trace.agent_run);
});

test("the Session mutation guard prevents a commit that reaches the deadline", async () => {
  const validate = await validator();
  const initialView = replaySession([{
    schema_version: 1, event_id: "deadline-start", session_id: "session:commit-deadline", base_revision: 0,
    occurred_at: "2026-08-05T10:00:00.000Z", type: "session.started", mission: "deadline test", mainline_topic_id: "mainline",
  }]);
  const reducerPort = createInMemorySessionRuntimePort(initialView);
  let now = Date.parse("2026-08-05T10:00:00.000Z");
  let receivedSignal = false;
  const deadlinePort: SessionRuntimePort = {
    readView: () => reducerPort.readView(),
    ensureUnknown: (...args) => reducerPort.ensureUnknown(...args),
    commitAgentTurn(content, expectedBaseRevision, guard) {
      receivedSignal = guard.signal instanceof AbortSignal;
      now += 31_000;
      return reducerPort.commitAgentTurn(content, expectedBaseRevision, guard);
    },
  };
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  const result = await new TianlongshanShadowAgent(world).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low" },
    {
      session_id: "session:commit-deadline", session_revision: 1,
      session_port: deadlinePort, now_ms: () => now,
    },
  );
  assert.equal(receivedSignal, true);
  assert.equal(result.runtime_trace.agent_run.stop_reason, "budget_exceeded");
  assert.deepEqual(result.runtime_trace.agent_run.session_commit, {
    commit_status: "not_attempted", expected_base_revision: 1,
  });
  assert.equal((await reducerPort.readView()).turns.length, 0);
  validate("agent_run.schema.json", result.runtime_trace.agent_run);
});

test("a commit that crossed the irreversible boundary keeps its exact receipt after deadline", async () => {
  const validate = await validator();
  const initialView = replaySession([{
    schema_version: 1, event_id: "post-guard-start", session_id: "session:post-guard", base_revision: 0,
    occurred_at: "2026-08-05T10:30:00.000Z", type: "session.started", mission: "post guard test", mainline_topic_id: "mainline",
  }]);
  const reducerPort = createInMemorySessionRuntimePort(initialView);
  let now = Date.parse("2026-08-05T10:30:00.000Z");
  const postGuardDeadlinePort: SessionRuntimePort = {
    readView: () => reducerPort.readView(),
    ensureUnknown: (...args) => reducerPort.ensureUnknown(...args),
    async commitAgentTurn(content, expectedBaseRevision, guard) {
      const receipt = await reducerPort.commitAgentTurn(content, expectedBaseRevision, guard);
      now += 31_000;
      return receipt;
    },
  };
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  const result = await new TianlongshanShadowAgent(world).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low" },
    {
      session_id: "session:post-guard", session_revision: 1,
      session_port: postGuardDeadlinePort, now_ms: () => now,
    },
  );
  assert.equal(result.runtime_trace.agent_run.stop_reason, "budget_exceeded");
  assert.deepEqual(result.runtime_trace.agent_run.session_commit, {
    commit_status: "committed", expected_base_revision: 1, committed_revision: 2,
  });
  assert.equal((await reducerPort.readView()).turns.length, 1);
  validate("agent_run.schema.json", result.runtime_trace.agent_run);
});

test("an unreadable post-commit outcome is explicitly marked for reconciliation", async () => {
  const validate = await validator();
  const initialView = replaySession([{
    schema_version: 1, event_id: "reconcile-start", session_id: "session:reconcile", base_revision: 0,
    occurred_at: "2026-08-05T11:00:00.000Z", type: "session.started", mission: "reconcile test", mainline_topic_id: "mainline",
  }]);
  const reducerPort = createInMemorySessionRuntimePort(initialView);
  let now = Date.parse("2026-08-05T11:00:00.000Z");
  const reconciliationPort: SessionRuntimePort = {
    readView: () => reducerPort.readView(),
    ensureUnknown: (...args) => reducerPort.ensureUnknown(...args),
    async commitAgentTurn() {
      now += 31_000;
      throw new SessionCommitReconciliationRequiredError("simulated unreadable post-commit outcome");
    },
  };
  const world = JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
  const result = await new TianlongshanShadowAgent(world).run(
    { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low" },
    {
      session_id: "session:reconcile", session_revision: 1,
      session_port: reconciliationPort, now_ms: () => now,
    },
  );
  assert.equal(result.runtime_trace.agent_run.stop_reason, "deterministic_error");
  assert.deepEqual(result.runtime_trace.agent_run.session_commit, {
    commit_status: "reconciliation_required", expected_base_revision: 1,
  });
  validate("agent_run.schema.json", result.runtime_trace.agent_run);
});
