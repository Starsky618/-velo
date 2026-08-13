from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.common.geometry_hash import strava_source_geometry_hash
from scripts import analyze_mountain_module as runner
from scripts import export_mountain_module_snapshot as exporter


REPO_ROOT = Path(__file__).resolve().parents[1]


def _snapshot() -> dict:
    def observation(
        observation_id: int,
        source_segment_id: str,
        name: str,
        points: list[list[float]],
        climb: float,
        descent: float,
        athletes: int,
    ) -> dict:
        return {
            "source_observation_id": observation_id,
            "source_segment_id": source_segment_id,
            "source_name": name,
            "source_geometry_hash": strava_source_geometry_hash(points),
            "geometry_normalization_version": "fixture-v1",
            "source_geometry_lonlat": points,
            "source_point_count": len(points),
            "source_fact_id": f"fact-{observation_id}",
            "glo_fact_id": observation_id,
            "glo_algorithm_version": "glo30_meaningful_ascent_v1",
            "derived_distance_m": 1000.0,
            "climb_m": climb,
            "descent_m": descent,
            "elevation_snapshot": [point + [100.0] for point in points],
            "elevation_profile": [[0.0, 100.0], [1.0, 200.0]],
            "athlete_count": athletes,
            "effort_count": athletes * 2,
            "star_count": 10,
        }

    points = [[112.4, 37.98], [112.41, 37.98]]
    reverse = list(reversed(points))
    observations = [
        observation(2, "14942511", "横岭11km爬坡", points, 622.2, 3.4, 532),
        observation(16, "24197317", "横岭下坡", reverse, 0.0, 620.1, 459),
        observation(24, "28417672", "stage-24", points, 34.8, 0.0, 607),
        observation(25, "28417728", "stage-25", points, 139.0, 0.0, 586),
        observation(26, "28417798", "stage-26", points, 119.7, 0.0, 545),
        observation(115, "41966872", "stage-115", points, 57.1, 0.0, 568),
    ]
    payload = {
        "schema_version": "mountain_module_source_slice_v1",
        "module_key": "taiyuan_xishan_hengling",
        "module_kind": "mountain_route_block_research",
        "census_batch_id": "xishan-20260813-v1",
        "elevation_fact_batch_id": "xishan-20260813-v1-glo30-v1-a1",
        "heat_snapshot_cohort": "xishan-20260813-v1",
        "reference_observation_id": 2,
        "observation_ids": [2, 16, 24, 25, 26, 115],
        "excluded_source_segment_ids": [
            "33133333",
            "39979642",
            "40127007",
            "40437410",
            "40589205",
            "40835241",
        ],
        "boundary": "fixture",
        "observations": observations,
        "database_write_count": 0,
        "network_request_count": 0,
    }
    payload["slice_sha256"] = runner._canonical_sha256(payload)
    return payload


def test_runner_is_offline_and_does_not_invent_endpoint_turnaround(
    tmp_path, monkeypatch
):
    spec_data = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )
    snapshot = _snapshot()
    reference = snapshot["observations"][0]
    spec_data["reference_axis"]["source_geometry_hash"] = reference[
        "source_geometry_hash"
    ]
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec_data), encoding="utf-8")
    snapshot_path = tmp_path / "snapshot.json"
    output_path = tmp_path / "run.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    def fail_network(*args, **kwargs):
        raise AssertionError("network must not be used")

    monkeypatch.setattr("socket.socket.connect", fail_network)
    args = runner.argparse.Namespace(
        spec=spec_path,
        snapshot=snapshot_path,
        output=output_path,
    )
    result = runner.run(args)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result["database_write_count"] == 0
    assert result["network_request_count"] == 0
    assert [item["recommendation_status"] for item in payload["route_blocks"]] == [
        "evidence_candidate",
        "evidence_candidate",
    ]
    assert payload["reference_axis_elevation_profile"]
    assert payload["heat_evidence_explanation"]["heat_evidence_mode"] == (
        "partial_identification_vector"
    )
    assert payload["heat_evidence_explanation"]["ranking_status"] == (
        "not_run_by_single_module_slice"
    )
    assert payload["connections"] == []
    assert all(
        port[role]["boundary_semantics"]
        == "source_observation_boundary_not_road_terminal"
        for block in payload["route_blocks"]
        for port in block["traversal_ports"]
        for role in ("entry", "exit")
    )
    assert "out-and-back" not in json.dumps(payload["route_blocks"])


def test_loader_rejects_slice_hash_drift(tmp_path):
    spec_path = REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
    snapshot = _snapshot()
    snapshot["observations"][0]["athlete_count"] += 1
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        runner._load_inputs(spec_path, snapshot_path)


def test_loader_rejects_legacy_v1_and_route_layer_blocker(tmp_path):
    spec = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )
    snapshot = _snapshot()
    spec_path = tmp_path / "spec.json"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    legacy = json.loads(json.dumps(spec))
    legacy["schema_version"] = "mountain_module_spec_v1"
    spec_path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported mountain module spec schema"):
        runner._load_inputs(spec_path, snapshot_path)

    blocked = json.loads(json.dumps(spec))
    blocked["route_blocks"][0]["recommendation_status"] = (
        "blocked_dead_end_turnaround_evidence_missing"
    )
    blocked["route_blocks"][0]["blockers"] = [
        {
            "code": "dead_end_turnaround_evidence_missing",
            "reason": "unsupported in destination evidence layer",
        }
    ]
    spec_path.write_text(json.dumps(blocked), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot embed route blockers"):
        runner._load_inputs(spec_path, snapshot_path)


def test_public_manifest_drops_coordinates_and_profiles():
    snapshot = _snapshot()
    expected_hash = snapshot.pop("slice_sha256")
    snapshot["slice_sha256"] = expected_hash
    spec = json.loads(
            (
                REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
            ).read_text(encoding="utf-8")
        )
    spec["reference_axis"]["source_geometry_hash"] = snapshot["observations"][0][
        "source_geometry_hash"
    ]
    payload = runner.build_run(spec, snapshot)

    manifest = runner.public_manifest(payload)
    serialized = json.dumps(manifest)

    assert "source_geometry_lonlat" not in serialized
    assert "elevation_profile" not in serialized
    assert manifest["database_write_count"] == 0
    assert manifest["network_request_count"] == 0
    assert manifest["connections"] == payload["connections"]
    assert manifest["heat_evidence_explanation"]["learned_utility"]["status"] == (
        "defined_not_executed_by_single_module_slice"
    )


def test_same_runner_accepts_a_different_one_way_module_shape():
    snapshot = _snapshot()
    spec = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )
    spec["module_key"] = "fixture_other_mountain"
    spec["module_name"] = "测试山区"
    spec["module_role"] = "destination_block"
    spec["reference_axis"]["direction_semantics"] = {
        "forward": "clockwise",
        "reverse": "counterclockwise",
    }
    spec["reference_axis"]["source_geometry_hash"] = snapshot["observations"][0][
        "source_geometry_hash"
    ]
    spec["reference_axis"]["source_segment_id"] = "14942511"
    spec["role_requirements"] = [
        {
            "role_key": "main_traversal",
            "observation_id": 2,
            "expected_direction": "forward",
            "min_source_coverage_ratio": 0.99,
            "min_axis_coverage_ratio": 0.99,
        }
    ]
    spec["route_blocks"] = [
        {
            "block_key_suffix": "one-way",
            "name_suffix": "单程",
            "block_role": "destination_traversal",
            "traversals": [
                {
                    "resource_observation_id": 2,
                    "min_resource_alignment_ratio": 0.99,
                    "direction": "forward",
                    "start_measure": "axis_start",
                    "end_measure": "axis_end",
                    "entry_port_key": "one-way:entry",
                    "exit_port_key": "one-way:exit",
                }
            ],
            "recommendation_status": "evidence_candidate",
            "recommendation_reasons": ["完整轴覆盖"],
        }
    ]
    spec["connections"] = []
    snapshot["module_key"] = spec["module_key"]
    snapshot_without_hash = dict(snapshot)
    snapshot_without_hash.pop("slice_sha256")
    snapshot["slice_sha256"] = runner._canonical_sha256(snapshot_without_hash)

    result = runner.build_run(spec, snapshot)

    assert [item["block_name"] for item in result["route_blocks"]] == [
        "测试山区单程"
    ]
    assert result["connections"] == []
    assert result["direction_semantics"]["forward"] == "clockwise"


def test_role_gate_rejects_short_segment_as_full_axis_role():
    snapshot = _snapshot()
    spec = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )
    spec["reference_axis"]["source_geometry_hash"] = snapshot["observations"][0][
        "source_geometry_hash"
    ]
    short = next(
        item
        for item in snapshot["observations"]
        if item["source_observation_id"] == 24
    )
    short["source_geometry_lonlat"] = [
        [112.4, 37.98],
        [112.401, 37.98],
    ]
    short["source_geometry_hash"] = strava_source_geometry_hash(
        short["source_geometry_lonlat"]
    )
    short["elevation_snapshot"] = [
        point + [100.0] for point in short["source_geometry_lonlat"]
    ]
    spec["role_requirements"][0]["observation_id"] = 24

    with pytest.raises(ValueError, match="axis coverage insufficient"):
        runner.build_run(spec, snapshot)


def test_route_resource_cannot_be_short_duplicated_or_false_connected(tmp_path):
    snapshot = _snapshot()
    spec = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )
    spec["reference_axis"]["source_geometry_hash"] = snapshot["observations"][0][
        "source_geometry_hash"
    ]
    short = next(
        item
        for item in snapshot["observations"]
        if item["source_observation_id"] == 24
    )
    short["source_geometry_lonlat"] = [[112.4, 37.98], [112.401, 37.98]]
    short["source_geometry_hash"] = strava_source_geometry_hash(
        short["source_geometry_lonlat"]
    )
    short["elevation_snapshot"] = [
        point + [100.0] for point in short["source_geometry_lonlat"]
    ]
    spec["route_blocks"][0]["traversals"][0][
        "resource_observation_id"
    ] = 24
    with pytest.raises(ValueError, match="does not align"):
        runner.build_run(spec, snapshot)

    duplicate_spec = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )
    duplicate_spec["reference_axis"]["source_geometry_hash"] = snapshot[
        "observations"
    ][0]["source_geometry_hash"]
    duplicate_spec["route_blocks"][0]["traversals"] = [
        duplicate_spec["route_blocks"][0]["traversals"][0],
        duplicate_spec["route_blocks"][0]["traversals"][0],
    ]
    duplicate_spec_path = tmp_path / "duplicate-spec.json"
    duplicate_snapshot_path = tmp_path / "duplicate-snapshot.json"
    duplicate_spec_path.write_text(json.dumps(duplicate_spec), encoding="utf-8")
    duplicate_snapshot_without_hash = dict(snapshot)
    duplicate_snapshot_without_hash.pop("slice_sha256", None)
    snapshot["slice_sha256"] = runner._canonical_sha256(
        duplicate_snapshot_without_hash
    )
    duplicate_snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one traversal"):
        runner._load_inputs(duplicate_spec_path, duplicate_snapshot_path)
    with pytest.raises(ValueError, match="exactly one traversal"):
        runner.build_run(duplicate_spec, snapshot)

    connection_spec = json.loads(json.dumps(spec))
    connection_spec["route_blocks"][0]["traversals"][0][
        "resource_observation_id"
    ] = 2
    connection_spec["connections"] = [
        {
            "connection_key_suffix": "invented-direct-edge",
            "from_port_key": "full-ascent:base-entry",
            "to_port_key": "full-ascent:upper-observation-boundary-exit",
            "status": "verified_connected",
            "evidence_ref": "fake",
            "reason": "fixture",
        }
    ]
    connection_spec_path = tmp_path / "connection-spec.json"
    connection_snapshot_path = tmp_path / "connection-snapshot.json"
    connection_spec_path.write_text(
        json.dumps(connection_spec), encoding="utf-8"
    )
    connection_snapshot_without_hash = dict(snapshot)
    connection_snapshot_without_hash.pop("slice_sha256", None)
    snapshot["slice_sha256"] = runner._canonical_sha256(
        connection_snapshot_without_hash
    )
    connection_snapshot_path.write_text(
        json.dumps(snapshot), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="cannot embed route connections"):
        runner._load_inputs(connection_spec_path, connection_snapshot_path)

    partial_spec = json.loads(json.dumps(connection_spec))
    partial_spec["connections"] = []
    partial_spec["route_blocks"][0]["traversals"][0]["end_measure"] = 500.0
    with pytest.raises(ValueError, match="does not align"):
        runner.build_run(partial_spec, snapshot)

    bypass_spec = json.loads(json.dumps(partial_spec))
    bypass_spec["route_blocks"][0]["traversals"][0][
        "min_resource_alignment_ratio"
    ] = 0.0
    with pytest.raises(ValueError, match="below the global minimum"):
        runner.build_run(bypass_spec, snapshot)


def test_generic_mechanical_files_do_not_embed_region_names():
    paths = (
        REPO_ROOT / "app/route_cognition/mountain_modules.py",
        REPO_ROOT / "scripts/analyze_mountain_module.py",
        REPO_ROOT / "scripts/export_mountain_module_snapshot.py",
    )

    for path in paths:
        content = path.read_text(encoding="utf-8").lower()
        for token in ("hengling", "taohuagou", "横岭", "桃花沟"):
            assert token not in content, f"{path.name} embeds {token}"


def test_snapshot_exporter_rejects_coordinate_output_outside_artifact(tmp_path):
    spec = json.loads(
        (
            REPO_ROOT / "data/research/mountain_modules/hengling_v1.json"
        ).read_text(encoding="utf-8")
    )

    with pytest.raises(ValueError, match="artifact_location"):
        exporter._validated_output_path(spec, tmp_path / "source.json")
