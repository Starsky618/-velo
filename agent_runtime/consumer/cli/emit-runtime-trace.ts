import { readFile } from "node:fs/promises";

import { TianlongshanShadowAgent, type ShadowDecisionModel } from "../planning/shadow.ts";
import { parsePlanningWorld } from "../planning/world-validator.ts";
import {
  createInMemorySessionRuntimePort,
  SessionCommitReconciliationRequiredError,
  type SessionRuntimePort,
} from "../session/committer.ts";
import { replaySession } from "../session/engine.ts";
import { AgentDeadlineExceededError, AgentV0RuntimeController } from "../runtime/agent-v0.ts";

const fixtureUrl = new URL("../../../tests/fixtures/ride_planning/tianlongshan_world.json", import.meta.url);
const world = parsePlanningWorld(JSON.parse(await readFile(fixtureUrl, "utf8")) as unknown);
const started = {
  schema_version: 1 as const,
  event_id: "runtime-trace-session-started",
  session_id: "session:tianlongshan-shadow",
  base_revision: 0,
  occurred_at: new Date().toISOString(),
  type: "session.started" as const,
  mission: "生成 Agent v0 语义 trace",
  mainline_topic_id: "mainline",
};
const request = {
  origin: "太原站附近",
  minutes: 240,
  max_climb_m: 1200,
  urban_exposure: "low" as const,
};
const scenario = process.argv[2] ?? "normal";
let trace;
if (scenario === "tool-timeout") {
  let now = Date.parse("2026-08-05T09:00:00.000Z");
  const runtime = new AgentV0RuntimeController({
    session_id: started.session_id, session_revision: 1, request_ref: "turn:tool-timeout",
    world_revision: world.world_revision, now_ms: () => now,
  });
  const turn = runtime.beginTurn("understand");
  try {
    await runtime.invokeTool(turn, "planning.retrieve_world_context", "world-request:timeout", () => {
      now += 31_000;
      return { world_revision: world.world_revision };
    });
  } catch (error) {
    if (!(error instanceof AgentDeadlineExceededError)) throw error;
  }
  runtime.finish("deterministic_error", undefined);
  trace = runtime.trace;
} else if (scenario === "model-timeout") {
  let now = Date.parse("2026-08-05T08:00:00.000Z");
  const model: ShadowDecisionModel = {
    decide(input) {
      if (input.phase === "retrieve_world") return { action_type: "propose_tool_call", tool_name: "planning.retrieve_world_context" };
      if (input.phase === "generate_candidates") return { action_type: "propose_tool_call", tool_name: "planning.generate_candidate_plans" };
      if (input.phase === "present") {
        now += 31_000;
        return { action_type: "present_valid_candidates", message: "超时结果" };
      }
      return {
        action_type: "ask_clarifying_question", question: "请补充起点。", question_kind: "location",
        answer_mode: "free_text", blocking_unknown_refs: ["unknown:exact-origin"],
      };
    },
  };
  const result = await new TianlongshanShadowAgent(world, model).run(request, {
    session_port: createInMemorySessionRuntimePort(replaySession([started])), now_ms: () => now,
  });
  trace = result.runtime_trace;
} else if (scenario === "commit-timeout") {
  let now = Date.parse("2026-08-05T10:00:00.000Z");
  const reducerPort = createInMemorySessionRuntimePort(replaySession([{ ...started, occurred_at: new Date(now).toISOString() }]));
  const deadlinePort: SessionRuntimePort = {
    readView: () => reducerPort.readView(),
    ensureUnknown: (...args) => reducerPort.ensureUnknown(...args),
    commitAgentTurn(content, expectedBaseRevision, guard) {
      now += 31_000;
      return reducerPort.commitAgentTurn(content, expectedBaseRevision, guard);
    },
  };
  const result = await new TianlongshanShadowAgent(world).run(request, { session_port: deadlinePort, now_ms: () => now });
  trace = result.runtime_trace;
} else if (scenario === "commit-after-deadline") {
  let now = Date.parse("2026-08-05T10:30:00.000Z");
  const reducerPort = createInMemorySessionRuntimePort(replaySession([{ ...started, occurred_at: new Date(now).toISOString() }]));
  const postGuardPort: SessionRuntimePort = {
    readView: () => reducerPort.readView(),
    ensureUnknown: (...args) => reducerPort.ensureUnknown(...args),
    async commitAgentTurn(content, expectedBaseRevision, guard) {
      const receipt = await reducerPort.commitAgentTurn(content, expectedBaseRevision, guard);
      now += 31_000;
      return receipt;
    },
  };
  const result = await new TianlongshanShadowAgent(world).run(request, { session_port: postGuardPort, now_ms: () => now });
  trace = result.runtime_trace;
} else if (scenario === "commit-reconciliation") {
  let now = Date.parse("2026-08-05T11:00:00.000Z");
  const reducerPort = createInMemorySessionRuntimePort(replaySession([{ ...started, occurred_at: new Date(now).toISOString() }]));
  const reconciliationPort: SessionRuntimePort = {
    readView: () => reducerPort.readView(),
    ensureUnknown: (...args) => reducerPort.ensureUnknown(...args),
    async commitAgentTurn() {
      now += 31_000;
      throw new SessionCommitReconciliationRequiredError("emitted reconciliation scenario");
    },
  };
  const result = await new TianlongshanShadowAgent(world).run(request, { session_port: reconciliationPort, now_ms: () => now });
  trace = result.runtime_trace;
} else {
  const result = await new TianlongshanShadowAgent(world).run(request, {
    session_port: createInMemorySessionRuntimePort(replaySession([started])),
  });
  trace = result.runtime_trace;
}
process.stdout.write(`${JSON.stringify(trace)}\n`);
