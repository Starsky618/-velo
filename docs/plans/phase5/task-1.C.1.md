# 任务 1.C.1：monitor 模块新建（worker 软目标 + 飞书告警）

> **task 卡 stale 修订**（2026-04-30 task-1.C.1 开工前同步 §7 第 5 问）：
> - "现状"区块行号 stale —— `_PROCESSING_TIMEOUT` 在 service.py **:41**（不是 :43）
> - spec §3.8 行号 stale —— 实际 **2287**（不是 2167-2245）
> - dev stack 同步：本 task 也加 `monitor` 容器到 `docker-compose.dev.yml`（task 卡只提生产 yml）

## 🎯 目标

新建 `app/monitor/processing_health.py`：扫 processing 状态超过 4 分钟的 activities，发飞书告警。沿用 v4 `_PROCESSING_TIMEOUT = 10 min` 硬上限**不改**——本 task 只加监控告警，不改业务。

## ⛓ 前置依赖

无（独立 worktree）。可与 Sprint 1 其他模块并行。

## 📤 输出契约

| 文件 / 容器 | 用途 |
|---|---|
| `app/monitor/__init__.py` | 包标识 |
| `app/monitor/processing_health.py` | `scan_processing_health(db) -> list[int]` 扫 + 推飞书 |
| docker-compose monitor 容器 | `while true; sleep 60; python -m app.monitor.processing_health` 包装 |

## 🧱 现状

- `app/monitor/` 目录**不存在**
- `app/activity/service.py:41` `_PROCESSING_TIMEOUT = 10 * 60`（沿用，不改 / grep 实证 :41 不是 :43）
- 现有 cron 模式：`scripts/cleanup_zombies.py` + docker-compose 内 `while true; sleep 300` 容器（沿用模式）
- `httpx==0.28.1` 已装（grep 实证 requirements.txt）—— 用 httpx 不用 requests
- `app/config.py` 无 `FEISHU_BOT_WEBHOOK` —— 本 task 加

## 🛠 完整代码

### 1. `app/monitor/__init__.py`

```python
"""运行时监控模块（v5 新建）。

边界：
- 读 activities 表（沿用现有，不改 status / _PROCESSING_TIMEOUT）
- 调外部告警通道（飞书 webhook）
- 不修改业务数据
"""
```

### 2. `app/monitor/processing_health.py`

抄 `docs/spec-v5.md §3.8`（行 2287 起）—— 含 `WARN_THRESHOLD_SEC = 4 * 60` + `scan_processing_health(db)`。

**关键修订（spec 已修）**：
- `from app.config import settings` + `settings.FEISHU_BOT_WEBHOOK`（陷阱 #2）
- `import httpx` 不是 `requests`
- timeout=5 秒
- 异常 catch 记 logger 不阻断（飞书挂不影响业务）

```python
# 主入口（命令行调用）
def main() -> int:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        stuck = scan_processing_health(db)
        return 0 if not stuck else 1  # 有 stuck 返 1 用于 cron 告警
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

### 3. `app/config.py` Settings 加

```python
FEISHU_BOT_WEBHOOK: str = ""
```

### 4. `.env.example` 加

```
FEISHU_BOT_WEBHOOK=
```

### 5. `docker-compose.yml` 新建 monitor 服务

```yaml
  monitor:
    build: .
    command: sh -c "while true; do python -m app.monitor.processing_health || true; sleep 60; done"
    depends_on:
      - db
    environment:
      DATABASE_URL: ${DATABASE_URL}
      FEISHU_BOT_WEBHOOK: ${FEISHU_BOT_WEBHOOK}
    restart: unless-stopped
```

> 沿用 cleanup_zombies 容器包装模式（docker-compose.yml:83 已有先例），周期 60s 比 cleanup 的 300s 更密（监控更敏）。第二轮双审 R3-Minor 修复说明独立周期。

## ✅ 测试

```python
# tests/test_monitor_processing_health.py
def test_scan_no_stuck_activities_returns_empty(db_session, activity_factory):
    # 全 completed → 返 []
def test_scan_stuck_4min_triggers_alert(db_session, activity_factory, mock_feishu):
    a = activity_factory(status='processing', updated_at=datetime.now(UTC) - timedelta(minutes=5))
    result = scan_processing_health(db_session)
    assert a.id in result
    mock_feishu.assert_called_once()
def test_scan_processing_under_4min_no_alert(db_session, activity_factory, mock_feishu):
    activity_factory(status='processing', updated_at=datetime.now(UTC) - timedelta(minutes=2))
    result = scan_processing_health(db_session)
    assert result == []
    mock_feishu.assert_not_called()
def test_scan_feishu_failure_swallowed(db_session, activity_factory, mock_feishu_500):
    # 飞书 5xx 不抛异常，仍返 stuck list
def test_scan_no_webhook_configured_skips(db_session, settings_no_webhook):
    # FEISHU_BOT_WEBHOOK="" → 跳过推送但仍记 logger
```

## 📝 commit

```
feat(monitor): 任务 1.C.1 monitor 模块新建（worker 软目标 + 飞书告警）

新建：
- app/monitor/__init__.py / processing_health.py
- WARN_THRESHOLD_SEC = 4 min（PRD 5.7.1 拍）
- 沿用 v4 _PROCESSING_TIMEOUT = 10 min 硬上限（不改）
- docker-compose 加 monitor 容器（while true; sleep 60 包装）
- app/config.py 加 FEISHU_BOT_WEBHOOK 字段
- httpx 调飞书（项目统一，不用 requests）

部署：worker 容器 --scale 3，monitor 单独容器 60s 一轮
```

## 🔍 自检三问

1. **崩溃恢复**：monitor 容器挂了，停几小时——业务受影响吗？  
   → 不影响。monitor 只读 + 推告警，不写业务表。停了仅丢失这段时间的告警；activities 仍走 v4 _PROCESSING_TIMEOUT 10 min 硬上限自愈。

2. **告警风暴防护**：同一卡死 activity 每 60s 一次告警，连续 5 分钟告警 5 次。会刷屏吗？  
   → v5 简化版接受刷屏。v6 可加"已告警 activity_id 缓存 30 min 不重发"。

3. **环境变量 N 处同步**（陷阱 #2）：FEISHU_BOT_WEBHOOK 是否在 settings + .env.example + docker-compose.yml monitor service environment 三处都加？  
   → 是。本 task 同 commit 改三处。
