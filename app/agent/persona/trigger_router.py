"""
NPC 触发路由层（task-3 实施）。

干啥用：
- 接 PersonaEvent dict 决定"该不该说话 + 说哪个场景 + 哪个段位"
- 7 种 event 类型路由到 (scene_type, segment) 组合
- 优先级：PR > 极端 trigger（夜骑 / 极端数据）> 段位 trigger（plan task-3 拍定）

类比：老登的"该说啥话"判断器——
- 看到你上传 PR → 走 'pr' 场景
- 看到你深夜 11 点骑 → 走 'extreme/night'（不管距离段位）
- 看到你普通 40km 周末骑 → 走 'segment_distance/{stage}_{bucket}'
- 看到你 8 天没上车 → 走 'silence'

操作注意（ADR-009 + 宪法 § 7.2 硬约束）：
- 本模块**不查 DB / 不 import 业务 service** / 只对 dict 做纯函数判断
- 所有数据由调用方（task-4 worker hook / endpoint）打包成 PersonaEvent 传入
- 路由判断不抛错 / 返 None 表示"该 event 暂无文案"

输入输出：
- 入：PersonaEvent（含 type / activity_data / user_data / timestamp / error_code）
- 出：Optional[PersonaDecision]（含 scene_type / segment / context_dict / fallback_template_id）

参考：docs/agent-rules/persona-constitution.md § 2（7 场景 ground truth）
+ docs/plans/persona-engine-task-3.md（7 种 event 路由判定表）
"""

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.agent.persona.template_lib import (
    compute_user_stage,
    compute_distance_bucket,
)


# ─── Event / Decision Pydantic models ───


class PersonaEvent(BaseModel):
    """业务模块喂给 NPC 系统的事件 dict / 由 task-4 调用方组装。"""

    model_config = ConfigDict(extra="ignore")

    # 7 种 event type：
    # 'activity_uploaded'         — 用户上传新活动（最常见）
    # 'consecutive_high_detected' — 后台检测到本周 ≥ 5 次连骑
    # 'silence_detected'          — 后台检测到 ≥ 7 天没骑
    # 'milestone_reached'         — 累计跨阈值 / 周年 / 节气
    # 'empty_state'               — 前端透传空数据状态
    # 'error_state'               — 前端透传错误状态
    # 'pr_detected'               — deprecated（PR 是 activity_uploaded 内分支判断）
    type: str
    # 活动相关数据（distance/elevation_gain/duration/np/started_at/id/is_pr 等）
    activity_data: Optional[dict] = None
    # 用户上下文（user_id/total_distance_m/last_activity_days/weekly_count 等）
    user_data: dict
    timestamp: datetime
    # error_state event 用（401/500/network_down 等错误码）
    error_code: Optional[str] = None


class PersonaDecision(BaseModel):
    """路由层输出 / 给 service 主流水线消费。"""

    model_config = ConfigDict(extra="ignore")

    scene_type: str
    segment: Optional[str] = None
    # 给前端展示用的附加上下文（如 user_id / activity_id / 时间戳）
    context_dict: dict = {}
    # 主 pool 空时降级用（v0.2 修 / 暂未启用 / 留接口）
    fallback_template_id: Optional[int] = None


# ─── 极端数据判定阈值（宪法 § 2.5 / plan task-3 line 85）───


_HIGH_SPEED_KMH = 35.0       # 平均 > 35 km/h 异常
_LOW_SPEED_KMH = 15.0        # 平均 < 15 km/h 自嘲


def _is_pr(activity: dict) -> bool:
    """判定本次活动是否打破历史 max（任一字段）。"""
    return bool(activity.get("is_pr"))


def _hour_of(activity: dict) -> Optional[int]:
    """从 activity_data.started_at 提取小时（datetime 或 ISO 字符串都行）。"""
    started = activity.get("started_at")
    if started is None:
        return None
    if isinstance(started, datetime):
        return started.hour
    if isinstance(started, str):
        try:
            return datetime.fromisoformat(started.replace("Z", "+00:00")).hour
        except (ValueError, TypeError):
            return None
    return None


def _extreme_segment(activity: dict) -> Optional[str]:
    """活动是否命中极端 trigger / 命中返 segment 名 / 否则 None。

    优先级（同一活动多命中时取第一个）：
    1. night（23:00 以后 或 00:00-04:59 / plan task-3 line 85 "23-04 点" / Claude B + Codex 抓）
    2. tiny（< 5km）
    3. long_dist（> 150km）
    4. high_speed（> 35 km/h 均速）
    5. low_speed（< 15 km/h 均速）
    6. early（仅 05:00-05:59 / 04 已归 night）
    7. rain / late_collapse 等需上游打标签（is_rain / is_late_collapse 字段）
    """
    hour = _hour_of(activity)
    if hour is not None and (hour >= 23 or hour <= 4):
        return "night"

    distance_m = activity.get("distance") or 0
    if distance_m < 5000:
        return "tiny"
    if distance_m > 150_000:
        return "long_dist"

    avg_speed_kmh = activity.get("avg_speed_kmh")
    if avg_speed_kmh is not None:
        if avg_speed_kmh > _HIGH_SPEED_KMH:
            return "high_speed"
        if avg_speed_kmh < _LOW_SPEED_KMH:
            return "low_speed"

    if hour is not None and hour == 5:
        return "early"

    # 上游显式打标签的极端类型
    if activity.get("is_rain"):
        return "rain"
    if activity.get("is_late_collapse"):
        return "late_collapse"

    return None


def _route_activity_uploaded(event: "PersonaEvent") -> Optional[PersonaDecision]:
    """activity_uploaded 子路由（PR > 极端 > 段位）。"""
    activity = event.activity_data or {}
    user = event.user_data

    if _is_pr(activity):
        return PersonaDecision(
            scene_type="pr",
            segment=None,
            context_dict={
                "user_id": user.get("user_id"),
                "activity_id": activity.get("id"),
            },
        )

    extreme = _extreme_segment(activity)
    if extreme is not None:
        return PersonaDecision(
            scene_type="extreme",
            segment=extreme,
            context_dict={
                "user_id": user.get("user_id"),
                "activity_id": activity.get("id"),
            },
        )

    # 段位 × 距离桶
    total_m = user.get("total_distance_m", 0)
    stage = compute_user_stage(total_m)
    distance_m = activity.get("distance") or 0
    bucket = compute_distance_bucket(distance_m)
    return PersonaDecision(
        scene_type="segment_distance",
        segment=f"{stage}_{bucket}",
        context_dict={
            "user_id": user.get("user_id"),
            "activity_id": activity.get("id"),
        },
    )


# ─── 主 route 函数 ───


def route(event: PersonaEvent) -> Optional[PersonaDecision]:
    """7 种 event 路由 / 返 None 表示该 event 暂无文案。

    判定表（详见 plan task-3 § 7 种 event 路由判定）：
    | event.type                  | scene_type        | segment            |
    | activity_uploaded + PR      | pr                | None               |
    | activity_uploaded + 极端    | extreme           | night/tiny/...     |
    | activity_uploaded + 普通    | segment_distance  | {stage}_{bucket}   |
    | consecutive_high_detected   | consecutive_high  | None               |
    | silence_detected            | silence           | None               |
    | empty_state / error_state   | empty_error       | error_code         |
    | milestone_reached           | surprise          | milestone_type     |
    """
    event_type = event.type
    user = event.user_data

    if event_type == "activity_uploaded":
        return _route_activity_uploaded(event)

    if event_type == "consecutive_high_detected":
        if user.get("weekly_count", 0) >= 5:
            return PersonaDecision(
                scene_type="consecutive_high",
                segment=None,
                context_dict={"user_id": user.get("user_id")},
            )
        return None

    if event_type == "silence_detected":
        if user.get("last_activity_days", 0) >= 7:
            return PersonaDecision(
                scene_type="silence",
                segment=None,
                context_dict={"user_id": user.get("user_id")},
            )
        return None

    if event_type in ("empty_state", "error_state"):
        return PersonaDecision(
            scene_type="empty_error",
            segment=event.error_code,
            context_dict={"user_id": user.get("user_id")},
        )

    if event_type == "milestone_reached":
        # milestone 类型由上游放入 user_data（节气 / 周年 / 累计跨阈值都是用户维度 / 非单次活动 / plan task-3 line 90 / Claude A 抓）
        milestone_type = user.get("milestone_type")
        if milestone_type is None:
            return None
        return PersonaDecision(
            scene_type="surprise",
            segment=milestone_type,
            context_dict={"user_id": user.get("user_id")},
        )

    # 未识别 event type / 返 None / 不抛错
    return None
