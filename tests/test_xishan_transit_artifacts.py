from __future__ import annotations

import json
from pathlib import Path

from app.route_cognition.transit_paths import canonical_sha256


REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DATA = REPO_ROOT / "data" / "research"


def _read(name: str) -> dict:
    return json.loads((RESEARCH_DATA / name).read_text(encoding="utf-8"))


def _assert_public_manifest(name: str) -> dict:
    payload = _read(name)
    declared = payload.pop("public_manifest_sha256")
    assert declared == canonical_sha256(payload)
    assert "geometry_wgs84" not in payload
    assert "profile" not in payload["elevation"]
    assert payload["provider"] in {"tencent_driving", "tencent_driving_shadow"}
    assert payload["provider_status"] in {
        "provider_path_not_bicycling_verified",
        "research_candidate_not_bicycling_verified",
    }
    assert payload["relation_input"]["candidate_count"] == 81
    assert payload["relation_input"]["included_count"] == 81
    assert payload["relation_input"]["excluded_count"] == 0
    assert payload["persistence_role"] == (
        "research_provider_candidate_not_internal_routing_connector_or_road_truth"
    )
    assert payload["database_write_count"] == 0
    return payload


def test_tracked_transit_manifests_keep_current_reproduction_results() -> None:
    hengling = _assert_public_manifest(
        "xishan_transit_path_hengling_taohuagou_v1_manifest.json"
    )
    aoshen = _assert_public_manifest(
        "xishan_transit_path_aoshen_langpo_v1_manifest.json"
    )
    langpo = _assert_public_manifest(
        "xishan_transit_path_langpo_base_taohuagou_v1_manifest.json"
    )

    assert hengling["provider_distance_m"] == 16856.0
    assert hengling["elevation"]["climb_m"] == 211.7
    assert hengling["evidence_coverage"]["coverage_lower_bound_ratio"] == 0.500291
    assert hengling["evidence_coverage"]["by_direction"]["same_direction"][
        "coverage_lower_bound_ratio"
    ] == 0
    assert hengling["evidence_coverage"]["by_direction"]["reverse_direction"][
        "coverage_lower_bound_ratio"
    ] == 0.500291
    assert {fact["source_observation_id"] for fact in hengling["evidence_facts"]} == {
        53,
        82,
    }

    assert aoshen["provider_distance_m"] == 2250.0
    assert aoshen["evidence_coverage"]["coverage_lower_bound_ratio"] == 0.819156
    assert aoshen["evidence_coverage"]["by_direction"]["same_direction"][
        "coverage_lower_bound_ratio"
    ] == 0
    assert [fact["source_observation_id"] for fact in aoshen["evidence_facts"]] == [
        7
    ]

    assert langpo["provider_distance_m"] == 14957.0
    assert langpo["elevation"]["climb_m"] == 231.3
    assert langpo["evidence_coverage"]["uncovered_state"] == "unobserved_not_zero"

    retrace = _assert_public_manifest(
        "xishan_transit_path_langpo_upper_taohuagou_retrace_v1_manifest.json"
    )
    assert retrace["research_verdict"] == (
        "blocked_after_destination_upper_first_candidate_retraces"
    )
    assert retrace["evidence_coverage"]["by_direction"]["reverse_direction"][
        "covered_intervals_m"
    ][0] == [0.0, 3371.2]


def test_selection_pointer_is_exact_active_81() -> None:
    payload = _read("xishan_relation_selection_81_v1_manifest.json")
    declared = payload.pop("manifest_sha256")
    assert declared == canonical_sha256(payload)
    assert payload["candidate_count"] == 81
    assert payload["included_count"] == 81
    assert payload["excluded_count"] == 0
    assert payload["excluded_source_segment_ids"] == []


def test_historical_baseline_manifest_is_hash_bound() -> None:
    payload = _read("xishan_multisegment_baseline_20260812_v1.json")
    declared = payload.pop("manifest_sha256")
    assert declared == canonical_sha256(payload)
    assert payload["funnel"]["raw_directed_chains"] == 4933
    assert payload["funnel"]["displayed_over_70km"] == 5


def test_transit_source_fact_refs_are_hash_bound_and_exclude_coordinates() -> None:
    payload = _read("xishan_transit_source_fact_refs_v1.json")
    declared = payload.pop("manifest_sha256")
    assert declared == canonical_sha256(payload)
    assert len(payload["facts"]) == 13
    assert len({row["source_observation_id"] for row in payload["facts"]}) == 13
    assert all("source_geometry_lonlat" not in row for row in payload["facts"])
    assert all(
        row["glo_algorithm_version"] == "glo30_meaningful_ascent_v1"
        for row in payload["facts"]
    )
