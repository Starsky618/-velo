# Task 7: Cron And Account Delete Hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-complete OPEN meetups after their estimated end time and clean meetup-owned state when a user account is deleted.

**Architecture:** Cron is the night watchman that marks finished rides complete. The user-delete hook is an intentionally documented reverse hook: before deleting a user, it cancels their OPEN meetups and hard-deletes their DRAFT meetups so the rest of the DB can apply normal FK behavior.

**Tech Stack:** Scheduler loop, SQLAlchemy session factory, pytest static and service tests.

---

## User Story

周六 9:30 约骑结束后，陈哥不用手动点“完成”；系统几分钟后自动把活动标成 COMPLETED。If 陈哥注销账号，他发起的 OPEN 约骑先变成 CANCELLED，草稿消失，参与者名额和路书保留下来。

## Files

- Create: `app/meetup/cron.py`
- Modify: `scheduler.py`
- Modify: `app/meetup/service.py`
- Modify: `app/user/service.py`
- Create: `tests/test_meetup_cron_delete_user.py`
- Test: `tests/test_meetup_cron_delete_user.py`

## Evidence Anchors

- [✓ grep] cron tick design: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:364-389`.
- [✓ grep] delete_user sequence: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:327-356`.
- [✓ grep] existing scheduler loop catches tick exceptions: `scheduler.py:42-50`.
- [✓ grep] reverse hook is explicitly listed: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:645-646`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 cron 和 delete_user hook；复审时确认测试者≠实现者，且 scheduler 异常隔离有静态证据。

## Steps

- [ ] **Step 1: Read cron and delete contracts**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '327,389p;641,646p'
nl -ba scheduler.py | sed -n '39,50p'
```

Expected: you see 5-minute meetup tick, independent exception isolation, and delete_user order.

- [ ] **Step 2: Write red tests**

Create `tests/test_meetup_cron_delete_user.py`:

```python
"""约骑模块 Task 7：cron 完成和删账号 hook 测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.meetup import cron, service
from app.meetup.models import Meetup
from app.segment.models import Segment
from app.user.models import User


ROOT = Path(__file__).resolve().parents[1]


def _segment(db):
    segment = Segment(
        name="cron路线",
        distance=10000.0,
        elevation_gain=100.0,
        start_lat=37.8,
        start_lon=112.5,
        end_lat=37.9,
        end_lon=112.6,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _meetup(db, user_id, status="OPEN", start_delta=-3, end_delta=-1):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(hours=start_delta)
    meetup = service.create_meetup(
        db, user_id, segment.id, None, start, datetime.now(timezone.utc) + timedelta(hours=end_delta),
        "集合点", "cruise", 4, None
    )
    if status == "OPEN":
        return service.publish_meetup(db, meetup.id, user_id)
    if status == "CANCELLED":
        service.publish_meetup(db, meetup.id, user_id)
        return service.cancel_meetup(db, meetup.id, user_id)
    return meetup


def test_cron_completes_open_meetups_after_estimated_end(db, test_user):
    past = _meetup(db, test_user.id, status="OPEN", end_delta=-1)
    future = _meetup(db, test_user.id, status="OPEN", start_delta=1, end_delta=3)

    changed = cron.complete_due_meetups(db)

    db.refresh(past)
    db.refresh(future)
    assert changed == 1
    assert past.status == "COMPLETED"
    assert past.completed_at is not None
    assert future.status == "OPEN"


def test_scheduler_has_independent_meetup_tick():
    source = (ROOT / "scheduler.py").read_text(encoding="utf-8")

    assert "from app.meetup.cron import run_meetup_complete_tick" in source
    assert "_meetup_tick_counter" in source
    assert "run_import_tick()" in source
    assert "run_meetup_complete_tick()" in source
    assert source.count("logger.exception") >= 2


def test_delete_user_cancels_open_and_deletes_draft(db, test_user):
    from app.user.service import delete_user

    open_meetup = _meetup(db, test_user.id, status="OPEN", start_delta=5, end_delta=8)
    draft_meetup = _meetup(db, test_user.id, status="DRAFT", start_delta=5, end_delta=8)

    delete_user(db, test_user.id)

    cancelled = db.query(Meetup).filter(Meetup.id == open_meetup.id).first()
    draft = db.query(Meetup).filter(Meetup.id == draft_meetup.id).first()
    user = db.query(User).filter(User.id == test_user.id).first()
    assert cancelled.status == "CANCELLED"
    assert draft is None
    assert user is None


def test_delete_user_uses_single_transaction():
    source = (ROOT / "app" / "user" / "service.py").read_text(encoding="utf-8")
    block = source[source.index("def delete_user"):source.index("db.delete(user)") + len("db.delete(user)")]
    assert "with db.begin()" in block
    assert "db.commit()" not in block
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_cron_delete_user.py -q
```

Expected: FAIL because cron and delete_user hook are missing.

- [ ] **Step 4: Add cron module**

Create `app/meetup/cron.py`:

```python
"""
约骑定时任务——把已经结束的 OPEN 约骑自动标成 COMPLETED。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.meetup.models import Meetup


logger = logging.getLogger(__name__)


def complete_due_meetups(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(Meetup)
        .filter(Meetup.status == "OPEN", Meetup.estimated_end_time <= now)
        .all()
    )
    for meetup in rows:
        meetup.status = "COMPLETED"
        meetup.completed_at = now
    db.commit()
    return len(rows)


def run_meetup_complete_tick() -> int:
    db = SessionLocal()
    try:
        changed = complete_due_meetups(db)
        if changed:
            logger.info("meetup complete tick changed=%s", changed)
        return changed
    finally:
        db.close()
```

- [ ] **Step 5: Modify scheduler**

In `scheduler.py`, add import:

```python
from app.meetup.cron import run_meetup_complete_tick
```

Add module variable after `_TICK_INTERVAL_SECONDS`:

```python
_meetup_tick_counter = 0
```

Replace the loop body with:

```python
    global _meetup_tick_counter
    while True:
        try:
            run_import_tick()
        except Exception:
            logger.exception("tick 执行失败")

        try:
            _meetup_tick_counter += 1
            if _meetup_tick_counter >= 20:
                run_meetup_complete_tick()
                _meetup_tick_counter = 0
        except Exception:
            logger.exception("meetup tick 失败")
            _meetup_tick_counter = 0

        time.sleep(_TICK_INTERVAL_SECONDS)
```

- [ ] **Step 6: Confirm Task 6 storage cleanup helpers exist**

Read `app/meetup/service.py` and confirm Task 6 already added these helpers:

```python
def _delete_meetup_row_and_collect_files(db: Session, meetup_id: int) -> list[str]:
def _cleanup_meetup_storage(file_ids: list[str]) -> None:
```

- [ ] **Step 7: Add `delete_user` hook**

Append to `app/user/service.py`:

```python
def delete_user(db, user_id: int) -> None:
    """
    删除用户前先收拾约骑生态：OPEN 取消，DRAFT 硬删，然后删用户本体。
    """
    from datetime import datetime, timezone

    from app.meetup.models import Meetup
    from app.meetup.service import _cleanup_meetup_storage, _delete_meetup_row_and_collect_files
    from app.user.models import User

    file_ids = []
    with db.begin():
        open_meetups = db.query(Meetup).filter(Meetup.creator_id == user_id, Meetup.status == "OPEN").all()
        for meetup in open_meetups:
            meetup.status = "CANCELLED"
            meetup.cancelled_at = datetime.now(timezone.utc)

        draft_ids = [
            row.id
            for row in db.query(Meetup.id).filter(Meetup.creator_id == user_id, Meetup.status == "DRAFT").all()
        ]
        for meetup_id in draft_ids:
            file_ids.extend(_delete_meetup_row_and_collect_files(db, meetup_id))

        user = db.query(User).filter(User.id == user_id).first()
        if user is not None:
            db.delete(user)

    _cleanup_meetup_storage(file_ids)
```

- [ ] **Step 8: Run green tests**

```bash
python3 -m pytest tests/test_meetup_cron_delete_user.py -q
```

Expected: PASS.

- [ ] **Step 9: Architecture grep**

Run:

```bash
grep -rn "from app.meetup\\|import app.meetup" app/user app/activity app/segment scheduler.py
grep -rh "^from app\\.\\|^import app\\." app/meetup/*.py | sort -u
```

Expected: `app/user/service.py` and `scheduler.py` are the only new reverse-hook hits from this task. Record them in the review report.

- [ ] **Step 10: Self-review**

- [ ] Spec coverage: cron, exception isolation, 5-minute counter, OPEN cancel before user delete, DRAFT hard delete, and route book retention are covered.
- [ ] Type consistency: `completed_at` and `cancelled_at` are tz-aware datetime values.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: intentional reverse hook is documented in the review report with file paths.

- [ ] **Step 11: Commit**

```bash
git add app/meetup/cron.py scheduler.py app/meetup/service.py app/user/service.py tests/test_meetup_cron_delete_user.py
git commit -F - <<'MSG'
feat(meetup): task 7 add completion tick and delete-user cleanup

Auto-complete due OPEN meetups through an isolated scheduler tick and clean creator-owned meetup state before user deletion.
Document and test the intentional user to meetup reverse hook.
MSG
```
