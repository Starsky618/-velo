#!/usr/bin/env python3
"""只读构建西山 81 条来源线的完整 raw-geometry pair oracle。

这是关系算法的阶段 0 研究纵切：所有 3,240 对都会实际计算。输出是原始
完整折线上的可重放 witness 与待标注候选，不是道路图、拓扑或生产关系真值。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func

from app.database import SessionLocal
from app.route_cognition.census_models import (
    SegmentElevationFact,
    SegmentElevationFactBatch,
    SegmentSourceObservation,
)
from app.route_cognition.models import JudgmentRun
from app.route_cognition.segment_elevation_facts import (
    source_geometry_hash,
    validated_source_geometry,
)
from app.route_cognition.spatial_relations import (
    RAW_SPATIAL_RELATION_ALGORITHM_VERSION,
    RAW_SPATIAL_RELATION_CONFIG_V1,
    SpatialRelationConfig,
    analyze_spatial_relation,
)
from app.parsing.geo_math import haversine
from scripts.audit_xishan_segment_alignment import (
    DEFAULT_LEGACY,
    DEFAULT_PROFILE,
    audit_snapshot,
    canonical_sha256,
    load_inputs,
)
from scripts.backfill_segment_elevation_facts import readback_fact_batch


SCHEMA_VERSION = "xishan_raw_relation_oracle_v1"
CANDIDATE_INDEX_VERSION = "raw_subcurve_bbox_candidate_v1"
SOURCE_EXACT_HASH_VERSION = "source_line_lonlat_7dp_sha256_v1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs/xishan-relation-oracle-v1"


# 这些只是用于生成标注候选和观察真实分布的保守 probe 参数，不是已晋级的
# 道路关系阈值。正式阈值必须由人工 gold 和 corridor holdout 校准后换版本。
RESEARCH_PROBE_CONFIG = RAW_SPATIAL_RELATION_CONFIG_V1


@dataclass(frozen=True)
class RelationObservationInput:
    source_observation_id: int
    source_segment_id: str
    source_name: str
    source_geometry_hash: str
    geometry_normalization_version: str
    geometry_resolution: str
    point_count: int
    points: tuple[tuple[float, float], ...]
    source_length_m: float
    source_exact_directed_hash: str
    source_exact_undirected_hash: str
    glo_fact_id: int
    glo_fact_batch_id: str
    glo_fact_status: str
    glo_algorithm_version: str
    glo_climb_m: float
    glo_descent_m: float
    athlete_count: int | None
    effort_count: int | None
    star_count: int | None

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("points")
        return value


def _sha256_lines(values: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _source_exact_hashes(
    points: tuple[tuple[float, float], ...],
) -> tuple[str, str]:
    as_lists = [[lon, lat] for lon, lat in points]
    directed = source_geometry_hash(as_lists)
    reversed_hash = source_geometry_hash(list(reversed(as_lists)))
    return directed, min(directed, reversed_hash)


def _expanded_bbox(
    points: list[tuple[float, float]],
    expansion_m: float,
) -> tuple[float, float, float, float]:
    mean_lat = sum(lat for _, lat in points) / len(points)
    lat_delta = expansion_m / 111_320.0
    lon_scale = max(0.1, math.cos(math.radians(mean_lat)))
    lon_delta = expansion_m / (111_320.0 * lon_scale)
    return (
        min(lon for lon, _ in points) - lon_delta,
        min(lat for _, lat in points) - lat_delta,
        max(lon for lon, _ in points) + lon_delta,
        max(lat for _, lat in points) + lat_delta,
    )


def _subcurve_bboxes(
    points: tuple[tuple[float, float], ...],
    *,
    chunk_length_m: float,
    expansion_m: float,
) -> list[tuple[float, float, float, float]]:
    chunks: list[list[tuple[float, float]]] = []
    current = [points[0]]
    current_length = 0.0
    for point in points[1:]:
        previous = current[-1]
        segment_length = haversine(previous[1], previous[0], point[1], point[0])
        if current_length > 0 and current_length + segment_length > chunk_length_m:
            chunks.append(current)
            current = [previous]
            current_length = 0.0
        current.append(point)
        current_length += segment_length
    chunks.append(current)
    return [_expanded_bbox(chunk, expansion_m) for chunk in chunks]


def _bbox_intersects(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] < right[0]
        or right[2] < left[0]
        or left[3] < right[1]
        or right[3] < left[1]
    )


def generate_candidate_pairs(
    observations: list[RelationObservationInput],
    *,
    expansion_m: float,
    chunk_length_m: float = 500.0,
) -> set[tuple[int, int]]:
    """只做召回的 subcurve bbox 索引；不参与关系判真。"""
    boxes = {
        item.source_observation_id: _subcurve_bboxes(
            item.points,
            chunk_length_m=chunk_length_m,
            expansion_m=expansion_m,
        )
        for item in observations
    }
    candidates: set[tuple[int, int]] = set()
    ordered = sorted(observations, key=lambda item: item.source_observation_id)
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if any(
                _bbox_intersects(left_box, right_box)
                for left_box in boxes[left.source_observation_id]
                for right_box in boxes[right.source_observation_id]
            ):
                candidates.add((left.source_observation_id, right.source_observation_id))
    return candidates


def build_relation_oracle(
    observations: list[RelationObservationInput],
    *,
    config: SpatialRelationConfig,
    run_identity: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ordered = sorted(observations, key=lambda item: item.source_observation_id)
    observation_ids = [item.source_observation_id for item in ordered]
    source_ids = [item.source_segment_id for item in ordered]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("关系输入包含重复 observation ID")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("关系输入包含重复 Strava ID")
    if any(len(item.points) < 2 for item in ordered):
        raise ValueError("关系输入包含无效来源线")

    expected_pair_count = len(ordered) * (len(ordered) - 1) // 2
    candidates = generate_candidate_pairs(
        ordered,
        expansion_m=config.match_distance_m,
    )
    pairs: list[dict[str, Any]] = []
    extent_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    exact_pair_count = 0
    relation_relevant_count = 0
    relation_relevant_candidate_count = 0

    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            pair_key = (left.source_observation_id, right.source_observation_id)
            result = analyze_spatial_relation(
                str(left.source_observation_id),
                left.points,
                str(right.source_observation_id),
                right.points,
                config=config,
            ).to_dict()
            candidate_generated = pair_key in candidates
            pair = {
                "pair_key": f"{pair_key[0]}:{pair_key[1]}",
                "observation_a_id": left.source_observation_id,
                "observation_b_id": right.source_observation_id,
                "source_segment_a_id": left.source_segment_id,
                "source_segment_b_id": right.source_segment_id,
                "geometry_hash_a": left.source_geometry_hash,
                "geometry_hash_b": right.source_geometry_hash,
                "candidate_generated": candidate_generated,
                "candidate_reasons": (
                    ["expanded_subcurve_bbox"] if candidate_generated else []
                ),
                "relation_basis": "raw_monotone_alignment",
                "comparison_status": "complete",
                "closure_safe_contains": False,
                "graph_raw_agreement": "not_available",
                "result": result,
            }
            pair["pair_record_sha256"] = canonical_sha256(pair)
            pairs.append(pair)

            extent = result["extent_relation"]
            direction = result["direction_relation"]
            extent_counts[extent] = extent_counts.get(extent, 0) + 1
            direction_counts[direction] = direction_counts.get(direction, 0) + 1
            if extent == "source_geometry_identical":
                exact_pair_count += 1
            # indeterminate 只有在 bbox 召回后才算 proximity/ambiguity 相关；
            # 远离且因单线质量问题 abstain 的 pair 不拿来虚增索引漏召回。
            relevant = extent != "disjoint" and (
                extent != "indeterminate" or candidate_generated
            )
            if relevant:
                relation_relevant_count += 1
                relation_relevant_candidate_count += int(candidate_generated)

    if len(pairs) != expected_pair_count:
        raise AssertionError("pair oracle 没有 exact 枚举所有无序对")
    ordered_pairs_sha256 = hashlib.sha256(
        b"\n".join(_canonical_json_bytes(pair) for pair in pairs)
    ).hexdigest()
    candidate_recall = (
        relation_relevant_candidate_count / relation_relevant_count
        if relation_relevant_count
        else 1.0
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": hashlib.sha256(
            _canonical_json_bytes(
                {
                    **run_identity,
                    "algorithm_version": RAW_SPATIAL_RELATION_ALGORITHM_VERSION,
                    "config": config.to_dict(),
                    "included_observation_ids": observation_ids,
                }
            )
        ).hexdigest()[:24],
        **run_identity,
        "evidence_scope": "raw_full_polyline_not_road_truth",
        "source_exact_hash_version": SOURCE_EXACT_HASH_VERSION,
        "relation_algorithm_version": RAW_SPATIAL_RELATION_ALGORITHM_VERSION,
        "parameter_manifest": config.to_dict(),
        "parameter_manifest_hash": canonical_sha256(config.to_dict()),
        "parameter_promotion_status": "research_probe_unpromoted",
        "candidate_index_version": CANDIDATE_INDEX_VERSION,
        "candidate_index_chunk_length_m": 500.0,
        "candidate_index_expansion_m": config.match_distance_m,
        "included_count": len(ordered),
        "included_observation_set_hash": _sha256_lines(
            str(value) for value in observation_ids
        ),
        "included_source_segment_set_hash": _sha256_lines(source_ids),
        "expected_pair_count": expected_pair_count,
        "emitted_pair_count": len(pairs),
        "fully_computed_pair_count": len(pairs),
        "truncated_pair_count": 0,
        "candidate_pair_count": len(candidates),
        "candidate_reduction_ratio": round(
            1.0 - len(candidates) / expected_pair_count, 6
        ),
        "relation_relevant_pair_count": relation_relevant_count,
        "relation_relevant_candidate_recall": round(candidate_recall, 6),
        "extent_counts": dict(sorted(extent_counts.items())),
        "direction_counts": dict(sorted(direction_counts.items())),
        "exact_pair_count": exact_pair_count,
        "determinate_pair_count": len(pairs)
        - extent_counts.get("indeterminate", 0),
        "indeterminate_pair_count": extent_counts.get("indeterminate", 0),
        "enumeration_complete": True,
        "computation_complete": True,
        "run_status": "complete",
        "budget_hits": [],
        "database_write_count": 0,
        "ordered_output_sha256": ordered_pairs_sha256,
        "boundary": (
            "全量 pair oracle 用于索引召回和人工标注，不是人工 gold；raw geometry "
            "不能证明平行路、桥隧、道路准入或拓扑连通。"
        ),
    }
    return manifest, pairs


def _read_database_inputs(
    db: Any,
    *,
    profile: dict[str, Any],
    legacy: dict[str, Any],
) -> tuple[dict[str, Any], list[RelationObservationInput]]:
    judgment = db.get(JudgmentRun, profile["human_review_judgment_run_id"])
    if judgment is None:
        raise LookupError("scope profile 指定的 JudgmentRun 不存在")
    fact_batch = db.get(SegmentElevationFactBatch, profile["elevation_fact_batch_id"])
    if fact_batch is None:
        raise LookupError("scope profile 指定的 GLO fact batch 不存在")
    facts = (
        db.query(SegmentElevationFact)
        .filter(SegmentElevationFact.fact_batch_id == fact_batch.id)
        .order_by(SegmentElevationFact.source_observation_id.asc())
        .all()
    )
    foundation = audit_snapshot(
        profile=profile,
        legacy=legacy,
        judgment=judgment,
        fact_batch=fact_batch,
        facts=facts,
        fact_readback=readback_fact_batch(db, fact_batch.id),
    )
    items = judgment.result_summary_json["items"]
    included_items = {
        item["source_observation_id"]: item
        for item in items
        if item["decision"] == "included"
    }
    if len(included_items) != profile["included_count"]:
        raise ValueError("JudgmentRun included 项不是 profile 指定的 exact set")
    observation_ids = sorted(included_items)
    rows = (
        db.query(
            SegmentSourceObservation,
            func.ST_AsText(SegmentSourceObservation.source_line).label("source_line_wkt"),
        )
        .filter(SegmentSourceObservation.id.in_(observation_ids))
        .order_by(SegmentSourceObservation.id.asc())
        .all()
    )
    if len(rows) != len(observation_ids):
        raise ValueError("数据库没有返回 exact 81 条 included observation")
    facts_by_observation = {fact.source_observation_id: fact for fact in facts}
    prepared: list[RelationObservationInput] = []
    for observation, source_line_wkt in rows:
        item = included_items[observation.id]
        fact = facts_by_observation[observation.id]
        points, actual_hash, derived_distance_m = validated_source_geometry(
            source_line_wkt,
            observation.geometry_point_count,
        )
        if (
            observation.source_segment_id != item["source_segment_id"]
            or actual_hash != item["source_geometry_hash"]
            or fact.source_segment_id != observation.source_segment_id
            or fact.source_geometry_hash != actual_hash
            or fact.fact_status != "complete"
        ):
            raise ValueError(f"observation {observation.id} 的来源/GLO binding 漂移")
        point_tuple = tuple((float(point[0]), float(point[1])) for point in points)
        directed_hash, undirected_hash = _source_exact_hashes(point_tuple)
        prepared.append(
            RelationObservationInput(
                source_observation_id=observation.id,
                source_segment_id=observation.source_segment_id,
                source_name=observation.source_name,
                source_geometry_hash=actual_hash,
                geometry_normalization_version=fact.geometry_normalization_version,
                geometry_resolution=observation.geometry_resolution,
                point_count=observation.geometry_point_count,
                points=point_tuple,
                source_length_m=round(derived_distance_m, 3),
                source_exact_directed_hash=directed_hash,
                source_exact_undirected_hash=undirected_hash,
                glo_fact_id=fact.id,
                glo_fact_batch_id=fact.fact_batch_id,
                glo_fact_status=fact.fact_status,
                glo_algorithm_version=fact.algorithm_version,
                glo_climb_m=float(fact.climb_m),
                glo_descent_m=float(fact.descent_m),
                athlete_count=observation.athlete_count,
                effort_count=observation.effort_count,
                star_count=observation.star_count,
            )
        )
    return foundation, prepared


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, path)


def write_artifact(
    output_dir: Path,
    *,
    manifest: dict[str, Any],
    observations: list[RelationObservationInput],
    pairs: list[dict[str, Any]],
) -> dict[str, str]:
    input_bytes = b"".join(
        _canonical_json_bytes(item.public_dict()) + b"\n"
        for item in sorted(observations, key=lambda item: item.source_observation_id)
    )
    pair_bytes = b"".join(_canonical_json_bytes(pair) + b"\n" for pair in pairs)
    review_pairs = [
        pair
        for pair in pairs
        if pair["result"]["extent_relation"] != "disjoint"
    ]
    review_bytes = b"".join(
        _canonical_json_bytes(pair) + b"\n" for pair in review_pairs
    )
    manifest = {
        **manifest,
        "input_artifact_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "pair_artifact_sha256": hashlib.sha256(pair_bytes).hexdigest(),
        "review_artifact_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "review_pair_count": len(review_pairs),
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    paths = {
        "manifest": output_dir / "manifest.json",
        "inputs": output_dir / "inputs.jsonl",
        "pairs": output_dir / "pairs.jsonl",
        "review": output_dir / "review.jsonl",
    }
    _atomic_write(paths["inputs"], input_bytes)
    _atomic_write(paths["pairs"], pair_bytes)
    _atomic_write(paths["review"], review_bytes)
    _atomic_write(paths["manifest"], manifest_bytes)
    return {key: str(value) for key, value in paths.items()}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--legacy-alignment", type=Path, default=DEFAULT_LEGACY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    profile, legacy = load_inputs(args.profile, args.legacy_alignment)
    db = SessionLocal()
    try:
        foundation, observations = _read_database_inputs(
            db,
            profile=profile,
            legacy=legacy,
        )
        manifest, pairs = build_relation_oracle(
            observations,
            config=RESEARCH_PROBE_CONFIG,
            run_identity={
                "profile_key": args.profile.stem,
                "profile_sha256": canonical_sha256(profile),
                "candidate_observation_set_hash": profile[
                    "candidate_observation_set_hash"
                ],
                "census_batch_id": profile["census_batch_id"],
                "elevation_fact_batch_id": profile["elevation_fact_batch_id"],
                "judgment_run_id": profile["human_review_judgment_run_id"],
                "foundation_status": foundation["foundation_status"],
                "census_enumeration_status": foundation["census_enumeration_status"],
            },
        )
        if db.new or db.dirty or db.deleted:
            raise RuntimeError("只读关系构建器产生了 ORM 写集合")
        paths = write_artifact(
            args.output_dir,
            manifest=manifest,
            observations=observations,
            pairs=pairs,
        )
        return {**manifest, "artifact_paths": paths}
    finally:
        db.rollback()
        db.close()


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
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
