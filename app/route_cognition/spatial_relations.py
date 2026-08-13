"""Deterministic raw-polyline relation witnesses for route research.

This module deliberately does *not* infer road identity.  It compares the complete
source polylines and emits a reproducible research candidate with enough evidence
for later map/topology review.  Extent and direction are independent axes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Sequence


RAW_SPATIAL_RELATION_ALGORITHM_VERSION = "raw_spatial_relation_witness_v1"
RAW_SPATIAL_RELATION_EVIDENCE_SCOPE = "raw_full_polyline_not_road_truth"


@dataclass(frozen=True)
class SpatialRelationConfig:
    """Versioned policy; every classification threshold is visible here."""

    version: str
    sample_spacing_m: float
    match_distance_m: float
    max_heading_delta_deg: float
    min_component_length_m: float
    max_component_gap_m: float
    measure_backtrack_tolerance_m: float
    max_measure_jump_ratio: float
    projection_ambiguity_distance_m: float
    projection_ambiguity_measure_separation_m: float
    component_dedup_min_interval_overlap: float
    equivalent_min_coverage: float
    containment_min_coverage: float
    containment_max_container_coverage: float
    partial_min_coverage: float
    disjoint_max_coverage: float
    parallel_ambiguity_min_coverage: float
    parallel_ambiguity_min_separation_m: float
    parallel_ambiguity_max_distance_spread_m: float
    self_overlap_distance_m: float
    self_overlap_measure_separation_m: float
    coordinate_decimals: int
    metric_decimals: int

    def __post_init__(self) -> None:
        positive = {
            "sample_spacing_m": self.sample_spacing_m,
            "match_distance_m": self.match_distance_m,
            "min_component_length_m": self.min_component_length_m,
            "max_component_gap_m": self.max_component_gap_m,
            "max_measure_jump_ratio": self.max_measure_jump_ratio,
            "projection_ambiguity_measure_separation_m": (
                self.projection_ambiguity_measure_separation_m
            ),
            "parallel_ambiguity_min_separation_m": (
                self.parallel_ambiguity_min_separation_m
            ),
            "self_overlap_distance_m": self.self_overlap_distance_m,
            "self_overlap_measure_separation_m": self.self_overlap_measure_separation_m,
        }
        if not self.version:
            raise ValueError("config version is required")
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        nonnegative = {
            "measure_backtrack_tolerance_m": self.measure_backtrack_tolerance_m,
            "projection_ambiguity_distance_m": self.projection_ambiguity_distance_m,
            "parallel_ambiguity_max_distance_spread_m": (
                self.parallel_ambiguity_max_distance_spread_m
            ),
        }
        for name, value in nonnegative.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not 0 < self.max_heading_delta_deg < 90:
            raise ValueError("max_heading_delta_deg must be between 0 and 90")
        ratios = {
            "equivalent_min_coverage": self.equivalent_min_coverage,
            "component_dedup_min_interval_overlap": (
                self.component_dedup_min_interval_overlap
            ),
            "containment_min_coverage": self.containment_min_coverage,
            "containment_max_container_coverage": self.containment_max_container_coverage,
            "partial_min_coverage": self.partial_min_coverage,
            "disjoint_max_coverage": self.disjoint_max_coverage,
            "parallel_ambiguity_min_coverage": self.parallel_ambiguity_min_coverage,
        }
        for name, value in ratios.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.coordinate_decimals < 0 or self.metric_decimals < 0:
            raise ValueError("decimal precision must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RAW_SPATIAL_RELATION_CONFIG_V1 = SpatialRelationConfig(
    version="xishan_raw_polyline_policy_v1",
    sample_spacing_m=15.0,
    match_distance_m=20.0,
    max_heading_delta_deg=35.0,
    min_component_length_m=75.0,
    max_component_gap_m=30.0,
    measure_backtrack_tolerance_m=12.0,
    max_measure_jump_ratio=3.0,
    projection_ambiguity_distance_m=2.0,
    projection_ambiguity_measure_separation_m=60.0,
    component_dedup_min_interval_overlap=0.80,
    equivalent_min_coverage=0.95,
    containment_min_coverage=0.95,
    containment_max_container_coverage=0.90,
    partial_min_coverage=0.10,
    disjoint_max_coverage=0.02,
    parallel_ambiguity_min_coverage=0.80,
    parallel_ambiguity_min_separation_m=5.0,
    parallel_ambiguity_max_distance_spread_m=3.0,
    self_overlap_distance_m=8.0,
    self_overlap_measure_separation_m=60.0,
    coordinate_decimals=7,
    metric_decimals=3,
)


@dataclass(frozen=True)
class DistanceQuantiles:
    p50: float | None
    p95: float | None
    maximum: float | None

    def to_dict(self, *, decimals: int) -> dict[str, float | None]:
        return {
            "p50": _rounded_optional(self.p50, decimals),
            "p95": _rounded_optional(self.p95, decimals),
            "max": _rounded_optional(self.maximum, decimals),
        }


@dataclass(frozen=True)
class OverlapComponent:
    left_start_m: float
    left_end_m: float
    right_start_m: float
    right_end_m: float
    length_m: float
    orientation: str
    distance_quantiles_m: DistanceQuantiles
    sample_count: int

    def to_dict(self, *, decimals: int) -> dict[str, Any]:
        return {
            "left_interval_m": [
                round(self.left_start_m, decimals),
                round(self.left_end_m, decimals),
            ],
            "right_interval_m": [
                round(self.right_start_m, decimals),
                round(self.right_end_m, decimals),
            ],
            "length_m": round(self.length_m, decimals),
            "orientation": self.orientation,
            "distance_quantiles_m": self.distance_quantiles_m.to_dict(
                decimals=decimals
            ),
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True)
class _LineEvidence:
    source_id: str
    length_m: float
    canonical_hash: str

    def to_dict(self, *, decimals: int) -> dict[str, Any]:
        return {
            "id": self.source_id,
            "length_m": round(self.length_m, decimals),
            "canonical_hash": self.canonical_hash,
        }


@dataclass(frozen=True)
class SpatialRelationResult:
    algorithm_version: str
    config: SpatialRelationConfig
    evidence_scope: str
    left: _LineEvidence
    right: _LineEvidence
    extent_relation: str
    direction_relation: str
    left_coverage_ratio: float
    right_coverage_ratio: float
    left_exclusive_length_m: float
    right_exclusive_length_m: float
    components: tuple[OverlapComponent, ...]
    distance_quantiles_m: DistanceQuantiles
    reason_codes: tuple[str, ...]

    def _payload(self) -> dict[str, Any]:
        decimals = self.config.metric_decimals
        return {
            "algorithm_version": self.algorithm_version,
            "config": self.config.to_dict(),
            "config_sha256": _canonical_sha256(self.config.to_dict()),
            "evidence_scope": self.evidence_scope,
            "left": self.left.to_dict(decimals=decimals),
            "right": self.right.to_dict(decimals=decimals),
            "extent_relation": self.extent_relation,
            "direction_relation": self.direction_relation,
            "left_coverage_ratio": round(self.left_coverage_ratio, decimals),
            "right_coverage_ratio": round(self.right_coverage_ratio, decimals),
            "left_exclusive_length_m": round(self.left_exclusive_length_m, decimals),
            "right_exclusive_length_m": round(self.right_exclusive_length_m, decimals),
            "components": [
                item.to_dict(decimals=decimals) for item in self.components
            ],
            "distance_quantiles_m": self.distance_quantiles_m.to_dict(
                decimals=decimals
            ),
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["result_sha256"] = canonical_result_sha256(self)
        return payload


@dataclass(frozen=True)
class _Polyline:
    xy: tuple[tuple[float, float], ...]
    cumulative_m: tuple[float, ...]
    segment_lengths_m: tuple[float, ...]

    @property
    def length_m(self) -> float:
        return self.cumulative_m[-1]


@dataclass(frozen=True)
class _Sample:
    measure_m: float
    point: tuple[float, float]
    tangent: tuple[float, float]


@dataclass(frozen=True)
class _Projection:
    measure_m: float
    distance_m: float
    tangent: tuple[float, float]
    ambiguous: bool


@dataclass(frozen=True)
class _MatchedSample:
    source_measure_m: float
    target_measure_m: float
    distance_m: float
    orientation: str


@dataclass(frozen=True)
class _OrderedAnalysis:
    components: tuple[OverlapComponent, ...]
    covered_source_intervals: tuple[tuple[float, float], ...]
    matched_distances: tuple[float, ...]
    ambiguity_seen: bool


def analyze_spatial_relation(
    left_id: str | int,
    left_points: Sequence[Sequence[float]],
    right_id: str | int,
    right_points: Sequence[Sequence[float]],
    *,
    config: SpatialRelationConfig,
) -> SpatialRelationResult:
    """Compare two ``[lon, lat]`` polylines without claiming road truth."""

    left_source_id = str(left_id)
    right_source_id = str(right_id)
    left_normalized = _normalize_points(left_points, config.coordinate_decimals)
    right_normalized = _normalize_points(right_points, config.coordinate_decimals)
    left_hash = _canonical_sha256(left_normalized)
    right_hash = _canonical_sha256(right_normalized)

    left_key = (left_source_id, left_hash)
    right_key = (right_source_id, right_hash)
    if left_key <= right_key:
        return _analyze_canonical_order(
            left_source_id,
            left_normalized,
            left_hash,
            right_source_id,
            right_normalized,
            right_hash,
            config,
        )
    canonical = _analyze_canonical_order(
        right_source_id,
        right_normalized,
        right_hash,
        left_source_id,
        left_normalized,
        left_hash,
        config,
    )
    return _swap_result(canonical)


def canonical_result_sha256(result: SpatialRelationResult | dict[str, Any]) -> str:
    """Hash the unordered pair evidence; swapping inputs keeps the same digest."""

    payload = result._payload() if isinstance(result, SpatialRelationResult) else dict(result)
    payload.pop("result_sha256", None)
    left = payload["left"]
    right = payload["right"]
    left_key = (str(left["id"]), str(left["canonical_hash"]))
    right_key = (str(right["id"]), str(right["canonical_hash"]))
    if left_key > right_key:
        payload = _swap_payload(payload)
    return _canonical_sha256(payload)


def _analyze_canonical_order(
    left_id: str,
    left_points: tuple[tuple[float, float], ...],
    left_hash: str,
    right_id: str,
    right_points: tuple[tuple[float, float], ...],
    right_hash: str,
    config: SpatialRelationConfig,
) -> SpatialRelationResult:
    left_xy, right_xy = _project_pair(left_points, right_points)
    left_line = _build_polyline(left_xy)
    right_line = _build_polyline(right_xy)
    left_evidence = _LineEvidence(left_id, left_line.length_m, left_hash)
    right_evidence = _LineEvidence(right_id, right_line.length_m, right_hash)

    exact_same = left_points == right_points
    exact_reverse = left_points == tuple(reversed(right_points))
    if exact_same or exact_reverse:
        direction = "same_direction" if exact_same else "reverse_direction"
        component = OverlapComponent(
            left_start_m=0.0,
            left_end_m=left_line.length_m,
            right_start_m=0.0 if exact_same else right_line.length_m,
            right_end_m=right_line.length_m if exact_same else 0.0,
            length_m=min(left_line.length_m, right_line.length_m),
            orientation="same" if exact_same else "reverse",
            distance_quantiles_m=DistanceQuantiles(0.0, 0.0, 0.0),
            sample_count=max(2, int(left_line.length_m // config.sample_spacing_m) + 1),
        )
        return SpatialRelationResult(
            algorithm_version=RAW_SPATIAL_RELATION_ALGORITHM_VERSION,
            config=config,
            evidence_scope=RAW_SPATIAL_RELATION_EVIDENCE_SCOPE,
            left=left_evidence,
            right=right_evidence,
            extent_relation="source_geometry_identical",
            direction_relation=direction,
            left_coverage_ratio=1.0,
            right_coverage_ratio=1.0,
            left_exclusive_length_m=0.0,
            right_exclusive_length_m=0.0,
            components=(component,),
            distance_quantiles_m=DistanceQuantiles(0.0, 0.0, 0.0),
            reason_codes=(
                "exact_same_sequence" if exact_same else "exact_reverse_sequence",
                "raw_geometry_only_not_road_identity",
            ),
        )

    if _bbox_distance_m(left_line.xy, right_line.xy) > config.match_distance_m:
        return SpatialRelationResult(
            algorithm_version=RAW_SPATIAL_RELATION_ALGORITHM_VERSION,
            config=config,
            evidence_scope=RAW_SPATIAL_RELATION_EVIDENCE_SCOPE,
            left=left_evidence,
            right=right_evidence,
            extent_relation="disjoint",
            direction_relation="indeterminate",
            left_coverage_ratio=0.0,
            right_coverage_ratio=0.0,
            left_exclusive_length_m=left_line.length_m,
            right_exclusive_length_m=right_line.length_m,
            components=(),
            distance_quantiles_m=DistanceQuantiles(None, None, None),
            reason_codes=(
                "expanded_polyline_bbox_disjoint",
                "raw_geometry_only_not_road_identity",
            ),
        )

    left_to_right = _analyze_ordered(left_line, right_line, config)
    right_to_left_raw = _analyze_ordered(right_line, left_line, config)
    right_to_left = _swap_ordered_components(right_to_left_raw)

    left_covered_m = _interval_union_length(left_to_right.covered_source_intervals)
    right_covered_m = _interval_union_length(right_to_left_raw.covered_source_intervals)
    left_coverage = _safe_ratio(left_covered_m, left_line.length_m)
    right_coverage = _safe_ratio(right_covered_m, right_line.length_m)

    all_components = _merge_component_evidence(
        left_to_right.components,
        right_to_left.components,
        config,
    )
    orientations = {component.orientation for component in all_components}
    if orientations == {"same"}:
        direction = "same_direction"
    elif orientations == {"reverse"}:
        direction = "reverse_direction"
    elif orientations:
        direction = "mixed_direction"
    else:
        direction = "indeterminate"

    distances = left_to_right.matched_distances + right_to_left_raw.matched_distances
    distance_quantiles = _quantiles(distances)
    self_overlap = bool(all_components) and (
        _has_self_overlap(left_line, config) or _has_self_overlap(right_line, config)
    )
    projection_ambiguity = (
        left_to_right.ambiguity_seen or right_to_left_raw.ambiguity_seen
    )
    parallel_ambiguity = _looks_like_parallel_near_line(
        left_coverage,
        right_coverage,
        distance_quantiles,
        config,
    )

    reasons: list[str] = ["raw_geometry_only_not_road_identity"]
    if self_overlap:
        reasons.append("self_overlap_requires_topology_review")
    if projection_ambiguity:
        reasons.append("multiple_projection_measures")
    if direction == "mixed_direction":
        reasons.append("mixed_orientation_components")
    if parallel_ambiguity:
        reasons.append("parallel_near_line_ambiguous")

    forced_gray = (
        self_overlap
        or projection_ambiguity
        or direction == "mixed_direction"
        or parallel_ambiguity
    )
    if forced_gray:
        extent = "indeterminate"
    elif (
        left_coverage >= config.equivalent_min_coverage
        and right_coverage >= config.equivalent_min_coverage
    ):
        extent = "equivalent"
        reasons.append("bidirectional_full_coverage")
    elif (
        right_coverage >= config.containment_min_coverage
        and left_coverage <= config.containment_max_container_coverage
    ):
        extent = "a_contains_b"
        reasons.append("right_fully_embedded_in_left")
    elif (
        left_coverage >= config.containment_min_coverage
        and right_coverage <= config.containment_max_container_coverage
    ):
        extent = "b_contains_a"
        reasons.append("left_fully_embedded_in_right")
    elif min(left_coverage, right_coverage) >= config.partial_min_coverage:
        extent = "partial_overlap"
        reasons.append("significant_partial_coverage")
    elif max(left_coverage, right_coverage) <= config.disjoint_max_coverage:
        extent = "disjoint"
        reasons.append("no_significant_overlap_component")
    else:
        extent = "indeterminate"
        reasons.append("coverage_in_policy_gray_zone")

    return SpatialRelationResult(
        algorithm_version=RAW_SPATIAL_RELATION_ALGORITHM_VERSION,
        config=config,
        evidence_scope=RAW_SPATIAL_RELATION_EVIDENCE_SCOPE,
        left=left_evidence,
        right=right_evidence,
        extent_relation=extent,
        direction_relation=direction,
        left_coverage_ratio=left_coverage,
        right_coverage_ratio=right_coverage,
        left_exclusive_length_m=max(0.0, left_line.length_m - left_covered_m),
        right_exclusive_length_m=max(0.0, right_line.length_m - right_covered_m),
        components=all_components,
        distance_quantiles_m=distance_quantiles,
        reason_codes=tuple(sorted(set(reasons))),
    )


def _normalize_points(
    points: Sequence[Sequence[float]], decimals: int
) -> tuple[tuple[float, float], ...]:
    normalized: list[tuple[float, float]] = []
    for point in points:
        if len(point) != 2:
            raise ValueError("each point must contain lon and lat")
        lon, lat = float(point[0]), float(point[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError("coordinates must be finite")
        if not -180 <= lon < 180 or not -90 < lat < 90:
            raise ValueError("coordinates are outside lon/lat bounds")
        lon = round(lon, decimals) or 0.0
        lat = round(lat, decimals) or 0.0
        normalized.append((lon, lat))
    if len(normalized) < 2:
        raise ValueError("a polyline needs at least two points")
    if len(set(normalized)) < 2:
        raise ValueError("a polyline must have positive length")
    return tuple(normalized)


def _project_pair(
    left: Sequence[tuple[float, float]], right: Sequence[tuple[float, float]]
) -> tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...]]:
    combined = tuple(left) + tuple(right)
    origin_lon = sum(point[0] for point in combined) / len(combined)
    origin_lat = sum(point[1] for point in combined) / len(combined)
    radius_m = 6_371_000.0
    lon_scale = math.cos(math.radians(origin_lat))

    def project(points: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
        return tuple(
            (
                math.radians(lon - origin_lon) * radius_m * lon_scale,
                math.radians(lat - origin_lat) * radius_m,
            )
            for lon, lat in points
        )

    return project(left), project(right)


def _build_polyline(points: Sequence[tuple[float, float]]) -> _Polyline:
    collapsed = [points[0]]
    for point in points[1:]:
        if math.dist(collapsed[-1], point) > 1e-9:
            collapsed.append(point)
    if len(collapsed) < 2:
        raise ValueError("a polyline must have positive length")
    segment_lengths = tuple(
        math.dist(collapsed[index - 1], collapsed[index])
        for index in range(1, len(collapsed))
    )
    cumulative = [0.0]
    for length in segment_lengths:
        cumulative.append(cumulative[-1] + length)
    return _Polyline(tuple(collapsed), tuple(cumulative), segment_lengths)


def _sample_polyline(line: _Polyline, spacing_m: float) -> tuple[_Sample, ...]:
    targets = [index * spacing_m for index in range(int(line.length_m // spacing_m) + 1)]
    if not targets or line.length_m - targets[-1] > 1e-9:
        targets.append(line.length_m)
    return tuple(_sample_at(line, target) for target in targets)


def _bbox_distance_m(
    left: Sequence[tuple[float, float]], right: Sequence[tuple[float, float]]
) -> float:
    left_min_x = min(point[0] for point in left)
    left_max_x = max(point[0] for point in left)
    left_min_y = min(point[1] for point in left)
    left_max_y = max(point[1] for point in left)
    right_min_x = min(point[0] for point in right)
    right_max_x = max(point[0] for point in right)
    right_min_y = min(point[1] for point in right)
    right_max_y = max(point[1] for point in right)
    gap_x = max(0.0, left_min_x - right_max_x, right_min_x - left_max_x)
    gap_y = max(0.0, left_min_y - right_max_y, right_min_y - left_max_y)
    return math.hypot(gap_x, gap_y)


def _sample_at(line: _Polyline, measure_m: float) -> _Sample:
    segment_index = len(line.segment_lengths_m) - 1
    for index, end_measure in enumerate(line.cumulative_m[1:]):
        if measure_m <= end_measure + 1e-9:
            segment_index = index
            break
    start = line.xy[segment_index]
    end = line.xy[segment_index + 1]
    length = line.segment_lengths_m[segment_index]
    ratio = max(0.0, min(1.0, (measure_m - line.cumulative_m[segment_index]) / length))
    point = (start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio)
    tangent = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
    return _Sample(measure_m, point, tangent)


def _project_to_polyline(
    point: tuple[float, float], target: _Polyline, config: SpatialRelationConfig
) -> _Projection | None:
    candidates: list[tuple[float, float, tuple[float, float]]] = []
    for index, length in enumerate(target.segment_lengths_m):
        start, end = target.xy[index], target.xy[index + 1]
        dx, dy = end[0] - start[0], end[1] - start[1]
        ratio = max(
            0.0,
            min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (length * length)),
        )
        projected = (start[0] + ratio * dx, start[1] + ratio * dy)
        distance = math.dist(point, projected)
        if distance <= config.match_distance_m:
            candidates.append(
                (
                    distance,
                    target.cumulative_m[index] + ratio * length,
                    (dx / length, dy / length),
                )
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    best = candidates[0]
    ambiguous = any(
        candidate[0] <= best[0] + config.projection_ambiguity_distance_m
        and abs(candidate[1] - best[1])
        >= config.projection_ambiguity_measure_separation_m
        for candidate in candidates[1:]
    )
    return _Projection(best[1], best[0], best[2], ambiguous)


def _orientation(
    source_tangent: tuple[float, float],
    target_tangent: tuple[float, float],
    config: SpatialRelationConfig,
) -> str | None:
    dot = max(
        -1.0,
        min(
            1.0,
            source_tangent[0] * target_tangent[0]
            + source_tangent[1] * target_tangent[1],
        ),
    )
    cosine_limit = math.cos(math.radians(config.max_heading_delta_deg))
    if dot >= cosine_limit:
        return "same"
    if dot <= -cosine_limit:
        return "reverse"
    return None


def _analyze_ordered(
    source: _Polyline, target: _Polyline, config: SpatialRelationConfig
) -> _OrderedAnalysis:
    matched: list[_MatchedSample] = []
    ambiguity_seen = False
    for sample in _sample_polyline(source, config.sample_spacing_m):
        projection = _project_to_polyline(sample.point, target, config)
        if projection is None:
            continue
        if projection.ambiguous:
            ambiguity_seen = True
            continue
        orientation = _orientation(sample.tangent, projection.tangent, config)
        if orientation is None:
            continue
        matched.append(
            _MatchedSample(
                sample.measure_m,
                projection.measure_m,
                projection.distance_m,
                orientation,
            )
        )

    raw_runs: list[list[_MatchedSample]] = []
    run: list[_MatchedSample] = []
    for item in matched:
        if not run:
            run = [item]
            continue
        prior = run[-1]
        source_delta = item.source_measure_m - prior.source_measure_m
        target_delta = item.target_measure_m - prior.target_measure_m
        orientation_ok = item.orientation == prior.orientation
        source_contiguous = source_delta <= config.max_component_gap_m + 1e-9
        if item.orientation == "same":
            monotone = target_delta >= -config.measure_backtrack_tolerance_m
        else:
            monotone = target_delta <= config.measure_backtrack_tolerance_m
        bounded_jump = abs(target_delta) <= (
            source_delta * config.max_measure_jump_ratio
            + config.measure_backtrack_tolerance_m
        )
        if orientation_ok and source_contiguous and monotone and bounded_jump:
            run.append(item)
        else:
            raw_runs.append(run)
            run = [item]
    if run:
        raw_runs.append(run)

    components: list[OverlapComponent] = []
    intervals: list[tuple[float, float]] = []
    retained_distances: list[float] = []
    for items in raw_runs:
        source_start = max(0.0, items[0].source_measure_m - config.sample_spacing_m / 2)
        source_end = min(source.length_m, items[-1].source_measure_m + config.sample_spacing_m / 2)
        target_start = items[0].target_measure_m
        target_end = items[-1].target_measure_m
        component_length = min(
            source_end - source_start,
            abs(target_end - target_start),
        )
        if component_length + 1e-9 < config.min_component_length_m:
            continue
        distances = tuple(item.distance_m for item in items)
        components.append(
            OverlapComponent(
                left_start_m=source_start,
                left_end_m=source_end,
                right_start_m=target_start,
                right_end_m=target_end,
                length_m=component_length,
                orientation=items[0].orientation,
                distance_quantiles_m=_quantiles(distances),
                sample_count=len(items),
            )
        )
        intervals.append((source_start, source_end))
        retained_distances.extend(distances)
    return _OrderedAnalysis(
        tuple(components),
        tuple(intervals),
        tuple(retained_distances),
        ambiguity_seen,
    )


def _swap_ordered_components(analysis: _OrderedAnalysis) -> _OrderedAnalysis:
    return _OrderedAnalysis(
        components=tuple(
            OverlapComponent(
                left_start_m=min(item.right_start_m, item.right_end_m),
                left_end_m=max(item.right_start_m, item.right_end_m),
                right_start_m=(
                    item.left_start_m if item.orientation == "same" else item.left_end_m
                ),
                right_end_m=(
                    item.left_end_m if item.orientation == "same" else item.left_start_m
                ),
                length_m=item.length_m,
                orientation=item.orientation,
                distance_quantiles_m=item.distance_quantiles_m,
                sample_count=item.sample_count,
            )
            for item in analysis.components
        ),
        covered_source_intervals=analysis.covered_source_intervals,
        matched_distances=analysis.matched_distances,
        ambiguity_seen=analysis.ambiguity_seen,
    )


def _merge_component_evidence(
    primary: tuple[OverlapComponent, ...],
    secondary: tuple[OverlapComponent, ...],
    config: SpatialRelationConfig,
) -> tuple[OverlapComponent, ...]:
    """Keep primary occurrences; add only secondary components with no matching witness."""

    result = list(primary)
    for candidate in secondary:
        duplicate = any(
            item.orientation == candidate.orientation
            and _interval_overlap_ratio(
                (item.left_start_m, item.left_end_m),
                (candidate.left_start_m, candidate.left_end_m),
            ) >= config.component_dedup_min_interval_overlap
            and _interval_overlap_ratio(
                (item.right_start_m, item.right_end_m),
                (candidate.right_start_m, candidate.right_end_m),
            ) >= config.component_dedup_min_interval_overlap
            for item in result
        )
        if not duplicate and candidate.length_m >= config.min_component_length_m:
            result.append(candidate)
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.left_start_m,
                item.left_end_m,
                item.right_start_m,
                item.orientation,
            ),
        )
    )


def _has_self_overlap(line: _Polyline, config: SpatialRelationConfig) -> bool:
    for sample in _sample_polyline(line, config.sample_spacing_m):
        for index, length in enumerate(line.segment_lengths_m):
            midpoint_measure = line.cumulative_m[index] + length / 2
            if abs(midpoint_measure - sample.measure_m) < config.self_overlap_measure_separation_m:
                continue
            start, end = line.xy[index], line.xy[index + 1]
            dx, dy = end[0] - start[0], end[1] - start[1]
            ratio = max(
                0.0,
                min(
                    1.0,
                    (
                        (sample.point[0] - start[0]) * dx
                        + (sample.point[1] - start[1]) * dy
                    )
                    / (length * length),
                ),
            )
            projected = (start[0] + ratio * dx, start[1] + ratio * dy)
            projected_measure = line.cumulative_m[index] + ratio * length
            if (
                abs(projected_measure - sample.measure_m)
                >= config.self_overlap_measure_separation_m
                and math.dist(sample.point, projected) <= config.self_overlap_distance_m
            ):
                return True
    return False


def _looks_like_parallel_near_line(
    left_coverage: float,
    right_coverage: float,
    distances: DistanceQuantiles,
    config: SpatialRelationConfig,
) -> bool:
    if distances.p50 is None or distances.p95 is None:
        return False
    return (
        min(left_coverage, right_coverage)
        >= config.parallel_ambiguity_min_coverage
        and distances.p50 >= config.parallel_ambiguity_min_separation_m
        and distances.p95 - distances.p50
        <= config.parallel_ambiguity_max_distance_spread_m
    )


def _quantiles(values: Iterable[float]) -> DistanceQuantiles:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return DistanceQuantiles(None, None, None)
    return DistanceQuantiles(
        _percentile(ordered, 0.50),
        _percentile(ordered, 0.95),
        ordered[-1],
    )


def _percentile(ordered: Sequence[float], percentile: float) -> float:
    position = (len(ordered) - 1) * percentile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _interval_union_length(intervals: Iterable[tuple[float, float]]) -> float:
    normalized = sorted((min(a, b), max(a, b)) for a, b in intervals)
    if not normalized:
        return 0.0
    total = 0.0
    start, end = normalized[0]
    for next_start, next_end in normalized[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _interval_overlap_ratio(
    left: tuple[float, float], right: tuple[float, float]
) -> float:
    left_start, left_end = min(left), max(left)
    right_start, right_end = min(right), max(right)
    overlap = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    denominator = min(left_end - left_start, right_end - right_start)
    return _safe_ratio(overlap, denominator)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _swap_result(result: SpatialRelationResult) -> SpatialRelationResult:
    relation = {
        "a_contains_b": "b_contains_a",
        "b_contains_a": "a_contains_b",
    }.get(result.extent_relation, result.extent_relation)
    return SpatialRelationResult(
        algorithm_version=result.algorithm_version,
        config=result.config,
        evidence_scope=result.evidence_scope,
        left=result.right,
        right=result.left,
        extent_relation=relation,
        direction_relation=result.direction_relation,
        left_coverage_ratio=result.right_coverage_ratio,
        right_coverage_ratio=result.left_coverage_ratio,
        left_exclusive_length_m=result.right_exclusive_length_m,
        right_exclusive_length_m=result.left_exclusive_length_m,
        components=tuple(
            OverlapComponent(
                left_start_m=min(item.right_start_m, item.right_end_m),
                left_end_m=max(item.right_start_m, item.right_end_m),
                right_start_m=(
                    item.left_start_m if item.orientation == "same" else item.left_end_m
                ),
                right_end_m=(
                    item.left_end_m if item.orientation == "same" else item.left_start_m
                ),
                length_m=item.length_m,
                orientation=item.orientation,
                distance_quantiles_m=item.distance_quantiles_m,
                sample_count=item.sample_count,
            )
            for item in result.components
        ),
        distance_quantiles_m=result.distance_quantiles_m,
        reason_codes=tuple(_swap_reason_code(code) for code in result.reason_codes),
    )


def _swap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    swapped = dict(payload)
    swapped["left"], swapped["right"] = payload["right"], payload["left"]
    swapped["left_coverage_ratio"], swapped["right_coverage_ratio"] = (
        payload["right_coverage_ratio"],
        payload["left_coverage_ratio"],
    )
    swapped["left_exclusive_length_m"], swapped["right_exclusive_length_m"] = (
        payload["right_exclusive_length_m"],
        payload["left_exclusive_length_m"],
    )
    swapped["extent_relation"] = {
        "a_contains_b": "b_contains_a",
        "b_contains_a": "a_contains_b",
    }.get(payload["extent_relation"], payload["extent_relation"])
    swapped["reason_codes"] = [
        _swap_reason_code(code) for code in payload["reason_codes"]
    ]
    components = []
    for item in payload["components"]:
        left_start, left_end = item["left_interval_m"]
        right_start, right_end = item["right_interval_m"]
        copied = dict(item)
        copied["left_interval_m"] = [min(right_start, right_end), max(right_start, right_end)]
        copied["right_interval_m"] = (
            [left_start, left_end]
            if item["orientation"] == "same"
            else [left_end, left_start]
        )
        components.append(copied)
    swapped["components"] = sorted(
        components,
        key=lambda item: (
            item["left_interval_m"][0],
            item["left_interval_m"][1],
            item["right_interval_m"][0],
            item["orientation"],
        ),
    )
    return swapped


def _rounded_optional(value: float | None, decimals: int) -> float | None:
    return None if value is None else round(value, decimals)


def _swap_reason_code(code: str) -> str:
    return {
        "left_fully_embedded_in_right": "right_fully_embedded_in_left",
        "right_fully_embedded_in_left": "left_fully_embedded_in_right",
    }.get(code, code)


def _canonical_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
