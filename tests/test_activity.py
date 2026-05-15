"""
Activity 模块测试。

覆盖功率区间、轨迹简化、上传接口、查询/删除接口。
GPX 解析器的测试已迁移到 test_parsing.py（40 个用例），这里不再重复。

注意事项：
- 上传接口测试需要 mock 文件存储（_storage）和 Redis 队列（_queue）
- fixture GPX 文件在 tests/fixtures/ 目录下
"""

import math
import os
from datetime import datetime, timezone

import pytest

from app.parsing.gpx_parser import GPXParser
from app.activity.power_zones import calculate_power_zones
from app.activity.simplify import simplify_track
from app.activity import service
from app.activity.models import ActivityPrivacy

# fixture 文件路径
_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(filename: str) -> bytes:
    """读取 tests/fixtures/ 下的测试文件"""
    with open(os.path.join(_FIXTURES_DIR, filename), "rb") as f:
        return f.read()


# ==================== 功率区间 ====================

def _parse_fixture_trackpoints_as_dicts(filename: str) -> list[dict]:
    """用 v2 解析器解析 fixture，将 Trackpoint 转为 dict 格式供 power_zones 使用"""
    content = _read_fixture(filename)
    result = GPXParser().parse(content)
    return [{"power": tp.power, "time": tp.time, "hr": tp.hr, "cad": tp.cad}
            for tp in result.trackpoints]

def test_10_power_zones_normal():
    """用例 10：FTP=235, 有功率数据 → 6 个区间 percent 之和接近 100"""
    tp_dicts = _parse_fixture_trackpoints_as_dicts("test_ride.gpx")
    zones = calculate_power_zones(tp_dicts, ftp=235)

    assert zones is not None
    assert len(zones) == 6
    total_pct = sum(z["percent"] for z in zones)
    # 四舍五入可能导致 ±1 的偏差
    assert 98 <= total_pct <= 102
    assert zones[0]["zone"] == "Z1"
    assert zones[5]["zone"] == "Z6"


def test_11_power_zones_no_power():
    """用例 11：FTP=235, 无功率数据 → 返回 None"""
    tp_dicts = _parse_fixture_trackpoints_as_dicts("test_ride_no_power.gpx")
    zones = calculate_power_zones(tp_dicts, ftp=235)
    assert zones is None


# ==================== 12-14：轨迹简化 ====================

def test_13_simplify_large():
    """用例 13：10000 点 → 输出 640-960 点"""
    # 构造 10000 个模拟轨迹点
    points = [
        {"lat": 37.0 + i * 0.0001 + math.sin(i / 50) * 0.01,
         "lon": 112.0 + i * 0.0001,
         "ele": 800.0 + math.sin(i / 30) * 50}
        for i in range(10000)
    ]
    result = simplify_track(points, target_count=800)
    assert 640 <= len(result) <= 960


def test_14_simplify_small():
    """用例 14：100 点 → 原样返回"""
    points = [{"lat": 37.0 + i * 0.001, "lon": 112.0, "ele": 800.0} for i in range(100)]
    result = simplify_track(points, target_count=800)
    assert len(result) == 100


def test_15_simplify_keep_endpoints():
    """用例 15：首尾点保留"""
    points = [
        {"lat": 37.0 + math.sin(i / 10) * 0.1, "lon": 112.0 + i * 0.001, "ele": 800.0}
        for i in range(5000)
    ]
    result = simplify_track(points, target_count=500)
    assert result[0]["lat"] == points[0]["lat"]
    assert result[0]["lon"] == points[0]["lon"]
    assert result[-1]["lat"] == points[-1]["lat"]
    assert result[-1]["lon"] == points[-1]["lon"]


# ==================== 16-19：上传接口 ====================

def test_16_upload_valid_gpx(client, auth_header, monkeypatch):
    """用例 16：合法 .gpx → 200 + activity_id + status=pending"""
    # Mock 存储和队列，不需要真实文件系统和 Redis
    monkeypatch.setattr("app.activity.service._storage.upload", lambda b, f: "202604/test.gpx")
    monkeypatch.setattr("app.activity.service._queue.enqueue", lambda *a, **kw: None)

    gpx_content = _read_fixture("test_ride.gpx")
    resp = client.post(
        "/api/activities/upload",
        files={"file": ("ride.gpx", gpx_content, "application/octet-stream")},
        headers=auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "activity_id" in data
    assert data["status"] == "pending"


def test_17_upload_wrong_extension(client, auth_header):
    """用例 17：.txt → 400"""
    resp = client.post(
        "/api/activities/upload",
        files={"file": ("ride.txt", b"some content", "text/plain")},
        headers=auth_header,
    )
    assert resp.status_code == 400
    assert "只接受" in resp.json()["detail"]


def test_18_upload_fake_gpx(client, auth_header):
    """用例 18：PDF 改后缀 .gpx → 400（256 字节校验）"""
    fake_content = _read_fixture("fake.gpx")
    resp = client.post(
        "/api/activities/upload",
        files={"file": ("ride.gpx", fake_content, "application/octet-stream")},
        headers=auth_header,
    )
    assert resp.status_code == 400
    assert "GPX格式" in resp.json()["detail"]


def test_19_upload_no_auth(client):
    """用例 19：未登录 → 401"""
    gpx_content = _read_fixture("test_ride.gpx")
    resp = client.post(
        "/api/activities/upload",
        files={"file": ("ride.gpx", gpx_content, "application/octet-stream")},
    )
    assert resp.status_code == 401


# ==================== 22-29：查询/删除接口 ====================

def _create_test_activity(db, user_id: int, title: str = "测试骑行", status: str = "completed"):
    """辅助函数：在简化版 activities 表中插入一条测试记录"""
    from tests.conftest import _activities_table
    db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title=title,
            status=status,
            file_url="202604/test.gpx",
            distance=50000.0,
            duration=3600,
            elevation_gain=500.0,
            started_at=datetime(2026, 4, 7, 6, 0, 0, tzinfo=timezone.utc),  # task-0.1 双审 C2 修复 naive→aware
        )
    )
    db.commit()
    # 返回刚插入的记录 ID
    row = db.execute(_activities_table.select().order_by(_activities_table.c.id.desc())).first()
    return row.id


def test_22_list_activities(client, auth_header, db, test_user):
    """用例 22：活动列表 → 200 + 分页"""
    _create_test_activity(db, test_user.id, "骑行1")
    _create_test_activity(db, test_user.id, "骑行2")

    resp = client.get("/api/activities?page=1&page_size=10", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["page"] == 1
    # 不应包含 simplified_track
    assert "simplified_track" not in data["items"][0]
    # 距离应该是公里（50000m → 50.0km）
    assert data["items"][0]["distance"] == 50.0


def test_23_activity_detail(client, auth_header, db, test_user):
    """用例 23：活动详情 → 200"""
    aid = _create_test_activity(db, test_user.id)

    resp = client.get(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == aid
    assert data["distance"] == 50.0  # 米→公里
    # 详情应包含这些字段（值可能为 None，但 key 必须在）
    assert "simplified_track" in data
    assert "splits" in data
    assert "power_zones" in data


def test_24_detail_other_user_default_public(client, auth_header, db, test_user):
    """用例 24（task-4.1 更新）：查别人活动默认可见 → 200。

    task-4.1 改了产品契约：activity 默认公开，他人能看到完整数据。
    若 owner 设私密 → 见 test_activity_privacy_private_blocks_others。
    """
    # 创建另一个用户的活动
    from app.user.models import User
    other_user = User(openid="other_user_openid")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    aid = _create_test_activity(db, other_user.id)

    resp = client.get(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 200


def test_activity_privacy_default_public(db, test_user):
    """老骑行没有 privacy 行时，别人仍按默认公开可见。"""
    aid = _create_test_activity(db, test_user.id)
    activity = service.get_activity_detail(db, aid, user_id=999999)
    assert activity.id == aid


def test_activity_privacy_private_blocks_others(client, auth_header, db):
    """私密骑行对他人表现成 404，像这条记录根本不存在。"""
    from app.user.models import User

    other_user = User(openid="privacy_owner")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    aid = _create_test_activity(db, other_user.id)
    db.add(ActivityPrivacy(activity_id=aid, visibility="private"))
    db.commit()

    resp = client.get(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 404


def test_activity_privacy_self_always_visible(client, auth_header, db, test_user):
    """本人看自己的私密骑行仍返回完整详情。"""
    aid = _create_test_activity(db, test_user.id)
    db.add(ActivityPrivacy(activity_id=aid, visibility="private"))
    db.commit()

    resp = client.get(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 200


def test_old_activities_default_public(client, auth_header, db):
    """没有 privacy 行的老数据，对其他登录用户继续默认公开。"""
    from app.user.models import User

    owner = User(openid="legacy_public_owner")
    db.add(owner)
    db.commit()
    db.refresh(owner)
    aid = _create_test_activity(db, owner.id)

    resp = client.get(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 200


def test_25_delete_activity(client, auth_header, db, test_user, monkeypatch):
    """用例 25：删除活动 → 204"""
    aid = _create_test_activity(db, test_user.id)
    monkeypatch.setattr("app.activity.service._storage.delete", lambda f: True)

    resp = client.delete(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 204

    # 确认已删除
    resp2 = client.get(f"/api/activities/{aid}", headers=auth_header)
    assert resp2.status_code == 404


def test_26_delete_other_user(client, auth_header, db, test_user):
    """用例 26：删别人活动 → 403"""
    from app.user.models import User
    other_user = User(openid="other_user_delete")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    aid = _create_test_activity(db, other_user.id)

    resp = client.delete(f"/api/activities/{aid}", headers=auth_header)
    assert resp.status_code == 403


def test_27_update_title(client, auth_header, db, test_user):
    """用例 27：编辑活动标题 → 200，title 更新"""
    aid = _create_test_activity(db, test_user.id, title="旧标题")

    resp = client.patch(
        f"/api/activities/{aid}",
        json={"title": "新标题"},
        headers=auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "新标题"


def test_28_update_other_user(client, auth_header, db, test_user):
    """用例 28：编辑别人的活动 → 403"""
    from app.user.models import User
    other_user = User(openid="other_user_update")
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    aid = _create_test_activity(db, other_user.id)

    resp = client.patch(
        f"/api/activities/{aid}",
        json={"title": "偷改"},
        headers=auth_header,
    )
    assert resp.status_code == 403


def test_edit_delete_still_owner_only(client, auth_header, db, test_user, monkeypatch):
    """就算活动是公开的，编辑和删除也仍像房门钥匙一样只认主人。"""
    from app.user.models import User

    owner = User(openid="public_owner")
    db.add(owner)
    db.commit()
    db.refresh(owner)
    aid = _create_test_activity(db, owner.id)
    db.add(ActivityPrivacy(activity_id=aid, visibility="public"))
    db.commit()
    monkeypatch.setattr("app.activity.service._storage.delete", lambda f: True)

    patch_resp = client.patch(
        f"/api/activities/{aid}",
        json={"title": "偷改"},
        headers=auth_header,
    )
    delete_resp = client.delete(f"/api/activities/{aid}", headers=auth_header)

    assert patch_resp.status_code == 403
    assert delete_resp.status_code == 403


def test_29_update_title_too_long(client, auth_header, db, test_user):
    """用例 29：标题超 128 字符 → 422"""
    aid = _create_test_activity(db, test_user.id)

    resp = client.patch(
        f"/api/activities/{aid}",
        json={"title": "x" * 129},
        headers=auth_header,
    )
    assert resp.status_code == 422


# ==================== 30-31：轨迹点数量校验 ====================

def test_validate_gpx_rejects_too_many_trackpoints():
    """轨迹点超过 50000 个的 GPX 应被拒绝"""
    header = b'<?xml version="1.0"?><gpx><trk><trkseg>'
    point = b'<trkpt lat="0" lon="0"></trkpt>'
    body = point * 50001
    footer = b'</trkseg></trk></gpx>'
    big_gpx = header + body + footer

    with pytest.raises(ValueError, match="轨迹点过多"):
        service.validate_ride_file("test.gpx", big_gpx)


def test_validate_gpx_accepts_normal_trackpoints():
    """正常数量的轨迹点应通过校验"""
    header = b'<?xml version="1.0"?><gpx><trk><trkseg>'
    point = b'<trkpt lat="0" lon="0"></trkpt>'
    body = point * 100
    footer = b'</trkseg></trk></gpx>'
    normal_gpx = header + body + footer

    service.validate_ride_file("test.gpx", normal_gpx)
