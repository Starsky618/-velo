"""
v5 task-1.B.1：app/agent/tasks.py 真 PG 集成测试。

测 RQ task 端到端：建 Segment → 调 generate_segment_draft_task → 验 segment_ai_drafts
- 用 dev stack 真 PostgreSQL（PostGIS / 真 UNIQUE 约束 / 真 IntegrityError 行为）
- mock segment_writer.generate_segment_draft 避免真调 DeepSeek API
- 测试间用前缀 [task-1.B.1 codex] 隔离，结束清理

为啥不用 SQLite mock：
- IntegrityError 并发场景在 SQLite mock 下不真触发
- segment_ai_drafts UNIQUE(segment_id) + status CHECK 约束需要真 PG 验证
"""

import os
from threading import Barrier, Thread
from queue import Queue as ThreadQueue
from unittest.mock import patch

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.agent import tasks
from app.segment.models import Segment, SegmentAiDraft


_PREFIX = "[task-1.B.1 codex]"


def _db_url() -> str:
    """容器内用 DATABASE_URL，宿主机退回 localhost:5435。"""
    return (
        os.getenv("VELO_TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://velo:velo@localhost:5435/velo"
    )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_db_url(), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"dev stack PostgreSQL 不可用: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine):
    Session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        # 测试前清理本前缀残留
        _cleanup(db)
        yield db
    finally:
        _cleanup(db)
        db.close()


def _cleanup(db):
    """按 _PREFIX 清理本测试组数据。"""
    db.execute(
        text(
            "DELETE FROM segment_ai_drafts WHERE segment_id IN "
            "(SELECT id FROM segments WHERE name LIKE :prefix)"
        ),
        {"prefix": f"{_PREFIX}%"},
    )
    db.execute(
        text("DELETE FROM segments WHERE name LIKE :prefix"),
        {"prefix": f"{_PREFIX}%"},
    )
    db.commit()


def _make_segment(db, suffix: str) -> Segment:
    """建一条测试 segment，名带 _PREFIX 保证清理时能识别。"""
    seg = Segment(
        name=f"{_PREFIX} {suffix}",
        distance=4500.0,
        elevation_gain=150.0,
        max_gradient=7.5,
        difficulty="medium",
        city="beijing",
        start_lat=39.9, start_lon=116.4,
        end_lat=39.95, end_lon=116.45,
        reference_line=WKTElement("LINESTRING(116.4 39.9, 116.45 39.95)", srid=4326),
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)
    return seg


def test_segment_id_not_exist_no_raise(pg_session):
    """segment_id 不存在 → 函数 return 不抛异常 / 不写 draft。"""
    # 用一个保证不存在的极大 id
    nonexistent_id = 999_999_999
    # 不该抛任何异常
    tasks.generate_segment_draft_task(nonexistent_id)
    # 验确实没写 draft
    count = pg_session.query(SegmentAiDraft).filter(
        SegmentAiDraft.segment_id == nonexistent_id
    ).count()
    assert count == 0


def test_creates_new_draft_with_pending_status(pg_session):
    """新 segment 调 task → 建 draft / status='pending' / ai_draft_text 等于 mock 返。"""
    seg = _make_segment(pg_session, "新建草稿")

    # mock LLM 返一段固定文本，避免真调 API
    with patch.object(tasks, "generate_segment_draft", return_value="测试 AI 草稿正文"):
        tasks.generate_segment_draft_task(seg.id)

    draft = (
        pg_session.query(SegmentAiDraft)
        .filter(SegmentAiDraft.segment_id == seg.id)
        .first()
    )
    assert draft is not None
    assert draft.status == "pending"
    assert draft.ai_draft_text == "测试 AI 草稿正文"


def test_pending_draft_overwritten_on_rerun(pg_session):
    """已有 status='pending' 的 draft → 再次 enqueue 应覆盖 ai_draft_text。"""
    seg = _make_segment(pg_session, "覆盖 pending")

    with patch.object(tasks, "generate_segment_draft", return_value="第一稿"):
        tasks.generate_segment_draft_task(seg.id)
    with patch.object(tasks, "generate_segment_draft", return_value="第二稿覆盖"):
        tasks.generate_segment_draft_task(seg.id)

    pg_session.expire_all()  # 强制重读 DB 拿最新值
    draft = (
        pg_session.query(SegmentAiDraft)
        .filter(SegmentAiDraft.segment_id == seg.id)
        .first()
    )
    assert draft.ai_draft_text == "第二稿覆盖"
    assert draft.status == "pending"


@pytest.mark.parametrize("protected_status", ["human_edited", "approved", "rejected"])
def test_non_pending_draft_not_overwritten(pg_session, protected_status):
    """
    任何 non-pending 状态都不被覆盖（codex 异源审 2026-04-30 Important：
    原只验 human_edited，但 4 状态机要 3 种 non-pending 都验保护）。

    保护逻辑：状态机 pending → human_edited → approved / rejected
    AI 重生成只能动 pending；其他 3 种状态都是人工干预过的成果，必须保留。
    """
    seg = _make_segment(pg_session, f"保护 {protected_status}")

    original_text = f"被 {protected_status} 锁定的内容"
    draft = SegmentAiDraft(
        segment_id=seg.id,
        ai_draft_text=original_text,
        status=protected_status,
    )
    pg_session.add(draft)
    pg_session.commit()

    # 再触发 task —— AI 想覆盖
    with patch.object(tasks, "generate_segment_draft", return_value="AI 想覆盖的新版本"):
        tasks.generate_segment_draft_task(seg.id)

    pg_session.expire_all()
    draft_after = (
        pg_session.query(SegmentAiDraft)
        .filter(SegmentAiDraft.segment_id == seg.id)
        .first()
    )
    assert draft_after.ai_draft_text == original_text  # 没变
    assert draft_after.status == protected_status


def test_empty_ai_text_skips_upsert(pg_session):
    """generate 返空字符串 → skip UPSERT，不建 draft / 不抛。"""
    seg = _make_segment(pg_session, "空文本 skip")

    with patch.object(tasks, "generate_segment_draft", return_value=""):
        tasks.generate_segment_draft_task(seg.id)

    count = (
        pg_session.query(SegmentAiDraft)
        .filter(SegmentAiDraft.segment_id == seg.id)
        .count()
    )
    assert count == 0


def test_integrity_error_swallowed_directly(pg_session):
    """
    直接 mock db.commit() 抛 IntegrityError → 验函数 catch + rollback + 不抛
    （codex 异源审 2026-04-30 Important：纯并发测试可能假通过，加直接路径测试）。

    场景：另一 worker 已抢先 INSERT 同 segment_id 占了 UNIQUE，本 worker commit 触发
    UNIQUE constraint violation。函数应内部消化不抛给 RQ。
    """
    seg = _make_segment(pg_session, "直接 IntegrityError")

    # 模拟 commit 抛 IntegrityError —— 用 patch 替换 SessionLocal 返回的 session 的 commit
    # tasks.py 内部新建 SessionLocal()，所以 patch SessionLocal 返一个 mock session 即可
    from unittest.mock import MagicMock
    from sqlalchemy.exc import IntegrityError

    fake_session = MagicMock()
    # 让 query.first() 链返 (Segment, None)
    fake_session.query.return_value.filter.return_value.first.side_effect = [
        seg,    # 第一次查 Segment 返已建赛段
        None,   # 第二次查 SegmentAiDraft 返无（→ 走 db.add 新建路径）
    ]
    fake_session.commit.side_effect = IntegrityError("mock", "mock", Exception("UNIQUE violation"))

    with patch.object(tasks, "SessionLocal", return_value=fake_session), \
         patch.object(tasks, "generate_segment_draft", return_value="测试草稿"):
        # 不该抛任何异常给 RQ
        tasks.generate_segment_draft_task(seg.id)

    # 验关键路径：commit 被调（触发 IntegrityError）/ rollback 被调（catch 后兜底）/ close 被调
    assert fake_session.commit.called
    assert fake_session.rollback.called
    assert fake_session.close.called


def test_concurrent_workers_swallow_integrity_error(pg_engine):
    """两个 worker 同时调同一 segment_id → 一个成功一个 catch IntegrityError 跳过不抛。"""
    Session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)

    setup = Session()
    _cleanup(setup)
    seg = Segment(
        name=f"{_PREFIX} 并发冲突",
        distance=3500.0,
        elevation_gain=80.0,
        max_gradient=4.0,
        difficulty="medium",
        city="beijing",
        start_lat=39.9, start_lon=116.4,
        end_lat=39.92, end_lon=116.42,
        reference_line=WKTElement("LINESTRING(116.4 39.9, 116.42 39.92)", srid=4326),
    )
    setup.add(seg)
    setup.commit()
    seg_id = seg.id
    setup.close()

    barrier = Barrier(2)
    results = ThreadQueue()

    def _worker(idx: int):
        try:
            barrier.wait(timeout=10)
            with patch.object(tasks, "generate_segment_draft", return_value=f"草稿{idx}"):
                tasks.generate_segment_draft_task(seg_id)
            results.put(("ok", idx))
        except Exception as exc:  # pragma: no cover - 并发 race 异常应该被内部消化
            results.put(("error", repr(exc)))

    threads = [Thread(target=_worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    seen = [results.get(timeout=1) for _ in range(2)]
    # 期望两个 worker 都正常返回（一个真写 / 一个 catch IntegrityError 静默跳）
    # 都没把异常抛到 RQ —— 否则 RQ 会 retry 浪费配额
    assert all(kind == "ok" for kind, _ in seen), f"并发冲突未被吞掉: {seen}"

    # 验 DB 最终只有 1 行 draft（UNIQUE 保证）
    verify = Session()
    try:
        count = verify.query(SegmentAiDraft).filter(
            SegmentAiDraft.segment_id == seg_id
        ).count()
        assert count == 1
    finally:
        _cleanup(verify)
        verify.close()
