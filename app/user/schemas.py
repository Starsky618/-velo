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

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ========== Sprint 6 task-1：bio 字段共享校验 ==========
#
# 个性签名一行短描述，要求"单行 / ≤ 30 字符"。
# 抽成独立 helper 是因为两个 request schema（UserProfileUpdate / UserPatchRequest）
# 都接 bio——同一规则两个入口都得守，复制粘贴 = 未来改一处忘另一处。
# 类比：小区"住户档案"两个登记窗口（户籍处 / 物业前台）共用同一张校验清单——
# 长度 ≤ 30 + 不许含换行符 / 制表符 / 其他控制字符（避免一行签名被塞成多行 / 显示错位）。

def _reject_newline_and_control(v: Optional[str]) -> Optional[str]:
    """共享：bio 校验拒收换行 / 控制字符（强制单行短签名）。

    None 直接透传（用户没改 / 想清空）；非 None 时扫描 \\n \\r \\t \\x00 等控制字符，
    含任意一个就 422——前端必须改成单行才能保存。
    """
    if v is None:
        return v
    if any(c in v for c in "\n\r\t\x00"):
        raise ValueError("签名不能含换行或控制字符")
    return v


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


class Badge(BaseModel):
    """单条身份徽章（Sprint 6 task-2 / 看自己 + 看他人对称返回）。

    字段：
    - type: 5 种枚举之一 — ftp / distance / elevation / regular_mountain / city_local
    - label: 展示文案 — "FTP 220W" / "累计 8000km" / "雀儿山常客" / "北京" 等
    """
    type: str
    label: str


class UserProfile(BaseModel):
    """用户资料响应：返回给前端的用户完整信息"""
    id: int
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    city: Optional[str] = None  # Sprint 4 codex 异源审拍加（P1-3 / 跟看他人 UserProfileResponse.city 字段对齐 / 默认公开 / 详 D9 fallback 2026-05-06）
    bio: Optional[str] = None  # Sprint 6 task-1：骑手签名（≤ 30 字符 / 一行短描述）
    ftp: Optional[int] = None
    weight: Optional[float] = None
    birth_year: Optional[int] = None
    max_hr: Optional[int] = None
    bike_type: Optional[str] = None
    weekly_goal: float
    created_at: datetime
    # Sprint 6 task-2：身份徽章列表 / top 3 / 服务端根据真实数据自动算 / 用户无法手填
    # 默认 [] 防 null / 自他对称返同样字段集
    badges: list[Badge] = []

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """
    用户资料更新请求——所有字段都是可选的，只传想改的。

    校验规则（与 spec 一致）：
    - ftp: 50-500 的整数，或 null（清除）
    - weight: 30.0-200.0
    - birth_year: 1900-当前年份（后端存出生年份，不存会过期的 age）
    - max_hr: 120-220 bpm
    - bike_type: road / gravel / mtb
    - weekly_goal: 10.0-2000.0
    - bio: ≤ 30 字符 + 单行（Sprint 6 task-1 / 详 _reject_newline_and_control）
    """
    nickname: Optional[str] = Field(None, max_length=64)
    avatar_url: Optional[str] = None
    ftp: Optional[int] = Field(None, ge=50, le=500)
    weight: Optional[float] = Field(None, ge=30.0, le=200.0)
    birth_year: Optional[int] = Field(None, ge=1900)
    max_hr: Optional[int] = Field(None, ge=120, le=220)
    bike_type: Optional[BikeType] = None
    weekly_goal: Optional[float] = Field(None, ge=10.0, le=2000.0)
    bio: Optional[str] = Field(None, max_length=30)

    @field_validator("bio")
    @classmethod
    def _validate_bio(cls, v):
        return _reject_newline_and_control(v)

    @field_validator("birth_year")
    @classmethod
    def _validate_birth_year(cls, v):
        if v is None:
            return v
        current_year = datetime.now(timezone.utc).year
        if v > current_year:
            raise ValueError("出生年份不能晚于今年")
        return v


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
    elevation_gain: int  # 米 / Tim 2026-05-11 拍整数显示 / int 而非 float 防 JSON 73205.0 .0 尾巴
    duration: int
    weekly_goal: float
    goal_percent: int


# ========== task-2.C.3：v5 user router 4 个新 endpoint ==========


class PowerCurvePeriod(str, Enum):
    """功率曲线 period 枚举 — 滚动窗口型（与 service 层 _power_curve_period_window 一致 / D16 v0.3 / Sprint 4 task-pre-4.2 升级）。

    设计：从"自然历法切片"（this_month / last_month）改为"滚动窗口"（last_N_days），
    解决"5 月 1 号那天看 this_month 只有 1 天数据"的语义不直观问题。
    任何时间打开都是稳定 N 天，进步对比直观。
    """
    last_30_days = "last_30_days"
    last_90_days = "last_90_days"
    last_180_days = "last_180_days"
    last_365_days = "last_365_days"
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


class HeatmapDetail(str, Enum):
    """个人热图的数据精度：轻量地图元数据 / 兼容预览 / 当前视野高精度。"""
    meta = "meta"
    card = "card"
    full = "full"
    viewport = "viewport"


class PowerCurveResponse(BaseModel):
    """
    功率曲线响应——"7 档时长各自的最佳平均功率"（D26 v2 polish / 0s 瞬时 + 3s/30s/1min/5min/20min/1h）。

    buckets 是 dict[str, float]：window_sec → max_avg_power_W
    （service 层 JSON 序列化保证 key 是 str，与前端 JSON 协议一致）
    """
    period: str
    buckets: dict[str, float]


class HeatmapResponse(BaseModel):
    """
    个人热图响应——"我在某城市去过的所有轨迹"（D27 v2 polish / Sprint 4 task-4.2 v2 / v3 polish city 可选）。

    tracks 是 list of list of [lon, lat]：保留 activity 边界；card/full 每个 activity 一条，
    viewport 允许同一 activity 因进出视野裁成多段。
    meta 只返回定位范围；card/full 保留旧客户端兼容；viewport 从原始 Trackpoint
    按当前视野生成曲率优先 LOD。前端完整绘制 viewport 响应中的点，多条 opacity
    叠加形成热力效果；任何入口都不下发数据库中的全量轨迹对象。

    旧版（v1）用 multipoint 扁平所有点 + markers 渲染 → 视觉差（粗灰圆点）。
    新版（v2）用 tracks 保留边界 + polyline 渲染。
    v3 polish：city 改可选——不传时返回所有 activity 轨迹（不按城市筛 / response.city = None）；
    传时保留旧行为按起点城市筛。前端"全部"视图直接不传 city。
    v5：viewport 按当前地图视野提供高精度 LOD，避免恢复 6 MB 全量响应；一条骑行可因
    进出视野被裁成多条 track，activity_count 统计实际保留的骑行数而不是折线段数。
    """
    city: Optional[str] = None
    tracks: list[list[list[float]]]
    activity_count: int
    # 原始轨迹变化时递增；客户端用它隔离瓦片缓存，旧文件不会污染新数据。
    generation: int = 0
    # 同时绑定 Redis generation 与数据库活动集合；Redis 失效失败也会换 URL/key。
    cache_version: str = "g0-d0"
    available_years: list[int] = Field(default_factory=list)
    selected_year: Optional[int] = None
    # meta 只下发两个范围角点；小程序首屏不再接收数千个 polyline 点。
    focus_points: list[list[float]] = Field(default_factory=list)
    all_points: list[list[float]] = Field(default_factory=list)


class UserPatchRequest(BaseModel):
    """
    PATCH /api/user/me 请求体——目前只支持改 city（其他字段沿用现有 PUT /profile）。

    设计选择（spec §4.2 / B2B-6 修）：新增 PATCH 不替换现有 PUT /profile，
    避免与其他用户资料字段（ftp/weight/bike_type/weekly_goal）耦合在一个端点。
    PATCH /me 专门做"小修小改"——目前只 city，未来加 settings 类字段也走这里。
    """
    # Sprint 6 task-4 hotfix（Tim 2026-05-17）：city 放宽到任意中文（picker 选省+市拼接）
    # 不再是 6 城 enum / 只校验长度 ≤ 32 + 不含换行 / 应用层 strip 空白
    # 历史 UserCity enum 保留给 heatmap endpoint 等其他地方 / 不影响
    city: Optional[str] = Field(
        None,
        max_length=32,
        description="家乡标签 / picker 选省+市拼接（如'山西-太原'）/ 任意中文 ≤ 32 字符 / 可选",
    )
    bio: Optional[str] = Field(
        None,
        max_length=30,
        description="骑手签名 / Sprint 6 task-1 / ≤ 30 字符 / 单行 / 空串等价清空（service 层转 NULL）",
    )

    @field_validator("bio")
    @classmethod
    def _validate_bio(cls, v):
        return _reject_newline_and_control(v)


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

    Sprint 4 codex 异源审 2026-05-06 砍 ftp（P1-4）：
    - v5 期误放 ftp 公开 / Sprint 4 brainstorm Tim 拍"默认公开"是页面层（路径任意人能看）
      不等于字段层（FTP 是骑手生理数据 / Strava 也允许独立隐私设置层）
    - 砍配套：service.py _PROFILE_RESPONSE_KEYS 同步砍 ftp
    """
    id: int
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    city: Optional[str] = None
    bio: Optional[str] = None  # Sprint 6 task-1：骑手签名 / 看他人也可见 / 与白名单 _PROFILE_RESPONSE_KEYS 对齐
    bike_type: Optional[str] = None
    total_distance_km: float
    total_elevation_m: float
    activity_count: int
    current_month_summary: _MonthSummary
    # Sprint 6 task-2：身份徽章列表 / 自他对称（与 UserProfile.badges 字段集一致）/ 真实数据自动算
    badges: list[Badge] = []


# ===== Sprint 5 task-3：探索 tab 骑友 section =====


class ActiveUserItem(BaseModel):
    """
    探索 tab 骑友 section 单条用户摘要。

    精简字段（不全等于 UserProfileResponse）：
    - 列表场景只需要"能让用户决定要不要点头像看详情"的最少信息
    - 头像 + 昵称 + 城市 + 总里程 = 4 维社交识别
    - 不返 ftp / bike_type / current_month_summary 等详情字段（需要点进 profile 看）
    """
    id: int
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    city: Optional[str] = None
    total_distance_km: float
    activity_count: int
    last_activity_at: Optional[datetime] = None  # 最近骑行时间（用于排序 + 前端"X 天前"显示）


class ActiveUsersResponse(BaseModel):
    """探索 tab 骑友 section 列表响应 / 按 last_activity_at desc 排序。"""
    items: list[ActiveUserItem]


# ===== Sprint 6 task-3：城市征服勋章 =====


class CityMedal(BaseModel):
    """单格城市勋章（"我的"页"城市征服墙"一格 / 自他对称返同样字段集）。

    字段：
    - city: 6 城枚举 code 之一（beijing / shanghai / hangzhou / shenzhen /
      chengdu / taiyuan）。不含 unknown —— unknown 不算"征服"。
    - label: 城市中文名（"北京" / "上海" / ...），与 cities.py CITY_LABELS 一致。
    - unlocked: True = 用户已骑过该城（completed activity 起点落在城内）。
    """
    city: str
    label: str
    unlocked: bool


class CityMedalsResponse(BaseModel):
    """城市勋章墙响应（GET /api/user/me/city-medals + /{user_id}/city-medals 共用）。

    自他对称（D-P08 红线 / 与 Sprint 6 task-2 一致）：看自己 = 看他人字段集合完全一致。

    字段：
    - unlocked: 已点亮城市 code 列表（sorted / 稳定顺序方便前端 diff）
    - unlocked_count: 已点亮城市数（unlocked 的长度）
    - total: 总城市数 = 6（VALID_CITY_CODES 长度 / 不含 unknown）
    - medals: 全 6 城列表（每格含 city / label / unlocked）—— 前端不用自己维护城市名
      和顺序，直接 v-for 渲染 6 格。
    """
    unlocked: list[str]
    unlocked_count: int
    total: int
    medals: list[CityMedal]
