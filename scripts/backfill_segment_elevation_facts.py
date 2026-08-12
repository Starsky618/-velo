#!/usr/bin/env python3
"""为冻结的来源赛段逐条生成、落账并回读 GLO-30 基础事实。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from sqlalchemy import func, text


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
    SOURCE_DISTANCE_ANOMALY_THRESHOLD_PCT,
    SOURCE_GEOMETRY_NORMALIZATION_VERSION,
    build_segment_elevation_fact,
    source_geometry_hash,
    validated_source_geometry,
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
    parser.add_argument(
        "--retry-failed-batch-id",
        help="仅重试一个已落账且只有 GLO/算法失败的不可变 attempt",
    )
    args = parser.parse_args(argv)
    if not args.readback_batch_id and not args.census_batch_id:
        parser.error("--dry-run/--apply 必须提供 --census-batch-id")
    for value, name in (
        (args.census_batch_id, "--census-batch-id"),
        (args.batch_id, "--batch-id"),
        (args.retry_failed_batch_id, "--retry-failed-batch-id"),
    ):
        if value and len(value) > 64:
            parser.error(f"{name} 最长 64 字符")
    if args.retry_failed_batch_id and args.batch_id:
        parser.error("重试会创建新 attempt，不能同时指定 --batch-id")
    return args


def _default_batch_id(census_batch_id: str, attempt_number: int) -> str:
    suffix = f"-glo30-v1-a{attempt_number}"
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


def _freeze_source_rows(rows) -> list[tuple]:
    """把 ORM 行复制成 DTO，避免真实 GLO 计算期间占用数据库事务。"""
    column_names = [
        column.name
        for column in SegmentSourceObservation.__table__.columns
        if column.name != "source_line"
    ]
    return [
        (
            SimpleNamespace(
                **{name: getattr(observation, name) for name in column_names}
            ),
            source_line_wkt,
        )
        for observation, source_line_wkt in rows
    ]


def _observation_set_hash(rows) -> str:
    payload = [
        [observation.id, observation.source_segment_id]
        for observation, _source_line_wkt in rows
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _input_lock_key(census_batch_id: str) -> str:
    return "|".join(
        (
            "segment_elevation_facts",
            census_batch_id,
            ROUTE_ELEVATION_METHOD,
            SOURCE_GEOMETRY_NORMALIZATION_VERSION,
            SCOPE,
        )
    )


def _audit_source_incomplete_items(
    items,
    source_ids_by_observation_id: dict[int, str],
) -> tuple[set[int], list[str]]:
    if not isinstance(items, list):
        return set(), ["source_incomplete_json_not_list"]
    observation_ids: set[int] = set()
    errors: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item_{index}:not_object")
            continue
        observation_id = item.get("source_observation_id")
        source_segment_id = item.get("source_segment_id")
        reasons = item.get("reasons")
        if not isinstance(observation_id, int):
            errors.append(f"item_{index}:invalid_observation_id")
            continue
        if observation_id in observation_ids:
            errors.append(f"item_{index}:duplicate_observation_id")
        observation_ids.add(observation_id)
        if source_ids_by_observation_id.get(observation_id) != source_segment_id:
            errors.append(f"item_{index}:source_segment_id_mismatch")
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(
                not isinstance(reason, str)
                or not reason.strip()
                or len(reason) > 300
                for reason in reasons
            )
        ):
            errors.append(f"item_{index}:invalid_reasons")
    return observation_ids, errors


def _partition_source_rows(rows) -> tuple[list[tuple], list[dict]]:
    eligible: list[tuple] = []
    incomplete: list[dict] = []
    for observation, source_line_wkt in rows:
        reasons: list[str] = []
        if observation.geometry_status != "complete" or not source_line_wkt:
            reasons.append(f"geometry_status:{observation.geometry_status}")
        if not reasons:
            try:
                validated_source_geometry(
                    source_line_wkt,
                    observation.geometry_point_count,
                )
            except Exception as exc:
                reasons.append(
                    f"geometry_invalid:{type(exc).__name__}:{str(exc)[:120]}"
                )
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


def _input_batches(db, census_batch_id: str) -> list[SegmentElevationFactBatch]:
    return (
        db.query(SegmentElevationFactBatch)
        .filter(
            SegmentElevationFactBatch.census_batch_id == census_batch_id,
            SegmentElevationFactBatch.algorithm_version == ROUTE_ELEVATION_METHOD,
            SegmentElevationFactBatch.geometry_normalization_version
            == SOURCE_GEOMETRY_NORMALIZATION_VERSION,
            SegmentElevationFactBatch.scope == SCOPE,
        )
        .order_by(SegmentElevationFactBatch.attempt_number.desc())
        .all()
    )


def compute_fact_batch(
    db,
    *,
    census_batch_id: str,
    batch_id: str,
    attempt_number: int = 1,
    elevation_builder=build_route_elevation_result,
) -> tuple[SegmentElevationFactBatch, list[SegmentElevationFact]]:
    census = db.get(SegmentCensusBatch, census_batch_id)
    if census is None:
        raise LookupError(f"census batch 不存在：{census_batch_id}")
    rows = _selected_source_rows(db, census_batch_id)
    if len(rows) != census.included_segment_count or not rows:
        raise RuntimeError(
            "来源集合与 census included 账不一致或为空："
            f"selected={len(rows)} included={census.included_segment_count}"
        )
    input_observation_set_hash = _observation_set_hash(rows)
    rows = _freeze_source_rows(rows)
    # 后面的真实 GLO-30 可能很慢；来源观测 append-only，提交前再核 exact set。
    db.rollback()
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
        attempt_number=attempt_number,
        input_observation_set_hash=input_observation_set_hash,
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
        "attempt_number": batch.attempt_number,
        "input_observation_set_hash": batch.input_observation_set_hash,
        "input_source_segment_ids": sorted(
            [fact.source_segment_id for fact in facts]
            + [
                item["source_segment_id"]
                for item in batch.source_incomplete_json
            ]
        ),
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
        "complete_source_segment_ids": [
            fact.source_segment_id for fact in facts if fact.fact_status == "complete"
        ],
        "source_incomplete": batch.source_incomplete_json,
        "fact_input_bindings": [
            {
                "source_observation_id": fact.source_observation_id,
                "source_segment_id": fact.source_segment_id,
                "source_geometry_hash": fact.source_geometry_hash,
                "geometry_normalization_version": fact.geometry_normalization_version,
                "algorithm_version": fact.algorithm_version,
                "fact_status": fact.fact_status,
                "failure": fact.failure_json,
            }
            for fact in facts
        ],
    }


def _commit_fact_batch(db, batch, facts) -> dict | None:
    census = db.get(SegmentCensusBatch, batch.census_batch_id)
    current_rows = _selected_source_rows(db, batch.census_batch_id)
    current_ids = {observation.id for observation, _wkt in current_rows}
    current_source_ids = {
        observation.id: observation.source_segment_id
        for observation, _wkt in current_rows
    }
    fact_ids = {fact.source_observation_id for fact in facts}
    incomplete_items = batch.source_incomplete_json
    incomplete_ids, incomplete_errors = _audit_source_incomplete_items(
        incomplete_items,
        current_source_ids,
    )
    if (
        census is None
        or len(current_rows) != census.included_segment_count
        or not current_rows
        or _observation_set_hash(current_rows) != batch.input_observation_set_hash
        or len(fact_ids) != len(facts)
        or incomplete_errors
        or bool(fact_ids & incomplete_ids)
        or fact_ids | incomplete_ids != current_ids
    ):
        raise RuntimeError("提交前来源 exact-set 与事实/不完整账不一致")
    db.add(batch)
    # 复合外键同时绑定 batch/census/algorithm/normalization。显式先落父行，
    # 仍留在同一事务内，避免 SQLAlchemy 在没有 ORM relationship 时先 flush facts。
    db.flush()
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
    selected_observation_ids = {
        observation.id for observation, _source_line_wkt in source_rows
    }
    selected_source_ids = {
        observation.id: observation.source_segment_id
        for observation, _source_line_wkt in source_rows
    }
    fact_observation_ids = {fact.source_observation_id for fact in facts}
    incomplete_items = batch.source_incomplete_json
    incomplete_observation_ids, incomplete_binding_errors = (
        _audit_source_incomplete_items(
            incomplete_items,
            selected_source_ids,
        )
    )
    exact_set_ok = (
        bool(source_rows)
        and len(source_rows) == census.included_segment_count
        and len(source_rows) == batch.input_observation_count
        and _observation_set_hash(source_rows) == batch.input_observation_set_hash
        and not incomplete_binding_errors
        and len(incomplete_items) == batch.source_incomplete_count
        and not fact_observation_ids & incomplete_observation_ids
        and fact_observation_ids | incomplete_observation_ids
        == selected_observation_ids
    )
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
        exact_set_ok
        and stored_count == batch.eligible_geometry_count
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
    source_identity_integrity_ok = all(
        source_audit[key] == 0
        for key in (
            "duplicate_source_id_count",
            "malformed_source_id_count",
            "id_url_mismatch_count",
            "missing_source_name_count",
            "required_source_field_missing_count",
        )
    )
    source_geometry_integrity_ok = all(
        source_audit[key] == 0
        for key in (
            "geometry_incomplete_count",
            "geometry_parse_error_count",
            "geometry_point_count_mismatch_count",
            "geometry_original_size_mismatch_count",
            "endpoint_over_1m_count",
        )
    )
    elevation_fact_batch_status = (
        "complete"
        if accounting_ok
        and source_geometry_integrity_ok
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
        "attempt_number": batch.attempt_number,
        "input_observation_set_hash": batch.input_observation_set_hash,
        "exact_observation_set_match": exact_set_ok,
        "source_incomplete_binding_errors": incomplete_binding_errors,
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
        "input_source_segment_ids": sorted(
            observation.source_segment_id
            for observation, _source_line_wkt in source_rows
        ),
        "source_incomplete": batch.source_incomplete_json,
        "source_audit": source_audit,
        "source_identity_integrity_status": (
            "complete" if source_identity_integrity_ok else "incomplete"
        ),
        "source_geometry_integrity_status": (
            "complete" if source_geometry_integrity_ok else "incomplete"
        ),
        "elevation_fact_batch_status": elevation_fact_batch_status,
        "single_segment_foundation_status": "not_certified_axes_reported_separately",
        "relation_analysis_status": "not_started_no_relation_gate_in_this_task",
        "census_enumeration_status": census.enumeration_status,
        "census_request_status": census.request_status,
        "census_snapshot_status": census.snapshot_status,
        "census_detail_status": census.detail_status,
        "census_geometry_status": census.geometry_status,
        "leaderboard_status": census.leaderboard_status,
        "raw_response_retained": census.raw_response_retained,
        "raw_replay_status": (
            "retention_declared_but_payload_location_not_in_census_schema"
            if census.raw_response_retained
            else "unavailable_original_response_not_retained"
        ),
        "raw_retention_contract_status": "unknown_missing_census_metadata",
        "raw_normalizer_version": None,
        "raw_retained_fields": None,
        "raw_discarded_fields": None,
        "raw_replay_boundary": "只能审计已保存的规范化字段，不能重建原始 Strava 响应",
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
        "required_source_field_missing_count": 0,
        "city_missing_count": 0,
        "qom_missing_count": 0,
        "distance_over_5pct_count": 0,
        "nullable_detail_field_null_counts": {},
    }
    sources_by_observation_id: dict[int, tuple] = {}
    required_source_fields = (
        "source_platform",
        "source_segment_id",
        "source_url",
        "source_name",
        "observed_at",
        "activity_type",
        "query_bounds_relation",
        "region_membership",
    )
    nullable_detail_fields = (
        "source_created_at", "source_updated_at", "city", "state", "country",
        "is_private", "is_hazardous", "climb_category",
        "distance_m",
        "average_gradient_pct",
        "maximum_gradient_pct",
        "elevation_gain_m",
        "elevation_high_m",
        "elevation_low_m",
        "athlete_count",
        "effort_count",
        "star_count",
        "kom_time_s",
        "overall_best_time_s",
    )
    audit["nullable_detail_field_null_counts"] = {
        field: 0 for field in nullable_detail_fields
    }
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
        if any(
            getattr(observation, field) is None
            or (isinstance(getattr(observation, field), str)
                and not getattr(observation, field).strip())
            for field in required_source_fields
        ):
            audit["required_source_field_missing_count"] += 1
        for field in nullable_detail_fields:
            if getattr(observation, field) is None:
                audit["nullable_detail_field_null_counts"][field] += 1
        if observation.city is None:
            audit["city_missing_count"] += 1
        if observation.qom_time_s is None:
            audit["qom_missing_count"] += 1
        if observation.geometry_status != "complete" or not source_line_wkt:
            continue
        try:
            points, _geometry_hash, geometry_distance = validated_source_geometry(
                source_line_wkt,
                observation.geometry_point_count,
            )
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
            difference_pct = (
                abs(geometry_distance - observation.distance_m)
                / observation.distance_m
                * 100
            )
            if difference_pct > SOURCE_DISTANCE_ANOMALY_THRESHOLD_PCT:
                audit["distance_over_5pct_count"] += 1
    return audit, sources_by_observation_id


def run(args: argparse.Namespace) -> dict:
    db = SessionLocal()
    lock_connection = None
    lock_key = None
    try:
        if args.readback_batch_id:
            return readback_fact_batch(db, args.readback_batch_id)
        lock_key = _input_lock_key(args.census_batch_id)
        lock_connection = db.get_bind().connect()
        lock_connection.execute(
            text("SELECT pg_advisory_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        if args.batch_id:
            existing_by_id = db.get(SegmentElevationFactBatch, args.batch_id)
            if existing_by_id is not None:
                identity = (
                    existing_by_id.census_batch_id,
                    existing_by_id.algorithm_version,
                    existing_by_id.geometry_normalization_version,
                    existing_by_id.scope,
                )
                expected_identity = (
                    args.census_batch_id,
                    ROUTE_ELEVATION_METHOD,
                    SOURCE_GEOMETRY_NORMALIZATION_VERSION,
                    SCOPE,
                )
                if identity != expected_identity:
                    raise RuntimeError("batch_id 已被另一个输入身份使用")
                return readback_fact_batch(db, existing_by_id.id)
        attempts = _input_batches(db, args.census_batch_id)
        latest_incomplete_result = None
        for existing in attempts:
            result = readback_fact_batch(db, existing.id)
            if result.get("database_status") != "committed_and_read_back":
                return result
            if result.get("elevation_fact_batch_status") == "complete":
                return result
            if latest_incomplete_result is None:
                latest_incomplete_result = result
        if latest_incomplete_result is not None:
            latest_id = latest_incomplete_result["batch_id"]
            if latest_incomplete_result["source_incomplete_count"] > 0:
                latest_incomplete_result["retry_status"] = (
                    "not_retryable_requires_new_census_source_geometry"
                )
                return latest_incomplete_result
            if latest_incomplete_result["failed_count"] <= 0:
                latest_incomplete_result["retry_status"] = (
                    "not_retryable_requires_source_or_contract_repair"
                )
                return latest_incomplete_result
            if args.retry_failed_batch_id != latest_id:
                latest_incomplete_result["retry_status"] = "explicit_retry_required"
                latest_incomplete_result["retry_with"] = (
                    f"--retry-failed-batch-id {latest_id}"
                )
                return latest_incomplete_result
        elif args.retry_failed_batch_id:
            raise RuntimeError("没有可重试的 GLO/算法失败 attempt")
        attempt_number = max(
            (batch.attempt_number for batch in attempts),
            default=0,
        ) + 1
        batch_id = args.batch_id or _default_batch_id(
            args.census_batch_id,
            attempt_number,
        )
        if db.get(SegmentElevationFactBatch, batch_id) is not None:
            raise RuntimeError(f"batch_id 已存在但输入版本不一致：{batch_id}")
        batch, facts = compute_fact_batch(
            db,
            census_batch_id=args.census_batch_id,
            batch_id=batch_id,
            attempt_number=attempt_number,
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
        if lock_connection is not None and lock_key is not None:
            try:
                lock_connection.execute(
                    text(
                        "SELECT pg_advisory_unlock("
                        "hashtextextended(:lock_key, 0))"
                    ),
                    {"lock_key": lock_key},
                )
            except Exception:
                # 连接关闭也会释放 session advisory lock；不能让清理异常覆盖主结果。
                pass
            finally:
                lock_connection.close()
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
    if (
        result.get("run_status") == "completed_with_failures"
        or result.get("elevation_fact_batch_status") == "incomplete"
    ):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
