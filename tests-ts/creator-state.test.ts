import assert from "node:assert/strict";
import test from "node:test";

import { replayCreatorWorkspace, validateCreatorEvent } from "../agent_runtime/creator/state/engine.ts";
import type { CreatorEvent } from "../agent_runtime/creator/state/types.ts";

function events(verdict: "pass" | "fail" | "needs_more_evidence" = "pass"): CreatorEvent[] {
  return [
    {
      schema_version: 1, event_id: "c-1", workspace_id: "creator-1", base_revision: 0,
      occurred_at: "2026-08-04T08:00:00.000Z", type: "creator.workspace_started", mission: "建立天龙山路线认知",
    },
    {
      schema_version: 1, event_id: "c-2", workspace_id: "creator-1", base_revision: 1,
      occurred_at: "2026-08-04T08:01:00.000Z", type: "creator.source_ingested", source_ref: "report:1",
      source_kind: "rider_report", content_hash: "sha256:report-1", provenance_ref: "rider-submission:1",
    },
    {
      schema_version: 1, event_id: "c-3", workspace_id: "creator-1", base_revision: 2,
      occurred_at: "2026-08-04T08:02:00.000Z", type: "creator.evidence_recorded", evidence_id: "evidence:1",
      source_ref: "report:1", subject_ref: "traversal:tianlongshan-climb-west", raw_observation: "周末上午景区入口常排队",
      observed_at: "2026-08-02T02:00:00.000Z",
    },
    {
      schema_version: 1, event_id: "c-4", workspace_id: "creator-1", base_revision: 3,
      occurred_at: "2026-08-04T08:03:00.000Z", type: "creator.claim_proposed", claim_id: "claim:1",
      subject_ref: "traversal:tianlongshan-climb-west", predicate: "traffic_queue_risk", proposed_value: "weekend_morning",
      temporality: "slow_changing", evidence_refs: ["evidence:1"],
    },
    {
      schema_version: 1, event_id: "c-5", workspace_id: "creator-1", base_revision: 4,
      occurred_at: "2026-08-04T08:04:00.000Z", type: "creator.eval_recorded", eval_id: "eval:1",
      claim_id: "claim:1", verdict, grader_ref: "grader:corroboration-v1", reason: "证据与时间范围检查完成",
    },
  ];
}

test("creator preserves source to evidence to claim to eval provenance", () => {
  const view = replayCreatorWorkspace(events());
  assert.equal(view.evidence["evidence:1"]?.raw_observation, "周末上午景区入口常排队");
  assert.deepEqual(view.claims["claim:1"]?.evidence_refs, ["evidence:1"]);
  assert.equal(view.evaluations["eval:1"]?.verdict, "pass");
});

test("creator may propose a world change only after a passing eval and never publishes directly", () => {
  const proposal: CreatorEvent = {
    schema_version: 1, event_id: "c-6", workspace_id: "creator-1", base_revision: 5,
    occurred_at: "2026-08-04T08:05:00.000Z", type: "creator.world_change_proposed", proposal_id: "proposal:1",
    claim_refs: ["claim:1"], target_world_revision: "world:r17",
  };
  const view = replayCreatorWorkspace([...events(), proposal]);
  assert.equal(view.world_change_proposals["proposal:1"]?.target_world_revision, "world:r17");
  assert.throws(() => replayCreatorWorkspace([...events("needs_more_evidence"), proposal]), /passing eval/);
  assert.throws(() => validateCreatorEvent({ ...proposal, type: "creator.world_published" }), /unknown or forbidden/);
});
