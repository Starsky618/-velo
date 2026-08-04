import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { compileRiderContext } from "../agent_runtime/consumer/context/compiler.ts";
import { JsonlSessionStore, replaySession } from "../agent_runtime/consumer/session/engine.ts";
import type { RiderSessionEvent } from "../agent_runtime/consumer/session/types.ts";

function start(): RiderSessionEvent {
  return {
    schema_version: 1,
    event_id: "event-1",
    session_id: "session-1",
    base_revision: 0,
    occurred_at: "2026-08-04T08:00:00.000Z",
    type: "session.started",
    mission: "规划天龙山门到门骑行",
    mainline_topic_id: "topic-main",
  };
}

function riderTurn(index: number, content = `原始对话 ${index}`): RiderSessionEvent {
  return {
    schema_version: 1,
    event_id: `event-turn-${index}`,
    session_id: "session-1",
    base_revision: index,
    occurred_at: `2026-08-04T08:${String(index).padStart(2, "0")}:00.000Z`,
    type: "turn.recorded",
    turn_id: `turn-${index}`,
    topic_id: "topic-main",
    role: "user",
    source_role: "user",
    authorship_basis: "direct_unquoted_message",
    content,
  };
}

test("exact raw turns replay and an old confirmed decision survives context compression", () => {
  const events: RiderSessionEvent[] = [start(), riderTurn(1, "我不要城区主干道，宁可多骑十分钟")];
  events.push({
    schema_version: 1,
    event_id: "event-decision-1",
    session_id: "session-1",
    base_revision: 2,
    occurred_at: "2026-08-04T08:02:00.000Z",
    type: "decision.recorded",
    decision_id: "decision-1",
    topic_id: "topic-main",
    decision_key: "urban_exposure",
    statement: "城区暴露必须为 low",
    status: "user_confirmed",
    source_turn_refs: ["turn-1"],
  });
  for (let index = 3; index <= 22; index += 1) {
    events.push({ ...riderTurn(index), base_revision: index });
  }

  const view = replaySession(events);
  const context = compileRiderContext(view, 4);

  assert.equal(view.turns[0]?.content, "我不要城区主干道，宁可多骑十分钟");
  assert.deepEqual(context.recent_turns.map((turn) => turn.id), ["turn-19", "turn-20", "turn-21", "turn-22"]);
  assert.deepEqual(context.confirmed_decisions.map((decision) => decision.id), ["decision-1"]);
  assert.deepEqual(context.decision_source_turns.map((turn) => turn.content), ["我不要城区主干道，宁可多骑十分钟"]);
  assert.equal(context.included_turn_refs.includes("turn-1"), true);
  assert.equal(context.omitted_turn_refs.includes("turn-2"), false);
  assert.equal(context.source_of_truth, false);
});

test("agent prose cannot be promoted into a rider-confirmed decision", () => {
  const agentTurn: RiderSessionEvent = {
    schema_version: 1,
    event_id: "event-agent",
    session_id: "session-1",
    base_revision: 1,
    occurred_at: "2026-08-04T08:01:00.000Z",
    type: "turn.recorded",
    turn_id: "turn-agent",
    topic_id: "topic-main",
    role: "agent",
    source_role: "agent",
    authorship_basis: "agent_generated",
    content: "用户应该喜欢爬坡",
  };
  const fabricatedDecision: RiderSessionEvent = {
    schema_version: 1,
    event_id: "event-fabricated",
    session_id: "session-1",
    base_revision: 2,
    occurred_at: "2026-08-04T08:02:00.000Z",
    type: "decision.recorded",
    decision_id: "decision-fabricated",
    topic_id: "topic-main",
    decision_key: "climbing",
    statement: "喜欢爬坡",
    status: "user_confirmed",
    source_turn_refs: ["turn-agent"],
  };

  assert.throws(() => replaySession([start(), agentTurn, fabricatedDecision]), /direct rider turn/);
});

test("jsonl store preserves branches, is idempotent, and rejects conflicting event ids", async () => {
  const directory = await mkdtemp(join(tmpdir(), "velo-rider-session-"));
  const store = new JsonlSessionStore(directory);
  const started = start();
  await store.append(started);
  await store.append(started);
  const branch: RiderSessionEvent = {
    schema_version: 1,
    event_id: "event-branch",
    session_id: "session-1",
    base_revision: 1,
    occurred_at: "2026-08-04T08:01:00.000Z",
    type: "topic.opened",
    topic_id: "topic-weather",
    parent_topic_id: "topic-main",
    title: "天气导致的临时调整",
    kind: "branch",
  };
  const view = await store.append(branch);
  const reloaded = await store.read("session-1");
  const lines = (await readFile(store.pathFor("session-1"), "utf8")).trim().split("\n");

  assert.equal(lines.length, 2);
  assert.equal(view.topics["topic-weather"]?.kind, "branch");
  assert.equal(reloaded.view?.topics["topic-weather"]?.title, "天气导致的临时调整");
  await assert.rejects(() => store.append({ ...branch, title: "被篡改", base_revision: 2 }), /event_id content conflict/);
});
