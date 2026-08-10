#!/usr/bin/env python3
"""预检或原子发布一批人工复核通过的路段 bundle。"""

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
from app.segment.verified_bundle_publisher import (
    SegmentPublicationResult,
    VerifiedSegmentBundleError,
    preflight_verified_segment_bundle,
    publish_verified_segment_bundle,
)
from app.segment.exceptions import SegmentOverlapError


def _read_bundle(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerifiedSegmentBundleError(f"bundle 不存在：{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifiedSegmentBundleError(f"bundle 无法读取：{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerifiedSegmentBundleError(f"bundle 顶层必须是对象：{path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true", help="不传时只做只读预检")
    parser.add_argument("--reviewer-user-id", type=int)
    args = parser.parse_args()
    if args.apply and (args.reviewer_user_id is None or args.reviewer_user_id <= 0):
        parser.error("--apply 必须同时提供正整数 --reviewer-user-id")

    paths = [path.resolve() for path in args.bundles]
    if len(set(paths)) != len(paths):
        parser.error("bundle 路径不能重复")

    db = SessionLocal()
    try:
        bundles = [(path, _read_bundle(path)) for path in paths]
        preflight = [
            (path, preflight_verified_segment_bundle(db, bundle))
            for path, bundle in bundles
        ]
        if not args.apply:
            print(
                json.dumps(
                    {
                        "status": "preflight_passed",
                        "count": len(preflight),
                        "items": [
                            {
                                "path": str(path),
                                "candidate_id": result.candidate_id,
                                "publication_status": (
                                    result.status
                                    if isinstance(result, SegmentPublicationResult)
                                    else "ready"
                                ),
                            }
                            for path, result in preflight
                        ],
                    },
                    ensure_ascii=False,
                )
            )
            db.rollback()
            return 0

        results = [
            publish_verified_segment_bundle(
                db,
                bundle=bundle,
                reviewer_user_id=args.reviewer_user_id,
            )
            for _path, bundle in bundles
        ]
        db.commit()
        print(
            json.dumps(
                {
                    "status": "committed",
                    "count": len(results),
                    "items": [asdict(result) for result in results],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (VerifiedSegmentBundleError, SegmentOverlapError) as exc:
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
