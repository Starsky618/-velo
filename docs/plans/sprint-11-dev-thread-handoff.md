# Sprint 11 代码开发新线程交接

> 用途：给新线程直接进入 TDD + task 开发。当前线程已完成原型、PRD、spec、plans、tasks、字段审查、异源审和 Tim 拍板；尚未写任何实现代码。

---

## 1. 新线程建议

建议新开线程开发，不建议在旧线程继续写代码。

原因：
- 旧线程已经承载原型、PRD、spec、plans、异源审和多轮修正文档，判断上下文很满。
- Sprint 11 实现要连续执行 Task 2-5，包含后端纯函数、API、小程序和最终复审，适合干净上下文。
- 新线程只需要读本文和正式 task 卡，不需要重放旧讨论。

---

## 2. 当前状态

- PRD：`docs/prd/sprint-11-prd.md`
- Spec：`docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`
- 总 plan：`docs/plans/sprint-11-training-distribution.md`
- 字段审查交接：`docs/plans/sprint-11-field-review-handoff.md`
- Task 2：`docs/plans/sprint-11-task-2-distribution-core.md`
- Task 3：`docs/plans/sprint-11-task-3-distribution-api.md`
- Task 4：`docs/plans/sprint-11-task-4-training-distribution-page.md`
- Task 5：`docs/plans/sprint-11-task-5-verification-review.md`

已拍板：
- 5 类型文案表按 v1 上线，执行 agent 不允许现场改写文案。
- 分类阈值按当前 v1：`threshold = Z4 >= 30%`，优先于 `sweet_spot`。
- 数据不足文案按 spec 固定响应字段。

当前 `git status --short` 应只看到 Sprint 11 文档/原型未跟踪；实现文件还没创建。

---

## 3. 新线程起手必读

```bash
nl -ba docs/plans/sprint-11-training-distribution.md | sed -n '13,195p'
nl -ba docs/plans/sprint-11-task-2-distribution-core.md | sed -n '1,235p'
nl -ba docs/plans/sprint-11-task-3-distribution-api.md | sed -n '1,315p'
nl -ba docs/plans/sprint-11-task-4-training-distribution-page.md | sed -n '1,250p'
nl -ba docs/plans/sprint-11-task-5-verification-review.md | sed -n '1,150p'
nl -ba docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md | sed -n '47,265p'
git status --short
```

---

## 4. 执行顺序

### Task 2：纯函数 + TDD

按 `docs/plans/sprint-11-task-2-distribution-core.md` 执行。

先写测试并确认失败，再实现：
- `tests/test_training_distribution.py`
- `app/training/distribution.py`

验收：

```bash
python3 -m pytest tests/test_training_distribution.py -q
python3 -c "from app.training.distribution import aggregate_power_zones, classify_distribution; print(aggregate_power_zones)"
git diff --check
```

### Task 3：API + TDD

按 `docs/plans/sprint-11-task-3-distribution-api.md` 执行。

先写 API 测试并确认失败，再实现：
- `tests/test_training_distribution_api.py`
- `app/training/distribution_service.py`
- `app/training/schemas.py`
- `app/training/router.py`

关键合同：
- service 查询只读当前用户。
- 过滤 `completed / cycling / duplicate_of IS NULL / started_at IS NOT NULL / 42 天双边界 / power_zones IS NOT NULL`。
- `distribution_service.py` 直接 import `_today_bj` 和 `_bj_day_start_utc`，不复制、不重构 `app/training/service.py`。
- 调用顺序固定：`normalize_power_zones` → `aggregate_power_zones` → `build_training_distribution_payload`。
- `raw_zones` 不返回 `min_w/max_w`。

验收：

```bash
python3 -m pytest tests/test_training_distribution.py tests/test_training_distribution_api.py -q
python3 -m pytest tests/test_training_load_api.py -q
python3 -m pytest tests/test_training_daily_load_hook.py -q
python3 -c "from app.training.router import router; print(router.prefix)"
git diff --check
```

### Task 4：小程序页面 + 静态测试

按 `docs/plans/sprint-11-task-4-training-distribution-page.md` 执行。

先写/改静态测试并确认失败，再实现：
- `tests/test_training_distribution_static.py`
- `tests/test_training_calendar_static.py`
- `miniprogram/pages/training-distribution/training-distribution.{wxml,wxss,js,json}`
- `miniprogram/app.json`
- `miniprogram/pages/profile/profile.wxml`
- `miniprogram/pages/profile/profile.js`

关键合同：
- 页面只请求 `/api/training/distribution`，参数 `{ range: "6w" }`。
- 不从 `/api/activities` 拼数据。
- 不硬编码 5 类型文案，只展示后端 response。
- 保留原“训练分析”入口和 `training-calendar` 页面。

验收：

```bash
python3 -m json.tool miniprogram/app.json >/tmp/velo-app-json-check.txt
python3 -m pytest tests/test_training_distribution_static.py tests/test_training_calendar_static.py -q
rg -n "pages/training-distribution/training-distribution|onTapTrainingDistribution|/api/training/distribution|current_description|target_description" miniprogram tests
git diff --check
```

### Task 5：最终验证 + 自审 + Claude 异源复审

按 `docs/plans/sprint-11-task-5-verification-review.md` 执行。

完整验证：

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

---

## 5. 不要碰

- 不新增数据库表、字段或 Alembic migration。
- 不改 `app/activity/worker.py` / `app/strava/worker_strava.py` 的 Sprint 10 hook。
- 不改 `app/training/service.py` 的 `/api/training/load` 服务，只从新 service import helper。
- 不改 `daily_training_load` 模型和表。
- 不让小程序从活动列表拼训练分布。
- 不把 `min_w/max_w` 返回给小程序。
- 不临时改训练学阈值。
- 不现场改写 spec §4.1 已确认的 v1 文案。

---

## 6. 给新线程的启动提示词

```markdown
请从 Sprint 11 代码实现开始，不要重写 PRD/spec/plans。

工作区：`/Users/macbookair/Desktop/velo`

先读：
- `docs/plans/sprint-11-dev-thread-handoff.md`
- `docs/plans/sprint-11-task-2-distribution-core.md`
- `docs/plans/sprint-11-task-3-distribution-api.md`
- `docs/plans/sprint-11-task-4-training-distribution-page.md`
- `docs/plans/sprint-11-task-5-verification-review.md`
- `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`

从 Task 2 开始，严格 TDD：
1. 先写 `tests/test_training_distribution.py`，确认红。
2. 再写 `app/training/distribution.py`。
3. Task 2 验收通过并自审后，再进入 Task 3。

硬规则：
- 不写 DB migration。
- 不动 Sprint 10 `/api/training/load` 行为。
- 不改 `app/training/service.py`，只在新 `distribution_service.py` 里直接 import `_today_bj/_bj_day_start_utc`。
- `raw_zones` 禁止返回 `min_w/max_w`。
- `groups` 百分比分母剔除 Z1；`raw_zones` 和 `total_power_seconds` 含 Z1。
- `threshold = Z4 >= 30%`，优先于 `sweet_spot`。
- spec §4.1 文案已由 Tim 确认为 v1，执行时不现场改写。
- 每个 task 完成后按 task 卡验收命令跑测试，并汇报下一个 task 的目标和模块位置。
```
