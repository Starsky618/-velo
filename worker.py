"""
rq Worker 启动脚本——后台"快递分拣工人"的入口。

用法：python worker.py
启动后会一直运行，自动从 Redis 队列中取出待处理的任务（如 GPX 解析）并执行。

好比快递站的分拣员：一直守在传送带旁边，有包裹来了就拆开处理，
没包裹时就待命等着。可以同时启动多个 Worker 来加快处理速度。

注意事项：
- 必须先启动 Redis 服务，否则 Worker 连不上队列
- Worker 和 API 共用同一套数据库 session 逻辑（全同步设计）
- 不要在这个文件里写业务逻辑，它只负责启动 Worker
"""

from redis import Redis
from rq import Worker, Queue

from app.config import settings

# 连接 Redis——队列的"传送带"就建在 Redis 上
redis_conn = Redis.from_url(settings.REDIS_URL)

# 创建名为 "ridemap" 的队列——所有异步任务都投递到这个队列
# 后续骑行模块上传 GPX 时，会把解析任务 enqueue 到这个队列
queue = Queue("ridemap", connection=redis_conn)

if __name__ == "__main__":
    # 启动 Worker，监听 ridemap 队列
    # Worker 会持续运行：取任务 → 执行 → 取下一个 → ...
    Worker([queue], connection=redis_conn).work()
