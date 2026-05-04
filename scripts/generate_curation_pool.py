"""候选池脚本（5.D.1）：每周一次跑，UPSERT top 100 候选。

排序分（PRD Q5 拍）：
- attempts_count：赛段被骑过多少次，代表热度
- kom_changes：用不同用户数 - 1 做 KOM 变化 proxy，代表竞争性
- difficulty_balance_factor：让 easy / medium / hard / extreme 四档尽量均衡

UPSERT by segment_id UNIQUE：幂等，可重复跑。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
import sys

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.segment.models import Segment, SegmentCurationPool, SegmentEffort


DIFFICULTIES = ("easy", "medium", "hard", "extreme")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Candidate:
    segment_id: int
    difficulty: str
    attempts_count: int
    kom_changes: int


def calculate_pool_score(
    attempts_count: int,
    kom_changes: int,
    difficulty_balance_factor: float,
) -> float:
    """
    候选池排序分（PRD Q5 拍：热度前 100 + 难度区间分布平衡）。

    分数 = attempts_count * 1.0 + kom_changes * 5.0 + difficulty_balance_factor * 50
    """
    return (
        attempts_count * 1.0
        + kom_changes * 5.0
        + difficulty_balance_factor * 50.0
    )


def _reason_for(candidate: _Candidate) -> str:
    if candidate.attempts_count > 0:
        return "high_attempts"
    return "difficulty_balance"


def _target_counts(top_n: int) -> dict[str, int]:
    base = top_n // len(DIFFICULTIES)
    remainder = top_n % len(DIFFICULTIES)
    return {
        difficulty: base + (1 if idx < remainder else 0)
        for idx, difficulty in enumerate(DIFFICULTIES)
    }


def _raw_score(candidate: _Candidate) -> float:
    return calculate_pool_score(
        candidate.attempts_count,
        candidate.kom_changes,
        1.0,
    )


def _pick_balanced_top(candidates: list[_Candidate], top_n: int) -> list[tuple[_Candidate, float]]:
    """
    先按四个难度篮子均分名额；某个篮子不够时，再把空位给全局高分候选。

    实施简化：当前只按 4 难度分组，spec §3.7.1 伪代码注释提的"城市维度"暂砍
    （100 用户量级 / 城市赛段稀疏 / 数据量起来再加）。
    """
    buckets: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        buckets[candidate.difficulty].append(candidate)

    for bucket in buckets.values():
        bucket.sort(key=_raw_score, reverse=True)

    targets = _target_counts(top_n)
    picked: list[_Candidate] = []
    picked_ids: set[int] = set()

    for difficulty in DIFFICULTIES:
        for candidate in buckets.get(difficulty, [])[: targets[difficulty]]:
            picked.append(candidate)
            picked_ids.add(candidate.segment_id)

    if len(picked) < top_n:
        remaining = [
            candidate
            for candidate in candidates
            if candidate.segment_id not in picked_ids
        ]
        remaining.sort(key=_raw_score, reverse=True)
        for candidate in remaining[: top_n - len(picked)]:
            picked.append(candidate)

    selected_counts: dict[str, int] = defaultdict(int)
    scored: list[tuple[_Candidate, float]] = []
    for candidate in picked[:top_n]:
        target = max(targets.get(candidate.difficulty, 0), 1)
        balance_factor = max(
            0.0,
            1.0 - (selected_counts[candidate.difficulty] / target),
        )
        selected_counts[candidate.difficulty] += 1
        scored.append((
            candidate,
            calculate_pool_score(
                candidate.attempts_count,
                candidate.kom_changes,
                balance_factor,
            ),
        ))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def _upsert_curation_pool(db: Session, candidate: _Candidate, score: float) -> None:
    values = {
        "segment_id": candidate.segment_id,
        "pool_score": score,
        "pool_reason": _reason_for(candidate),
        "selected_for_v5": False,
    }
    update_values = {
        "pool_score": score,
        "pool_reason": values["pool_reason"],
    }

    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        stmt = pg_insert(SegmentCurationPool).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_curation_pool_segment_id",
            set_=update_values,
        )
        db.execute(stmt)
        return

    if dialect_name == "sqlite":
        stmt = sqlite_insert(SegmentCurationPool).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["segment_id"],
            set_=update_values,
        )
        db.execute(stmt)
        return

    existing = (
        db.query(SegmentCurationPool)
        .filter(SegmentCurationPool.segment_id == candidate.segment_id)
        .first()
    )
    if existing:
        existing.pool_score = score
        existing.pool_reason = values["pool_reason"]
    else:
        db.add(SegmentCurationPool(**values))


def _prune_unselected_stale_rows(db: Session, current_segment_ids: set[int]) -> None:
    """清掉本轮未入选的未选候选；已人工选中的候选不碰。"""
    if not current_segment_ids:
        return

    (
        db.query(SegmentCurationPool)
        .filter(
            SegmentCurationPool.selected_for_v5.is_(False),
            SegmentCurationPool.segment_id.notin_(current_segment_ids),
        )
        .delete(synchronize_session=False)
    )


def generate_curation_pool(db: Session, top_n: int = 100) -> int:
    """
    计算每条 segment 的 pool_score，UPSERT 写入 segment_curation_pool top N。

    幂等：重跑不重复（UPSERT by segment_id UNIQUE）。
    返回：写入的赛段数。
    """
    if top_n <= 0:
        return 0

    rows = (
        db.query(
            Segment.id.label("segment_id"),
            Segment.difficulty.label("difficulty"),
            func.count(SegmentEffort.id).label("attempts_count"),
            func.count(func.distinct(SegmentEffort.user_id)).label("user_count"),
        )
        .outerjoin(SegmentEffort, SegmentEffort.segment_id == Segment.id)
        .group_by(Segment.id, Segment.difficulty)
        .all()
    )

    candidates = [
        _Candidate(
            segment_id=row.segment_id,
            difficulty=row.difficulty,
            attempts_count=row.attempts_count or 0,
            kom_changes=max((row.user_count or 0) - 1, 0),
        )
        for row in rows
        if row.difficulty in DIFFICULTIES
    ]
    if not candidates:
        return 0

    scored_top = _pick_balanced_top(candidates, top_n)
    for candidate, score in scored_top:
        _upsert_curation_pool(db, candidate, score)

    _prune_unselected_stale_rows(
        db,
        {candidate.segment_id for candidate, _ in scored_top},
    )
    db.commit()
    logger.info("generate_curation_pool: wrote %d segments", len(scored_top))
    return len(scored_top)


def main() -> int:
    db = SessionLocal()
    try:
        logger.info("=== 开始生成候选池 ===")
        written = generate_curation_pool(db)
        logger.info("完成：写入 %d 条", written)
        return 0
    except Exception:
        logger.exception("候选池生成失败")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
