from __future__ import annotations

import json
from pathlib import Path

from app.route_cognition.transit_paths import canonical_sha256


PATH = Path("data/research/xishan_route_heat_recommendation_v1.json")


def test_complete_hengling_huaketou_taohuagou_pattern_is_frozen() -> None:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    declared = payload.pop("manifest_sha256")
    assert declared == canonical_sha256(payload)
    assert set(payload["input_bindings"]) == {
        "active_source_slice_sha256",
        "full_ascent_exit_port_sha256",
        "mountain_module_run_sha256",
        "transit_result_sha256",
    }
    assert payload["candidate"]["hard_failure_codes"] == []
    vector = payload["candidate"]["heat_vector"]
    assert payload["recommendation_status"] == "recommended_research_pattern"
    assert vector["distance_km"] == 37.888
    assert vector["climb_m"] == 1100.3
    assert vector["descent_m"] == 390.3
    assert vector["evidence_coverage"] == 0.555101
    assert vector["connector_ratio"] == 0.444899
    assert vector["reach_lower_person_km"] == 7566.493
    assert vector["reach_upper_person_km"] == 10854.163
    assert payload["ranking"]["ranked_candidate_ids"] == [
        "hengling-ascent-huaketou-taohuagou"
    ]
