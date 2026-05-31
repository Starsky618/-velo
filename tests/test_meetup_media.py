"""约骑模块 Task 6：媒体上传和删除测试。"""

from datetime import datetime, timedelta, timezone

from app.meetup import service
from app.meetup.models import MeetupMedia
from app.segment.models import Segment
from app.user.models import User


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
    return service.create_meetup(
        db,
        owner_id,
        segment.id,
        None,
        start,
        start + timedelta(hours=2),
        "集合点",
        "cruise",
        4,
        None,
    )


def _open_meetup(db, owner_id):
    draft = _draft(db, owner_id)
    return service.publish_meetup(db, draft.id, owner_id)


def _other_user(db, openid="meetup-media-other"):
    user = User(openid=openid, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_upload_media_creator_only_and_escapes_caption(client, db, auth_header, test_user, monkeypatch):
    meetup = _draft(db, test_user.id)

    class FakeStorage:
        def upload(self, file_bytes, filename):
            assert file_bytes == b"jpg-bytes"
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
    assert body["type"] == "image"


def test_upload_media_rejects_non_creator(client, db, admin_header, test_user):
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


def test_upload_media_rejects_oversized_image(client, db, auth_header, test_user):
    meetup = _draft(db, test_user.id)
    too_large = b"x" * (5 * 1024 * 1024 + 1)

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.jpg", too_large, "image/jpeg")},
        headers=auth_header,
    )

    assert res.status_code == 413


def test_upload_media_rejects_long_caption_before_storage(client, db, auth_header, test_user, monkeypatch):
    meetup = _draft(db, test_user.id)
    called = []

    class FakeStorage:
        def upload(self, file_bytes, filename):
            called.append(filename)
            return "202605/too-long.jpg"

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        data={"caption": "x" * 129},
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=auth_header,
    )

    assert res.status_code == 422
    assert called == []


def test_upload_storage_failure_rolls_back_db_record(client, db, auth_header, test_user, monkeypatch):
    meetup = _draft(db, test_user.id)

    class FakeStorage:
        def upload(self, file_bytes, filename):
            raise OSError("disk full")

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=auth_header,
    )

    assert res.status_code == 500
    assert db.query(MeetupMedia).filter_by(meetup_id=meetup.id).count() == 0


def test_upload_cancelled_meetup_keeps_creator_only_policy(client, db, auth_header, test_user, monkeypatch):
    meetup = _open_meetup(db, test_user.id)
    service.cancel_meetup(db, meetup.id, test_user.id)

    class FakeStorage:
        def upload(self, file_bytes, filename):
            return "202605/cancelled.jpg"

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=auth_header,
    )

    assert res.status_code == 200
    assert res.json()["file_id"] == "202605/cancelled.jpg"


def test_uploaded_media_becomes_first_media_in_list_and_detail(client, db, auth_header, test_user, monkeypatch):
    meetup = _open_meetup(db, test_user.id)

    class FakeStorage:
        def upload(self, file_bytes, filename):
            return "202605/first.jpg"

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())
    upload_res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=auth_header,
    )
    assert upload_res.status_code == 200

    list_res = client.get("/api/meetups", params={"status": "OPEN"})
    detail_res = client.get(f"/api/meetups/{meetup.id}")

    assert list_res.status_code == 200
    assert detail_res.status_code == 200
    assert list_res.json()["items"][0]["first_media_file_id"] == "202605/first.jpg"
    assert detail_res.json()["first_media_file_id"] == "202605/first.jpg"


def test_publish_response_keeps_first_media_after_draft_upload(client, db, auth_header, test_user, monkeypatch):
    meetup = _draft(db, test_user.id)

    class FakeStorage:
        def upload(self, file_bytes, filename):
            return "202605/draft-first.jpg"

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())
    upload_res = client.post(
        f"/api/meetups/{meetup.id}/media",
        files={"file": ("cover.jpg", b"jpg-bytes", "image/jpeg")},
        headers=auth_header,
    )
    assert upload_res.status_code == 200

    publish_res = client.post(f"/api/meetups/{meetup.id}/publish", headers=auth_header)

    assert publish_res.status_code == 200
    assert publish_res.json()["first_media_file_id"] == "202605/draft-first.jpg"


def test_delete_media_checks_path_meetup_id(client, db, auth_header, test_user):
    meetup = _draft(db, test_user.id)
    other_owner = _other_user(db)
    other = _draft(db, other_owner.id)
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
            assert db.query(MeetupMedia).filter_by(id=media.id).first() is None
            deleted.append(file_id)
            return True

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.delete(f"/api/meetups/{meetup.id}/media/{media.id}", headers=auth_header)

    assert res.status_code == 204
    assert db.query(MeetupMedia).filter_by(id=media.id).first() is None
    assert deleted == ["202605/a.jpg"]


def test_delete_media_allows_creator_or_uploader(client, db, auth_header, test_user, admin_user, monkeypatch):
    meetup = _draft(db, test_user.id)
    media = MeetupMedia(meetup_id=meetup.id, uploader_id=admin_user.id, type="image", file_id="202605/uploader.jpg", seq=0)
    db.add(media)
    db.commit()
    db.refresh(media)

    class FakeStorage:
        def delete(self, file_id):
            return True

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.delete(f"/api/meetups/{meetup.id}/media/{media.id}", headers=auth_header)

    assert res.status_code == 204


def test_delete_media_allows_uploader(client, db, admin_header, test_user, admin_user, monkeypatch):
    meetup = _draft(db, test_user.id)
    media = MeetupMedia(meetup_id=meetup.id, uploader_id=admin_user.id, type="image", file_id="202605/uploader.jpg", seq=0)
    db.add(media)
    db.commit()
    db.refresh(media)

    class FakeStorage:
        def delete(self, file_id):
            return True

    monkeypatch.setattr("app.meetup.media_service._storage", FakeStorage())

    res = client.delete(f"/api/meetups/{meetup.id}/media/{media.id}", headers=admin_header)

    assert res.status_code == 204


def test_delete_draft_meetup_cleans_media_storage(db, test_user, monkeypatch):
    draft = _draft(db, test_user.id)
    media = MeetupMedia(meetup_id=draft.id, uploader_id=test_user.id, type="image", file_id="202605/draft.jpg", seq=0)
    db.add(media)
    db.commit()
    media_id = media.id
    deleted = []

    class FakeStorage:
        def delete(self, file_id):
            deleted.append(file_id)

    monkeypatch.setattr("app.meetup.service._storage", FakeStorage())

    service.delete_draft_meetup(db, draft.id, test_user.id)

    assert db.query(MeetupMedia).filter_by(id=media_id).first() is None
    assert deleted == ["202605/draft.jpg"]
