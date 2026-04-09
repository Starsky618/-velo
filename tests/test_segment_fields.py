"""
赛段新增字段测试——验证 elevation_loss、avg_gradient、elevation_profile 的计算逻辑。

这个测试文件专门针对 Task 2 新增的三个字段：
- elevation_loss：累计下降（只算下坡，单位米）
- avg_gradient：平均坡度（爬升/水平距离 × 100，单位%）
- elevation_profile：海拔采样数组（约80个点，前端画海拔曲线用）

测试策略：先让测试跑红（字段不存在），再实现，最后跑绿——TDD 节奏。
"""

import pytest

from app.user.models import User
from app.user.service import create_token


@pytest.fixture()
def admin_user(db):
    """创建一个管理员测试用户。"""
    user = User(openid="admin_openid_999", is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_header(admin_user):
    """生成管理员 JWT 请求头。"""
    token = create_token(admin_user.id)
    return {"Authorization": f"Bearer {token}"}


def test_01_create_segment_new_fields(client, admin_header):
    """创建带海拔数据的赛段，验证新增字段正确计算。"""
    payload = {
        "name": "测试坡段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55, "ele": 800.0},
            {"lat": 37.871, "lon": 112.55, "ele": 850.0},
            {"lat": 37.872, "lon": 112.55, "ele": 900.0},
            {"lat": 37.873, "lon": 112.55, "ele": 880.0},
            {"lat": 37.874, "lon": 112.55, "ele": 850.0},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    assert resp.status_code == 200
    data = resp.json()

    # 上坡：800→850（+50）、850→900（+50）= 累计爬升 100m
    # 下坡：900→880（-20）、880→850（-30）= 累计下降 50m
    assert data["elevation_gain"] == 100.0
    assert data["elevation_loss"] == 50.0
    assert data["avg_gradient"] is not None
    assert data["avg_gradient"] > 0
    assert data["elevation_profile"] is not None
    profile = data["elevation_profile"]
    assert isinstance(profile, list)
    assert len(profile) > 0
    # 5 个点 < 80，直接返回原始点，首尾分别是 800.0 和 850.0
    assert abs(profile[0] - 800.0) < 1.0
    assert abs(profile[-1] - 850.0) < 1.0


def test_02_create_segment_no_elevation(client, admin_header):
    """无海拔数据时，新字段应为 null。"""
    payload = {
        "name": "无海拔赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    assert resp.status_code == 200
    data = resp.json()

    # 没有海拔数据，四个字段都应为 null
    assert data["elevation_gain"] is None
    assert data["elevation_loss"] is None
    assert data["avg_gradient"] is None
    assert data["elevation_profile"] is None


def test_03_create_segment_distance_precision(client, admin_header):
    """距离精度应为 2 位小数。"""
    payload = {
        "name": "精度测试",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    data = resp.json()
    dist_str = str(data["distance"])
    if "." in dist_str:
        decimal_places = len(dist_str.split(".")[1])
        assert decimal_places <= 2


def test_04_flat_segment_zero_gradient(client, admin_header):
    """完全平坦的赛段，坡度应为 0。"""
    payload = {
        "name": "平坦赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55, "ele": 800.0},
            {"lat": 37.871, "lon": 112.55, "ele": 800.0},
            {"lat": 37.872, "lon": 112.55, "ele": 800.0},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    data = resp.json()

    # 海拔无变化：爬升=0，下降=0，坡度=0
    assert data["elevation_gain"] == 0.0
    assert data["elevation_loss"] == 0.0
    assert data["avg_gradient"] == 0.0
