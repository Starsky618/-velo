"""
RIDEMAP 后端 API 入口

整个应用的"大门"——所有请求从这里进来，被分配到各个模块的路由去处理。
可以把它想象成一栋大楼的前台：来客先到前台登记，前台再告诉你去几楼找谁。

目前只有一个 /health 端点，用来检查服务是否活着（类似心跳检测）。
后续每个模块开发完成后，会在这里用 include_router 把模块的路由"挂载"上来。
"""

from fastapi import FastAPI

# 创建 FastAPI 应用实例
# title 和 version 会显示在自动生成的 API 文档页面上（/docs）
app = FastAPI(
    title="RIDEMAP API",
    version="0.1.0",
    description="公路骑行垂直平台后端 API",
)


@app.get("/health")
def health_check():
    """
    健康检查端点——最简单的"活着吗？"接口。
    部署后用监控工具定期请求这个端点，
    如果返回 {"status": "ok"} 说明服务正常运行，
    否则说明服务挂了，需要报警。
    """
    return {"status": "ok"}
