# velo Sprint 9 战术 PRD —— FTP 智能化 + 单次活动评分

> **2026-05-21 ✅ 全部 ship**：8 task + 9 hotfix / Alembic head = `sprint9_breakthrough_events` / git main = `5ba4229`。完工记录见 `docs/changelog.md` 2026-05-20→21 段。P1 tech debt：ftp_estimator 算 Tim ftp=117W vs 真实 250W（`docs/tech-debt.md` P1）/ Sprint 10 后专题。
>
> **本文件性质**：Sprint 9 战术 PRD，给执行 spec subagent 看的执行手册。
>
> **写作规范**（沿用 sprint-6-prd.md / Tim 2026-04-28 拍）：每子任务严格 **9 章节**（用户目标 / 使用场景 / 功能范围 / 用户流程 / 页面&状态 / 数据需求 / 异常情况 / 验收标准 / 不做项）+ 来源追溯一行。
> - PRD 不写具体 DB 表结构 / API 路径（放 plans/task 卡）
> - PRD 可写必要技术约束
> - UI/UX 只写页面结构 / 信息优先级 / 流程 / 状态，**不写视觉参数**
>
> **维护**：Tim + Claude 协作。版本 **v0.1**（首版 / 待 spec 双审）。
>
> **上游路线图**：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md`（模块 A = 本 Sprint）。

---

## 0. Sprint 9 north star

**1 主轴**：让用户**第一次进 velo 就被服务到** —— 不用自己查"什么是 FTP / 怎么测"+ 不用研究专业训练术语，系统帮新用户估 FTP / 加上一套量化训练效果的数字（NP / IF / TSS）/ 让"我今天到底有多累 / 这一年到底变强了多少"看得见。

**8 个子任务**：

- **后端 task-1**：DB 字段扩展（`activities.snapshot_ftp` + `activities.intensity_factor` + `activities.tss` + Alembic 迁移）
- **后端 task-2**：worker 写 `snapshot_ftp` + 算 IF/TSS（FIT/Strava 已有 NP / GPX 路径 NP 为 NULL 时 IF/TSS 自然 NULL）
- **后端 task-3**：一次性 baseline 同步 + detail 显示 snapshot_ftp（"按 FTP 220W 算"小字透明化）
- **后端 task-4**：用户首次填 ftp 触发回填（PUT /api/user/profile 检测 ftp NULL → 有值 → enqueue 该用户所有 snapshot_ftp=NULL 活动回填）
- **后端 task-5**：CP 3-param + 心率加权 eFTP 估算器（`app/activity/ftp_estimator.py` / scipy curve_fit 拟合）
- **前端 task-6**：profile 加体重输入 + 首次填 ftp 系统估算弹窗（"我估算你 ftp 220W / 用这个？"）
- **前端 task-7**：详情页加 W/kg / NP / IF / TSS 显示卡
- **后端+前端 task-8**：Breakthrough 自动检测 + 弹窗（新活动解析后调 estimator / 超过当前 ftp × 1.05 → 弹窗提示更新）

**预估工期**：**10 天**（最复杂的一期 / 含 snapshot_ftp 地基架构 + 三审 + 真用回归）。

**前置依赖**：
- ✅ Sprint 8 已 ship（max_cadence + power_zones 回填完工）
- ✅ Sprint 8 commit `11cd81f` 跑过的回填脚本数据可复用

**Sprint 范围外（明确延后）**：

- **训练负荷曲线 PMC（CTL/ATL/TSB）** → Sprint 10（计算 + 训练日历页 + 状态评分）
- **训练分布饼图分析** → Sprint 11（Polarized / Pyramidal / Sweet Spot 自动分类 + 建议）
- **每日推荐 = LLM 教练总结** → Sprint 12（**LLM 版** / DeepSeek 4 段卡片 / 早上 6 点 cron + 用户手动刷新 / 详见 `docs/superpowers/specs/2026-05-20-coach-engine-design.md`）
- **HRV / 健康监测接入** → **永久不做**（research 实证 velo 永远拿不到 / 微信小程序限制 + 硬件壁垒 / 详见 coach-engine §6.2）
- **GPX 路径补 NP 算法**（30 秒移动平均 4 次方再开方）→ Sprint 9 不做 / GPX 用户 IF/TSS 保持 NULL
- **hrTSS 兜底**（GPX 无 NP 用心率 + LTHR 算 TSS）→ Sprint 12 coach-engine 内部用 / **不回填 activity.tss 字段**（coach-engine 是运行时算 / 不是 Sprint 9 字段补全）
- **教练-运动员协作 / 训练计划编辑器** → 永不做（B 端工具 / 不在 velo 范围）
- **设备 ANT+ / 功率计校准** → 永不做（硬件赛道）
- **Persona Engine（老登便利贴）已砍** → 整目录晾着不删 / 详见 memory `feedback_decoration_vs_guidance_velo_persona_lesson.md`

---

## 0.1 真实代码事实表（grep 实证 / spec subagent 起手必读）

> sprint-6-prd.md §0.1 同模板 / 所有 [file:line] 已亲 Read 实证。
> spec subagent 实施前必须重新 grep 验证一遍（防 stale / 见 memory `feedback_phase5_task_card_grep_stale.md`）。

### User 字段（`app/user/models.py:42-119`）

| 字段 | 真值 | 注 |
|---|---|---|
| ftp | Integer / nullable | [models.py:51] |
| **weight** | **Float / nullable / 已存在** ✓ | [models.py:54] ⚠️ task-1 不用新加 / 直接用 |
| bike_type | String(20) / nullable | [models.py:57] |
| weekly_goal | Float / server_default "200.0" | [models.py:62] |
| nickname / avatar_url | 已有 | - |
| city / mute_notifications / is_admin | 已有 | - |

**Schema**：`UserProfileUpdate.ftp` Field(None, **ge=50, le=500**) [`app/user/schemas.py:111`]

### Activity 字段（`app/activity/models.py:42-164`）

| 字段 | 真值 | 注 |
|---|---|---|
| distance / duration / moving_time | ✓ 已有 | - |
| avg_power / max_power / avg_hr / max_hr / avg_cadence / max_cadence | ✓ 已有 | max_cadence = Sprint 8 task-1.1 加 |
| **normalized_power** | Float / nullable / **GPX = NULL** | [stats_calculator.py:128] GPX 算不出 / FIT/Strava 有 |
| power_zones | JSONB / nullable | Sprint 8 task-1.4 回填后 182 条有数据 |
| **calories** | Float / nullable / GPX 用 `avg_power × duration × 0.25` 估算 | [stats_calculator.py:226] |
| **snapshot_ftp** | **本 task-1 新加 / Integer / nullable** | 跟 user.ftp 同类型 Integer / 永久快照 |
| **intensity_factor** | **本 task-1 新加 / Float / nullable** | IF = NP / FTP |
| **tss** | **本 task-1 新加 / Float / nullable** | TSS = (秒 × NP × IF) / (FTP × 3600) × 100 |

### Endpoint（`app/user/router.py:83`）

`PUT /api/user/profile` → `update_profile()` / 接 `UserProfileUpdate` schema（含 ftp / weight / bike_type / weekly_goal / nickname / avatar_url）。**当前没有"首次填 ftp 触发回填"逻辑** / 本 task-4 加。

### 三路 parser 现状（NP 来源）

| 路径 | NP 实证 | task-2 影响 |
|------|---------|-------------|
| **GPX** (`app/parsing/stats_calculator.py:128`) | `normalized_power=None` ← GPX 无法算 NP | IF/TSS 自然 NULL / 前端整块隐藏 |
| **FIT** (`app/parsing/fit_parser.py:319`) | `normalized_power = _safe_get_int(session, "normalized_power")` ← FIT session 自带 | IF/TSS 能算 |
| **Strava** (`app/parsing/strava_adapter.py:189`) | `normalized_power=detail.get("weighted_average_watts") if has_sensors else None` ← Strava API 自带 | IF/TSS 能算 |

### power_zones 算法（`app/activity/power_zones.py`）

- `calculate_power_zones(trackpoints: list[dict], ftp: int)` → 返 list[dict] / 6 区间分布
- L47 守卫：`if len(trackpoints) < 2 or ftp <= 0: return None`
- **Sprint 8 task-1.4 实证**：调用前 `tp_dicts = [{"power": tp.power, "time": tp.timestamp} for tp in tps]`（[backfill 脚本 L114]）

### 当前生产 DB 状态（Sprint 8 task-1.4 跑完后）

- 用户 id=2 (Tim) ftp=220 / 295 条 completed cycling 活动
- 184 条 max_cadence 有值 / 182 条 power_zones 有值 / 其余 trackpoints 无传感器数据
- **295 条 snapshot_ftp 全 NULL** / 本 Sprint task-3 一次性同步全设为 user.ftp=220

---

## 1. 子任务 task-1：DB 字段扩展 + Alembic 迁移

### 1.1 用户目标
让 IF / TSS / snapshot_ftp 三个核心训练数字有地方存。

### 1.2 使用场景
spec subagent 起手第一个 task / 没有任何字段就什么都做不了。

### 1.3 功能范围
- `activities` 表加 3 列：`snapshot_ftp` **Integer** nullable / `intensity_factor` Float nullable / `tss` Float nullable
  - snapshot_ftp 跟 user.ftp 同类型 Integer（防 220 vs 220.0 类型不一致 / reviewer-spec Critical 4）
- Alembic 迁移 `sprint9_training_metrics.py`
- down_revision = `sprint8_max_cadence`（当前 head）
- **requirements.txt 加 `scipy>=1.11`**（task-5 ftp_estimator 用 scipy.optimize.curve_fit / 不加上线就 ImportError）

### 1.4 用户流程
（无 / 纯后端字段）

### 1.5 页面&状态
（无 / 纯后端字段）

### 1.6 数据需求
- 字段类型：snapshot_ftp 跟 user.ftp 同 Integer / intensity_factor + tss 是 Float（小数有意义）
- nullable=True：老活动允许 NULL / 前端 wx:if 隐藏

### 1.7 异常情况
- 迁移失败：alembic 回滚 / 重跑

### 1.8 验收标准
- `alembic upgrade head` 跑过 / `\d activities` 看到 3 个新字段
- `alembic downgrade -1` 能回滚
- docker rebuild api + worker 后 `python -c "from scipy.optimize import curve_fit"` 不 ImportError

### 1.9 不做项
- 不动 user 表（weight 已有）
- 不加 snapshot_ftp 自动写入逻辑（task-2 做）

**来源**：路线图 §1 模块 A / Tim 拍快照式 ftp。

---

## 2. 子任务 task-2：worker 写 snapshot_ftp + 算 IF/TSS

### 2.1 用户目标
每次新解析活动时把当时 ftp 永久锁定在该活动 / 同时算出 IF/TSS。

### 2.2 使用场景
- 用户从 Strava 同步新活动 → worker_strava 路径
- 用户上传 GPX/FIT → worker.py 路径
- 都在 `save_parse_result()` 统一写入

### 2.3 功能范围
- **改 `save_parse_result(db, activity, result)` 函数签名加 `user` 参数 → `save_parse_result(db, activity, result, user)`**
- **3 个调用方全部同步改**（reviewer 三轮抓到 / 真实代码 grep 实证）：
  - `app/activity/worker.py:277`（GPX/FIT 实时上传路径 / worker.py:253 已查过 user / 直接传）
  - `app/strava/worker_strava.py:233`（Strava webhook 实时同步路径 / 同位置已有 user）
  - `app/strava/import_scheduler.py:507`（Strava **历史批量导入**路径 / import_scheduler.py:502 已有 user / 不传会让用户绑定 Strava 时拉的历史 200 条全部 snapshot_ftp NULL = 关键 bug）
- 函数内部加 3 行：
  - `activity.snapshot_ftp = user.ftp` (该用户当前 ftp / 可能为 None)
  - 算 `intensity_factor` 和 `tss`（需 NP + snapshot_ftp 都不为 None + duration > 0 / 任一缺失或 0 则 NULL）
- IF 公式：`NP / snapshot_ftp`（round 3 位）
- TSS 公式：`(duration_seconds × NP × IF) / (snapshot_ftp × 3600) × 100`（round 1 位）
- 共享逻辑：抽 helper `calculate_intensity_metrics(np, ftp, duration_seconds)` → 返 (if, tss) / 或 (None, None)
  - helper 内部第一行守卫：`if np is None or not ftp or not duration_seconds: return (None, None)`（防 0 / 防 None）

### 2.4 用户流程
（无 / 纯后端写入）

### 2.5 页面&状态
（无 / 纯后端写入）

### 2.6 数据需求
- 输入：`activity.normalized_power` + `user.ftp` + `activity.duration`
- 输出：`activity.snapshot_ftp` + `activity.intensity_factor` + `activity.tss`
- GPX 路径 NP = None → IF/TSS 自然 None（不报错）

### 2.7 异常情况
- user.ftp 为 None（新用户没填）→ snapshot_ftp = None / IF/TSS 也 None
- NP 为 None（GPX 路径）→ IF/TSS None
- duration 为 0 → IF/TSS None（防除零）

### 2.8 验收标准
- 新上传 GPX 活动（worker.py 路径）：snapshot_ftp = user.ftp（如有）/ IF/TSS = None
- 新同步 Strava 活动（worker_strava.py webhook 路径）：三个字段全有值（如 user.ftp 有）
- **历史批量导入活动（import_scheduler.py 路径）：snapshot_ftp = user.ftp 也应有值**（reviewer 抓到的真用回归 hot spot / 用户绑定 Strava 时拉的 200 条历史活动走这条路）
- pytest 单元测试覆盖 4 种情况（FIT 有 NP / Strava 有 NP / GPX 无 NP / 用户无 ftp）

### 2.9 不做项
- 不补 GPX 路径 NP 算法（推迟）
- 不动 dedupe / 不动 ActivitySummary list 返回（IF/TSS 不返列表 / 只 detail）

**来源**：路线图 §1 模块 A / Tim 拍快照式 + IF/TSS。

---

## 3. 子任务 task-3：一次性 baseline 同步 + detail 显示 snapshot_ftp

### 3.1 用户目标
让 Sprint 8 跑完的 182 条 power_zones 有"按 FTP 220W 算"的明确锚点 / 详情页透明化。

### 3.2 使用场景
- spec subagent 部署 task-1 迁移后 / 立刻跑一次性 SQL 同步
- 用户打开任何带 power_zones 的老活动 → 看到功率区间块上方"按 FTP 220W 算"小字

### 3.3 功能范围
- 一次性 SQL（写进 task-3 部署步骤 / 不进迁移文件 / **两条 SQL 必须同一事务 BEGIN ... COMMIT 包起来顺序跑** / 否则第二条读不到第一条结果会扫到空集跳过）：
  ```sql
  UPDATE activities
  SET snapshot_ftp = (SELECT ftp FROM users WHERE id = activities.user_id)
  WHERE power_zones IS NOT NULL AND snapshot_ftp IS NULL;
  ```
- 同时同步 IF/TSS（如该活动 NP 不为 NULL）：
  ```sql
  UPDATE activities
  SET intensity_factor = ROUND((normalized_power::numeric / snapshot_ftp), 3),
      tss = ROUND((duration::numeric * normalized_power * (normalized_power::numeric / snapshot_ftp)) / (snapshot_ftp * 3600) * 100, 1)
  WHERE snapshot_ftp IS NOT NULL AND normalized_power IS NOT NULL AND duration > 0 AND tss IS NULL;
  ```
- detail.wxml 功率区间块上方加一行小字 `<text class="zones-meta">按 FTP {{activity.snapshot_ftp}}W 算</text>`
- ActivityDetail schema 加 `snapshot_ftp: Optional[int]`（跟 DB Integer 一致 / 前端显示 `220W` 不是 `220.0W`）

### 3.4 用户流程
1. 你打开 Evening Ride (id=422) 详情页 → 滚动到"功率区间分布"块
2. 看到 ZZ1-ZZ6 横条上面一行灰色小字"按 FTP 220W 算"
3. 心里清楚这条活动的区间锚点

### 3.5 页面&状态
- detail.wxml `.zones` 块内 / `.zones-label` 上方加 `.zones-meta`
- 文案：`按 FTP {{snapshot_ftp}}W 算`
- 字体：灰色 24rpx 小字 / 跟 `.zones-label` 对齐
- snapshot_ftp 为 NULL 时整段 wx:if 隐藏（按永久规则不显示 -）

### 3.6 数据需求
- 输入：`activity.snapshot_ftp`（task-1 字段 + 本 task SQL 同步）
- 输出：detail wxml 渲染

### 3.7 异常情况
- snapshot_ftp 仍 NULL（用户 ftp 为 NULL）→ 小字整段隐藏
- SQL 同步失败：手动跑 SQL / 不阻塞部署

### 3.8 验收标准
- 部署 task-3 后跑 `SELECT COUNT(*) FROM activities WHERE power_zones IS NOT NULL AND snapshot_ftp IS NULL` = 0
- 详情页打开 Evening Ride 看到"按 FTP 220W 算"小字
- 用户 ftp NULL 时活动详情页不显示该小字

### 3.9 不做项
- 不在迁移文件里跑 UPDATE（迁移只 add column / SQL 单独跑）
- 不显示"FTP 已变化 / 当前 240W"等差异提示（Sprint 9 不做）

**来源**：路线图 §1 模块 A / Tim 拍"详情页透明化"。

---

## 4. 子任务 task-4：用户首次填 ftp 触发回填

### 4.1 用户目标
新用户先骑后填 ftp 时 / 系统自动给历史活动补 snapshot_ftp + power_zones + IF/TSS / 用户不需要手动重处理。

### 4.2 使用场景
- 张三注册账号 / 没填 ftp / 上传 5 条 GPX → 这 5 条 snapshot_ftp = NULL
- 张三进设置页填 ftp = 220
- 系统自动回填这 5 条活动 + 重算 power_zones / IF / TSS
- 张三回详情页看 → 5 条活动全部能看到功率区间 + IF/TSS

### 4.3 功能范围
- `app/user/router.py update_profile()` 加：
  - 拿旧 ftp 跟新 ftp 比对
  - **首次填**（旧 NULL / 新有值）→ enqueue 回填任务（RQ）
  - **改 ftp**（旧有值 / 新有值不同）→ **不动历史**（快照式）
  - 清 ftp（旧有值 / 新 NULL）→ 不动历史 + 不报错
- 新建 `app/activity/backfill_ftp.py` 含 `backfill_user_snapshot_ftp(user_id, new_ftp)` 函数：
  - 扫该用户所有 `snapshot_ftp IS NULL AND status='completed' AND activity_type='cycling'` 活动
  - 每条：写 snapshot_ftp = new_ftp / 调 `calculate_power_zones` / 算 IF/TSS
  - **共享逻辑**：算 IF/TSS 必须 `from app.activity.worker import calculate_intensity_metrics`（task-2 抽的 helper）/ 不在 backfill 重复实现 / 防止两套逻辑漂移
- RQ 任务队列：`enqueue_backfill_ftp(user_id, new_ftp)` 异步跑 / 不阻塞 PUT 请求

### 4.4 用户流程
1. 张三注册 / 上传 5 条 GPX 解析完 / 打开任何详情页 → 没有功率区间块（snapshot_ftp NULL → 整块隐藏）
2. 张三进设置 → 填 ftp = 220 → 提交
3. PUT endpoint 返 200 / 后台 RQ 任务跑（5 条 × 几百毫秒 = 几秒）
4. 张三 30 秒后回详情页 → 5 条全部显示功率区间块（按 220 算）

### 4.5 页面&状态
- profile 页 ftp 输入字段（已有 / 不动）
- 提交后 toast "FTP 已保存 / 正在计算历史活动 (1-2 分钟)"
- 不显示进度条（异步 RQ / 用户可以离开页面）

### 4.6 数据需求
- 输入：PUT 请求里的新 ftp
- 比对：DB 里旧 user.ftp
- 输出：RQ enqueue / DB 异步更新

### 4.7 异常情况
- 用户 30 秒内连续改两次 ftp（先填 220 / 立刻改 240）：
  - 首次填 220 → enqueue 回填 220
  - 改成 240 → **不触发新回填**（快照式 / 改 ftp 不动历史）
  - 历史活动 snapshot_ftp = 220（首次填那一刻锁定 / 不被后续 ftp 更新覆盖）
- 用户有 1000 条历史活动：回填可能跑 10+ 分钟 → RQ 默认 timeout 5 min 不够 → 加 `job_timeout=1800`
- RQ 任务失败：log + 用户下次进 profile 看到"历史活动回填失败 / 联系客服"toast（暂不实现 / 看真用情况）

### 4.8 验收标准
- pytest 覆盖 4 个场景：首次填 / 改 ftp / 清 ftp / 同值改写
- 真用回归：新建测试账号 / 上传 1 条 GPX / 填 ftp / 30 秒后看详情页有功率区间块
- DB 校验：该用户所有 completed 活动 snapshot_ftp 都等于首次填的 ftp 值

### 4.9 不做项
- 不做"用户改 ftp 时弹窗问要不要回填最近 N 条"（escape hatch / Sprint 10 后视情况加）
- 不做"实时回填进度条"（用户不需要这个细节）
- 不做"回填失败重试机制"（RQ 默认 3 次 / 够用）

**来源**：路线图 §1 模块 A / Tim 拍"首次填 ftp 触发回填 / 之后改 ftp 不影响历史"。

---

## 5. 子任务 task-5：CP 3-param + 心率加权 eFTP 估算器

### 5.1 用户目标
新用户不用查"什么是 FTP / 怎么测" / 系统看几条历史活动就估个值出来。

### 5.2 使用场景
- 张三注册账号 / 同步 Strava 拉进来 200 条历史活动
- 张三进设置页准备填 ftp / 看到"系统估算你 ftp ≈ 220W / 用这个 / 还是手动填"
- 张三点"用这个" → ftp 设为 220 → 触发 task-4 回填

### 5.3 功能范围
- 新文件 `app/activity/ftp_estimator.py`：
  - `estimate_ftp_for_user(db, user_id) → EstimationResult` 主入口
  - 内部步骤：
    1. 扫该用户最近 6 个月 completed cycling 活动 + trackpoints
    2. 提取 best 3/5/10/20/60 分钟 power（滑动窗口 / 5 个数据点）
    3. **心率加权**：每个 best 段算 Pa:HR 漂移（前后半段 power/HR 比 变化）/ 漂移 < 5% 权重 1.0 / > 10% 权重 0.5
    4. 用 scipy.optimize.curve_fit 拟合 CP 3-param 公式：`t = W'/(P-CP) + W'/(P_max-CP)`（Morton 1996 标准公式 / 第二项分母是 P_max-CP / 不是 CP-Pmax / reviewer 抓到 cyclingtools R 包文档可能 typo / 实现前再核对 Morton 1996 原始论文 PMID 8854981）
    5. 返回 `EstimationResult(ftp: int, confidence: 'high'/'medium'/'low'/'insufficient', method: 'cp3_hr_weighted', r2: float)`
- `EstimationResult` 字段：
  - `ftp`：估算 ftp 整数（CP 渐近线四舍五入）
  - `confidence`：4 档（high R²>0.95 / medium R²>0.85 / low R²>0.75 / insufficient 数据不足）
  - `method`：算法名（未来扩展可改 ML）
  - `r2`：拟合质量（给前端展示"用 200 条活动 R²=0.98 拟合"）
- 单元测试覆盖：5 个 best efforts → 拟合 → CP ≈ 已知 ftp ±5%（用模拟数据）

### 5.4 用户流程
（无 / 纯算法 / task-6 调用）

### 5.5 页面&状态
（无 / 纯算法 / task-6 调用）

### 5.6 数据需求
- 输入：user_id / db session
- 内部查询：6 个月 completed activities 的 trackpoints（power + time + hr）
- 输出：EstimationResult dataclass

### 5.7 异常情况
- 用户 0 条活动 → 返 `confidence='insufficient'` / ftp=None
- 用户都是 < 3 分钟的短骑 → 滑动窗口拿不到 3 分钟段 → insufficient
- 拟合失败（scipy curve_fit RuntimeError）→ try/except → insufficient
- 用户没心率数据（trackpoints.hr 全 NULL）→ 退化为不加权的 CP 3-param / method='cp3_no_hr'

### 5.8 验收标准
- pytest 模拟 5 个已知 best efforts 数据 → 拟合出 CP ≈ 设定值 ±5%
- pytest 模拟边界情况（数据不足 / 拟合失败 / 无心率）→ 正确返 insufficient
- 真用回归：在你账号上跑一次 estimate / 看返回值是否在 200-240W 区间（你真实 ftp 220）

### 5.9 不做项
- 不做"AI/ML 模型"（22000 用户 9 个月才出 / 我们没数据）
- 不做"用 NP 估算"（Strautomator 用 / 准确性不如 CP 3-param）
- 不做"实时秒级 MPA"（Xert 设备端能力 / 我们 App 不做）

**来源**：路线图 §1 模块 A / Tim 拍"CP 3-param + 心率加权 / 信息茧房之外的真发现"。

---

## 6. 子任务 task-6：profile 体重输入 + 首次填 ftp 系统估算弹窗

### 6.1 用户目标
新用户进 profile 填 ftp 时 / 系统主动给个建议值 + 顺便填体重。

### 6.2 使用场景
- 张三注册账号 / 同步 Strava → 进 profile 设置
- profile 看到"FTP"字段为空 → 点编辑
- 弹窗（如有数据估出）："我们看了你最近的活动 / 估算 ftp ≈ 220W（高置信度 / 200 条活动拟合 R²=0.98）/ 用这个？/ 或手动填"
- 张三点"用这个" → 自动填入 220 → 提交 → 触发 task-4 回填
- 同弹窗下面提示"还差体重就能算 W/kg" → 体重输入框

### 6.3 功能范围
- profile 页 ftp 字段加"系统估算"按钮（前端）
- 点按钮调新 endpoint `GET /api/user/me/ftp-estimate` → 返 EstimationResult
- 弹窗组件：显示估算值 + 置信度 + 拟合 R² + 两个按钮（用这个 / 手动填）
- profile 页加 weight 字段输入（kg / Float / ge=30 le=200）
- weight 跟 ftp 一起在 PUT /api/user/profile 提交（schema 已有）

### 6.4 用户流程
1. 张三进 profile → FTP 字段空 → 点"编辑"
2. 看到两个按钮："让系统估算" / "手动填"
3. 点"让系统估算" → loading 2-3 秒 → 弹窗
4. 弹窗显示"我们估算你 ftp 220W / 高置信度（R²=0.98 / 200 条活动）" + "用这个 220W" / "我手动填"
5. 点"用这个" → ftp 自动填 220 → profile 表单 ftp 字段已填
6. 同弹窗下方"还想加体重？(可选 / 算 W/kg 用)" → 输入 70
7. 点"保存" → PUT /api/user/profile → 后台触发回填

### 6.5 页面&状态
- ftp 字段：编辑按钮 / "让系统估算"按钮
- 估算 loading 状态：转圈 2-3 秒（estimator 跑时间）
- 弹窗：
  - confidence='high'：绿色置信度 + "用这个" 突出
  - confidence='medium'：黄色 + "用这个" + "我手动填" 平权
  - confidence='low'：橙色 + "我手动填" 突出 + "用这个" 次要
  - confidence='insufficient'：弹窗不出现 / 直接让用户手动填
- weight 输入框：可选 / placeholder "70.0 kg"

### 6.6 数据需求
- 输入：用户点"让系统估算"按钮
- 后端：调 estimate_ftp_for_user → 返 EstimationResult
- 前端：渲染弹窗 + 保存到 ftp 字段

### 6.7 异常情况
- 估算 confidence='insufficient'：弹窗不出现 / 提示"历史活动不够 / 请手动填"
- 估算 endpoint 500：toast "估算失败 / 请手动填"
- 用户点"用这个" 又改：手动输入覆盖估算值（前端校验 50-500）
- 体重为空：提交 OK（可选字段）

### 6.8 验收标准
- 真用回归：你账号 estimate → 弹窗应显示 ftp ≈ 220 / confidence=high
- 测试账号新建（无活动）→ 点"让系统估算" → 应不弹窗 / 直接让手动填
- weight 输入 / 保存 / DB 校验 user.weight 已写入

### 6.9 不做项
- 不做"年龄 / 性别 / 训练年龄"等额外档案字段（增加输入负担）
- 不做"每月 / 每季度自动 re-estimate ftp"（任由用户手动触发）
- 不做"估算原理详解"页面（弹窗里一行说明够用）

**来源**：路线图 §1 模块 A / Tim 拍"首次填 ftp 弹窗 + 体重输入"。

---

## 7. 子任务 task-7：详情页 W/kg + NP / IF / TSS 显示卡

### 7.1 用户目标
用户在详情页看到自己这次骑的科学量化数字 / 不只是平均功率。

### 7.2 使用场景
- 张三骑完今天间歇训练 / 打开 velo 详情页
- 看到"功率"卡片：平均 200W / 最大 450W / **W/kg 2.86** / **NP 215W** / **IF 0.98** / **TSS 95**
- 心里清楚这次骑得有多用力

### 7.3 功能范围
- detail.wxml 现有"功率"卡片增强：
  - 已有：平均功率 / 最大功率 / 卡路里
  - 加：**W/kg**（**后端 detail endpoint service 算好返 / 不在前端算**：拉 user.weight + activity.avg_power → 算 `avg_power / weight` round 2 位 → 通过新加 schema 字段 `power_per_kg` 返）
  - 加：**NP**（normalized_power / ActivityDetail schema 已有 / 不动）
  - 加：**IF**（intensity_factor / ActivityDetail schema 加字段）
  - 加：**TSS**（tss / ActivityDetail schema 加字段）
- ActivityDetail schema 加 3 字段：`power_per_kg: Optional[float]` + `intensity_factor: Optional[float]` + `tss: Optional[float]`（snapshot_ftp 已在 task-3 加）
- 4 个字段都 wx:if 防 NULL（无 weight → 隐藏 W/kg / 无 NP → 隐藏 NP+IF+TSS）
- detail.js 加各字段取整逻辑（W/kg 保 2 位小数 / 其他取整）

### 7.4 用户流程
1. 张三打开 Evening Ride (id=422) 详情页
2. 滚到"功率"卡片
3. 看到：平均 98W / 最大 474W / **W/kg 1.4**（98/70）/ **NP 110W** / **IF 0.5** / **TSS 45**
4. 心想"今天 IF 0.5 / 是个轻松恢复骑 / TSS 45 / 跟之前差不多累"

### 7.5 页面&状态
- 详情页"功率"卡片 metric-row 加 4 行（W/kg / NP / IF / TSS）
- 每行 wx:if="{{字段}}" 整块隐藏 NULL
- 字体：跟"平均功率 / 最大功率"同款 metric-row 样式
- 顺序：平均功率 → 最大功率 → W/kg → 卡路里 → NP → IF → TSS

### 7.6 数据需求
- 输入：ActivityDetail schema 返回的字段
- 输出：detail.wxml 渲染

### 7.7 异常情况
- W/kg：user.weight 为 NULL → 整行隐藏
- NP/IF/TSS：activity.normalized_power 为 NULL（GPX 路径）→ 3 行全隐藏
- 极端值：IF > 1.5（数据脏）→ 显示原值不裁剪（用户能看出异常 / 不当机）

### 7.8 验收标准
- Evening Ride (id=422) 详情页：W/kg / NP / IF / TSS 全显示
- 早期 GPX 活动（id=35）：NP 缺失 → IF/TSS 行整块隐藏
- 你没填 weight 时：W/kg 行整块隐藏

### 7.9 不做项
- 不做"NP/IF/TSS 含义点击解释"小程序内 wiki（Sprint 10 可加）
- 不做"跟同档骑友 IF/TSS 对比"（Sprint 11/12 训练分布做）

**来源**：路线图 §1 模块 A / Tim 拍"W/kg 显示 + NP/IF/TSS 详情卡"。

---

## 8. 子任务 task-8：Breakthrough 自动检测 + 弹窗

### 8.1 用户目标
用户骑出超过当前 ftp 预估的段 → 系统主动检测并提示更新 ftp / 不需要用户自己手动重测。

### 8.2 使用场景
- 张三 ftp=220 已经用了 2 个月
- 张三今天跟车跟得猛 / 拉了 15 分钟全力 280W
- 系统解析完活动 → estimate_ftp_for_user 算出新 eFTP=232W → 比当前 ftp×1.05=231 高
- 张三打开 velo → 通知中心 / 或下次进 profile → 弹窗"我们检测到你今天活动突破了 / 估算新 ftp=232W / 更新？"
- 张三点"更新" → user.ftp = 232（注意：**只动 user.ftp / 不动历史 snapshot_ftp**）

### 8.3 功能范围
- `save_parse_result()` 完成后调 `detect_breakthrough(db, user, activity)`（共享函数 / GPX/FIT/Strava 三路覆盖）
- 函数逻辑（按 Tim brainstorm 共识 / 单层 1.05 阈值 / 无预过滤）：
  - 拿当前 user.ftp（如为 None → 跳过）
  - 调 estimate_ftp_for_user(db, user_id) 算新 eFTP
  - 如新 eFTP > user.ftp × **1.05** → 写 `BreakthroughEvent` 表（新表）
  - 性能担忧：estimator 每条新活动跑一次 / 单次耗时 < 3 秒（task-5 §5.7 约束）/ 实测真慢再加缓存或预过滤（Sprint 9 后视情况）
- `breakthrough_events` 新表（小表）：
  - id / user_id / activity_id / detected_at / old_ftp / suggested_ftp / status (pending / accepted / rejected / expired)
  - **另建 Alembic 迁移文件** `sprint9_breakthrough_events.py` / down_revision = `sprint9_training_metrics`（task-1 迁移）/ 不要合并到 task-1 迁移文件 / downgrade 边界清晰
- endpoint `GET /api/user/me/breakthroughs?status=pending` → 返 list
- endpoint `PATCH /api/user/me/breakthroughs/:id` → status=accepted/rejected
  - accepted → user.ftp = suggested_ftp（但**不触发 task-4 回填** / 只动当前 ftp）
  - rejected → 仅改 status
- 前端 profile 页打开时调 GET endpoint 检查 pending breakthrough → 有则弹窗

### 8.4 用户流程
1. 张三周二跟车 280W 跑 15 分钟（突破活动）
2. velo 后台静默检测 + 写入 BreakthroughEvent (status=pending)
3. 周三早上张三打开 velo → 进 profile 页
4. profile.js 调 GET /breakthroughs?status=pending → 返 1 条
5. 弹窗"恭喜！我们检测到你周二骑出了突破 / 当前 ftp 220 / 系统估算新 ftp 232 / 更新？"
6. 张三点"更新" → user.ftp = 232 / 历史 snapshot_ftp 全不动 / 下次新活动按 232 算

### 8.5 页面&状态
- 弹窗组件：可复用 task-6 的 ftp 确认弹窗（不同文案）
- 文案对照 Persona 宪法 / 不夸张
- 弹窗按钮："更新 ftp" / "暂不更新" / "再也别提这个"（rejected 永久标记）

### 8.6 数据需求
- 输入：activity（含 NP / trackpoints）+ user.ftp
- 内部：调 estimate_ftp_for_user + 写 BreakthroughEvent
- 输出：profile 页弹窗

### 8.7 异常情况
- 用户从来不进 profile：BreakthroughEvent 永远 pending → 加 `expires_at = detected_at + 7 days` / 过期自动 status=expired
- 用户连续 3 天骑出新突破：detect 函数加防抖（7 天内 pending 已有 → 用最新覆盖 / 不重复弹）
- detect_breakthrough 失败：log + 不影响 save_parse_result 主流程（用 try/except 隔离）

### 8.8 验收标准
- pytest 覆盖：单次突破 / 连续 3 天突破 / 用户 rejected / 7 天过期
- 真用回归：你账号造一条 NP 远超 230 的活动 → 应触发 BreakthroughEvent
- DB 校验：breakthrough_events 表 status 流转正确

### 8.9 不做项
- 不做"自动更新 ftp 不询问用户"（用户必须确认 / 保持掌控感）
- 不做"突破时立刻 push 通知"（小程序无 push / 改进 profile 弹窗即可）
- 不做"突破历史时间线"页面（Sprint 10 后看用户反馈）

**来源**：路线图 §1 模块 A / Tim 拍"Xert 风格 Breakthrough"。

---

## 9. 跨子任务约束

### 9.1 弹窗触发频次（防新用户被淹）
按 Sprint 9 风险评估 / 严格限制：
- **首次填 ftp 弹窗**（task-6）：只在用户主动点"让系统估算"时出现 / 不主动弹
- **Breakthrough 弹窗**（task-8）：只在用户进 profile 页时检查 pending / 不在首页 / 详情页等无关位置弹
- **体重输入**（task-6）：跟 ftp 弹窗同一个 / 不单独弹

### 9.2 性能约束
- estimate_ftp_for_user 调用：< 3 秒返回（200 条活动 + scipy 拟合）
- task-4 RQ 回填：< 5 分钟（1000 条活动上限）
- detail 页加载：不能因为新加 4 个字段慢 > 100ms

### 9.3 兜底
- estimate_ftp_for_user 拟合失败：confidence='insufficient' / 让用户手动填
- task-4 RQ 失败：log + 静默 / 用户下次进设置可手动重触发
- task-8 detect_breakthrough 失败：try/except / 不影响活动 ship

---

## 来源追溯

- 上游：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md` 模块 A
- Tim 拍板（2026-05-20）：
  - 快照式 ftp（每条活动 snapshot_ftp 永久锁定）
  - CP 3-param + 心率加权 eFTP 估算
  - 体重字段 + W/kg 显示
  - Breakthrough 自动检测 + 弹窗确认
  - 首次填 ftp 触发回填 / 之后改 ftp 不动历史
- 算法选型：CP 3-param 公式来源 Morton 1996 / cyclingtools R 包 / 心率加权 = TrainerRoad / Xert 思想
- 工程实证：Sprint 8 task-1.4 backfill_max_cadence_and_power_zones.py 框架可复用
