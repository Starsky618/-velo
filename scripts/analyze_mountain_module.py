#!/usr/bin/env python3
"""离线重放通用山区积木，输出方向、组合资源和热度证据范围。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.route_cognition.carrier_projection import DirectedTraversal
from app.common.geometry_hash import strava_source_geometry_hash
from app.route_cognition.mountain_modules import (
    MOUNTAIN_MODULE_ALGORITHM_VERSION,
    MOUNTAIN_MODULE_CONFIG_SHA256,
    MOUNTAIN_MODULE_CONFIG_VERSION,
    MIN_RESOURCE_ALIGNMENT_RATIO,
    MountainModuleSpec,
    MountainObservation,
    analyze_mountain_module,
    heat_evidence_explanation,
    summarize_route_block,
)


RUN_SCHEMA_VERSION = "mountain_module_run_v2"


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


def _set_sha256(values: list[int]) -> str:
    return hashlib.sha256(
        "\n".join(sorted(str(value) for value in values)).encode("utf-8")
    ).hexdigest()


def _load_inputs(spec_path: Path, snapshot_path: Path) -> tuple[dict, dict]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != "mountain_module_spec_v2":
        raise ValueError("unsupported mountain module spec schema")
    if spec.get("module_role") != "destination_block":
        raise ValueError("mountain module must declare destination_block role")
    if spec.get("source_selection", {}).get("mode") != "exact_observation_ids":
        raise ValueError("mountain module requires exact observation selection")
    direction_semantics = spec.get("reference_axis", {}).get(
        "direction_semantics"
    )
    if not isinstance(direction_semantics, dict) or set(direction_semantics) != {
        "forward",
        "reverse",
    }:
        raise ValueError("reference axis needs forward/reverse direction semantics")
    if not all(
        isinstance(value, str) and value.strip()
        for value in direction_semantics.values()
    ):
        raise ValueError("reference axis direction semantics must be named")
    expected_hash = snapshot.pop("slice_sha256", None)
    if expected_hash != _canonical_sha256(snapshot):
        raise ValueError("source slice hash 漂移")
    snapshot["slice_sha256"] = expected_hash
    if spec["module_key"] != snapshot["module_key"]:
        raise ValueError("spec 与 source slice module identity 不一致")
    if spec["census_batch_id"] != snapshot["census_batch_id"]:
        raise ValueError("spec 与 source slice census batch 不一致")
    if (
        spec["elevation_fact_batch_id"]
        != snapshot["elevation_fact_batch_id"]
    ):
        raise ValueError("spec 与 source slice GLO fact batch 不一致")
    if (
        spec["source_selection"]["observation_ids"]
        != snapshot["observation_ids"]
    ):
        raise ValueError("spec 与 source slice observation exact set 不一致")
    if spec["source_selection"]["observation_set_sha256"] != _set_sha256(
        snapshot["observation_ids"]
    ):
        raise ValueError("source slice observation set hash 漂移")
    if spec["heat_snapshot_cohort"] != snapshot["heat_snapshot_cohort"]:
        raise ValueError("spec 与 source slice heat cohort 不一致")
    if spec["excluded_source_segment_ids"] != snapshot[
        "excluded_source_segment_ids"
    ]:
        raise ValueError("spec 与 source slice exclusion set 不一致")
    observation_ids = set(snapshot["observation_ids"])
    holdout_ids = spec.get("holdout_observation_ids", [])
    if len(holdout_ids) != len(set(holdout_ids)) or observation_ids & set(
        holdout_ids
    ):
        raise ValueError("holdout observations must be unique and outside exact set")
    role_ids = [
        item["observation_id"] for item in spec.get("role_requirements", [])
    ]
    if len(role_ids) != len(set(role_ids)) or not set(role_ids) <= observation_ids:
        raise ValueError("role requirements must be unique members of exact set")
    if spec.get("axis_profile_observation_id") not in observation_ids:
        raise ValueError("axis profile observation must belong to exact set")
    resource_ids = [
        traversal["resource_observation_id"]
        for block in spec["route_blocks"]
        for traversal in block["traversals"]
    ]
    if not resource_ids or not set(resource_ids) <= observation_ids:
        raise ValueError("route block resources must belong to exact set")
    for block in spec["route_blocks"]:
        if block.get("block_role") != "destination_traversal":
            raise ValueError("route block must declare destination_traversal role")
        if block.get("recommendation_status") != "evidence_candidate":
            raise ValueError("destination traversal cannot embed route blockers")
        if block.get("blockers"):
            raise ValueError("destination traversal cannot embed route blockers")
        block_resources = [
            item["resource_observation_id"] for item in block["traversals"]
        ]
        if len(block_resources) != 1:
            raise ValueError(
                "destination traversal v2 requires exactly one traversal"
            )
        if len(block_resources) != len(set(block_resources)):
            raise ValueError("route block cannot count one source fact twice")
    block_suffixes = [item["block_key_suffix"] for item in spec["route_blocks"]]
    if len(block_suffixes) != len(set(block_suffixes)):
        raise ValueError("route block suffixes must be unique")
    if spec.get("connections"):
        raise ValueError(
            "single destination module cannot embed route connections; "
            "assemble full transit-road traversals later"
        )
    return spec, snapshot


def _projection_by_observation(analysis: dict[str, Any]) -> dict[int, dict]:
    return {
        item["source_observation_id"]: item["result"]
        for item in analysis["projections"]
    }


def _interval_union_length(intervals: list[list[float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def _validate_role_requirements(
    spec_data: dict[str, Any], analysis: dict[str, Any]
) -> None:
    projections = _projection_by_observation(analysis)
    axis_length = analysis["reference_axis_length_m"]
    for role in spec_data.get("role_requirements", []):
        result = projections[role["observation_id"]]
        runs = result["matched_runs"]
        axis_coverage = (
            _interval_union_length(
                [item["carrier_interval_m"] for item in runs]
            )
            / axis_length
        )
        if result["direction"] != role["expected_direction"]:
            raise ValueError(f"role {role['role_key']} direction mismatch")
        if result["source_coverage_ratio"] < role["min_source_coverage_ratio"]:
            raise ValueError(f"role {role['role_key']} source coverage insufficient")
        if axis_coverage < role["min_axis_coverage_ratio"]:
            raise ValueError(f"role {role['role_key']} axis coverage insufficient")


def _measure(value: str | float, axis_length: float) -> float:
    if value == "axis_start":
        return 0.0
    if value == "axis_end":
        return axis_length
    number = float(value)
    if number < 0 or number > axis_length:
        raise ValueError("traversal measure outside reference axis")
    return number


def _traversal_coverage_ratio(
    projection: dict[str, Any], start: float, end: float
) -> tuple[float, float]:
    low, high = sorted((start, end))
    if high <= low:
        raise ValueError("route traversal must have positive length")
    clipped = []
    for item in projection["matched_runs"]:
        run_start, run_end = item["carrier_interval_m"]
        clipped_start = max(low, run_start)
        clipped_end = min(high, run_end)
        if clipped_end > clipped_start:
            clipped.append([clipped_start, clipped_end])
    intersection_length = _interval_union_length(clipped)
    resource_length = _interval_union_length(
        [item["carrier_interval_m"] for item in projection["matched_runs"]]
    )
    return (
        intersection_length / (high - low),
        intersection_length / resource_length if resource_length else 0.0,
    )


def _observations(snapshot: dict) -> tuple[MountainObservation, ...]:
    observations = tuple(
        MountainObservation(
            source_observation_id=item["source_observation_id"],
            source_segment_id=item["source_segment_id"],
            source_name=item["source_name"],
            source_geometry_hash=item["source_geometry_hash"],
            source_geometry_lonlat=tuple(
                (float(point[0]), float(point[1]))
                for point in item["source_geometry_lonlat"]
            ),
            source_fact_id=item["source_fact_id"],
            derived_distance_m=float(item["derived_distance_m"]),
            climb_m=float(item["climb_m"]),
            descent_m=float(item["descent_m"]),
            elevation_profile=tuple(
                (float(point[0]), float(point[1]))
                for point in item["elevation_profile"]
            ),
            athlete_count=item["athlete_count"],
            effort_count=item["effort_count"],
            star_count=item["star_count"],
        )
        for item in snapshot["observations"]
    )
    for source, observation in zip(snapshot["observations"], observations):
        if source["source_point_count"] != len(observation.source_geometry_lonlat):
            raise ValueError("source slice geometry point count 漂移")
        if strava_source_geometry_hash(
            [list(point) for point in observation.source_geometry_lonlat]
        ) != observation.source_geometry_hash:
            raise ValueError("source slice geometry hash 漂移")
        if source["glo_algorithm_version"] != "glo30_meaningful_ascent_v1":
            raise ValueError("source slice GLO algorithm version 不一致")
        if len(source["elevation_snapshot"]) != source["source_point_count"]:
            raise ValueError("source slice GLO snapshot point count 漂移")
    return observations


def build_run(spec_data: dict, snapshot: dict) -> dict[str, Any]:
    if spec_data.get("schema_version") != "mountain_module_spec_v2":
        raise ValueError("unsupported mountain module spec schema")
    if spec_data.get("module_role") != "destination_block":
        raise ValueError("mountain module must declare destination_block role")
    if spec_data.get("connections"):
        raise ValueError(
            "single destination module cannot embed route connections; "
            "assemble full transit-road traversals later"
        )
    for block in spec_data.get("route_blocks", []):
        if block.get("block_role") != "destination_traversal":
            raise ValueError("route block must declare destination_traversal role")
        if block.get("recommendation_status") != "evidence_candidate":
            raise ValueError("destination traversal cannot embed route blockers")
        if block.get("blockers"):
            raise ValueError("destination traversal cannot embed route blockers")
        if len(block.get("traversals", [])) != 1:
            raise ValueError("destination traversal v2 requires exactly one traversal")
    observations = _observations(snapshot)
    spec = MountainModuleSpec(
        module_key=spec_data["module_key"],
        reference_observation_id=spec_data["reference_axis"][
            "source_observation_id"
        ],
        heat_snapshot_cohort=spec_data["heat_snapshot_cohort"],
        observation_ids=tuple(spec_data["source_selection"]["observation_ids"]),
        excluded_source_segment_ids=tuple(
            spec_data["excluded_source_segment_ids"]
        ),
    )
    analysis = analyze_mountain_module(spec, observations)
    by_id = {item.source_observation_id: item for item in observations}
    axis_length = analysis["reference_axis_length_m"]
    _validate_role_requirements(spec_data, analysis)
    reference = by_id[spec_data["reference_axis"]["source_observation_id"]]
    if (
        reference.source_segment_id
        != spec_data["reference_axis"]["source_segment_id"]
        or reference.source_geometry_hash
        != spec_data["reference_axis"]["source_geometry_hash"]
    ):
        raise ValueError("reference axis source identity 漂移")
    module_name = spec_data["module_name"]
    profile_observation = by_id[spec_data["axis_profile_observation_id"]]
    axis_profile = [
        [round(point[0], 4), round(point[1], 1)]
        for point in profile_observation.elevation_profile
    ]
    blocks = []
    projections = _projection_by_observation(analysis)
    for definition in spec_data["route_blocks"]:
        traversal_definitions = definition["traversals"]
        block_resource_ids = [
            item["resource_observation_id"] for item in traversal_definitions
        ]
        if len(block_resource_ids) != len(set(block_resource_ids)):
            raise ValueError("route block cannot count one source fact twice")
        traversals = tuple(
            DirectedTraversal(
                item["direction"],
                _measure(item["start_measure"], axis_length),
                _measure(item["end_measure"], axis_length),
            )
            for item in traversal_definitions
        )
        resources = []
        for traversal_definition, traversal in zip(
            traversal_definitions, traversals
        ):
            resource_id = traversal_definition["resource_observation_id"]
            projection = projections[resource_id]
            alignment = traversal_definition["min_resource_alignment_ratio"]
            if not MIN_RESOURCE_ALIGNMENT_RATIO <= alignment <= 1.0:
                raise ValueError(
                    "resource alignment ratio is below the global minimum"
                )
            if projection["direction"] != traversal.direction:
                raise ValueError("route resource direction does not match traversal")
            traversal_coverage, resource_extent_coverage = _traversal_coverage_ratio(
                projection,
                traversal.start_measure_m,
                traversal.end_measure_m,
            )
            if (
                projection["source_coverage_ratio"] < alignment
                or traversal_coverage < alignment
                or resource_extent_coverage < alignment
            ):
                raise ValueError("route resource does not align with traversal extent")
            resources.append(by_id[resource_id])
        blocks.append(
            summarize_route_block(
                analysis,
                block_key=f"{spec.module_key}:{definition['block_key_suffix']}",
                block_name=f"{module_name}{definition['name_suffix']}",
                traversals=traversals,
                distance_m=sum(item.derived_distance_m for item in resources),
                climb_m=sum(item.climb_m for item in resources),
                descent_m=sum(item.descent_m for item in resources),
                recommendation_reasons=definition["recommendation_reasons"],
                traversal_port_keys=tuple(
                    (item["entry_port_key"], item["exit_port_key"])
                    for item in traversal_definitions
                ),
            )
        )
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "algorithm_version": MOUNTAIN_MODULE_ALGORITHM_VERSION,
        "config_version": MOUNTAIN_MODULE_CONFIG_VERSION,
        "config_sha256": MOUNTAIN_MODULE_CONFIG_SHA256,
        "module_key": spec.module_key,
        "module_name": spec_data["module_name"],
        "module_role": spec_data["module_role"],
        "direction_semantics": spec_data["reference_axis"][
            "direction_semantics"
        ],
        "artifact_location": spec_data["artifact_location"],
        "spec_sha256": _canonical_sha256(spec_data),
        "source_slice_sha256": snapshot["slice_sha256"],
        "analysis": analysis,
        "heat_evidence_explanation": heat_evidence_explanation(analysis),
        "reference_axis_elevation_profile": axis_profile,
        "route_blocks": blocks,
        "connections": [],
        "holdout_observation_ids": spec_data["holdout_observation_ids"],
        "holdout_status": "off_axis_connection_not_proven",
        "database_write_count": 0,
        "network_request_count": 0,
    }
    payload["run_sha256"] = _canonical_sha256(payload)
    return payload


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, path)


def public_manifest(result: dict[str, Any]) -> dict[str, Any]:
    """Return a coordinate-free pointer safe to keep with the repository."""

    payload = {
        "schema_version": "mountain_module_run_pointer_v2",
        "module_key": result["module_key"],
        "module_role": result["module_role"],
        "direction_semantics": result["direction_semantics"],
        "status": "research_shadow",
        "spec_sha256": result["spec_sha256"],
        "source_slice_sha256": result["source_slice_sha256"],
        "run_sha256": result["run_sha256"],
        "analysis_sha256": result["analysis"]["analysis_sha256"],
        "algorithm_version": result["algorithm_version"],
        "config_version": result["config_version"],
        "config_sha256": result["config_sha256"],
        "projection_algorithm_version": result["analysis"][
            "projection_algorithm_version"
        ],
        "evidence_algorithm_version": result["analysis"][
            "evidence_algorithm_version"
        ],
        "observation_count": result["analysis"]["observation_count"],
        "accepted_posting_count": result["analysis"]["accepted_posting_count"],
        "heat_evidence_explanation": result["heat_evidence_explanation"],
        "route_blocks": [
            {
                key: block[key]
                for key in (
                    "block_key",
                    "block_name",
                    "recommendation_status",
                    "distance_km",
                    "climb_m",
                    "descent_m",
                    "traversal_ports",
                    "heat_evidence",
                    "recommendation_policy",
                    "recommendation_reasons",
                    "blockers",
                    "block_sha256",
                )
            }
            for block in result["route_blocks"]
        ],
        "connections": result["connections"],
        "holdout_observation_ids": result["holdout_observation_ids"],
        "holdout_status": result["holdout_status"],
        "database_write_count": result["database_write_count"],
        "network_request_count": result["network_request_count"],
        "artifact_location": result["artifact_location"],
        "boundary": (
            "完整来源坐标和 GLO snapshot 位于本机 evidence ledger；仓库仅保存 hash、"
            "算法版本、积木摘要和 research 边界。"
        ),
    }
    return payload


def region_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Compact evidence-only payload used by the human-readable visual."""

    analysis = result["analysis"]
    return {
        "schema_version": "mountain_module_visual_summary_v2",
        "module_key": result["module_key"],
        "module_name": result["module_name"],
        "module_role": result["module_role"],
        "direction_semantics": result["direction_semantics"],
        "run_sha256": result["run_sha256"],
        "reference_axis_length_m": analysis["reference_axis_length_m"],
        "reference_axis_elevation_profile": result[
            "reference_axis_elevation_profile"
        ],
        "projections": [
            {
                "source_observation_id": item["source_observation_id"],
                "source_segment_id": item["source_segment_id"],
                "source_name": item["source_name"],
                "athlete_count": item["athlete_count"],
                "effort_count": item["effort_count"],
                "star_count": item["star_count"],
                "direction": item["result"]["direction"],
                "source_coverage_ratio": item["result"][
                    "source_coverage_ratio"
                ],
                "matched_runs": [
                    run["carrier_interval_m"]
                    for run in item["result"]["matched_runs"]
                ],
            }
            for item in analysis["projections"]
        ],
        "directed_evidence_cells": [
            {
                key: cell[key]
                for key in (
                    "direction",
                    "start_measure_m",
                    "end_measure_m",
                    "support_state",
                    "reach_union_lower_bound",
                    "reach_union_upper_bound",
                    "repeat_proxy_range",
                    "star_proxy_range",
                    "projection_quality_floor",
                    "raw_support_count",
                )
            }
            for cell in analysis["directed_evidence"]["cells"]
        ],
        "route_blocks": result["route_blocks"],
        "connections": result["connections"],
        "heat_evidence_explanation": result["heat_evidence_explanation"],
        "holdout_observation_ids": result["holdout_observation_ids"],
        "holdout_status": result["holdout_status"],
        "boundary": analysis["boundary"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    spec, snapshot = _load_inputs(args.spec, args.snapshot)
    result = build_run(spec, snapshot)
    _atomic_write(
        args.output,
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n",
    )
    return {
        "status": "complete",
        "output": str(args.output),
        "run_sha256": result["run_sha256"],
        "route_block_count": len(result["route_blocks"]),
        "database_write_count": 0,
        "network_request_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-manifest-output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    try:
        result = run(args)
        if args.public_manifest_output is not None:
            full_result = json.loads(args.output.read_text(encoding="utf-8"))
            _atomic_write(
                args.public_manifest_output,
                json.dumps(
                    public_manifest(full_result),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n",
            )
        if args.summary_output is not None:
            full_result = json.loads(args.output.read_text(encoding="utf-8"))
            _atomic_write(
                args.summary_output,
                json.dumps(
                    region_summary(full_result),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n",
            )
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}:{exc}"},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
