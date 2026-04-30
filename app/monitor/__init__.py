"""
运行时监控模块（v5 task-1.C.1 / 5.7.1 / 新建）。

干啥用：
- 周期性扫 activities 表里 status='processing' 卡住超 4 分钟的记录，推飞书告警
- 让我们三人（Tim / CCF / 颜颜）能及时知道"哪个用户的 GPX 解析挂了"
- 单纯监控告警，**不改业务**——卡 10 分钟硬上限的自愈仍走 v4 worker 现有机制

操作注意（边界硬约束）：
- 本模块只读 activities 表 / 调外部 webhook，**不写任何业务表**
- **不改** `_PROCESSING_TIMEOUT = 10 * 60`（v4 硬上限，不动）
- 飞书 webhook 挂了 / 没配 → 不阻断业务，logger 记一笔即可
- 单元 / 集成测试时 mock httpx.post，禁止真调外部接口

数据流：
- 入：DB session（每 60 秒由 docker-compose monitor 容器定时调）
- 出：触发告警的 activity_id 列表（[]空表示一切正常）+ 副作用 httpx.post 推飞书
"""
