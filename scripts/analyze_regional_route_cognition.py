#!/usr/bin/env python3
"""Reconcile one bounded observation batch and project evidence onto road-family axes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.route_cognition.carrier_projection import (  # noqa: E402
    CARRIER_PROJECTION_ALGORITHM_VERSION,
    CARRIER_PROJECTION_CONFIG_V1,
    DIRECTED_EVIDENCE_ALGORITHM_VERSION,
    EvidencePosting,
    arrange_directed_evidence,
    project_polyline_to_carrier,
)
from app.common.geometry_hash import strava_source_geometry_hash  # noqa: E402
from app.route_cognition.transit_paths import canonical_sha256  # noqa: E402


SPEC_SCHEMA_VERSION = "regional_route_cognition_spec_v1"
RUN_SCHEMA_VERSION = "regional_route_cognition_run_v1"


def _self_hash(payload: dict[str, Any], field: str) -> str:
    unhashed = dict(payload)
    unhashed.pop(field, None)
    return canonical_sha256(unhashed)


def _set_sha256(values: Iterable[int]) -> str:
    return hashlib.sha256(
        "\n".join(str(value) for value in sorted(values)).encode("utf-8")
    ).hexdigest()


def _bbox_intersects(points: Sequence[Sequence[float]], bbox: dict[str, float]) -> bool:
    lons = [float(point[0]) for point in points]
    lats = [float(point[1]) for point in points]
    return (
        min(lons) <= float(bbox["max_lon"])
        and max(lons) >= float(bbox["min_lon"])
        and min(lats) <= float(bbox["max_lat"])
        and max(lats) >= float(bbox["min_lat"])
    )


def _load_pair_subset(
    pairs: Iterable[dict[str, Any]],
    *,
    exact_ids: set[int],
    geometry_hashes: dict[int, str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    selected = []
    by_key = {}
    for item in pairs:
        left = int(item["observation_a_id"])
        right = int(item["observation_b_id"])
        if left not in exact_ids or right not in exact_ids:
            continue
        if item.get("comparison_status") != "complete":
            raise ValueError("regional oracle pair is not complete")
        if item.get("geometry_hash_a") != geometry_hashes[left]:
            raise ValueError("regional oracle left geometry hash drift")
        if item.get("geometry_hash_b") != geometry_hashes[right]:
            raise ValueError("regional oracle right geometry hash drift")
        if item.get("pair_record_sha256") != _self_hash(item, "pair_record_sha256"):
            raise ValueError("regional oracle pair record hash drift")
        selected.append(item)
        by_key[str(item["pair_key"])] = item
    expected_count = len(exact_ids) * (len(exact_ids) - 1) // 2
    if len(selected) != expected_count or len(by_key) != expected_count:
        raise ValueError("regional oracle pair exact set is incomplete")
    return selected, by_key


def _project_family(
    definition: dict[str, Any], observations: dict[int, dict[str, Any]], cohort: str
) -> dict[str, Any]:
    reference_id = int(definition["reference_observation_id"])
    reference = observations[reference_id]
    projections = []
    postings = []
    for observation_id in definition["evidence_observation_ids"]:
        item = observations[int(observation_id)]
        result = project_polyline_to_carrier(
            f"source-observation:{reference_id}",
            reference["source_geometry_lonlat"],
            str(observation_id),
            item["source_geometry_lonlat"],
            config=CARRIER_PROJECTION_CONFIG_V1,
        )
        result_dict = result.to_dict()
        projections.append(
            {
                "source_observation_id": int(observation_id),
                "source_segment_id": str(item["source_segment_id"]),
                "source_name": item["source_name"],
                "source_geometry_hash": item["source_geometry_hash"],
                "glo_fact_id": int(item["glo_fact_id"]),
                "derived_distance_m": float(item["derived_distance_m"]),
                "climb_m": float(item["climb_m"]),
                "descent_m": float(item["descent_m"]),
                "athlete_count": item["athlete_count"],
                "effort_count": item["effort_count"],
                "star_count": item["star_count"],
                "projection": {
                    "completion_status": result_dict["completion_status"],
                    "failure_code": result_dict["failure_code"],
                    "status": result_dict["status"],
                    "direction": result_dict["direction"],
                    "source_coverage_ratio": result_dict["source_coverage_ratio"],
                    "carrier_coverage_ratio": result_dict["carrier_coverage_ratio"],
                    "matched_runs": [
                        {
                            "orientation": run["orientation"],
                            "carrier_interval_m": run["carrier_interval_m"],
                            "source_interval_m": run["source_interval_m"],
                            "distance_quantiles_m": run["distance_quantiles_m"],
                        }
                        for run in result_dict["matched_runs"]
                    ],
                    "reason_codes": result_dict["reason_codes"],
                    "result_sha256": result_dict["result_sha256"],
                },
            }
        )
        if result.status != "research_projected" or result.direction not in {
            "forward",
            "reverse",
        }:
            continue
        for run in result.matched_runs:
            start, end = run.carrier_interval_m
            if end <= start:
                continue
            postings.append(
                EvidencePosting(
                    source_fact_id=f"glo-fact:{item['glo_fact_id']}",
                    cohort=cohort,
                    direction=result.direction,
                    start_measure_m=start,
                    end_measure_m=end,
                    athlete_count=item["athlete_count"],
                    effort_count=item["effort_count"],
                    star_count=item["star_count"],
                    projection_quality=result.source_coverage_ratio,
                )
            )
    axis_length_m = project_polyline_to_carrier(
        f"source-observation:{reference_id}",
        reference["source_geometry_lonlat"],
        str(reference_id),
        reference["source_geometry_lonlat"],
        config=CARRIER_PROJECTION_CONFIG_V1,
    ).carrier_length_m
    arrangement = arrange_directed_evidence(
        f"source-observation:{reference_id}", axis_length_m, postings
    ).to_dict()
    profile_ready = all(
        item.get("elevation_profile") and item.get("elevation_snapshot")
        for item in (
            observations[int(value)] for value in definition["evidence_observation_ids"]
        )
    )
    payload = {
        "family_key": definition["family_key"],
        "family_name": definition["family_name"],
        "family_role": definition["family_role"],
        "reference_observation_id": reference_id,
        "reference_source_geometry_hash": reference["source_geometry_hash"],
        "reference_axis_length_m": round(axis_length_m, 3),
        "canonical_geometry_storage": "one_reference_axis_geometry_only",
        "reverse_traversal_rule": (
            "reuse canonical geometry in reverse; swap entry/exit and climb/descent"
        ),
        "evidence_observation_ids": definition["evidence_observation_ids"],
        "resource_observation_id": definition.get("resource_observation_id"),
        "projections": projections,
        "directed_evidence": arrangement,
        "module_resource_status": (
            "ready_for_mountain_module_replay"
            if profile_ready
            else "glo_profile_pending_readonly_export"
        ),
        "module_resource_boundary": (
            "existing GLO totals are reconciled; full stored elevation snapshots are "
            "required before MountainModule resource publication"
        ),
    }
    payload["family_sha256"] = canonical_sha256(payload)
    return payload


def analyze(
    spec: dict[str, Any],
    source_slice: dict[str, Any],
    selection: dict[str, Any],
    pairs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise ValueError("unsupported regional route cognition spec")
    if source_slice.get("slice_sha256") != _self_hash(source_slice, "slice_sha256"):
        raise ValueError("source slice self hash drift")
    if selection.get("snapshot_sha256") != _self_hash(selection, "snapshot_sha256"):
        raise ValueError("selection snapshot self hash drift")
    if source_slice["slice_sha256"] != spec["source_slice_sha256"]:
        raise ValueError("regional spec references another source slice")
    if selection["snapshot_sha256"] != spec["selection_snapshot_sha256"]:
        raise ValueError("regional spec references another selection")
    if selection["source_slice_sha256"] != source_slice["slice_sha256"]:
        raise ValueError("selection references another source slice")
    all_observations = {
        int(item["source_observation_id"]): item
        for item in source_slice["observations"]
    }
    bbox_ids = sorted(
        observation_id
        for observation_id, item in all_observations.items()
        if _bbox_intersects(item["source_geometry_lonlat"], spec["bbox"])
    )
    exact_ids = [int(value) for value in spec["exact_observation_ids"]]
    if bbox_ids != exact_ids:
        raise ValueError("bbox does not reproduce the declared exact observation set")
    if spec["observation_set_sha256"] != _set_sha256(exact_ids):
        raise ValueError("regional observation set hash drift")
    observations = {value: all_observations[value] for value in exact_ids}
    bindings = {
        int(item["source_observation_id"]): item
        for item in selection["included_bindings"]
    }
    fact_fields = (
        "source_segment_id",
        "source_geometry_hash",
        "glo_fact_id",
        "glo_algorithm_version",
        "athlete_count",
        "effort_count",
        "star_count",
    )
    facts = []
    for observation_id in exact_ids:
        item = observations[observation_id]
        binding = bindings.get(observation_id)
        if binding is None:
            raise ValueError("regional observation is outside active selection")
        for field in fact_fields:
            if str(item[field]) != str(binding[field]):
                raise ValueError(f"regional {field} does not match active selection")
        if len(item["source_geometry_lonlat"]) != int(item["source_point_count"]):
            raise ValueError("regional source point count drift")
        if strava_source_geometry_hash(item["source_geometry_lonlat"]) != item[
            "source_geometry_hash"
        ]:
            raise ValueError("regional source geometry hash drift")
        facts.append(
            {
                key: item[key]
                for key in (
                    "source_observation_id",
                    "source_segment_id",
                    "source_name",
                    "source_geometry_hash",
                    "glo_fact_id",
                    "glo_algorithm_version",
                    "derived_distance_m",
                    "climb_m",
                    "descent_m",
                    "athlete_count",
                    "effort_count",
                    "star_count",
                    "source_point_count",
                )
            }
        )
    geometry_hashes = {
        observation_id: item["source_geometry_hash"]
        for observation_id, item in observations.items()
    }
    pair_rows, pair_by_key = _load_pair_subset(
        pairs, exact_ids=set(exact_ids), geometry_hashes=geometry_hashes
    )
    for expected in spec.get("expected_oracle_pairs") or []:
        actual = pair_by_key[expected["pair_key"]]
        if actual["result"]["extent_relation"] != expected["extent_relation"]:
            raise ValueError(f"oracle counterexample drift: {expected['pair_key']}")
        if actual["result"]["direction_relation"] != expected["direction_relation"]:
            raise ValueError(f"oracle direction counterexample drift: {expected['pair_key']}")

    primary_ids = [
        int(value)
        for item in spec["primary_dispositions"]
        for value in item["observation_ids"]
    ]
    if sorted(primary_ids) != exact_ids or len(primary_ids) != len(set(primary_ids)):
        raise ValueError("primary family dispositions must cover exact set once")
    families = [
        _project_family(item, observations, spec["heat_snapshot_cohort"])
        for item in spec["families"]
    ]
    extent_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for pair in pair_rows:
        extent = pair["result"]["extent_relation"]
        direction = pair["result"]["direction_relation"]
        extent_counts[extent] = extent_counts.get(extent, 0) + 1
        direction_counts[direction] = direction_counts.get(direction, 0) + 1
    payload = {
        "schema_version": RUN_SCHEMA_VERSION,
        "batch_key": spec["batch_key"],
        "status": "research_shadow",
        "source_slice_sha256": source_slice["slice_sha256"],
        "selection_snapshot_sha256": selection["snapshot_sha256"],
        "observation_set_sha256": spec["observation_set_sha256"],
        "exact_observation_ids": exact_ids,
        "fact_reconciliation": {
            "observation_count": len(facts),
            "unique_source_segment_count": len({item["source_segment_id"] for item in facts}),
            "unique_geometry_hash_count": len({item["source_geometry_hash"] for item in facts}),
            "unique_glo_fact_count": len({item["glo_fact_id"] for item in facts}),
            "heat_complete_count": sum(
                all(item[key] is not None for key in ("athlete_count", "effort_count", "star_count"))
                for item in facts
            ),
            "glo_algorithm_version": "glo30_meaningful_ascent_v1",
            "observations": facts,
        },
        "oracle_summary": {
            "pair_count": len(pair_rows),
            "complete_count": len(pair_rows),
            "extent_counts": extent_counts,
            "direction_counts": direction_counts,
            "raw_geometry_boundary": "research oracle not road identity or access truth",
        },
        "primary_dispositions": spec["primary_dispositions"],
        "families": families,
        "projection_algorithm_version": CARRIER_PROJECTION_ALGORITHM_VERSION,
        "projection_config": CARRIER_PROJECTION_CONFIG_V1.to_dict(),
        "evidence_algorithm_version": DIRECTED_EVIDENCE_ALGORITHM_VERSION,
        "database_write_count": 0,
        "network_request_count": 0,
        "boundary": (
            "active-81 downstream regional holdout; research candidates only. "
            "No Strava fetch, GLO recomputation, production write, or access claim."
        ),
    }
    payload["run_sha256"] = canonical_sha256(payload)
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
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


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--source-slice", type=Path, required=True)
    parser.add_argument("--selection-snapshot", type=Path, required=True)
    parser.add_argument("--oracle-pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = analyze(
        json.loads(args.spec.read_text(encoding="utf-8")),
        json.loads(args.source_slice.read_text(encoding="utf-8")),
        json.loads(args.selection_snapshot.read_text(encoding="utf-8")),
        _read_jsonl(args.oracle_pairs),
    )
    _atomic_write(args.output, result)
    print(
        json.dumps(
            {
                "status": "complete",
                "run_sha256": result["run_sha256"],
                "observation_count": result["fact_reconciliation"]["observation_count"],
                "family_count": len(result["families"]),
                "pair_count": result["oracle_summary"]["pair_count"],
                "module_resource_statuses": {
                    item["family_key"]: item["module_resource_status"]
                    for item in result["families"]
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
