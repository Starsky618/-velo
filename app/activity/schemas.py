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
from typing import Any, Optional

from pydantic import BaseModel, Field


# ========== 任务 3.5：GPX 上传 ==========

class UploadResponse(BaseModel):
    """上传成功后的响应：返回活动 ID 和当前状态"""
    activity_id: int
    status: str


# ========== 任务 3.7：活动查询 ==========

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
    duration: Optional[int] = None           # 秒
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
    duration: Optional[int] = None
    elevation_gain: Optional[float] = None
    avg_speed: Optional[float] = None
    max_speed: Optional[float] = None
    avg_power: Optional[float] = None
    max_power: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_cadence: Optional[float] = None
    calories: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    simplified_track: Optional[Any] = None   # JSONB: [{lat, lon, ele}, ...]
    splits: Optional[Any] = None             # JSONB: [{km, avg_speed, ...}, ...]
    power_zones: Optional[Any] = None        # JSONB: [{zone, name, ...}, ...]
    created_at: Optional[datetime] = None

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
