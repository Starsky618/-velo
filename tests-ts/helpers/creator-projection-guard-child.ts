import { readFile } from "node:fs/promises";

import { createTestCreatorPrincipal } from "../../agent_runtime/creator/capabilities.ts";
import {
  CreatorContextDriftStopError,
  ProjectionVerifiedCreatorContextCompiler,
  type CreatorContextSafetyAlarm,
  type CreatorContextSafetyAlarmSink,
} from "../../agent_runtime/creator/context/projection-guard.ts";
import { CreatorAgentV0, type CreatorRunRequest } from "../../agent_runtime/creator/runtime/agent-v0.ts";
import type { CreatorDecisionModel } from "../../agent_runtime/creator/runtime/model.ts";
import { HttpCreatorWorkspaceStore } from "../../agent_runtime/creator/state/http-store.ts";
import { canonicalJson } from "../../agent_runtime/shared/canonical.ts";

const [, , eventResponsePath, projectionResponsePath, requestPath] = process.argv;
if (!eventResponsePath || !projectionResponsePath || !requestPath) {
  throw new Error(
    "usage: creator-projection-guard-child <event-response.json> <projection-response.json> <request.json>",
  );
}

const [eventResponse, projectionResponse, request] = await Promise.all([
  readFile(eventResponsePath, "utf8").then(JSON.parse),
  readFile(projectionResponsePath, "utf8").then(JSON.parse),
  readFile(requestPath, "utf8").then(JSON.parse) as Promise<CreatorRunRequest>,
]);

const principal = createTestCreatorPrincipal();
const alarms: CreatorContextSafetyAlarm[] = [];
const sink: CreatorContextSafetyAlarmSink = {
  append: async (alarm) => { alarms.push(structuredClone(alarm)); },
};
const model: CreatorDecisionModel & { calls: number } = {
  model_ref: "shadow:postgresql-http-projection-guard",
  calls: 0,
  decide: async function () {
    this.calls += 1;
    return { type: "no_action", reason: "No model call is allowed for drift fixtures." };
  },
};
const fakeFetch: typeof globalThis.fetch = async (input, init) => {
  if (init?.method !== "GET") throw new Error("Projection guard child accepts GET only");
  const rawUrl = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(rawUrl);
  const payload = url.pathname.endsWith("/projection-records") ? projectionResponse : eventResponse;
  return new Response(canonicalJson(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
const store = new HttpCreatorWorkspaceStore({
  base_url: "https://creator-shadow.test",
  credentials: async () => ({ bearer_token: "projection-test-token", principal }),
  fetch: fakeFetch,
});
const compiler = new ProjectionVerifiedCreatorContextCompiler(
  sink,
  () => "2026-08-06T02:00:00.000Z",
);

try {
  await new CreatorAgentV0(store, principal, model, compiler).run(request);
  throw new Error("Projection drift fixture reached the model or completed without stopping");
} catch (error) {
  if (!(error instanceof CreatorContextDriftStopError)) throw error;
  if (model.calls !== 0 || alarms.length !== 1) {
    throw new Error("Projection drift must stop before one model call and persist exactly one alarm");
  }
  process.stdout.write(canonicalJson({
    stopped: true,
    model_calls: model.calls,
    alarm_count: alarms.length,
    reasons: error.alarm.reasons,
  }));
}
