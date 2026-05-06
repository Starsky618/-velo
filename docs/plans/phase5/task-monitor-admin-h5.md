# 任务 monitor-admin-h5：admin H5 → api 端到端监测探针

> **2026-05-06 admin H5 502 事故的深层防御**（事故复盘见 `docs/deployment-diary.md`）
> Sprint 1+2+3 收尾后的独立增量 / 不依赖 Sprint 4 整体规划

## 🎯 目标

velo-monitor 容器里加一个新探针函数（与现有 `processing_health` 同级），每 60 秒探一次 admin H5 端到端链路。任何一项失败 → 飞书告警。

**抓哪类故障**（这次踩的就是这种）：
- admin-h5 容器挂了
- admin-h5 nginx 配置坏 / 启动失败
- admin-h5 → api 反代链路断（nginx DNS 缓存 / api 容器换 IP / network 隔离）
- 公网入口防火墙 / 端口映射坏

**不抓**：业务层错误（4xx / 5xx 含义在反代层都是"通"，告警太敏感反而噪音）。

## ⛓ 前置依赖

- task-1.C.1 已落地（`app/monitor/processing_health.py` + 飞书 webhook + monitor 容器）✅
- admin-h5 service 在 `docker-compose.yml` 里（D.5 部署时加的）✅
- monitor 容器在同 docker network 里，可以直接 hostname 访问 admin-h5（不需走公网）✅

## 📤 输出契约

| 文件 | 用途 |
|---|---|
| `app/monitor/admin_h5_health.py` | `scan_admin_h5_health() -> list[str]` 探 + 推飞书 |
| `tests/test_monitor_admin_h5_health.py` | 5 条路径单测（全 mock httpx） |
| `docker-compose.yml` 改 | monitor 容器主循环加调用 |

## 🧱 现状

- `app/monitor/processing_health.py` 已有完整模式可抄（scan + raise_for_status + catch + main 退码）
- `app/monitor/__init__.py` 已存在 / 包标识 OK
- `httpx==0.28.1` 已装
- `docker-compose.yml` 现状：`monitor.command: sh -c "while true; do python -m app.monitor.processing_health || true; sleep 60; done"`

## 🛠 完整设计

### 1. 探测项（2 条）

| 项 | URL | 期望响应 | 失败定义 |
|---|---|---|---|
| 静态站可达 | `GET http://admin-h5/` | 200 | 非 200 / timeout / network err |
| 反代到 api | `GET http://admin-h5/api/admin/whoami`（无 token）| **401**（"无效凭证"）| 5xx / timeout / network err |

**为啥反代探测期望 401 而不是 200**：
- `whoami` 需要 admin token；不带 token → backend `decode_token` 抛 → 返 401
- 如果反代到 api 通畅，401 是预期响应（说明全链路活着）
- 如果反代挂 → 502 / 503 / 504 → 探测失败（这就是本次事故的精确捕获点）
- 不带 token 探测最干净，不依赖任何 admin 凭证

### 2. 函数签名

```python
def scan_admin_h5_health() -> list[str]:
    """
    探活 admin H5 端到端 → 任何探测项失败 → 飞书告警。

    返回：
        list[str] 失败探测项名（空 = 全绿 / 不发告警）
    """
```

注意没有 `db: Session` 参数 —— 本探针不查 DB，只走 HTTP。

### 3. 失败处理

- 单次探测失败即告警（沿用 task-1.C.1 的简化模式 / 不去抖动 / 噪音过多再加）
- 飞书 webhook 5xx / 网络错 → catch + logger.error，不阻断
- `FEISHU_BOT_WEBHOOK` 未配 → 跳过推送但仍返失败列表（dev / CI 兼容）

### 4. monitor 容器主循环加调用

`docker-compose.yml` 改成：
```yaml
command: >
  sh -c "while true; do
    python -m app.monitor.processing_health || true;
    python -m app.monitor.admin_h5_health || true;
    sleep 60;
  done"
```

两个探针独立退码 / 独立失败 / 互不影响。

### 5. 飞书消息模板

```
🚨 admin H5 探活告警
失败项：static_site / api_proxy
建议：sudo docker compose ps / docker compose logs admin-h5
```

不带敏感信息（无 token / 无 IP / 无 user_id）→ 群里安全。

## ✅ 端到端验收

- [ ] 单测 5 条全过（全绿 / 静态站 502 / 反代 502 / webhook 挂 / 未配 webhook）
- [ ] 部署后手测：`sudo docker compose stop admin-h5` → 60 秒内飞书收到告警
- [ ] 恢复：`sudo docker compose up -d admin-h5` → 60 秒内自动绿（不需 ack / 没有"已恢复"消息也行 / 沉默 = 绿）
- [ ] 反代故障模拟：临时改 admin-h5 nginx 让 proxy_pass 指向不存在的 hostname（如 `not-exist:8000`）→ 60 秒内告警 "api_proxy"

## 🔍 自检三问

1. **为啥不监测公网 9000 端口（114.132.190.245:9000）**？
   → 容器内探测 `http://admin-h5/` 已能覆盖（admin-h5 容器是 nginx 入口）。公网 9000 失败一般是防火墙 / 端口映射，那不是 admin H5 自己的问题，留给基础设施监测（腾讯云）做。
2. **为啥单次失败就告警，不去抖动**？
   → 探测频率 60s / 每次只 2 个 HTTP 请求 / 真有故障 60 秒延迟告警已经够快。去抖动（连续 3 次失败）会让真故障延迟 3 分钟，得不偿失。如果生产噪音过多再加。
3. **为啥不集成进 processing_health.py 一起跑**？
   → 探针**不查 DB**（无 `Session` 参数）；processing_health 查 DB。模块边界划清：DB 层 vs HTTP 层不混。两个独立 main 命令 / 退码独立 / 失败互不影响。

## 📝 commit message

```
feat(monitor): admin H5 端到端探针 + 飞书告警

- 新增 app/monitor/admin_h5_health.py：探静态站 + 反代到 api 链路
- monitor 容器主循环加调用，每 60 秒探一次
- 单测 5 条路径全 mock httpx
- 抓本次（2026-05-06）502 事故同类故障：nginx DNS 缓存 / 反代挂 / 容器挂

参考 docs/plans/phase5/task-monitor-admin-h5.md
```
