from __future__ import annotations

from app.common.geometry_hash import strava_source_geometry_hash
from scripts.analyze_regional_route_cognition import analyze
from app.route_cognition.transit_paths import canonical_sha256


def _hashed(payload, field):
    payload[field] = canonical_sha256(payload)
    return payload


def test_regional_batch_reconciles_and_keeps_profile_pending() -> None:
    observations = []
    bindings = []
    for observation_id, lon in ((1, 112.4), (2, 112.41)):
        points = [[lon, 37.7], [lon + 0.005, 37.705]]
        item = {
            "source_observation_id": observation_id,
            "source_segment_id": str(100 + observation_id),
            "source_name": f"o{observation_id}",
            "source_geometry_hash": strava_source_geometry_hash(points),
            "glo_fact_id": observation_id,
            "glo_algorithm_version": "glo30_meaningful_ascent_v1",
            "derived_distance_m": 1000.0,
            "climb_m": 100.0,
            "descent_m": 5.0,
            "athlete_count": 10,
            "effort_count": 20,
            "star_count": 1,
            "source_point_count": 2,
            "source_geometry_lonlat": points,
        }
        observations.append(item)
        bindings.append({key: item[key] for key in (
            "source_observation_id", "source_segment_id", "source_geometry_hash",
            "glo_fact_id", "glo_algorithm_version", "athlete_count", "effort_count",
            "star_count",
        )})
    source = _hashed(
        {
            "census_batch_id": "census",
            "elevation_fact_batch_id": "facts",
            "observations": observations,
        },
        "slice_sha256",
    )
    selection = _hashed(
        {
            "source_slice_sha256": source["slice_sha256"],
            "included_bindings": bindings,
        },
        "snapshot_sha256",
    )
    pair = {
        "observation_a_id": 1,
        "observation_b_id": 2,
        "pair_key": "1:2",
        "comparison_status": "complete",
        "geometry_hash_a": observations[0]["source_geometry_hash"],
        "geometry_hash_b": observations[1]["source_geometry_hash"],
        "result": {
            "extent_relation": "disjoint",
            "direction_relation": "indeterminate",
        },
    }
    pair["pair_record_sha256"] = canonical_sha256(pair)
    spec = {
        "schema_version": "regional_route_cognition_spec_v1",
        "batch_key": "test",
        "bbox": {"min_lon": 112.3, "max_lon": 112.5, "min_lat": 37.6, "max_lat": 37.8},
        "exact_observation_ids": [1, 2],
        "observation_set_sha256": __import__("hashlib").sha256(b"1\n2").hexdigest(),
        "source_slice_sha256": source["slice_sha256"],
        "selection_snapshot_sha256": selection["snapshot_sha256"],
        "heat_snapshot_cohort": "test",
        "primary_dispositions": [{"disposition": "family", "observation_ids": [1, 2]}],
        "expected_oracle_pairs": [{"pair_key": "1:2", "extent_relation": "disjoint", "direction_relation": "indeterminate"}],
        "families": [{
            "family_key": "one",
            "family_name": "one",
            "family_role": "destination_module",
            "reference_observation_id": 1,
            "resource_observation_id": 1,
            "evidence_observation_ids": [1],
        }],
    }

    result = analyze(spec, source, selection, [pair])

    assert result["exact_observation_ids"] == [1, 2]
    assert result["oracle_summary"]["pair_count"] == 1
    assert result["families"][0]["module_resource_status"] == "glo_profile_pending_readonly_export"
    assert result["database_write_count"] == 0
