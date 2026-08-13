#!/usr/bin/env python3
"""Compose the complete Hengling -> Huaketou -> Taohuagou pattern and heat vector."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.route_cognition.route_heat import (
    POPULAR_RELIABLE_POLICY_VERSION,
    ROUTE_HEAT_ALGORITHM_VERSION,
    component_from_directed_cells,
    compose_route_heat,
    rank_heat_candidates,
)
from app.route_cognition.carrier_projection import (
    EvidencePosting,
    arrange_directed_evidence,
)
from app.route_cognition.transit_paths import canonical_sha256


SCHEMA_VERSION = "xishan_route_heat_recommendation_v1"
EXPECTED_TRANSIT_KEY = "hengling-upper-to-taohuagou-huaketou"
EXPECTED_TRANSIT_VERDICT = "connection_candidate"


def _self_hash_matches(payload: dict, field: str) -> bool:
    declared = payload.get(field)
    unhashed = {key: value for key, value in payload.items() if key != field}
    return isinstance(declared, str) and declared == canonical_sha256(unhashed)


def _route_hard_failures(
    mountain_module_run: dict,
    transit_run: dict,
    source_slice: dict,
    ascent_block: dict,
    hengling_source: dict,
    taohuagou_source: dict,
) -> tuple[str, ...]:
    """Return only failures that make this ordered three-part route invalid."""
    failures: list[str] = []
    if not _self_hash_matches(mountain_module_run, "run_sha256"):
        failures.append("mountain_module_hash_mismatch")
    if not _self_hash_matches(transit_run, "result_sha256"):
        failures.append("transit_result_hash_mismatch")
    if not _self_hash_matches(source_slice, "slice_sha256"):
        failures.append("source_slice_hash_mismatch")
    if transit_run.get("transit_key") != EXPECTED_TRANSIT_KEY:
        failures.append("unexpected_transit_path")
    if transit_run.get("research_verdict") != EXPECTED_TRANSIT_VERDICT:
        failures.append("transit_not_connection_candidate")
    if ascent_block.get("blockers"):
        failures.append("full_ascent_blocked")

    traversal_ports = ascent_block.get("traversal_ports") or []
    exit_port = traversal_ports[0].get("exit") if len(traversal_ports) == 1 else None
    transit_from = transit_run.get("from") or {}
    if not exit_port or any(
        (
            transit_from.get("module_key") != exit_port.get("module_key"),
            transit_from.get("port_key") != exit_port.get("port_key"),
            transit_from.get("module_port_sha256") != exit_port.get("port_sha256"),
            exit_port.get("reference_source_geometry_hash")
            != hengling_source.get("source_geometry_hash"),
        )
    ):
        failures.append("full_ascent_exit_port_mismatch")

    expected_from = hengling_source["source_geometry_lonlat"][-1]
    actual_from = transit_from.get("lonlat") or []
    if len(actual_from) != 2 or max(
        abs(float(a) - float(b)) for a, b in zip(expected_from, actual_from)
    ) > 1e-6:
        failures.append("full_ascent_exit_not_joined_to_transit")

    transit_to = transit_run.get("to") or {}
    expected_to = taohuagou_source["source_geometry_lonlat"][0]
    actual_to = transit_to.get("lonlat") or []
    to_binding_mismatch = any(
        (
            transit_to.get("source_observation_id") != 6,
            transit_to.get("source_geometry_hash")
            != taohuagou_source.get("source_geometry_hash"),
            len(actual_to) != 2,
        )
    )
    to_coordinate_mismatch = (
        len(actual_to) == 2
        and max(abs(float(a) - float(b)) for a, b in zip(expected_to, actual_to))
        > 1e-6
    )
    if to_binding_mismatch or to_coordinate_mismatch:
        failures.append("transit_not_joined_to_huaketou_taohuagou")
    return tuple(failures)


def _single_source_cells(source: dict) -> list[dict]:
    athlete_count = source.get("athlete_count")
    effort_count = source.get("effort_count")
    star_count = source.get("star_count")
    if athlete_count is None or effort_count is None or star_count is None:
        raise ValueError("destination source heat facts are incomplete")
    if athlete_count <= 0:
        raise ValueError("destination source athlete count must be positive")
    repeat_proxy = max(effort_count - athlete_count, 0) / athlete_count
    intent_proxy = math.log1p(star_count)
    return [
        {
            "direction": "forward",
            "start_measure_m": 0.0,
            "end_measure_m": float(source["derived_distance_m"]),
            "support_state": "observed",
            "cohorts": ["xishan-20260813-v1"],
            "reach_union_lower_bound": athlete_count,
            "reach_union_upper_bound": athlete_count,
            "projection_quality_floor": 1.0,
            "repeat_proxy_range": {"min": repeat_proxy, "max": repeat_proxy},
            "star_proxy_range": {"min": intent_proxy, "max": intent_proxy},
        }
    ]


def _transit_component(transit_run: dict):
    direction_map = {
        "same_direction": "forward",
        "reverse_direction": "reverse",
    }
    postings = []
    for fact in transit_run.get("evidence_facts") or []:
        direction = direction_map.get(fact["direction_relation"])
        if fact.get("evidence_status") != "admitted_directional_evidence" or not direction:
            continue
        for interval in fact["transit_intervals_m"]:
            postings.append(
                EvidencePosting(
                    source_fact_id=f"observation:{fact['source_observation_id']}",
                    cohort="xishan-20260813-v1",
                    direction=direction,
                    start_measure_m=float(interval[0]),
                    end_measure_m=float(interval[1]),
                    athlete_count=fact.get("athlete_count"),
                    effort_count=fact.get("effort_count"),
                    star_count=fact.get("star_count"),
                    projection_quality=float(fact["source_coverage_ratio"]),
                )
            )
    distance_m = float(transit_run["provider_distance_m"])
    arrangement = arrange_directed_evidence(
        transit_run["transit_key"], distance_m, postings
    )
    return component_from_directed_cells(
        component_key="hengling-upper:huaketou-transit",
        distance_m=distance_m,
        climb_m=float(transit_run["elevation"]["climb_m"]),
        descent_m=float(transit_run["elevation"]["descent_m"]),
        cells=arrangement.to_dict()["cells"],
        direction="forward",
    )


def build_recommendation(
    mountain_module_run: dict,
    transit_run: dict,
    source_slice: dict,
) -> dict:
    observations = {
        int(item["source_observation_id"]): item
        for item in source_slice.get("observations") or []
    }
    if len(observations) != 81:
        raise ValueError("active road source slice must contain exact 81 observations")
    taohuagou = observations.get(6)
    if taohuagou is None or str(taohuagou["source_segment_id"]) != "22350861":
        raise ValueError("Huaketou-Taohuagou source fact is unavailable")
    hengling_source = observations.get(2)
    if hengling_source is None or str(hengling_source["source_segment_id"]) != "14942511":
        raise ValueError("Hengling full-ascent source fact is unavailable")
    ascent_block = next(
        block
        for block in mountain_module_run["route_blocks"]
        if block["block_key"].endswith(":full-ascent")
    )
    hard_failure_codes = _route_hard_failures(
        mountain_module_run,
        transit_run,
        source_slice,
        ascent_block,
        hengling_source,
        taohuagou,
    )
    if hard_failure_codes:
        raise ValueError(
            "route hard gate failed: " + ", ".join(hard_failure_codes)
        )
    hengling = component_from_directed_cells(
        component_key="hengling:full-ascent",
        distance_m=float(hengling_source["derived_distance_m"]),
        climb_m=float(hengling_source["climb_m"]),
        descent_m=float(hengling_source["descent_m"]),
        cells=mountain_module_run["analysis"]["directed_evidence"]["cells"],
        direction="forward",
    )
    transit = _transit_component(transit_run)
    taohuagou_component = component_from_directed_cells(
        component_key="huaketou:taohuagou",
        distance_m=float(taohuagou["derived_distance_m"]),
        climb_m=float(taohuagou["climb_m"]),
        descent_m=float(taohuagou["descent_m"]),
        cells=_single_source_cells(taohuagou),
        direction="forward",
    )
    heat_vector = compose_route_heat(
        "hengling-ascent-huaketou-taohuagou",
        (hengling, transit, taohuagou_component),
    )
    candidate = {
        "candidate_id": heat_vector["candidate_id"],
        "hard_gate_scope": "regional_destination_pattern_research",
        "hard_failure_codes": list(hard_failure_codes),
        "ordered_component_keys": [
            "hengling:full-ascent",
            "hengling-upper:huaketou-transit",
            "huaketou:taohuagou",
        ],
        "heat_vector": heat_vector,
    }
    ranking = rank_heat_candidates(
        [candidate], policy_version=POPULAR_RELIABLE_POLICY_VERSION
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ROUTE_HEAT_ALGORITHM_VERSION,
        "policy_version": POPULAR_RELIABLE_POLICY_VERSION,
        "input_bindings": {
            "active_source_slice_sha256": source_slice["slice_sha256"],
            "full_ascent_exit_port_sha256": ascent_block["traversal_ports"][0][
                "exit"
            ]["port_sha256"],
            "mountain_module_run_sha256": mountain_module_run["run_sha256"],
            "transit_result_sha256": transit_run["result_sha256"],
        },
        "candidate": candidate,
        "ranking": ranking,
        "recommendation_status": "recommended_research_pattern",
        "recommendation_reasons": [
            "横岭完整爬坡、完整过境道路、化客头—桃花沟三段已经顺序接通",
            "总距离和GLO爬升逐段只记一次，赛段重叠不会重复增加里程或爬升",
            "热度只使用当前骑行方向；中间无同向赛段证据的道路保持未观测",
            "横岭重叠赛段只提高区间热度证据密度与上下界，不相加成唯一骑手数",
        ],
        "provider_mode_boundary": (
            "Tencent driving/bicycling is treated as the same connectivity proposal "
            "for this research stage; it is not public access truth"
        ),
        "database_write_count": 0,
        "network_request_count": 0,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


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
    parser.add_argument("--mountain-module-run", type=Path, required=True)
    parser.add_argument("--transit-run", type=Path, required=True)
    parser.add_argument("--source-slice", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_recommendation(
        json.loads(args.mountain_module_run.read_text(encoding="utf-8")),
        json.loads(args.transit_run.read_text(encoding="utf-8")),
        json.loads(args.source_slice.read_text(encoding="utf-8")),
    )
    _write_json_atomic(args.output, result)
    print(json.dumps({
        "status": "complete",
        "manifest_sha256": result["manifest_sha256"],
        "heat_vector": result["candidate"]["heat_vector"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
