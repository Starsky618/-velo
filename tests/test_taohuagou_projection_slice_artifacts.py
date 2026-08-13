import hashlib
import json
from pathlib import Path

from scripts.analyze_taohuagou_carrier_projection import (
    _load_inputs,
    _source_geometry_hash,
    build_run,
    write_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CARRIER_PATH = REPO_ROOT / "data/research/taohuagou_carrier_candidate_v1.json"
SLICE_PATH = REPO_ROOT / "data/research/taohuagou_projection_slice_v1.json"
MANIFEST_PATH = (
    REPO_ROOT / "data/research/taohuagou_carrier_projection_v1_manifest.json"
)


def _canonical_geometry_hash(points: list[list[float]]) -> str:
    payload = json.dumps(points, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_taohuagou_carrier_candidate_freezes_provider_identity_and_geometry():
    carrier = json.loads(CARRIER_PATH.read_text(encoding="utf-8"))

    assert carrier["provider"] == "openstreetmap"
    assert carrier["provider_object_id"] == "840111674"
    assert carrier["provider_object_version"] == 6
    assert carrier["status"] == "research_candidate_not_carrier_graph_truth"
    assert carrier["access_state"] == "unknown"
    assert len(carrier["topology_identity"]["node_ids"]) == 389
    assert len(carrier["geometry_lonlat"]) == 389
    assert carrier["geometry_sha256"] == _canonical_geometry_hash(
        carrier["geometry_lonlat"]
    )
    assert (
        carrier["source_snapshot"]["historical_crosscheck"][
            "provider_object_geometry_agreement"
        ]
        == "exact_coordinate_sequence"
    )
    assert "OpenStreetMap contributors" in carrier["attribution"]


def test_taohuagou_slice_binds_exact_seven_source_and_glo_facts():
    value = json.loads(SLICE_PATH.read_text(encoding="utf-8"))
    observations = value["observations"]

    assert value["carrier_candidate_id"] == "osm-way-840111674-v6"
    assert value["census_batch_id"] == "xishan-20260813-v1"
    assert value["elevation_fact_batch_id"] == "xishan-20260813-v1-glo30-v1-a1"
    assert value["selection_policy"]["observation_count"] == 7
    assert [item["source_observation_id"] for item in observations] == [
        22,
        44,
        46,
        47,
        70,
        81,
        92,
    ]
    assert len({item["source_segment_id"] for item in observations}) == 7
    assert len({item["source_geometry_hash"] for item in observations}) == 7
    assert len({item["source_fact_id"] for item in observations}) == 7
    assert all(
        item["geometry_normalization_version"]
        == "strava_source_line_lonlat_7dp_v1"
        for item in observations
    )
    assert all(
        item["glo_algorithm_version"] == "glo30_meaningful_ascent_v1"
        for item in observations
    )
    assert all(item["athlete_count"] is not None for item in observations)
    assert all(item["effort_count"] is not None for item in observations)
    assert all(item["star_count"] is not None for item in observations)
    assert all(
        len(item["source_geometry_lonlat"]) >= 2
        and _source_geometry_hash(item["source_geometry_lonlat"])
        == item["source_geometry_hash"]
        for item in observations
    )


def test_frozen_projection_manifest_matches_deterministic_replay(tmp_path):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    carrier, slice_input = _load_inputs(CARRIER_PATH, SLICE_PATH)
    result = build_run(carrier, slice_input)
    cells = result["directed_evidence"]["cells"]
    generated_paths = write_artifacts(
        tmp_path,
        result=result,
        carrier_path=CARRIER_PATH,
        slice_path=SLICE_PATH,
    )
    generated_manifest = json.loads(
        Path(generated_paths["manifest"]).read_text(encoding="utf-8")
    )

    assert manifest["inputs"]["carrier_input_sha256"] == hashlib.sha256(
        CARRIER_PATH.read_bytes()
    ).hexdigest()
    assert manifest["inputs"]["slice_input_sha256"] == hashlib.sha256(
        SLICE_PATH.read_bytes()
    ).hexdigest()
    assert manifest["run_sha256"] == result["run_sha256"]
    for hash_field in (
        "projection_artifact_sha256",
        "evidence_artifact_sha256",
        "directed_evidence_result_sha256",
    ):
        assert manifest[hash_field] == generated_manifest[hash_field]
    assert manifest["projection_direction_counts"] == result[
        "projection_direction_counts"
    ]
    assert manifest["accepted_posting_count"] == result[
        "accepted_posting_count"
    ]
    assert manifest["directed_evidence_support_state_counts"] == result[
        "directed_evidence_support_state_counts"
    ]
    assert manifest["directed_evidence_cell_count"] == len(cells)
    assert manifest["maximum_cell_source_fact_count"] == max(
        cell["raw_support_count"] for cell in cells
    )
    observation_70 = next(
        item
        for item in result["projections"]
        if item["source_observation_id"] == 70
    )
    runs = observation_70["result"]["matched_runs"]
    assert len(runs) == 2
    assert runs[0]["source_interval_m"][1] <= 415
    assert runs[1]["source_interval_m"][0] >= 435
    assert runs[0]["carrier_interval_m"][1] < runs[1]["carrier_interval_m"][0]
    assert manifest["parameter_promotion_status"] == (
        "research_probe_unpromoted"
    )
    assert manifest["evidence_eligibility"] == (
        "shadow_only_not_route_ranking_input"
    )
