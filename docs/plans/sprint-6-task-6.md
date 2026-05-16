# Sprint 6 Task-6 — 真用回归

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 6 个 task / 收尾 / 依赖 task-1 ~ task-5 全部 ship
> v0.2（2026-05-16）：D-P08 验收精确改 / 只对新增字段（bio / badges / city-medals）强制一致 / 既有字段差异符合预期 / endpoint 前缀 /api/user 单数 / 部署 SOP 加迁移 + backfill 步骤
> v0.3（2026-05-16）：修第二轮 Critical —— D-P08 diff 脚本分两步（city_medals 不是 profile 字段 / 是独立 endpoint）
> 上下文：CLAUDE.md "三重审判" 真用回归原则 + memory `feedback_real_usage_vs_mock_blindspot.md` 5 类盲区 + memory `feedback_deploy_must_curl_verify_not_just_docker_ps.md` 5 步部署 SOP

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

task-1 ~ task-5 全部 ship + 部署到生产后 / 你（Tim）拿小程序在真实账号 + 真实活动数据下跑 6 个场景 / 找到所有"mock 测过但真用挂"的盲区 / 修完才算 Sprint 6 ship。

### 用户故事

**场景 1 — 新用户注册全链路**
拿一个全新微信账号 → wx.login → POST /api/user/login → 后端发 token → 默认 profile（nickname / avatar_url 从微信拉 / bio NULL / city NULL / 0 徽章 / 0 勋章）→ 上传第一条活动 → worker 写 activity.city → 自动算出徽章 / 解锁第 1 城。

**场景 2 — 改资料全流程**
在"我的"页 → 改昵称 / 改头像 / 加签名 "成都老登 / 公路党 / FTP 220W" / 切换城市为 chengdu → 改昵称/头像走 PUT /api/user/profile / 改签名/城市走 PATCH /api/user/me → 全部保存 → 刷新页面看到更新。

**场景 3 — 新字段自他对称验证（D-P08 落地版 / v0.4 分两步精确）**
你（Tim）的账号看自己 + 颜颜的账号看你 → **分两步 diff**：

第 1 步 - profile（bio + badges）：
- 拉 `/api/user/profile`（self）+ `/api/user/{TIM_ID}/profile`（others）
- diff `bio` 和 `badges` 字段必须完全一致（新增字段强制对称）
- 既有字段差异：self 含 ftp / weight / weekly_goal / created_at / others 故意不返（符合预期 / 不是 bug / Sprint 4 codex P1-4 砍）

第 2 步 - city-medals（独立 endpoint / v0.4 修 / 不在 profile 里）：
- 拉 `/api/user/me/city-medals`（self）+ `/api/user/{TIM_ID}/city-medals`（others）
- 整个 JSON 必须完全一致

❌ 新增字段（bio/badges/city-medals）值不一致 = bug
❌ ftp / weight 出现在 others profile = bug（泄漏）

**场景 4 — 上传多次活动看徽章 / 勋章**
上传 5 条不同活动 / 不同城市 / 不同距离 / 同山 ≥ 5 次（达到"山名常客"阈值）→ 看徽章自动更新（FTP / 累计 km / 山名常客 该出现）/ 城市勋章 N/6 解锁数对（v0.2 修：6 城不是 7 城）。

**场景 5 — 解绑 Strava 不丢活动**
绑定 Strava → 同步几条活动 → 进 settings 解绑 → 调 POST /api/strava/unbind → 看 profile 活动列表 → **已同步的活动还在**（不会因为解绑被删）→ DB 验证 user.strava_athlete_id IS NULL + 4 个 strava 字段全清 → 重新绑定 → dedupe 不重复导入。

**场景 6 — 退出登录干净**
退出登录 → token 清掉 → 跳回 profile 显示登录按钮 → 重新微信登录 → 数据恢复（同账号）。

### 怎么算做对了

- ✓ 6 场景全部跑通 / 没有 500 / 没有"-"占位符 / 没有字段不渲染
- ✓ **D-P08 落地验证**（v0.2 精确版）：新增字段完全一致 / 既有字段差异符合预期
- ✓ 性能：profile 页打开 < 1s（首屏 paint）/ 后端聚合 < 800ms
- ✓ bug 清单清空才能 ship
- ✓ 部署 5 步 SOP 全跑（不省略 Redis 清缓存 / 不省略 curl verify）
- ✓ task-3 backfill 脚本干跑 + 真跑都过
- ✗ docker compose ps Up 但 curl 500 → 是部署没完成 / 不算 ship
- ✗ mock 测全过但真用挂 → 列入下次 Sprint 的回归测试增强

### 这次**不做**的事

- 自动化 e2e 测试脚本（手动真用回归就足够 / 100 用户量级）
- 多用户压测 / 性能瓶颈分析（不到量）
- A/B 灰度发布（团队 < 5 人 / 不做）
- 用户行为埋点 / 数据分析平台（保留给未来"数据增长" Sprint）

### 估时

1 天（含修 bug 一轮 / 如果 bug 多可能延到 2 天）

---

## ─────── 折叠：执行细节 ───────

<details>
<summary>展开</summary>

### 部署前 checklist（CLAUDE.md "部署前强制检查清单"）

- [ ] requirements.txt 是否含新依赖（task-2 / task-3 应该不需要新包）
- [ ] docker-compose.yml 是否同步新环境变量（应无）
- [ ] Alembic 迁移在 PostgreSQL 跑通：
  - sprint6_user_bio（task-1 / bio 字段）
  - sprint6_activity_city（task-3 / city 字段 + CHECK + partial index）
- [ ] task-3 backfill 脚本干跑确认 row 数

### 部署 SOP（v0.2 / 5 步基础 + 2 步 task-3 专属）

```bash
# 1. 本地 git push
git push origin main

# 2. 远端 git pull
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull"

# 3. 跑 Alembic upgrade head（含 task-1 bio + task-3 activity.city）
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose exec api python3 -m alembic upgrade head"

# 4. 跑 task-3 backfill 脚本（**先干跑**确认 row 数 / 再真跑）
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose exec api python3 scripts/backfill_activity_city.py --dry-run"
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose exec api python3 scripts/backfill_activity_city.py"

# 5. 改 schema 必清 Redis（profile / user / city-medals 相关 cache）
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose exec redis redis-cli FLUSHDB"

# 6. up -d --build（worker 镜像必须 rebuild / task-3 加了 worker hook 代码）
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"

# 7. curl verify（必跑 / 不可省）
TOKEN=<拿一个有效 token>
curl -s "https://<生产域名>/api/user/profile" -H "Authorization: Bearer $TOKEN" | jq '.bio, .badges, .city'
curl -s "https://<生产域名>/api/user/me/city-medals" -H "Authorization: Bearer $TOKEN" | jq '.unlocked_count, .total'
# total 应该是 6（v0.2 改 / 不是 7）
curl -s "https://<生产域名>/api/strava/unbind" -X POST -H "Authorization: Bearer $TOKEN"
# 应 204 / 或 200（看实现）
```

### 5 类盲区检查（按 memory `feedback_real_usage_vs_mock_blindspot.md`）

| 盲区 | 怎么检查 |
|---|---|
| 1. mock 断言绿但真路径挂 | curl 真 endpoint / 不只看 pytest 数字 |
| 2. 进程独立 import（worker 没同步 deploy）| `sudo docker compose logs worker --tail 30` 看启动报错 + 上传活动验证 worker hook 真生效 |
| 3. SQLite vs PG（CHECK 约束 / partial index 在 PG 才生效）| city-medals 在真 PG 跑性能测试 |
| 4. 单线程 vs 容器集群（pgbouncer / Redis 缓存）| 改 schema 必清 Redis（已在 SOP 第 5 步）|
| 5. 第三方依赖激活状态（Strava 真能解绑吗）| 真账号跑解绑流程 / 看 DB 字段真清 / 重新绑定 OK |

### D-P08 自他对称 diff 工具（v0.3 修 / 分两步 / Critical）

**关键修复**（v0.2 → v0.3）：`city_medals` 不是 `/api/user/profile` 的字段 / 是**独立 endpoint** `/api/user/me/city-medals` 的返回体。v0.2 diff 脚本对着 profile JSON 跑 `.city_medals` 永远是 null → 自他对称验证失效。

**步骤 1：对比 profile（bio + badges）**

```bash
# 用 Tim 账号 token 拉自己 profile
curl -s "/api/user/profile" -H "Authorization: Bearer $TIM_TOKEN" > /tmp/tim_self_profile.json

# 用颜颜账号 token 拉看 Tim profile
curl -s "/api/user/$TIM_USER_ID/profile" -H "Authorization: Bearer $YANYAN_TOKEN" > /tmp/yanyan_sees_tim_profile.json

# 比较新增字段 bio + badges（必须完全一致）
jq '{bio, badges}' /tmp/tim_self_profile.json
jq '{bio, badges}' /tmp/yanyan_sees_tim_profile.json
# 两组输出必须一致 / 不一致 = bug

# 既有字段差异（符合预期 / 不是 bug）
jq 'keys' /tmp/tim_self_profile.json | sort > /tmp/self_keys
jq 'keys' /tmp/yanyan_sees_tim_profile.json | sort > /tmp/others_keys
diff /tmp/self_keys /tmp/others_keys
# 预期差异：
# self only: ftp / weight / weekly_goal / created_at
# others only: total_distance_km / total_elevation_m / activity_count / current_month_summary
```

**步骤 2：对比 city-medals（独立 endpoint）**

```bash
# Tim 看自己的 city-medals
curl -s "/api/user/me/city-medals" -H "Authorization: Bearer $TIM_TOKEN" > /tmp/tim_self_medals.json

# 颜颜看 Tim 的 city-medals
curl -s "/api/user/$TIM_USER_ID/city-medals" -H "Authorization: Bearer $YANYAN_TOKEN" > /tmp/yanyan_sees_tim_medals.json

# 比较 unlocked + unlocked_count + total + medals（必须完全一致）
diff <(jq -S '.' /tmp/tim_self_medals.json) <(jq -S '.' /tmp/yanyan_sees_tim_medals.json)
# 完全一致 / 任何差异 = bug（city-medals 是新增字段 / 强制自他对称）
```

### Bug 清单（真用回归发现的 / 模板）

| # | 场景 | 现象 | 根因 | 修复 commit |
|---|------|------|------|-------------|
| 1 | ... | ... | ... | ... |

每条 bug 修完后再跑一次场景验证。

### 收尾

- 所有 bug 修完 → Sprint 6 ship
- 在 `docs/changelog.md` 添加 Sprint 6 条目
- 把 Sprint 5 / Sprint 6 进度更新到 memory `project_velo_current_position.md`
- 把 Sprint 6 完整经验更新到 memory `project_velo_full_progress_history.md`

### 依赖 / 顺序

- 依赖：task-1 ~ task-5 全部 ship + commit
- 阻塞：无（Sprint 6 收尾 task）

</details>
