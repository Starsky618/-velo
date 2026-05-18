"""
VELO 后端 API 入口

整个应用的"大门"——所有请求从这里进来，被分配到各个模块的路由去处理。
可以把它想象成一栋大楼的前台：来客先到前台登记，前台再告诉你去几楼找谁。

除了 /health 健康检查端点外，各业务模块的路由通过 include_router 挂载。
新增模块时只需 import 其 router 并 include_router 即可，无需改动其他代码。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.activity.router import router as activity_router
from app.admin.router import router as admin_router
from app.segment.router import (
    activity_segment_router,
    router as segment_router,
    user_effort_router,
)
from app.strava.router import router as strava_router
from app.user.router import router as user_router

# 创建 FastAPI 应用实例
# title 和 version 会显示在自动生成的 API 文档页面上（/docs）
app = FastAPI(
    title="VELO API",
    version="0.1.0",
    description="公路骑行垂直平台后端 API",
)

# 跨域配置——允许赛段创建工具（本地 HTML 文件）访问 API
# 生产环境应限制为实际域名，本地开发允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载各模块路由——每个模块的接口通过 include_router 注册到应用上
# 注册顺序无所谓，FastAPI 根据路径前缀分发请求
app.include_router(user_router)
app.include_router(activity_router)
app.include_router(segment_router)
app.include_router(user_effort_router)
app.include_router(activity_segment_router)
app.include_router(admin_router)
# Strava 集成模块——OAuth 授权、Webhook 回调、历史导入等
app.include_router(strava_router)
# 通知模块——PR/KOM 通知列表 + 用户荣誉表
from app.notification.router import notification_router, honor_router
app.include_router(notification_router)
app.include_router(honor_router)
# PERSONA_START / Persona Engine NPC 文案模块——给用户每条骑行一句"老登"半句话（task-4）
from app.agent.persona.router import router as persona_router
app.include_router(persona_router)
# PERSONA_END


@app.get("/health")
def health_check():
    """
    健康检查端点——最简单的"活着吗？"接口。
    部署后用监控工具定期请求这个端点，
    如果返回 {"status": "ok"} 说明服务正常运行，
    否则说明服务挂了，需要报警。
    """
    return {"status": "ok"}
