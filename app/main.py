"""
VELO 后端 API 入口

整个应用的"大门"——所有请求从这里进来，被分配到各个模块的路由去处理。
可以把它想象成一栋大楼的前台：来客先到前台登记，前台再告诉你去几楼找谁。

除了 /health 健康检查端点外，各业务模块的路由通过 include_router 挂载。
新增模块时只需 import 其 router 并 include_router 即可，无需改动其他代码。
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# api 容器的应用层日志开关——uvicorn 只配它自己的 access/error 日志，
# 不给应用 logger 配 handler，所有业务 logger.info（如五环节 SENSOR 埋点）会被静默吞掉。
# worker / scheduler 各自入口有 basicConfig，唯独 api 没有——2026-06-11 T6 真用回归实证：
# 请求 200 但 SENSOR view 行永不出现（喇叭没插电第 4 例）。root 已有 handler 时本行是 no-op。
logging.basicConfig(level=logging.INFO, format="%(asctime)s [api] %(levelname)s %(message)s")

# httpx 的 INFO 请求日志会包含完整 URL；腾讯地图、微信登录等接口会把 key、sig、secret
# 放在查询参数里，若跟随根 logger 输出就会把凭据写进容器日志。业务异常由各调用方记录，
# HTTP 客户端本身只保留 WARNING 以上，避免生产日志成为第二份凭据仓库。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.activity.router import router as activity_router
from app.admin.router import router as admin_router
from app.meetup.router import router as meetup_router
from app.route_book.guides_router import router as route_guides_router  # /api/route-guides
from app.route_book.router import router as route_book_router
from app.segment.router import (
    activity_segment_router,
    router as segment_router,
    user_effort_router,
)
from app.strava.router import router as strava_router
from app.training.router import router as training_router
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
app.include_router(route_book_router)
app.include_router(route_guides_router)
app.include_router(meetup_router)
app.include_router(admin_router)
# 训练负荷模块——PMC 曲线（CTL/ATL/TSB）和训练日历顶部状态卡
app.include_router(training_router)
# Strava 集成模块——OAuth 授权、Webhook 回调、历史导入等
app.include_router(strava_router)
# 通知模块——PR/KOM 通知列表 + 用户荣誉表
from app.notification.router import notification_router, honor_router
app.include_router(notification_router)
app.include_router(honor_router)


@app.get("/health")
def health_check():
    """
    健康检查端点——最简单的"活着吗？"接口。
    部署后用监控工具定期请求这个端点，
    如果返回 {"status": "ok"} 说明服务正常运行，
    否则说明服务挂了，需要报警。
    """
    return {"status": "ok"}
