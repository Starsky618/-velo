"""
赛段模块的请求/响应数据格式定义——"赛道管理表格"。

好比赛事组委会的各种表格模板：
- 创建赛段时要填"赛道申报表"（SegmentCreateRequest）
- 查看赛段列表像"赛道目录"（SegmentListItem）
- 查看赛段详情像"赛道档案 + 成绩榜"（SegmentDetailResponse）

注意事项：
- reference_points 至少需要 2 个坐标点，才能连成一条线
- 距离单位：API 层返回公里（数据库存米，service 层转换）
- 排行榜按用时升序排列（用时越短排名越高）
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ========== 创建赛段 ==========

class PointInput(BaseModel):
    """
    参考路线上的一个坐标点。

    GPS 坐标规则：
    - 纬度（lat）：-90 到 90，正值为北纬，负值为南纬
    - 经度（lon）：-180 到 180，正值为东经，负值为西经
    - 海拔（ele）：可选，单位米，用于计算爬升
    """
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    ele: Optional[float] = None


class SegmentCreateRequest(BaseModel):
    """
    创建赛段请求——管理员专用。

    管理员在地图上画一条路线，提交坐标点数组，
    后端自动计算距离、爬升，生成赛段。
    match_tolerance 和 min_match_ratio 不传就用默认值（50米、80%）。
    """
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    reference_points: list[PointInput] = Field(..., min_length=2)
    # 坐标系声明：管理员从腾讯/高德地图取的坐标是 GCJ-02（默认值），
    # 从 GPX 文件或 GPS 设备直接拿的坐标是 WGS-84。
    # 后端会根据这个字段决定是否做坐标转换，确保存入数据库的都是 WGS-84。
    coordinate_system: Literal["gcj02", "wgs84"] = Field(
        default="gcj02",
        description="坐标系：gcj02（腾讯/高德地图）或 wgs84（GPS/GPX原始坐标）",
    )
    match_tolerance: Optional[float] = Field(None, gt=0)
    min_match_ratio: Optional[float] = Field(None, gt=0, le=1.0)


# ========== 赛段响应 ==========

class SegmentResponse(BaseModel):
    """赛段完整信息——创建成功后返回"""
    id: int
    name: str
    description: Optional[str] = None
    distance: float                                      # 公里
    elevation_gain: Optional[float] = None               # 米
    elevation_loss: Optional[float] = None               # 米，累计下降
    avg_gradient: Optional[float] = None                 # %，平均坡度
    elevation_profile: Optional[list[float]] = None      # 海拔采样数组（约80点）
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    match_tolerance: float
    min_match_ratio: float
    created_at: Optional[datetime] = None


class SegmentListItem(BaseModel):
    """
    赛段列表项——"赛道目录"里的一行。

    比完整信息更精简，多了 entries（成绩记录数）字段，
    前端用它显示"已有 XX 人挑战"。

    v5 task-1.A.3 新增 4 字段（avg_gradient/max_gradient/difficulty/city），
    服务于赛段卡片展示坡度信息 + 列表筛选 + 城市标签。
    """
    id: int
    name: str
    distance: float                          # 公里
    elevation_gain: Optional[float] = None   # 米
    avg_gradient: Optional[float] = None     # %，平均坡度（v5）
    max_gradient: Optional[float] = None     # %，最陡 100m 滑窗坡度（v5）
    difficulty: str                          # easy/medium/hard/extreme（v5）
    city: str                                # beijing/.../taiyuan/unknown（v5）
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    entries: int
    created_at: Optional[datetime] = None    # 创建时间（Sprint 4 task-4.4 NEW 标签判断用 / 30 天内为 NEW）


class SegmentListResponse(BaseModel):
    """赛段列表响应——带分页"""
    items: list[SegmentListItem]
    total: int
    page: int
    page_size: int


# ========== 排行榜 ==========

class LeaderboardEntry(BaseModel):
    """
    排行榜条目——某个用户在某赛段上的成绩。

    好比马拉松成绩榜上的一行：
    名次、姓名、用时、配速……
    """
    rank: int
    user_id: int
    activity_id: Optional[int] = None        # task-4.2：对应"最快那次"的活动 ID（前端 task-4.4 用作跳转）
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    elapsed_time: int                        # 秒
    avg_speed: Optional[float] = None        # km/h
    avg_power: Optional[float] = None        # W
    bike_type: Optional[str] = None          # 车型（Task 4.5 新增）
    created_at: Optional[datetime] = None
    is_private_self: bool = False            # 仅本人能看到自己的私密成绩时为 True


class LeaderboardResponse(BaseModel):
    """
    排行榜分页响应——Task 4.5 独立排行榜接口用。

    Sprint 4 D7 hotfix（2026-05-10）：加 my_rank + my_elapsed_time 字段，
    让登录用户在前端能精确显示"我在这个赛段排第几 / 我的 PR 用时"，
    无论是否在 top 10 内。未登录或没骑过 → 两字段为 None。

    已知语义边界（tied PR / 双 review I1 backlog 跟 D33 一起做）：
    多用户 elapsed_time 完全相等时，my_rank 算法 count(elapsed_time < my_pr) + 1
    与主榜 enumerate rank（无二级排序键）可能错位 1：
    - my_rank 取"tied 群里最小可能 rank"（下界）
    - items rank 由 enumerate 决定 / 同 elapsed_time 时顺序未定
    百级用户量 tied 概率 < 1%，未来用户量大或 D33 一起补：
    主榜 ORDER BY 加二级键 (elapsed_time, effort_id) +
    my_rank 算法配套 count(elapsed_time < pr OR (= pr AND id < my_id)) + 1。
    """
    items: list[LeaderboardEntry]
    total: int
    page: int
    page_size: int
    my_rank: Optional[int] = None             # 登录用户在该赛段的真排名（基于 PR / 比我快的人数 + 1 / task-4.2 去重）
    my_elapsed_time: Optional[int] = None     # 登录用户的 PR 用时（秒）/ 用于前端独立行展示


class SegmentDetailResponse(BaseModel):
    """
    赛段详情——赛段信息 + 排行榜前 20 名。

    v5 task-1.A.3 新增 4 字段（avg_gradient/max_gradient/difficulty/city），
    详情页要展示完整赛段画像（不止距离爬升，还要坡度+难度+城市）。

    elevation_profile：约 80 个海拔采样数值（米），按沿赛段距离均匀分布。
    前端画海拔曲线用——X 轴位置按 i/N * distance 算，因为采样本身是等距的。
    老赛段未生成时为 None，前端要兜底降级为 placeholder。
    """
    id: int
    name: str
    description: Optional[str] = None
    distance: float                          # 公里
    elevation_gain: Optional[float] = None   # 米
    avg_gradient: Optional[float] = None     # %（v5）
    max_gradient: Optional[float] = None     # %（v5）
    difficulty: str                          # 4 档枚举（v5）
    city: str                                # 城市枚举（v5）
    elevation_profile: Optional[list[float]] = None   # 约 80 个海拔采样（米）
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    match_tolerance: float
    min_match_ratio: float
    created_at: Optional[datetime] = None
    leaderboard: list[LeaderboardEntry]


# ========== 即时反馈（v5 task-1.A.3 新增） ==========

class EffortCompareResponse(BaseModel):
    """
    赛段即时反馈对比——"骑完看进步"语义。

    每次骑完该赛段，前端调 GET /api/segments/{id}/efforts/me 拿这个对象，
    展示"上次 28 分钟、这次 26 分钟、PR 25 分钟"——让用户直观感受进步。

    与 leaderboard endpoint 的区别：那里看排名，这里看自己；这里不含名次。

    字段一一对应 spec §4.1 endpoint 响应（spec §3.2.1 service 契约）。
    """
    current_attempt_elapsed_time: Optional[int] = None   # 这次（最新一次骑行）用时秒
    last_attempt_elapsed_time: Optional[int] = None      # 上次用时秒
    pr_elapsed_time: Optional[int] = None                # 个人最佳用时秒
    current_attempt_diff_to_last: Optional[int] = None   # last - current（正数 = 变快）
    current_attempt_is_pr: bool                          # 这次是否破或持平 PR
    is_first_attempt: bool                               # 是否首次（无 last 对比）


# ========== 用户赛段成绩（Task 4.5） ==========

class UserEffortItem(BaseModel):
    """
    用户在某赛段的成绩——"我的成绩单"中的一行。

    包含赛段名称和自己在该赛段的排名，
    让用户一眼看到"我在哪条赛道排第几"。
    """
    segment_id: int
    segment_name: str
    elapsed_time: int                        # 秒
    avg_speed: Optional[float] = None        # km/h
    rank: int
    created_at: Optional[datetime] = None


class UserEffortsResponse(BaseModel):
    """用户所有赛段成绩响应"""
    items: list[UserEffortItem]


# ========== 活动途经赛段（Task 4.6） ==========

class ActivitySegmentItem(BaseModel):
    """
    某次骑行途经的一条赛段成绩。

    好比跑完马拉松后查分段计时牌：
    在哪个计时点用了多久、排第几、是不是个人最快。
    """
    segment_id: int
    segment_name: str
    elapsed_time: int                        # 秒
    avg_speed: Optional[float] = None        # km/h
    avg_power: Optional[float] = None        # W
    rank: int
    is_pr: bool                              # 是否个人最佳


class ActivitySegmentsResponse(BaseModel):
    """某次骑行途经的所有赛段成绩响应"""
    items: list[ActivitySegmentItem]
