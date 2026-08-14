"""ClimbPro 输入边界合同。

Climb Planner 只会分析调用者交给它的海拔数组，无法自行判断这段数组究竟是整坡、
半坡还是一条普通道路。这个模块把“剖面算得完整”和“道路身份已经证明完整”拆开，
防止一段局部 Strava 赛段因为数组没有缺点就被误发布为完整命名爬坡。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Literal, Sequence

from app.elevation.route_elevation import (
    RouteElevationResult,
    build_route_elevation_result_from_values,
)


ScopeKind = Literal[
    "named_climb",
    "road_corridor",
    "scenic_axis",
    "identity_candidate",
    "route_composition",
]
ExtentStatus = Literal[
    "full_verified",
    "full_candidate",
    "not_applicable_corridor",
    "identity_pending",
    "partial",
    "complete_route_composition",
]
TraversalDirection = Literal["forward", "reverse", "geometry_order"]


class ClimbProfileContractError(ValueError):
    """输入身份、范围或覆盖率不足，不能进入正式 ClimbPro。"""


@dataclass(frozen=True)
class ClimbProfileContract:
    """一份有向 3D 剖面的身份与范围证明。"""

    scope_key: str
    scope_kind: ScopeKind
    extent_status: ExtentStatus
    traversal_direction: TraversalDirection
    geometry_source: str
    start_anchor: str
    end_anchor: str
    geometry_coverage_ratio: float = 1.0
    elevation_profile_coverage_ratio: float = 1.0
    source_observation_ids: tuple[int, ...] = ()
    source_geometry_hashes: tuple[str, ...] = ()
    anchor_evidence_refs: tuple[str, ...] = ()
    parent_scope_key: str | None = None
    start_offset_m: float | None = None
    end_offset_m: float | None = None

    def validate(self) -> None:
        if not self.scope_key.strip():
            raise ClimbProfileContractError("scope_key is required")
        if not self.geometry_source.strip():
            raise ClimbProfileContractError("geometry_source is required")
        if not self.start_anchor.strip() or not self.end_anchor.strip():
            raise ClimbProfileContractError("start/end anchors are required")
        for field, value in (
            ("geometry_coverage_ratio", self.geometry_coverage_ratio),
            (
                "elevation_profile_coverage_ratio",
                self.elevation_profile_coverage_ratio,
            ),
        ):
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ClimbProfileContractError(f"{field} must be between 0 and 1")
        if self.geometry_coverage_ratio < 0.99:
            raise ClimbProfileContractError("geometry coverage is below 0.99")
        if self.elevation_profile_coverage_ratio < 0.99:
            raise ClimbProfileContractError("elevation profile coverage is below 0.99")
        if len(self.source_observation_ids) != len(set(self.source_observation_ids)):
            raise ClimbProfileContractError("source observations must be unique")
        if any(value <= 0 for value in self.source_observation_ids):
            raise ClimbProfileContractError("source observations must be positive")
        if any(len(value) != 64 for value in self.source_geometry_hashes):
            raise ClimbProfileContractError("source geometry hashes must be sha256")
        if any(not value.strip() for value in self.anchor_evidence_refs):
            raise ClimbProfileContractError("anchor evidence refs cannot be empty")

        if self.scope_kind == "named_climb" and self.extent_status not in {
            "full_verified",
            "full_candidate",
            "partial",
        }:
            raise ClimbProfileContractError(
                "named climb needs full_verified, full_candidate or partial extent"
            )
        if self.extent_status == "full_verified" and not self.anchor_evidence_refs:
            raise ClimbProfileContractError(
                "full_verified needs canonical anchor evidence refs"
            )
        if self.scope_kind == "road_corridor" and self.extent_status != "not_applicable_corridor":
            raise ClimbProfileContractError("road corridor cannot claim a full named climb")
        if self.scope_kind == "scenic_axis" and self.extent_status != "not_applicable_corridor":
            raise ClimbProfileContractError("scenic axis cannot claim a full named climb")
        if self.scope_kind == "identity_candidate" and self.extent_status != "identity_pending":
            raise ClimbProfileContractError("identity candidate must remain identity_pending")
        if self.scope_kind == "route_composition" and self.extent_status != "complete_route_composition":
            raise ClimbProfileContractError(
                "route composition needs complete_route_composition extent"
            )
        if self.extent_status == "partial":
            if not self.parent_scope_key:
                raise ClimbProfileContractError("partial climb needs parent_scope_key")
            if self.start_offset_m is None or self.end_offset_m is None:
                raise ClimbProfileContractError(
                    "partial climb needs start_offset_m and end_offset_m"
                )
            if (
                not math.isfinite(float(self.start_offset_m))
                or not math.isfinite(float(self.end_offset_m))
                or float(self.start_offset_m) < 0
                or float(self.end_offset_m) <= float(self.start_offset_m)
            ):
                raise ClimbProfileContractError("partial climb offsets are invalid")
        elif self.parent_scope_key is not None:
            raise ClimbProfileContractError(
                "parent_scope_key is reserved for partial climb traversals"
            )
        elif self.start_offset_m is not None or self.end_offset_m is not None:
            raise ClimbProfileContractError(
                "start/end offsets are reserved for partial climb traversals"
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["source_observation_ids"] = list(self.source_observation_ids)
        payload["source_geometry_hashes"] = list(self.source_geometry_hashes)
        payload["anchor_evidence_refs"] = list(self.anchor_evidence_refs)
        payload["schema_version"] = "climb_profile_contract_v1"
        return payload


def build_climb_plan_from_contract(
    points: Sequence[Sequence[float]],
    elevations: Sequence[float],
    *,
    contract: ClimbProfileContract,
    source_method: str,
) -> RouteElevationResult:
    """校验整段身份后，从已保存高度重放有向 ClimbPro。"""
    contract.validate()
    if len(points) != len(elevations) or len(points) < 2:
        raise ClimbProfileContractError(
            "geometry and elevation profile must cover the same complete input"
        )
    result = build_route_elevation_result_from_values(
        points,
        elevations,
        source_method=source_method,
    )
    plan = dict(result.climb_plan or {})
    plan["traversal_direction"] = contract.traversal_direction
    plan["input_contract"] = contract.to_dict()
    source = dict(plan.get("source") or {})
    checks = dict(source.get("quality_checks") or {})
    checks["profile_complete_for_input_extent"] = True
    checks["profile_complete_for_route"] = (
        contract.extent_status == "complete_route_composition"
    )
    checks["profile_complete_for_named_climb"] = (
        contract.extent_status == "full_verified"
    )
    checks["profile_complete_for_named_climb_candidate"] = (
        contract.extent_status in {"full_verified", "full_candidate"}
    )
    source["quality_checks"] = checks
    plan["source"] = source
    composition = dict(plan.get("composition") or {})
    composition["input_scope_kind"] = contract.scope_kind
    composition["input_extent_status"] = contract.extent_status
    plan["composition"] = composition
    return replace(result, climb_plan=plan)
