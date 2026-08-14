#!/usr/bin/env python3
"""离线重放一条有向海拔剖面的 VELO ClimbPlan v1。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.elevation.climb_planner import build_climb_plan, build_rider_climb_plan


INPUT_SCHEMA_VERSION = "climb_plan_input_v1"
RESULT_SCHEMA_VERSION = "climb_plan_result_v1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def analyze(payload: dict) -> dict:
    if payload.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError("unsupported climb plan input schema")
    route_key = payload.get("route_key")
    geometry_hash = payload.get("geometry_hash")
    traversal = payload.get("traversal")
    if not isinstance(route_key, str) or not route_key.strip():
        raise ValueError("route_key is required")
    if not isinstance(geometry_hash, str) or len(geometry_hash) != 64:
        raise ValueError("geometry_hash must be a sha256 string")
    if traversal not in {"forward", "reverse", "geometry_order"}:
        raise ValueError("traversal must be forward, reverse, or geometry_order")
    profile = payload.get("profile")
    if not isinstance(profile, list) or len(profile) < 2:
        raise ValueError("profile needs at least two distance/elevation points")
    try:
        distances = [float(point[0]) for point in profile]
        elevations = [float(point[1]) for point in profile]
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("profile points must be [distance_m, elevation_m]") from exc
    source = payload.get("source")
    if not isinstance(source, dict) or not source.get("method"):
        raise ValueError("source.method is required")
    variants = {}
    for name, variant_profile in (payload.get("smoothing_variants") or {}).items():
        if not isinstance(variant_profile, list) or len(variant_profile) != len(profile):
            raise ValueError("smoothing variant must align with the main profile")
        variants[str(name)] = [float(point[1]) for point in variant_profile]

    climb_plan = build_climb_plan(
        distances,
        elevations,
        source_method=str(source["method"]),
        horizontal_resolution_m=source.get("horizontal_resolution_m"),
        traversal_direction=traversal,
        smoothing_variants=variants,
        residual_mad_m=source.get("residual_mad_m"),
    )
    rider_payload = payload.get("rider_profile")
    rider_plan = None
    if rider_payload is not None:
        if not isinstance(rider_payload, dict):
            raise ValueError("rider_profile must be an object")
        rider_plan = build_rider_climb_plan(
            climb_plan,
            ftp_w=rider_payload.get("ftp_w"),
            rider_mass_kg=rider_payload.get("rider_mass_kg"),
            bike_type=rider_payload.get("bike_type"),
            power_curve_w=rider_payload.get("power_curve_w"),
        )

    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "route_key": route_key,
        "geometry_hash": geometry_hash,
        "traversal": traversal,
        "input_sha256": _sha256(payload),
        "climb_plan": climb_plan,
        "rider_plan": rider_plan,
    }
    result["result_sha256"] = _sha256(result)
    return result


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    os.chmod(temp_path, 0o644)
    os.replace(temp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = analyze(payload)
    if args.output:
        _write_atomic(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
