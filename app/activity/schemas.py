"""
骑行活动模块的请求/响应数据格式定义——"表格模板"。

和 User 模块的 schemas.py 一样的角色：
规定前端发请求时要填什么格式，后端返回数据时用什么格式。

注意事项：
- 每个接口的请求和响应都要有对应的 schema
- 不要在 schema 里写业务逻辑，只管格式校验
- 后续任务（3.7 查询接口）会在这里追加更多 schema
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ========== 任务 3.5：GPX 上传 ==========

class UploadResponse(BaseModel):
    """上传成功后的响应：返回活动 ID 和当前状态"""
    activity_id: int
    status: str


# ========== 任务 3.7：活动查询 ==========

class ActivityPrivacyResponse(BaseModel):
    """隐私设置响应——returned 在 ActivityDetail.privacy 嵌套字段 + PATCH endpoint 响应"""
    visibility: str
    hide_power: bool
    hide_heartrate: bool

    class Config:
        from_attributes = True


class ActivitySummary(BaseModel):
    """
    活动摘要——列表页用的"精简版信息卡"。
    不含轨迹和大 JSON（simplified_track/splits/power_zones），
    只有前端列表页需要的核心统计数据。
    """
    id: int
    title: Optional[str] = None
    status: str
    distance: Optional[float] = None        # 公里
    duration: Optional[int] = None           # 全程耗时（秒，含停车）
    moving_time: Optional[int] = None        # 移动时间（秒，去掉停车）；老活动 NULL → 前端 fallback duration
    elevation_gain: Optional[float] = None   # 米
    avg_speed: Optional[float] = None        # km/h
    avg_power: Optional[float] = None        # W
    avg_hr: Optional[float] = None           # bpm
    started_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ActivityDetail(BaseModel):
    """
    活动详情——详情页用的"完整档案"。
    包含全部统计量 + 简化轨迹 + 分段 + 功率区间。
    不返回 trackpoints 原始数据（太大了）。
    """
    id: int
    user_id: int
    title: Optional[str] = None
    status: str
    distance: Optional[float] = None
    duration: Optional[int] = None                     # 全程耗时（秒，含停车）
    moving_time: Optional[int] = None                  # 移动时间（秒，去掉停车）；老活动为 NULL → 前端 fallback "-"
    elevation_gain: Optional[float] = None
    avg_speed: Optional[float] = None
    max_speed: Optional[float] = None
    avg_power: Optional[float] = None
    max_power: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_cadence: Optional[float] = None
    max_cadence: Optional[float] = None
    snapshot_ftp: Optional[int] = None     # 这条活动锁定的 FTP（W）/ 跟 DB Integer 一致 / 前端显示 220W 不是 220.0W
    intensity_factor: Optional[float] = None
    tss: Optional[float] = None
    power_per_kg: Optional[float] = None   # W/kg = avg_power / user.weight（service 算好返）
    calories: Optional[float] = None
    normalized_power: Optional[float] = None  # 标准化功率（NP），FIT 自带
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    data_source: Optional[str] = None         # 数据来源：gpx / fit / strava
    simplified_track: Optional[Any] = None   # JSONB: [{lat, lon, ele}, ...]
    splits: Optional[Any] = None             # JSONB: [{km, avg_speed, ...}, ...]
    power_zones: Optional[Any] = None        # JSONB: [{zone, name, ...}, ...]
    duplicate_of: Optional[int] = None       # Sprint 5 task-2 dedupe：非 None = 本活动是 dedup 重复 / 前端按需显示提示
    created_at: Optional[datetime] = None
    # task-4.6：附带当前隐私设置（None = 老活动无配置 / 视同全公开）
    # 仅 owner 需要用 / 用于初始化隐私开关 UI 状态
    privacy: Optional[ActivityPrivacyResponse] = None

    class Config:
        from_attributes = True


class ActivityListResponse(BaseModel):
    """活动列表响应——带分页信息"""
    items: list[ActivitySummary]
    total: int
    page: int
    page_size: int


class ActivityUpdateRequest(BaseModel):
    """活动编辑请求——目前只能改标题"""
    title: str = Field(..., min_length=1, max_length=128)


class ActivityStatusResponse(BaseModel):
    """解析状态轮询响应"""
    status: str
    error_message: Optional[str] = None
    duplicate_of: Optional[int] = None  # Sprint 5 task-2 dedupe：上传后前端轮询看到非 None → 跳到合并目标 + toast


# ========== 隐私设置（task-4.6） ==========

class ActivityPrivacyUpdate(BaseModel):
    """
    PATCH /api/activities/{id}/privacy 请求体——3 个隐私开关都可选改。

    extra="forbid"：防止 admin 误改 distance / user_id 等核心字段后还看到 200 OK
    （v5 task-3.A.4/5 admin endpoint 复利实证 / CLAUDE.md 关键技术约定）。
    """
    visibility: Optional[Literal["public", "private"]] = None
    hide_power: Optional[bool] = None
    hide_heartrate: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")


# （ActivityPrivacyResponse 已在文件顶部定义 / 此处删除重复）


# ========== 时序数据（供前端画速度/功率/心率曲线） ==========

class TimeseriesResponse(BaseModel):
    """
    时序数据响应——"骑行过程的连续心电图"。

    前端拿到这些等长数组后，以 distances 为 X 轴，
    分别画出速度、功率、心率、海拔的连续曲线。

    所有数组长度相同（采样后的点数）。
    无传感器数据的字段整个数组为 null（不是数组里每个元素为 null）。
    """
    distances: list[float]                        # 累计公里数（X 轴）
    elevations: list[Optional[float]]             # 海拔 m
    speeds: list[Optional[float]]                 # 速度 km/h
    powers: Optional[list[Optional[float]]] = None       # 功率 W（无功率计则整个为 null）
    heart_rates: Optional[list[Optional[float]]] = None  # 心率 bpm（无心率带则整个为 null）
    cadences: Optional[list[Optional[float]]] = None     # 踏频 rpm（无踏频传感器则整个为 null）
