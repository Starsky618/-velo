#!/usr/bin/env python3
"""Build one hash-bound Tencent connectivity shadow for TransitPath replay."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.elevation.route_elevation import (  # noqa: E402
    ROUTE_ELEVATION_METHOD,
    build_route_elevation_result,
)
from app.route_book.tencent_direction import (  # noqa: E402
    plan_tencent_bicycling_route,
    plan_tencent_driving_route,
)
from app.segment.coord_convert import (  # noqa: E402
    convert_points_to_wgs84,
    wgs84_to_gcj02,
)
from app.route_cognition.transit_paths import canonical_sha256  # noqa: E402


SCHEMA_VERSION = "transit_provider_request_v1"
SNAPSHOT_SCHEMA_VERSION = "transit_path_provider_snapshot_v1"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _validate_endpoint(endpoint: dict[str, Any]) -> None:
    if endpoint.get("binding_type") not in {
        "source_observation_candidate",
        "canonical_module_port",
    }:
        raise ValueError("unsupported transit endpoint binding")
    lonlat = endpoint.get("lonlat")
    if not isinstance(lonlat, list) or len(lonlat) != 2:
        raise ValueError("transit endpoint needs WGS-84 lonlat")
    float(lonlat[0])
    float(lonlat[1])


def build_snapshot(
    request: dict[str, Any],
    *,
    planners: dict[str, Callable[..., dict[str, Any]]] | None = None,
    elevation_builder: Callable[..., Any] = build_route_elevation_result,
) -> dict[str, Any]:
    if request.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported transit provider request schema")
    profile = request.get("routing_profile")
    if profile not in {"bicycling", "driving"}:
        raise ValueError("routing profile must be bicycling or driving")
    for endpoint_name in ("from", "to"):
        _validate_endpoint(request[endpoint_name])
    if request.get("research_verdict") != "connection_candidate":
        raise ValueError("provider builder only publishes connection candidates")

    default_planners = {
        "bicycling": plan_tencent_bicycling_route,
        "driving": plan_tencent_driving_route,
    }
    planner = (planners or default_planners)[profile]
    start_lon, start_lat = map(float, request["from"]["lonlat"])
    end_lon, end_lat = map(float, request["to"]["lonlat"])
    start_gcj = wgs84_to_gcj02(start_lat, start_lon)
    end_gcj = wgs84_to_gcj02(end_lat, end_lon)
    planned = planner(start_gcj, end_gcj)
    distance_m = float(planned.get("distance") or 0)
    points_gcj02 = planned.get("points") or []
    steps = planned.get("steps") or []
    if distance_m <= 0 or len(points_gcj02) < 2 or not steps:
        raise ValueError("Tencent provider response is incomplete")
    points_wgs84 = convert_points_to_wgs84(points_gcj02, "gcj02")
    geometry = [
        [round(float(point["lon"]), 7), round(float(point["lat"]), 7)]
        for point in points_wgs84
    ]
    elevation = elevation_builder(geometry)
    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "transit_key": request["transit_key"],
        "provider": f"tencent_{profile}_shadow",
        "provider_observed_at": request["provider_observed_at"],
        "status": "connectivity_shadow_not_access_verified",
        "research_verdict": "connection_candidate",
        "from": request["from"],
        "to": request["to"],
        "distance_m": distance_m,
        "provider_duration_raw": planned.get("duration"),
        "geometry_wgs84": geometry,
        "road_steps": steps,
        "elevation": {
            "algorithm_version": ROUTE_ELEVATION_METHOD,
            "point_count": elevation.point_count,
            "climb_m": elevation.climb,
            "descent_m": elevation.descent,
            "profile": elevation.profile,
        },
        "network_request_count": 1,
        "database_write_count": 0,
        "boundary": (
            "腾讯 profile 只作 connectivity shadow；不证明骑行许可、安全、路况、"
            "施工或完整出行可用。"
        ),
    }
    payload["snapshot_sha256"] = canonical_sha256(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    result = build_snapshot(request)
    _atomic_write(args.output, result)
    print(
        json.dumps(
            {
                "status": "complete",
                "transit_key": result["transit_key"],
                "provider": result["provider"],
                "distance_m": result["distance_m"],
                "climb_m": result["elevation"]["climb_m"],
                "descent_m": result["elevation"]["descent_m"],
                "snapshot_sha256": result["snapshot_sha256"],
                "database_write_count": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
