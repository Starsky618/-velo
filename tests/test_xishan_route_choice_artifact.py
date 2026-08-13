from __future__ import annotations

import json
from pathlib import Path

from app.route_cognition.transit_paths import canonical_sha256


PATH = Path("data/research/xishan_route_choice_set_v1_result.json")


def test_four_xishan_hard_data_choices_are_frozen() -> None:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    declared = payload.pop("result_sha256")
    assert declared == canonical_sha256(payload)
    assert payload["ranking_status"] == "not_ranked_across_distinct_rider_jobs"
    assert len(payload["candidates"]) == 4
    assert all(not item["hard_failure_codes"] for item in payload["candidates"])
    facts = {
        item["candidate_id"]: item["heat_vector"]
        for item in payload["candidates"]
    }
    assert facts["hengling-ascent-core"]["distance_km"] == 10.932
    assert facts["hengling-ascent-core"]["climb_m"] == 622.2
    assert facts["taohuagou-ascent-core"]["distance_km"] == 6.363
    assert facts["taohuagou-ascent-core"]["climb_m"] == 377.9
    assert facts["hengling-to-taohuagou-regional-chain"]["distance_km"] == 37.888
    assert facts["hengling-to-taohuagou-regional-chain"]["climb_m"] == 1100.3
    reverse = facts["taohuagou-to-hengling-regional-chain"]
    assert reverse["distance_km"] == 37.888
    assert reverse["climb_m"] == 390.3
    assert reverse["descent_m"] == 1100.3
    forward = facts["hengling-to-taohuagou-regional-chain"]
    assert reverse["distance_km"] == forward["distance_km"]
    assert reverse["climb_m"] == forward["descent_m"]
    assert reverse["descent_m"] == forward["climb_m"]
    candidate_by_id = {
        item["candidate_id"]: item for item in payload["candidates"]
    }
    forward_components = candidate_by_id[
        "hengling-to-taohuagou-regional-chain"
    ]["ordered_components"]
    reverse_components = candidate_by_id[
        "taohuagou-to-hengling-regional-chain"
    ]["ordered_components"]
    for stored, reversed_component in zip(
        forward_components, reversed(reverse_components)
    ):
        assert stored["component_geometry_sha256"] == reversed_component[
            "component_geometry_sha256"
        ]
        assert stored["component_extent_m"] == reversed_component[
            "component_extent_m"
        ]
        assert {
            stored["traversal_orientation"],
            reversed_component["traversal_orientation"],
        } == {"forward", "reverse"}
        assert stored["distance_km"] == reversed_component["distance_km"]
        assert stored["climb_m"] == reversed_component["descent_m"]
        assert stored["descent_m"] == reversed_component["climb_m"]


def test_four_choices_only_explain_available_hard_facts() -> None:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    for candidate in payload["candidates"]:
        explanation = candidate["rider_explanation"]
        views = explanation["hard_fact_views"]
        assert views["scenery_evidence_status"] == "not_provided"
        assert views["road_surface_evidence_status"] == "not_provided"
        assert views["traffic_evidence_status"] == "not_provided"
        assert views["supply_evidence_status"] == "not_provided"
        assert explanation["forbidden_inferences"]
