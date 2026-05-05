"""admin 编排逻辑。

3.A.2+ 会在这里追加候选池审核、AI 草稿同步、批量管理等函数。
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from rq import Retry
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.queue import ai_drafts_queue
from app.segment.models import Segment, SegmentAiDraft, SegmentCurationPool


_AI_DRAFT_TASK = "app.agent.tasks.generate_segment_draft_task"


def _curation_pool_item(pool: SegmentCurationPool, segment: Segment) -> dict:
    """把候选池 ORM + 赛段 ORM 合成后台列表需要的一行。"""
    return {
        "id": pool.id,
        "segment_id": pool.segment_id,
        "segment_name": segment.name,
        "segment_city": segment.city,
        "segment_difficulty": segment.difficulty,
        "pool_score": pool.pool_score,
        "pool_reason": pool.pool_reason,
        "selected_for_v5": pool.selected_for_v5,
        "selected_by_user_id": pool.selected_by_user_id,
        "selected_at": pool.selected_at,
    }


def list_curation_pool(
    db: Session,
    selected: bool | None,
    city: str | None,
    difficulty: str | None,
    page: int,
    page_size: int,
) -> dict:
    """列出候选池，支持 selected / city / difficulty 筛选。"""
    query = db.query(SegmentCurationPool, Segment).join(
        Segment,
        SegmentCurationPool.segment_id == Segment.id,
    )
    if selected is not None:
        query = query.filter(SegmentCurationPool.selected_for_v5.is_(selected))
    if city is not None:
        query = query.filter(Segment.city == city)
    if difficulty is not None:
        query = query.filter(Segment.difficulty == difficulty)

    total = query.count()
    selected_count = (
        db.query(func.count(SegmentCurationPool.id))
        .filter(SegmentCurationPool.selected_for_v5.is_(True))
        .scalar()
    )
    rows = (
        query.order_by(SegmentCurationPool.pool_score.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [_curation_pool_item(pool, segment) for pool, segment in rows],
        "total": total,
        "selected_count": selected_count,
    }


def update_curation_pool(
    db: Session,
    pool_id: int,
    selected_for_v5: bool,
    admin_id: int,
) -> dict:
    """更新候选池勾选状态；false → true 时派发 AI 草稿任务。"""
    pool = db.get(SegmentCurationPool, pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="候选项不存在")

    if selected_for_v5 and pool.selected_for_v5 is not True:
        # 并发取舍：两个 admin 同时从 49 勾选不同项，可能都通过校验后到 51。
        # task-3.A.2 自检已接受 admin H5 低频操作的小幅越界；未来高频协作再加
        # PostgreSQL advisory lock（参考 from-activity 模式），本轮不提前加锁。
        current_selected = (
            db.query(func.count(SegmentCurationPool.id))
            .filter(SegmentCurationPool.selected_for_v5.is_(True))
            .scalar()
        )
        if current_selected >= 50:
            raise HTTPException(
                status_code=400,
                detail="候选池已达 50 上限，请先取消勾选其他项",
            )

    was_selected = pool.selected_for_v5 is True
    pool.selected_for_v5 = selected_for_v5
    if selected_for_v5:
        pool.selected_by_user_id = admin_id
        pool.selected_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(pool)

    if selected_for_v5 and not was_selected:
        try:
            enqueue_ai_draft_generation(pool.segment_id)
        except Exception as exc:
            pool.selected_for_v5 = False
            pool.selected_by_user_id = None
            pool.selected_at = None
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="AI 草稿任务派发失败，请稍后重试",
            ) from exc

    segment = db.get(Segment, pool.segment_id)
    return _curation_pool_item(pool, segment)


def enqueue_ai_draft_generation(segment_id: int):
    """把 AI 草稿生成任务丢给 RQ，所有 admin 入口共用同一队列调用。"""
    return ai_drafts_queue.enqueue(
        _AI_DRAFT_TASK,
        segment_id,
        job_timeout=120,
        retry=Retry(max=2, interval=[30, 90]),
    )


def generate_ai_draft(db: Session, segment_id: int) -> dict:
    """预校验 segment 存在后，异步派发 AI 草稿生成任务。"""
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="赛段不存在")

    try:
        job = enqueue_ai_draft_generation(segment_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="AI 草稿任务派发失败，请稍后重试",
        ) from exc

    return {
        "job_id": job.id,
        "segment_id": segment_id,
        "status": "enqueued",
    }


def _ai_draft_item(draft: SegmentAiDraft, segment_name: str) -> dict:
    """把 AI 草稿 ORM + 赛段名合成后台审稿台需要的一行。"""
    return {
        "id": draft.id,
        "segment_id": draft.segment_id,
        "segment_name": segment_name,
        "ai_draft_text": draft.ai_draft_text,
        "human_edited_text": draft.human_edited_text,
        "status": draft.status,
        "editor_user_id": draft.editor_user_id,
        "updated_at": draft.updated_at,
    }


def list_ai_drafts(db: Session, status: str, page: int, page_size: int) -> dict:
    """列出 AI 草稿，按状态筛选并带出 segment 名称。"""
    query = (
        db.query(SegmentAiDraft, Segment.name.label("segment_name"))
        .join(Segment, SegmentAiDraft.segment_id == Segment.id)
        .filter(SegmentAiDraft.status == status)
    )
    total = query.count()
    rows = (
        query.order_by(SegmentAiDraft.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            _ai_draft_item(draft, segment_name)
            for draft, segment_name in rows
        ],
        "total": total,
    }


def update_ai_draft(db: Session, draft_id: int, body, admin_id: int) -> dict:
    """编辑 AI 草稿；approved 时同步 Segment.description。"""
    draft = db.get(SegmentAiDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")

    if body.human_edited_text is None and body.status is None:
        raise HTTPException(status_code=422, detail="请提供要更新的草稿内容或状态")

    if body.human_edited_text is not None:
        draft.human_edited_text = body.human_edited_text
        draft.editor_user_id = admin_id
        if body.status is None:
            draft.status = "human_edited"

    if body.status is not None:
        draft.status = body.status

    if body.status == "approved":
        if draft.human_edited_text is None:
            raise HTTPException(status_code=422, detail="通过前请先填写人工编辑文本")
        segment = db.get(Segment, draft.segment_id)
        if segment is None:
            raise HTTPException(status_code=404, detail="赛段不存在")
        segment.description = draft.human_edited_text

    db.commit()
    db.refresh(draft)
    segment = db.get(Segment, draft.segment_id)
    return _ai_draft_item(draft, segment.name)


def _pool_status(pool: SegmentCurationPool | None) -> str | None:
    """把候选池记录折成 admin 列表状态。"""
    if pool is None:
        return None
    if pool.selected_for_v5 is True:
        return "selected"
    return "candidate"


def _admin_segment_item(
    segment: Segment,
    draft_status: str | None,
    pool: SegmentCurationPool | None,
) -> dict:
    """把 Segment + 内部运营状态合成 admin 批量管理列表项。"""
    return {
        "id": segment.id,
        "name": segment.name,
        "description": segment.description,
        "distance": round(segment.distance / 1000.0, 2),
        "elevation_gain": segment.elevation_gain,
        "elevation_loss": segment.elevation_loss,
        "avg_gradient": segment.avg_gradient,
        "max_gradient": segment.max_gradient,
        "difficulty": segment.difficulty,
        "city": segment.city,
        "start_lat": segment.start_lat,
        "start_lon": segment.start_lon,
        "end_lat": segment.end_lat,
        "end_lon": segment.end_lon,
        "match_tolerance": segment.match_tolerance,
        "min_match_ratio": segment.min_match_ratio,
        "created_at": segment.created_at,
        "draft_status": draft_status,
        "pool_status": _pool_status(pool),
    }


def list_segments_admin(
    db: Session,
    city: str | None,
    difficulty: str | None,
    has_draft: bool | None,
    page: int,
    page_size: int,
) -> dict:
    """列出 admin 批量管理赛段，带 draft / curation pool 内部状态。"""
    # OUTER JOIN 安全前提：segment_ai_drafts.segment_id + segment_curation_pool.segment_id
    # 都是 UNIQUE FK（spec §2.2），保证每 segment 最多一行。改 schema 时同步评估此处。
    query = (
        db.query(
            Segment,
            SegmentAiDraft.status.label("draft_status"),
            SegmentCurationPool,
        )
        .outerjoin(SegmentAiDraft, SegmentAiDraft.segment_id == Segment.id)
        .outerjoin(SegmentCurationPool, SegmentCurationPool.segment_id == Segment.id)
    )
    if city is not None:
        query = query.filter(Segment.city == city)
    if difficulty is not None:
        query = query.filter(Segment.difficulty == difficulty)
    if has_draft is True:
        query = query.filter(SegmentAiDraft.id.isnot(None))
    elif has_draft is False:
        query = query.filter(SegmentAiDraft.id.is_(None))

    total = query.count()
    rows = (
        query.order_by(Segment.created_at.desc(), Segment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            _admin_segment_item(segment, draft_status, pool)
            for segment, draft_status, pool in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_segment_admin(db: Session, segment_id: int, body) -> dict:
    """更新 admin 允许人工修正的 4 个 Segment 元数据字段。"""
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="赛段不存在")

    if body.name is None and body.description is None and body.city is None and body.difficulty is None:
        raise HTTPException(status_code=422, detail="请提供要更新的赛段字段")

    if body.name is not None:
        segment.name = body.name
    if body.description is not None:
        segment.description = body.description
    if body.city is not None:
        segment.city = body.city
    if body.difficulty is not None:
        segment.difficulty = body.difficulty

    db.commit()
    db.refresh(segment)
    draft = (
        db.query(SegmentAiDraft)
        .filter(SegmentAiDraft.segment_id == segment.id)
        .first()
    )
    pool = (
        db.query(SegmentCurationPool)
        .filter(SegmentCurationPool.segment_id == segment.id)
        .first()
    )
    return _admin_segment_item(
        segment,
        draft.status if draft is not None else None,
        pool,
    )


def admin_segment_response(segment: Segment) -> dict:
    """把刚创建的 Segment 转成 admin 响应；新赛段暂无 draft/pool 状态。"""
    return _admin_segment_item(segment, None, None)
