from __future__ import annotations

import json
from pathlib import Path

from app.route_cognition.transit_paths import canonical_sha256


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data" / "research"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_xishan_south_batch_manifest_is_hash_bound_and_complete() -> None:
    manifest = _read(RESEARCH / "xishan_south_destination_network_v1_manifest.json")
    declared = manifest.pop("manifest_sha256")
    assert declared == canonical_sha256(manifest)
    assert manifest["exact_observation_ids"] == [
        4, 8, 9, 17, 18, 21, 28, 49, 50, 51, 55,
        57, 78, 79, 85, 87, 89, 93, 96, 97, 98,
    ]
    assert manifest["fact_reconciliation"]["source_geometry_hash_recomputed_count"] == 21
    assert manifest["oracle_subset"]["complete_count"] == 210
    assert len(manifest["destination_families"]) == 5
    assert len(manifest["transit_paths"]) == 6
    assert manifest["route_choices"]["hard_feasible_count"] == 11
    assert manifest["route_choices"]["hard_rejected_count"] == 1
    assert manifest["route_choices"]["execution_mode"] == (
        "source_corridor_shadow_pending_mountain_module_runs"
    )
    assert manifest["regression"]["exact_match"] is True
    assert manifest["execution_accounting"]["database_write_count"] == 0


def test_module_specs_use_one_canonical_axis_and_remain_profile_pending() -> None:
    manifest = _read(RESEARCH / "xishan_south_destination_network_v1_manifest.json")
    for resource in manifest["mountain_module_specs"]:
        spec = _read(ROOT / resource["path"])
        assert resource["spec_sha256"] == canonical_sha256(spec)
        assert spec["status"] == "research_shadow_pending_glo_profile_export"
        reference_id = spec["reference_axis"]["source_observation_id"]
        assert all(
            traversal["resource_observation_id"] == reference_id
            for block in spec["route_blocks"]
            for traversal in block["traversals"]
        )
    west = _read(
        RESEARCH / "mountain_modules/xishan_south_tianlongshan_west_gate_v1.json"
    )
    assert [
        block["traversals"][0]["direction"] for block in west["route_blocks"]
    ] == ["forward"]
    assert any(
        requirement["expected_direction"] == "reverse"
        for requirement in west["role_requirements"]
    )
    assert "reverse choices reuse the block" in west["boundary"]


def test_six_transit_public_manifests_are_hash_bound_and_coordinate_reduced() -> None:
    batch = _read(RESEARCH / "xishan_south_destination_network_v1_manifest.json")
    expected = {item["transit_key"]: item for item in batch["transit_paths"]}
    actual = {}
    for path in (RESEARCH / "transit_paths").glob("*_v1_manifest.json"):
        payload = _read(path)
        declared = payload.pop("public_manifest_sha256")
        assert declared == canonical_sha256(payload)
        assert "geometry_wgs84" not in payload
        assert "ordered_road_steps" not in payload
        assert "profile" not in payload["elevation"]
        assert payload["provider"] == "tencent_bicycling_shadow"
        assert payload["provider_status"] == "connectivity_shadow_not_access_verified"
        actual[payload["transit_key"]] = payload
    assert set(actual) == set(expected)
    assert all(
        actual[key]["result_sha256"] == expected[key]["result_sha256"]
        for key in expected
    )


def test_eleven_choices_are_feasible_and_one_retrace_is_typed_rejected() -> None:
    result = _read(RESEARCH / "xishan_south_route_choice_set_v1_result.json")
    declared = result.pop("result_sha256")
    assert declared == canonical_sha256(result)
    assert len(result["candidates"]) == 12
    feasible = [item for item in result["candidates"] if not item["hard_failure_codes"]]
    rejected = [item for item in result["candidates"] if item["hard_failure_codes"]]
    assert len(feasible) == 11
    assert rejected == [
        {
            "assembly_status": "hard_rejected",
            "candidate_id": "long-taigu-diantou-mengshan-north-west",
            "choice_name": "太古路—店头—蒙山—北侧—西门",
            "comparison_scope": "long_regional_chain",
            "hard_failure_codes": ["immediate_full_source_retrace"],
        }
    ]
    assert {item["comparison_scope"] for item in result["ranking_groups"]} == {
        "short_destination_core",
        "medium_destination_chain",
        "long_regional_chain",
    }
    ranked = {
        item["candidate_id"]
        for group in result["ranking_groups"]
        for item in result["candidates"]
        if item["candidate_id"] in group["ranked_candidate_ids"]
        and item["comparison_scope"] == group["comparison_scope"]
    }
    assert ranked == {
        item["candidate_id"]
        for item in result["candidates"]
        if item["candidate_id"]
        in {
            candidate_id
            for group in result["ranking_groups"]
            for candidate_id in group["ranked_candidate_ids"]
        }
    }
