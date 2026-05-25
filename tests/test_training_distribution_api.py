"""Sprint 11 task-3：训练结构 API 测试。"""

import json
from datetime import datetime, timedelta, timezone

from app.activity.models import Activity
from app.training.service import _today_bj
from app.user.models import User


_BJ_TZ = timezone(timedelta(hours=8))
_USE_DEFAULT_STARTED_AT = object()
_USE_DEFAULT_POWER_ZONES = object()


def _utc_for_bj_day(day_offset: int, hour: int = 12) -> datetime:
    target = _today_bj() + timedelta(days=day_offset)
    return datetime(target.year, target.month, target.day, hour, 0, 0, tzinfo=_BJ_TZ).astimezone(timezone.utc)


def _zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z6=0):
    return [
        {"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": z1, "percent": 9},
        {"zone": "Z2", "name": "耐力", "min_w": 130, "max_w": 176, "seconds": z2, "percent": 40},
        {"zone": "Z3", "name": "节奏", "min_w": 177, "max_w": 211, "seconds": z3, "percent": 27},
        {"zone": "Z4", "name": "阈值", "min_w": 212, "max_w": 247, "seconds": z4, "percent": 15},
        {"zone": "Z5", "name": "VO2max", "min_w": 248, "max_w": 282, "seconds": z5, "percent": 8},
        {"zone": "Z6", "name": "无氧", "min_w": 283, "max_w": None, "seconds": z6, "percent": 0},
    ]


def _insert_activity(
    db,
    user_id: int,
    *,
    power_zones=_USE_DEFAULT_POWER_ZONES,
    status="completed",
    activity_type="cycling",
    duplicate_of=None,
    started_at=_USE_DEFAULT_STARTED_AT,
):
    actual_started_at = _utc_for_bj_day(-1) if started_at is _USE_DEFAULT_STARTED_AT else started_at
    actual_power_zones = _zones() if power_zones is _USE_DEFAULT_POWER_ZONES else power_zones
    activity = Activity(
        user_id=user_id,
        title="训练结构测试骑行",
        status=status,
        activity_type=activity_type,
        duration=3600,
        started_at=actual_started_at,
        power_zones=actual_power_zones,
        duplicate_of=duplicate_of,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def _seed_three_valid_activities(db, user_id: int):
    return [_insert_activity(db, user_id, started_at=_utc_for_bj_day(-day)) for day in (1, 2, 3)]


def test_training_distribution_returns_complete_payload(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["range"] == "6w"
    assert data["window_days"] == 42
    assert data["activity_count"] == 3
    assert data["data_complete"] is True
    assert data["insufficient_power_data"] is False
    assert data["current_type"] == "sweet_spot"
    assert data["headline"]
    assert len(data["groups"]) == 3
    assert len(data["raw_zones"]) == 6
    assert len(data["actions"]) == 3
    assert len(data["week_plan"]) == 7


def test_training_distribution_requires_login(client):
    resp = client.get("/api/training/distribution?range=6w")

    assert resp.status_code == 401


def test_training_distribution_invalid_range_returns_422(client, auth_header):
    resp = client.get("/api/training/distribution?range=30d", headers=auth_header)

    assert resp.status_code == 422


def test_training_distribution_does_not_leak_other_user_data(client, db, test_user, auth_header):
    other = User(openid="training_distribution_other")
    db.add(other)
    db.commit()
    db.refresh(other)
    _seed_three_valid_activities(db, other.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["activity_count"] == 0
    assert data["data_complete"] is False
    assert data["total_power_seconds"] == 0


def test_training_distribution_filters_duplicate_activities(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)
    _insert_activity(db, test_user.id, duplicate_of=1)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["activity_count"] == 3


def test_training_distribution_filters_non_cycling_and_failed(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)
    _insert_activity(db, test_user.id, activity_type="running")
    _insert_activity(db, test_user.id, status="failed")

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["activity_count"] == 3


def test_training_distribution_filters_missing_started_at(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)
    _insert_activity(db, test_user.id, started_at=None)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["activity_count"] == 3


def test_training_distribution_filters_missing_power_zones(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)
    _insert_activity(db, test_user.id, power_zones=None)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["activity_count"] == 3


def test_training_distribution_raw_zones_are_privacy_safe(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert all("min_w" not in zone and "max_w" not in zone for zone in resp.json()["raw_zones"])


def test_training_distribution_accepts_sqlite_json_string_power_zones(client, db, test_user, auth_header):
    for day in (1, 2, 3):
        _insert_activity(db, test_user.id, power_zones=json.dumps(_zones(), ensure_ascii=False), started_at=_utc_for_bj_day(-day))

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["activity_count"] == 3
    assert resp.json()["data_complete"] is True


def test_training_distribution_incomplete_flags_match(client, db, test_user, auth_header):
    _insert_activity(db, test_user.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["data_complete"] is False
    assert data["insufficient_power_data"] is True
    assert data["current_type"] is None
    assert data["actions"] == []
    assert data["week_plan"] == []


def test_training_load_endpoint_still_works_after_distribution_route_added(client, auth_header):
    resp = client.get("/api/training/load?range=30d", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["range"] == "30d"


def test_training_distribution_filters_outside_42_day_window(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)
    _insert_activity(db, test_user.id, started_at=_utc_for_bj_day(-42))
    _insert_activity(db, test_user.id, started_at=_utc_for_bj_day(1))

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    assert resp.status_code == 200
    assert resp.json()["activity_count"] == 3


def test_training_distribution_current_and_target_descriptions_present(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    data = resp.json()
    assert data["current_description"]
    assert data["target_description"]


def test_training_distribution_groups_have_fixed_label_and_role(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    groups = resp.json()["groups"]
    assert [(item["key"], item["label"], item["role"]) for item in groups] == [
        ("endurance", "耐力", "打底时间"),
        ("tempo_threshold", "中强度", "最容易堆累"),
        ("high_intensity", "高强度", "刺激偏少"),
    ]


def test_training_distribution_week_plan_is_structured(client, db, test_user, auth_header):
    _seed_three_valid_activities(db, test_user.id)

    resp = client.get("/api/training/distribution?range=6w", headers=auth_header)

    week_plan = resp.json()["week_plan"]
    assert len(week_plan) == 7
    assert all(set(item) == {"day", "title", "focus"} for item in week_plan)
