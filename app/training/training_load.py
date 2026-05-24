"""
训练负荷公式像一个固定口径的"计算器"：输入昨天的体能/疲劳和今天的 TSS，输出今天的 CTL、ATL、TSB 与状态档位。

操作注意事项：这里必须保持纯函数，不读数据库、不猜活动来源；回填脚本、worker 和 API 都应调用同一套公式，
否则同一个用户在不同入口看到的训练状态会像三把尺子量同一段路，各给一个结果。

输入/输出数据流：输入是按北京时间自然日汇总后的 TSS 与上一日快照；输出给 daily_training_load 表、训练日历 API 和后续教练总结读取。
"""

from decimal import Decimal, ROUND_HALF_UP
from math import exp


CTL_TIME_CONSTANT_DAYS = 42
ATL_TIME_CONSTANT_DAYS = 7

STATUS_FRESH = "fresh"
STATUS_OK = "ok"
STATUS_TIRED = "tired"
STATUS_OVERREACHED = "overreached"

_STATUS_LABELS = {
    STATUS_FRESH: "状态饱满",
    STATUS_OK: "状态 OK",
    STATUS_TIRED: "累",
    STATUS_OVERREACHED: "过累",
}


def _to_non_negative_float(value: float | int | None, field_name: str) -> float:
    """把空值按 0 处理，并拦住负数这种脏数据。"""
    if value is None:
        return 0.0

    result = float(value)
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return result


def _calculate_exponential_load(
    previous_load: float | int | None,
    tss_today: float | int | None,
    time_constant_days: int,
) -> float:
    """
    指数加权可以理解成"昨天状态自然衰减一点，再把今天训练压力加进去"。

    CTL 用 42 天慢慢变，像长期体能；ATL 用 7 天快速变，像最近疲劳。
    """
    previous = _to_non_negative_float(previous_load, "previous_load")
    tss = _to_non_negative_float(tss_today, "tss_today")
    decay = exp(-1 / time_constant_days)
    return previous * decay + tss * (1 - decay)


def calculate_daily_ctl(
    last_ctl: float | int | None,
    tss_today: float | int | None,
) -> float:
    """计算今天 CTL：长期体能，42 天慢速响应。参数名 last_ctl 为 plan §8 + Sprint 12 coach-engine 锁定的下游合同签名，禁止改名。"""
    return _calculate_exponential_load(last_ctl, tss_today, CTL_TIME_CONSTANT_DAYS)


def calculate_daily_atl(
    last_atl: float | int | None,
    tss_today: float | int | None,
) -> float:
    """计算今天 ATL：短期疲劳，7 天快速响应。参数名 last_atl 为下游合同签名，禁止改名。"""
    return _calculate_exponential_load(last_atl, tss_today, ATL_TIME_CONSTANT_DAYS)


def calculate_tsb(ctl: float | int | None, atl: float | int | None) -> float:
    """TSB 是体能减疲劳，越高代表越清爽，越低代表越累。"""
    ctl_value = _to_non_negative_float(ctl, "ctl")
    atl_value = _to_non_negative_float(atl, "atl")
    return ctl_value - atl_value


def classify_tsb_status(tsb: float | int | None) -> str:
    """把 TSB 数字翻译成前端能展示的 4 档状态。"""
    tsb_value = 0.0 if tsb is None else float(tsb)

    if tsb_value > 10:
        return STATUS_FRESH
    if tsb_value < -20:
        return STATUS_OVERREACHED
    if tsb_value < -10:
        return STATUS_TIRED
    return STATUS_OK


def format_status_label(status_band: str) -> str:
    """把内部状态值翻译成短中文标签，未知值直接报错，避免静默显示假文案。"""
    try:
        return _STATUS_LABELS[status_band]
    except KeyError as exc:
        raise ValueError(f"unknown status_band: {status_band}") from exc


def round_1(value: float) -> float:
    """
    全链路统一的 1 位小数四舍五入（ROUND_HALF_UP / 符合用户直觉）。

    写表（service.py）和 API 序列化（schemas.py）必须共用这一个实现：
    Python 内置 round() 是银行家舍入（round half to even），同一原始值在
    DB 和接口会出现两种结果（如 65.25 → round()=65.2 / ROUND_HALF_UP=65.3）。
    先 round(_, 10) 消浮点尾差，再 Decimal 量化到 0.1。
    """
    stable_value = round(float(value), 10)
    return float(Decimal(str(stable_value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
