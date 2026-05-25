"""Sprint 11 task-6：历史 power_zones 补 zero_seconds 的回填脚本测试。"""

import json
from datetime import datetime, timedelta, timezone

from app.activity.models import Activity
from scripts.backfill_power_zone_zero_seconds import (
    backfill_power_zone_zero_seconds_for_user,
    preview_power_zone_zero_seconds_for_user,
)
from tests.conftest import _activities_table, _trackpoints_table


def _zones(z1=0, z2=0, z3=0, z4=0, z5=0, z6=0, z1_zero=None):
    z1_item = {"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 109, "seconds": z1, "percent": 0}
    if z1_zero is not None:
        z1_item["zero_seconds"] = z1_zero
    return [
        z1_item,
        {"zone": "Z2", "name": "耐力", "min_w": 110, "max_w": 149, "seconds": z2, "percent": 0},
        {"zone": "Z3", "name": "节奏", "min_w": 150, "max_w": 179, "seconds": z3, "percent": 0},
        {"zone": "Z4", "name": "阈值", "min_w": 180, "max_w": 209, "seconds": z4, "percent": 0},
        {"zone": "Z5", "name": "VO2max", "min_w": 210, "max_w": 239, "seconds": z5, "percent": 0},
        {"zone": "Z6", "name": "无氧", "min_w": 240, "max_w": None, "seconds": z6, "percent": 0},
    ]


def _insert_activity(
    db,
    user_id: int,
    *,
    power_zones=None,
    snapshot_ftp: int | None = 200,
    status: str = "completed",
    activity_type: str = "cycling",
) -> int:
    result = db.execute(
        _activities_table.insert().values(
            user_id=user_id,
            title="zero seconds backfill test",
            status=status,
            activity_type=activity_type,
            distance=12000.0,
            duration=30,
            snapshot_ftp=snapshot_ftp,
            power_zones=json.dumps(power_zones if power_zones is not None else _zones(z1=20), ensure_ascii=False),
            started_at=datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    return result.inserted_primary_key[0]


def _insert_trackpoints(db, activity_id: int, powers: list[int | None]):
    base = datetime(2026, 5, 25, 10, 0, 0, tzinfo=timezone.utc)
    for index, power in enumerate(powers):
        db.execute(
            _trackpoints_table.insert().values(
                activity_id=activity_id,
                seq=index,
                latitude=37.0,
                longitude=112.0,
                timestamp=base + timedelta(seconds=index * 10),
                power=power,
            )
        )
    db.commit()


def _activity(db, activity_id: int) -> Activity:
    return db.query(Activity).filter_by(id=activity_id).first()


def _z1(activity: Activity) -> dict:
    zones = activity.power_zones
    if isinstance(zones, str):
        zones = json.loads(zones)
    return next(item for item in zones if item["zone"] == "Z1")


def _zone(activity: Activity, zone: str) -> dict:
    zones = activity.power_zones
    if isinstance(zones, str):
        zones = json.loads(zones)
    return next(item for item in zones if item["zone"] == zone)


def test_preview_reports_zero_seconds_without_writing(db, test_user):
    """dry-run 只预览前后差异，不改 activities.power_zones。"""
    activity_id = _insert_activity(db, test_user.id)
    _insert_trackpoints(db, activity_id, [0, 100, 180, 180])

    previews = preview_power_zone_zero_seconds_for_user(db, test_user.id)

    assert len(previews) == 1
    assert previews[0].activity_id == activity_id
    assert previews[0].after_zero_seconds == 10
    assert "zero_seconds" not in _z1(_activity(db, activity_id))


def test_apply_recomputes_power_zones_with_zero_seconds(db, test_user):
    """apply 复用 calculate_power_zones 重算整条 power_zones，并写入 Z1.zero_seconds。"""
    activity_id = _insert_activity(db, test_user.id)
    _insert_trackpoints(db, activity_id, [0, 100, 180, 180])

    stats = backfill_power_zone_zero_seconds_for_user(db, test_user.id)
    db.commit()

    activity = _activity(db, activity_id)
    assert stats["updated"] == 1
    assert _z1(activity)["zero_seconds"] == 10
    assert _z1(activity)["seconds"] == 20
    assert _zone(activity, "Z4")["seconds"] == 10


def test_existing_zero_seconds_is_skipped(db, test_user):
    """已经补过的活动不再覆盖，保证脚本可重复跑。"""
    activity_id = _insert_activity(db, test_user.id, power_zones=_zones(z1=20, z1_zero=8))
    _insert_trackpoints(db, activity_id, [0, 100, 180])

    stats = backfill_power_zone_zero_seconds_for_user(db, test_user.id)
    db.commit()

    assert stats["skipped_existing"] == 1
    assert _z1(_activity(db, activity_id))["zero_seconds"] == 8


def test_snapshot_ftp_is_used_before_current_user_ftp(db, test_user):
    """历史活动有 snapshot_ftp 时，优先用它重算，避免用户后来改 FTP 污染历史区间。"""
    test_user.ftp = 300
    db.commit()
    activity_id = _insert_activity(db, test_user.id, snapshot_ftp=200, power_zones=_zones(z1=20))
    _insert_trackpoints(db, activity_id, [120, 120, 120])

    backfill_power_zone_zero_seconds_for_user(db, test_user.id)
    db.commit()

    activity = _activity(db, activity_id)
    assert _z1(activity)["seconds"] == 0
    assert _zone(activity, "Z2")["seconds"] == 20


def test_missing_ftp_is_skipped(db, test_user):
    """没有 snapshot_ftp、当前用户也没 ftp 时不能瞎算。"""
    test_user.ftp = None
    db.commit()
    activity_id = _insert_activity(db, test_user.id, snapshot_ftp=None)
    _insert_trackpoints(db, activity_id, [0, 100, 180])

    stats = backfill_power_zone_zero_seconds_for_user(db, test_user.id)
    db.commit()

    assert stats["skipped_no_ftp"] == 1
    assert "zero_seconds" not in _z1(_activity(db, activity_id))


def test_non_completed_or_non_cycling_activity_is_not_considered(db, test_user):
    """只处理 completed + cycling + power_zones 非空的历史骑行。"""
    pending_id = _insert_activity(db, test_user.id, status="pending")
    running_id = _insert_activity(db, test_user.id, activity_type="running")
    _insert_trackpoints(db, pending_id, [0, 100])
    _insert_trackpoints(db, running_id, [0, 100])

    assert preview_power_zone_zero_seconds_for_user(db, test_user.id) == []
