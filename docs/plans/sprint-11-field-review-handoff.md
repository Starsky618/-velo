# Sprint 11 字段审查交接给 Claude

> **状态**：Codex 已做字段审查和文档修正；尚未写代码实现。
>
> **请 Claude 审**：PRD + spec + plan 是否足够开工；重点看字段合同、隐私、可删除边界。

---

## 1. 一句话结论

Sprint 11 可以继续进入 spec 审核，但不能直接实现；关键字段真实存在，主要风险已经收束到 4 条硬合同：`raw_zones` 脱敏、42 天北京时间双边界、dedupe 过滤、Sprint 11 不误伤现有 `/api/training/load`。

---

## 2. 智能体自检结果

### 字段审查智能体

结论：无 Critical。字段真实存在，可以进入 spec 编写。

Important：
- `raw_zones` 不能原样返回；真实 `power_zones` 带 `min_w/max_w`，[✓ grep] `app/activity/power_zones.py:97-104`，隐私遮罩也把它视为可反推 FTP 的字段，[✓ grep] `app/activity/service.py:91-95`。
- 42 天窗口必须写上下界；现有训练模块已有北京时间转 UTC 的做法，[✓ grep] `app/training/service.py:73-75`、`:107-123`。
- `duplicate_of IS NULL` 必须写入新 service；现有训练负荷覆盖率查询没有 dedupe，[✓ grep] `app/training/service.py:117-123`，不能照抄。

### 模块边界智能体

结论：原 PRD 有 1 个 Critical，已修。

Critical：
- 原文写“不让 activity 模块 import training”，但真实系统已有 Sprint 10 daily load hook：[✓ grep] `app/activity/worker.py:371-381`、`app/strava/worker_strava.py:373-381`。已改成“Sprint 11 不新增 activity -> training 依赖；现有 Sprint 10 hook 保留”。

Important：
- `/api/training/load` 和新 `/distribution` 共用 router/schema 文件，必须写清删除 Sprint 11 时只撤新 route/schema/service。
- 新页面追加会撞旧静态测试：[✓ grep] `tests/test_training_calendar_static.py:16-21`。已写入计划：改成 training-calendar 仍注册，新页面在末尾。
- 需要正式 spec 或明确 PRD 兼任 spec。已新增轻量 spec：`docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`。

---

## 3. 关键字段清单

### 3.1 后端已有字段

| 字段 | 证据 | Sprint 11 用法 |
|---|---|---|
| `activities.power_zones` | [✓ grep] `app/activity/models.py:159-162` | 核心数据源 |
| `power_zones[].zone/name/seconds/percent` | [✓ grep] `app/activity/power_zones.py:31-45`、`:97-104` | 累加 Z1-Z6 |
| `power_zones[].min_w/max_w` | [✓ grep] `app/activity/power_zones.py:97-104` | 只读后丢弃，不返回 |
| `activities.status` | [✓ grep] `app/activity/models.py:54-56` | 只取 `completed` |
| `activities.activity_type` | [✓ grep] `app/activity/models.py:100-108` | 只取 `cycling` |
| `activities.duplicate_of` | [✓ grep] `app/activity/models.py:117-128` | 必须 `IS NULL` |
| `activities.started_at` | [✓ grep] `app/activity/models.py:91-94` | 42 天北京时间窗口 |
| `activities.snapshot_ftp` | [✓ grep] `app/activity/models.py:86-88` | 本期不读；power_zones 已按当时 FTP 算好 |

### 3.2 API 响应字段

这些字段只在 `/api/training/distribution?range=6w` 响应里出现，不写 DB：

`range`、`window_days`、`activity_count`、`total_power_seconds`、`total_power_hours`、`data_complete`、`insufficient_power_data`、`current_type`、`current_label`、`target_label`、`headline`、`explanation`、`groups`、`raw_zones`、`actions`、`week_plan`。

`raw_zones` 每项只允许：

```json
{
  "zone": "Z2",
  "name": "耐力",
  "seconds": 1234,
  "percent": 56
}
```

### 3.3 不应新增到 DB 的字段

- 不新增 `training_distribution` 表。
- 不新增 `activities.training_type`。
- 不新增 `users.training_goal`。
- 不新增 `daily_training_load.distribution`。
- 不把 `current_type/current_label/target_label/headline/explanation/groups/raw_zones/actions/week_plan` 回写数据库。

---

## 4. Claude 重点审查问题

1. `docs/prd/sprint-11-prd.md` 是否已经把用户故事、字段合同、可删除边界讲清楚？
2. `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md` 是否足够指导实现，不会让 agent 现场猜字段？
3. `docs/plans/sprint-11-training-distribution.md` 的任务票是否能防止直接开工、漏测隐私和破坏 `/load`？
4. 是否还需要升级成 `docs/spec-vN.md`，还是这份轻量 spec 对 Sprint 11 足够？

---

## 5. 当前改动范围

- `docs/prd/sprint-11-prd.md`
- `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`
- `docs/plans/sprint-11-training-distribution.md`
- `docs/plans/sprint-11-field-review-handoff.md`

没有代码实现改动。
