"""功率区间纯函数测试：锁住 0W 滑行时间的统计口径。"""

from datetime import datetime, timedelta, timezone

from app.activity.power_zones import calculate_power_zones


def _tp(power, seconds: int) -> dict:
    return {
        "power": power,
        "time": datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds),
    }


def _zone(zones: list[dict], zone: str) -> dict:
    return next(item for item in zones if item["zone"] == zone)


def test_calculate_power_zones_records_zero_seconds_inside_z1():
    """0W 只是一种合法功率读数：它进 Z1，同时额外记入 zero_seconds。"""
    zones = calculate_power_zones(
        [
            _tp(0, 0),
            _tp(100, 10),
            _tp(None, 20),
            _tp(180, 30),
            _tp(250, 40),
        ],
        ftp=200,
    )

    z1 = _zone(zones, "Z1")
    assert z1["seconds"] == 20
    assert z1["zero_seconds"] == 10
    assert _zone(zones, "Z4")["seconds"] == 10


def test_calculate_power_zones_sets_zero_seconds_to_zero_without_zero_power():
    """有功率但不停踩时，Z1 仍带 zero_seconds=0，方便聚合层统一读取。"""
    zones = calculate_power_zones([_tp(100, 0), _tp(120, 10), _tp(180, 20)], ftp=200)

    assert _zone(zones, "Z1")["zero_seconds"] == 0


def test_calculate_power_zones_does_not_treat_none_as_zero_power():
    """None 代表设备没给功率，不能和 0W 停踩混在一起。"""
    zones = calculate_power_zones([_tp(None, 0), _tp(0, 10), _tp(100, 20)], ftp=200)

    z1 = _zone(zones, "Z1")
    assert z1["seconds"] == 10
    assert z1["zero_seconds"] == 10
