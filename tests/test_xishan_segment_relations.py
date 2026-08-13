from dataclasses import replace
import hashlib
import json
from pathlib import Path

from app.route_cognition.spatial_relations import SpatialRelationConfig
from scripts.analyze_xishan_segment_relations import (
    RelationObservationInput,
    build_relation_oracle,
    generate_candidate_pairs,
    write_artifact,
)


CONFIG = SpatialRelationConfig(
    version="test-v1",
    sample_spacing_m=10.0,
    match_distance_m=8.0,
    max_heading_delta_deg=30.0,
    min_component_length_m=20.0,
    max_component_gap_m=20.0,
    measure_backtrack_tolerance_m=10.0,
    max_measure_jump_ratio=3.0,
    projection_ambiguity_distance_m=1.0,
    projection_ambiguity_measure_separation_m=30.0,
    component_dedup_min_interval_overlap=0.80,
    equivalent_min_coverage=0.95,
    containment_min_coverage=0.95,
    containment_max_container_coverage=0.90,
    partial_min_coverage=0.10,
    disjoint_max_coverage=0.01,
    parallel_ambiguity_min_coverage=0.50,
    parallel_ambiguity_min_separation_m=5.0,
    parallel_ambiguity_max_distance_spread_m=3.0,
    self_overlap_distance_m=5.0,
    self_overlap_measure_separation_m=30.0,
    coordinate_decimals=7,
    metric_decimals=3,
)


def _observation(
    observation_id: int,
    points: tuple[tuple[float, float], ...],
) -> RelationObservationInput:
    return RelationObservationInput(
        source_observation_id=observation_id,
        source_segment_id=str(10_000_000 + observation_id),
        source_name=f"segment-{observation_id}",
        source_geometry_hash=f"{observation_id:064x}",
        geometry_normalization_version="norm-v1",
        geometry_resolution="high",
        point_count=len(points),
        points=points,
        source_length_m=100.0,
        source_exact_directed_hash=f"{observation_id:064x}",
        source_exact_undirected_hash=f"{observation_id:064x}",
        glo_fact_id=observation_id,
        glo_fact_batch_id="glo-v1",
        glo_fact_status="complete",
        glo_algorithm_version="glo-v1",
        glo_climb_m=10.0,
        glo_descent_m=2.0,
        athlete_count=1,
        effort_count=2,
        star_count=0,
    )


def _identity() -> dict:
    return {
        "profile_key": "test-profile",
        "profile_sha256": "a" * 64,
        "candidate_observation_set_hash": "b" * 64,
        "census_batch_id": "census-v1",
        "elevation_fact_batch_id": "glo-v1",
        "judgment_run_id": 20,
        "foundation_status": "mechanically_aligned_for_relation_algorithm_design",
        "census_enumeration_status": "indeterminate",
    }


def test_oracle_enumerates_every_unordered_pair_and_is_permutation_stable():
    observations = [
        _observation(3, ((112.0, 37.0), (112.001, 37.0))),
        _observation(1, ((112.0, 37.0), (112.0, 37.001))),
        _observation(2, ((112.01, 37.01), (112.011, 37.01))),
    ]
    manifest, pairs = build_relation_oracle(
        observations,
        config=CONFIG,
        run_identity=_identity(),
    )
    replay_manifest, replay_pairs = build_relation_oracle(
        list(reversed(observations)),
        config=CONFIG,
        run_identity=_identity(),
    )

    assert manifest["expected_pair_count"] == 3
    assert manifest["emitted_pair_count"] == 3
    assert manifest["fully_computed_pair_count"] == 3
    assert manifest["truncated_pair_count"] == 0
    assert [pair["pair_key"] for pair in pairs] == ["1:2", "1:3", "2:3"]
    assert pairs == replay_pairs
    assert manifest["ordered_output_sha256"] == replay_manifest["ordered_output_sha256"]
    assert manifest["database_write_count"] == 0


def test_candidate_index_recalls_near_subcurves_and_rejects_far_pair():
    near_a = _observation(1, ((112.0, 37.0), (112.003, 37.0)))
    near_b = _observation(2, ((112.001, 37.00002), (112.002, 37.00002)))
    far = _observation(3, ((113.0, 38.0), (113.001, 38.0)))

    assert generate_candidate_pairs(
        [near_a, near_b, far], expansion_m=8.0, chunk_length_m=100.0
    ) == {(1, 2)}


def test_artifact_hashes_bind_canonical_inputs_pairs_and_review_subset(tmp_path):
    observations = [
        _observation(1, ((112.0, 37.0), (112.002, 37.0))),
        _observation(2, ((112.001, 37.0), (112.003, 37.0))),
    ]
    manifest, pairs = build_relation_oracle(
        observations,
        config=CONFIG,
        run_identity=_identity(),
    )
    paths = write_artifact(
        tmp_path,
        manifest=manifest,
        observations=observations,
        pairs=pairs,
    )

    stored = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    assert stored["input_artifact_sha256"] == hashlib.sha256(
        Path(paths["inputs"]).read_bytes()
    ).hexdigest()
    assert stored["pair_artifact_sha256"] == hashlib.sha256(
        Path(paths["pairs"]).read_bytes()
    ).hexdigest()
    assert stored["review_artifact_sha256"] == hashlib.sha256(
        Path(paths["review"]).read_bytes()
    ).hexdigest()
    assert Path(paths["inputs"]).read_text(encoding="utf-8").count("\n") == 2
    assert Path(paths["pairs"]).read_text(encoding="utf-8").count("\n") == 1
    assert stored["review_pair_count"] in {0, 1}


def test_duplicate_observation_or_strava_id_is_rejected():
    left = _observation(1, ((112.0, 37.0), (112.001, 37.0)))
    duplicate_observation = replace(
        _observation(2, ((112.01, 37.01), (112.011, 37.01))),
        source_observation_id=1,
    )
    duplicate_strava = replace(
        _observation(2, ((112.01, 37.01), (112.011, 37.01))),
        source_segment_id=left.source_segment_id,
    )

    for bad in (duplicate_observation, duplicate_strava):
        try:
            build_relation_oracle(
                [left, bad], config=CONFIG, run_identity=_identity()
            )
        except ValueError:
            pass
        else:
            raise AssertionError("重复关系输入必须失败")
