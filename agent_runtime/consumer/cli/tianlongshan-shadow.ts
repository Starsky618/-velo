import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { JsonlSessionStore } from "../session/engine.ts";
import type { RiderSessionEvent } from "../session/types.ts";
import { JsonlSessionRuntimePort } from "../session/jsonl-runtime-port.ts";
import { compileRiderContext } from "../context/compiler.ts";
import { renderResult, TianlongshanShadowAgent } from "../planning/shadow.ts";
import type { RideRequest, UrbanExposure } from "../planning/types.ts";
import { parsePlanningWorld } from "../planning/world-validator.ts";

function valueAfter(flag: string): string {
  const index = process.argv.indexOf(flag);
  const value = index >= 0 ? process.argv[index + 1] : undefined;
  if (!value) throw new Error(`missing ${flag}`);
  return value;
}

const request: RideRequest = {
  origin: valueAfter("--origin"),
  minutes: Number(valueAfter("--minutes")),
  max_climb_m: Number(valueAfter("--max-climb-m")),
  urban_exposure: valueAfter("--urban-exposure") as UrbanExposure,
};
const sessionId = process.argv.includes("--session-id") ? valueAfter("--session-id") : randomUUID();
const storeRoot = process.argv.includes("--session-dir") ? valueAfter("--session-dir") : ".agent-runtime/sessions";
const fixturePath = resolve("tests/fixtures/ride_planning/tianlongshan_world.json");
const world = parsePlanningWorld(JSON.parse(await readFile(fixturePath, "utf8")) as unknown);
const store = new JsonlSessionStore(storeRoot);
let current = await store.read(sessionId);
const occurredAt = new Date().toISOString();
if (!current.view) {
  current.view = await store.append({
    schema_version: 1,
    event_id: randomUUID(),
    session_id: sessionId,
    base_revision: 0,
    occurred_at: occurredAt,
    type: "session.started",
    mission: "规划天龙山门到门骑行",
    mainline_topic_id: "mainline",
  });
}
const exactInput = JSON.stringify(request);
const userEvent: RiderSessionEvent = {
  schema_version: 1,
  event_id: randomUUID(),
  session_id: sessionId,
  base_revision: current.view.revision,
  occurred_at: new Date().toISOString(),
  type: "turn.recorded",
  turn_id: randomUUID(),
  topic_id: current.view.mainline_topic_id,
  role: "user",
  source_role: "user",
  authorship_basis: "direct_unquoted_message",
  content: exactInput,
};
current.view = await store.append(userEvent);
const mainlineTopicId = current.view.mainline_topic_id;
const sessionPort = new JsonlSessionRuntimePort(store, sessionId, mainlineTopicId);
const result = await new TianlongshanShadowAgent(world).run(request, {
  session_id: sessionId,
  session_revision: current.view.revision,
  request_ref: userEvent.turn_id,
  rider_context: compileRiderContext(current.view),
  session_port: sessionPort,
});
const rendered = renderResult(result);
console.log(rendered);
console.error(`session_id=${sessionId}`);
if (["budget_exceeded", "deterministic_error"].includes(result.runtime_trace.agent_run.stop_reason as string)) {
  process.exitCode = 1;
}
