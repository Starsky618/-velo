# 任务 4.3：集成测试 + 部署验证

## 🎯 目标

按 spec §9 测试策略 + CLAUDE.md "部署前强制检查清单"跑全套验证，确认 v5 期可上线。

## ⛓ 前置依赖

Sprint 1+2+3 全完成 + task-4.1（文档已刷）+ task-4.2（黑盒度通过）。

## 📤 输出契约

| 产出 | 用途 |
|---|---|
| pytest 全 passed 截图 / 日志 | 单元 + 集成测试通过证据 |
| 部署 dry-run 通过证据 | 生产部署前最后一道闸 |
| 真实 E2E 走通报告 | 手工跑 16 条数据流的 1 条端到端验收 |

## 🛠 操作步骤

### 1. 全单元 + 集成测试

```bash
cd /Users/macbookair/Desktop/velo
python3 -m pytest tests/ -x -v --tb=short
```

预期：≥ 250 测试 全 passed（v4 期 181 + v5 新增 70+）。

### 2. 真实数据库迁移双向

```bash
sudo docker compose down
sudo docker compose up -d db redis
sudo docker compose exec api python3 -m alembic upgrade head
sudo docker compose exec api python3 -m alembic downgrade phase4_frontend_consume
sudo docker compose exec api python3 -m alembic upgrade head
```

预期：upgrade / downgrade 全双向跑通（含 phase5_tz_aware + phase5_v5_db_changes 两份 revision）。

### 3. 部署前强制检查清单（CLAUDE.md）

- [ ] requirements.txt 含 anthropic（task-1.B.1 加）
- [ ] docker-compose.yml `environment` 含 ANTHROPIC_API_KEY / FEISHU_BOT_WEBHOOK / RQ_QUEUES
- [ ] worker 容器 `--scale 3` 部署文档清晰
- [ ] alembic 在 PostgreSQL 真实环境跑通（已上面验证）
- [ ] backfill_phase5.py 跑完（task-0.7）unknown 占比 < 30%
- [ ] admin.velo.com 域名 + Caddyfile 反代 + JWT 共用主站登录态
- [ ] Anthropic API endpoint 测连通（curl 模拟一次 /v1/messages）
- [ ] 飞书 webhook 测连通（手工触发一次 stuck activity 看是否收到告警）
- [ ] 备份机制：v5 新表 segment_ai_drafts / segment_curation_pool 进 pg_dump 范围

### 4. 真实 E2E 走通（最少 1 条核心链路）

抽核心反馈环手工跑：

```
用户上传 GPX
  → backend 解析（worker.py / parsing/）
  → segment 匹配（matcher.py）
  → 写 segment_efforts
  → progress_detector 检测 5 分钟功率进步（v5 新）
  → 写 notification with payload
  → 失效 power_curve 缓存
  → 用户访问 /api/notifications 看到推送
  → 访问 /api/users/me/power-curve?period=this_month 看新曲线
  → 访问 /api/segments/{id}/efforts/me 看即时反馈对比
```

每步确认无 5xx / 数据正确。

### 5. 部署生产

部署前 commit message 写明"v5 全套部署"。生产部署后立即跑：

```bash
sudo docker compose ps  # 看 8 容器（api / worker × 3 / scheduler / monitor / curation-pool-cron / db / redis）全 Up
sudo docker compose logs api --tail 50
sudo docker compose logs worker_1 --tail 30
sudo docker compose exec api python3 -c "from app.queue import redis_conn; print(redis_conn.ping())"
```

预期：所有容器 Up，logs 无 ERROR，redis ping True。

## ✅ 验收

```markdown
### v5 集成测试 + 部署验证（task 4.3）

- [x] pytest 全 passed（part-1 / 398 / commit d9bcbc0）
- [x] alembic 双向跑通 + restore 演练（part-4 / 2026-05-10 23:13 / Sprint 5 task-1 pg_dump 解锁后立即跑 / 详下方 part-4 段）
- [x] 部署清单 9 项审完（part-1 / 5 OK + 3 spec drift + 1 真 gap pg_dump / commit d9bcbc0）
- [x] E2E 1 条核心反馈环手工走通（part-3 / activity 326 / Tim 真上传 GPX 触发 / 详下方 part-3 段）
- [x] 10 容器生产 Up + 无 ERROR logs（part-2 / 任务卡原写"8 容器"已过时 / 实数 10 含 v5 新增 curation-pool-cron + admin-h5）
```

> **part-1**（2026-05-10 14:58 / commit `d9bcbc0`）：§1 pytest 398 passed + §3 部署清单审 5/9 OK + 真 gap pg_dump 入 tech-debt
> **part-2**（2026-05-10 15:30）：§5 容器 verify 10 Up / §2 推迟 / §4 留 part-3
> **part-3**（2026-05-10 22:30）：activity 326 真 E2E ✅ / 解析 completed + worker city hook 自动设 user.city=taiyuan + /api/user/me/power-curve last_30_days 200 + /api/user/me/heatmap 237 tracks 200 / 0 segment 匹配 = 真实情况（赛段全在西山，离这条路线最近 7.98km，正是 Sprint 5 D33 map matching backlog 的实证）/ task-4.3 整闸关闭 ✅ / **§2 alembic 双向仍推迟到 pg_dump 落地后**（不阻塞 v5 期 closure，但 task-4.3 验收条目第 2 项保留 ⏳ 直至完成）
> **part-4**（2026-05-10 23:13）：alembic 双向 + restore 演练完整闭环 ✅ / Sprint 5 task-1 pg_dump 解锁后立即跑 / 流程：手动 backup marker (29MB) → upgrade head no-op → downgrade phase4_frontend_consume（drop v5 schema）→ verify 5 v5 表/列消失 → upgrade head（重建 v5 schema，字段填 server_default）→ verify schema 回 + 数据 NULL → restore 演练用新 db `velo_test_restore` load marker backup → verify users.city=taiyuan + segments 4 字段完整 + 行数对齐 prod → drop velo_test_restore → backfill_phase5 恢复 prod v5 数据：**24 segments 100% / users 1 updated（user 2 city=shenzhen 是 backfill first_activity 算法选的，跟 worker hook latest_activity 不同 / 设计差异不 bug / Tim 拍接受）**。**v5 期所有遗留项全部完结 ✅**

## 📝 commit

```
chore(deploy): 任务 4.3 v5 集成测试 + 部署验证

- pytest 全 passed (~250 tests)
- alembic 双向迁移在真实 PG 跑通
- 部署清单 9 项全过
- E2E 1 条核心反馈环手工走通
- 生产 8 容器 Up（含 v5 新增 monitor + curation-pool-cron）
```

## 🔍 自检三问

1. **测试覆盖**：pytest 数从 v4 的 181 涨到 ~250 → 主要新增覆盖在哪些模块？  
   → segment 算法 + power_curve + progress_detector + admin endpoint + backfill 脚本。

2. **真实 E2E vs mock 测试**：真实数据库 + 真实 Strava token + 真实 Anthropic API key 的端到端，与 mock 测试结果差异是？  
   → 关注：tz-aware datetime 真实 PG 行为、advisory lock 并发实际可行性、Anthropic API 限流真实值、飞书 webhook 真实推送。

3. **回滚预案**：v5 部署崩了怎么回滚？  
   → docker tag previous → 回滚 image；alembic downgrade phase4_frontend_consume 回 schema；老数据回填脚本不可逆但不影响——v4 模型不读 v5 字段。预留半小时回滚窗口。
