# 任务 4.1：文档刷新

## 🎯 目标

收尾期间刷新 4 份关键文档，让架构 / 数据流 / 变更 / 技术债的"地图"反映 v5 期最新状态。

## ⛓ 前置依赖

Sprint 1+2+3 全部完成（含部署）。

## 📤 输出契约

| 文档 | 改动 |
|---|---|
| `docs/architecture-guide.md` | 加 v5 新模块（agent / monitor / common / admin）+ 新增的 7 条数据流 |
| `docs/data-flow-guide.md` | 加 7 条新链路（spec §1.3 列出） |
| `docs/changelog.md` | 追加 v5 期 changelog 条目（按 task 分类） |
| `docs/tech-debt.md` | 移除 Sprint 0 已修的 P1（datetime / Redis 散点 / .get() / scheduler 复用） + 新增 v5 实施期发现的 |

## 🧱 现状

- `docs/architecture-guide.md` 现有 v4 状态（含 6 模块：user / activity / segment / notification / strava / 顶层）
- `docs/data-flow-guide.md` 现有 9 条链路
- `docs/changelog.md` 现有 v0-v4 条目
- `docs/tech-debt.md` 现有列表（Sprint 0 task 0.1-0.5 / 0.8 对应 P1 项）

## 🛠 操作步骤

### 1. architecture-guide.md 刷新

- 模块清单加 4 新模块：`app/common/` / `app/agent/` / `app/monitor/` / `app/admin/`
- 模块依赖图加新边：admin → segment / user，agent → segment.models / RQ，monitor → activity.models
- 描述各新模块"是干什么的 / 操作注意事项"（项目硬要求：每个 Python 文件夹 __init__.py 第一句话用通俗语言说明）

### 2. data-flow-guide.md 加 7 条链路

按 spec §1.3 + §2.7 列的 7 条链路展开：

1. **赛段创建 (5.B.1 + 5.D.4)**：trackpoints → 算法 → segments
2. **AI 介绍 (5.B.2 + 5.D.1 + 5.D.2)**：候选池脚本 → admin 勾选 → ai_drafts_queue → tasks.py → Anthropic → segment_ai_drafts → 审核 → segments.description
3. **即时反馈 (5.C.1)**：访问赛段页 → service 查 last/PR + diff → API 返
4. **功率曲线 (5.C.2)**：访问个人页 → 算 power_curve_from_activities → Redis 缓存 → 返多曲线
5. **进步推送 (5.C.3)**：activity completed → progress_detector → 阈值 → notifications
6. **个人热图 (5.A.1)**：访问个人页 → service 按 user.city 查 simplified_track → JSONB Python 聚合 → 返 points
7. **看他人主页 (5.A.2)**：跳转 → GET /api/users/{id}/profile → RESPONSE_KEYS 白名单 → 返

每条链路标注：模块 / 表 / 关键陷阱。

### 3. changelog.md 追加

```markdown
## v5 (2026-04 至 2026-06) — 赛段内容深化 + 数据成长 + 个人页 + admin 工具

### Sprint 0：地基修补
- task 0.1 datetime 全局 tz-aware（5 表 12 列 + Python 端）
- task 0.2 ensure_valid_token 签名改造
- ...

### Sprint 1
- task 1.A.* segment 模块 5.B.1/5.B.3/5.C.1
- task 1.B.1 agent 模块新建 + ai_drafts_queue 异步路径
- task 1.C.1 monitor 模块 + 飞书告警

### Sprint 2
- task 2.A.1 progress_detector + payload 字段
- task 2.B.1 power_curve 算法
- task 2.C.* user 模块 5.C.2/5.A.1/5.A.2

### Sprint 3
- task 3.A.* admin 5 endpoint
- task 3.B.1 H5 admin 项目骨架
- task 3.C.1 候选池脚本 + cron

### 重要修订
- 三轮 spec 双审 14 Critical + 28 Important 全修
- 第二轮拍 3 决策（公开赛段目录 / queue.py 单一源 / common.geo）
```

### 4. tech-debt.md 处理

**移除 Sprint 0 已修项**：
- ❌ datetime naive 散点（已修）
- ❌ Redis 连接散在 4 处（已修，task-0.8 收敛）
- ❌ ensure_valid_token 行锁注释化（已修）
- ❌ SQLAlchemy legacy `.get()`（已修）
- ❌ scheduler Redis 连接（已修，task-0.5）

**新增 v5 实施期发现的 P1 / P2**：
- 由 4.4 复盘归档时填入

## ✅ 测试

无单元测试（纯文档）。但执行验收：

- 我（主 agent）通读 architecture-guide.md 能 10 分钟内复述全貌（黑盒度三问之一）
- 任意 subagent 拿到 data-flow-guide.md 任一链路能 30 秒内走通

## 📝 commit

```
docs(v5): 任务 4.1 收尾文档刷新

- architecture-guide.md：加 v5 4 新模块（common/agent/monitor/admin）
- data-flow-guide.md：加 v5 7 条新链路
- changelog.md：v5 期完整 task 清单
- tech-debt.md：移除 Sprint 0 已修 P1 5 项
```

## 🔍 自检三问

1. **架构图同步**：4 新模块在依赖图上的位置画对了吗？common 在最下方（任意模块可向下依赖）/ admin 在 segment+user 之上 / agent 与 segment 平级 / monitor 与 activity 平级。  
   → 验证 architecture-guide 依赖图。

2. **数据流可复述性**：data-flow-guide.md 7 条新链路写完后，任意找一条让自己复述能不查文档？  
   → 黑盒度三问之二（4.2 任务）。

3. **changelog 简洁度**：每个 task 一行（不展开内部细节）。subagent 拿任务卡 + spec 已能拼出全部细节，changelog 是索引不是档案。  
   → 是。
