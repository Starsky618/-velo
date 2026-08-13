#!/usr/bin/env python3
"""重放桃花沟 7 条来源线的单 carrier 投影与方向化 evidence bounds。

输入都是已冻结、可 hash 的 research artifact。脚本不连接数据库、不调用网络、
不写生产表；输出仍是 research shadow，不是正式 RoadCarrierGraph、ProjectionSet、
唯一骑手热度或路线推荐。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.route_cognition.carrier_projection import (
    CARRIER_PROJECTION_ALGORITHM_VERSION,
    CARRIER_PROJECTION_CONFIG_V1,
    DIRECTED_EVIDENCE_ALGORITHM_VERSION,
    RESEARCH_EVIDENCE_STATUS,
    EvidencePosting,
    arrange_directed_evidence,
    project_polyline_to_carrier,
)
from app.common.geometry_hash import strava_source_geometry_hash


SCHEMA_VERSION = "taohuagou_carrier_projection_run_v1"
DEFAULT_CARRIER = REPO_ROOT / "data/research/taohuagou_carrier_candidate_v1.json"
DEFAULT_SLICE = REPO_ROOT / "data/research/taohuagou_projection_slice_v1.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs/taohuagou-carrier-projection-v1"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _source_geometry_hash(points: list[list[float]]) -> str:
    """复现 census 的 7dp Strava source-line hash，不加载 DB/DEM 模块。"""

    return strava_source_geometry_hash(points)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, path)


def _load_inputs(carrier_path: Path, slice_path: Path) -> tuple[dict, dict]:
    carrier = json.loads(carrier_path.read_text(encoding="utf-8"))
    slice_input = json.loads(slice_path.read_text(encoding="utf-8"))
    if carrier["candidate_id"] != slice_input["carrier_candidate_id"]:
        raise ValueError("slice 与 carrier candidate identity 不一致")
    if carrier["status"] != "research_candidate_not_carrier_graph_truth":
        raise ValueError("carrier candidate 越过了 research 边界")
    if carrier["access_state"] != "unknown":
        raise ValueError("本切片只接受 access_state=unknown 的 research candidate")
    if len(slice_input["observations"]) != 7:
        raise ValueError("桃花沟 slice 必须是 exact 7 条 observation")
    observation_ids = [
        item["source_observation_id"] for item in slice_input["observations"]
    ]
    source_ids = [item["source_segment_id"] for item in slice_input["observations"]]
    fact_ids = [item["source_fact_id"] for item in slice_input["observations"]]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("slice 含重复 observation ID")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("slice 含重复 Strava ID")
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("slice 含重复 source fact ID")
    for item in slice_input["observations"]:
        if _source_geometry_hash(item["source_geometry_lonlat"]) != item[
            "source_geometry_hash"
        ]:
            raise ValueError(
                f"observation {item['source_observation_id']} geometry hash 漂移"
            )
    return carrier, slice_input


def build_run(carrier: dict, slice_input: dict) -> dict[str, Any]:
    projections = []
    postings = []
    accepted_statuses = {"research_projected"}
    for item in sorted(
        slice_input["observations"],
        key=lambda value: value["source_observation_id"],
    ):
        result = project_polyline_to_carrier(
            carrier["candidate_id"],
            carrier["geometry_lonlat"],
            item["source_observation_id"],
            item["source_geometry_lonlat"],
            config=CARRIER_PROJECTION_CONFIG_V1,
        )
        projection = {
            "source_observation_id": item["source_observation_id"],
            "source_segment_id": item["source_segment_id"],
            "source_name": item["source_name"],
            "source_geometry_hash": item["source_geometry_hash"],
            "source_fact_id": item["source_fact_id"],
            "result": result.to_dict(),
        }
        projection["record_sha256"] = _canonical_sha256(projection)
        projections.append(projection)
        if (
            result.status in accepted_statuses
            and result.direction in {"forward", "reverse"}
            and result.matched_runs
        ):
            for matched_run in result.matched_runs:
                start, end = matched_run.carrier_interval_m
                if end <= start:
                    continue
                postings.append(
                    EvidencePosting(
                        source_fact_id=item["source_fact_id"],
                        cohort=slice_input["heat_snapshot_cohort"],
                        direction=result.direction,
                        start_measure_m=start,
                        end_measure_m=end,
                        athlete_count=item["athlete_count"],
                        effort_count=item["effort_count"],
                        star_count=item["star_count"],
                        projection_quality=result.source_coverage_ratio,
                    )
                )
    arrangement = arrange_directed_evidence(
        carrier["candidate_id"],
        projections[0]["result"]["carrier_length_m"],
        postings,
    )
    status_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    for projection in projections:
        status = projection["result"]["status"]
        direction = projection["result"]["direction"]
        status_counts[status] = status_counts.get(status, 0) + 1
        direction_counts[direction] = direction_counts.get(direction, 0) + 1
    evidence_cells = arrangement.to_dict()["cells"]
    support_state_counts: dict[str, int] = {}
    for cell in evidence_cells:
        support_state = cell["support_state"]
        support_state_counts[support_state] = (
            support_state_counts.get(support_state, 0) + 1
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "evidence_status": RESEARCH_EVIDENCE_STATUS,
        "boundary": (
            "单 OSM way 的 research shadow；不证明道路身份、access、拓扑、"
            "正式 ProjectionSet、唯一骑手热度或路线可推荐。"
        ),
        "carrier_candidate_id": carrier["candidate_id"],
        "carrier_provider_identity": {
            "provider": carrier["provider"],
            "provider_object_id": carrier["provider_object_id"],
            "provider_object_version": carrier["provider_object_version"],
            "provider_object_timestamp": carrier["provider_object_timestamp"],
            "geometry_sha256": carrier["geometry_sha256"],
            "access_state": carrier["access_state"],
        },
        "census_batch_id": slice_input["census_batch_id"],
        "elevation_fact_batch_id": slice_input["elevation_fact_batch_id"],
        "heat_snapshot_cohort": slice_input["heat_snapshot_cohort"],
        "projection_algorithm_version": CARRIER_PROJECTION_ALGORITHM_VERSION,
        "projection_config": CARRIER_PROJECTION_CONFIG_V1.to_dict(),
        "projection_config_sha256": _canonical_sha256(
            CARRIER_PROJECTION_CONFIG_V1.to_dict()
        ),
        "evidence_algorithm_version": DIRECTED_EVIDENCE_ALGORITHM_VERSION,
        "parameter_promotion_status": "research_probe_unpromoted",
        "evidence_eligibility": "shadow_only_not_route_ranking_input",
        "observation_count": len(projections),
        "accepted_projection_count": sum(
            count
            for status, count in status_counts.items()
            if status in accepted_statuses
        ),
        "accepted_posting_count": len(postings),
        "abstained_projection_count": sum(
            count
            for status, count in status_counts.items()
            if status not in accepted_statuses
        ),
        "projection_status_counts": dict(sorted(status_counts.items())),
        "projection_direction_counts": dict(sorted(direction_counts.items())),
        "directed_evidence_support_state_counts": dict(
            sorted(support_state_counts.items())
        ),
        "projections": projections,
        "directed_evidence": arrangement.to_dict(),
        "database_write_count": 0,
        "network_request_count": 0,
    }
    payload["run_sha256"] = _canonical_sha256(payload)
    return payload


def write_artifacts(
    output_dir: Path,
    *,
    result: dict[str, Any],
    carrier_path: Path,
    slice_path: Path,
) -> dict[str, str]:
    projection_lines = b"".join(
        _canonical_bytes(item) + b"\n" for item in result["projections"]
    )
    evidence_lines = b"".join(
        _canonical_bytes(item) + b"\n"
        for item in result["directed_evidence"]["cells"]
    )
    manifest = {
        key: value
        for key, value in result.items()
        if key not in {"projections", "directed_evidence"}
    }
    manifest.update(
        {
            "carrier_input_sha256": _file_sha256(carrier_path),
            "slice_input_sha256": _file_sha256(slice_path),
            "projection_artifact_sha256": hashlib.sha256(
                projection_lines
            ).hexdigest(),
            "evidence_artifact_sha256": hashlib.sha256(evidence_lines).hexdigest(),
            "directed_evidence_result_sha256": result["directed_evidence"][
                "result_sha256"
            ],
            "directed_evidence_cell_count": len(
                result["directed_evidence"]["cells"]
            ),
        }
    )
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    generation_sha256 = _canonical_sha256(manifest)
    generations_dir = output_dir / "generations"
    generation_dir = generations_dir / generation_sha256
    output_dir.mkdir(parents=True, exist_ok=True)
    generations_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{generation_sha256}.", dir=generations_dir)
    )
    contents = {
        "manifest": manifest_bytes,
        "projections": projection_lines,
        "directed_evidence": evidence_lines,
    }
    filenames = {
        "manifest": "manifest.json",
        "projections": "projections.jsonl",
        "directed_evidence": "directed_evidence.jsonl",
    }
    try:
        for key in ("projections", "directed_evidence", "manifest"):
            _write_generation_file(temporary_dir / filenames[key], contents[key])
        if generation_dir.exists():
            for key, filename in filenames.items():
                if (generation_dir / filename).read_bytes() != contents[key]:
                    raise ValueError(
                        "同一 generation hash 已存在但文件内容不一致"
                    )
        else:
            os.replace(temporary_dir, generation_dir)
        current = {
            "schema_version": "taohuagou_artifact_pointer_v1",
            "generation_sha256": generation_sha256,
            "generation_path": f"generations/{generation_sha256}",
            "run_sha256": result["run_sha256"],
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "projection_artifact_sha256": manifest[
                "projection_artifact_sha256"
            ],
            "evidence_artifact_sha256": manifest["evidence_artifact_sha256"],
        }
        _atomic_write(
            output_dir / "current.json",
            json.dumps(
                current, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
    paths = {
        key: generation_dir / filename for key, filename in filenames.items()
    }
    paths["current"] = output_dir / "current.json"
    return {key: str(value) for key, value in paths.items()}


def _write_generation_file(path: Path, content: bytes) -> None:
    """只写未发布 generation；目录发布前失败不会污染 current。"""

    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carrier", type=Path, default=DEFAULT_CARRIER)
    parser.add_argument("--slice", type=Path, default=DEFAULT_SLICE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    carrier, slice_input = _load_inputs(args.carrier, args.slice)
    result = build_run(carrier, slice_input)
    paths = write_artifacts(
        args.output_dir,
        result=result,
        carrier_path=args.carrier,
        slice_path=args.slice,
    )
    return {**result, "artifact_paths": paths}


def main() -> int:
    try:
        result = run(_parse_args())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}:{exc}"},
                ensure_ascii=False,
            )
        )
        return 1
    summary = {
        key: result[key]
        for key in (
            "schema_version",
            "evidence_status",
            "observation_count",
            "accepted_projection_count",
            "abstained_projection_count",
            "projection_status_counts",
            "projection_direction_counts",
            "directed_evidence_support_state_counts",
            "parameter_promotion_status",
            "evidence_eligibility",
            "run_sha256",
            "database_write_count",
            "network_request_count",
            "artifact_paths",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
