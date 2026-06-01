# Task 8: Segment Upcoming Meetups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one public endpoint showing upcoming OPEN meetups for a segment.

**Architecture:** This is the second intentional reverse hook. Segment detail can show “这条路线最近有人约骑” without making meetup part of segment core logic.

**Tech Stack:** FastAPI router extension, Pydantic response schema, SQLAlchemy aggregate query, pytest API/static tests.

---

## User Story

阿杰点开“太山爬坡”赛段详情，不只是看排行榜，还能看到周六有人组织骑这条线。他点进去就能加入约骑。Before this task,赛段详情只告诉他“这条路有多强”，不能告诉他“谁要一起骑”。

## Files

- Modify: `app/segment/schemas.py`
- Modify: `app/segment/router.py`
- Create: `tests/test_segment_upcoming_meetups.py`
- Test: `tests/test_segment_upcoming_meetups.py`

## Evidence Anchors

- [✓ grep] endpoint is explicitly allowed: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:424-428`.
- [✓ grep] reverse hook is explicitly listed: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:645-646`.
- [✓ grep] existing segment router pattern: `app/segment/router.py:180-198`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 segment upcoming endpoint；复审时确认测试者≠实现者，且反向 hook 被架构 grep 记录。

## Steps

- [ ] **Step 1: Read allowed hook**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '424,428p;641,646p'
nl -ba app/segment/router.py | sed -n '180,220p'
```

Expected: you see exactly one new segment endpoint and the reverse-hook deletion SOP.

- [ ] **Step 2: Write red tests**

Create `tests/test_segment_upcoming_meetups.py`:

```python
"""约骑模块 Task 8：赛段详情 upcoming-meetups endpoint 测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.meetup import service
from app.segment.models import Segment


ROOT = Path(__file__).resolve().parents[1]


def _segment(db, name):
    segment = Segment(
        name=name,
        distance=10000.0,
        elevation_gain=200.0,
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


def _open_meetup(db, user_id, segment_id, days=2):
    start = datetime.now(timezone.utc) + timedelta(days=days)
    meetup = service.create_meetup(
        db, user_id, segment_id, None, start, start + timedelta(hours=2), "集合点", "cruise", 4, "一起骑"
    )
    return service.publish_meetup(db, meetup.id, user_id)


def test_segment_upcoming_meetups_returns_public_open_future_items(client, db, auth_header, test_user):
    segment = _segment(db, "太山爬坡")
    other = _segment(db, "晋阳湖")
    target = _open_meetup(db, test_user.id, segment.id, days=2)
    _open_meetup(db, test_user.id, other.id, days=2)
    past = _open_meetup(db, test_user.id, segment.id, days=-2)

    res = client.get(f"/api/segments/{segment.id}/upcoming-meetups")

    assert res.status_code == 200
    body = res.json()
    assert body["items"][0]["id"] == target.id
    assert all(item["id"] != past.id for item in body["items"])


def test_segment_upcoming_endpoint_is_public(client, db, test_user):
    segment = _segment(db, "公开路线")
    _open_meetup(db, test_user.id, segment.id, days=2)

    res = client.get(f"/api/segments/{segment.id}/upcoming-meetups")

    assert res.status_code == 200


def test_segment_reverse_hook_is_exactly_one_endpoint():
    router = (ROOT / "app" / "segment" / "router.py").read_text(encoding="utf-8")

    assert "@router.get(\"/{segment_id}/upcoming-meetups\"" in router
    assert "from app.meetup.models import Meetup" in router
    assert "from app.route_book" not in router
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_segment_upcoming_meetups.py -q
```

Expected: FAIL because schema and endpoint do not exist.

- [ ] **Step 4: Add schemas**

Append to `app/segment/schemas.py`:

```python
class SegmentUpcomingMeetupItem(BaseModel):
    """赛段详情页上显示的一张 upcoming meetup 小卡。"""

    id: int
    snapshot_route_name: str
    snapshot_distance: float
    snapshot_climb: Optional[float] = None
    snapshot_city: str
    start_time: datetime
    meeting_point: str
    pace_level: str
    max_participants: int
    participants_count: int


class SegmentUpcomingMeetupsResponse(BaseModel):
    """某个赛段未来开放约骑列表。"""

    items: list[SegmentUpcomingMeetupItem]
```

- [ ] **Step 5: Add endpoint**

In `app/segment/router.py`, add imports:

```python
from datetime import datetime, timezone
from app.meetup.models import Meetup, MeetupParticipant
```

Append endpoint near other segment-detail routes:

```python
@router.get("/{segment_id}/upcoming-meetups", response_model=schemas.SegmentUpcomingMeetupsResponse)
def get_segment_upcoming_meetups(
    segment_id: int,
    db: Session = Depends(get_db),
):
    """
    查看某条赛段未来的开放约骑。

    这是 spec 允许的可删除反向 hook：删约骑模块时整段 endpoint 一起删。
    """
    now = datetime.now(timezone.utc)
    meetups = (
        db.query(Meetup)
        .filter(
            Meetup.segment_id == segment_id,
            Meetup.status == "OPEN",
            Meetup.start_time > now,
        )
        .order_by(Meetup.start_time.asc())
        .limit(5)
        .all()
    )
    meetup_ids = [m.id for m in meetups]
    counts = {}
    if meetup_ids:
        rows = (
            db.query(MeetupParticipant.meetup_id, MeetupParticipant.id)
            .filter(MeetupParticipant.meetup_id.in_(meetup_ids))
            .all()
        )
        for row in rows:
            counts[row.meetup_id] = counts.get(row.meetup_id, 0) + 1
    return schemas.SegmentUpcomingMeetupsResponse(
        items=[
            schemas.SegmentUpcomingMeetupItem(
                id=m.id,
                snapshot_route_name=m.snapshot_route_name,
                snapshot_distance=m.snapshot_distance,
                snapshot_climb=m.snapshot_climb,
                snapshot_city=m.snapshot_city,
                start_time=m.start_time,
                meeting_point=m.meeting_point,
                pace_level=m.pace_level,
                max_participants=m.max_participants,
                participants_count=counts.get(m.id, 0),
            )
            for m in meetups
        ]
    )
```

- [ ] **Step 6: Run green tests**

```bash
python3 -m pytest tests/test_segment_upcoming_meetups.py -q
```

Expected: PASS.

- [ ] **Step 7: Architecture grep**

```bash
grep -rn "from app.meetup\\|import app.meetup" app/user app/activity app/segment scheduler.py
grep -rn "upcoming-meetups" app/segment tests docs/superpowers/plans/2026-05-28-meetup-module
```

Expected: `app/segment/router.py` is the only segment reverse-hook hit. Record it in review.

- [ ] **Step 8: Self-review**

- [ ] Spec coverage: endpoint path, public access, future OPEN filter, participant count, and deletion SOP are covered.
- [ ] Type consistency: response uses `snapshot_*` fields from meetup, not live segment fields.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: no route_book import appears in `app/segment/router.py`.

- [ ] **Step 9: Commit**

```bash
git add app/segment/schemas.py app/segment/router.py tests/test_segment_upcoming_meetups.py
git commit -F - <<'MSG'
feat(segment): task 8 show upcoming meetups

Add a public segment upcoming-meetups endpoint backed by the spec-approved segment to meetup reverse hook.
Return future OPEN meetup cards using frozen snapshot fields and participant counts.
MSG
```
