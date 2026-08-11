import json

import pytest

from app.route_book.manual_geometry_patch import (
    ManualGeometryPatchError,
    build_patch_candidate,
)


def _manifest(parts):
    return {
        "schema_version": 1,
        "segment": {
            "source_segment_id": "123",
            "source_segment_name": "测试绿道",
            "source_url": "https://www.strava.com/segments/123",
            "observed_distance_m": 2220,
        },
        "fallback_chain": [
            {
                "stage": "tencent",
                "outcome": "rejected",
                "evidence": "tencent-attempt.json",
            },
            {
                "stage": "osm",
                "outcome": "rejected",
                "evidence": "osm-attempt.json",
            },
            {
                "stage": "freehand",
                "outcome": "selected",
                "evidence": "strava-source-stream.json",
            },
        ],
        "join_policy": {"max_gap_m": 20, "snap_within_m": 2},
        "parts": parts,
    }


def test_strava_stream_is_simplified_and_validated_through_freehand_interface(tmp_path):
    locations = [
        [37.8 + index * 0.00001, 112.5 + index * 0.0001]
        for index in range(201)
    ]
    source = tmp_path / "strava.json"
    source.write_text(
        json.dumps({"streams": {"location": locations}}),
        encoding="utf-8",
    )
    candidate = build_patch_candidate(
        _manifest(
            [
                {
                    "part_id": "strava-shape",
                    "source_type": "strava_page_stream",
                    "source_name": "Strava 详情页 location stream",
                    "source_path": "strava.json",
                    "simplify_tolerance_m": "auto",
                    "max_simplify_error_m": 3,
                    "review_status": "source_shape",
                }
            ]
        ),
        manifest_dir=tmp_path,
    )

    assert candidate["review"]["status"] == "source_shape"
    assert candidate["geometry"]["point_count"] < len(locations)
    assert candidate["geometry"]["points_wgs84"][0] == [112.5, 37.8]
    assert candidate["geometry"]["points_wgs84"][-1] == [112.52, 37.802]
    provenance = candidate["provenance"]["parts"][0]
    assert provenance["source_point_count"] == len(locations)
    assert provenance["source_material_point_count"] == len(locations)
    assert provenance["normalized_source_point_count"] == len(locations)
    assert provenance["simplify_mode"] == "auto_fit_freehand_budget"
    assert provenance["retained_point_count"] <= 120
    assert provenance["max_source_deviation_m"] <= 3
    assert provenance["max_source_gap_m"] < 20
    assert provenance["points_wgs84"] is None


def test_routed_and_hand_drawn_parts_can_join_with_explicit_provenance(tmp_path):
    candidate = build_patch_candidate(
        _manifest(
            [
                {
                    "part_id": "routed-before",
                    "source_type": "routing_candidate",
                    "source_name": "Tencent routed part",
                    "points_wgs84": [[112.5, 37.8], [112.51, 37.8]],
                    "max_source_gap_m": 1000,
                    "review_status": "human_reviewed",
                },
                {
                    "part_id": "hand-gap",
                    "source_type": "hand_drawn",
                    "source_name": "reviewed hand patch",
                    "points_wgs84": [
                        [112.5101, 37.8],
                        [112.515, 37.801],
                        [112.52, 37.8],
                    ],
                    "max_source_gap_m": 1000,
                    "review_status": "human_reviewed",
                },
            ]
        ),
        manifest_dir=tmp_path,
    )

    join = candidate["provenance"]["joins"][0]
    assert 8 < join["gap_m"] < 10
    assert join["action"] == "explicit_straight_join"
    assert candidate["review"]["status"] == "needs_review"
    assert "显式直线连接" in candidate["review"]["warnings"][0]


def test_large_implicit_gap_is_rejected(tmp_path):
    with pytest.raises(ManualGeometryPatchError, match="不允许隐式补直线"):
        build_patch_candidate(
            _manifest(
                [
                    {
                        "part_id": "a",
                        "source_type": "hand_drawn",
                        "points_wgs84": [[112.5, 37.8], [112.51, 37.8]],
                        "max_source_gap_m": 1000,
                    },
                    {
                        "part_id": "b",
                        "source_type": "hand_drawn",
                        "points_wgs84": [[112.52, 37.8], [112.53, 37.8]],
                        "max_source_gap_m": 1000,
                    },
                ]
            ),
            manifest_dir=tmp_path,
        )


def test_source_stream_gap_is_not_hidden_by_freehand(tmp_path):
    with pytest.raises(ManualGeometryPatchError, match="不能自动手绘跨过缺口"):
        build_patch_candidate(
            _manifest(
                [
                    {
                        "part_id": "broken-source",
                        "source_type": "strava_page_stream",
                        "points_wgs84": [[112.5, 37.8], [112.51, 37.8]],
                        "simplify_tolerance_m": "auto",
                        "max_simplify_error_m": 3,
                    }
                ]
            ),
            manifest_dir=tmp_path,
        )


def test_fallback_chain_order_is_required(tmp_path):
    manifest = _manifest(
        [
            {
                "part_id": "hand",
                "source_type": "hand_drawn",
                "points_wgs84": [[112.5, 37.8], [112.5001, 37.8]],
            }
        ]
    )
    manifest["fallback_chain"][0]["stage"] = "osm"
    with pytest.raises(ManualGeometryPatchError, match="顺序必须是"):
        build_patch_candidate(manifest, manifest_dir=tmp_path)


def test_manual_straight_connector_has_a_hard_distance_limit(tmp_path):
    with pytest.raises(ManualGeometryPatchError, match="直线连接长"):
        build_patch_candidate(
            _manifest(
                [
                    {
                        "part_id": "too-long",
                        "source_type": "manual_straight_connector",
                        "points_wgs84": [[112.5, 37.8], [112.51, 37.8]],
                    }
                ]
            ),
            manifest_dir=tmp_path,
        )
