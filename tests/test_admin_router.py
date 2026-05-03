"""admin router 骨架测试。"""

from datetime import datetime, timezone

import pytest

from app.segment.models import Segment


@pytest.fixture()
def segment_for_delete(db):
    """创建一个可删除的测试赛段。"""
    segment = Segment(
        name="待删除赛段",
        description="admin router delete test",
        distance=1200.0,
        elevation_gain=80.0,
        elevation_loss=20.0,
        avg_gradient=6.6,
        elevation_profile="[100, 180]",
        start_lat=37.87,
        start_lon=112.55,
        end_lat=37.88,
        end_lon=112.56,
        reference_line="SRID=4326;LINESTRING(112.55 37.87, 112.56 37.88)",
        match_tolerance=50.0,
        min_match_ratio=0.8,
        difficulty="medium",
        max_gradient=8.0,
        city="taiyuan",
        created_at=datetime.now(timezone.utc),
    )
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


def test_delete_segment_admin_only(client, auth_header, admin_header, segment_for_delete):
    """admin 新路径只允许管理员删除赛段，普通用户应被 403 拦下。"""
    res = client.delete(
        f"/api/admin/segments/{segment_for_delete.id}",
        headers=auth_header,
    )
    assert res.status_code == 403

    res = client.delete(
        f"/api/admin/segments/{segment_for_delete.id}",
        headers=admin_header,
    )
    assert res.status_code == 204


def test_delete_segment_admin_requires_auth(client, segment_for_delete):
    """没带 JWT 就像没出示门禁卡，请求应在身份层返回 401。"""
    res = client.delete(f"/api/admin/segments/{segment_for_delete.id}")

    assert res.status_code == 401


def test_delete_segment_admin_returns_404_for_missing_segment(client, admin_header):
    """管理员删除不存在的赛段时，应沿用 service 语义返回 404。"""
    res = client.delete("/api/admin/segments/999999", headers=admin_header)

    assert res.status_code == 404


def test_delete_segment_legacy_path_still_works(client, admin_header, segment_for_delete):
    """旧 DELETE /api/segments/{id} 保留兼容，管理员仍可删除。"""
    res = client.delete(
        f"/api/segments/{segment_for_delete.id}",
        headers=admin_header,
    )

    assert res.status_code == 204


def test_delete_segment_legacy_path_rejects_normal_user_403(
    client,
    auth_header,
    segment_for_delete,
):
    """旧路径虽然兼容，但普通用户仍应被 service 权限兜底拦下。"""
    res = client.delete(
        f"/api/segments/{segment_for_delete.id}",
        headers=auth_header,
    )

    assert res.status_code == 403
