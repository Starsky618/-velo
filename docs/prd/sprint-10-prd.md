# velo Sprint 10 战术 PRD —— PMC 训练负荷曲线（CTL / ATL / TSB）

> **本文件性质**：Sprint 10 战术 PRD，给执行 spec subagent 看的执行手册。
>
> **写作规范**（沿用 `sprint-9-prd.md` 风格 / Tim 2026-04-28 拍）：每子任务严格 **9 章节**（用户目标 / 使用场景 / 功能范围 / 用户流程 / 页面&状态 / 数据需求 / 异常情况 / 验收标准 / 不做项）+ 来源追溯一行。
> - PRD 不写具体 DB 表结构 / API 路径（放 plans/task 卡）
> - PRD 可写必要技术约束 + 字段类型方向
> - UI/UX 只写页面结构 / 信息优先级 / 流程 / 状态，**不写视觉参数**
>
> **维护**：Tim + Claude 协作。版本 **v0.2**（2026-05-25 / 第四轮 Codex 异源审收敛 / 修 Critical 1 + Important 3 / task-5+task-7 合并为 6 task / 真 head 命令改 `alembic heads`）。
>
> **上游路线图**：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md`（模块 B = 本 Sprint）。
>
> **下游字段合同**：`docs/superpowers/specs/2026-05-20-coach-engine-design.md`（Sprint 12 LLM 教练总结要复用 `daily_training_load` 表的 CTL/ATL/TSB/weekly_tss）。

---

## 0. Sprint 10 north star

**1 主轴**：让用户**看到健身度涨没涨 + 现在适不适合继续上量** —— 不用打开 intervals.icu 网页 / velo 直接把过去 30 / 90 / 全年的 CTL（健身度）/ ATL（疲劳度）/ TSB（状态）三条曲线画出来 + 给一句"今天该歇还是该练"。

**用户故事**：
> 张三周末打开 velo / 进"我的"页 → 点"训练分析" → 看 30 天曲线 → 绿线（健身度）从 50 涨到 68 / 黄线（疲劳度）今天 80 偏高 / 蓝线（状态）-12 → 顶部状态卡说"状态：累 / TSB -12 / 你这周累计 TSS 450 / 周中可以安排个轻松骑"→ 心里有数：再扛一两天 / 周三轻松骑 / 周六大组继续上量。

**6 个子任务**（v0.2 合并 task-5+task-7 / 符合 CLAUDE.md "一期任务数 ≤ 6"硬规则）：

- **后端 task-1**：DB 新表 `daily_training_load` + Alembic 迁移（down_revision = `sprint10_user_hr_profile`）+ ORM 模型 `app/training/models.py`（**task-3 backfill 脚本 import 依赖 / 不能拖到 task-4 才建**）
- **后端 task-2**：训练负荷算法（纯函数 `app/training/training_load.py` / TSS·CTL·ATL·TSB·4 档状态分类 / **Sprint 12 coach-engine 直接 import 复用 / 不重复实现**）
- **后端 task-3**：一次性历史回填脚本（你账号 295 条 + 全用户 / 按时间序滑窗递推 / 跳过 GPX 无 TSS 活动 / **抽 helper `backfill_daily_training_load_for_user(db, user_id)` 给 task-6 import_scheduler 完工后调**）
- **后端 task-4**：`GET /api/training/load` endpoint（30 / 90 / 365 天三档 / 返曲线 + summary）
- **前端 task-5**：训练日历页（`miniprogram/pages/training-calendar/` 新建 / canvas 三条曲线 + 顶部状态卡 + 空数据状态）+ "我的"页二级入口（profile.wxml 加"训练分析"二级入口 / 不挤 Sprint 12 的动态 tab 顶部大卡）
- **后端 task-6**：worker 增量更新（worker.py + worker_strava.py 单条 hook 算当日 / **import_scheduler 路径不挂单条 hook**——tier2 完工时调一次 task-3 backfill helper 全量正序递推 / 防倒序处理 CTL/ATL 时序错乱 / 2026-05-25 Codex 异源审实证）

**预估工期**：**7 天**（路线图 §3 时间表 / 比 Sprint 9 简单 / 没新弹窗 / 没拟合算法 / 主要是 SQL 滑窗 + 一张曲线图）。

**前置依赖**：
- ✅ Sprint 9 已 ship（`activity.tss` / `activity.snapshot_ftp` / `activity.intensity_factor` 三字段已写入 / 295 条 baseline 已同步）
- ✅ Sprint 10 hotfix 已 ship（`sprint10_user_hr_profile` 迁移 / users.birth_year + max_hr 字段 / 不影响本 sprint 但要在 alembic chain 上接好）

**Sprint 范围外（明确延后）**：

- **训练分布饼图分析**（Z2/Z3/Z4 累计时间占比 + Polarized/Pyramidal/Sweet Spot 自动分类）→ **Sprint 11** 模块 C
- **每日推荐 = LLM 教练总结**（DeepSeek 4 段卡片 / 早上 6 点 cron）→ **Sprint 12** 模块 D（设计稿 `docs/superpowers/specs/2026-05-20-coach-engine-design.md`）
- **GPX 路径补 NP 算法 / hrTSS 兜底**（基于心率 + LTHR 算 TSS）→ **永久不在本 Sprint 做** / Sprint 12 coach-engine 内部如需要再单独评估 / **不回写 `activity.tss` 字段 / 不影响本 sprint daily_training_load**
- **CTL/ATL 长期对比 / 同档骑友 PMC 排行榜** → v1.5+
- **用户自定义 CTL/ATL 时间常数**（默认 42 / 7 / 不让用户改）→ 永久不做（产品复杂度爆炸）
- **训练计划编辑器 / 教练-运动员协作** → 永久不做（B 端工具 / 不在 velo 范围）
- **HRV / 健康监测接入** → 永久不做（research 实证 velo 永远拿不到 / 详 roadmap §1 模块 E）
- **FTP 估算精度专题**（P1 tech debt / Tim ftp=117W vs 真实 250W）→ Sprint 10 后单独排期 / 已通过 `sprint10_user_hr_profile` 加 HR-gated 改进一部分 / 完整重写排在 Sprint 11/12 之间

---

## 0.1 真实代码事实表（grep 实证 / spec subagent 起手必读）

> sprint-9-prd.md §0.1 同模板 / 所有 [file:line] 已亲 Read 实证。
> spec subagent 实施前必须重新 grep 验证一遍（防 stale / 见 memory `feedback_phase5_task_card_grep_stale.md`）。

### Activity 字段（`app/activity/models.py:42-164`）

| 字段 | 真值 | 注 |
|---|---|---|
| **tss** | Float / nullable / **Sprint 9 已 ship** ✓ | [models.py:88] TSS = (秒×NP×IF) / (FTP×3600) × 100 / round 1 位 |
| **snapshot_ftp** | Integer / nullable / **Sprint 9 已 ship** ✓ | [models.py:86] 该活动锁定的 FTP |
| **intensity_factor** | Float / nullable / **Sprint 9 已 ship** ✓ | [models.py:87] IF = NP / snapshot_ftp / round 3 位 |
| **started_at** | DateTime(timezone=True) / nullable | [models.py:94] 骑行开始时间（UTC）/ ⚠ 本 sprint task-2/3/6 必按北京时间 UTC+8 归日 |
| **activity_type** | String / cycling/running/other | [models.py:103] task-3/6 过滤 `='cycling'` |
| **status** | String(20) / completed/processing/failed/pending | [models.py:56] task-3/6 过滤 `='completed'` |
| **normalized_power** | Float / nullable / GPX = NULL | task-3/6 不过滤 NP / 直接看 tss 字段是否 NULL |

### User 字段（`app/user/models.py`）

| 字段 | 真值 | 注 |
|---|---|---|
| ftp | Integer / nullable | 不直接影响本 sprint（CTL/ATL 基于 TSS 不基于 FTP）|
| weight | Float / nullable | 不影响本 sprint |
| **birth_year** | **Integer / nullable / Sprint 10 hotfix 已加** ✓ | 不影响本 sprint（FTP estimator 用）|
| **max_hr** | Integer / nullable / Sprint 10 hotfix 已加 ✓ | 不影响本 sprint |

### Alembic head 真状态（2026-05-25 实证）

| 项 | 真值 | 注 |
|---|---|---|
| **当前 head** | **`sprint10_user_hr_profile`** ✓ | [migrations/versions/sprint10_user_hr_profile.py:11] |
| 下游 down_revision | `sprint9_persona_cleanup` | 链路：sprint9_training_metrics → sprint9_breakthrough_events → sprint9_persona_cleanup → sprint10_user_hr_profile |
| 本 sprint task-1 down_revision | **`sprint10_user_hr_profile`** | 必须接最新 head / 不能写 `sprint9_breakthrough_events` 或 `sprint9_persona_cleanup` |
| memory stale 提示 | `project_velo_current_position.md` line 10/96 把当前 head 写成 `sprint9_persona_cleanup` / **真 head 是 `sprint10_user_hr_profile`**（hotfix 已 ship / memory 未刷）| spec subagent 起手必跑 `sudo docker compose exec -T api python3 -m alembic heads`（**不要用 `ls migrations/versions/ \| tail -3`** / 字符串排序 `sprint10` < `sprint8` < `sprint9` / tail 看不到 sprint10）/ 不要被 memory 误导 |

### save_parse_result 真现状（`app/activity/worker.py:387`）

`save_parse_result(db, activity, result, user)` 已签 / 3 个调用方都已传 user：
- `app/activity/worker.py:230`（GPX/FIT 实时上传 worker）
- `app/strava/worker_strava.py:233`（Strava webhook 实时同步 worker）
- `app/strava/import_scheduler.py:507`（Strava 历史批量导入 scheduler）

**task-6 实施约束**（v0.2 / 第二轮 spec+集成审 + 第四轮 Codex 异源审收敛 / 2026-05-25）：
- ⚠ **hook 不挂在 `save_parse_result` 内部** —— save_parse_result docstring 明示"不调 db.commit() / 由 caller 控制事务边界"
- **单条 hook 挂在 caller 的 `db.commit()` 之前 / activity.status='completed' 之后**（仿 worker.py:261-263 注释 + 现有 5 个 hook 同 pattern / 都在 commit 之前 + SAVEPOINT 隔离）
- 设计哲学：daily_training_load 跟 activity 主流程绑同一事务 / activity 解析失败外层 rollback 时 daily_training_load 跟着 rollback 是预期语义（防孤儿数据）
- **2 个 caller 加单条 hook + 1 个 caller 走完工 backfill**（v0.2 修正 / import_scheduler 倒序处理会让 CTL/ATL 时序错乱）：
  - `app/activity/worker.py` `_do_parse()` 步骤 10.5-10.8 hook chain 末尾加"步骤 10.9" / 在 line 371 commit 之前
  - `app/strava/worker_strava.py` 进入 `_strava_post_parse_hooks()` 函数（line 281-370）末尾加第 6 个 hook block / 不在 caller 层另挂
  - **`app/strava/import_scheduler.py` 不挂单条 hook** / 改成 tier2 完工（`import_task.status='completed'` 赋值后）调一次 `backfill_daily_training_load_for_user(db, user_id)`（task-3 抽的 helper / 正序全量递推）
- SAVEPOINT pattern 仿 worker.py:351-369 breakthrough hook 精确写法（双层 try/except / `nested.rollback()` 不动外层 / 不加内层 `db.commit()`）/ 详 §6.3

### 当前生产 DB 状态（你账号 user_id=2 / Sprint 9 ship 后）

- 295 条 completed cycling 活动 / **184 条 NP 有值**（FIT + Strava）/ **111 条 NP 为 NULL**（早期 GPX）
- 184 条都有 `snapshot_ftp = 220`（Sprint 9 task-3 baseline 同步过）
- 184 条都有 `tss` 字段（IF/TSS 已算）
- 111 条 NP 为 NULL → `tss` 也 NULL → task-3 回填时**整条跳过 / 不算入 CTL/ATL**（决策 ★4 拍过）
- 跨度估算：294 条 / 平均每周 ~5 条 → 历史跨度约 14 个月 / 远超 CTL 时间常数 42 天 → 90 天曲线完整可视

### 训练负荷模块整体新建在 `app/training/`（不放 app/activity/）

- `app/training/` 整目录新建（**单一真相源 / Sprint 12 coach-engine §3.5 直接 import 复用 / 不重复实现**）
- `app/training/__init__.py` 一句话说明
- `app/training/models.py`（task-1 建 / `DailyTrainingLoad` ORM）—— **task-3 backfill 脚本 import 它 / 必须先于 task-3 实施**
- `app/training/training_load.py`（task-2 建 / 纯函数：TSS·CTL·ATL·TSB 公式 + 4 档分类 + 中文 label 格式化）
- `app/training/service.py`（task-4 建 / 查表逻辑 + 调 format_status_label / task-6 hook helper 也放这里）
- `app/training/schemas.py`（task-4 建 / Pydantic 响应 schema）
- `app/training/router.py`（task-4 建 / `GET /api/training/load`）

> **为什么不放 `app/activity/`**：训练负荷算法跟 `activity` 模块解耦 / `app/training/` 是新独立模块 / 单一真相源 / Sprint 12 跨模块 import 路径清晰（`from app.training.training_load import ...`）/ 不让 `app/agent/coach/` 在 Sprint 12 重复实现一套公式（共享逻辑识别红线）。

### 训练日历页是新页（不复用现有页面）

- `miniprogram/pages/training-calendar/` 不存在 / 全新建
- `miniprogram/pages/profile/profile.wxml` 加二级入口（task-7）
- `miniprogram/app.json` pages 列表加 `pages/training-calendar/training-calendar`（**加到列表末尾 / 不影响默认启动页**）

---

## 1. 子任务 task-1：DB 新表 daily_training_load + Alembic 迁移 + ORM 模型

### 1.1 用户目标
让 CTL / ATL / TSB / 每日 TSS / 每周累计 TSS / 状态档位有地方存 / 不用每次开训练日历页都重算 365 天。**同时把 `DailyTrainingLoad` ORM 模型建好 / 让 task-3 backfill 脚本能 import 到（task-3 必须先于 task-4 跑 / 不能等 task-4 才建 ORM）**。

### 1.2 使用场景
spec subagent 起手第一个 task / 没字段就什么都做不了 / 是后续所有 task 的地基。

### 1.3 功能范围
- 新建 `app/training/__init__.py`（模块说明 / 一句话）
- 新建 `app/training/models.py`：`DailyTrainingLoad` ORM 模型（**task-3 import 依赖 / 必须本 task 建好 / 不拖到 task-4**）
- 新建 `daily_training_load` 表（防火墙式扩展 / 不动 `activities` / `users` 等核心表）
- 字段方向（具体名 + 精度在 task 卡定）：
  - `id` 主键
  - `user_id` 外键 `users.id` / 级联删
  - `date` 北京时间日期（DATE 类型 / 不带时区 / 任 spec subagent 确认 Postgres DATE vs TIMESTAMP）
  - `ctl` Float / 1 位小数 / 健身度
  - `atl` Float / 1 位小数 / 疲劳度
  - `tsb` Float / 1 位小数 / 状态 = CTL - ATL
  - `tss_today` Float / 1 位小数 / 当日累计 TSS（同日多条活动求和）
  - `weekly_tss` Integer / 滚动 7 天累计 TSS（含当日 / **写入时必 round(SUM(float))** 转整数 / float SUM 直接写 Integer 列会报类型错 / Sprint 12 LLM 教练总结用整数）
  - `status_band` String(20) / 4 档枚举（fresh / ok / tired / overreached）
  - `updated_at` DateTime(timezone=True) / 写表/更新时间
- **唯一约束 UNIQUE(user_id, date)**：每用户每天最多一条 / task-6 增量更新走 upsert
- 索引 `idx_dtl_user_date` on (user_id, date DESC)：训练日历页查 365 天范围用
- Alembic 迁移 `sprint10_daily_training_load.py`：
  - `revision = "sprint10_daily_training_load"`
  - `down_revision = "sprint10_user_hr_profile"`（**当前真 head / 不是 sprint9_persona_cleanup**）

### 1.4 用户流程
（无 / 纯后端字段）

### 1.5 页面&状态
（无 / 纯后端字段）

### 1.6 数据需求
- 表规模估算：100 用户 × 365 天 = 36500 行 / 一年 / 极小
- DATE 类型字段 = 北京时间日期（不存时区）/ 所有写入方（task-3/6）必须先 `started_at.astimezone(BJ).date()` 再写

### 1.7 异常情况
- 迁移失败：alembic 回滚 / 重跑
- 老用户 birth_year/max_hr 为 NULL：不影响本表（本表不依赖这俩字段）

### 1.8 验收标准
- `alembic upgrade head` 跑过 / `\d daily_training_load` 看到全部字段 + UNIQUE + 索引
- `alembic downgrade -1` 能回到 `sprint10_user_hr_profile` / 不报错
- 真 PostgreSQL 生产部署后跑 `SELECT COUNT(*) FROM daily_training_load` 返 0（空表 / 等 task-3 回填）

### 1.9 不做项
- 不动 `activities` 表（防火墙红线）
- 不在迁移文件里跑 UPDATE / INSERT（回填走 task-3 独立脚本）
- 不加"用户自定义 CTL 时间常数"字段（默认 42/7 不让用户改）
- ORM `DailyTrainingLoad` 本 task 建 / **但本 task 不写查表 service**（service.py 留给 task-4 / 本 task 只到 models.py 这一层）

**来源**：路线图 §1 模块 B / Tim 2026-05-25 拍"存每日快照表"。

---

## 2. 子任务 task-2：训练负荷算法（纯函数模块）

### 2.1 用户目标
把 TSS / CTL / ATL / TSB / 4 档状态分类的公式写成纯函数 / 不查 DB / 任何调用方喂 (last_ctl, last_atl, tss_today) 就能返今日新值。

### 2.2 使用场景
- task-3 历史回填脚本调（按时间序递推 295 天）
- task-6 worker 增量更新调（写新活动后算当日新值）
- 单元测试可独立跑（纯函数 / 无副作用）

### 2.3 功能范围
- 新文件 `app/training/training_load.py`（**Sprint 12 coach-engine §3.5 已同步更新为 import 本路径 / 单一真相源 / 不在 `app/agent/coach/` 重复实现一套公式**）：
  - `calculate_daily_ctl(last_ctl: float, tss_today: float) -> float` —— 指数加权 / 时间常数 42 天
  - `calculate_daily_atl(last_atl: float, tss_today: float) -> float` —— 指数加权 / 时间常数 7 天
  - `calculate_tsb(ctl: float, atl: float) -> float` —— 简单减法 round 1 位
  - `classify_tsb_status(tsb: float) -> str` —— 返 4 档之一（fresh / ok / tired / overreached）
  - `format_status_label(band: str) -> str` —— 返中文文案（"状态饱满" / "状态 OK" / "累" / "过累"）
- 公式参考 coach-engine §3.1（行业标准 / TrainingPeaks PMC / 不发明公式）：
  ```
  CTL_today = CTL_yesterday × e^(-1/42) + TSS_today × (1 - e^(-1/42))
  ATL_today = ATL_yesterday × e^(-1/7)  + TSS_today × (1 - e^(-1/7))
  TSB = CTL - ATL
  ```
- 4 档状态阈值（Tim 2026-05-25 拍）：
  - **状态饱满**（fresh）：TSB > +10
  - **状态 OK**（ok）：-10 ≤ TSB ≤ +10
  - **累**（tired）：-20 ≤ TSB < -10
  - **过累**（overreached）：TSB < -20
- 单元测试覆盖：
  - 已知 last_ctl=50 / tss_today=80 → 返新 ctl ≈ 50.71（手算实证）
  - 边界：last_ctl=0 / tss_today=0 → 返 0
  - 4 档阈值边界（TSB=+10.0 / +10.1 / -10.0 / -20.0 各档归属）

### 2.4 用户流程
（无 / 纯算法 / task-3 + task-6 调用）

### 2.5 页面&状态
（无 / 纯算法 / task-3 + task-6 调用）

### 2.6 数据需求
- 输入：last_ctl / last_atl / tss_today（全 float）
- 输出：(new_ctl, new_atl, tsb, status_band) tuple 或 dataclass
- 类型方向：内部全用 float / round 在写表前做

### 2.7 异常情况
- last_ctl / last_atl 为 None（用户首日 / 没历史）→ 视为 0.0 起步
- tss_today 为 None（当日无活动）→ 视为 0.0 / CTL/ATL 按公式自然衰减
- tss_today 负数（脏数据）→ 抛 ValueError / 不静默吞

### 2.8 验收标准
- pytest 5 个测试全过：手算实证 / 边界值 / 4 档阈值 / None 处理 / 负数抛异常
- 模块独立 import 不依赖 DB / SQLAlchemy（纯函数纪律 / CLAUDE.md 已立规则）
- 真用回归：用你账号 task-3 回填出 90 天曲线 / TSB 应在 ±30 区间 / CTL 应在 40-90 区间（基于 295 条历史 + 平均每周 5 条骑行）

### 2.9 不做项
- 不在本模块查 DB（违反纯函数纪律）
- 不写"动态时间常数"（用户自定义 42/7）
- 不写 hrTSS 算法（GPX 无 NP 活动 task-3/6 跳过 / 不在此处补 TSS）
- 不写状态文案的中文长句（"今天可以再扛一两天"那种 Sprint 12 LLM 教练总结写 / 本 sprint task-5 只渲染短标签如"累"）

**来源**：路线图 §1 模块 B / coach-engine §3.1 公式 / Tim 2026-05-25 拍 4 档阈值。

---

## 3. 子任务 task-3：一次性历史回填脚本

### 3.1 用户目标
你账号 295 条历史活动 / Sprint 10 部署后立刻看到完整 90 天甚至全年 PMC 曲线 / 不用再骑 6 周等 CTL 累积。

### 3.2 使用场景
- spec subagent 部署 task-1 迁移后 / 立刻跑回填脚本（dry-run 1 用户 → apply 全用户）
- 全用户回填一次（生产 ~10 个活跃用户 / 量级小）

### 3.3 功能范围
- 新文件 `scripts/backfill_daily_training_load.py`（仿 `scripts/backfill_max_cadence_and_power_zones.py` 模板）
- 脚本顶部**显式 import 所有 ORM**（防独立脚本 ORM 加载陷阱 / memory `feedback_standalone_script_orm_loading.md`）：
  ```python
  from app.user.models import User  # noqa: F401
  from app.activity.models import Activity  # noqa: F401
  from app.training.models import DailyTrainingLoad  # noqa: F401
  ```
- 两段流程：
  - **dry-run 段**（默认 / 无 `--apply` 参数）：扫一个用户（默认 user_id=2 = Tim）/ 算出 365 天 daily_training_load / 打印前 10 行 + 最后 10 行 + summary（CTL 范围 / ATL 范围 / TSB 范围）/ 不写表
  - **apply 段**（`--apply --user-id X` 或 `--all-users`）：实际写表
- **抽 helper `backfill_daily_training_load_for_user(db, user_id) -> int` 函数**（返回写入行数 / 给 task-6 import_scheduler 完工后调）/ 脚本 main() 只负责 dry-run flag + for 循环 + sleep 节流 / 真正算法逻辑在 helper 里。
- 单用户算法（每用户独立 / 在 helper 内）：
  1. 拉该用户最早 completed cycling 活动 started_at → 北京时间归日 → 作为 start_date
  2. 从 start_date 走到今天 / 每天一个循环：
     - 拉该日所有 completed cycling 活动 + tss 不为 NULL（自动跳过 GPX 无 TSS）
     - 求和得 tss_today
     - 调 `calculate_daily_ctl(last_ctl, tss_today)` / `calculate_daily_atl(last_atl, tss_today)`
     - 算 TSB + 4 档分类
     - upsert 到 `daily_training_load`（按 UNIQUE(user_id, date) 冲突 → UPDATE）
     - **`db.flush()`**（让 SELECT SUM 同事务内可见 / 否则查不到本循环刚 upsert 的行 → weekly_tss 偏低）
     - 算 weekly_tss = round(SUM(tss_today)) WHERE date BETWEEN (当日-6) AND 当日 / 写回该日 daily_training_load 行
  3. 单用户全部循环完毕后 `db.commit()` / 走到下一个用户
- 节流：每用户处理完 sleep 0.5 秒 / 不会冲击 DB
- **共享逻辑**：所有算法调 task-2 的 `training_load.py` 函数 / 不在 backfill 重复实现（防两套逻辑漂移）

### 3.4 用户流程
（无 / 一次性脚本 / spec subagent 跑）

### 3.5 页面&状态
（无 / 纯后端脚本）

### 3.6 数据需求
- 输入：DB 现有 `activities` 表 295 条 + 你 user.ftp=210（但脚本不直接用 user.ftp / 用 activity.tss 已写入的值）
- 输出：`daily_training_load` 表写入 ~365 行/用户
- 跨度估算：你 user_id=2 / 14 个月历史 / 写入约 425 行

### 3.7 异常情况
- 用户 0 条 cycling 活动 → 脚本 log "user_id=X 无历史活动 / skip" / 不写任何行
- 用户全部活动都是 GPX 无 TSS → 脚本算出所有 daily 都 tss_today=0 + CTL/ATL 衰减到 ~0 / 写表但是 fresh 档（TSB=0）/ Sprint 11/12 评估是否在前端隐藏 PMC 入口
- DB 错误 → 单用户事务回滚 / 不影响其他用户 / log + continue
- 用户最早活动是 2024 年 / 跨度超 365 天 → 仍然算全部 / 不截断（CTL/ATL 指数加权 / 早期数据影响很小但留底）

### 3.8 验收标准
- dry-run 你账号：打印 90 天 PMC summary（CTL 起点 vs 终点 / TSB 范围 / weekly_tss 范围）/ 数字合理（CTL ≥ 30 / ≤ 90）
- apply --user-id 2：DB 写入 ~400 行 / `SELECT COUNT(*) FROM daily_training_load WHERE user_id=2` ≥ 365
- apply --all-users：全用户跑完 / log 显示每用户写入条数 / 总耗时 < 10 分钟
- 复跑幂等：再跑一次 apply 不报错（upsert 冲突走 UPDATE）/ DB 行数不变

### 3.9 不做项
- 不补 GPX 无 NP 活动的 TSS（按拍板 ★4 跳过）
- 不写"增量回填"（部署后 task-6 增量更新接手）
- 不写"回填进度条"（脚本只在 spec subagent 终端跑 / 看 log 够用）
- 不在脚本里改 alembic head（task-1 迁移单独跑）

**来源**：路线图 §1 模块 B + Tim 2026-05-25 拍"一次性回填"+ Sprint 7 backfill_activity_city.py 节流模板。

---

## 4. 子任务 task-4：GET /api/training/load endpoint

### 4.1 用户目标
前端训练日历页一次请求拿到 30/90/365 天的曲线点 + 当前状态卡数据 / 不用前端拼装多个接口。

### 4.2 使用场景
- 用户进训练日历页 → 默认 30 天 tab → 调 `GET /api/training/load?range=30d`
- 切换 90d / 1y tab → 重新调一次（不在前端裁剪 / 后端按 range 返不同条数）

### 4.3 功能范围
- 本 task 在 `app/training/` 模块下补建 task-1 没建的部分（不复用 `app/activity/router.py` / 不挤 activities 命名空间）：
  - `app/training/router.py` 新建 / 含 `GET /api/training/load`
  - `app/training/schemas.py` 新建 / 含 Pydantic 响应 schema（强制 round 1 位小数 / 见下方"字段精度"）
  - `app/training/service.py` 新建 / 含查表逻辑 + 调 `format_status_label(status_band)` 转中文 / task-6 hook helper 也放这里
  - `app/training/__init__.py` 已 task-1 建好
  - `app/training/models.py` 已 task-1 建好（`DailyTrainingLoad` ORM）
- **register router**（**集成审 Critical 必修 / 不写 endpoint 会永远 404**）：
  - 在 `app/main.py` 加 `from app.training.router import router as training_router` + `app.include_router(training_router)`
  - 验收：curl 真 endpoint 返 200 / 不是 404
- endpoint 设计方向：
  - `GET /api/training/load?range=30d|90d|1y`（**待 Tim 拍**：是否分三个 endpoint / 推荐单 endpoint + query param）
  - 鉴权：JWT 必填 / 只返当前用户数据
  - 响应字段方向：
    ```
    {
      "range": "30d",
      "points": [
        { "date": "2026-05-25", "ctl": 65.3, "atl": 78.1, "tsb": -12.8, "tss_today": 95.5, "status_band": "tired" },
        ...
      ],
      "summary": {
        "current_ctl": 65.3,
        "current_atl": 78.1,
        "current_tsb": -12.8,
        "current_status_band": "tired",
        "current_status_label": "累",
        "weekly_tss": 450,
        "data_complete": true   // false 表示用户 < 14 天历史 / 前端显示"再骑 N 天能看到完整曲线"
      }
    }
    ```
  - 字段精度（Tim 2026-05-25 拍 / §8 ★6）：ctl/atl/tsb 1 位小数 / tss_today 1 位小数 / weekly_tss 整数
- status_label 转换：service.py 查完表后 / 对 summary.current_status_band 调 `training_load.format_status_label()` 返中文（"状态饱满" / "状态 OK" / "累" / "过累"）/ 填入 `current_status_label`。**这一步在 service 层做 / 不在 schema 自动算 / 不在前端硬编码**（Sprint 12 coach-engine 直接读 status_band 原始枚举 / current_status_label 是给小程序前端展示用）
- 性能约束：30 天返 30 个点 / 90 天返 90 个点 / 1y 返 365 个点 / 单次查询 < 200ms
- 缺数据填充语义（澄清 §4.7 边界）：
  - **窗口内部分缺日**（用户某些天没骑车 / 但其他天有 daily_training_load 记录）→ endpoint 在响应 points 数组里补出该日的全零点（ctl/atl 走自然衰减 / tss_today=0 / status_band 按 TSB 重算）
  - **完全无记录**（新用户 / 没跑过 task-3 也没 task-6 hook）→ 返 `points=[]` + `summary.data_complete=false`（详 §4.7）

### 4.4 用户流程
1. 张三进训练日历页（task-5）→ 默认 30 天 tab
2. 前端 `wx.request` 调 `GET /api/training/load?range=30d`
3. 后端拉 30 天 daily_training_load 记录 / 缺日补 0 / 返 30 个点 + summary
4. 前端 canvas 画曲线 + 顶部状态卡渲染 summary

### 4.5 页面&状态
（无 / 纯后端 endpoint）

### 4.6 数据需求
- 输入：query param `range` ∈ {30d, 90d, 1y}
- 输出：points list + summary dict（数据 schema 见 §4.3）
- DB 查询：单 SELECT 按 user_id + date range / 走 task-1 加的 idx_dtl_user_date 索引

### 4.7 异常情况
- 用户无任何 daily_training_load 记录（新用户 / 还没跑过 task-3 也没 task-6 hook）→ 返 `points=[]` + `summary.data_complete=false` + `current_ctl=0` 等全 0
- 用户有但 < 14 天 → 返实际有的 + `data_complete=false`（前端文案"再骑 N 天能看完整曲线"）
- range 非法值（如 `range=7d`）→ 422 Validation Error
- 鉴权失败 → 401

### 4.8 验收标准
- **`app/main.py` 已加 `include_router(training_router)`**（否则 404 / curl 必失败）
- 你账号（user_id=2 / 跑过 task-3）：30d 返 30 个点 / 90d 返 90 个点 / 1y 返 365 个点 / summary.current_ctl 在合理范围
- 新建测试账号（无历史）：30d 返 `points=[]` + `data_complete=false`
- 单测覆盖 4 个场景（30d/90d/1y/无数据）
- curl 真实 endpoint：`GET /api/training/load?range=30d` 返 200 + JSON 结构正确（按部署 SOP 验证）
- summary.current_status_label 真的是中文（不是英文枚举 / 证明 service.py 调了 format_status_label）

### 4.9 不做项
- 不返"对比同档骑友"数据（Sprint 11/12 训练分布做）
- 不返"建议训练计划"文案（Sprint 12 LLM 教练总结做）
- 不做 CSV 导出（v1.5+）
- 不做"上周对比"差值字段（前端可自己算 / 不在 endpoint 加复杂度）

**来源**：路线图 §1 模块 B / Sprint 12 字段合同对照 coach-engine §4.2。

---

## 5. 子任务 task-5：训练日历页前端 + 我的页二级入口

> **v0.2 合并**：原 task-5（训练日历页）+ 原 task-7（入口位置）合并为本 task / 同前端 PR 自然 / 符合 CLAUDE.md "一期任务数 ≤ 6"硬规则。

### 5.1 用户目标
张三周末打开 velo / 在"我的"页找到"训练分析"入口 / 点进训练日历页 / 一眼看清三条曲线 + 顶部状态卡 / 不用研究 PMC 是什么。**严肃骑手能找到入口 / 轻度用户感知不到 / 不挤 Sprint 12 的动态 tab 顶部大卡**。

### 5.2 使用场景
- 张三周末复盘上周训练 / 进"我的"页 → 点"训练分析" → 想知道是不是该歇了
- 张三周三决定明天上不上量 / 看 TSB 决定
- 新用户进 velo / 默认看动态 tab / 不会主动去"我的"二级 / 也不被推训练分析（避免被淹）

### 5.3 功能范围

**A. 训练日历页**：
- 新建页 `miniprogram/pages/training-calendar/training-calendar.{wxml,wxss,js,json}`
- `miniprogram/app.json` pages 列表加 `pages/training-calendar/training-calendar`（**加到列表末尾 / 不要插到第一行 / app.json pages 第一项是默认启动页 / 误插会让用户开 App 直接进训练日历而不是动态 feed**）
- 页面结构（从上到下）：
  1. **顶部状态卡**（占屏宽 / ~200rpx 高）：
     - 大字状态标签（"状态饱满" / "状态 OK" / "累" / "过累" / 4 档 + 4 种背景色）
     - 数据行：CTL 65 / ATL 78 / TSB -13 / 本周累计 TSS 450
     - 短描述（1 行 / 不长 / 由前端按 status_band 硬编码 4 套文案 / 不调 LLM）：
       - fresh：你状态饱满 / 可以上强度
       - ok：状态 OK / 按计划训练即可
       - tired：累 / 建议中低强度或休息
       - overreached：过累 / 强烈建议休息 1-2 天
  2. **时间窗 tab**（30 天 / 90 天 / 全年 / 默认 30 天）
  3. **曲线图区**（canvas 2d 画 / 占屏宽 / ~500rpx 高）：
     - 三条线：绿色（CTL）/ 黄色（ATL）/ 蓝色（TSB / TSB 是减法所以有正负 / 蓝线在 0 轴上下浮动）
     - x 轴：日期（30 天每周一标 / 90 天每两周 / 1y 每月）
     - y 轴：左 CTL/ATL 范围（0-100）/ 右 TSB 范围（-30 ~ +30）
     - 图例：右上角小字（CTL / ATL / TSB 三色）
     - **canvas 2d 用 `<canvas type="2d" id="pmc-chart"></canvas>` + setData callback `setTimeout(fn, 100)` 兜底**（防 wx.nextTick race / memory `feedback_wechat_miniprogram_hard_limits.md` 类陷阱）
  4. **空数据态**（`summary.data_complete=false`）：
     - 状态卡部分文案改"再骑 N 天能看到完整训练负荷曲线 / 我们需要至少 14 天数据才能算出健身度"
     - 曲线图区不画 / 显示一张占位插图（不显示假数据曲线 / 防误导）
- wx:if 严格控制：summary 缺失 → 整页空数据态 / 不显示 "-" 占位符（memory `feedback_no_dash_placeholder.md`）

**B. "我的"页二级入口**：
- 改 `miniprogram/pages/profile/profile.wxml` 加一行：
  - 文案"训练分析" + 副标"看 30/90/全年训练负荷曲线"
  - 位置：放在已有"我的荣誉"入口下方（commit `a195355` 已加我的荣誉 / 风格对齐）
  - 点击 wx.navigateTo 到 `pages/training-calendar/training-calendar`
- **入口常显 / 不依赖 user_stats 粗筛**（v0.2 Codex 异源审修正 / 2026-05-25）：
  - 原 v0.1 写"用 user_stats 判断 ≥1 条 cycling 活动"——但 `profile.js:150` 调的是 `period=week` / `schemas.py:163,167` rides 是**本周次数** / 严肃老用户本周休息 → rides=0 → 入口被错误隐藏
  - 改为：**入口常显 / 不做粗筛**；进训练日历页后由训练日历页空数据态接管（`summary.data_complete=false` → 显示"再骑 N 天能看到完整曲线"+ 占位插图 / 不画假曲线）
  - 收益：① 老用户永远找得到入口 ② 简化代码（不需要 period=all 新 endpoint）③ 一致 UX（"入口在 / 进去看真实状态"比"入口忽隐忽现"友好）

### 5.4 用户流程
1. 张三进"我的"页 → 看到"训练分析"二级入口（永远显示 / 不消失）→ 点击
2. 进训练日历页 → 默认 30 天 tab → loading 转圈
3. canvas 画完三条曲线 / 顶部状态卡渲染
4. 张三点 90 天 tab → 重新拉数据 → canvas 重画
5. 张三看完关页

### 5.5 页面&状态
- loading 状态：转圈（cv 2d 渲染前）
- 错误状态：toast "训练分析加载失败 / 请重试"
- 空数据态：不显示曲线 / 顶部"再骑 N 天能看到"文案 + 占位插图
- 4 档状态卡的背景色由 status_band 决定（fresh 绿 / ok 蓝灰 / tired 橙 / overreached 红）—— 但**不要让红色看起来像在批评用户 / 用暖红不是警告红 / 类比饿了么"再点份就饱了"那种暖提醒**

### 5.6 数据需求
- 输入：调 `GET /api/training/load?range={30d|90d|1y}`（task-4）
- 输出：canvas 绘制 + 状态卡 setData

### 5.7 异常情况
- endpoint 500 → toast + 退出页 / 不卡死
- canvas 2d 初始化失败（极慢机型）→ setTimeout 100ms 兜底（memory `feedback_wechat_miniprogram_hard_limits.md` 第 17 条陷阱）
- 用户 PullDownRefresh：重新拉数据 + 重画

### 5.8 验收标准
- 真用回归你账号：进"我的"页 → 看到"训练分析"入口（永远显示）→ 点击进训练日历页 → 30 天曲线三条线都出来 / 顶部状态卡正确
- 切 90 天 / 1y / 都能渲染
- 测试账号（无活动）：进"我的"页 **入口仍显示**（v0.2 改 / 不再 wx:if 隐藏）→ 点击进训练日历页看到空数据态 + 不显示曲线
- 严肃老用户本周休息场景（user_stats?period=week → rides=0）：入口仍显示（v0.2 防误藏 / Codex 异源审实证 fix）
- 真机回归 2 台机型（你的 iPhone + 一台 Android）/ canvas 2d 都正常渲染

### 5.9 不做项
- 不画"用户自定义时间窗"（如自定义 60 天）
- 不做"曲线点击查看那天活动详情"（Sprint 11 后看反馈再加）
- 不做"曲线导出图片分享"（v1.5+）
- 不做"和上月对比箭头"（前端不算）
- 不写 LLM 风格的长文案推荐（4 档短标签 + 1 行硬编码就够 / Sprint 12 教练总结才上 LLM 长文）
- 不做"首页通知红点"提示训练分析（Sprint 12 LLM 教练总结才主动推 / 本 sprint 不挤）
- 不做"详情页跳训练日历"按钮（路径太散 / 不增加入口噪音）
- 不在动态 tab 顶部加大卡（保留给 Sprint 12 coach-engine）

**来源**：路线图 §1 + §6.2 + Tim 2026-05-25 拍 4 档状态文案 + 二级入口策略 + memory feedback_no_dash_placeholder / feedback_wechat_miniprogram_hard_limits 已踩坑沉淀 + 2026-05-25 Codex 异源审"入口常显防误藏"修正。

---

## 6. 子任务 task-6：worker 增量更新 daily_training_load

### 6.1 用户目标
用户上传 / 同步新活动后 / 当日 `daily_training_load` 自动更新 / 用户下次进训练日历页能看到今天的数据 / 不用等次日 cron。

### 6.2 使用场景
- 张三今天骑完 / Strava 同步 → worker_strava 处理 → 写完 activity 后单条 hook 更新当日 PMC
- 张三上传 GPX/FIT → worker 处理 → 同单条 hook
- **Strava 历史批量导入（绑定时拉 200 条）→ import_scheduler tier2 倒序处理（最新先 / `import_scheduler.py:440` `order_by(started_at.desc())`）→ 不挂单条 hook**（倒序触发会让 CTL/ATL 时序错乱 / CTL 正序递推依赖前一日 / 倒序处理时每日 CTL 都基于"过去无历史"=0 起步 / 曲线全错）→ **tier2 完工时调一次 `backfill_daily_training_load_for_user(db, user_id)`**（task-3 抽的 helper / 正序全量递推 / 一次性算对所有日）/ 2026-05-25 Codex 异源审实证

### 6.3 功能范围

**hook 在 caller 的 `db.commit()` 之前 / 与 `activity.status='completed'` 在同一事务提交 / 仿 worker.py 现有 5 个 hook pattern**（第二轮 spec+集成审 grep 实证 worker.py:260-371 修正 / 2026-05-25）：

- 关键事实（grep 实证）：worker.py:261-263 注释明写"hook 落在 status='completed' 赋值后、db.commit 前——这样 detector 写的 notification 与 activity.status 在同一 transaction 提交（一致性 OK）"。现有 5 个 hook（dedupe / detect_5min_power_progress / activity.city / user.city / breakthrough_detector）全部在 line 371 `db.commit()` **之前** + 用 `db.begin_nested()` SAVEPOINT 隔离。
- 设计哲学：daily_training_load 跟 activity 主流程绑同一事务 / activity 解析失败外层 rollback 时 daily_training_load 跟着 rollback **是预期语义**（防孤儿数据：activity 不存在但当日负荷已更新）。SAVEPOINT 只防止"hook 自己出错炸了外层 activity.status"。
- helper 函数：`update_daily_load_for_activity(db, user, activity)` 写在 `app/training/service.py` / 内部用 try/except 兜底 / **不在 helper 内调 `db.commit()` / 也不在 caller hook block 内调 `db.commit()`**（caller 现有 `db.commit()` 统一提交）。
- **2 个 caller 加单条 hook + 1 个 caller 走完工 backfill**（v0.2 Codex 异源审修正）：
  - `app/activity/worker.py` `_do_parse()`：现有 hook chain（步骤 10.5-10.8）末尾加"步骤 10.9：daily_training_load 增量更新" / 紧跟 breakthrough hook（line 345-369）之后 / **在 line 371 `db.commit()` 之前**
  - `app/strava/worker_strava.py`：进入 `_strava_post_parse_hooks()` 函数（line 281-370）末尾加第 6 个 hook block / 在 line 266 `db.commit()` 之前（仿现有 5 hook 同 pattern / 不在 caller 层另挂）
  - **`app/strava/import_scheduler.py`：不挂单条 hook**（tier2 倒序处理会让 CTL/ATL 时序错乱）/ 改成在 tier2 全部完工（`import_task.status='completed'` 赋值后）调一次 `backfill_daily_training_load_for_user(db, import_task.user_id)` / 一次性正序递推全部历史。具体挂入点：`import_scheduler.py` tier2 完工分支（grep `status="completed"` 找位置）加 try/except 兜底（backfill 失败 log + 不影响 import_task 状态）
- SAVEPOINT block pattern（仿 worker.py:351-369 breakthrough hook 精确写法 / 双层 try/except / **无内层 `db.commit()`** / **except 用 `nested.rollback()` 不动外层事务**）：
  ```python
  # 在 caller activity.status='completed' 之后、db.commit() 之前
  if not is_duplicate:
      try:
          from app.training.service import update_daily_load_for_activity
          nested_dtl = db.begin_nested()
          try:
              update_daily_load_for_activity(db, user, activity)
              nested_dtl.commit()       # RELEASE SAVEPOINT / 数据仍在外层事务
          except Exception:
              nested_dtl.rollback()     # 只回退 SAVEPOINT / 不动 activity.status
      except Exception:
          # 最外层兜底：begin_nested 失败 / 模块 import 极端失败
          logger.exception(
              "update_daily_load hook outer SAVEPOINT failed activity_id=%s",
              activity.id,
          )
  # 然后 caller 现有 db.commit() 统一提交 daily_training_load + activity.status
  ```

helper 内部逻辑（写在 `app/training/service.py`）：
  1. 计算 activity 归属哪一天：`bj_date = activity.started_at.astimezone(_BJ_TZ).date()`（**`_BJ_TZ` 在本 service.py 内独立声明 `timezone(timedelta(hours=8))` / 不跨模块 import `progress_detector` 的私有符号 / 仿相同 pattern**）
  2. 拿该用户该日 daily_training_load 记录（如存在）+ 该用户**最近一条 date < bj_date 的记录**（拿 last_ctl/last_atl / **`ORDER BY date DESC LIMIT 1` / 不限 N 天范围** / 否则用户 2 周没骑车曲线会断崖回 0）
  3. 拿该用户该日**所有 completed cycling + tss 不 NULL** 的活动 → 求和 tss_today
  4. 调 `training_load.py` 算出新 ctl/atl/tsb/status_band
  5. upsert 到 `daily_training_load`（UNIQUE 冲突 → UPDATE）
  6. 更新 weekly_tss：`db.flush()` 后 SELECT SUM(tss_today) WHERE date BETWEEN (bj_date-6) AND bj_date → round() 整数 / 写回该日 daily_training_load.weekly_tss 列

**批量导入策略**（v0.2 Codex 异源审修正 / 不再"每条都触发 hook"）：
- import_scheduler tier2 路径**不挂单条 hook**（防 CTL/ATL 时序错乱）
- tier2 完工时调一次 `backfill_daily_training_load_for_user(db, user_id)` 全量正序递推
- 收益：① 解决倒序时序错乱 ② 同时消解 reviewer-integration 第一轮抓的"40000 ops 峰值"性能 hot spot（不再 200 × 4 ops 逐条触发）
- 兜底：backfill 失败 log + 不影响 import_task.status / 用户下次同步 Strava 触发新 tier2 完工再跑（自愈）

**部署边界**（集成审 Important 1）：
- 改的代码涉及 `app/activity/worker.py`（单条 hook）+ `app/strava/worker_strava.py`（单条 hook）+ `app/strava/import_scheduler.py`（tier2 完工调 backfill）+ 新 `app/training/service.py` + `scripts/backfill_daily_training_load.py`
- api / worker / scheduler / cleanup / curation-pool-cron 5 个容器共享 `build: .` 同一 image / 改 import_scheduler.py 必 rebuild scheduler 容器
- **部署 SOP 必跑** `docker compose up -d --build`（不指定 service / 让 docker 自动 rebuild 所有受影响容器）/ **不能只 rebuild worker**（2026-05-20 Persona 漏 rebuild scheduler 实证）

### 6.4 用户流程
（无 / 纯后端 hook / 用户无感知）

### 6.5 页面&状态
（无 / 纯后端）

### 6.6 数据需求
- 输入：activity 对象（已写完 tss / snapshot_ftp / started_at 等）
- 输出：`daily_training_load` 表 upsert 一行 + 重算 weekly_tss
- 时区：activity.started_at 是 UTC / 必转北京时间归日

### 6.7 异常情况
- activity.tss 为 NULL（GPX 无 NP）→ tss_today 仍按当日**其他活动** sum 算 / 该 activity 不贡献 / 不报错
- activity.started_at 为 NULL（脏数据）→ helper 跳过 + log warn / 不影响主流程
- DB 错误 → SAVEPOINT 回滚 / 主流程继续
- 用户当日已有 daily_training_load 但前日没有（昨天没骑车）→ helper 用 `ORDER BY date DESC LIMIT 1` 查该用户最近一条记录（不限 N 天范围 / 防"2 周没骑车曲线断崖回 0"）/ 真无任何历史记录 → last_ctl/last_atl=0.0 起步（首日场景）

### 6.8 验收标准
- 单测覆盖：新活动 hook 触发 / upsert 已存在记录 / SAVEPOINT 失败不污染主流程 / 时区归日正确
- 真用回归：你账号上传 1 条 GPX → 看 `daily_training_load` 该日记录有更新（即使 tss_today=0 也更新了 updated_at）
- 真用回归：你账号触发 Strava webhook 同步一条新活动 → 同样验证 daily_training_load 更新
- 性能：单 activity hook 增量耗时 < 100ms（不延迟 save_parse_result 主流程）

### 6.9 不做项
- 不做"cron 每天 0:00 全用户批量算"（增量 hook 够用 / 无活动的用户不需要算）
- 不做"用户改 ftp 后回填 daily_training_load"（Sprint 9 task-4 已经触发回填 activity.tss / 但 daily_training_load 不重算 / 因为 CTL/ATL 公式基于已写入的历史 tss / 不依赖 ftp）
- 不做"删活动 / 改 activity status 时回退 daily_training_load"（本 sprint 删活动 / 改 status 后 daily_training_load 不自动更新 / 留 Sprint 11 评估是否做回退 SQL UPDATE / 用户真用回归暴露问题再处理）

**来源**：路线图 §1 模块 B / save_parse_result 已存在 3 路覆盖 / memory feedback_savepoint_isolation 已沉淀 pattern。

---

## 7. 跨子任务约束

### 7.1 时区统一（北京时间 UTC+8）
- 所有"日"边界按北京时间（UTC+8）
- **`app/training/service.py` + `scripts/backfill_daily_training_load.py` 内独立声明 `_BJ_TZ = timezone(timedelta(hours=8))`**（仿 `app/notification/progress_detector.py:46` 同 pattern / 但**不跨模块 import 私有符号 `_BJ_TZ`** / 私有变量带下划线前缀外部 import 是反模式 / 各模块独立声明同 pattern 更安全）
- daily_training_load.date 字段存 DATE 类型（不带时区）/ 写入前必转北京时间日期
- 一天起点 = 北京时间 0:00（不是 6:00 / 跟 weekly_tss 滚动 7 天对齐）

### 7.2 性能约束
- task-2 纯函数：单次调用 < 1ms（指数加权简单计算）
- task-3 回填脚本：单用户 < 30 秒 / 10 用户全跑 < 10 分钟
- task-4 endpoint：单次响应 < 200ms（30/90/365 天查询走索引）
- task-5 训练日历页首屏：< 1.5 秒（含 endpoint + canvas 渲染）
- task-6 hook：单 activity 增量更新 < 100ms（含 last_ctl 查询 + tss_today SUM + upsert + weekly_tss SUM 4 个 DB 操作）
- **task-6 Strava 批量导入策略**（v0.2 / Codex 异源审 Critical 1 修法）：import_scheduler tier2 路径不挂单条 hook / 完工时调一次 `backfill_daily_training_load_for_user` 全量正序递推 / 单次执行 < 30 秒（200 条历史 × 单日 ~4 DB ops = ~800 ops 一次性）/ 顺便消解第二轮 reviewer-integration 抓的"40000 ops 峰值"hot spot（不再 200 条逐条触发）

### 7.3 兜底
- task-3 回填失败：log + 用户下次进训练日历页看到"曲线数据不全 / 请联系客服"（暂不实现自动重试 / 看真用情况）
- task-4 endpoint 异常：返 503 / 前端 toast / 不影响其他页面
- task-5 canvas 渲染失败：toast + 占位插图
- task-6 hook 失败：SAVEPOINT 回滚 / 不影响 save_parse_result 主流程 / 下次同用户新活动 hook 触发时会重算当日

### 7.4 真用回归路径（按 memory `feedback_real_usage_vs_mock_blindspot.md`）
- **回归 1**（task-3 部署后）：你账号打开训练日历页 → 看到完整 90 天曲线 → CTL 数字符合直觉（你过去半年训练量 → CTL 应在 40-70 区间）
- **回归 2**（task-6 部署后 GPX 路径）：你上传 1 条新 GPX → 等 worker 处理完 → 进训练日历页 → 当日曲线点更新（tss_today 反映新活动）
- **回归 3**（task-6 部署后 Strava webhook 路径）：你 Strava 上传一条新活动 → webhook 同步 → 进训练日历页 → 当日曲线更新
- **回归 4**（task-6 Strava 批量导入路径 / v0.2 Codex 异源审 Critical 1 强化）：用测试账号走完整 Strava 绑定流程 → import_scheduler 拉 200 条历史 + tier2 完工触发 backfill helper → **跟完整 backfill 结果逐日比对**（不只是 COUNT(*) / 而是 SELECT date, ctl, atl, tsb 对照 / 验证 CTL/ATL 正序递推没错乱）/ 这条路径覆盖 SAVEPOINT 边界 + scheduler 容器 rebuild + Codex 抓的倒序时序错乱三个 Critical 风险点
- **回归 5**（task-5 真机）：iPhone + Android 各开一次 / 三条曲线都正常 / 不卡死 / 1y tab 渲染 1095 点（3 线 × 365）低端机不超 setTimeout 100ms 兜底
- **回归 6**（4 档状态文案）：你拍 4 种状态下的截图（fresh / ok / tired / overreached）+ 看文案是否得体 / 不批评用户 / 不夸张

### 7.5 spec subagent 起手必做（防 stale）
- `sudo docker compose exec -T api python3 -m alembic heads` 确认 alembic head 真值（**当前 = `sprint10_user_hr_profile` / memory current_position line 10/96 stale**）/ **不要用 `ls migrations/versions/ | tail -3`**（字符串排序陷阱：sprint10 < sprint8 < sprint9 / tail 看不到 sprint10 / 2026-05-25 Codex 异源审实证）
- 真 DB 查"current activity counts"：`SELECT COUNT(*) FROM activities WHERE user_id=2 AND status='completed' AND activity_type='cycling'` / 应 ≥ 295
- 真 DB 查 tss 覆盖率：`SELECT COUNT(*) FROM activities WHERE user_id=2 AND tss IS NOT NULL` / 应 ≈ 184
- 真 DB 查 normalized_power 覆盖：`SELECT COUNT(*) FROM activities WHERE user_id=2 AND normalized_power IS NULL AND activity_type='cycling' AND status='completed'` / 应 ≈ 111

---

## 8. 待 Tim 过 PRD 时拍板的剩余决策

> 写到这里发现 4 个核心决策（架构 / 状态档 / 回填 / GPX 处理）已拍 / 但写章节过程中又产生几个细节决策点 / 列在这里集中拍。

| # | 决策点 | 我推荐 | 影响 |
|---|--------|--------|------|
| ★5 | task-4 endpoint 形态：单 endpoint + query param vs 三个 endpoint | **单 endpoint + range=30d/90d/1y** | RESTful 风格统一 / 前端 1 个 helper 函数 |
| ★6 | 字段精度合同 | CTL/ATL/TSB/tss_today **1 位小数** / weekly_tss **整数** | 跟 Sprint 12 coach-engine §4.2 字段合同对齐 |
| ★7 | weekly_tss 是滚动 7 天还是自然周（周一开始） | **滚动 7 天**（含当日往前 6 天） | 自然周用户跨周看会有断裂感 / 滚动 7 天平滑 |
| ★8 | task-6 batch 模式：Strava 200 条历史批量导入触发 hook 是否合并最后一次算 | **每条都触发 hook**（简单 / 100 用户量级可接受 / 真慢再优化） | 简化代码路径 / 不引入"批量 vs 单条"分支判断 |
| ★9 | task-5 4 档背景色：fresh/ok/tired/overreached 4 色 vs 3 色（合并 ok+fresh） | **4 色**（绿色 fresh / 浅蓝 ok / 暖橙 tired / 暖红 overreached） | 跟 4 档状态分类一一对应 / 不让"OK 和饱满"视觉混淆 |
| ★10 | task-1 索引：UNIQUE(user_id, date) 已加 / 是否额外加 (user_id, status_band) 索引 | **不加**（reverse lookup "all overreached users today" 是 v1.5+ 排行榜场景 / 当前不做）| 索引只加真要查的 / 不预想未来 |

---

## 来源追溯

- 上游：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md` 模块 B
- 下游字段合同：`docs/superpowers/specs/2026-05-20-coach-engine-design.md` §3.1 / §4.2 / §3.5（**已同步更新为 import `app.training.training_load` / 路径单一真相源**）/ §3.3（**已同步更新为 4 档状态阈值 / 跟本 PRD 一致 / 原 v0.1 写的 3 档已废**）
- **状态档位权威**：4 档（fresh > +10 / ok -10~+10 / tired -20~-10 / overreached < -20）以本 PRD §2.3 + 来源追溯下方 Tim 拍板段为准 / coach-engine-design.md §3.3 已同步 / Sprint 12 实施时按本 PRD 4 档 schema 对接 daily_training_load.status_band
- Tim 2026-05-25 brainstorm + 拍板（4 个核心决策）：
  - 存每日快照表（防全年曲线每次重算）
  - 4 档状态阈值（fresh / ok / tired / overreached / TSB 边界 +10 -10 -20）
  - 一次性历史回填（你账号 295 条 / 部署后立刻看 90 天曲线）
  - GPX 无 TSS 活动跳过（不引入 hrTSS / 等 Sprint 12 coach-engine 内部如需要再单评）
- 算法公式：行业标准 / TrainingPeaks PMC 公开（CTL τ=42 / ATL τ=7）/ 不发明
- 工程实证：Sprint 9 backfill_max_cadence_and_power_zones.py 脚本框架可复用 / SAVEPOINT 隔离 pattern 在 progress_detector / dedupe 已有先例 / **hook 挂在 caller `db.commit()` 之前 + SAVEPOINT 隔离** 仿 worker.py:351-369 breakthrough_detector hook 同 pattern（第二轮 spec+集成审 grep 实证 worker.py:261 注释明示"hook 落在 status='completed' 赋值后、db.commit 前"）
- 第二轮双审收敛（2026-05-25 / Critical 5 + Important 8 + Nit 4 全修）：
  - Critical #1 training_load.py 路径 → `app/training/training_load.py`（两审独立共识）
  - Critical #2 4 档 vs 3 档 → PRD + coach-engine §3.3 同步声明 4 档为准
  - Critical #3 SAVEPOINT 边界 → hook 在 caller commit **之前** + SAVEPOINT 隔离（第一轮误判 commit 之后 / 第二轮 grep 实证 worker.py 现有 5 hook 全部 commit 之前 / 已纠正）
  - Critical #4 main.py 注册 → §4.8 验收明确加 include_router
  - Critical #5 task-3 ORM import → models.py 在 task-1 建（不拖到 task-4）
  - Important #1-8：容器 rebuild / last_ctl 查询 / weekly_tss flush / BJ 时区 / 缺日补 0 语义 / status_label 转换 / app.json 顺序 / Strava 批量真用回归
- **v0.2 第四轮 Codex 异源审收敛（2026-05-25 / Critical 1 + Important 3 全修）**：
  - Critical 1 Strava 历史导入 CTL/ATL 时序错乱 → import_scheduler tier2 不挂单条 hook / 完工后调 backfill helper 全量正序递推（task-3 抽 helper）+ 真用回归改"逐日比对"非 COUNT(*)
  - Important 1 profile 入口误藏 → 入口常显 / 不依赖 user_stats?period=week 粗筛 / 由训练日历页空数据态接管
  - Important 2 `ls | tail -3` 不可靠 → 改 `alembic heads`（字符串排序陷阱 sprint10 < sprint8 < sprint9）
  - Important 3 7 task 超 ≤ 6 硬规则 → 合并原 task-5（训练日历页）+ 原 task-7（入口）为新 task-5 / 6 task
