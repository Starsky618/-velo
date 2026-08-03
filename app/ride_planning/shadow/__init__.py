"""A bounded, deterministic Tianlongshan shadow-planning slice.

This module deliberately does not use the legacy ``app.agent`` package.  It
contains only a fixture-backed orchestration loop suitable for a repeatable
CLI demo and end-to-end tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class AgentAction(str, Enum):
    ASK_ONE_QUESTION = "ASK_ONE_QUESTION"
    CALL_TOOL = "CALL_TOOL"
    PRESENT_CANDIDATES = "PRESENT_CANDIDATES"
    NO_RESULT = "NO_RESULT"


ALLOWED_TOOLS = frozenset(
    {
        "retrieve_rider_context",
        "retrieve_world_context",
        "generate_candidate_plans",
        "validate_plan",
        "compare_plans",
    }
)
MAX_MODEL_TURNS = 4
MAX_TOOL_CALLS = 6
URBAN_EXPOSURE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class RideRequest:
    origin: str
    minutes: int
    max_climb_m: int
    urban_exposure: str


@dataclass(frozen=True)
class Decision:
    action: AgentAction
    tool_name: str | None = None
    question: str | None = None


@dataclass
class ShadowResult:
    action: AgentAction
    candidates: list[dict[str, Any]] = field(default_factory=list)
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)
    question: str | None = None
    rejection_reasons: list[str] = field(default_factory=list)
    model_turns: int = 0
    tool_calls: int = 0
    candidate_generation_count: int = 0


class ScriptedDecisionModel:
    """Free, repeatable policy for the small permitted agent state machine."""

    def decide(
        self,
        *,
        request: RideRequest,
        exact_origin: bool,
        turn: int,
    ) -> Decision:
        if not exact_origin:
            return Decision(
                AgentAction.ASK_ONE_QUESTION,
                question="你是从太原站附近的哪个出发点出发？请补充具体地点。",
            )
        sequence = (
            Decision(AgentAction.CALL_TOOL, "retrieve_world_context"),
            Decision(AgentAction.CALL_TOOL, "generate_candidate_plans"),
            Decision(AgentAction.PRESENT_CANDIDATES),
        )
        return sequence[turn]


class TianlongshanShadowAgent:
    """A bounded single-agent loop over five high-level fixture tools."""

    def __init__(self, world: Mapping[str, Any], model: ScriptedDecisionModel | None = None):
        self.world = world
        self.model = model or ScriptedDecisionModel()
        self.trace: list[str] = []

    def run(
        self,
        request: RideRequest,
        *,
        before_present: Callable[[], None] | None = None,
    ) -> ShadowResult:
        self.trace = []
        exact_origin = request.origin in self.world["origins"]
        result = ShadowResult(action=AgentAction.NO_RESULT)
        rider_context: dict[str, Any] = {}
        world_context: dict[str, Any] | None = None
        candidates: list[dict[str, Any]] = []

        for turn in range(MAX_MODEL_TURNS):
            decision = self.model.decide(
                request=request, exact_origin=exact_origin, turn=turn
            )
            result.model_turns += 1

            if decision.action == AgentAction.ASK_ONE_QUESTION:
                result.action = decision.action
                result.question = decision.question
                return result
            if decision.action == AgentAction.CALL_TOOL:
                if decision.tool_name not in ALLOWED_TOOLS:
                    raise ValueError("decision attempted a tool outside the allowlist")
                if decision.tool_name == "retrieve_rider_context":
                    rider_context = self.retrieve_rider_context(request)
                elif decision.tool_name == "retrieve_world_context":
                    world_context = self.retrieve_world_context(request)
                elif decision.tool_name == "generate_candidate_plans":
                    candidates = self.generate_candidate_plans(
                        request, rider_context, world_context or {}
                    )
                    result.candidate_generation_count += 1
                result.tool_calls += 1
                self.trace.append(decision.tool_name)
                continue

            if decision.action == AgentAction.PRESENT_CANDIDATES:
                if before_present is not None:
                    before_present()
                    before_present = None
                valid, rejected, rejected_candidates, stale = self.validate_plan(
                    request, candidates
                )
                result.tool_calls += 1
                self.trace.append("validate_plan")
                # A changed origin revision invalidates every old candidate.  Re-read
                # fixture context and generate fresh candidates within the call cap.
                if candidates and stale == len(candidates):
                    world_context = self.retrieve_world_context(request)
                    candidates = self.generate_candidate_plans(
                        request, rider_context, world_context
                    )
                    result.candidate_generation_count += 1
                    result.tool_calls += 1
                    self.trace.append("generate_candidate_plans")
                    valid, rejected, rejected_candidates, _ = self.validate_plan(
                        request, candidates
                    )
                    result.tool_calls += 1
                    self.trace.append("validate_plan")
                ranked = self.compare_plans(valid)
                result.tool_calls += 1
                self.trace.append("compare_plans")
                if result.tool_calls > MAX_TOOL_CALLS:
                    raise RuntimeError("shadow agent exceeded its tool-call cap")
                result.candidates = self.describe_ranked_candidates(request, ranked[:3])
                result.rejected_candidates = rejected_candidates
                result.rejection_reasons = rejected
                result.action = (
                    AgentAction.PRESENT_CANDIDATES if ranked else AgentAction.NO_RESULT
                )
                return result

        raise RuntimeError("shadow agent exceeded its model-turn cap")

    def retrieve_rider_context(self, request: RideRequest) -> dict[str, Any]:
        return {"preference": request.urban_exposure, "source": "cli_input"}

    def retrieve_world_context(self, request: RideRequest) -> dict[str, Any]:
        origin = self.world["origins"].get(request.origin)
        return {"origin": origin, "fixture_version": self.world["fixture_version"]}

    def generate_candidate_plans(
        self,
        request: RideRequest,
        rider_context: Mapping[str, Any],
        world_context: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        origin = world_context.get("origin")
        if origin is None:
            return []
        plans: list[dict[str, Any]] = []
        for plan in self.world["candidate_plans"]:
            copied = dict(plan)
            copied["origin_ref"] = origin["ref"]
            copied["origin_revision"] = origin["revision"]
            plans.append(copied)
        return plans

    def validate_plan(
        self, request: RideRequest, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], int]:
        valid: list[dict[str, Any]] = []
        rejected: list[str] = []
        rejected_candidates: list[dict[str, Any]] = []
        stale = 0
        requested_exposure = URBAN_EXPOSURE_RANK[request.urban_exposure]
        live_origin = self.world["origins"].get(request.origin)
        for candidate in candidates:
            reasons: list[str] = []
            if live_origin is None or candidate["origin_revision"] != live_origin["revision"]:
                reasons.append("起点版本已变更，旧候选失效")
                stale += 1
            if candidate["estimated_minutes"] > request.minutes:
                reasons.append("预计时间超过硬限制")
            if candidate["total_climb_m"] > request.max_climb_m:
                reasons.append("总爬升超过硬限制")
            if URBAN_EXPOSURE_RANK[candidate["urban_exposure"]] > requested_exposure:
                reasons.append("城区暴露超过偏好")
            if candidate.get("unknowns"):
                reasons.append("存在未确认项，不能按通过处理")
            if reasons:
                rejected.append(f"{candidate['name']}：{'；'.join(reasons)}")
                rejected_candidate = dict(candidate)
                rejected_candidate["rejection_reasons"] = reasons
                rejected_candidates.append(rejected_candidate)
            else:
                valid.append(candidate)
        return valid, rejected, rejected_candidates, stale

    def compare_plans(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            candidates,
            key=lambda candidate: (
                URBAN_EXPOSURE_RANK[candidate["urban_exposure"]],
                candidate["estimated_minutes"],
                candidate["total_climb_m"],
            ),
        )

    def describe_ranked_candidates(
        self, request: RideRequest, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Add request-bound recommendation and trade-off text after ranking."""
        described: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates, start=1):
            described_candidate = dict(candidate)
            limit_summary = (
                f"本次 {request.minutes} 分钟、{request.max_climb_m} m 上限和"
                f"{request.urban_exposure} 城区偏好"
            )
            if index == 1:
                described_candidate["recommendation_reason"] = (
                    f"在{limit_summary}下排名第 1；城区暴露为"
                    f"{candidate['urban_exposure']}。"
                )
            else:
                leader = candidates[0]
                described_candidate["recommendation_reason"] = (
                    f"满足{limit_summary}，排名第 {index}；相对首选多用 "
                    f"{candidate['estimated_minutes'] - leader['estimated_minutes']} 分钟、"
                    f"多爬 {candidate['total_climb_m'] - leader['total_climb_m']} m。"
                )
            described_candidate["tradeoff"] = self._tradeoff(candidate, candidates, index)
            described.append(described_candidate)
        return described

    @staticmethod
    def _tradeoff(
        candidate: Mapping[str, Any], candidates: list[dict[str, Any]], index: int
    ) -> str:
        if len(candidates) == 1:
            return "这是唯一通过全部硬约束的方案。"
        if index == 1:
            next_candidate = candidates[1]
            return (
                f"相对下一方案少用 "
                f"{next_candidate['estimated_minutes'] - candidate['estimated_minutes']} 分钟、"
                f"少爬 {next_candidate['total_climb_m'] - candidate['total_climb_m']} m。"
            )
        leader = candidates[0]
        return (
            f"相对首选增加 {candidate['estimated_minutes'] - leader['estimated_minutes']} 分钟、"
            f"{candidate['total_climb_m'] - leader['total_climb_m']} m 爬升。"
        )


def render_result(request: RideRequest, result: ShadowResult) -> str:
    if result.action == AgentAction.ASK_ONE_QUESTION:
        return f"需要补充一个问题：{result.question}"
    if result.action == AgentAction.NO_RESULT:
        lines = ["没有符合全部硬约束的天龙山门到门候选。"]
        if result.rejection_reasons:
            lines.extend(f"淘汰理由：{reason}" for reason in result.rejection_reasons)
        return "\n".join(lines)

    blocks = []
    for index, candidate in enumerate(result.candidates, start=1):
        blocks.append(
            "\n".join(
                (
                    f"候选 {index}：{candidate['name']}",
                    f"access：{candidate['access']['path_ref']}（{candidate['access']['summary']}）",
                    f"core：{candidate['core']['path_ref']}（{candidate['core']['summary']}）",
                    f"return：{candidate['return']['path_ref']}（{candidate['return']['summary']}）",
                    f"总距离：{candidate['total_distance_km']:.1f} km",
                    f"总爬升：{candidate['total_climb_m']} m",
                    f"预计时间：{candidate['estimated_minutes']} 分钟",
                    f"城区暴露：{candidate['urban_exposure']}",
                    f"风险：{candidate['risk']}",
                    f"unknowns：{', '.join(candidate['unknowns']) or '无'}",
                    f"推荐理由：{candidate['recommendation_reason']}",
                    f"方案取舍：{candidate['tradeoff']}",
                )
            )
        )
    for candidate in result.rejected_candidates:
        blocks.append(
            "\n".join(
                (
                    f"淘汰方案：{candidate['name']}",
                    f"淘汰原因：{'；'.join(candidate['rejection_reasons'])}",
                )
            )
        )
    return "\n\n".join(blocks)
