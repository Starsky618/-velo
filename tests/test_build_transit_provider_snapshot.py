from __future__ import annotations

from dataclasses import dataclass

from scripts.build_transit_provider_snapshot import build_snapshot


@dataclass
class _Elevation:
    point_count: int = 2
    climb: float = 12.3
    descent: float = 4.5
    profile: tuple[tuple[float, float], ...] = ((0.0, 100.0), (0.8, 108.0))


def _request(profile: str = "bicycling") -> dict:
    return {
        "schema_version": "transit_provider_request_v1",
        "transit_key": "a-to-b",
        "routing_profile": profile,
        "provider_observed_at": "2026-08-14",
        "research_verdict": "connection_candidate",
        "from": {
            "port_key": "a:exit",
            "binding_type": "source_observation_candidate",
            "source_observation_id": 1,
            "source_geometry_hash": "a" * 64,
            "lonlat": [112.4, 37.7],
        },
        "to": {
            "port_key": "b:entry",
            "binding_type": "source_observation_candidate",
            "source_observation_id": 2,
            "source_geometry_hash": "b" * 64,
            "lonlat": [112.41, 37.71],
        },
    }


def test_build_snapshot_keeps_steps_and_access_boundary() -> None:
    captured = {}

    def planner(start, end):
        captured["start"] = start
        captured["end"] = end
        return {
            "distance": 800.0,
            "duration": 4,
            "points": [
                {"lat": start[0], "lon": start[1]},
                {"lat": end[0], "lon": end[1]},
            ],
            "steps": [{"road_name": "测试路", "distance_m": 800.0}],
        }

    result = build_snapshot(
        _request(),
        planners={"bicycling": planner},
        elevation_builder=lambda _points: _Elevation(),
    )

    assert captured["start"] != (37.7, 112.4)
    assert result["provider"] == "tencent_bicycling_shadow"
    assert result["status"] == "connectivity_shadow_not_access_verified"
    assert result["road_steps"] == [{"road_name": "测试路", "distance_m": 800.0}]
    assert result["elevation"]["algorithm_version"] == "glo30_meaningful_ascent_v1"
    assert result["database_write_count"] == 0
    assert len(result["snapshot_sha256"]) == 64
