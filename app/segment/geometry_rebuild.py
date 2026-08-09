"""赛段标准几何替换与历史成绩重建核心。

本模块只负责 segment 自己的状态：准备候选几何、重新匹配活动、原子替换
segments/segment_efforts。路线认知的失效和来源登记由 admin 编排层调用下游
route_cognition hook，避免 segment 反向依赖路线认知。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from types import SimpleNamespace

from geoalchemy2 import WKTElement
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.common.geo import infer_city_from_coords
from app.common.geometry_hash import SEGMENT_GEOMETRY_NORMALIZATION_VERSION, stable_line_hash
from app.segment._geo_utils import _haversine, _sample_elevation_profile
from app.segment.algorithms import calculate_difficulty, calculate_max_gradient
from app.segment.coord_convert import convert_points_to_wgs84
from app.segment.models import Segment, SegmentEffort, SegmentGeometryRevision
from app.segment.service_create import _build_segment_elevation_result


SEGMENT_MATCH_LOCK_NAMESPACE = 92811
SEGMENT_GEOMETRY_EPOCH_LOCK_NAMESPACE = 92812
SEGMENT_GEOMETRY_EPOCH_LOCK_KEY = 0


class SegmentGeometryRevisionError(ValueError):
    """候选几何无法安全暂存或激活。"""


class ObsoleteSegmentGeometryAttempt(SegmentGeometryRevisionError):
    """旧 RQ attempt 已被新的 job_id 取代，必须只读退出。"""


@dataclass(frozen=True)
class PreparedSegmentGeometry:
    reference_line_wkt: str
    geometry_hash: str
    distance: float
    elevation_gain: float
    elevation_loss: float
    avg_gradient: float
    elevation_profile_json: str
    max_gradient: float | None
    difficulty: str
    city: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float


@dataclass(frozen=True)
class EffortCandidate:
    activity_id: int
    user_id: int
    elapsed_time: int
    avg_speed: float
    avg_power: float | None
    start_index: int
    end_index: int


@dataclass(frozen=True)
class ActivationSummary:
    segment_id: int
    revision_id: int
    matched_efforts: int
    inserted_efforts: int
    updated_efforts: int
    deleted_efforts: int


def parse_linestring_wkt(wkt: str) -> list[tuple[float, float]]:
    """把 WKT (lon lat) 转成 matcher 使用的 (lat, lon)。"""
    match = re.search(r"LINESTRING\s*\((.+)\)", wkt, re.IGNORECASE)
    if not match:
        return []
    coordinates: list[tuple[float, float]] = []
    for pair in match.group(1).split(","):
        lon, lat = (float(value) for value in pair.strip().split()[:2])
        coordinates.append((lat, lon))
    return coordinates


def prepare_segment_geometry(
    reference_points: list[dict],
    *,
    coordinate_system: str,
) -> PreparedSegmentGeometry:
    """把腾讯驾车折线变成可激活的 WGS84 标准几何和 GLO-30 派生数据。"""
    points = [dict(point) for point in reference_points]
    points = convert_points_to_wgs84(points, coordinate_system)
    if len(points) < 2:
        raise SegmentGeometryRevisionError("标准几何至少需要 2 个点")

    distance = sum(
        _haversine(
            points[index - 1]["lat"],
            points[index - 1]["lon"],
            points[index]["lat"],
            points[index]["lon"],
        )
        for index in range(1, len(points))
    )
    if distance < 1.0:
        raise SegmentGeometryRevisionError("标准几何距离过短")

    elevation_result = _build_segment_elevation_result(points)
    elevations = [float(point[2]) for point in elevation_result.snapshot]
    if len(elevations) != len(points):
        raise SegmentGeometryRevisionError("GLO-30 海拔点数与标准几何不一致")

    elevated_points = [
        SimpleNamespace(
            latitude=point["lat"],
            longitude=point["lon"],
            elevation=elevations[index],
        )
        for index, point in enumerate(points)
    ]
    max_gradient = calculate_max_gradient(elevated_points)
    elevation_gain = float(elevation_result.climb)
    elevation_loss = float(elevation_result.descent)
    avg_gradient = round((elevations[-1] - elevations[0]) / distance * 100, 1)
    difficulty = calculate_difficulty(distance, elevation_gain, max_gradient)
    city = infer_city_from_coords(points[0]["lat"], points[0]["lon"])
    elevation_profile = _sample_elevation_profile(
        [{"ele": point[1]} for point in elevation_result.profile],
        target_count=80,
    )
    wkt = "LINESTRING(" + ",".join(
        f"{point['lon']} {point['lat']}" for point in points
    ) + ")"

    return PreparedSegmentGeometry(
        reference_line_wkt=wkt,
        geometry_hash=stable_line_hash(wkt),
        distance=distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        avg_gradient=avg_gradient,
        elevation_profile_json=json.dumps(elevation_profile),
        max_gradient=max_gradient,
        difficulty=difficulty,
        city=city,
        start_lat=points[0]["lat"],
        start_lon=points[0]["lon"],
        end_lat=points[-1]["lat"],
        end_lon=points[-1]["lon"],
    )


def stage_geometry_revision(
    db: Session,
    *,
    segment_id: int,
    prepared: PreparedSegmentGeometry,
    source_url: str,
    coordinate_system: str,
    created_by: int,
) -> SegmentGeometryRevision:
    """暂存候选几何；不修改标准线和成绩。事务由调用方提交。"""
    if not source_url.strip():
        raise SegmentGeometryRevisionError("source_url 不能为空")
    # 先锁稳定的 segment 父行，再查 pending，避免两个并发请求都通过“无任务”检查，
    # 最后只靠 partial unique 抛出难以解释的 IntegrityError。
    row = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("reference_line_wkt"))
        .filter(Segment.id == segment_id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise SegmentGeometryRevisionError("赛段不存在")
    segment, previous_wkt = row
    pending = (
        db.query(SegmentGeometryRevision.id)
        .filter(
            SegmentGeometryRevision.segment_id == segment_id,
            SegmentGeometryRevision.status.in_(("staged", "processing")),
        )
        .first()
    )
    if pending is not None:
        raise SegmentGeometryRevisionError("该赛段已有正在处理的标准几何替换")
    if not previous_wkt:
        raise SegmentGeometryRevisionError("赛段缺少现有标准几何")

    endpoint_tolerance = max(
        200.0,
        min(float(segment.match_tolerance or 50.0) * 4, 500.0),
    )
    start_shift = _haversine(
        segment.start_lat,
        segment.start_lon,
        prepared.start_lat,
        prepared.start_lon,
    )
    end_shift = _haversine(
        segment.end_lat,
        segment.end_lon,
        prepared.end_lat,
        prepared.end_lon,
    )
    if start_shift > endpoint_tolerance or end_shift > endpoint_tolerance:
        raise SegmentGeometryRevisionError(
            "候选线起终点偏离现有赛段，不能在同一个 segment_id 下覆盖"
        )
    candidate_wkt = prepared.reference_line_wkt
    if db.bind.dialect.name == "postgresql":
        candidate_wkt = db.execute(
            text("SELECT ST_AsText(ST_GeomFromText(:candidate_wkt, 4326))"),
            {"candidate_wkt": candidate_wkt},
        ).scalar_one()
    candidate_hash = stable_line_hash(candidate_wkt)
    previous_hash = stable_line_hash(previous_wkt)
    if previous_hash == candidate_hash:
        raise SegmentGeometryRevisionError("候选几何与当前标准几何相同")

    previous_snapshot = {
        "distance": segment.distance,
        "elevation_gain": segment.elevation_gain,
        "elevation_loss": segment.elevation_loss,
        "avg_gradient": segment.avg_gradient,
        "elevation_profile": segment.elevation_profile,
        "max_gradient": segment.max_gradient,
        "difficulty": segment.difficulty,
        "city": segment.city,
        "start_lat": segment.start_lat,
        "start_lon": segment.start_lon,
        "end_lat": segment.end_lat,
        "end_lon": segment.end_lon,
    }
    revision = SegmentGeometryRevision(
        segment_id=segment_id,
        status="staged",
        previous_geometry_hash=previous_hash,
        candidate_geometry_hash=candidate_hash,
        previous_reference_line_wkt=previous_wkt,
        candidate_reference_line_wkt=candidate_wkt,
        previous_snapshot_json=json.dumps(previous_snapshot, ensure_ascii=False),
        distance=prepared.distance,
        elevation_gain=prepared.elevation_gain,
        elevation_loss=prepared.elevation_loss,
        avg_gradient=prepared.avg_gradient,
        elevation_profile=prepared.elevation_profile_json,
        max_gradient=prepared.max_gradient,
        difficulty=prepared.difficulty,
        city=prepared.city,
        start_lat=prepared.start_lat,
        start_lon=prepared.start_lon,
        end_lat=prepared.end_lat,
        end_lon=prepared.end_lon,
        match_tolerance=segment.match_tolerance if segment.match_tolerance is not None else 50.0,
        min_match_ratio=segment.min_match_ratio if segment.min_match_ratio is not None else 0.8,
        source_url=source_url,
        routing_provider="tencent",
        routing_mode="driving",
        original_coordinate_system=coordinate_system,
        normalization_version=SEGMENT_GEOMETRY_NORMALIZATION_VERSION,
        created_by=created_by,
    )
    db.add(revision)
    db.flush()
    return revision


def mark_revision_processing(
    db: Session,
    revision_id: int,
    attempt_job_id: str,
) -> SegmentGeometryRevision:
    revision = (
        db.query(SegmentGeometryRevision)
        .filter(SegmentGeometryRevision.id == revision_id)
        .with_for_update()
        .first()
    )
    if revision is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if revision.job_id != attempt_job_id:
        raise ObsoleteSegmentGeometryAttempt("RQ attempt 已过期，不能修改当前任务")
    if revision.status == "active":
        return revision
    if revision.status not in {"staged", "processing"}:
        raise SegmentGeometryRevisionError(f"标准几何替换任务不可执行：{revision.status}")
    revision.status = "processing"
    revision.started_at = revision.started_at or datetime.now(timezone.utc)
    revision.error_message = None
    db.flush()
    return revision


def collect_effort_candidates(
    db: Session,
    revision: SegmentGeometryRevision,
) -> dict[int, EffortCandidate]:
    """对旧成绩和新线附近活动重新跑完整 matcher。"""
    activity_ids = candidate_activity_ids(
        db,
        segment_id=revision.segment_id,
        candidate_wkt=revision.candidate_reference_line_wkt,
    )
    results: dict[int, EffortCandidate] = {}
    for activity_id in activity_ids:
        effort = match_activity_to_revision(db, activity_id, revision)
        if effort is not None:
            results[activity_id] = effort
    return results


def candidate_activity_ids(db: Session, *, segment_id: int, candidate_wkt: str) -> list[int]:
    """候选集 = 旧成绩活动 + 新标准线 100m 内的已完成骑行。"""
    existing_ids = {
        row[0]
        for row in db.query(SegmentEffort.activity_id)
        .filter(SegmentEffort.segment_id == segment_id)
        .all()
    }
    if db.bind.dialect.name != "postgresql":
        return sorted(existing_ids)

    nearby_ids = set(
        db.execute(
            text(
                """
                SELECT DISTINCT tp.activity_id
                FROM trackpoints AS tp
                JOIN activities AS a ON a.id = tp.activity_id
                WHERE tp.geom IS NOT NULL
                  AND a.status = 'completed'
                  AND a.activity_type = 'cycling'
                  AND a.duplicate_of IS NULL
                  AND ST_DWithin(
                        tp.geom::geography,
                        ST_GeomFromText(:candidate_wkt, 4326)::geography,
                        100
                  )
                """
            ),
            {"candidate_wkt": candidate_wkt},
        ).scalars()
    )
    return sorted(existing_ids | nearby_ids)


def match_activity_to_revision(
    db: Session,
    activity_id: int,
    revision: SegmentGeometryRevision,
) -> EffortCandidate | None:
    from app.segment.matcher import match_segment

    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if activity is None or activity.status != "completed":
        return None
    if activity.activity_type != "cycling" or activity.duplicate_of is not None:
        return None
    trackpoints = (
        db.query(Trackpoint)
        .filter(Trackpoint.activity_id == activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )
    if len(trackpoints) < 2:
        return None

    reference_coords = parse_linestring_wkt(revision.candidate_reference_line_wkt)
    if len(reference_coords) < 2:
        raise SegmentGeometryRevisionError("候选标准几何不是有效 LINESTRING")
    result = match_segment(
        trackpoints=[
            {
                "lat": point.latitude,
                "lon": point.longitude,
                "time": point.timestamp,
                "seq": point.seq,
            }
            for point in trackpoints
        ],
        segment_start=(revision.start_lat, revision.start_lon),
        segment_end=(revision.end_lat, revision.end_lon),
        reference_coords=reference_coords,
        match_tolerance=revision.match_tolerance,
        min_match_ratio=revision.min_match_ratio,
    )
    if not result["matched"] or result["elapsed_time"] <= 0:
        return None

    start_index = result["start_index"]
    end_index = result["end_index"]
    powers = [
        point.power
        for point in trackpoints
        if start_index <= point.seq <= end_index and point.power is not None
    ]
    elapsed_time = result["elapsed_time"]
    return EffortCandidate(
        activity_id=activity.id,
        user_id=activity.user_id,
        elapsed_time=elapsed_time,
        avg_speed=round((revision.distance / elapsed_time) * 3.6, 1),
        avg_power=round(sum(powers) / len(powers), 1) if powers else None,
        start_index=start_index,
        end_index=end_index,
    )


def acquire_segment_match_lock(db: Session, segment_id: int) -> None:
    """让实时匹配和几何切换按 segment 串行，关闭旧线成绩晚写入竞态。"""
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :segment_id)"),
            {"namespace": SEGMENT_MATCH_LOCK_NAMESPACE, "segment_id": segment_id},
        )


def acquire_geometry_match_read_lock(db: Session) -> None:
    """活动匹配从粗筛到成绩提交持有共享锁，避免跨几何版本漏匹配。"""
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock_shared(:namespace, :lock_key)"),
            {
                "namespace": SEGMENT_GEOMETRY_EPOCH_LOCK_NAMESPACE,
                "lock_key": SEGMENT_GEOMETRY_EPOCH_LOCK_KEY,
            },
        )


def acquire_geometry_activation_lock(db: Session) -> None:
    """几何最终追扫和切换持有排他锁，与所有实时活动粗筛形成读写屏障。"""
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_key)"),
            {
                "namespace": SEGMENT_GEOMETRY_EPOCH_LOCK_NAMESPACE,
                "lock_key": SEGMENT_GEOMETRY_EPOCH_LOCK_KEY,
            },
        )


def activate_revision_core(
    db: Session,
    *,
    revision_id: int,
    attempt_job_id: str,
    precomputed_efforts: dict[int, EffortCandidate],
) -> ActivationSummary:
    """在调用方事务中原子替换标准线和成绩；不 commit。"""
    revision_ref = (
        db.query(
            SegmentGeometryRevision.id,
            SegmentGeometryRevision.segment_id,
            SegmentGeometryRevision.status,
            SegmentGeometryRevision.job_id,
        )
        .filter(SegmentGeometryRevision.id == revision_id)
        .first()
    )
    if revision_ref is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if revision_ref.job_id != attempt_job_id:
        raise ObsoleteSegmentGeometryAttempt("RQ attempt 已过期，不能激活当前任务")
    if revision_ref.status == "active":
        existing_count = db.query(SegmentEffort.id).filter_by(
            segment_id=revision_ref.segment_id
        ).count()
        return ActivationSummary(
            revision_ref.segment_id, revision_ref.id, existing_count, 0, 0, 0
        )
    if revision_ref.status != "processing":
        raise SegmentGeometryRevisionError(
            f"标准几何替换任务不可激活：{revision_ref.status}"
        )

    # 必须在最终候选追扫之前拿全局排他屏障。活动导入已先提交 Activity，随后
    # auto_match 从粗筛到 effort commit 持共享锁：要么旧版匹配先完成、这里能看到
    # 活动并重算；要么这里先切换完成、auto_match 之后按新版几何粗筛。
    acquire_geometry_activation_lock(db)
    acquire_segment_match_lock(db, revision_ref.segment_id)
    row = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("reference_line_wkt"))
        .filter(Segment.id == revision_ref.segment_id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise SegmentGeometryRevisionError("赛段不存在")
    segment, current_wkt = row
    # 全链路锁序统一为 epoch -> Segment -> revision。retry/stage 不拿 epoch，
    # 但同样先 Segment 后 revision，因此旧 worker 与 Admin 恢复不会形成等待环。
    revision = (
        db.query(SegmentGeometryRevision)
        .filter(SegmentGeometryRevision.id == revision_id)
        .with_for_update()
        .first()
    )
    if revision is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if revision.job_id != attempt_job_id:
        raise ObsoleteSegmentGeometryAttempt("RQ attempt 已过期，不能激活当前任务")
    if revision.status == "active":
        existing_count = db.query(SegmentEffort.id).filter_by(
            segment_id=revision.segment_id
        ).count()
        return ActivationSummary(revision.segment_id, revision.id, existing_count, 0, 0, 0)
    if revision.status != "processing":
        raise SegmentGeometryRevisionError(f"标准几何替换任务不可激活：{revision.status}")
    if stable_line_hash(current_wkt) != revision.previous_geometry_hash:
        raise SegmentGeometryRevisionError("标准几何已被其他任务修改，本任务已过期")

    # 再扫一次候选集，补上首轮计算后刚导入的活动。实时 matcher 会拿同一把锁，
    # 因此最终提交后不会再把旧线结果写回来。
    effort_results = dict(precomputed_efforts)
    for activity_id in candidate_activity_ids(
        db,
        segment_id=revision.segment_id,
        candidate_wkt=revision.candidate_reference_line_wkt,
    ):
        if activity_id not in effort_results:
            effort = match_activity_to_revision(db, activity_id, revision)
            if effort is not None:
                effort_results[activity_id] = effort

    existing_efforts = {
        effort.activity_id: effort
        for effort in db.query(SegmentEffort)
        .filter(SegmentEffort.segment_id == revision.segment_id)
        .all()
    }
    inserted = 0
    updated = 0
    for activity_id, candidate in effort_results.items():
        effort = existing_efforts.pop(activity_id, None)
        if effort is None:
            effort = SegmentEffort(segment_id=revision.segment_id, activity_id=activity_id)
            db.add(effort)
            inserted += 1
        else:
            updated += 1
        effort.user_id = candidate.user_id
        effort.elapsed_time = candidate.elapsed_time
        effort.avg_speed = candidate.avg_speed
        effort.avg_power = candidate.avg_power
        effort.start_index = candidate.start_index
        effort.end_index = candidate.end_index

    deleted = len(existing_efforts)
    for effort in existing_efforts.values():
        db.delete(effort)

    segment.reference_line = WKTElement(revision.candidate_reference_line_wkt, srid=4326)
    segment.distance = revision.distance
    segment.elevation_gain = revision.elevation_gain
    segment.elevation_loss = revision.elevation_loss
    segment.avg_gradient = revision.avg_gradient
    segment.elevation_profile = revision.elevation_profile
    segment.max_gradient = revision.max_gradient
    segment.difficulty = revision.difficulty
    segment.city = revision.city
    segment.start_lat = revision.start_lat
    segment.start_lon = revision.start_lon
    segment.end_lat = revision.end_lat
    segment.end_lon = revision.end_lon

    db.query(SegmentGeometryRevision).filter(
        SegmentGeometryRevision.segment_id == revision.segment_id,
        SegmentGeometryRevision.id != revision.id,
        SegmentGeometryRevision.status == "active",
    ).update({SegmentGeometryRevision.status: "superseded"}, synchronize_session=False)
    revision.status = "active"
    revision.activated_at = datetime.now(timezone.utc)
    revision.error_message = None
    db.flush()
    return ActivationSummary(
        segment_id=revision.segment_id,
        revision_id=revision.id,
        matched_efforts=len(effort_results),
        inserted_efforts=inserted,
        updated_efforts=updated,
        deleted_efforts=deleted,
    )


def mark_revision_failed(
    db: Session,
    revision_id: int,
    error_message: str,
    *,
    attempt_job_id: str,
) -> None:
    # 条件 UPDATE 会在等待并发激活事务后重新判断 status，避免另一个重复任务已把
    # 几何切成 active，本任务的迟到异常却再把审计状态覆盖成 failed。
    db.query(SegmentGeometryRevision).filter(
        SegmentGeometryRevision.id == revision_id,
        SegmentGeometryRevision.job_id == attempt_job_id,
        SegmentGeometryRevision.status.in_(("staged", "processing")),
    ).update(
        {
            SegmentGeometryRevision.status: "failed",
            SegmentGeometryRevision.error_message: error_message[:2000],
        },
        synchronize_session=False,
    )
    db.commit()
