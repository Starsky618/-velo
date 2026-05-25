# Sprint 11 训练分布执行拆解

> 来源：`docs/prd/sprint-11-prd.md`
>
> 原型：`docs/prototypes/sprint11-training-distribution-demo.html`
>
> Spec：`docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`
>
> 字段审查：`docs/plans/sprint-11-field-review-handoff.md`
>
> 执行原则：只读 `activities.power_zones`，不改核心表；Sprint 11 可删除，现有训练负荷不受影响。

## 任务图

```text
PRD/字段合同/Claude 审查
  ↓
轻量 spec
  ↓
纯函数 distribution.py
  ↓
API schemas + distribution_service + router
  ↓
小程序 training-distribution 页面 + profile 入口
  ↓
pytest + 静态合同测试 + 自审
```

## 文件范围

### 正式 task 卡

- `docs/plans/sprint-11-task-2-distribution-core.md`
- `docs/plans/sprint-11-task-3-distribution-api.md`
- `docs/plans/sprint-11-task-4-training-distribution-page.md`
- `docs/plans/sprint-11-task-5-verification-review.md`

### 新增

- `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`
- `docs/plans/sprint-11-field-review-handoff.md`
- `docs/plans/sprint-11-task-2-distribution-core.md`
- `docs/plans/sprint-11-task-3-distribution-api.md`
- `docs/plans/sprint-11-task-4-training-distribution-page.md`
- `docs/plans/sprint-11-task-5-verification-review.md`
- `app/training/distribution.py`
- `app/training/distribution_service.py`
- `miniprogram/pages/training-distribution/training-distribution.{wxml,wxss,js,json}`
- `tests/test_training_distribution.py`
- `tests/test_training_distribution_api.py`
- `tests/test_training_distribution_static.py`

### 修改

- `app/training/schemas.py`
- `app/training/router.py`
- `miniprogram/app.json`
- `miniprogram/pages/profile/profile.wxml`
- `miniprogram/pages/profile/profile.js`

## 后端实现合同

### 必须先过的门

- Claude 异源审确认 PRD/spec/plan 的 Critical=0。
- 不允许在审查前写代码实现。
- 发现字段合同和真实代码不一致，先改文档，不临场改代码绕过去。
- `distribution_service.py` 直接 import `app.training.service._today_bj` 和 `_bj_day_start_utc`；不复制北京时间逻辑，不重构 `app/training/service.py`。

### 纯函数输入

`list[list[dict]]`：每条活动一个 `power_zones` 数组。

每个 zone 项至少需要：
- `zone`: `"Z1"` 到 `"Z6"`
- `seconds`: int/float

兼容输入：
- PostgreSQL 真实环境：`power_zones` 是 list。
- SQLite 测试环境：`power_zones` 可能是 JSON string。

### 纯函数输出

- raw Z1-Z6 累计秒数
- 三组页面分布：Z2 / Z3-Z4 / Z5+
- 训练类型：`polarized` / `pyramidal` / `sweet_spot` / `threshold` / `mixed`
- 当前对比卡描述：`current_description`
- 建议方向对比卡描述：`target_description`
- 3 条行动建议
- 7 天示意安排

脱敏要求：
- 输出 `raw_zones` 只允许 `zone/name/seconds/percent`。
- 禁止返回 `min_w/max_w`。

百分比口径：
- `groups[].percent` 和分类判断的分母 = Z2+Z3+Z4+Z5+Z6，剔除 Z1。
- `raw_zones[].percent` 的分母 = Z1+Z2+Z3+Z4+Z5+Z6，沿用现有单条活动口径。
- `total_power_seconds` / `total_power_hours` 含 Z1。
- `threshold` 判定写死为 Z4 单区占比 >= 30%，占比同样剔除 Z1；v1 阈值可调。
- 本接口 `insufficient_power_data` 恒等于 `not data_complete`。
- `groups` 固定三组：`endurance/耐力/打底时间`、`tempo_threshold/中强度/最容易堆累`、`high_intensity/高强度/刺激偏少`。
- `sum(groups[].seconds)` 不等于 `total_power_seconds`，因为 groups 不含 Z1、total 含 Z1。
- `week_plan` 必须返回 7 个 `{day,title,focus}` 结构化项，例如 `{day:"一", title:"Z2", focus:"45 分"}`。

### API 查询过滤

```text
Activity.user_id == 当前用户
Activity.status == "completed"
Activity.activity_type == "cycling"
Activity.duplicate_of IS NULL
Activity.started_at IS NOT NULL
Activity.started_at >= start_utc
Activity.started_at < end_utc
Activity.power_zones IS NOT NULL
```

时间窗口：
- `start_day = 今天北京时间日期 - 41 天`
- `end_day = 今天北京时间日期 + 1 天`
- SQL 必须双边界，不能只写 `>= 最近 42 天`。

### 可删除边界

删除 Sprint 11 时只撤 `/distribution` route、新 schema、新 service、新纯函数、新页面、新入口和 Sprint 11 测试。

不得删除或改坏：
- `/api/training/load`
- `app/training/service.py`
- `app/training/training_load.py`
- `app/training/models.py`
- `daily_training_load`
- GPX / Strava worker 里的 Sprint 10 训练负荷 hook

## 具体任务票

### Task 1：字段合同和 spec 审查

- Goal：让 Claude 能先审“要拿哪些字段、哪些字段不能拿”，再决定是否允许开工。
- Context：读 `docs/prd/sprint-11-prd.md`、本 plan、Sprint 11 spec、字段审查交接。
- Constraints：不改代码实现。
- Done when：Claude 确认 Critical=0；若有 Critical，回到文档修正。
- Fallback：如果 Claude 认为缺正式 `docs/spec-vN.md`，停止实现，让 Tim/Claude 决定是否升级成大 spec。

### Task 2：训练分布纯函数

- Goal：把多条活动的 `power_zones` 翻译成训练结构类型。
- Context：新增 `app/training/distribution.py` 和 `tests/test_training_distribution.py`。
- Constraints：不碰 DB、不 import FastAPI/SQLAlchemy、不返回 `min_w/max_w`。
- Done when：纯函数测试覆盖 Sweet Spot / Polarized / Pyramidal / Threshold / Mixed / 数据不足 / JSON string 输入 / 0 秒边界 / groups 分母剔除 Z1 / raw_zones 分母含 Z1 / Z4 >= 30% 命中 threshold。
- Fallback：分类阈值争议时停在测试，不临时改成新训练学规则。

### Task 3：训练分布 API

- Goal：小程序一次请求拿到完整页面数据。
- Context：新增 `distribution_service.py`，修改 `schemas.py` 和 `router.py`。
- Constraints：只读当前用户；不支持他人 `user_id`；不动 `/load`；直接 import `_today_bj/_bj_day_start_utc`，不复制时间 helper。
- Done when：API 测试覆盖 200 / 401 / 422 / duplicate 过滤 / 非 cycling 过滤 / failed 过滤 / 无 power_zones 过滤 / `raw_zones` 脱敏 / `insufficient_power_data == (not data_complete)` / `current_description` 与 `target_description` 存在 / groups 固定 label-role / week_plan 是 7 个结构化项。
- Fallback：如果 `/load` 测试红，先修 Sprint 11 route/schema 隔离，不改 Sprint 10 行为。

### Task 4：小程序训练结构页

- Goal：用户点 profile 新入口后看到判断、原因和下周行动。
- Context：新增 `miniprogram/pages/training-distribution/`，修改 `app.json` 和 profile。
- Constraints：不复用训练日历页面做业务逻辑；不从活动列表拼数据。
- Done when：页面有 loading / error / 数据不足 / 正常四态；静态测试确认 endpoint 字符串和页面注册。
- Fallback：如果 app.json 末尾测试冲突，更新测试表达为“training-calendar 仍注册，新页面在末尾”。

### Task 5：自审 + Claude 异源审

- Goal：证明实现忠于 spec，没有把新模块焊死到旧系统上。
- Context：跑本 plan 验证命令，写自审报告。
- Constraints：Critical/Important 未处理前不 commit。
- Done when：自审逐项核销字段脱敏、42 天上下界、dedupe、可删除边界、`/load` 不破坏；Claude 复审同意。
- Fallback：3 轮不收敛时停下让 Tim 拍板。

## 验证命令

```bash
pytest tests/test_training_distribution.py tests/test_training_distribution_api.py tests/test_training_distribution_static.py
pytest tests/test_training_load_api.py tests/test_training_calendar_static.py
pytest tests/test_training_daily_load_hook.py
git diff --check
```

## 风险清单

- `power_zones` 在 SQLite 测试里可能是 JSON 字符串：service 层必须兼容 list 和 JSON string。
- Z1 是否计入分类会影响百分比：v1 只把 Z2 / Z3-Z4 / Z5+ 作为核心结构，Z1 放 `raw_zones` 透明返回。
- 功率隐私：本接口只返回当前登录用户自己的训练结构，不提供看他人入口；`raw_zones` 不带 `min_w/max_w`。
- 低耦合：Sprint 11 不新增 `app/activity -> app/training` 依赖；只允许训练模块读取 Activity。
- 测试冲突：新增页面后要同步更新 `tests/test_training_calendar_static.py`，防旧测试误以为 training-calendar 必须永远是最后一页。
- 文案风险：5 类型文案表在 spec §4.1；Tim 已确认其余 4 类草稿先作为 v1 上线，后续根据真实用户反馈再调整。
- 页面数据风险：当前 vs 建议方向两句描述由后端响应字段承载，不让小程序页面现场硬编。
