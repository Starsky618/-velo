from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.route_cognition.transit_paths import canonical_sha256


RESEARCH = Path("data/research")
MODULES = RESEARCH / "mountain_modules"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _self_hash(payload: dict, field: str) -> str:
    return canonical_sha256({key: value for key, value in payload.items() if key != field})


def _regional_id_set_hash(values: list[int]) -> str:
    return hashlib.sha256(
        "\n".join(str(value) for value in sorted(values)).encode("utf-8")
    ).hexdigest()


def _module_id_set_hash(values: list[int]) -> str:
    return hashlib.sha256(
        "\n".join(sorted(str(value) for value in values)).encode("utf-8")
    ).hexdigest()


def test_full_active_81_batch_and_oracle_are_frozen() -> None:
    spec = _read(RESEARCH / "xishan_full_destination_network_v1.json")
    run = _read(RESEARCH / "xishan_full_destination_network_v1_run.json")
    manifest = _read(RESEARCH / "xishan_full_destination_network_v1_manifest.json")

    exact_ids = spec["exact_observation_ids"]
    assert len(exact_ids) == len(set(exact_ids)) == 81
    assert spec["observation_set_sha256"] == _regional_id_set_hash(exact_ids)
    disposition_ids = [
        value
        for item in spec["primary_dispositions"]
        for value in item["observation_ids"]
    ]
    assert sorted(disposition_ids) == exact_ids
    assert len(disposition_ids) == len(set(disposition_ids))

    assert run["run_sha256"] == _self_hash(run, "run_sha256")
    assert run["exact_observation_ids"] == exact_ids
    assert run["fact_reconciliation"]["observation_count"] == 81
    assert run["fact_reconciliation"]["unique_source_segment_count"] == 81
    assert run["fact_reconciliation"]["unique_geometry_hash_count"] == 81
    assert run["fact_reconciliation"]["unique_glo_fact_count"] == 81
    assert run["fact_reconciliation"]["heat_complete_count"] == 81
    assert run["oracle_summary"]["pair_count"] == 3240
    assert run["oracle_summary"]["complete_count"] == 3240
    assert len(run["families"]) == 24

    assert manifest["manifest_sha256"] == _self_hash(manifest, "manifest_sha256")
    assert manifest["regional_spec_sha256"] == canonical_sha256(spec)
    assert manifest["regional_run_sha256"] == run["run_sha256"]
    assert manifest["fact_reconciliation"]["observation_count"] == 81
    assert manifest["oracle_subset"]["pair_count"] == 3240
    assert manifest["road_family_accounting"] == {
        "canonical_family_count": 24,
        "planned_mountain_module_count": 23,
        "transit_range_axis_count": 1,
        "all_physical_axes_store_one_reference_geometry": True,
        "reverse_rule": "reuse canonical geometry; reverse traversal and swap climb/descent",
    }


def test_all_declared_mountain_module_specs_are_hash_bound_and_single_axis() -> None:
    manifest = _read(RESEARCH / "xishan_full_destination_network_v1_manifest.json")
    spec = _read(RESEARCH / "xishan_full_destination_network_v1.json")
    run = _read(RESEARCH / "xishan_full_destination_network_v1_run.json")
    run_families = {item["family_key"]: item for item in run["families"]}
    facts = {
        int(item["source_observation_id"]): item
        for item in run["fact_reconciliation"]["observations"]
    }
    family_resource_ids = [
        int(item["resource_observation_id"])
        for item in spec["families"]
        if item.get("resource_observation_id") is not None
    ]
    assert len(family_resource_ids) == len(set(family_resource_ids))

    declarations = manifest["mountain_module_specs"]
    assert len(declarations) == 23
    module_keys: set[str] = set()
    for declaration in declarations:
        path = Path(declaration["path"])
        payload = _read(path)
        assert declaration["spec_sha256"] == canonical_sha256(payload)
        assert payload["module_key"] not in module_keys
        module_keys.add(payload["module_key"])
        assert payload["module_role"] == "destination_block"
        source_ids = payload["source_selection"]["observation_ids"]
        assert payload["source_selection"]["observation_set_sha256"] == _module_id_set_hash(
            source_ids
        )
        assert payload["axis_profile_observation_id"] == payload["reference_axis"][
            "source_observation_id"
        ]
        assert payload["reference_axis"]["source_observation_id"] in source_ids
        reference = facts[payload["reference_axis"]["source_observation_id"]]
        assert payload["reference_axis"]["source_segment_id"] == str(
            reference["source_segment_id"]
        )
        assert payload["reference_axis"]["source_geometry_hash"] == reference[
            "source_geometry_hash"
        ]
        family = run_families[payload["module_key"]]
        projections = {
            int(item["source_observation_id"]): item["projection"]
            for item in family["projections"]
        }
        for requirement in payload["role_requirements"]:
            projection = projections[requirement["observation_id"]]
            assert projection["direction"] == requirement["expected_direction"]
            assert projection["source_coverage_ratio"] >= requirement[
                "min_source_coverage_ratio"
            ]
            assert projection["carrier_coverage_ratio"] >= requirement[
                "min_axis_coverage_ratio"
            ]
        assert payload["route_blocks"]
        for block in payload["route_blocks"]:
            assert block["block_role"] == "destination_traversal"
            assert block["recommendation_status"] == "evidence_candidate"
            for traversal in block["traversals"]:
                assert traversal["resource_observation_id"] in source_ids
                resource_projection = projections[traversal["resource_observation_id"]]
                assert resource_projection["direction"] == traversal["direction"]
                assert resource_projection["source_coverage_ratio"] >= traversal[
                    "min_resource_alignment_ratio"
                ]
                assert resource_projection["carrier_coverage_ratio"] >= traversal[
                    "min_resource_alignment_ratio"
                ]

    new_paths = [
        item["path"]
        for item in declarations
        if not item["path"].endswith("hengling_v1.json")
        and "xishan_south_" not in item["path"]
    ]
    assert len(new_paths) == 17
    assert all(Path(path).is_file() for path in new_paths)


def test_remaining_choice_set_has_12_hard_feasible_real_choices() -> None:
    choice = _read(RESEARCH / "xishan_remaining_route_choice_set_v1.json")
    result = _read(RESEARCH / "xishan_remaining_route_choice_set_v1_result.json")
    manifest = _read(RESEARCH / "xishan_full_destination_network_v1_manifest.json")

    assert result["result_sha256"] == _self_hash(result, "result_sha256")
    assert len(choice["candidates"]) == len(result["candidates"]) == 12
    assert all(
        item["assembly_status"] == "hard_feasible_research_candidate"
        and not item["hard_failure_codes"]
        for item in result["candidates"]
    )
    scope_counts = {
        scope: sum(item["comparison_scope"] == scope for item in result["candidates"])
        for scope in {
            "short_destination_core",
            "medium_destination_chain",
            "long_regional_chain",
        }
    }
    assert scope_counts == {
        "short_destination_core": 8,
        "medium_destination_chain": 2,
        "long_regional_chain": 2,
    }
    assert manifest["route_choices"]["choice_spec_sha256"] == canonical_sha256(choice)
    assert manifest["route_choices"]["result_sha256"] == result["result_sha256"]

    facts = {item["candidate_id"]: item["heat_vector"] for item in result["candidates"]}
    assert facts["short-wanmu-aoshen-main"]["distance_km"] == 5.225
    assert facts["short-langpo-main"]["climb_m"] == 271.7
    assert facts["short-duguan-classic"]["distance_km"] == 9.286
    assert facts["short-erku-gelou-matoushui"]["descent_m"] == 57.0
    assert facts["medium-wanmu-aoshen-langpo"]["distance_km"] == 10.89
    assert facts["medium-wanmu-aoshen-langpo"]["climb_m"] == 634.9
    assert facts["medium-langpo-aoshen-wanmu-reverse"]["climb_m"] == 195.4
    assert facts["medium-langpo-aoshen-wanmu-reverse"]["descent_m"] == 634.9
    assert facts["long-hengling-huaketou-taohuagou"]["distance_km"] == 37.888
    assert facts["long-hengling-huaketou-taohuagou"]["climb_m"] == 1100.3
    assert facts["long-taohuagou-huaketou-hengling-reverse"]["climb_m"] == 390.3
    assert facts["long-taohuagou-huaketou-hengling-reverse"]["descent_m"] == 1100.3

    candidates = {item["candidate_id"]: item for item in result["candidates"]}
    for forward_id, reverse_id in (
        ("medium-wanmu-aoshen-langpo", "medium-langpo-aoshen-wanmu-reverse"),
        (
            "long-hengling-huaketou-taohuagou",
            "long-taohuagou-huaketou-hengling-reverse",
        ),
    ):
        forward = candidates[forward_id]
        reverse = candidates[reverse_id]
        assert forward["heat_vector"]["distance_km"] == reverse["heat_vector"][
            "distance_km"
        ]
        assert forward["heat_vector"]["climb_m"] == reverse["heat_vector"][
            "descent_m"
        ]
        assert forward["heat_vector"]["descent_m"] == reverse["heat_vector"][
            "climb_m"
        ]
        for stored, reversed_component in zip(
            forward["ordered_components"], reversed(reverse["ordered_components"])
        ):
            assert stored["component_geometry_sha256"] == reversed_component[
                "component_geometry_sha256"
            ]
            assert stored["distance_km"] == reversed_component["distance_km"]
            assert stored["climb_m"] == reversed_component["descent_m"]
            assert stored["descent_m"] == reversed_component["climb_m"]


def test_supplemental_roads_and_backbone_patterns_do_not_claim_active_truth() -> None:
    ledger = _read(RESEARCH / "xishan_remaining_supplemental_resource_ledger_v1.json")
    patterns = _read(RESEARCH / "xishan_backbone_route_patterns_v1.json")
    manifest = _read(RESEARCH / "xishan_full_destination_network_v1_manifest.json")

    assert ledger["accounting"] == {
        "active_81_facts_added": 0,
        "database_write_count": 0,
        "glo_recomputation_count": 0,
        "strava_request_count": 0,
        "new_provider_request_count": 0,
    }
    resources = {item["resource_key"]: item for item in ledger["resources"]}
    assert resources["zaodu_full_climb_source_34856789"]["source_segment_id"] == "34856789"
    assert "source_elevation_gain_m_not_glo" in resources[
        "zaodu_full_climb_source_34856789"
    ]["source_measurements"]
    assert resources["duguan_new_tourism_road_source_37687861"]["source_segment_id"] == "37687861"
    assert resources["miaoqianshan_curated_destination"]["pending"]
    assert resources["qichunge_curated_destination"]["curated_measurements"][
        "climb_m_legacy_not_glo"
    ] == 263.0

    assert len(patterns["patterns"]) == 8
    assert all(
        item["assembly_status"] != "hard_feasible_research_candidate"
        for item in patterns["patterns"]
    )
    assert all(item["typed_blockers"] for item in patterns["patterns"])
    assert manifest["backbone_patterns"]["artifact_sha256"] == canonical_sha256(
        patterns
    )
    assert manifest["supplemental_resources"]["artifact_sha256"] == canonical_sha256(
        ledger
    )


def test_south_and_hengling_regressions_remain_exact() -> None:
    south = _read(RESEARCH / "xishan_south_route_choice_set_v1_result.json")
    hengling = _read(RESEARCH / "xishan_route_choice_set_v1_result.json")
    manifest = _read(RESEARCH / "xishan_full_destination_network_v1_manifest.json")

    assert south["result_sha256"] == "b815dfe77a29d60e26396548b0b13de243a038056db3e77ab69d14e08039d87e"
    assert hengling["result_sha256"] == "d118b5289b1b5b7f706f167627889371799a89a6c880a49f408c6c1a4cbcfe36"
    assert manifest["regression"]["south_choice_result_sha256"] == south[
        "result_sha256"
    ]
    assert manifest["regression"]["hengling_choice_result_sha256"] == hengling[
        "result_sha256"
    ]


def test_public_overview_states_profile_and_connector_boundaries() -> None:
    text = (
        Path("docs/research/2026-08-14-xishan-full-destination-network-v1.md")
        .read_text(encoding="utf-8")
    )
    for phrase in (
        "五种骑法",
        "12 条可重放选择",
        "经典杜关线",
        "新杜关旅游公路",
        "枣杜",
        "启春阁",
        "汾河二库阁楼",
        "王封一线天",
        "庙前山",
        "不能给全环一个精确公里数",
        "full elevation profile 仍待生产只读一次导出",
    ):
        assert phrase in text
