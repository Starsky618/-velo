"""verified 路段 bundle 发布门禁与事务写入测试。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.elevation.route_elevation import ROUTE_ELEVATION_METHOD, route_elevation_metadata
from app.route_cognition.geometry_hash import (
    SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
    hash_segment_geometry_wkt,
)
from app.route_cognition.models import SegmentGeometrySource
from app.segment._geo_utils import _haversine
from app.segment.algorithms import calculate_max_gradient
from app.segment.verified_bundle_publisher import (
    SOURCE_FILE_PREFIX,
    SegmentPublicationResult,
    VerifiedSegmentBundleError,
    publish_verified_segment_bundle,
    validate_verified_segment_bundle,
)


def _bundle() -> dict:
    name = "测试热门路段"
    input_hash = "a" * 64
    candidate_id = hashlib.sha256(f"{name}:{input_hash}".encode()).hexdigest()[:24]
    points = [
        [112.50000000, 37.80000000],
        [112.50000000, 37.80100000],
        [112.50000000, 37.80200000],
        [112.50000000, 37.80300000],
        [112.50000000, 37.80400000],
    ]
    snapshot = [
        [lon, lat, 800.0 + index * 10.0]
        for index, (lon, lat) in enumerate(points)
    ]
    distance_m = sum(
        _haversine(left[1], left[0], right[1], right[0])
        for left, right in zip(points, points[1:])
    )
    trackpoints = [
        SimpleNamespace(latitude=lat, longitude=lon, elevation=ele)
        for lon, lat, ele in snapshot
    ]
    geometry_wkt = "LINESTRING(" + ",".join(
        f"{lon:.8f} {lat:.8f}" for lon, lat in points
    ) + ")"
    profile = [
        [round(distance_m / 1000 * index / 4, 6), 800.0 + index * 10.0]
        for index in range(5)
    ]
    profile[-1][0] = round(distance_m / 1000, 6)
    reviewed_at = datetime(2026, 8, 10, 12, tzinfo=timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "status": "verified",
        "publication_eligible": True,
        "generated_at": reviewed_at,
        "segment": {
            "name": name,
            "city": "taiyuan",
            "direction": "从南向北",
        },
        "identity_evidence": {
            "target_definition": {"physical_role": "测试道路"},
            "selection": {"source_segment_name": name},
            "source_observation": {},
        },
        "hard_knowledge": {
            "geometry": {
                "source": "tencent_directions",
                "routing_profile": "bicycling",
                "coordinate_system": "wgs84",
                "normalization_version": SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
                "geometry_hash": hash_segment_geometry_wkt(geometry_wkt),
                "wkt": geometry_wkt,
                "points": points,
                "point_count": len(points),
                "routing_anchor_count": 2,
            },
            "metrics": {
                "distance_m": round(distance_m, 2),
                "provider_distance_m": round(distance_m, 2),
                "elevation_gain_m": 40.0,
                "elevation_loss_m": 0.0,
                "average_gradient_pct": round(40.0 / distance_m * 100, 2),
                "maximum_gradient_pct": round(calculate_max_gradient(trackpoints), 2),
            },
            "elevation": {
                "method": ROUTE_ELEVATION_METHOD,
                "metadata": route_elevation_metadata(),
                "snapshot": snapshot,
                "profile": profile,
                "point_count": len(points),
            },
        },
        "popularity_observation": {
            "source_type": "strava_public_page",
            "source_url": "https://www.strava.com/segments/12345",
            "observed_at": reviewed_at,
            "athlete_count": 100,
            "effort_count": 300,
            "star_count": 20,
            "comparison_scope": "测试范围",
            "nearby_comparisons": [],
        },
        "derived_judgments": [],
        "provenance": {
            "strava_access_mode": "human_visible_public_page",
            "strava_api_used": False,
            "input_sha256": input_hash,
            "tencent_routing_profile": "bicycling",
        },
        "quality_gates": {
            "target_identity_match": "passed",
            "gpx_independent_coordinates": "passed",
            "tencent_route_generated": "passed",
            "tencent_distance_match": "passed",
            "elevation_complete": "passed",
            "endpoint_match": "passed",
            "direction_match": "passed",
            "shape_match": "passed",
            "warnings_reviewed": "passed",
        },
        "warnings": [],
        "review": {
            "verdict": "accept",
            "reviewer": "Tim",
            "reviewed_at": reviewed_at,
            "note": "逐段核对起终点、方向和路形一致",
            "endpoint_match": "yes",
            "direction_match": "yes",
            "shape_match": "yes",
            "warnings_reviewed": "yes",
            "reviewed_geometry_hash": hash_segment_geometry_wkt(geometry_wkt),
        },
    }


def test_validated_bundle_preserves_published_identity():
    validated = validate_verified_segment_bundle(_bundle())

    assert validated.name == "测试热门路段"
    assert validated.city == "taiyuan"
    assert validated.source_file_id == f"{SOURCE_FILE_PREFIX}{validated.candidate_id}"
    assert validated.geometry_hash == hash_segment_geometry_wkt(validated.geometry_wkt)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda bundle: bundle.update(status="needs_review"), "verified"),
        (
            lambda bundle: bundle["hard_knowledge"]["geometry"].update(
                wkt=bundle["hard_knowledge"]["geometry"]["wkt"].replace(",", ", ")
            ),
            "规范形式",
        ),
        (
            lambda bundle: bundle["quality_gates"].update(shape_match="pending"),
            "质量门禁",
        ),
        (
            lambda bundle: bundle["hard_knowledge"]["metrics"].update(
                maximum_gradient_pct=24.0
            ),
            "Segment 算法",
        ),
        (
            lambda bundle: bundle["hard_knowledge"]["metrics"].update(
                elevation_gain_m=400.0
            ),
            "elevation.snapshot",
        ),
        (
            lambda bundle: bundle["hard_knowledge"]["elevation"]["profile"][2].__setitem__(
                1,
                bundle["hard_knowledge"]["elevation"]["profile"][2][1] + 100.0,
            ),
            "profile.*snapshot",
        ),
    ],
)
def test_validator_rejects_unreviewed_or_drifted_bundle(mutate, match):
    bundle = _bundle()
    mutate(bundle)

    with pytest.raises(VerifiedSegmentBundleError, match=match):
        validate_verified_segment_bundle(bundle)


def test_publish_is_transactional_and_retry_idempotent(db, verified_bundle_tables):
    bundle = _bundle()

    first = publish_verified_segment_bundle(db, bundle=bundle, reviewer_user_id=1)
    second = publish_verified_segment_bundle(db, bundle=bundle, reviewer_user_id=1)

    assert first.status == "published"
    assert second == SegmentPublicationResult(
        status="already_published",
        candidate_id=first.candidate_id,
        segment_id=first.segment_id,
        geometry_hash=first.geometry_hash,
        source_file_id=first.source_file_id,
    )
    assert db.execute(text("SELECT count(*) FROM segments")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM judgment_runs")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM segment_geometry_sources")).scalar_one() == 1
    assert db.execute(text("SELECT count(*) FROM route_cognition_segments")).scalar_one() == 1

    source = db.query(SegmentGeometrySource).one()
    assert source.source_file_id == first.source_file_id
    assert source.source_url == "https://www.strava.com/segments/12345"
    assert source.quality_metrics_json["verified_bundle"]["candidate_id"] == first.candidate_id


def test_same_candidate_id_with_changed_bundle_is_conflict(db, verified_bundle_tables):
    bundle = _bundle()
    publish_verified_segment_bundle(db, bundle=bundle, reviewer_user_id=1)
    changed = deepcopy(bundle)
    changed["popularity_observation"]["effort_count"] += 1

    with pytest.raises(VerifiedSegmentBundleError, match="bundle.*冲突"):
        publish_verified_segment_bundle(db, bundle=changed, reviewer_user_id=1)

    assert db.execute(text("SELECT count(*) FROM segments")).scalar_one() == 1


@pytest.fixture()
def verified_bundle_tables(db):
    db.execute(text("DROP TABLE IF EXISTS route_cognition_segments"))
    db.execute(text("DROP TABLE IF EXISTS segment_geometry_sources"))
    db.execute(text("DROP TABLE IF EXISTS judgment_runs"))
    db.execute(text("DELETE FROM segment_efforts"))
    db.execute(text("DELETE FROM segments"))
    db.execute(text("DELETE FROM users"))
    db.execute(
        text(
            """
            CREATE TABLE judgment_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                route_book_id INTEGER,
                route_version_id INTEGER,
                segment_id INTEGER,
                engine_name TEXT,
                engine_version TEXT,
                model_name TEXT,
                model_version TEXT,
                code_version TEXT,
                params_json TEXT,
                input_hash TEXT,
                confidence NUMERIC,
                confidence_method TEXT,
                confidence_state TEXT NOT NULL,
                result_summary_json TEXT,
                missing_data_json TEXT,
                contradiction_json TEXT,
                defensive_silence_recommended BOOLEAN DEFAULT 0 NOT NULL,
                parent_run_id INTEGER,
                challenged_run_id INTEGER,
                created_by_user_id INTEGER,
                created_by_service TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE segment_geometry_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_activity_id INTEGER,
                source_file_id TEXT,
                source_url TEXT,
                source_start_index INTEGER,
                source_end_index INTEGER,
                source_start_time DATETIME,
                source_end_time DATETIME,
                original_coordinate_system TEXT,
                geometry_hash TEXT NOT NULL,
                source_content_hash TEXT,
                normalization_version TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                quality_metrics_json TEXT,
                created_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(id, segment_id),
                UNIQUE(id, segment_id, geometry_hash),
                UNIQUE(source_file_id)
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE route_cognition_segments (
                segment_id INTEGER PRIMARY KEY,
                primary_geometry_source_id INTEGER UNIQUE,
                review_basis TEXT NOT NULL,
                eligibility_status TEXT NOT NULL,
                geometry_hash TEXT NOT NULL,
                normalization_version TEXT NOT NULL,
                accepted_judgment_run_id INTEGER NOT NULL,
                reviewed_by INTEGER,
                reviewed_at DATETIME NOT NULL,
                review_note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
    )
    db.execute(text("INSERT INTO users (id, openid, is_admin) VALUES (1, 'publisher', 1)"))
    try:
        yield
    finally:
        db.rollback()
        for table_name in (
            "route_cognition_segments",
            "segment_geometry_sources",
            "judgment_runs",
        ):
            db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
