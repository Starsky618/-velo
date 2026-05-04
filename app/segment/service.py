"""
赛段模块的业务逻辑层主入口——保持旧 import 路径不变。

本文件在 v5 task-pre-3.B 中完成物理拆分：
- 创建赛段相关逻辑搬到 service_create.py
- 查询赛段相关逻辑搬到 service_query.py
- 本文件保留删除、共享排名、即时反馈对比，并转导出拆分后的函数
"""

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.activity.models import Activity
from app.segment.models import Segment, SegmentEffort
from app.user.models import User

# v5 task-pre-3.B：service.py 793 行红灯 → 拆 3 文件，对外契约不变
# 调用方按 `from app.segment.service import xxx` 继续工作，不必感知文件分拆细节
from app.segment.service_create import (  # noqa: F401 — 转导出
    create_segment,
    create_segment_from_activity,
)
from app.segment.service_query import (  # noqa: F401 — 转导出
    get_activity_segments,
    get_leaderboard,
    get_segment_detail,
    get_segment_list,
    get_user_efforts,
)

# v5 task-1.A.1：算法纯函数实体住 algorithms.py（service.py 红灯保护）
# 这里转导出让 spec §3.1 / scripts/backfill_phase5.py 等调用方按
# `from app.segment.service import calculate_max_gradient, calculate_difficulty`
# 写的代码能正常 import，不必感知文件分拆细节
from app.segment.algorithms import (  # noqa: F401 — 转导出
    _haversine_distance,
    calculate_difficulty,
    calculate_max_gradient,
)


# ==================== 删除赛段 ====================

def delete_segment(db: Session, segment_id: int, user_id: int) -> None:
    """
    删除赛段——管理员专用。

    删除赛段时，该赛段下的所有成绩记录一并删除。
    好比拆掉一条赛道：赛道没了，上面的成绩自然作废。
    """
    user = db.query(User).filter_by(id=user_id).first()
    # 注意：deprecated legacy DELETE /api/segments/{id} 兼容到 2026-11-03，
    # 这段检查是旧路径的唯一 admin 防线；兼容期内不能删除。
    # 期满后也建议保留——新 admin router 走 require_admin + 此处校验形成双重防御，
    # 删除会让新路径降级为单层，且内部脚本直接调 service 时会裸奔。
    if not user or not user.is_admin:
        raise PermissionError("需要管理员权限")

    segment = db.query(Segment).filter_by(id=segment_id).first()
    if segment is None:
        raise ValueError("赛段不存在")

    # 先删成绩记录（外键无 CASCADE，需手动删）
    db.query(SegmentEffort).filter_by(segment_id=segment_id).delete()
    db.delete(segment)
    db.commit()


# ==================== 共享排名计算（notification 和 segment 共用） ====================

def get_effort_rank(db: Session, effort) -> int:
    """
    计算某条成绩在其赛段中的排名——"在这条赛道上你排第几"。

    共享函数：notification 模块和 segment 模块共用，避免排名逻辑重复。

    排名规则：COUNT(同赛段中"比我快"的成绩) + 1。
    并列处理：同 elapsed_time 时按 created_at 先到先得（tiebreaker）。
    好比百米决赛：两人都跑 10.0 秒，先撞线的排前面。

    使用索引：idx_efforts_segment_time (segment_id, elapsed_time)
    """
    # "比我快"的定义：
    # 1. elapsed_time 更短的（显然更快）
    # 2. elapsed_time 一样但 created_at 更早的（先到先得）
    faster_count = (
        db.query(func.count(SegmentEffort.id))
        .filter(
            SegmentEffort.segment_id == effort.segment_id,
            sa.or_(
                SegmentEffort.elapsed_time < effort.elapsed_time,
                sa.and_(
                    SegmentEffort.elapsed_time == effort.elapsed_time,
                    SegmentEffort.created_at < effort.created_at,
                ),
            ),
        )
        .scalar()
    )
    return faster_count + 1


# ==================== 我的赛段即时反馈（v5 task-1.A.2 / fix 对齐 spec §3.2.1） ====================

def get_my_effort_with_compare(
    db: Session,
    segment_id: int,
    user_id: int,
) -> dict:
    """
    返回当前用户在某赛段的即时反馈对比数据。

    设计思路（spec §3.2.1）：
    - 这是"骑完看进步"的语义，对比"这次 vs 上次 vs 个人最佳"
    - 不是"看排行榜第几名"——排名走另一个 leaderboard endpoint，不在这里
    - 类比成绩单：每次骑完打开看"上次 28 分钟，这次 26 分钟，PR 是 25 分钟"

    陷阱警示：
    - "current/last" 必须按 **Activity.started_at**（实际骑行时间）排序，
      不能按 SegmentEffort.created_at（DB 入库时间）。
      反例：用户先上传今天的骑行，再补传昨天的 GPX —— 用 created_at 会把昨天误标 current。
    - PR 与时序无关：用 MIN(elapsed_time) 子查询，不需 join。PR 是历史最佳，谁先创下不影响。
    - is_pr 仅判 current.elapsed_time == pr_time；并列时 is_pr=True（用时持平视为 PR）。
    - 用现有索引 idx_efforts_segment_user_time（app/segment/models.py）。

    返回 6 字段（与 spec §4.1 endpoint 响应字段一一对应）：
    - current_attempt_elapsed_time: int? 这次（按骑行时间最新一次）用时（秒）
    - last_attempt_elapsed_time:    int? 上次（按骑行时间倒数第二次）用时（秒）
    - pr_elapsed_time:              int? 个人最佳用时（秒）
    - current_attempt_diff_to_last: int? last - current（正数 = 变快，负数 = 变慢）
    - current_attempt_is_pr:        bool 这次是否破或持平 PR
    - is_first_attempt:             bool 是否首次（无 last 对比）

    无 effort 时（首次访问该赛段）：6 字段全 None / False / True 兜底，由 router 层包装回前端。
    404（segment 不存在）由 router 层显式查 db.get(Segment) 抛出，**本函数不抛 404**。
    """
    # 第 1 步：取最近 2 条 effort，按 Activity.started_at 倒序。
    # 类比翻日记本最新两页——"今天"和"昨天"；只取 2 条够算 current+last。
    efforts = (
        db.query(SegmentEffort)
        .join(Activity, SegmentEffort.activity_id == Activity.id)
        .filter(
            SegmentEffort.segment_id == segment_id,
            SegmentEffort.user_id == user_id,
        )
        .order_by(Activity.started_at.desc())
        .limit(2)
        .all()
    )

    # 第 2 步：算 PR（历史最佳用时）。
    # 用 MIN 子查询不 join Activity——PR 是历史最佳，与骑行时间先后无关。
    # 陷阱 #4：用 .scalar()（无记录返 None），不用 .one()（NoResultFound 抛 500）。
    pr_time = (
        db.query(func.min(SegmentEffort.elapsed_time))
        .filter(
            SegmentEffort.segment_id == segment_id,
            SegmentEffort.user_id == user_id,
        )
        .scalar()
    )

    # 第 3 步：兜底 — 用户在此赛段从未留 effort，6 字段全初始态。
    if not efforts:
        return {
            "current_attempt_elapsed_time": None,
            "last_attempt_elapsed_time": None,
            "pr_elapsed_time": None,
            "current_attempt_diff_to_last": None,
            "current_attempt_is_pr": False,
            "is_first_attempt": True,
        }

    current = efforts[0]
    last = efforts[1] if len(efforts) > 1 else None

    return {
        "current_attempt_elapsed_time": current.elapsed_time,
        "last_attempt_elapsed_time": last.elapsed_time if last is not None else None,
        "pr_elapsed_time": pr_time,
        # diff = last - current（正数 = 这次比上次快，符合用户直觉"快了 N 秒"）
        "current_attempt_diff_to_last": (
            last.elapsed_time - current.elapsed_time if last is not None else None
        ),
        # 用 == 判等而非 <=，因为 pr_time 已是历史最小，current 不会比它更小（除非并列）
        "current_attempt_is_pr": (current.elapsed_time == pr_time),
        "is_first_attempt": last is None,
    }
