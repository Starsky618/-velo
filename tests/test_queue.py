"""
v5 task-0.8 验证：app/queue.py 单一 Redis 连接源契约保证。

不连真 Redis（导入级别测试），只验证：
1. redis_conn 模块级单例（多次 import 同一对象）
2. default_queue / ai_drafts_queue 共享同一连接
3. Queue 命名稳定（防拼写漂移成两个队列）
4. 请求链路的热图预热 producer 使用有界超时连接
"""


def test_redis_conn_is_module_singleton():
    """多次 import redis_conn 得到同一对象——证明是模块级单例。"""
    from app.queue import redis_conn
    from app.queue import redis_conn as redis_conn_2

    # 单例契约：is 比较（同一对象）而非 == 比较（值相等）
    assert redis_conn is redis_conn_2


def test_queues_share_redis_connection():
    """default_queue 和 ai_drafts_queue 必须共享同一 Redis 连接。

    若各自构造连接，连接池配置变更（max_connections / socket_keepalive）
    要改两处，违反 task-0.8 单一源原则。
    """
    from app.queue import redis_conn, default_queue, ai_drafts_queue

    assert default_queue.connection is redis_conn
    assert ai_drafts_queue.connection is redis_conn


def test_queue_names_stable():
    """队列名硬编码契约——防 'ai_drafts' / 'ai-drafts' 拼写漂移。

    若有人改了 Queue 实例名但漏改 enqueue 字符串，任务会进错队列
    Worker 永远捞不到 → 用户体感为"AI 草稿生成卡死"。
    """
    from app.queue import (
        default_queue,
        heatmap_prewarm_queue,
        ai_drafts_queue,
        segment_rebuilds_queue,
    )

    assert default_queue.name == "velo"
    assert heatmap_prewarm_queue.name == default_queue.name
    assert ai_drafts_queue.name == "ai_drafts"
    assert segment_rebuilds_queue.name == "segment_rebuilds"


def test_heatmap_prewarm_producer_has_bounded_redis_timeouts():
    """Redis 网络黑洞时，活动上传/删除不能卡在 post-commit 入队。"""
    from app.queue import heatmap_prewarm_queue

    kwargs = heatmap_prewarm_queue.connection.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 1.0
    assert kwargs["socket_timeout"] == 1.0
    assert kwargs["retry_on_timeout"] is False


def test_segment_rebuild_producer_has_bounded_redis_timeouts():
    """admin 提交标准几何时，Redis 黑洞不能无限卡住请求。"""
    from app.queue import segment_rebuilds_queue

    kwargs = segment_rebuilds_queue.connection.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 1.0
    assert kwargs["socket_timeout"] == 1.0


def test_redis_conn_decode_responses_is_false():
    """RQ 内部要 bytes—— decode_responses 必须 False，
    否则 RQ enqueue / dequeue 全部炸。"""
    from app.queue import redis_conn

    # connection_pool.connection_kwargs 是 redis-py 暴露的实际配置
    assert redis_conn.connection_pool.connection_kwargs.get("decode_responses") is False
