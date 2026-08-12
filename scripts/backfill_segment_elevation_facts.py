#!/usr/bin/env python3
"""为冻结的来源赛段逐条生成、落账并回读 GLO-30 基础事实。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from sqlalchemy import func


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.elevation.route_elevation import (
    ROUTE_ELEVATION_METHOD,
    build_route_elevation_result,
)
from app.route_cognition.census_models import (
    SegmentCensusBatch,
    SegmentElevationFact,
    SegmentElevationFactBatch,
    SegmentSourceObservation,
)
from app.route_cognition.segment_elevation_facts import (
    SOURCE_GEOMETRY_NORMALIZATION_VERSION,
    build_segment_elevation_fact,
    points_from_linestring_wkt,
    source_geometry_hash,
)
from app.parsing.geo_math import haversine


SCOPE = "inside_or_crosses"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="完整计算但整体不写库")
    mode.add_argument("--apply", action="store_true", help="原子写入事实批次并回读")
    mode.add_argument(
        "--readback-batch-id",
        help="不计算海拔，只回读并机械审计一个事实批次",
    )
    parser.add_argument("--census-batch-id")
    parser.add_argument("--batch-id")
    args = parser.parse_args(argv)
    if not args.readback_batch_id and not args.census_batch_id:
        parser.error("--dry-run/--apply 必须提供 --census-batch-id")
    for value, name in (
        (args.census_batch_id, "--census-batch-id"),
        (args.batch_id, "--batch-id"),
    ):
        if value and len(value) > 64:
            parser.error(f"{name} 最长 64 字符")
    return args


def _default_batch_id(census_batch_id: str) -> str:
    suffix = "-glo30-v1"
    return census_batch_id[: 64 - len(suffix)] + suffix


def _selected_source_rows(db, census_batch_id: str):
    return (
        db.query(
            SegmentSourceObservation,
            func.ST_AsText(SegmentSourceObservation.source_line).label("source_line_wkt"),
        )
        .filter(
            SegmentSourceObservation.census_batch_id == census_batch_id,
            SegmentSourceObservation.region_membership.in_(("inside", "crosses")),
        )
        .order_by(SegmentSourceObservation.source_segment_id.asc())
        .all()
    )


def _partition_source_rows(rows) -> tuple[list[tuple], list[dict]]:
    eligible: list[tuple] = []
    incomplete: list[dict] = []
    for observation, source_line_wkt in rows:
        reasons: list[str] = []
        if observation.detail_status != "complete":
            reasons.append(f"detail_status:{observation.detail_status}")
        if observation.geometry_status != "complete" or not source_line_wkt:
            reasons.append(f"geometry_status:{observation.geometry_status}")
        if not reasons:
            try:
                points = points_from_linestring_wkt(source_line_wkt)
                if len(points) != observation.geometry_point_count:
                    reasons.append("geometry_point_count_mismatch")
            except Exception as exc:
                reasons.append(f"geometry_parse:{type(exc).__name__}:{str(exc)[:120]}")
        if reasons:
            incomplete.append(
                {
                    "source_observation_id": observation.id,
                    "source_segment_id": observation.source_segment_id,
                    "reasons": reasons,
                }
            )
        else:
            eligible.append((observation, source_line_wkt))
    return eligible, incomplete


def _existing_input_batch(db, census_batch_id: str):
    return (
        db.query(SegmentElevationFactBatch)
        .filter(
            SegmentElevationFactBatch.census_batch_id == census_batch_id,
            SegmentElevationFactBatch.algorithm_version == ROUTE_ELEVATION_METHOD,
            SegmentElevationFactBatch.geometry_normalization_version
            == SOURCE_GEOMETRY_NORMALIZATION_VERSION,
            SegmentElevationFactBatch.scope == SCOPE,
        )
        .one_or_none()
    )


def compute_fact_batch(
    db,
    *,
    census_batch_id: str,
    batch_id: str,
    elevation_builder=build_route_elevation_result,
) -> tuple[SegmentElevationFactBatch, list[SegmentElevationFact]]:
    census = db.get(SegmentCensusBatch, census_batch_id)
    if census is None:
        raise LookupError(f"census batch 不存在：{census_batch_id}")
    rows = _selected_source_rows(db, census_batch_id)
    eligible, source_incomplete = _partition_source_rows(rows)
    started_at = datetime.now(timezone.utc)
    facts: list[SegmentElevationFact] = []
    for index, (observation, source_line_wkt) in enumerate(eligible, start=1):
        values = build_segment_elevation_fact(
            source_observation_id=observation.id,
            source_segment_id=observation.source_segment_id,
            source_line_wkt=source_line_wkt,
            source_point_count=observation.geometry_point_count,
            source_distance_m=observation.distance_m,
            elevation_builder=elevation_builder,
        )
        facts.append(
            SegmentElevationFact(
                fact_batch_id=batch_id,
                census_batch_id=census_batch_id,
                **values,
            )
        )
        if index == 1 or index % 10 == 0 or index == len(eligible):
            print(
                json.dumps(
                    {
                        "progress_segments": index,
                        "eligible_segments": len(eligible),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
    complete_count = sum(fact.fact_status == "complete" for fact in facts)
    failed_count = len(facts) - complete_count
    source_incomplete_count = len(source_incomplete)
    batch = SegmentElevationFactBatch(
        id=batch_id,
        census_batch_id=census_batch_id,
        scope=SCOPE,
        algorithm_version=ROUTE_ELEVATION_METHOD,
        geometry_normalization_version=SOURCE_GEOMETRY_NORMALIZATION_VERSION,
        run_status=(
            "completed"
            if source_incomplete_count == 0 and failed_count == 0
            else "completed_with_failures"
        ),
        input_observation_count=len(rows),
        eligible_geometry_count=len(eligible),
        source_incomplete_count=source_incomplete_count,
        source_incomplete_json=source_incomplete,
        complete_count=complete_count,
        failed_count=failed_count,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
    )
    return batch, facts


def _dry_run_result(batch: SegmentElevationFactBatch, facts: list[SegmentElevationFact]) -> dict:
    return {
        "database_status": "not_written_dry_run",
        "batch_id": batch.id,
        "census_batch_id": batch.census_batch_id,
        "run_status": batch.run_status,
        "algorithm_version": batch.algorithm_version,
        "geometry_normalization_version": batch.geometry_normalization_version,
        "input_observation_count": batch.input_observation_count,
        "eligible_geometry_count": batch.eligible_geometry_count,
        "source_incomplete_count": batch.source_incomplete_count,
        "complete_count": batch.complete_count,
        "failed_count": batch.failed_count,
        "distance_anomaly_count": sum(
            fact.quality_flags_json.get("source_distance_status") == "anomaly_over_5pct"
            for fact in facts
        ),
        "failed_source_segment_ids": [
            fact.source_segment_id for fact in facts if fact.fact_status == "failed"
        ],
    }


def _commit_fact_batch(db, batch, facts) -> dict | None:
    db.add(batch)
    db.add_all(facts)
    db.flush()
    stored_count = (
        db.query(func.count(SegmentElevationFact.id))
        .filter(SegmentElevationFact.fact_batch_id == batch.id)
        .scalar()
    )
    if stored_count != batch.eligible_geometry_count:
        raise RuntimeError("提交前事实数量与合格来源几何数量不一致")
    try:
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "database_status": "committed_outcome_unknown",
            "batch_id": batch.id,
            "reconcile_with": f"--readback-batch-id {batch.id}",
            "commit_error": f"{type(exc).__name__}:{str(exc)[:160]}",
        }
    return None


def _post_commit_result(db, batch_id: str) -> dict:
    try:
        result = readback_fact_batch(db, batch_id)
        if result.get("database_status") != "committed_and_read_back":
            raise RuntimeError("事实批次数据库回读与提交结果不一致")
        return result
    except Exception as exc:
        return {
            "database_status": "committed_outcome_unknown",
            "batch_id": batch_id,
            "reconcile_with": f"--readback-batch-id {batch_id}",
            "readback_error": f"{type(exc).__name__}:{str(exc)[:160]}",
        }


def readback_fact_batch(db, batch_id: str) -> dict:
    batch = db.get(SegmentElevationFactBatch, batch_id)
    if batch is None:
        raise LookupError(f"elevation fact batch 不存在：{batch_id}")
    census = db.get(SegmentCensusBatch, batch.census_batch_id)
    if census is None:
        raise RuntimeError("事实批次引用的 census batch 不存在")
    facts = (
        db.query(SegmentElevationFact)
        .filter(SegmentElevationFact.fact_batch_id == batch_id)
        .order_by(SegmentElevationFact.source_segment_id.asc())
        .all()
    )
    stored_count = len(facts)
    complete_count = sum(fact.fact_status == "complete" for fact in facts)
    failed_count = stored_count - complete_count
    distinct_observation_count = len({fact.source_observation_id for fact in facts})
    distinct_source_id_count = len({fact.source_segment_id for fact in facts})
    bad_hash_count = sum(
        len(fact.source_geometry_hash) != 64
        or any(char not in "0123456789abcdef" for char in fact.source_geometry_hash)
        for fact in facts
    )
    method_mismatch_count = sum(
        fact.algorithm_version != batch.algorithm_version
        or fact.geometry_normalization_version != batch.geometry_normalization_version
        or fact.method_metadata_json.get("method") != batch.algorithm_version
        for fact in facts
    )
    point_mismatch_count = sum(
        fact.fact_status == "complete"
        and fact.elevation_point_count != fact.source_point_count
        for fact in facts
    )
    source_rows = _selected_source_rows(db, batch.census_batch_id)
    source_audit, sources_by_observation_id = _audit_source_rows(source_rows)
    source_binding_mismatch_count = 0
    for fact in facts:
        source = sources_by_observation_id.get(fact.source_observation_id)
        if source is None:
            source_binding_mismatch_count += 1
            continue
        observation, points = source
        if (
            fact.source_segment_id != observation.source_segment_id
            or fact.source_point_count != observation.geometry_point_count
            or fact.source_geometry_hash != source_geometry_hash(points)
        ):
            source_binding_mismatch_count += 1
    distance_anomalies = [
        {
            "source_segment_id": fact.source_segment_id,
            "difference_pct": fact.source_distance_difference_pct,
        }
        for fact in facts
        if fact.quality_flags_json.get("source_distance_status") == "anomaly_over_5pct"
    ]
    accounting_ok = (
        stored_count == batch.eligible_geometry_count
        and complete_count == batch.complete_count
        and failed_count == batch.failed_count
        and complete_count + failed_count == batch.eligible_geometry_count
        and batch.eligible_geometry_count + batch.source_incomplete_count
        == batch.input_observation_count
        and distinct_observation_count == stored_count
        and distinct_source_id_count == stored_count
        and bad_hash_count == 0
        and method_mismatch_count == 0
        and point_mismatch_count == 0
        and source_binding_mismatch_count == 0
    )
    source_integrity_ok = all(
        source_audit[key] == 0
        for key in (
            "duplicate_source_id_count",
            "malformed_source_id_count",
            "id_url_mismatch_count",
            "missing_source_name_count",
            "detail_incomplete_count",
            "geometry_incomplete_count",
            "geometry_parse_error_count",
            "geometry_point_count_mismatch_count",
            "geometry_original_size_mismatch_count",
            "endpoint_over_1m_count",
            "required_detail_field_missing_count",
        )
    )
    single_segment_base_status = (
        "complete"
        if accounting_ok
        and source_integrity_ok
        and batch.source_incomplete_count == 0
        and failed_count == 0
        and complete_count == batch.input_observation_count
        else "incomplete"
    )
    return {
        "database_status": (
            "committed_and_read_back" if accounting_ok else "readback_mismatch"
        ),
        "batch_id": batch.id,
        "census_batch_id": batch.census_batch_id,
        "run_status": batch.run_status,
        "scope": batch.scope,
        "algorithm_version": batch.algorithm_version,
        "geometry_normalization_version": batch.geometry_normalization_version,
        "input_observation_count": batch.input_observation_count,
        "eligible_geometry_count": batch.eligible_geometry_count,
        "source_incomplete_count": batch.source_incomplete_count,
        "stored_fact_count": stored_count,
        "complete_count": complete_count,
        "failed_count": failed_count,
        "distinct_observation_count": distinct_observation_count,
        "distinct_source_id_count": distinct_source_id_count,
        "bad_hash_count": bad_hash_count,
        "method_mismatch_count": method_mismatch_count,
        "point_mismatch_count": point_mismatch_count,
        "source_binding_mismatch_count": source_binding_mismatch_count,
        "distance_anomaly_count": len(distance_anomalies),
        "distance_anomalies": distance_anomalies,
        "failed_source_segment_ids": [
            fact.source_segment_id for fact in facts if fact.fact_status == "failed"
        ],
        "source_incomplete": batch.source_incomplete_json,
        "source_audit": source_audit,
        "single_segment_base_status": single_segment_base_status,
        "relation_input_ready": single_segment_base_status == "complete",
        "census_enumeration_status": census.enumeration_status,
        "leaderboard_status": census.leaderboard_status,
        "raw_replay_status": (
            "retained" if census.raw_response_retained else "unavailable_by_collection_policy"
        ),
    }


def _audit_source_rows(rows) -> tuple[dict, dict[int, tuple]]:
    source_ids = [observation.source_segment_id for observation, _wkt in rows]
    audit = {
        "row_count": len(rows),
        "distinct_source_id_count": len(set(source_ids)),
        "duplicate_source_id_count": len(source_ids) - len(set(source_ids)),
        "malformed_source_id_count": 0,
        "id_url_mismatch_count": 0,
        "missing_source_name_count": 0,
        "detail_incomplete_count": 0,
        "geometry_incomplete_count": 0,
        "geometry_parse_error_count": 0,
        "geometry_point_count_mismatch_count": 0,
        "geometry_original_size_mismatch_count": 0,
        "endpoint_over_1m_count": 0,
        "required_detail_field_missing_count": 0,
        "city_missing_count": 0,
        "qom_missing_count": 0,
        "distance_over_5pct_count": 0,
    }
    sources_by_observation_id: dict[int, tuple] = {}
    required_fields = (
        "source_created_at",
        "source_updated_at",
        "state",
        "country",
        "is_private",
        "is_hazardous",
        "climb_category",
        "distance_m",
        "average_gradient_pct",
        "maximum_gradient_pct",
        "elevation_high_m",
        "elevation_low_m",
        "athlete_count",
        "effort_count",
        "star_count",
        "kom_time_s",
        "overall_best_time_s",
    )
    for observation, source_line_wkt in rows:
        if not observation.source_segment_id.isdigit():
            audit["malformed_source_id_count"] += 1
        if observation.source_url != (
            f"https://www.strava.com/segments/{observation.source_segment_id}"
        ):
            audit["id_url_mismatch_count"] += 1
        if not observation.source_name.strip():
            audit["missing_source_name_count"] += 1
        if observation.detail_status != "complete":
            audit["detail_incomplete_count"] += 1
        if observation.geometry_status != "complete" or not source_line_wkt:
            audit["geometry_incomplete_count"] += 1
        if any(getattr(observation, field) is None for field in required_fields):
            audit["required_detail_field_missing_count"] += 1
        if observation.city is None:
            audit["city_missing_count"] += 1
        if observation.qom_time_s is None:
            audit["qom_missing_count"] += 1
        if observation.geometry_status != "complete" or not source_line_wkt:
            continue
        try:
            points = points_from_linestring_wkt(source_line_wkt)
        except Exception:
            audit["geometry_parse_error_count"] += 1
            continue
        sources_by_observation_id[observation.id] = (observation, points)
        if len(points) != observation.geometry_point_count:
            audit["geometry_point_count_mismatch_count"] += 1
        if observation.geometry_original_size != observation.geometry_point_count:
            audit["geometry_original_size_mismatch_count"] += 1
        if None not in (
            observation.start_lat,
            observation.start_lon,
            observation.end_lat,
            observation.end_lon,
        ):
            start_error = haversine(
                observation.start_lat,
                observation.start_lon,
                points[0][1],
                points[0][0],
            )
            end_error = haversine(
                observation.end_lat,
                observation.end_lon,
                points[-1][1],
                points[-1][0],
            )
            if max(start_error, end_error) > 1.0:
                audit["endpoint_over_1m_count"] += 1
        if observation.distance_m and observation.distance_m > 0:
            geometry_distance = sum(
                haversine(previous[1], previous[0], current[1], current[0])
                for previous, current in zip(points, points[1:])
            )
            difference_pct = (
                abs(geometry_distance - observation.distance_m)
                / observation.distance_m
                * 100
            )
            if difference_pct > 5.0:
                audit["distance_over_5pct_count"] += 1
    return audit, sources_by_observation_id


def run(args: argparse.Namespace) -> dict:
    db = SessionLocal()
    try:
        if args.readback_batch_id:
            return readback_fact_batch(db, args.readback_batch_id)
        existing = _existing_input_batch(db, args.census_batch_id)
        if existing is not None:
            if args.batch_id and args.batch_id != existing.id:
                raise RuntimeError(
                    "相同 census/hash/algorithm 已有不可变事实批次：" + existing.id
                )
            return readback_fact_batch(db, existing.id)
        batch_id = args.batch_id or _default_batch_id(args.census_batch_id)
        if db.get(SegmentElevationFactBatch, batch_id) is not None:
            raise RuntimeError(f"batch_id 已存在但输入版本不一致：{batch_id}")
        batch, facts = compute_fact_batch(
            db,
            census_batch_id=args.census_batch_id,
            batch_id=batch_id,
        )
        if args.dry_run:
            db.rollback()
            return _dry_run_result(batch, facts)
        outcome = _commit_fact_batch(db, batch, facts)
        return outcome or _post_commit_result(db, batch.id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    args = _parse_args()
    try:
        result = run(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}:{str(exc)[:240]}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("database_status") in {
        "committed_outcome_unknown",
        "readback_mismatch",
    }:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
