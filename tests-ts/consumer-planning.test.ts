import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { renderResult, TianlongshanShadowAgent } from "../agent_runtime/consumer/planning/shadow.ts";
import type { PlanningWorld, RideRequest } from "../agent_runtime/consumer/planning/types.ts";
import { assertPlanningWorld } from "../agent_runtime/consumer/planning/world-validator.ts";
import { contentHash } from "../agent_runtime/shared/canonical.ts";

const fixtureUrl = new URL("../tests/fixtures/ride_planning/tianlongshan_world.json", import.meta.url);

async function world(): Promise<PlanningWorld> {
  return JSON.parse(await readFile(fixtureUrl, "utf8")) as PlanningWorld;
}

function request(overrides: Partial<RideRequest> = {}): RideRequest {
  return { origin: "太原站附近", minutes: 240, max_climb_m: 1200, urban_exposure: "low", ...overrides };
}

test("normal request presents two deterministic candidates with a locked canonical core", async () => {
  const result = await new TianlongshanShadowAgent(await world()).run(request());
  assert.equal(result.action, "PRESENT_CANDIDATES");
  assert.deepEqual(result.candidates.map((candidate) => candidate.name), ["蒙山补给环线", "晋祠低城区暴露环线"]);
  assert.equal(result.model_turns, 3);
  assert.equal(result.tool_calls, 2);
  assert.equal(result.runtime_trace.context_manifests.length, 3);
  assert.deepEqual(result.runtime_trace.tool_calls.map((call) => call.tool_name), ["planning.retrieve_world_context", "planning.generate_candidate_plans"]);
  assert.equal(result.candidates.every((candidate) => candidate.legs.some((leg) => leg.role === "core" && leg.locked)), true);
});

test("too little time returns no result", async () => {
  const result = await new TianlongshanShadowAgent(await world()).run(request({ minutes: 180 }));
  assert.equal(result.action, "NO_RESULT");
  assert.equal(result.candidates.length, 0);
  assert.equal(result.rejection_reasons.some((reason) => reason.includes("预计时间超过硬限制")), true);
});

test("ambiguous origin asks exactly one question", async () => {
  const result = await new TianlongshanShadowAgent(await world()).run(request({ origin: "太原站" }));
  assert.equal(result.action, "ASK_ONE_QUESTION");
  assert.equal(result.question, "你是从太原站附近的哪个出发点出发？请补充具体地点。");
  assert.equal(result.model_turns, 1);
  assert.equal(result.tool_calls, 0);
});

test("candidate over the hard climb limit is rejected", async () => {
  const fixture = await world();
  fixture.candidate_plans = fixture.candidate_plans.filter((candidate) => candidate.name === "城区直达强度线");
  const result = await new TianlongshanShadowAgent(fixture).run(request({ max_climb_m: 1200, urban_exposure: "high", minutes: 300 }));
  assert.deepEqual(result.rejection_reasons, ["城区直达强度线：总爬升超过硬限制"]);
});

test("changed origin revision invalidates and regenerates old candidates", async () => {
  const fixture = await world();
  const agent = new TianlongshanShadowAgent(fixture);
  const result = await agent.run(request(), {
    before_present: () => {
      fixture.origins["太原站附近"]!.revision = "origin-r2";
    },
  });
  assert.equal(result.action, "PRESENT_CANDIDATES");
  assert.equal(result.candidate_generation_count, 2);
  assert.equal(result.tool_calls, 4);
  assert.equal(result.model_turns, 5);
  assert.deepEqual(new Set(result.candidates.map((candidate) => candidate.origin_revision)), new Set(["origin-r2"]));
});

test("origin identity swap is stale even when its revision label is unchanged", async () => {
  const fixture = await world();
  const agent = new TianlongshanShadowAgent(fixture);
  const result = await agent.run(request(), { before_present: () => {
    fixture.origins["太原站附近"] = { ref: "origin:replacement", revision: "origin-r1" };
  } });
  assert.equal(result.candidate_generation_count, 2);
  assert.deepEqual(new Set(result.candidates.map((candidate) => candidate.origin_ref)), new Set(["origin:replacement"]));
});

test("changed request and world revision cannot present candidates generated for the old state", async () => {
  const fixture = await world();
  const currentRequest = request();
  const result = await new TianlongshanShadowAgent(fixture).run(currentRequest, { before_present: () => {
    currentRequest.minutes = 230;
    fixture.world_revision = "world:tianlongshan-r2";
  } });
  assert.equal(result.candidate_generation_count, 2);
  assert.equal(result.candidates.every((candidate) => candidate.request_hash === contentHash(currentRequest)), true);
  assert.equal(result.candidates.every((candidate) => candidate.world_revision === "world:tianlongshan-r2"), true);
});

test("high urban exposure still ranks low exposure candidates first", async () => {
  const result = await new TianlongshanShadowAgent(await world()).run(request({ minutes: 300, max_climb_m: 1600, urban_exposure: "high" }));
  assert.deepEqual(result.candidates.map((candidate) => candidate.name), ["蒙山补给环线", "晋祠低城区暴露环线", "城区直达强度线"]);
});

test("recommendation reason is generated from the current request", async () => {
  const result = await new TianlongshanShadowAgent(await world()).run(request({ minutes: 300, max_climb_m: 1600, urban_exposure: "high" }));
  assert.match(result.candidates[0]?.recommendation_reason ?? "", /300 分钟、1600 m 上限和high 城区偏好/);
  assert.doesNotMatch(result.candidates[0]?.recommendation_reason ?? "", /4 小时|1200 米/);
});

test("normal output includes rejected plan and exact reasons", async () => {
  const output = renderResult(await new TianlongshanShadowAgent(await world()).run(request()));
  assert.match(output, /淘汰方案：城区直达强度线/);
  assert.match(output, /预计时间超过硬限制；总爬升超过硬限制；城区暴露超过偏好/);
  assert.doesNotMatch(output, /淘汰理由：无/);
});

test("Tencent is rejected when it attempts to regenerate the core segment", async () => {
  const fixture = await world();
  fixture.candidate_plans[0]!.legs.find((leg) => leg.role === "core")!.source_adapter = "tencent_bicycling";
  fixture.candidate_plans = [fixture.candidate_plans[0]!];
  const result = await new TianlongshanShadowAgent(fixture).run(request());
  assert.match(result.rejection_reasons[0] ?? "", /核心赛段不能由腾讯重新生成/);
});

test("tampered core geometry is rejected even when identifiers still match", async () => {
  const fixture = await world();
  fixture.candidate_plans[0]!.legs.find((leg) => leg.role === "core")!.geometry_hash = "sha256:tampered";
  fixture.candidate_plans = [fixture.candidate_plans[0]!];
  const result = await new TianlongshanShadowAgent(fixture).run(request());
  assert.match(result.rejection_reasons[0] ?? "", /核心赛段版本或几何与已发布事实不一致/);
});

test("a canonical traversal identity cannot be downgraded into a Tencent connector while another core remains", async () => {
  const fixture = await world();
  const plan = fixture.candidate_plans[0]!;
  plan.legs[0]!.path_ref = "traversal:tianlongshan-climb-east";
  plan.legs[0]!.path_revision = "traversal-r2";
  plan.legs[0]!.geometry_hash = "sha256:tianlongshan-east-r2-fixture";
  fixture.candidate_plans = [plan];
  const result = await new TianlongshanShadowAgent(fixture).run(request());
  assert.match(result.rejection_reasons[0] ?? "", /已发布 Traversal 身份只能作为锁定核心赛段/);
});

test("a disconnected Tencent connector fails closed", async () => {
  const fixture = await world();
  fixture.candidate_plans[0]!.legs[0]!.to_ref = "junction:wrong";
  fixture.candidate_plans = [fixture.candidate_plans[0]!];
  const result = await new TianlongshanShadowAgent(fixture).run(request());
  assert.match(result.rejection_reasons[0] ?? "", /未首尾相接/);
});

test("Tencent may connect multiple locked core traversals without changing either core", async () => {
  const fixture = await world();
  const west = structuredClone(fixture.candidate_plans[0]!.legs.find((leg) => leg.role === "core")!);
  const east = structuredClone(fixture.candidate_plans[1]!.legs.find((leg) => leg.role === "core")!);
  const access = structuredClone(fixture.candidate_plans[0]!.legs[0]!);
  const returning = structuredClone(fixture.candidate_plans[1]!.legs.at(-1)!);
  fixture.candidate_plans = [{
    plan_id: "plan:two-core",
    name: "双核心赛段组合线",
    legs: [
      access,
      west,
      {
        role: "connector",
        source_adapter: "tencent_bicycling",
        from_ref: west.to_ref,
        to_ref: east.from_ref,
        path_ref: "tencent:path:west-to-east",
        path_revision: "provider-r1",
        geometry_hash: "sha256:west-to-east-fixture",
        summary: "腾讯只连接两个核心赛段",
        locked: false,
      },
      east,
      returning,
    ],
    total_distance_km: 88,
    total_climb_m: 1100,
    estimated_minutes: 235,
    urban_exposure: "low",
    risk: "连续两个核心爬升",
    unknowns: [],
  }];
  const result = await new TianlongshanShadowAgent(fixture).run(request());
  assert.equal(result.action, "PRESENT_CANDIDATES");
  assert.deepEqual(result.candidates[0]?.legs.map((leg) => leg.role), ["access", "core", "connector", "core", "return"]);
});

test("external planning JSON rejects invalid enums, negative metrics and registry key/ref mismatches", async () => {
  const invalidRole = await world() as unknown as Record<string, unknown>;
  ((invalidRole.candidate_plans as Array<{ legs: Array<{ role: string }> }>)[0]!.legs[0]!).role = "shortcut";
  assert.throws(() => assertPlanningWorld(invalidRole), /invalid leg role/);

  const negative = await world() as unknown as Record<string, unknown>;
  (negative.candidate_plans as Array<{ total_distance_km: number }>)[0]!.total_distance_km = -1;
  assert.throws(() => assertPlanningWorld(negative), /finite and non-negative/);

  const mismatch = await world() as unknown as Record<string, unknown>;
  (mismatch.core_traversals as Record<string, { traversal_ref: string }>)["traversal:tianlongshan-climb-west"]!.traversal_ref = "traversal:other";
  assert.throws(() => assertPlanningWorld(mismatch), /registry key\/ref mismatch/);
});
