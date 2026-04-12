"""
赛段模块的业务逻辑层——赛道管理的"后台办事员"。

和其他模块的 service.py 一样的角色：
router 是前台接待员（接请求、回结果），service 是后台办事员（处理业务、操作数据库）。

负责四件核心事务：
1. 创建赛段：管理员提交坐标 → 计算距离/爬升 → 存入数据库
2. 查询赛段列表：支持"附近赛段"的地理位置筛选
3. 查询赛段详情：赛段信息 + 排行榜 TOP20
4. 排行榜查询 + 用户成绩查询

自动匹配逻辑（Worker 调用）已拆分到 auto_match.py，避免本文件超过 500 行红线。

注意事项：
- 管理员权限在 service 层校验（查 User.is_admin）
- PostGIS 查询必须转 geography 类型，否则距离单位是度不是米
- 距离单位转换：数据库存米，API 返回公里
"""

import json

from geoalchemy2 import Geography
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.segment._geo_utils import _haversine, _sample_elevation_profile
from app.segment.coord_convert import convert_points_to_wgs84
from app.segment.models import Segment, SegmentEffort
from app.user.models import User


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

    # 计算累计爬升、累计下降、平均坡度、海拔缩略图
    # 只有所有坐标点都带海拔数据（ele 字段）时才能计算，否则四个字段全为 None
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

    db.add(segment)
    db.commit()
    db.refresh(segment)

    return segment


# ==================== 查询赛段列表 ====================

def get_segment_list(
    db: Session,
    page: int,
    page_size: int,
    near_lat: float | None = None,
    near_lon: float | None = None,
    radius: float = 50000,
) -> tuple[list[dict], int]:
    """
    查询赛段列表（分页），支持按地理位置筛选附近赛段。

    附近搜索原理：
    用 PostGIS 的 ST_DWithin 函数画一个"圆圈"——
    以指定坐标为圆心、radius 为半径，看哪些赛段的参考路线落在圆圈内。
    必须转 geography 类型，否则距离单位是"度"而不是"米"。

    返回 (赛段列表, 总条数)，每条赛段带 entries（成绩记录数）。
    """
    # 构建过滤条件（如果有附近搜索参数）
    # ST_SetSRID 给坐标点加上"坐标系标签"（4326 = WGS84，GPS 用的标准坐标系）
    # cast(..., Geography) 把几何对象转成地理对象，这样 ST_DWithin 才用米做单位
    filters = []
    if near_lat is not None and near_lon is not None:
        filters.append(
            func.ST_DWithin(
                cast(Segment.reference_line, Geography),
                cast(
                    func.ST_SetSRID(func.ST_MakePoint(near_lon, near_lat), 4326),
                    Geography,
                ),
                radius,
            )
        )

    # 总条数（独立查询，不含 GROUP BY，避免计数偏差）
    count_query = db.query(func.count(Segment.id))
    for f in filters:
        count_query = count_query.filter(f)
    total = count_query.scalar()

    # 分页查询：赛段 + 每个赛段的成绩记录数
    # LEFT JOIN：即使没有任何成绩记录的赛段也会出现在列表中（entries=0）
    entries_count = func.count(SegmentEffort.id).label("entries")
    query = (
        db.query(Segment, entries_count)
        .outerjoin(SegmentEffort, SegmentEffort.segment_id == Segment.id)
        .group_by(Segment.id)
    )
    for f in filters:
        query = query.filter(f)

    results = (
        query
        .order_by(Segment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 组装返回数据，距离从米转公里
    items = []
    for segment, entries in results:
        items.append({
            "id": segment.id,
            "name": segment.name,
            "distance": round(segment.distance / 1000.0, 2),
            "elevation_gain": segment.elevation_gain,
            "start_lat": segment.start_lat,
            "start_lon": segment.start_lon,
            "end_lat": segment.end_lat,
            "end_lon": segment.end_lon,
            "entries": entries,
        })

    return items, total


# ==================== 查询赛段详情 ====================

def get_segment_detail(db: Session, segment_id: int) -> dict:
    """
    获取赛段详情 + 排行榜前 20 名。

    排行榜按用时从短到长排序（越快越靠前），
    类似马拉松成绩榜——跑得越快排名越高。
    JOIN users 表拿昵称和头像，让排行榜不只是冷冰冰的数字。
    """
    segment = db.query(Segment).filter_by(id=segment_id).first()
    if segment is None:
        raise ValueError("赛段不存在")

    # 查排行榜 TOP20
    # JOIN User 表：用 user_id 关联，拿到昵称和头像
    # ORDER BY elapsed_time ASC：用时最短的排最前
    leaderboard_rows = (
        db.query(
            SegmentEffort.user_id,
            User.nickname,
            User.avatar_url,
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.avg_power,
            User.bike_type,
            SegmentEffort.created_at,
        )
        .join(User, User.id == SegmentEffort.user_id)
        .filter(SegmentEffort.segment_id == segment_id)
        .order_by(SegmentEffort.elapsed_time.asc())
        .limit(20)
        .all()
    )

    # 组装排行榜（加上 rank 序号，从 1 开始）
    leaderboard = []
    for rank, row in enumerate(leaderboard_rows, start=1):
        leaderboard.append({
            "rank": rank,
            "user_id": row.user_id,
            "nickname": row.nickname,
            "avatar_url": row.avatar_url,
            "elapsed_time": row.elapsed_time,
            "avg_speed": row.avg_speed,
            "avg_power": row.avg_power,
            "bike_type": row.bike_type,
            "created_at": row.created_at,
        })

    return {
        "id": segment.id,
        "name": segment.name,
        "description": segment.description,
        "distance": round(segment.distance / 1000.0, 2),  # 米 → 公里
        "elevation_gain": segment.elevation_gain,
        "start_lat": segment.start_lat,
        "start_lon": segment.start_lon,
        "end_lat": segment.end_lat,
        "end_lon": segment.end_lon,
        "match_tolerance": segment.match_tolerance,
        "min_match_ratio": segment.min_match_ratio,
        "created_at": segment.created_at,
        "leaderboard": leaderboard,
    }


# ==================== 排行榜查询（Task 4.5） ====================

def get_leaderboard(
    db: Session,
    segment_id: int,
    page: int,
    page_size: int,
    bike_type: str | None = None,
) -> tuple[list[dict], int]:
    """
    获取某赛段的完整排行榜（分页，支持车型过滤）。

    与 get_segment_detail 里的 TOP20 不同，这个函数支持：
    - 分页翻阅完整排行榜（不只前 20 名）
    - 按车型过滤（只看公路车、砾石车等）

    rank 的计算考虑了分页偏移：第 2 页第 1 条的 rank 不是 1 而是 page_size+1。
    """
    segment = db.query(Segment).filter_by(id=segment_id).first()
    if segment is None:
        raise ValueError("赛段不存在")

    # 基础查询：JOIN users 拿昵称头像车型
    query = (
        db.query(
            SegmentEffort.user_id,
            User.nickname,
            User.avatar_url,
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.avg_power,
            User.bike_type,
            SegmentEffort.created_at,
        )
        .join(User, User.id == SegmentEffort.user_id)
        .filter(SegmentEffort.segment_id == segment_id)
    )

    # 可选：按车型过滤
    if bike_type is not None:
        query = query.filter(User.bike_type == bike_type)

    # 按用时升序（越快越靠前）
    query = query.order_by(SegmentEffort.elapsed_time.asc())

    total = query.count()

    rows = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # rank 从分页偏移开始计算
    start_rank = (page - 1) * page_size + 1
    items = []
    for i, row in enumerate(rows):
        items.append({
            "rank": start_rank + i,
            "user_id": row.user_id,
            "nickname": row.nickname,
            "avatar_url": row.avatar_url,
            "elapsed_time": row.elapsed_time,
            "avg_speed": row.avg_speed,
            "avg_power": row.avg_power,
            "bike_type": row.bike_type,
            "created_at": row.created_at,
        })

    return items, total


# ==================== 用户赛段成绩（Task 4.5） ====================

def get_user_efforts(db: Session, user_id: int) -> list[dict]:
    """
    获取当前用户在所有赛段的成绩。

    好比一个运动员查自己的"全赛道成绩单"：
    在哪些赛道跑过、用时多少、排第几名。

    rank 通过子查询计算：数一数同赛段中用时比我短的人有几个，+1 就是我的名次。
    """
    # 查出该用户的所有赛段成绩，JOIN segments 拿赛段名
    efforts = (
        db.query(
            SegmentEffort.segment_id,
            Segment.name.label("segment_name"),
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.created_at,
        )
        .join(Segment, Segment.id == SegmentEffort.segment_id)
        .filter(SegmentEffort.user_id == user_id)
        .order_by(SegmentEffort.created_at.desc())
        .all()
    )

    # TODO: 当前用 N+1 查询计算排名（每条成绩单独发一次 COUNT SQL）。
    # 100 用户量级无性能问题；用户量上千后考虑用窗口函数 RANK() 一次性算排名。
    items = []
    for effort in efforts:
        # 计算该成绩在对应赛段中的排名
        # "比我快的人数 + 1 = 我的名次"
        faster_count = (
            db.query(func.count(SegmentEffort.id))
            .filter(
                SegmentEffort.segment_id == effort.segment_id,
                SegmentEffort.elapsed_time < effort.elapsed_time,
            )
            .scalar()
        )
        rank = faster_count + 1

        items.append({
            "segment_id": effort.segment_id,
            "segment_name": effort.segment_name,
            "elapsed_time": effort.elapsed_time,
            "avg_speed": effort.avg_speed,
            "rank": rank,
            "created_at": effort.created_at,
        })

    return items


# ==================== 活动途经赛段（Task 4.6） ====================

def get_activity_segments(db: Session, activity_id: int, user_id: int) -> list[dict]:
    """
    获取某次骑行途经的所有赛段成绩。

    好比跑完马拉松后查"分段计时牌"：
    经过了哪些计时点、每段用了多久、排第几、是不是个人最快。

    权限：只能查看自己的活动，他人的返回 403。
    """
    # 权限检查：这次骑行是不是你的？
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if activity.user_id != user_id:
        raise PermissionError("无权查看此活动")

    # 查出这次骑行匹配到的所有赛段成绩
    efforts = (
        db.query(
            SegmentEffort.segment_id,
            Segment.name.label("segment_name"),
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.avg_power,
        )
        .join(Segment, Segment.id == SegmentEffort.segment_id)
        .filter(SegmentEffort.activity_id == activity_id)
        .all()
    )

    # TODO: N+1 查询（每条 effort 发 2 次额外 SQL 算 rank 和 is_pr）。
    # 100 用户量级无性能问题；用户量上千后考虑用窗口函数一次性算。
    items = []
    for effort in efforts:
        # rank：在这条赛段所有成绩中排第几（用时比我短的人数 + 1）
        faster_count = (
            db.query(func.count(SegmentEffort.id))
            .filter(
                SegmentEffort.segment_id == effort.segment_id,
                SegmentEffort.elapsed_time < effort.elapsed_time,
            )
            .scalar()
        )
        rank = faster_count + 1

        # is_pr：这次成绩是不是我在这条赛段的个人最佳？
        # 查我在这条赛段的历史最短用时，如果等于这次用时就是 PR
        best_time = (
            db.query(func.min(SegmentEffort.elapsed_time))
            .filter(
                SegmentEffort.segment_id == effort.segment_id,
                SegmentEffort.user_id == user_id,
            )
            .scalar()
        )
        is_pr = (best_time == effort.elapsed_time)

        items.append({
            "segment_id": effort.segment_id,
            "segment_name": effort.segment_name,
            "elapsed_time": effort.elapsed_time,
            "avg_speed": effort.avg_speed,
            "avg_power": effort.avg_power,
            "rank": rank,
            "is_pr": is_pr,
        })

    return items


# ==================== 删除赛段 ====================

def delete_segment(db: Session, segment_id: int, user_id: int) -> None:
    """
    删除赛段——管理员专用。

    删除赛段时，该赛段下的所有成绩记录一并删除。
    好比拆掉一条赛道：赛道没了，上面的成绩自然作废。
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user or not user.is_admin:
        raise PermissionError("需要管理员权限")

    segment = db.query(Segment).filter_by(id=segment_id).first()
    if segment is None:
        raise ValueError("赛段不存在")

    # 先删成绩记录（外键无 CASCADE，需手动删）
    db.query(SegmentEffort).filter_by(segment_id=segment_id).delete()
    db.delete(segment)
    db.commit()
