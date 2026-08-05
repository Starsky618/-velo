import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { compileCreatorContext } from "../agent_runtime/creator/context/compiler.ts";
import { evaluateCreatorContextReplay } from "../agent_runtime/creator/eval/context-replay.ts";
import {
  createTestCreatorAgentPrincipal,
  createTestCreatorPrincipal,
  createTestCreatorReviewerPrincipal,
} from "../agent_runtime/creator/capabilities.ts";
import { CreatorAgentV0 } from "../agent_runtime/creator/runtime/agent-v0.ts";
import {
  DeterministicCreatorShadowModel,
  validateCreatorModelAction,
  type CreatorDecisionModel,
} from "../agent_runtime/creator/runtime/model.ts";
import { JsonlCreatorStore } from "../agent_runtime/creator/state/engine.ts";
import type { CreatorEvent } from "../agent_runtime/creator/state/types.ts";
import { contentHash } from "../agent_runtime/shared/canonical.ts";
import type { RuntimePrincipal } from "../agent_runtime/shared/capability-gate.ts";

const fullPrincipal = createTestCreatorPrincipal();
const agentPrincipal = createTestCreatorAgentPrincipal();
const reviewerPrincipal = createTestCreatorReviewerPrincipal();
const workspaceId = "creator-tianlongshan-loop";
const subjectRef = "route:tianlongshan";

function at(minute: number): string {
  return `2026-08-05T09:${String(minute).padStart(2, "0")}:00.000Z`;
}

async function commit(
  store: JsonlCreatorStore,
  event: CreatorEvent,
  principal: RuntimePrincipal = fullPrincipal,
) {
  const current = await store.read(workspaceId);
  return store.appendAs({ ...event, base_revision: current.view?.revision ?? 0 } as CreatorEvent, principal);
}

function base(eventId: string, occurredAt: string) {
  return { schema_version: 1 as const, event_id: eventId, workspace_id: workspaceId, base_revision: 0, occurred_at: occurredAt };
}

async function setupRealTianlongshanLoop() {
  const directory = await mkdtemp(join(tmpdir(), "velo-creator-loop-"));
  const store = new JsonlCreatorStore(directory, fullPrincipal);
  const guideUrl = new URL("../content/routes/tianlongshan/guide.md", import.meta.url);
  const metaUrl = new URL("../content/routes/tianlongshan/meta.json", import.meta.url);
  const blueprintUrl = new URL("../docs/agent-first/source/VELO_路线认知基础设施_v0.1.md", import.meta.url);
  const [guide, metaText, blueprint] = await Promise.all([
    readFile(guideUrl, "utf8"),
    readFile(metaUrl, "utf8"),
    readFile(blueprintUrl, "utf8"),
  ]);
  const meta = JSON.parse(metaText) as { source_ref: string };
  const guideObservation = guide.split("\n").find((line) => line.includes("坡不算陡，但够长"));
  const blueprintObservation = blueprint.split("\n").find((line) => line.includes("| 天龙山 | 线性 | 核心爬坡 | 半开放 |"));
  assert.ok(guideObservation, "real Tianlongshan guide observation must exist");
  assert.ok(blueprintObservation, "real Tianlongshan blueprint classification must exist");

  await commit(store, {
    ...base("loop-1", at(0)), type: "creator.workspace_started", mission: "从真实天龙山材料建立可确认、可替代的路线判断",
  });
  await commit(store, {
    ...base("loop-2", at(1)), type: "creator.source_ingested", source_ref: "repo:tianlongshan-guide",
    source_kind: "repository", content_hash: contentHash(guide), provenance_ref: meta.source_ref,
  });
  await commit(store, {
    ...base("loop-3", at(2)), type: "creator.rights_checked", rights_check_id: "rights:guide",
    source_ref: "repo:tianlongshan-guide", decision: "allowed", policy_ref: "policy:repository-internal-v1",
    reason: "VELO 仓库内 Tim 已拍定本材料，仅用于本地 Creator Shadow。",
  });
  await commit(store, {
    ...base("loop-4", at(3)), type: "creator.source_ingested", source_ref: "conversation:shadow-review",
    source_kind: "conversation", content_hash: contentHash("creator-loop-shadow-review"), provenance_ref: "shadow:tim-review-protocol",
  });
  await commit(store, {
    ...base("loop-5", at(4)), type: "creator.rights_checked", rights_check_id: "rights:shadow-review",
    source_ref: "conversation:shadow-review", decision: "allowed", policy_ref: "policy:local-shadow-v1",
    reason: "本地测试只保存显式 Shadow 审核事件，不冒充生产 Tim 身份。",
  });
  await commit(store, {
    ...base("loop-6", at(5)), type: "creator.evidence_recorded", evidence_id: "evidence:guide",
    source_ref: "repo:tianlongshan-guide", subject_ref: subjectRef, raw_observation: guideObservation,
    observed_at: "2026-06-11T00:00:00.000Z",
  });

  const firstStatement = "天龙山是一条以长距离耐力爬升为核心的路线认知对象。";
  const replacementStatement = "天龙山是线性、核心爬坡、半开放的路线认知对象。";
  const model = new DeterministicCreatorShadowModel("shadow:creator-route-judgment-v0", [
    {
      when: { evidence_ref: "evidence:blueprint", active_judgment_id: "judgment:tianlongshan-v1" },
      action: {
        type: "propose_judgment", proposal_id: "judgment:tianlongshan-v2", judgment_key: "route.tianlongshan.structure",
        subject_ref: subjectRef, statement: replacementStatement, typed_value: "linear_core_climb_semi_open",
        temporality: "slow_changing", review_at: "2027-01-01T00:00:00.000Z", source_turn_refs: [],
        evidence_refs: ["evidence:blueprint"], supersedes_judgment_id: "judgment:tianlongshan-v1",
        reason: "蓝图提供了比旧判断更精确的结构边界。",
      },
    },
    {
      when: { evidence_ref: "evidence:guide", no_active_judgment_key: "route.tianlongshan.structure" },
      action: {
        type: "propose_judgment", proposal_id: "judgment:tianlongshan-v1", judgment_key: "route.tianlongshan.structure",
        subject_ref: subjectRef, statement: firstStatement, typed_value: "endurance_climb",
        temporality: "slow_changing", review_at: "2027-01-01T00:00:00.000Z", source_turn_refs: [],
        evidence_refs: ["evidence:guide"], reason: "仓库定本描述了长而不陡、以耐力为主的核心体验。",
      },
    },
  ]);
  const runtime = new CreatorAgentV0(store, agentPrincipal, model);
  return { store, runtime, directory, blueprint, firstStatement, replacementStatement };
}

test("Creator binds Tim confirmation to the exact proposal and rejects prose or Agent authority", async () => {
  const { store, runtime, firstStatement } = await setupRealTianlongshanLoop();
  const firstRun = await runtime.run({
    workspace_id: workspaceId, event_id: "loop-7", occurred_at: at(6), task: "判断天龙山路线结构",
    subject_refs: [subjectRef],
  });
  assert.equal(firstRun.action.type, "propose_judgment");
  assert.equal(firstRun.context_manifest.request_hash, contentHash({
    task: "判断天龙山路线结构", subject_refs: [subjectRef], max_pending_turns: 20, max_evidence: 30,
  }));
  const proposedView = (await store.read(workspaceId)).view!;
  assert.equal(proposedView.judgments["judgment:tianlongshan-v1"]?.context_request_hash, firstRun.context_manifest.request_hash);
  assert.equal(proposedView.judgments["judgment:tianlongshan-v1"]?.context_hash, firstRun.context_manifest.context_hash);

  await commit(store, {
    ...base("loop-8", at(7)), type: "creator.conversation_turn_recorded", turn_id: "turn:plain-confirm",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:plain-confirm", source_role: "user",
    actor: "tim", authorship_basis: "direct_unquoted_message", raw_text: "我同意", content_hash: contentHash("我同意"),
    subject_refs: [subjectRef],
  }, reviewerPrincipal);
  await assert.rejects(() => commit(store, {
    ...base("loop-9-invalid-prose", at(8)), type: "creator.judgment_responded", decision_id: "decision:invalid-prose",
    proposal_id: "judgment:tianlongshan-v1", response_turn_ref: "turn:plain-confirm", response: "tim_confirmed",
    expected_statement_hash: contentHash(firstStatement),
  }, reviewerPrincipal), /not bound to this exact proposal/);

  await commit(store, {
    ...base("loop-9", at(8)), type: "creator.conversation_turn_recorded", turn_id: "turn:confirm-v1",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:confirm-v1", source_role: "user",
    actor: "tim", authorship_basis: "direct_unquoted_message", raw_text: "确认第一版判断",
    content_hash: contentHash("确认第一版判断"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:tianlongshan-v1", statement_hash: contentHash(firstStatement), response: "tim_confirmed" },
  }, reviewerPrincipal);
  const decision: CreatorEvent = {
    ...base("loop-10", at(9)), type: "creator.judgment_responded", decision_id: "decision:v1",
    proposal_id: "judgment:tianlongshan-v1", response_turn_ref: "turn:confirm-v1", response: "tim_confirmed",
    expected_statement_hash: contentHash(firstStatement),
  };
  await assert.rejects(() => commit(store, decision, agentPrincipal), /capability denied.*judgment.decide/);
  const confirmed = await commit(store, decision, reviewerPrincipal);
  assert.equal(confirmed.judgments["judgment:tianlongshan-v1"]?.status, "tim_confirmed");

  await assert.rejects(() => commit(store, {
    ...base("loop-duplicate-turn", at(10)), type: "creator.conversation_turn_recorded", turn_id: "turn:duplicate",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:confirm-v1", source_role: "user",
    actor: "tim", authorship_basis: "direct_unquoted_message", raw_text: "重复导入", content_hash: contentHash("重复导入"),
    subject_refs: [subjectRef],
  }, reviewerPrincipal), /duplicate source_message_ref/);
});

test("real Tianlongshan materials survive replacement, cold replay and context compression", async () => {
  const { store, runtime, directory, blueprint, firstStatement, replacementStatement } = await setupRealTianlongshanLoop();
  await runtime.run({ workspace_id: workspaceId, event_id: "loop-7", occurred_at: at(6), task: "判断天龙山路线结构", subject_refs: [subjectRef] });
  await commit(store, {
    ...base("loop-8", at(7)), type: "creator.conversation_turn_recorded", turn_id: "turn:confirm-v1",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:confirm-v1", source_role: "user", actor: "tim",
    authorship_basis: "direct_unquoted_message", raw_text: "确认第一版判断", content_hash: contentHash("确认第一版判断"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:tianlongshan-v1", statement_hash: contentHash(firstStatement), response: "tim_confirmed" },
  }, reviewerPrincipal);
  await commit(store, {
    ...base("loop-9", at(8)), type: "creator.judgment_responded", decision_id: "decision:v1", proposal_id: "judgment:tianlongshan-v1",
    response_turn_ref: "turn:confirm-v1", response: "tim_confirmed", expected_statement_hash: contentHash(firstStatement),
  }, reviewerPrincipal);
  await commit(store, {
    ...base("loop-10", at(9)), type: "creator.source_ingested", source_ref: "repo:route-cognition-blueprint",
    source_kind: "repository", content_hash: contentHash(blueprint), provenance_ref: "docs/agent-first/source/VELO_路线认知基础设施_v0.1.md",
  });
  await commit(store, {
    ...base("loop-11", at(10)), type: "creator.rights_checked", rights_check_id: "rights:blueprint",
    source_ref: "repo:route-cognition-blueprint", decision: "allowed", policy_ref: "policy:repository-internal-v1", reason: "VELO 仓库内路线认知蓝图。",
  });
  const blueprintObservation = blueprint.split("\n").find((line) => line.includes("| 天龙山 | 线性 | 核心爬坡 | 半开放 |"))!;
  await commit(store, {
    ...base("loop-12", at(11)), type: "creator.evidence_recorded", evidence_id: "evidence:blueprint",
    source_ref: "repo:route-cognition-blueprint", subject_ref: subjectRef, raw_observation: blueprintObservation,
    observed_at: "2026-08-01T00:00:00.000Z",
  });
  await commit(store, {
    ...base("loop-13", at(12)), type: "creator.judgment_contradiction_recorded", contradiction_id: "contradiction:v1-too-broad",
    judgment_id: "judgment:tianlongshan-v1", contradicting_ref: "evidence:blueprint",
    reason: "旧判断遗漏线性与半开放边界，不能独立支撑后续组合规则。",
  }, agentPrincipal);
  const secondRun = await runtime.run({
    workspace_id: workspaceId, event_id: "loop-14", occurred_at: at(13), task: "用蓝图修订天龙山结构判断", subject_refs: [subjectRef],
  });
  assert.equal(secondRun.action.type, "propose_judgment");
  assert.deepEqual(secondRun.context_manifest.included.contradiction_refs, ["contradiction:v1-too-broad"]);

  await commit(store, {
    ...base("loop-15", at(14)), type: "creator.conversation_turn_recorded", turn_id: "turn:confirm-v2",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:confirm-v2", source_role: "user", actor: "tim",
    authorship_basis: "direct_unquoted_message", raw_text: "确认替代判断", content_hash: contentHash("确认替代判断"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:tianlongshan-v2", statement_hash: contentHash(replacementStatement), response: "tim_confirmed" },
  }, reviewerPrincipal);
  await commit(store, {
    ...base("loop-16", at(15)), type: "creator.judgment_responded", decision_id: "decision:v2", proposal_id: "judgment:tianlongshan-v2",
    response_turn_ref: "turn:confirm-v2", response: "tim_confirmed", expected_statement_hash: contentHash(replacementStatement),
  }, reviewerPrincipal);
  const liveView = await commit(store, {
    ...base("loop-17", at(16)), type: "creator.judgment_contradiction_resolved", resolution_id: "resolution:v1",
    contradiction_id: "contradiction:v1-too-broad", resolution: "superseded", resolution_ref: "judgment:tianlongshan-v2",
    reason: "Tim 已明确确认更精确的替代判断。",
  }, agentPrincipal);

  const request = { task: "生成天龙山路线认知上下文", subject_refs: [subjectRef] };
  const bundle = compileCreatorContext(liveView, request);
  assert.deepEqual(bundle.manifest.included.judgment_refs, ["judgment:tianlongshan-v2"]);
  assert.equal(bundle.context.current_judgments[0]?.statement, replacementStatement);
  assert.equal(bundle.context.current_judgments.some((item) => item.statement === firstStatement), false);
  assert.equal(bundle.manifest.omissions.some((item) => item.reason === "superseded" && item.refs.includes("judgment:tianlongshan-v1")), true);
  assert.equal(bundle.manifest.omissions.some((item) => item.reason === "resolved" && item.refs.includes("contradiction:v1-too-broad")), true);
  assert.equal(bundle.manifest.included.source_revisions.some((item) => item.source_ref === "repo:tianlongshan-guide"), true);
  assert.equal(bundle.manifest.included.source_revisions.some((item) => item.source_ref === "repo:route-cognition-blueprint"), true);
  assert.equal(bundle.manifest.included.source_revisions.some((item) => item.source_ref === "conversation:shadow-review"), true);
  assert.deepEqual(bundle.manifest.included.judgment_source_turn_refs, ["turn:confirm-v2"]);
  const constrained = compileCreatorContext(liveView, {
    task: "极小上下文仍保留当前判断的来源", subject_refs: [subjectRef], max_pending_turns: 0, max_evidence: 0,
  });
  assert.deepEqual(constrained.context.pending_input_turns, []);
  assert.deepEqual(constrained.manifest.included.evidence_refs, ["evidence:blueprint"]);

  const coldStore = new JsonlCreatorStore(directory, fullPrincipal);
  const coldView = (await coldStore.read(workspaceId)).view!;
  const evaluation = evaluateCreatorContextReplay(liveView, coldView, request, {
    current_judgment_refs: ["judgment:tianlongshan-v2"],
    forbidden_judgment_refs: ["judgment:tianlongshan-v1"],
    unresolved_contradiction_refs: [],
  });
  assert.equal(evaluation.verdict, "pass", JSON.stringify(evaluation.checks));
});

test("Tim can explicitly reject an Agent judgment without creating current truth", async () => {
  const { store, runtime, firstStatement } = await setupRealTianlongshanLoop();
  await runtime.run({ workspace_id: workspaceId, event_id: "reject-7", occurred_at: at(6), task: "判断天龙山路线结构", subject_refs: [subjectRef] });
  await commit(store, {
    ...base("reject-8", at(7)), type: "creator.conversation_turn_recorded", turn_id: "turn:reject-v1",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:reject-v1", source_role: "user", actor: "tim",
    authorship_basis: "direct_unquoted_message", raw_text: "拒绝这条判断", content_hash: contentHash("拒绝这条判断"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:tianlongshan-v1", statement_hash: contentHash(firstStatement), response: "rejected" },
  }, reviewerPrincipal);
  const view = await commit(store, {
    ...base("reject-9", at(8)), type: "creator.judgment_responded", decision_id: "decision:reject-v1",
    proposal_id: "judgment:tianlongshan-v1", response_turn_ref: "turn:reject-v1", response: "rejected",
    expected_statement_hash: contentHash(firstStatement),
  }, reviewerPrincipal);
  const bundle = compileCreatorContext(view, { task: "重新判断天龙山", subject_refs: [subjectRef] });
  assert.deepEqual(bundle.context.current_judgments, []);
  assert.equal(bundle.manifest.omissions.some((item) => item.reason === "rejected" && item.refs.includes("judgment:tianlongshan-v1")), true);
});

test("Creator model output fails closed on unknown fields", () => {
  assert.throws(() => validateCreatorModelAction({
    type: "propose_judgment", proposal_id: "p", judgment_key: "k", subject_ref: "s", statement: "x",
    typed_value: true, temporality: "permanent", source_turn_refs: [], evidence_refs: ["e"], reason: "r",
    publish_immediately: true,
  }), /unknown fields/);
});

test("Creator runtime rejects model citations that were not present in its compiled context", async () => {
  const { store } = await setupRealTianlongshanLoop();
  const leakingModel: CreatorDecisionModel = {
    model_ref: "test:leaking-model",
    async decide() {
      return {
        type: "propose_judgment", proposal_id: "judgment:leak", judgment_key: "route.other.structure",
        subject_ref: "route:other", statement: "引用了本次 Context 看不到的天龙山证据。", typed_value: "invalid",
        temporality: "permanent", source_turn_refs: [], evidence_refs: ["evidence:guide"],
        reason: "用于验证运行时拒绝越界引用。",
      };
    },
  };
  const runtime = new CreatorAgentV0(store, agentPrincipal, leakingModel);
  await assert.rejects(() => runtime.run({
    workspace_id: workspaceId, event_id: "leak-7", occurred_at: at(6), task: "判断另一条路线",
    subject_refs: ["route:other"],
  }), /evidence outside the compiled context/);
  assert.equal((await store.read(workspaceId)).view?.revision, 6);
});
