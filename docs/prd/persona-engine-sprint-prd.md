# velo Persona Engine Sprint PRD —— NPC 文案系统 v0.1 落地

> **本文件性质**：Persona Engine Sprint 战术 PRD，给执行 spec subagent 看的执行手册。
>
> **写作规范**（沿用 sprint-6-prd.md / Tim 2026-04-28 拍）：每子任务严格 **9 章节**（用户目标 / 使用场景 / 功能范围 / 用户流程 / 页面&状态 / 数据需求 / 异常情况 / 验收标准 / 不做项）+ 来源追溯一行。
>
> **前置必读**：
> - `docs/agent-rules/persona-constitution.md`（Persona 宪法 v0.1 / NPC 文案灵魂源）
> - `docs/adr/009-为什么-agent-层独立.md`（agent 层独立架构原则）
>
> **维护**：Tim + Claude 协作。版本 **v0.1**（2026-05-16 / 仅 task 概览层 / 待 Tim 审 task 拆分 OK 后深入 9 章节）。

---

## 0. Persona Engine Sprint north star

**1 主轴**：让老登 NPC 在 velo 全 App 7 个高频场景说话——**46 条固定模板覆盖 92% 场景 / 0 LLM 调用 / 0 漂移 / 0 成本**。用户每天打开 velo 都被这个隐形人格陪伴。

**主轴拆解**（基于 Persona 宪法 § 2 八场景 / 本 Sprint 实施 46 模板部分）：

| 宪法场景 | 触发条件 | 模板数 |
|---|---|---|
| § 2.1 PR | 上传后检测 distance/elevation/duration/np 任一字段为历史 max | 6 |
| § 2.2 段位×距离 | 上传完成时按累计 km 段位 × 距离桶查表 | 8 |
| § 2.3 连骑高频 | 本周次数 ≥ 5 | 6 |
| § 2.4 沉寂 | 距上次骑车 > 7 天 | 6 |
| § 2.5 极端数据 | 8 个 trigger（夜骑 / 短距 / 长距 / 高速度 / 后崩 / 雨天 / 早出 / 低速 / v0.3 修 / Claude A 抓 I-new-1 / "高速度"不是"高功率"） | 8 |
| § 2.6 空状态/错误/加载 | 前端状态映射 | 8 |
| § 2.8 错峰惊喜 | 节气 / 周年 / 里程碑 | 4 |
| **总** | | **46 条** |

**Sprint 范围外（明确延后）**：

- **§ 2.7 跨时间镜像 4 条** → v0.5 Sprint（接 LLM）
- **LLM 接入** → v0.5 Sprint
- **用户反馈机制**（点赞 / 踩 / 长按）→ v1.0
- **A/B 实验框架** → v1.0
- **年报 / 月报 / 个性化长文** → v1.0+
- **多人格 / 多地域 NPC**（北京 NPC / 上海 NPC 等）→ v2.0+
- **段位之外的拟人化文案**（如根据用户兴趣推荐路线）→ 永不做（Persona 宪法范围之外）

**前置依赖**：
- ✅ Persona 宪法 v0.1 落档（2026-05-16 / `docs/agent-rules/persona-constitution.md`）
- ⏳ Sprint 6 task-1~6 完成（profile 页 / 上传完成 toast / settings 是 NPC 文案展示位 / 当前 task list #6 pending 由新 claude 进程接手）
- ✅ `app/agent/` 模块 + DeepSeek 配置（已就绪 / 本 Sprint 仅复用模块骨架 / 不调 LLM）
- ✅ Activity worker SAVEPOINT hook pattern（已就绪 / 复用）

**1 个跨子任务软目标**：单次 NPC 文案查询 < 50ms（纯模板 + 算法 / 0 LLM 调用 / 命中即返）。

**预估工期**：**8.5-10.5 天**（单人估算 / 三人协作可压到 5-6 天）。

---

## 0.1 真实代码事实表（grep 实证 / spec subagent 起手必读）

> 本表所有 [file:line] 已亲 grep 实证。spec subagent 实施前必须重新 grep 验证一遍（防 stale / 见 memory `feedback_phase5_task_card_grep_stale.md`）。

### Agent 模块现状（NPC 系统的复用基础）

| 文件 | 行数 | 内容 |
|---|---|---|
| `app/agent/__init__.py` | 22 | ADR-009 边界声明 / 不反向 import 业务模块 |
| `app/agent/segment_writer.py` | 142 | DeepSeek client 单例（L39-42）+ `generate_segment_draft(props_dict) -> str`（L72）|
| `app/agent/tasks.py` | 131 | RQ async 入口 / `generate_segment_draft_task(segment_id)`（L39）|

**DeepSeek 配置**（已就绪 / v0.5+ 才复用 / 本 Sprint 不调 LLM）：
- `app/config.py:55` `DEEPSEEK_API_KEY: str = ""`
- `app/config.py:58` `DEEPSEEK_MODEL: str = "deepseek-chat"`
- base_url: `https://api.deepseek.com`

### Activity worker hook（NPC 接入位 / SAVEPOINT pattern）

`app/activity/worker.py:165-250` 已有完整 hook 链 / **NPC hook 应插入此处同级**：
- SAVEPOINT 隔离 pattern（CLAUDE.md 陷阱 #13）
- city hook（L228-250 / 写 user.city + activity.city）
- detector hook
- segment 匹配
- heatmap cache 清理

**NPC hook 设计**：和 detector / city hook 同级 / SAVEPOINT 隔离 / 失败不影响主流程（满足宪法 § 7.2 "不传染失败"）。

### 业务字段（NPC trigger 需要读 / 不直查 / 通过 service 喂参数 dict）

| 字段 | 来自 | NPC 用途 |
|---|---|---|
| `User.id / nickname` | `app/user/models.py:27-119` | 个性化 |
| `User.city` | `app/user/models.py:101` | 地域文案（未来扩展）|
| `User.ftp` | `app/user/models.py` | FTP trigger / 高功率参考 |
| `Activity.distance` | `app/activity/models.py:42-164` | 段位 + 极端距离 trigger |
| `Activity.elevation_gain` | 同上 | PR 检测 |
| `Activity.duration / moving_time` | 同上 | 时长 trigger |
| `Activity.avg_speed / max_speed` | 同上 | 速度 trigger |
| `Activity.avg_power / normalized_power` | 同上 | 高功率 trigger |
| `Activity.started_at` | 同上 | 夜骑 / 早出 trigger |
| `Activity.activity_type` | 同上 | 仅 'cycling' 触发 |

**红线**：NPC 不直接查这些字段——必须通过 service 层喂参数 dict（ADR-009 + 宪法 § 7.2）。

### 前端展示位（pages / NPC 接入界面）

`miniprogram/pages/` 现有 11 个 page。本 Sprint NPC 接入：
- ✅ `profile/` — "我的"页（stats 区附注 / 签名旁段位文案）
- ✅ `user/` — 看他人主页（同上 / 自他对称）
- ✅ `detail/` — 活动详情页（PR 横幅 / 段位文案 / 极端数据标记）
- ✅ `upload/` — 上传完成 toast
- ✅ `home/` — 首页（活动列表卡片附注）
- ✅ 全局 — 空状态 / 错误页 / loading 加载文案
- ❌ `explore/` / `segment/` / `segment-efforts/` / `honor/` / `notification/` — 暂不接入（不属于宪法 § 2 八场景）

### 最新 Alembic 迁移头（v0.2 修 / Claude B 抓 Critical）

- **当前真 head = `sprint6_activity_city`**（grep 实证 / Sprint 6 task-3 已 ship）
- 链：`sprint5_activity_privacy` → `sprint6_user_bio` → `sprint6_activity_city`
- → Persona Engine Sprint 第一条新迁移（`persona_engine_init`）的 `down_revision` **必须**写 `sprint6_activity_city`
- **实施前**必须重新 `ls migrations/versions/ | tail -3` + 看 `down_revision` 链 / 防 Sprint 6 实施持续推进 head 又前移

### 现有 utils（NPC 可复用）

- `app/common/geo.py` — `infer_city_from_coords` 等纯函数 / 城市判断
- `app/activity/worker.py` SAVEPOINT pattern — 复用 hook 写法（陷阱 #13）
- `app/agent/segment_writer.py` DeepSeek client 单例 — v0.5+ 直接复用

---

## 1. 共用规范引用（spec subagent 必读）

### 1.1 语言风格

**唯一真相源**：`docs/agent-rules/persona-constitution.md`

所有 NPC 文案必须**严格**按宪法走：
- § 1 老登人格画像（8 条 P-01 ~ P-08）
- § 2 50 条精选黄金示范（46 模板 + 4 LLM / **本 Sprint 只实施 46 模板部分**）
- § 2.5 文案双标尺（信息密度 5 因子 + 字数 ≥ 5 + 软字 3 工具）
- § 3 反例禁区（9 类）
- § 4 黑话词典
- § 5 调侃尺度边界

**禁止偏离 Persona 宪法**——任何不在 § 2 范围的新文案需走宪法 § 6.3 新场景接入流程（Tim 拍）后才能入。

### 1.2 技术栈

参 `CLAUDE.md` "技术栈"章节（FastAPI 同步 / SQLAlchemy 2.0 / PostgreSQL + PostGIS / 微信小程序 / 禁止 async def / 复用 RQ async）。

### 1.3 边界（INV / D-P / ADR-009 / Persona 宪法 § 7）

**Persona 宪法 § 7 架构约束（硬约束）**：
- NPC 必须是"可拔的码表"——拔掉它 velo 主功能照样跑
- 四不规则：不直接读业务数据 / 不直接改业务数据 / 不阻塞主流程 / 不传染失败
- 数据隔离：`persona_*` 表前缀 / 不和主业务表混

**ADR-009 边界**：agent 不反向 import 业务模块 / 只通过参数 dict 输入 / 自有表写。

### 1.4 规则界限

- **共享逻辑识别**（CLAUDE.md spec 自审 #2）：7 个场景共用模板查表 / trigger 路由逻辑 → 必抽 helper / 禁止复制粘贴
- **状态机完整性**：`persona_outputs` 状态机（pending → shown）含异常恢复路径
- **强制检查清单 + 技术栈陷阱清单**：参 CLAUDE.md
- **部署纪律**：参 CLAUDE.md "部署经验"

---

## 2. task 概览

| # | task | 模块 | 估时 | 依赖 |
|---|---|---|---|---|
| 1 | `app/agent/persona/` 模块脚手架 + 3 张 `persona_*` 表迁移 | 后端 agent | 0.5 天 | - |
| 2 | template_lib.py 46 条模板 + 段位查表 + trigger 注册 | 后端 agent | 1.5 天 | task-1 |
| 3 | trigger_router.py + filters.py + cache.py + persona service api | 后端 agent | 2 天 | task-2 |
| 4 | 业务接入点（worker hook / endpoint / push）调用 persona service | 后端跨模块 | 1.5 天 | task-3 |
| 5 | 小程序 NPC 文案展示（profile / detail / upload toast / 空状态 / 错误）| 前端 miniprogram | 2-3 天 | task-3 |
| 6 | 真用回归（注册 → 各场景触发 → 覆盖 ≥ 80%）| 双方 | 1 天 | task-1~5 |

**串并顺序**：task-1 起步；task-2 等 task-1；task-3 等 task-2；task-4 + task-5 都依赖 task-3 可部分并行；task-6 等全部。

**部署顺序**：Alembic 链强制串行 / Sprint 6 末尾迁移 → persona_engine_init (task-1) / 部署 `alembic upgrade head` 自动按链跑。

**合计 8.5-10.5 天**（单人估算 / 三人协作可压到 5-6 天）。

---

## 3. task 详情

### 3.1 task-1 - 后端 - `app/agent/persona/` 模块脚手架 + 3 张 persona_* 表迁移

**用户目标**：建好 NPC 系统的"空房子"——后端目录 + 数据库表准备好，让后续 task 能往里填模板和接业务。本 task 完成后系统**没有任何可见效果**，纯基础设施。

**使用场景**：内部工程任务 / 无用户故事 / 仅给后续 task 提供脚手架。

**功能范围**：
- 新建 `app/agent/persona/` 子目录 + `__init__.py`（含 ADR-009 边界声明 + 宪法 reference）
- 新建空骨架文件：`trigger_router.py` / `template_lib.py` / `filters.py` / `cache.py`（每个含 docstring 说明该模块职责 / 暂无实际函数）
- Alembic 迁移 `migrations/versions/persona_engine_init.py` 建 3 张表：
  - `persona_outputs`：NPC 说过的话历史
  - `persona_templates`：模板库元数据
  - `persona_feedback`：用户反馈（v1.0+ 才用 / 本 Sprint 建表占位）
- ORM 模型加进 `app/agent/models.py`（沿用 segment_ai_drafts 同位置）
- 写 `app/agent/persona/MANIFEST.md` 资产清单初版（按宪法 § 7.5.2）

**用户流程**：N/A（无前端流程）。

**页面&状态**：N/A。

**数据需求**：
- `persona_outputs`：id PK / user_id FK / scene_type VARCHAR(32) / template_id INTEGER FK / shown_at timestamptz / activity_id FK nullable / index (user_id, scene_type, shown_at)
- `persona_templates`：id PK / scene_type VARCHAR(32) / segment VARCHAR(32) nullable / template_text TEXT / weight INTEGER default 1 / active BOOLEAN default true / index (scene_type, active)
- `persona_feedback`：id PK / user_id FK / output_id FK / reaction ENUM('like','dislike','dismiss') / created_at timestamptz
- 所有表名以 `persona_` 前缀（宪法 § 7.5.1）

**异常情况**：
- Alembic 迁移在 PG + SQLite 都跑通
- 迁移 down 能干净回退
- `from app.agent.persona import *` 不抛错（即便子模块全空）

**验收标准**：
- pytest：`from app.agent.persona import trigger_router, template_lib, filters, cache` 全 import 成功
- Alembic upgrade head + downgrade -1 在 PG + SQLite 都跑通
- `persona_*` 3 表 schema 正确 / 索引在
- `MANIFEST.md` v0.1 写好（即便初版资产很少）
- 不破坏既有 pytest

**不做项**：
- 任何 NPC 文案逻辑（留 task-2/3）
- 任何业务接入（留 task-4）
- 任何前端展示（留 task-5）
- persona_feedback 的写入逻辑（v1.0+）

**来源追溯**：Persona 宪法 § 7.4 模块结构 + § 7.5 可拔性验证 / Tim 2026-05-16 拍。

---

### 3.2 task-2 - 后端 - template_lib.py（46 条模板 + 段位查表 + trigger 注册）

**用户目标**：把宪法 § 2 那 46 条金标尺台词全部入库 / 让系统知道"什么场景该说哪句"。

**使用场景**：内部工程任务 / 为 task-3 决策大脑提供素材。

**功能范围**：
- 把宪法 § 2 共 46 条文案（去掉 § 2.7 跨时间镜像 4 条 / 留 v0.5）写进 `persona_templates` 表（通过 Alembic data migration）
- 每条挂上 scene_type + segment：
  - scene_type: `pr` / `segment_distance` / `consecutive_high` / `silence` / `extreme` / `empty_error` / `surprise`
  - segment: 段位（rookie/entry/mid/veteran）或距离桶（tiny/short/normal/long/extreme）或极端类型（night/tiny/long_dist/high_speed/late_collapse/rain/early/low_speed / v0.3 修 / 与 task-2 data migration TEMPLATES 真值对齐）
- 写 `template_lib.py` 提供查询接口：
  - `get_templates_for_scene(scene_type, segment=None) -> list[Template]`
  - `pick_template(templates, user_id, recent_outputs) -> Template`（随机选 + 避免最近 7 天用过的）
- 段位算法（纯函数 / 在 `template_lib.py` 内）：`compute_user_stage(total_distance_m) -> str`
- 距离桶算法（纯函数）：`compute_distance_bucket(distance_m) -> str`

**用户流程**：N/A（内部模块）。

**页面&状态**：N/A。

**数据需求**：
- 46 条文案**严格按宪法 § 2 原文入库**（不许改字 / 不许漏 / 不许加 / 漂移检测靠 pytest 字面比对）
- 段位阈值（宪法 § 2.2）：< 500km → 萌新 / 500-3000 → 入门 / 3000-8000 → 进阶 / > 8000 → 老登
- 距离桶（业务自定义 / 实施时按宪法 § 2.5 极端 trigger 校准）：< 5km → tiny / 5-50 → short / 50-100 → normal / 100-150 → long / > 150 → extreme

**异常情况**：
- 某 scene_type 模板库为空 → 返空列表（不抛错 / caller 降级或不展示）
- segment 不匹配（如系统认为是老登但传 "萌新"）→ 返该 scene_type 该段位的并集
- 模板文本含 § 3 反例关键词（应该不会 / 但兜底）→ data migration 时 fail 触发 PR review

**验收标准**（v0.2 扩 / 每场景 ≥ 5 条新硬约束）：
- pytest：`SELECT count(*) FROM persona_templates WHERE active = true` ≥ 46（v0.2 目标 ~158 / 实施时按副线 cycle 入库进度记真值）
- pytest：每条 template_text 和宪法 § 2 字面 byte-by-byte 一致 / **只比"文案内容。"部分**（标签 `【...】` 和括号说明 `（...）` 不入 template_text / 见宪法 § 2 ground truth 注释）
- pytest：每个 (scene_type, segment) 组合查询返 ≥ 5 条（防 broken record / v0.2 新硬约束）
- pytest：`compute_user_stage(8_500_000)` == "veteran"（英文 enum / 与 task-2 实现对齐 / 不是中文）
- pytest：`compute_distance_bucket(80_000)` == "normal"
- pytest：`get_templates_for_scene("pr")` 返 ≥ 5 条
- pytest：`pick_template` 在 user_id 最近 7 天用过的不再选（除非 pool 已耗尽）

**stage / bucket 英文枚举（v0.2 修 / Claude A 抓 C2）**：
- stage：`'rookie' / 'entry' / 'mid' / 'veteran'`（**英文 enum** / 不是中文）
- bucket：`'tiny' / 'short' / 'normal' / 'long' / 'extreme'`
- segment 字段拼接：`f"{stage}_{bucket}"` / 如 `"veteran_normal"`

**不做项**：
- 触发判断逻辑（留 task-3 trigger_router）
- 任何 LLM 调用（v0.5+）
- 模板动态变量替换（如把 distance 填进模板）→ 本 Sprint 模板都是固定文案 / 不需要变量

**来源追溯**：Persona 宪法 § 2 黄金示范（本 task 实施 46 条 / 跳过 § 2.7 4 条 LLM 场景）。

---

### 3.3 task-3 - 后端 - trigger_router.py + filters.py + cache.py + persona service api

**用户目标**：让 NPC 系统真正能"决策说话"——根据用户行为判断 scene_type + 选模板 + 防漂移 + 防重复。

**使用场景**：被 task-4 业务模块调用 / 决定 NPC 在某场景下输出什么。

**功能范围**：
- `trigger_router.py`：根据 `PersonaEvent` + user context dict 决定 scene_type + segment
  - 输入：`PersonaEvent(type, activity_data, user_data, timestamp)`
  - 输出：`PersonaDecision(scene_type, segment, context_dict)` 或 `None`（无文案）
  - 7 种 event 路由：activity_uploaded（含 PR 内分支 / **PR 不再独立 event** / v0.3 修 / Claude A 抓 I-new-6）/ consecutive_high_detected / silence_detected / empty_state / error_state / milestone_reached（共 6 种 / "7 种" 是历史措辞 / 实际 6 种）
- `filters.py`：后置防漂移
  - `check_anti_pattern(text) -> bool`：扫宪法 § 3 反例 9 类关键词
  - `check_length(text) -> bool`：字数在 5-25 字甜区
  - 任一 fail → reject
- `cache.py`：防重复
  - `get_recent_outputs(user_id, scene_type, days=7) -> list[int]`：查最近 7 天 template_id
  - `record_output(user_id, scene_type, template_id, activity_id)`：写 persona_outputs
- `app/agent/persona/service.py`（新建 / 对外 API 唯一入口）：
  - `generate_persona_output(event: PersonaEvent, db: Session) -> Optional[str]`：一站式 router → template_lib → filters → cache 流水线

**用户流程**：N/A（内部服务）。

**页面&状态**：N/A。

**数据需求**：
- `PersonaEvent` Pydantic 结构（type / activity_data / user_data / timestamp）
- `PersonaDecision` Pydantic 结构（scene_type / segment / context_dict / fallback_template_id）
- 7 种 event 的 trigger 条件（详 task-2 段位 / 距离桶 + 各场景）

**异常情况**：
- DB query 失败 → caller 收到 `None`（不抛错让业务感知）
- 没匹配模板 → 返 `None`
- filter reject → 返 `None` + 日志记录（告警未来超过阈值时排查）
- cache 写失败 → fire-and-forget / 不影响输出
- 任何子模块抛 unhandled exception → service 顶层 catch / 返 `None`（宪法 § 7.2 "不传染失败"）

**验收标准**：
- pytest：7 种 event 各模拟一次 / router 返对 scene_type
- pytest：filter 扫到 "恭喜你" 开头 → reject
- pytest：filter 扫到 4 字短文案 → reject
- pytest：`cache.get_recent_outputs(user_id, "pr", days=7)` 返 list
- pytest：`service.generate_persona_output` 端到端跑通 / mock event → 返 str 或 None
- pytest：故意让子模块抛 Exception → service 顶层 catch / 返 None / 不污染调用方事务
- 不破坏既有 pytest

**不做项**：
- LLM 调用（v0.5+）
- 用户 A/B 分组（v1.0+）
- 输出 personalization（如把 user nickname 插模板）→ 本 Sprint 模板都是固定 / 不需要

**来源追溯**：Persona 宪法 § 6.1 算法 vs LLM 分工 + § 7.2 四不规则。

---

### 3.4 task-4 - 后端 - 业务接入点（worker hook / endpoint / scheduler）调用 persona service

**用户目标**：让 velo 业务模块在用户做某事时 cue NPC。

**使用场景**：
- 用户上传 GPX → worker 完成后 → 发 PersonaEvent → 写 persona_outputs / 等前端拿
- 用户一周没骑 → 后台 scanner 发现 → 写沉寂场景 NPC 文案
- 用户达成里程碑 / 节气 → 后台 scanner 写错峰惊喜文案
- 前端 profile / 详情页打开 → endpoint 返最新 NPC 文案

**功能范围**：
- `app/activity/worker.py` 加 NPC hook（和 city hook / detector hook 同级 / SAVEPOINT 隔离）
  - activity 完成 → 调 service.generate_persona_output → 写 persona_outputs
- 新增 endpoint：`GET /api/persona/output?scene_type=xxx&activity_id=yyy(optional)` —— 前端按场景 + 可选活动 ID 拿当前 NPC 文案（v0.2 修 / Claude B 抓 / activity_id 让 detail 页精准拿当前活动文案 / 不串到别活动）
- 新增 endpoint：`GET /api/persona/recent?limit=10` —— 前端拿用户最近 N 条 NPC 文案历史
- **scanner 容器**（v0.2 修 / Claude B 抓 C5）：docker-compose.yml 新增 `persona-scanner` 容器 / 仿现有 cleanup 容器模式（`while true; sleep 86400; python scripts/persona_*_scanner.py; done`）
- 沉寂 scanner：`scripts/persona_silence_scanner.py`（持续运行 / 内部 sleep 86400）
- 里程碑 scanner：`scripts/persona_milestone_scanner.py`（同上 / 持续运行）

**用户流程**：
1. 用户上传 GPX → worker 完成 → 算文案 → 写 DB
2. 用户打开 profile → 前端调 `/api/persona/output?scene_type=profile_open` → 返当前应展示文案
3. 用户一周没骑 → scanner 发现 → 写文案 → 下次打开 velo 时前端拿到

**页面&状态**：N/A（后端）。

**数据需求**：
- worker hook 输入：activity 完成数据 + user 上下文 dict
- endpoint schema：`PersonaOutputResponse(template_text: str | None, scene_type: str, created_at: datetime | None)`
- scheduler 配置：silence 每日 02:00 跑 / milestone 每日 00:30 跑

**异常情况**：
- worker hook 失败 → SAVEPOINT 隔离 / 不影响 activity 主流程（宪法 § 7.2）
- endpoint 调 service 抛错 → 返 200 + `template_text: null`（不让前端崩）
- scheduler 任务失败 → 日志记录 / 下次重跑
- endpoint 返 null → 前端 wx:if 不显示（不报错）

**验收标准**：
- pytest：worker 完成 PR activity → persona_outputs 写入 1 条 PR 场景文案
- pytest：worker 完成普通 80km activity → persona_outputs 写入 1 条段位场景文案
- pytest：endpoint GET /api/persona/output?scene_type=profile_open 返合法响应
- pytest：worker hook 故意抛 exception → activity 仍正常 completed（拔出测试 / 不传染失败）
- 不破坏既有 worker / activity pytest

**不做项**：
- 推送通知（push notification）主动 cue NPC → 本 Sprint 仅在用户打开 velo 时拿文案
- WebSocket 实时推送 → 用 polling / 不上 ws
- 用户反馈机制（点赞 / 踩）→ v1.0+

**来源追溯**：宪法 § 7.2 四不规则 + PRD § 0.1 真实代码事实表（worker hook 插入位）。

---

### 3.5 task-5 - 前端 - 小程序 NPC 文案展示（profile / detail / upload toast / 空状态 / 错误）

**用户目标**：让用户在 velo 里真看到 NPC 老登说话。

**使用场景**：
- 小明打开"我的"页 → 段位 + 头像旁 NPC 一句话
- 小明刷活动列表 → 大卡片顶部偶尔 NPC 一句
- 小明上传完活动 → toast 显示 NPC 反应（"今天嗑药了？" 或 "80km。蹬两脚意思意思。"）
- 小明断网 → 错误页显示 "连不上。WiFi 切流量试试。"

**功能范围**：
- `miniprogram/pages/profile/profile.wxml` 加 `<!-- PERSONA_START -->` / `<!-- PERSONA_END -->` 标记块 + NPC 文案显示位
- `miniprogram/pages/user/user.wxml` 同上（看他人页 / 自他对称）
- `miniprogram/pages/detail/detail.wxml` 顶部 PR 横幅 + 段位文案
- `miniprogram/pages/upload/upload.wxml` 上传完成 toast 升级显示 NPC 文案
- `miniprogram/utils/persona_fetch.js` 全局工具调 `/api/persona/output`
- 错误页 / loading 页 / empty state 全局组件升级文案（按宪法 § 2.6 八条空状态/错误文案）

**用户流程**：
1. 打开 profile → utils 调 `/api/persona/output?scene_type=profile_open` → 拿文案 → 显示在 PERSONA_START/END 块内
2. 上传完成 → 等 worker 完成（轮询 1 次 status）→ 调 `/api/persona/output?scene_type=activity_upload&activity_id=xxx` → 显示 toast 3 秒
3. 网络错误 → 直接显示前端写死的错误文案（不调后端 / 后端可能也炸了）

**页面&状态**：
- profile NPC 块：loading / loaded / empty（wx:if 隐藏） / error（wx:if 隐藏）
- toast：show（3s 后 dismiss）
- 错误页：写死宪法 § 2.6 中 4 条错误场景文案

**数据需求**：
- API 响应：`{template_text: string | null, scene_type: string}`
- 前端缓存：localStorage 缓存最近 24h 文案 / 防重复请求

**异常情况**：
- API 返 null → wx:if 不显示 NPC 块
- API 失败 / 网络断 → 不显示 NPC 块（不让用户看到错误）
- 文案过长 → CSS truncate（虽然后端有 25 字限制 / 前端兜底）
- PERSONA_START/END 块未注释正确 → 拔出测试时无法剥离（宪法 § 7.5.1 红线）

**验收标准**：
- 真用：注册账号 → 打开 profile → 看到至少 1 条 NPC 文案
- 真用：上传 PR 活动 → toast 显示 PR 场景文案
- 真用：上传普通 80km 活动 → toast 显示段位场景文案
- 真用：断网打开 velo → 错误页文案对 / 不崩
- 真用：5 个 page 都有 PERSONA_START/END 标记块（拔出测试可剥离）
- 不破坏既有页面真用回归

**不做项**：
- 用户对 NPC 文案点赞 / 踩 / 长按反馈（v1.0+）
- NPC 文案动画 / 渐入渐出（先静态显示）
- 多人格选择 UI（v2.0+）
- explore / segment / honor / notification 等 page 接入（不属于宪法 § 2 八场景）

**来源追溯**：宪法 § 2 50 条精选场景分布 + § 7.5.1 PERSONA_START/END 前端标记块约定。

---

### 3.6 task-6 - 真用回归（注册到查看 NPC 全链路）

**用户目标**：上线前 final gate / 验证 NPC 文案系统真用情况下 7 个场景都触发 / 模板覆盖率 ≥ 80%。

**使用场景**：上线前最后一关 / 防 mock 测试盲区（memory `feedback_real_usage_vs_mock_blindspot.md`）。

**功能范围**：
- 注册新用户 → 上传 GPX → 看 NPC 段位文案
- 上传 PR 活动 → 看 PR 文案
- 连骑 5 天测试（mock 日期）→ 看连骑高频文案
- 模拟沉寂 8 天（改 DB started_at）→ 看沉寂文案
- 上传短 / 长 / 夜骑 / 雨天活动 → 看极端文案
- 断网 / 错误 → 看错误页文案
- 节气日（mock）→ 看错峰惊喜文案
- 拔出测试：跑 `scripts/persona_pluck_dryrun.sh` → 核心 pytest 全绿（宪法 § 7.5.3）
- deployment-diary 记录 NPC Engine 真用激活时间 + 第三方依赖激活回归

**用户流程**：详上述 9 步。

**页面&状态**：全 page 真用回归。

**数据需求**：
- 测试账号 + 测试活动 GPX 准备
- mock 时间 / DB 直改方法（不允许跑生产）

**异常情况**：
- 某场景没触发 → 排查 trigger / filter / cache 哪层挡了
- 触发文案不对（如 PR 触发了"通勤吧"）→ 排查 segment 计算
- 拔出测试不绿 → 必修复后才能上线（红线）

**验收标准**：
- 7 个场景都触发文案（至少 1 次）
- 模板覆盖率 ≥ 80%（46 条至少 37 条被触发过）
- 拔出测试全绿
- 部署后 24h 内 owner 故意触发一次错误场景验证错误页文案显示
- deployment-diary 记录"NPC Engine 真用激活时间"+ 第三方依赖（DeepSeek 暂不调 / 但 endpoint 真用）激活状态

**不做项**：
- 自动化端到端测试框架 → 本 Sprint 手测即可（100 用户量级）
- 模板覆盖率监控仪表盘 → v1.0+
- A/B 实验 → v1.0+

**来源追溯**：memory `feedback_real_usage_vs_mock_blindspot.md` 真用回归 5 类盲区 + 宪法 § 7.5.3 拔出测试。

---

## 4. 不做项汇总（Sprint 范围外 / 防 scope creep）

汇总 § 0 north star "Sprint 范围外"清单：

- § 2.7 跨时间镜像 4 条 → v0.5 Sprint（接 LLM）
- LLM 接入 / DeepSeek 调用 → v0.5 Sprint
- 用户反馈机制（点赞 / 踩 / 长按）→ v1.0
- A/B 实验框架 → v1.0
- 年报 / 月报 / 个性化长文 → v1.0+
- 多人格 / 多地域 NPC → v2.0+
- 段位之外的拟人化文案 → 永不做（宪法 § 2 范围之外 = scope creep）

---

*本 v0.1 草稿由 Claude 起草 / 2026-05-16 / Tim 审 task 拆分 → v0.2 深入 9 章节 → 进双审*
