#!/usr/bin/env python3
"""只读核对西山赛段标注、GLO 事实和旧 48 范围，不创建新数据层。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.route_cognition.census_models import (
    SegmentElevationFact,
    SegmentElevationFactBatch,
)
from app.route_cognition.models import JudgmentRun
from scripts.backfill_segment_elevation_facts import readback_fact_batch


DEFAULT_PROFILE = REPO_ROOT / "data/research/xishan_relation_input_profile_v1.json"
DEFAULT_LEGACY = (
    REPO_ROOT / "data/research/taiyuan_strava_local_48_20260812_v1.json"
)
INCLUDE_REASON = "retained_unchanged_in_road_relation_scope"
EXCLUDE_REASON = "human_confirmed_out_of_road_relation_scope"


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sorted_unique_lines_sha256(values: list[str]) -> str:
    if len(values) != len(set(values)):
        raise ValueError("集合含重复 ID")
    return hashlib.sha256("\n".join(sorted(values)).encode("utf-8")).hexdigest()


def load_inputs(profile_path: Path, legacy_path: Path) -> tuple[dict, dict]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != "relation_input_scope_profile_v1":
        raise ValueError("scope profile schema_version 不受支持")
    if legacy.get("schema_version") != "source_scope_alignment_v1":
        raise ValueError("legacy alignment schema_version 不受支持")
    if canonical_sha256(legacy) != profile.get("legacy_alignment_sha256"):
        raise ValueError("旧48清单与 scope profile 绑定 hash 不一致")
    legacy_items = legacy.get("items")
    if not isinstance(legacy_items, list) or not legacy_items:
        raise ValueError("旧48清单 items 为空")
    legacy_ids = [str(item.get("source_segment_id", "")) for item in legacy_items]
    if any(not source_id.isdigit() for source_id in legacy_ids):
        raise ValueError("旧48清单含非法 Strava ID")
    source = legacy.get("baseline_source") or {}
    if (
        len(legacy_ids) != source.get("source_id_count")
        or sorted_unique_lines_sha256(legacy_ids) != source.get("source_id_set_sha256")
    ):
        raise ValueError("旧48 ID 数量或集合 hash 不一致")
    decisions = [item.get("scope_decision") for item in legacy_items]
    expected_count = decisions.count("expected_in_current_xishan")
    outside_count = decisions.count("user_confirmed_outside_xishan")
    scope = legacy.get("scope_decision") or {}
    if (
        expected_count + outside_count != len(legacy_items)
        or expected_count != scope.get("current_xishan_count")
        or outside_count != scope.get("outside_xishan_count")
    ):
        raise ValueError("旧48逐条范围决定不是 exact partition")
    excluded_ids = profile.get("excluded_source_segment_ids")
    if (
        not isinstance(excluded_ids, list)
        or len(excluded_ids) != len(set(excluded_ids))
        or len(excluded_ids) != profile.get("excluded_count")
        or profile.get("included_count") + profile.get("excluded_count")
        != profile.get("candidate_count")
    ):
        raise ValueError("scope profile 的 included/excluded 账不一致")
    return profile, legacy


def audit_snapshot(
    *,
    profile: dict,
    legacy: dict,
    judgment: JudgmentRun,
    fact_batch: SegmentElevationFactBatch,
    facts: list[SegmentElevationFact],
    fact_readback: dict,
) -> dict:
    if judgment.id != profile["human_review_judgment_run_id"]:
        raise ValueError("JudgmentRun ID 与 scope profile 不一致")
    if (
        judgment.run_type != "human_review"
        or judgment.status != "succeeded"
        or judgment.confidence_state != "human_accepted"
    ):
        raise ValueError("JudgmentRun 不是已接受的成功人工审核")
    if judgment.input_hash != profile["human_review_declared_hash"]:
        raise ValueError("JudgmentRun 声明 hash 漂移")
    summary = judgment.result_summary_json
    if not isinstance(summary, dict):
        raise ValueError("JudgmentRun 缺少 result_summary_json")
    summary_without_declared_hash = {
        key: value for key, value in summary.items() if key != "selection_hash"
    }
    if canonical_sha256(summary_without_declared_hash) != profile["selection_payload_sha256"]:
        raise ValueError("JudgmentRun 逐条审核 payload 漂移")
    if (
        summary.get("schema_version") != "road_relation_input_selection_v1"
        or summary.get("analysis_scope") != "road_segment_spatial_relation"
        or summary.get("partition_exact") is not True
        or summary.get("selection_hash") != judgment.input_hash
        or summary.get("selection_policy_version")
        != profile["selection_policy_version"]
        or summary.get("census_batch_id") != profile["census_batch_id"]
        or summary.get("source_elevation_fact_batch_id")
        != profile["elevation_fact_batch_id"]
        or summary.get("candidate_observation_set_hash")
        != profile["candidate_observation_set_hash"]
    ):
        raise ValueError("JudgmentRun 输入身份或审核合同不一致")
    items = summary.get("items")
    if not isinstance(items, list):
        raise ValueError("JudgmentRun 没有逐条审核项")
    observation_ids = [item.get("source_observation_id") for item in items]
    source_ids = [str(item.get("source_segment_id", "")) for item in items]
    if (
        len(observation_ids) != len(set(observation_ids))
        or len(source_ids) != len(set(source_ids))
        or any(not source_id.isdigit() for source_id in source_ids)
    ):
        raise ValueError("JudgmentRun observation/Strava ID 重复或非法")
    included = [item for item in items if item.get("decision") == "included"]
    excluded = [item for item in items if item.get("decision") == "excluded"]
    excluded_ids = {item["source_segment_id"] for item in excluded}
    if (
        len(items) != profile["candidate_count"]
        or len(included) != profile["included_count"]
        or len(excluded) != profile["excluded_count"]
        or len(included) + len(excluded) != len(items)
        or summary.get("candidate_count") != len(items)
        or summary.get("included_count") != len(included)
        or summary.get("excluded_count") != len(excluded)
        or excluded_ids != set(profile["excluded_source_segment_ids"])
    ):
        raise ValueError("当前审核不是 profile 指定的 exact 81+6 或 XC ID 集")
    if any(
        item.get("reason_code") != INCLUDE_REASON
        or item.get("decision_note") is not None
        for item in included
    ):
        raise ValueError("included 项原因不一致")
    if any(
        item.get("reason_code") != profile["exclusion_reason_code"]
        or item.get("decision_note") != profile["exclusion_note"]
        for item in excluded
    ):
        raise ValueError("excluded 项原因或人工 note 不一致")

    if (
        fact_batch.id != profile["elevation_fact_batch_id"]
        or fact_batch.census_batch_id != profile["census_batch_id"]
        or fact_batch.input_observation_set_hash
        != profile["candidate_observation_set_hash"]
        or fact_batch.run_status != "completed"
        or fact_batch.input_observation_count != profile["candidate_count"]
        or fact_batch.complete_count != profile["candidate_count"]
        or fact_batch.failed_count != 0
        or fact_batch.source_incomplete_count != 0
    ):
        raise ValueError("GLO fact batch 不是 profile 指定的 87/87 complete 批次")
    facts_by_observation = {fact.source_observation_id: fact for fact in facts}
    if len(facts) != len(facts_by_observation) or len(facts) != len(items):
        raise ValueError("GLO fact 与审核项不是 observation exact set")
    binding_errors = []
    for item in items:
        fact = facts_by_observation.get(item["source_observation_id"])
        if fact is None or (
            fact.source_segment_id != item["source_segment_id"]
            or fact.source_geometry_hash != item.get("source_geometry_hash")
            or fact.geometry_normalization_version
            != item.get("geometry_normalization_version")
            or fact.fact_status != "complete"
        ):
            binding_errors.append(item["source_segment_id"])
    if binding_errors:
        raise ValueError(f"审核项与 GLO 逐条 binding 不一致：{binding_errors[:5]}")
    if not (
        fact_readback.get("database_status") == "committed_and_read_back"
        and fact_readback.get("exact_observation_set_match") is True
        and fact_readback.get("source_identity_integrity_status") == "complete"
        and fact_readback.get("source_geometry_integrity_status") == "complete"
        and fact_readback.get("elevation_fact_batch_status") == "complete"
        and fact_readback.get("source_binding_mismatch_count") == 0
    ):
        raise ValueError("既有 GLO/source readback 未通过")

    candidate_ids = set(source_ids)
    included_ids = {item["source_segment_id"] for item in included}
    legacy_items = legacy["items"]
    legacy_ids = {item["source_segment_id"] for item in legacy_items}
    expected_legacy_ids = {
        item["source_segment_id"]
        for item in legacy_items
        if item["scope_decision"] == "expected_in_current_xishan"
    }
    outside_legacy_ids = legacy_ids - expected_legacy_ids
    if (
        candidate_ids & legacy_ids != expected_legacy_ids
        or not expected_legacy_ids <= included_ids
        or outside_legacy_ids & candidate_ids
        or expected_legacy_ids & excluded_ids
    ):
        raise ValueError("旧48与当前 81+6 不是确认的 11+37 exact alignment")
    return {
        "status": "complete",
        "database_write_count": 0,
        "foundation_status": "mechanically_aligned_for_relation_algorithm_design",
        "census_batch_id": fact_batch.census_batch_id,
        "elevation_fact_batch_id": fact_batch.id,
        "judgment_run_id": judgment.id,
        "candidate_count": len(items),
        "included_count": len(included),
        "excluded_count": len(excluded),
        "excluded_source_segment_ids": sorted(excluded_ids),
        "source_observation_binding_mismatch_count": 0,
        "strava_source_id_binding_mismatch_count": 0,
        "geometry_hash_binding_mismatch_count": 0,
        "glo_fact_binding_mismatch_count": 0,
        "legacy_count": len(legacy_ids),
        "legacy_current_xishan_count": len(expected_legacy_ids),
        "legacy_outside_xishan_count": len(outside_legacy_ids),
        "legacy_current_xishan_all_included": True,
        "legacy_outside_xishan_in_candidate_count": 0,
        "census_enumeration_status": fact_readback["census_enumeration_status"],
        "relation_algorithm_status": "not_started",
        "boundary": "这是关系算法的冻结研究输入，不等于西山来源枚举完整。",
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--legacy-alignment", type=Path, default=DEFAULT_LEGACY)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    profile, legacy = load_inputs(args.profile, args.legacy_alignment)
    db = SessionLocal()
    try:
        judgment = db.get(JudgmentRun, profile["human_review_judgment_run_id"])
        if judgment is None:
            raise LookupError("scope profile 指定的 JudgmentRun 不存在")
        fact_batch = db.get(
            SegmentElevationFactBatch,
            profile["elevation_fact_batch_id"],
        )
        if fact_batch is None:
            raise LookupError("scope profile 指定的 GLO fact batch 不存在")
        facts = (
            db.query(SegmentElevationFact)
            .filter(SegmentElevationFact.fact_batch_id == fact_batch.id)
            .order_by(SegmentElevationFact.source_segment_id.asc())
            .all()
        )
        return audit_snapshot(
            profile=profile,
            legacy=legacy,
            judgment=judgment,
            fact_batch=fact_batch,
            facts=facts,
            fact_readback=readback_fact_batch(db, fact_batch.id),
        )
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
