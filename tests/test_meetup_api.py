"""约骑模块 Task 4：HTTP API 测试。"""

from datetime import datetime, timedelta, timezone

from app.meetup.models import Meetup
from app.segment.models import Segment
from app.user.models import User
from app.user.service import create_token


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


def _auth_header_for(db, openid):
    user = User(openid=openid, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"Authorization": f"Bearer {create_token(user.id)}"}


def test_create_patch_publish_and_cancel_paths(client, db, auth_header):
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
    # 发布后创建者自动占 1 个名额，响应里人数应真实反映而不是 0
    assert publish_res.json()["participants_count"] == 1

    cancel_res = client.post(f"/api/meetups/{meetup_id}/cancel", headers=auth_header)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"
    # 取消不删参与记录，人数口径要和发布时一致
    assert cancel_res.json()["participants_count"] == 1


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
    # 列表页人数走 SQL 聚合，发布后应为 1
    assert list_res.json()["items"][0]["participants_count"] == 1
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == meetup_id
    # 详情页人数必须和列表页同口径，不能恒为 0（否则发布后详情显示"0 人参加"劝退用户）
    assert detail_res.json()["participants_count"] == 1
    # 距离必须是 km（DB 存米，API 出口转 km）：28000 米 → 28.0 km，不能漏转把米当 km 返回
    assert detail_res.json()["snapshot_distance"] == 28.0
    assert list_res.json()["items"][0]["snapshot_distance"] == 28.0


def test_create_rejects_extra_field(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["unexpected"] = "bad"

    res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert res.status_code == 422


def test_create_rejects_duplicate_draft(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    client.post("/api/meetups", json=payload, headers=auth_header)

    res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "draft_exists"


def test_detail_returns_404_for_missing_meetup(client):
    res = client.get("/api/meetups/999999")

    assert res.status_code == 404


def test_non_creator_cannot_patch_or_delete_draft(client, db, auth_header):
    segment = _segment(db)
    create_res = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header)
    meetup_id = create_res.json()["id"]
    other_header = _auth_header_for(db, "other_openid")

    patch_res = client.patch(f"/api/meetups/{meetup_id}", json={"meeting_point": "别人的集合点"}, headers=other_header)
    delete_res = client.delete(f"/api/meetups/{meetup_id}", headers=other_header)

    assert patch_res.status_code == 403
    assert delete_res.status_code == 403


def test_open_meetup_cannot_be_patched_or_deleted(client, db, auth_header):
    segment = _segment(db)
    create_res = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header)
    meetup_id = create_res.json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    patch_res = client.patch(f"/api/meetups/{meetup_id}", json={"meeting_point": "已发布后改点"}, headers=auth_header)
    delete_res = client.delete(f"/api/meetups/{meetup_id}", headers=auth_header)

    assert patch_res.status_code == 409
    assert delete_res.status_code == 409


def test_cancel_returns_410_after_cutoff(client, db, auth_header):
    segment = _segment(db)
    start = datetime.now(timezone.utc) + timedelta(minutes=20)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    create_res = client.post("/api/meetups", json=payload, headers=auth_header)
    meetup_id = create_res.json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    res = client.post(f"/api/meetups/{meetup_id}/cancel", headers=auth_header)

    assert res.status_code == 410


def test_main_mounts_meetup_and_route_book_routers():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.router.routes}
    assert "/api/meetups" in paths
    assert "/api/route-books" in paths
