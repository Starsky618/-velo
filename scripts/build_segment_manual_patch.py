#!/usr/bin/env python3
"""从有来源记录的路由/手绘/Strava 部件生成赛段候选几何。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.route_book.manual_geometry_patch import (  # noqa: E402
    ManualGeometryPatchError,
    build_patch_candidate,
    load_patch_manifest,
    write_candidate_files,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="用可追溯手绘部件补赛段几何缺口",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-gpx", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest_path = args.manifest.resolve()
        manifest = load_patch_manifest(manifest_path)
        candidate = build_patch_candidate(manifest, manifest_dir=manifest_path.parent)
        write_candidate_files(
            candidate,
            json_path=args.output_json.resolve(),
            gpx_path=args.output_gpx.resolve(),
        )
    except ManualGeometryPatchError as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": "candidate_created",
                "segment_id": candidate["identity"]["source_segment_id"],
                "point_count": candidate["geometry"]["point_count"],
                "distance_m": candidate["geometry"]["distance_m"],
                "distance_delta_pct": candidate["geometry"]["distance_delta_pct"],
                "review_status": candidate["review"]["status"],
                "output_json": str(args.output_json.resolve()),
                "output_gpx": str(args.output_gpx.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
