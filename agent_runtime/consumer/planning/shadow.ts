import { createRiderCapabilityGate } from "../capabilities.ts";
import type {
  AgentAction,
  CandidatePlan,
  CandidatePlanTemplate,
  PlanningWorld,
  RejectedCandidate,
  RideRequest,
  ShadowResult,
} from "./types.ts";

const ALLOWED_TOOLS = new Set([
  "retrieve_world_context",
  "generate_candidate_plans",
  "validate_plan",
  "compare_plans",
]);
const MAX_MODEL_TURNS = 4;
const MAX_TOOL_CALLS = 6;
const URBAN_EXPOSURE_RANK = { low: 0, medium: 1, high: 2 } as const;
const LEG_ROLES = new Set(["access", "connector", "core", "exit", "return"]);
const PATH_SOURCES = new Set(["canonical_traversal", "tencent_bicycling"]);

interface Decision {
  action: AgentAction;
  tool_name?: string;
  question?: string;
}

interface WorldContext {
  origin?: { ref: string; revision: string };
  fixture_version: string;
}

interface ValidationBatch {
  valid: CandidatePlan[];
  rejected: string[];
  rejectedCandidates: RejectedCandidate[];
  staleCount: number;
}

/** A repeatable proposal policy. The deterministic runtime owns gates, tools, validation and state. */
export class ScriptedDecisionModel {
  decide(exactOrigin: boolean, turn: number): Decision {
    if (!exactOrigin) {
      return { action: "ASK_ONE_QUESTION", question: "你是从太原站附近的哪个出发点出发？请补充具体地点。" };
    }
    const sequence: Decision[] = [
      { action: "CALL_TOOL", tool_name: "retrieve_world_context" },
      { action: "CALL_TOOL", tool_name: "generate_candidate_plans" },
      { action: "PRESENT_CANDIDATES" },
    ];
    const decision = sequence[turn];
    if (!decision) throw new Error("scripted model exceeded its bounded sequence");
    return decision;
  }
}

export class TianlongshanShadowAgent {
  readonly trace: string[] = [];
  readonly #capabilities = createRiderCapabilityGate();
  readonly #world: PlanningWorld;
  readonly #model: ScriptedDecisionModel;

  constructor(world: PlanningWorld, model = new ScriptedDecisionModel()) {
    this.#world = world;
    this.#model = model;
  }

  run(request: RideRequest, options: { before_present?: () => void } = {}): ShadowResult {
    this.trace.length = 0;
    this.#assertRequest(request);
    const exactOrigin = Object.hasOwn(this.#world.origins, request.origin);
    const result: ShadowResult = {
      action: "NO_RESULT",
      candidates: [],
      rejected_candidates: [],
      rejection_reasons: [],
      model_turns: 0,
      tool_calls: 0,
      candidate_generation_count: 0,
    };
    let worldContext: WorldContext | undefined;
    let candidates: CandidatePlan[] = [];
    let beforePresent = options.before_present;

    for (let turn = 0; turn < MAX_MODEL_TURNS; turn += 1) {
      const decision = this.#model.decide(exactOrigin, turn);
      result.model_turns += 1;
      if (decision.action === "ASK_ONE_QUESTION") {
        result.action = decision.action;
        if (decision.question) result.question = decision.question;
        return result;
      }
      if (decision.action === "CALL_TOOL") {
        if (!decision.tool_name || !ALLOWED_TOOLS.has(decision.tool_name)) throw new Error("decision attempted a tool outside the rider allowlist");
        if (decision.tool_name === "retrieve_world_context") worldContext = this.retrieveWorldContext(request);
        if (decision.tool_name === "generate_candidate_plans") {
          candidates = this.generateCandidatePlans(worldContext);
          result.candidate_generation_count += 1;
        }
        result.tool_calls += 1;
        this.trace.push(decision.tool_name);
        continue;
      }
      if (decision.action === "PRESENT_CANDIDATES") {
        if (beforePresent) {
          beforePresent();
          beforePresent = undefined;
        }
        let batch = this.validatePlans(request, candidates);
        result.tool_calls += 1;
        this.trace.push("validate_plan");
        if (candidates.length > 0 && batch.staleCount === candidates.length) {
          worldContext = this.retrieveWorldContext(request);
          candidates = this.generateCandidatePlans(worldContext);
          result.candidate_generation_count += 1;
          result.tool_calls += 1;
          this.trace.push("generate_candidate_plans");
          batch = this.validatePlans(request, candidates);
          result.tool_calls += 1;
          this.trace.push("validate_plan");
        }
        const ranked = this.comparePlans(batch.valid);
        result.tool_calls += 1;
        this.trace.push("compare_plans");
        if (result.tool_calls > MAX_TOOL_CALLS) throw new Error("shadow agent exceeded its tool-call cap");
        result.candidates = this.#describeRanked(request, ranked.slice(0, 3));
        result.rejected_candidates = batch.rejectedCandidates;
        result.rejection_reasons = batch.rejected;
        result.action = ranked.length > 0 ? "PRESENT_CANDIDATES" : "NO_RESULT";
        return result;
      }
    }
    throw new Error("shadow agent exceeded its model-turn cap");
  }

  retrieveWorldContext(request: RideRequest): WorldContext {
    this.#capabilities.require("world.read_published");
    const origin = this.#world.origins[request.origin];
    return {
      ...(origin ? { origin: structuredClone(origin) } : {}),
      fixture_version: this.#world.fixture_version,
    };
  }

  generateCandidatePlans(context?: WorldContext): CandidatePlan[] {
    this.#capabilities.require("plan.generate");
    if (!context?.origin) return [];
    return this.#world.candidate_plans.map((template) => this.#resolveTemplate(template, context.origin!));
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
      if (!liveOrigin || candidate.origin_revision !== liveOrigin.revision) {
        reasons.push("起点版本已变更，旧候选失效");
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

  #resolveTemplate(template: CandidatePlanTemplate, origin: { ref: string; revision: string }): CandidatePlan {
    const replaceOrigin = (value: string): string => value === "$origin" ? origin.ref : value;
    return {
      ...structuredClone(template),
      origin_ref: origin.ref,
      origin_revision: origin.revision,
      legs: template.legs.map((leg) => ({
        ...structuredClone(leg),
        from_ref: replaceOrigin(leg.from_ref),
        to_ref: replaceOrigin(leg.to_ref),
      })),
    };
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
      if (leg.role === "core") {
        if (leg.source_adapter !== "canonical_traversal") reasons.push("核心赛段不能由腾讯重新生成，必须引用已发布 Traversal");
        if (!leg.locked) reasons.push("核心赛段必须锁定几何");
        const canonical = this.#world.core_traversals[leg.path_ref];
        if (!canonical || canonical.traversal_ref !== leg.path_ref
          || canonical.revision !== leg.path_revision || canonical.geometry_hash !== leg.geometry_hash
          || canonical.start_ref !== leg.from_ref || canonical.end_ref !== leg.to_ref) {
          reasons.push("核心赛段版本或几何与已发布事实不一致");
        }
      } else if (leg.source_adapter !== "tencent_bicycling") {
        reasons.push("非核心连接段必须来自腾讯骑行路径，不能冒充核心赛段");
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
