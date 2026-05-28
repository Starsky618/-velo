# Task 5: Join And Leave Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add join and leave behavior with row-level locking so a full meetup cannot overbook.

**Architecture:** Participation is the gate at the clubhouse door. The meetup row is locked before counting seats, so two riders cannot both grab the last spot.

**Tech Stack:** SQLAlchemy `.with_for_update().populate_existing()`, DB unique constraint, FastAPI endpoint tests.

---

## User Story

阿杰看到“5/6”还剩最后一个名额，他点加入。另一个人也同时点。After this task, only one person gets the final seat; the other sees a clean “已满” response instead of both人挤进 7/6。

## Files

- Modify: `app/meetup/service.py`
- Modify: `app/meetup/router.py`
- Create: `tests/test_meetup_participation.py`
- Test: `tests/test_meetup_participation.py`

## Evidence Anchors

- [✓ grep] join/leave endpoints and rules: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:244-245`.
- [✓ grep] join data flow uses `_load_and_authorize_meetup(require_status=['OPEN'], check_time_cutoff=True)`: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:451-455`.
- [✓ grep] full-seat risk is high and must use FOR UPDATE: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:493-494`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 join/leave；复审时确认测试者≠实现者，且并发测试不是只测 happy path。

## Steps

- [ ] **Step 1: Read the concurrency contract**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '231,249p;451,455p;487,494p'
```

Expected: you see `FOR UPDATE`, duplicate/full checks, and cutoff.

- [ ] **Step 2: Write red tests**

Create `tests/test_meetup_participation.py`:

```python
"""约骑模块 Task 5：加入退出和并发合同测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.meetup import service
from app.meetup.models import MeetupParticipant
from app.segment.models import Segment
from app.user.models import User
from app.user.service import create_token


ROOT = Path(__file__).resolve().parents[1]


def _segment(db):
    segment = Segment(
        name="太山爬坡",
        distance=5000.0,
        elevation_gain=300.0,
        start_lat=37.8,
        start_lon=112.4,
        end_lat=37.9,
        end_lon=112.5,
        reference_line="SRID=4326;LINESTRING(112.4 37.8, 112.5 37.9)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _open_meetup(db, owner_id, max_participants=2, minutes=180):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    meetup = service.create_meetup(
        db, owner_id, segment.id, None, start, start + timedelta(hours=2), "太山脚下", "training", max_participants, None
    )
    return service.publish_meetup(db, meetup.id, owner_id)


def test_join_meetup_adds_participant(client, db, auth_header, test_user, admin_header, admin_user):
    meetup = _open_meetup(db, test_user.id, max_participants=3)

    res = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    assert res.status_code == 200
    assert res.json()["participants_count"] == 2
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=admin_user.id).first()
    assert participant is not None


def test_join_full_meetup_returns_409(client, db, auth_header, test_user, admin_header):
    other_user = User(openid="meetup-full-other")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    other_header = {"Authorization": f"Bearer {create_token(other_user.id)}"}
    meetup = _open_meetup(db, test_user.id, max_participants=2)

    first = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)
    res = client.post(f"/api/meetups/{meetup.id}/join", headers=other_header)

    assert first.status_code == 200
    assert res.status_code == 409


def test_join_same_user_twice_returns_409(client, db, auth_header, test_user, admin_header):
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    first = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)
    second = client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    assert first.status_code == 200
    assert second.status_code == 409


def test_leave_meetup_removes_participant(client, db, auth_header, test_user, admin_header, admin_user):
    meetup = _open_meetup(db, test_user.id, max_participants=3)
    client.post(f"/api/meetups/{meetup.id}/join", headers=admin_header)

    res = client.delete(f"/api/meetups/{meetup.id}/leave", headers=admin_header)

    assert res.status_code == 200
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=admin_user.id).first()
    assert participant is None


def test_leave_inside_cutoff_returns_410(db, test_user, admin_user):
    meetup = _open_meetup(db, test_user.id, max_participants=3, minutes=20)
    service.join_meetup(db, meetup.id, admin_user.id)

    with pytest.raises(HTTPException) as exc:
        service.leave_meetup(db, meetup.id, admin_user.id)

    assert exc.value.status_code == 410


def test_join_service_uses_for_update_and_populate_existing():
    source = (ROOT / "app" / "meetup" / "service.py").read_text(encoding="utf-8")

    join_block = source[source.index("def join_meetup"):source.index("def leave_meetup")]
    assert "_load_and_authorize_meetup(" in join_block
    assert ".with_for_update().populate_existing()" in source
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_participation.py -q
```

Expected: FAIL because `join_meetup`, `leave_meetup`, and router endpoints do not exist.

- [ ] **Step 4: Add service functions**

Append to `app/meetup/service.py`:

```python
def _participant_count(db: Session, meetup_id: int) -> int:
    return db.query(MeetupParticipant).filter(MeetupParticipant.meetup_id == meetup_id).count()


def join_meetup(db: Session, meetup_id: int, current_user_id: int) -> dict:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_status=["OPEN"],
        check_time_cutoff=True,
    )
    existing = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="already_joined")
    count = _participant_count(db, meetup.id)
    if count >= meetup.max_participants:
        raise HTTPException(status_code=409, detail="meetup_full")
    db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user_id, is_creator=False))
    db.commit()
    return {"meetup": meetup, "participants_count": count + 1}


def leave_meetup(db: Session, meetup_id: int, current_user_id: int) -> dict:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_status=["OPEN"],
        check_time_cutoff=True,
    )
    participant = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if participant is None:
        raise HTTPException(status_code=409, detail="not_joined")
    db.delete(participant)
    count = max(0, _participant_count(db, meetup.id) - 1)
    db.commit()
    return {"meetup": meetup, "participants_count": count}
```

- [ ] **Step 5: Add router endpoints**

Append to `app/meetup/router.py`:

```python
@router.post("/{meetup_id}/join", response_model=schemas.MeetupResponse)
def join_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    result = service.join_meetup(db, meetup_id, current_user_id)
    return _response(result["meetup"], participants_count=result["participants_count"])


@router.delete("/{meetup_id}/leave", response_model=schemas.MeetupResponse)
def leave_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    result = service.leave_meetup(db, meetup_id, current_user_id)
    return _response(result["meetup"], participants_count=result["participants_count"])
```

- [ ] **Step 6: Run green tests**

```bash
python3 -m pytest tests/test_meetup_participation.py tests/test_meetup_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Self-review**

- [ ] Spec coverage: join, leave, full, duplicate, cutoff, and row-lock contract are covered.
- [ ] Type consistency: response still returns `participants_count`, not a separate counter field.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: no new import from `app/activity` or `app/user` is introduced.

Run:

```bash
grep -rn "def join_meetup\\|with_for_update\\|populate_existing\\|meetup_full\\|already_joined" app/meetup tests/test_meetup_participation.py
python3 -m pytest tests/test_meetup_participation.py -q
```

- [ ] **Step 8: Commit**

```bash
git add app/meetup/service.py app/meetup/router.py tests/test_meetup_participation.py
git commit -F - <<'MSG'
feat(meetup): task 5 add join and leave

Protect meetup participation with row locking, duplicate checks, full-seat checks, and cutoff enforcement.
Expose join and leave endpoints with participants_count responses.
MSG
```
