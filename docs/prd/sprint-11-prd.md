# velo Sprint 11 战术 PRD —— 训练分布分析（Polarized / Pyramidal / Sweet Spot）

> **本文件性质**：Sprint 11 战术 PRD，给 Tim、执行 agent 和 reviewer 用；它描述用户要得到什么，不直接授权开工写代码。
>
> **授权来源**：Tim 2026-05-25 在 Sprint 11 原型确认后明确要求：“按这个标准设计 prd、架构和列举要从后端拿的数据字段；一定低耦合、模块化、独立化；确保去掉这个模块后现有系统也能正常运行。”
>
> **上游原型**：`docs/prototypes/sprint11-training-distribution-demo.html`
>
> **上游路线图**：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md` 模块 C。
>
> **下游技术合同**：`docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`
>
> **字段审查交接**：`docs/plans/sprint-11-field-review-handoff.md`

---

## 0. North Star

**一句话**：让用户看懂自己最近 6 周到底是在“打底、硬顶、还是卡在半累不累的中间”，并马上知道下周先改哪一件事。

**用户故事**：
> 张三周日打开 velo，点进“训练结构”。页面第一句话告诉他：“你最近练得太挤在中间，容易累，但突破感不强。”他往下看，发现最近 6 周有 47% 时间卡在 Z3-Z4。velo 不要求他懂训练学术语，而是直接说：下周把一次节奏骑换成 90 分钟轻松骑，保留一次短间歇，阈值骑只留一次。张三心里有数：不是继续堆强度，而是把训练分开。

**本 sprint 成功标准**：
- 用户看到“当前训练结构类型 + 原因 + 下周怎么改”，而不是只看到一个饼图。
- 后端只读现有 `activities.power_zones`，不改 `activities` / `users` / `daily_training_load` 表结构。
- 整个 Sprint 11 模块可拔插：删掉新 endpoint、纯函数、前端页面和入口后，上传、活动详情、训练负荷曲线仍正常运行。

---

## 0.1 真实代码事实表（grep 已验证）

| 事实 | 证据 | 对 Sprint 11 的含义 |
|---|---|---|
| `power_zones` 已存在于 `activities` | [✓ grep] `app/activity/models.py:159-162` | Sprint 11 不新建训练分布表，直接读每条活动已有分区 |
| `power_zones` 格式是 Z1-Z6，每项有 `seconds` / `percent` | [✓ grep] `app/activity/power_zones.py:31-45`、`:97-104` | 后端可以累加最近 6 周每个 zone 的秒数 |
| Activity 已有 `snapshot_ftp` / `tss` / `started_at` / `activity_type` / `status` | [✓ grep] `app/activity/models.py:86-94`、`:100-108` | 查询要过滤 completed cycling，并按 started_at 做 6 周窗口 |
| `training` 模块已经独立挂载 | [✓ grep] `app/main.py:22`、`:50-51` | Sprint 11 继续放 `app/training/`，不反向污染 activity/user |
| 训练负荷接口已有 `/api/training/load` | [✓ grep] `app/training/router.py:16-26` | Sprint 11 新增同前缀 `/api/training/distribution` |
| 小程序训练分析入口当前只进训练负荷页 | [✓ grep] `miniprogram/pages/profile/profile.wxml:120-124`、`profile.js:356-358` | Sprint 11 可加第二张入口卡，不挤掉 PMC 页 |
| 聚合类查询应跳过 dedupe 重复活动 | [✓ grep] `app/user/service_stats.py:21`、`app/activity/service.py:285` | Sprint 11 查询加 `duplicate_of IS NULL`，防同一骑行重复计数 |
| 他人看活动时，隐藏功率会把 `power_zones` 挖空 | [✓ grep] `app/activity/service.py:82-95` | Sprint 11 只能看当前登录用户自己的训练结构；响应不能泄露 `min_w/max_w` |
| Sprint 10 训练负荷已经有 activity worker hook | [✓ grep] `app/activity/worker.py:371-381`、`app/strava/worker_strava.py:373-381` | Sprint 11 不新增 worker hook；不能把现有 Sprint 10 hook 当违规 |
| 训练日历静态测试当前要求 training-calendar 是 app.json 最后一页 | [✓ grep] `tests/test_training_calendar_static.py:16-21` | Sprint 11 加新页面时必须同步改测试表达，不让测试假红 |

---

## 0.2 模块边界

### 放在哪里

Sprint 11 只新增训练结构这一组零件：
- `app/training/distribution.py`：纯函数，只做分区累加、百分比、类型判断。
- `app/training/distribution_service.py`：查当前用户最近 6 周活动，把 DB 行翻译成接口响应。
- `app/training/schemas.py`：新增训练分布响应格式。
- `app/training/router.py`：新增 `GET /api/training/distribution?range=6w`。
- `miniprogram/pages/training-distribution/`：新页面。
- `miniprogram/pages/profile/`：只新增入口，不承载业务逻辑。

### 不放在哪里

- 不往 `activities` 加新列。
- 不往 `daily_training_load` 塞训练分布结果。
- Sprint 11 不新增 `activity -> training` 依赖；现有 Sprint 10 训练负荷 worker hook 保留，不属于本模块可删范围。
- 不让前端自己从活动列表拼分布。
- 不接 LLM，不写“教练总结”。Sprint 12 再做。
- 不新增 `training_distribution` 表。
- 不新增 `activities.training_type` / `users.training_goal` / `daily_training_load.distribution`。
- 不把 `current_type` / `groups` / `actions` / `week_plan` 回写数据库；这些只在请求时计算。

### 可拔插要求

删掉 Sprint 11 训练结构页面/API 新文件 + 从 `app.json` 和 profile 入口移除新页面后：
- `/api/training/load` 仍可用。
- 活动上传 / Strava 同步仍可用。
- 活动详情的功率区间仍可用。
- `daily_training_load` 账本仍可用。

删除时只撤这些东西：
- `app/training/distribution.py`
- `app/training/distribution_service.py`
- `app/training/schemas.py` 里 Sprint 11 新增的响应类
- `app/training/router.py` 里 `/distribution` 这一段
- `miniprogram/pages/training-distribution/`
- `profile` 新入口和新跳转函数
- Sprint 11 页面/API 专属测试

注意：2026-05-26 后 `miniprogram/utils/power-zones.js` 也服务活动详情页；删除 Sprint 11 时不能直接删它，除非先确认活动详情页已不再 import。

删除时不能碰：
- `app/training/service.py` 的 `/load` 服务
- `app/training/training_load.py`
- `app/training/models.py` 的 `daily_training_load`
- `app/activity/worker.py` / `app/strava/worker_strava.py` 里 Sprint 10 训练负荷 hook
- `miniprogram/pages/detail/` 的功率区间展示
- `miniprogram/utils/power-zones.js` 中仍被活动详情页使用的展示函数

---

## 1. 后端字段合同

### 请求

`GET /api/training/distribution?range=6w`

只支持 `6w`。先做最近 6 周，避免 30/90/全年三套含义混乱。

### 响应字段

| 字段 | 类型 | 用户含义 |
|---|---|---|
| `range` | `"6w"` | 当前时间窗口 |
| `window_days` | int | 42 天 |
| `activity_count` | int | 参与统计的骑行数量 |
| `total_power_seconds` | int | 有效训练秒数 |
| `total_power_hours` | float | 有效训练小时，前端显示 `16h` |
| `data_complete` | bool | 是否足够给建议 |
| `insufficient_power_data` | bool | 本接口恒等于 `not data_complete` |
| `current_type` | string/null | `polarized` / `pyramidal` / `sweet_spot` / `threshold` / `mixed` |
| `current_label` | string | 如 `Sweet Spot 倾向` |
| `current_description` | string | “当前”对比卡下面的小句子 |
| `target_label` | string | 如 `80 / 20` |
| `target_description` | string | “建议方向”对比卡下面的小句子 |
| `headline` | string | 第一屏主句 |
| `explanation` | string | 第一屏解释 |
| `groups` | list | 页面三组：Z2 / Z3-Z4 / Z5+ |
| `raw_zones` | list | Z1-Z6 脱敏累计，只允许 `zone/name/seconds/percent` |
| `actions` | list | 下周先改 3 件事 |
| `week_plan` | list | 一周示意安排 |

字段口径：
- `total_power_seconds` / `total_power_hours` = Z1+Z2+Z3+Z4+Z5+Z6，总有功率记录时间，含 Z1。
- `groups[].percent` 和分类判断的分母 = Z2+Z3+Z4+Z5+Z6，剔除 Z1；原型三组 44%+47%+9%=100，用的就是这个口径。
- `raw_zones[].percent` 的分母 = Z1+Z2+Z3+Z4+Z5+Z6，沿用现有单条活动 `power_zones[].percent` 口径。
- 两套百分比故意不同：`groups` 给用户看训练结构，`raw_zones` 给调试和后续扩展看原始分区。
- `groups` 三组不含 Z1，所以 `sum(groups.seconds)` 不等于 `total_power_seconds`；差值就是 Z1 秒数。
- `groups` 文案固定：耐力 / 中强度 / 高强度；对应 role 是 `打底时间` / `最容易堆累` / `刺激偏少`。
- `week_plan` 必须是 7 个结构化项，不是一整句字符串；例如 `{day:"一", title:"Z2", focus:"45 分"}`。

### 数据来源

后端读取 `activities`：
- `user_id = 当前用户`
- `status = "completed"`
- `activity_type = "cycling"`
- `duplicate_of IS NULL`
- `started_at IS NOT NULL`
- `started_at >= start_utc AND started_at < end_utc`
- `power_zones IS NOT NULL`

时间窗口写死为北京时间自然日：
- `today_bj = 今天北京时间日期`
- `start_day = today_bj - 41 天`
- `end_day = today_bj + 1 天`
- `distribution_service.py` 直接 import `app.training.service._today_bj` 和 `_bj_day_start_utc`，不复制逻辑、不重构 `app/training/service.py`。

### 字段分层

| 类别 | 字段 | 处理方式 |
|---|---|---|
| 只读已有字段 | `activities.power_zones` | 读取并累加；可兼容 list 和 SQLite 测试里的 JSON string |
| 只读已有字段 | `status` / `activity_type` / `duplicate_of` / `started_at` | 只做过滤，不改变 |
| 可读但本期不需要 | `snapshot_ftp` / `tss` | 不参与 Sprint 11 计算；以后展示“当时 FTP”再单独审隐私 |
| API 现算字段 | `current_type` / `current_description` / `target_description` / `groups` / `actions` / `week_plan` | 每次请求时算，不进 DB |
| 禁止返回字段 | `min_w` / `max_w` | 原始 `power_zones` 里有，但响应必须剔除，避免别人反推出 FTP |
| 禁止新增 DB 字段 | `training_distribution` / `activities.training_type` / `users.training_goal` / `daily_training_load.distribution` | 本 sprint 不建表、不加列 |

---

## 2. 类型判断规则（v1）

先把每条活动的 `power_zones` 加总：
- Z2 = 耐力时间
- Z3-Z4 = 中强度时间
- Z5-Z6 = 高强度时间
- Z1 保留在 `raw_zones`，不作为核心类型判断主轴

百分比口径：
- 分类判断只看 Z2-Z6，剔除 Z1。
- `raw_zones` 仍按 Z1-Z6 原始总秒数算百分比。
- `total_power_seconds` / `total_power_hours` 含 Z1。

分类顺序：
1. `threshold`：Z4 单区占比 >= 30%，用户总在阈值附近硬顶；这个 v1 阈值可调。
2. `sweet_spot`：Z3-Z4 ≥ 40%，像原型里“卡在中间”。
3. `polarized`：Z2 ≥ 70%，且 Z5+ ≥ 8%，中强度 ≤ 22%。
4. `pyramidal`：Z2 > Z3-Z4 > Z5+，结构像金字塔。
5. `mixed`：其余都先叫“结构不稳定”，不强行贴专业标签。

训练建议文案不在 PRD 里现场脑补；实现时按 spec §4.1 的 5 类型文案表作为 v1 上线文案。

**数据不足**：
- 最近 6 周参与活动少于 2 条，或有效训练时间少于 3 小时：`data_complete=false`。（门槛 3→2 / Tim 2026-05-25 拍）
- 页面只显示“功率数据不足 / 先多记录几次有功率骑行”，不输出训练建议。

---

## 3. 子任务拆分

### task-1：PRD + 字段合同 + 任务卡

用户目标：先把用户故事、后端字段、模块边界说清楚，防止写出一个漂亮但无法维护的功能。

验收：
- 本 PRD 存在。
- `docs/plans/sprint-11-training-distribution.md` 存在。
- `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md` 存在。
- `docs/plans/sprint-11-field-review-handoff.md` 存在，能交给 Claude 异源审。
- 文档明确“不改核心表 / 可拔插 / 低耦合”。
- 字段审查明确 `raw_zones` 脱敏、42 天上下界、dedupe 过滤、现有 `/load` 不受影响。
- PRD 明确两套百分比分母、`threshold` 数字界限、`insufficient_power_data` 与 `data_complete` 的关系。
- PRD 明确 `current_description` / `target_description`、groups 固定文案、week_plan 结构化格式。

### task-2：训练分布纯函数

用户目标：把最近 6 周的 `power_zones` 翻译成“你像哪种练法”。

验收：
- 有 `app/training/distribution.py`。
- 单测覆盖 Sweet Spot / Polarized / Pyramidal / Threshold / Mixed / 数据不足。
- 单测覆盖 groups 百分比剔除 Z1、raw_zones 百分比含 Z1、Z4 >= 30% 命中 threshold。
- 纯函数不 import DB / FastAPI / ORM。

### task-3：训练分布 API

用户目标：小程序一次请求拿到页面需要的全部数据，不自己拼活动列表。

验收：
- `GET /api/training/distribution?range=6w` 返回 200。
- 未登录返回 401。
- 非本人数据不会串。
- `range=30d` 返回 422。
- 跳过 duplicate / 非 cycling / failed / 无 power_zones 活动。
- 响应里的 `raw_zones` 不含 `min_w/max_w`。
- 响应里包含 `current_description` / `target_description`，前端不现场编对比卡文案。
- `groups` 返回固定 label/role，且不要求 `sum(groups.seconds) == total_power_seconds`。
- `week_plan` 返回 7 个 `{day,title,focus}` 结构化项。
- `/api/training/load` 的测试继续通过。

### task-4：小程序训练结构页

用户目标：打开后先看到判断和行动建议，再看饼图和数据来源。

验收：
- 新增 `miniprogram/pages/training-distribution/` 四文件。
- `app.json` 注册新页面；同时更新训练日历静态测试，表达为“训练日历仍注册，新训练结构页在末尾”，不要继续断言训练日历永远是最后一页。
- profile 新增“训练结构”入口。
- 页面处理 loading / error / 数据不足 / 正常四种状态。

### task-5：验证与自审

验收：
- 跑相关 pytest。
- 静态检查小程序页面文件存在、endpoint 字符串正确。
- 自审确认 Critical=0；代码实现后需 Claude 异源审再 commit。
- 自审必须逐项核销：字段脱敏、时间窗口、dedupe、可删除边界、`/load` 不破坏。

---

## 4. 不做项

- 不做训练计划编辑器。
- 不做 LLM 教练总结。
- 不做社交对比。
- 不做用户自定义分类阈值。
- 不回写训练分布结果到数据库。
- 不基于无功率活动瞎补估算。
