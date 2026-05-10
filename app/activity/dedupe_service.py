"""
GPX dedupe service 层（Sprint 5 task-2 / Day 1）。

干啥用：
- 调 app/activity/dedupe.py 纯函数 + DB 读写。
- 新 activity 解析完成后，从 DB 找时间窗内的同用户 candidates，
  4 维 signature 比对，找到重复则比 completeness score，标 duplicate_of。

操作注意：
- **DB 读写在本层 / 算法在 dedupe.py 纯函数层**——分离让算法可独立单测
- **caller 必须包 SAVEPOINT**：本函数 db.flush() 写 duplicate_of / 失败不应阻断
  caller（如 worker.py parse_activity）已 set 的 activity.status='completed'
- **不查已是 duplicate 的 candidate**：WHERE duplicate_of IS NULL，避免链式判断
  （A 跟 B 重复 / B 已标 duplicate_of=A → 新来的 C 只跟 A 比，不跟 B 比）
- **score 比较语义**：
  - new 高 → existing 标 duplicate_of=new（new 成新主）
  - new <= existing → new 标 duplicate_of=existing（existing 仍主 / 含相等场景：保守不动）

数据流：
- 入：Session + 新 Activity ORM
- 中：构造 ActivitySig → 时间窗查 candidates → 4 维比对 → 比 score → 标 duplicate_of
- 出：Optional[int] 被标的那一行 ID（None 表示无重复）
"""

import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.activity.dedupe import (
    DEFAULT_TIME_TOLERANCE_SEC,
    ActivityScoreData,
    ActivitySig,
    compute_completeness_score,
    is_potential_duplicate,
)
from app.activity.models import Activity


logger = logging.getLogger(__name__)


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


def _build_score(activity: Activity) -> ActivityScoreData:
    """
    从 Activity ORM 构造 ActivityScoreData。

    trackpoint_count 用 simplified_track 长度（不是 trackpoints 表 COUNT(*)）。
    Why：simplified_track 是固定数据源 / 已在 ORM 上 / 不用额外 DB 查询。
    """
    track_count = len(activity.simplified_track or [])
    return ActivityScoreData(
        avg_power=activity.avg_power,
        avg_hr=activity.avg_hr,
        avg_cadence=activity.avg_cadence,
        trackpoint_count=track_count,
    )


def find_and_mark_duplicate(db: Session, new_activity: Activity) -> Optional[int]:
    """
    新 activity 解析完成后，找 dedupe candidate / 找到则标 duplicate_of。

    设计思路：
    - 时间窗预筛：candidates 必在 ± DEFAULT_TIME_TOLERANCE_SEC 起骑时间窗内
      （减少 O(N) 扫描 / 100 用户量级单次查询 < 10 行）
    - 4 维比对：调 dedupe.is_potential_duplicate（纯函数）
    - score 比较：调 dedupe.compute_completeness_score（纯函数）
    - 短路：找到一个重复就标 + 返回（极少出现 1 个新 activity 跟多个旧 activity 都重复）

    类比交警查重号车牌 —— 限定时间窗 + 多维比对 + 找到立刻处理。

    参数：
        db: SQLAlchemy Session
        new_activity: 已解析完成、status='completed' 但未 commit 的 Activity

    返回：
        None: 没找到重复
        int: 找到重复，被标 duplicate_of 那一行的 ID
            - 可能是 new_activity.id（new 数据较少 / 标自己）
            - 也可能是 existing.id（new 数据更全 / 标旧的）

    异常：
        - DB 查询失败 / 字段缺失 → caller SAVEPOINT 兜底
        - new_activity sig 构造失败（缺数据）→ 直接返 None
    """
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
            Activity.started_at.between(time_window_start, time_window_end),
        )
        .all()
    )

    if not candidates:
        return None

    # 第 3 步：对每个 candidate 跑 4 维比对（纯函数）
    for c in candidates:
        c_sig = _build_sig(c)
        if c_sig is None:
            continue
        if not is_potential_duplicate(new_sig, c_sig):
            continue

        # 第 4 步：找到重复 / 比 score 决定标谁
        new_score = compute_completeness_score(_build_score(new_activity))
        c_score = compute_completeness_score(_build_score(c))

        if new_score > c_score:
            # new 数据更全 → existing 标 duplicate_of=new（new 成新主）
            c.duplicate_of = new_activity.id
            logger.info(
                f"dedupe mark: existing activity {c.id} → duplicate_of new activity {new_activity.id} "
                f"(new score {new_score:.2f} > existing {c_score:.2f})"
            )
            return c.id
        else:
            # new 数据 <= existing → new 标 duplicate_of=existing（existing 仍主）
            new_activity.duplicate_of = c.id
            logger.info(
                f"dedupe mark: new activity {new_activity.id} → duplicate_of existing activity {c.id} "
                f"(new score {new_score:.2f} <= existing {c_score:.2f})"
            )
            return new_activity.id

    return None
