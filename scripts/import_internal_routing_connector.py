#!/usr/bin/env python3
"""预检或写入一条仅供规划器使用的内部路线连接段。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.segment.internal_connectors import (
    InternalRoutingConnectorError,
    create_internal_routing_connector,
    prepare_internal_routing_connector,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gpx", type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--endpoint-a-segment-id", type=int, required=True)
    parser.add_argument(
        "--endpoint-a-position", choices=("start", "end"), required=True
    )
    parser.add_argument("--endpoint-b-segment-id", type=int, required=True)
    parser.add_argument(
        "--endpoint-b-position", choices=("start", "end"), required=True
    )
    parser.add_argument(
        "--traversal-policy",
        choices=("bidirectional", "a_to_b_only"),
        default="bidirectional",
    )
    parser.add_argument("--blocked-provider", default="tencent")
    parser.add_argument("--max-snap-m", type=float, default=100.0)
    parser.add_argument("--review-note")
    parser.add_argument("--reviewer-user-id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.apply and (
        args.reviewer_user_id is None
        or args.reviewer_user_id <= 0
        or not args.review_note
    ):
        parser.error("--apply 必须同时提供 --reviewer-user-id 和 --review-note")

    try:
        payload = args.gpx.read_bytes()
    except OSError as exc:
        print(f"ERROR: GPX 无法读取：{exc}")
        return 2

    db = SessionLocal()
    try:
        prepared = prepare_internal_routing_connector(
            db,
            gpx_payload=payload,
            city=args.city,
            endpoint_a_segment_id=args.endpoint_a_segment_id,
            endpoint_a_position=args.endpoint_a_position,
            endpoint_b_segment_id=args.endpoint_b_segment_id,
            endpoint_b_position=args.endpoint_b_position,
            max_snap_distance_m=args.max_snap_m,
        )
        if not args.apply:
            print(
                json.dumps(
                    {
                        "status": "preflight_passed",
                        "slug": args.slug,
                        "distance_m": round(prepared.distance_m, 1),
                        "source_point_count": prepared.source_point_count,
                        "stored_point_count": len(prepared.coordinates),
                        "input_was_reversed": prepared.input_was_reversed,
                        "endpoint_a_snap_m": round(prepared.endpoint_a_snap_m, 1),
                        "endpoint_b_snap_m": round(prepared.endpoint_b_snap_m, 1),
                        "traversal_policy": args.traversal_policy,
                        "geometry_hash": prepared.geometry_hash,
                    },
                    ensure_ascii=False,
                )
            )
            db.rollback()
            return 0

        result = create_internal_routing_connector(
            db,
            slug=args.slug,
            name=args.name,
            city=args.city,
            gpx_payload=payload,
            source_name=args.gpx.name,
            endpoint_a_segment_id=args.endpoint_a_segment_id,
            endpoint_a_position=args.endpoint_a_position,
            endpoint_b_segment_id=args.endpoint_b_segment_id,
            endpoint_b_position=args.endpoint_b_position,
            traversal_policy=args.traversal_policy,
            blocked_provider=args.blocked_provider,
            review_note=args.review_note,
            reviewer_user_id=args.reviewer_user_id,
            max_snap_distance_m=args.max_snap_m,
        )
        db.commit()
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 0
    except InternalRoutingConnectorError as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
