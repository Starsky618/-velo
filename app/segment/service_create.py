"""
赛段创建相关业务逻辑。

从 service.py 拆出，保持函数签名、返回值和业务行为不变。
"""

import json
from types import SimpleNamespace

from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.common.geo import infer_city_from_coords
from app.segment._geo_utils import _haversine, _sample_elevation_profile
from app.segment.algorithms import (
    _haversine_distance,
    calculate_difficulty,
    calculate_max_gradient,
)
from app.segment.dem_client import DEMServiceError, query_elevations
from app.segment.coord_convert import convert_points_to_wgs84
from app.segment.exceptions import InvalidSegmentRangeError, SegmentOverlapError
from app.segment.models import Segment
from app.user.models import User


# ==================== 共享：Hausdorff 重复检测（v5 task-3.A.6 / spec 自审 #2 共享逻辑识别）====================

def _check_hausdorff_overlap(db: Session, wkt: str) -> bool:
    """检查给定 WKT LINESTRING 是否与既有赛段高度重叠（Hausdorff 距离 < 0.0005°）。

    类比：「拿一根新绳子比对已有的所有绳子」——如果新绳子整体形状和某根已有绳子贴得很近
    （Hausdorff 距离衡量"两条线最远偏离点的距离"），就视为重复，避免同路段被反复建赛段。

    陷阱警示：不用 ST_Intersection + ST_Length —— 它容易把局部交叉误判成整体重复。

    dialect 守卫：仅 PostgreSQL/PostGIS 环境真跑——SQLite 测试 fixture 不支持
    ST_HausdorffDistance / ST_GeomFromText。SQLite 直接返 False（视为"没重叠"让插入继续），
    实际产品保护在生产真 PG 起作用。SQLite 单元测试不该验"查重"业务规则
    （应在 dev stack 真 PG 集成测试验证 / 详 task-3.A.6 review N1 决策）。

    返回：True = 已有重叠 / False = 没有重叠。
    """
    if db.bind.dialect.name != "postgresql":
        return False
    overlap = db.execute(
        text(
            """
            SELECT id
            FROM segments
            WHERE ST_HausdorffDistance(reference_line, ST_GeomFromText(:wkt, 4326)) < :threshold
            LIMIT 1
            """
        ),
        {"wkt": wkt, "threshold": 0.0005},
    ).first()
    return overlap is not None


# ==================== 创建赛段 ====================

def create_segment(
    db: Session,
    user_id: int,
    name: str,
    reference_points: list[dict],
    description: str | None = None,
    match_tolerance: float | None = None,
    min_match_ratio: float | None = None,
    coordinate_system: str = "gcj02",
) -> Segment:
    """
    创建一条赛段——管理员专用。

    流程好比在地图上"画一条赛道"：
    1. 验证画图的人是管理员（普通用户不能画赛道）
    2. 量一量这条路有多长（haversine 逐段求和）
    3. 算一算爬了多高（只算上坡，下坡不计）
    4. 记下起点和终点坐标
    5. 把这条线存进地图数据库（PostGIS LINESTRING）
    """
    # 权限检查：只有管理员能创建赛段
    user = db.query(User).filter_by(id=user_id).first()
    if not user or not user.is_admin:
        raise PermissionError("需要管理员权限")

    # 坐标系转换：如果传入的是 GCJ-02（腾讯/高德地图坐标），转成 WGS-84。
    # GPX 轨迹点天然是 WGS-84，赛段参考线也必须是 WGS-84 才能正确匹配。
    # 不转的话两套坐标偏差 100~700 米，50 米容差的 matcher 必然匹配失败。
    reference_points = convert_points_to_wgs84(reference_points, coordinate_system)

    # 计算总距离（米）：把相邻点之间的距离加起来
    # 好比用尺子量一段段弯路，每段量完加总
    total_distance = 0.0
    for i in range(1, len(reference_points)):
        total_distance += _haversine(
            reference_points[i - 1]["lat"], reference_points[i - 1]["lon"],
            reference_points[i]["lat"], reference_points[i]["lon"],
        )

    # 防御：坐标完全重合导致距离为 0 的赛段没有意义
    if total_distance < 1.0:
        raise ValueError("赛段距离过短，请检查坐标点")

    # DEM 海拔替换（v3 / 2026-05-14）：GPS 海拔精度 ±10-15m 物理限制，
    # 任何平滑算法都洗不掉系统偏差（夜骑清徐 GPS 测得 26% 假坡度，DEM 实测 0.018%）。
    # 业界 2024 共识：换数据源，从 SRTM 30m DEM 查表替换。
    # 失败时抛 DEMServiceError，让 admin 知道服务挂了不要默默用 GPS 假数据。
    dem_coords = [(p["lat"], p["lon"]) for p in reference_points]
    dem_elevations = query_elevations(dem_coords)

    # 把 DEM 海拔覆盖回 reference_points 的 ele 字段（保留原 list 结构供后续使用）
    # 个别点 DEM 查不到（海上 / 数据空洞）时返 None，保持原值兜底
    for i, dem_ele in enumerate(dem_elevations):
        if dem_ele is not None:
            reference_points[i]["ele"] = float(dem_ele)

    # 计算累计爬升、累计下降、平均坡度、海拔缩略图
    # DEM 替换后基本所有点都有 ele；若 DEM 整批查不到（极少数情况），降级为 None
    elevation_gain = None
    elevation_loss = None
    avg_gradient = None
    elevation_profile = None
    if all(p.get("ele") is not None for p in reference_points):
        elevation_gain = 0.0
        elevation_loss = 0.0
        for i in range(1, len(reference_points)):
            diff = reference_points[i]["ele"] - reference_points[i - 1]["ele"]
            if diff > 0:
                # 上坡：累计爬升
                elevation_gain += diff
            elif diff < 0:
                # 下坡：累计下降（abs 转为正数，好比"下了多少层楼"）
                elevation_loss += abs(diff)

        # 平均坡度（%）= 累计爬升 ÷ 水平距离 × 100
        # 好比爬 100 米高差的山，水平走了 1000 米，坡度就是 10%
        avg_gradient = round(elevation_gain / total_distance * 100, 1) if total_distance > 0 else 0.0

        # 海拔缩略图：等距采样约 80 个点，前端用来画海拔曲线
        elevation_profile = _sample_elevation_profile(reference_points, target_count=80)

    # 提取首尾坐标（赛段的"起跑线"和"终点线"）
    first = reference_points[0]
    last = reference_points[-1]

    # 构建 WKT LINESTRING——PostGIS 能理解的"画线指令"
    # 注意：WKT 坐标顺序是 (经度 纬度)，不是 (纬度 经度)！
    # 这是 GIS 领域的通用约定，和日常说的"北纬xx度、东经xx度"顺序相反
    coords_str = ", ".join(
        f"{p['lon']} {p['lat']}" for p in reference_points
    )
    wkt = f"SRID=4326;LINESTRING({coords_str})"

    # 创建赛段记录（elevation_profile 序列化为 JSON 字符串存入 Text 字段）
    # json.dumps 把 Python 列表 [800.0, 850.0, ...] 变成 "[800.0, 850.0, ...]" 字符串
    # 读取时用 json.loads 还原回列表，router 层负责反序列化
    segment = Segment(
        name=name,
        description=description,
        distance=total_distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        avg_gradient=avg_gradient,
        elevation_profile=json.dumps(elevation_profile) if elevation_profile is not None else None,
        start_lat=first["lat"],
        start_lon=first["lon"],
        end_lat=last["lat"],
        end_lon=last["lon"],
        reference_line=wkt,
    )

    # 匹配参数：显式赋值，不依赖 server_default
    # 原因：server_default 是数据库层面的默认值，在 db.commit() 前 Python 对象上是 None。
    # 虽然 commit+refresh 后 PostgreSQL 会回填，但 SQLite 测试环境可能不会，
    # 导致后续构造响应时 Pydantic 遇到 None 而 schema 要求 float → 报错。
    # 显式赋值确保 Python 端始终有值，无论数据库类型。
    segment.match_tolerance = match_tolerance if match_tolerance is not None else 50.0
    segment.min_match_ratio = min_match_ratio if min_match_ratio is not None else 0.8

    # Hausdorff 查重：用共享 helper 跨 from-gpx + from-activity 两条创建路径（task-3.A.6 review N1）
    _hausdorff_coords = ", ".join(
        f"{p['lon']} {p['lat']}" for p in reference_points
    )
    if _check_hausdorff_overlap(db, f"LINESTRING({_hausdorff_coords})"):
        raise SegmentOverlapError("新赛段与已有赛段高度重叠")

    db.add(segment)
    db.commit()
    db.refresh(segment)

    return segment


# ==================== 从已骑活动创建赛段（v5 task-1.A.2） ====================

def create_segment_from_activity(
    db: Session,
    activity_id: int,
    name: str,
    start_index: int,
    end_index: int,
    city: str | None = None,
    difficulty: str | None = None,
) -> Segment:
    """
    从一段已完成骑行轨迹中裁剪出新赛段。

    这像从一根长绳上剪下一段做成标准赛道：先锁住剪刀避免两个人同时剪，
    再检查起止点、量长度、查重，最后把线段写进 PostGIS。
    """
    # 1. 入函数立即拿事务级 advisory lock。
    # 类比：创建赛段前先拿唯一号码牌，同一时刻只有一个人能裁剪，避免并发重复创建。
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('segment-create-from-activity'))"))

    # 2. 先检查索引方向。起点必须早于终点，像剪绳子不能从右往左倒着剪。
    if start_index >= end_index:
        raise InvalidSegmentRangeError("start_index 必须小于 end_index")

    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")

    tps = (
        db.query(Trackpoint)
        .filter(
            Trackpoint.activity_id == activity_id,
            Trackpoint.seq >= start_index,
            Trackpoint.seq <= end_index,
        )
        .order_by(Trackpoint.seq)
        .all()
    )
    if len(tps) < 2:
        raise InvalidSegmentRangeError("赛段至少需要 2 个轨迹点")

    # 3. 先算距离（不依赖海拔），太短早 raise 避免无效 DEM 调用
    distance = 0.0
    for i in range(1, len(tps)):
        distance += _haversine_distance(
            tps[i - 1].latitude, tps[i - 1].longitude,
            tps[i].latitude, tps[i].longitude,
        )
    if distance < 1000:
        raise InvalidSegmentRangeError("赛段太短，至少 1 公里")

    # 3.5 DEM 海拔替换（v3 / 2026-05-14）：用 SRTM 30m DEM 查表替换 GPS 海拔。
    # 详 service_create.create_segment 同步说明 / from-gpx 路径同款逻辑。
    # 用 SimpleNamespace wrapper 不动 ORM 实例，避免 SQLAlchemy 误以为要 update Trackpoint。
    dem_coords = [(tp.latitude, tp.longitude) for tp in tps]
    dem_elevations = query_elevations(dem_coords)
    tps_with_dem = [
        SimpleNamespace(
            latitude=tp.latitude,
            longitude=tp.longitude,
            elevation=(float(dem_elevations[i]) if dem_elevations[i] is not None else tp.elevation),
        )
        for i, tp in enumerate(tps)
    ]

    # 用 DEM 替换后的海拔算累计爬升 / 下降
    elevation_gain = 0.0
    elevation_loss = 0.0
    for i in range(1, len(tps_with_dem)):
        prev = tps_with_dem[i - 1]
        curr = tps_with_dem[i]
        if prev.elevation is not None and curr.elevation is not None:
            diff = curr.elevation - prev.elevation
            if diff > 0:
                elevation_gain += diff
            else:
                elevation_loss += abs(diff)
    avg_gradient = (elevation_gain - elevation_loss) / distance * 100 if distance > 0 else 0.0

    # 4. Hausdorff 查重：用共享 helper（防御 / 跨 from-gpx + from-activity 一致 / dialect 守卫含 SQLite 兼容）
    coords = ", ".join(f"{p.longitude} {p.latitude}" for p in tps)
    wkt = f"LINESTRING({coords})"
    if _check_hausdorff_overlap(db, wkt):
        raise SegmentOverlapError("新赛段与已有赛段高度重叠")

    # 5. 自动推断城市和难度。调用方没填时，系统用起点和坡度尺自己判断。
    # 注意 is None 才代表未传，不能用 `if not city`，因为空字符串也可能是调用方错误输入。
    start = tps[0]
    inferred_city = city
    if inferred_city is None:
        inferred_city = infer_city_from_coords(start.latitude, start.longitude)

    # max_gradient 用 DEM 替换后的海拔算（不是原 GPS）—— 这是 v3 关键修复点
    max_gradient = calculate_max_gradient(tps_with_dem)
    inferred_difficulty = difficulty
    if inferred_difficulty is None:
        inferred_difficulty = calculate_difficulty(distance, elevation_gain, max_gradient)

    # 5.5 海拔曲线：DEM 替换后基本所有点都有 ele；极少数 DEM 查不到时降级。
    elevation_profile = None
    if all(tp.elevation is not None for tp in tps_with_dem):
        elevation_profile = _sample_elevation_profile(
            [{"ele": tp.elevation} for tp in tps_with_dem],
            target_count=80,
        )

    # 6. 构建 PostGIS LineString。WKT 坐标顺序是"经度 纬度"，和日常说法相反。
    path = WKTElement(wkt, srid=4326)

    # 7. 插入并 flush，让调用方在同一个事务里能拿到 id；是否 commit 由外层决定。
    # 类比：先把报名表放进柜台系统并拿到流水号，最后盖章提交交给调用方统一处理。
    segment = Segment(
        name=name,
        distance=distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        avg_gradient=avg_gradient,
        elevation_profile=json.dumps(elevation_profile) if elevation_profile is not None else None,
        start_lat=start.latitude,
        start_lon=start.longitude,
        end_lat=tps[-1].latitude,
        end_lon=tps[-1].longitude,
        reference_line=path,
        city=inferred_city,
        difficulty=inferred_difficulty,
        max_gradient=max_gradient,
    )
    db.add(segment)
    db.flush()
    return segment
