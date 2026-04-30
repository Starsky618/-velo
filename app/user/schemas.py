"""
用户模块的请求/响应数据格式定义——相当于"表格模板"。

好比去银行办业务要填的表格：每张表格规定了要填哪些栏、每栏填什么格式。
前端发请求时必须按这个格式填，后端返回数据时也按这个格式给。

Pydantic 会自动检查格式是否合规，不合规直接返回 422 错误，
不用手动写校验逻辑。

注意事项：
- 每个接口的请求和响应都要有对应的 schema
- 字段校验规则必须与 spec 一致（如 ftp 范围 50-500）
- 不要在 schema 里写业务逻辑，它只管格式校验
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ========== 任务 2.2：微信登录 ==========

class LoginRequest(BaseModel):
    """登录请求：前端传过来的微信授权 code"""
    code: str


class LoginResponse(BaseModel):
    """登录响应：返回通行证（token）和用户基本信息"""
    token: str
    user_id: int
    is_new_user: bool


# ========== 任务 2.4：用户资料 ==========

class BikeType(str, Enum):
    """车型枚举——只允许这三种值，传别的直接 422"""
    road = "road"
    gravel = "gravel"
    mtb = "mtb"


class UserProfile(BaseModel):
    """用户资料响应：返回给前端的用户完整信息"""
    id: int
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    ftp: Optional[int] = None
    weight: Optional[float] = None
    bike_type: Optional[str] = None
    weekly_goal: float
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """
    用户资料更新请求——所有字段都是可选的，只传想改的。

    校验规则（与 spec 一致）：
    - ftp: 50-500 的整数，或 null（清除）
    - weight: 30.0-200.0
    - bike_type: road / gravel / mtb
    - weekly_goal: 10.0-2000.0
    """
    nickname: Optional[str] = Field(None, max_length=64)
    avatar_url: Optional[str] = None
    ftp: Optional[int] = Field(None, ge=50, le=500)
    weight: Optional[float] = Field(None, ge=30.0, le=200.0)
    bike_type: Optional[BikeType] = None
    weekly_goal: Optional[float] = Field(None, ge=10.0, le=2000.0)


# ========== 任务 2.5：骑行统计 ==========

class StatsPeriod(str, Enum):
    """
    统计时间范围枚举。
    week = 本周（ISO 标准，周一为周首日）
    month = 本月
    year = 今年
    all = 全部历史
    传别的值直接 422。
    """
    week = "week"
    month = "month"
    year = "year"
    all = "all"


class StatsResponse(BaseModel):
    """
    骑行统计响应——"你这段时间骑了多少"的成绩单。

    distance 单位是公里（数据库存米，service 层转换）。
    duration 单位是秒。
    goal_percent 是 distance / weekly_goal 的百分比（0-100+），
    只在 period=week 时有实际意义，其他时段也照算不影响。
    """
    period: str
    distance: float
    rides: int
    elevation_gain: float
    duration: int
    weekly_goal: float
    goal_percent: int


# ========== task-2.C.3：v5 user router 4 个新 endpoint ==========


class PowerCurvePeriod(str, Enum):
    """功率曲线 period 枚举（与 service 层 _power_curve_period_window 一致）。"""
    this_month = "this_month"
    last_month = "last_month"
    this_year = "this_year"
    last_year = "last_year"
    all_time = "all_time"


class UserCity(str, Enum):
    """用户主城市枚举（与 segments.city / users.city CheckConstraint 一致）。"""
    beijing = "beijing"
    shanghai = "shanghai"
    hangzhou = "hangzhou"
    shenzhen = "shenzhen"
    chengdu = "chengdu"
    taiyuan = "taiyuan"
    unknown = "unknown"


class PowerCurveResponse(BaseModel):
    """
    功率曲线响应——"6 档时长各自的最佳平均功率"。

    buckets 是 dict[str, float]：window_sec → max_avg_power_W
    （service 层 JSON 序列化保证 key 是 str，与前端 JSON 协议一致）
    """
    period: str
    buckets: dict[str, float]


class _MultiPoint(BaseModel):
    """GeoJSON MultiPoint 子结构。"""
    type: str
    coordinates: list[list[float]]


class HeatmapResponse(BaseModel):
    """
    个人热图响应——"我在某城市去过的所有点位"。

    multipoint 是 GeoJSON MultiPoint（坐标顺序 [lon, lat]）。
    """
    city: str
    multipoint: _MultiPoint
    activity_count: int


class UserPatchRequest(BaseModel):
    """
    PATCH /api/user/me 请求体——目前只支持改 city（其他字段沿用现有 PUT /profile）。

    设计选择（spec §4.2 / B2B-6 修）：新增 PATCH 不替换现有 PUT /profile，
    避免与其他用户资料字段（ftp/weight/bike_type/weekly_goal）耦合在一个端点。
    PATCH /me 专门做"小修小改"——目前只 city，未来加 settings 类字段也走这里。
    """
    city: Optional[UserCity] = Field(
        None,
        description="可选 / 不传不改 / 传 null 清空 / 传枚举值更新",
    )


class _MonthSummary(BaseModel):
    """看他人主页 / 当月汇总子结构。"""
    distance_km: float
    elevation_m: float
    avg_power_w: float


class UserProfileResponse(BaseModel):
    """
    看他人主页响应——D-P08 红线"看自己 = 看他人"严格白名单。

    与 service.get_user_profile_for_others 的 _PROFILE_RESPONSE_KEYS 字段集合**完全一致**。
    FastAPI 会把 service 返回 dict 里多余的 key 自动忽略，本 schema 是双重保险。
    """
    id: int
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    city: Optional[str] = None
    ftp: Optional[int] = None
    bike_type: Optional[str] = None
    total_distance_km: float
    total_elevation_m: float
    activity_count: int
    current_month_summary: _MonthSummary
