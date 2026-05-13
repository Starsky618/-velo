# Sprint 5 task-1：pg_dump 自动备份脚本（MVP）

> **背景**：v5 收尾 task-4.3 part-1 抓到生产 DB 无任何备份机制（任意手抖 / alembic 翻车 / drop = 数据全损），列入 tech-debt 顶部 P0 + 阻塞 task-4.3 §2 alembic 真 PG 双向。
> **临时目录命名**：`docs/plans/sprint-5/`（沿用 v5 期 sprint-frontend/ 的临时命名风格 / 未来开 phase-6 整期 PRD 时 `mv` 重命名）。
> **Tim 2026-05-10 22:40 brainstorm 拍板**（详 §1）。

## 🎯 目标

实现"任意手抖 / alembic 翻车 / drop 类操作能 5 分钟回滚到昨晚"的 MVP 备份能力。最坏丢一天。

## ⛓ 前置依赖

- v5 期 closure（已 commit `9a9c3fa`）
- 现有 polling 容器模式（cleanup / monitor / curation-pool-cron / 见 docker-compose.yml）

## 📤 输出契约

- `~/velo/backups/velo_YYYYMMDD_HHMMSS.sql.gz` 文件（每天凌晨 3 点新增 / 7 天滚动）
- `monitor` 容器 stdout：`backup_freshness` 探针每 60s 跑一次 / 最新备份 > 30h → log warning（log-only / D 决策）
- `db-backup` 容器 stdout：每次 dump 完成 / 失败 → logger.info / logger.error

## 🛠 §1 Brainstorm 决策入册（Tim 2026-05-10 22:40 拍）

| # | 决策点 | Tim 选 | 备选 + 推迟原因 |
|---|------|------|-------|
| 1 | 备份范围 | **MVP（本地 + 天 cron + 7 天保留）** | 异地（scp/OSS）/ 全云直推 留 Sprint 5 backlog（100 用户量级 + 服务器物理炸概率极低，最大风险是 alembic / 手抖 → 本地够） |
| 2 | 触发时机 | **每 24h 一次（启动相对周期 / 不强制凌晨）** | alembic 钩子 / 手动 trigger / alpine crond 真凌晨调度都留 backlog（先建立基础节奏 + 跟现有 cleanup/monitor/curation-pool-cron 同 while-true 模式 / 100 用户量级 + log-only + pg_dump MVCC 不锁表 → 中午跑也不影响 / codex 异源审 2026-05-10 抓 spec drift "凌晨"已修文档保架构一致） |
| 3 | 告警机制 | **monitor 探针 backup_freshness（log-only / D 决策一致）** | 飞书 webhook 推迟（D 决策 / .env 加一行可激活但暂不接通）/ 未升级 monitor 仅日志路径 |
| 4 | 备份路径 | **~/velo/backups/**（host 路径 / docker volume 挂载） | /var/backups/velo 需 sudo 不便利 / docker volume 不能 SSH ls |
| 5 | 检查方式 | **monitor 加 backup_freshness 探针** | 仅看 db-backup 容器日志（更简但需手动）→ 升级到 monitor 探针 / 多 20 分钟落地 |
| 6 | 首次跑 | **部署完手动跑一次 verify** | 等今晚凌晨 cron 自然跑（首次跑出问题不知道直到明天）→ 拒 |
| 7 | 期范围 | **先单任务推进 / 不开 phase-6 PRD** | Sprint 5 backlog 还有 D33 / tied PR / D28 等，但今晚先做完 pg_dump 这一项 |

**关键技术决策**：

| 维度 | 选 | 原因 |
|---|---|---|
| backup 容器镜像 | `postgres:16-alpine` | 自带 pg_dump / 不用给主 velo 镜像装 postgresql-client / 镜像本就有所以 0 额外大小 |
| 备份文件格式 | `.sql.gz` | pg_dump 文本 + gzip ~10x 压缩比 / 可读 / restore 简单 `gunzip < x.sql.gz \| psql` |
| 滚动策略 | 7 天滚动（按 mtime 删 7 天前文件） | MVP 简单 / 未来加分级（周备份月备份）留 backlog |
| 探针频率 | monitor 主循环复用 60s 一轮 | 跟现有 processing_health / admin_h5_health 同节奏 / 0 新调度 |
| 告警阈值 | 最新备份 mtime > 30h 触发 warning | 留 6h buffer（cron 失败 1 次仍允许 / 失败 2 次才 warning） |

## 🛠 §2 操作步骤

### 1. 写 backup 脚本 `scripts/backup_db.sh`

```bash
#!/bin/sh
# 在 db-backup 容器内跑（postgres:16-alpine 镜像）
# 用 PGPASSWORD env 自动认证，pg_dump 出 .sql 后立刻 gzip 压
# 删 7 天前的 .sql.gz 文件
```

要点：
- 用 `PGPASSWORD` env / 容器内 `pg_dump -h db -U velo -d velo`（连 docker network 内的 db 服务）
- 文件名 `velo_$(date +%Y%m%d_%H%M%S).sql.gz`
- `find /backups -name 'velo_*.sql.gz' -mtime +7 -delete` 删 7 天前文件
- 错误分支：pg_dump 失败 → echo error + exit 1（让 sh 主循环看到非 0 但不停）

### 2. 写 monitor 探针 `app/monitor/backup_freshness.py`

沿用 `processing_health.py` 风格（模块 docstring 完整 / 干啥用 / 注意事项 / 数据流 / 部署 / 函数 docstring）。

要点：
- `Path("/backups").glob("velo_*.sql.gz")` 找最新文件
- `mtime` < now - 30h → `logger.warning("backup stale: latest is X hours old")`
- 无任何文件（首次 / 备份从没跑成）→ `logger.error("no backup found in /backups")`
- main() 退码：0=新鲜 / 1=陈旧或无文件

### 3. 改 `docker-compose.yml`

新增 `db-backup` 服务：
```yaml
db-backup:
  image: postgres:16-alpine
  command: sh -c "while true; do /scripts/backup_db.sh || true; sleep 86400; done"
  restart: unless-stopped
  environment:
    PGPASSWORD: ${DB_PASSWORD}
  volumes:
    - ./scripts:/scripts:ro
    - ./backups:/backups
  depends_on:
    - db
```

改 `monitor` 服务 command 加第 3 个探针：
```yaml
command: >
  sh -c "while true;
  do python -m app.monitor.processing_health || true;
  python -m app.monitor.admin_h5_health || true;
  python -m app.monitor.backup_freshness || true;
  sleep 60;
  done"
```

monitor 容器需挂 `./backups:/backups:ro`（只读访问 / 探针只 stat 不写）。

### 4. 测试 `tests/test_backup_freshness.py`

- 探针对空目录 → log error + 退 1
- 探针对 < 30h 的文件 → log info + 退 0
- 探针对 > 30h 的文件 → log warning + 退 1
- 探针对多个文件取最新 mtime（不是 ctime / 不是文件名时间戳）

### 5. 部署 SOP（按 memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md` 5 步）

```bash
# 1. 本地 git push
git push origin main

# 2. 远端 git pull
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull"

# 3. 创建 backup 目录（host 侧）+ chmod 755
ssh ubuntu@114.132.190.245 "mkdir -p ~/velo/backups && chmod 755 ~/velo/backups"

# 4. up -d --build（不是 restart / 改 docker-compose 必须 build）
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build db-backup monitor"

# 5. 手动跑一次 verify + 看 monitor 探针
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose exec db-backup /scripts/backup_db.sh"
ssh ubuntu@114.132.190.245 "ls -lh ~/velo/backups/"  # 应该看到 velo_xxx.sql.gz
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose exec db-backup gunzip -c /backups/velo_*.sql.gz | head -50"  # 看 pg_dump 内容真实
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose logs monitor --tail 20"  # 应该看到 backup_freshness 跑
```

## ✅ 验收（全部 ✅ / 2026-05-10 23:05 ship / commit `e5c71d0`）

- [x] `scripts/backup_db.sh` 写完 + 含 pg_isready 等待 + pg_dump 拆 pipe（codex round-1 抓 Critical 闭环）
- [x] `app/monitor/backup_freshness.py` 写完 + pytest **7 case 通过**（5 主路径 + 2 边界 case / codex round-2 Nice 闭环）
- [x] `docker-compose.yml` 加 `db-backup`（postgres:16-alpine）+ monitor 挂 `./backups:/backups:ro` + monitor command 加 backup_freshness 探针（第 3 个）
- [x] Claude 主 agent 自审 + 抓 1 Critical（pg_dump|gzip pipe 退码陷阱）+ 修闭环
- [x] codex 异源审 2 轮收敛（round-1 1 Critical + 1 Important + 1 Nice / round-2 全闭环 Critical=0）
- [x] 部署 + 手动跑 verify（28.2 MB 备份 / gunzip 头部真 pg_dump 16.13 + PostGIS schema）+ monitor 探针 log 健康路径 silent
- [x] **生产 11 容器全 Up**（cleanup / curation-pool-cron / db / **db-backup** / redis / scheduler / worker / monitor / api / admin-h5 / caddy）

**真实 verify 数据**（生产服务器 ubuntu@114.132.190.245 / 23:04 SSH 实证）：
```
ls -lh ~/velo/backups/
-rw-r--r-- 1 root root 29M May 10 23:04 velo_20260510_150351.sql.gz  ← 容器自启动时跑
-rw-r--r-- 1 root root 29M May 10 23:04 velo_20260510_150409.sql.gz  ← 我手动跑
```

backup 8 秒完成 / 文件 29M / 含 PostgreSQL 16.4 + PostGIS tiger schema + 全表 dump。restore 命令（未来真灾难时）：
```bash
gunzip -c ~/velo/backups/velo_<TS>.sql.gz | sudo docker compose exec -T db psql -U velo -d velo
```

## 📝 commit

```
feat(infra): Sprint 5 task-1 pg_dump 自动备份 MVP

- scripts/backup_db.sh：pg_dump | gzip / 7 天滚动
- db-backup 容器（postgres:16-alpine / 天 cron）
- monitor 加 backup_freshness 探针（log-only / D 决策）
- 部署后手动跑 + verify backup 文件 + monitor 日志
```

## 🔍 自检三问

1. **MVP 边界**：服务器物理炸 / 被删 / 整盘格式化 → 本方案能救吗？  
   → 不能。MVP 只防 alembic / 手抖 / drop 类应用层失误。物理炸场景留 Sprint 5 backlog（异地 scp 或 OSS）。

2. **首次部署后 30h 内**：探针会不会误报"陈旧"？  
   → 会。首次部署后 30h 内若 cron 还没跑过第一次（凌晨 3 点），探针会 warning。**所以 §2 步骤 5 强制部署完手动跑一次** = 解决首日 false alarm。

3. **备份失败 → 探针报陈旧 → 我能修复吗？**  
   → 能。`sudo docker compose logs db-backup` 看错误原因（连 db 失败 / 磁盘满 / 权限错）→ 修后再手动跑一次。下次自然 cron 接上。
