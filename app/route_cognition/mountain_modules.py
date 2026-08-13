"""Deterministic mountain route-block views over one reference source axis.

This research core keeps regional data outside the algorithm.  It can assemble
directed evidence and auditable destination-block summaries, but a source
segment endpoint is not a road endpoint.  Transit paths, access, verified road
terminals/turnarounds, and complete ride-plan feasibility belong to later route
assembly.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Sequence

from app.route_cognition.carrier_projection import (
    CARRIER_PROJECTION_ALGORITHM_VERSION,
    CARRIER_PROJECTION_CONFIG_V1,
    DIRECTED_EVIDENCE_ALGORITHM_VERSION,
    DirectedEvidenceArrangement,
    DirectedTraversal,
    EvidencePosting,
    arrange_directed_evidence,
    integrate_directed_reach_bounds,
    project_polyline_to_carrier,
)


MOUNTAIN_MODULE_ALGORITHM_VERSION = "reference_axis_mountain_module_v2"
MOUNTAIN_MODULE_CONFIG_VERSION = "mountain_module_contract_v2"
MOUNTAIN_MODULE_EVIDENCE_STATUS = "research_shadow"
MIN_RESOURCE_ALIGNMENT_RATIO = 0.99


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


MOUNTAIN_MODULE_CONFIG_SHA256 = _canonical_sha256(
    {
        "config_version": MOUNTAIN_MODULE_CONFIG_VERSION,
        "projection_config": CARRIER_PROJECTION_CONFIG_V1.to_dict(),
        "route_resource_accounting": "sum_each_traversed_full_source_fact_once",
        "port_identity": "reference_geometry_hash_axis_measure_direction_role",
        "segment_endpoint_semantics": "observation_boundary_not_road_terminal",
        "route_assembly": "destination_blocks_plus_explicit_transit_paths",
        "ranking_policy": "hard_gate_pareto_intent_lexicographic_optional_ml",
        "min_resource_alignment_ratio": MIN_RESOURCE_ALIGNMENT_RATIO,
    }
)


@dataclass(frozen=True)
class MountainObservation:
    source_observation_id: int
    source_segment_id: str
    source_name: str
    source_geometry_hash: str
    source_geometry_lonlat: tuple[tuple[float, float], ...]
    source_fact_id: str
    derived_distance_m: float
    climb_m: float
    descent_m: float
    elevation_profile: tuple[tuple[float, float], ...]
    athlete_count: int | None
    effort_count: int | None
    star_count: int | None

    def __post_init__(self) -> None:
        if self.source_observation_id <= 0 or not self.source_segment_id:
            raise ValueError("observation identity is required")
        if not self.source_name or not self.source_geometry_hash:
            raise ValueError("observation name and geometry hash are required")
        if len(self.source_geometry_lonlat) < 2:
            raise ValueError("observation geometry requires at least two points")
        for name, value in {
            "derived_distance_m": self.derived_distance_m,
            "climb_m": self.climb_m,
            "descent_m": self.descent_m,
        }.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if len(self.elevation_profile) < 2:
            raise ValueError("observation elevation profile requires two points")


@dataclass(frozen=True)
class MountainModuleSpec:
    module_key: str
    reference_observation_id: int
    heat_snapshot_cohort: str
    observation_ids: tuple[int, ...]
    excluded_source_segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.module_key or not self.heat_snapshot_cohort:
            raise ValueError("module key and heat cohort are required")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("module observation IDs must be unique")
        if self.reference_observation_id not in self.observation_ids:
            raise ValueError("reference observation must belong to the module")


def _observation_payload(item: MountainObservation) -> dict[str, Any]:
    return {
        "source_observation_id": item.source_observation_id,
        "source_segment_id": item.source_segment_id,
        "source_name": item.source_name,
        "source_geometry_hash": item.source_geometry_hash,
        "source_fact_id": item.source_fact_id,
        "derived_distance_m": round(item.derived_distance_m, 3),
        "climb_m": round(item.climb_m, 1),
        "descent_m": round(item.descent_m, 1),
        "elevation_profile": [
            [round(point[0], 4), round(point[1], 1)]
            for point in item.elevation_profile
        ],
        "athlete_count": item.athlete_count,
        "effort_count": item.effort_count,
        "star_count": item.star_count,
    }


def _validate_inputs(
    spec: MountainModuleSpec, observations: Sequence[MountainObservation]
) -> dict[int, MountainObservation]:
    by_id = {item.source_observation_id: item for item in observations}
    if len(by_id) != len(observations):
        raise ValueError("module observations contain duplicate IDs")
    if set(by_id) != set(spec.observation_ids):
        raise ValueError("module observation exact set does not match spec")
    source_ids = [item.source_segment_id for item in observations]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("module observations contain duplicate Strava IDs")
    if set(source_ids) & set(spec.excluded_source_segment_ids):
        raise ValueError("module observations contain an excluded source segment")
    return by_id


def analyze_mountain_module(
    spec: MountainModuleSpec,
    observations: Sequence[MountainObservation],
) -> dict[str, Any]:
    """Project a region onto its reference source axis and arrange heat bounds."""

    by_id = _validate_inputs(spec, observations)
    reference = by_id[spec.reference_observation_id]
    projections = []
    postings = []
    for item in sorted(observations, key=lambda value: value.source_observation_id):
        result = project_polyline_to_carrier(
            f"source-observation:{reference.source_observation_id}",
            reference.source_geometry_lonlat,
            str(item.source_observation_id),
            item.source_geometry_lonlat,
            config=CARRIER_PROJECTION_CONFIG_V1,
        )
        projection = {
            **_observation_payload(item),
            "result": result.to_dict(),
        }
        projection["record_sha256"] = _canonical_sha256(projection)
        projections.append(projection)
        if (
            result.status == "research_projected"
            and result.direction in {"forward", "reverse"}
        ):
            for matched_run in result.matched_runs:
                start, end = matched_run.carrier_interval_m
                if end <= start:
                    continue
                postings.append(
                    EvidencePosting(
                        source_fact_id=item.source_fact_id,
                        cohort=spec.heat_snapshot_cohort,
                        direction=result.direction,
                        start_measure_m=start,
                        end_measure_m=end,
                        athlete_count=item.athlete_count,
                        effort_count=item.effort_count,
                        star_count=item.star_count,
                        projection_quality=result.source_coverage_ratio,
                    )
                )
    reference_projection = next(
        item
        for item in projections
        if item["source_observation_id"] == reference.source_observation_id
    )
    reference_axis_length_m = reference_projection["result"]["carrier_length_m"]
    arrangement = arrange_directed_evidence(
        f"source-observation:{reference.source_observation_id}",
        reference_axis_length_m,
        postings,
    )
    payload = {
        "schema_version": "mountain_module_analysis_v1",
        "algorithm_version": MOUNTAIN_MODULE_ALGORITHM_VERSION,
        "evidence_status": MOUNTAIN_MODULE_EVIDENCE_STATUS,
        "module_key": spec.module_key,
        "reference_observation_id": reference.source_observation_id,
        "reference_source_segment_id": reference.source_segment_id,
        "reference_source_geometry_hash": reference.source_geometry_hash,
        "reference_axis_length_m": reference_axis_length_m,
        "heat_snapshot_cohort": spec.heat_snapshot_cohort,
        "projection_algorithm_version": CARRIER_PROJECTION_ALGORITHM_VERSION,
        "projection_config": CARRIER_PROJECTION_CONFIG_V1.to_dict(),
        "evidence_algorithm_version": DIRECTED_EVIDENCE_ALGORITHM_VERSION,
        "observation_count": len(observations),
        "projection_count": len(projections),
        "accepted_posting_count": len(postings),
        "projections": projections,
        "directed_evidence": arrangement.to_dict(),
        "boundary": (
            "单 Strava 来源线参考轴 research shadow；可证明轴上 occurrence、方向、"
            "原子区间和热度证据范围。来源赛段端点不是道路端点；过境路径、access、"
            "真实断头路掉头和完整路线可达性由后续路线组装证明。"
        ),
    }
    payload["analysis_sha256"] = _canonical_sha256(payload)
    return payload


def heat_evidence_explanation(analysis: dict[str, Any]) -> dict[str, Any]:
    """Expose the final-manual ranking strategy and its learnable boundary."""

    observed = [
        cell
        for cell in analysis["directed_evidence"]["cells"]
        if cell["support_state"] == "observed"
    ]
    return {
        "heat_evidence_mode": "partial_identification_vector",
        "ranking_status": "not_run_by_single_module_slice",
        "ranking_strategy_ref": (
            "final_v2_hard_gate_pareto_intent_lexicographic_v1"
        ),
        "dimensions": [
            {
                "key": "reach_lower_bound_surface",
                "meaning": "至少被多少骑手证据覆盖；重叠 facts 取 max",
                "direction": "higher_is_better",
            },
            {
                "key": "reach_uncertainty_width",
                "meaning": "唯一骑手不可识别造成的上下界宽度",
                "direction": "lower_is_better",
            },
            {
                "key": "repeat_proxy_range",
                "meaning": "effort/athlete 派生的复骑强度范围",
                "direction": "higher_is_more_repeat_evidence",
            },
            {
                "key": "star_proxy_range",
                "meaning": "log1p(star) 收藏意图证据范围",
                "direction": "higher_is_more_intent_evidence",
            },
            {
                "key": "evidence_coverage",
                "meaning": "路线有同方向来源事实支持的距离比例",
                "direction": "higher_is_better",
            },
            {
                "key": "projection_quality_floor",
                "meaning": "参与区间的最低几何投影覆盖质量",
                "direction": "higher_is_better",
            },
        ],
        "density_effect": (
            "重叠赛段只切细区间并收紧/提高该区间证据范围；不增加物理距离、"
            "整线爬升，也不直接相加成唯一骑手数。"
        ),
        "deterministic_fallback": (
            "hard gate -> Pareto non-dominated set -> versioned intent-specific "
            "lexicographic policy -> stable tie-break"
        ),
        "learned_utility": {
            "status": "defined_not_executed_by_single_module_slice",
            "scope": "rerank_hard_feasible_pareto_candidates_only",
            "training_evidence": (
                "同一次候选集内的展示、位置概率、选择/拒绝和完成/放弃 episode"
            ),
            "guardrail": (
                "模型不决定几何、连通、access、硬可行性或重叠去重"
            ),
        },
        "fixed_scalar_weight_status": "rejected_by_design",
        "observed_cell_count": len(observed),
    }


def summarize_route_block(
    analysis: dict[str, Any],
    *,
    block_key: str,
    block_name: str,
    traversals: Iterable[DirectedTraversal],
    distance_m: float,
    climb_m: float,
    descent_m: float,
    recommendation_reasons: Sequence[str],
    traversal_port_keys: Sequence[tuple[str, str]] | None = None,
    arrangement: DirectedEvidenceArrangement | None = None,
) -> dict[str, Any]:
    """Summarize one explicit route block without inventing a scalar heat score."""

    if distance_m < 0 or climb_m < 0 or descent_m < 0:
        raise ValueError("route resources must be non-negative")
    traversal_items = tuple(traversals)
    if len(traversal_items) != 1:
        raise ValueError("destination evidence block requires exactly one traversal")
    port_keys = tuple(traversal_port_keys or ())
    if port_keys and len(port_keys) != len(traversal_items):
        raise ValueError("traversal port keys must match traversals")
    cells = (
        arrangement.cells
        if arrangement is not None
        else _cells_from_payload(analysis["directed_evidence"])
    )
    integral = integrate_directed_reach_bounds(cells, traversal_items)
    covered_km = integral.covered_length_m / 1000
    payload = {
        "block_key": block_key,
        "block_name": block_name,
        "recommendation_status": "evidence_candidate",
        "distance_km": round(distance_m / 1000, 3),
        "climb_m": round(climb_m, 1),
        "descent_m": round(descent_m, 1),
        "traversals": [
            {
                "direction": item.direction,
                "start_measure_m": round(item.start_measure_m, 3),
                "end_measure_m": round(item.end_measure_m, 3),
            }
            for item in traversal_items
        ],
        "traversal_ports": [],
        "heat_evidence": {
            "covered_distance_km": round(covered_km, 3),
            "reach_lower_person_km": (
                None
                if integral.lower_person_metres is None
                else round(integral.lower_person_metres / 1000, 3)
            ),
            "reach_upper_person_km": (
                None
                if integral.upper_person_metres is None
                else round(integral.upper_person_metres / 1000, 3)
            ),
            "meaning": "方向化 reach 证据范围，不是唯一骑手人数或单一热度分",
        },
        "recommendation_policy": (
            "hard gate -> Pareto -> intent-specific lexicographic fallback; "
            "optional learned utility may rerank only hard-feasible Pareto candidates"
        ),
        "recommendation_reasons": list(recommendation_reasons),
        "blockers": [],
        "evidence_status": MOUNTAIN_MODULE_EVIDENCE_STATUS,
    }
    for index, item in enumerate(traversal_items):
        entry_measure = (
            item.start_measure_m
            if item.direction == "forward"
            else item.end_measure_m
        )
        exit_measure = (
            item.end_measure_m
            if item.direction == "forward"
            else item.start_measure_m
        )
        entry_key, exit_key = (
            port_keys[index]
            if port_keys
            else (f"traversal-{index}-entry", f"traversal-{index}-exit")
        )
        ports = []
        for role, port_key, measure in (
            ("entry", entry_key, entry_measure),
            ("exit", exit_key, exit_measure),
        ):
            port = {
                "port_key": port_key,
                "role": role,
                "module_key": analysis["module_key"],
                "reference_source_geometry_hash": analysis[
                    "reference_source_geometry_hash"
                ],
                "axis_measure_m": round(measure, 3),
                "direction": item.direction,
                "boundary_semantics": "source_observation_boundary_not_road_terminal",
            }
            port["port_sha256"] = _canonical_sha256(port)
            ports.append(port)
        payload["traversal_ports"].append(
            {
                "traversal_index": index,
                "entry": ports[0],
                "exit": ports[1],
            }
        )
    payload["block_sha256"] = _canonical_sha256(payload)
    return payload


def _cells_from_payload(payload: dict[str, Any]) -> tuple[Any, ...]:
    """Rebuild typed evidence using the public deterministic core contract."""

    # Re-arranging from the analysis postings would duplicate public payload.  The
    # caller keeps a private typed object only while building a run, so this helper
    # intentionally imports the compact public field types for offline replay.
    from app.route_cognition.carrier_projection import (
        DirectedEvidenceCell,
        ProxyRange,
    )

    result = []
    for item in payload["cells"]:
        result.append(
            DirectedEvidenceCell(
                carrier_id=item["carrier_id"],
                direction=item["direction"],
                start_measure_m=item["start_measure_m"],
                end_measure_m=item["end_measure_m"],
                support_state=item["support_state"],
                supporting_fact_ids=tuple(item["supporting_fact_ids"]),
                cohorts=tuple(item["cohorts"]),
                snapshot_comparability=item["snapshot_comparability"],
                reach_union_lower_bound=item["reach_union_lower_bound"],
                reach_union_upper_bound=item["reach_union_upper_bound"],
                projection_quality_floor=item["projection_quality_floor"],
                repeat_proxy_range=ProxyRange(
                    item["repeat_proxy_range"]["min"],
                    item["repeat_proxy_range"]["max"],
                ),
                star_proxy_range=ProxyRange(
                    item["star_proxy_range"]["min"],
                    item["star_proxy_range"]["max"],
                ),
                reason_codes=tuple(item["reason_codes"]),
                evidence_status=item["evidence_status"],
            )
        )
    return tuple(result)
