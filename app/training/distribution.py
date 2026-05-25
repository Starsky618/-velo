"""
训练结构计算器——把多条骑行的 Z1-Z6 功率时间，翻译成用户能看懂的训练类型。

操作注意事项：这里是纯函数文件，不读数据库、不知道当前用户是谁，也不返回 min_w/max_w 这类会暴露 FTP 的字段。
输入/输出数据流：输入是活动里的 power_zones 列表，输出给 Sprint 11 的 API 和小程序页面直接展示。
"""

from __future__ import annotations

import json
from typing import Any


ZONE_ORDER = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
ZONE_NAMES = {
    "Z1": "恢复",
    "Z2": "耐力",
    "Z3": "节奏",
    "Z4": "阈值",
    "Z5": "VO2max",
    "Z6": "无氧",
}
GROUPS = [
    ("endurance", "耐力", ["Z2"], "打底时间"),
    ("tempo_threshold", "中强度", ["Z3", "Z4"], "最容易堆累"),
    ("high_intensity", "高强度", ["Z5", "Z6"], "刺激偏少"),
]
MIN_COMPLETE_ACTIVITIES = 2
MIN_COMPLETE_SECONDS = 10_800

_INSUFFICIENT_COPY = {
    "current_type": None,
    "current_label": "功率数据不足",
    "current_description": "最近 6 周有功率区间的骑行还不够，暂时不能判断训练结构。",
    "target_label": "先补记录",
    "target_description": "先多记录几次有功率计的骑行，再让 velo 判断训练时间怎么分布。",
    "headline": "功率数据还不够，先别急着判断训练结构。",
    "explanation": "最近 6 周至少需要 2 条有功率区间的骑行，且总有功率时间达到 3 小时。",
    "actions": [],
    "week_plan": [],
}

_TYPE_COPY = {
    "sweet_spot": {
        "current_label": "Sweet Spot 倾向",
        "current_description": "时间紧、想快点见效时常见，但中强度堆多了会觉得天天都累。",
        "target_label": "更分明的 80 / 20",
        "target_description": "更多轻松骑打底，保留少量真正高强度，训练更分明。",
        "headline": "你最近练得太挤在中间，容易累，但突破感不强。",
        "explanation": "过去 6 周，你有 {tempo}% 时间卡在节奏和阈值区。下周先把一次中强度骑换成轻松长骑，让身体有空间吸收训练。",
        "actions": [
            ("换成轻松长骑", "把一次节奏骑换成 90 分钟轻松骑：目标是让 Z2 时间涨起来，能完整说话，不追速度。"),
            ("保留短间歇", "保留一次短间歇：例如 5 组 3 分钟高强度，中间充分恢复。"),
            ("阈值只留一次", "阈值骑只留一次：如果本周已经爬坡或拉扯很多，就不要再补一场硬骑。"),
        ],
        "week_plan": [
            ("一", "Z2", "45 分"),
            ("二", "Z5", "短间歇"),
            ("三", "休", "恢复"),
            ("四", "Z2", "90 分"),
            ("五", "Z3", "轻节奏"),
            ("六", "Z2", "长骑"),
            ("日", "休", "看状态"),
        ],
    },
    "polarized": {
        "current_label": "Polarized 倾向",
        "current_description": "轻松骑和高强度都有，中间区很少，训练日之间分得比较清楚。",
        "target_label": "继续守住分明结构",
        "target_description": "继续守住轻松日的轻松，只保留少量真正高强度，不要把每次都骑成半硬不硬。",
        "headline": "你最近练得很分明，轻松骑和高强度都有，但中间区很少。",
        "explanation": "这种结构接近 80/20，适合有时间做耐力打底、也愿意保留真正刺激的车手。下周重点不是再加一堆中强度，而是守住轻松日的轻松。",
        "actions": [
            ("守住轻松日", "保留两次真正轻松的 Z2，不要骑着骑着变成节奏骑。"),
            ("高强度只留一次", "高强度只留一次，做短而清楚的间歇。"),
            ("累了先砍强度", "如果感觉累，先砍高强度，不要砍恢复。"),
        ],
        "week_plan": [
            ("一", "Z2", "45 分"),
            ("二", "休", "恢复"),
            ("三", "Z5", "短间歇"),
            ("四", "Z2", "60 分"),
            ("五", "休", "恢复"),
            ("六", "Z2", "长骑"),
            ("日", "Z1", "轻松恢复"),
        ],
    },
    "pyramidal": {
        "current_label": "Pyramidal 倾向",
        "current_description": "耐力最多，中强度次之，高强度最少，是比较稳的训练底座。",
        "target_label": "稳住底座，加清楚刺激",
        "target_description": "保持耐力底座，同时让一次高强度更清楚，别把刺激都摊成中强度。",
        "headline": "你的训练像金字塔，耐力最多，中强度次之，高强度最少。",
        "explanation": "这是一种稳健结构，适合逐步变强。下周不要急着变成 80/20，先保持底座，同时给一次清楚的高强度刺激。",
        "actions": [
            ("保留最长 Z2", "保留本周最长的 Z2 骑，继续打底。"),
            ("拉扯改成间歇", "把一次随意拉扯改成有目的的短间歇。"),
            ("给恢复留空", "中强度不要天天出现，给恢复日留空。"),
        ],
        "week_plan": [
            ("一", "休", "恢复"),
            ("二", "Z2", "60 分"),
            ("三", "Z4", "控制骑"),
            ("四", "Z2", "45 分"),
            ("五", "休", "恢复"),
            ("六", "Z2", "长骑"),
            ("日", "Z5", "短刺激"),
        ],
    },
    "threshold": {
        "current_label": "Threshold 倾向",
        "current_description": "阈值附近待得太久，容易把训练骑成比赛，短期爽但恢复压力大。",
        "target_label": "减少硬顶",
        "target_description": "先减少硬顶，把更多时间还给轻松骑，只留一次清楚的阈值课。",
        "headline": "你最近太常在阈值附近硬顶，短期很爽，但恢复压力会变大。",
        "explanation": "Z4 时间过高说明你经常把训练骑成比赛。下周先把硬骑次数降下来，让高强度更少、更清楚。",
        "actions": [
            ("阈值只保留一次", "阈值训练只保留一次，其他日不追均速。"),
            ("补回轻松骑", "加一到两次 Z2 轻松骑，把恢复空间补回来。"),
            ("间歇宁可短", "高强度间歇宁可短，不要把整场都拖成硬顶。"),
        ],
        "week_plan": [
            ("一", "休", "恢复"),
            ("二", "Z2", "45 分"),
            ("三", "Z4", "阈值一次"),
            ("四", "休", "恢复"),
            ("五", "Z2", "60 分"),
            ("六", "Z2", "长骑"),
            ("日", "Z1", "轻松恢复"),
        ],
    },
    "mixed": {
        "current_label": "Mixed 倾向",
        "current_description": "强度分布还不稳定，可能今天轻松、明天硬顶，身体很难形成节奏。",
        "target_label": "先稳定一周节奏",
        "target_description": "先把一周安排变简单，固定轻松日和强度日，再谈更专业的训练结构。",
        "headline": "你最近训练结构还不稳定，先别急着贴训练流派。",
        "explanation": "过去 6 周的时间分布不够清楚，可能是活动太杂、强度忽高忽低。下周先把一周安排变简单，让身体知道每一天在练什么。",
        "actions": [
            ("固定轻松骑", "先固定两次 Z2 轻松骑。"),
            ("只留一次强度", "只安排一次明确的强度课。"),
            ("别临时加码", "其他骑行不要临时加码，先让节奏稳定下来。"),
        ],
        "week_plan": [
            ("一", "休", "恢复"),
            ("二", "Z2", "45 分"),
            ("三", "Z5/Z4", "一次强度"),
            ("四", "休", "恢复"),
            ("五", "Z2", "60 分"),
            ("六", "自由", "轻松骑"),
            ("日", "休", "恢复或休息"),
        ],
    },
}


def normalize_power_zones(value: list[dict] | str | None) -> list[dict]:
    """把数据库或测试里的 power_zones 统一成 list[dict]，像先把不同包装拆成同一种零件盒。"""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def aggregate_power_zones(zone_sets: list[list[dict]], exclude_zero: bool = False) -> dict:
    """累计 Z1-Z6 秒数、raw 百分比和三组页面分布。

    入参约定：每个 zone_set 必须是已经过 normalize_power_zones 清洗的 list[dict]。
    清洗（string→list、过滤非 dict）只在数据进入系统的边界做一次，由调用方
    distribution_service 负责；本函数信任这份契约、不再重复 normalize。
    好处：避免"边界和核心各清洗一半"的隐性矛盾——将来谁改了一侧，另一侧也不会被静默拖坏。
    """
    zone_seconds = {zone: 0 for zone in ZONE_ORDER}
    total_zero_seconds = 0
    for zone_set in zone_sets:
        for item in zone_set:
            zone = item.get("zone")
            if zone not in zone_seconds:
                continue
            zone_seconds[zone] += _safe_seconds(item.get("seconds"))
            if zone == "Z1":
                total_zero_seconds += _safe_seconds(item.get("zero_seconds"))

    total_power_seconds = sum(zone_seconds.values())
    classification_seconds = sum(zone_seconds[zone] for zone in ZONE_ORDER if zone != "Z1")
    display_zone_seconds = dict(zone_seconds)
    if exclude_zero:
        # exclude_zero 只改变页面展示口径：像从总账里临时划掉"滑行/等灯"这类 0W 时间，
        # 原始 zone_seconds 仍保留给分类和 data_complete，避免开关一开就改变训练类型。
        display_zone_seconds["Z1"] = max(0, zone_seconds["Z1"] - total_zero_seconds)
    display_total_power_seconds = sum(display_zone_seconds.values())
    raw_zones = [
        {
            "zone": zone,
            "name": ZONE_NAMES[zone],
            "seconds": display_zone_seconds[zone],
            "percent": _percent(display_zone_seconds[zone], display_total_power_seconds),
        }
        for zone in ZONE_ORDER
    ]
    groups = [
        {
            "key": key,
            "label": label,
            "zones": zones,
            "seconds": sum(zone_seconds[zone] for zone in zones),
            "percent": _percent(sum(zone_seconds[zone] for zone in zones), classification_seconds),
            "role": role,
        }
        for key, label, zones, role in GROUPS
    ]
    activity_count = len(zone_sets)
    data_complete = activity_count >= MIN_COMPLETE_ACTIVITIES and total_power_seconds >= MIN_COMPLETE_SECONDS

    return {
        "activity_count": activity_count,
        "zone_seconds": zone_seconds,
        "classification_seconds": classification_seconds,
        "total_power_seconds": display_total_power_seconds,
        "total_power_hours": round(display_total_power_seconds / 3600, 1),
        "data_complete": data_complete,
        "insufficient_power_data": not data_complete,
        "raw_zones": raw_zones,
        "groups": groups,
    }


def classify_distribution(stats: dict) -> str | None:
    """按 spec 顺序返回 threshold/sweet_spot/polarized/pyramidal/mixed。"""
    if not stats.get("data_complete"):
        return None

    zone_seconds = stats.get("zone_seconds") or {}
    denominator = int(stats.get("classification_seconds") or 0)
    if denominator <= 0:
        return "mixed"

    z2 = _ratio(zone_seconds.get("Z2", 0), denominator)
    z3_z4 = _ratio(zone_seconds.get("Z3", 0) + zone_seconds.get("Z4", 0), denominator)
    z4 = _ratio(zone_seconds.get("Z4", 0), denominator)
    z5_plus = _ratio(zone_seconds.get("Z5", 0) + zone_seconds.get("Z6", 0), denominator)

    if z4 >= 0.30:
        return "threshold"
    if z3_z4 >= 0.40:
        return "sweet_spot"
    if z2 >= 0.70 and z5_plus >= 0.08 and z3_z4 <= 0.22:
        return "polarized"
    if z2 > z3_z4 > z5_plus:
        return "pyramidal"
    return "mixed"


def build_training_distribution_payload(stats: dict) -> dict:
    """生成 headline、解释、行动建议和一周示意安排。"""
    base_payload = {
        "activity_count": int(stats.get("activity_count") or 0),
        "total_power_seconds": int(stats.get("total_power_seconds") or 0),
        "total_power_hours": float(stats.get("total_power_hours") or 0.0),
        "data_complete": bool(stats.get("data_complete")),
        "insufficient_power_data": bool(stats.get("insufficient_power_data")),
        "groups": stats.get("groups") or [],
        "raw_zones": stats.get("raw_zones") or _empty_raw_zones(),
    }

    current_type = classify_distribution(stats)
    if current_type is None:
        return {**base_payload, **_INSUFFICIENT_COPY}

    copy = _TYPE_COPY[current_type]
    # 动态百分比：把三组真实占比填进解释文案（demo 那种"你有 47% 时间卡在中间"比"较多时间"更戳人）。
    # 没有 {} 占位的文案 format 后原样不变，所以目前只有 sweet_spot 的 {tempo} 会被填充；
    # 将来想给别的类型加动态数字，只需在对应 explanation 里写 {endurance}/{tempo}/{high} 占位。
    group_pct = {g["key"]: g["percent"] for g in (stats.get("groups") or [])}
    explanation = copy["explanation"].format(
        endurance=group_pct.get("endurance", 0),
        tempo=group_pct.get("tempo_threshold", 0),
        high=group_pct.get("high_intensity", 0),
    )
    return {
        **base_payload,
        "current_type": current_type,
        "current_label": copy["current_label"],
        "current_description": copy["current_description"],
        "target_label": copy["target_label"],
        "target_description": copy["target_description"],
        "headline": copy["headline"],
        "explanation": explanation,
        "actions": [{"title": title, "body": body} for title, body in copy["actions"]],
        "week_plan": [{"day": day, "title": title, "focus": focus} for day, title, focus in copy["week_plan"]],
    }


def _safe_seconds(value: Any) -> int:
    """把 seconds 变成非负整数；坏值按 0 处理，避免一条脏 zone 拖垮整页。"""
    if isinstance(value, bool):
        return 0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return round(seconds)


def _percent(seconds: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return round(seconds / denominator * 100)


def _ratio(seconds: int | float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(seconds) / denominator


def _empty_raw_zones() -> list[dict]:
    return [{"zone": zone, "name": ZONE_NAMES[zone], "seconds": 0, "percent": 0} for zone in ZONE_ORDER]
