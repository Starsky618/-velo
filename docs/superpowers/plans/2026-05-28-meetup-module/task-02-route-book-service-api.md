# Task 2: Route Book Service And API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a rider create and delete route books from GPX/FIT uploads or from one of their own completed activities.

**Architecture:** Route book is the reusable drawing layer. It reads parser output, activity rows, and storage, then writes only `route_books`; it does not create meetups and does not participate in KOM rankings.

**Tech Stack:** FastAPI sync router, UploadFile, SQLAlchemy, GeoAlchemy2 WKTElement, existing GPX/FIT parsers, existing LocalStorage.

---

## User Story

陈哥不想每次约骑都重新画路线。他上传一条 GPX 或 FIT，或者从自己以前骑过的一条活动里生成路书。之后创建约骑时，他能直接选这张图纸。

## Files

- Create: `app/route_book/schemas.py`
- Create: `app/route_book/service.py`
- Create: `app/route_book/router.py`
- Create: `tests/test_route_book_api.py`
- Modify: none in `app/main.py` for this task; Task 4 mounts routers together.
- Test: `tests/test_route_book_api.py`

## Evidence Anchors

- [✓ grep] Route book model contract: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:154-204`.
- [✓ grep] GPX and FIT upload are existing supported file types: `app/activity/service.py:124-150`.
- [✓ grep] parsers return `ParseResult`: `app/parsing/types.py:138-153`.
- [✓ grep] storage keeps original extension: `app/storage/local.py:64-74`.
- [✓ grep] route book API list: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:414-421`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 route_book service/router；复审时确认测试者≠实现者。

## Steps

- [ ] **Step 1: Read source files**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '154,204p;414,421p'
nl -ba app/activity/service.py | sed -n '124,150p'
nl -ba app/parsing/types.py | sed -n '138,153p'
```

Expected: you can point to file_upload, activity_derived, GPX/FIT, and orphan semantics.

- [ ] **Step 2: Write red API tests**

Create `tests/test_route_book_api.py`:

```python
"""约骑模块 Task 2：路书 API 测试。"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.activity.models import Activity, Trackpoint


def _activity(db, user_id: int, **overrides):
    data = {
        "user_id": user_id,
        "title": "周末路线",
        "status": "completed",
        "activity_type": "cycling",
        "file_url": "202605/ride.gpx",
        "distance": 42000.0,
        "elevation_gain": 580.0,
        "started_at": datetime(2026, 5, 20, 1, 0, tzinfo=timezone.utc),
    }
    data.update(overrides)
    activity = Activity(**data)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    db.add_all([
        Trackpoint(activity_id=activity.id, seq=0, latitude=37.8, longitude=112.5, distance=0.0),
        Trackpoint(activity_id=activity.id, seq=1, latitude=37.9, longitude=112.6, distance=42000.0),
    ])
    db.commit()
    return activity


def test_activity_derived_requires_source_activity_id(client, auth_header):
    res = client.post(
        "/api/route-books",
        data={"name": "无来源", "source": "activity_derived"},
        headers=auth_header,
    )
    assert res.status_code == 422
    assert "source_activity_id" in res.text


def test_activity_derived_rejects_other_user_activity(client, db, auth_header, admin_user):
    other_activity = _activity(db, admin_user.id)

    res = client.post(
        "/api/route-books",
        data={"name": "别人的路线", "source": "activity_derived", "source_activity_id": str(other_activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 403


def test_activity_derived_creates_route_book(client, db, auth_header, test_user):
    activity = _activity(db, test_user.id, city="taiyuan")

    res = client.post(
        "/api/route-books",
        data={"name": "汾河训练线", "source": "activity_derived", "source_activity_id": str(activity.id)},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "汾河训练线"
    assert body["source"] == "activity_derived"
    assert body["source_activity_id"] == activity.id
    assert body["file_id"] is None
    assert body["file_type"] is None
    assert body["city"] == "taiyuan"


def test_file_upload_supports_gpx_and_preserves_file_id(client, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.gpx"
            return "202605/route.gpx"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 1234.0,
        "climb": 50.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
    })

    res = client.post(
        "/api/route-books",
        data={"name": "上传路线", "source": "file_upload"},
        files={"file": ("route.gpx", b"<?xml version='1.0'?><gpx></gpx>", "application/gpx+xml")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/route.gpx"
    assert body["file_type"] == "gpx"


def test_file_upload_supports_fit_and_preserves_file_id(client, auth_header, monkeypatch):
    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename == "route.fit"
            return "202605/route.fit"

    monkeypatch.setattr("app.route_book.service._storage", FakeStorage())
    monkeypatch.setattr("app.route_book.service._parse_route_file", lambda filename, b: {
        "distance": 2345.0,
        "climb": 80.0,
        "city": "taiyuan",
        "wkt": "SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
    })

    res = client.post(
        "/api/route-books",
        data={"name": "FIT 路线", "source": "file_upload"},
        files={"file": ("route.fit", b"fit-bytes", "application/octet-stream")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/route.fit"
    assert body["file_type"] == "fit"


def test_list_supports_public_mine_and_city_filters(client, db, auth_header, admin_header, test_user, admin_user):
    from app.route_book.models import RouteBook

    mine = RouteBook(
        creator_id=test_user.id,
        name="我的训练路线",
        distance=1800.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    other = RouteBook(
        creator_id=admin_user.id,
        name="别人的路线",
        distance=2200.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.7 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add_all([mine, other])
    db.commit()
    db.refresh(mine)
    db.refresh(other)

    list_res = client.get("/api/route-books?city=taiyuan", headers=auth_header)
    assert list_res.status_code == 200
    names = [item["name"] for item in list_res.json()["items"]]
    assert "我的训练路线" in names
    assert "别人的路线" in names

    public_res = client.get("/api/route-books?city=taiyuan")
    assert public_res.status_code == 200
    assert len(public_res.json()["items"]) == 2

    mine_res = client.get("/api/route-books?mine=1", headers=auth_header)
    assert mine_res.status_code == 200
    mine_names = [item["name"] for item in mine_res.json()["items"]]
    assert "我的训练路线" in mine_names
    assert "别人的路线" not in mine_names

    unauth_mine = client.get("/api/route-books?mine=1")
    assert unauth_mine.status_code == 401

    detail_res = client.get(f"/api/route-books/{other.id}", headers=auth_header)
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == other.id


def test_delete_route_book_is_owner_only(client, db, auth_header, admin_header, test_user):
    from app.route_book.models import RouteBook

    route = RouteBook(
        creator_id=test_user.id,
        name="可删路线",
        distance=1000.0,
        reference_line="SRID=4326;LINESTRING(112.5 37.8, 112.6 37.9)",
        source="activity_derived",
        source_activity_id=None,
        city="taiyuan",
    )
    db.add(route)
    db.commit()
    db.refresh(route)

    forbidden = client.delete(f"/api/route-books/{route.id}", headers=admin_header)
    assert forbidden.status_code == 403

    ok = client.delete(f"/api/route-books/{route.id}", headers=auth_header)
    assert ok.status_code == 204


def test_activity_candidates_only_returns_current_user_completed_cycling(client, db, auth_header, test_user, admin_user):
    own = _activity(db, test_user.id, title="自己的骑行", city="taiyuan")
    _activity(db, test_user.id, title="跑步", activity_type="running")
    _activity(db, test_user.id, title="失败上传", status="failed")
    _activity(db, admin_user.id, title="别人骑行")

    res = client.get("/api/route-books/activity-candidates", headers=auth_header)

    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["id"] for item in items] == [own.id]
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_route_book_api.py -q
```

Expected: FAIL because route book schemas/service/router are missing and routes are not mounted in the local test app until you include the router for this test.

- [ ] **Step 4: Add schemas**

Create `app/route_book/schemas.py`:

```python
"""
路书接口格式——前端创建、查看、删除路线图纸时使用的表格。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


RouteBookSource = Literal["file_upload", "activity_derived"]
RouteBookFileType = Literal["gpx", "fit"]
City = Literal["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]


class RouteBookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    distance: float
    climb: float | None = None
    file_id: str | None = None
    file_type: RouteBookFileType | None = None
    source: RouteBookSource
    source_activity_id: int | None = None
    city: City
    created_at: datetime | None = None


class RouteBookListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RouteBookResponse]


class ActivityCandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    title: str | None = None
    distance: float | None = None
    elevation_gain: float | None = None
    city: City | None = None
    started_at: datetime | None = None


class ActivityCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActivityCandidateItem]
```

- [ ] **Step 5: Add service**

Create `app/route_book/service.py`. The full service code:

```python
"""
路书业务逻辑——把 GPX/FIT 或已有骑行翻译成可复用路线图纸。
"""

from geoalchemy2 import WKTElement
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.activity.service import validate_ride_file
from app.common.geo import infer_city_from_coords
from app.parsing.fit_parser import FITParser
from app.parsing.gpx_parser import GPXParser
from app.route_book.models import RouteBook
from app.storage.local import LocalStorage


_storage = LocalStorage()


def _file_type(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"gpx", "fit"}:
        raise ValueError("只接受 .gpx 或 .fit 文件")
    return suffix


def _parse_route_file(filename: str, file_bytes: bytes) -> dict:
    validate_ride_file(filename, file_bytes)
    parser = GPXParser() if _file_type(filename) == "gpx" else FITParser()
    result = parser.parse(file_bytes)
    points = [
        {"lat": p.lat, "lon": p.lon, "ele": p.ele}
        for p in result.trackpoints
        if p.lat is not None and p.lon is not None
    ]
    return _route_payload_from_points(points, result.summary.distance, result.summary.elevation_gain)


def _route_payload_from_points(points: list[dict], distance: float | None, climb: float | None) -> dict:
    if len(points) < 2:
        raise ValueError("路线至少需要 2 个有效轨迹点")
    coords = ", ".join(f"{p['lon']} {p['lat']}" for p in points)
    first = points[0]
    return {
        "distance": float(distance or 0),
        "climb": climb,
        "city": infer_city_from_coords(first.get("lat"), first.get("lon")),
        "wkt": f"SRID=4326;LINESTRING({coords})",
    }


def create_route_book(
    db: Session,
    current_user_id: int,
    name: str,
    source: str,
    source_activity_id: int | None = None,
    upload_filename: str | None = None,
    upload_bytes: bytes | None = None,
) -> RouteBook:
    if source == "activity_derived":
        if source_activity_id is None:
            raise ValueError("activity_derived 必须提供 source_activity_id")
        activity = db.query(Activity).filter(Activity.id == source_activity_id).first()
        if activity is None:
            raise LookupError("activity not found")
        if activity.user_id != current_user_id:
            raise PermissionError("not owner")
        if activity.status != "completed" or activity.activity_type != "cycling":
            raise ValueError("activity is not a completed cycling ride")
        trackpoints = (
            db.query(Trackpoint)
            .filter(Trackpoint.activity_id == activity.id)
            .order_by(Trackpoint.seq.asc())
            .all()
        )
        points = [
            {"lat": p.latitude, "lon": p.longitude, "ele": p.elevation}
            for p in trackpoints
            if p.latitude is not None and p.longitude is not None
        ]
        payload = _route_payload_from_points(points, activity.distance, activity.elevation_gain)
        route = RouteBook(
            creator_id=current_user_id,
            name=name,
            distance=payload["distance"],
            climb=payload["climb"],
            reference_line=WKTElement(payload["wkt"], srid=4326),
            file_id=None,
            file_type=None,
            source="activity_derived",
            source_activity_id=source_activity_id,
            city=activity.city or payload["city"],
        )
    elif source == "file_upload":
        if not upload_filename or upload_bytes is None:
            raise ValueError("file_upload 必须上传路线文件")
        payload = _parse_route_file(upload_filename, upload_bytes)
        file_id = _storage.upload(upload_bytes, upload_filename)
        route = RouteBook(
            creator_id=current_user_id,
            name=name,
            distance=payload["distance"],
            climb=payload["climb"],
            reference_line=WKTElement(payload["wkt"], srid=4326),
            file_id=file_id,
            file_type=_file_type(upload_filename),
            source="file_upload",
            source_activity_id=None,
            city=payload["city"],
        )
    else:
        raise ValueError("invalid source")

    db.add(route)
    db.commit()
    db.refresh(route)
    return route


def list_route_books(
    db: Session,
    current_user_id: int | None,
    *,
    mine: bool = False,
    city: str | None = None,
) -> list[RouteBook]:
    query = db.query(RouteBook)
    if mine:
        if current_user_id is None:
            raise PermissionError("login required")
        query = query.filter(RouteBook.creator_id == current_user_id)
    if city:
        query = query.filter(RouteBook.city == city)
    return query.order_by(RouteBook.created_at.desc()).all()


def get_route_book(db: Session, route_book_id: int) -> RouteBook:
    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise LookupError("route_book not found")
    return route


def delete_route_book(db: Session, route_book_id: int, current_user_id: int) -> None:
    route = db.query(RouteBook).filter(RouteBook.id == route_book_id).first()
    if route is None:
        raise LookupError("route_book not found")
    if route.creator_id != current_user_id:
        raise PermissionError("not owner")
    file_id = route.file_id
    db.delete(route)
    db.commit()
    if file_id:
        _storage.delete(file_id)


def list_activity_candidates(db: Session, current_user_id: int) -> list[Activity]:
    return (
        db.query(Activity)
        .filter(
            Activity.user_id == current_user_id,
            Activity.status == "completed",
            Activity.activity_type == "cycling",
            Activity.duplicate_of.is_(None),
        )
        .order_by(Activity.started_at.desc())
        .limit(50)
        .all()
    )
```

- [ ] **Step 6: Add router**

Create `app/route_book/router.py`:

```python
"""
路书 API 路由——前端创建或删除路线图纸的服务台。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_optional_user
from app.route_book import schemas, service


router = APIRouter(prefix="/api/route-books", tags=["route_book"])


@router.get("", response_model=schemas.RouteBookListResponse)
def list_route_books(
    mine: bool = Query(False),
    city: schemas.City | None = None,
    current_user_id: int | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        items = service.list_route_books(db, current_user_id, mine=mine, city=city)
        return schemas.RouteBookListResponse(items=items)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("", response_model=schemas.RouteBookResponse)
def create_route_book(
    name: str = Form(...),
    source: schemas.RouteBookSource = Form(...),
    source_activity_id: int | None = Form(None),
    file: UploadFile | None = File(None),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload_bytes = file.file.read() if file is not None else None
    upload_filename = file.filename if file is not None else None
    try:
        return service.create_route_book(
            db=db,
            current_user_id=current_user_id,
            name=name,
            source=source,
            source_activity_id=source_activity_id,
            upload_filename=upload_filename,
            upload_bytes=upload_bytes,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/activity-candidates", response_model=schemas.ActivityCandidateResponse)
def list_activity_candidates(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = service.list_activity_candidates(db, current_user_id)
    return schemas.ActivityCandidateResponse(items=items)


@router.get("/{route_book_id}", response_model=schemas.RouteBookResponse)
def get_route_book(
    route_book_id: int,
    db: Session = Depends(get_db),
):
    try:
        return service.get_route_book(db, route_book_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{route_book_id}", status_code=204)
def delete_route_book(
    route_book_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        service.delete_route_book(db, route_book_id, current_user_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


```

- [ ] **Step 7: Mount route router inside the test app only**

Before running this task's tests against repo `app.main`, Task 4 will mount routers globally. For Task 2 red-green in isolation, add this to `tests/test_route_book_api.py` after imports:

```python
from app.main import app
from app.route_book.router import router as route_book_router


if not any(getattr(route, "path", "") == "/api/route-books" for route in app.router.routes):
    app.include_router(route_book_router)
```

- [ ] **Step 8: Run green tests**

```bash
python3 -m pytest tests/test_route_book_api.py -q
```

Expected: PASS.

- [ ] **Step 9: Self-review**

- [ ] Spec coverage: `file_upload`, `activity_derived`, list/detail/delete, GPX/FIT extension, and activity-derived orphan semantics are represented.
- [ ] Type consistency: `file_id`, `file_type`, `source`, and `source_activity_id` match Task 1.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: `app/activity/` does not import `app.route_book`; only route_book reads upstream modules.

Run:

```bash
grep -rn "from app.route_book\\|import app.route_book" app/activity app/user app/segment
python3 -m pytest tests/test_route_book_api.py -q
```

Expected: grep empty; tests pass.

- [ ] **Step 10: Commit**

```bash
git add app/route_book/schemas.py app/route_book/service.py app/route_book/router.py tests/test_route_book_api.py
git commit -F - <<'MSG'
feat(route-book): task 2 add route book service and API

Add route book create/delete and activity-candidate endpoints with GPX/FIT upload, activity-derived ownership checks, and storage cleanup.
Keep route books independent from meetup creation and KOM ranking.
MSG
```
