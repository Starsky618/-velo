"""
约骑接口格式——小程序和后端约定每张约骑卡片长什么样。

操作注意事项：这里只定义请求/响应形状，不放状态机规则；状态机统一在 service 层执行。
输入/输出数据流：router 接收这些 schema，调用 service 后再组装成 `MeetupResponse`。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MeetupStatus = Literal["DRAFT", "OPEN", "CANCELLED", "COMPLETED"]
PaceLevel = Literal["relaxed", "cruise", "training", "race"]
City = Literal["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]


class MeetupCreateRequest(BaseModel):
    """创建草稿约骑时，小程序提交的表单。"""

    model_config = ConfigDict(extra="forbid")

    segment_id: int | None = None
    route_book_id: int | None = None
    start_time: datetime
    estimated_end_time: datetime
    meeting_point: str = Field(..., min_length=1, max_length=128)
    pace_level: PaceLevel
    max_participants: int = Field(..., ge=2, le=20)
    description: str | None = Field(None, max_length=2000)


class MeetupPatchRequest(BaseModel):
    """修改草稿约骑时允许改的字段。"""

    model_config = ConfigDict(extra="forbid")

    segment_id: int | None = None
    route_book_id: int | None = None
    start_time: datetime | None = None
    estimated_end_time: datetime | None = None
    meeting_point: str | None = Field(None, min_length=1, max_length=128)
    pace_level: PaceLevel | None = None
    max_participants: int | None = Field(None, ge=2, le=20)
    description: str | None = Field(None, max_length=2000)


class MeetupResponse(BaseModel):
    """返回给小程序的一张约骑卡片。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    creator_id: int | None = None
    status: MeetupStatus
    segment_id: int | None = None
    route_book_id: int | None = None
    snapshot_route_name: str
    snapshot_distance: float
    snapshot_climb: float | None = None
    snapshot_city: City
    start_time: datetime
    estimated_end_time: datetime
    meeting_point: str
    pace_level: PaceLevel
    max_participants: int
    description: str | None = None
    participants_count: int = 0
    first_media_file_id: str | None = None
    # 当前请求者视角的两个标记：前端靠它决定详情页显示"取消/退出/加入"哪个按钮。
    # 未登录（游客）时都为 False（详情仍可公开查看）。
    is_creator: bool = False
    has_joined: bool = False
    created_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None


class MeetupListResponse(BaseModel):
    """约骑列表页响应：卡片数组 + 分页信息。"""

    model_config = ConfigDict(extra="forbid")

    items: list[MeetupResponse]
    total: int
    page: int
    page_size: int


class MeetupMediaResponse(BaseModel):
    """返回给小程序的一张约骑图片或视频记录。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    meetup_id: int
    uploader_id: int | None = None
    type: Literal["image", "video"]
    file_id: str
    caption: str | None = None
    seq: int
    created_at: datetime | None = None
