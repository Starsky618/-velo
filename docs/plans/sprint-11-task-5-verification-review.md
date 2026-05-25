# Sprint 11 Task-5 — 验证、自审、Claude 异源复审

> 所属：Sprint 11（训练分布分析）/ 第 5 个 task / 收口层。
> 前置：Task 2-4 已各自通过验收。
> 范围：跑完整验证、写自审、交给 Claude 异源复审；不新增功能。

---

## ─────── 给 Tim 看 ───────

### 干啥用

确认 Sprint 11 不是“看起来写完了”，而是真的守住了字段、隐私、低耦合和用户体验。

它像盖楼最后验收：不是再往楼里加房间，而是检查电路、水管、防火门、逃生通道都没问题。

### 用户故事

张三打开训练结构页能看到建议；同时老功能不坏：训练负荷页还能打开，上传和 Strava 同步不受影响，别人也不能看到他的功率隐私。

### 怎么算做对了

- ✓ Task 2/3/4 测试全部通过。
- ✓ `/api/training/load` 回归通过。
- ✓ 静态测试确认小程序入口和 endpoint 字符串正确。
- ✓ `git diff --check` 通过。
- ✓ 自审报告逐项核销字段脱敏、42 天上下界、dedupe、可删除边界、`/load` 不破坏。
- ✓ Claude 异源复审 Critical=0。

### 这次不做

- 不加新功能。
- 不临时改阈值。
- 不现场改写 spec §4.1 已确认的 v1 文案。
- 不部署生产，除非 Tim 单独下部署指令。

### 估时

0.5 天。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
git status --short
nl -ba docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md | sed -n '230,250p'
nl -ba docs/plans/sprint-11-training-distribution.md | sed -n '167,176p'
rg -n "raw_zones|min_w|max_w|duplicate_of|start_utc|end_utc|current_description|target_description|training-distribution" app tests miniprogram docs/plans docs/prd docs/superpowers/specs
```

## 2. 完整验证命令

```bash
python3 -m pytest tests/test_training_distribution.py -q
python3 -m pytest tests/test_training_distribution_api.py -q
python3 -m pytest tests/test_training_distribution_static.py tests/test_training_calendar_static.py -q
python3 -m pytest tests/test_training_load_api.py -q
python3 -m pytest tests/test_training_daily_load_hook.py -q
python3 -m json.tool miniprogram/app.json >/tmp/velo-app-json-check.txt
python3 -c "from app.training.distribution import aggregate_power_zones, classify_distribution; print('distribution import ok')"
python3 -c "from app.training.router import router; print(router.prefix)"
git diff --check
```

## 3. 自审核销清单

逐项写“通过 / 未通过 + file:line 证据”：

### 字段与隐私
- `raw_zones` 不含 `min_w/max_w`。
- 响应含 `current_description` / `target_description`。
- `groups` 固定 label/role。
- `week_plan` 是 7 个结构化项。

### 查询与数据
- 查询过滤 `duplicate_of IS NULL`。
- 查询过滤 `status == "completed"`。
- 查询过滤 `activity_type == "cycling"`。
- 查询过滤 `started_at IS NOT NULL`。
- 查询使用 `start_utc` / `end_utc` 双边界。
- SQLite JSON string 的 `power_zones` 测试通过。

### 分类
- `groups` 分母剔除 Z1。
- `raw_zones` 分母含 Z1。
- `total_power_seconds` 含 Z1。
- Z4 `>= 30%` 先命中 `threshold`。
- `sweet_spot` / `polarized` / `pyramidal` / `mixed` 都有测试。

### 可删除边界
- 删除 Sprint 11 训练结构页面/API 部分只需撤 `/distribution` route、新 schema、新 service、新纯函数、新页面、新入口和 Sprint 11 页面/API 专属测试。
- 2026-05-26 后 `miniprogram/utils/power-zones.js` 被活动详情页复用；删除 Sprint 11 时不能直接删这个共享工具，除非活动详情页已不再 import。
- `/api/training/load` 测试继续通过。
- 未改 `app/activity/worker.py` / `app/strava/worker_strava.py` 的 Sprint 10 hook。
- 未改 DB 迁移。

### 小程序
- `training-calendar` 仍注册。
- `training-distribution` 注册在 app.json 末尾。
- profile “训练分析”入口仍存在。
- profile 新增“训练结构”入口。
- 页面不请求 `/api/activities`。

## 4. Claude 异源复审提示词模板

```markdown
请只做 Sprint 11 实现复审，不要继续写代码。

范围：
- Task 2: `app/training/distribution.py`, `tests/test_training_distribution.py`
- Task 3: `app/training/distribution_service.py`, `app/training/schemas.py`, `app/training/router.py`, `tests/test_training_distribution_api.py`
- Task 4: `miniprogram/pages/training-distribution/`, `miniprogram/app.json`, `miniprogram/pages/profile/profile.wxml`, `miniprogram/pages/profile/profile.js`, `tests/test_training_distribution_static.py`, `tests/test_training_calendar_static.py`

重点审：
1. `raw_zones` 是否彻底剔除 `min_w/max_w`。
2. groups 百分比分母是否剔除 Z1，raw_zones 是否含 Z1。
3. `threshold` 是否 Z4 >= 30% 且优先于 sweet_spot。
4. API 是否只读当前用户，并过滤 duplicate/non-cycling/failed/null started_at/null power_zones。
5. `/api/training/load` 是否没有被破坏。
6. Sprint 11 删除边界是否成立。
7. 小程序是否只展示后端文案，不现场脑补 current/target 描述。

请按 Critical / Important / Minor 输出，每条带 file:line。最后给是否建议 commit。
```

## 5. 失败处理

- 任一 pytest 红：先定位到对应 task，不跨 task 大改。
- `/api/training/load` 红：优先检查 router/schema import 是否污染 Sprint 10。
- 静态测试红：先修 app.json/profile/page 字符串，不改后端。
- Claude 复审有 Critical：修完再跑完整命令，不带 Critical commit。

## 6. 5 字段 issue 草稿

背景：Sprint 11 已完成纯函数、API、小程序页面，需要最终证明它能独立上线且不破坏 Sprint 10。目标：跑完整测试、写自审报告、交给 Claude 异源复审。验收命令：完整验证命令全部通过，Claude 复审 Critical=0。不要碰：新功能范围之外的代码、迁移、部署配置、其他 sprint 文档。失败处理：任何 Critical 停在当前 task，修复后重新跑完整验证；3 轮不收敛让 Tim 拍板。

## 7. commit message 模板

`feat(training): sprint11 training distribution`

正文：`Add Sprint 11 training distribution core, API, mini-program page, and tests. Keep module removable, preserve /api/training/load, and enforce privacy-safe raw_zones plus current-user-only distribution data.`

</details>
