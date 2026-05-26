"""
活动时序指针测试——检查图表下面那把“可滑动尺子”拿到的数据够不够准。

这些测试只盯 timeseries 接口的数据契约：
- 后端按骑行总距离自动决定每隔多少米给前端一个可吸附点
- 每个点带上距离、时间和原始轨迹序号，让前端能像 Strava 一样显示瞬时读数
- 隐私门禁仍然生效，别人看不到被隐藏的功率/心率曲线
"""

from datetime import datetime, timedelta, timezone

from app.activity.models import Activity, ActivityPrivacy, Trackpoint
from app.activity.service import get_activity_timeseries
from app.user.models import User


def _create_completed_activity(db, user_id: int, distance_m: float) -> Activity:
    activity = Activity(
        user_id=user_id,
        title="指针测试骑行",
        status="completed",
        distance=distance_m,
        duration=3600,
        started_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def _add_trackpoints(
    db,
    activity_id: int,
    count: int,
    distance_step_m: float,
    *,
    start_time: datetime | None = None,
    speed_mps: float | None = 10.0,
    with_power: bool = True,
    with_hr: bool = True,
    with_cadence: bool = True,
    use_distance: bool = True,
) -> None:
    start = start_time or datetime(2026, 5, 1, 8, 0, tzinfo=timezone.utc)
    for seq in range(count):
        db.add(
            Trackpoint(
                activity_id=activity_id,
                seq=seq,
                latitude=30.0 + seq * 0.0001,
                longitude=120.0,
                elevation=100.0 + (seq % 20),
                timestamp=start + timedelta(seconds=seq * 10),
                heart_rate=150 if with_hr else None,
                cadence=88 if with_cadence else None,
                power=230 if with_power else None,
                speed=speed_mps,
                distance=seq * distance_step_m if use_distance else None,
            )
        )
    db.commit()


def test_timeseries_uses_roughly_200m_steps_for_long_rides(db, test_user):
    activity = _create_completed_activity(db, test_user.id, 100_000.0)
    _add_trackpoints(db, activity.id, count=1001, distance_step_m=100.0)

    data = get_activity_timeseries(db, activity.id, test_user.id, max_points=1200)

    assert data["sample_step_m"] == 200.0
    assert data["resolution_label"] == "约 200m/点"
    assert 495 <= len(data["distances"]) <= 505
    assert len(data["times"]) == len(data["distances"])
    assert len(data["original_indices"]) == len(data["distances"])
    assert data["distances"][1] == 0.2
    assert data["times"][1] == 20
    assert data["original_indices"][1] == 2
    assert data["speeds"][1] == 36.0


def test_timeseries_uses_finer_steps_for_short_rides(db, test_user):
    activity = _create_completed_activity(db, test_user.id, 10_000.0)
    _add_trackpoints(db, activity.id, count=201, distance_step_m=50.0)

    data = get_activity_timeseries(db, activity.id, test_user.id, max_points=1200)

    assert data["sample_step_m"] == 50.0
    assert data["resolution_label"] == "约 50m/点"
    assert len(data["distances"]) == 201
    assert data["distances"][1] == 0.05
    assert data["original_indices"][1] == 1


def test_timeseries_falls_back_to_gps_distance_when_trackpoint_distance_missing(db, test_user):
    activity = _create_completed_activity(db, test_user.id, 5_000.0)
    _add_trackpoints(
        db,
        activity.id,
        count=120,
        distance_step_m=0.0,
        use_distance=False,
    )

    data = get_activity_timeseries(db, activity.id, test_user.id, max_points=1200)

    assert data["sample_step_m"] == 50.0
    assert data["distances"][0] == 0
    assert data["distances"][-1] > 0
    assert len(data["times"]) == len(data["distances"])
    assert len(data["original_indices"]) == len(data["distances"])


def test_timeseries_keeps_sensor_arrays_null_when_sensor_data_missing(db, test_user):
    activity = _create_completed_activity(db, test_user.id, 20_000.0)
    _add_trackpoints(
        db,
        activity.id,
        count=101,
        distance_step_m=200.0,
        with_power=False,
        with_hr=False,
        with_cadence=False,
    )

    data = get_activity_timeseries(db, activity.id, test_user.id, max_points=1200)

    assert data["powers"] is None
    assert data["heart_rates"] is None
    assert data["cadences"] is None
    assert len(data["speeds"]) == len(data["distances"])


def test_timeseries_privacy_masks_power_and_heartrate_for_other_viewer(db, test_user):
    other = User(openid="timeseries_other_viewer", is_admin=False)
    db.add(other)
    db.commit()
    db.refresh(other)

    activity = _create_completed_activity(db, test_user.id, 20_000.0)
    db.add(
        ActivityPrivacy(
            activity_id=activity.id,
            visibility="public",
            hide_power=True,
            hide_heartrate=True,
        )
    )
    _add_trackpoints(db, activity.id, count=101, distance_step_m=200.0)
    db.commit()

    data = get_activity_timeseries(db, activity.id, other.id, max_points=1200)

    assert data["powers"] is None
    assert data["heart_rates"] is None
    assert data["cadences"] is not None
    assert data["speeds"][1] == 36.0
