#!/usr/bin/env python3
"""把冻结 provider 路径与当前赛段 witness 合成为可重放 TransitPath。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.route_cognition.transit_paths import (
    TransitEvidenceFact,
    TransitPort,
    TransitStep,
    build_transit_path,
    canonical_sha256,
)
from app.route_cognition.spatial_relations import (
    RAW_SPATIAL_RELATION_CONFIG_V1,
    analyze_spatial_relation,
)


def derive_selection_snapshot(source_slice: dict, relation_profile: dict) -> dict:
    declared_hash = source_slice.get("slice_sha256")
    unhashed = dict(source_slice)
    unhashed.pop("slice_sha256", None)
    if declared_hash != canonical_sha256(unhashed):
        raise ValueError("source slice hash drift")
    observations = source_slice.get("observations") or []
    if len(observations) != relation_profile["candidate_count"]:
        raise ValueError("source slice candidate count drift")
    excluded = {
        str(value) for value in relation_profile["excluded_source_segment_ids"]
    }
    included = [
        item for item in observations if str(item["source_segment_id"]) not in excluded
    ]
    if len(included) != relation_profile["included_count"]:
        raise ValueError("source slice included count drift")
    bindings = [
        {
            "source_observation_id": int(item["source_observation_id"]),
            "source_segment_id": str(item["source_segment_id"]),
            "source_geometry_hash": item["source_geometry_hash"],
            "source_length_m": round(float(item["derived_distance_m"]), 3),
            "glo_fact_id": int(item["glo_fact_id"]),
            "glo_algorithm_version": item["glo_algorithm_version"],
            "athlete_count": item["athlete_count"],
            "effort_count": item["effort_count"],
            "star_count": item["star_count"],
        }
        for item in sorted(included, key=lambda row: int(row["source_observation_id"]))
    ]
    payload = {
        "schema_version": "xishan_relation_selection_snapshot_v1",
        "profile_key": relation_profile["profile_key"],
        "relation_profile_sha256": canonical_sha256(relation_profile),
        "census_batch_id": relation_profile["census_batch_id"],
        "elevation_fact_batch_id": relation_profile["elevation_fact_batch_id"],
        "candidate_count": relation_profile["candidate_count"],
        "included_count": relation_profile["included_count"],
        "excluded_count": relation_profile["excluded_count"],
        "excluded_source_segment_ids": sorted(excluded),
        "source_slice_sha256": declared_hash,
        "included_bindings": bindings,
        "included_binding_sha256": canonical_sha256(bindings),
        "database_write_count": 0,
    }
    payload["snapshot_sha256"] = canonical_sha256(payload)
    return payload


def _validate_selection(
    selection_snapshot: dict,
    relation_profile: dict,
) -> dict[int, dict]:
    declared_hash = selection_snapshot.get("snapshot_sha256")
    unhashed = dict(selection_snapshot)
    unhashed.pop("snapshot_sha256", None)
    if declared_hash != canonical_sha256(unhashed):
        raise ValueError("selection snapshot hash drift")
    profile_hash = canonical_sha256(relation_profile)
    if selection_snapshot.get("relation_profile_sha256") != profile_hash:
        raise ValueError("selection snapshot references another relation profile")
    expected_fields = (
        "profile_key",
        "census_batch_id",
        "elevation_fact_batch_id",
        "candidate_count",
        "included_count",
        "excluded_count",
        "excluded_source_segment_ids",
    )
    for field in expected_fields:
        if selection_snapshot.get(field) != relation_profile.get(field):
            raise ValueError(f"selection snapshot {field} drift")
    rows = selection_snapshot.get("included_bindings") or []
    if len(rows) != relation_profile["included_count"]:
        raise ValueError("selection included binding count drift")
    by_observation = {int(row["source_observation_id"]): row for row in rows}
    if len(by_observation) != len(rows):
        raise ValueError("selection included observations must be unique")
    if len({str(row["source_segment_id"]) for row in rows}) != len(rows):
        raise ValueError("selection included source segments must be unique")
    if canonical_sha256(rows) != selection_snapshot.get("included_binding_sha256"):
        raise ValueError("selection included binding hash drift")
    excluded = {str(value) for value in relation_profile["excluded_source_segment_ids"]}
    if any(str(row["source_segment_id"]) in excluded for row in rows):
        raise ValueError("selection included bindings contain excluded source segment")
    return by_observation


def _interval_union_length(intervals: list[list[float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted((float(row[0]), float(row[1])) for row in intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def _source_component_union_length(components: list[dict]) -> float:
    intervals = [
        sorted((float(row[0]), float(row[1])))
        for row in (component["right_interval_m"] for component in components)
    ]
    return _interval_union_length(intervals)


def _validate_source_slice(
    source_slice: dict,
    selection_snapshot: dict,
    relation_profile: dict,
) -> list[dict]:
    declared_hash = source_slice.get("slice_sha256")
    unhashed = dict(source_slice)
    unhashed.pop("slice_sha256", None)
    if declared_hash != canonical_sha256(unhashed):
        raise ValueError("source slice hash drift")
    if declared_hash != selection_snapshot.get("source_slice_sha256"):
        raise ValueError("source slice does not match selection snapshot")
    if source_slice.get("census_batch_id") != relation_profile["census_batch_id"]:
        raise ValueError("source slice census batch drift")
    if source_slice.get("elevation_fact_batch_id") != relation_profile[
        "elevation_fact_batch_id"
    ]:
        raise ValueError("source slice elevation fact batch drift")
    observations = source_slice.get("observations") or []
    if len(observations) != relation_profile["candidate_count"]:
        raise ValueError("source slice candidate count drift")
    by_observation = {
        int(item["source_observation_id"]): item for item in observations
    }
    if len(by_observation) != len(observations):
        raise ValueError("source slice observations must be unique")
    included_ids = {
        int(item["source_observation_id"])
        for item in selection_snapshot["included_bindings"]
    }
    excluded_ids = {
        str(value) for value in relation_profile["excluded_source_segment_ids"]
    }
    selected = [by_observation[value] for value in sorted(included_ids)]
    if len(selected) != relation_profile["included_count"]:
        raise ValueError("source slice is missing included observations")
    candidate_source_ids = {str(item["source_segment_id"]) for item in observations}
    if not excluded_ids.issubset(candidate_source_ids):
        raise ValueError("source slice is missing excluded observations")
    for binding in selection_snapshot["included_bindings"]:
        item = by_observation[int(binding["source_observation_id"])]
        for field in (
            "source_segment_id",
            "source_geometry_hash",
            "glo_fact_id",
            "glo_algorithm_version",
            "athlete_count",
            "effort_count",
            "star_count",
        ):
            if str(item[field]) != str(binding[field]):
                raise ValueError(f"source slice {field} does not match selection")
        if abs(float(item["derived_distance_m"]) - float(binding["source_length_m"])) > 0.1:
            raise ValueError("source slice length does not match selection")
        if item["glo_algorithm_version"] != "glo30_meaningful_ascent_v1":
            raise ValueError("source slice GLO algorithm drift")
        if len(item.get("source_geometry_lonlat") or []) < 2:
            raise ValueError("source slice geometry is incomplete")
    return selected


def derive_evidence_snapshot(
    provider_snapshot: dict,
    selection_snapshot: dict,
    relation_profile: dict,
    source_slice: dict,
) -> dict:
    selected = _validate_source_slice(
        source_slice,
        selection_snapshot,
        relation_profile,
    )
    facts: list[dict] = []
    for item in selected:
        result = analyze_spatial_relation(
            f"transit:{provider_snapshot['transit_key']}",
            provider_snapshot["geometry_wgs84"],
            f"observation:{item['source_observation_id']}",
            item["source_geometry_lonlat"],
            config=RAW_SPATIAL_RELATION_CONFIG_V1,
        ).to_dict()
        components = result["components"]
        if not components:
            continue
        intervals = [component["left_interval_m"] for component in components]
        shared_length_m = _interval_union_length(intervals)
        source_shared_length_m = _source_component_union_length(components)
        if shared_length_m <= 0:
            continue
        source_length_m = float(item["derived_distance_m"])
        provider_distance_m = float(provider_snapshot["distance_m"])
        facts.append(
            {
                "source_observation_id": int(item["source_observation_id"]),
                "source_segment_id": str(item["source_segment_id"]),
                "source_name": item["source_name"],
                "source_geometry_hash": item["source_geometry_hash"],
                "source_length_m": round(source_length_m, 3),
                "shared_length_m": round(shared_length_m, 3),
                "transit_intervals_m": intervals,
                "transit_coverage_ratio": round(
                    shared_length_m / provider_distance_m,
                    6,
                ),
                "source_coverage_ratio": round(
                    min(1.0, source_shared_length_m / source_length_m),
                    6,
                ),
                "direction_relation": result["direction_relation"],
                "extent_relation": result["extent_relation"],
                "evidence_status": (
                    "admitted_directional_evidence"
                    if result["extent_relation"]
                    in {
                        "equivalent",
                        "a_contains_b",
                        "b_contains_a",
                        "partial_overlap",
                    }
                    else "diagnostic_indeterminate"
                ),
                "reason_codes": result["reason_codes"],
                "athlete_count": item["athlete_count"],
                "effort_count": item["effort_count"],
                "star_count": item["star_count"],
                "relation_result_sha256": result["result_sha256"],
                "components": components,
            }
        )
    payload = {
        "schema_version": "xishan_transit_evidence_snapshot_v2",
        "transit_key": provider_snapshot["transit_key"],
        "provider_snapshot_sha256": provider_snapshot["snapshot_sha256"],
        "selection_snapshot_sha256": selection_snapshot["snapshot_sha256"],
        "relation_profile_key": relation_profile["profile_key"],
        "relation_algorithm_version": RAW_SPATIAL_RELATION_CONFIG_V1.version,
        "candidate_count": relation_profile["candidate_count"],
        "included_count": relation_profile["included_count"],
        "excluded_count": relation_profile["excluded_count"],
        "evidence_facts": facts,
        "database_write_count": 0,
    }
    payload["evidence_snapshot_sha256"] = canonical_sha256(payload)
    return payload


def _validate_port_bindings(
    provider_snapshot: dict,
    selection_snapshot: dict,
    source_slice: dict | None,
    module_manifests: list[dict] | None,
) -> None:
    included = {
        int(item["source_observation_id"]): item
        for item in selection_snapshot["included_bindings"]
    }
    source_by_observation = {
        int(item["source_observation_id"]): item
        for item in ((source_slice or {}).get("observations") or [])
    }
    module_ports: dict[tuple[str, str, str], dict] = {}
    manifests = (
        [module_manifests]
        if isinstance(module_manifests, dict)
        else (module_manifests or [])
    )
    for module_manifest in manifests:
        for block in module_manifest.get("route_blocks") or []:
            for traversal in block.get("traversal_ports") or []:
                for role in ("entry", "exit"):
                    item = traversal[role]
                    key = (item["module_key"], item["port_key"], item["port_sha256"])
                    if key in module_ports:
                        raise ValueError("duplicate canonical module port")
                    module_ports[key] = item
    for endpoint_name in ("from", "to"):
        endpoint = provider_snapshot[endpoint_name]
        if endpoint["binding_type"] == "source_observation_candidate":
            observation_id = int(endpoint["source_observation_id"])
            binding = included.get(observation_id)
            source = source_by_observation.get(observation_id)
            if binding is None or source is None:
                raise ValueError("candidate port is outside the included source facts")
            if endpoint["source_geometry_hash"] != binding["source_geometry_hash"]:
                raise ValueError("candidate port geometry hash drift")
            source_points = source["source_geometry_lonlat"]
            candidate_port = endpoint["lonlat"]
            endpoint_distances = [
                _haversine_lonlat(candidate_port, source_points[0]),
                _haversine_lonlat(candidate_port, source_points[-1]),
            ]
            if min(endpoint_distances) > 30.0:
                raise ValueError("candidate port is not a source observation endpoint")
        elif endpoint["binding_type"] == "canonical_module_port":
            key = (
                endpoint["module_key"],
                endpoint["port_key"],
                endpoint["module_port_sha256"],
            )
            registered = module_ports.get(key)
            if registered is None:
                raise ValueError("canonical port is outside the module manifest")
            source = next(
                (
                    item
                    for item in source_by_observation.values()
                    if item["source_geometry_hash"]
                    == registered["reference_source_geometry_hash"]
                ),
                None,
            )
            if source is None:
                raise ValueError("canonical port reference source is unavailable")
            source_points = source["source_geometry_lonlat"]
            source_length_m = float(source["derived_distance_m"])
            axis_measure_m = float(registered["axis_measure_m"])
            if min(axis_measure_m, abs(source_length_m - axis_measure_m)) > 30.0:
                raise ValueError("v1 canonical transit port must be a source endpoint")
            expected_point = (
                source_points[0]
                if axis_measure_m <= source_length_m / 2
                else source_points[-1]
            )
            if _haversine_lonlat(endpoint["lonlat"], expected_point) > 30.0:
                raise ValueError("canonical port coordinates drift")
        else:
            raise ValueError("unsupported port binding type")


def _haversine_lonlat(left: list[float], right: list[float]) -> float:
    from app.parsing.geo_math import haversine

    return haversine(float(left[1]), float(left[0]), float(right[1]), float(right[0]))


def build_run(
    provider_snapshot: dict,
    evidence_snapshot: dict,
    selection_snapshot: dict,
    relation_profile: dict,
    source_slice: dict | None = None,
    module_manifests: list[dict] | None = None,
) -> dict:
    included = _validate_selection(selection_snapshot, relation_profile)
    declared_hash = provider_snapshot.get("snapshot_sha256")
    unhashed_provider = dict(provider_snapshot)
    unhashed_provider.pop("snapshot_sha256", None)
    if declared_hash != canonical_sha256(unhashed_provider):
        raise ValueError("provider snapshot hash drift")
    expected_provider_hash = evidence_snapshot["provider_snapshot_sha256"]
    if declared_hash != expected_provider_hash:
        raise ValueError("evidence manifest references another provider snapshot")
    _validate_port_bindings(
        provider_snapshot,
        selection_snapshot,
        source_slice,
        module_manifests,
    )
    if source_slice is not None:
        derived_evidence = derive_evidence_snapshot(
            provider_snapshot,
            selection_snapshot,
            relation_profile,
            source_slice,
        )
        if evidence_snapshot != derived_evidence:
            raise ValueError("evidence snapshot does not match exact active-road replay")
    declared_evidence_hash = evidence_snapshot.get("evidence_snapshot_sha256")
    unhashed_evidence = dict(evidence_snapshot)
    unhashed_evidence.pop("evidence_snapshot_sha256", None)
    if declared_evidence_hash != canonical_sha256(unhashed_evidence):
        raise ValueError("evidence snapshot hash drift")
    if evidence_snapshot["transit_key"] != provider_snapshot["transit_key"]:
        raise ValueError("provider and evidence transit key drift")
    if evidence_snapshot.get("selection_snapshot_sha256") != selection_snapshot.get(
        "snapshot_sha256"
    ):
        raise ValueError("evidence references another selection snapshot")
    if evidence_snapshot.get("relation_profile_key") != relation_profile["profile_key"]:
        raise ValueError("evidence relation profile drift")

    for item in evidence_snapshot["evidence_facts"]:
        binding = included.get(int(item["source_observation_id"]))
        if binding is None:
            raise ValueError("evidence observation is outside the included selection")
        for field in ("source_segment_id", "source_geometry_hash"):
            if str(item[field]) != str(binding[field]):
                raise ValueError(f"evidence {field} does not match selection binding")
        if abs(float(item["source_length_m"]) - float(binding["source_length_m"])) > 0.1:
            raise ValueError("evidence source length does not match selection binding")
        for field in ("athlete_count", "effort_count", "star_count"):
            if item.get(field) != binding.get(field):
                raise ValueError(f"evidence {field} does not match selection binding")

    facts = tuple(
        TransitEvidenceFact(
            source_observation_id=int(item["source_observation_id"]),
            source_segment_id=str(item["source_segment_id"]),
            source_name=item["source_name"],
            source_geometry_hash=item["source_geometry_hash"],
            source_length_m=float(item["source_length_m"]),
            shared_length_m=float(item["shared_length_m"]),
            transit_intervals_m=tuple(
                (float(interval[0]), float(interval[1]))
                for interval in item["transit_intervals_m"]
            ),
            transit_coverage_ratio=float(item["transit_coverage_ratio"]),
            source_coverage_ratio=float(item["source_coverage_ratio"]),
            direction_relation=item["direction_relation"],
            extent_relation=item["extent_relation"],
            evidence_status=item["evidence_status"],
            reason_codes=tuple(item["reason_codes"]),
            athlete_count=item.get("athlete_count"),
            effort_count=item.get("effort_count"),
            star_count=item.get("star_count"),
        )
        for item in evidence_snapshot["evidence_facts"]
    )
    run = build_transit_path(
        transit_key=evidence_snapshot["transit_key"],
        from_port=TransitPort(
            port_key=provider_snapshot["from"]["port_key"],
            longitude=float(provider_snapshot["from"]["lonlat"][0]),
            latitude=float(provider_snapshot["from"]["lonlat"][1]),
            binding_type=provider_snapshot["from"]["binding_type"],
            module_key=provider_snapshot["from"].get("module_key"),
            module_port_sha256=provider_snapshot["from"].get("module_port_sha256"),
            source_observation_id=provider_snapshot["from"].get(
                "source_observation_id"
            ),
            source_geometry_hash=provider_snapshot["from"].get(
                "source_geometry_hash"
            ),
        ),
        to_port=TransitPort(
            port_key=provider_snapshot["to"]["port_key"],
            longitude=float(provider_snapshot["to"]["lonlat"][0]),
            latitude=float(provider_snapshot["to"]["lonlat"][1]),
            binding_type=provider_snapshot["to"]["binding_type"],
            module_key=provider_snapshot["to"].get("module_key"),
            module_port_sha256=provider_snapshot["to"].get("module_port_sha256"),
            source_observation_id=provider_snapshot["to"].get(
                "source_observation_id"
            ),
            source_geometry_hash=provider_snapshot["to"].get(
                "source_geometry_hash"
            ),
        ),
        provider=provider_snapshot["provider"],
        provider_observed_at=provider_snapshot["provider_observed_at"],
        provider_status=provider_snapshot["status"],
        research_verdict=provider_snapshot["research_verdict"],
        provider_snapshot_sha256=declared_hash,
        evidence_snapshot_sha256=declared_evidence_hash,
        provider_distance_m=float(provider_snapshot["distance_m"]),
        provider_duration_raw=provider_snapshot.get("provider_duration_raw"),
        geometry_wgs84=provider_snapshot["geometry_wgs84"],
        steps=(
            TransitStep(
                road_name=item["road_name"],
                distance_m=float(item["distance_m"]),
                instruction=item.get("instruction"),
                action=item.get("act_desc"),
            )
            for item in provider_snapshot["road_steps"]
        ),
        elevation=provider_snapshot["elevation"],
        evidence_facts=facts,
    )
    run["relation_input"] = {
        "profile_key": relation_profile["profile_key"],
        "selection_snapshot_sha256": selection_snapshot["snapshot_sha256"],
        "candidate_count": relation_profile["candidate_count"],
        "included_count": relation_profile["included_count"],
        "excluded_count": relation_profile["excluded_count"],
        "included_binding_sha256": selection_snapshot["included_binding_sha256"],
    }
    run["result_sha256"] = canonical_sha256(
        {key: value for key, value in run.items() if key != "result_sha256"}
    )
    return run


def public_manifest(run: dict) -> dict:
    manifest = {
        key: value
        for key, value in run.items()
        if key not in {"geometry_wgs84", "ordered_road_steps"}
    }
    manifest["elevation"] = {
        key: value
        for key, value in run["elevation"].items()
        if key != "profile"
    }
    manifest["ordered_road_summary"] = [
        {
            "road_name": item["road_name"],
            "distance_m": item["distance_m"],
        }
        for item in run["ordered_road_steps"]
    ]
    manifest["public_manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-snapshot", type=Path, required=True)
    parser.add_argument("--evidence-snapshot", type=Path, required=True)
    parser.add_argument("--selection-snapshot", type=Path, required=True)
    parser.add_argument("--source-slice", type=Path, required=True)
    parser.add_argument("--module-manifest", type=Path, action="append", default=[])
    parser.add_argument(
        "--relation-profile",
        type=Path,
        default=REPO_ROOT / "data/research/xishan_relation_input_profile_v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--visibility",
        choices=("private", "public"),
        default="private",
        help="一次原子发布一种表示，避免两件套半更新",
    )
    args = parser.parse_args()
    provider = json.loads(args.provider_snapshot.read_text(encoding="utf-8"))
    evidence = json.loads(args.evidence_snapshot.read_text(encoding="utf-8"))
    selection = json.loads(args.selection_snapshot.read_text(encoding="utf-8"))
    source_slice = json.loads(args.source_slice.read_text(encoding="utf-8"))
    module_manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.module_manifest
    ]
    relation_profile = json.loads(args.relation_profile.read_text(encoding="utf-8"))
    run = build_run(
        provider,
        evidence,
        selection,
        relation_profile,
        source_slice,
        module_manifests,
    )
    output_payload = public_manifest(run) if args.visibility == "public" else run
    _write_json_atomic(args.output, output_payload)
    print(
        json.dumps(
            {
                "status": "complete",
                "result_sha256": run["result_sha256"],
                "distance_m": run["provider_distance_m"],
                "evidence_coverage": run["evidence_coverage"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
