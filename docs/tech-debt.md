# 技术债务清单

> 项目 CLAUDE.md 防黑盒化机制 3："每期开工前做回溯体检"——新期 Spec 不允许依赖"还在 tech-debt 清单里"的功能，先修清理再做。
>
> **2026-05-13 刷新**：清理废条目 3 条（pg_dump P0 / service.py 红灯 3 文件 / middleware untracked）—— 全部已 ship / 详见对应 commit 链。本表只留真未修条目。

---

## 🟢 P3：badges 看他人时全计入私密 effort（Sprint 6 task-2 / Tim 2026-05-16 拍 A / 2026-05-16）

`app/user/service_social.py:_aggregate_badges_input` 山名常客频次查询：
```python
.filter(SegmentEffort.user_id == user_id)
```
**没有** JOIN `ActivityPrivacy` 过滤 visibility。相比之下 `app/segment/service.py:100` 排行榜查询有完整的 `outerjoin(ActivityPrivacy) + visibility` 过滤。

**Tim 2026-05-16 拍 A**（全计入私密 effort）：

| 选项 | 含义 | Tim 评价 |
|---|---|---|
| **A 全计入** | self / others 都算上所有 effort（含私密） | ✅ **选这个** / badges 是聚合派生 / 不暴露具体活动详情 / 简单产品语义 |
| B others 过滤 | 看自己全算 / 看他人只算非私密 | ❌ self vs others 字段值不一致 / 违反 D-P08 新增字段对称（badges 数组可能 self 含 / others 不含） |
| C 全过滤 | self / others 都不算私密 effort | ❌ 自己看自己也少徽章 / 与"badges 反映真实数据"理念冲突 |

**当前行为 = A**（已 ship / Tim 拍 / 与 Sprint 5 排行榜对私密 effort 的过滤规则不一致 / 但 badges 是派生数据不直接暴露活动详情 / 风险可接受）。

**重审触发条件**（Tim 已拍但保留 awareness）：
- 用户报"我设私密的活动还是被人看出来骑过几次"
- 用户量上 1000 / 私密占比上升 / 私密含敏感信息（如军用敏感地区路线）的真实案例

**重审时修法草稿**（如未来翻 B）：改 `_aggregate_badges_input` SQL 加 `outerjoin(ActivityPrivacy) + visibility` 守卫 / 区分 self vs others 调用方。

---

## 🟢 P3：profile endpoint 调用链 SQL 重复聚合（Sprint 6 task-2 Codex 异源审 / 2026-05-16）

`get_user_profile_for_others` 已查 `target / totals / current_month_summary`（3 次 SQL）/ 随后 `get_user_badges()` 又重新查 `user / activities`（2 次 SQL）→ 热路径从 3 次膨胀到 6 次。100 用户量级 / 6 SQL 也就几十 ms / 不阻塞 ship。

**触发清理条件**：
- profile p99 响应时间 > 500ms / 或
- 用户量上 1000 后真用回归报"profile 页加载慢"

**修法草稿**：重构 `_aggregate_badges_input` 接受 `pre_computed_totals` 可选参数 / `get_user_profile_for_others` 内部复用已查的 totals / 减少 2 次 SQL。需同步改 self profile 路径（GET /profile router 内）。

---

## 🟢 P3：Sprint 6 task-3 Strava worker hook 缺真 e2e 测试（task 卡 v0.4 红线未完全满足 / 2026-05-16）

当前 case-9（`tests/test_city_medals.py:262`）= source-level grep `_set_activity_city` 字符串 + case-9b 直调 helper / 双层防回退。但 task 卡 v0.4 L218 明文要求"测试 case-9 必须真覆盖该路径（不能只 mock activity / 必须从 import_scheduler 起跑到 hook）"。

**为什么不立即修**：
- 完整 e2e 需 mock 5-7 个 import_scheduler 上游依赖（StravaClient.list_activities / fetch_streams / from_streams / save_parse_result / normalize 等）+ setup user + token + 假 Strava activity / 估时 30-60 分钟
- 接入点已 grep 锁定 `app/strava/import_scheduler.py:425`（reviewer + subagent + 主 agent 三方实证）
- task-6 真用回归会真 Strava 同步打通验证（小明真同步活动看 city 是否点亮）
- 100 用户量级真用回归足以兜底

**触发清理条件**：
- task-6 真用回归发现 Strava 同步 city 漏写
- 或 Strava import_scheduler 重构 / 接入点位置改动 / 担心 source grep 失灵

**修法草稿**：参考 `tests/test_strava_*` 已有 mock pattern / mock 顶层 Strava 客户端 + from_streams 返特定 simplified_track / 真调 `_run_tier2` / 断言 `activity.city` DB 写入。

---

## 🟢 P3：Sprint 6 task-3 PG partial index 命中验证缺（Codex 异源审 / 2026-05-16）

`migrations/versions/sprint6_activity_city.py:65` `idx_activities_user_city_completed` 是 partial index（条件 `status='completed' AND city IS NOT NULL AND duplicate_of IS NULL`）/ 用于加速 `service_social.get_city_medals` 聚合查询。

当前 case-14（`tests/test_city_medals.py:190` 1000 条 < 100ms）在 SQLite 内存表跑 / **无 partial index**（PG-only / 走 dialect 守卫跳过）/ 只能证明 SQL 写法不退化 N+1 / **不能证明 PG 生产真命中此 index**。

**触发清理条件**：
- 真用回归 city-medals 慢（p99 > 500ms / 100 用户量级不应该出现）
- 用户量上 1000 后聚合扫表
- dev stack 准备好真 PG fixture 后

**修法草稿**：dev stack 用真 PG 跑 `EXPLAIN ANALYZE SELECT city FROM activities WHERE user_id=X AND status='completed' AND city IS NOT NULL AND duplicate_of IS NULL GROUP BY city` / 断言 `Index Scan using idx_activities_user_city_completed`（不是 `Seq Scan`）。

---

## 🟢 P3：Strava unbind 在途 worker 竞态（Sprint 6 task-5 Codex 异源审 / 2026-05-16）

`app/strava/service_sync.unbind_strava` 把 active strava_imports → paused 阻止**下一次** scheduler pick。但**挡不住已在途**的 `_run_tier1()`：worker 已通过 `ensure_valid_token()` 拿到旧 access_token / 用户此刻解绑（token 清 + imports paused）/ 当前 tier1 调用仍能成功 / 落 activity + commit。

**为什么不立即修**：
- 时间窗口极短（worker 拿 token 到 commit 之间 ms 级 / 用户手动点解绑刚好撞上 < 0.1% 概率）
- 100 用户量级 / 用户解绑频次低 / 撞上的预期 = 0
- 修法复杂：`_run_tier1` 落库前 `SELECT FOR UPDATE` 复核 import 任务 status / 牵动 import_scheduler 主链路

**触发清理条件**：
- 真用回归发现"解绑后又同步过来 1 条新 activity"
- 用户量上 1000 后撞上概率升高

**修法草稿**：在 `_run_tier1` worker 完成 fetch 准备 save 之前加一次 SELECT FOR UPDATE 复核 `import.status == 'active'` / 若已 paused 则 abort 当前轮不写 DB / 与 unbind 同事务竞态由 DB 行锁兜底。

---

## 🟢 P3：PATCH /api/user/me 同传 city+bio 时双 commit 无原子保证（Sprint 6 task-1 三审共识 / 2026-05-16）

`app/user/router.py:230-247` 路由先调 `update_user_city`（service_social 内 commit + 清 heatmap 缓存）/ 再调 `update_user_profile`（service_auth 内 commit）/ 中间无 SAVEPOINT。第二次 commit 若 DB 异常 → city 已持久化 + 缓存已清 / bio 未写入 / 用户收 500 但 city 已变。

**为什么不立即修**：
- 100 用户量级 / DB 抖动概率极低
- 修法（router 直接 setattr 单 commit）会牵动 3 条既有 mock 测试（`test_patch_me_valid_city_calls_service` / `_empty_body_does_not_call_update` / `_explicit_null_clears_city`）+ 失去 service 层注释追溯
- 三审共识：Claude B + Codex 都建议合并但都接受 tech-debt
- 真用频次低：用户同时改 city + bio 不是高频场景

**触发清理条件**：
- 用户量级升 1000 以上 / 或
- 真用回归报出"改了 city 但 bio 没保存"投诉 / 或
- 下一次大改 PATCH /me（如加 settings 新字段）顺手收编

**修法草稿**：router 内 `try: user = service.get_user_by_id(...)` → setattr `user.city = ...` + setattr `user.bio = ...` + `db.commit()` + commit 后才 `invalidate_heatmap_cache`。需同步改 3 条 mock 测试为"断言 user.city / user.bio 真值"而不是"断言 service 函数被调用"。

---

## 🟡 P2：前端历史代码"-"占位符全工程清理（2026-05-15 Tim 拍永久规则）

Tim 拍永久 UX 规则："前端永远不显示 '-' 或'暂无 XX' 占位符 / 字段缺失必须整块隐藏"。
详见 memory `feedback_no_dash_placeholder.md`。

**已修**：`miniprogram/pages/segment-efforts/`（task-4.5 现场 / 已 commit 本次 hotfix）

**遗留**（待集中清理）：
- `miniprogram/pages/detail/detail.wxml:109/113/121/142/180/218` — 5+ 处 `xxx != null ? xxx : '-'` 模式
- `miniprogram/pages/honor/honor.js:63,97` — speedText / formatDuration fallback '-'
- `miniprogram/pages/segment/segment.js:110-112,274-282` — elevationGainText / avgGradientText / maxGradientText 初始值和兜底

**修法 pattern**：
1. wxml `<text>{{x || '-'}}</text>` → `<text wx:if="{{x}}">{{x}}</text>`
2. js fallback `'-'` → `''`（空字符串触发 wxml wx:if 不渲染）
3. 复合卡片整块：用 `wx:if="{{activity.fieldName}}"` 包整块 view（已有 pattern / detail.wxml:121 功率卡片）

**为什么不立刻清**：detail.wxml 等场景多数字段（如 avg_speed / duration）几乎不为 null / "-"实际不触发 / 用户看不到 / 不算 hotfix 紧急。但写在这等下次有人改 detail 页时一并清。

---

## 🟢 P3：用户主页 `current_month_summary.avg_power_w` 字段后端返但前端不渲染（task-4.6 Codex 异源审 I3 / Sprint 6 task-4 续工 2026-05-16 复核）

**当前状态**：
- 看他人 endpoint `GET /api/user/{user_id}/profile` 返 `current_month_summary.avg_power_w`（`app/user/schemas.py:189 _MonthSummary` + `service_social.py` 真填这字段）
- **self stats endpoint `GET /api/user/stats?period=week` 不返此字段**（`schemas.py:140 StatsResponse` + `service_stats.py:99` 真实聚合只产 distance / rides / elevation_gain / duration / weekly_goal / goal_percent）
- 前端 `user.wxml`（他人主页）+ `profile.wxml`（self 主页）都完全**不渲染** avg_power_w

**为什么不修**：
1. **产品层不暴露**：Tim 2026-05-15 拍"产品里没有每月平均功率 / 只有最大功率 / 最大功率只能本人看"——前端不渲染 = 产品决策 / 不是 bug
2. **self 视图 schema 也不返**：task-4 续工原本想"profile 页渲染 self 当月平均功率"清掉 P3，但 grep 实证 self stats endpoint 根本不返此字段——要么改后端 stats schema 加派生字段（动核心 endpoint 风险大），要么 self 页改调 `GET /api/user/{me_id}/profile` 多调一次（浪费 endpoint）。Tim 已拍 self 视图也不渲染——产品层不要这个字段
3. task-4.6 `hide_power` 已覆盖所有产品可见的功率字段

**未来恢复 trigger**：如果未来加"他人主页 / self 主页显示月均功率"UI：
- **先在 `app/user/schemas.py:140 StatsResponse` 加 `avg_power: Optional[float]` 派生字段**（self 路径）
- **同时在 `app/user/service_social.py:317-345` 加 `hide_power` 联动**：扫用户本月活动如有任一条 `hide_power=true` → avg_power_w 返 None / 前端 wxml 用 `wx:if` 整块消失（他人路径）

否则会重蹈 task-4.6 Codex C1 `power_zones` 二阶泄露的覆辙——汇总字段表面是聚合但反推能力强（min_w/max_w 直接推出 FTP）。

---

## 🟡 P2：赛段 max_gradient 前端砍掉 / 等数据源升级恢复（2026-05-15 Step 2-DEM Tim 拍）

velo 用 SRTM 公开 DEM（30m / 90m 像素）测窄带状公路（5-10m 宽）坡度 6 次算法迭代仍达不到 Tim 体感真值（天龙山 5% 缓坡 vs 算出 9.8-13.9% / 太山-蒙山下坡单调下坡 vs 曲线有锯齿）。根因：DEM 像素采到的可能是路边山势不是路面，算法平滑洗不掉数据源采错对象。

**当前状态**：
- 前端 segment.wxml 4 数字 grid 砍掉"最大坡度"（commit `b2ae57c`）/ 改 3 列 grid（距离 / 米爬升 / 平均坡度）
- 后端 `Segment.max_gradient` 字段保留 / API 仍返 / 回填脚本仍算（给未来恢复留路）
- `calculate_difficulty` 仍用 max_gradient 内部判断（不显示数字但 difficulty 评级仍用）

**升级 trigger（任一满足即可恢复 max_gradient 显示）**：
1. **Step 3 群体融合**：用户量起来后同段路 ≥5-10 个用户骑过 → 多用户 GPS 数据中位数校正 DEM（Strava 模式 / elevation basemap）
2. **气压计数据接入**：用户用佳明 / Wahoo 码表导入活动 → 拉气压计字段（±0.1m / 比 GPS 高 100 倍）
3. 中国境内 12m 商业 DEM 数据集开放（短期不可能 / TanDEM-X 中国授权复杂）

**为什么不彻底删字段**：DB 字段保留 + API 保留 = 数据层不动 / 未来恢复零工程量（前端 wxml 加回一格 + difficulty 算法可继续用）。详 memory `feedback_dem_precision_physical_limit.md`。

---

## 🟡 P2：Strava 老用户无 `needs_reauth` 状态机（2026-05-11 Strava scope 事故 codex round-2 抓）

velo 升级 OAuth scope `activity:read` → `activity:read_all` 后（commit TBD），老用户的 token 还在 DB 里挂着但 scope 不足：
- `app/strava/service.py:412` `get_strava_status` 只看 `strava_athlete_id IS NOT NULL` → 老用户显示 connected ✅
- `app/strava/service.py:537` `ensure_valid_token` refresh 时不校验 scope
- 老用户视角：小程序显示"已绑定 Strava" / 但私密活动**永远拉不到** / 表现为"我上传了为啥看不到"
- 后端无 schema 字段记录 granted scope / 无 needs_reauth 标志 / 无前端 UX 提示

**当前为何 P2 不是 P0**：
- 真实老 token 用户**只有 Tim 一人**（user_id=2）
  - 生产 DB 实证（2026-05-11 21:05 北京 / ssh 跑 SQL）：
    ```
     id | nickname | has_strava | strava_token_expires_at
    ----+----------+------------+-------------------------
      1 | Admin    | f          |
      2 |          | t          | 2026-05-05 21:47:41+00
    (2 rows)
    ```
  - `SELECT COUNT(*) FROM users WHERE strava_athlete_id IS NOT NULL;` = **1**（仅 Tim）
  - colleagues（CCF / 颜颜）暂未注册 velo 账号 / 未触发 OAuth
- Tim 升级后会立刻重新 OAuth = 隐含修复
- 新代码 `app/strava/service.py:285` Step 2.5 token response 二次校验**已堵住未来任何限权 token 写入 DB**
- = 这条 debt 只对"想象中的未来老用户"敞口 / YAGNI

**升级 trigger（任一即开工）**：
- 颜颜 / CCF / 其他真用户**接入并完成首次 OAuth 后**，velo 再升级 scope 第 N 次（再来一次同类事故）
- 或加入第 3 个真实用户前预防性修

**修法**（0.5-1 天工程 / 真有用户时再做）：
1. `users` 表加 `strava_scope` VARCHAR 列 + Alembic 迁移（回填 NULL = 老 token）
2. `handle_callback` Step 2.5 后写入 `user.strava_scope = response_scope`
3. `get_strava_status` 加 `needs_reauth` 字段：`strava_scope IS NULL OR not contains activity:read_all`
4. 小程序前端：`needs_reauth=true` 时 banner 提示"请重新授权 Strava 同步私密活动"

**来源**：codex round-2 review C2（2026-05-11 / agent `a37a362755e5446ee`）/ Tim 拍 A 进 tech-debt

---

## v5 实施期发现 P2/P3（task-4.4 复盘归档 / 2026-05-10）

> 不阻塞生产，但日积月累会变 P1。每条都有 spec §7 限定 + 触发重评估的条件。

| # | 项 | 优先级 | 说明 / 触发重评估 |
|---|---|---|---|
| v5-1 | `power_curve` 假设 1Hz 采样 | P2 | spec §7 限定。Strava 导入的 streams 大多 1Hz / GPX 解析不一定 / 非均匀采样下 max-mean-power 算法精度不准。**重评估触发**：用户反馈"我的 5 分钟最大功率不准" / 或导入 FIT 含变频率数据时 |
| v5-2 | `infer_city_from_coords` 跨省 / 海外起点不准 | P2 | spec §7 限定。靠 5.D.3 admin 人工修。6 城矩形边界粗略，跨省骑行（北京-天津 / 杭州-上海）会按起点判定；海外骑行返 unknown。**重评估触发**：城市枚举扩到 8+ / 每周 admin 修正占比 > 20% |
| v5-3 | 候选池脚本周一次跑 | P2 | spec §7 限定。`scripts/generate_curation_pool.py` 每周一刷新，新赛段最长 7 天才进候选池。**重评估触发**：admin 反馈"新热门赛段太晚被推 AI 写"/ 或贡献者投诉自己的赛段 1 周才被处理 |
| v5-4 | AI 草稿质量依赖人工审核 | P3 | PRD D-P10 拍。DeepSeek 生成质量参差，60-70% 可一稿过 / 30-40% 需人工改 / 偶尔有事实性错误（赛段位置写错）。**重评估触发**：DeepSeek 模型升级后人工修订率 < 10% / 或换更强模型 |

**为什么记**：v6+ 任何 agent 看到这 4 项时，先看"重评估触发"是否命中——命中 = 该升级；没命中 = 维持现状不动。防止"我觉得这里能优化"主动重写。

---

### 来源：生产部署缺陷（CLAUDE.md 已有条目）

已在主 CLAUDE.md "已知部署缺陷"小节记录：
- OAuth callback 可重复创建 strava_imports（本期 task-7.3 已修）
- ~~无 scheduler 容器~~（本期 task-7.9 将修）

### 来源：task-0.7 收尾遗漏（2026-04-30 dev stack 验证发现）

**现状**：commit `01caa5e` 改 `scripts/backfill_phase5.py` 用
`select(Segment.reference_line).where(...).scalar_subquery()` 解决 EWKB hex 字符串
被误当 WKT 解析，但 `tests/test_backfill_phase5.py` 的 `_FakeSegment` mock 类
未同步加 `reference_line` 类属性 → 2 测试持续失败。

**影响**：
- `test_backfill_segments_updates_each_segment_and_commits_once`
- `test_backfill_segments_keeps_going_when_one_segment_fails`

**性质**：fix-then-fix（hot-fix 后测试 fixture 漏同步），生产 backfill 已实证 24/24
回填成功（commit `daf6f1f` + `01caa5e`），所以 mock 测试失败不代表生产逻辑挂。

**下期动作**（性价比低 / 可推迟）：
- 给 `_FakeSegment` 加 `reference_line = Mock()` 或改测试用真 PG fixture（更稳但慢）
- 或者评估把 backfill 测试整体迁到集成测试（dev stack 已就绪）

---

### 来源：task-3.A.4 批量管理 endpoint 收尾（2026-05-04 Claude 复审）

**现状**：
- `tests/test_admin_router.py` 759 行红灯（>600），混合 4 个 endpoint domain：
  segment delete / curation_pool / ai_drafts / admin_segments。
- `app/admin/service.py` 353 行黄灯（>300），混合 3 个 admin 子领域：
  pool / draft / segment admin。

**性质**：
- 当前职责仍集中在 admin 模块内，task-3.A.4 不顺手拆，避免把功能交付和测试结构治理混在一起。

**触发条件**：
- task-3.A.5 已把 from-activity 新测试放到 `tests/admin/`，避免继续撑大
  `tests/test_admin_router.py`；下一次 admin endpoint 系列继续膨胀时，升级为拆分任务。

**下期动作**：
- 拆 `tests/test_admin_router.py` → `tests/admin/test_curation_pool.py` /
  `tests/admin/test_ai_drafts.py` / `tests/admin/test_admin_segments.py`。
- 同步评估 `app/admin/service.py` 拆成 pool / draft / segment admin 子模块，保持 router 编排层不变。

---

### 来源：task-3.B.1 D.3 admin 草稿 reject 后 human_edited_text 残留（2026-05-05 集成审 reviewer 提出 / 超出 D.3 范围）

**现状**：admin 编辑过草稿（写入 human_edited_text / status 自动转 human_edited）→ reject 时 backend 只改 status='rejected' / **不清 human_edited_text**。运营之后再 PATCH status='approved' 时，backend service.py:215 把残留的旧 human_edited_text 同步到 segments.description → 写入"已被运营丢弃"的旧文案。

**真实业务影响**：
- 运营场景：admin 编完决定 reject → 改主意再 approve → 旧编辑稿被静默发布到赛段介绍
- D.3 前端 reject 走 `{ status: 'rejected' }` 不传 human_edited_text → backend 保留旧值 → 已是 D.3 工作流默认行为（前端不能在 reject 时清，因为 backend schema `human_edited_text?: string` 没有显式 null sentinel）

**性质**：backend schema 演进任务 / 非 D.3 范围

**下期动作**（Sprint 3 收尾或 Sprint 4 起手）：
- 选项 A：`AiDraftPatchRequest.human_edited_text` 改为 `Optional[str | None]` + 显式 sentinel（如 `Field(... description="None=保留 / 空字符串=清空")`）/ 前端 reject 时显式传 `human_edited_text=""`
- 选项 B：backend service.py:196-230 在 status 切到 rejected 时自动清 human_edited_text（保守）
- 选项 C：admin H5 reject 时 modal.confirm 加"是否同时清空已编辑稿？"二选项

**优先级**：低 / Sprint 3 admin 工具内部低频场景 / 真踩才修

---

### 来源：task-3.A.6 admin from-gpx + Hausdorff 共享 helper（2026-05-05 reviewer 第二轮主动建议）

**现状**：commit `1432fad` 加了 `_check_hausdorff_overlap(db, wkt)` 共享 helper（含 dialect 守卫），from-gpx + from-activity 两条创建路径都走 helper。但**所有相关测试都用 mock**（admin 套件惯例）→ 真 Hausdorff 行为没在 SQLite 单元测试覆盖（守卫让 SQLite 跳过，无法在 SQLite fixture 验"重叠时抛 SegmentOverlapError"）。

**影响**：
- 生产 PG 真行为在 commit 时没有真实证（dev stack 真 PG 集成测试缺）
- 万一未来 helper 内部 SQL 写错 / 阈值调错 / 字段名漂移，单元测试都看不出来

**性质**：单元测试 mock 充分 / 但缺集成测试一层

**下期动作**（Sprint 3 收尾建议）：
- dev stack 真 PG 启动 + admin POST 同样 GPX 两次 → 第一次 201 / 第二次 409
- admin POST from-activity 同样 segment → 同样验
- 若纳入 CI / 评估 testcontainers + 真 PG fixture，统一 admin 套件真路径覆盖

### 来源：Sprint 1+2+3 部署后真用回归 — 产品观察 backlog（2026-05-06 Tim admin H5 真用 + Strava 绑定后反馈）

> **性质**：产品 feature 决策 / 非技术债 / 不阻塞 Sprint 4 排期 / Sprint 5+ PRD 时优先考虑。

**P1.PROD-1「不是所有赛段都适合加介绍」**（功能开关 / admin 审稿状态机）
- 现状：admin H5 草稿审核只有「通过 / 拒绝」/ 拒绝后 segment.description 依然空 / 但 admin 没法表达「永久跳过 / 不再生成」
- 未来方向：审稿状态机加「skip」状态 → segment.description 永久空 / 不再 enqueue AI 重生

**P1.PROD-2「AI 介绍很假 / 没特色 / admin 还得自己写」**（AI 输出质量 / 2026-05-06 重新定义）
- 现状：DeepSeek prompt 只喂 metadata（坐标 / 距离 / 爬升 / 难度）+ 调性要求 / 没真实"地气"输入
- 本质：metadata 写不出特色 / 活人感来自人 / AI 退化为格式补全工具

### AI 角色重定义（2026-05-06 Tim 真用 + 7 条改写洞察）

读 Tim 7 条 approved 改稿（segment_id 6/8/9/10/20/21/22）/ 提炼出**他的独家武器**：

1. **致命点警告**（事故 / 安全）—— "已发生多起车祸事故！且旁边就是悬崖" / "切记提前减速！不可逆行" / "经常有汽车或摩托越线行驶"
2. **实用补给情报** —— "终点旁边有补给，可买水、面皮和夹肉饼，约 10 元" / "藤原豆腐店（三岔路口左转上陡坡 500 米 / 平均 10%）"
3. **跨 GEO 社交基准** —— "横岭被戏称为'太原妙峰山'" / "进阶爬坡手 45 分钟大关 / 40 分钟以内是…" / "整体强度类似北京戒台寺"

**这三类 AI 永远编不出**：实地骑过 + 当地骑友口述 + 跨 GEO 横向语义网。AI 写出"教你做人""断腿前的最后一哆嗦""骨科预备役"语言节奏好但**全是空梗**（无真实事故 / 无补给 / 无基准）。

**重新定义**：
```
Tim（人）= raw material 来源（实地 + 当地圈子 + 网络评价 + 微信聊天记录）
AI       = 格式编辑器（不生成内容 / 只把散乱情报结构化 + 节奏化）
```
类比：Tim 是**现场记者** / AI 是**美编**。两者互补 / 不替代。

### 形态 B 详细设计（Tim 2026-05-06 拍 / 待 Sprint 5+ PRD）

**核心**：建 `segment_facts` 表存 raw 情报点 / AI 拼装时引用 / 事实可追溯到来源。

**Schema 草案**：
```sql
CREATE TABLE segment_facts (
  id SERIAL PRIMARY KEY,
  segment_id INT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  fact_type VARCHAR(20) NOT NULL CHECK (fact_type IN (
    'safety',      -- 致命点 / 事故警告
    'supply',      -- 补给点 / 商家 / 价格
    'benchmark',   -- 时间基准 / 跨 GEO 对标
    'history',     -- 历史 / 文化梗
    'condition',   -- 路况 / 季节性 / 时段
    'misc'
  )),
  content TEXT NOT NULL,
  source VARCHAR(20) NOT NULL CHECK (source IN (
    'admin_field',     -- Tim 实地骑过 / 朋友讲述
    'user_comment',    -- segment_efforts 评论
    'web_scrape',      -- 小红书 / 微博 / 抖音 / 知乎爬虫
    'wechat_log'       -- 微信聊天记录手工 ingest
  )),
  source_ref TEXT,         -- 来源 URL / 用户 ID / 聊天截图路径
  weight INT DEFAULT 1,    -- 权重（admin_field 权重高 / web_scrape 低）
  created_at TIMESTAMPTZ DEFAULT now(),
  is_active BOOLEAN DEFAULT TRUE  -- admin 可关闭过时情报
);
```

**AI 拼装 prompt 设计原则**：
- 不让 AI 自己**编**安全警告 / 补给详情 / 时间基准（这三类必须**只**从 segment_facts 引用）
- AI 只负责：组织顺序 + 段落分层 + 节奏润色
- prompt 模板大致：
  ```
  这条赛段的 metadata：{distance}/{elevation}/{difficulty}/{city}
  本地实测情报（必须保留 / 不可删 / 不可改事实）：
  - 致命点：{safety_facts}
  - 补给：{supply_facts}
  - 时间基准：{benchmark_facts}
  - 历史 / 梗：{history_facts}
  请把上面情报组织成 100-200 字的段落 / 节奏自然 / 不堆砌 / 致命点放显眼位置。
  ```

**数据来源演进**：
1. **短期（Sprint 5）**：admin H5 加 `segment_facts` CRUD UI / Tim 自己录 + 录的同时 AI 自动拼装 description
2. **中期（Sprint 6+）**：用户骑完 segment 在 segment_efforts 写评论 / admin 审核高质量评论标 fact_type 入库
3. **长期（Sprint 7+）**：网络爬虫（小红书 / 抖音 / 微博 / 知乎）+ LLM 语义提取 fact / admin 审入库
4. **最长期（Sprint 8+）**：微信聊天记录手工 ingest（隐私敏感 / 性价比待评估 / 可能不做）

**与 PROD-3 的关系**：PROD-3「信息源不全」是"raw material 哪里来" / PROD-2 形态 B 是"raw material 怎么用"。两者**配套**——PROD-3 解决供给端 / PROD-2 解决消费端。

**为什么不现做**：
- 当前 v5 admin H5 已经能让 Tim 手工写 description（活人感真情报已能进库 / 7 条实证）
- 形态 B 是 scale 时的事（赛段 50 → 500 时手工写不动 / 才需要拼装机制）
- 50 条规模手工写 OK / 500 条才需 AI 辅助拼装

**触发条件 / 何时升级**：
- 候选池 selected 数量 > 50 / 手工写吃不消时
- 或 Tim 觉得"raw material 多了 / AI 拼装比手写省力"时

**P1.PROD-5「活动列表索引筛选 / 像 Strava 按日期/距离/时长筛」**（UX + endpoint 扩展 / 非架构）
- 现状：home.js 列表已支持加载更多（v5 commit / onReachBottom 翻页）/ 但**没有筛选**
- 痛点：用户活动量大（实证 user_id=2 已 325 条 / 部分骑友更多）/ 翻页找老活动效率低
- 未来方向（待 Sprint 4-5 PRD）：
  - 后端：activity router 加 filter 参数（start_date_from/to / distance_min/max / duration_min/max）
  - 前端：筛选弹窗 / 日期 picker / range slider / chip 选择
- **配套硬规则**（写进未来 PRD 时考虑）：扩前端列表能力时（活动 / 排行榜 / 通知）应**统一引入分页 + 筛选模式** / 不要每页单独发明轮子（避免重复设计 + 用户体验割裂）

**P1.PROD-3「信息源不全 / 需要小红书 / 抖音 / 微信聊天记录」**（数据基础）
- 现状：admin 自己骑过 + 朋友讲述（Tim 当前的方式）/ 手头信息有限
- 三层未来方向：
  - 短期：用户在 segment_efforts 写评论 / 项目内已有路径可补
  - 中期：小红书 / 抖音 API 公开内容爬取 + LLM 语义提取
  - 长期：微信聊天记录手工 ingest（隐私 + 操作复杂 / 性价比待评估）

**下期动作**（Sprint 4 / 5 PRD 时评估）：
- A 三点 PROD-1/2/3 优先级排序（性价比 vs 当前痛点）
- B 是否合并出 'phase-N AI 草稿 v2' PRD：跳过状态 + 风味词补充 + 评论 RAG 一次性设计

---

## P2（远期）

### 前端相关
- 小程序 web-view 业务域名白名单未配（task-7.10 临时用剪贴板+模态过渡）
- 积分 + 骑行等级系统（spec §9.5，用户活跃度达标后启动）
- 微信服务消息推送（spec §9.3，独立大任务）

### 后端相关
- N+1 查询（排名计算循环发 SQL）—— 代码已标 TODO；**v5 task-4.2 已修 power-curve N+1（24s → 1-2s）/ 排名循环未修**
- trackpoints 表无分区策略（百万级用户后要加）
- service.py 三大文件红灯 ✅ 全部已拆（2026-05-13 验：strava 906→48 facade `54fe26b` / user 834→48 facade `6b5c827` / segment 793→189 + 子模块 task-pre-3.B / 当前 0 红灯）

---

## 来源：v5 Sprint 4 task-4.2 v3 polish 遗留（2026-05-09）

### D33 map matching（v5 真闭环 6 hotfix 链遗留）

**现状**：heatmap 山区赛段（如太原西山片区）有真物理 GPS 误差散网——单 segment >500m 跳点 1263 条。task-4.2 v3 polish 用"分层虚实线 + simplify 1500 + backfill"hack 修了 65%（1263 → 443 / 中位数 30m → 21m），但根本问题是 GPS 物理误差不是软件能完全修的。

**未来方向**：
- A. OSRM 容器（开源 / 自建 / 用 OpenStreetMap road network）/ trackpoint 喂进去 snap 到最近道路
- B. 高德 navigation match API（国内合规 / 速度快 / 但要 API 配额）
- 工程量 1-3 天 / 性价比中

**触发条件**：Sprint 5/6 跟 D28 高德 webview（探索 tab 用高德地图渲染）一起做 / 不单独立项

**优先级**：低 / 当前 hack 已让 90% 用户满意 / 真根治留 v6+

### tied PR my_rank off-by-one（D7 双 review I1）

**现状**：task-4.5 D7 真排名 hotfix（commit `33212a1`）给 LeaderboardResponse 加 my_rank + my_elapsed_time。算法基于 `(elapsed_time, created_at)` 排序，**tied PR**（相同 elapsed_time）场景下 my_rank 可能 off-by-one（用户看到第 4 实际是第 3-4 并列）。

**真实业务影响**：百级用户量 tied 概率 < 1% / 出现不影响数据正确性 / 视觉差 1 名

**下期动作**（跟 D33 一起补）：
- 主榜加 `(elapsed_time, effort_id)` 二级排序键 / effort_id 是单调递增 → 永远稳定 tie-break
- 测试加"两 effort 同 elapsed_time 不同 effort_id 的 my_rank 计算"边界

**优先级**：低 / 真踩才修

### 测试覆盖盲区 2 处（v3 polish ship 后批 review）

- worker hook 触发 invalidate_heatmap_cache 回归测试（heatmap city 改可选后双 cache key 是否真清）
- 无 city 精确 key 被清验证

**下期动作**：Codex --resume 时列下轮 backlog / 不阻塞当前 ship

---

## 来源：v5 PROD-2 AI 角色重定义（Tim 2026-05-06 真用 + 7 条改写洞察）

### 现状
admin H5 草稿审核生产真用 / Tim 改稿 7 条 approved（segment_id 6/8/9/10/20/21/22）/ 提炼三类"独家武器"AI 永远编不出：致命点警告 / 实用补给情报 / 跨 GEO 社交基准。

### 形态 B 详细设计已沉淀（见本文件上方"### 形态 B 详细设计"段）

### 触发条件
- 候选池 selected 数量 > 50 / 手工写吃不消时
- 或 Tim 觉得"raw material 多了 / AI 拼装比手写省力"时

### 优先级
中 / Sprint 5+ PRD 时考虑 / 当前 50 条规模手工写 OK

---

## 来源：v5 Sprint 3 task-3.A.4 admin 模块红灯（待再膨胀时升级）

### 现状
- `tests/test_admin_router.py` 759 行红灯（>600）/ 混合 4 个 endpoint domain
- `app/admin/service.py` 353 行黄灯（>300）/ 混合 3 个子领域

### 触发条件
- 下一次 admin endpoint 系列继续膨胀时（task-3.A.5 已把 from-activity 测试放 `tests/admin/` 部分缓解）

### 下期动作
- 拆 `tests/test_admin_router.py` → `tests/admin/test_curation_pool.py` / `tests/admin/test_ai_drafts.py` / `tests/admin/test_admin_segments.py`
- 同步评估 `app/admin/service.py` 拆 pool / draft / segment admin 子模块

### 优先级
低 / 当前 admin 系列稳定 / 真撑大再拆

---

## 🟢 P3：限流 middleware 未接入任何 router（代码 commit b82d692 / 仍欠接入）

### 现状
- `app/middleware/rate_limit.py` 172 行 + `app/middleware/__init__.py` 20 行 / 已 commit
- 完整功能：`check_rate_limit_by_user` / `check_rate_limit_by_ip` + X-Forwarded-For 解析 + Redis 不可用降级放行 + 飞书告警（每日去抖）
- **grep 全库 0 调用** —— 无任何 router import / 工具写好待开槽

### 修法（< 1d）
- 接入 3 个关键端点：strava router OAuth callback（IP 限流 / 防 CSRF state 撞码）/ activity router upload（user 限流 / 防刷上传）/ user router login（IP 限流 / 防暴力破解）
- 配套真用回归：6 秒内 11 次请求 → 第 11 次 429

### 触发条件
- 公测 / 用户量过 500 时
- 或第一次出限流相关事故（CSRF / 暴力破解）

### 优先级
低 / 当前内测期 0 攻击 / 工具已写好待开槽

---

## 清理节奏

> 每期 10-20% 时间处理 P1，P2 评估性价比再决定。
> 完成清理的条目从本文件移除并在 `docs/changelog.md` 记录一句。
