#!/usr/bin/env python3
"""从私有 Strava/GLO 快照重放公开安全的西山 3D ClimbPro 目录。

私有输入含完整经纬度；公开结果只保留身份、哈希、距离-海拔曲线与爬坡组成。
本脚本不访问网络、不查询数据库，也不重算 GLO。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.elevation.climb_profile_contract import (  # noqa: E402
    ClimbProfileContract,
    build_climb_plan_from_contract,
)
from app.parsing.geo_math import haversine  # noqa: E402


RESULT_SCHEMA_VERSION = "xishan_climb_catalog_result_v1"
MAX_COMPONENT_ENDPOINT_GAP_M = 50.0


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _self_hash(value: dict, field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return _canonical_sha256(payload)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _load_source_slices(root: Path) -> tuple[dict[str, dict], dict[int, dict]]:
    modules: dict[str, dict] = {}
    observations: dict[int, dict] = {}
    for path in sorted(root.glob("*/source-slice.json")):
        payload = _load_json(path)
        expected = payload.get("slice_sha256")
        if expected != _self_hash(payload, "slice_sha256"):
            raise ValueError(f"source slice hash drift: {path}")
        module_key = str(payload.get("module_key") or "")
        if not module_key or module_key in modules:
            raise ValueError(f"duplicate or missing module key: {path}")
        modules[module_key] = payload
        for row in payload.get("observations") or []:
            observation_id = int(row["source_observation_id"])
            previous = observations.get(observation_id)
            if previous is not None and _canonical_sha256(previous) != _canonical_sha256(row):
                raise ValueError(
                    f"observation {observation_id} differs across private source slices"
                )
            observations[observation_id] = row
    return modules, observations


def _load_transit_runs(roots: Sequence[Path]) -> dict[str, dict]:
    runs: dict[str, dict] = {}
    for root in roots:
        for path in sorted(root.glob("*.run.json")):
            payload = _load_json(path)
            expected = payload.get("result_sha256")
            if expected != _self_hash(payload, "result_sha256"):
                raise ValueError(f"transit result hash drift: {path}")
            key = str(payload.get("transit_key") or "")
            if not key:
                raise ValueError(f"transit key missing: {path}")
            previous = runs.get(key)
            if previous is not None and previous["result_sha256"] != expected:
                raise ValueError(f"duplicate transit key with different result: {key}")
            runs[key] = payload
    return runs


def _profile_row(row: dict) -> tuple[list[list[float]], list[float]]:
    points = row.get("source_geometry_lonlat") or []
    snapshot = row.get("elevation_snapshot") or []
    if len(points) < 2 or len(points) != len(snapshot):
        raise ValueError(
            f"observation {row.get('source_observation_id')} geometry/profile coverage mismatch"
        )
    elevations: list[float] = []
    for point, sample in zip(points, snapshot):
        if len(sample) < 3 or any(
            abs(float(left) - float(right)) > 1e-6
            for left, right in zip(point[:2], sample[:2])
        ):
            raise ValueError(
                f"observation {row.get('source_observation_id')} snapshot geometry drift"
            )
        elevations.append(float(sample[2]))
    return [[float(point[0]), float(point[1])] for point in points], elevations


def _directional_values(
    points: Sequence[Sequence[float]],
    elevations: Sequence[float],
    direction: str,
) -> tuple[list[list[float]], list[float]]:
    if direction not in {"forward", "reverse"}:
        raise ValueError(f"unsupported traversal direction: {direction}")
    directed_points = [[float(point[0]), float(point[1])] for point in points]
    directed_elevations = [float(value) for value in elevations]
    if direction == "reverse":
        directed_points.reverse()
        directed_elevations.reverse()
    return directed_points, directed_elevations


def _public_plan(result, *, authoritative_climb_m: float, authoritative_descent_m: float) -> dict:
    payload = {
        "route_distance_m": result.climb_plan["route_distance_m"],
        "stored_glo_meaningful_ascent_m": round(float(authoritative_climb_m), 1),
        "stored_glo_meaningful_descent_m": round(float(authoritative_descent_m), 1),
        "snapshot_replay_meaningful_ascent_m": result.climb,
        "snapshot_replay_meaningful_descent_m": result.descent,
        "elevation_profile": result.profile,
        "climb_plan": result.climb_plan,
    }
    payload["direction_result_sha256"] = _canonical_sha256(payload)
    return payload


def _axis_anchor_contract(axis: dict, semantics: dict) -> tuple[str, str, tuple[str, ...]]:
    if axis["extent_status"] != "full_verified":
        return semantics["forward"], semantics["reverse"], ()
    base_anchor = axis.get("base_anchor")
    summit_anchor = axis.get("summit_anchor")
    refs = tuple(axis.get("anchor_evidence_refs") or ())
    if (
        not isinstance(base_anchor, str)
        or not isinstance(summit_anchor, str)
        or base_anchor == summit_anchor
        or "_" not in base_anchor
        or "_" not in summit_anchor
        or not refs
    ):
        raise ValueError("full_verified axis needs explicit distinct canonical anchors")
    for ref in refs:
        path_text, separator, fragment = ref.partition("#")
        path = _resolve_repo_path(path_text)
        if not separator or not fragment or not path.is_file():
            raise ValueError(f"canonical anchor evidence ref is invalid: {ref}")
        normalized_fragment = "".join(fragment.split())
        normalized_source = "".join(path.read_text(encoding="utf-8").split())
        if normalized_fragment not in normalized_source:
            raise ValueError(f"canonical anchor evidence fragment is missing: {ref}")
    return base_anchor, summit_anchor, refs


def _axis_result(axis: dict, modules: dict[str, dict], observations: dict[int, dict]) -> dict:
    spec_path = _resolve_repo_path(axis["module_spec"])
    spec = _load_json(spec_path)
    module_key = spec["module_key"]
    source_slice = modules.get(module_key)
    if source_slice is None:
        raise ValueError(f"private source slice missing for {module_key}")
    if spec["source_selection"]["observation_ids"] != source_slice["observation_ids"]:
        raise ValueError(f"exact observation set drift for {module_key}")
    observation_id = int(spec["axis_profile_observation_id"])
    row = observations[observation_id]
    reference = spec["reference_axis"]
    if int(reference["source_observation_id"]) != observation_id:
        raise ValueError(f"axis profile observation drift for {module_key}")
    if reference["source_geometry_hash"] != row["source_geometry_hash"]:
        raise ValueError(f"axis source geometry hash drift for {module_key}")
    points, elevations = _profile_row(row)
    directions: dict[str, dict] = {}
    semantics = reference["direction_semantics"]
    base_anchor, summit_anchor, anchor_evidence_refs = _axis_anchor_contract(
        axis, semantics
    )
    for direction in ("forward", "reverse"):
        directed_points, directed_elevations = _directional_values(
            points, elevations, direction
        )
        start_semantic = base_anchor if direction == "forward" else summit_anchor
        end_semantic = summit_anchor if direction == "forward" else base_anchor
        contract = ClimbProfileContract(
            scope_key=module_key,
            scope_kind=axis["scope_kind"],
            extent_status=axis["extent_status"],
            traversal_direction=direction,
            geometry_source="strava_full_segment_projection",
            start_anchor=start_semantic,
            end_anchor=end_semantic,
            source_observation_ids=(observation_id,),
            source_geometry_hashes=(row["source_geometry_hash"],),
            anchor_evidence_refs=anchor_evidence_refs,
        )
        result = build_climb_plan_from_contract(
            directed_points,
            directed_elevations,
            contract=contract,
            source_method="glo30_meaningful_ascent_v1_snapshot_replay_v1",
        )
        stored_climb = float(row["climb_m"])
        stored_descent = float(row["descent_m"])
        if direction == "reverse":
            stored_climb, stored_descent = stored_descent, stored_climb
        directions[direction] = _public_plan(
            result,
            authoritative_climb_m=stored_climb,
            authoritative_descent_m=stored_descent,
        )
    payload = {
        "module_key": module_key,
        "module_name": spec["module_name"],
        "scope_kind": axis["scope_kind"],
        "extent_status": axis["extent_status"],
        "module_spec_path": str(Path(axis["module_spec"])),
        "module_spec_sha256": _canonical_sha256(spec),
        "source_slice_sha256": source_slice["slice_sha256"],
        "source_observation_id": observation_id,
        "source_segment_id": row["source_segment_id"],
        "source_geometry_hash": row["source_geometry_hash"],
        "geometry_point_count": len(points),
        "directions": directions,
        "publication_boundary": spec["boundary"],
    }
    payload["axis_result_sha256"] = _canonical_sha256(payload)
    return payload


def _cumulative_distances(points: Sequence[Sequence[float]]) -> list[float]:
    values = [0.0]
    for left, right in zip(points, points[1:]):
        values.append(
            values[-1]
            + haversine(float(left[1]), float(left[0]), float(right[1]), float(right[0]))
        )
    return values


def _point_at_distance(
    points: Sequence[Sequence[float]], distances: Sequence[float], target: float
) -> list[float]:
    if target <= 0:
        return [float(points[0][0]), float(points[0][1])]
    if target >= distances[-1]:
        return [float(points[-1][0]), float(points[-1][1])]
    for index in range(1, len(distances)):
        if distances[index] < target:
            continue
        span = distances[index] - distances[index - 1]
        ratio = 0.0 if span <= 0 else (target - distances[index - 1]) / span
        return [
            float(points[index - 1][0])
            + (float(points[index][0]) - float(points[index - 1][0])) * ratio,
            float(points[index - 1][1])
            + (float(points[index][1]) - float(points[index - 1][1])) * ratio,
        ]
    raise AssertionError("distance interpolation fell through")


def _value_at_distance(
    values: Sequence[float], distances: Sequence[float], target: float
) -> float:
    if target <= 0:
        return float(values[0])
    if target >= distances[-1]:
        return float(values[-1])
    for index in range(1, len(distances)):
        if distances[index] < target:
            continue
        span = distances[index] - distances[index - 1]
        ratio = 0.0 if span <= 0 else (target - distances[index - 1]) / span
        return float(values[index - 1]) + (
            float(values[index]) - float(values[index - 1])
        ) * ratio
    raise AssertionError("value interpolation fell through")


def _slice_profile(
    points: Sequence[Sequence[float]],
    elevations: Sequence[float],
    *,
    start_offset_m: float,
    end_offset_m: float,
) -> tuple[list[list[float]], list[float]]:
    distances = _cumulative_distances(points)
    if start_offset_m < 0 or end_offset_m <= start_offset_m:
        raise ValueError("partial profile offsets are invalid")
    if end_offset_m > distances[-1] + 1.0:
        raise ValueError("partial profile exceeds parent axis")
    end_offset_m = min(end_offset_m, distances[-1])
    sliced_points = [_point_at_distance(points, distances, start_offset_m)]
    sliced_elevations = [_value_at_distance(elevations, distances, start_offset_m)]
    for point, elevation, distance in zip(points, elevations, distances):
        if start_offset_m < distance < end_offset_m:
            sliced_points.append([float(point[0]), float(point[1])])
            sliced_elevations.append(float(elevation))
    sliced_points.append(_point_at_distance(points, distances, end_offset_m))
    sliced_elevations.append(_value_at_distance(elevations, distances, end_offset_m))
    return sliced_points, sliced_elevations


def _partial_result(
    partial: dict,
    *,
    axis_specs: dict[str, dict],
    observations: dict[int, dict],
    projection_index: dict[tuple[str, int], dict],
) -> dict:
    parent_key = partial["parent_module_key"]
    parent_spec = axis_specs.get(parent_key)
    if parent_spec is None:
        raise ValueError(f"partial parent axis missing: {parent_key}")
    parent_observation_id = int(parent_spec["axis_profile_observation_id"])
    evidence_observation_id = int(partial["evidence_observation_id"])
    if evidence_observation_id not in parent_spec["source_selection"]["observation_ids"]:
        raise ValueError("partial evidence observation is outside parent exact set")
    parent_row = observations[parent_observation_id]
    evidence_row = observations[evidence_observation_id]
    projection_row = projection_index.get((parent_key, evidence_observation_id))
    if projection_row is None:
        raise ValueError("partial directed projection evidence is missing")
    projection = projection_row["projection"]
    matched_runs = projection.get("matched_runs") or []
    interval_starts = [float(run["carrier_interval_m"][0]) for run in matched_runs]
    interval_ends = [float(run["carrier_interval_m"][1]) for run in matched_runs]
    if (
        projection_row["reference_observation_id"] != parent_observation_id
        or evidence_row["source_geometry_hash"] != partial["evidence_source_geometry_hash"]
        or projection_row["source_geometry_hash"] != partial["evidence_source_geometry_hash"]
        or projection.get("result_sha256") != partial["projection_result_sha256"]
        or projection.get("direction") != partial["traversal_direction"]
        or abs(float(projection.get("source_coverage_ratio")) - float(partial["source_coverage_ratio"])) > 1e-6
        or projection.get("status") != "research_projected"
        or projection.get("completion_status") != "complete"
        or not matched_runs
        or abs(min(interval_starts) - float(partial["start_offset_m"])) > 0.01
        or abs(max(interval_ends) - float(partial["end_offset_m"])) > 0.01
    ):
        raise ValueError("partial directed projection evidence drift")
    points, elevations = _profile_row(parent_row)
    points, elevations = _slice_profile(
        points,
        elevations,
        start_offset_m=float(partial["start_offset_m"]),
        end_offset_m=float(partial["end_offset_m"]),
    )
    direction = partial["traversal_direction"]
    points, elevations = _directional_values(points, elevations, direction)
    contract = ClimbProfileContract(
        scope_key=partial["partial_key"],
        scope_kind="named_climb",
        extent_status="partial",
        traversal_direction=direction,
        geometry_source="parent_named_climb_axis_subrange",
        start_anchor=f"{parent_key}:offset:{partial['start_offset_m']}",
        end_anchor=f"{parent_key}:offset:{partial['end_offset_m']}",
        source_observation_ids=(parent_observation_id, evidence_observation_id),
        source_geometry_hashes=(
            parent_row["source_geometry_hash"],
            evidence_row["source_geometry_hash"],
        ),
        parent_scope_key=parent_key,
        start_offset_m=float(partial["start_offset_m"]),
        end_offset_m=float(partial["end_offset_m"]),
    )
    result = build_climb_plan_from_contract(
        points,
        elevations,
        contract=contract,
        source_method="glo30_parent_axis_snapshot_subrange_v1",
    )
    payload = {
        "partial_key": partial["partial_key"],
        "name": partial["name"],
        "parent_module_key": parent_key,
        "parent_source_observation_id": parent_observation_id,
        "evidence_observation_id": evidence_observation_id,
        "evidence_source_segment_id": evidence_row["source_segment_id"],
        "evidence_source_geometry_hash": evidence_row["source_geometry_hash"],
        "projection_result_sha256": projection["result_sha256"],
        "source_coverage_ratio": float(projection["source_coverage_ratio"]),
        "traversal_direction": direction,
        "start_offset_m": float(partial["start_offset_m"]),
        "end_offset_m": float(partial["end_offset_m"]),
        "profile_replay": _public_plan(
            result,
            authoritative_climb_m=result.climb,
            authoritative_descent_m=result.descent,
        ),
    }
    payload["partial_result_sha256"] = _canonical_sha256(payload)
    return payload


def _transit_profile(run: dict, direction: str) -> tuple[list[list[float]], list[float]]:
    geometry = run.get("geometry_wgs84") or []
    profile = (run.get("elevation") or {}).get("profile") or []
    if len(geometry) < 2 or len(profile) < 2:
        raise ValueError(f"transit {run.get('transit_key')} lacks complete geometry/profile")
    geometry_distances = _cumulative_distances(geometry)
    profile_distances = [float(item[0]) * 1000.0 for item in profile]
    if profile_distances[-1] <= 0:
        raise ValueError(f"transit {run.get('transit_key')} profile distance is empty")
    scale = geometry_distances[-1] / profile_distances[-1]
    points = [
        _point_at_distance(geometry, geometry_distances, distance * scale)
        for distance in profile_distances
    ]
    elevations = [float(item[1]) for item in profile]
    return _directional_values(points, elevations, direction)


def _component_profile(
    component: dict,
    *,
    observations: dict[int, dict],
    module_specs: dict[str, dict],
    transits: dict[str, dict],
) -> tuple[list[list[float]], list[float], dict]:
    kind = component["kind"]
    if kind == "source_corridor":
        observation_id = int(component["source_observation_id"])
        row = observations.get(observation_id)
        if row is None:
            raise ValueError(f"source observation {observation_id} is unavailable")
        if component["source_geometry_hash"] != row["source_geometry_hash"]:
            raise ValueError(f"source geometry hash drift for observation {observation_id}")
        points, elevations = _profile_row(row)
        direction = component["direction"]
        points, elevations = _directional_values(points, elevations, direction)
        return points, elevations, {
            "kind": kind,
            "occurrence_id": component["occurrence_id"],
            "source_observation_id": observation_id,
            "source_geometry_hash": row["source_geometry_hash"],
            "traversal_direction": direction,
        }
    if kind == "mountain_block":
        module_key = component["module_key"]
        spec = module_specs[module_key]
        block_suffix = component["block_key"].split(":", 1)[-1]
        block = next(
            item for item in spec["route_blocks"] if item["block_key_suffix"] == block_suffix
        )
        observation_id = int(block["traversals"][0]["resource_observation_id"])
        if component.get("traversal_direction") == "reverse":
            observation_id = int(spec["axis_profile_observation_id"])
            direction = "reverse"
        else:
            direction = block["traversals"][0]["direction"]
        row = observations[observation_id]
        points, elevations = _profile_row(row)
        points, elevations = _directional_values(points, elevations, direction)
        return points, elevations, {
            "kind": kind,
            "occurrence_id": component["occurrence_id"],
            "module_key": module_key,
            "source_observation_id": observation_id,
            "source_geometry_hash": row["source_geometry_hash"],
            "traversal_direction": direction,
        }
    if kind == "transit_path":
        key = component["transit_key"]
        run = transits.get(key)
        if run is None:
            raise ValueError(f"private transit run missing for {key}")
        if component["result_sha256"] != run["result_sha256"]:
            raise ValueError(f"transit result hash drift for {key}")
        direction = (
            "reverse" if component.get("traversal_direction") == "reverse" else "forward"
        )
        points, elevations = _transit_profile(run, direction)
        return points, elevations, {
            "kind": kind,
            "occurrence_id": component["occurrence_id"],
            "transit_key": key,
            "transit_result_sha256": run["result_sha256"],
            "traversal_direction": direction,
        }
    raise ValueError(f"unsupported route component kind: {kind}")


def _join_profiles(
    components: Iterable[tuple[list[list[float]], list[float], dict]]
) -> tuple[list[list[float]], list[float], list[dict]]:
    route_points: list[list[float]] = []
    route_elevations: list[float] = []
    public_components: list[dict] = []
    for points, elevations, public in components:
        if route_points:
            gap = haversine(
                route_points[-1][1],
                route_points[-1][0],
                points[0][1],
                points[0][0],
            )
            public["endpoint_gap_from_previous_m"] = round(gap, 1)
            if gap > MAX_COMPONENT_ENDPOINT_GAP_M:
                raise ValueError(
                    f"component {public['occurrence_id']} endpoint gap {gap:.1f}m exceeds gate"
                )
            if gap <= 0.1:
                points = points[1:]
                elevations = elevations[1:]
        else:
            public["endpoint_gap_from_previous_m"] = None
        route_points.extend(points)
        route_elevations.extend(elevations)
        public_components.append(public)
    if len(route_points) < 2 or len(route_points) != len(route_elevations):
        raise ValueError("assembled route profile is incomplete")
    return route_points, route_elevations, public_components


def _long_route_result(
    candidate: dict,
    result_row: dict,
    *,
    observations: dict[int, dict],
    module_specs: dict[str, dict],
    transits: dict[str, dict],
) -> dict:
    failure_codes = list(result_row.get("hard_failure_codes") or [])
    if result_row.get("assembly_status") != "hard_feasible_research_candidate":
        return {
            "candidate_id": candidate["candidate_id"],
            "choice_name": candidate["choice_name"],
            "status": "hard_rejected",
            "hard_failure_codes": failure_codes,
        }
    assembled = [
        _component_profile(
            component,
            observations=observations,
            module_specs=module_specs,
            transits=transits,
        )
        for component in candidate["components"]
    ]
    points, elevations, public_components = _join_profiles(assembled)
    source_observation_ids = tuple(
        dict.fromkeys(
            int(component["source_observation_id"])
            for component in public_components
            if component.get("source_observation_id") is not None
        )
    )
    source_hashes = tuple(
        dict.fromkeys(
            str(component["source_geometry_hash"])
            for component in public_components
            if component.get("source_geometry_hash")
        )
    )
    contract = ClimbProfileContract(
        scope_key=candidate["candidate_id"],
        scope_kind="route_composition",
        extent_status="complete_route_composition",
        traversal_direction="geometry_order",
        geometry_source="frozen_source_and_transit_component_composition",
        start_anchor=f"route_start:{public_components[0]['occurrence_id']}",
        end_anchor=f"route_end:{public_components[-1]['occurrence_id']}",
        source_observation_ids=source_observation_ids,
        source_geometry_hashes=source_hashes,
    )
    elevation_result = build_climb_plan_from_contract(
        points,
        elevations,
        contract=contract,
        source_method="frozen_component_profile_composition_v1",
    )
    heat_vector = result_row.get("heat_vector") or {}
    public = {
        "candidate_id": candidate["candidate_id"],
        "choice_name": candidate["choice_name"],
        "comparison_scope": candidate["comparison_scope"],
        "outing_boundary": candidate["outing_boundary"],
        "status": "hard_feasible_research_candidate",
        "hard_failure_codes": [],
        "ordered_components": public_components,
        "choice_fact_totals": {
            "distance_m": round(float(heat_vector.get("distance_km") or 0) * 1000.0, 1),
            "climb_m": round(float(heat_vector.get("climb_m") or 0), 1),
            "descent_m": round(float(heat_vector.get("descent_m") or 0), 1),
        },
        "profile_replay": _public_plan(
            elevation_result,
            authoritative_climb_m=float(heat_vector.get("climb_m") or 0),
            authoritative_descent_m=float(heat_vector.get("descent_m") or 0),
        ),
    }
    public["route_result_sha256"] = _canonical_sha256(public)
    return public


def build_catalog_result(
    catalog: dict,
    *,
    module_evidence_dir: Path,
    transit_evidence_dirs: Sequence[Path],
) -> dict:
    if catalog.get("schema_version") != "xishan_climb_catalog_spec_v1":
        raise ValueError("unsupported climb catalog spec")
    modules, observations = _load_source_slices(module_evidence_dir)
    transits = _load_transit_runs(transit_evidence_dirs)
    partial_projection_artifact = _load_json(
        _resolve_repo_path(catalog["partial_projection_artifact"])
    )
    if (
        partial_projection_artifact.get("run_sha256")
        != catalog["partial_projection_artifact_sha256"]
        or partial_projection_artifact.get("run_sha256")
        != _self_hash(partial_projection_artifact, "run_sha256")
    ):
        raise ValueError("partial projection artifact hash drift")
    partial_projection_index = {
        (family["family_key"], int(row["source_observation_id"])): {
            **row,
            "reference_observation_id": int(family["reference_observation_id"]),
        }
        for family in partial_projection_artifact["families"]
        for row in family["projections"]
    }
    axes = [_axis_result(axis, modules, observations) for axis in catalog["axes"]]
    module_specs = {
        axis["module_key"]: _load_json(_resolve_repo_path(axis["module_spec_path"]))
        for axis in axes
    }
    partials = [
        _partial_result(
            partial,
            axis_specs=module_specs,
            observations=observations,
            projection_index=partial_projection_index,
        )
        for partial in catalog.get("partial_climbs", [])
    ]
    long_routes: list[dict] = []
    selected_ids: set[str] = set()
    for group in catalog["long_route_choices"]:
        choice_spec = _load_json(_resolve_repo_path(group["choice_spec"]))
        choice_result = _load_json(_resolve_repo_path(group["choice_result"]))
        if choice_result.get("result_sha256") != _self_hash(choice_result, "result_sha256"):
            raise ValueError(f"choice result hash drift: {group['choice_result']}")
        candidates = {row["candidate_id"]: row for row in choice_spec["candidates"]}
        results = {row["candidate_id"]: row for row in choice_result["candidates"]}
        for candidate_id in group["candidate_ids"]:
            if candidate_id in selected_ids:
                raise ValueError(f"duplicate long route selection: {candidate_id}")
            selected_ids.add(candidate_id)
            long_routes.append(
                _long_route_result(
                    candidates[candidate_id],
                    results[candidate_id],
                    observations=observations,
                    module_specs=module_specs,
                    transits=transits,
                )
            )
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "catalog_key": catalog["catalog_key"],
        "catalog_spec_sha256": _canonical_sha256(catalog),
        "algorithm_version": "velo_climb_plan_v1",
        "source_profile_method": catalog["profile_source_method"],
        "network_request_count": 0,
        "database_write_count": 0,
        "glo_recomputation_count": 0,
        "privacy_boundary": catalog["privacy_boundary"],
        "identity_rule": catalog["identity_rule"],
        "axis_count": len(axes),
        "directional_axis_result_count": len(axes) * 2,
        "partial_climb_count": len(partials),
        "long_route_count": len(long_routes),
        "long_route_hard_feasible_count": sum(
            row["status"] == "hard_feasible_research_candidate" for row in long_routes
        ),
        "long_route_hard_rejected_count": sum(
            row["status"] == "hard_rejected" for row in long_routes
        ),
        "axes": axes,
        "partial_climbs": partials,
        "long_routes": long_routes,
        "route_guide_bindings": catalog["route_guide_bindings"],
        "publication_exclusions": catalog["publication_exclusions"],
        "legacy_geometry_retirement": catalog["legacy_geometry_retirement"],
    }
    result["result_sha256"] = _canonical_sha256(result)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-spec",
        default="data/research/xishan_climb_catalog_v1.json",
    )
    parser.add_argument("--module-evidence-dir", required=True)
    parser.add_argument(
        "--transit-evidence-dir",
        action="append",
        required=True,
        help="repeat for each frozen transit run directory",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    catalog_path = _resolve_repo_path(args.catalog_spec)
    result = build_catalog_result(
        _load_json(catalog_path),
        module_evidence_dir=Path(args.module_evidence_dir),
        transit_evidence_dirs=[Path(value) for value in args.transit_evidence_dir],
    )
    output = _resolve_repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {output}: axes={result['axis_count']} "
        f"directional={result['directional_axis_result_count']} "
        f"long_feasible={result['long_route_hard_feasible_count']} "
        f"long_rejected={result['long_route_hard_rejected_count']}"
    )


if __name__ == "__main__":
    main()
