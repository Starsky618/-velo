"""
RIDEMAP 后端 API 入口

整个应用的"大门"——所有请求从这里进来，被分配到各个模块的路由去处理。
可以把它想象成一栋大楼的前台：来客先到前台登记，前台再告诉你去几楼找谁。

除了 /health 健康检查端点外，各业务模块的路由通过 include_router 挂载。
新增模块时只需 import 其 router 并 include_router 即可，无需改动其他代码。
"""

from fastapi import FastAPI

from app.user.router import router as user_router

# 创建 FastAPI 应用实例
# title 和 version 会显示在自动生成的 API 文档页面上（/docs）
app = FastAPI(
    title="RIDEMAP API",
    version="0.1.0",
    description="公路骑行垂直平台后端 API",
)

# 挂载各模块路由——每个模块的接口通过 include_router 注册到应用上
app.include_router(user_router)


@app.get("/health")
def health_check():
    """
    健康检查端点——最简单的"活着吗？"接口。
    部署后用监控工具定期请求这个端点，
    如果返回 {"status": "ok"} 说明服务正常运行，
    否则说明服务挂了，需要报警。
    """
    return {"status": "ok"}
