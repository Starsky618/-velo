#!/usr/bin/env python3
"""只读导出一个 manifest 指定的山区积木来源/GLO/热度事实。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = next(
    (
        parent
        for parent in (SCRIPT_PATH.parent, *SCRIPT_PATH.parents)
        if (parent / "app").is_dir()
    ),
    SCRIPT_PATH.parents[1],
)
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, text

from app.common.geometry_hash import strava_source_geometry_hash
from app.database import SessionLocal
from app.route_cognition.census_models import (
    SegmentElevationFact,
    SegmentSourceObservation,
)
from app.route_cognition.segment_elevation_facts import points_from_linestring_wkt


SCHEMA_VERSION = "mountain_module_source_slice_v1"


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


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _validated_output_path(spec: dict[str, Any], output: Path) -> Path:
    artifact_root = (REPO_ROOT / spec["artifact_location"]).resolve()
    outputs_root = (REPO_ROOT / "outputs").resolve()
    destination = output.resolve()
    if artifact_root != outputs_root and outputs_root not in artifact_root.parents:
        raise ValueError("manifest artifact_location must stay under repository outputs")
    if destination != artifact_root and artifact_root not in destination.parents:
        raise ValueError("source snapshot output must stay under manifest artifact_location")
    return destination


def build_slice(db: Any, *, spec: dict[str, Any]) -> dict[str, Any]:
    module_key = spec["module_key"]
    census_batch_id = spec["census_batch_id"]
    elevation_fact_batch_id = spec["elevation_fact_batch_id"]
    heat_snapshot_cohort = spec["heat_snapshot_cohort"]
    reference_observation_id = spec["reference_axis"]["source_observation_id"]
    observation_ids = tuple(spec["source_selection"]["observation_ids"])
    excluded_source_segment_ids = tuple(spec["excluded_source_segment_ids"])
    if spec["source_selection"]["observation_set_sha256"] != hashlib.sha256(
        "\n".join(sorted(str(value) for value in observation_ids)).encode("utf-8")
    ).hexdigest():
        raise ValueError("manifest observation set hash 漂移")
    rows = (
        db.query(
            SegmentSourceObservation,
            SegmentElevationFact,
            func.ST_AsText(SegmentSourceObservation.source_line).label(
                "source_line_wkt"
            ),
        )
        .join(
            SegmentElevationFact,
            (SegmentElevationFact.source_observation_id == SegmentSourceObservation.id)
            & (
                SegmentElevationFact.census_batch_id
                == SegmentSourceObservation.census_batch_id
            )
            & (
                SegmentElevationFact.source_segment_id
                == SegmentSourceObservation.source_segment_id
            ),
        )
        .filter(
            SegmentSourceObservation.census_batch_id == census_batch_id,
            SegmentSourceObservation.id.in_(observation_ids),
            SegmentElevationFact.fact_batch_id == elevation_fact_batch_id,
        )
        .order_by(SegmentSourceObservation.id.asc())
        .all()
    )
    if [row[0].id for row in rows] != list(observation_ids):
        raise ValueError("生产库没有返回 manifest 指定的 exact observation set")

    observations = []
    source_segment_ids = []
    for observation, fact, source_line_wkt in rows:
        if observation.geometry_status != "complete" or fact.fact_status != "complete":
            raise ValueError(f"observation {observation.id} 来源线或 GLO 事实不完整")
        points = points_from_linestring_wkt(source_line_wkt)
        geometry_hash = strava_source_geometry_hash(points)
        if (
            geometry_hash != fact.source_geometry_hash
            or len(points) != observation.geometry_point_count
            or len(points) != fact.source_point_count
            or fact.elevation_point_count != fact.source_point_count
        ):
            raise ValueError(f"observation {observation.id} 来源/GLO binding 漂移")
        source_segment_ids.append(observation.source_segment_id)
        observations.append(
            {
                "source_observation_id": observation.id,
                "source_segment_id": observation.source_segment_id,
                "source_name": observation.source_name,
                "source_geometry_hash": geometry_hash,
                "geometry_normalization_version": fact.geometry_normalization_version,
                "source_geometry_lonlat": points,
                "source_point_count": len(points),
                "source_fact_id": (
                    f"strava:{census_batch_id}:{observation.source_segment_id}:"
                    f"{geometry_hash}"
                ),
                "glo_fact_id": fact.id,
                "glo_algorithm_version": fact.algorithm_version,
                "derived_distance_m": fact.derived_distance_m,
                "climb_m": fact.climb_m,
                "descent_m": fact.descent_m,
                "elevation_snapshot": fact.elevation_snapshot_json,
                "elevation_profile": fact.elevation_profile_json,
                "athlete_count": observation.athlete_count,
                "effort_count": observation.effort_count,
                "star_count": observation.star_count,
            }
        )
    if set(source_segment_ids) & set(excluded_source_segment_ids):
        raise ValueError("山区 slice 混入 manifest 已排除赛段")
    reference = next(
        item
        for item in observations
        if item["source_observation_id"] == reference_observation_id
    )
    if (
        reference["source_segment_id"]
        != spec["reference_axis"]["source_segment_id"]
        or reference["source_geometry_hash"]
        != spec["reference_axis"]["source_geometry_hash"]
    ):
        raise ValueError("manifest reference axis source identity 漂移")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "module_key": module_key,
        "module_kind": "mountain_route_block_research",
        "census_batch_id": census_batch_id,
        "elevation_fact_batch_id": elevation_fact_batch_id,
        "heat_snapshot_cohort": heat_snapshot_cohort,
        "reference_observation_id": reference_observation_id,
        "observation_ids": list(observation_ids),
        "excluded_source_segment_ids": list(excluded_source_segment_ids),
        "boundary": spec["boundary"],
        "observations": observations,
        "database_write_count": 0,
        "network_request_count": 0,
    }
    payload["slice_sha256"] = _canonical_sha256(payload)
    return payload


def run(spec_path: Path, output: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    output = _validated_output_path(spec, output)
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        payload = build_slice(db, spec=spec)
        if db.new or db.dirty or db.deleted:
            raise RuntimeError("只读山区导出器产生了 ORM 写集合")
        _atomic_write(
            output,
            (
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )
        return {
            "status": "complete",
            "output": str(output),
            "slice_sha256": payload["slice_sha256"],
            "observation_count": len(payload["observations"]),
            "database_write_count": 0,
        }
    finally:
        db.rollback()
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.spec, args.output)
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
