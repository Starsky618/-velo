"""跨目的地积木的过境道路研究对象与机械对账。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Iterable, Sequence

from app.parsing.geo_math import haversine


TRANSIT_PATH_SCHEMA_VERSION = "transit_path_research_v1"
TRANSIT_PATH_ALGORITHM_VERSION = "destination_port_transit_path_v1"
TRANSIT_PORT_MAX_ENDPOINT_DISTANCE_M = 30.0
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def geometry_length_m(points: Sequence[Sequence[float]]) -> float:
    if len(points) < 2:
        raise ValueError("transit path geometry needs at least two points")
    total = 0.0
    for previous, current in zip(points, points[1:]):
        if len(previous) < 2 or len(current) < 2:
            raise ValueError("transit path point needs lon and lat")
        lon1, lat1 = float(previous[0]), float(previous[1])
        lon2, lat2 = float(current[0]), float(current[1])
        if not all(math.isfinite(value) for value in (lon1, lat1, lon2, lat2)):
            raise ValueError("transit path coordinates must be finite")
        total += haversine(lat1, lon1, lat2, lon2)
    return total


@dataclass(frozen=True)
class TransitPort:
    port_key: str
    longitude: float
    latitude: float
    binding_type: str
    module_key: str | None = None
    module_port_sha256: str | None = None
    source_observation_id: int | None = None
    source_geometry_hash: str | None = None

    def __post_init__(self) -> None:
        if self.binding_type == "canonical_module_port":
            if not self.module_key or not self.module_port_sha256:
                raise ValueError("canonical transit port needs module binding")
            if not _SHA256_PATTERN.fullmatch(self.module_port_sha256):
                raise ValueError("canonical transit port SHA-256 is invalid")
        elif self.binding_type == "source_observation_candidate":
            if self.source_observation_id is None or not self.source_geometry_hash:
                raise ValueError("candidate transit port needs source binding")
            if not _SHA256_PATTERN.fullmatch(self.source_geometry_hash):
                raise ValueError("candidate transit port geometry SHA-256 is invalid")
        else:
            raise ValueError("unsupported transit port binding type")

    def to_dict(self) -> dict[str, Any]:
        return {
            "port_key": self.port_key,
            "lonlat": [round(self.longitude, 7), round(self.latitude, 7)],
            "binding_type": self.binding_type,
            "module_key": self.module_key,
            "module_port_sha256": self.module_port_sha256,
            "source_observation_id": self.source_observation_id,
            "source_geometry_hash": self.source_geometry_hash,
        }


@dataclass(frozen=True)
class TransitStep:
    road_name: str
    distance_m: float
    instruction: str | None = None
    action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "road_name": self.road_name or "未命名道路",
            "distance_m": round(float(self.distance_m), 1),
            "instruction": self.instruction,
            "action": self.action or "",
        }


@dataclass(frozen=True)
class TransitEvidenceFact:
    source_observation_id: int
    source_segment_id: str
    source_name: str
    source_geometry_hash: str
    source_length_m: float
    shared_length_m: float
    transit_intervals_m: tuple[tuple[float, float], ...]
    transit_coverage_ratio: float
    source_coverage_ratio: float
    direction_relation: str
    extent_relation: str
    evidence_status: str
    reason_codes: tuple[str, ...]
    athlete_count: int | None
    effort_count: int | None
    star_count: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_observation_id": self.source_observation_id,
            "source_segment_id": self.source_segment_id,
            "source_name": self.source_name,
            "source_geometry_hash": self.source_geometry_hash,
            "source_length_m": round(self.source_length_m, 1),
            "shared_length_m": round(self.shared_length_m, 1),
            "transit_intervals_m": [
                [round(start, 1), round(end, 1)]
                for start, end in self.transit_intervals_m
            ],
            "transit_coverage_ratio": round(self.transit_coverage_ratio, 6),
            "source_coverage_ratio": round(self.source_coverage_ratio, 6),
            "direction_relation": self.direction_relation,
            "extent_relation": self.extent_relation,
            "evidence_status": self.evidence_status,
            "reason_codes": list(self.reason_codes),
            "athlete_count": self.athlete_count,
            "effort_count": self.effort_count,
            "star_count": self.star_count,
        }


def build_transit_path(
    *,
    transit_key: str,
    from_port: TransitPort,
    to_port: TransitPort,
    provider: str,
    provider_observed_at: str,
    provider_status: str,
    provider_snapshot_sha256: str,
    evidence_snapshot_sha256: str,
    research_verdict: str,
    provider_distance_m: float,
    provider_duration_raw: float | None,
    geometry_wgs84: Sequence[Sequence[float]],
    steps: Iterable[TransitStep],
    elevation: dict[str, Any],
    evidence_facts: Iterable[TransitEvidenceFact] = (),
) -> dict[str, Any]:
    if not _SHA256_PATTERN.fullmatch(provider_snapshot_sha256):
        raise ValueError("provider snapshot SHA-256 is invalid")
    if not _SHA256_PATTERN.fullmatch(evidence_snapshot_sha256):
        raise ValueError("evidence snapshot SHA-256 is invalid")
    if provider not in {"tencent_driving", "tencent_driving_shadow"}:
        raise ValueError("unsupported transit provider")
    if provider_status not in {
        "research_candidate_not_bicycling_verified",
        "provider_path_not_bicycling_verified",
    }:
        raise ValueError("transit path is missing the bicycling verification boundary")
    if research_verdict not in {
        "connection_candidate",
        "portal_pair_control",
        "portal_pair_control_not_completed_destination_traversal",
        "blocked_after_destination_upper_first_candidate_retraces",
    }:
        raise ValueError("unsupported transit research verdict")
    points = [
        [round(float(point[0]), 7), round(float(point[1]), 7)]
        for point in geometry_wgs84
    ]
    derived_distance_m = geometry_length_m(points)
    from_offset_m = haversine(
        from_port.latitude,
        from_port.longitude,
        points[0][1],
        points[0][0],
    )
    to_offset_m = haversine(
        to_port.latitude,
        to_port.longitude,
        points[-1][1],
        points[-1][0],
    )
    if max(from_offset_m, to_offset_m) > TRANSIT_PORT_MAX_ENDPOINT_DISTANCE_M:
        raise ValueError("transit geometry endpoint does not match its port")
    provider_distance_m = float(provider_distance_m)
    if provider_distance_m <= 0:
        raise ValueError("provider transit distance must be positive")
    difference_ratio = abs(derived_distance_m - provider_distance_m) / provider_distance_m
    if difference_ratio > 0.03:
        raise ValueError("provider and geometry transit distances drift over 3%")
    step_rows = [step.to_dict() for step in steps]
    if not step_rows:
        raise ValueError("transit path must retain ordered road steps")
    step_total_m = sum(row["distance_m"] for row in step_rows)
    if abs(step_total_m - provider_distance_m) / provider_distance_m > 0.03:
        raise ValueError("ordered road steps do not account for provider distance")
    _validate_elevation(elevation, geometry_point_count=len(points), distance_m=derived_distance_m)
    fact_rows = [fact.to_dict() for fact in evidence_facts]
    if len({row["source_observation_id"] for row in fact_rows}) != len(fact_rows):
        raise ValueError("transit evidence observations must be unique")
    for row in fact_rows:
        if not _SHA256_PATTERN.fullmatch(row["source_geometry_hash"]):
            raise ValueError("transit evidence geometry SHA-256 is invalid")
        if row["shared_length_m"] <= 0:
            raise ValueError("transit evidence shared length must be positive")
        if row["source_length_m"] <= 0:
            raise ValueError("transit evidence source length must be positive")
        if not (0 <= row["transit_coverage_ratio"] <= 1):
            raise ValueError("transit evidence coverage must stay within [0, 1]")
        if row["direction_relation"] not in {
            "same_direction",
            "reverse_direction",
            "mixed_direction",
            "indeterminate",
        }:
            raise ValueError("unsupported transit evidence direction")
        if row["evidence_status"] not in {
            "admitted_directional_evidence",
            "diagnostic_indeterminate",
        }:
            raise ValueError("unsupported transit evidence status")
        admitted_extents = {
            "equivalent",
            "a_contains_b",
            "b_contains_a",
            "partial_overlap",
        }
        expected_status = (
            "admitted_directional_evidence"
            if row["extent_relation"] in admitted_extents
            else "diagnostic_indeterminate"
        )
        if row["evidence_status"] != expected_status:
            raise ValueError("transit evidence status contradicts extent relation")
        if not row["transit_intervals_m"]:
            raise ValueError("transit evidence must retain interval witnesses")
        if any(
            start < 0 or end <= start or end > provider_distance_m * 1.03
            for start, end in row["transit_intervals_m"]
        ):
            raise ValueError("transit evidence interval outside path measure")
        fact_intervals = _merge_intervals(row["transit_intervals_m"])
        interval_length_m = sum(end - start for start, end in fact_intervals)
        if abs(interval_length_m - row["shared_length_m"]) > max(
            1.0, row["shared_length_m"] * 0.01
        ):
            raise ValueError("transit evidence shared length and intervals drift")
        expected_transit_coverage = interval_length_m / provider_distance_m
        if abs(row["transit_coverage_ratio"] - expected_transit_coverage) > 0.001:
            raise ValueError("transit evidence path coverage and intervals drift")
        if not 0 <= row["source_coverage_ratio"] <= 1:
            raise ValueError("transit evidence source coverage must stay within [0, 1]")

    road_summary: dict[str, float] = {}
    for row in step_rows:
        road_summary[row["road_name"]] = round(
            road_summary.get(row["road_name"], 0.0) + row["distance_m"],
            1,
        )
    admitted_rows = [
        row
        for row in fact_rows
        if row["evidence_status"] == "admitted_directional_evidence"
    ]
    diagnostic_rows = [
        row
        for row in fact_rows
        if row["evidence_status"] == "diagnostic_indeterminate"
    ]
    intervals = sorted(
        interval
        for row in admitted_rows
        for interval in row["transit_intervals_m"]
    )
    merged_intervals = _merge_intervals(intervals)
    covered_length_m = sum(end - start for start, end in merged_intervals)
    coverage_by_direction: dict[str, dict[str, Any]] = {}
    for direction in (
        "same_direction",
        "reverse_direction",
        "mixed_direction",
        "indeterminate",
    ):
        direction_intervals = _merge_intervals(
            interval
            for row in admitted_rows
            if row["direction_relation"] == direction
            for interval in row["transit_intervals_m"]
        )
        direction_length_m = sum(end - start for start, end in direction_intervals)
        coverage_by_direction[direction] = {
            "covered_length_lower_bound_m": round(direction_length_m, 1),
            "coverage_lower_bound_ratio": round(
                direction_length_m / provider_distance_m,
                6,
            ),
            "covered_intervals_m": [
                [round(start, 1), round(end, 1)]
                for start, end in direction_intervals
            ],
        }
    payload = {
        "schema_version": TRANSIT_PATH_SCHEMA_VERSION,
        "algorithm_version": TRANSIT_PATH_ALGORITHM_VERSION,
        "transit_key": transit_key,
        "from": from_port.to_dict(),
        "to": to_port.to_dict(),
        "provider": provider,
        "provider_observed_at": provider_observed_at,
        "provider_status": provider_status,
        "research_verdict": research_verdict,
        "provider_snapshot_sha256": provider_snapshot_sha256,
        "evidence_snapshot_sha256": evidence_snapshot_sha256,
        "provider_distance_m": round(provider_distance_m, 1),
        "provider_duration_raw": provider_duration_raw,
        "provider_duration_unit": "unknown_not_used",
        "geometry_wgs84": points,
        "geometry_point_count": len(points),
        "derived_geometry_distance_m": round(derived_distance_m, 1),
        "port_endpoint_offsets_m": {
            "from": round(from_offset_m, 1),
            "to": round(to_offset_m, 1),
            "maximum_allowed": TRANSIT_PORT_MAX_ENDPOINT_DISTANCE_M,
        },
        "ordered_road_steps": step_rows,
        "road_summary_m": road_summary,
        "elevation": elevation,
        "evidence_facts": fact_rows,
        "evidence_coverage": {
            "mode": "interval_union_lower_bound",
            "semantic_role": "geometry_coverage_qa_not_directional_heat_score",
            "covered_length_lower_bound_m": round(covered_length_m, 1),
            "covered_intervals_m": [
                [round(start, 1), round(end, 1)]
                for start, end in merged_intervals
            ],
            "coverage_lower_bound_ratio": round(
                covered_length_m / provider_distance_m,
                6,
            ),
            "uncovered_state": "unobserved_not_zero",
            "by_direction": coverage_by_direction,
            "diagnostic_indeterminate_fact_count": len(diagnostic_rows),
        },
        "persistence_role": (
            "research_provider_candidate_not_internal_routing_connector_or_road_truth"
        ),
        "boundary": (
            "provider 提出完整过境道路；来源赛段只投影贡献方向化证据，"
            "不成为必须访问的 waypoint，也不自动证明骑行 access。"
        ),
        "database_write_count": 0,
    }
    payload["result_sha256"] = canonical_sha256(payload)
    return payload


def _merge_intervals(
    intervals: Iterable[Sequence[float]],
) -> list[list[float]]:
    merged: list[list[float]] = []
    for interval in sorted((float(row[0]), float(row[1])) for row in intervals):
        start, end = interval
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def _validate_elevation(
    elevation: dict[str, Any], *, geometry_point_count: int, distance_m: float
) -> None:
    if elevation.get("algorithm_version") != "glo30_meaningful_ascent_v1":
        raise ValueError("transit elevation must use glo30_meaningful_ascent_v1")
    if int(elevation.get("point_count", -1)) != geometry_point_count:
        raise ValueError("transit elevation point count does not match geometry")
    for field in ("climb_m", "descent_m"):
        value = float(elevation.get(field, math.nan))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"transit elevation {field} must be finite and non-negative")
    profile = elevation.get("profile")
    if not isinstance(profile, list) or len(profile) < 2:
        raise ValueError("transit elevation profile is incomplete")
    profile_rows = [[float(value) for value in row[:2]] for row in profile]
    if any(len(row) < 2 or not all(math.isfinite(value) for value in row) for row in profile_rows):
        raise ValueError("transit elevation profile contains invalid values")
    if abs(profile_rows[0][0]) > 0.001:
        raise ValueError("transit elevation profile must start at zero")
    if abs(profile_rows[-1][0] * 1000.0 - distance_m) > max(25.0, distance_m * 0.01):
        raise ValueError("transit elevation profile length does not match geometry")
