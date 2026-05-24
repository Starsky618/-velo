"""训练负荷 API 的请求/响应格式，像给小程序画图准备的一张固定菜单。"""

from typing import Literal
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, field_validator


TrainingLoadRange = Literal["30d", "90d", "1y"]
StatusBand = Literal["fresh", "ok", "tired", "overreached"]


def _round_1(value: float) -> float:
    """所有曲线数字统一保留 1 位，避免前端各页面各自四舍五入。"""
    stable_value = round(float(value), 10)
    return float(Decimal(str(stable_value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


class TrainingLoadPoint(BaseModel):
    """曲线上的一天，一个点就是训练日历里的一小格。"""

    model_config = ConfigDict(extra="forbid")

    date: str
    ctl: float
    atl: float
    tsb: float
    tss_today: float
    status_band: StatusBand

    @field_validator("ctl", "atl", "tsb", "tss_today")
    @classmethod
    def round_float_fields(cls, value):
        return _round_1(value)


class TrainingLoadSummary(BaseModel):
    """顶部状态卡的数据，告诉用户今天适不适合继续上量。"""

    model_config = ConfigDict(extra="forbid")

    current_ctl: float
    current_atl: float
    current_tsb: float
    current_status_band: StatusBand
    current_status_label: str
    tss_today: float
    weekly_tss: int
    data_complete: bool

    @field_validator("current_ctl", "current_atl", "current_tsb", "tss_today")
    @classmethod
    def round_float_fields(cls, value):
        return _round_1(value)


class TrainingLoadResponse(BaseModel):
    """训练负荷接口响应：一组画图点 + 顶部状态卡。"""

    model_config = ConfigDict(extra="forbid")

    range: TrainingLoadRange
    points: list[TrainingLoadPoint]
    summary: TrainingLoadSummary
