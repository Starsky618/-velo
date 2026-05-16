# Sprint 6 工作交接（spec → 实施）

> **本文件性质**：spec 阶段完结 / 新 claude 进程起手必读 / 不读历史会话上下文 / 直接进 task-1 实施。
>
> **写作日期**：2026-05-16
>
> **交接动机**：spec 阶段 4 轮起草 + 3 轮双审消耗了大量 context / 实施阶段 6 task × 多 subagent 报告会爆 / 干净 context 更准。

---

## 1. 当前位置

**Sprint 6 spec 阶段 100% 完结**：

- ✅ `docs/prd/sprint-6-prd.md` v0.4（Critical=0）
- ✅ `docs/plans/sprint-6-task-{1..6}.md` v0.4（双层结构 / 第一层给 Tim / 第二层给 subagent）
- ✅ 3 轮双审收敛（v0.1: 5+ Critical → v0.2: 5 → v0.3: 1 → v0.4: 0）
- ✅ memory `project_velo_persona_engine_sprint_seed.md`（NPC Sprint 种子 / 推迟到 Sprint 6 之后）

**下一步 = task-1 实施**。

---

## 2. Sprint 6 主轴（一句话）

把"我的"页（`pages/profile`）从字段表格升级为骑手身份名片——签名 + 自动徽章 + 训练统计 + 城市征服墙 + 历史活动列表。

**不写任何 NPC 拟人化文案**（"今天嗑药了？" / 数字祝贺 那套）—— 延后到 Persona Engine 独立 Sprint。

---

## 3. task 拆分 + 依赖图 + 估时

| # | task | 估时 | 依赖 |
|---|---|---|---|
| 1 | User.bio 字段 + 迁移 + schema | 0.5 天 | 无 |
| 2 | 数据徽章规则（badges.py 纯函数）+ cities.py 共享常量 | 1 天 | task-1（schema 同位字段） |
| 3 | activities.city 字段 + worker hook + backfill + city-medals endpoint | 1-1.5 天 | 弱依赖 task-2 cities.py |
| 4 | 前端 profile 页改造（4 模块）| 2-3 天 | task-1/2/3 全 ship |
| 5 | 前端 settings 子页 + 后端 POST /api/strava/unbind | 1-2 天 | 无 |
| 6 | 真用回归（6 场景 + 5 类盲区清单）| 1 天 | task-1-5 全 ship |

**串并顺序**：task-1 / task-5 可并行；task-2 等 task-1；task-3 等 task-2 的 cities.py merge；task-4 等 task-1/2/3；task-6 收尾。**总 7-10 天**。

**Alembic 链**：sprint5_activity_privacy → sprint6_user_bio (task-1) → sprint6_activity_city (task-3)

---

## 4. 起手必读清单（按顺序）

1. **本文件**（你正在读）
2. `docs/prd/sprint-6-prd.md` v0.4 § 0.1 **真实代码事实表**（防再凭印象 / file:line 实证锚）
3. `docs/prd/sprint-6-prd.md` § 1.3 边界 + § 1.4 规则界限
4. 准备做哪个 task → 读对应 `docs/plans/sprint-6-task-N.md` 完整（第一层 + 第二层折叠）
5. memory `project_velo_persona_engine_sprint_seed.md`（仅 grep "当前状态"段确认延后状态 / 防 NPC 文案污染本 Sprint）

**禁止**：读 spec-v5.md / phase-5-prd.md / Sprint 5 task 卡（除非 task 卡 spec 行号引用）

---

## 5. 8 条红线（违反 = bug）

1. **NULL vs 'unknown' 语义严格区分**（task-3 / 三轮 Critical 实证）：
   - `activity.city = NULL` = 从未推断过（旧数据 / 无坐标 / worker hook 异常）
   - `activity.city = 'unknown'` = 推断过但不在 6 城（用户骑老家小县城）
   - worker hook + backfill 脚本两处空轨迹 / 坐标缺失 → 都**保持 NULL**（不写 'unknown'）

2. **新增字段（bio / badges / city-medals）自他对称强制**（D-P08 落地版）：
   - 既有字段集**故意不对称**（self 含 ftp/weight / others 不返 / Sprint 4 codex P1-4 砍）保留
   - 本次新增字段 self 和 others 都必须返 / 字段名 + 值完全一致

3. **白名单 `_PROFILE_RESPONSE_KEYS` 必须用 `|=` 追加**（永不整体重写 / 防丢既有 9 字段）：
   - 既有 9 字段（id/nickname/avatar_url/city/bike_type/total_distance_km/total_elevation_m/activity_count/current_month_summary）
   - + task-1 bio = 10 字段
   - + task-2 badges = 11 字段

4. **用户手填徽章永不允许**（破坏护城河 / Pydantic schema 不接受用户传入 badges）

5. **endpoint 前缀 `/api/user` 单数**（Tim 2026-04-30 拍 A / router.py:23 实证 / 不是 /api/users）

6. **真实字段名（凭印象坑过 3 次）**：
   - `Activity.distance`（不是 distance_m）/ `Activity.elevation_gain`（不是 elevation_gain_m）
   - `User.strava_athlete_id`（不是 strava_user_id）

7. **6 城单一真相源**：`app/common/geo.py:29-36` `_CITY_BOUNDS` keys → cities.py 派生 `tuple(_CITY_BOUNDS.keys())`。**真实 6 城** = beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan（**不含 xi-an / guangzhou** / 历史 v0.1 凭印象错过）。
   - 加新城市需改 3 处：geo.py + users.city CHECK + activities.city CHECK（Alembic 迁移不能 import 应用代码 / 工程不可避免）

8. **PATCH /me 改 bio + city（settings 类）/ PUT /profile 改 nickname/avatar_url/ftp/weight/bike_type/weekly_goal（主资料）**（v5 期 task-2.C.3 分工 / 不要混）

---

## 6. 实施流程（每个 task）

每个 task 走标准 4 步（CLAUDE.md "三重审判"）：

1. **派 subagent 实施**（按 task 卡第二层技术细节 / subagent 起手必跑 grep 验证现状）
2. **Claude A 忠 PRD 双审**（reviewer-spec-faithful）/ 抓 spec 偏离
3. **Claude B 集成审**（reviewer-integration）/ 抓跨模块影响
4. **Codex 异源审**（codex:codex-rescue）/ 抓 Claude 系统性盲区
5. 任一抓 Critical → 修 → resume 复查 → 最多 3 轮收敛
6. 双审 + Codex 都过 → commit（按 CLAUDE.md commit 前 4 问）

**违反三审 = 双重违规**（CLAUDE.md 项目规则 §8）。

---

## 7. 部署 SOP（每次 commit 后必跑 5 步）

详见 memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md`：

1. 本地 `git push origin main`
2. 远端 `ssh ubuntu@114.132.190.245 "cd ~/velo && git pull"`
3. **改 schema 必清 Redis** + **`alembic upgrade head`**（哪怕"觉得没改"）
4. `sudo docker compose up -d --build`（不是 restart / worker 镜像必须 rebuild）
5. curl verify 真 endpoint（不只看 `docker compose ps`）

task-3 加 2 步：跑 `scripts/backfill_activity_city.py --dry-run` + 真跑（限速 5 条/秒）

---

## 8. 新进程起手 prompt 建议

复制粘贴到新 claude session 开头：

```
继续 velo Sprint 6 实施工作。读 docs/plans/sprint-6-handoff.md 起手 / 然后读 docs/prd/sprint-6-prd.md § 0.1 真实代码事实表 / 然后读 docs/plans/sprint-6-task-1.md（task-1: bio 字段）/ 派 subagent 实施 task-1 / 跑三审 / commit。
```

---

## 9. 关键 file:line 速查（防再凭印象）

| 真值 | 位置 | 备注 |
|---|---|---|
| User 字段（含 strava_athlete_id）| `app/user/models.py:27-119` | - |
| Activity 字段（含 distance / elevation_gain / 无 city）| `app/activity/models.py:42-164` | task-3 加 city |
| Router 前缀 `/api/user` 单数 | `app/user/router.py:23` + L116-117 | Tim 2026-04-30 拍 A |
| 看他人白名单 9 字段 | `app/user/service_social.py:71-75` | task-1/2 用 `|=` 追加 |
| 6 城 GPS box | `app/common/geo.py:29-36` | 单一真相源 |
| users.city CHECK 约束 | `app/user/models.py:115-118` | 6 城 + unknown |
| 最新 Alembic head | `migrations/versions/sprint5_activity_privacy.py:12` | task-1 down_revision |
| Strava `/status` 返字段 `bound` | `app/strava/service_token.py:71` | task-5 前端用 |
| `_handle_athlete_deauthorize` pattern | `app/strava/service_sync.py:115-123` | task-5 unbind 对齐 |

---

## 10. Sprint 范围外（明确推迟）

- NPC 拟人化文案 / 数字祝贺 / 黑色幽默 → Persona Engine Sprint（独立 / memory `project_velo_persona_engine_sprint_seed.md`）
- 关注/粉丝/feed 流/点赞 → 社交关系 Sprint
- 地图叙事化（路线着色 + 徽章贴地图）→ 远期大工程
- 长简介 / Markdown / 用户手填徽章 → 永不做

---

> **交接完成**。新 claude 进程读完本文件 → § 0.1 事实表 → task-1 卡 → 派 subagent 实施。
