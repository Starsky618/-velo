# Task 6: Media Upload And Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let meetup creators upload and delete meetup media with MIME limits, path ownership checks, caption escaping, and storage cleanup.

**Architecture:** Media is the picture wall on a meetup card. The database record is the source of truth; storage follows it and never decides whether a media item exists.

**Tech Stack:** FastAPI UploadFile, SQLAlchemy, LocalStorage, Python `html.escape`, pytest API tests.

---

## User Story

陈哥发约骑时传一张路线封面图。If upload fails, the database should not show a broken image. If he deletes it later, the card disappears first, and storage cleanup runs after the DB is already right.

## Files

- Create: `app/meetup/media_service.py`
- Modify: `app/meetup/service.py`
- Modify: `app/meetup/router.py`
- Modify: `app/meetup/schemas.py`
- Create: `tests/test_meetup_media.py`
- Test: `tests/test_meetup_media.py`

## Evidence Anchors

- [✓ grep] media fields and IDOR rule: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:130-145`.
- [✓ grep] media safety and upload/delete direction: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:147-152`.
- [✓ grep] storage delete API takes `file_id`: `app/storage/local.py:85-94`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后写 media service/router；复审时确认测试者≠实现者，且 storage 失败路径被测到。

## Steps

- [ ] **Step 1: Read media contract**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '130,152p;410,411p'
nl -ba app/storage/local.py | sed -n '85,94p'
```

Expected: you see `file_id`, MIME whitelist, size limits, path meetup_id equality, DB-first directions.

- [ ] **Step 2: Write red tests**

Create `tests/test_meetup_media.py`:

```python
"""约骑模块 Task 6：媒体上传和删除测试。"""

from datetime import datetime, timedelta, timezone

from app.meetup import service
from app.meetup.models import MeetupMedia
from app.segment.models import Segment


def _segment(db):
    segment = Segment(
        name="媒体路线",
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


def _draft(db, owner_id):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return service.create_meetup(db, owner_id, segment.id, None, start, start + timedelta(hours=2), "集合点", "cruise", 4, None)


def test_upload_media_creator_only_and_escapes_caption(client, db, auth_header, test_user, monkeypatch):
    meetup = _draft(db, test_user.id)

    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert filename.endswith(".jpg")
            return "202605/media.jpg"

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        data={"caption": "<b>集合点</b>"},
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=auth_header,
    )

    assert res.status_code == 200
    body = res.json()
    assert body["file_id"] == "202605/media.jpg"
    assert body["caption"] == "&lt;b&gt;集合点&lt;/b&gt;"


def test_upload_media_rejects_non_creator(client, db, auth_header, admin_header, test_user):
    meetup = _draft(db, test_user.id)

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=admin_header,
    )

    assert res.status_code == 403


def test_upload_media_rejects_bad_mime(client, db, auth_header, test_user):
    meetup = _draft(db, test_user.id)

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.svg", b"<svg></svg>", "image/svg+xml")},
        headers=auth_header,
    )

    assert res.status_code == 415


def test_delete_media_checks_path_meetup_id(client, db, auth_header, test_user):
    meetup = _draft(db, test_user.id)
    other = _draft(db, test_user.id)
    media = MeetupMedia(meetup_id=meetup.id, uploader_id=test_user.id, type="image", file_id="202605/a.jpg", seq=0)
    db.add(media)
    db.commit()
    db.refresh(media)

    res = client.delete(f"/api/meetups/{other.id}/media/{media.id}", headers=auth_header)

    assert res.status_code == 404


def test_delete_media_commits_db_before_storage_cleanup(client, db, auth_header, test_user, monkeypatch):
    meetup = _draft(db, test_user.id)
    media = MeetupMedia(meetup_id=meetup.id, uploader_id=test_user.id, type="image", file_id="202605/a.jpg", seq=0)
    db.add(media)
    db.commit()
    db.refresh(media)
    deleted = []

    class FakeStorage:
        def delete(self, file_id):
            deleted.append(file_id)
            return True

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.delete(f"/api/meetups/{meetup.id}/media/{media.id}", headers=auth_header)

    assert res.status_code == 204
    assert db.query(MeetupMedia).filter_by(id=media.id).first() is None
    assert deleted == ["202605/a.jpg"]


def test_delete_draft_meetup_cleans_media_storage(db, test_user, monkeypatch):
    draft = _draft(db, test_user.id)
    media = MeetupMedia(meetup_id=draft.id, uploader_id=test_user.id, type="image", file_id="202605/draft.jpg", seq=0)
    db.add(media)
    db.commit()
    deleted = []

    class FakeStorage:
        def delete(self, file_id):
            deleted.append(file_id)

    monkeypatch.setattr("app.meetup.service.LocalStorage", FakeStorage)

    service.delete_draft_meetup(db, draft.id, test_user.id)

    assert db.query(MeetupMedia).filter_by(id=media.id).first() is None
    assert deleted == ["202605/draft.jpg"]
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_media.py -q
```

Expected: FAIL because media service and routes do not exist.

- [ ] **Step 4: Add schema**

Append to `app/meetup/schemas.py`:

```python
class MeetupMediaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    meetup_id: int
    uploader_id: int | None = None
    type: Literal["image", "video"]
    file_id: str
    caption: str | None = None
    seq: int
    created_at: datetime | None = None
```

- [ ] **Step 5: Add media service**

Create `app/meetup/media_service.py`:

```python
"""
约骑媒体业务逻辑——处理封面图、视频和 storage 清理。
"""

import html
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.meetup.models import MeetupMedia
from app.meetup.service import _load_and_authorize_meetup
from app.storage.local import LocalStorage


logger = logging.getLogger(__name__)
_storage = LocalStorage()

_MEDIA_RULES = {
    "image/jpeg": ("image", 5 * 1024 * 1024, ".jpg"),
    "image/png": ("image", 5 * 1024 * 1024, ".png"),
    "image/webp": ("image", 5 * 1024 * 1024, ".webp"),
    "video/mp4": ("video", 50 * 1024 * 1024, ".mp4"),
}


def upload_meetup_media(
    db: Session,
    meetup_id: int,
    current_user_id: int,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    caption: str | None,
) -> MeetupMedia:
    meetup = _load_and_authorize_meetup(db, meetup_id, current_user_id, require_creator=True)
    if content_type not in _MEDIA_RULES:
        raise HTTPException(status_code=415, detail="unsupported media type")
    media_type, max_size, ext = _MEDIA_RULES[content_type]
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=413, detail="media too large")

    safe_caption = html.escape(caption) if caption else None
    next_seq = db.query(MeetupMedia).filter(MeetupMedia.meetup_id == meetup.id).count()
    media = MeetupMedia(
        meetup_id=meetup.id,
        uploader_id=current_user_id,
        type=media_type,
        file_id="pending",
        caption=safe_caption,
        seq=next_seq,
    )
    db.add(media)
    db.flush()
    try:
        file_id = _storage.upload(file_bytes, f"meetup-{meetup.id}-media-{media.id}{ext}")
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="media upload failed")
    media.file_id = file_id
    db.commit()
    db.refresh(media)
    return media


def delete_meetup_media(db: Session, meetup_id: int, media_id: int, current_user_id: int) -> None:
    media = db.query(MeetupMedia).filter(MeetupMedia.id == media_id).first()
    if media is None or media.meetup_id != meetup_id:
        raise HTTPException(status_code=404, detail="media not found")
    meetup = _load_and_authorize_meetup(db, meetup_id, current_user_id)
    if media.uploader_id != current_user_id and meetup.creator_id != current_user_id:
        raise HTTPException(status_code=403, detail="not allowed")

    file_id = media.file_id
    db.delete(media)
    db.commit()
    try:
        _storage.delete(file_id)
    except Exception:
        logger.warning("meetup media storage delete failed file_id=%s", file_id, exc_info=True)
```

- [ ] **Step 6: Make draft deletion clean media storage**

In `app/meetup/service.py`, add imports near the top:

```python
import logging

from app.storage.local import LocalStorage

logger = logging.getLogger(__name__)
```

Append these helpers:

```python
def _delete_meetup_row_and_collect_files(db: Session, meetup_id: int) -> list[str]:
    file_ids = [row.file_id for row in db.query(MeetupMedia).filter(MeetupMedia.meetup_id == meetup_id).all()]
    meetup = db.query(Meetup).filter(Meetup.id == meetup_id).first()
    if meetup is None:
        return file_ids
    db.delete(meetup)
    return file_ids


def _cleanup_meetup_storage(file_ids: list[str]) -> None:
    storage = LocalStorage()
    for file_id in file_ids:
        try:
            storage.delete(file_id)
        except Exception:
            logger.warning("meetup delete storage cleanup failed file_id=%s", file_id, exc_info=True)
```

Replace `delete_draft_meetup` with:

```python
def delete_draft_meetup(db: Session, meetup_id: int, current_user_id: int) -> None:
    meetup = _load_and_authorize_meetup(
        db, meetup_id, current_user_id, require_creator=True, require_status=["DRAFT"]
    )
    file_ids = _delete_meetup_row_and_collect_files(db, meetup.id)
    db.commit()
    _cleanup_meetup_storage(file_ids)
```

- [ ] **Step 7: Add router endpoints**

In `app/meetup/router.py`, add import:

```python
from fastapi import File, Form, UploadFile
from app.meetup import media_service
```

Append endpoints:

```python
@router.post("/{meetup_id}/media", response_model=schemas.MeetupMediaResponse)
def upload_media(
    meetup_id: int,
    caption: str | None = Form(None),
    file: UploadFile = File(...),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file_bytes = file.file.read()
    return media_service.upload_meetup_media(
        db,
        meetup_id=meetup_id,
        current_user_id=current_user_id,
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        file_bytes=file_bytes,
        caption=caption,
    )


@router.delete("/{meetup_id}/media/{media_id}", status_code=204)
def delete_media(
    meetup_id: int,
    media_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    media_service.delete_meetup_media(db, meetup_id, media_id, current_user_id)
```

- [ ] **Step 8: Run green tests**

```bash
python3 -m pytest tests/test_meetup_media.py tests/test_meetup_api.py -q
```

Expected: PASS.

- [ ] **Step 9: Self-review**

- [ ] Spec coverage: MIME whitelist, size limits, caption escape, DB-first upload, DB-first delete, draft-delete storage cleanup, and meetup_id path check are covered.
- [ ] Type consistency: response uses `file_id`, not URL.
- [ ] Placeholder scan: grep this task and touched files for unfinished marker words before commit.
- [ ] Architecture: `media_service.py` imports `meetup.service`, storage, and models only; `service.py` owns draft-delete cleanup so Task 6 leaves no orphan storage gap.

Run:

```bash
grep -rn "file_url\\|media_url\\|image/svg\\|html.escape\\|pending" app/meetup tests/test_meetup_media.py
python3 -m pytest tests/test_meetup_media.py -q
```

- [ ] **Step 10: Commit**

```bash
git add app/meetup/media_service.py app/meetup/service.py app/meetup/router.py app/meetup/schemas.py tests/test_meetup_media.py
git commit -F - <<'MSG'
feat(meetup): task 6 add meetup media handling

Add creator-only media upload and delete with MIME limits, caption escaping, meetup_id path checks, and storage cleanup.
Keep database records as the source of truth for media existence.
MSG
```
