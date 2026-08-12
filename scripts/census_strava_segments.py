#!/usr/bin/env python3
"""两遍枚举太原西山 Strava 骑行赛段，并原子写入内部来源观测表。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from geoalchemy2.elements import WKTElement
from sqlalchemy import func


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal
from app.route_cognition.census_models import (
    SegmentCensusBatch,
    SegmentSourceObservation,
)
from app.route_cognition.strava_census import (
    Bounds,
    compare_passes,
    enumerate_source_visible_segments,
    fetch_segment_observation,
)
from app.strava.client import StravaClient
from app.user.models import User


REGION_KEY = "taiyuan_xishan"
REGION_VERSION = "taiyuan_xishan_v1"
ROOT_BOUNDS = Bounds(37.65, 112.23, 38.02, 112.46)
PROTOCOL_VERSION = "strava_explore_quadtree_v1"
VISIBILITY_CONTEXT = "authorized_athlete_public_segments"


class RequestPacer:
    def __init__(self, interval_seconds: float, max_requests: int) -> None:
        self.interval_seconds = interval_seconds
        self.max_requests = max_requests
        self.count = 0
        self._last_request_started: float | None = None

    def before_request(self) -> None:
        if self.count >= self.max_requests:
            raise RuntimeError(f"本批次 API 请求超过上限 {self.max_requests}")
        now = time.monotonic()
        if self._last_request_started is not None:
            remaining = self.interval_seconds - (now - self._last_request_started)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_started = time.monotonic()
        self.count += 1
        if self.count == 1 or self.count % 20 == 0:
            print(
                json.dumps({"progress_api_requests": self.count}),
                file=sys.stderr,
                flush=True,
            )


class ShortLivedStravaClient:
    """每次 API 调用独占一个短 session，避免整批普查长期持有用户行锁。"""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id

    def _call(self, method_name: str, *args):
        db = SessionLocal()
        try:
            user = db.get(User, self.user_id)
            if user is None:
                raise RuntimeError("Strava 授权用户已不存在")
            client = StravaClient(db, user)
            return getattr(client, method_name)(*args)
        finally:
            db.close()

    def explore_segments(self, bounds):
        return self._call("explore_segments", bounds)

    def get_segment_detail(self, segment_id: int):
        return self._call("get_segment_detail", segment_id)

    def get_segment_latlng_stream(self, segment_id: int):
        return self._call("get_segment_latlng_stream", segment_id)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--enumeration-only",
        action="store_true",
        help="只跑两遍区域枚举，不抓详情、不写数据库",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="抓详情和来源几何，并在末尾一次性写入数据库",
    )
    parser.add_argument("--strava-user-id", type=int)
    parser.add_argument("--batch-id")
    parser.add_argument("--max-depth", type=int, default=9)
    parser.add_argument("--request-interval-seconds", type=float, default=5.2)
    parser.add_argument("--max-api-requests", type=int, default=950)
    args = parser.parse_args(argv)
    if args.max_depth < 0:
        parser.error("--max-depth 不能小于 0")
    if args.request_interval_seconds < 4.6:
        parser.error("--request-interval-seconds 不能小于 4.6")
    if not 1 <= args.max_api_requests <= 950:
        parser.error("--max-api-requests 必须在 1..950")
    if args.batch_id and len(args.batch_id) > 64:
        parser.error("--batch-id 最长 64 字符")
    return args


def _select_strava_user(db, user_id: int | None) -> User:
    query = db.query(User).filter(
        User.strava_access_token.isnot(None),
        User.strava_refresh_token.isnot(None),
    )
    if user_id is not None:
        user = query.filter(User.id == user_id).one_or_none()
        if user is None:
            raise RuntimeError("指定用户没有完整 Strava 授权")
        return user
    users = query.limit(2).all()
    if len(users) != 1:
        raise RuntimeError("必须用 --strava-user-id 明确选择一个已绑定用户")
    return users[0]


def _default_batch_id(started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return f"xishan-{timestamp}-{uuid4().hex[:8]}"


def _seen_passes(segment_id: int, passes: list) -> dict[str, list[str]]:
    return {
        str(number): result.seen_cells.get(segment_id, [])
        for number, result in enumerate(passes, start=1)
        if segment_id in result.seen_cells
    }


def _enumeration_status(passes: list, diff: dict) -> str:
    clean = all(not item.errors and not item.saturated_cells for item in passes)
    return "source_visible_complete" if clean and diff["identical"] else "indeterminate"


def _result_summary(*, batch_id: str | None, status: str, passes: list, diff: dict, request_count: int) -> dict:
    union_ids = sorted(set().union(*(item.segment_ids for item in passes)))
    return {
        "batch_id": batch_id,
        "region_version": REGION_VERSION,
        "root_bounds": ROOT_BOUNDS.as_tuple(),
        "enumeration_status": status,
        "unique_segment_count": len(union_ids),
        "pass_counts": [len(item.segment_ids) for item in passes],
        "passes_identical": diff["identical"],
        "saturated_cell_count": sum(len(item.saturated_cells) for item in passes),
        "enumeration_error_count": sum(len(item.errors) for item in passes),
        "api_request_count": request_count,
    }


def run(args: argparse.Namespace) -> dict:
    started_at = datetime.now(timezone.utc)
    pacer = RequestPacer(args.request_interval_seconds, args.max_api_requests)
    bootstrap_db = SessionLocal()
    try:
        user_id = _select_strava_user(bootstrap_db, args.strava_user_id).id
    finally:
        bootstrap_db.close()

    client = ShortLivedStravaClient(user_id)
    passes = [
        enumerate_source_visible_segments(
            client,
            ROOT_BOUNDS,
            max_depth=args.max_depth,
            before_request=pacer.before_request,
        )
        for _ in range(2)
    ]
    diff = compare_passes(passes[0], passes[1])
    status = _enumeration_status(passes, diff)
    if args.enumeration_only:
        return _result_summary(
            batch_id=None,
            status=status,
            passes=passes,
            diff=diff,
            request_count=pacer.count,
        )

    batch_id = args.batch_id or _default_batch_id(started_at)
    summaries: dict[int, dict] = {}
    for result in passes:
        summaries.update(result.segment_summaries)
    observations = []
    for segment_id in sorted(summaries):
        observation = fetch_segment_observation(
            client,
            segment_id,
            summaries[segment_id],
            seen_passes=_seen_passes(segment_id, passes),
            root_bounds=ROOT_BOUNDS,
            before_request=pacer.before_request,
            observed_at=datetime.now(timezone.utc),
        )
        observations.append(observation)

    finished_at = datetime.now(timezone.utc)
    detail_complete_count = sum(
        item["detail_status"] == "complete" for item in observations
    )
    geometry_complete_count = sum(
        item["geometry_status"] == "complete" for item in observations
    )
    leaderboard_complete_count = sum(
        item["leaderboard_status"] == "complete" for item in observations
    )
    observation_error_count = sum(
        len(item["failure_json"] or {}) for item in observations
    )
    batch = SegmentCensusBatch(
        id=batch_id,
        region_key=REGION_KEY,
        region_version=REGION_VERSION,
        source_platform="strava",
        activity_type="riding",
        protocol_version=PROTOCOL_VERSION,
        visibility_context=VISIBILITY_CONTEXT,
        root_south=ROOT_BOUNDS.south,
        root_west=ROOT_BOUNDS.west,
        root_north=ROOT_BOUNDS.north,
        root_east=ROOT_BOUNDS.east,
        max_depth=args.max_depth,
        status=status,
        request_count=pacer.count,
        unique_segment_count=len(observations),
        detail_complete_count=detail_complete_count,
        geometry_complete_count=geometry_complete_count,
        leaderboard_complete_count=leaderboard_complete_count,
        saturated_cell_count=sum(len(item.saturated_cells) for item in passes),
        error_count=sum(len(item.errors) for item in passes) + observation_error_count,
        pass_summaries_json=[item.audit_summary() for item in passes],
        pass_diff_json=diff,
        raw_response_retained=False,
        started_at=started_at,
        finished_at=finished_at,
    )
    write_db = SessionLocal()
    try:
        if write_db.get(SegmentCensusBatch, batch_id) is not None:
            raise RuntimeError(f"batch_id 已存在：{batch_id}")
        write_db.add(batch)
        for item in observations:
            wkt = item.pop("source_line_wkt")
            write_db.add(
                SegmentSourceObservation(
                    census_batch_id=batch_id,
                    source_line=WKTElement(wkt, srid=4326) if wkt else None,
                    **item,
                )
            )
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        write_db.close()

    readback = SessionLocal()
    try:
        stored = readback.get(SegmentCensusBatch, batch_id)
        stored_count = (
            readback.query(func.count(SegmentSourceObservation.id))
            .filter(SegmentSourceObservation.census_batch_id == batch_id)
            .scalar()
        )
        if stored is None or stored_count != stored.unique_segment_count:
            raise RuntimeError("数据库回读与提交结果不一致")
        result = _result_summary(
            batch_id=batch_id,
            status=stored.status,
            passes=passes,
            diff=diff,
            request_count=stored.request_count,
        )
        result.update(
            {
                "database_status": "committed_and_read_back",
                "stored_observation_count": stored_count,
                "detail_complete_count": stored.detail_complete_count,
                "geometry_complete_count": stored.geometry_complete_count,
                "leaderboard_complete_count": stored.leaderboard_complete_count,
                "error_count": stored.error_count,
            }
        )
        return result
    finally:
        readback.close()


def main() -> int:
    args = _parse_args()
    try:
        result = run(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}:{str(exc)[:240]}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
