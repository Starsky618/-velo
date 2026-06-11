"""
约骑接口格式——小程序和后端约定每张约骑卡片长什么样。

操作注意事项：这里只定义请求/响应形状，不放状态机规则；状态机统一在 service 层执行。
输入/输出数据流：router 接收这些 schema，调用 service 后再组装成 `MeetupResponse`。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MeetupStatus = Literal["DRAFT", "OPEN", "CANCELLED", "COMPLETED"]
PaceLevel = Literal["relaxed", "cruise", "training", "race"]
City = Literal["beijing", "shanghai", "hangzhou", "shenzhen", "chengdu", "taiyuan", "unknown"]
MeetupVisibility = Literal["public", "invite_only"]

_AUDIENCE_TAGS = {
    "climb_steady",
    "high_intensity",
    "leisure",
    "photography",
    "female_friendly",
    "newbie_caution",
}


def _validate_audience_tags(value):
    if value is None:
        return None

    cleaned = []
    seen = set()
    for tag in value:
        if tag not in _AUDIENCE_TAGS:
            raise ValueError("audience_tags 包含非法标签")
        if tag not in seen:
            cleaned.append(tag)
            seen.add(tag)

    if len(cleaned) > 6:
        raise ValueError("audience_tags 最多 6 个")
    return cleaned


class MeetupSocialFields(BaseModel):
    """约骑发布前总览里的社交字段：谁适合来、谁能看到、有什么安全提示。"""

    supply_point: str | None = Field(None, max_length=128)
    audience_tags: list[str] = Field(default_factory=list)
    visibility: MeetupVisibility = "public"
    eligibility_note: str | None = Field(None, max_length=100)
    safety_note: str | None = Field(None, max_length=200)

    @field_validator("audience_tags")
    @classmethod
    def validate_audience_tags(cls, value):
        return _validate_audience_tags(value)


class MeetupCreateRequest(MeetupSocialFields):
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
    supply_point: str | None = Field(None, max_length=128)
    audience_tags: list[str] | None = None
    visibility: MeetupVisibility | None = None
    eligibility_note: str | None = Field(None, max_length=100)
    safety_note: str | None = Field(None, max_length=200)

    @field_validator("audience_tags")
    @classmethod
    def validate_patch_audience_tags(cls, value):
        return _validate_audience_tags(value)


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
    supply_point: str | None = None
    audience_tags: list[str] = Field(default_factory=list)
    visibility: MeetupVisibility = "public"
    eligibility_note: str | None = None
    safety_note: str | None = None
    share_token: str | None = None
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


class InviteeSummary(BaseModel):
    """已加入骑友列表里的单个用户摘要。"""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    nickname: str | None = None
    avatar_url: str | None = None
    is_creator: bool
    joined_at: datetime | None = None


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


class MeetupReportTotals(BaseModel):
    """战报顶部的合计数字：只统计已交卷的骑行，未交卷的人只占人数。"""

    model_config = ConfigDict(extra="forbid")

    distance_km: float
    climb_m: float
    rider_count: int
    submitted_count: int


class MeetupReportCell(BaseModel):
    """战报里的一格：已交卷显示成绩，未交卷保留灰格。"""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    nickname: str | None = None
    avatar_url: str | None = None
    submitted: bool
    distance_km: float | None = None
    avg_speed: float | None = None
    elevation_gain: float | None = Field(default=None, serialization_alias="climb_m")
    created_at: datetime | None = Field(default=None, serialization_alias="submitted_at")


class MeetupReportOut(BaseModel):
    """一场约骑的成绩册：合计、照片墙和每人一格。"""

    model_config = ConfigDict(extra="forbid")

    meetup_id: int
    totals: MeetupReportTotals
    media: list[MeetupMediaResponse]
    cells: list[MeetupReportCell]
