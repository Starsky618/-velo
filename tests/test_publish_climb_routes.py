"""Strava/GLO 路书发布器的双向、长线与稳定身份行为门。"""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

from app.common.geometry_hash import strava_source_geometry_hash
from app.elevation.dem_client import (
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_ACCURACY_M,
)
from app.elevation.climb_profile_contract import (
    ClimbProfileContract,
    build_climb_plan_from_contract,
)
from app.elevation.route_elevation import ROUTE_ELEVATION_METHOD
from app.parsing.geo_math import haversine
from app.route_book.elevation_quality import has_elevation_metadata_method
from app.route_book.elevation_workflow import _merged_navigation_metadata
from scripts import publish_climb_routes as publisher
import pytest


POINTS = [[112.0, 37.0], [112.001, 37.001], [112.002, 37.002]]
ELEVATIONS = [100.0, 120.0, 110.0]
SOURCE_HASH = strava_source_geometry_hash(POINTS)
METHOD = "glo30_meaningful_ascent_v1_snapshot_replay_v1"


def _row():
    distance = sum(
        haversine(left[1], left[0], right[1], right[0])
        for left, right in zip(POINTS, POINTS[1:])
    )
    observation = SimpleNamespace(
        source_segment_id="123",
        source_url="https://www.strava.com/segments/123",
    )
    fact = SimpleNamespace(
        id=9,
        fact_batch_id="facts-v1",
        source_geometry_hash=SOURCE_HASH,
        derived_distance_m=distance,
        climb_m=20.0,
        descent_m=10.0,
    )
    return observation, fact, POINTS, ELEVATIONS


def _axis_plan(direction: str) -> dict:
    points, elevations = publisher._directional_values(POINTS, ELEVATIONS, direction)
    result = build_climb_plan_from_contract(
        points,
        elevations,
        contract=ClimbProfileContract(
            scope_key="test-axis",
            scope_kind="named_climb",
            extent_status="full_candidate",
            traversal_direction=direction,
            geometry_source="strava_full_segment_projection",
            start_anchor="base" if direction == "forward" else "summit",
            end_anchor="summit" if direction == "forward" else "base",
            source_observation_ids=(1,),
            source_geometry_hashes=(SOURCE_HASH,),
        ),
        source_method=METHOD,
    )
    return result.climb_plan


def _projection(*, transit_statuses: tuple[str, ...] = ()) -> publisher.ProjectionInput:
    elevation_result = build_climb_plan_from_contract(
        POINTS,
        ELEVATIONS,
        contract=ClimbProfileContract(
            scope_key="test-axis",
            scope_kind="named_climb",
            extent_status="full_candidate",
            traversal_direction="forward",
            geometry_source="strava_full_segment_projection",
            start_anchor="base",
            end_anchor="summit",
            source_observation_ids=(1,),
            source_geometry_hashes=(SOURCE_HASH,),
        ),
        source_method=METHOD,
    )
    return publisher.ProjectionInput(
        route_key="test-axis:forward",
        module_key="test-axis",
        module_name="测试整轴",
        projection_kind="long_route" if transit_statuses else "axis",
        traversal_direction="forward",
        scope_kind="named_climb",
        extent_status="full_candidate",
        module_spec_sha256="a" * 64,
        observation_id=1,
        source_segment_id="123",
        source_url="https://www.strava.com/segments/123",
        source_geometry_hash=SOURCE_HASH,
        source_line_wkt="LINESTRING (112 37, 112.001 37.001, 112.002 37.002)",
        fact_id=9,
        fact_batch_id="facts-v1",
        derived_distance_m=elevation_result.climb_plan["route_distance_m"],
        stored_climb_m=20.0,
        stored_descent_m=10.0,
        elevation_result=elevation_result,
        projection_identity_sha256="b" * 64,
        transit_provider_statuses=transit_statuses,
    )


def test_axis_preflight_emits_forward_and_reverse_from_one_physical_geometry(
    monkeypatch, tmp_path
):
    spec = {
        "module_key": "test-axis",
        "module_name": "测试整轴",
        "census_batch_id": "census-v2",
        "elevation_fact_batch_id": "facts-v2",
        "axis_profile_observation_id": 1,
        "reference_axis": {
            "source_segment_id": "123",
            "source_geometry_hash": SOURCE_HASH,
            "direction_semantics": {"forward": "base", "reverse": "summit"},
            "selection_basis": "candidate axis",
        },
    }
    spec_path = tmp_path / "axis.json"
    spec_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publisher, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(publisher, "_load_json", lambda _path: spec)
    source_binding_calls = []

    def source_row(*args):
        source_binding_calls.append(args[1:])
        return _row()

    monkeypatch.setattr(publisher, "_production_profile_row", source_row)
    catalog = {
        "axes": [
            {
                "module_spec": "axis.json",
                "scope_kind": "named_climb",
                "extent_status": "full_candidate",
            }
        ],
        "publication_exclusions": [],
        "profile_source_method": METHOD,
    }
    result = {
        "axes": [
            {
                "module_key": "test-axis",
                "directions": {
                    "forward": {"climb_plan": _axis_plan("forward")},
                    "reverse": {"climb_plan": _axis_plan("reverse")},
                },
            }
        ]
    }

    projections = publisher._preflight_projections(object(), catalog, result)

    assert [row.traversal_direction for row in projections] == ["forward", "reverse"]
    assert projections[0].source_geometry_hash == projections[1].source_geometry_hash
    assert projections[0].stored_climb_m == projections[1].stored_descent_m == 20.0
    assert projections[0].stored_descent_m == projections[1].stored_climb_m == 10.0
    assert projections[0].source_line_wkt != projections[1].source_line_wkt
    assert source_binding_calls == [("census-v2", "facts-v2", 1)]
    assert projections[0].fact_batch_ids == ("facts-v1",)


def test_long_route_preflight_persists_complete_composition_climb_plan(monkeypatch):
    monkeypatch.setattr(publisher, "_production_profile_row", lambda *_args: _row())
    contract = ClimbProfileContract(
        scope_key="long-one",
        scope_kind="route_composition",
        extent_status="complete_route_composition",
        traversal_direction="geometry_order",
        geometry_source="frozen_source_and_transit_component_composition",
        start_anchor="route_start:first",
        end_anchor="route_end:first",
        source_observation_ids=(1,),
        source_geometry_hashes=(SOURCE_HASH,),
    )
    expected = build_climb_plan_from_contract(
        POINTS,
        ELEVATIONS,
        contract=contract,
        source_method="frozen_component_profile_composition_v1",
    )
    component = {
        "kind": "source_corridor",
        "occurrence_id": "first",
        "source_observation_id": 1,
        "source_geometry_hash": SOURCE_HASH,
        "traversal_direction": "forward",
        "endpoint_gap_from_previous_m": None,
    }
    result = {
        "long_route_hard_feasible_count": 1,
        "long_routes": [
            {
                "candidate_id": "long-one",
                "choice_name": "测试长线",
                "status": "hard_feasible_research_candidate",
                "route_result_sha256": "b" * 64,
                "ordered_components": [component],
                "choice_fact_totals": {
                    "distance_m": expected.climb_plan["route_distance_m"],
                    "climb_m": 20.0,
                    "descent_m": 10.0,
                },
                "profile_replay": {"climb_plan": expected.climb_plan},
            }
        ],
    }

    projections = publisher._preflight_long_route_projections(
        object(),
        {"census_batch_id": "census-v1", "elevation_fact_batch_id": "facts-v1"},
        result,
        transit_runs={},
    )

    assert len(projections) == 1
    projection = projections[0]
    assert projection.projection_kind == "long_route"
    assert projection.route_key == "long:long-one"
    assert projection.elevation_result.climb_plan["input_contract"][
        "extent_status"
    ] == "complete_route_composition"
    assert projection.fact_batch_ids == ("facts-v1",)


def test_routebook_identity_does_not_change_with_canonical_segment_revision(monkeypatch):
    monkeypatch.setattr(publisher, "_production_profile_row", lambda *_args: _row())
    projection = publisher._preflight_long_route_projections
    assert callable(projection)
    axis = SimpleNamespace(route_key="test-axis:forward")
    first = publisher._source_ref(axis)
    axis.source_segment_id = "new-segment"
    assert publisher._source_ref(axis) == first == "strava:projection:test-axis:forward"


def test_projection_metadata_uses_trusted_glo_contract_and_keeps_replay_provenance():
    projection = _projection()
    extra = publisher._projection_elevation_metadata(
        projection,
        catalog={"catalog_key": "catalog-v1", "profile_source_method": METHOD},
        catalog_result={"result_sha256": "c" * 64},
    )
    metadata = _merged_navigation_metadata(
        None,
        source_name=GLO30_SOURCE_NAME,
        license_id=GLO30_LICENSE_ID,
        accuracy_m=GLO30_VERTICAL_ACCURACY_M,
        point_count=projection.elevation_result.point_count,
        method=ROUTE_ELEVATION_METHOD,
        timestamp_field="projected_at",
        extra_metadata=extra,
        climb_plan=projection.elevation_result.climb_plan,
    )

    assert has_elevation_metadata_method(
        json.dumps(metadata),
        expected_count=projection.elevation_result.point_count,
    )
    assert metadata["elevation"]["projection"]["profile_replay_method"] == METHOD


def test_apply_keeps_unverified_transit_as_unlisted_draft(monkeypatch):
    projection = _projection(
        transit_statuses=("connectivity_shadow_not_access_verified",)
    )
    captured = {}

    class Query:
        def filter(self, *_args):
            return self

        def one_or_none(self):
            return None

        def scalar(self):
            return 0

    class DB:
        def query(self, _model):
            return Query()

        def add(self, row):
            if getattr(row, "id", None) is None:
                row.id = 101

        def flush(self):
            return None

    def capture_write(_db, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(publisher, "write_route_elevation_result", capture_write)

    route, version = publisher._apply_projection(
        DB(),
        projection,
        guide_by_module={},
        catalog={"catalog_key": "catalog-v1", "profile_source_method": METHOD},
        catalog_result={"result_sha256": "c" * 64},
    )

    assert route.visibility == "unlisted"
    assert route.publish_status == "draft"
    assert version.navigation_status == "pending"
    assert json.loads(version.validation_warnings_json) == [
        "transit_access_not_verified:connectivity_shadow_not_access_verified"
    ]
    assert captured["method"] == ROUTE_ELEVATION_METHOD
    assert captured["extra_metadata"]["projection"]["transit_provider_statuses"] == [
        "connectivity_shadow_not_access_verified"
    ]


def test_guide_binding_refuses_to_take_over_user_routebook():
    guide = SimpleNamespace(name="奥申", route_book_id=77)
    user_route = SimpleNamespace(
        id=77,
        creator_id=5,
        is_official=False,
        source="file_upload",
    )

    class Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *_args):
            return self

        def one_or_none(self):
            return self.value

    class DB:
        def query(self, model):
            if model is publisher.RouteGuide:
                return Query(guide)
            if model is publisher.RouteBook:
                return Query(user_route)
            raise AssertionError(model)

    with pytest.raises(ValueError, match="not an official replaceable route"):
        publisher._guide_bindings(
            DB(),
            {
                "route_guide_bindings": [
                    {"guide_name": "奥申", "module_key": "test-axis"}
                ]
            },
        )

    assert user_route.creator_id == 5
    assert user_route.is_official is False


def test_guide_binding_refuses_projection_for_another_axis():
    guide = SimpleNamespace(name="奥申", route_book_id=77)
    wrong_projection = SimpleNamespace(
        id=77,
        creator_id=None,
        is_official=True,
        source="strava_projection",
        file_id="strava:projection:some-other-axis:forward",
    )

    class Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *_args):
            return self

        def one_or_none(self):
            return self.value

    class DB:
        def query(self, model):
            return Query(guide if model is publisher.RouteGuide else wrong_projection)

    with pytest.raises(ValueError, match="another Strava projection"):
        publisher._guide_bindings(
            DB(),
            {
                "route_guide_bindings": [
                    {"guide_name": "奥申", "module_key": "test-axis"}
                ]
            },
        )


def test_unreplaced_legacy_retirement_refuses_non_file_upload(
    monkeypatch, tmp_path
):
    route_dir = tmp_path / "content/routes/wanmu"
    route_dir.mkdir(parents=True)
    (route_dir / "meta.json").write_text(
        json.dumps({"name": "万亩"}), encoding="utf-8"
    )
    guide = SimpleNamespace(name="万亩", route_book_id=77)
    route = SimpleNamespace(
        id=77,
        creator_id=None,
        is_official=True,
        source="tencent_direction",
        publish_status="published",
        visibility="public",
    )

    class Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *_args):
            return self

        def one_or_none(self):
            return self.value

    class DB:
        def query(self, model):
            return Query(guide if model is publisher.RouteGuide else route)

    monkeypatch.setattr(publisher, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="official file upload"):
        publisher._retire_unreplaced_legacy_geometry(
            DB(),
            {
                "legacy_geometry_retirement": [
                    {
                        "path": "content/routes/wanmu/track.gpx",
                        "replacement_module_key": None,
                    }
                ]
            },
        )

    assert route.publish_status == "published"
    assert guide.route_book_id == 77
