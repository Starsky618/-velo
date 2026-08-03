"""Grounded, bounded Tianlongshan door-to-door shadow planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import product
from typing import Any, Mapping, Sequence

from app.ride_planning.shadow.repository import GroundedWorldRepository, Traversal


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
_GENERATED_CANDIDATE_PROOF = object()


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


@dataclass(frozen=True)
class CandidatePlan:
    """A plan composed only from repository-returned Traversals."""

    access: Traversal
    core: Traversal
    return_leg: Traversal
    generation_proof: object | None = field(default=None, repr=False, compare=False)

    @property
    def legs(self) -> tuple[Traversal, Traversal, Traversal]:
        return (self.access, self.core, self.return_leg)

    @property
    def name(self) -> str:
        return self.core.display_name

    @property
    def total_distance_km(self) -> float:
        return sum(leg.distance_km.value for leg in self.legs)

    @property
    def total_climb_m(self) -> float:
        return sum(leg.climb_m.value for leg in self.legs)

    @property
    def estimated_minutes(self) -> float:
        return sum(leg.estimated_minutes.value for leg in self.legs)

    @property
    def urban_exposure(self) -> str:
        return max(
            (leg.urban_exposure for leg in self.legs),
            key=URBAN_EXPOSURE_RANK.__getitem__,
        )


@dataclass
class ShadowResult:
    action: AgentAction
    candidates: list[dict[str, Any]] = field(default_factory=list)
    question: str | None = None
    rejection_reasons: list[str] = field(default_factory=list)
    model_turns: int = 0
    tool_calls: int = 0
    candidate_generation_count: int = 0


class ScriptedDecisionModel:
    """Free, repeatable policy for the permitted agent state machine."""

    def decide(self, *, exact_origin: bool, turn: int) -> Decision:
        if not exact_origin:
            return Decision(
                AgentAction.ASK_ONE_QUESTION,
                question="你是从太原站附近的哪个出发点出发？请补充具体地点。",
            )
        return (
            Decision(AgentAction.CALL_TOOL, "retrieve_world_context"),
            Decision(AgentAction.CALL_TOOL, "generate_candidate_plans"),
            Decision(AgentAction.PRESENT_CANDIDATES),
        )[turn]


class TianlongshanShadowAgent:
    """Single-agent loop whose world access is fail-closed and provenance-bound."""

    def __init__(
        self,
        world: Mapping[str, Any],
        model: ScriptedDecisionModel | None = None,
        repository: GroundedWorldRepository | None = None,
    ):
        self.world = world
        self.model = model or ScriptedDecisionModel()
        self.repository = repository or GroundedWorldRepository(world)
        self.trace: list[str] = []

    def run(self, request: RideRequest) -> ShadowResult:
        self.trace = []
        exact_origin = request.origin in self.world.get("origins", {})
        result = ShadowResult(action=AgentAction.NO_RESULT)
        world_context: dict[str, Any] = {}
        candidates: list[CandidatePlan] = []

        for turn in range(MAX_MODEL_TURNS):
            decision = self.model.decide(exact_origin=exact_origin, turn=turn)
            result.model_turns += 1

            if decision.action == AgentAction.ASK_ONE_QUESTION:
                result.action = decision.action
                result.question = decision.question
                return result
            if decision.action == AgentAction.CALL_TOOL:
                if decision.tool_name not in ALLOWED_TOOLS:
                    raise ValueError("decision attempted a tool outside the allowlist")
                if decision.tool_name == "retrieve_world_context":
                    world_context = self.retrieve_world_context(request)
                elif decision.tool_name == "generate_candidate_plans":
                    candidates = self.generate_candidate_plans(request, world_context)
                    result.candidate_generation_count += 1
                result.tool_calls += 1
                self.trace.append(decision.tool_name)
                continue

            if decision.action == AgentAction.PRESENT_CANDIDATES:
                valid, rejected = self.validate_plan(request, candidates)
                result.tool_calls += 1
                self.trace.append("validate_plan")
                ranked = self.compare_plans(valid)
                result.tool_calls += 1
                self.trace.append("compare_plans")
                if result.tool_calls > MAX_TOOL_CALLS:
                    raise RuntimeError("shadow agent exceeded its tool-call cap")
                result.candidates = self.describe_ranked_candidates(request, ranked[:3])
                result.rejection_reasons = rejected
                result.action = (
                    AgentAction.PRESENT_CANDIDATES if ranked else AgentAction.NO_RESULT
                )
                return result

        raise RuntimeError("shadow agent exceeded its model-turn cap")

    def retrieve_rider_context(self, request: RideRequest) -> dict[str, Any]:
        return {"preference": request.urban_exposure, "source": "cli_input"}

    def retrieve_world_context(self, request: RideRequest) -> dict[str, Any]:
        return {
            "origin": self.world.get("origins", {}).get(request.origin),
            "traversals": self.repository.list_traversals(),
            "fixture_version": self.world.get("fixture_version"),
        }

    def generate_candidate_plans(
        self, request: RideRequest, world_context: Mapping[str, Any]
    ) -> list[CandidatePlan]:
        """Compose candidates; never invent names, paths, or leg metrics."""
        origin = world_context.get("origin")
        if not origin:
            return []
        origin_anchor_ref = origin.get("anchor_ref")
        recorded_by_ref = {
            traversal.traversal_ref: traversal
            for traversal in self.repository.list_traversals()
        }
        traversals = [
            traversal
            for traversal in world_context.get("traversals", [])
            if isinstance(traversal, Traversal)
            and recorded_by_ref.get(traversal.traversal_ref) == traversal
        ]
        by_role = {
            role: [traversal for traversal in traversals if traversal.role == role]
            for role in ("access", "core", "return")
        }
        candidates: list[CandidatePlan] = []
        for access, core, return_leg in product(
            by_role["access"], by_role["core"], by_role["return"]
        ):
            legs = (access, core, return_leg)
            if len({leg.composition_ref for leg in legs}) != 1:
                continue
            if access.start_anchor_ref != origin_anchor_ref:
                continue
            if return_leg.end_anchor_ref != origin_anchor_ref:
                continue
            if access.end_anchor_ref != core.start_anchor_ref:
                continue
            if core.end_anchor_ref != return_leg.start_anchor_ref:
                continue
            candidates.append(
                CandidatePlan(
                    access=access,
                    core=core,
                    return_leg=return_leg,
                    generation_proof=_GENERATED_CANDIDATE_PROOF,
                )
            )
        return candidates

    def validate_plan(
        self, request: RideRequest, candidates: Sequence[object]
    ) -> tuple[list[CandidatePlan], list[str]]:
        valid: list[CandidatePlan] = []
        rejected: list[str] = []
        requested_exposure = URBAN_EXPOSURE_RANK[request.urban_exposure]
        origin = self.world.get("origins", {}).get(request.origin, {})

        for candidate in candidates:
            if not isinstance(candidate, CandidatePlan) or (
                candidate.generation_proof is not _GENERATED_CANDIDATE_PROOF
            ):
                rejected.append("手写 candidate 未经 grounded generator，拒绝进入系统")
                continue
            reasons: list[str] = []
            if tuple(leg.role for leg in candidate.legs) != ("access", "core", "return"):
                reasons.append("leg roles 不完整")
            if len({leg.composition_ref for leg in candidate.legs}) != 1:
                reasons.append("legs 不属于同一可追溯组合")
            if candidate.access.start_anchor_ref != origin.get("anchor_ref"):
                reasons.append("access 未从本次起点开始")
            if candidate.return_leg.end_anchor_ref != origin.get("anchor_ref"):
                reasons.append("return 未回到本次起点")
            if candidate.access.end_anchor_ref != candidate.core.start_anchor_ref or (
                candidate.core.end_anchor_ref != candidate.return_leg.start_anchor_ref
            ):
                reasons.append("legs 不连续")
            for leg in candidate.legs:
                if self.repository.get_traversal(leg.traversal_ref) != leg:
                    reasons.append(
                        f"{leg.traversal_ref}: leg 不是 repository 当前返回的来源对象"
                    )
                leg_errors = self.repository.eligibility_errors(leg)
                reasons.extend(f"{leg.traversal_ref}: {error}" for error in leg_errors)
            if candidate.estimated_minutes > request.minutes:
                reasons.append("预计时间超过硬限制")
            if candidate.total_climb_m > request.max_climb_m:
                reasons.append("总爬升超过硬限制")
            if URBAN_EXPOSURE_RANK[candidate.urban_exposure] > requested_exposure:
                reasons.append("城区暴露超过偏好")
            if reasons:
                rejected.append(f"{candidate.name}：{'；'.join(reasons)}")
            else:
                valid.append(candidate)
        return valid, rejected

    def compare_plans(self, candidates: list[CandidatePlan]) -> list[CandidatePlan]:
        return sorted(
            candidates,
            key=lambda candidate: (
                URBAN_EXPOSURE_RANK[candidate.urban_exposure],
                candidate.estimated_minutes,
                candidate.total_climb_m,
            ),
        )

    def describe_ranked_candidates(
        self, request: RideRequest, candidates: list[CandidatePlan]
    ) -> list[dict[str, Any]]:
        described: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates, start=1):
            legs = {
                "access": self._leg_view(candidate.access),
                "core": self._leg_view(candidate.core),
                "return": self._leg_view(candidate.return_leg),
            }
            described.append(
                {
                    "name": candidate.name,
                    **legs,
                    "total_distance_km": candidate.total_distance_km,
                    "total_climb_m": candidate.total_climb_m,
                    "estimated_minutes": candidate.estimated_minutes,
                    "urban_exposure": candidate.urban_exposure,
                    "risk": "；".join(dict.fromkeys(leg.risk for leg in candidate.legs)),
                    "unknowns": [],
                    "source_object_refs": [
                        leg.source_object_ref for leg in candidate.legs
                    ],
                    "metrics_provenance_refs": [
                        source_ref
                        for leg in candidate.legs
                        for source_ref in (
                            leg.distance_km.calculation_source_ref,
                            leg.climb_m.calculation_source_ref,
                            leg.estimated_minutes.calculation_source_ref,
                        )
                    ],
                    "recommendation_reason": (
                        f"本次 {request.minutes} 分钟、{request.max_climb_m} m 上限下"
                        f"排名第 {index}；全部 leg 均通过来源与通行校验。"
                    ),
                    "tradeoff": self._tradeoff(candidate, candidates, index),
                }
            )
        return described

    @staticmethod
    def _leg_view(leg: Traversal) -> dict[str, Any]:
        return {
            "traversal_ref": leg.traversal_ref,
            "path_ref": leg.path_ref,
            "start_anchor_ref": leg.start_anchor_ref,
            "end_anchor_ref": leg.end_anchor_ref,
            "source_object_ref": leg.source_object_ref,
            "revision_ref": leg.revision_ref,
            "evidence_refs": [item.evidence_ref for item in leg.evidence],
        }

    @staticmethod
    def _tradeoff(
        candidate: CandidatePlan, candidates: list[CandidatePlan], index: int
    ) -> str:
        if len(candidates) == 1:
            return "这是唯一通过全部 grounding 与硬约束的方案。"
        if index == 1:
            other = candidates[1]
            return (
                f"相对下一方案少用 {other.estimated_minutes - candidate.estimated_minutes:g} 分钟、"
                f"少爬 {other.total_climb_m - candidate.total_climb_m:g} m。"
            )
        leader = candidates[0]
        return (
            f"相对首选增加 {candidate.estimated_minutes - leader.estimated_minutes:g} 分钟、"
            f"{candidate.total_climb_m - leader.total_climb_m:g} m 爬升。"
        )


def render_result(request: RideRequest, result: ShadowResult) -> str:
    if result.action == AgentAction.ASK_ONE_QUESTION:
        return f"需要补充一个问题：{result.question}"
    if result.action == AgentAction.NO_RESULT:
        lines = ["NO_RESULT：没有通过 grounding 与全部硬约束的天龙山门到门候选。"]
        lines.extend(f"拒绝原因：{reason}" for reason in result.rejection_reasons)
        return "\n".join(lines)

    blocks: list[str] = []
    for index, candidate in enumerate(result.candidates, start=1):
        blocks.append(
            "\n".join(
                (
                    f"候选 {index}：{candidate['name']}",
                    _render_leg("access", candidate["access"]),
                    _render_leg("core", candidate["core"]),
                    _render_leg("return", candidate["return"]),
                    f"总距离：{candidate['total_distance_km']:.1f} km",
                    f"总爬升：{candidate['total_climb_m']:g} m",
                    f"预计时间：{candidate['estimated_minutes']:g} 分钟",
                    f"城区暴露：{candidate['urban_exposure']}",
                    f"风险：{candidate['risk']}",
                    "unknowns：无",
                    f"推荐理由：{candidate['recommendation_reason']}",
                    f"方案取舍：{candidate['tradeoff']}",
                    f"metrics provenance：{', '.join(candidate['metrics_provenance_refs'])}",
                )
            )
        )
    blocks.extend(f"淘汰方案：{reason}" for reason in result.rejection_reasons)
    return "\n\n".join(blocks)


def _render_leg(label: str, leg: Mapping[str, Any]) -> str:
    return (
        f"{label}：{leg['path_ref']} | traversal={leg['traversal_ref']} | "
        f"source={leg['source_object_ref']}@{leg['revision_ref']} | "
        f"evidence={','.join(leg['evidence_refs'])}"
    )
