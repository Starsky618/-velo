import { createRiderCapabilityGate, createShadowRiderPrincipal } from "../capabilities.ts";
import { contentHash } from "../../shared/canonical.ts";
import type { RiderConversationContext } from "../context/compiler.ts";
import type { RiderTaskContextPacket } from "../context/rider-task-context.ts";
import { AgentDeadlineExceededError, AgentV0RuntimeController } from "../runtime/agent-v0.ts";
import {
  createInMemorySessionRuntimePort,
  SessionCommitReconciliationRequiredError,
  type SessionRuntimePort,
} from "../session/committer.ts";
import { replaySession } from "../session/engine.ts";
import type { RiderSessionEvent, SessionUnknown } from "../session/types.ts";
import type {
  CandidatePlan,
  CandidatePlanTemplate,
  PlanningWorld,
  RejectedCandidate,
  RideRequest,
  ShadowResult,
} from "./types.ts";
import { assertPlanningWorld } from "./world-validator.ts";

const URBAN_EXPOSURE_RANK = { low: 0, medium: 1, high: 2 } as const;
const LEG_ROLES = new Set(["access", "connector", "core", "exit", "return"]);
const PATH_SOURCES = new Set(["canonical_traversal", "tencent_bicycling"]);

interface WorldContext {
  origin?: { ref: string; revision: string };
  fixture_version: string;
  world_revision: string;
  request_hash: string;
}

interface ValidationBatch {
  valid: CandidatePlan[];
  rejected: string[];
  rejectedCandidates: RejectedCandidate[];
  staleCount: number;
}

type ShadowModelProposal =
  | {
    action_type: "ask_clarifying_question";
    question: string;
    question_kind: "intent" | "location" | "time_budget" | "route_preference" | "candidate_choice";
    answer_mode: "single_choice" | "multi_choice" | "free_text" | "map_pin" | "yes_no";
    blocking_unknown_refs: string[];
  }
  | { action_type: "propose_tool_call"; tool_name: "planning.retrieve_world_context" | "planning.generate_candidate_plans" }
  | { action_type: "present_valid_candidates"; message: string }
  | { action_type: "no_result"; message: string };

export interface ShadowModelInput {
  phase: "resolve_origin" | "retrieve_world" | "generate_candidates" | "present";
  request: RideRequest;
  rider_context: RiderConversationContext | undefined;
  rider_task_context: RiderTaskContextPacket | undefined;
  candidate_count: number;
  signal: AbortSignal;
}

export interface ShadowDecisionModel {
  decide(input: ShadowModelInput): ShadowModelProposal | Promise<ShadowModelProposal>;
}

/** Recorded deterministic fake model for Shadow. Each logical model turn consumes the compiled rider context. */
export class ScriptedDecisionModel implements ShadowDecisionModel {
  decide(input: ShadowModelInput): ShadowModelProposal {
    if (input.phase === "resolve_origin") {
      return {
        action_type: "ask_clarifying_question",
        question: "你是从太原站附近的哪个出发点出发？请补充具体地点。",
        question_kind: "location",
        answer_mode: "free_text",
        blocking_unknown_refs: ["unknown:exact-origin"],
      };
    }
    const durableDecision = input.rider_context?.confirmed_decisions.find(
      (decision) => decision.decision_key === "urban_exposure" && typeof decision.typed_value === "string",
    );
    const durableUrbanPreference = durableDecision?.typed_value as keyof typeof URBAN_EXPOSURE_RANK | undefined;
    if (input.phase === "retrieve_world" && durableUrbanPreference !== undefined && durableUrbanPreference in URBAN_EXPOSURE_RANK
      && URBAN_EXPOSURE_RANK[input.request.urban_exposure] > URBAN_EXPOSURE_RANK[durableUrbanPreference!]) {
      return {
        action_type: "ask_clarifying_question",
        question: `你之前确认城区暴露为 ${durableUrbanPreference}，这次填写的是 ${input.request.urban_exposure}。是否以这次请求为准？`,
        question_kind: "route_preference",
        answer_mode: "yes_no",
        blocking_unknown_refs: [`unknown:preference-conflict:${durableDecision!.id}`],
      };
    }
    if (input.phase === "retrieve_world") return { action_type: "propose_tool_call", tool_name: "planning.retrieve_world_context" };
    if (input.phase === "generate_candidates") return { action_type: "propose_tool_call", tool_name: "planning.generate_candidate_plans" };
    return input.candidate_count > 0
      ? { action_type: "present_valid_candidates", message: "已生成并校验候选路线。" }
      : { action_type: "no_result", message: "没有候选通过全部确定性门禁。" };
  }
}

export class TianlongshanShadowAgent {
  readonly trace: string[] = [];
  readonly #capabilities = createRiderCapabilityGate(createShadowRiderPrincipal());
  readonly #world: PlanningWorld;
  readonly #model: ShadowDecisionModel;

  constructor(world: PlanningWorld, model: ShadowDecisionModel = new ScriptedDecisionModel()) {
    assertPlanningWorld(world);
    this.#world = world;
    this.#model = model;
  }

  async run(request: RideRequest, options: {
    before_present?: () => void | Promise<void>;
    session_id?: string;
    session_revision?: number;
    request_ref?: string;
    rider_context?: RiderConversationContext;
    rider_task_context?: RiderTaskContextPacket;
    session_port?: SessionRuntimePort;
    now_ms?: () => number;
  } = {}): Promise<ShadowResult> {
    this.trace.length = 0;
    this.#assertRequest(request);
    if (options.rider_task_context !== undefined) this.#capabilities.require("user_context.read_authorized");
    const exactOrigin = Object.hasOwn(this.#world.origins, request.origin);
    const sessionId = options.session_id ?? "session:tianlongshan-shadow";
    let sessionRevision = options.session_revision ?? 1;
    const sessionPort = options.session_port ?? this.#createStandalonePort(sessionId, sessionRevision);
    const blockingUnknown = this.#blockingUnknown(request, options.rider_context);
    let preparationRejected = false;
    let preparationError: unknown;
    if (blockingUnknown) {
      const controller = new AbortController();
      try {
        const preparation = await sessionPort.ensureUnknown(blockingUnknown, sessionRevision, {
          signal: controller.signal,
          assertCanCommit: () => undefined,
        });
        if (preparation.preparation_status === "rejected_stale") {
          preparationRejected = true;
        } else {
          sessionRevision = preparation.current_revision;
        }
      } catch (error) {
        preparationError = error;
      }
    }
    const runtime = new AgentV0RuntimeController({
      session_id: sessionId,
      session_revision: sessionRevision,
      request_ref: options.request_ref ?? `request:${contentHash(request).slice(-24)}`,
      world_revision: this.#world.world_revision,
      ...(options.rider_context ? { rider_context: options.rider_context } : {}),
      ...(options.rider_task_context ? { rider_task_context: options.rider_task_context } : {}),
      ...(options.now_ms ? { now_ms: options.now_ms } : {}),
    });
    const result: ShadowResult = {
      action: "NO_RESULT", candidates: [], rejected_candidates: [], rejection_reasons: [],
      model_turns: 0, tool_calls: 0, candidate_generation_count: 0, runtime_trace: runtime.trace,
    };
    const decide = (phase: ShadowModelInput["phase"], candidateCount: number) => runtime.invokeModel((signal) => this.#model.decide({
      phase,
      request,
      rider_context: options.rider_context,
      rider_task_context: options.rider_task_context,
      candidate_count: candidateCount,
      signal,
    }));
    const clearUnsafeOutput = (reason: string): void => {
      result.action = "NO_RESULT";
      result.candidates = [];
      result.rejected_candidates = [];
      delete result.question;
      result.rejection_reasons = [reason];
    };
    const finalize = async (
      stopReason: "completed" | "no_result" | "waiting_for_user",
    ): Promise<void> => {
      const commit = await runtime.commitSession(renderResult(result), sessionPort);
      if (commit.commit_status === "rejected_stale") {
        clearUnsafeOutput("会话在生成结果期间已更新，本次旧结果未提交，请基于最新输入重试。");
        runtime.finish("deterministic_error", commit);
        return;
      }
      runtime.finish(stopReason, commit);
      if (runtime.trace.agent_run.stop_reason === "budget_exceeded") {
        clearUnsafeOutput("Agent v0 超过本次运行时限，未把结果当作完成结果展示。");
      }
    };

    if (preparationRejected || preparationError !== undefined) {
      clearUnsafeOutput(preparationRejected
        ? "会话在准备待确认项期间已更新，请基于最新输入重试。"
        : `Session 待确认项写入失败：${preparationError instanceof Error ? preparationError.message : String(preparationError)}`);
      runtime.finish("deterministic_error", preparationError instanceof SessionCommitReconciliationRequiredError
        ? { commit_status: "reconciliation_required", expected_base_revision: sessionRevision }
        : undefined);
      return result;
    }

    try {
      if (!exactOrigin) {
        const turn = runtime.beginTurn("discover");
        const proposal = await decide("resolve_origin", 0);
        if (proposal.action_type !== "ask_clarifying_question") throw new Error("shadow model must clarify an unresolved origin");
        result.action = "ASK_ONE_QUESTION";
        result.question = proposal.question;
        runtime.recordQuestion(turn, proposal);
        await finalize("waiting_for_user");
        result.model_turns = runtime.modelTurns;
        result.tool_calls = runtime.toolCallCount;
        return result;
      }

      let turn = runtime.beginTurn("understand");
      let proposal = await decide("retrieve_world", 0);
      if (proposal.action_type === "ask_clarifying_question") {
        result.action = "ASK_ONE_QUESTION";
        result.question = proposal.question;
        runtime.recordQuestion(turn, proposal);
        await finalize("waiting_for_user");
        result.model_turns = runtime.modelTurns;
        result.tool_calls = runtime.toolCallCount;
        return result;
      }
      if (proposal.action_type !== "propose_tool_call" || proposal.tool_name !== "planning.retrieve_world_context") throw new Error("shadow model proposed the wrong first action");
      let worldContext = await runtime.invokeTool(turn, proposal.tool_name, `world-request:${contentHash(request).slice(-16)}`, () => this.retrieveWorldContext(request));
      this.trace.push("planning.retrieve_world_context");
      turn = runtime.beginTurn("execute");
      proposal = await decide("generate_candidates", 0);
      if (proposal.action_type !== "propose_tool_call" || proposal.tool_name !== "planning.generate_candidate_plans") throw new Error("shadow model proposed the wrong generation action");
      let candidates = await runtime.invokeTool(turn, proposal.tool_name, `plan-generation:${worldContext.request_hash.slice(-16)}`, () => this.generateCandidatePlans(worldContext));
      this.trace.push("planning.generate_candidate_plans");
      result.candidate_generation_count += 1;

      await options.before_present?.();
      runtime.checkDeadline();
      let batch = this.validatePlans(request, candidates);
      this.trace.push("gate.validate_plan");
      if (candidates.length > 0 && batch.staleCount === candidates.length) {
        runtime.updateWorldRevision(this.#world.world_revision);
        turn = runtime.beginTurn("understand");
        proposal = await decide("retrieve_world", 0);
        if (proposal.action_type !== "propose_tool_call" || proposal.tool_name !== "planning.retrieve_world_context") throw new Error("shadow model did not approve stale-world refresh");
        worldContext = await runtime.invokeTool(turn, proposal.tool_name, `world-request:${contentHash(request).slice(-16)}:refresh`, () => this.retrieveWorldContext(request));
        this.trace.push("planning.retrieve_world_context");
        turn = runtime.beginTurn("execute");
        proposal = await decide("generate_candidates", 0);
        if (proposal.action_type !== "propose_tool_call" || proposal.tool_name !== "planning.generate_candidate_plans") throw new Error("shadow model did not approve stale-plan regeneration");
        candidates = await runtime.invokeTool(turn, proposal.tool_name, `plan-generation:${worldContext.request_hash.slice(-16)}:refresh`, () => this.generateCandidatePlans(worldContext));
        this.trace.push("planning.generate_candidate_plans");
        result.candidate_generation_count += 1;
        batch = this.validatePlans(request, candidates);
        this.trace.push("gate.validate_plan");
      }
      const ranked = this.comparePlans(batch.valid);
      this.trace.push("gate.compare_plans");
      result.candidates = this.#describeRanked(request, ranked.slice(0, 3));
      result.rejected_candidates = batch.rejectedCandidates;
      result.rejection_reasons = batch.rejected;
      result.action = ranked.length > 0 ? "PRESENT_CANDIDATES" : "NO_RESULT";
      turn = runtime.beginTurn("compare", result.candidates);
      proposal = await decide("present", result.candidates.length);
      if (result.action === "PRESENT_CANDIDATES" && proposal.action_type !== "present_valid_candidates") throw new Error("shadow model refused valid candidates");
      if (result.action === "NO_RESULT" && proposal.action_type !== "no_result") throw new Error("shadow model attempted to present an empty set");
      if (proposal.action_type !== "present_valid_candidates" && proposal.action_type !== "no_result") throw new Error("shadow model proposed a non-terminal action at presentation");
      runtime.recordTerminal(turn, result.candidates, proposal.message);
      await finalize(result.action === "PRESENT_CANDIDATES" ? "completed" : "no_result");
      result.model_turns = runtime.modelTurns;
      result.tool_calls = runtime.toolCallCount;
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      clearUnsafeOutput(error instanceof AgentDeadlineExceededError
        ? "Agent v0 超过本次运行时限，未把结果当作完成结果展示。"
        : `Agent v0 确定性运行失败：${message}`);
      if (Object.keys(runtime.trace.agent_run).length === 0) {
        runtime.recordModelFailure(runtime.modelTurns, error instanceof AgentDeadlineExceededError
          ? "Agent v0 超过本次运行时限，请稍后重试。"
          : "Agent v0 未能完成本轮决策，请稍后重试。");
        runtime.finish("deterministic_error", error instanceof SessionCommitReconciliationRequiredError
          ? { commit_status: "reconciliation_required", expected_base_revision: sessionRevision }
          : undefined);
      }
      result.model_turns = runtime.modelTurns;
      result.tool_calls = runtime.toolCallCount;
      return result;
    }
  }

  #createStandalonePort(sessionId: string, sessionRevision: number): SessionRuntimePort {
    if (sessionRevision !== 1) {
      throw new Error("a resumed Shadow session requires a reducer/store-backed session_committer");
    }
    const started: RiderSessionEvent = {
      schema_version: 1,
      event_id: `shadow-start-${contentHash(sessionId).slice(-24)}`,
      session_id: sessionId,
      base_revision: 0,
      occurred_at: new Date().toISOString(),
      type: "session.started",
      mission: "执行隔离的路线规划 Shadow",
      mainline_topic_id: "mainline",
    };
    return createInMemorySessionRuntimePort(replaySession([started]));
  }

  #blockingUnknown(request: RideRequest, riderContext: RiderConversationContext | undefined): SessionUnknown | undefined {
    if (!Object.hasOwn(this.#world.origins, request.origin)) {
      return {
        unknown_id: "unknown:exact-origin",
        unknown_kind: "location",
        blocking: true,
        user_safe_summary: "尚未解析骑手本次请求的精确起点引用。",
      };
    }
    const durableDecision = riderContext?.confirmed_decisions.find(
      (decision) => decision.decision_key === "urban_exposure" && typeof decision.typed_value === "string",
    );
    const durablePreference = durableDecision?.typed_value as keyof typeof URBAN_EXPOSURE_RANK | undefined;
    if (durableDecision && durablePreference !== undefined && durablePreference in URBAN_EXPOSURE_RANK
      && URBAN_EXPOSURE_RANK[request.urban_exposure] > URBAN_EXPOSURE_RANK[durablePreference]) {
      return {
        unknown_id: `unknown:preference-conflict:${durableDecision.id}`,
        unknown_kind: "session_consistency",
        blocking: true,
        user_safe_summary: "本次城区暴露偏好与骑手已确认的长期偏好冲突。",
        related_ref: durableDecision.id,
      };
    }
    return undefined;
  }

  retrieveWorldContext(request: RideRequest): WorldContext {
    this.#capabilities.require("world.read_published");
    const origin = this.#world.origins[request.origin];
    return {
      ...(origin ? { origin: structuredClone(origin) } : {}),
      fixture_version: this.#world.fixture_version,
      world_revision: this.#world.world_revision,
      request_hash: contentHash(request),
    };
  }

  generateCandidatePlans(context?: WorldContext): CandidatePlan[] {
    this.#capabilities.require("plan.generate");
    if (!context?.origin) return [];
    return this.#world.candidate_plans.map((template) => this.#resolveTemplate(template, { ...context, origin: context.origin! }));
  }

  validatePlans(request: RideRequest, candidates: CandidatePlan[]): ValidationBatch {
    this.#capabilities.require("plan.validate");
    const valid: CandidatePlan[] = [];
    const rejected: string[] = [];
    const rejectedCandidates: RejectedCandidate[] = [];
    let staleCount = 0;
    const liveOrigin = this.#world.origins[request.origin];
    for (const candidate of candidates) {
      const reasons: string[] = [];
      if (!liveOrigin || candidate.origin_ref !== liveOrigin.ref || candidate.origin_revision !== liveOrigin.revision
        || candidate.request_hash !== contentHash(request) || candidate.world_revision !== this.#world.world_revision) {
        reasons.push("请求、起点或世界版本已变更，旧候选失效");
        staleCount += 1;
      }
      if (candidate.estimated_minutes > request.minutes) reasons.push("预计时间超过硬限制");
      if (candidate.total_climb_m > request.max_climb_m) reasons.push("总爬升超过硬限制");
      if (URBAN_EXPOSURE_RANK[candidate.urban_exposure] > URBAN_EXPOSURE_RANK[request.urban_exposure]) reasons.push("城区暴露超过偏好");
      if (candidate.unknowns.length > 0) reasons.push("存在未确认项，不能按通过处理");
      reasons.push(...this.#validateLegs(candidate));
      if (reasons.length === 0) {
        valid.push(candidate);
      } else {
        rejected.push(`${candidate.name}：${reasons.join("；")}`);
        rejectedCandidates.push({ ...candidate, rejection_reasons: reasons });
      }
    }
    return { valid, rejected, rejectedCandidates, staleCount };
  }

  comparePlans(candidates: CandidatePlan[]): CandidatePlan[] {
    this.#capabilities.require("plan.compare");
    return [...candidates].sort((left, right) =>
      URBAN_EXPOSURE_RANK[left.urban_exposure] - URBAN_EXPOSURE_RANK[right.urban_exposure]
      || left.estimated_minutes - right.estimated_minutes
      || left.total_climb_m - right.total_climb_m,
    );
  }

  #resolveTemplate(template: CandidatePlanTemplate, context: WorldContext & { origin: { ref: string; revision: string } }): CandidatePlan {
    const origin = context.origin;
    const replaceOrigin = (value: string): string => value === "$origin" ? origin.ref : value;
    const resolved = {
      ...structuredClone(template),
      origin_ref: origin.ref,
      origin_revision: origin.revision,
      request_hash: context.request_hash,
      world_revision: context.world_revision,
      legs: template.legs.map((leg) => ({
        ...structuredClone(leg),
        from_ref: replaceOrigin(leg.from_ref),
        to_ref: replaceOrigin(leg.to_ref),
      })),
    };
    return { ...resolved, plan_revision: `plan:${contentHash(resolved).slice(-24)}` };
  }

  #validateLegs(candidate: CandidatePlan): string[] {
    const reasons: string[] = [];
    if (candidate.legs.length === 0) return ["方案没有路线腿"];
    if (candidate.legs[0]?.from_ref !== candidate.origin_ref || candidate.legs.at(-1)?.to_ref !== candidate.origin_ref) {
      reasons.push("方案不是从当前起点出发并返回");
    }
    for (let index = 1; index < candidate.legs.length; index += 1) {
      if (candidate.legs[index - 1]?.to_ref !== candidate.legs[index]?.from_ref) {
        reasons.push(`第 ${index} 与第 ${index + 1} 段未首尾相接`);
      }
    }
    const coreLegs = candidate.legs.filter((leg) => leg.role === "core");
    if (coreLegs.length === 0) reasons.push("方案没有锁定的核心赛段");
    for (const leg of candidate.legs) {
      if (!LEG_ROLES.has(leg.role)) reasons.push("存在未知路线腿类型");
      if (!PATH_SOURCES.has(leg.source_adapter)) reasons.push("存在未知路径来源");
      const canonical = this.#world.core_traversals[leg.path_ref];
      if (canonical) {
        if (leg.role === "core" && leg.source_adapter !== "canonical_traversal") {
          reasons.push("核心赛段不能由腾讯重新生成，必须引用已发布 Traversal");
        }
        if (leg.role !== "core" || leg.source_adapter !== "canonical_traversal" || !leg.locked) {
          reasons.push("已发布 Traversal 身份只能作为锁定核心赛段，不能降级伪装成腾讯连接段");
        }
        if (canonical.traversal_ref !== leg.path_ref
          || canonical.revision !== leg.path_revision || canonical.geometry_hash !== leg.geometry_hash
          || canonical.start_ref !== leg.from_ref || canonical.end_ref !== leg.to_ref) {
          reasons.push("核心赛段版本或几何与已发布事实不一致");
        }
      } else if (leg.role === "core") {
        reasons.push("核心赛段必须引用已发布且锁定的 canonical Traversal");
      } else if (leg.source_adapter !== "tencent_bicycling" || !leg.path_ref.startsWith("tencent:path:") || leg.locked) {
        reasons.push("非核心连接段必须使用独立腾讯路径身份，且不能冒充锁定核心赛段");
      }
    }
    return [...new Set(reasons)];
  }

  #describeRanked(request: RideRequest, candidates: CandidatePlan[]): CandidatePlan[] {
    return candidates.map((candidate, index) => {
      const limitSummary = `本次 ${request.minutes} 分钟、${request.max_climb_m} m 上限和${request.urban_exposure} 城区偏好`;
      const leader = candidates[0]!;
      const recommendationReason = index === 0
        ? `在${limitSummary}下排名第 1；城区暴露为${candidate.urban_exposure}。`
        : `满足${limitSummary}，排名第 ${index + 1}；相对首选多用 ${candidate.estimated_minutes - leader.estimated_minutes} 分钟、多爬 ${candidate.total_climb_m - leader.total_climb_m} m。`;
      let tradeoff = "这是唯一通过全部硬约束的方案。";
      if (candidates.length > 1 && index === 0) {
        const next = candidates[1]!;
        tradeoff = `相对下一方案少用 ${next.estimated_minutes - candidate.estimated_minutes} 分钟、少爬 ${next.total_climb_m - candidate.total_climb_m} m。`;
      } else if (candidates.length > 1) {
        tradeoff = `相对首选增加 ${candidate.estimated_minutes - leader.estimated_minutes} 分钟、${candidate.total_climb_m - leader.total_climb_m} m 爬升。`;
      }
      return { ...candidate, recommendation_reason: recommendationReason, tradeoff };
    });
  }

  #assertRequest(request: RideRequest): void {
    if (!Number.isInteger(request.minutes) || request.minutes <= 0) throw new Error("minutes must be a positive integer");
    if (!Number.isInteger(request.max_climb_m) || request.max_climb_m < 0) throw new Error("max_climb_m must be a non-negative integer");
    if (!(request.urban_exposure in URBAN_EXPOSURE_RANK)) throw new Error("invalid urban_exposure");
  }
}

export function renderResult(result: ShadowResult): string {
  if (result.action === "ASK_ONE_QUESTION") return `需要补充一个问题：${result.question ?? ""}`;
  if (result.action === "NO_RESULT") {
    return ["没有符合全部硬约束的天龙山门到门候选。", ...result.rejection_reasons.map((reason) => `淘汰理由：${reason}`)].join("\n");
  }
  const blocks = result.candidates.map((candidate, index) => {
    const legs = candidate.legs.map((leg) => `${leg.role}：${leg.path_ref}（${leg.summary}）`).join("\n");
    return [
      `候选 ${index + 1}：${candidate.name}`,
      legs,
      `总距离：${candidate.total_distance_km.toFixed(1)} km`,
      `总爬升：${candidate.total_climb_m} m`,
      `预计时间：${candidate.estimated_minutes} 分钟`,
      `城区暴露：${candidate.urban_exposure}`,
      `风险：${candidate.risk}`,
      `unknowns：${candidate.unknowns.join(", ") || "无"}`,
      `推荐理由：${candidate.recommendation_reason ?? ""}`,
      `方案取舍：${candidate.tradeoff ?? ""}`,
    ].join("\n");
  });
  blocks.push(...result.rejected_candidates.map((candidate) =>
    `淘汰方案：${candidate.name}\n淘汰原因：${candidate.rejection_reasons.join("；")}`,
  ));
  return blocks.join("\n\n");
}
