"""Admin 标准赛段几何替换编排：segment 核心 + route cognition hook + RQ。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from rq.job import Job
from rq.exceptions import NoSuchJobError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.queue import segment_rebuilds_queue
from app.route_cognition.services.segment_geometry_change import record_geometry_change
from app.segment.geometry_rebuild import (
    SEGMENT_GEOMETRY_GATE_VERSION,
    SegmentGeometryRevisionError,
    activate_revision_core,
    collect_effort_candidates,
    mark_revision_failed,
    mark_revision_processing,
    prepare_segment_geometry_from_evidence,
    stage_geometry_revision,
)
from app.segment.models import Segment, SegmentGeometryRevision


logger = logging.getLogger(__name__)
_TASK_PATH = "app.admin.segment_geometry_workflow.run_segment_geometry_revision_task"
_STAGED_RECOVERY_AFTER = timedelta(minutes=5)
_PROCESSING_RECOVERY_AFTER = timedelta(minutes=75)


class SegmentGeometryWorkflowError(RuntimeError):
    """任务已经落库但无法安全派发或执行。"""


def request_segment_geometry_rebuild(
    db: Session,
    *,
    segment_id: int,
    source_observation_id: str,
    routing_candidate_id: int,
    admin_id: int,
) -> SegmentGeometryRevision:
    """准备、暂存并派发替换任务；此时公开标准线仍完全不变。"""
    prepared = prepare_segment_geometry_from_evidence(
        db,
        segment_id=segment_id,
        source_observation_id=source_observation_id,
        routing_candidate_id=routing_candidate_id,
    )
    revision = stage_geometry_revision(
        db,
        segment_id=segment_id,
        prepared=prepared,
        source_observation_id=source_observation_id,
        routing_candidate_id=routing_candidate_id,
        created_by=admin_id,
    )
    db.commit()
    db.refresh(revision)

    return _dispatch_revision(db, revision)


def retry_segment_geometry_revision(
    db: Session,
    *,
    segment_id: int,
    revision_id: int,
) -> SegmentGeometryRevision:
    """恢复失败或租约过期的任务；Admin 显式触发，不能重跑健康任务。"""
    # 与新建 revision 使用同一父行锁，避免 failed -> staged 与新请求竞争。
    segment = (
        db.query(Segment.id)
        .filter(Segment.id == segment_id)
        .with_for_update()
        .first()
    )
    if segment is None:
        raise SegmentGeometryRevisionError("赛段不存在")
    revision = (
        db.query(SegmentGeometryRevision)
        .filter(
            SegmentGeometryRevision.id == revision_id,
            SegmentGeometryRevision.segment_id == segment_id,
        )
        .populate_existing()
        .with_for_update()
        .first()
    )
    if revision is None:
        raise SegmentGeometryRevisionError("标准几何替换任务不存在")
    if (
        revision.source_observation_id is None
        or revision.routing_candidate_id is None
        or revision.candidate_payload_hash is None
        or revision.validation_version != SEGMENT_GEOMETRY_GATE_VERSION
    ):
        raise SegmentGeometryRevisionError("历史几何任务缺少当前门禁证据，不能重试；请新建 revision")

    now = datetime.now(timezone.utc)
    retrying_processing = revision.status == "processing"
    if revision.status == "failed":
        pass
    elif revision.status == "staged":
        dispatch_age = revision.dispatch_claimed_at or revision.created_at
        if not _is_older_than(dispatch_age, now - _STAGED_RECOVERY_AFTER):
            raise SegmentGeometryRevisionError("暂存任务仍在有效派发窗口内，不能重复派发")
        if revision.job_id is not None and _rq_job_is_live(revision.job_id):
            raise SegmentGeometryRevisionError("后台任务仍在队列或执行中，不能重复派发")
    elif revision.status == "processing":
        if not _is_older_than(revision.started_at, now - _PROCESSING_RECOVERY_AFTER):
            raise SegmentGeometryRevisionError("重建任务仍在有效执行租约内，不能重复派发")
    else:
        raise SegmentGeometryRevisionError(f"当前任务状态不可重试：{revision.status}")

    other_pending = (
        db.query(SegmentGeometryRevision.id)
        .filter(
            SegmentGeometryRevision.segment_id == segment_id,
            SegmentGeometryRevision.id != revision_id,
            SegmentGeometryRevision.status.in_(("staged", "processing")),
        )
        .first()
    )
    if other_pending is not None:
        raise SegmentGeometryRevisionError("该赛段已有另一个正在处理的标准几何替换")

    revision.status = "processing" if retrying_processing else "staged"
    revision.job_id = _new_job_id(revision.id)
    revision.dispatch_claimed_at = now
    revision.error_message = None
    revision.started_at = now if retrying_processing else None
    revision.activated_at = None
    db.commit()
    db.refresh(revision)
    return _dispatch_revision(db, revision)


def _dispatch_revision(db: Session, revision: SegmentGeometryRevision) -> SegmentGeometryRevision:
    """派发已提交的可执行 revision，并把 Redis 失败变成可恢复状态。"""
    if revision.job_id is None:
        # 先把本次派发 attempt 的确定 ID 落库，再触碰 Redis。并发 retry 会看到
        # 同一个 live/missing job；API 硬死时也能用这个 ID 判断是否真的入过队。
        revision.job_id = _new_job_id(revision.id)
        revision.dispatch_claimed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(revision)

    try:
        job = segment_rebuilds_queue.enqueue(
            _TASK_PATH,
            revision.id,
            revision.job_id,
            job_id=revision.job_id,
            job_timeout=3600,
        )
    except Exception as exc:
        mark_revision_failed(
            db,
            revision.id,
            f"任务派发失败：{exc}",
            attempt_job_id=revision.job_id,
        )
        raise SegmentGeometryWorkflowError("标准几何已暂存，但后台重建任务派发失败") from exc

    if job.id != revision.job_id:
        mark_revision_failed(
            db,
            revision.id,
            "RQ 返回的 job_id 与派发凭据不一致",
            attempt_job_id=revision.job_id,
        )
        raise SegmentGeometryWorkflowError("后台重建任务派发凭据不一致")
    db.refresh(revision)
    return revision


def _new_job_id(revision_id: int) -> str:
    return f"segment-geometry-{revision_id}-{uuid4().hex}"


def _rq_job_is_live(job_id: str) -> bool:
    try:
        job = Job.fetch(job_id, connection=segment_rebuilds_queue.connection)
        status = job.get_status(refresh=True)
    except NoSuchJobError:
        return False
    except Exception as exc:
        raise SegmentGeometryWorkflowError("无法核实旧后台任务状态，请稍后重试") from exc
    status_value = getattr(status, "value", str(status)).lower()
    return status_value in {"queued", "started", "deferred", "scheduled"}


def _is_older_than(value: datetime | None, threshold: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= threshold


def get_segment_geometry_revision(
    db: Session,
    *,
    segment_id: int,
    revision_id: int,
) -> SegmentGeometryRevision | None:
    return (
        db.query(SegmentGeometryRevision)
        .filter(
            SegmentGeometryRevision.id == revision_id,
            SegmentGeometryRevision.segment_id == segment_id,
        )
        .first()
    )


def run_segment_geometry_revision_task(revision_id: int, attempt_job_id: str) -> dict:
    """RQ 任务：先完整计算，最后一次事务切换标准线、成绩和认知状态。"""
    read_db = SessionLocal()
    try:
        revision = mark_revision_processing(read_db, revision_id, attempt_job_id)
        if revision.status == "active":
            return {"revision_id": revision_id, "status": "active", "idempotent": True}
        read_db.commit()
        revision = read_db.query(SegmentGeometryRevision).filter_by(id=revision_id).one()
        precomputed_efforts = collect_effort_candidates(read_db, revision)
    except Exception as exc:
        read_db.rollback()
        _fail_revision_with_fresh_session(revision_id, attempt_job_id, exc)
        raise
    finally:
        read_db.close()

    write_db = SessionLocal()
    try:
        summary = activate_revision_core(
            write_db,
            revision_id=revision_id,
            attempt_job_id=attempt_job_id,
            precomputed_efforts=precomputed_efforts,
        )
        active_revision = write_db.query(SegmentGeometryRevision).filter_by(id=revision_id).one()
        record_geometry_change(
            write_db,
            revision=active_revision,
            matched_efforts=summary.matched_efforts,
        )
        write_db.commit()
        return {
            "revision_id": revision_id,
            "segment_id": summary.segment_id,
            "status": "active",
            "matched_efforts": summary.matched_efforts,
            "inserted_efforts": summary.inserted_efforts,
            "updated_efforts": summary.updated_efforts,
            "deleted_efforts": summary.deleted_efforts,
        }
    except Exception as exc:
        write_db.rollback()
        _fail_revision_with_fresh_session(revision_id, attempt_job_id, exc)
        raise
    finally:
        write_db.close()


def _fail_revision_with_fresh_session(
    revision_id: int,
    attempt_job_id: str,
    exc: Exception,
) -> None:
    logger.exception("segment geometry rebuild failed revision_id=%s", revision_id)
    failure_db = SessionLocal()
    try:
        mark_revision_failed(
            failure_db,
            revision_id,
            str(exc),
            attempt_job_id=attempt_job_id,
        )
    finally:
        failure_db.close()
