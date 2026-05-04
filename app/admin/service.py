"""admin 编排逻辑。

3.A.2+ 会在这里追加候选池审核、AI 草稿同步、批量管理等函数。
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.queue import ai_drafts_queue
from app.segment.models import Segment, SegmentCurationPool


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
            ai_drafts_queue.enqueue(
                "app.agent.tasks.generate_segment_draft_task",
                pool.segment_id,
                job_timeout=120,
                retry={"max": 2, "interval": [30, 90]},
            )
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
