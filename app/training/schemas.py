"""训练负荷 API 的请求/响应格式，像给小程序画图准备的一张固定菜单。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

# 全链路统一的 1 位小数实现（写表 + API 序列化共用 / 防 DB 值与接口值舍入不一致）
from app.training.training_load import round_1 as _round_1


TrainingLoadRange = Literal["30d", "90d", "1y"]
TrainingDistributionRange = Literal["6w"]
TrainingDistributionType = Literal["polarized", "pyramidal", "sweet_spot", "threshold", "mixed"]
StatusBand = Literal["fresh", "ok", "tired", "overreached"]
RiderCapabilityConfidence = Literal["insufficient", "low", "medium", "high"]
RiderCapabilityFreshness = Literal["none", "fresh", "stale"]
RiderCapabilityReasonCode = Literal[
    "no_usable_activities",
    "too_few_usable_activities",
    "history_stale",
    "insufficient_elevation_history",
]


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


class TrainingDistributionZone(BaseModel):
    """Z1-Z6 原始累计区间，只保留用户可看的安全字段。"""

    model_config = ConfigDict(extra="forbid")

    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
    name: str
    seconds: int
    percent: int


class TrainingDistributionGroup(BaseModel):
    """页面三组训练时间，像把六个抽屉合并成三类给用户看。"""

    model_config = ConfigDict(extra="forbid")

    key: Literal["endurance", "tempo_threshold", "high_intensity"]
    label: str
    zones: list[str]
    seconds: int
    percent: int
    role: str


class TrainingDistributionAction(BaseModel):
    """下周先改的一件事。"""

    model_config = ConfigDict(extra="forbid")

    title: str
    body: str


class TrainingDistributionWeekItem(BaseModel):
    """一周示意安排里的一天。"""

    model_config = ConfigDict(extra="forbid")

    day: str
    title: str
    focus: str


class TrainingDistributionResponse(BaseModel):
    """训练结构接口响应：判断、原因、分布和下周行动建议。"""

    model_config = ConfigDict(extra="forbid")

    range: TrainingDistributionRange
    window_days: int
    activity_count: int
    total_power_seconds: int
    total_power_hours: float
    data_complete: bool
    insufficient_power_data: bool
    current_type: TrainingDistributionType | None
    current_label: str
    current_description: str
    target_label: str
    target_description: str
    headline: str
    explanation: str
    groups: list[TrainingDistributionGroup]
    raw_zones: list[TrainingDistributionZone]
    actions: list[TrainingDistributionAction]
    week_plan: list[TrainingDistributionWeekItem]


class RiderCapabilityPrivacy(BaseModel):
    """Fields deliberately withheld from the route-planning snapshot."""

    model_config = ConfigDict(extra="forbid")

    exact_coordinates_included: Literal[False] = False
    raw_activity_tracks_included: Literal[False] = False
    health_metrics_included: Literal[False] = False


class RiderCapabilitySnapshotResponse(BaseModel):
    """Observed recent route envelope for one authenticated rider."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1.0"]
    snapshot_id: str
    generated_at: datetime
    source_revision: str
    window_days: int
    source_activity_count: int
    excluded_activity_count: int
    elevation_activity_count: int
    data_complete: bool
    confidence: RiderCapabilityConfidence
    freshness: RiderCapabilityFreshness
    latest_activity_at: datetime | None
    typical_distance_km: float | None
    upper_observed_distance_km: float | None
    typical_duration_minutes: int | None
    typical_climb_m_per_km: float | None
    source_types: list[str]
    reason_codes: list[RiderCapabilityReasonCode]
    privacy: RiderCapabilityPrivacy
