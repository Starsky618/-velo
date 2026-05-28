# Task 4: Meetup API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the route book and meetup services through FastAPI, including the 12 meetup endpoints and app-level router mounts.

**Architecture:** Router functions are the front desk. They validate request shapes, call service functions, translate known service errors into HTTP responses, and never duplicate state-machine logic.

**Tech Stack:** FastAPI APIRouter, Pydantic v2 schemas, pytest API tests.

---

## User Story

阿杰打开小程序能看到约骑列表，点进去看详情，陈哥能创建草稿、修改、发布、取消或删除草稿。Before this task, backend service exists but users cannot reach it by HTTP.

## Files

- Create: `app/meetup/schemas.py`
- Create: `app/meetup/router.py`
- Create: `tests/test_meetup_api.py`
- Modify: `app/main.py`
- Test: `tests/test_meetup_api.py`

## Evidence Anchors

- [✓ grep] 12 meetup endpoints: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:397-412`.
- [✓ grep] route book router also needs main mount: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:414-421`.
- [✓ grep] app router mount pattern: `app/main.py:42-57`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 schemas/router/main mount；复审时确认测试者≠实现者。

## Steps

- [ ] **Step 1: Read endpoint list and app mount pattern**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '397,421p'
nl -ba app/main.py | sed -n '14,57p'
```

Expected: you can name every endpoint and exactly where routers are mounted.

- [ ] **Step 2: Write red API tests**

Create `tests/test_meetup_api.py`:

```python
"""约骑模块 Task 4：HTTP API 测试。"""

from datetime import datetime, timedelta, timezone

from app.meetup.models import Meetup
from app.route_book.models import RouteBook
from app.segment.models import Segment


def _segment(db):
    segment = Segment(
        name="晋阳湖绕圈",
        distance=28000.0,
        elevation_gain=120.0,
        start_lat=37.7,
        start_lon=112.4,
        end_lat=37.8,
        end_lon=112.5,
        reference_line="SRID=4326;LINESTRING(112.4 37.7, 112.5 37.8)",
        city="taiyuan",
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def _payload(segment_id):
    start = datetime.now(timezone.utc) + timedelta(days=3)
    return {
        "segment_id": segment_id,
        "start_time": start.isoformat(),
        "estimated_end_time": (start + timedelta(hours=3)).isoformat(),
        "meeting_point": "晋阳湖东门",
        "pace_level": "cruise",
        "max_participants": 6,
        "description": "均速 28 左右",
    }


def test_create_patch_publish_cancel_and_delete_paths(client, db, auth_header):
    segment = _segment(db)

    create_res = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header)
    assert create_res.status_code == 200
    meetup_id = create_res.json()["id"]
    assert create_res.json()["status"] == "DRAFT"

    patch_res = client.patch(
        f"/api/meetups/{meetup_id}",
        json={"meeting_point": "晋阳湖西门", "description": "集合点改西门"},
        headers=auth_header,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["meeting_point"] == "晋阳湖西门"

    draft_res = client.get("/api/meetups/my-draft", headers=auth_header)
    assert draft_res.status_code == 200
    assert draft_res.json()["id"] == meetup_id

    publish_res = client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    assert publish_res.status_code == 200
    assert publish_res.json()["status"] == "OPEN"

    cancel_res = client.post(f"/api/meetups/{meetup_id}/cancel", headers=auth_header)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"


def test_delete_draft_returns_204(client, db, auth_header):
    segment = _segment(db)
    create_res = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header)
    meetup_id = create_res.json()["id"]

    res = client.delete(f"/api/meetups/{meetup_id}", headers=auth_header)

    assert res.status_code == 204
    assert db.query(Meetup).filter(Meetup.id == meetup_id).first() is None


def test_list_and_detail_are_public(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    create_res = client.post("/api/meetups", json=payload, headers=auth_header)
    meetup_id = create_res.json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    start = datetime.fromisoformat(payload["start_time"])
    params = {
        "status": "OPEN",
        "city": "taiyuan",
        "date_range": f"{(start - timedelta(hours=1)).isoformat()},{(start + timedelta(hours=1)).isoformat()}",
        "pace": "cruise",
    }
    list_res = client.get("/api/meetups", params=params)
    detail_res = client.get(f"/api/meetups/{meetup_id}")

    assert list_res.status_code == 200
    assert list_res.json()["items"][0]["id"] == meetup_id
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == meetup_id


def test_create_rejects_extra_field(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["unexpected"] = "bad"

    res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert res.status_code == 422


def test_main_mounts_meetup_and_route_book_routers():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.router.routes}
    assert "/api/meetups" in paths
    assert "/api/route-books" in paths
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_api.py -q
```

Expected: FAIL because schemas/router/main mounts are not finished.

- [ ] **Step 4: Add schemas**

Create `app/meetup/schemas.py`:

```python
"""
约骑接口格式——小程序和后端约定每张约骑卡片长什么样。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MeetupStatus = Literal["DRAFT", "OPEN", "CANCELLED", "COMPLETED"]
PaceLevel = Literal["relaxed", "cruise", "training", "race"]
City = Literal["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]


class MeetupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: int | None = None
    route_book_id: int | None = None
    start_time: datetime
    estimated_end_time: datetime
    meeting_point: str = Field(..., min_length=1, max_length=128)
    pace_level: PaceLevel
    max_participants: int = Field(..., ge=2, le=20)
    description: str | None = Field(None, max_length=2000)


class MeetupPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: int | None = None
    route_book_id: int | None = None
    start_time: datetime | None = None
    estimated_end_time: datetime | None = None
    meeting_point: str | None = Field(None, min_length=1, max_length=128)
    pace_level: PaceLevel | None = None
    max_participants: int | None = Field(None, ge=2, le=20)
    description: str | None = Field(None, max_length=2000)


class MeetupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    creator_id: int | None = None
    status: MeetupStatus
    segment_id: int | None = None
    route_book_id: int | None = None
    snapshot_route_name: str
    snapshot_distance: float
    snapshot_climb: float | None = None
    snapshot_city: City
    start_time: datetime
    estimated_end_time: datetime
    meeting_point: str
    pace_level: PaceLevel
    max_participants: int
    description: str | None = None
    participants_count: int = 0
    first_media_file_id: str | None = None
    created_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None


class MeetupListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MeetupResponse]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 5: Add router**

Create `app/meetup/router.py`:

```python
"""
约骑 API 路由——列表、详情、草稿、发布、取消和删除的 HTTP 服务台。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.meetup import schemas, service


router = APIRouter(prefix="/api/meetups", tags=["meetup"])


def _response(meetup, participants_count=0, first_media_file_id=None) -> schemas.MeetupResponse:
    return schemas.MeetupResponse(
        id=meetup.id,
        creator_id=meetup.creator_id,
        status=meetup.status,
        segment_id=meetup.segment_id,
        route_book_id=meetup.route_book_id,
        snapshot_route_name=meetup.snapshot_route_name,
        snapshot_distance=meetup.snapshot_distance,
        snapshot_climb=meetup.snapshot_climb,
        snapshot_city=meetup.snapshot_city,
        start_time=meetup.start_time,
        estimated_end_time=meetup.estimated_end_time,
        meeting_point=meetup.meeting_point,
        pace_level=meetup.pace_level,
        max_participants=meetup.max_participants,
        description=meetup.description,
        participants_count=participants_count,
        first_media_file_id=first_media_file_id,
        created_at=meetup.created_at,
        cancelled_at=meetup.cancelled_at,
        completed_at=meetup.completed_at,
    )


@router.get("", response_model=schemas.MeetupListResponse)
def list_meetups(
    status: schemas.MeetupStatus | None = None,
    city: schemas.City | None = None,
    date_range: str | None = None,
    pace: schemas.PaceLevel | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_meetups(
        db,
        status=status,
        city=city,
        date_range=date_range,
        pace=pace,
        page=page,
        page_size=page_size,
    )
    items = [
        _response(
            meetup,
            participants_count=result["participants_count"].get(meetup.id, 0),
            first_media_file_id=result["first_media"].get(meetup.id),
        )
        for meetup in result["items"]
    ]
    return schemas.MeetupListResponse(items=items, total=result["total"], page=page, page_size=page_size)


@router.get("/my-draft", response_model=schemas.MeetupResponse | None)
def get_my_draft(current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    meetup = service.get_my_draft(db, current_user_id)
    return _response(meetup) if meetup is not None else None


@router.get("/{meetup_id}", response_model=schemas.MeetupResponse)
def get_meetup(meetup_id: int, db: Session = Depends(get_db)):
    return _response(service.get_meetup_detail(db, meetup_id))


@router.post("", response_model=schemas.MeetupResponse)
def create_meetup(
    req: schemas.MeetupCreateRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    meetup = service.create_meetup(
        db,
        current_user_id=current_user_id,
        segment_id=req.segment_id,
        route_book_id=req.route_book_id,
        start_time=req.start_time,
        estimated_end_time=req.estimated_end_time,
        meeting_point=req.meeting_point,
        pace_level=req.pace_level,
        max_participants=req.max_participants,
        description=req.description,
    )
    return _response(meetup)


@router.patch("/{meetup_id}", response_model=schemas.MeetupResponse)
def update_meetup(
    meetup_id: int,
    req: schemas.MeetupPatchRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    changes = req.model_dump(exclude_unset=True)
    return _response(service.update_meetup(db, meetup_id, current_user_id, **changes))


@router.post("/{meetup_id}/publish", response_model=schemas.MeetupResponse)
def publish_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(service.publish_meetup(db, meetup_id, current_user_id), participants_count=1)


@router.post("/{meetup_id}/cancel", response_model=schemas.MeetupResponse)
def cancel_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    return _response(service.cancel_meetup(db, meetup_id, current_user_id))


@router.delete("/{meetup_id}", status_code=204)
def delete_meetup(meetup_id: int, current_user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    service.delete_draft_meetup(db, meetup_id, current_user_id)
```

- [ ] **Step 6: Mount routers in `app/main.py`**

Add imports near other routers:

```python
from app.meetup.router import router as meetup_router
from app.route_book.router import router as route_book_router
```

Add includes after `segment_router` and before admin/training:

```python
app.include_router(route_book_router)
app.include_router(meetup_router)
```

- [ ] **Step 7: Run green tests**

```bash
python3 -m pytest tests/test_meetup_api.py tests/test_route_book_api.py -q
```

Expected: PASS.

- [ ] **Step 8: Self-review**

- [ ] Spec coverage: list filters (`status`, `city`, `date_range`, `pace`, `page`), detail/create/patch/publish/cancel/delete/my-draft, and both router mounts are covered here; Task 5 adds join/leave paths and Task 6 adds media paths without changing these existing routes.
- [ ] Type consistency: API response names match Task 3 service and Task 1 model names.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: `app/main.py` imports routers only; business modules do not import `app.main`.

Run:

```bash
python3 - <<'PY'
from app.main import app
paths = sorted(getattr(route, "path", "") for route in app.router.routes)
for path in ["/api/meetups", "/api/meetups/{meetup_id}", "/api/route-books"]:
    assert path in paths, path
print("router paths mounted")
PY
python3 -m pytest tests/test_meetup_api.py tests/test_route_book_api.py -q
```

- [ ] **Step 9: Commit**

```bash
git add app/meetup/schemas.py app/meetup/router.py app/main.py tests/test_meetup_api.py
git commit -F - <<'MSG'
feat(meetup): task 4 expose meetup API

Add meetup schemas, router, and app mounts for meetup and route book endpoints.
Keep state-machine rules in service while router stays a thin HTTP translator.
MSG
```
