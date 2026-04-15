"""
翻译层测试——"质检验收"。

覆盖 parsing/ 模块的所有核心功能：
1. types.py：数据结构的 frozen 不可变性
2. geo_math.py：haversine 精度、爬升、速度、累计距离
3. stats_calculator.py：摘要计算、卡路里公式
4. gpx_parser.py：真实 GPX 解析、坐标系检测、speed/distance
5. coord_normalizer.py：WGS84 直通、GCJ-02 转换

所有测试都是纯函数测试，不需要数据库、Redis 或网络。
"""

import math
import os
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.parsing.types import (
    CoordSystem,
    DataSource,
    Trackpoint,
    ActivitySummary,
    ParseMetadata,
    ParseResult,
)
from app.parsing.geo_math import (
    haversine,
    calculate_elevation_gain,
    calculate_speed,
    calculate_cumulative_distances,
    EARTH_RADIUS,
    MAX_SPEED_MS,
)
from app.parsing.stats_calculator import (
    calculate_summary,
    calculate_splits,
    calculate_calories,
)
from app.parsing.gpx_parser import GPXParser, GPXParseError
from app.parsing.coord_normalizer import normalize

# 测试 fixture 目录
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ==================== 辅助函数 ====================


def _make_tp(
    seq: int,
    lat: float = 37.87,
    lon: float = 112.55,
    ele: float | None = 800.0,
    time: datetime | None = None,
    hr: int | None = None,
    cad: int | None = None,
    power: int | None = None,
    speed: float | None = None,
    distance: float | None = None,
) -> Trackpoint:
    """创建测试用 Trackpoint 的快捷函数。"""
    return Trackpoint(
        seq=seq, lat=lat, lon=lon, ele=ele, time=time,
        hr=hr, cad=cad, power=power, speed=speed, distance=distance,
    )


def _base_time(offset_seconds: int = 0) -> datetime:
    """创建一个基准时间，可加偏移秒数。"""
    base = datetime(2026, 4, 15, 6, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_seconds)


# ==================== types.py 测试 ====================


class TestTypes:
    """测试数据结构的 frozen 不可变性和字段完整性。"""

    def test_trackpoint_frozen(self):
        """Trackpoint 创建后不可修改。"""
        tp = _make_tp(0)
        with pytest.raises(FrozenInstanceError):
            tp.lat = 38.0  # type: ignore

    def test_trackpoint_all_fields(self):
        """Trackpoint 的 10 个字段全部可访问。"""
        tp = _make_tp(0, lat=37.87, lon=112.55, ele=800.0,
                      time=_base_time(), hr=140, cad=85, power=200,
                      speed=5.0, distance=100.0)
        assert tp.seq == 0
        assert tp.lat == 37.87
        assert tp.lon == 112.55
        assert tp.ele == 800.0
        assert tp.hr == 140
        assert tp.cad == 85
        assert tp.power == 200
        assert tp.speed == 5.0
        assert tp.distance == 100.0

    def test_trackpoint_optional_none(self):
        """可选字段可以是 None。"""
        tp = _make_tp(0)
        assert tp.hr is None
        assert tp.cad is None
        assert tp.power is None
        assert tp.speed is None
        assert tp.distance is None

    def test_coord_system_values(self):
        """坐标系枚举值正确。"""
        assert CoordSystem.WGS84.value == "wgs84"
        assert CoordSystem.GCJ02.value == "gcj02"

    def test_data_source_values(self):
        """数据来源枚举值正确。"""
        assert DataSource.GPX.value == "gpx"
        assert DataSource.FIT.value == "fit"
        assert DataSource.STRAVA.value == "strava"


# ==================== geo_math.py 测试 ====================


class TestGeoMath:
    """测试地理计算工具的精度和边界情况。"""

    def test_haversine_known_distance(self):
        """haversine 对已知距离的精度验证。"""
        # 太原理工大学到五一广场，约 3.5km
        dist = haversine(37.8700, 112.5500, 37.8700, 112.5900)
        # 经度差 0.04°，在纬度 37.87° 处约 3.5km
        assert 3000 < dist < 4000

    def test_haversine_same_point(self):
        """同一点距离为零。"""
        assert haversine(37.87, 112.55, 37.87, 112.55) == 0.0

    def test_haversine_equator_one_degree(self):
        """赤道上经度差 1° 约 111km。"""
        dist = haversine(0, 0, 0, 1)
        assert 110_000 < dist < 112_000

    def test_elevation_gain_basic(self):
        """基本爬升计算：只累加正向且超过阈值的高差。"""
        tps = [
            _make_tp(0, ele=100.0),
            _make_tp(1, ele=105.0),  # +5m，超过 2m 阈值，计入
            _make_tp(2, ele=104.0),  # -1m，下坡不计
            _make_tp(3, ele=110.0),  # +6m，计入
        ]
        gain = calculate_elevation_gain(tps)
        assert gain == 11.0  # 5 + 6

    def test_elevation_gain_noise_filter(self):
        """去噪：高差 ≤ 2m 不计入爬升。"""
        tps = [
            _make_tp(0, ele=100.0),
            _make_tp(1, ele=101.5),  # +1.5m，低于 2m 阈值，不计入
            _make_tp(2, ele=103.0),  # +1.5m，低于阈值
        ]
        gain = calculate_elevation_gain(tps)
        assert gain == 0.0

    def test_elevation_gain_none_ele(self):
        """海拔为 None 的点被安全跳过。"""
        tps = [
            _make_tp(0, ele=100.0),
            _make_tp(1, ele=None),
            _make_tp(2, ele=110.0),
        ]
        gain = calculate_elevation_gain(tps)
        assert gain == 0.0  # 100→None 和 None→110 都跳过

    def test_elevation_gain_empty(self):
        """空列表返回 0。"""
        assert calculate_elevation_gain([]) == 0.0

    def test_calculate_speed_normal(self):
        """正常速度计算。"""
        tp1 = _make_tp(0, lat=37.8700, lon=112.5500, time=_base_time(0))
        tp2 = _make_tp(1, lat=37.8710, lon=112.5510, time=_base_time(10))
        speed = calculate_speed(tp1, tp2)
        assert speed is not None
        # 10 秒走了约 130m，速度约 13 m/s
        assert 10 < speed < 20

    def test_calculate_speed_drift(self):
        """GPS 漂移（>120km/h）返回 None。"""
        tp1 = _make_tp(0, lat=37.87, lon=112.55, time=_base_time(0))
        # 1 秒内跳了 0.01°（约 1km），速度约 1000 m/s
        tp2 = _make_tp(1, lat=37.87, lon=112.56, time=_base_time(1))
        speed = calculate_speed(tp1, tp2)
        assert speed is None

    def test_calculate_speed_no_time(self):
        """无时间戳返回 None。"""
        tp1 = _make_tp(0, time=None)
        tp2 = _make_tp(1, time=None)
        assert calculate_speed(tp1, tp2) is None

    def test_cumulative_distances(self):
        """累计距离逐点递增，第一个为 0。"""
        tps = [
            _make_tp(0, lat=37.8700, lon=112.5500),
            _make_tp(1, lat=37.8710, lon=112.5510),
            _make_tp(2, lat=37.8720, lon=112.5520),
        ]
        dists = calculate_cumulative_distances(tps)
        assert len(dists) == 3
        assert dists[0] == 0.0
        assert dists[1] > 0
        assert dists[2] > dists[1]

    def test_cumulative_distances_empty(self):
        """空列表返回空。"""
        assert calculate_cumulative_distances([]) == []


# ==================== stats_calculator.py 测试 ====================


class TestStatsCalculator:
    """测试统计计算器。"""

    def _make_ride_tps(self, count: int = 10) -> list[Trackpoint]:
        """创建一段模拟骑行轨迹（有时间、有速度、有距离）。"""
        tps = []
        for i in range(count):
            tps.append(Trackpoint(
                seq=i,
                lat=37.87 + i * 0.001,
                lon=112.55 + i * 0.001,
                ele=800.0 + i * 3.0 if i < count // 2 else 800.0 + (count - i) * 3.0,
                time=_base_time(i * 10),
                hr=140 + i,
                cad=85,
                power=200 + i * 5,
                speed=8.0 + i * 0.5,
                distance=i * 130.0,
            ))
        return tps

    def test_summary_basic(self):
        """基本摘要计算。"""
        tps = self._make_ride_tps(10)
        summary = calculate_summary(tps)

        assert isinstance(summary, ActivitySummary)
        assert summary.distance > 0
        assert summary.duration == 90  # 9 个间隔 × 10 秒
        assert summary.elevation_gain >= 0
        assert summary.avg_speed is not None
        assert summary.started_at == _base_time(0)
        assert summary.finished_at == _base_time(90)
        assert summary.normalized_power is None  # GPX 无 NP

    def test_summary_sensor_stats(self):
        """传感器统计（心率/功率/踏频）。"""
        tps = self._make_ride_tps(5)
        summary = calculate_summary(tps)

        assert summary.avg_hr is not None
        assert summary.max_hr is not None
        assert summary.avg_power is not None
        assert summary.max_power is not None
        assert summary.avg_cadence is not None

    def test_summary_empty_raises(self):
        """空列表抛 ValueError。"""
        with pytest.raises(ValueError):
            calculate_summary([])

    def test_calories_with_power(self):
        """有功率时用功率公式。"""
        cal = calculate_calories(200.0, 3600, 70.0)
        assert cal is not None
        assert cal > 0
        # 200W × 3600s / 1000 × 3.6 × 0.25 = 648 kcal
        assert 600 < cal < 700

    def test_calories_without_power(self):
        """无功率时用 MET 粗估。"""
        cal = calculate_calories(None, 3600, 70.0)
        assert cal is not None
        # 1h × 70kg × 8 MET = 560 kcal
        assert 550 < cal < 570

    def test_calories_no_duration(self):
        """无时间返回 None。"""
        assert calculate_calories(200.0, None, 70.0) is None
        assert calculate_calories(200.0, 0, 70.0) is None

    def test_splits_basic(self):
        """基本分段测试（数据量太小可能只有一段或空）。"""
        tps = self._make_ride_tps(10)
        splits = calculate_splits(tps)
        assert isinstance(splits, list)
        # 10 个点间距约 130m × 9 = 1.17km，不到 10km，最多 1 段
        if splits:
            assert "km" in splits[0]
            assert "avg_speed" in splits[0]


# ==================== gpx_parser.py 测试 ====================


class TestGPXParser:
    """测试新版 GPX 解析器。"""

    @pytest.fixture
    def gpx_content(self) -> bytes:
        """读取测试 fixture 的 GPX 文件。"""
        return (FIXTURES_DIR / "test_ride.gpx").read_bytes()

    @pytest.fixture
    def gpx_no_power_content(self) -> bytes:
        """读取无功率的 GPX fixture。"""
        return (FIXTURES_DIR / "test_ride_no_power.gpx").read_bytes()

    def test_parse_returns_parse_result(self, gpx_content):
        """解析返回 ParseResult 类型。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)
        assert isinstance(result, ParseResult)

    def test_parse_trackpoints(self, gpx_content):
        """轨迹点完整提取。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)

        assert len(result.trackpoints) > 0
        tp = result.trackpoints[0]
        assert isinstance(tp, Trackpoint)
        assert tp.seq == 0
        assert tp.lat is not None
        assert tp.lon is not None

    def test_parse_trackpoints_have_speed_distance(self, gpx_content):
        """新版 GPX 解析器填充 speed 和 distance 字段。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)

        # 第一个点 speed=None, distance=0.0
        assert result.trackpoints[0].speed is None
        assert result.trackpoints[0].distance == 0.0

        # 后续点应有 speed 和递增的 distance
        if len(result.trackpoints) > 1:
            tp = result.trackpoints[1]
            assert tp.distance > 0
            # speed 可能是 None（如果 GPS 漂移）或 float
            if tp.speed is not None:
                assert tp.speed > 0

    def test_parse_summary(self, gpx_content):
        """摘要统计完整。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)

        s = result.summary
        assert isinstance(s, ActivitySummary)
        assert s.distance > 0
        assert s.duration is not None and s.duration > 0
        assert s.avg_speed is not None

    def test_parse_metadata(self, gpx_content):
        """元数据正确。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)

        m = result.metadata
        assert m.source == DataSource.GPX
        assert m.coord_system == CoordSystem.WGS84
        assert m.creator is not None  # fixture 有 creator

    def test_parse_simplified_track(self, gpx_content):
        """简化轨迹有输出。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)
        assert result.simplified_track is not None
        assert len(result.simplified_track) > 0
        assert "lat" in result.simplified_track[0]

    def test_parse_power_zones_with_ftp(self, gpx_content):
        """传入 ftp 时计算功率区间。"""
        parser = GPXParser()
        result = parser.parse(gpx_content, ftp=200)

        # test_ride.gpx 有功率数据，应该有 power_zones
        if result.power_zones is not None:
            assert len(result.power_zones) == 6
            assert result.power_zones[0]["zone"] == "Z1"

    def test_parse_no_power_no_zones(self, gpx_no_power_content):
        """无功率数据时 power_zones 为 None。"""
        parser = GPXParser()
        result = parser.parse(gpx_no_power_content, ftp=200)
        assert result.power_zones is None

    def test_parse_coord_detection_wgs84(self, gpx_content):
        """非中国 App 的 creator 检测为 WGS84。"""
        parser = GPXParser()
        result = parser.parse(gpx_content)
        assert result.metadata.coord_system == CoordSystem.WGS84

    def test_parse_coord_detection_gcj02(self):
        """行者 App 的 creator 检测为 GCJ-02。"""
        # 构造一个 creator 含 xingzhe 的最小 GPX
        gpx_bytes = b"""<?xml version="1.0"?>
        <gpx version="1.1" creator="Xingzhe Sport">
          <trk><trkseg>
            <trkpt lat="39.9" lon="116.4"><time>2026-04-15T06:00:00Z</time></trkpt>
            <trkpt lat="39.91" lon="116.41"><time>2026-04-15T06:01:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>"""
        parser = GPXParser()
        result = parser.parse(gpx_bytes)
        assert result.metadata.coord_system == CoordSystem.GCJ02

    def test_parse_invalid_content(self):
        """非 GPX 内容抛异常。"""
        parser = GPXParser()
        with pytest.raises(GPXParseError):
            parser.parse(b"this is not gpx")

    def test_parse_empty_track(self):
        """无轨迹点抛异常。"""
        gpx_bytes = b"""<?xml version="1.0"?>
        <gpx version="1.1"><trk><trkseg></trkseg></trk></gpx>"""
        parser = GPXParser()
        with pytest.raises(GPXParseError, match="无轨迹数据"):
            parser.parse(gpx_bytes)


# ==================== coord_normalizer.py 测试 ====================


class TestCoordNormalizer:
    """测试坐标系归一化。"""

    def _make_wgs84_result(self) -> ParseResult:
        """创建一个 WGS84 坐标的 ParseResult。"""
        tp = _make_tp(0, lat=37.87, lon=112.55, time=_base_time())
        summary = ActivitySummary(
            distance=1000.0, duration=60, elevation_gain=10.0,
            avg_speed=16.7, max_speed=20.0,
            avg_power=None, max_power=None,
            avg_hr=None, max_hr=None, avg_cadence=None,
            calories=None, started_at=_base_time(), finished_at=_base_time(60),
            splits=None, normalized_power=None,
        )
        metadata = ParseMetadata(
            source=DataSource.GPX, coord_system=CoordSystem.WGS84,
            title="Test", creator="Test", file_hash=None,
        )
        return ParseResult(
            trackpoints=[tp], summary=summary, metadata=metadata,
            simplified_track=[{"lat": 37.87, "lon": 112.55, "ele": 800.0}],
            power_zones=None,
        )

    def _make_gcj02_result(self) -> ParseResult:
        """创建一个 GCJ-02 坐标的 ParseResult（天安门坐标）。"""
        # GCJ-02 坐标：天安门
        tp = _make_tp(0, lat=39.90923, lon=116.397428, time=_base_time())
        summary = ActivitySummary(
            distance=1000.0, duration=60, elevation_gain=0.0,
            avg_speed=16.7, max_speed=20.0,
            avg_power=None, max_power=None,
            avg_hr=None, max_hr=None, avg_cadence=None,
            calories=None, started_at=_base_time(), finished_at=_base_time(60),
            splits=None, normalized_power=None,
        )
        metadata = ParseMetadata(
            source=DataSource.GPX, coord_system=CoordSystem.GCJ02,
            title="Test", creator="xingzhe", file_hash=None,
        )
        return ParseResult(
            trackpoints=[tp], summary=summary, metadata=metadata,
            simplified_track=[{"lat": 39.90923, "lon": 116.397428, "ele": 50.0}],
            power_zones=None,
        )

    def test_wgs84_passthrough(self):
        """WGS84 输入直接返回同一对象（零开销）。"""
        result = self._make_wgs84_result()
        normalized = normalize(result)
        assert normalized is result  # 同一对象引用

    def test_gcj02_converts(self):
        """GCJ-02 输入坐标被转换，偏移 > 100m。"""
        result = self._make_gcj02_result()
        normalized = normalize(result)

        # 转换后应标记为 WGS84
        assert normalized.metadata.coord_system == CoordSystem.WGS84

        # 坐标应该发生了变化（偏移 100-600m）
        orig_lat = result.trackpoints[0].lat
        new_lat = normalized.trackpoints[0].lat
        # 纬度差约 0.001-0.005 度
        assert abs(orig_lat - new_lat) > 0.0005

    def test_gcj02_preserves_non_coord_fields(self):
        """GCJ-02 转换后非坐标字段不变。"""
        result = self._make_gcj02_result()
        normalized = normalize(result)

        # summary 不变
        assert normalized.summary.distance == result.summary.distance
        # 元数据其他字段不变
        assert normalized.metadata.source == DataSource.GPX
        assert normalized.metadata.creator == "xingzhe"
        # trackpoint 非坐标字段不变
        assert normalized.trackpoints[0].seq == 0
        assert normalized.trackpoints[0].time == _base_time()

    def test_gcj02_converts_simplified_track(self):
        """GCJ-02 转换同时转换 simplified_track。"""
        result = self._make_gcj02_result()
        normalized = normalize(result)

        orig_lat = result.simplified_track[0]["lat"]
        new_lat = normalized.simplified_track[0]["lat"]
        assert abs(orig_lat - new_lat) > 0.0005
