#!/usr/bin/env python3
"""把冻结的 Strava 完整道路轴投影为官方 RouteBook。

默认只读 dry-run；只有显式 ``--apply`` 才在一个事务里写库。脚本只读取已落库的
来源几何和 GLO 快照，不请求 Strava、不查询 DEM。全部轴先预检成功，才开始替换旧
GPX 投影；研究身份未闭合的轴保持不发布。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from geoalchemy2 import WKTElement  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.activity.models import Activity  # noqa: E402,F401
from app.database import SessionLocal  # noqa: E402
from app.elevation.climb_profile_contract import (  # noqa: E402
    ClimbProfileContract,
    build_climb_plan_from_contract,
)
from app.elevation.dem_client import (  # noqa: E402
    GLO30_HORIZONTAL_RESOLUTION_M,
    GLO30_LICENSE_ID,
    GLO30_SOURCE_NAME,
    GLO30_VERTICAL_ACCURACY_M,
)
from app.elevation.route_elevation import (  # noqa: E402
    ROUTE_ELEVATION_METHOD,
    route_elevation_metadata,
)
from app.route_book.elevation_workflow import write_route_elevation_result  # noqa: E402
from app.route_book.models import (  # noqa: E402
    RouteBook,
    RouteGuide,
    RouteVersion,
    _preview_points_from_wkt,
)
from app.route_book.service import _line_hash  # noqa: E402
from app.route_cognition.census_models import (  # noqa: E402
    SegmentElevationFact,
    SegmentSourceObservation,
)
from app.common.geometry_hash import strava_source_geometry_hash  # noqa: E402
from app.user.models import User  # noqa: E402,F401
from scripts.analyze_climb_catalog import (  # noqa: E402
    _directional_values,
    _axis_anchor_contract,
    _join_profiles,
    _load_transit_runs,
    _transit_profile,
)


@dataclass(frozen=True)
class ProjectionInput:
    route_key: str
    module_key: str
    module_name: str
    projection_kind: str
    traversal_direction: str
    scope_kind: str
    extent_status: str
    module_spec_sha256: str
    observation_id: int
    source_segment_id: str
    source_url: str
    source_geometry_hash: str
    source_line_wkt: str
    fact_id: int
    fact_batch_id: str
    derived_distance_m: float
    stored_climb_m: float
    stored_descent_m: float
    elevation_result: Any
    projection_identity_sha256: str
    component_provenance: tuple[dict, ...] = ()
    transit_provider_statuses: tuple[str, ...] = ()


VERIFIED_TRANSIT_PROVIDER_STATUSES = frozenset({"bicycling_access_verified"})


def _projection_validation_warnings(projection: ProjectionInput) -> list[str]:
    return [
        f"transit_access_not_verified:{status}"
        for status in sorted(
            status
            for status in projection.transit_provider_statuses
            if status not in VERIFIED_TRANSIT_PROVIDER_STATUSES
        )
    ]


def _projection_elevation_metadata(
    projection: ProjectionInput,
    *,
    catalog: dict,
    catalog_result: dict,
) -> dict:
    return {
        "horizontal_resolution_m": GLO30_HORIZONTAL_RESOLUTION_M,
        **route_elevation_metadata(),
        "projection": {
            "catalog_key": catalog["catalog_key"],
            "catalog_result_sha256": catalog_result["result_sha256"],
            "projection_identity_sha256": projection.projection_identity_sha256,
            "route_key": projection.route_key,
            "projection_kind": projection.projection_kind,
            "module_key": projection.module_key,
            "module_spec_sha256": projection.module_spec_sha256,
            "scope_kind": projection.scope_kind,
            "extent_status": projection.extent_status,
            "source_observation_id": projection.observation_id,
            "source_segment_id": projection.source_segment_id,
            "source_geometry_hash": projection.source_geometry_hash,
            "glo_fact_id": projection.fact_id,
            "glo_fact_batch_id": projection.fact_batch_id,
            "traversal_direction": projection.traversal_direction,
            "component_provenance": list(projection.component_provenance),
            "transit_provider_statuses": list(projection.transit_provider_statuses),
            "profile_replay_method": catalog["profile_source_method"],
            "network_request_count": 0,
            "glo_recomputation_count": 0,
        },
    }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_catalog(catalog_path: Path, result_path: Path) -> tuple[dict, dict]:
    catalog = _load_json(catalog_path)
    result = _load_json(result_path)
    if catalog.get("schema_version") != "xishan_climb_catalog_spec_v1":
        raise ValueError("unsupported climb catalog spec")
    if result.get("schema_version") != "xishan_climb_catalog_result_v1":
        raise ValueError("unsupported climb catalog result")
    if result.get("catalog_spec_sha256") != _canonical_sha256(catalog):
        raise ValueError("catalog spec/result hash drift")
    expected_result_hash = result.get("result_sha256")
    unhashed = dict(result)
    unhashed.pop("result_sha256", None)
    if expected_result_hash != _canonical_sha256(unhashed):
        raise ValueError("catalog result self hash drift")
    return catalog, result


def _fact_profile(
    source_line_wkt: str, elevation_snapshot: list
) -> tuple[list[list[float]], list[float]]:
    points = _preview_points_from_wkt(source_line_wkt)
    if len(points) < 2 or len(points) != len(elevation_snapshot):
        raise ValueError("source geometry/elevation snapshot coverage mismatch")
    elevations: list[float] = []
    for point, sample in zip(points, elevation_snapshot):
        if len(sample) < 3 or any(
            abs(float(left) - float(right)) > 1e-6
            for left, right in zip(point[:2], sample[:2])
        ):
            raise ValueError("source geometry/elevation snapshot coordinate drift")
        elevations.append(float(sample[2]))
    return points, elevations


def _line_wkt(points: Sequence[Sequence[float]]) -> str:
    if len(points) < 2:
        raise ValueError("projection needs at least two geometry points")
    return "LINESTRING (" + ", ".join(
        f"{float(point[0]):.7f} {float(point[1]):.7f}" for point in points
    ) + ")"


def _production_profile_row(db, catalog: dict, observation_id: int):
    row = (
        db.query(
            SegmentSourceObservation,
            SegmentElevationFact,
            func.ST_AsText(SegmentSourceObservation.source_line),
        )
        .join(
            SegmentElevationFact,
            (
                SegmentElevationFact.source_observation_id
                == SegmentSourceObservation.id
            )
            & (
                SegmentElevationFact.census_batch_id
                == SegmentSourceObservation.census_batch_id
            )
            & (
                SegmentElevationFact.source_segment_id
                == SegmentSourceObservation.source_segment_id
            ),
        )
        .filter(
            SegmentSourceObservation.id == observation_id,
            SegmentSourceObservation.census_batch_id == catalog["census_batch_id"],
            SegmentElevationFact.fact_batch_id == catalog["elevation_fact_batch_id"],
        )
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"production source/GLO fact missing for observation {observation_id}")
    observation, fact, source_line_wkt = row
    if observation.detail_status != "complete" or observation.geometry_status != "complete":
        raise ValueError(f"source observation incomplete: {observation_id}")
    if fact.fact_status != "complete":
        raise ValueError(f"GLO fact incomplete: {observation_id}")
    points, elevations = _fact_profile(
        source_line_wkt,
        list(fact.elevation_snapshot_json or []),
    )
    if strava_source_geometry_hash(points) != fact.source_geometry_hash:
        raise ValueError(f"source geometry content hash drift: {observation_id}")
    return observation, fact, points, elevations


def _preflight_projections(db, catalog: dict, catalog_result: dict) -> list[ProjectionInput]:
    exclusions = {row["module_key"] for row in catalog["publication_exclusions"]}
    public_axes = {row["module_key"]: row for row in catalog_result["axes"]}
    projections: list[ProjectionInput] = []
    for axis in catalog["axes"]:
        spec_path = REPO_ROOT / axis["module_spec"]
        spec = _load_json(spec_path)
        module_key = spec["module_key"]
        if module_key in exclusions:
            continue
        if module_key not in public_axes:
            raise ValueError(f"public axis result missing for {module_key}")
        observation_id = int(spec["axis_profile_observation_id"])
        observation, fact, points, elevations = _production_profile_row(
            db, catalog, observation_id
        )
        reference = spec["reference_axis"]
        if (
            observation.source_segment_id != reference["source_segment_id"]
            or fact.source_geometry_hash != reference["source_geometry_hash"]
        ):
            raise ValueError(f"source identity drift for {module_key}")
        semantics = reference["direction_semantics"]
        base_anchor, summit_anchor, anchor_evidence_refs = _axis_anchor_contract(
            axis, semantics
        )
        module_spec_sha256 = _canonical_sha256(spec)
        for direction in ("forward", "reverse"):
            directed_points, directed_elevations = _directional_values(
                points, elevations, direction
            )
            contract = ClimbProfileContract(
                scope_key=module_key,
                scope_kind=axis["scope_kind"],
                extent_status=axis["extent_status"],
                traversal_direction=direction,
                geometry_source="strava_full_segment_projection",
                start_anchor=base_anchor if direction == "forward" else summit_anchor,
                end_anchor=summit_anchor if direction == "forward" else base_anchor,
                source_observation_ids=(observation_id,),
                source_geometry_hashes=(fact.source_geometry_hash,),
                anchor_evidence_refs=anchor_evidence_refs,
            )
            elevation_result = build_climb_plan_from_contract(
                directed_points,
                directed_elevations,
                contract=contract,
                source_method=catalog["profile_source_method"],
            )
            stored_climb = float(fact.climb_m)
            stored_descent = float(fact.descent_m)
            if direction == "reverse":
                stored_climb, stored_descent = stored_descent, stored_climb
            elevation_result = replace(
                elevation_result,
                climb=round(stored_climb, 1),
                descent=round(stored_descent, 1),
            )
            expected_plan = public_axes[module_key]["directions"][direction]["climb_plan"]
            if _canonical_sha256(elevation_result.climb_plan) != _canonical_sha256(expected_plan):
                raise ValueError(f"axis ClimbPro replay drift for {module_key}:{direction}")
            route_key = f"{module_key}:{direction}"
            projection_identity = {
                "route_key": route_key,
                "module_spec_sha256": module_spec_sha256,
                "source_observation_id": observation_id,
                "source_geometry_hash": fact.source_geometry_hash,
                "fact_id": int(fact.id),
                "fact_batch_id": fact.fact_batch_id,
                "climb_profile_hash": elevation_result.climb_plan["source"]["profile_hash"],
                "traversal_direction": direction,
            }
            projections.append(
                ProjectionInput(
                    route_key=route_key,
                    module_key=module_key,
                    module_name=(
                        spec["module_name"]
                        if direction == "forward"
                        else f"{spec['module_name']}（反向）"
                    ),
                    projection_kind="axis",
                    traversal_direction=direction,
                    scope_kind=axis["scope_kind"],
                    extent_status=axis["extent_status"],
                    module_spec_sha256=module_spec_sha256,
                    observation_id=observation_id,
                    source_segment_id=observation.source_segment_id,
                    source_url=observation.source_url,
                    source_geometry_hash=fact.source_geometry_hash,
                    source_line_wkt=_line_wkt(directed_points),
                    fact_id=int(fact.id),
                    fact_batch_id=fact.fact_batch_id,
                    derived_distance_m=float(fact.derived_distance_m),
                    stored_climb_m=stored_climb,
                    stored_descent_m=stored_descent,
                    elevation_result=elevation_result,
                    projection_identity_sha256=_canonical_sha256(projection_identity),
                    component_provenance=(
                        {
                            "source_observation_id": observation_id,
                            "source_geometry_hash": fact.source_geometry_hash,
                            "glo_fact_id": int(fact.id),
                            "glo_fact_batch_id": fact.fact_batch_id,
                            "traversal_direction": direction,
                        },
                    ),
                )
            )
    expected = (len(catalog["axes"]) - len(exclusions)) * 2
    if len(projections) != expected:
        raise ValueError("published projection count drift")
    return projections


def _preflight_long_route_projections(
    db,
    catalog: dict,
    catalog_result: dict,
    *,
    transit_runs: dict[str, dict],
) -> list[ProjectionInput]:
    projections: list[ProjectionInput] = []
    profile_cache: dict[int, tuple[Any, Any, list[list[float]], list[float]]] = {}
    for route in catalog_result["long_routes"]:
        if route["status"] == "hard_rejected":
            continue
        assembled = []
        provenance: list[dict] = []
        source_observation_ids: list[int] = []
        source_hashes: list[str] = []
        fact_ids: list[int] = []
        transit_provider_statuses: list[str] = []
        for component in route["ordered_components"]:
            direction = component["traversal_direction"]
            public_component = dict(component)
            public_component.pop("endpoint_gap_from_previous_m", None)
            if component["kind"] == "transit_path":
                transit_key = component["transit_key"]
                run = transit_runs.get(transit_key)
                if run is None:
                    raise ValueError(f"private transit run missing for {transit_key}")
                if run["result_sha256"] != component["transit_result_sha256"]:
                    raise ValueError(f"transit result hash drift for {transit_key}")
                points, elevations = _transit_profile(run, direction)
                provider_status = run.get("provider_status")
                if not isinstance(provider_status, str) or not provider_status:
                    raise ValueError(f"transit provider status missing for {transit_key}")
                transit_provider_statuses.append(provider_status)
                provenance.append(
                    {
                        "kind": "transit_path",
                        "transit_key": transit_key,
                        "transit_result_sha256": run["result_sha256"],
                        "provider_status": provider_status,
                        "traversal_direction": direction,
                    }
                )
            else:
                observation_id = int(component["source_observation_id"])
                row = profile_cache.get(observation_id)
                if row is None:
                    row = _production_profile_row(db, catalog, observation_id)
                    profile_cache[observation_id] = row
                observation, fact, points, elevations = row
                if fact.source_geometry_hash != component["source_geometry_hash"]:
                    raise ValueError(
                        f"long route source identity drift for observation {observation_id}"
                    )
                points, elevations = _directional_values(points, elevations, direction)
                source_observation_ids.append(observation_id)
                source_hashes.append(fact.source_geometry_hash)
                fact_ids.append(int(fact.id))
                provenance.append(
                    {
                        "kind": component["kind"],
                        "source_observation_id": observation_id,
                        "source_segment_id": observation.source_segment_id,
                        "source_geometry_hash": fact.source_geometry_hash,
                        "glo_fact_id": int(fact.id),
                        "glo_fact_batch_id": fact.fact_batch_id,
                        "traversal_direction": direction,
                    }
                )
            assembled.append((points, elevations, public_component))
        points, elevations, joined_components = _join_profiles(assembled)
        expected_components = route["ordered_components"]
        if _canonical_sha256(joined_components) != _canonical_sha256(expected_components):
            raise ValueError(f"long route component replay drift: {route['candidate_id']}")
        unique_observation_ids = tuple(dict.fromkeys(source_observation_ids))
        unique_hashes = tuple(dict.fromkeys(source_hashes))
        contract = ClimbProfileContract(
            scope_key=route["candidate_id"],
            scope_kind="route_composition",
            extent_status="complete_route_composition",
            traversal_direction="geometry_order",
            geometry_source="frozen_source_and_transit_component_composition",
            start_anchor=f"route_start:{joined_components[0]['occurrence_id']}",
            end_anchor=f"route_end:{joined_components[-1]['occurrence_id']}",
            source_observation_ids=unique_observation_ids,
            source_geometry_hashes=unique_hashes,
        )
        elevation_result = build_climb_plan_from_contract(
            points,
            elevations,
            contract=contract,
            source_method="frozen_component_profile_composition_v1",
        )
        expected_plan = route["profile_replay"]["climb_plan"]
        if _canonical_sha256(elevation_result.climb_plan) != _canonical_sha256(expected_plan):
            raise ValueError(f"long route ClimbPro replay drift: {route['candidate_id']}")
        totals = route["choice_fact_totals"]
        elevation_result = replace(
            elevation_result,
            climb=float(totals["climb_m"]),
            descent=float(totals["descent_m"]),
        )
        source_line_wkt = _line_wkt(points)
        geometry_hash = _line_hash(source_line_wkt)
        route_key = f"long:{route['candidate_id']}"
        projection_identity = {
            "route_key": route_key,
            "route_result_sha256": route["route_result_sha256"],
            "geometry_hash": geometry_hash,
            "climb_profile_hash": elevation_result.climb_plan["source"]["profile_hash"],
            "component_provenance": provenance,
        }
        projections.append(
            ProjectionInput(
                route_key=route_key,
                module_key=route["candidate_id"],
                module_name=route["choice_name"],
                projection_kind="long_route",
                traversal_direction="geometry_order",
                scope_kind="route_composition",
                extent_status="complete_route_composition",
                module_spec_sha256=route["route_result_sha256"],
                observation_id=unique_observation_ids[0],
                source_segment_id="composite",
                source_url="",
                source_geometry_hash=geometry_hash,
                source_line_wkt=source_line_wkt,
                fact_id=fact_ids[0],
                fact_batch_id=catalog["elevation_fact_batch_id"],
                derived_distance_m=float(elevation_result.climb_plan["route_distance_m"]),
                stored_climb_m=float(totals["climb_m"]),
                stored_descent_m=float(totals["descent_m"]),
                elevation_result=elevation_result,
                projection_identity_sha256=_canonical_sha256(projection_identity),
                component_provenance=tuple(provenance),
                transit_provider_statuses=tuple(
                    dict.fromkeys(transit_provider_statuses)
                ),
            )
        )
    expected = int(catalog_result["long_route_hard_feasible_count"])
    if len(projections) != expected:
        raise ValueError("long route published projection count drift")
    return projections


def _source_ref(projection: ProjectionInput) -> str:
    # RouteBook 的稳定发布身份不随 canonical segment / observation / fact 重建；
    # 这些可变事实进入不可变 RouteVersion metadata。
    return f"strava:projection:{projection.route_key}"


def _metadata_projection_identity(version: RouteVersion | None) -> str | None:
    if version is None or not version.navigation_metadata_json:
        return None
    try:
        metadata = json.loads(version.navigation_metadata_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return (
        ((metadata or {}).get("elevation") or {}).get("projection") or {}
    ).get("projection_identity_sha256")


def _create_version(db, route: RouteBook, projection: ProjectionInput) -> RouteVersion:
    current = None
    if route.current_version_id is not None:
        current = (
            db.query(RouteVersion)
            .filter(
                RouteVersion.id == route.current_version_id,
                RouteVersion.route_book_id == route.id,
            )
            .one_or_none()
        )
    if _metadata_projection_identity(current) == projection.projection_identity_sha256:
        return current
    if current is not None:
        current.status = "archived"
    version_no = (
        db.query(func.max(RouteVersion.version_no))
        .filter(RouteVersion.route_book_id == route.id)
        .scalar()
        or 0
    ) + 1
    validation_warnings = _projection_validation_warnings(projection)
    version = RouteVersion(
        route_book_id=route.id,
        version_no=version_no,
        status="current",
        created_by=None,
        geometry_source="strava_projection",
        navigation_status="pending" if validation_warnings else "ready",
        reference_line_snapshot=WKTElement(projection.source_line_wkt, srid=4326),
        line_hash=_line_hash(projection.source_line_wkt),
        distance=projection.derived_distance_m,
        climb=None,
        elevation_profile=None,
        elevation_points_snapshot=None,
        point_count=len(projection.elevation_result.snapshot),
        component_snapshot_hash=projection.projection_identity_sha256,
        validation_warnings_json=json.dumps(validation_warnings, ensure_ascii=False),
    )
    db.add(version)
    db.flush()
    route.current_version_id = version.id
    return version


def _apply_projection(
    db,
    projection: ProjectionInput,
    *,
    guide_by_module: dict[str, RouteGuide],
    catalog: dict,
    catalog_result: dict,
) -> tuple[RouteBook, RouteVersion]:
    source_ref = _source_ref(projection)
    guide = (
        guide_by_module.get(projection.module_key)
        if projection.projection_kind == "axis"
        and projection.traversal_direction == "forward"
        else None
    )
    route = None
    if guide is not None and guide.route_book_id is not None:
        route = db.query(RouteBook).filter(RouteBook.id == guide.route_book_id).one_or_none()
    if route is None:
        route = (
            db.query(RouteBook)
            .filter(
                RouteBook.source == "strava_projection",
                RouteBook.file_id == source_ref,
                RouteBook.is_official.is_(True),
            )
            .one_or_none()
        )
    if route is None:
        route = RouteBook()
        db.add(route)
    route.creator_id = None
    route.name = projection.module_name
    route.distance = projection.derived_distance_m
    route.reference_line = WKTElement(projection.source_line_wkt, srid=4326)
    route.file_id = source_ref
    route.file_type = None
    route.source = "strava_projection"
    route.source_activity_id = None
    route.city = "taiyuan"
    route.is_official = True
    has_unverified_transit = bool(_projection_validation_warnings(projection))
    route.visibility = "unlisted" if has_unverified_transit else "public"
    route.publish_status = "draft" if has_unverified_transit else "published"
    route.line_hash = _line_hash(projection.source_line_wkt)
    db.flush()
    version = _create_version(db, route, projection)
    write_route_elevation_result(
        db,
        route=route,
        version=version,
        result=projection.elevation_result,
        source_name=GLO30_SOURCE_NAME,
        license_id=GLO30_LICENSE_ID,
        accuracy_m=GLO30_VERTICAL_ACCURACY_M,
        method=ROUTE_ELEVATION_METHOD,
        timestamp_field="projected_at",
        extra_metadata=_projection_elevation_metadata(
            projection,
            catalog=catalog,
            catalog_result=catalog_result,
        ),
    )
    if guide is not None:
        guide.route_book_id = route.id
        guide.source_route_version_id = version.id
        guide.elevation_profile = route.elevation_profile
        guide.imported_at = datetime.now(timezone.utc)
    return route, version


def _guide_bindings(db, catalog: dict) -> dict[str, RouteGuide]:
    bindings: dict[str, RouteGuide] = {}
    seen_guides: set[str] = set()
    seen_route_books: set[int] = set()
    for row in catalog["route_guide_bindings"]:
        guide_name = row["guide_name"]
        if guide_name in seen_guides or row["module_key"] in bindings:
            raise ValueError("route guide binding must be one-to-one")
        seen_guides.add(guide_name)
        guide = db.query(RouteGuide).filter(RouteGuide.name == guide_name).one_or_none()
        if guide is None:
            raise ValueError(f"route guide missing for binding: {guide_name}")
        if guide.route_book_id is not None:
            route_book_id = int(guide.route_book_id)
            if route_book_id in seen_route_books:
                raise ValueError("route guide bindings must not reuse one RouteBook")
            seen_route_books.add(route_book_id)
            route = (
                db.query(RouteBook)
                .filter(RouteBook.id == route_book_id)
                .one_or_none()
            )
            if route is None:
                raise ValueError(f"route guide has missing RouteBook: {guide_name}")
            if (
                route.creator_id is not None
                or not route.is_official
                or route.source not in {"file_upload", "strava_projection"}
            ):
                raise ValueError(
                    f"route guide binding is not an official replaceable route: {guide_name}"
                )
            expected_source_ref = f"strava:projection:{row['module_key']}:forward"
            if (
                route.source == "strava_projection"
                and route.file_id != expected_source_ref
            ):
                raise ValueError(
                    f"route guide binding points at another Strava projection: {guide_name}"
                )
        bindings[row["module_key"]] = guide
    return bindings


def _retire_unreplaced_legacy_geometry(db, catalog: dict) -> list[str]:
    retired: list[str] = []
    for row in catalog["legacy_geometry_retirement"]:
        if row["replacement_module_key"] is not None:
            continue
        meta_path = REPO_ROOT / Path(row["path"]).parent / "meta.json"
        guide_name = _load_json(meta_path)["name"]
        guide = db.query(RouteGuide).filter(RouteGuide.name == guide_name).one_or_none()
        if guide is None or guide.route_book_id is None:
            continue
        route = db.query(RouteBook).filter(RouteBook.id == guide.route_book_id).one_or_none()
        if route is None:
            raise ValueError(f"unreplaced legacy guide has missing RouteBook: {guide_name}")
        if (
            route.creator_id is not None
            or not route.is_official
            or route.source != "file_upload"
        ):
            raise ValueError(
                f"unreplaced legacy guide is not bound to an official file upload: {guide_name}"
            )
        route.publish_status = "archived"
        route.visibility = "unlisted"
        guide.route_book_id = None
        guide.source_route_version_id = None
        guide.elevation_profile = None
        retired.append(guide_name)
    return retired


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-spec",
        default=str(REPO_ROOT / "data/research/xishan_climb_catalog_v1.json"),
    )
    parser.add_argument(
        "--catalog-result",
        default=str(REPO_ROOT / "data/research/xishan_climb_catalog_v1_result.json"),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write all preflighted projections in one transaction",
    )
    parser.add_argument(
        "--transit-evidence-dir",
        action="append",
        default=[],
        help="private frozen TransitPath run directory; repeat as needed",
    )
    args = parser.parse_args(argv)

    catalog, catalog_result = _load_catalog(
        Path(args.catalog_spec), Path(args.catalog_result)
    )
    if catalog_result["long_route_hard_feasible_count"] and not args.transit_evidence_dir:
        parser.error("long route publication requires --transit-evidence-dir")
    transit_runs = _load_transit_runs(
        [Path(value) for value in args.transit_evidence_dir]
    )
    db = SessionLocal()
    try:
        axis_projections = _preflight_projections(db, catalog, catalog_result)
        long_projections = _preflight_long_route_projections(
            db,
            catalog,
            catalog_result,
            transit_runs=transit_runs,
        )
        projections = axis_projections + long_projections
        excluded = [row["module_key"] for row in catalog["publication_exclusions"]]
        print(
            f"PREFLIGHT OK: axis_traversals={len(axis_projections)} "
            f"long_routes={len(long_projections)} excluded_axes={len(excluded)} "
            "network_requests=0 db_writes=0 glo_recomputation=0"
        )
        for projection in projections:
            print(
                f"- {projection.module_name}: o{projection.observation_id} "
                f"{projection.derived_distance_m / 1000:.3f}km "
                f"+{projection.stored_climb_m:.1f}/-{projection.stored_descent_m:.1f}m"
            )
        if not args.apply:
            db.rollback()
            print("DRY RUN: no database writes")
            return
        guide_by_module = _guide_bindings(db, catalog)
        route_ids: list[int] = []
        for projection in projections:
            route, _version = _apply_projection(
                db,
                projection,
                guide_by_module=guide_by_module,
                catalog=catalog,
                catalog_result=catalog_result,
            )
            route_ids.append(int(route.id))
        retired_guides = _retire_unreplaced_legacy_geometry(db, catalog)
        db.commit()
        print(
            f"APPLIED: routes={len(route_ids)} guides_bound={len(guide_by_module)} "
            f"legacy_guides_unlinked={len(retired_guides)}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
