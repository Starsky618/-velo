"""太原两条人工确认赛段纠偏的机械变换。"""

from __future__ import annotations

import pytest

from app.segment.reviewed_boundary_corrections import (
    CORRECTION_SPECS,
    BoundaryCorrectionSpec,
    build_boundary_correction_candidate,
    decode_strava_polyline,
    polyline_distance_m,
    validate_boundary_correction_metrics,
)
from app.strava.client import StravaClient


def _encode_polyline(points: list[tuple[float, float]]) -> str:
    result = []
    previous_lat = previous_lon = 0
    for lat, lon in points:
        current_lat = round(lat * 1e5)
        current_lon = round(lon * 1e5)
        for delta in (current_lat - previous_lat, current_lon - previous_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                result.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            result.append(chr(value + 63))
        previous_lat = current_lat
        previous_lon = current_lon
    return "".join(result)


def _detail(segment_id: int, name: str, points: list[tuple[float, float]]) -> dict:
    return {
        "id": segment_id,
        "name": name,
        "distance": polyline_distance_m(tuple(points)),
        "map": {"polyline": _encode_polyline(points)},
    }


def test_scope_excludes_tianlong_after_user_correction():
    assert set(CORRECTION_SPECS) == {30, 39}


def test_decode_strava_polyline_known_example():
    decoded = decode_strava_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    expected = ((38.5, -120.2), (40.7, -120.95), (43.252, -126.453))
    assert len(decoded) == len(expected)
    for actual, wanted in zip(decoded, expected):
        assert actual == pytest.approx(wanted)


def test_use_source_polyline_keeps_order_and_endpoints(monkeypatch):
    points = [(37.60, 112.60), (37.605, 112.61), (37.61, 112.62)]
    distance_m = polyline_distance_m(tuple(points))
    monkeypatch.setitem(
        CORRECTION_SPECS,
        39,
        BoundaryCorrectionSpec(
            segment_id=39,
            segment_name="潇河南岸单程",
            source_segment_id=39,
            source_name_fragment="潇河南岸",
            expected_source_distance_m=distance_m,
            expected_source_start=points[0],
            expected_source_end=points[-1],
            operation="use_source_polyline",
        ),
    )

    candidate = build_boundary_correction_candidate(
        39,
        _detail(39, "潇河南岸单程", points),
    )

    assert candidate.points == tuple(points)
    assert candidate.metrics["operation"] == "use_source_polyline"


def test_remove_northern_out_and_back_only_cuts_confirmed_retrace(monkeypatch):
    points = []
    for index in range(353):
        points.append((37.80, 112.40 + index * 0.00001))
    for index in range(1, 39):
        points.append((37.80 + index * 0.0005, points[352][1]))
    for index in range(37, 0, -1):
        points.append((37.80 + index * 0.0005, points[352][1]))
    points.append(points[352])
    for index in range(71):
        points.append((37.80, points[352][1] + (index + 1) * 0.00001))
    assert len(points) == 500
    distance_m = polyline_distance_m(tuple(points))
    monkeypatch.setitem(
        CORRECTION_SPECS,
        30,
        BoundaryCorrectionSpec(
            segment_id=30,
            segment_name="南内环桥-中北福源阁-南内环桥",
            source_segment_id=30,
            source_name_fragment="南内环桥",
            expected_source_distance_m=distance_m,
            expected_source_start=points[0],
            expected_source_end=points[-1],
            operation="remove_northern_out_and_back",
        ),
    )

    candidate = build_boundary_correction_candidate(
        30,
        _detail(30, "南内环桥-中北福源阁-南内环桥", points),
    )
    decoded = decode_strava_polyline(_encode_polyline(points))

    assert candidate.points[:353] == decoded[:353]
    assert candidate.points[353:] == decoded[428:]
    assert candidate.metrics["join_gap_m"] == pytest.approx(0.0)
    assert candidate.metrics["removed_path_m"] > 4000


def test_metrics_must_still_match_candidate_body(monkeypatch):
    points = [(37.60, 112.60), (37.605, 112.61), (37.61, 112.62)]
    distance_m = polyline_distance_m(tuple(points))
    monkeypatch.setitem(
        CORRECTION_SPECS,
        39,
        BoundaryCorrectionSpec(
            segment_id=39,
            segment_name="潇河南岸单程",
            source_segment_id=39,
            source_name_fragment="潇河南岸",
            expected_source_distance_m=distance_m,
            expected_source_start=points[0],
            expected_source_end=points[-1],
            operation="use_source_polyline",
        ),
    )
    candidate = build_boundary_correction_candidate(
        39,
        _detail(39, "潇河南岸单程", points),
    )

    validate_boundary_correction_metrics(
        candidate.metrics,
        segment_id=39,
        source_segment_id="39",
        candidate_points=list(candidate.points),
        candidate_distance_m=distance_m,
    )
    with pytest.raises(ValueError, match="距离"):
        validate_boundary_correction_metrics(
            candidate.metrics,
            segment_id=39,
            source_segment_id="39",
            candidate_points=list(candidate.points),
            candidate_distance_m=distance_m + 10,
        )


def test_strava_client_exposes_segment_detail(monkeypatch):
    client = object.__new__(StravaClient)
    monkeypatch.setattr(
        client,
        "_request",
        lambda method, path: {"id": 37160997, "method": method, "path": path},
    )

    result = client.get_segment_detail(37160997)

    assert result["path"] == "/segments/37160997"
    with pytest.raises(ValueError, match="正整数"):
        client.get_segment_detail(0)
