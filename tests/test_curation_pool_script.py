"""候选池脚本测试。"""

from datetime import datetime, timezone

from app.segment.models import Segment, SegmentCurationPool, SegmentEffort
from scripts.generate_curation_pool import (
    calculate_pool_score,
    generate_curation_pool,
)


def _make_segment(db, name, *, difficulty="medium", city="taiyuan", distance=1200.0):
    """创建一个候选池脚本可扫描的赛段。"""
    segment = Segment(
        name=name,
        description=f"{name} description",
        distance=distance,
        elevation_gain=80.0,
        elevation_loss=20.0,
        avg_gradient=6.6,
        elevation_profile="[100, 180]",
        start_lat=37.87,
        start_lon=112.55,
        end_lat=37.88,
        end_lon=112.56,
        reference_line="SRID=4326;LINESTRING(112.55 37.87, 112.56 37.88)",
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty=difficulty,
        max_gradient=8.0,
        city=city,
        created_at=datetime.now(timezone.utc),
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _add_efforts(db, segment_id, count, *, user_offset=1, activity_offset=1):
    """给赛段追加若干成绩，用不同 activity_id 避免真实唯一约束冲突。"""
    efforts = [
        SegmentEffort(
            segment_id=segment_id,
            activity_id=activity_offset + idx,
            user_id=user_offset + idx,
            elapsed_time=300 + idx,
            avg_speed=28.0,
            avg_power=180.0,
            start_index=0,
            end_index=10,
            created_at=datetime.now(timezone.utc),
        )
        for idx in range(count)
    ]
    db.add_all(efforts)
    db.commit()


def test_calculate_pool_score_weights_attempts_kom_and_balance():
    """分数函数应按 spec 的 attempts + KOM proxy + 难度平衡三项加权。"""
    assert calculate_pool_score(10, 2, 0.5) == 45.0


def test_generate_handles_empty_segments_table(db):
    """0 条 segments 时脚本应跑通，像空篮子筛选一样直接返回 0。"""
    written = generate_curation_pool(db)

    assert written == 0
    assert db.query(SegmentCurationPool).count() == 0


def test_generate_creates_top_n_and_balances_difficulty(db):
    """top_n 应按四档难度均衡取候选，避免热门 easy 赛段挤掉所有爬坡档。"""
    difficulties = ["easy", "medium", "hard", "extreme"]
    activity_id = 1
    for difficulty in difficulties:
        for idx in range(3):
            seg = _make_segment(db, f"{difficulty}-{idx}", difficulty=difficulty)
            _add_efforts(
                db,
                seg.id,
                20 - idx,
                user_offset=1000 * (difficulties.index(difficulty) + 1) + idx * 10,
                activity_offset=activity_id,
            )
            activity_id += 100

    written = generate_curation_pool(db, top_n=8)

    rows = (
        db.query(SegmentCurationPool, Segment)
        .join(Segment, Segment.id == SegmentCurationPool.segment_id)
        .all()
    )
    counts = {difficulty: 0 for difficulty in difficulties}
    for _, segment in rows:
        counts[segment.difficulty] += 1

    assert written == 8
    assert db.query(SegmentCurationPool).count() == 8
    assert counts == {"easy": 2, "medium": 2, "hard": 2, "extreme": 2}


def test_generate_popularity_weighted_within_same_difficulty(db):
    """同难度内，成绩更多的赛段应优先入池且分数更高。"""
    hot = _make_segment(db, "热门爬坡", difficulty="hard")
    cold = _make_segment(db, "冷门爬坡", difficulty="hard")
    _add_efforts(db, hot.id, 8, user_offset=10, activity_offset=10)
    _add_efforts(db, cold.id, 1, user_offset=100, activity_offset=100)

    generate_curation_pool(db, top_n=1)

    row = db.query(SegmentCurationPool).one()
    assert row.segment_id == hot.id
    assert row.pool_score > calculate_pool_score(1, 0, 1.0)
    assert row.pool_reason == "high_attempts"


def test_generate_idempotent_and_preserves_manual_selection_fields(db):
    """重复跑应走 UPSERT，只更新脚本字段，不覆盖 admin 人工勾选字段。"""
    segment = _make_segment(db, "保留人工勾选", difficulty="medium")
    _add_efforts(db, segment.id, 2, user_offset=10, activity_offset=10)
    generate_curation_pool(db, top_n=10)

    pool = db.query(SegmentCurationPool).one()
    selected_at = datetime.now(timezone.utc)
    pool.selected_for_v5 = True
    pool.selected_by_user_id = 42
    pool.selected_at = selected_at
    old_score = pool.pool_score
    db.commit()

    _add_efforts(db, segment.id, 3, user_offset=100, activity_offset=100)
    generate_curation_pool(db, top_n=10)

    rows = db.query(SegmentCurationPool).all()
    assert len(rows) == 1
    assert rows[0].selected_for_v5 is True
    assert rows[0].selected_by_user_id == 42
    assert rows[0].selected_at == selected_at.replace(tzinfo=None)
    assert rows[0].pool_score > old_score


def test_generate_prunes_unselected_stale_rows_but_keeps_selected(db):
    """本轮没进 top_n 的未选候选应清掉；人工已选的候选像贴了标签，不能被脚本删掉。"""
    hot = _make_segment(db, "热赛段", difficulty="easy")
    warm = _make_segment(db, "温赛段", difficulty="medium")
    selected_cold = _make_segment(db, "已选冷门赛段", difficulty="hard")
    unselected_cold = _make_segment(db, "未选冷门赛段", difficulty="extreme")
    _add_efforts(db, hot.id, 10, user_offset=10, activity_offset=10)
    _add_efforts(db, warm.id, 8, user_offset=100, activity_offset=100)
    _add_efforts(db, selected_cold.id, 1, user_offset=200, activity_offset=200)
    _add_efforts(db, unselected_cold.id, 1, user_offset=300, activity_offset=300)
    generate_curation_pool(db, top_n=4)

    selected_pool = (
        db.query(SegmentCurationPool)
        .filter(SegmentCurationPool.segment_id == selected_cold.id)
        .one()
    )
    selected_pool.selected_for_v5 = True
    db.commit()

    generate_curation_pool(db, top_n=2)

    segment_ids = {
        row.segment_id
        for row in db.query(SegmentCurationPool).order_by(SegmentCurationPool.segment_id)
    }
    assert hot.id in segment_ids
    assert warm.id in segment_ids
    assert selected_cold.id in segment_ids
    assert unselected_cold.id not in segment_ids
