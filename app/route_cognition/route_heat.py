"""Deterministic route-level heat evidence and Pareto ranking.

The input cells are already direction-aware atomic intervals.  This layer only
integrates each physical interval once, keeps unknown connector distance as
unobserved, and ranks hard-feasible candidates without inventing a scalar
popularity score.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence


ROUTE_HEAT_ALGORITHM_VERSION = "route_heat_partial_identification_v1"
POPULAR_RELIABLE_POLICY_VERSION = "popular_reliable_lexicographic_v1"


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class RouteHeatComponent:
    component_key: str
    distance_m: float
    climb_m: float
    descent_m: float
    observed_length_m: float
    reach_lower_person_metres: float
    reach_upper_person_metres: float
    conditional_support_numerator: float
    uncertainty_numerator: float
    repeat_proxy_numerator: float
    repeat_proxy_length_m: float
    intent_proxy_numerator: float
    intent_proxy_length_m: float
    projection_quality_numerator: float
    snapshot_comparability: str

    def __post_init__(self) -> None:
        values = (
            self.distance_m,
            self.climb_m,
            self.descent_m,
            self.observed_length_m,
            self.reach_lower_person_metres,
            self.reach_upper_person_metres,
            self.conditional_support_numerator,
            self.uncertainty_numerator,
            self.repeat_proxy_numerator,
            self.repeat_proxy_length_m,
            self.intent_proxy_numerator,
            self.intent_proxy_length_m,
            self.projection_quality_numerator,
        )
        if not self.component_key or any(not math.isfinite(value) for value in values):
            raise ValueError("route heat component contains invalid values")
        if any(value < 0 for value in values):
            raise ValueError("route heat component values must be non-negative")
        if self.observed_length_m > self.distance_m + 1.0:
            raise ValueError("observed evidence cannot exceed component distance")
        if self.reach_lower_person_metres > self.reach_upper_person_metres:
            raise ValueError("route heat lower bound cannot exceed upper bound")
        if self.repeat_proxy_length_m > self.observed_length_m + 1e-6:
            raise ValueError("repeat proxy coverage exceeds observed evidence")
        if self.intent_proxy_length_m > self.observed_length_m + 1e-6:
            raise ValueError("intent proxy coverage exceeds observed evidence")
        if self.snapshot_comparability not in {
            "same_cohort",
            "not_applicable_unobserved",
        }:
            raise ValueError("unsupported heat snapshot comparability")

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_key": self.component_key,
            "distance_km": round(self.distance_m / 1000, 3),
            "climb_m": round(self.climb_m, 1),
            "descent_m": round(self.descent_m, 1),
            "observed_distance_km": round(self.observed_length_m / 1000, 3),
            "reach_lower_person_km": round(
                self.reach_lower_person_metres / 1000, 3
            ),
            "reach_upper_person_km": round(
                self.reach_upper_person_metres / 1000, 3
            ),
            "snapshot_comparability": self.snapshot_comparability,
        }


def component_from_directed_cells(
    *,
    component_key: str,
    distance_m: float,
    climb_m: float,
    descent_m: float,
    cells: Iterable[Mapping[str, Any]],
    direction: str,
    start_measure_m: float = 0.0,
    end_measure_m: float | None = None,
) -> RouteHeatComponent:
    """Integrate already-atomic cells over one directed occurrence."""

    if direction not in {"forward", "reverse"}:
        raise ValueError("route heat direction must be forward or reverse")
    end = float(distance_m if end_measure_m is None else end_measure_m)
    start = float(start_measure_m)
    if start < 0 or end <= start or end > distance_m + 1.0:
        raise ValueError("route heat traversal interval is invalid")

    observed = lower_surface = upper_surface = 0.0
    support_numerator = uncertainty_numerator = 0.0
    repeat_numerator = repeat_length = 0.0
    intent_numerator = intent_length = 0.0
    quality_numerator = 0.0
    cohorts: set[str] = set()
    for cell in cells:
        if cell.get("direction") != direction:
            continue
        low = max(start, float(cell["start_measure_m"]))
        high = min(end, float(cell["end_measure_m"]))
        length = max(0.0, high - low)
        if length <= 0 or cell.get("support_state") != "observed":
            continue
        lower = cell.get("reach_union_lower_bound")
        upper = cell.get("reach_union_upper_bound")
        quality = cell.get("projection_quality_floor")
        if lower is None or upper is None or quality is None:
            raise ValueError("observed route heat cell is incomplete")
        lower = float(lower)
        upper = float(upper)
        if lower < 0 or upper < lower or not 0 <= float(quality) <= 1:
            raise ValueError("observed route heat cell has invalid evidence")
        observed += length
        lower_surface += length * lower
        upper_surface += length * upper
        support_numerator += length * math.log1p(lower)
        uncertainty_numerator += length * math.log((1 + upper) / (1 + lower))
        quality_numerator += length * float(quality)
        cohorts.update(str(value) for value in cell.get("cohorts") or ())

        repeat = cell.get("repeat_proxy_range") or {}
        if repeat.get("minimum") is not None:
            repeat_numerator += length * float(repeat["minimum"])
            repeat_length += length
        elif repeat.get("min") is not None:
            repeat_numerator += length * float(repeat["min"])
            repeat_length += length
        intent = cell.get("star_proxy_range") or {}
        if intent.get("minimum") is not None:
            intent_numerator += length * float(intent["minimum"])
            intent_length += length
        elif intent.get("min") is not None:
            intent_numerator += length * float(intent["min"])
            intent_length += length

    return RouteHeatComponent(
        component_key=component_key,
        distance_m=float(distance_m),
        climb_m=float(climb_m),
        descent_m=float(descent_m),
        observed_length_m=observed,
        reach_lower_person_metres=lower_surface,
        reach_upper_person_metres=upper_surface,
        conditional_support_numerator=support_numerator,
        uncertainty_numerator=uncertainty_numerator,
        repeat_proxy_numerator=repeat_numerator,
        repeat_proxy_length_m=repeat_length,
        intent_proxy_numerator=intent_numerator,
        intent_proxy_length_m=intent_length,
        projection_quality_numerator=quality_numerator,
        snapshot_comparability=(
            "same_cohort" if observed > 0 and len(cohorts) <= 1
            else "not_applicable_unobserved"
        ),
    )


def unobserved_component(
    *, component_key: str, distance_m: float, climb_m: float, descent_m: float
) -> RouteHeatComponent:
    return RouteHeatComponent(
        component_key=component_key,
        distance_m=distance_m,
        climb_m=climb_m,
        descent_m=descent_m,
        observed_length_m=0.0,
        reach_lower_person_metres=0.0,
        reach_upper_person_metres=0.0,
        conditional_support_numerator=0.0,
        uncertainty_numerator=0.0,
        repeat_proxy_numerator=0.0,
        repeat_proxy_length_m=0.0,
        intent_proxy_numerator=0.0,
        intent_proxy_length_m=0.0,
        projection_quality_numerator=0.0,
        snapshot_comparability="not_applicable_unobserved",
    )


def compose_route_heat(
    candidate_id: str,
    components: Sequence[RouteHeatComponent],
) -> dict[str, Any]:
    if not candidate_id or not components:
        raise ValueError("route heat candidate and components are required")
    keys = [item.component_key for item in components]
    if len(keys) != len(set(keys)):
        raise ValueError("route heat component occurrence cannot be counted twice")
    distance = sum(item.distance_m for item in components)
    observed = sum(item.observed_length_m for item in components)
    lower = sum(item.reach_lower_person_metres for item in components)
    upper = sum(item.reach_upper_person_metres for item in components)
    repeat_length = sum(item.repeat_proxy_length_m for item in components)
    intent_length = sum(item.intent_proxy_length_m for item in components)
    payload = {
        "algorithm_version": ROUTE_HEAT_ALGORITHM_VERSION,
        "candidate_id": candidate_id,
        "distance_km": round(distance / 1000, 3),
        "climb_m": round(sum(item.climb_m for item in components), 1),
        "descent_m": round(sum(item.descent_m for item in components), 1),
        "reach_lower_person_km": round(lower / 1000, 3),
        "reach_upper_person_km": round(upper / 1000, 3),
        "reach_uncertainty_width_person_km": round((upper - lower) / 1000, 3),
        "evidence_coverage": round(observed / distance, 6),
        "connector_ratio": round(1 - observed / distance, 6),
        "conditional_support_lower_bound": round(
            sum(item.conditional_support_numerator for item in components)
            / observed,
            6,
        ) if observed else None,
        "uncertainty": round(
            sum(item.uncertainty_numerator for item in components) / distance,
            6,
        ),
        "repeat_proxy": round(
            sum(item.repeat_proxy_numerator for item in components) / repeat_length,
            6,
        ) if repeat_length else None,
        "repeat_proxy_coverage": round(repeat_length / distance, 6),
        "intent_proxy": round(
            sum(item.intent_proxy_numerator for item in components) / intent_length,
            6,
        ) if intent_length else None,
        "intent_proxy_coverage": round(intent_length / distance, 6),
        "projection_quality_coverage": round(
            sum(item.projection_quality_numerator for item in components) / distance,
            6,
        ),
        "snapshot_comparability": (
            "same_cohort_with_unobserved_connectors"
            if any(
                item.observed_length_m < item.distance_m - 1.0
                for item in components
            )
            else "same_cohort"
        ),
        "components": [item.to_dict() for item in components],
        "overlap_accounting": (
            "atomic directed cells count physical distance once; reach lower=max "
            "and upper=sum were resolved before route integration"
        ),
        "unobserved_semantics": "missing evidence is unknown, not zero popularity",
    }
    payload["heat_vector_sha256"] = _canonical_sha256(payload)
    return payload


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    dimensions = (
        ("evidence_coverage", 1),
        ("conditional_support_lower_bound", 1),
        ("uncertainty", -1),
        ("repeat_proxy", 1),
        ("intent_proxy", 1),
        ("projection_quality_coverage", 1),
    )
    strictly_better = False
    for key, direction in dimensions:
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value is None or right_value is None:
            continue
        left_ordered = direction * float(left_value)
        right_ordered = direction * float(right_value)
        if left_ordered < right_ordered - 1e-12:
            return False
        strictly_better |= left_ordered > right_ordered + 1e-12
    return strictly_better


def rank_heat_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    policy_version: str = POPULAR_RELIABLE_POLICY_VERSION,
) -> dict[str, Any]:
    """Rank one intent cohort after hard failures have been applied."""

    if policy_version != POPULAR_RELIABLE_POLICY_VERSION:
        raise ValueError("unsupported route heat ranking policy")
    feasible = [item for item in candidates if not item.get("hard_failure_codes")]
    pareto = [
        item
        for item in feasible
        if not any(_dominates(other["heat_vector"], item["heat_vector"])
                   for other in feasible if other is not item)
    ]

    def key(item: Mapping[str, Any]) -> tuple[Any, ...]:
        vector = item["heat_vector"]
        return (
            -float(vector["evidence_coverage"]),
            -float(vector["conditional_support_lower_bound"] or -1),
            float(vector["uncertainty"]),
            -float(vector["repeat_proxy"] or -1),
            -float(vector["intent_proxy"] or -1),
            -float(vector["projection_quality_coverage"]),
            str(item["candidate_id"]),
        )

    ordered = sorted(pareto, key=key)
    payload = {
        "algorithm_version": ROUTE_HEAT_ALGORITHM_VERSION,
        "policy_version": policy_version,
        "hard_feasible_count": len(feasible),
        "pareto_count": len(pareto),
        "ranked_candidate_ids": [item["candidate_id"] for item in ordered],
        "hard_rejected": [
            {
                "candidate_id": item["candidate_id"],
                "hard_failure_codes": list(item.get("hard_failure_codes") or ()),
            }
            for item in candidates
            if item.get("hard_failure_codes")
        ],
        "rule": (
            "hard gate -> Pareto -> popular reliable lexicographic policy -> "
            "stable candidate id"
        ),
        "learned_rerank_status": "disabled_until_frozen_choice_outcome_episodes",
    }
    payload["ranking_sha256"] = _canonical_sha256(payload)
    return payload
