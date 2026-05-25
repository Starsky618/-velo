"""训练负荷 API 的请求/响应格式，像给小程序画图准备的一张固定菜单。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

# 全链路统一的 1 位小数实现（写表 + API 序列化共用 / 防 DB 值与接口值舍入不一致）
from app.training.training_load import round_1 as _round_1


TrainingLoadRange = Literal["30d", "90d", "1y"]
StatusBand = Literal["fresh", "ok", "tired", "overreached"]


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
    # 区分 data_complete=false 的两种原因：< 14 天历史（再骑几天）vs 当前 range 功率数据不足
    # 前端按此分流文案：功率不足时显示"需要更多有功率计的骑行" / 而非"再骑 N 天"
    insufficient_power_data: bool = False

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
