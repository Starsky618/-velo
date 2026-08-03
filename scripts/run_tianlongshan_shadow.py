#!/usr/bin/env python3
"""Run the deterministic Tianlongshan door-to-door shadow agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ride_planning.shadow import (  # noqa: E402
    RideRequest,
    TianlongshanShadowAgent,
    render_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--minutes", required=True, type=int)
    parser.add_argument("--max-climb-m", required=True, type=int)
    parser.add_argument("--urban-exposure", required=True, choices=("low", "medium", "high"))
    parser.add_argument(
        "--model",
        default="scripted",
        choices=("scripted",),
        help="Free repeatable mode; no live provider is used in this vertical slice.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixture_path = PROJECT_ROOT / "tests/fixtures/ride_planning/tianlongshan_world.json"
    world = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = RideRequest(
        origin=args.origin,
        minutes=args.minutes,
        max_climb_m=args.max_climb_m,
        urban_exposure=args.urban_exposure,
    )
    result = TianlongshanShadowAgent(world).run(request)
    print(render_result(request, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
