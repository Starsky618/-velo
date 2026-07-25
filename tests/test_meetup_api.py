"""约骑模块 Task 4：HTTP API 测试。"""

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.route_book.tencent_direction import TencentMapError
from sqlalchemy import text

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


def test_meetup_create_prototype_columns_are_declared_in_model_and_test_table(db):
    expected = {
        "supply_point",
        "audience_tags",
        "visibility",
        "eligibility_note",
        "safety_note",
        "share_token",
    }

    model_columns = set(Meetup.__table__.columns.keys())
    sqlite_columns = {row[1] for row in db.execute(text("PRAGMA table_info(meetups)")).fetchall()}

    assert expected <= model_columns
    assert expected <= sqlite_columns


def test_create_patch_and_list_return_custom_power_speed_hints(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["recommended_power_label"] = "FTP 180-220W"
    payload["average_speed_range"] = "24-27 km/h"

    create_res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert create_res.status_code == 200
    meetup_id = create_res.json()["id"]
    assert create_res.json()["recommended_power_label"] == "FTP 180-220W"
    assert create_res.json()["average_speed_range"] == "24-27 km/h"

    patch_res = client.patch(
        f"/api/meetups/{meetup_id}",
        json={
            "recommended_power_label": "FTP 200W 左右",
            "average_speed_range": "26 km/h 左右",
        },
        headers=auth_header,
    )

    assert patch_res.status_code == 200
    assert patch_res.json()["recommended_power_label"] == "FTP 200W 左右"
    assert patch_res.json()["average_speed_range"] == "26 km/h 左右"

    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    detail_res = client.get(f"/api/meetups/{meetup_id}")
    list_res = client.get("/api/meetups?status=OPEN")

    assert detail_res.json()["recommended_power_label"] == "FTP 200W 左右"
    assert detail_res.json()["average_speed_range"] == "26 km/h 左右"
    item = next(item for item in list_res.json()["items"] if item["id"] == meetup_id)
    assert item["recommended_power_label"] == "FTP 200W 左右"
    assert item["average_speed_range"] == "26 km/h 左右"


def test_meetup_favorite_places_are_user_scoped_and_sort_by_recent_use(client, db, auth_header, monkeypatch):
    now = datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: now)
    first = client.post(
        "/api/meetups/favorite-places",
        json={
            "name": "晋阳湖东门",
            "address": "太原市晋源区",
            "latitude": 37.715,
            "longitude": 112.476,
        },
        headers=auth_header,
    )
    assert first.status_code == 200

    monkeypatch.setattr("app.meetup.service._now_utc", lambda: now + timedelta(minutes=10))
    second = client.post(
        "/api/meetups/favorite-places",
        json={
            "name": "太原植物园北门",
            "address": "晋源区太古路",
            "latitude": 37.728,
            "longitude": 112.437,
        },
        headers=auth_header,
    )
    assert second.status_code == 200

    monkeypatch.setattr("app.meetup.service._now_utc", lambda: now + timedelta(minutes=20))
    repeat = client.post(
        "/api/meetups/favorite-places",
        json={
            "name": "晋阳湖东门",
            "address": "太原市晋源区东门",
            "latitude": 37.716,
            "longitude": 112.477,
        },
        headers=auth_header,
    )
    assert repeat.status_code == 200
    assert repeat.json()["usage_count"] == 2
    assert repeat.json()["address"] == "太原市晋源区东门"

    mine = client.get("/api/meetups/favorite-places", headers=auth_header)
    assert mine.status_code == 200
    assert [item["name"] for item in mine.json()] == ["晋阳湖东门", "太原植物园北门"]

    other_header = _auth_header_for(db, "favorite-place-other")
    assert client.get("/api/meetups/favorite-places", headers=other_header).json() == []
    assert client.delete(f"/api/meetups/favorite-places/{first.json()['id']}", headers=other_header).status_code == 404

    delete_res = client.delete(f"/api/meetups/favorite-places/{first.json()['id']}", headers=auth_header)
    assert delete_res.status_code == 204
    remaining = client.get("/api/meetups/favorite-places", headers=auth_header).json()
    assert [item["name"] for item in remaining] == ["太原植物园北门"]


def test_meetup_favorite_place_converts_gcj02_to_wgs84(client, auth_header):
    from app.segment.coord_convert import gcj02_to_wgs84

    gcj_lat = 37.87
    gcj_lon = 112.55
    expected_lat, expected_lon = gcj02_to_wgs84(gcj_lat, gcj_lon)

    res = client.post(
        "/api/meetups/favorite-places",
        json={
            "name": "微信地图手动点",
            "address": "太原市",
            "latitude": gcj_lat,
            "longitude": gcj_lon,
            "coordinate_system": "gcj02",
        },
        headers=auth_header,
    )

    assert res.status_code == 200
    assert res.json()["latitude"] == expected_lat
    assert res.json()["longitude"] == expected_lon
    assert res.json()["latitude"] != gcj_lat
    assert res.json()["longitude"] != gcj_lon


def test_meetup_place_suggestions_applies_user_rate_limit(client, auth_header, test_user, monkeypatch):
    calls = []

    def fake_rate_limit(user_id, key_prefix, limit, window_sec):
        calls.append((user_id, key_prefix, limit, window_sec))

    monkeypatch.setattr("app.meetup.router.check_rate_limit_by_user", fake_rate_limit)
    monkeypatch.setattr("app.route_book.tencent_place.suggest_places", lambda keyword, region="太原": [])

    res = client.get("/api/meetups/place-suggestions", params={"keyword": "晋祠"}, headers=auth_header)

    assert res.status_code == 200
    # 实时联想一次输入会防抖出多次请求，额度比旧单次搜索宽（60 次/5 分钟）
    assert calls == [(test_user.id, "meetup-place-suggest", 60, 300)]


def test_meetup_place_suggestions_wraps_tencent_list_without_secret(client, auth_header, monkeypatch):
    captured = {}

    def fake_suggest_places(keyword, region="太原"):
        captured["keyword"] = keyword
        captured["region"] = region
        return [
            {
                "keyword": keyword,
                "title": "晋祠公园东门",
                "address": "太原市晋源区",
                "lat": 37.708,
                "lon": 112.438,
                "source": "tencent_suggestion",
                "provider_poi_id": "poi-jinci-east",
                "category": "旅游景点:公园",
                "category_code": "110101",
                "type": "0",
                "adcode": "140110",
                "province": "山西省",
                "city": "太原市",
                "district": "晋源区",
                "gcj_lat": 37.7086,
                "gcj_lon": 112.4444,
            },
            {
                "keyword": keyword,
                "title": "晋祠博物馆",
                "address": "太原市晋源区晋祠镇",
                "lat": 37.703,
                "lon": 112.435,
                "source": "tencent_suggestion",
            },
        ]

    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "secret-sk")
    monkeypatch.setattr("app.route_book.tencent_place.suggest_places", fake_suggest_places)

    res = client.get(
        "/api/meetups/place-suggestions",
        params={"keyword": " 晋祠 ", "region": " 太原 "},
        headers=auth_header,
    )

    assert res.status_code == 200
    assert captured == {"keyword": "晋祠", "region": "太原"}
    body = res.json()
    assert [item["title"] for item in body] == ["晋祠公园东门", "晋祠博物馆"]
    assert body[0]["latitude"] == 37.708
    assert body[0]["longitude"] == 112.438
    assert body[0]["provider_poi_id"] == "poi-jinci-east"
    assert body[0]["category_code"] == "110101"
    assert body[0]["district"] == "晋源区"
    assert body[0]["gcj_lat"] == 37.7086
    assert body[0]["gcj_lon"] == 112.4444
    assert "secret-sk" not in res.text


def test_meetup_place_suggestions_returns_empty_list_for_no_result(client, auth_header, monkeypatch):
    monkeypatch.setattr("app.route_book.tencent_place.suggest_places", lambda keyword, region="太原": [])

    res = client.get("/api/meetups/place-suggestions", params={"keyword": "不存在地点"}, headers=auth_header)

    assert res.status_code == 200
    assert res.json() == []


def test_meetup_place_suggestions_maps_tencent_failure_without_secret(client, auth_header, monkeypatch):
    def boom(keyword, region="太原"):
        raise TencentMapError("腾讯地点联想请求失败：HTTP 403")

    monkeypatch.setattr(settings, "TENCENT_MAP_SK", "secret-sk")
    monkeypatch.setattr("app.route_book.tencent_place.suggest_places", boom)

    res = client.get("/api/meetups/place-suggestions", params={"keyword": "晋祠"}, headers=auth_header)

    assert res.status_code == 422
    assert "腾讯地点联想请求失败" in res.text
    assert "secret-sk" not in res.text


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


def test_create_returns_social_fields_and_creator_only_share_token(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload.update({
        "supply_point": "天龙山景区口",
        "audience_tags": ["climb_steady", "female_friendly", "climb_steady"],
        "visibility": "public",
        "eligibility_note": "报名需有 5 次骑行记录",
        "safety_note": "头盔必戴 · 遵守交规 · 量力而行",
    })

    create_res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert create_res.status_code == 200
    body = create_res.json()
    assert body["supply_point"] == "天龙山景区口"
    assert body["audience_tags"] == ["climb_steady", "female_friendly"]
    assert body["visibility"] == "public"
    assert body["eligibility_note"] == "报名需有 5 次骑行记录"
    assert body["safety_note"] == "头盔必戴 · 遵守交规 · 量力而行"
    assert isinstance(body["share_token"], str)
    assert len(body["share_token"]) >= 32

    other_header = _auth_header_for(db, "social-fields-other")
    detail_res = client.get(f"/api/meetups/{body['id']}", headers=other_header)
    assert detail_res.status_code == 200
    assert detail_res.json()["share_token"] is None


def test_create_accepts_all_allowed_audience_tags(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["audience_tags"] = [
        "climb_steady",
        "high_intensity",
        "leisure",
        "photography",
        "female_friendly",
        "newbie_caution",
    ]

    create_res = client.post("/api/meetups", json=payload, headers=auth_header)

    assert create_res.status_code == 200
    assert len(create_res.json()["audience_tags"]) == 6


def test_patch_updates_social_fields_instead_of_silently_dropping_them(client, db, auth_header):
    segment = _segment(db)
    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]

    patch_res = client.patch(
        f"/api/meetups/{meetup_id}",
        json={
            "supply_point": "晋祠补水",
            "audience_tags": ["photography"],
            "visibility": "invite_only",
            "eligibility_note": "能稳定骑完 60km",
            "safety_note": "山路多弯 · 控制下坡车速 · 保持车距",
        },
        headers=auth_header,
    )

    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["supply_point"] == "晋祠补水"
    assert body["audience_tags"] == ["photography"]
    assert body["visibility"] == "invite_only"
    assert body["eligibility_note"] == "能稳定骑完 60km"
    assert body["safety_note"] == "山路多弯 · 控制下坡车速 · 保持车距"


def test_patch_null_audience_tags_clears_to_empty_list(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["audience_tags"] = ["climb_steady", "photography"]
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]

    patch_res = client.patch(
        f"/api/meetups/{meetup_id}",
        json={"audience_tags": None},
        headers=auth_header,
    )
    detail_res = client.get(f"/api/meetups/{meetup_id}", headers=auth_header)

    assert patch_res.status_code == 200
    assert detail_res.status_code == 200
    assert detail_res.json()["audience_tags"] == []
    db.expire_all()
    assert db.query(Meetup).filter(Meetup.id == meetup_id).first().audience_tags == []


def test_public_list_hides_invite_only_but_mine_keeps_owner_items(client, db, auth_header):
    seg_public = _segment(db)
    public_id = client.post("/api/meetups", json=_payload(seg_public.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{public_id}/publish", headers=auth_header)

    seg_private = _segment(db)
    private_payload = _payload(seg_private.id)
    private_payload["visibility"] = "invite_only"
    private_id = client.post("/api/meetups", json=private_payload, headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{private_id}/publish", headers=auth_header)

    public_list = client.get("/api/meetups?status=OPEN")
    mine = client.get("/api/meetups/mine?role=created", headers=auth_header)

    public_ids = [item["id"] for item in public_list.json()["items"]]
    mine_ids = [item["id"] for item in mine.json()["items"]]
    assert public_id in public_ids
    assert private_id not in public_ids
    assert public_id in mine_ids
    assert private_id in mine_ids


def test_social_field_validation_and_share_token_forbid(client, db, auth_header):
    segment = _segment(db)
    bad_tag = _payload(segment.id)
    bad_tag["audience_tags"] = ["not_a_real_tag"]
    assert client.post("/api/meetups", json=bad_tag, headers=auth_header).status_code == 422

    too_long = _payload(segment.id)
    too_long["safety_note"] = "x" * 201
    assert client.post("/api/meetups", json=too_long, headers=auth_header).status_code == 422

    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]
    forbidden = client.patch(
        f"/api/meetups/{meetup_id}",
        json={"share_token": "frontend-must-not-send-this"},
        headers=auth_header,
    )
    assert forbidden.status_code == 422

    bad_patch_tag = client.patch(
        f"/api/meetups/{meetup_id}",
        json={"audience_tags": ["not_a_real_tag"]},
        headers=auth_header,
    )
    assert bad_patch_tag.status_code == 422


def test_invite_only_requires_token_for_detail_join_and_participants(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["visibility"] = "invite_only"
    create_res = client.post("/api/meetups", json=payload, headers=auth_header)
    meetup_id = create_res.json()["id"]
    token = create_res.json()["share_token"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    outsider = _auth_header_for(db, "invite-only-outsider")

    assert client.get(f"/api/meetups/{meetup_id}", headers=outsider).status_code == 404
    assert client.post(f"/api/meetups/{meetup_id}/join", headers=outsider).status_code == 404
    assert client.get(f"/api/meetups/{meetup_id}/participants", headers=outsider).status_code == 404

    assert client.get(f"/api/meetups/{meetup_id}?token={token}", headers=outsider).status_code == 200
    assert client.post(f"/api/meetups/{meetup_id}/join?token={token}", headers=outsider).status_code == 200
    assert client.get(f"/api/meetups/{meetup_id}/participants", headers=outsider).status_code == 200
    assert client.get(f"/api/meetups/{meetup_id}", headers=outsider).status_code == 200

    # /media 同样受私圈门禁：另一个全新外部用户不带 token → 404，带 token → 200
    fresh = _auth_header_for(db, "invite-only-media-outsider")
    assert client.get(f"/api/meetups/{meetup_id}/media", headers=fresh).status_code == 404
    assert client.get(f"/api/meetups/{meetup_id}/media?token={token}").status_code == 200

    # 参与者端点用 get_optional_user（C6 修 / 2026-06-13）：未登录受邀者（分享链接进来，
    # 无 JWT、只带 token）也要能看到"谁来了"——否则前端骑友列表静默消失。
    # 完全不带任何凭证 → 404（私圈门禁）；只带 token 不登录 → 200。
    assert client.get(f"/api/meetups/{meetup_id}/participants").status_code == 404
    assert client.get(f"/api/meetups/{meetup_id}/participants?token={token}").status_code == 200


def test_invite_only_creator_can_open_without_token(client, db, auth_header):
    segment = _segment(db)
    payload = _payload(segment.id)
    payload["visibility"] = "invite_only"
    create_res = client.post("/api/meetups", json=payload, headers=auth_header)
    meetup_id = create_res.json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    detail = client.get(f"/api/meetups/{meetup_id}", headers=auth_header)
    participants = client.get(f"/api/meetups/{meetup_id}/participants", headers=auth_header)

    assert detail.status_code == 200
    assert participants.status_code == 200


def test_public_meetup_participants_return_user_summary(client, db, auth_header, test_user):
    test_user.nickname = "组织者"
    test_user.avatar_url = "https://example.com/creator.png"
    segment = _segment(db)
    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    other_header = _auth_header_for(db, "participants-other")
    other = db.query(User).filter(User.openid == "participants-other").first()
    other.nickname = "阿泽"
    other.avatar_url = "https://example.com/aze.png"
    db.commit()
    client.post(f"/api/meetups/{meetup_id}/join", headers=other_header)

    res = client.get(f"/api/meetups/{meetup_id}/participants", headers=auth_header)

    assert res.status_code == 200
    assert res.json() == [
        {
            "user_id": test_user.id,
            "nickname": "组织者",
            "avatar_url": "https://example.com/creator.png",
            "is_creator": True,
            "joined_at": res.json()[0]["joined_at"],
        },
        {
            "user_id": other.id,
            "nickname": "阿泽",
            "avatar_url": "https://example.com/aze.png",
            "is_creator": False,
            "joined_at": res.json()[1]["joined_at"],
        },
    ]


def test_public_meetup_detail_and_join_do_not_need_token(client, db, auth_header):
    segment = _segment(db)
    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    other_header = _auth_header_for(db, "public-no-token-other")

    detail = client.get(f"/api/meetups/{meetup_id}", headers=other_header)
    join = client.post(f"/api/meetups/{meetup_id}/join", headers=other_header)

    assert detail.status_code == 200
    assert join.status_code == 200


def test_participants_optional_auth_and_missing_meetup_404(client, db, auth_header):
    # C6 修（2026-06-13）：参与者端点改 get_optional_user（私圈受邀游客带 token 也能看）。
    # 不存在的约骑：无论登录与否都 404（不再是"未登录 401"——鉴权下放给私圈门禁）。
    assert client.get("/api/meetups/999999/participants").status_code == 404
    assert client.get("/api/meetups/999999/participants", headers=auth_header).status_code == 404
    # public 约骑：未登录游客也能看参与者（约骑就是要被围观、被加入）
    segment = _segment(db)
    create_res = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header)
    meetup_id = create_res.json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    assert client.get(f"/api/meetups/{meetup_id}/participants").status_code == 200


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


def test_cancel_returns_410_after_cutoff(client, db, auth_header, monkeypatch):
    # 注意：Task6 起 publish 也走 30min 截止线，所以不能再"发布一个 20min 后的约骑"。
    # 正确做法：先发布一个足够远的约骑（发布时在截止线外），再把时间推进到截止窗内测 cancel→410。
    base = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: base)
    segment = _segment(db)
    start = base + timedelta(hours=1)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]
    assert client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header).status_code == 200

    # 时间推进到出发前 20 分钟（已过 30min 截止线）→ 取消应 410
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: start - timedelta(minutes=20))
    res = client.post(f"/api/meetups/{meetup_id}/cancel", headers=auth_header)

    assert res.status_code == 410


def test_detail_exposes_creator_and_joined_flags(client, db, auth_header):
    # 详情要告诉前端"当前用户是不是发起人/加没加入"，前端才能显示对的按钮（取消/退出/加入）
    segment = _segment(db)
    meetup_id = client.post("/api/meetups", json=_payload(segment.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)

    # 发起人视角：is_creator + has_joined（publish 自动把发起人占 1 个名额）都 True
    creator_view = client.get(f"/api/meetups/{meetup_id}", headers=auth_header).json()
    assert creator_view["is_creator"] is True
    assert creator_view["has_joined"] is True

    # 他人未加入视角：都 False
    other_header = _auth_header_for(db, "detail-flags-other")
    other_view = client.get(f"/api/meetups/{meetup_id}", headers=other_header).json()
    assert other_view["is_creator"] is False
    assert other_view["has_joined"] is False

    # 他人加入后再看：has_joined 变 True（前端据此显示"退出"而非"加入"）
    client.post(f"/api/meetups/{meetup_id}/join", headers=other_header)
    joined_view = client.get(f"/api/meetups/{meetup_id}", headers=other_header).json()
    assert joined_view["is_creator"] is False
    assert joined_view["has_joined"] is True

    # 游客（无 token）：详情仍可看（public 不变），标记都 False
    guest_res = client.get(f"/api/meetups/{meetup_id}")
    assert guest_res.status_code == 200
    assert guest_res.json()["is_creator"] is False
    assert guest_res.json()["has_joined"] is False


def test_my_meetups_created_and_joined(client, db, auth_header):
    # 个人页"我的约骑"：我发起的 vs 我加入的（后者排除自己发起的，避免重复）
    seg1 = _segment(db)
    mine_id = client.post("/api/meetups", json=_payload(seg1.id), headers=auth_header).json()["id"]
    client.post(f"/api/meetups/{mine_id}/publish", headers=auth_header)

    # 别人发起一个并发布，我去加入
    other_header = _auth_header_for(db, "mine-test-other")
    seg2 = _segment(db)
    other_id = client.post("/api/meetups", json=_payload(seg2.id), headers=other_header).json()["id"]
    client.post(f"/api/meetups/{other_id}/publish", headers=other_header)
    client.post(f"/api/meetups/{other_id}/join", headers=auth_header)

    # 我发起的：含自己创建的、不含别人的
    created = client.get("/api/meetups/mine?role=created", headers=auth_header).json()
    created_ids = [i["id"] for i in created["items"]]
    assert mine_id in created_ids
    assert other_id not in created_ids
    # created tab 每条都必须 is_creator=True，否则个人页卡片按钮状态全错（该显示"取消"却显示"加入"）。
    # 之前 /mine 没把 current_user_id 传给响应组装函数，这两个标记永远 False，是 Codex 异源审抓到的 bug。
    assert all(i["is_creator"] is True for i in created["items"])
    # 锁死契约：created tab 只置 is_creator，has_joined 保持 False（发起人 UI 靠 is_creator 驱动）。
    # 防止将来误把两个 flag 都置 True。
    assert all(i["has_joined"] is False for i in created["items"])

    # 我加入的：含我加入别人的、不含自己发起的（即使发起人 publish 自动占位也排除）
    joined = client.get("/api/meetups/mine?role=joined", headers=auth_header).json()
    joined_ids = [i["id"] for i in joined["items"]]
    assert other_id in joined_ids
    assert mine_id not in joined_ids
    # joined tab 每条都必须 has_joined=True（前端据此显示"退出"而非"加入"）
    assert all(i["has_joined"] is True for i in joined["items"])
    # 锁死契约：joined tab 只置 has_joined，is_creator 保持 False（这些都是别人发起的）
    assert all(i["is_creator"] is False for i in joined["items"])


def test_main_mounts_meetup_and_route_book_routers():
    from app.main import app

    paths = {getattr(route, "path", "") for route in app.router.routes}
    assert "/api/meetups" in paths
    assert "/api/route-books" in paths


def test_publish_rejects_draft_after_registration_cutoff(client, db, auth_header, monkeypatch):
    # 出发前 30 分钟截止线：进入截止窗的草稿不许发布（发了也没人能 join）→ 410
    fixed_now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: fixed_now)
    segment = _segment(db)
    start = fixed_now + timedelta(minutes=29)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]

    res = client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    assert res.status_code == 410


def test_publish_allows_draft_before_registration_cutoff(client, db, auth_header, monkeypatch):
    fixed_now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: fixed_now)
    segment = _segment(db)
    start = fixed_now + timedelta(minutes=31)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]

    res = client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    assert res.status_code == 200
    assert res.json()["status"] == "OPEN"


def test_publish_allows_draft_well_before_cutoff(client, db, auth_header, monkeypatch):
    # spec §8 边界三组的第三组：出发还远（now+2h）→ 发布 200
    fixed_now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("app.meetup.service._now_utc", lambda: fixed_now)
    segment = _segment(db)
    start = fixed_now + timedelta(hours=2)
    payload = _payload(segment.id)
    payload["start_time"] = start.isoformat()
    payload["estimated_end_time"] = (start + timedelta(hours=2)).isoformat()
    meetup_id = client.post("/api/meetups", json=payload, headers=auth_header).json()["id"]

    res = client.post(f"/api/meetups/{meetup_id}/publish", headers=auth_header)
    assert res.status_code == 200
