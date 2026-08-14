#!/usr/bin/env python3
"""精确抓取两条已点名 Strava 完整赛段，不重跑区域 census。

只有 ``--apply`` 会发请求并原子写入；``--readback`` 只审计既有批次。任一详情或
完整 high-resolution latlng stream 失败时，整个批次不落库。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from geoalchemy2 import WKTElement  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.route_cognition.census_models import (  # noqa: E402
    SegmentCensusBatch,
    SegmentSourceObservation,
)
from app.route_cognition.strava_census import Bounds, fetch_segment_observation  # noqa: E402
from scripts.census_strava_segments import (  # noqa: E402
    CensusAttemptGovernor,
    ShortLivedStravaClient,
    _select_strava_user,
)


PROTOCOL_VERSION = "strava_exact_segment_ids_v1"
VISIBILITY_CONTEXT = "authorized_athlete_explicit_public_segments"


def _load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != "exact_strava_climb_ingest_spec_v1":
        raise ValueError("unsupported exact Strava climb ingest spec")
    segments = spec.get("segments") or []
    ids = [str(row.get("source_segment_id") or "") for row in segments]
    if len(ids) != 2 or len(ids) != len(set(ids)) or any(not value.isdigit() for value in ids):
        raise ValueError("exact ingest needs two unique numeric segment ids")
    bounds = spec.get("query_bounds") or {}
    values = [bounds.get(key) for key in ("south", "west", "north", "east")]
    if any(not isinstance(value, (int, float)) for value in values):
        raise ValueError("exact ingest query bounds are required")
    if not values[0] < values[2] or not values[1] < values[3]:
        raise ValueError("exact ingest query bounds are invalid")
    if not isinstance(spec.get("batch_id"), str) or len(spec["batch_id"]) > 64:
        raise ValueError("exact ingest batch id is invalid")
    return spec


def _bounds(spec: dict) -> Bounds:
    raw = spec["query_bounds"]
    return Bounds(raw["south"], raw["west"], raw["north"], raw["east"])


def _polygon(bounds: Bounds) -> tuple[tuple[float, float], ...]:
    return (
        (bounds.west, bounds.south),
        (bounds.east, bounds.south),
        (bounds.east, bounds.north),
        (bounds.west, bounds.north),
        (bounds.west, bounds.south),
    )


def _polygon_wkt(bounds: Bounds) -> str:
    return "POLYGON ((" + ", ".join(
        f"{lon:.7f} {lat:.7f}" for lon, lat in _polygon(bounds)
    ) + "))"


def _readback(batch_id: str) -> dict:
    db = SessionLocal()
    try:
        batch = db.get(SegmentCensusBatch, batch_id)
        if batch is None:
            return {"status": "not_found", "batch_id": batch_id}
        rows = (
            db.query(
                SegmentSourceObservation.id,
                SegmentSourceObservation.source_segment_id,
                SegmentSourceObservation.source_name,
                SegmentSourceObservation.geometry_point_count,
                SegmentSourceObservation.detail_status,
                SegmentSourceObservation.geometry_status,
            )
            .filter(SegmentSourceObservation.census_batch_id == batch_id)
            .order_by(SegmentSourceObservation.source_segment_id)
            .all()
        )
        return {
            "status": "committed_and_read_back",
            "batch_id": batch_id,
            "protocol_version": batch.protocol_version,
            "request_status": batch.request_status,
            "observation_count": len(rows),
            "observations": [
                {
                    "source_observation_id": row.id,
                    "source_segment_id": row.source_segment_id,
                    "source_name": row.source_name,
                    "geometry_point_count": row.geometry_point_count,
                    "detail_status": row.detail_status,
                    "geometry_status": row.geometry_status,
                }
                for row in rows
            ],
        }
    finally:
        db.close()


def _apply(spec: dict, *, user_id: int, interval_seconds: float) -> dict:
    bootstrap = SessionLocal()
    try:
        if bootstrap.get(SegmentCensusBatch, spec["batch_id"]) is not None:
            raise RuntimeError(f"batch_id already exists: {spec['batch_id']}")
        selected_user_id = _select_strava_user(bootstrap, user_id).id
    finally:
        bootstrap.close()

    governor = CensusAttemptGovernor(interval_seconds, max_requests=6)
    client = ShortLivedStravaClient(selected_user_id, governor)
    bounds = _bounds(spec)
    polygon = _polygon(bounds)
    started_at = datetime.now(timezone.utc)
    observations: list[dict] = []
    for item in spec["segments"]:
        segment_id = int(item["source_segment_id"])
        observation = fetch_segment_observation(
            client,
            segment_id,
            {
                "id": segment_id,
                "name": item["expected_name"],
                "activity_type": "Ride",
            },
            seen_passes={"exact_request": [str(segment_id)]},
            root_bounds=bounds,
            region_polygon=polygon,
            observed_at=datetime.now(timezone.utc),
        )
        if observation["detail_status"] != "complete":
            raise RuntimeError(f"Strava detail incomplete for {segment_id}")
        if observation["geometry_status"] != "complete":
            raise RuntimeError(f"Strava full stream incomplete for {segment_id}")
        if observation["region_membership"] not in {"inside", "crosses"}:
            raise RuntimeError(f"exact segment falls outside declared bounds: {segment_id}")
        observations.append(observation)
    finished_at = datetime.now(timezone.utc)
    if governor.failed_request_count or governor.blocked_request_count:
        raise RuntimeError("exact Strava request batch did not close cleanly")

    batch = SegmentCensusBatch(
        id=spec["batch_id"],
        region_key=spec["region_key"],
        region_version=spec["region_version"],
        source_platform="strava",
        activity_type="riding",
        protocol_version=PROTOCOL_VERSION,
        visibility_context=VISIBILITY_CONTEXT,
        region_definition_json={
            "mode": "exact_source_segment_ids",
            "source_segment_ids": [row["source_segment_id"] for row in spec["segments"]],
            "query_bounds": spec["query_bounds"],
            "exhaustive_region_census_claim": False,
            "request_boundary": spec["request_boundary"],
        },
        region_polygon=WKTElement(_polygon_wkt(bounds), srid=4326),
        root_south=bounds.south,
        root_west=bounds.west,
        root_north=bounds.north,
        root_east=bounds.east,
        max_depth=0,
        run_status="completed",
        # 本批只按已知 ID 精确抓取，未做区域枚举；不能借用“来源可见完整”的
        # census 语义。现有枚举状态闭集只能诚实记录为 indeterminate。
        enumeration_status="indeterminate",
        request_status="complete",
        snapshot_status="complete",
        detail_status="complete",
        geometry_status="complete",
        leaderboard_status="not_collected",
        planned_request_count=governor.planned_request_count,
        attempted_request_count=governor.attempted_request_count,
        succeeded_request_count=governor.succeeded_request_count,
        failed_request_count=governor.failed_request_count,
        blocked_request_count=governor.blocked_request_count,
        unique_segment_count=len(observations),
        included_segment_count=len(observations),
        outside_segment_count=0,
        unknown_membership_count=0,
        detail_complete_count=len(observations),
        geometry_complete_count=len(observations),
        leaderboard_complete_count=0,
        saturated_cell_count=0,
        error_count=0,
        pass_summaries_json=[
            {
                "mode": "exact_source_segment_ids",
                "requested_ids": [row["source_segment_id"] for row in spec["segments"]],
                "complete_count": len(observations),
            }
        ],
        pass_diff_json={"not_applicable": "exact ids; no two-pass enumeration"},
        raw_response_retained=False,
        started_at=started_at,
        finished_at=finished_at,
    )
    db = SessionLocal()
    try:
        if db.get(SegmentCensusBatch, spec["batch_id"]) is not None:
            raise RuntimeError(f"batch_id already exists: {spec['batch_id']}")
        db.add(batch)
        for item in observations:
            source_line_wkt = item.pop("source_line_wkt")
            db.add(
                SegmentSourceObservation(
                    census_batch_id=spec["batch_id"],
                    source_line=WKTElement(source_line_wkt, srid=4326),
                    **item,
                )
            )
        db.flush()
        count = (
            db.query(func.count(SegmentSourceObservation.id))
            .filter(SegmentSourceObservation.census_batch_id == spec["batch_id"])
            .scalar()
        )
        if count != len(observations):
            raise RuntimeError("exact Strava ingest transaction count mismatch")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return _readback(spec["batch_id"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        default=str(REPO_ROOT / "data/research/xishan_supplemental_exact_climb_ingest_v1.json"),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--readback", action="store_true")
    parser.add_argument("--strava-user-id", type=int)
    parser.add_argument("--request-interval-seconds", type=float, default=5.2)
    args = parser.parse_args(argv)
    if args.request_interval_seconds < 4.6:
        parser.error("--request-interval-seconds must be at least 4.6")
    spec = _load_spec(Path(args.spec))
    if args.readback:
        result = _readback(spec["batch_id"])
    else:
        if args.strava_user_id is None:
            parser.error("--apply requires --strava-user-id")
        result = _apply(
            spec,
            user_id=args.strava_user_id,
            interval_seconds=args.request_interval_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
