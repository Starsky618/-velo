"""约骑模块 Task 4：HTTP API 测试。"""

from datetime import datetime, timedelta, timezone

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
