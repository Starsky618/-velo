"""
赛段自动匹配引擎——"体育场自动计时系统"。

Worker 解析完骑行轨迹后，调用这里的函数自动检查：
这次骑行经过了哪些已知赛段？经过了就记录成绩。

好比马拉松比赛的芯片计时：
选手跑完后不需要手动申报成绩，计时毯自动感应、自动录入。

处理流程：
1. PostGIS 粗筛：用轨迹的凸包快速排除不可能经过的赛段
2. 取轨迹点：从数据库加载全部 GPS 点
3. 逐赛段精确匹配：调用 matcher.match_segment() 做点对点匹配
4. 记录成绩：写入 segment_efforts 表

注意事项：
- 由 Worker 在独立进程中调用，不在 FastAPI 请求上下文中
- 单个赛段匹配失败不影响其他赛段（SAVEPOINT 事务隔离）
- PostGIS 查询必须转 geography 类型，否则距离单位是度不是米
"""

import logging
import re

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.activity.models import Activity, Trackpoint
from app.notification.service import detect_events
from app.segment.matcher import match_segment
from app.segment.models import Segment, SegmentEffort

logger = logging.getLogger(__name__)


def _parse_linestring_wkt(wkt: str) -> list[tuple[float, float]]:
    """
    从 WKT 格式的 LINESTRING 中提取坐标点列表。

    PostGIS 返回的 WKT 格式是 "LINESTRING(lon1 lat1, lon2 lat2, ...)"。
    注意 WKT 中坐标顺序是 (经度, 纬度)，我们需要返回 (纬度, 经度)，
    因为 matcher 的接口用 (lat, lon) 顺序。
    """
    # 提取括号内的坐标字符串
    m = re.search(r"LINESTRING\s*\((.+)\)", wkt, re.IGNORECASE)
    if not m:
        return []

    coords = []
    for pair in m.group(1).split(","):
        parts = pair.strip().split()
        lon, lat = float(parts[0]), float(parts[1])
        coords.append((lat, lon))  # 返回 (lat, lon) 顺序
    return coords


def match_activity_against_segments(activity_id: int, db: Session) -> None:
    """
    自动检查一次骑行是否经过了已知赛段，匹配成功则记录成绩。

    由 Worker 在 GPX 解析完成后调用（步骤 11）。
    好比体育场的"自动计时系统"：选手跑完后，系统自动扫描所有赛道，
    看选手经过了哪些，把成绩自动录入。

    关键规则：
    - 单个赛段匹配失败不影响其他赛段（每个赛段独立 SAVEPOINT）
    - 粗筛用 geography 转换，距离单位是米（100 米容差）
    - avg_speed 用赛段固定距离/实际用时，比用 GPS 累计距离更稳定
    """
    # 先查出活动对应的用户 ID（写入成绩时需要）
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        return
    user_id = activity.user_id

    # ===== 第 1 步：PostGIS 粗筛 =====
    # 用 ST_ConvexHull + ST_Collect 把轨迹点"套上一个最小外框"（凸包），
    # 然后用 ST_DWithin 检查哪些赛段参考线与这个外框距离 ≤100 米。
    # 这一步快速排除 99% 不可能经过的赛段，避免对每条赛段都做精确匹配。
    trackpoints_hull = (
        select(
            cast(
                func.ST_ConvexHull(func.ST_Collect(Trackpoint.geom)),
                Geography,
            )
        )
        .where(Trackpoint.activity_id == activity_id)
        .scalar_subquery()
    )

    candidates = (
        db.query(Segment, func.ST_AsText(Segment.reference_line).label("ref_wkt"))
        .filter(
            func.ST_DWithin(
                cast(Segment.reference_line, Geography),
                trackpoints_hull,
                100,  # 100 米粗筛容差
            )
        )
        .all()
    )

    if not candidates:
        return  # 没有候选赛段，直接返回

    # ===== 第 2 步：取轨迹点 =====
    # 从数据库加载该活动的全部 trackpoints，按 seq 排序
    trackpoints = (
        db.query(Trackpoint)
        .filter_by(activity_id=activity_id)
        .order_by(Trackpoint.seq)
        .all()
    )

    if len(trackpoints) < 2:
        return

    # 把 ORM 对象映射成 matcher 期望的 dict 格式
    # Trackpoint 模型用全称（latitude/longitude/timestamp），matcher 用缩写（lat/lon/time）
    tp_dicts = [
        {
            "lat": tp.latitude,
            "lon": tp.longitude,
            "time": tp.timestamp,
            "seq": tp.seq,
        }
        for tp in trackpoints
    ]

    # ===== 第 3 步：逐赛段精确匹配 =====
    # 用 begin_nested()（SAVEPOINT）隔离每个赛段的操作。
    # 好比每次考试用单独的答题卡：一科交白卷不影响其他科的成绩。
    # 如果用 db.rollback()，会回滚整个事务（连前面赛段的成绩一起清掉）。
    # SAVEPOINT 只回滚到"存档点"，保留前面已写入的成绩。
    new_efforts = []  # 收集成功写入的 effort，commit 后逐个检测通知
    for segment, ref_wkt in candidates:
        savepoint = db.begin_nested()
        try:
            # 检查是否已有成绩记录（防止 Worker 重试导致重复写入）
            existing = db.query(SegmentEffort).filter_by(
                segment_id=segment.id, activity_id=activity_id,
            ).first()
            if existing:
                continue

            # 从 WKT 提取参考路线坐标
            reference_coords = _parse_linestring_wkt(ref_wkt)
            if len(reference_coords) < 2:
                continue

            # 调用精确匹配算法
            result = match_segment(
                trackpoints=tp_dicts,
                segment_start=(segment.start_lat, segment.start_lon),
                segment_end=(segment.end_lat, segment.end_lon),
                reference_coords=reference_coords,
                match_tolerance=segment.match_tolerance,
                min_match_ratio=segment.min_match_ratio,
            )

            if not result["matched"]:
                continue

            # ===== 第 4 步：计算成绩并记录 =====
            start_seq = result["start_index"]
            end_seq = result["end_index"]
            elapsed_time = result["elapsed_time"]

            # 防御：elapsed_time 必须为正数（matcher 已保证，此处二次校验）
            if elapsed_time <= 0:
                continue

            # avg_speed：用赛段的固定距离 / 实际用时，单位 km/h
            # 用赛段距离而非 GPS 累计距离，更稳定（不受 GPS 漂移影响）
            avg_speed = round((segment.distance / elapsed_time) * 3.6, 1)

            # avg_power：匹配区间内有功率数据的轨迹点求平均
            matched_powers = [
                tp.power for tp in trackpoints
                if start_seq <= tp.seq <= end_seq and tp.power is not None
            ]
            avg_power = (
                round(sum(matched_powers) / len(matched_powers), 1)
                if matched_powers else None
            )

            # 写入成绩记录
            effort = SegmentEffort(
                segment_id=segment.id,
                activity_id=activity_id,
                user_id=user_id,
                elapsed_time=elapsed_time,
                avg_speed=avg_speed,
                avg_power=avg_power,
                start_index=start_seq,
                end_index=end_seq,
            )
            db.add(effort)
            db.flush()
            new_efforts.append(effort)

        except Exception as e:
            # 只回滚当前赛段的 SAVEPOINT，不影响其他赛段已写入的成绩
            savepoint.rollback()
            logger.warning(f"赛段 {segment.id} 匹配失败: {e}")

    # 所有赛段匹配完成后统一提交
    db.commit()

    # ---- 成绩已全部 commit，逐个检测 PR/KOM 事件 ----
    # 必须在 commit 之后调用：detect_events 需要查排名，排名依赖已提交的数据。
    # detect_events 内部有 try/except + SAVEPOINT 隔离，单条失败不影响其他。
    for effort in new_efforts:
        detect_events(db, effort)
