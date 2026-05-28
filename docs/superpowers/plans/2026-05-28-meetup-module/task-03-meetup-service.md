# Task 3: Meetup Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement meetup lifecycle service logic: draft, patch, publish, cancel, delete, list, detail, snapshot recalculation, and authorization helper.

**Architecture:** The service is the backstage worker for meetup state. Router later becomes a thin translator; all rules that protect DRAFT/OPEN, the 30-minute cutoff, and snapshot freeze live here.

**Tech Stack:** SQLAlchemy sync session, FastAPI HTTPException, pytest service tests.

---

## User Story

陈哥先保存草稿，反复换路线和集合点。发布前，路线名和距离跟着他选的 segment 或路书变化；发布后，别人看到的约骑卡片不再被后续路线改名影响。出发前 30 分钟以内，系统会拒绝取消。

## Files

- Create: `app/meetup/service.py`
- Create: `tests/test_meetup_service.py`
- Modify: none outside `app/meetup/`
- Test: `tests/test_meetup_service.py`

## Evidence Anchors

- [✓ grep] state machine and cutoff: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:208-223`.
- [✓ grep] helper contract: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:252-272`.
- [✓ grep] draft snapshot recalculation and publish freeze: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:113-116`.
- [✓ grep] creator participant inserted at publish: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:439-445`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 meetup lifecycle service；复审时确认测试者≠实现者。

## Steps

- [ ] **Step 1: Read the service contract**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '208,223p;252,316p;439,445p'
```

Expected: you see status values, 30-minute cutoff, `_load_and_authorize_meetup`, draft unique handling, and creator participant insertion.

- [ ] **Step 2: Write red service tests**

Create `tests/test_meetup_service.py`:

```python
"""约骑模块 Task 3：service 状态机测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.meetup import service
from app.meetup.models import Meetup, MeetupParticipant
from app.route_book.models import RouteBook
from app.segment.models import Segment


def _segment(db, name="龙城大道", city="taiyuan"):
    segment = Segment(
        name=name,
        distance=3200.0,
        elevation_gain=80.0,
        start_lat=37.8,
        start_lon=112.5,
        end_lat=37.9,
        end_lon=112.6,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        city=city,
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _route_book(db, user_id, name="汾河路书", city="taiyuan"):
    route = RouteBook(
        creator_id=user_id,
        name=name,
        distance=42000.0,
        climb=520.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city=city,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def _start(days=2):
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_create_meetup_from_segment_writes_snapshot(db, test_user):
    segment = _segment(db)

    meetup = service.create_meetup(
        db,
        current_user_id=test_user.id,
        segment_id=segment.id,
        route_book_id=None,
        start_time=_start(),
        estimated_end_time=_start() + timedelta(hours=3),
        meeting_point="龙城公园东门",
        pace_level="cruise",
        max_participants=6,
        description="稳定巡航",
    )

    assert meetup.status == "DRAFT"
    assert meetup.snapshot_route_name == "龙城大道"
    assert meetup.snapshot_distance == 3200.0
    assert meetup.snapshot_city == "taiyuan"


def test_update_draft_route_recalculates_snapshot(db, test_user):
    segment = _segment(db, name="旧路线")
    route = _route_book(db, test_user.id, name="新路书")
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "relaxed", 4, None
    )

    updated = service.update_meetup(db, meetup.id, test_user.id, route_book_id=route.id, segment_id=None)

    assert updated.route_book_id == route.id
    assert updated.segment_id is None
    assert updated.snapshot_route_name == "新路书"
    assert updated.snapshot_distance == 42000.0


def test_publish_freezes_snapshot_and_adds_creator_participant(db, test_user):
    segment = _segment(db, name="发布前名字")
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "training", 2, None
    )

    published = service.publish_meetup(db, meetup.id, test_user.id)
    segment.name = "发布后改名"
    db.commit()
    db.refresh(published)

    participants = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id).all()
    assert published.status == "OPEN"
    assert published.snapshot_route_name == "发布前名字"
    assert len(participants) == 1
    assert participants[0].is_creator is True


def test_cancel_rejects_inside_cutoff(db, test_user):
    segment = _segment(db)
    meetup = service.create_meetup(
        db,
        test_user.id,
        segment.id,
        None,
        datetime.now(timezone.utc) + timedelta(minutes=20),
        datetime.now(timezone.utc) + timedelta(hours=2),
        "A",
        "cruise",
        4,
        None,
    )
    service.publish_meetup(db, meetup.id, test_user.id)

    with pytest.raises(HTTPException) as exc:
        service.cancel_meetup(db, meetup.id, test_user.id)

    assert exc.value.status_code == 410


def test_delete_only_allows_draft(db, test_user):
    segment = _segment(db)
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "cruise", 4, None
    )
    service.publish_meetup(db, meetup.id, test_user.id)

    with pytest.raises(HTTPException) as exc:
        service.delete_draft_meetup(db, meetup.id, test_user.id)

    assert exc.value.status_code == 409


def test_load_and_authorize_creator_guard(db, test_user, admin_user):
    segment = _segment(db)
    meetup = service.create_meetup(
        db, test_user.id, segment.id, None, _start(), _start() + timedelta(hours=2), "A", "cruise", 4, None
    )

    with pytest.raises(HTTPException) as exc:
        service._load_and_authorize_meetup(db, meetup.id, admin_user.id, require_creator=True)

    assert exc.value.status_code == 403
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_service.py -q
```

Expected: FAIL because `app/meetup/service.py` is missing.

- [ ] **Step 4: Add service**

Create `app/meetup/service.py` with this complete code:

```python
"""
约骑业务逻辑——把路线图纸变成可发布、可取消、可查看的约骑活动。
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.meetup.models import Meetup, MeetupMedia, MeetupParticipant
from app.route_book.models import RouteBook
from app.segment.models import Segment


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _snapshot_from_route(db: Session, segment_id: int | None, route_book_id: int | None) -> dict:
    if (segment_id is None) == (route_book_id is None):
        raise HTTPException(status_code=422, detail="segment_id 和 route_book_id 必须二选一")

    if segment_id is not None:
        segment = db.query(Segment).filter(Segment.id == segment_id).first()
        if segment is None:
            raise HTTPException(status_code=404, detail="segment not found")
        return {
            "snapshot_route_name": segment.name,
            "snapshot_distance": segment.distance,
            "snapshot_climb": segment.elevation_gain,
            "snapshot_city": segment.city or "unknown",
        }

    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise HTTPException(status_code=404, detail="route_book not found")
    return {
        "snapshot_route_name": route.name,
        "snapshot_distance": route.distance,
        "snapshot_climb": route.climb,
        "snapshot_city": route.city or "unknown",
    }


def _load_and_authorize_meetup(
    db: Session,
    meetup_id: int,
    current_user_id: int,
    *,
    require_creator: bool = False,
    require_status: list[str] | None = None,
    check_time_cutoff: bool = False,
) -> Meetup:
    query = db.query(Meetup).filter(Meetup.id == meetup_id).with_for_update().populate_existing()
    meetup = query.first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    if require_creator and meetup.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="not creator")
    if require_status and meetup.status not in require_status:
        raise HTTPException(status_code=409, detail=f"invalid status: {meetup.status}")
    if check_time_cutoff:
        cutoff = _ensure_aware(meetup.start_time) - timedelta(minutes=30, seconds=30)
        if _now_utc() >= cutoff:
            raise HTTPException(status_code=410, detail="meetup cutoff passed")
    return meetup


def create_meetup(
    db: Session,
    current_user_id: int,
    segment_id: int | None,
    route_book_id: int | None,
    start_time: datetime,
    estimated_end_time: datetime,
    meeting_point: str,
    pace_level: str,
    max_participants: int,
    description: str | None,
) -> Meetup:
    existing = db.query(Meetup).filter(Meetup.creator_id == current_user_id, Meetup.status == "DRAFT").first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="draft_exists")

    snapshot = _snapshot_from_route(db, segment_id, route_book_id)
    meetup = Meetup(
        creator_id=current_user_id,
        status="DRAFT",
        segment_id=segment_id,
        route_book_id=route_book_id,
        start_time=_ensure_aware(start_time),
        estimated_end_time=_ensure_aware(estimated_end_time),
        meeting_point=meeting_point,
        pace_level=pace_level,
        max_participants=max_participants,
        description=description,
        **snapshot,
    )
    db.add(meetup)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_meetups_creator_draft" in str(exc.orig):
            raise HTTPException(status_code=409, detail="draft_exists")
        raise
    db.refresh(meetup)
    return meetup


def update_meetup(db: Session, meetup_id: int, current_user_id: int, **changes) -> Meetup:
    meetup = _load_and_authorize_meetup(
        db, meetup_id, current_user_id, require_creator=True, require_status=["DRAFT"]
    )
    route_changed = "segment_id" in changes or "route_book_id" in changes
    if route_changed:
        snapshot = _snapshot_from_route(db, changes.get("segment_id"), changes.get("route_book_id"))
        for key, value in snapshot.items():
            setattr(meetup, key, value)
        meetup.segment_id = changes.get("segment_id")
        meetup.route_book_id = changes.get("route_book_id")

    for key in ("start_time", "estimated_end_time", "meeting_point", "pace_level", "max_participants", "description"):
        if key in changes:
            value = changes[key]
            if key in {"start_time", "estimated_end_time"} and value is not None:
                value = _ensure_aware(value)
            setattr(meetup, key, value)

    db.commit()
    db.refresh(meetup)
    return meetup


def publish_meetup(db: Session, meetup_id: int, current_user_id: int) -> Meetup:
    meetup = _load_and_authorize_meetup(
        db, meetup_id, current_user_id, require_creator=True, require_status=["DRAFT"]
    )
    meetup.status = "OPEN"
    existing = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id, user_id=current_user_id).first()
    if existing is None:
        db.add(MeetupParticipant(meetup_id=meetup.id, user_id=current_user_id, is_creator=True))
    db.commit()
    db.refresh(meetup)
    return meetup


def cancel_meetup(db: Session, meetup_id: int, current_user_id: int) -> Meetup:
    meetup = _load_and_authorize_meetup(
        db,
        meetup_id,
        current_user_id,
        require_creator=True,
        require_status=["OPEN"],
        check_time_cutoff=True,
    )
    meetup.status = "CANCELLED"
    meetup.cancelled_at = _now_utc()
    db.commit()
    db.refresh(meetup)
    return meetup


def delete_draft_meetup(db: Session, meetup_id: int, current_user_id: int) -> None:
    meetup = _load_and_authorize_meetup(
        db, meetup_id, current_user_id, require_creator=True, require_status=["DRAFT"]
    )
    db.delete(meetup)
    db.commit()


def get_my_draft(db: Session, current_user_id: int) -> Meetup | None:
    return db.query(Meetup).filter(Meetup.creator_id == current_user_id, Meetup.status == "DRAFT").first()


def list_meetups(
    db: Session,
    status: str | None = None,
    city: str | None = None,
    date_range: str | None = None,
    pace: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    base = db.query(Meetup)
    if status:
        base = base.filter(Meetup.status == status)
    if city:
        base = base.filter(Meetup.snapshot_city == city)
    if pace:
        base = base.filter(Meetup.pace_level == pace)
    if date_range:
        start_text, end_text = date_range.split(",", 1)
        start_dt = _ensure_aware(datetime.fromisoformat(start_text))
        end_dt = _ensure_aware(datetime.fromisoformat(end_text))
        base = base.filter(Meetup.start_time >= start_dt, Meetup.start_time <= end_dt)
    total = base.count()
    items = (
        base.order_by(Meetup.start_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    meetup_ids = [m.id for m in items]
    counts = {}
    first_media = {}
    if meetup_ids:
        rows = (
            db.query(MeetupParticipant.meetup_id, MeetupParticipant.id)
            .filter(MeetupParticipant.meetup_id.in_(meetup_ids))
            .all()
        )
        for row in rows:
            counts[row.meetup_id] = counts.get(row.meetup_id, 0) + 1
        media_rows = (
            db.query(MeetupMedia.meetup_id, MeetupMedia.file_id)
            .filter(MeetupMedia.meetup_id.in_(meetup_ids), MeetupMedia.seq == 0)
            .all()
        )
        first_media = {row.meetup_id: row.file_id for row in media_rows}
    return {"items": items, "total": total, "participants_count": counts, "first_media": first_media}


def get_meetup_detail(db: Session, meetup_id: int) -> Meetup:
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        raise HTTPException(status_code=404, detail="meetup not found")
    return meetup
```

- [ ] **Step 5: Run green tests**

```bash
python3 -m pytest tests/test_meetup_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Self-review**

- [ ] Spec coverage: status transitions, helper, time cutoff, draft recalc, publish freeze, and creator participant insertion are covered.
- [ ] Type consistency: service uses `route_book_id`, not `route_id`; `snapshot_climb`, not `snapshot_elevation`.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: this task creates no reverse imports outside `app/meetup/`.

Run:

```bash
grep -rn "from app.meetup\\|import app.meetup" app/user app/activity app/segment
python3 -m pytest tests/test_meetup_service.py -q
```

Expected: grep empty; tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/meetup/service.py tests/test_meetup_service.py
git commit -F - <<'MSG'
feat(meetup): task 3 add lifecycle service

Add draft, patch, publish, cancel, delete, list, detail, and authorization helpers for meetup lifecycle.
Preserve draft snapshot recalculation, publish freeze, creator participant insertion, and 30-minute cutoff.
MSG
```
