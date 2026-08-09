"""
rq Worker 启动脚本——后台"快递分拣工人"的入口。

用法：python worker.py
启动后会一直运行，自动从 Redis 队列中取出待处理的任务（如 GPX 解析）并执行。

好比快递站的分拣员：一直守在传送带旁边，有包裹来了就拆开处理，
没包裹时就待命等着。可以同时启动多个 Worker 来加快处理速度。

v5 task-0.8 改造：
- Redis 连接 + Queue 实例从 app.queue 单一源 import，不再就地 Redis.from_url
- 支持 RQ_QUEUES env 多队列订阅。生产主 worker 跑 velo + ai_drafts；独立
  heatmap-worker 只跑 heatmap_tiles，避免不可抢占的长 PNG 任务堵住骑行导入。
- **列表顺序 = 队列优先级**：RQ Worker 按 queues 列表顺序消费，第一个有任务就
  优先处理。当前默认 "velo,ai_drafts"；heatmap_tiles 必须由显式环境变量启动的
  独立 worker 消费——改队列归属前先想清楚不可抢占任务的阻塞语义

注意事项：
- 必须先启动 Redis 服务，否则 Worker 连不上队列
- Worker 和 API 共用同一套数据库 session 逻辑（全同步设计）
- 不要在这个文件里写业务逻辑，它只负责启动 Worker
"""

import os

from rq import Worker

from app.queue import (
    ai_drafts_queue,
    default_queue,
    heatmap_tiles_queue,
    redis_conn,
    segment_rebuilds_queue,
)


# 已知队列名 → Queue 实例的映射
# 任何新加 Queue 必须在 app/queue.py 里 expose 后，在这登记一次
_QUEUES_MAP = {
    "velo": default_queue,
    "ai_drafts": ai_drafts_queue,
    "heatmap_tiles": heatmap_tiles_queue,
    "segment_rebuilds": segment_rebuilds_queue,
}


def _resolve_queues() -> list:
    """从 env RQ_QUEUES 解析要订阅的队列列表，未设 env 时默认订阅全部。"""
    raw = os.getenv("RQ_QUEUES", "velo,ai_drafts")
    names = [name.strip() for name in raw.split(",") if name.strip()]
    return [_QUEUES_MAP[name] for name in names if name in _QUEUES_MAP]


if __name__ == "__main__":
    queues = _resolve_queues()
    if not queues:
        raise RuntimeError(
            "RQ_QUEUES env 解析后 0 个有效队列——请检查拼写，"
            f"可选：{list(_QUEUES_MAP)}"
        )
    # 启动 Worker，监听指定队列；多队列时按列表顺序优先级处理
    Worker(queues, connection=redis_conn).work()
