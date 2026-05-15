"""
赛段查询相关业务逻辑。

从 service.py 拆出，保持函数签名、返回值和业务行为不变。
"""

import json

from geoalchemy2 import Geography
from sqlalchemy import and_, cast, func, or_
from sqlalchemy.orm import Session

from app.activity.models import Activity, ActivityPrivacy
from app.activity.service import _can_view_activity
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
        # Sprint 5 task-3 真用 codex 第 2 轮 review Important：escape SQL wildcard（% _）
        # 跟 app/user/service.py get_active_users 同 pattern / 防用户输 % 匹配所有 segment
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Segment.name.ilike(f"%{escaped}%", escape="\\"))
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
            "created_at": segment.created_at,  # Sprint 4 task-4.4 NEW 标签判断（30 天内）
        })

    return items, total


# ==================== 排行榜查询 helper（task-4.2） ====================

def _user_best_effort_subquery(
    db: Session,
    segment_id: int,
    current_user_id: int | None,
):
    """
    构建子查询：每个用户在该赛段的"最佳一条 effort"。

    用窗口函数 ROW_NUMBER() OVER PARTITION BY user_id ORDER BY elapsed_time ASC：
    给每个人的多条 effort 按用时升序编号，外层只保留 rn=1（最快那条）。

    类比：班级里每个学生考了好几次，给每个学生的成绩从高到低排号，
    只挑每人最高那一份当作排行榜上的代表。

    同时附带 task-4.1 隐私过滤（OR 三支）：他人私密 effort 直接消失，
    自己的私密 effort 保留（在外层根据 privacy_visibility 渲染 is_private_self）。
    """
    row_number = func.row_number().over(
        partition_by=SegmentEffort.user_id,
        # 同用时时用 id 兜底排序：让结果稳定可复现（防 SQLite/PG 行为差异）
        order_by=[SegmentEffort.elapsed_time.asc(), SegmentEffort.id.asc()],
    ).label("rn")

    return (
        db.query(
            SegmentEffort.id.label("effort_id"),
            SegmentEffort.user_id.label("user_id"),
            SegmentEffort.activity_id.label("activity_id"),
            SegmentEffort.elapsed_time.label("elapsed_time"),
            SegmentEffort.avg_speed.label("avg_speed"),
            SegmentEffort.avg_power.label("avg_power"),
            SegmentEffort.created_at.label("created_at"),
            ActivityPrivacy.visibility.label("privacy_visibility"),
            ActivityPrivacy.hide_power.label("privacy_hide_power"),  # task-4.6：挖功率字段用
            row_number,
        )
        .outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
        .filter(SegmentEffort.segment_id == segment_id)
        .filter(
            or_(
                ActivityPrivacy.visibility == "public",
                ActivityPrivacy.visibility.is_(None),
                SegmentEffort.user_id == current_user_id,
            )
        )
        .subquery()
    )


# ==================== 查询赛段详情 ====================

def get_segment_detail(
    db: Session,
    segment_id: int,
    current_user_id: int | None = None,
) -> dict:
    """
    获取赛段详情 + 排行榜前 20 名。

    排行榜按用时从短到长排序（越快越靠前），
    类似马拉松成绩榜——跑得越快排名越高。
    JOIN users 表拿昵称和头像，让排行榜不只是冷冰冰的数字。

    task-4.2：每个用户只显示最佳那一条 effort（去重）。
    task-4.1 隐私行为：
    - 其他人看排行榜：他人设了私密的成绩**完全不显示**
    - 登录用户看排行榜：能看到自己的私密成绩排在原位 + is_private_self=true 标记
    - 未登录访问：私密成绩全部消失（current_user_id=None，OR 第三支不生效）
    """
    segment = db.query(Segment).filter_by(id=segment_id).first()
    if segment is None:
        raise ValueError("赛段不存在")

    # 排行榜 TOP20：用 helper 子查询拿"每人最佳"，外层 JOIN User 拿昵称车型
    best = _user_best_effort_subquery(db, segment_id, current_user_id)
    leaderboard_rows = (
        db.query(
            best.c.user_id,
            best.c.activity_id,
            User.nickname,
            User.avatar_url,
            best.c.elapsed_time,
            best.c.avg_speed,
            best.c.avg_power,
            User.bike_type,
            best.c.created_at,
            best.c.privacy_visibility,
            best.c.privacy_hide_power,  # task-4.6
        )
        .select_from(best)
        .join(User, User.id == best.c.user_id)
        .filter(best.c.rn == 1)
        .order_by(best.c.elapsed_time.asc(), best.c.effort_id.asc())
        .limit(20)
        .all()
    )

    # 组装排行榜（rank 在过滤后再编号 / 一人一行）
    leaderboard = []
    for rank, row in enumerate(leaderboard_rows, start=1):
        # task-4.6：他人查看时 owner 设了 hide_power → avg_power 挖空成 None
        is_other_viewer = (row.user_id != current_user_id)
        avg_power = None if (is_other_viewer and row.privacy_hide_power) else row.avg_power
        leaderboard.append({
            "rank": rank,
            "user_id": row.user_id,
            "activity_id": row.activity_id,
            "nickname": row.nickname,
            "avatar_url": row.avatar_url,
            "elapsed_time": row.elapsed_time,
            "avg_speed": row.avg_speed,
            "avg_power": avg_power,
            "bike_type": row.bike_type,
            "created_at": row.created_at,
            "is_private_self": (
                row.privacy_visibility == "private"
                and row.user_id == current_user_id
            ),
        })

    # elevation_profile 在 DB 里是 JSON 字符串（service_create.py:152 写入时 json.dumps），
    # 这里反序列化回 Python list 让 schema 自动校验+前端直接消费。
    # 老数据可能为 NULL（建表早期没此字段），保持 None 兜底。
    elevation_profile = (
        json.loads(segment.elevation_profile)
        if segment.elevation_profile
        else None
    )

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
        "elevation_profile": elevation_profile,  # 约 80 个海拔采样数值（米），前端画曲线
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
    current_user_id: int | None = None,
) -> tuple[list[dict], int, int | None, int | None]:
    """
    获取某赛段的完整排行榜（分页，支持车型过滤 / 可选登录用户的 my_rank）。

    与 get_segment_detail 里的 TOP20 不同，这个函数支持：
    - 分页翻阅完整排行榜（不只前 20 名）
    - 按车型过滤（只看公路车、砾石车等）
    - Sprint 4 D7 hotfix：登录用户传 current_user_id → 算 my_rank + my_elapsed_time
      （让前端在 top 10 外也能精确展示"我排第几"，不用 # 占位）

    rank 的计算考虑了分页偏移：第 2 页第 1 条的 rank 不是 1 而是 page_size+1。

    返回 4 元组：(items, total, my_rank, my_elapsed_time)
    - my_rank：登录用户在该赛段的排名（基于 PR / 比我快的人数 + 1 / 跟主榜升序一致 / task-4.2 去重）
    - my_elapsed_time：登录用户的 PR 用时（秒）
    - 未登录 / 没骑过 / bike_type filter 排除了我的车型 → 两字段为 None
    """
    segment = db.query(Segment).filter_by(id=segment_id).first()
    if segment is None:
        raise ValueError("赛段不存在")

    # task-4.2：基于 helper 子查询，每个用户在主榜上只出现 1 次（最快那条）
    best = _user_best_effort_subquery(db, segment_id, current_user_id)
    query = (
        db.query(
            best.c.user_id,
            best.c.activity_id,
            User.nickname,
            User.avatar_url,
            best.c.elapsed_time,
            best.c.avg_speed,
            best.c.avg_power,
            User.bike_type,
            best.c.created_at,
            best.c.privacy_visibility,
            best.c.privacy_hide_power,  # task-4.6
        )
        .select_from(best)
        .join(User, User.id == best.c.user_id)
        .filter(best.c.rn == 1)
    )

    # 可选：按车型过滤（外层 JOIN User 后加 / 不影响子查询窗口分组）
    if bike_type is not None:
        query = query.filter(User.bike_type == bike_type)

    # 按用时升序（越快越靠前）
    query = query.order_by(best.c.elapsed_time.asc(), best.c.effort_id.asc())

    # task-4.2：total 也是"人数"（基于去重后的查询 count）
    total = query.count()

    rows = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # rank 从分页偏移开始计算（每人一行 / 不重复 / 不跳号）
    start_rank = (page - 1) * page_size + 1
    items = []
    for i, row in enumerate(rows):
        # task-4.6：他人查看时 owner 设了 hide_power → avg_power 挖空成 None
        is_other_viewer = (row.user_id != current_user_id)
        avg_power = None if (is_other_viewer and row.privacy_hide_power) else row.avg_power
        items.append({
            "rank": start_rank + i,
            "user_id": row.user_id,
            "activity_id": row.activity_id,
            "nickname": row.nickname,
            "avatar_url": row.avatar_url,
            "elapsed_time": row.elapsed_time,
            "avg_speed": row.avg_speed,
            "avg_power": avg_power,
            "bike_type": row.bike_type,
            "created_at": row.created_at,
            "is_private_self": (
                row.privacy_visibility == "private"
                and row.user_id == current_user_id
            ),
        })

    # Sprint 4 D7 hotfix：算登录用户的 my_rank + my_elapsed_time
    my_rank = None
    my_elapsed_time = None
    if current_user_id is not None:
        # 我的 PR：MIN(elapsed_time WHERE user_id=me, segment_id=X)
        # 同时拿 PR 那条 effort 的 id —— 用于 my_rank 计算时跟主榜的 (elapsed_time, effort_id) tiebreaker 对齐。
        # bike_type filter 跟主榜一致：如果筛了车型 / 我的 PR 也只看该车型 effort
        # 不需要 privacy 过滤：本来就只查自己的 effort，自己看自己的所有成绩（含私密）。
        my_pr_query = (
            db.query(SegmentEffort.elapsed_time, SegmentEffort.id)
            .filter(SegmentEffort.segment_id == segment_id)
            .filter(SegmentEffort.user_id == current_user_id)
        )
        if bike_type is not None:
            # JOIN User 看 bike_type；如果用户车型不匹配 / 查不到 effort / my_pr=None
            my_pr_query = my_pr_query.join(User, User.id == SegmentEffort.user_id).filter(User.bike_type == bike_type)
        my_pr_row = my_pr_query.order_by(SegmentEffort.elapsed_time.asc(), SegmentEffort.id.asc()).first()

        if my_pr_row is not None:
            my_elapsed_time = my_pr_row[0]
            my_pr_effort_id = my_pr_row[1]
            # task-4.2：my_rank = "比我快的人数" + 1（DISTINCT user_id）
            # Codex 异源审 I2：tiebreaker 用 (elapsed_time, effort_id) 跟主榜 enumerate 一致，
            # 否则"不同用户同秒"时 my_rank 跟主榜显示的 rank 数字分叉。
            # "比我快" = elapsed_time < my_pr OR (elapsed_time == my_pr AND effort_id < my_pr_id)
            rank_query = (
                db.query(func.count(func.distinct(SegmentEffort.user_id)))
                .outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
                .filter(SegmentEffort.segment_id == segment_id)
                .filter(
                    or_(
                        SegmentEffort.elapsed_time < my_elapsed_time,
                        and_(
                            SegmentEffort.elapsed_time == my_elapsed_time,
                            SegmentEffort.id < my_pr_effort_id,
                        ),
                    )
                )
                .filter(
                    or_(
                        ActivityPrivacy.visibility == "public",
                        ActivityPrivacy.visibility.is_(None),
                        SegmentEffort.user_id == current_user_id,
                    )
                )
            )
            if bike_type is not None:
                rank_query = rank_query.join(User, User.id == SegmentEffort.user_id).filter(User.bike_type == bike_type)
            my_rank = rank_query.scalar() + 1

    return items, total, my_rank, my_elapsed_time


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
        # task-4.2：数"比我快的人数"（DISTINCT user_id），不是"effort 条数"——
        # 跟主排行榜（每人一行）保持一致；CCF 骑 5 次比我快只算 1 人不算 5 人。
        # task-4.1 隐私过滤：他人的私密 effort 不算进 faster_count，自己的正常计入。
        faster_count = (
            db.query(func.count(func.distinct(SegmentEffort.user_id)))
            .outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
            .filter(
                SegmentEffort.segment_id == effort.segment_id,
                SegmentEffort.elapsed_time < effort.elapsed_time,
            )
            .filter(
                or_(
                    ActivityPrivacy.visibility == "public",
                    ActivityPrivacy.visibility.is_(None),
                    SegmentEffort.user_id == user_id,
                )
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

    权限：本人永远可看；公开活动别人也可看；私密活动对别人表现成不存在。
    """
    # 权限检查：这次骑行是不是你的？
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        raise ValueError("活动不存在")
    if not _can_view_activity(activity, user_id):
        raise ValueError("活动不存在")

    # 查出这次骑行匹配到的所有赛段成绩
    # task-4.3 集成审 I1：拿 effort.id 用于 is_pr tiebreaker，跟 get_my_efforts_on_segment 一致
    efforts = (
        db.query(
            SegmentEffort.id.label("effort_id"),
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
        # rank：在这条赛段所有成绩中排第几
        # task-4.2：数"比我快的人数"（DISTINCT user_id），不是"effort 条数"——
        # 跟主排行榜（每人一行）保持一致；否则 CCF 骑 5 次都比我快会把我从第 2 挤到第 6。
        # task-4.1 隐私过滤：他人的私密 effort 不算进 faster_count，自己的正常计入。
        faster_count = (
            db.query(func.count(func.distinct(SegmentEffort.user_id)))
            .outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
            .filter(
                SegmentEffort.segment_id == effort.segment_id,
                SegmentEffort.elapsed_time < effort.elapsed_time,
            )
            .filter(
                or_(
                    ActivityPrivacy.visibility == "public",
                    ActivityPrivacy.visibility.is_(None),
                    SegmentEffort.user_id == user_id,
                )
            )
            .scalar()
        )
        rank = faster_count + 1

        # is_pr：这次成绩是不是我在这条赛段的个人最佳？
        # task-4.3 集成审 I1：tiebreaker 用 (elapsed_time, id) 跟 get_my_efforts_on_segment 一致——
        # 同秒并列时只有 id 最小那条算 PR，避免成绩列表页 vs 骑行详情页两个屏幕展示的黄点数量不一致。
        my_best_row = (
            db.query(SegmentEffort.elapsed_time, SegmentEffort.id)
            .filter(
                SegmentEffort.segment_id == effort.segment_id,
                SegmentEffort.user_id == user_id,
            )
            .order_by(SegmentEffort.elapsed_time.asc(), SegmentEffort.id.asc())
            .first()
        )
        is_pr = (
            my_best_row is not None
            and (my_best_row[0], my_best_row[1]) == (effort.elapsed_time, effort.effort_id)
        )

        # task-4.6：他人查看公开活动时按 owner 的 hide_power 挖空 avg_power
        is_other_viewer = (activity.user_id != user_id)
        hide_power = (
            is_other_viewer
            and activity.privacy is not None
            and activity.privacy.hide_power
        )
        avg_power = None if hide_power else effort.avg_power

        items.append({
            "segment_id": effort.segment_id,
            "segment_name": effort.segment_name,
            "elapsed_time": effort.elapsed_time,
            "avg_speed": effort.avg_speed,
            "avg_power": avg_power,
            "rank": rank,
            "is_pr": is_pr,
        })

    return items


# ==================== 我在某赛段的所有成绩（task-4.3） ====================

def get_my_efforts_on_segment(
    db: Session, segment_id: int, user_id: int
) -> list[dict]:
    """
    返回当前登录用户在某个赛段的全部成绩——"我在妙峰山骑了 5 次都长啥样"。

    跟主排行榜（每人一行）不同：这是我自己的成绩单，5 次 effort 全部列出来。

    ⚠ 时间字段陷阱（2026-05-15 Tim 真用回归发现）：
    必须用 Activity.started_at（真实骑行时间）做排序和年份分组，
    绝对不要用 SegmentEffort.created_at（effort 写入 DB 那一刻）——
    Strava 自动同步会把一堆活动在同一秒批量解析，所有 effort 的 created_at
    都变成"同步那一刻"，年份分组全挤到当年，排序也乱。
    详见 memory `feedback_time_field_use_business_not_db_writetime.md`。

    is_pr 标记：5 次里最快那条标 true（图 1 黄色小圆点）。
    并列 tiebreaker 跟主榜 task-4.2 一致：(elapsed_time, effort.id) 最小那条算 PR。
    """
    # 校验赛段存在（404 而不是 200 []）
    if db.query(Segment.id).filter_by(id=segment_id).first() is None:
        raise ValueError("赛段不存在")

    # JOIN Activity 拿 started_at（真实骑行时间 / 不是 effort.created_at DB 写入时间）
    rows = (
        db.query(
            SegmentEffort.id.label("effort_id"),
            SegmentEffort.activity_id,
            SegmentEffort.elapsed_time,
            SegmentEffort.avg_speed,
            SegmentEffort.avg_power,
            Activity.started_at.label("started_at"),
        )
        .join(Activity, Activity.id == SegmentEffort.activity_id)
        .filter(
            SegmentEffort.segment_id == segment_id,
            SegmentEffort.user_id == user_id,
        )
        # nullslast：极少数 strava 活动 started_at 为 NULL 时降级到 effort.id 兜底
        .order_by(Activity.started_at.desc().nullslast(), SegmentEffort.id.desc())
        .all()
    )
    if not rows:
        return []

    # PR 用 (elapsed_time, effort_id) tuple 兜底——同秒并列时取 id 最小的（跟主榜一致）
    pr_key = min((r.elapsed_time, r.effort_id) for r in rows)

    return [
        {
            "activity_id": r.activity_id,
            "elapsed_time": r.elapsed_time,
            "avg_speed": r.avg_speed,
            "avg_power": r.avg_power,
            # 字段名保留 created_at 兼容前端但语义是 Activity.started_at（真骑行时间）
            "created_at": r.started_at,
            "is_pr": (r.elapsed_time, r.effort_id) == pr_key,
        }
        for r in rows
    ]
