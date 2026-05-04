"""
赛段查询相关业务逻辑。

从 service.py 拆出，保持函数签名、返回值和业务行为不变。
"""

from geoalchemy2 import Geography
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.segment.models import Segment, SegmentEffort
from app.user.models import User


# ==================== 查询赛段列表 ====================

def get_segment_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    near_lat: float | None = None,
    near_lon: float | None = None,
    radius: float = 50000,
    search: str | None = None,
    city: str | None = None,
    difficulty: str | None = None,
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
    # v5 搜索筛选：这些条件像在赛段目录上叠三张透明筛网。
    # 注意用 is not None，空字符串也是调用方明确传入的搜索值，不用 truthiness 猜语义。
    if search is not None:
        filters.append(Segment.name.ilike(f"%{search}%"))
    if city is not None:
        filters.append(Segment.city == city)
    if difficulty is not None:
        filters.append(Segment.difficulty == difficulty)

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
            # v5 task-1.A.3 新增 4 字段（task-1.A.2 已落 DB 但 dict 未带，本次补全）
            "avg_gradient": segment.avg_gradient,
            "max_gradient": segment.max_gradient,
            "difficulty": segment.difficulty,
            "city": segment.city,
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
        # v5 task-1.A.3 新增 4 字段（spec §4.1：详情响应加 max_gradient/city/difficulty）
        "avg_gradient": segment.avg_gradient,
        "max_gradient": segment.max_gradient,
        "difficulty": segment.difficulty,
        "city": segment.city,
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
        .order_by(SegmentEffort.start_index)
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
