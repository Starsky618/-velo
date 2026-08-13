from __future__ import annotations

import pytest

from app.route_cognition.transit_paths import canonical_sha256
from scripts.analyze_xishan_transit_path import (
    _write_json_atomic,
    build_run,
    derive_evidence_snapshot,
    derive_selection_snapshot,
    public_manifest,
)


def _provider() -> dict:
    payload = {
        "schema_version": "transit_path_provider_snapshot_v1",
        "transit_key": "a-to-b",
        "provider": "tencent_driving_shadow",
        "provider_observed_at": "2026-08-13",
        "status": "provider_path_not_bicycling_verified",
        "research_verdict": "connection_candidate",
        "from": {
            "port_key": "a:exit",
            "lonlat": [112.4, 37.9],
            "binding_type": "source_observation_candidate",
            "source_observation_id": 1,
            "source_geometry_hash": "a" * 64,
        },
        "to": {
            "port_key": "b:entry",
            "lonlat": [112.409, 37.9],
            "binding_type": "source_observation_candidate",
            "source_observation_id": 2,
            "source_geometry_hash": "b" * 64,
        },
        "distance_m": 790.0,
        "provider_duration_raw": 2,
        "geometry_wgs84": [[112.4, 37.9], [112.409, 37.9]],
        "road_steps": [{"road_name": "测试路", "distance_m": 790.0}],
        "elevation": {
            "algorithm_version": "glo30_meaningful_ascent_v1",
            "point_count": 2,
            "climb_m": 20.0,
            "descent_m": 10.0,
            "profile": [[0.0, 100.0], [0.79, 110.0]],
        },
        "database_write_count": 0,
    }
    payload["snapshot_sha256"] = canonical_sha256(payload)
    return payload


def _profile() -> dict:
    return {
        "profile_key": "test-profile",
        "census_batch_id": "census",
        "elevation_fact_batch_id": "elevation",
        "candidate_count": 2,
        "included_count": 2,
        "excluded_count": 0,
        "excluded_source_segment_ids": [],
    }


def _selection(profile: dict, source_slice: dict | None = None) -> dict:
    return derive_selection_snapshot(source_slice or _source_slice(profile), profile)


def _source_slice(profile: dict) -> dict:
    rows = []
    for observation_id, segment_id, geometry_hash, points in (
        (1, "1", "a" * 64, [[112.4, 37.9], [112.4, 37.90005]]),
        (2, "2", "b" * 64, [[112.409, 37.9], [112.409, 37.90005]]),
    ):
        rows.append(
            {
                "source_observation_id": observation_id,
                "source_segment_id": segment_id,
                "source_geometry_hash": geometry_hash,
                "derived_distance_m": 5.6,
                "glo_fact_id": observation_id,
                "glo_algorithm_version": "glo30_meaningful_ascent_v1",
                "athlete_count": 1,
                "effort_count": 1,
                "star_count": 1,
                "source_name": f"source-{observation_id}",
                "source_geometry_lonlat": points,
            }
        )
    payload = {
        "census_batch_id": profile["census_batch_id"],
        "elevation_fact_batch_id": profile["elevation_fact_batch_id"],
        "observations": rows,
    }
    payload["slice_sha256"] = canonical_sha256(payload)
    return payload


def _evidence(provider_hash: str, selection_hash: str) -> dict:
    payload = {
        "transit_key": "a-to-b",
        "provider_snapshot_sha256": provider_hash,
        "selection_snapshot_sha256": selection_hash,
        "relation_profile_key": "test-profile",
        "evidence_facts": [],
    }
    payload["evidence_snapshot_sha256"] = canonical_sha256(payload)
    return payload


def test_build_run_is_stable_and_public_manifest_removes_geometry() -> None:
    provider = _provider()
    profile = _profile()
    source_slice = _source_slice(profile)
    selection = _selection(profile, source_slice)
    evidence = derive_evidence_snapshot(provider, selection, profile, source_slice)
    first = build_run(provider, evidence, selection, profile, source_slice, {})
    second = build_run(provider, evidence, selection, profile, source_slice, {})
    assert first["result_sha256"] == second["result_sha256"]
    public = public_manifest(first)
    assert "geometry_wgs84" not in public
    assert "ordered_road_steps" not in public
    assert "profile" not in public["elevation"]
    assert public["ordered_road_summary"] == [
        {"road_name": "测试路", "distance_m": 790.0}
    ]
    assert public["provider_snapshot_sha256"] == provider["snapshot_sha256"]
    declared_hash = public.pop("public_manifest_sha256")
    assert declared_hash == canonical_sha256(public)


def test_build_run_rejects_provider_hash_drift() -> None:
    provider = _provider()
    profile = _profile()
    source_slice = _source_slice(profile)
    selection = _selection(profile, source_slice)
    evidence = _evidence(provider["snapshot_sha256"], selection["snapshot_sha256"])
    provider["distance_m"] = 791.0
    with pytest.raises(ValueError, match="hash drift"):
        build_run(provider, evidence, selection, profile, source_slice, {})


def test_build_run_rejects_evidence_hash_drift() -> None:
    provider = _provider()
    profile = _profile()
    source_slice = _source_slice(profile)
    selection = _selection(profile, source_slice)
    evidence = _evidence(provider["snapshot_sha256"], selection["snapshot_sha256"])
    evidence["transit_key"] = "changed"
    with pytest.raises(ValueError, match="evidence snapshot"):
        build_run(provider, evidence, selection, profile, source_slice, {})


def test_build_run_rejects_transit_key_drift() -> None:
    provider = _provider()
    profile = _profile()
    source_slice = _source_slice(profile)
    selection = _selection(profile, source_slice)
    evidence = _evidence(provider["snapshot_sha256"], selection["snapshot_sha256"])
    evidence["transit_key"] = "another-path"
    evidence["evidence_snapshot_sha256"] = canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_snapshot_sha256"}
    )
    with pytest.raises(ValueError, match="exact active-road replay"):
        build_run(provider, evidence, selection, profile, source_slice, {})


def test_build_run_rejects_source_slice_outside_selection_hash() -> None:
    provider = _provider()
    profile = _profile()
    source_slice = _source_slice(profile)
    selection = _selection(profile, source_slice)
    evidence = derive_evidence_snapshot(provider, selection, profile, source_slice)
    mutated = {**source_slice, "observations": [dict(row) for row in source_slice["observations"]]}
    mutated["observations"][0]["source_name"] = "mutated"
    mutated["slice_sha256"] = canonical_sha256(
        {key: value for key, value in mutated.items() if key != "slice_sha256"}
    )
    with pytest.raises(ValueError, match="does not match selection"):
        build_run(provider, evidence, selection, profile, mutated, {})


def test_build_run_rejects_forged_candidate_port_binding() -> None:
    provider = _provider()
    profile = _profile()
    source_slice = _source_slice(profile)
    selection = _selection(profile, source_slice)
    provider["to"]["source_observation_id"] = 1
    provider["to"]["source_geometry_hash"] = "a" * 64
    provider["snapshot_sha256"] = canonical_sha256(
        {key: value for key, value in provider.items() if key != "snapshot_sha256"}
    )
    evidence = derive_evidence_snapshot(provider, selection, profile, source_slice)
    with pytest.raises(ValueError, match="not a source observation endpoint"):
        build_run(provider, evidence, selection, profile, source_slice, {})


def test_atomic_writer_cleans_temp_on_serialization_failure(
    tmp_path,
) -> None:
    output = tmp_path / "run.json"
    with pytest.raises(TypeError):
        _write_json_atomic(output, {"bad": object()})
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []
