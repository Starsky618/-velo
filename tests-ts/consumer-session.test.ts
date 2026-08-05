import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, utimes } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { compileRiderContext } from "../agent_runtime/consumer/context/compiler.ts";
import { applySessionEvent, JsonlSessionStore, replaySession, validateSessionEvent } from "../agent_runtime/consumer/session/engine.ts";
import { JsonlSessionRuntimePort, type SessionEventStore } from "../agent_runtime/consumer/session/jsonl-runtime-port.ts";
import type { RiderSessionEvent, SessionView, TurnRecordedEvent } from "../agent_runtime/consumer/session/types.ts";
import { contentHash } from "../agent_runtime/shared/canonical.ts";

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

function riderTurn(index: number, content = `原始对话 ${index}`): TurnRecordedEvent {
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
    type: "decision.proposed",
    decision_id: "decision-1",
    topic_id: "topic-main",
    decision_key: "urban_exposure",
    statement: "城区暴露必须为 low",
    typed_value: "low",
    source_turn_refs: ["turn-1"],
  });
  events.push({
    ...riderTurn(3, "确认采用低城区暴露"),
    base_revision: 3,
    interaction: { kind: "decision_response", decision_id: "decision-1", statement_hash: contentHash("城区暴露必须为 low"), response: "user_confirmed" },
  });
  events.push({
    schema_version: 1, event_id: "event-decision-response-1", session_id: "session-1", base_revision: 4,
    occurred_at: "2026-08-04T08:04:00.000Z", type: "decision.responded", decision_id: "decision-1",
    response_turn_id: "turn-3", response: "user_confirmed", expected_statement_hash: contentHash("城区暴露必须为 low"),
  });
  for (let index = 5; index <= 22; index += 1) {
    events.push({ ...riderTurn(index), base_revision: index });
  }

  const view = replaySession(events);
  const context = compileRiderContext(view, 4);

  assert.equal(view.turns[0]?.content, "我不要城区主干道，宁可多骑十分钟");
  assert.deepEqual(context.recent_turns.map((turn) => turn.id), ["turn-19", "turn-20", "turn-21", "turn-22"]);
  assert.deepEqual(context.confirmed_decisions.map((decision) => decision.id), ["decision-1"]);
  assert.deepEqual(context.decision_source_turns.map((turn) => turn.content), ["我不要城区主干道，宁可多骑十分钟", "确认采用低城区暴露"]);
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
  const proposal: RiderSessionEvent = {
    schema_version: 1,
    event_id: "event-fabricated",
    session_id: "session-1",
    base_revision: 2,
    occurred_at: "2026-08-04T08:02:00.000Z",
    type: "decision.proposed",
    decision_id: "decision-fabricated",
    topic_id: "topic-main",
    decision_key: "climbing",
    statement: "喜欢爬坡",
    typed_value: true,
    source_turn_refs: ["turn-agent"],
  };
  const fabricatedResponse: RiderSessionEvent = {
    schema_version: 1, event_id: "event-fabricated-response", session_id: "session-1", base_revision: 3,
    occurred_at: "2026-08-04T08:03:00.000Z", type: "decision.responded", decision_id: "decision-fabricated",
    response_turn_id: "turn-agent", response: "user_confirmed", expected_statement_hash: contentHash("喜欢爬坡"),
  };
  assert.throws(() => replaySession([start(), agentTurn, proposal, fabricatedResponse]), /not bound to this exact proposal/);
});

test("a direct rider turn cannot confirm a different decision or statement", () => {
  const statement = "喜欢爬坡";
  const proposal: RiderSessionEvent = {
    schema_version: 1, event_id: "proposal", session_id: "session-1", base_revision: 2,
    occurred_at: "2026-08-04T08:02:00.000Z", type: "decision.proposed", decision_id: "climb",
    decision_key: "climbing", topic_id: "topic-main", statement, typed_value: true, source_turn_refs: ["turn-1"],
  };
  const responseTurn: RiderSessionEvent = {
    ...riderTurn(3, "我不喜欢爬坡"), base_revision: 3,
    interaction: { kind: "decision_response", decision_id: "different", statement_hash: contentHash(statement), response: "user_confirmed" },
  };
  const response: RiderSessionEvent = {
    schema_version: 1, event_id: "response", session_id: "session-1", base_revision: 4,
    occurred_at: "2026-08-04T08:04:00.000Z", type: "decision.responded", decision_id: "climb",
    response_turn_id: "turn-3", response: "user_confirmed", expected_statement_hash: contentHash(statement),
  };
  assert.throws(() => replaySession([start(), riderTurn(1), proposal, responseTurn, response]), /not bound/);
});

test("illegal role/source/authorship combinations and terminal-session appends fail closed", () => {
  assert.throws(() => replaySession([start(), { ...riderTurn(1), role: "agent" }]), /illegal turn provenance/);
  const terminal: RiderSessionEvent = {
    schema_version: 1, event_id: "terminal", session_id: "session-1", base_revision: 1,
    occurred_at: "2026-08-04T08:01:00.000Z", type: "session.status_changed", status: "resolved",
  };
  assert.throws(() => replaySession([start(), terminal, { ...riderTurn(2), base_revision: 2 }]), /session is terminal/);
});

test("session events reject unknown top-level and nested fields instead of persisting smuggled data", () => {
  assert.throws(() => validateSessionEvent({ ...start(), raw_evidence: "secret" }), /unknown fields: raw_evidence/);
  const turn = riderTurn(1);
  assert.throws(() => validateSessionEvent({
    ...turn,
    interaction: {
      kind: "decision_response", decision_id: "d", statement_hash: contentHash("x"),
      response: "user_confirmed", exact_coordinates: [1, 2],
    },
  }), /unknown fields: exact_coordinates/);
});

test("the deterministic reducer records a resolvable blocking unknown", () => {
  const unknown: RiderSessionEvent = {
    schema_version: 1, event_id: "unknown-1", session_id: "session-1", base_revision: 1,
    occurred_at: "2026-08-04T08:01:00.000Z", type: "unknown.recorded",
    unknown_id: "unknown:preference-conflict:decision-1", unknown_kind: "session_consistency",
    blocking: true, user_safe_summary: "本次偏好与已确认偏好冲突。", related_ref: "decision-1",
  };
  const view = replaySession([start(), unknown]);
  assert.deepEqual(view.unknowns, [{
    unknown_id: "unknown:preference-conflict:decision-1", unknown_kind: "session_consistency",
    blocking: true, user_safe_summary: "本次偏好与已确认偏好冲突。", related_ref: "decision-1",
  }]);
});

test("a proposed replacement does not erase the last confirmed rider decision until the replacement is confirmed", () => {
  const oldStatement = "城区暴露必须为 low";
  const newStatement = "城区暴露可以为 medium";
  const events: RiderSessionEvent[] = [
    start(),
    riderTurn(1, "尽量少走城区"),
    { schema_version: 1, event_id: "old-proposal", session_id: "session-1", base_revision: 2, occurred_at: "2026-08-04T08:02:00.000Z", type: "decision.proposed", decision_id: "old", decision_key: "urban", topic_id: "topic-main", statement: oldStatement, typed_value: "low", source_turn_refs: ["turn-1"] },
    { ...riderTurn(3, "确认 low"), base_revision: 3, interaction: { kind: "decision_response", decision_id: "old", statement_hash: contentHash(oldStatement), response: "user_confirmed" } },
    { schema_version: 1, event_id: "old-response", session_id: "session-1", base_revision: 4, occurred_at: "2026-08-04T08:04:00.000Z", type: "decision.responded", decision_id: "old", response_turn_id: "turn-3", response: "user_confirmed", expected_statement_hash: contentHash(oldStatement) },
    { ...riderTurn(5, "这次可以稍微经过城区"), base_revision: 5 },
    { schema_version: 1, event_id: "new-proposal", session_id: "session-1", base_revision: 6, occurred_at: "2026-08-04T08:06:00.000Z", type: "decision.proposed", decision_id: "new", decision_key: "urban", topic_id: "topic-main", statement: newStatement, typed_value: "medium", source_turn_refs: ["turn-5"], supersedes_decision_id: "old" },
  ];
  const proposed = replaySession(events);
  assert.deepEqual(compileRiderContext(proposed).confirmed_decisions.map((decision) => decision.id), ["old"]);

  events.push({ ...riderTurn(7, "确认 medium"), base_revision: 7, interaction: { kind: "decision_response", decision_id: "new", statement_hash: contentHash(newStatement), response: "user_confirmed" } });
  events.push({ schema_version: 1, event_id: "new-response", session_id: "session-1", base_revision: 8, occurred_at: "2026-08-04T08:08:00.000Z", type: "decision.responded", decision_id: "new", response_turn_id: "turn-7", response: "user_confirmed", expected_statement_hash: contentHash(newStatement) });
  const confirmed = replaySession(events);
  assert.deepEqual(compileRiderContext(confirmed).confirmed_decisions.map((decision) => decision.id), ["new"]);
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

test("JSONL Session port reconciles an exact event revision despite a later concurrent event", async () => {
  const started = start();
  let events: RiderSessionEvent[] = [started];
  let view: SessionView = replaySession(events);
  const failingAfterCommit: SessionEventStore = {
    async read() {
      return { events: structuredClone(events), view: structuredClone(view) };
    },
    async append(event, beforeCommit) {
      beforeCommit?.();
      view = applySessionEvent(view, event);
      events = [...events, structuredClone(event)];
      const laterUserEvent: RiderSessionEvent = {
        schema_version: 1,
        event_id: "concurrent-user-after-agent",
        session_id: "session-1",
        base_revision: view.revision,
        occurred_at: new Date(new Date(event.occurred_at).valueOf() + 1).toISOString(),
        type: "turn.recorded",
        turn_id: "concurrent-user-turn",
        topic_id: "topic-main",
        role: "user",
        source_role: "user",
        authorship_basis: "direct_unquoted_message",
        content: "并发的新请求",
      };
      view = applySessionEvent(view, laterUserEvent);
      events = [...events, laterUserEvent];
      throw new Error("simulated directory fsync failure after atomic rename");
    },
  };
  const port = new JsonlSessionRuntimePort(failingAfterCommit, "session-1", "topic-main");
  const controller = new AbortController();
  const result = await port.commitAgentTurn("已生成路线", 1, {
    signal: controller.signal,
    assertCanCommit: () => undefined,
  });
  assert.deepEqual(result, { commit_status: "committed", expected_base_revision: 1, committed_revision: 2 });
  assert.equal((await port.readView()).turns[0]?.content, "已生成路线");
  assert.equal((await port.readView()).revision, 3);
});

test("jsonl store recovers an expired heartbeat lock", async () => {
  const directory = await mkdtemp(join(tmpdir(), "velo-rider-session-stale-lock-"));
  const store = new JsonlSessionStore(directory);
  const path = store.pathFor("session-1");
  await mkdir(`${path}.lock`);
  await utimes(`${path}.lock`, new Date("2020-01-01T00:00:00.000Z"), new Date("2020-01-01T00:00:00.000Z"));
  const view = await store.append(start());
  assert.equal(view.revision, 1);
});

test("two stale-lock recoverers never both enter the JSONL critical section", async () => {
  const directory = await mkdtemp(join(tmpdir(), "velo-rider-session-lock-race-"));
  const store = new JsonlSessionStore(directory);
  await store.append(start());
  const path = store.pathFor("session-1");
  await mkdir(`${path}.lock`);
  await utimes(`${path}.lock`, new Date("2020-01-01T00:00:00.000Z"), new Date("2020-01-01T00:00:00.000Z"));
  const outcomes = await Promise.allSettled([
    store.append(riderTurn(1, "recoverer A")),
    store.append({ ...riderTurn(1, "recoverer B"), event_id: "event-turn-b", turn_id: "turn-b" }),
  ]);
  assert.equal(
    outcomes.filter((outcome) => outcome.status === "fulfilled").length,
    1,
    outcomes.map((outcome) => outcome.status === "rejected" ? String(outcome.reason) : "fulfilled").join(" | "),
  );
  const reloaded = await store.read("session-1");
  assert.equal(reloaded.events.length, 2);
  assert.equal(reloaded.view?.revision, 2);
});
