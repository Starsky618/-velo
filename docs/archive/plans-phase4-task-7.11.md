# 任务 7.11：集成测试 + 收尾

> 第 4 期收尾任务。所有代码任务（7.1~7.10）完成后进行。
> 不写新功能，只做"验收 + 知识沉淀 + 防黑盒化"——确保这期的能力稳定下线。

---

## 🎯 目标（一句话）

把第 4 期做的东西跑一遍完整集成测试、把系统全景更新到 `docs/architecture-guide.md`、把本期踩过的坑和好经验沉淀成文档——让半年后的自己或新队员进来一眼能看懂系统现在的样子。

---

## ⛓ 前置依赖

**全部前置任务完成** — task-7.1 ~ task-7.10。

---

## 🛠 完整步骤

### 步骤 1：后端单元测试全绿

```bash
cd /Users/macbookair/Desktop/velo

# 跑全部测试，含本期新加的
pytest -v

# 性能体检（硬性要求：总耗时 < 30s 红灯阈值）
pytest --durations=10
```

**验收标准**：
- [ ] 所有用例 PASSED，无 FAILED / ERROR
- [ ] 总耗时 < 10s（黄灯）/ < 30s（红灯）
- [ ] 本期新增的测试文件都被收进来：
  - `tests/strava/test_webhook.py`（7.4）
  - `tests/strava/test_import_progress.py`（7.5）
  - `tests/strava/test_hardening.py`（7.6）
  - `tests/activity/test_parse_activity_type.py`（7.7）
  - `tests/notification/test_mark_all_read.py`（7.8）
  - `tests/test_scheduler_entry.py`（7.9）
  - `tests/strava/test_oauth_state.py`（7.2）
  - `tests/strava/test_callback.py`（7.3）

### 步骤 2：后端集成测试

**OAuth 端到端**（mock Strava token endpoint）：

```python
# tests/integration/test_oauth_end_to_end.py
def test_oauth_full_flow_from_authorize_to_status(client_with_auth, db, user_factory):
    """
    走完: /authorize -> 模拟 Strava 回调 -> /callback -> /status
    期望: status.bound = True, athlete_id 匹配
    """
    # ...具体实现略，体力活，参照现有 test_callback.py 扩展
```

**导入进度端到端**（mock Strava list+detail）：

```python
# tests/integration/test_import_end_to_end.py
def test_import_tier1_then_tier2_progresses(...):
    """
    1. 创建 active StravaImport
    2. mock Strava list 返回 3 条活动
    3. 调 run_import_tick 几次
    4. 验证 tier1_completed 和 tier2_completed 推进
    """
```

**stalled 自愈**：

```python
def test_stalled_view_status_detected(db, user_factory):
    """
    updated_at 设为 6 分钟前 → get_import_progress 返 view_status='stalled'
    """
```

### 步骤 3：Strava 真实环境 E2E（生产验证）

**前置**：本机跑完冒烟、生产部署完毕。

```
1. 用 Strava 账号 A 走完: 小程序 → 绑定 → 授权 → 回跳 → 看 status
2. 查 /api/strava/status → bound=True, athlete_id=A
3. 查 /api/strava/import-progress → view_status=active 或 completed
4. 等导入完成，首页应看到骑行记录出现
5. 检测通知：如果有赛段匹配出 PR/KOM 会在铃铛红点出现
6. 切换账号 B：重新走授权流程
   - 账号 A 的 importing 活动应被置 failed
   - 账号 B 的导入开始
7. 关闭 web-view 立刻重新打开 Profile 页，状态应一致（view_status != 'none'）
8. 人为让 Redis 丢 scheduler 那个 empty_key 测试 I9 降级
```

### 步骤 4：前端手工回归（小程序开发者工具）

完整跑一遍 `task-7.10.md` 的"手工测试 checklist"。

### 步骤 5：更新 `docs/architecture-guide.md`（防黑盒化机制 1）

> **核心约束**：这份文档在每期结束必须刷新，让它永远反映系统最新样子。过时的导览比没导览更坑。

**必做改动**：

1. **模块关系图**：把 notification 模块的"消费侧"（前端通知中心 + 荣誉页）补进拓扑图
2. **数据流图**：新增 5 条核心流
   - 流 1：打开 App 看红点（home.onShow → /notifications?unread_only=1 → unread_count）
   - 流 2：看通知列表（navigate → /notifications + /mark-all-read 并行）
   - 流 3：点通知跳赛段（navigate with segment_id，NULL 时兜底）
   - 流 4：绑定 Strava（authorize → H5 跳板 → Strava → callback → status）
   - 流 5：看导入进度（status → import-progress 轮询 → view_status 分支）
3. **容器拓扑图**：api / worker / scheduler（新）/ cleanup / caddy / db / redis
4. **新接口清单**：
   - POST /api/notifications/mark-all-read
   - GET /api/notifications（新参数 unread_only + 响应加 unread_count）
   - GET /api/strava/import-progress（新字段 view_status）
   - POST /api/strava/webhook（加 subscription_id 校验）
5. **新字段清单**：notifications.is_read / activities.activity_type / users.mute_notifications / strava_imports.updated_at(tz)

**检查标准**：新人（或半年后的 Starsky）只读这份导览，能在 10 分钟内搞懂系统全貌，不需要翻代码。

### 步骤 6：回答"黑盒度体检三问"（防黑盒化机制 2）

把下面三问的答案写进本期完工报告（不是单独文件，直接贴在 commit message 或 changelog 里）：

**问 1：10 分钟讲解挑战**

> 我能否用 10 分钟给陌生人讲清整个系统？哪个模块卡壳最多？

**问 2：数据流复述**

> 挑一个典型用户操作——"上传 GPX 并看到赛段成绩"——从按钮点击到数据落库的完整路径，能在纸上画清楚吗？

**问 3：30 秒读懂**

> 有没有哪个文件 / 函数自己看都要想超过 30 秒才明白意图？如有，清理：加注释 / 拆分 / 重命名。

**不满足则当期内清理**。

### 步骤 7：更新 `docs/changelog.md`

在文件顶部加一段：

```markdown
## 2026-04-xx 第 4 期：前端反馈环闭合 + Strava 集成加固

**本期交付**：
- 通知中心页 + 荣誉页 + 首页红点 + 免打扰开关
- Strava 绑定用户端完整流程（Profile 组件 + H5 跳板）
- Scheduler 容器部署（C3 修复）
- 8 个 Critical + 11 个 Important 风险全部修复

**技术亮点**：
- OAuth state 改 Redis GETDEL 一次性消费（防 CSRF + 重放）
- callback UNIQUE 检测置于清理之前（顺序不可换）
- scheduler 独立容器 + tier1 连续 2 次空判定（防 Strava 抽风）

**文档更新**：
- docs/architecture-guide.md（系统全景图刷新）
- docs/spec-v4.md（Critical=0 终版）
- docs/plans/phase4/（11 任务实施计划）
```

### 步骤 8：更新 `docs/tech-debt.md`（若存在或新建）

记下本期发现但没修的东西，下一期评估：

```markdown
## 本期遗留（P1：下期评估）

1. **H5 跳板方案临时化**：小程序 web-view 未配业务域名白名单，当前用剪贴板+模态提示过渡。
   **后续动作**：发布前配 web-view 域名；改 profile.js 的 onTapStravaBind 为 web-view 跳转。

2. **积分 + 骑行等级系统**：spec §9.5 规划，第 5/6 期用户活跃度达标后启动。

3. **微信服务消息推送**：spec §9.3，独立大任务，下期规划。

4. **N+1 查询**（排名计算）：历史已标注 TODO，下期性能专项一起清。
```

### 步骤 9：更新 `velo/CLAUDE.md` 当前进度

在 "### 第 3 期：事件通知系统（2026-04-16 完成 + 部署）" 下加：

```markdown
### 第 4 期：前端反馈环闭合 + Strava 集成加固（2026-04-xx 完成 + 部署）
- [x] 任务 7.1：Alembic 迁移 + 模型改动（5 合 1）
- [x] 任务 7.2：Strava OAuth state 加固（C1 + C8）
- [x] 任务 7.3：callback 防重复绑定 + 换号清理（C2 + I6）
- [x] 任务 7.4：Webhook subscription_id 校验（C4）
- [x] 任务 7.5：import-progress stalled + 限速（C7 + I11）
- [x] 任务 7.6：Strava 现有函数加固（I7 I8 I9 I10）
- [x] 任务 7.7：解析器入口分流（种子 3）
- [x] 任务 7.8：mark-all-read + unread_count（I2 I3）
- [x] 任务 7.9：scheduler 容器部署（C3）
- [x] 任务 7.10：小程序前端 6 页/组件
- [x] 任务 7.11：集成测试 + 收尾
```

并在四步战略规划处打钩：`- [x] 第 4 期 ✅`。

---

## 📦 Commit 指令

本任务分多个 commit（每个步骤一个）：

```bash
# Commit A：更新 architecture-guide.md
git add docs/architecture-guide.md
git commit -m "docs(phase4): 刷新架构导览 — 本期新增模块/数据流/接口"

# Commit B：更新 changelog + tech-debt + CLAUDE.md 进度
git add docs/changelog.md docs/tech-debt.md CLAUDE.md
git commit -m "docs(phase4): 第 4 期收尾文档 — changelog + tech-debt + 进度"

# Commit C：集成测试
git add tests/integration/
git commit -m "test(phase4): OAuth 端到端 + 导入端到端 + stalled 自愈集成测试"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清本任务"收尾"干了什么？

> 三件事：①把本期写的代码跑一遍端到端测试（后端 + Strava 真实环境 + 小程序）；②把"系统现在长什么样"这份导览文档（architecture-guide.md）刷新到最新；③把没修完的东西写进 tech-debt.md 当下期 P1 候选。
>
> 精髓：**宁可多花半天做收尾，不让黑盒在此处长起来**。

**2. 崩溃场景**：如果生产 E2E 测试失败怎么办？

> 按严重度处理：
> - Critical 级（用户无法绑定、数据损坏）→ 立即回滚部署（`git revert` + `sudo docker compose up -d`），修完再上
> - Important（某路径体验异常）→ 当天 hotfix patch 独立 commit
> - Minor（日志 warning）→ 记进 tech-debt 下期清
>
> 原则：**生产永远有一个可回退的版本**。本期所有改动分散在多个任务的 commit 里，revert 某个具体 commit 成本低。

**3. 边界纪律**：收尾任务有没有做 spec 没要求的"顺手优化"？

> 本任务是收尾 = 专门做 spec 要求的 3 件事（集成测试 / 刷架构导览 / 答体检三问）。严格不做额外优化——
> - 不顺手重构"收尾期新发现的不爽代码"（那是第 5 期开工前的回溯体检该做的）
> - 不顺手给没覆盖到的功能补测试（只补 spec §8.2 明确要求的端到端测试）
> - 不顺手做 README 美化（本期改 changelog 即可）
