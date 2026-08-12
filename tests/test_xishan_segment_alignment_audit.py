import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.audit_xishan_segment_alignment import (
    audit_snapshot,
    canonical_sha256,
    load_inputs,
)


PROFILE = Path("data/research/xishan_relation_input_profile_v1.json")
LEGACY = Path("data/research/taiyuan_strava_local_48_20260812_v1.json")


def test_checked_in_alignment_is_exact_87_81_6_and_48_11_37():
    profile, legacy = load_inputs(PROFILE, LEGACY)
    expected = {
        item["source_segment_id"]
        for item in legacy["items"]
        if item["scope_decision"] == "expected_in_current_xishan"
    }
    outside = {
        item["source_segment_id"]
        for item in legacy["items"]
        if item["scope_decision"] == "user_confirmed_outside_xishan"
    }

    assert (profile["candidate_count"], profile["included_count"], profile["excluded_count"]) == (87, 81, 6)
    assert set(profile["excluded_source_segment_ids"]) == {
        "33133333",
        "39979642",
        "40127007",
        "40437410",
        "40589205",
        "40835241",
    }
    assert len(expected) == 11
    assert len(outside) == 37
    assert len(expected | outside) == 48
    assert not expected & outside


def test_profile_hash_binds_every_legacy_id_and_scope_decision(tmp_path):
    profile, legacy = load_inputs(PROFILE, LEGACY)
    changed = copy.deepcopy(legacy)
    changed["items"][0]["scope_decision"] = "expected_in_current_xishan"
    path = tmp_path / "changed.json"
    path.write_text(__import__("json").dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="绑定 hash"):
        load_inputs(PROFILE, path)


def test_legacy_duplicate_id_fails_even_if_profile_hash_is_updated(tmp_path):
    profile, legacy = load_inputs(PROFILE, LEGACY)
    changed = copy.deepcopy(legacy)
    changed["items"][1]["source_segment_id"] = changed["items"][0]["source_segment_id"]
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(__import__("json").dumps(changed), encoding="utf-8")
    profile["legacy_alignment_sha256"] = __import__(
        "scripts.audit_xishan_segment_alignment",
        fromlist=["canonical_sha256"],
    ).canonical_sha256(changed)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(__import__("json").dumps(profile), encoding="utf-8")

    with pytest.raises(ValueError, match="重复 ID"):
        load_inputs(profile_path, legacy_path)


def _toy_snapshot():
    items = [
        {
            "source_observation_id": 1,
            "source_segment_id": "22350861",
            "source_geometry_hash": "a" * 64,
            "geometry_normalization_version": "norm-v1",
            "decision": "included",
            "reason_code": "retained_unchanged_in_road_relation_scope",
            "decision_note": None,
        },
        {
            "source_observation_id": 2,
            "source_segment_id": "40127007",
            "source_geometry_hash": "b" * 64,
            "geometry_normalization_version": "norm-v1",
            "decision": "excluded",
            "reason_code": "human_confirmed_out_of_road_relation_scope",
            "decision_note": "pure_xc",
        },
    ]
    summary = {
        "schema_version": "road_relation_input_selection_v1",
        "analysis_scope": "road_segment_spatial_relation",
        "partition_exact": True,
        "selection_hash": "c" * 64,
        "selection_policy_version": "policy-v1",
        "census_batch_id": "census-v1",
        "source_elevation_fact_batch_id": "glo-v1",
        "candidate_observation_set_hash": "d" * 64,
        "candidate_count": 2,
        "included_count": 1,
        "excluded_count": 1,
        "items": items,
    }
    profile = {
        "human_review_judgment_run_id": 20,
        "human_review_declared_hash": "c" * 64,
        "selection_payload_sha256": canonical_sha256(
            {key: value for key, value in summary.items() if key != "selection_hash"}
        ),
        "selection_policy_version": "policy-v1",
        "census_batch_id": "census-v1",
        "elevation_fact_batch_id": "glo-v1",
        "candidate_observation_set_hash": "d" * 64,
        "candidate_count": 2,
        "included_count": 1,
        "excluded_count": 1,
        "excluded_source_segment_ids": ["40127007"],
        "exclusion_reason_code": "human_confirmed_out_of_road_relation_scope",
        "exclusion_note": "pure_xc",
    }
    judgment = SimpleNamespace(
        id=20,
        run_type="human_review",
        status="succeeded",
        confidence_state="human_accepted",
        input_hash="c" * 64,
        result_summary_json=summary,
    )
    fact_batch = SimpleNamespace(
        id="glo-v1",
        census_batch_id="census-v1",
        input_observation_set_hash="d" * 64,
        run_status="completed",
        input_observation_count=2,
        complete_count=2,
        failed_count=0,
        source_incomplete_count=0,
    )
    facts = [
        SimpleNamespace(
            source_observation_id=item["source_observation_id"],
            source_segment_id=item["source_segment_id"],
            source_geometry_hash=item["source_geometry_hash"],
            geometry_normalization_version="norm-v1",
            fact_status="complete",
        )
        for item in items
    ]
    legacy = {
        "items": [
            {
                "source_segment_id": "22350861",
                "scope_decision": "expected_in_current_xishan",
            },
            {
                "source_segment_id": "99999999",
                "scope_decision": "user_confirmed_outside_xishan",
            },
        ]
    }
    readback = {
        "database_status": "committed_and_read_back",
        "exact_observation_set_match": True,
        "source_identity_integrity_status": "complete",
        "source_geometry_integrity_status": "complete",
        "elevation_fact_batch_status": "complete",
        "source_binding_mismatch_count": 0,
        "census_enumeration_status": "indeterminate",
    }
    return profile, legacy, judgment, fact_batch, facts, readback


def test_snapshot_audit_accepts_only_exact_selection_glo_and_legacy_partitions():
    profile, legacy, judgment, fact_batch, facts, readback = _toy_snapshot()
    result = audit_snapshot(
        profile=profile,
        legacy=legacy,
        judgment=judgment,
        fact_batch=fact_batch,
        facts=facts,
        fact_readback=readback,
    )

    assert result["status"] == "complete"
    assert result["database_write_count"] == 0
    assert result["source_observation_binding_mismatch_count"] == 0
    assert result["legacy_current_xishan_all_included"] is True


def test_snapshot_audit_rejects_replaced_xc_even_when_counts_still_add_up():
    profile, legacy, judgment, fact_batch, facts, readback = _toy_snapshot()
    judgment.result_summary_json["items"][1]["source_segment_id"] = "40437410"
    profile["selection_payload_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in judgment.result_summary_json.items()
            if key != "selection_hash"
        }
    )

    with pytest.raises(ValueError, match="XC ID 集"):
        audit_snapshot(
            profile=profile,
            legacy=legacy,
            judgment=judgment,
            fact_batch=fact_batch,
            facts=facts,
            fact_readback=readback,
        )
