"""Generic deterministic assembly of route-pattern choices.

Segments provide directed evidence, transit paths provide physical connection,
and a traversal says which way the rider uses a frozen geometry.  This layer
validates ordered boundaries and delegates heat accounting to the existing
atomic-cell core.  It does not search a national road graph or invent scenery,
access, rider ability, or route-choice feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
from typing import Any, Mapping, Sequence

from app.parsing.geo_math import haversine
from app.route_cognition.carrier_projection import (
    EvidencePosting,
    arrange_directed_evidence,
    project_polyline_to_carrier,
)
from app.route_cognition.route_heat import (
    component_from_directed_cells,
    compose_route_heat,
)
from app.route_cognition.transit_paths import canonical_sha256


ROUTE_PATTERN_ASSEMBLY_VERSION = "route_pattern_assembly_v1"
ROUTE_CHOICE_EXPLANATION_VERSION = "hard_fact_rider_explanation_v1"
MAX_COMPONENT_JOIN_DISTANCE_M = 30.0
CARRIER_GEOMETRY_NORMALIZATION_VERSION = "lonlat_7dp_directionless_v1"


class RoutePatternAssemblyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Endpoint:
    longitude: float
    latitude: float
    binding_type: str
    source_observation_id: int | None = None
    source_geometry_hash: str | None = None
    module_key: str | None = None
    module_port_sha256: str | None = None
    module_reference_geometry_hash: str | None = None
    module_axis_measure_m: float | None = None


@dataclass(frozen=True)
class _AssembledComponent:
    occurrence_id: str
    kind: str
    entry: _Endpoint
    exit: _Endpoint
    heat: Any
    evidence_source_ids: frozenset[int]
    full_source_traversals: frozenset[tuple[int, str]]
    public_facts: Mapping[str, Any]


def _require_self_hash(payload: Mapping[str, Any], field: str, code: str) -> None:
    declared = payload.get(field)
    unhashed = {key: value for key, value in payload.items() if key != field}
    if not isinstance(declared, str) or declared != canonical_sha256(unhashed):
        raise RoutePatternAssemblyError(code, f"{field} does not match payload")


def _component_geometry_sha256(points: Sequence[Sequence[float]]) -> str:
    """Hash one frozen geometry independently of traversal direction."""

    normalized = [
        [round(float(point[0]), 7), round(float(point[1]), 7)]
        for point in points
    ]
    reversed_normalized = list(reversed(normalized))
    canonical = min(normalized, reversed_normalized)
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _source_index(source_slice: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    _require_self_hash(source_slice, "slice_sha256", "source_slice_hash_mismatch")
    observations = source_slice.get("observations") or []
    by_id = {int(item["source_observation_id"]): item for item in observations}
    if len(by_id) != len(observations):
        raise RoutePatternAssemblyError(
            "duplicate_source_observation", "source observations must be unique"
        )
    source_ids = [str(item["source_segment_id"]) for item in observations]
    if len(source_ids) != len(set(source_ids)):
        raise RoutePatternAssemblyError(
            "duplicate_source_segment", "source segment IDs must be unique"
        )
    for item in observations:
        if item.get("glo_algorithm_version") != "glo30_meaningful_ascent_v1":
            raise RoutePatternAssemblyError(
                "source_glo_fact_invalid", "source fact must use GLO-30"
            )
        if int(item.get("glo_fact_id", 0)) <= 0:
            raise RoutePatternAssemblyError(
                "source_glo_fact_invalid", "source fact ID is missing"
            )
        if len(item.get("source_geometry_lonlat") or []) < 2:
            raise RoutePatternAssemblyError(
                "source_geometry_incomplete", "source geometry is incomplete"
            )
    return by_id


def _validate_selection(
    selection: Mapping[str, Any],
    source_slice: Mapping[str, Any],
    source_by_id: Mapping[int, dict[str, Any]],
) -> None:
    _require_self_hash(selection, "snapshot_sha256", "selection_hash_mismatch")
    if selection.get("source_slice_sha256") != source_slice.get("slice_sha256"):
        raise RoutePatternAssemblyError(
            "selection_source_slice_mismatch",
            "selection references another source slice",
        )
    bindings = selection.get("included_bindings") or []
    if int(selection.get("included_count", -1)) != len(bindings):
        raise RoutePatternAssemblyError(
            "selection_count_mismatch", "selection binding count drift"
        )
    if canonical_sha256(bindings) != selection.get("included_binding_sha256"):
        raise RoutePatternAssemblyError(
            "selection_binding_hash_mismatch", "selection binding hash drift"
        )
    by_observation = {
        int(item["source_observation_id"]): item for item in bindings
    }
    if set(by_observation) != set(source_by_id):
        raise RoutePatternAssemblyError(
            "selection_exact_set_mismatch",
            "selection and source slice do not contain the same observations",
        )
    for observation_id, source in source_by_id.items():
        binding = by_observation[observation_id]
        for field in (
            "source_segment_id",
            "source_geometry_hash",
            "glo_fact_id",
            "glo_algorithm_version",
            "athlete_count",
            "effort_count",
            "star_count",
        ):
            if str(binding.get(field)) != str(source.get(field)):
                raise RoutePatternAssemblyError(
                    "selection_source_binding_mismatch",
                    f"selection {field} does not match source observation",
                )


def _bind_source(
    component_spec: Mapping[str, Any], source_by_id: Mapping[int, dict[str, Any]]
) -> dict[str, Any]:
    observation_id = int(component_spec["source_observation_id"])
    source = source_by_id.get(observation_id)
    if source is None:
        raise RoutePatternAssemblyError(
            "source_observation_missing", f"source observation {observation_id} missing"
        )
    for field in ("source_segment_id", "source_geometry_hash"):
        if str(component_spec.get(field)) != str(source.get(field)):
            raise RoutePatternAssemblyError(
                "source_identity_mismatch", f"source {field} does not match"
            )
    return source


def _source_endpoint(source: Mapping[str, Any], *, at_start: bool) -> _Endpoint:
    point = source["source_geometry_lonlat"][0 if at_start else -1]
    return _Endpoint(
        longitude=float(point[0]),
        latitude=float(point[1]),
        binding_type="source_observation_boundary",
        source_observation_id=int(source["source_observation_id"]),
        source_geometry_hash=str(source["source_geometry_hash"]),
    )


def _source_corridor_component(
    component_spec: Mapping[str, Any],
    source_by_id: Mapping[int, dict[str, Any]],
    *,
    cohort: str,
    projection_cache: dict[int, tuple[float, list[dict[str, Any]]]] | None = None,
) -> _AssembledComponent:
    source = _bind_source(component_spec, source_by_id)
    direction = str(component_spec.get("direction"))
    if direction not in {"forward", "reverse"}:
        raise RoutePatternAssemblyError(
            "source_direction_invalid", "source direction must be forward or reverse"
        )
    cache = projection_cache if projection_cache is not None else {}
    observation_id = int(source["source_observation_id"])
    component_geometry_sha256 = _component_geometry_sha256(
        source["source_geometry_lonlat"]
    )
    cached = cache.get(observation_id)
    if cached is None:
        postings: list[EvidencePosting] = []
        carrier_length_m: float | None = None
        for evidence in sorted(
            source_by_id.values(), key=lambda item: int(item["source_observation_id"])
        ):
            projection = project_polyline_to_carrier(
                f"source-observation:{observation_id}",
                source["source_geometry_lonlat"],
                str(evidence["source_observation_id"]),
                evidence["source_geometry_lonlat"],
            )
            if int(evidence["source_observation_id"]) == observation_id:
                carrier_length_m = float(projection.carrier_length_m)
            if projection.status != "research_projected" or projection.direction not in {
                "forward",
                "reverse",
            }:
                continue
            for matched_run in projection.matched_runs:
                start, end = matched_run.carrier_interval_m
                if end <= start:
                    continue
                postings.append(
                    EvidencePosting(
                        source_fact_id=(
                            f"observation:{evidence['source_observation_id']}"
                        ),
                        cohort=cohort,
                        direction=projection.direction,
                        start_measure_m=start,
                        end_measure_m=end,
                        athlete_count=evidence.get("athlete_count"),
                        effort_count=evidence.get("effort_count"),
                        star_count=evidence.get("star_count"),
                        projection_quality=projection.source_coverage_ratio,
                    )
                )
        if carrier_length_m is None:
            raise RoutePatternAssemblyError(
                "source_self_projection_missing", "source carrier measure is unavailable"
            )
        arrangement = arrange_directed_evidence(
            f"source-observation:{observation_id}",
            carrier_length_m,
            postings,
        )
        cells = arrangement.to_dict()["cells"]
        cache[observation_id] = (carrier_length_m, cells)
    else:
        carrier_length_m, cells = cached
    distance_m = float(source["derived_distance_m"])
    climb = float(source["climb_m"])
    descent = float(source["descent_m"])
    if direction == "reverse":
        climb, descent = descent, climb
    occurrence_id = str(component_spec["occurrence_id"])
    heat = component_from_directed_cells(
        component_key=occurrence_id,
        distance_m=distance_m,
        climb_m=climb,
        descent_m=descent,
        cells=cells,
        direction=direction,
    )
    entry = _source_endpoint(source, at_start=direction == "forward")
    exit = _source_endpoint(source, at_start=direction == "reverse")
    return _AssembledComponent(
        occurrence_id=occurrence_id,
        kind="source_corridor",
        entry=entry,
        exit=exit,
        heat=heat,
        evidence_source_ids=frozenset({observation_id}),
        full_source_traversals=frozenset({(observation_id, direction)}),
        public_facts={
            "occurrence_id": occurrence_id,
            "kind": "source_corridor",
            "component_geometry_sha256": component_geometry_sha256,
            "component_geometry_normalization_version": (
                CARRIER_GEOMETRY_NORMALIZATION_VERSION
            ),
            "component_extent_m": [0.0, round(distance_m, 3)],
            "traversal_orientation": direction,
            "source_observation_id": int(source["source_observation_id"]),
            "source_segment_id": str(source["source_segment_id"]),
            "source_geometry_hash": str(source["source_geometry_hash"]),
            "source_name": source["source_name"],
            "glo_fact_id": int(source["glo_fact_id"]),
            "glo_algorithm_version": str(source["glo_algorithm_version"]),
            "direction": direction,
            "distance_km": round(distance_m / 1000, 3),
            "climb_m": round(climb, 1),
            "descent_m": round(descent, 1),
        },
    )


def _module_port_registry(
    module_runs: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    registry: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for run in module_runs.values():
        for block in run.get("route_blocks") or []:
            for traversal in block.get("traversal_ports") or []:
                for role in ("entry", "exit"):
                    port = traversal[role]
                    registry[
                        (port["module_key"], port["port_key"], port["port_sha256"])
                    ] = port
    return registry


def _module_endpoint(
    port: Mapping[str, Any],
    source_by_id: Mapping[int, dict[str, Any]],
) -> _Endpoint:
    reference_hash = str(port["reference_source_geometry_hash"])
    source = next(
        (
            item
            for item in source_by_id.values()
            if item["source_geometry_hash"] == reference_hash
        ),
        None,
    )
    if source is None:
        raise RoutePatternAssemblyError(
            "module_reference_source_missing", "module reference source is unavailable"
        )
    measure = float(port["axis_measure_m"])
    distance = float(source["derived_distance_m"])
    if min(measure, abs(distance - measure)) > MAX_COMPONENT_JOIN_DISTANCE_M:
        raise RoutePatternAssemblyError(
            "module_port_not_endpoint", "v1 module port must be an axis endpoint"
        )
    point = source["source_geometry_lonlat"][0 if measure <= distance / 2 else -1]
    return _Endpoint(
        longitude=float(point[0]),
        latitude=float(point[1]),
        binding_type="canonical_module_port",
        module_key=str(port["module_key"]),
        module_port_sha256=str(port["port_sha256"]),
        module_reference_geometry_hash=reference_hash,
        module_axis_measure_m=measure,
    )


def _mountain_component(
    component_spec: Mapping[str, Any],
    source_by_id: Mapping[int, dict[str, Any]],
    module_runs: Mapping[str, Mapping[str, Any]],
) -> _AssembledComponent:
    module_key = str(component_spec["module_key"])
    run = module_runs.get(module_key)
    if run is None:
        raise RoutePatternAssemblyError("module_run_missing", "module run is unavailable")
    _require_self_hash(run, "run_sha256", "module_run_hash_mismatch")
    if run["run_sha256"] != component_spec.get("run_sha256"):
        raise RoutePatternAssemblyError(
            "module_run_binding_mismatch", "candidate references another module run"
        )
    block_key = str(component_spec["block_key"])
    blocks = [item for item in run["route_blocks"] if item["block_key"] == block_key]
    if len(blocks) != 1:
        raise RoutePatternAssemblyError(
            "mountain_block_missing", "mountain block must exist exactly once"
        )
    block = blocks[0]
    declared_block_hash = block.get("block_sha256")
    unhashed_block = {key: value for key, value in block.items() if key != "block_sha256"}
    if declared_block_hash != canonical_sha256(unhashed_block):
        raise RoutePatternAssemblyError(
            "mountain_block_hash_mismatch", "mountain block hash drift"
        )
    if block.get("blockers"):
        raise RoutePatternAssemblyError(
            "mountain_block_blocked", "mountain block contains blockers"
        )
    for projection in run["analysis"].get("projections") or []:
        source = source_by_id.get(int(projection["source_observation_id"]))
        if source is None:
            raise RoutePatternAssemblyError(
                "module_source_outside_active_selection",
                "module source is outside the active road selection",
            )
        for field in (
            "source_segment_id",
            "source_geometry_hash",
            "athlete_count",
            "effort_count",
            "star_count",
        ):
            if str(projection.get(field)) != str(source.get(field)):
                raise RoutePatternAssemblyError(
                    "module_source_binding_mismatch",
                    f"module source {field} drift",
                )
    traversals = block.get("traversals") or []
    ports = block.get("traversal_ports") or []
    if len(traversals) != 1 or len(ports) != 1:
        raise RoutePatternAssemblyError(
            "mountain_traversal_invalid", "v1 block needs exactly one traversal"
        )
    traversal_direction = str(component_spec.get("traversal_direction", "stored"))
    if traversal_direction not in {"stored", "reverse"}:
        raise RoutePatternAssemblyError(
            "mountain_direction_invalid",
            "mountain traversal direction must be stored or reverse",
        )
    traversal = traversals[0]
    stored_direction = str(traversal["direction"])
    direction = stored_direction
    distance_m = float(block["distance_km"]) * 1000
    climb_m = float(block["climb_m"])
    descent_m = float(block["descent_m"])
    raw_entry = ports[0]["entry"]
    raw_exit = ports[0]["exit"]
    reference_source = next(
        item
        for item in source_by_id.values()
        if item["source_geometry_hash"]
        == run["analysis"]["reference_source_geometry_hash"]
    )
    component_geometry_sha256 = _component_geometry_sha256(
        reference_source["source_geometry_lonlat"]
    )
    if traversal_direction == "reverse":
        direction = "reverse" if stored_direction == "forward" else "forward"
        climb_m, descent_m = descent_m, climb_m
        raw_entry, raw_exit = raw_exit, raw_entry
    supporting_fact_ids = {
        str(fact_id)
        for cell in run["analysis"]["directed_evidence"]["cells"]
        if cell.get("direction") == direction
        and cell.get("support_state") == "observed"
        for fact_id in cell.get("supporting_fact_ids") or []
    }
    directional_source_ids = {
        int(item["source_observation_id"])
        for item in run["analysis"].get("projections") or []
        if any(
            f":{item['source_segment_id']}:{item['source_geometry_hash']}" in fact_id
            for fact_id in supporting_fact_ids
        )
    }
    occurrence_id = str(component_spec["occurrence_id"])
    heat = component_from_directed_cells(
        component_key=occurrence_id,
        distance_m=distance_m,
        climb_m=climb_m,
        descent_m=descent_m,
        cells=run["analysis"]["directed_evidence"]["cells"],
        direction=direction,
        start_measure_m=float(traversal["start_measure_m"]),
        end_measure_m=float(traversal["end_measure_m"]),
    )
    entry = _module_endpoint(raw_entry, source_by_id)
    exit = _module_endpoint(raw_exit, source_by_id)
    return _AssembledComponent(
        occurrence_id=occurrence_id,
        kind="mountain_block",
        entry=entry,
        exit=exit,
        heat=heat,
        evidence_source_ids=frozenset(directional_source_ids),
        full_source_traversals=frozenset(),
        public_facts={
            "occurrence_id": occurrence_id,
            "kind": "mountain_block",
            "component_geometry_sha256": component_geometry_sha256,
            "component_geometry_normalization_version": (
                CARRIER_GEOMETRY_NORMALIZATION_VERSION
            ),
            "component_extent_m": [
                round(
                    min(
                        float(traversal["start_measure_m"]),
                        float(traversal["end_measure_m"]),
                    ),
                    3,
                ),
                round(
                    max(
                        float(traversal["start_measure_m"]),
                        float(traversal["end_measure_m"]),
                    ),
                    3,
                ),
            ],
            "traversal_orientation": direction,
            "module_key": module_key,
            "block_key": block_key,
            "module_run_sha256": str(run["run_sha256"]),
            "mountain_block_sha256": str(block["block_sha256"]),
            "block_name": block["block_name"],
            "direction": direction,
            "traversal_direction": traversal_direction,
            "physical_geometry_reuse": (
                "stored_geometry"
                if traversal_direction == "stored"
                else "same_geometry_reversed"
            ),
            "distance_km": round(distance_m / 1000, 3),
            "climb_m": round(climb_m, 1),
            "descent_m": round(descent_m, 1),
        },
    )


def _transit_endpoint(
    payload: Mapping[str, Any],
    source_by_id: Mapping[int, dict[str, Any]],
    module_ports: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> _Endpoint:
    point = payload["lonlat"]
    if payload["binding_type"] == "source_observation_candidate":
        source = source_by_id.get(int(payload["source_observation_id"]))
        if source is None or source["source_geometry_hash"] != payload.get(
            "source_geometry_hash"
        ):
            raise RoutePatternAssemblyError(
                "transit_source_port_mismatch", "transit source port binding drift"
            )
        return _Endpoint(
            float(point[0]),
            float(point[1]),
            "source_observation_boundary",
            source_observation_id=int(source["source_observation_id"]),
            source_geometry_hash=str(source["source_geometry_hash"]),
        )
    key = (
        payload.get("module_key"),
        payload.get("port_key"),
        payload.get("module_port_sha256"),
    )
    port = module_ports.get(key)
    if port is None:
        raise RoutePatternAssemblyError(
            "transit_module_port_mismatch", "transit module port binding drift"
        )
    return _Endpoint(
        float(point[0]),
        float(point[1]),
        "canonical_module_port",
        module_key=str(port["module_key"]),
        module_port_sha256=str(port["port_sha256"]),
        module_reference_geometry_hash=str(port["reference_source_geometry_hash"]),
        module_axis_measure_m=float(port["axis_measure_m"]),
    )


def _transit_component(
    component_spec: Mapping[str, Any],
    source_by_id: Mapping[int, dict[str, Any]],
    transit_runs: Mapping[str, Mapping[str, Any]],
    module_ports: Mapping[tuple[str, str, str], Mapping[str, Any]],
    *,
    cohort: str,
) -> _AssembledComponent:
    transit_key = str(component_spec["transit_key"])
    run = transit_runs.get(transit_key)
    if run is None:
        raise RoutePatternAssemblyError(
            "transit_run_missing", "transit path run is unavailable"
        )
    _require_self_hash(run, "result_sha256", "transit_run_hash_mismatch")
    if run["result_sha256"] != component_spec.get("result_sha256"):
        raise RoutePatternAssemblyError(
            "transit_run_binding_mismatch", "candidate references another transit run"
        )
    if run.get("research_verdict") != "connection_candidate":
        raise RoutePatternAssemblyError(
            "transit_not_connection_candidate", "transit path is not admitted"
        )
    relation_input = run.get("relation_input") or {}
    if relation_input.get("selection_snapshot_sha256") != component_spec.get(
        "selection_snapshot_sha256"
    ):
        raise RoutePatternAssemblyError(
            "transit_selection_binding_mismatch",
            "transit evidence references another active road selection",
        )
    traversal_direction = str(component_spec.get("traversal_direction"))
    if traversal_direction not in {"stored", "reverse"}:
        raise RoutePatternAssemblyError(
            "transit_direction_invalid", "transit traversal direction is invalid"
        )
    direction_map = {
        "same_direction": "forward",
        "reverse_direction": "reverse",
    }
    postings: list[EvidencePosting] = []
    selected_heat_direction = (
        "reverse" if traversal_direction == "reverse" else "forward"
    )
    admitted_source_ids: set[int] = set()
    full_source_traversals: set[tuple[int, str]] = set()
    for fact in run.get("evidence_facts") or []:
        source = source_by_id.get(int(fact["source_observation_id"]))
        if source is None:
            raise RoutePatternAssemblyError(
                "transit_evidence_outside_active_selection",
                "transit evidence source is outside the active road selection",
            )
        for field in (
            "source_segment_id",
            "source_geometry_hash",
            "athlete_count",
            "effort_count",
            "star_count",
        ):
            if str(fact.get(field)) != str(source.get(field)):
                raise RoutePatternAssemblyError(
                    "transit_evidence_binding_mismatch",
                    f"transit evidence {field} drift",
                )
        direction = direction_map.get(fact["direction_relation"])
        if fact.get("evidence_status") != "admitted_directional_evidence" or not direction:
            continue
        traversal_evidence_direction = direction
        if traversal_direction == "reverse":
            traversal_evidence_direction = (
                "reverse" if direction == "forward" else "forward"
            )
        if float(fact.get("source_coverage_ratio") or 0) >= 0.95:
            full_source_traversals.add(
                (int(fact["source_observation_id"]), traversal_evidence_direction)
            )
        if direction == selected_heat_direction:
            admitted_source_ids.add(int(fact["source_observation_id"]))
        for interval in fact["transit_intervals_m"]:
            postings.append(
                EvidencePosting(
                    source_fact_id=f"observation:{fact['source_observation_id']}",
                    cohort=cohort,
                    direction=direction,
                    start_measure_m=float(interval[0]),
                    end_measure_m=float(interval[1]),
                    athlete_count=fact.get("athlete_count"),
                    effort_count=fact.get("effort_count"),
                    star_count=fact.get("star_count"),
                    projection_quality=float(fact["source_coverage_ratio"]),
                )
            )
    distance_m = float(run["provider_distance_m"])
    measure_distance_m = float(run.get("derived_geometry_distance_m", distance_m))
    component_geometry_sha256 = _component_geometry_sha256(run["geometry_wgs84"])
    # Projection intervals are measured on the retained provider geometry, not
    # on the provider's rounded summary distance.  TransitPath already gates
    # those two measures to within 3%; keep the geometric measure for atomic
    # evidence and the provider measure for the rider-facing route total.
    arrangement = arrange_directed_evidence(
        transit_key, max(distance_m, measure_distance_m), postings
    )
    climb = float(run["elevation"]["climb_m"])
    descent = float(run["elevation"]["descent_m"])
    heat_direction = selected_heat_direction
    raw_entry, raw_exit = run["from"], run["to"]
    if traversal_direction == "reverse":
        climb, descent = descent, climb
        raw_entry, raw_exit = raw_exit, raw_entry
    occurrence_id = str(component_spec["occurrence_id"])
    heat = component_from_directed_cells(
        component_key=occurrence_id,
        distance_m=distance_m,
        climb_m=climb,
        descent_m=descent,
        cells=arrangement.to_dict()["cells"],
        direction=heat_direction,
    )
    return _AssembledComponent(
        occurrence_id=occurrence_id,
        kind="transit_path",
        entry=_transit_endpoint(raw_entry, source_by_id, module_ports),
        exit=_transit_endpoint(raw_exit, source_by_id, module_ports),
        heat=heat,
        evidence_source_ids=frozenset(admitted_source_ids),
        full_source_traversals=frozenset(full_source_traversals),
        public_facts={
            "occurrence_id": occurrence_id,
            "kind": "transit_path",
            "component_geometry_sha256": component_geometry_sha256,
            "component_geometry_normalization_version": (
                CARRIER_GEOMETRY_NORMALIZATION_VERSION
            ),
            "component_extent_m": [0.0, round(distance_m, 3)],
            "traversal_orientation": heat_direction,
            "transit_key": transit_key,
            "transit_result_sha256": str(run["result_sha256"]),
            "selection_snapshot_sha256": str(
                relation_input["selection_snapshot_sha256"]
            ),
            "traversal_direction": traversal_direction,
            "physical_geometry_reuse": (
                "stored_geometry" if traversal_direction == "stored"
                else "same_geometry_reversed"
            ),
            "distance_km": round(distance_m / 1000, 3),
            "climb_m": round(climb, 1),
            "descent_m": round(descent, 1),
        },
    )


def _endpoint_distance(left: _Endpoint, right: _Endpoint) -> float:
    return haversine(left.latitude, left.longitude, right.latitude, right.longitude)


def _physically_same_boundary(left: _Endpoint, right: _Endpoint) -> bool:
    if _endpoint_distance(left, right) > MAX_COMPONENT_JOIN_DISTANCE_M:
        return False
    if left.binding_type == right.binding_type == "source_observation_boundary":
        return (
            left.source_observation_id == right.source_observation_id
            and left.source_geometry_hash == right.source_geometry_hash
        )
    if left.binding_type == right.binding_type == "canonical_module_port":
        return (
            left.module_key == right.module_key
            and left.module_reference_geometry_hash
            == right.module_reference_geometry_hash
            and abs(
                float(left.module_axis_measure_m or 0)
                - float(right.module_axis_measure_m or 0)
            )
            <= MAX_COMPONENT_JOIN_DISTANCE_M
        )
    return False


def _rank_positions(
    source_by_id: Mapping[int, dict[str, Any]], observation_id: int
) -> dict[str, Any]:
    source = source_by_id[observation_id]
    result: dict[str, Any] = {
        "source_observation_id": observation_id,
        "source_segment_id": str(source["source_segment_id"]),
        "source_name": source["source_name"],
    }
    for field, output in (
        ("athlete_count", "athlete_rank"),
        ("effort_count", "effort_rank"),
        ("star_count", "star_rank"),
    ):
        value = int(source[field])
        result[field] = value
        result[output] = 1 + sum(int(item[field]) > value for item in source_by_id.values())
    result["comparison_population"] = len(source_by_id)
    result["efforts_per_athlete"] = round(
        float(source["effort_count"]) / float(source["athlete_count"]), 3
    )
    return result


def _hard_fact_explanation(
    candidate_spec: Mapping[str, Any],
    heat_vector: Mapping[str, Any],
    anchor_facts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    scope = str(candidate_spec["comparison_scope"])
    climb = float(heat_vector["climb_m"])
    descent = float(heat_vector["descent_m"])
    if climb >= max(1.0, descent * 2):
        resource_shape = "ascent_dominant"
        shape_text = "爬升占主导"
    elif descent >= max(1.0, climb * 2):
        resource_shape = "descent_dominant"
        shape_text = "累计下降占主导"
    else:
        resource_shape = "mixed_vertical_load"
        shape_text = "爬升与下降混合"
    if scope == "destination_core":
        fit = (
            f"适合愿意完成约{heat_vector['distance_km']:.1f}公里山区核心段、"
            f"承担约{heat_vector['climb_m']:.0f}米累计爬升，并接受本卡不含"
            "市区接驳与返程的骑手。"
        )
    else:
        fit = (
            f"适合愿意承担约{heat_vector['distance_km']:.1f}公里山区内部行程、"
            f"约{heat_vector['climb_m']:.0f}米累计爬升和"
            f"约{heat_vector['descent_m']:.0f}米累计下降，并接受整趟"
            f"{shape_text}的骑手。"
        )
    why = []
    for item in anchor_facts:
        why.append(
            f"{item['source_name']}：{item['athlete_count']}名骑手（第"
            f"{item['athlete_rank']}）、{item['effort_count']}次（第"
            f"{item['effort_rank']}）、收藏{item['star_count']}（第"
            f"{item['star_rank']}），人均记录{item['efforts_per_athlete']:.2f}次；"
            f"比较范围为当前{item['comparison_population']}条。"
        )
    why.append(
        "当前骑行方向有热度证据覆盖"
        f"{heat_vector['evidence_coverage'] * 100:.1f}%的物理距离；"
        "其余保持未观测。"
    )
    costs = [
        (
            f"硬工作量为{heat_vector['distance_km']:.3f}公里、"
            f"+{heat_vector['climb_m']:.1f}米/"
            f"-{heat_vector['descent_m']:.1f}米。"
        ),
        str(candidate_spec["outing_boundary"]),
    ]
    if heat_vector["connector_ratio"] >= 0.001:
        costs.insert(
            1,
            f"约{heat_vector['connector_ratio'] * 100:.1f}%的距离"
            "没有当前方向赛段热度，含义是未知，不是冷门。",
        )
    return {
        "version": ROUTE_CHOICE_EXPLANATION_VERSION,
        "suitable_for": fit,
        "why": why,
        "costs": costs,
        "hard_fact_views": {
            "climb_density_m_per_km": round(
                float(heat_vector["climb_m"])
                / float(heat_vector["distance_km"]),
                1,
            ),
            "resource_shape": resource_shape,
            "directional_evidence_coverage": heat_vector["evidence_coverage"],
            "unobserved_distance_ratio": heat_vector["connector_ratio"],
            "scenery_evidence_status": "not_provided",
            "road_surface_evidence_status": "not_provided",
            "traffic_evidence_status": "not_provided",
            "supply_evidence_status": "not_provided",
        },
        "forbidden_inferences": [
            "不由累计爬升推断新手/高手、危险、路面或技术难度",
            "不由赛段热度推断完整路线已被多数骑友这样骑过",
            "不在没有风景、交通、补给事实时编造体验描述",
        ],
    }


def assemble_candidate(
    candidate_spec: Mapping[str, Any],
    *,
    source_by_id: Mapping[int, dict[str, Any]],
    module_runs: Mapping[str, Mapping[str, Any]],
    transit_runs: Mapping[str, Mapping[str, Any]],
    cohort: str,
    source_corridor_cache: dict[
        int, tuple[float, list[dict[str, Any]]]
    ] | None = None,
) -> dict[str, Any]:
    module_ports = _module_port_registry(module_runs)
    assembled: list[_AssembledComponent] = []
    try:
        for component_spec in candidate_spec.get("components") or []:
            kind = component_spec.get("kind")
            if kind == "mountain_block":
                component = _mountain_component(
                    component_spec, source_by_id, module_runs
                )
            elif kind == "transit_path":
                component = _transit_component(
                    component_spec,
                    source_by_id,
                    transit_runs,
                    module_ports,
                    cohort=cohort,
                )
            elif kind == "source_corridor":
                component = _source_corridor_component(
                    component_spec,
                    source_by_id,
                    cohort=cohort,
                    projection_cache=source_corridor_cache,
                )
            else:
                raise RoutePatternAssemblyError(
                    "component_kind_unsupported", f"unsupported component kind {kind}"
                )
            assembled.append(component)
        if not assembled:
            raise RoutePatternAssemblyError(
                "candidate_components_empty", "candidate needs at least one component"
            )
        occurrence_ids = [item.occurrence_id for item in assembled]
        if len(occurrence_ids) != len(set(occurrence_ids)):
            raise RoutePatternAssemblyError(
                "duplicate_occurrence_id", "route occurrence IDs must be unique"
            )
        for previous, current in zip(assembled, assembled[1:]):
            if not _physically_same_boundary(previous.exit, current.entry):
                raise RoutePatternAssemblyError(
                    "component_boundary_mismatch",
                    f"{previous.occurrence_id} does not join {current.occurrence_id}",
                )
            previous_by_source = dict(previous.full_source_traversals)
            current_by_source = dict(current.full_source_traversals)
            if any(
                current_by_source.get(source_id) not in {None, direction}
                for source_id, direction in previous_by_source.items()
            ):
                raise RoutePatternAssemblyError(
                    "immediate_full_source_retrace",
                    f"{previous.occurrence_id} immediately retraces a complete source "
                    f"in {current.occurrence_id}",
                )
        allowed_anchor_ids = set().union(
            *(set(item.evidence_source_ids) for item in assembled)
        )
        requested_anchor_ids = [
            int(observation_id)
            for observation_id in candidate_spec.get("anchor_observation_ids") or []
        ]
        if any(item not in allowed_anchor_ids for item in requested_anchor_ids):
            raise RoutePatternAssemblyError(
                "anchor_not_route_evidence",
                "anchor observation is not bound to this route candidate",
            )
        heat_vector = compose_route_heat(
            str(candidate_spec["candidate_id"]), tuple(item.heat for item in assembled)
        )
        anchors = [
            _rank_positions(source_by_id, observation_id)
            for observation_id in requested_anchor_ids
        ]
        payload = {
            "candidate_id": candidate_spec["candidate_id"],
            "choice_name": candidate_spec["choice_name"],
            "comparison_scope": candidate_spec["comparison_scope"],
            "assembly_status": "hard_feasible_research_candidate",
            "hard_failure_codes": [],
            "ordered_components": [dict(item.public_facts) for item in assembled],
            "heat_vector": heat_vector,
            "anchor_heat_facts": anchors,
        }
        payload["rider_explanation"] = _hard_fact_explanation(
            candidate_spec, heat_vector, anchors
        )
        payload["candidate_sha256"] = canonical_sha256(payload)
        return payload
    except RoutePatternAssemblyError as exc:
        failure_code = exc.code
    except (KeyError, TypeError, ValueError):
        failure_code = "candidate_input_invalid"
    return {
        "candidate_id": candidate_spec.get("candidate_id", "invalid-candidate"),
        "choice_name": candidate_spec.get("choice_name", "无效候选"),
        "comparison_scope": candidate_spec.get("comparison_scope", "unknown"),
        "hard_failure_codes": [failure_code],
        "assembly_status": "hard_rejected",
    }


def _hard_fact_contrasts(candidates: Sequence[Mapping[str, Any]]) -> list[dict]:
    rows: list[dict] = []
    feasible = [item for item in candidates if not item["hard_failure_codes"]]
    for left, right in combinations(feasible, 2):
        if left["comparison_scope"] != right["comparison_scope"]:
            continue
        left_vector = left["heat_vector"]
        right_vector = right["heat_vector"]
        rows.append(
            {
                "comparison_scope": left["comparison_scope"],
                "left_candidate_id": left["candidate_id"],
                "right_candidate_id": right["candidate_id"],
                "left_minus_right": {
                    "distance_km": round(
                        left_vector["distance_km"] - right_vector["distance_km"],
                        3,
                    ),
                    "climb_m": round(
                        left_vector["climb_m"] - right_vector["climb_m"], 1
                    ),
                    "descent_m": round(
                        left_vector["descent_m"] - right_vector["descent_m"], 1
                    ),
                    "directional_evidence_coverage": round(
                        left_vector["evidence_coverage"]
                        - right_vector["evidence_coverage"],
                        6,
                    ),
                },
                "interpretation_boundary": (
                    "hard resource and evidence contrast only; not a universal "
                    "better-route verdict"
                ),
            }
        )
    return rows


def _validate_declared_reverse_pairs(
    candidate_specs: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> None:
    results = {str(item["candidate_id"]): item for item in candidates}
    for spec in candidate_specs:
        forward_id = spec.get("reverse_of_candidate_id")
        if forward_id is None:
            continue
        reverse = results[str(spec["candidate_id"])]
        forward = results.get(str(forward_id))
        if forward is None:
            raise RoutePatternAssemblyError(
                "reverse_candidate_missing", "declared forward candidate is missing"
            )
        if reverse["hard_failure_codes"] or forward["hard_failure_codes"]:
            continue
        forward_components = forward["ordered_components"]
        reverse_components = reverse["ordered_components"]
        if len(forward_components) != len(reverse_components):
            raise RoutePatternAssemblyError(
                "reverse_component_count_mismatch",
                "reverse candidate must traverse the same frozen geometry count",
            )
        for stored, reversed_component in zip(
            forward_components, reversed(reverse_components)
        ):
            if stored.get("component_geometry_sha256") != reversed_component.get(
                "component_geometry_sha256"
            ):
                raise RoutePatternAssemblyError(
                    "reverse_component_geometry_mismatch",
                    "reverse candidate must traverse the same frozen geometries",
                )
            if stored.get("component_extent_m") != reversed_component.get(
                "component_extent_m"
            ):
                raise RoutePatternAssemblyError(
                    "reverse_component_extent_mismatch",
                    "reverse candidate must traverse the same geometry extent",
                )
            stored_orientation = stored.get("traversal_orientation")
            reversed_orientation = reversed_component.get("traversal_orientation")
            if {stored_orientation, reversed_orientation} != {"forward", "reverse"}:
                raise RoutePatternAssemblyError(
                    "reverse_traversal_orientation_mismatch",
                    "reverse candidate must invert traversal orientation",
                )
            if (
                stored.get("distance_km") != reversed_component.get("distance_km")
                or stored.get("climb_m") != reversed_component.get("descent_m")
                or stored.get("descent_m") != reversed_component.get("climb_m")
            ):
                raise RoutePatternAssemblyError(
                    "reverse_resource_mismatch",
                    "reverse candidate must reuse distance and swap climb/descent",
                )


def assemble_choice_set(
    choice_spec: Mapping[str, Any],
    *,
    source_slice: Mapping[str, Any],
    selection_snapshot: Mapping[str, Any],
    module_runs: Mapping[str, Mapping[str, Any]],
    transit_runs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    choice_spec_sha256 = canonical_sha256(choice_spec)
    source_by_id = _source_index(source_slice)
    _validate_selection(selection_snapshot, source_slice, source_by_id)
    if source_slice["slice_sha256"] != choice_spec.get("source_slice_sha256"):
        raise RoutePatternAssemblyError(
            "choice_source_slice_mismatch", "choice set references another source slice"
        )
    if selection_snapshot["snapshot_sha256"] != choice_spec.get(
        "selection_snapshot_sha256"
    ):
        raise RoutePatternAssemblyError(
            "choice_selection_mismatch",
            "choice set references another active-road selection",
        )
    candidate_ids = [
        str(item.get("candidate_id")) for item in choice_spec["candidates"]
    ]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise RoutePatternAssemblyError(
            "duplicate_candidate_id", "route choice candidate IDs must be unique"
        )
    cohort = str(choice_spec["heat_snapshot_cohort"])
    source_corridor_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
    candidates = [
        assemble_candidate(
            item,
            source_by_id=source_by_id,
            module_runs=module_runs,
            transit_runs=transit_runs,
            cohort=cohort,
            source_corridor_cache=source_corridor_cache,
        )
        for item in choice_spec["candidates"]
    ]
    _validate_declared_reverse_pairs(choice_spec["candidates"], candidates)
    payload = {
        "schema_version": "route_pattern_choice_set_v1",
        "algorithm_version": ROUTE_PATTERN_ASSEMBLY_VERSION,
        "choice_set_key": choice_spec["choice_set_key"],
        "choice_spec_sha256": choice_spec_sha256,
        "source_slice_sha256": source_slice["slice_sha256"],
        "selection_snapshot_sha256": selection_snapshot["snapshot_sha256"],
        "comparison_rule": (
            "choices with different rider jobs or directions are compared by hard facts "
            "side by side; no global popularity ranking is forced"
        ),
        "reverse_traversal_rule": (
            "one frozen physical road geometry; reverse traversal reuses it in reverse, "
            "swaps climb/descent, and reads reverse-direction evidence"
        ),
        "candidates": candidates,
        "hard_fact_contrasts": _hard_fact_contrasts(candidates),
        "ranking_status": "not_ranked_across_distinct_rider_jobs",
        "database_write_count": 0,
        "network_request_count": 0,
    }
    payload["result_sha256"] = canonical_sha256(payload)
    return payload
