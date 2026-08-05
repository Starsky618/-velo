import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import { compileCreatorContext } from "../agent_runtime/creator/context/compiler.ts";
import { evaluateCreatorContextReplay } from "../agent_runtime/creator/eval/context-replay.ts";
import {
  createTestCreatorAgentPrincipal,
  createTestCreatorPrincipal,
  createTestCreatorReviewerPrincipal,
} from "../agent_runtime/creator/capabilities.ts";
import {
  CreatorAgentV0,
  CreatorCommitReconciliationRequiredError,
} from "../agent_runtime/creator/runtime/agent-v0.ts";
import {
  DeterministicCreatorShadowModel,
  validateCreatorModelAction,
  type CreatorDecisionModel,
} from "../agent_runtime/creator/runtime/model.ts";
import { JsonlCreatorStore } from "../agent_runtime/creator/state/engine.ts";
import type { CreatorEvent } from "../agent_runtime/creator/state/types.ts";
import { canonicalJson, contentHash } from "../agent_runtime/shared/canonical.ts";
import type { RuntimePrincipal } from "../agent_runtime/shared/capability-gate.ts";
import { createShadowRiderPrincipal } from "../agent_runtime/consumer/capabilities.ts";
import type { CreatorWorkspaceStore } from "../agent_runtime/creator/state/store-port.ts";

const execFileAsync = promisify(execFile);

const fullPrincipal = createTestCreatorPrincipal();
const agentPrincipal = createTestCreatorAgentPrincipal();
const reviewerPrincipal = createTestCreatorReviewerPrincipal();
const workspaceId = "creator-tianlongshan-loop";
const subjectRef = "route:tianlongshan";

function at(minute: number): string {
  return `2026-08-05T09:${String(minute).padStart(2, "0")}:00.000Z`;
}

function gitBlobRef(content: string): string {
  const hash = createHash("sha1").update(`blob ${Buffer.byteLength(content, "utf8")}\0`).update(content).digest("hex");
  return `git-blob:${hash}`;
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
    source_kind: "repository", content_hash: contentHash(guide), immutable_ref: gitBlobRef(guide), provenance_ref: meta.source_ref,
  });
  await commit(store, {
    ...base("loop-3", at(2)), type: "creator.rights_checked", rights_check_id: "rights:guide",
    source_ref: "repo:tianlongshan-guide", decision: "allowed", policy_ref: "policy:repository-internal-v1",
    reason: "VELO 仓库内 Tim 已拍定本材料，仅用于本地 Creator Shadow。",
  });
  await commit(store, {
    ...base("loop-4", at(3)), type: "creator.source_ingested", source_ref: "conversation:shadow-review",
    source_kind: "conversation", content_hash: contentHash("creator-loop-shadow-review"),
    immutable_ref: contentHash("creator-loop-shadow-review"), provenance_ref: "shadow:tim-review-protocol",
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
  return { store, runtime, model, directory, blueprint, firstStatement, replacementStatement };
}

test("Creator binds Tim confirmation to the exact proposal and rejects prose or Agent authority", async () => {
  const { store, runtime, firstStatement } = await setupRealTianlongshanLoop();
  const firstRun = await runtime.run({
    workspace_id: workspaceId, event_id: "loop-7", occurred_at: at(6), task: "判断天龙山路线结构",
    subject_refs: [subjectRef],
  });
  assert.equal(firstRun.action.type, "propose_judgment");
  assert.equal(firstRun.context_manifest.request_hash, contentHash({
    task: "判断天龙山路线结构", subject_refs: [subjectRef], as_of: at(6), max_pending_turns: 20, max_evidence: 30,
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
    source_kind: "repository", content_hash: contentHash(blueprint), immutable_ref: gitBlobRef(blueprint),
    provenance_ref: "docs/agent-first/source/VELO_路线认知基础设施_v0.1.md",
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
  const guideSource = bundle.manifest.included.source_revisions.find((item) => item.source_ref === "repo:tianlongshan-guide");
  assert.equal(guideSource?.source_event_revision, 2);
  assert.match(guideSource?.immutable_ref ?? "", /^git-blob:[0-9a-f]{40}$/);
  assert.equal(guideSource?.rights_decision, "allowed");
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
  const records = (await store.read(workspaceId)).records;
  assert.equal(records.find((item) => item.event.event_id === "loop-14")?.committed_by.principal_id, agentPrincipal.principal_id);
  assert.equal(records.find((item) => item.event.event_id === "loop-16")?.committed_by.principal_id, reviewerPrincipal.principal_id);
  const helperPath = fileURLToPath(new URL("./helpers/creator-replay-child.ts", import.meta.url));
  const { stdout } = await execFileAsync(process.execPath, [
    "--no-warnings", "--experimental-strip-types", helperPath, directory, workspaceId, JSON.stringify(request),
  ]);
  assert.equal(stdout, canonicalJson(bundle));
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
  await assert.rejects(() => runtime.run({
    workspace_id: workspaceId, event_id: "cross-subject-7", occurred_at: at(6), task: "同时查看两条路线但不得串用证据",
    subject_refs: [subjectRef, "route:other"],
  }), /judgment evidence belongs to another subject/);
  const unchanged = await store.read(workspaceId);
  assert.equal(unchanged.view?.revision, 6);
  const otherContext = compileCreatorContext(unchanged.view!, { task: "判断另一条路线", subject_refs: ["route:other"] });
  assert.equal(otherContext.manifest.omissions.some((item) => (
    item.category === "evidence" && item.reason === "subject_mismatch" && item.refs.includes("evidence:guide")
  )), true);
});

test("Creator rejects Rider reads before compiling private Context or invoking the model", async () => {
  const { store } = await setupRealTianlongshanLoop();
  let modelCalls = 0;
  const observingModel: CreatorDecisionModel = {
    model_ref: "test:must-not-run",
    async decide() {
      modelCalls += 1;
      return { type: "no_action", reason: "must not observe Creator private context" };
    },
  };
  const riderPrincipal = createShadowRiderPrincipal();
  const runtime = new CreatorAgentV0(store, riderPrincipal, observingModel);
  await assert.rejects(() => runtime.run({
    workspace_id: workspaceId, event_id: "rider-leak", occurred_at: at(6), task: "读取 Creator 私有材料",
    subject_refs: [subjectRef],
  }), /capability denied.*context\.read_private/);
  await assert.rejects(() => store.readAs(workspaceId, riderPrincipal), /capability denied.*context\.read_private/);
  assert.equal(modelCalls, 0);
});

test("Creator runtime reconciles a committed event and retries without invoking the model twice", async () => {
  const { store, model } = await setupRealTianlongshanLoop();
  let modelCalls = 0;
  const countingModel: CreatorDecisionModel = {
    model_ref: model.model_ref,
    async decide(bundle, signal) {
      modelCalls += 1;
      return model.decide(bundle, signal);
    },
  };
  let failResponseOnce = true;
  const commitThenFailStore: CreatorWorkspaceStore = {
    readAs: (workspace, principal) => store.readAs(workspace, principal),
    async appendAs(event, principal) {
      const view = await store.appendAs(event, principal);
      if (failResponseOnce) {
        failResponseOnce = false;
        throw new Error("simulated response loss after durable Creator commit");
      }
      return view;
    },
  };
  const runtime = new CreatorAgentV0(commitThenFailStore, agentPrincipal, countingModel);
  const request = {
    workspace_id: workspaceId, event_id: "reconcile-7", occurred_at: at(6), task: "判断天龙山路线结构",
    subject_refs: [subjectRef],
  };
  const first = await runtime.run(request);
  assert.equal(first.commit_status, "reconciled");
  assert.equal(first.committed_revision, 7);
  const retry = await runtime.run(request);
  assert.equal(retry.commit_status, "reconciled");
  assert.equal(retry.context_manifest.context_hash, first.context_manifest.context_hash);
  assert.equal(modelCalls, 1);
});

test("Creator runtime reports typed reconciliation_required when commit outcome cannot be read", async () => {
  const { store, model } = await setupRealTianlongshanLoop();
  let reads = 0;
  const unreadableStore: CreatorWorkspaceStore = {
    async readAs(workspace, principal) {
      reads += 1;
      if (reads > 1) throw new Error("simulated reconciliation read failure");
      return store.readAs(workspace, principal);
    },
    async appendAs() {
      throw new Error("simulated ambiguous commit failure");
    },
  };
  const runtime = new CreatorAgentV0(unreadableStore, agentPrincipal, model);
  await assert.rejects(() => runtime.run({
    workspace_id: workspaceId, event_id: "unreadable-7", occurred_at: at(6), task: "判断天龙山路线结构",
    subject_refs: [subjectRef],
  }), (error: unknown) => (
    error instanceof CreatorCommitReconciliationRequiredError
    && /read-after-error reconciliation also failed/.test(error.message)
  ));
});

test("Creator requires the exact active proposal before recording a Tim response interaction", async () => {
  const { store } = await setupRealTianlongshanLoop();
  await assert.rejects(() => commit(store, {
    ...base("early-response", at(6)), type: "creator.conversation_turn_recorded", turn_id: "turn:early-response",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:early-response", source_role: "user",
    actor: "tim", authorship_basis: "direct_unquoted_message", raw_text: "提前确认不存在的提议",
    content_hash: contentHash("提前确认不存在的提议"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:not-created", statement_hash: contentHash("不存在"), response: "tim_confirmed" },
  }, reviewerPrincipal), /requires an existing exact active proposal/);
});

test("Creator Context fails closed when rights are revoked or a judgment reaches review_at", async () => {
  const { store, runtime, firstStatement } = await setupRealTianlongshanLoop();
  await runtime.run({ workspace_id: workspaceId, event_id: "fresh-7", occurred_at: at(6), task: "判断天龙山路线结构", subject_refs: [subjectRef] });
  await commit(store, {
    ...base("fresh-8", at(7)), type: "creator.conversation_turn_recorded", turn_id: "turn:fresh-confirm",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:fresh-confirm", source_role: "user", actor: "tim",
    authorship_basis: "direct_unquoted_message", raw_text: "确认待复核判断", content_hash: contentHash("确认待复核判断"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:tianlongshan-v1", statement_hash: contentHash(firstStatement), response: "tim_confirmed" },
  }, reviewerPrincipal);
  const confirmed = await commit(store, {
    ...base("fresh-9", at(8)), type: "creator.judgment_responded", decision_id: "decision:fresh-v1",
    proposal_id: "judgment:tianlongshan-v1", response_turn_ref: "turn:fresh-confirm", response: "tim_confirmed",
    expected_statement_hash: contentHash(firstStatement),
  }, reviewerPrincipal);
  const due = compileCreatorContext(confirmed, {
    task: "复核过期判断", subject_refs: [subjectRef], as_of: "2027-01-01T00:00:00.000Z",
  });
  assert.deepEqual(due.context.current_judgments, []);
  assert.equal(due.manifest.omissions.some((item) => item.reason === "review_due" && item.refs.includes("judgment:tianlongshan-v1")), true);

  const revoked = await commit(store, {
    ...base("rights-revoked-10", at(9)), type: "creator.rights_checked", rights_check_id: "rights:guide-revoked",
    source_ref: "repo:tianlongshan-guide", decision: "forbidden", policy_ref: "policy:repository-revoked-v1",
    reason: "验证撤权后原始材料不会继续进入模型 Context。",
  });
  const blocked = compileCreatorContext(revoked, { task: "撤权后重新编译", subject_refs: [subjectRef], as_of: at(9) });
  assert.deepEqual(blocked.context.current_judgments, []);
  assert.deepEqual(blocked.context.relevant_evidence, []);
  assert.equal(blocked.manifest.omissions.some((item) => item.reason === "rights_not_allowed" && item.refs.includes("evidence:guide")), true);
  assert.equal(blocked.manifest.included.source_revisions.some((item) => item.source_ref === "repo:tianlongshan-guide"), false);
});

test("latest source rights follow event revision when timestamps are identical", async () => {
  const { store } = await setupRealTianlongshanLoop();
  await commit(store, {
    ...base("z-rights-allowed", at(6)), type: "creator.rights_checked", rights_check_id: "rights:z-allowed",
    source_ref: "repo:tianlongshan-guide", decision: "allowed", policy_ref: "policy:same-time-v1", reason: "较早 revision。",
  });
  const forbiddenView = await commit(store, {
    ...base("a-rights-forbidden", at(6)), type: "creator.rights_checked", rights_check_id: "rights:a-forbidden",
    source_ref: "repo:tianlongshan-guide", decision: "forbidden", policy_ref: "policy:same-time-v1", reason: "较晚 revision 必须生效。",
  });
  const forbidden = compileCreatorContext(forbiddenView, { task: "同时间撤权", subject_refs: [subjectRef], as_of: at(6) });
  assert.deepEqual(forbidden.context.relevant_evidence, []);
  assert.equal(forbidden.manifest.omissions.some((item) => item.reason === "rights_not_allowed" && item.refs.includes("evidence:guide")), true);

  await commit(store, {
    ...base("z-rights-forbidden", at(7)), type: "creator.rights_checked", rights_check_id: "rights:z-forbidden",
    source_ref: "repo:tianlongshan-guide", decision: "forbidden", policy_ref: "policy:same-time-v1", reason: "较早 revision。",
  });
  const allowedView = await commit(store, {
    ...base("a-rights-allowed", at(7)), type: "creator.rights_checked", rights_check_id: "rights:a-allowed",
    source_ref: "repo:tianlongshan-guide", decision: "allowed", policy_ref: "policy:same-time-v1", reason: "较晚 revision 必须生效。",
  });
  const allowed = compileCreatorContext(allowedView, { task: "同时间重新授权", subject_refs: [subjectRef], as_of: at(7) });
  assert.deepEqual(allowed.manifest.included.evidence_refs, ["evidence:guide"]);
  assert.equal(allowed.manifest.included.source_revisions[0]?.rights_check_id, "rights:a-allowed");
});

test("needs_more_evidence keeps a contradiction open until a later terminal resolution", async () => {
  const { store, runtime, firstStatement } = await setupRealTianlongshanLoop();
  await runtime.run({ workspace_id: workspaceId, event_id: "open-7", occurred_at: at(6), task: "判断天龙山路线结构", subject_refs: [subjectRef] });
  await commit(store, {
    ...base("open-8", at(7)), type: "creator.conversation_turn_recorded", turn_id: "turn:open-confirm",
    source_ref: "conversation:shadow-review", source_message_ref: "shadow-message:open-confirm", source_role: "user", actor: "tim",
    authorship_basis: "direct_unquoted_message", raw_text: "确认第一版", content_hash: contentHash("确认第一版"), subject_refs: [subjectRef],
    interaction: { kind: "judgment_response", proposal_id: "judgment:tianlongshan-v1", statement_hash: contentHash(firstStatement), response: "tim_confirmed" },
  }, reviewerPrincipal);
  await commit(store, {
    ...base("open-9", at(8)), type: "creator.judgment_responded", decision_id: "decision:open-v1",
    proposal_id: "judgment:tianlongshan-v1", response_turn_ref: "turn:open-confirm", response: "tim_confirmed",
    expected_statement_hash: contentHash(firstStatement),
  }, reviewerPrincipal);
  await commit(store, {
    ...base("open-10-other-evidence", at(9)), type: "creator.evidence_recorded", evidence_id: "evidence:other-route",
    source_ref: "repo:tianlongshan-guide", subject_ref: "route:other", raw_observation: "OTHER_ROUTE_PRIVATE",
    observed_at: "2026-08-05T08:00:00.000Z",
  });
  await assert.rejects(() => commit(store, {
    ...base("open-11-invalid-contradiction", at(10)), type: "creator.judgment_contradiction_recorded", contradiction_id: "contradiction:cross-subject",
    judgment_id: "judgment:tianlongshan-v1", contradicting_ref: "evidence:other-route", reason: "不能跨路线引用私有证据。",
  }, agentPrincipal), /contradiction ref belongs to another subject/);
  await commit(store, {
    ...base("open-11", at(10)), type: "creator.judgment_contradiction_recorded", contradiction_id: "contradiction:open",
    judgment_id: "judgment:tianlongshan-v1", contradicting_ref: "evidence:guide", reason: "需要第二份独立材料。",
  }, agentPrincipal);
  await assert.rejects(() => commit(store, {
    ...base("open-12-invalid-resolution", at(11)), type: "creator.judgment_contradiction_resolved", resolution_id: "resolution:cross-subject",
    contradiction_id: "contradiction:open", resolution: "needs_more_evidence", resolution_ref: "evidence:other-route",
    reason: "不能用其他路线的证据解决矛盾。",
  }, agentPrincipal), /resolution ref belongs to another subject/);
  await commit(store, {
    ...base("open-12", at(11)), type: "creator.human_review_requested", review_id: "review:more-evidence",
    target_ref: "contradiction:open", request_kind: "request_more_evidence", reason: "继续收集骑友实测。",
  });
  const view = await commit(store, {
    ...base("open-13", at(12)), type: "creator.judgment_contradiction_resolved", resolution_id: "resolution:still-open",
    contradiction_id: "contradiction:open", resolution: "needs_more_evidence", resolution_ref: "review:more-evidence",
    reason: "当前不能关闭矛盾。",
  }, agentPrincipal);
  assert.equal(view.judgment_contradictions["contradiction:open"]?.resolved, false);
  const bundle = compileCreatorContext(view, { task: "继续判断天龙山", subject_refs: [subjectRef], as_of: at(12) });
  assert.deepEqual(bundle.manifest.included.contradiction_refs, ["contradiction:open"]);
  assert.equal(bundle.context.relevant_evidence.some((item) => item.raw_observation === "OTHER_ROUTE_PRIVATE"), false);
});
