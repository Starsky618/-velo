"""Deterministic single-carrier projection and bounded evidence arrangement.

This module is deliberately a research/shadow core.  It can linear-reference one
source observation against one carrier polyline and arrange already-projected
facts into directed atomic cells.  It does not infer a road graph, accept a
``ProjectionSet`` as route truth, estimate unique riders, or emit a heat score.

The implementation has no GIS dependency.  Longitude/latitude inputs are mapped
to a carrier-anchored local equirectangular plane, source samples are placed at a
fixed spacing, and a deterministic monotone dynamic program chooses a
directional measure witness.  Considering several projection candidates per
sample is important around hairpins and nearby branches: pointwise nearest
projection alone can jump backwards along carrier measure.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Sequence


CARRIER_PROJECTION_ALGORITHM_VERSION = "single_carrier_monotone_projection_v1"
DIRECTED_EVIDENCE_ALGORITHM_VERSION = "directed_evidence_arrangement_v1"
RESEARCH_EVIDENCE_STATUS = "research_shadow"
EARTH_RADIUS_M = 6_371_008.8


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rounded(value: float, decimals: int) -> float:
    result = round(value, decimals)
    return 0.0 if result == 0 else result


@dataclass(frozen=True)
class CarrierProjectionConfig:
    """Frozen, explicit matching policy for one carrier."""

    version: str
    sample_spacing_m: float
    max_projection_distance_m: float
    candidate_measure_merge_m: float
    max_candidates_per_sample: int
    measure_backtrack_tolerance_m: float
    max_measure_jump_ratio: float
    max_unmatched_gap_m: float
    min_source_coverage_ratio: float
    direction_min_coverage_margin: float
    direction_min_distance_margin_m: float
    coordinate_decimals: int
    metric_decimals: int

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("config version is required")
        positive = {
            "sample_spacing_m": self.sample_spacing_m,
            "max_projection_distance_m": self.max_projection_distance_m,
            "candidate_measure_merge_m": self.candidate_measure_merge_m,
            "max_measure_jump_ratio": self.max_measure_jump_ratio,
            "max_unmatched_gap_m": self.max_unmatched_gap_m,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        nonnegative = {
            "measure_backtrack_tolerance_m": self.measure_backtrack_tolerance_m,
            "direction_min_coverage_margin": self.direction_min_coverage_margin,
            "direction_min_distance_margin_m": self.direction_min_distance_margin_m,
        }
        for name, value in nonnegative.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.max_candidates_per_sample < 1:
            raise ValueError("max_candidates_per_sample must be positive")
        if not 0 <= self.min_source_coverage_ratio <= 1:
            raise ValueError("min_source_coverage_ratio must be between 0 and 1")
        if not 0 <= self.direction_min_coverage_margin <= 1:
            raise ValueError(
                "direction_min_coverage_margin must be between 0 and 1"
            )
        if self.coordinate_decimals < 0 or self.metric_decimals < 0:
            raise ValueError("decimal precision must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CARRIER_PROJECTION_CONFIG_V1 = CarrierProjectionConfig(
    version="single_carrier_research_policy_v1",
    sample_spacing_m=10.0,
    max_projection_distance_m=25.0,
    candidate_measure_merge_m=0.25,
    max_candidates_per_sample=12,
    measure_backtrack_tolerance_m=3.0,
    max_measure_jump_ratio=3.0,
    max_unmatched_gap_m=35.0,
    min_source_coverage_ratio=0.20,
    direction_min_coverage_margin=0.08,
    direction_min_distance_margin_m=2.0,
    coordinate_decimals=7,
    metric_decimals=3,
)


@dataclass(frozen=True)
class ProjectionDistanceQuantiles:
    p50: float | None
    p95: float | None
    maximum: float | None

    def to_dict(self, *, decimals: int) -> dict[str, float | None]:
        return {
            "p50": None if self.p50 is None else _rounded(self.p50, decimals),
            "p95": None if self.p95 is None else _rounded(self.p95, decimals),
            "max": None if self.maximum is None else _rounded(self.maximum, decimals),
        }


@dataclass(frozen=True)
class ProjectionMeasureWitness:
    """One ordered source-measure to carrier-measure match."""

    source_measure_m: float
    carrier_measure_m: float
    distance_m: float

    def to_dict(self, *, decimals: int) -> dict[str, float]:
        return {
            "source_measure_m": _rounded(self.source_measure_m, decimals),
            "carrier_measure_m": _rounded(self.carrier_measure_m, decimals),
            "distance_m": _rounded(self.distance_m, decimals),
        }


@dataclass(frozen=True)
class ProjectionMatchedRun:
    """One contiguous fixed-sample match, suitable as an ArcSlice witness.

    ``carrier_interval_m`` is the ascending physical carrier extent.  The
    traversal start/end fields preserve source order, so reverse runs expose a
    decreasing carrier measure without overloading interval ordering.
    """

    run_index: int
    orientation: str
    source_interval_m: tuple[float, float]
    carrier_interval_m: tuple[float, float]
    carrier_traversal_start_m: float
    carrier_traversal_end_m: float
    witnesses: tuple[ProjectionMeasureWitness, ...]
    distance_quantiles_m: ProjectionDistanceQuantiles

    def __post_init__(self) -> None:
        if self.run_index < 0:
            raise ValueError("run_index must be non-negative")
        if self.orientation not in {"forward", "reverse"}:
            raise ValueError("run orientation must be forward or reverse")
        if self.source_interval_m[1] <= self.source_interval_m[0]:
            raise ValueError("matched run source interval must have positive length")
        if self.carrier_interval_m[1] < self.carrier_interval_m[0]:
            raise ValueError("matched run carrier interval must be ascending")
        if not self.witnesses:
            raise ValueError("matched run requires at least one witness")

    def to_dict(self, *, decimals: int) -> dict[str, Any]:
        payload = {
            "run_index": self.run_index,
            "orientation": self.orientation,
            "source_interval_m": _rounded_interval(
                self.source_interval_m, decimals
            ),
            "carrier_interval_m": _rounded_interval(
                self.carrier_interval_m, decimals
            ),
            "carrier_traversal_start_m": _rounded(
                self.carrier_traversal_start_m, decimals
            ),
            "carrier_traversal_end_m": _rounded(
                self.carrier_traversal_end_m, decimals
            ),
            "witness_count": len(self.witnesses),
            "witnesses": [
                witness.to_dict(decimals=decimals) for witness in self.witnesses
            ],
            "distance_quantiles_m": self.distance_quantiles_m.to_dict(
                decimals=decimals
            ),
        }
        payload["matched_run_sha256"] = _canonical_sha256(payload)
        return payload


@dataclass(frozen=True)
class CarrierProjectionResult:
    algorithm_version: str
    evidence_status: str
    config: CarrierProjectionConfig
    carrier_id: str
    source_id: str
    carrier_geometry_sha256: str
    source_geometry_sha256: str
    carrier_length_m: float
    source_length_m: float
    completion_status: str
    failure_code: str | None
    status: str
    direction: str
    witness_orientation: str | None
    source_coverage_ratio: float
    carrier_coverage_ratio: float
    matched_source_length_m: float
    source_interval_envelope_m: tuple[float, float] | None
    unmatched_source_intervals_m: tuple[tuple[float, float], ...]
    carrier_interval_envelope_m: tuple[float, float] | None
    matched_runs: tuple[ProjectionMatchedRun, ...]
    distance_quantiles_m: ProjectionDistanceQuantiles
    witnesses: tuple[ProjectionMeasureWitness, ...]
    reason_codes: tuple[str, ...]

    def _payload(self) -> dict[str, Any]:
        decimals = self.config.metric_decimals
        return {
            "algorithm_version": self.algorithm_version,
            "evidence_status": self.evidence_status,
            "config": self.config.to_dict(),
            "config_sha256": _canonical_sha256(self.config.to_dict()),
            "carrier_id": self.carrier_id,
            "source_id": self.source_id,
            "carrier_geometry_sha256": self.carrier_geometry_sha256,
            "source_geometry_sha256": self.source_geometry_sha256,
            "carrier_length_m": _rounded(self.carrier_length_m, decimals),
            "source_length_m": _rounded(self.source_length_m, decimals),
            "completion_status": self.completion_status,
            "failure_code": self.failure_code,
            "status": self.status,
            "direction": self.direction,
            "witness_orientation": self.witness_orientation,
            "source_coverage_ratio": _rounded(
                self.source_coverage_ratio, decimals
            ),
            "carrier_coverage_ratio": _rounded(
                self.carrier_coverage_ratio, decimals
            ),
            "matched_source_length_m": _rounded(
                self.matched_source_length_m, decimals
            ),
            "source_interval_envelope_m": _rounded_interval(
                self.source_interval_envelope_m, decimals
            ),
            "unmatched_source_intervals_m": [
                _rounded_interval(interval, decimals)
                for interval in self.unmatched_source_intervals_m
            ],
            "carrier_interval_envelope_m": _rounded_interval(
                self.carrier_interval_envelope_m, decimals
            ),
            "matched_runs": [
                run.to_dict(decimals=decimals) for run in self.matched_runs
            ],
            "distance_quantiles_m": self.distance_quantiles_m.to_dict(
                decimals=decimals
            ),
            "witnesses": [
                witness.to_dict(decimals=decimals) for witness in self.witnesses
            ],
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["result_sha256"] = _canonical_sha256(payload)
        return payload


def _rounded_interval(
    interval: tuple[float, float] | None, decimals: int
) -> list[float] | None:
    if interval is None:
        return None
    return [_rounded(interval[0], decimals), _rounded(interval[1], decimals)]


@dataclass(frozen=True)
class _MetricPolyline:
    xy: tuple[tuple[float, float], ...]
    cumulative_m: tuple[float, ...]
    segment_lengths_m: tuple[float, ...]

    @property
    def length_m(self) -> float:
        return self.cumulative_m[-1]


@dataclass(frozen=True)
class _MetricSample:
    measure_m: float
    point: tuple[float, float]
    coverage_weight_m: float


@dataclass(frozen=True)
class _ProjectionCandidate:
    carrier_measure_m: float
    distance_m: float


@dataclass(frozen=True)
class _MatchPath:
    matched_weight_m: float
    total_distance_m: float
    transition_residual_m: float
    nodes: tuple[tuple[int, _ProjectionCandidate], ...]

    @property
    def mean_distance_m(self) -> float:
        return self.total_distance_m / len(self.nodes)


def project_polyline_to_carrier(
    carrier_id: str | int,
    carrier_points: Sequence[Sequence[float]],
    source_id: str | int,
    source_points: Sequence[Sequence[float]],
    *,
    config: CarrierProjectionConfig = CARRIER_PROJECTION_CONFIG_V1,
) -> CarrierProjectionResult:
    """Project one source polyline to one carrier with an ordered witness.

    The result is always ``research_shadow``.  ``research_projected`` means only
    that this bounded geometric probe found a sufficiently covered, directional
    monotone witness; it is not graph admission or road identity.
    """

    carrier_lonlat = _validated_lonlat(carrier_points, label="carrier_points")
    source_lonlat = _validated_lonlat(source_points, label="source_points")
    anchor_lon = sum(point[0] for point in carrier_lonlat) / len(carrier_lonlat)
    anchor_lat = sum(point[1] for point in carrier_lonlat) / len(carrier_lonlat)
    carrier = _metric_polyline(carrier_lonlat, anchor_lon, anchor_lat)
    source = _metric_polyline(source_lonlat, anchor_lon, anchor_lat)
    samples = _sample_polyline(source, config.sample_spacing_m)
    layers = tuple(
        _projection_candidates(sample.point, carrier, config) for sample in samples
    )

    forward = _best_monotone_path(
        samples, layers, carrier.length_m, "forward", config
    )
    reverse = _best_monotone_path(
        samples, layers, carrier.length_m, "reverse", config
    )
    winner, direction, reasons = _select_direction(
        forward, reverse, source.length_m, config
    )

    if winner is None:
        status = "research_no_candidate"
        completion_status = "incomplete"
        failure_code = "projection_no_candidate"
        direction = "indeterminate"
        witness_orientation = None
        coverage = 0.0
        carrier_coverage = 0.0
        matched_length = 0.0
        source_interval = None
        unmatched_source_intervals = ((0.0, source.length_m),)
        carrier_interval = None
        matched_runs: tuple[ProjectionMatchedRun, ...] = ()
        witnesses: tuple[ProjectionMeasureWitness, ...] = ()
        quantiles = ProjectionDistanceQuantiles(None, None, None)
    else:
        # _select_direction attaches this marker to its reason list so the chosen
        # orientation remains explicit even when final direction is indeterminate.
        witness_orientation = (
            "reverse" if "selected_reverse_witness" in reasons else "forward"
        )
        matched_length = min(source.length_m, winner.matched_weight_m)
        coverage = min(1.0, matched_length / source.length_m)
        matched_source_intervals = _sample_coverage_intervals(
            samples,
            (index for index, _ in winner.nodes),
            source.length_m,
        )
        source_interval = (
            matched_source_intervals[0][0],
            matched_source_intervals[-1][1],
        )
        unmatched_source_intervals = _interval_complement(
            matched_source_intervals, source.length_m
        )
        witnesses = tuple(
            ProjectionMeasureWitness(
                source_measure_m=samples[index].measure_m,
                carrier_measure_m=candidate.carrier_measure_m,
                distance_m=candidate.distance_m,
            )
            for index, candidate in winner.nodes
        )
        matched_runs = _build_matched_runs(
            samples=samples,
            nodes=winner.nodes,
            source_length_m=source.length_m,
            carrier_length_m=carrier.length_m,
            orientation=witness_orientation,
        )
        carrier_interval = (
            min(run.carrier_interval_m[0] for run in matched_runs),
            max(run.carrier_interval_m[1] for run in matched_runs),
        )
        covered_carrier_intervals = _merge_intervals(
            run.carrier_interval_m for run in matched_runs
        )
        carrier_coverage = min(
            1.0,
            sum(end - start for start, end in covered_carrier_intervals)
            / carrier.length_m,
        )
        quantiles = _distance_quantiles(
            [candidate.distance_m for _, candidate in winner.nodes]
        )
        if coverage < config.min_source_coverage_ratio:
            status = "research_insufficient_coverage"
            completion_status = "incomplete"
            failure_code = "projection_geometry_insufficient"
            reasons.append("source_coverage_below_research_threshold")
        elif direction == "indeterminate":
            status = "research_ambiguous_direction"
            completion_status = "incomplete"
            failure_code = "projection_multimodal"
        else:
            status = "research_projected"
            completion_status = "complete"
            failure_code = None
            reasons.append("monotone_measure_witness")

    if unmatched_source_intervals:
        reasons.append("fixed_sample_source_coverage_gap")
    if len(matched_runs) > 1:
        reasons.append("matched_runs_split_at_source_coverage_gap")
    if carrier_interval is not None:
        reasons.append("aggregate_intervals_are_envelopes_not_postings")

    reasons = [reason for reason in reasons if not reason.startswith("selected_")]
    return CarrierProjectionResult(
        algorithm_version=CARRIER_PROJECTION_ALGORITHM_VERSION,
        evidence_status=RESEARCH_EVIDENCE_STATUS,
        config=config,
        carrier_id=str(carrier_id),
        source_id=str(source_id),
        carrier_geometry_sha256=_geometry_sha256(carrier_lonlat, config),
        source_geometry_sha256=_geometry_sha256(source_lonlat, config),
        carrier_length_m=carrier.length_m,
        source_length_m=source.length_m,
        completion_status=completion_status,
        failure_code=failure_code,
        status=status,
        direction=direction,
        witness_orientation=witness_orientation,
        source_coverage_ratio=coverage,
        carrier_coverage_ratio=carrier_coverage,
        matched_source_length_m=matched_length,
        source_interval_envelope_m=source_interval,
        unmatched_source_intervals_m=unmatched_source_intervals,
        carrier_interval_envelope_m=carrier_interval,
        matched_runs=matched_runs,
        distance_quantiles_m=quantiles,
        witnesses=witnesses,
        reason_codes=tuple(sorted(set(reasons))),
    )


def canonical_projection_result_sha256(result: CarrierProjectionResult) -> str:
    return _canonical_sha256(result._payload())


def _validated_lonlat(
    points: Sequence[Sequence[float]], *, label: str
) -> tuple[tuple[float, float], ...]:
    if len(points) < 2:
        raise ValueError(f"{label} must contain at least two points")
    result: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if len(point) < 2:
            raise ValueError(f"{label}[{index}] must contain longitude and latitude")
        lon, lat = float(point[0]), float(point[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise ValueError(f"{label}[{index}] must be finite")
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError(f"{label}[{index}] is outside longitude/latitude bounds")
        if not result or (lon, lat) != result[-1]:
            result.append((lon, lat))
    if len(result) < 2:
        raise ValueError(f"{label} must contain two distinct consecutive points")
    return tuple(result)


def _geometry_sha256(
    points: Sequence[tuple[float, float]], config: CarrierProjectionConfig
) -> str:
    return _canonical_sha256(
        [
            [
                _rounded(point[0], config.coordinate_decimals),
                _rounded(point[1], config.coordinate_decimals),
            ]
            for point in points
        ]
    )


def _metric_polyline(
    points: Sequence[tuple[float, float]], anchor_lon: float, anchor_lat: float
) -> _MetricPolyline:
    cos_lat = math.cos(math.radians(anchor_lat))
    xy = tuple(
        (
            math.radians(lon - anchor_lon) * EARTH_RADIUS_M * cos_lat,
            math.radians(lat - anchor_lat) * EARTH_RADIUS_M,
        )
        for lon, lat in points
    )
    cumulative = [0.0]
    lengths: list[float] = []
    for left, right in zip(xy, xy[1:]):
        length = math.hypot(right[0] - left[0], right[1] - left[1])
        if length <= 1e-9:
            continue
        lengths.append(length)
        cumulative.append(cumulative[-1] + length)
    if not lengths:
        raise ValueError("polyline length must be positive")
    if len(lengths) != len(xy) - 1:
        compact_xy = [xy[0]]
        for point in xy[1:]:
            if math.hypot(
                point[0] - compact_xy[-1][0], point[1] - compact_xy[-1][1]
            ) > 1e-9:
                compact_xy.append(point)
        xy = tuple(compact_xy)
    return _MetricPolyline(
        xy=xy,
        cumulative_m=tuple(cumulative),
        segment_lengths_m=tuple(lengths),
    )


def _sample_polyline(
    line: _MetricPolyline, spacing_m: float
) -> tuple[_MetricSample, ...]:
    measures = [0.0]
    measure = spacing_m
    while measure < line.length_m - 1e-9:
        measures.append(measure)
        measure += spacing_m
    if line.length_m > measures[-1] + 1e-9:
        measures.append(line.length_m)
    points = [_point_at_measure(line, value) for value in measures]
    weights: list[float] = []
    for index, value in enumerate(measures):
        left = 0.0 if index == 0 else (measures[index - 1] + value) / 2
        right = (
            line.length_m
            if index == len(measures) - 1
            else (value + measures[index + 1]) / 2
        )
        weights.append(right - left)
    return tuple(
        _MetricSample(measure_m=value, point=point, coverage_weight_m=weight)
        for value, point, weight in zip(measures, points, weights)
    )


def _sample_coverage_intervals(
    samples: Sequence[_MetricSample],
    matched_indices: Iterable[int],
    source_length_m: float,
) -> tuple[tuple[float, float], ...]:
    """Return the fixed-sample Voronoi intervals represented by matches."""

    intervals: list[tuple[float, float]] = []
    for index in sorted(set(matched_indices)):
        measure = samples[index].measure_m
        start = (
            0.0
            if index == 0
            else (samples[index - 1].measure_m + measure) / 2
        )
        end = (
            source_length_m
            if index == len(samples) - 1
            else (measure + samples[index + 1].measure_m) / 2
        )
        intervals.append((start, end))
    return _merge_intervals(intervals)


def _build_matched_runs(
    *,
    samples: Sequence[_MetricSample],
    nodes: Sequence[tuple[int, _ProjectionCandidate]],
    source_length_m: float,
    carrier_length_m: float,
    orientation: str,
) -> tuple[ProjectionMatchedRun, ...]:
    """Split a match path wherever fixed-sample source coverage is absent."""

    if not nodes:
        return ()
    node_runs: list[list[tuple[int, _ProjectionCandidate]]] = [[nodes[0]]]
    for node in nodes[1:]:
        if node[0] == node_runs[-1][-1][0] + 1:
            node_runs[-1].append(node)
        else:
            node_runs.append([node])

    result: list[ProjectionMatchedRun] = []
    for run_index, run_nodes in enumerate(node_runs):
        source_intervals = _sample_coverage_intervals(
            samples,
            (index for index, _ in run_nodes),
            source_length_m,
        )
        if len(source_intervals) != 1:
            raise ValueError("contiguous matched nodes must form one source interval")
        source_interval = source_intervals[0]
        traversal_start, traversal_end = _run_carrier_traversal_interval(
            samples=samples,
            nodes=run_nodes,
            source_interval_m=source_interval,
            carrier_length_m=carrier_length_m,
            orientation=orientation,
        )
        witnesses = tuple(
            ProjectionMeasureWitness(
                source_measure_m=samples[index].measure_m,
                carrier_measure_m=candidate.carrier_measure_m,
                distance_m=candidate.distance_m,
            )
            for index, candidate in run_nodes
        )
        result.append(
            ProjectionMatchedRun(
                run_index=run_index,
                orientation=orientation,
                source_interval_m=source_interval,
                carrier_interval_m=(
                    min(traversal_start, traversal_end),
                    max(traversal_start, traversal_end),
                ),
                carrier_traversal_start_m=traversal_start,
                carrier_traversal_end_m=traversal_end,
                witnesses=witnesses,
                distance_quantiles_m=_distance_quantiles(
                    [item.distance_m for item in witnesses]
                ),
            )
        )
    return tuple(result)


def _run_carrier_traversal_interval(
    *,
    samples: Sequence[_MetricSample],
    nodes: Sequence[tuple[int, _ProjectionCandidate]],
    source_interval_m: tuple[float, float],
    carrier_length_m: float,
    orientation: str,
) -> tuple[float, float]:
    """Extend endpoint witnesses to their fixed-sample coverage boundaries."""

    first_index, first_candidate = nodes[0]
    last_index, last_candidate = nodes[-1]
    if len(nodes) == 1:
        sign = 1.0 if orientation == "forward" else -1.0
        start_slope = end_slope = sign
    else:
        second_index, second_candidate = nodes[1]
        prior_index, prior_candidate = nodes[-2]
        start_slope = _directional_slope(
            (
                second_candidate.carrier_measure_m
                - first_candidate.carrier_measure_m
            )
            / (samples[second_index].measure_m - samples[first_index].measure_m),
            orientation,
        )
        end_slope = _directional_slope(
            (
                last_candidate.carrier_measure_m
                - prior_candidate.carrier_measure_m
            )
            / (samples[last_index].measure_m - samples[prior_index].measure_m),
            orientation,
        )
    start = first_candidate.carrier_measure_m + start_slope * (
        source_interval_m[0] - samples[first_index].measure_m
    )
    end = last_candidate.carrier_measure_m + end_slope * (
        source_interval_m[1] - samples[last_index].measure_m
    )
    return (
        min(carrier_length_m, max(0.0, start)),
        min(carrier_length_m, max(0.0, end)),
    )


def _directional_slope(raw_slope: float, orientation: str) -> float:
    if orientation == "forward":
        return max(0.0, raw_slope)
    if orientation == "reverse":
        return min(0.0, raw_slope)
    raise ValueError(f"unsupported orientation: {orientation}")


def _interval_complement(
    covered: Sequence[tuple[float, float]], total_length_m: float
) -> tuple[tuple[float, float], ...]:
    result: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in covered:
        if start > cursor + 1e-9:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total_length_m - 1e-9:
        result.append((cursor, total_length_m))
    return tuple(result)


def _point_at_measure(
    line: _MetricPolyline, measure_m: float
) -> tuple[float, float]:
    if measure_m <= 0:
        return line.xy[0]
    if measure_m >= line.length_m:
        return line.xy[-1]
    for index, end in enumerate(line.cumulative_m[1:]):
        if measure_m <= end:
            start = line.cumulative_m[index]
            ratio = (measure_m - start) / line.segment_lengths_m[index]
            left, right = line.xy[index], line.xy[index + 1]
            return (
                left[0] + ratio * (right[0] - left[0]),
                left[1] + ratio * (right[1] - left[1]),
            )
    return line.xy[-1]


def _projection_candidates(
    point: tuple[float, float],
    carrier: _MetricPolyline,
    config: CarrierProjectionConfig,
) -> tuple[_ProjectionCandidate, ...]:
    raw: list[_ProjectionCandidate] = []
    for index, (left, right) in enumerate(zip(carrier.xy, carrier.xy[1:])):
        dx, dy = right[0] - left[0], right[1] - left[1]
        denominator = dx * dx + dy * dy
        t = (
            ((point[0] - left[0]) * dx + (point[1] - left[1]) * dy)
            / denominator
        )
        t = min(1.0, max(0.0, t))
        projected = (left[0] + t * dx, left[1] + t * dy)
        distance = math.hypot(point[0] - projected[0], point[1] - projected[1])
        if distance <= config.max_projection_distance_m:
            raw.append(
                _ProjectionCandidate(
                    carrier_measure_m=(
                        carrier.cumulative_m[index]
                        + t * carrier.segment_lengths_m[index]
                    ),
                    distance_m=distance,
                )
            )
    raw.sort(key=lambda item: (item.carrier_measure_m, item.distance_m))
    merged: list[_ProjectionCandidate] = []
    for candidate in raw:
        if (
            merged
            and candidate.carrier_measure_m - merged[-1].carrier_measure_m
            <= config.candidate_measure_merge_m
        ):
            previous = merged[-1]
            if (candidate.distance_m, candidate.carrier_measure_m) < (
                previous.distance_m,
                previous.carrier_measure_m,
            ):
                merged[-1] = candidate
        else:
            merged.append(candidate)
    closest = sorted(
        merged, key=lambda item: (item.distance_m, item.carrier_measure_m)
    )[: config.max_candidates_per_sample]
    return tuple(sorted(closest, key=lambda item: item.carrier_measure_m))


def _best_monotone_path(
    samples: Sequence[_MetricSample],
    layers: Sequence[Sequence[_ProjectionCandidate]],
    carrier_length_m: float,
    orientation: str,
    config: CarrierProjectionConfig,
) -> _MatchPath | None:
    states: list[list[_MatchPath]] = [[] for _ in samples]
    best: _MatchPath | None = None
    for index, candidates in enumerate(layers):
        for candidate in candidates:
            current = _MatchPath(
                matched_weight_m=samples[index].coverage_weight_m,
                total_distance_m=candidate.distance_m,
                transition_residual_m=0.0,
                nodes=((index, candidate),),
            )
            prior_index = index - 1
            while prior_index >= 0:
                source_delta = (
                    samples[index].measure_m - samples[prior_index].measure_m
                )
                if source_delta > config.max_unmatched_gap_m + 1e-9:
                    break
                for prior in states[prior_index]:
                    prior_candidate = prior.nodes[-1][1]
                    prior_oriented = _oriented_measure(
                        prior_candidate.carrier_measure_m,
                        carrier_length_m,
                        orientation,
                    )
                    current_oriented = _oriented_measure(
                        candidate.carrier_measure_m,
                        carrier_length_m,
                        orientation,
                    )
                    carrier_delta = current_oriented - prior_oriented
                    if carrier_delta < -config.measure_backtrack_tolerance_m:
                        continue
                    if carrier_delta > (
                        source_delta * config.max_measure_jump_ratio
                        + config.measure_backtrack_tolerance_m
                    ):
                        continue
                    proposed = _MatchPath(
                        matched_weight_m=(
                            prior.matched_weight_m
                            + samples[index].coverage_weight_m
                        ),
                        total_distance_m=(
                            prior.total_distance_m + candidate.distance_m
                        ),
                        transition_residual_m=(
                            prior.transition_residual_m
                            + abs(max(0.0, carrier_delta) - source_delta)
                        ),
                        nodes=prior.nodes + ((index, candidate),),
                    )
                    if _path_is_better(proposed, current):
                        current = proposed
                prior_index -= 1
            states[index].append(current)
            if best is None or _path_is_better(current, best):
                best = current
    return best


def _oriented_measure(
    measure_m: float, carrier_length_m: float, orientation: str
) -> float:
    if orientation == "forward":
        return measure_m
    if orientation == "reverse":
        return carrier_length_m - measure_m
    raise ValueError(f"unsupported orientation: {orientation}")


def _path_key(path: _MatchPath) -> tuple[tuple[int, float, float], ...]:
    return tuple(
        (index, candidate.carrier_measure_m, candidate.distance_m)
        for index, candidate in path.nodes
    )


def _path_is_better(candidate: _MatchPath, current: _MatchPath) -> bool:
    candidate_score = (
        candidate.matched_weight_m,
        -candidate.total_distance_m,
        -candidate.transition_residual_m,
        len(candidate.nodes),
    )
    current_score = (
        current.matched_weight_m,
        -current.total_distance_m,
        -current.transition_residual_m,
        len(current.nodes),
    )
    if candidate_score != current_score:
        return candidate_score > current_score
    return _path_key(candidate) < _path_key(current)


def _select_direction(
    forward: _MatchPath | None,
    reverse: _MatchPath | None,
    source_length_m: float,
    config: CarrierProjectionConfig,
) -> tuple[_MatchPath | None, str, list[str]]:
    if forward is None and reverse is None:
        return None, "indeterminate", ["no_sample_within_projection_distance"]
    if reverse is None:
        return forward, "forward", ["selected_forward_witness"]
    if forward is None:
        return reverse, "reverse", ["selected_reverse_witness"]

    forward_coverage = min(1.0, forward.matched_weight_m / source_length_m)
    reverse_coverage = min(1.0, reverse.matched_weight_m / source_length_m)
    coverage_delta = forward_coverage - reverse_coverage
    if abs(coverage_delta) >= config.direction_min_coverage_margin:
        if coverage_delta > 0:
            return forward, "forward", ["selected_forward_witness"]
        return reverse, "reverse", ["selected_reverse_witness"]

    distance_delta = forward.mean_distance_m - reverse.mean_distance_m
    if abs(distance_delta) >= config.direction_min_distance_margin_m:
        if distance_delta < 0:
            return forward, "forward", ["selected_forward_witness"]
        return reverse, "reverse", ["selected_reverse_witness"]

    if _path_is_better(forward, reverse):
        winner, marker = forward, "selected_forward_witness"
    else:
        winner, marker = reverse, "selected_reverse_witness"
    return winner, "indeterminate", [marker, "direction_margin_insufficient"]


def _distance_quantiles(values: Sequence[float]) -> ProjectionDistanceQuantiles:
    if not values:
        return ProjectionDistanceQuantiles(None, None, None)
    ordered = sorted(values)
    return ProjectionDistanceQuantiles(
        p50=_quantile(ordered, 0.50),
        p95=_quantile(ordered, 0.95),
        maximum=ordered[-1],
    )


def _quantile(ordered: Sequence[float], probability: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] + ratio * (ordered[upper] - ordered[lower])


@dataclass(frozen=True)
class EvidenceArrangementConfig:
    """Versioned policy for directed carrier-measure arrangements."""

    version: str
    boundary_tolerance_m: float
    metric_decimals: int

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("config version is required")
        if not math.isfinite(self.boundary_tolerance_m) or self.boundary_tolerance_m <= 0:
            raise ValueError("boundary_tolerance_m must be finite and positive")
        if self.metric_decimals < 0:
            raise ValueError("metric_decimals must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EVIDENCE_ARRANGEMENT_CONFIG_V1 = EvidenceArrangementConfig(
    version="directed_partial_identification_policy_v1",
    boundary_tolerance_m=0.001,
    metric_decimals=3,
)


class EvidenceArrangementError(ValueError):
    """Typed fail-closed evidence arrangement error."""

    def __init__(self, message: str, *, failure_code: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code


class EvidenceSnapshotIncomparableError(EvidenceArrangementError):
    def __init__(self) -> None:
        super().__init__(
            "mixed cohorts are not comparable in one arrangement",
            failure_code="heat_snapshot_incomparable",
        )


@dataclass(frozen=True)
class EvidencePosting:
    """One source fact projected onto one directed carrier interval."""

    source_fact_id: str
    cohort: str
    direction: str
    start_measure_m: float
    end_measure_m: float
    athlete_count: int | None
    effort_count: int | None
    star_count: int | None
    projection_quality: float
    evidence_status: str = RESEARCH_EVIDENCE_STATUS

    def __post_init__(self) -> None:
        if not self.source_fact_id:
            raise ValueError("source_fact_id is required")
        if not self.cohort:
            raise ValueError("cohort is required")
        if self.direction not in {"forward", "reverse"}:
            raise ValueError("direction must be forward or reverse")
        for name, value in {
            "start_measure_m": self.start_measure_m,
            "end_measure_m": self.end_measure_m,
            "projection_quality": self.projection_quality,
        }.items():
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.start_measure_m < 0 or self.end_measure_m <= self.start_measure_m:
            raise ValueError("posting interval must satisfy 0 <= start < end")
        for name, value in {
            "athlete_count": self.athlete_count,
            "effort_count": self.effort_count,
            "star_count": self.star_count,
        }.items():
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if not 0 <= self.projection_quality <= 1:
            raise ValueError("projection_quality must be between 0 and 1")
        if self.evidence_status != RESEARCH_EVIDENCE_STATUS:
            raise ValueError("only research_shadow evidence is accepted by this core")

    def fact_payload(
        self,
    ) -> tuple[str, int | None, int | None, int | None, str]:
        return (
            self.cohort,
            self.athlete_count,
            self.effort_count,
            self.star_count,
            self.evidence_status,
        )

    def to_dict(self, *, decimals: int) -> dict[str, Any]:
        return {
            "source_fact_id": self.source_fact_id,
            "cohort": self.cohort,
            "direction": self.direction,
            "start_measure_m": _rounded(self.start_measure_m, decimals),
            "end_measure_m": _rounded(self.end_measure_m, decimals),
            "athlete_count": self.athlete_count,
            "effort_count": self.effort_count,
            "star_count": self.star_count,
            "projection_quality": _rounded(self.projection_quality, decimals),
            "evidence_status": self.evidence_status,
        }


@dataclass(frozen=True)
class ProxyRange:
    minimum: float | None
    maximum: float | None

    def to_dict(self, *, decimals: int) -> dict[str, float | None]:
        return {
            "min": None if self.minimum is None else _rounded(self.minimum, decimals),
            "max": None if self.maximum is None else _rounded(self.maximum, decimals),
        }


@dataclass(frozen=True)
class DirectedEvidenceCell:
    carrier_id: str
    direction: str
    start_measure_m: float
    end_measure_m: float
    support_state: str
    supporting_fact_ids: tuple[str, ...]
    cohorts: tuple[str, ...]
    snapshot_comparability: str
    reach_union_lower_bound: int | None
    reach_union_upper_bound: int | None
    projection_quality_floor: float | None
    repeat_proxy_range: ProxyRange
    star_proxy_range: ProxyRange
    reason_codes: tuple[str, ...]
    evidence_status: str = RESEARCH_EVIDENCE_STATUS

    def __post_init__(self) -> None:
        if self.direction not in {"forward", "reverse"}:
            raise ValueError("cell direction must be forward or reverse")
        if self.end_measure_m <= self.start_measure_m:
            raise ValueError("cell interval must satisfy start < end")
        if self.support_state not in {"observed", "unobserved"}:
            raise ValueError("support_state must be observed or unobserved")
        expected_comparability = (
            "same_cohort"
            if self.support_state == "observed"
            else "not_applicable_unobserved"
        )
        if self.snapshot_comparability != expected_comparability:
            raise ValueError("snapshot_comparability does not match support state")
        bounds = (self.reach_union_lower_bound, self.reach_union_upper_bound)
        if (bounds[0] is None) != (bounds[1] is None):
            raise ValueError("reach bounds must both be present or both be None")
        if bounds[0] is not None and bounds[0] > bounds[1]:
            raise ValueError("reach lower bound cannot exceed upper bound")
        if self.support_state == "observed":
            if not self.supporting_fact_ids or self.projection_quality_floor is None:
                raise ValueError("observed cell requires fact support and quality")
        elif any(
            (
                self.supporting_fact_ids,
                self.cohorts,
                bounds[0] is not None,
                self.projection_quality_floor is not None,
                self.repeat_proxy_range.minimum is not None,
                self.repeat_proxy_range.maximum is not None,
                self.star_proxy_range.minimum is not None,
                self.star_proxy_range.maximum is not None,
            )
        ):
            raise ValueError("unobserved cell cannot carry evidence values")

    @property
    def length_m(self) -> float:
        return self.end_measure_m - self.start_measure_m

    @property
    def bound_width(self) -> int | None:
        if self.reach_union_lower_bound is None:
            return None
        assert self.reach_union_upper_bound is not None
        return self.reach_union_upper_bound - self.reach_union_lower_bound

    @property
    def raw_support_count(self) -> int:
        return len(self.supporting_fact_ids)

    def to_dict(self, *, decimals: int) -> dict[str, Any]:
        payload = {
            "carrier_id": self.carrier_id,
            "direction": self.direction,
            "start_measure_m": _rounded(self.start_measure_m, decimals),
            "end_measure_m": _rounded(self.end_measure_m, decimals),
            "length_m": _rounded(self.length_m, decimals),
            "support_state": self.support_state,
            "supporting_fact_ids": list(self.supporting_fact_ids),
            "cohorts": list(self.cohorts),
            "snapshot_comparability": self.snapshot_comparability,
            "reach_union_lower_bound": self.reach_union_lower_bound,
            "reach_union_upper_bound": self.reach_union_upper_bound,
            "bound_width": self.bound_width,
            "projection_quality_floor": (
                None
                if self.projection_quality_floor is None
                else _rounded(self.projection_quality_floor, decimals)
            ),
            "raw_support_count": self.raw_support_count,
            "repeat_proxy_range": self.repeat_proxy_range.to_dict(
                decimals=decimals
            ),
            "star_proxy_range": self.star_proxy_range.to_dict(decimals=decimals),
            "reason_codes": list(self.reason_codes),
            "evidence_status": self.evidence_status,
        }
        payload["directed_cell_sha256"] = _canonical_sha256(payload)
        return payload


@dataclass(frozen=True)
class DirectedEvidenceArrangement:
    algorithm_version: str
    evidence_status: str
    config: EvidenceArrangementConfig
    carrier_id: str
    carrier_length_m: float
    source_posting_count: int
    unique_source_fact_count: int
    cells: tuple[DirectedEvidenceCell, ...]
    reason_codes: tuple[str, ...]

    def _payload(self) -> dict[str, Any]:
        decimals = self.config.metric_decimals
        return {
            "algorithm_version": self.algorithm_version,
            "evidence_status": self.evidence_status,
            "config": self.config.to_dict(),
            "config_sha256": _canonical_sha256(self.config.to_dict()),
            "carrier_id": self.carrier_id,
            "carrier_length_m": _rounded(self.carrier_length_m, decimals),
            "source_posting_count": self.source_posting_count,
            "unique_source_fact_count": self.unique_source_fact_count,
            "cells": [cell.to_dict(decimals=decimals) for cell in self.cells],
            "reason_codes": list(self.reason_codes),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._payload()
        payload["result_sha256"] = _canonical_sha256(payload)
        return payload


def arrange_directed_evidence(
    carrier_id: str | int,
    carrier_length_m: float,
    postings: Iterable[EvidencePosting],
    *,
    refinement_boundaries_m: Iterable[float] = (),
    config: EvidenceArrangementConfig = EVIDENCE_ARRANGEMENT_CONFIG_V1,
) -> DirectedEvidenceArrangement:
    """Build atomic directed cells and partial-identification evidence bounds.

    A source fact contributes at most once to a directed cell even if repeated
    postings cover that cell.  Lower ``max(A_i)`` and upper ``sum(A_i)`` are
    bounds only; neither is reported as unique reach or as a heat score.
    """

    if not math.isfinite(carrier_length_m) or carrier_length_m <= 0:
        raise ValueError("carrier_length_m must be finite and positive")
    posting_list = tuple(postings)
    _validate_posting_facts(posting_list, carrier_length_m, config)
    refinement = _normalized_boundaries(
        refinement_boundaries_m, carrier_length_m, config
    )

    cells: list[DirectedEvidenceCell] = []
    for direction in ("forward", "reverse"):
        directed = [item for item in posting_list if item.direction == direction]
        field_refinement = refinement if directed else ()
        boundaries = _normalized_boundaries(
            [0.0, carrier_length_m]
            + [
                boundary
                for item in directed
                for boundary in (item.start_measure_m, item.end_measure_m)
            ]
            + list(field_refinement),
            carrier_length_m,
            config,
        )
        for start, end in zip(boundaries, boundaries[1:]):
            covering = [
                item
                for item in directed
                if item.start_measure_m <= start + config.boundary_tolerance_m
                and item.end_measure_m >= end - config.boundary_tolerance_m
            ]
            if not covering:
                cells.append(
                    DirectedEvidenceCell(
                        carrier_id=str(carrier_id),
                        direction=direction,
                        start_measure_m=start,
                        end_measure_m=end,
                        support_state="unobserved",
                        supporting_fact_ids=(),
                        cohorts=(),
                        snapshot_comparability="not_applicable_unobserved",
                        reach_union_lower_bound=None,
                        reach_union_upper_bound=None,
                        projection_quality_floor=None,
                        repeat_proxy_range=ProxyRange(None, None),
                        star_proxy_range=ProxyRange(None, None),
                        reason_codes=("no_source_fact_coverage",),
                    )
                )
                continue
            by_fact: dict[str, EvidencePosting] = {}
            for item in covering:
                previous = by_fact.get(item.source_fact_id)
                if previous is None or (
                    item.projection_quality,
                    -item.start_measure_m,
                    item.end_measure_m,
                ) > (
                    previous.projection_quality,
                    -previous.start_measure_m,
                    previous.end_measure_m,
                ):
                    by_fact[item.source_fact_id] = item
            facts = [by_fact[fact_id] for fact_id in sorted(by_fact)]
            athlete_counts = [
                item.athlete_count
                for item in facts
                if item.athlete_count is not None
            ]
            repeat_values = [
                value for item in facts if (value := _repeat_proxy(item)) is not None
            ]
            star_values = [
                math.log1p(item.star_count)
                for item in facts
                if item.star_count is not None
            ]
            cells.append(
                DirectedEvidenceCell(
                    carrier_id=str(carrier_id),
                    direction=direction,
                    start_measure_m=start,
                    end_measure_m=end,
                    support_state="observed",
                    supporting_fact_ids=tuple(item.source_fact_id for item in facts),
                    cohorts=tuple(sorted({item.cohort for item in facts})),
                    snapshot_comparability="same_cohort",
                    reach_union_lower_bound=(
                        max(athlete_counts) if athlete_counts else None
                    ),
                    reach_union_upper_bound=(
                        sum(athlete_counts) if athlete_counts else None
                    ),
                    projection_quality_floor=min(
                        item.projection_quality for item in facts
                    ),
                    repeat_proxy_range=_proxy_range(repeat_values),
                    star_proxy_range=_proxy_range(star_values),
                    reason_codes=("source_fact_coverage",),
                )
            )
    cells.sort(
        key=lambda item: (
            0 if item.direction == "forward" else 1,
            item.start_measure_m,
            item.end_measure_m,
            item.supporting_fact_ids,
        )
    )
    reasons = ["partial_identification_bounds_not_unique_reach"]
    if not posting_list:
        reasons.append("no_evidence_postings")
    if any(cell.support_state == "unobserved" for cell in cells):
        reasons.append("unobserved_cells_explicit")
    if len({item.source_fact_id for item in posting_list}) < len(posting_list):
        reasons.append("duplicate_source_fact_postings_collapsed_per_cell")
    if refinement and posting_list:
        reasons.append("explicit_atomic_refinement_boundaries_applied")
    return DirectedEvidenceArrangement(
        algorithm_version=DIRECTED_EVIDENCE_ALGORITHM_VERSION,
        evidence_status=RESEARCH_EVIDENCE_STATUS,
        config=config,
        carrier_id=str(carrier_id),
        carrier_length_m=carrier_length_m,
        source_posting_count=len(posting_list),
        unique_source_fact_count=len(
            {item.source_fact_id for item in posting_list}
        ),
        cells=tuple(cells),
        reason_codes=tuple(sorted(reasons)),
    )


def canonical_evidence_result_sha256(
    result: DirectedEvidenceArrangement,
) -> str:
    return _canonical_sha256(result._payload())


def _validate_posting_facts(
    postings: Sequence[EvidencePosting],
    carrier_length_m: float,
    config: EvidenceArrangementConfig,
) -> None:
    cohorts = {item.cohort for item in postings}
    if len(cohorts) > 1:
        raise EvidenceSnapshotIncomparableError()
    payload_by_fact: dict[
        str, tuple[str, int | None, int | None, int | None, str]
    ] = {}
    for item in postings:
        if item.end_measure_m > carrier_length_m + config.boundary_tolerance_m:
            raise ValueError(
                f"posting {item.source_fact_id!r} exceeds carrier length"
            )
        previous = payload_by_fact.setdefault(item.source_fact_id, item.fact_payload())
        if previous != item.fact_payload():
            raise ValueError(
                f"source_fact_id {item.source_fact_id!r} has conflicting metric payloads"
            )


def _normalized_boundaries(
    values: Iterable[float],
    carrier_length_m: float,
    config: EvidenceArrangementConfig,
) -> tuple[float, ...]:
    checked: list[float] = []
    for raw in values:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("refinement and posting boundaries must be finite")
        if value < -config.boundary_tolerance_m or value > (
            carrier_length_m + config.boundary_tolerance_m
        ):
            raise ValueError("boundary is outside carrier measure range")
        checked.append(min(carrier_length_m, max(0.0, value)))
    checked.sort()
    normalized: list[float] = []
    for value in checked:
        if not normalized or value - normalized[-1] > config.boundary_tolerance_m:
            normalized.append(value)
    return tuple(normalized)


def _repeat_proxy(posting: EvidencePosting) -> float | None:
    if (
        posting.athlete_count is None
        or posting.effort_count is None
        or posting.athlete_count <= 0
    ):
        return None
    repeat_efforts = max(posting.effort_count - posting.athlete_count, 0)
    return repeat_efforts / posting.athlete_count


def _proxy_range(values: Sequence[float]) -> ProxyRange:
    if not values:
        return ProxyRange(None, None)
    return ProxyRange(min(values), max(values))


@dataclass(frozen=True)
class DirectedTraversal:
    direction: str
    start_measure_m: float
    end_measure_m: float

    def __post_init__(self) -> None:
        if self.direction not in {"forward", "reverse"}:
            raise ValueError("direction must be forward or reverse")
        if (
            not math.isfinite(self.start_measure_m)
            or not math.isfinite(self.end_measure_m)
            or self.start_measure_m < 0
            or self.end_measure_m <= self.start_measure_m
        ):
            raise ValueError("traversal interval must satisfy 0 <= start < end")


@dataclass(frozen=True)
class ReachBoundIntegral:
    """Length-weighted reach-bound evidence, with repeated traversal deduped."""

    evidence_status: str
    covered_length_m: float
    lower_person_metres: float | None
    upper_person_metres: float | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (self.lower_person_metres is None) != (self.upper_person_metres is None):
            raise ValueError("integral bounds must both be present or both be None")
        if (
            self.lower_person_metres is not None
            and self.upper_person_metres is not None
            and self.lower_person_metres > self.upper_person_metres + 1e-9
        ):
            raise ValueError("lower bound integral cannot exceed upper bound")


def integrate_directed_reach_bounds(
    cells: Iterable[DirectedEvidenceCell],
    traversals: Iterable[DirectedTraversal],
) -> ReachBoundIntegral:
    """Integrate bounds over each directed carrier interval at most once.

    This is an evidence integral (person-metres), not a popularity score.  The
    union of repeated route traversals is used independently for each direction.
    """

    cell_list = tuple(cells)
    traversal_list = tuple(traversals)
    merged_by_direction = {
        direction: _merge_intervals(
            (item.start_measure_m, item.end_measure_m)
            for item in traversal_list
            if item.direction == direction
        )
        for direction in ("forward", "reverse")
    }
    covered_length = 0.0
    lower = 0.0
    upper = 0.0
    missing_reach_bounds = False
    for cell in cell_list:
        if cell.support_state != "observed":
            continue
        for start, end in merged_by_direction[cell.direction]:
            overlap = max(
                0.0,
                min(cell.end_measure_m, end) - max(cell.start_measure_m, start),
            )
            if overlap <= 0:
                continue
            covered_length += overlap
            if cell.reach_union_lower_bound is None:
                missing_reach_bounds = True
                continue
            assert cell.reach_union_upper_bound is not None
            lower += overlap * cell.reach_union_lower_bound
            upper += overlap * cell.reach_union_upper_bound
    reasons = [
        "reach_bounds_only_not_heat_score",
        "repeated_directed_traversal_counted_once",
        "unobserved_cells_excluded_from_covered_length",
    ]
    if missing_reach_bounds:
        reasons.append("observed_cell_reach_metric_missing")
    return ReachBoundIntegral(
        evidence_status=RESEARCH_EVIDENCE_STATUS,
        covered_length_m=covered_length,
        lower_person_metres=None if missing_reach_bounds else lower,
        upper_person_metres=None if missing_reach_bounds else upper,
        reason_codes=tuple(reasons),
    )


def _merge_intervals(
    intervals: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    ordered = sorted(intervals)
    if not ordered:
        return ()
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)
