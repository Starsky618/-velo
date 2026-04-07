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
