import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { JsonlCreatorStore, replayCreatorWorkspace, validateCreatorEvent } from "../agent_runtime/creator/state/engine.ts";
import { createTestCreatorPrincipal } from "../agent_runtime/creator/capabilities.ts";
import { createShadowRiderPrincipal } from "../agent_runtime/consumer/capabilities.ts";
import type { CreatorEvent } from "../agent_runtime/creator/state/types.ts";

const principal = createTestCreatorPrincipal();

function events(verdict: "pass" | "fail" | "needs_more_evidence" = "pass"): CreatorEvent[] {
  return [
    {
      schema_version: 1, event_id: "c-1", workspace_id: "creator-1", base_revision: 0,
      occurred_at: "2026-08-04T08:00:00.000Z", type: "creator.workspace_started", mission: "建立天龙山路线认知",
    },
    {
      schema_version: 1, event_id: "c-2", workspace_id: "creator-1", base_revision: 1,
      occurred_at: "2026-08-04T08:01:00.000Z", type: "creator.source_ingested", source_ref: "report:1",
      source_kind: "rider_report", content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000001", immutable_ref: "rider-submission:1:revision:1",
      provenance_ref: "rider-submission:1",
    },
    {
      schema_version: 1, event_id: "c-3", workspace_id: "creator-1", base_revision: 2,
      occurred_at: "2026-08-04T08:02:00.000Z", type: "creator.rights_checked", rights_check_id: "rights:1",
      source_ref: "report:1", decision: "allowed", policy_ref: "policy:rider-submission-v1", reason: "骑友明确授权用于路线认知审核",
    },
    {
      schema_version: 1, event_id: "c-4", workspace_id: "creator-1", base_revision: 3,
      occurred_at: "2026-08-04T08:03:00.000Z", type: "creator.evidence_recorded", evidence_id: "evidence:1",
      source_ref: "report:1", subject_ref: "traversal:tianlongshan-climb-west", raw_observation: "周末上午景区入口常排队",
      observed_at: "2026-08-02T02:00:00.000Z",
    },
    {
      schema_version: 1, event_id: "c-5", workspace_id: "creator-1", base_revision: 4,
      occurred_at: "2026-08-04T08:04:00.000Z", type: "creator.claim_proposed", claim_id: "claim:1",
      subject_ref: "traversal:tianlongshan-climb-west", predicate: "traffic_queue_risk", proposed_value: "weekend_morning",
      temporality: "slow_changing", review_at: "2026-09-01T00:00:00.000Z", evidence_refs: ["evidence:1"],
    },
    {
      schema_version: 1, event_id: "c-6", workspace_id: "creator-1", base_revision: 5,
      occurred_at: "2026-08-04T08:05:00.000Z", type: "creator.conflict_analyzed", analysis_id: "conflict:1",
      claim_id: "claim:1", result: "clear", conflicting_claim_refs: [], reason: "当前 Published World 中没有相反的同范围 Claim",
    },
    {
      schema_version: 1, event_id: "c-7", workspace_id: "creator-1", base_revision: 6,
      occurred_at: "2026-08-04T08:06:00.000Z", type: "creator.eval_recorded", eval_id: "eval:1",
      claim_id: "claim:1", verdict, grader_ref: "grader:corroboration-v1", reason: "证据与时间范围检查完成",
    },
  ];
}

test("creator preserves source to evidence to claim to eval provenance", () => {
  const view = replayCreatorWorkspace(events(), principal);
  assert.equal(view.evidence["evidence:1"]?.raw_observation, "周末上午景区入口常排队");
  assert.deepEqual(view.claims["claim:1"]?.evidence_refs, ["evidence:1"]);
  assert.equal(view.evaluations["eval:1"]?.verdict, "pass");
});

test("a Rider principal cannot create or claim a Creator workspace", () => {
  assert.throws(() => replayCreatorWorkspace([events()[0]!], createShadowRiderPrincipal()), /capability denied/);
});

test("creator may propose a world change only after a passing eval and never publishes directly", () => {
  const proposal: CreatorEvent = {
    schema_version: 1, event_id: "c-8", workspace_id: "creator-1", base_revision: 7,
    occurred_at: "2026-08-04T08:07:00.000Z", type: "creator.world_change_proposed", proposal_id: "proposal:1",
    claim_refs: ["claim:1"], target_world_revision: "world:r17",
  };
  const view = replayCreatorWorkspace([...events(), proposal], principal);
  assert.equal(view.world_change_proposals["proposal:1"]?.target_world_revision, "world:r17");
  assert.throws(() => replayCreatorWorkspace([...events("needs_more_evidence"), proposal], principal), /latest eval to pass/);
  assert.throws(() => validateCreatorEvent({ ...proposal, type: "creator.world_published" }), /unknown or forbidden/);
});

test("creator fails closed before rights and conflict checks, and supports human interruption", () => {
  const withoutRights = events().filter((event) => event.type !== "creator.rights_checked").map((event, index) => ({ ...event, base_revision: index })) as CreatorEvent[];
  assert.throws(() => replayCreatorWorkspace(withoutRights, principal), /allowed rights check/);
  const review: CreatorEvent = {
    schema_version: 1, event_id: "c-8-review", workspace_id: "creator-1", base_revision: 7,
    occurred_at: "2026-08-04T08:07:00.000Z", type: "creator.human_review_requested", review_id: "review:1",
    target_ref: "claim:1", request_kind: "request_more_evidence", reason: "需要第二位骑友交叉验证",
  };
  const view = replayCreatorWorkspace([...events("needs_more_evidence"), review], principal);
  assert.equal(view.human_review_requests["review:1"]?.request_kind, "request_more_evidence");
});

test("temporary claims require an explicit validity window", () => {
  const claim = events().find((event) => event.type === "creator.claim_proposed")!;
  assert.throws(() => validateCreatorEvent({ ...claim, temporality: "temporary", review_at: undefined }), /requires valid_from/);
});

test("creator events reject unknown private/provider payload fields", () => {
  assert.throws(() => validateCreatorEvent({ ...events()[0]!, rider_private_payload: "secret" }), /unknown fields/);
  assert.throws(() => validateCreatorEvent({ ...events()[1]!, raw_provider_payload: { hidden: true } }), /unknown fields/);
});

test("creator JSONL store durably replays exact append-only events", async () => {
  const directory = await mkdtemp(join(tmpdir(), "velo-creator-store-"));
  const store = new JsonlCreatorStore(directory, principal);
  const creatorEvents = events();
  const started = creatorEvents[0] as Extract<CreatorEvent, { type: "creator.workspace_started" }>;
  for (const event of creatorEvents) await store.append(event);
  await store.append(started);
  const reloaded = await store.read("creator-1");
  const lines = (await readFile(store.pathFor("creator-1"), "utf8")).trim().split("\n");
  assert.equal(lines.length, 7);
  const records = lines.map((line) => JSON.parse(line) as { committed_by: { principal_id: string; capability: string } });
  assert.equal(records[0]?.committed_by.principal_id, principal.principal_id);
  assert.equal(records[0]?.committed_by.capability, "workspace.create");
  assert.equal(reloaded.view?.claims["claim:1"]?.proposed_value, "weekend_morning");
  await assert.rejects(() => store.append({ ...started, mission: "tampered" }), /event_id content conflict/);
});
