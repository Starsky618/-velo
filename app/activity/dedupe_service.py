"""
GPX dedupe service 层（Sprint 5 task-2 / Day 1 / 修法 A 简化版）。

干啥用：
- 调 app/activity/dedupe.py 纯函数 + DB 读写。
- 新 activity 解析完成后，从 DB 找时间窗内的同用户 candidates，
  4 维 signature 比对，找到重复则**永远把 new 标 duplicate_of=existing**（不比 score）。

操作注意：
- **DB 读写在本层 / 算法在 dedupe.py 纯函数层**——分离让算法可独立单测
- **caller 必须包 SAVEPOINT**：本函数 db.flush() 写 duplicate_of / 失败不应阻断
  caller 已 set 的 activity.status='completed'
- **不查已是 duplicate 的 candidate**：WHERE duplicate_of IS NULL，避免链式判断
- **永远旧的为主 / 新的标 duplicate**（修法 A / Tim 2026-05-11 拍）：
  - 简单语义 / existing 一直是主（已有 efforts / 通知 / segment 排行榜不变）
  - 新版本 hide / 不引入 efforts 迁移 / notifications 迁移 / 字段重算等深层耦合
  - trade-off：新 GPX 数据更全（如带功率）也被隐藏 / 但实际场景 Strava 同步通常在前 / 后传 GPX 隐藏不损失什么
  - completeness score 公式保留在 dedupe.py（未来历史回扫脚本用 / 当前 service 不调）

数据流：
- 入：Session + 新 Activity ORM
- 中：advisory lock per-user → 构造 ActivitySig → 时间窗查 candidates → 4 维比对 → 标 new.duplicate_of=existing.id
- 出：Optional[int] 找到重复则返 new_activity.id，否则 None
"""

import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.activity.dedupe import (
    DEFAULT_TIME_TOLERANCE_SEC,
    ActivitySig,
    is_potential_duplicate,
)
from app.activity.models import Activity


logger = logging.getLogger(__name__)


# advisory lock namespace（与 segment-create-from-activity 命名风格一致）
# 用 hashtext('dedupe-activity') 作为 namespace key + user_id 作为 instance key
# = pg_advisory_xact_lock(namespace, user_id) 双 key 形式
# 同 user dedupe 串行 / 不同 user 并发 OK / 事务结束自动释放
_DEDUPE_LOCK_NAMESPACE_SQL = "hashtext('dedupe-activity')"


def _build_sig(activity: Activity) -> Optional[ActivitySig]:
    """
    从 Activity ORM 构造 ActivitySig / 缺关键字段返 None（不参与 dedupe）。

    缺字段场景：
    - started_at / distance / duration NULL（解析失败 / 未完成）
    - simplified_track 空（无 GPS 轨迹）
    - 第一个 trackpoint 缺 lat/lon
    """
    if activity.started_at is None or activity.distance is None or activity.duration is None:
        return None
    track = activity.simplified_track
    if not track or len(track) == 0:
        return None
    first = track[0]
    lat = first.get("lat")
    lon = first.get("lon")
    if lat is None or lon is None:
        return None
    return ActivitySig(
        started_at=activity.started_at,
        distance=activity.distance,
        duration=activity.duration,
        start_lat=lat,
        start_lon=lon,
    )


def find_and_mark_duplicate(db: Session, new_activity: Activity) -> Optional[int]:
    """
    新 activity 解析完成后，找 dedupe candidate / 找到则标 duplicate_of。

    设计思路：
    - 时间窗预筛：candidates 必在 ± DEFAULT_TIME_TOLERANCE_SEC 起骑时间窗内
      （减少 O(N) 扫描 / 100 用户量级单次查询 < 10 行）
    - 4 维比对：调 dedupe.is_potential_duplicate（纯函数）
    - 永远旧的为主 / 新的标 duplicate（修法 A 简化版）：找到第一个匹配就标 + 返回

    类比交警查重号车牌 —— 限定时间窗 + 多维比对 + 找到立刻按"先来先到"处理。

    参数：
        db: SQLAlchemy Session
        new_activity: 已解析完成、status='completed' 但未 commit 的 Activity

    返回：
        None: 没找到重复（new 是独立活动）
        int: 找到重复，固定返回 new_activity.id（new 被标 duplicate_of=existing.id）

    异常：
        - DB 查询失败 / 字段缺失 → caller SAVEPOINT 兜底
        - new_activity sig 构造失败（缺数据）→ 直接返 None
    """
    # 第 0 步：per-user advisory lock 防多 worker 并发 race
    # 场景：未来 docker compose --scale worker=3 时 / 同一用户的两份重复 GPX 同时被两 worker 解析 →
    #     各自 SELECT 看不到对方未提交的 status='completed' → 双双 miss dedupe → 用户得到两份独立活动
    # 修法：同 user dedupe 串行 / 锁在事务结束自动释放（pg_advisory_xact_lock 而非 pg_advisory_lock）
    # SQLite fixture 不支持 pg_advisory_xact_lock → 用 dialect.name 守卫（CLAUDE.md 陷阱 #15 同款 pattern）
    if db.bind.dialect.name == "postgresql":
        db.execute(
            text(f"SELECT pg_advisory_xact_lock({_DEDUPE_LOCK_NAMESPACE_SQL}, :user_id)"),
            {"user_id": new_activity.user_id},
        )

    # 第 1 步：构造 new sig（缺数据则跳过）
    new_sig = _build_sig(new_activity)
    if new_sig is None:
        logger.info(
            f"dedupe skip: activity {new_activity.id} 缺关键字段（started_at / distance / duration / track）"
        )
        return None

    # 第 2 步：时间窗预筛 candidates
    # 同 user / 不是自己 / 已 completed / 不是已标 duplicate / started_at 在 ± 5min 内
    time_window_start = new_sig.started_at - timedelta(seconds=DEFAULT_TIME_TOLERANCE_SEC)
    time_window_end = new_sig.started_at + timedelta(seconds=DEFAULT_TIME_TOLERANCE_SEC)

    candidates = (
        db.query(Activity)
        .filter(
            Activity.user_id == new_activity.user_id,
            Activity.id != new_activity.id,
            Activity.status == "completed",
            Activity.duplicate_of.is_(None),
            Activity.activity_type == "cycling",  # Sprint 7 Fix 7：dedupe 候选只取骑行 / 防跑步骑行交叉误判
            Activity.started_at.between(time_window_start, time_window_end),
        )
        .all()
    )

    if not candidates:
        return None

    # 第 3 步：对每个 candidate 跑 4 维比对（纯函数）/ 找到第一个匹配就标
    for c in candidates:
        c_sig = _build_sig(c)
        if c_sig is None:
            continue
        if not is_potential_duplicate(new_sig, c_sig):
            continue

        # 第 4 步：找到重复 / 永远旧的为主 / new 标 duplicate_of=existing
        new_activity.duplicate_of = c.id
        logger.info(
            f"dedupe mark: new activity {new_activity.id} → duplicate_of existing activity {c.id}"
        )
        return new_activity.id

    return None
