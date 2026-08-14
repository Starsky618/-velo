"""西山全部单轴与真实长路线的 3D ClimbPro 冻结门。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import CheckConstraint


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data/research/xishan_climb_catalog_v1.json"
RESULT_PATH = ROOT / "data/research/xishan_climb_catalog_v1_result.json"


def _canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _self_hash(value: dict, field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return _canonical_sha256(payload)


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_catalog_has_all_axes_both_directions_and_hash_chain():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["catalog_spec_sha256"] == _canonical_sha256(spec)
    assert result["result_sha256"] == _self_hash(result, "result_sha256")
    assert result["axis_count"] == len(spec["axes"]) == 25
    assert result["directional_axis_result_count"] == 50
    assert result["partial_climb_count"] == len(spec["partial_climbs"]) == 6
    assert len(result["axes"]) == 25
    assert len({row["module_key"] for row in result["axes"]}) == 25
    assert sum(row["extent_status"] == "full_verified" for row in result["axes"]) == 3
    assert sum(row["extent_status"] == "full_candidate" for row in result["axes"]) == 15
    assert result["source_batches"] == spec["source_batches"]

    for axis in result["axes"]:
        module_spec = json.loads((ROOT / axis["module_spec_path"]).read_text(encoding="utf-8"))
        assert axis["module_spec_sha256"] == _canonical_sha256(module_spec)
        assert axis["census_batch_id"] == module_spec["census_batch_id"]
        assert axis["elevation_fact_batch_id"] == module_spec[
            "elevation_fact_batch_id"
        ]
        assert axis["axis_result_sha256"] == _self_hash(axis, "axis_result_sha256")
        assert set(axis["directions"]) == {"forward", "reverse"}
        forward = axis["directions"]["forward"]
        reverse = axis["directions"]["reverse"]
        assert forward["direction_result_sha256"] == _self_hash(
            forward, "direction_result_sha256"
        )
        assert reverse["direction_result_sha256"] == _self_hash(
            reverse, "direction_result_sha256"
        )
        assert forward["route_distance_m"] == reverse["route_distance_m"]
        assert forward["stored_glo_meaningful_ascent_m"] == reverse[
            "stored_glo_meaningful_descent_m"
        ]
        assert forward["stored_glo_meaningful_descent_m"] == reverse[
            "stored_glo_meaningful_ascent_m"
        ]
        for direction in (forward, reverse):
            checks = direction["climb_plan"]["source"]["quality_checks"]
            assert checks["profile_complete_for_input_extent"] is True
            assert checks["profile_complete_for_route"] is False
            assert direction["elevation_profile"]
        if axis["extent_status"] == "full_verified":
            assert forward["climb_plan"]["input_contract"]["anchor_evidence_refs"]
            assert forward["climb_plan"]["source"]["quality_checks"][
                "profile_complete_for_named_climb"
            ] is True


def test_exact_zaodu_is_cat2_but_new_duguan_is_a_3d_corridor_not_one_climb():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    axes = {row["module_key"]: row for row in result["axes"]}

    zaodu = axes["taiyuan_xishan_zaodu_road"]
    assert zaodu["extent_status"] == "full_candidate"
    assert zaodu["source_observation_id"] == 116
    assert zaodu["glo_fact_id"] == 88
    zaodu_forward = zaodu["directions"]["forward"]
    assert zaodu_forward["route_distance_m"] == 8825.4
    assert zaodu_forward["stored_glo_meaningful_ascent_m"] == 469.9
    assert len(zaodu_forward["climb_plan"]["climbs"]) == 1
    zaodu_climb = zaodu_forward["climb_plan"]["climbs"][0]
    assert zaodu_climb["category"] == "2"
    assert zaodu_climb["category_status"] == "candidate"
    assert zaodu_climb["shape"] == "long_sustained"
    assert zaodu_climb["max_sustained_grade_pct"] == {"500m": 9.1, "1000m": 8.4}
    assert zaodu["directions"]["reverse"]["climb_plan"]["climbs"] == []

    new_duguan = axes["taiyuan_xishan_duguan_new_tourism"]
    assert new_duguan["scope_kind"] == "road_corridor"
    assert new_duguan["extent_status"] == "not_applicable_corridor"
    assert new_duguan["source_observation_id"] == 117
    assert new_duguan["glo_fact_id"] == 89
    new_duguan_forward = new_duguan["directions"]["forward"]
    assert new_duguan_forward["route_distance_m"] == 15022.5
    assert new_duguan_forward["stored_glo_meaningful_ascent_m"] == 296.8
    assert new_duguan_forward["climb_plan"]["climbs"] == []
    assert new_duguan_forward["climb_plan"]["composition"]["sequence_label"] == (
        "无显著爬坡"
    )
    assert new_duguan["directions"]["reverse"]["climb_plan"]["climbs"] == []


def test_aoshen_and_langpo_are_not_mislabelled_as_steady_easy_climbs():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    axes = {row["module_key"]: row for row in result["axes"]}

    aoshen = axes["taiyuan_xishan_wanmu_aoshen"]["directions"]["forward"]
    aoshen_climb = aoshen["climb_plan"]["climbs"][0]
    assert aoshen_climb["category"] == "2"
    assert aoshen_climb["shape"] == "late_wall"
    assert aoshen_climb["shape"] != "steady"

    langpo = axes["taiyuan_xishan_langpo"]["directions"]["forward"]
    langpo_climb = langpo["climb_plan"]["climbs"][0]
    assert langpo_climb["category"] == "3"
    assert langpo_climb["shape"] == "short_wall"
    assert langpo_climb["shape"] != "steady"


def test_known_half_climbs_keep_parent_and_offsets_without_duplicate_full_axis():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    partials = {row["partial_key"]: row for row in result["partial_climbs"]}
    assert set(partials) == {
        "langpo_yaoyuege_local",
        "langpo_front_local",
        "aoshen_reverse_partial",
        "duguan_steep_local",
        "duguan_upper_local",
        "duguan_gate_upper_local",
    }
    for row in partials.values():
        assert row["end_offset_m"] > row["start_offset_m"] >= 0
        assert row["partial_result_sha256"] == _self_hash(
            row, "partial_result_sha256"
        )
        contract = row["profile_replay"]["climb_plan"]["input_contract"]
        assert contract["extent_status"] == "partial"
        assert contract["parent_scope_key"] == row["parent_module_key"]
        assert contract["start_offset_m"] == row["start_offset_m"]
        assert contract["end_offset_m"] == row["end_offset_m"]
        assert row["projection_result_sha256"]
        assert row["evidence_source_geometry_hash"] in contract[
            "source_geometry_hashes"
        ]
        assert row["source_coverage_ratio"] > 0
        checks = row["profile_replay"]["climb_plan"]["source"]["quality_checks"]
        assert checks["profile_complete_for_input_extent"] is True
        assert checks["profile_complete_for_named_climb"] is False


def test_long_routes_have_complete_ordered_profiles_and_typed_rejection():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    assert result["long_route_count"] == 11
    assert result["long_route_hard_feasible_count"] == 10
    assert result["long_route_hard_rejected_count"] == 1

    rejected = [row for row in result["long_routes"] if row["status"] == "hard_rejected"]
    assert rejected == [
        {
            "candidate_id": "long-taigu-diantou-mengshan-north-west",
            "choice_name": "太古路—店头—蒙山—北侧—西门",
            "status": "hard_rejected",
            "hard_failure_codes": ["immediate_full_source_retrace"],
        }
    ]
    for route in result["long_routes"]:
        if route["status"] == "hard_rejected":
            continue
        assert route["route_result_sha256"] == _self_hash(route, "route_result_sha256")
        assert route["ordered_components"]
        for component in route["ordered_components"][1:]:
            assert component["endpoint_gap_from_previous_m"] <= 50.0
        checks = route["profile_replay"]["climb_plan"]["source"]["quality_checks"]
        assert checks["profile_complete_for_route"] is True
        assert checks["profile_complete_for_named_climb"] is False


def test_public_catalog_contains_no_private_coordinates():
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    forbidden = {
        "geometry_wgs84",
        "source_geometry_lonlat",
        "coordinates",
        "lonlat",
        "source_line_wkt",
        "elevation_snapshot",
    }
    assert forbidden.isdisjoint(set(_walk_keys(result)))


def test_legacy_gpx_geometry_sources_are_retired_from_content_tree():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    retired = [ROOT / row["path"] for row in spec["legacy_geometry_retirement"]]
    assert len(retired) == 6
    assert all(not path.exists() for path in retired)
    assert list((ROOT / "content/routes").glob("*/track.gpx")) == []


def test_route_book_schema_and_publisher_accept_only_typed_strava_projection():
    from app.route_book.models import RouteBook, RouteGuide, RouteVersion
    from scripts.publish_climb_routes import _load_catalog

    spec, result = _load_catalog(SPEC_PATH, RESULT_PATH)
    assert len(spec["publication_exclusions"]) == 1
    assert result["route_guide_bindings"] == spec["route_guide_bindings"]

    checks = {
        constraint.name: str(constraint.sqltext)
        for table in (RouteBook.__table__, RouteVersion.__table__, RouteGuide.__table__)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "strava_projection" in checks["ck_route_books_source"]
    assert "strava_projection" in checks["ck_route_books_file_type_source"]
    assert "strava_projection" in checks["ck_route_versions_geometry_source"]
    assert "strava_projection" not in checks["ck_route_guides_content_origin"]

    migration = (
        ROOT / "migrations/versions/20260814_climb_projection.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "20260814_climb_projection"' in migration
    assert 'down_revision = "20260813_seg_elev_facts"' in migration
