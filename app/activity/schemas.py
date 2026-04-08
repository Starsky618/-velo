"""
骑行活动模块的请求/响应数据格式定义——"表格模板"。

和 User 模块的 schemas.py 一样的角色：
规定前端发请求时要填什么格式，后端返回数据时用什么格式。

注意事项：
- 每个接口的请求和响应都要有对应的 schema
- 不要在 schema 里写业务逻辑，只管格式校验
- 后续任务（3.7 查询接口）会在这里追加更多 schema
"""

from pydantic import BaseModel


# ========== 任务 3.5：GPX 上传 ==========

class UploadResponse(BaseModel):
    """上传成功后的响应：返回活动 ID 和当前状态"""
    activity_id: int
    status: str
