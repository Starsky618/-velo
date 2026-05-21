# velo 数据流全景 v2

> **Primary audience: AI coding agents.** Humans may reference but will find it terse.
> 本文档是 `architecture-guide.md` 的动态维度补充:架构讲"有什么",此文档讲"怎么动"。
> 每条链路独立成节。修改某链路任何一步前,必须读完整节,识别所有不变式和幂等性要求。

---

## 目录

0. [通用约定](#0-通用约定)
1. [链路 1: 本地上传 → 解析 → 匹配 → 通知(主干)](#1-链路-1-本地上传--解析--匹配--通知)
2. [链路 2: Strava OAuth 绑定](#2-链路-2-strava-oauth-绑定)
3. [链路 3: Strava 历史导入(scheduler)](#3-链路-3-strava-历史导入scheduler)
4. [链路 4: Strava Webhook 实时同步](#4-链路-4-strava-webhook-实时同步)
5. [链路 5: 微信登录 → JWT](#5-链路-5-微信登录--jwt)
6. [链路 6: 通知读取 + 标读](#6-链路-6-通知读取--标读)
7. [链路 7: 骑行详情页数据聚合](#7-链路-7-骑行详情页数据聚合)
8. [链路 8: 赛段详情与排行榜](#8-链路-8-赛段详情与排行榜)
9. [链路 9: cleanup 僵尸扫描](#9-链路-9-cleanup-僵尸扫描)
10. [链路 10: AI 草稿生成 (v5)](#链路-10ai-草稿生成v5-task-1b1--5b2)
11. [链路 11: worker 软目标监控 (v5)](#链路-11worker-软目标监控v5-task-1c1--571)
12. 链路 12-16: 功率曲线 / 城市热图 / 看他人 / 赛段创建 / 即时反馈（v5）
13. 链路 17: NPC 文案 hook（Persona v0.1 / 2026-05-18）
12. [链路 12: 用户功率曲线查询 + 缓存 (v5)](#链路-12用户功率曲线查询--缓存v5-task-2c2--5c2)
13. [链路 13: 城市热图 + PATCH 改 city (v5)](#链路-13城市热图--patch-改-cityv5-task-2c2c3--5a1)
14. [链路 14: 看他人主页 (v5)](#链路-14看他人主页v5-task-2c3--5a2)
15. [链路 15: 赛段创建 (v5 admin from-gpx + from-activity)](#链路-15赛段创建v5-task-3a5--3a6--5b1--5d4--5d6)
16. [链路 16: 即时反馈 (v5 赛段详情页对比 6 字段)](#链路-16即时反馈v5-task-1a3--5c1)
17. [全局不变式](#全局不变式)
18. [未实现链路(易踩坑)](#未实现链路易踩坑)

---

## 0. 通用约定

### 0.1 符号

| 符号 | 含义 |
|---|---|
| `→` | 同步调用 / 数据流向 |
| `⇢` | 异步消息(rq 队列 / Redis) |
| `⟳` | 轮询 / 定时 |
| `⚡` | 失败路径 |
| `🔒` | 原子操作 / 加锁点 |

### 0.2 容器缩写

后文用 api / worker / scheduler / cleanup / db / redis / caddy 直接指代容器。

### 0.3 文件路径约定

- 后端 Python: `app/<模块>/<文件>.py:<函数名>`(不写完整路径前缀)
- 前端小程序: `miniprogram/pages/<页>/<文件>`
- 纯函数(标✨): 不碰 DB/文件系统,独立可测

### 0.4 读文档前提

读者应已读过:
- `architecture-guide.md`(7 容器、6 模块、7 表)
- `CLAUDE.md`(命名/铁律/陷阱)

---

## 1. 链路 1: 本地上传 → 解析 → 匹配 → 通知(主干)

**这是 velo 最核心、最长、最容易出 bug 的一条链路。改任何一步之前读完本节。**

### 1.1 触发

- 用户小程序 tab "上传(+)" → 选 GPX/FIT 文件 → 点上传
- (或 Strava webhook 推送,见链路 4)

### 1.2 序列

```
[小程序]
  │
  │ wx.chooseMessageFile / chooseMedia 获取临时文件
  │ multipart/form-data,Header: Authorization: Bearer <JWT>
  ▼
[caddy:443]
  │
  │ HTTPS 终结 → 内部 HTTP 转发
  ▼
[api]  POST /api/activities/upload
  │    → router: app/activity/router.py
  │    → service: app/activity/service.py
  │
  │ Step A: JWT 中间件 → 解出 user_id
  │ Step B: 校验 Content-Type、文件后缀、文件大小(≤ 50MB)
  │ Step C: 计算 SHA-256 哈希
  │ Step D: SELECT FROM activities WHERE user_id=? AND file_hash=?
  │         ⚡ 命中 → 返回已存在 activity_id(秒级去重,防双击)
  │         (v0 去重机制,UNIQUE(user_id, file_hash) 兜底并发)
  │ Step E: StorageBackend.upload() 文件落 LocalStorage
  │         路径: uploads/<uuid>.gpx
  │ Step F: INSERT activities (status='pending', file_hash=..., file_url=...)
  │         ⚡ IntegrityError(极低概率并发命中 UNIQUE(user_id, file_hash))
  │         → 捕获 + 删文件 + 返回已存在 activity_id
  │ Step G: queue.enqueue(parse_activity, activity_id=N)
  │         rq 序列化任务 LPUSH 到 Redis list `rq:queue:velo`
  │ Step H: 返回 { activity_id, status: 'pending' }
  │
  │ 前端开始轮询 GET /api/activities/{N}/status
  ▼
  (api 此刻已解脱,小程序看到"解析中")
  │
  │ ⇢ Redis 队列
  ▼
[worker]  rq BLPOP → parse_activity(N)
  │        → app/activity/worker.py:parse_activity
  │
  │ 🔒 Step 1 (原子抢锁):
  │   UPDATE activities
  │   SET status='processing', updated_at=now()
  │   WHERE id=N AND status='pending'
  │   RETURNING id
  │   ⚡ 0 行 → 已被另一 worker 或重试取走,直接 return(幂等)
  │
  │ Step 2: SELECT activity → 获取 file_url
  │
  │ Step 3: activity_type 分流(v4 task-7.7):
  │   如果 activity_type != 'cycling' 且 != None:
  │     UPDATE activities SET status='failed',
  │       error_message='暂不支持的运动类型: <type>'
  │     return
  │
  │ Step 4: StorageBackend.download() 读文件 bytes
  │
  │ Step 5: parsing 翻译层 ✨(纯函数):
  │   if file ends with .gpx: parsing/gpx_parser.py:parse_gpx(bytes)
  │   if file ends with .fit: parsing/fit_parser.py:parse_fit(bytes)
  │   返回统一的 ParseResult {
  │     title, started_at, finished_at,
  │     distance, duration, elevation_gain, avg_speed, max_speed,  # 速度 m/s
  │     avg_power, normalized_power, max_power,
  │     avg_hr, max_hr, avg_cadence, calories,
  │     splits: [...], power_zones: {...},
  │     trackpoints: [{seq, lat, lon, ele, time, hr, cad, power, speed, distance}, ...]
  │   }
  │   ⚡ GPXParseError/FITParseError →
  │     UPDATE activities SET status='failed', error_message=...
  │     return
  │
  │ Step 6: 轨迹简化 ✨(纯函数):
  │   app/activity/simplify.py:douglas_peucker(trackpoints)
  │   → simplified_track(几百点,给前端地图用)
  │
  │ Step 7: 批量写 trackpoints:
  │   bulk_insert_mappings(Trackpoint, [
  │     {activity_id: N, seq: i, latitude, longitude, elevation, timestamp,
  │      heart_rate, cadence, power, speed, distance,
  │      geom: ST_SetSRID(ST_MakePoint(lon, lat), 4326)}
  │     for each trackpoint
  │   ])
  │   上限 50000 点,每批 500 条
  │
  │ Step 8: UPDATE activities SET 所有统计字段 + simplified_track + status='completed'
  │
  │ Step 9: 同步触发 auto_match:
  │   app/segment/auto_match.py:match_activity_against_segments(activity_id=N)
  │   (见 §1.3 下面展开)
  │
  │ Step 10: 同步触发 notification detection:
  │   app/notification/service.py:detect_events (每条新 effort 调用,见 §1.4)
  │
  │ 完成,worker 回到 BLPOP 等下一任务
```

### 1.3 赛段匹配子流程(Step 9 展开)

```
match_activity_against_segments(activity_id)
  │
  │ Step 9.1 粗筛(PostGIS):
  │   SELECT DISTINCT segments.id
  │   FROM segments
  │   JOIN trackpoints ON ST_DWithin(
  │     segments.reference_line::geography,
  │     trackpoints.geom::geography,
  │     segments.match_tolerance
  │   )
  │   WHERE trackpoints.activity_id = ?
  │   GROUP BY segments.id
  │   HAVING COUNT(*) > 10
  │
  │   ⚠️ 必须 ::geography 转型,否则 match_tolerance 单位变成度(~111km)
  │
  │ Step 9.2 对每个候选 segment_id,精确匹配 ✨(纯函数):
  │   app/segment/matcher.py:match(activity_trackpoints, segment)
  │   算法:
  │     - 找到轨迹中最接近赛段起点的点 → start_idx
  │     - 从 start_idx 往后找最接近赛段终点的点 → end_idx
  │     - 校验覆盖率 ≥ segment.min_match_ratio
  │     - 校验方向一致
  │     - 起终点偏差 ≤ match_tolerance
  │     如果通过,返回 {start_index, end_index, elapsed_time, avg_power, avg_speed}
  │
  │ 🔒 Step 9.3 SAVEPOINT 隔离写入:
  │   for each matched segment:
  │     db.begin_nested()  # SAVEPOINT
  │     try:
  │       INSERT segment_efforts (segment_id, activity_id, user_id,
  │                               elapsed_time, avg_speed, avg_power,
  │                               start_index, end_index)
  │       UNIQUE(segment_id, activity_id) 约束
  │         ⚡ IntegrityError(重试场景)→ skip
  │       commit savepoint
  │       new_efforts.append(effort)  # 收集,稍后调 detect_events
  │     except:
  │       rollback savepoint  # 不炸外层事务
  │       log "匹配 segment_id=X 失败,<原因>"
  │
  │ 结束,返回 new_efforts(供 Step 10 逐个调 detect_events)
```

### 1.4 通知检测子流程(Step 10 展开)

```
for effort in new_efforts:
    detect_events(db, effort)
  │
  │ Step 10.1 加载历史 efforts:
  │   SELECT * FROM segment_efforts
  │   WHERE segment_id = effort.segment_id
  │   (用于判定 PR / KOM)
  │
  │ Step 10.2 ✨ 纯函数 detector(signature 可能内联在 service):
  │   → 返回事件列表: ['pr', 'kom', 'kom_lost']
  │   判定逻辑:
  │     - pr: 当前 elapsed_time < 用户在此 segment 的历史最快(排除当前 effort)
  │     - kom: 当前 elapsed_time < 本 segment 全局最快(跨所有用户)
  │     - kom_lost: 新 KOM 诞生时,对旧 KOM 所有者触发
  │   注意: 纯函数不访问 DB,历史 efforts 由调用方传入
  │
  │ 🔒 Step 10.3 SAVEPOINT 隔离写入:
  │   for each event:
  │     db.begin_nested()
  │     try:
  │       INSERT notifications (
  │         user_id, event_type, segment_id, activity_id, effort_id,
  │         elapsed_time, rank, rival_user_id(仅 kom_lost),
  │         expires_at=now()+60days, is_read=false
  │       )
  │       UNIQUE(effort_id, event_type) 约束 ⚡ IntegrityError → skip(幂等)
  │       commit savepoint
  │     except:
  │       rollback savepoint
  │       log warning
  │
  │ Step 10.4 处理 KOM 被夺场景:
  │   如果新写入了 event_type='kom':
  │     找到旧 KOM 所有者的 user_id → rival_user_id
  │     INSERT notifications (user_id=<旧>, event_type='kom_lost',
  │                           rival_user_id=<新 kom 获得者>, ...)
```

### 1.4.5 5min 功率进步检测子流程（v5 task-2.A.1 新增）

worker.py:162 `activity.status = "completed"` 后、`db.commit()` 前调用：

```
detect_5min_power_progress(db, user_id, activity_id)（progress_detector.py）
  │
  │ Step 10.5.1 当前 activity 5min 最大平均功率:
  │   tps = SELECT trackpoints WHERE activity_id=N ORDER BY seq
  │   curve = calculate_power_curve(tps, windows_sec=[300]) ✨ 纯函数
  │   current_5min = curve[300]
  │   if current_5min <= 0: return None  # 无功率数据 → 不检测
  │
  │ Step 10.5.2 上月时间窗（按 BJ_TZ +8 划月，CLAUDE.md 时区约定）:
  │   now_bj = now_utc.astimezone(BJ_TZ)
  │   first_this_month_bj = now_bj.replace(day=1, hour=0, ...)
  │   last_month_start_bj = first_this_month_bj - 1 month（含跨年特例）
  │   start, end = (BJ → UTC 互转后)
  │
  │ Step 10.5.3 上月 baseline（按 activity 分组，禁止跨 activity 拼接 trackpoints）:
  │   baseline_acts = SELECT Activity.id WHERE user_id=? AND status='completed'
  │                   AND started_at >= last_month_start AND started_at < first_this_month
  │   if not baseline_acts: return None  # 上月无骑行 → 无 baseline
  │
  │   for each act_id:
  │     tps = SELECT trackpoints WHERE activity_id=act_id ORDER BY seq
  │     baseline_acts_tps.append(tps)
  │
  │   baseline_curve = calculate_power_curve_from_activities(baseline_acts_tps, windows_sec=[300])
  │     ⚠️ 用 _from_activities 不直接拼 trackpoints —— 防止跨 activity 算出虚假 5min 极值
  │   baseline_5min = baseline_curve[300]
  │
  │   if baseline_5min <= 0: return None
  │     ⚠️ 守卫：上月骑行全无功率（如全在训练台/无功率计） → baseline=0 → 不假阳性"涨 200W"
  │     "从无到有"不算"进步 5W+"
  │
  │ Step 10.5.4 阈值检测 + 静音:
  │   delta = current_5min - baseline_5min
  │   if delta < 5W: return None  # PRD Q6 路径 C / Tim 拍 5W 阈值
  │   user = SELECT User WHERE id=user_id
  │   if user.mute_notifications: return None
  │
  │ Step 10.5.5 应用层幂等检查:
  │   existing = SELECT Notification WHERE activity_id=N AND event_type='progress_5min_power'
  │   if existing: return None
  │
  │ 🔒 Step 10.5.6 SAVEPOINT 隔离写入（CLAUDE.md 陷阱 #13 / 跨模块场景）:
  │   notification = Notification(
  │     user_id, event_type='progress_5min_power', activity_id=N,
  │     expires_at=now+60d,
  │     payload={current_value, prev_value, delta, window_sec=300, baseline_period='last_month'},
  │   )
  │   nested = db.begin_nested()  # SAVEPOINT
  │   try:
  │     db.add(notification)
  │     db.flush()  # 强制 INSERT 触达 DB，让 IntegrityError 在这里抛
  │     nested.commit()
  │   except IntegrityError:
  │     # 部分唯一索引 uniq_progress_notification_per_activity 触发约束
  │     # 仅回退到 SAVEPOINT —— 外层 worker 的 activity.status='completed' 不受影响
  │     nested.rollback()
  │     return None
  │
  │ 然后 worker 自己 db.commit() 把 activity.status + notification 一起提交
```

**与 1.4 PR/KOM detector 的区别**：
- 1.4 路径：每条新 effort 检测 → PR/KOM 通知（同步检测，跟匹配赛段绑死）
- 1.4.5 路径：activity 整体 status='completed' 时检测 → progress 通知（不依赖赛段，关心整体进步）
- payload 字段是 1.4.5 用的（progress 类），1.4（PR/KOM）沿用 elapsed_time/rank/rival_user_id

**worker hook 时序与 try/except 兜底**（worker.py:162-181）：
- hook 必须在 `activity.status='completed'` **赋值后**、`db.commit()` **前**调用
  - 在前调用：detector 读 activity 看到的还是 `processing` 状态，逻辑会判错
  - 在后调用：activity status 已 commit，但本意是让 notification 与 status 同事务原子提交
- detector 异常用 `try/except Exception: pass` 兜底（与 `match_activity_against_segments` 同模式）
  - 失败静默跳过，不影响 activity 已经 completed 的事实
- `invalidate_power_curve_cache(user_id)` 在 detector 之后调（清 Redis 缓存让下次查曲线走真实计算）

⚠️ notifications 表**没有** `message` 字段 —— 通知内容由前端按 `event_type` + 关联实体数据组装展示（progress 类前端读 `payload.delta` 等字段）。

### 1.5 状态机回顾

```
[不存在] --upload--> [pending] --worker抢锁--> [processing] --解析成功--> [completed]
                       │                           │
                       │ 超 10min (cleanup)         │ 解析失败
                       ▼                           ▼
                    [failed]                    [failed]
```

### 1.6 幂等性

| 步骤 | 幂等性保证 |
|---|---|
| upload | UNIQUE(user_id, file_hash),相同文件返回同一 activity_id |
| worker 抢锁 | UPDATE WHERE status='pending',0 行则 return |
| trackpoint 插入 | ⚠️ **不完全幂等**:缺 UNIQUE(activity_id, seq) 约束,重试会产生重复(tech-debt) |
| segment_effort 插入 | UNIQUE(segment_id, activity_id) 保证(**两列**,不含 user_id) |
| notification PR/KOM 插入 | **幂等**,UNIQUE(effort_id, event_type) 兜底;kom_lost 场景 effort_id 可为 NULL,幂等性由 service 层逻辑保证 |
| notification progress 插入 | **幂等**,部分唯一索引 `uniq_progress_notification_per_activity` 兜底（仅 progress_% 类生效），应用层 + DB 双层防 worker 重试 / 并发重复推送 |

### 1.7 失败恢复

| 失败点 | 后果 | 自愈 |
|---|---|---|
| worker 进程崩溃,status 卡 processing | 活动卡壳 | cleanup 容器 5min 扫一次,超 10min 置 failed |
| rq BLPOP 后 fork 子进程前崩 | job 返回 retry 队列 | rq 重试 3 次,然后 dead letter |
| parse 异常 | status=failed + error_message | 用户可手动删除重传 |
| 粗筛后精确匹配某个 segment 异常 | SAVEPOINT 回滚,跳过此 segment | 其他 segment 不受影响 |
| notification detector 异常 | SAVEPOINT 回滚,跳过此事件 | 其他事件不受影响 |

### 1.8 不变式

**改动本链路代码时,以下约束不能破坏:**

1. worker 抢锁 SQL 必须带 `WHERE status='pending'`,不能无条件 UPDATE
2. parsing 纯函数绝对不能碰 DB/文件系统(ADR-008)
3. matcher 纯函数绝对不能碰 DB(ADR-008)
4. detector 判定逻辑如果抽成纯函数,历史数据由 caller 读好传入,不能碰 DB
5. trackpoints bulk_insert_mappings 批次 500,不能改回 session.add 循环(内存爆炸)
6. segment 匹配循环必须 SAVEPOINT 隔离,一个失败不能炸掉其他
7. notification 写入必须 SAVEPOINT 隔离,同上
8. status 转换只能按状态机箭头,禁止跨越(如 pending 直接 completed)
9. 解析失败必须把 `error_message` 写入 activity(字段名就是 `error_message`,不是 `last_error`),否则用户不知道为什么失败

### 1.9 ⚠️ agent 修改本链路时的强制自检

- [ ] 改了状态转换?检查 worker 抢锁 SQL 是否仍是原子的
- [ ] 加了新字段到 activities?是否走 Alembic 迁移
- [ ] 加了纯函数?是否真的不碰 DB/文件系统
- [ ] 改了 matcher?跑 fixture 测试,确认假阳/假阴率
- [ ] 加了新 event_type?detector 返回列表要加,notifications 表的 CheckConstraint(`event_type IN ('pr','kom','kom_lost')`) 要加
- [ ] 循环里有 flush?检查是否需要 begin_nested

---

## 2. 链路 2: Strava OAuth 绑定

### 2.1 触发

- 用户小程序"我的 → 连接 Strava"(v4 前端瘦身版未完整实现 UI,留第 5 期)

### 2.2 序列

```
[小程序]
  │
  ▼
[api]  GET /api/strava/authorize
  │    → app/strava/router.py:authorize
  │    → app/strava/service.py:generate_authorize_url
  │
  │ Step A: 生成 nonce (uuid4)
  │ Step B: 🔒 redis.set(f"strava:state:{nonce}", user_id, ex=600)
  │         TTL 10 分钟
  │ Step C: 组装 Strava 授权 URL:
  │   https://www.strava.com/oauth/authorize
  │   ?client_id=...
  │   &redirect_uri=https://api.velo.xxx/api/strava/callback
  │   &response_type=code
  │   &scope=read,activity:read_all
  │   &state={nonce}
  │
  │ 返回 { authorize_url }
  │
  │ (小程序端跳转 Strava)
  │
  ▼
[用户] 在 Strava 网页授权
  │
  ▼
[Strava] → GET /api/strava/callback?code=XXX&state=YYY
  │        → app/strava/router.py:callback
  │        → app/strava/service.py:handle_callback
  │
  │ Step 1: 🔒 user_id = redis.getdel(f"strava:state:{YYY}")
  │         一次性消费(防重放)
  │         ⚡ None → 400 "state 无效或已过期"
  │
  │ Step 2: POST https://www.strava.com/oauth/token
  │         exchange code → {access_token, refresh_token, expires_at, athlete}
  │
  │ Step 3: 🔒 事务内:
  │   SELECT FROM users WHERE strava_athlete_id = ? (换号检查)
  │   如果命中且 != 当前 user_id:
  │     → 清理旧 user 的 Strava 字段(防重复绑定)
  │     → UPDATE 旧 user 的进行中 activity:error_message='换号绑定:...'
  │   UPDATE users SET
  │     strava_athlete_id, strava_access_token, strava_refresh_token,
  │     strava_token_expires_at
  │     WHERE id = user_id
  │
  │ Step 4: 创建或复用 strava_imports:
  │   SELECT FROM strava_imports WHERE user_id=? AND status IN ('active','paused')
  │   命中 → UPDATE SET status='active', updated_at=now()
  │   未命中 → INSERT INTO strava_imports (user_id, strava_athlete_id, status='active')
  │   (表上无 UNIQUE(user_id) 约束,所以不能用 ON CONFLICT;
  │    同一 user 可能有多条历史 import 记录,但同时只有一条 active)
  │
  │ Step 5: 返回 HTML 成功页 + postMessage 到小程序 webview
```

### 2.3 幂等性

- state nonce:Redis GETDEL 保证一次性消费
- 重复点"连接 Strava":生成新 nonce,旧的 TTL 过期自然失效
- 同一 Strava 账号绑到新 velo 账号:Step 3 换号清理

### 2.4 不变式

1. state 必须 Redis 一次性消费(GETDEL),不能 GET + DEL 两步(有 race)
2. refresh_token 必须立即写 DB,不能只留内存
3. 重复绑定必须清理旧 user 的 Strava 字段

### 2.5 ⚠️ agent 注意

- `redis.getdel()` 返回 bytes,需要 `.decode()` 或直接判 `if value is None`(陷阱 #5)
- redirect_uri 代码里写不够,**Strava 后台也要配**(部署经验)
- 换号场景要测:用户 A 绑了 Strava → 解绑 → 用户 B 绑同一个 Strava
- strava_imports 表**无** `UNIQUE(user_id)`,所以 `INSERT ... ON CONFLICT (user_id)` 会报错;必须先 SELECT 再决定 UPDATE 或 INSERT

---

## 3. 链路 3: Strava 历史导入(scheduler)

### 3.1 触发

- scheduler 容器每 30 秒轮询 `⟳`

### 3.2 序列

```
[scheduler] ⟳ 每 30s → scheduler.py:main_loop
  │
  │ Step A: SELECT * FROM strava_imports
  │         WHERE status='active'
  │         ORDER BY updated_at ASC
  │         LIMIT 10  (一轮处理几个用户)
  │
  │ for each strava_import in 结果:
  │   ▼
  │   [app/strava/import_scheduler.py]
  │
  │   Step 1: 🔒 Redis 限速检查:
  │     redis.set(f"strava:ratelimit:{user_id}", 1, ex=1, nx=True)
  │     ⚡ 已存在 → 跳过此用户本轮
  │     (保证每 user 每秒 ≤ 1 次 Strava API 调用)
  │
  │   Step 2: ensure_valid_token(user_id) (见 §3.3)
  │
  │   Step 3: 根据 tier1 进度分流(tier1_completed 是 **int 计数器**,不是 bool):
  │
  │     tier1 未扫完 → _run_tier1(): 最近 30 天数据,高频批次
  │       GET /athlete/activities?after=<30天前>&page=<推算>
  │       返回 activity list
  │       for each activity:
  │         走链路 1 的 Step 2+(但 status='importing' 不是 'pending')
  │         data_source='strava', strava_activity_id=...
  │         复用 activity/worker.py:save_parse_result 落 DB
  │       更新 strava_imports:
  │         tier1_completed += 本批成功数
  │         如果 Strava 返回 < page_size → tier1 扫完,下轮进 tier2
  │
  │     tier1 扫完 → _run_tier2(): 历史数据,慢推
  │       同上,但 before 参数指向继续向历史的 cursor_before
  │       tier2_completed / tier2_skipped 各自累加
  │       cursor_before 推进
  │       直到 Strava 返回空 → SET status='completed'
  │
  │   Step 4: commit(含隐式 updated_at=now())
  │
  │ ⚡ 任何步骤 Strava 返回 429 → Redis 加退避计数,下轮跳过此用户
  │ ⚡ 401 → 清空 user 的 strava_*_token 字段,SET status='paused'
```

### 3.3 token 刷新子流程(Step 2 展开)

```
ensure_valid_token(user_id)
  → app/strava/service.py:ensure_valid_token

  🔒 SELECT * FROM users WHERE id=? FOR UPDATE  (行锁,v4 task-7.6 I8)

  ⚠️ 脆弱路径(tech-debt #3): strava_refresh_token is None → 抛"未绑定"

  if strava_token_expires_at - now() > 5 分钟:
    return (user, access_token)  # 仍有效,无需刷新

  POST https://www.strava.com/oauth/token
    grant_type=refresh_token, refresh_token=<旧>
    → {access_token, refresh_token, expires_at}

  UPDATE users SET
    strava_access_token, strava_refresh_token, strava_token_expires_at
  commit (释放行锁)

  return (user, 新 access_token)
```

### 3.4 状态机(StravaImport)

```
[不存在]
   │ OAuth 回调成功
   ▼
[active] ─── 用户手动暂停 ──► [paused]
   │          ◄── 用户继续
   │
   │ tier1 + tier2 都扫到 Strava 返回空
   ▼
[completed]
```

### 3.5 进度视图(/api/strava/import-progress)

前端轮询此接口,service 层聚合返回:
- `view_status`: `none` / `active` / `stalled` / `paused` / `completed`
- `tier1_completed`: **int 计数**(不是 bool;表字段是 int 计数器)
- `tier2_completed` / `tier2_skipped`: int
- `total_activities`: int(首扫列表后填,之前为 null)
- `total_imported`: service 层聚合字段 = tier1_completed + tier2_completed(不是表字段,看 service 实现)
- `stalled` 判定: `updated_at < now() - 5 分钟` 且 status='active' → 说明 scheduler 没在推

Redis 限速: 每 user 每秒 1 次查询(v4 task-7.5)。

### 3.6 幂等性

- scheduler 多实例同时跑:会竞争,但 Strava 限速和 `ORDER BY updated_at ASC` 让竞争退化为乱序。每 user 并发 ≤ 1 靠 Step 1 的 Redis SETNX 保证。
- tier1 重入:每次从 cursor 开始拉,已导入的 activity 会走 strava_activity_id UNIQUE 去重(activities.strava_activity_id unique),不会重复

### 3.7 不变式

1. scheduler 必须单实例部署(docker-compose 中只启一个 scheduler 容器)
2. Redis 限速必须 SET NX 且 TTL 精确 1 秒
3. token 刷新必须在行锁内,防并发刷出两套 token
4. 失败不能把 status 置为 `completed`

### 3.8 ⚠️ agent 注意

- scheduler 中 Redis 连接目前每次新建(tech-debt #5),第 5 期要复用全局 `_redis`
- **禁止** `datetime.utcnow()`,用 `datetime.now(timezone.utc)`
- 测试时 mock Strava API 不等于生产(见部署经验)
- Strava token 有效期 6 小时,refresh_token 不过期但可能被吊销
- `tier1_completed` 是 **int 计数器**,判断"扫完"看 scheduler 推进逻辑,不是读 `== True`

---

## 4. 链路 4: Strava Webhook 实时同步

### 4.1 触发

- 用户在 Strava 端新建/更新活动 → Strava 推 POST 到 velo webhook endpoint

### 4.2 序列

```
[Strava] POST /api/strava/webhook
  │ body: {object_type, aspect_type, owner_id, object_id,
  │        subscription_id, ...}
  ▼
[api] → app/strava/router.py:webhook_handler
  │
  │ Step 1: 校验 subscription_id (v4 task-7.4):
  │   if body.subscription_id != settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID:
  │     return 403
  │   (防伪造 webhook 攻击)
  │
  │ Step 2: 过滤:
  │   if object_type != 'activity' or aspect_type != 'create':
  │     return 200 (忽略,只处理新建)
  │
  │ Step 3: SELECT user FROM users WHERE strava_athlete_id = body.owner_id
  │   ⚡ 未找到 → 200(可能是已解绑用户的遗留 webhook,忽略)
  │
  │ Step 4: ensure_valid_token(user.id)
  │
  │ Step 5: GET https://www.strava.com/api/v3/activities/{body.object_id}
  │   → 取完整 activity 数据 + streams(轨迹流)
  │
  │ Step 6:
  │   INSERT activities (user_id, strava_activity_id=body.object_id,
  │                      data_source='strava', status='importing', ...)
  │   去重兜底:UNIQUE(strava_activity_id) 约束
  │   ⚡ IntegrityError → 已导入过,返回 200
  │
  │ Step 7: 同步执行链路 1 的 Step 5~10:
  │   解析 → 写 trackpoints → 写 activity 统计 → status='completed'
  │   → 触发 auto_match → 触发 notification
  │
  │ (注意:webhook 不入 rq 队列,直接在 api 进程同步处理,
  │  因为 Strava 需要 2 秒内 200 响应)
  │
  │ 返回 200
```

### 4.3 ⚠️ 危险点

- Strava 要求 webhook 2s 内响应。如果同步处理超时,Strava 会重试、最终放弃订阅。**Step 5-7 总耗时必须 < 1.5s**,否则考虑分拆:只写 status='importing' + 入 rq 队列,后续异步处理
- subscription_id 只有一个(整个 velo app 一个),泄漏等于所有用户的 webhook 都能伪造

### 4.4 不变式

1. subscription_id 校验是第一道门,不校验等于放弃 webhook 安全
2. webhook 绝对不在 DB 事务外调 Strava API(避免长事务 holding 锁)
3. 失败只 log,不抛异常给 Strava(否则会被标记不健康然后吊销订阅)

---

## 5. 链路 5: 微信登录 → JWT

### 5.1 触发

- 小程序冷启动 或 JWT 过期 401

### 5.2 序列

```
[小程序]
  │ wx.login() → 拿 5 分钟 TTL 的 code
  ▼
[api] POST /api/user/login  body: {code}
  │ → app/user/router.py:login
  │ → app/user/service.py:login_or_register
  │
  │ Step 1: GET https://api.weixin.qq.com/sns/jscode2session
  │   ?appid=<>&secret=<>&js_code={code}&grant_type=authorization_code
  │   → {openid, session_key, unionid?}
  │   ⚡ errcode != 0 → 400 "微信登录失败"
  │   (微信返回的 unionid 当前被丢弃;users 表无 unionid 字段)
  │
  │ Step 2: SELECT * FROM users WHERE openid=?
  │   找到 → is_new=false, user=现有
  │   没找到 → INSERT + is_new=true
  │
  │ Step 3: 签 JWT:
  │   payload: {user_id, iat, exp}  exp=now+7天
  │   sign with settings.JWT_SECRET (HS256)
  │
  │ 返回 { token, user, is_new }
```

### 5.3 后续请求鉴权

```
小程序每个请求 Header: Authorization: Bearer <token>
[api] JWT 中间件:
  校验签名 + exp
  ⚡ 过期 → 401 { code: 'TOKEN_EXPIRED' }
  成功 → 注入 request.state.user_id → 路由处理函数通过 Depends(get_current_user)

小程序 interceptor 拿到 401:
  静默调 wx.login() 重来 → 存新 token → 重试原请求
```

### 5.4 不变式

1. JWT_SECRET 必须 env var,不能 hardcode,不能进 git
2. 过期时间 7 天,过短引起频繁 re-login,过长引起泄漏风险
3. 前端 interceptor 必须处理 401 静默续期,不能弹"请重新登录"

### 5.5 ⚠️ agent 注意

- 微信 code 5 分钟 TTL,前端拿到必须立即发送不能缓存
- **users 表无 `unionid` 字段**,微信返回的 unionid 当前被丢弃。如未来需要跨 appid 识别用户,需加字段 + 迁移

---

## 6. 链路 6: 通知读取 + 标读

### 6.1 首页红点(高频,每次 onShow)

```
[小程序 home.onShow]
  │
  ▼
GET /api/notifications?unread_only=true&page_size=1
  │
  │ → app/notification/service.py:get_notifications
  │
  │ Step 1: SELECT COUNT(*) FROM notifications
  │         WHERE user_id=? AND is_read=false
  │         (用部分索引 idx_notifications_user_unread WHERE is_read=FALSE)
  │
  │ Step 2: SELECT * FROM notifications
  │         WHERE user_id=? AND is_read=false
  │         ORDER BY created_at DESC LIMIT 1
  │
  │ 返回 {
  │   items: [最新 1 条或空],
  │   unread_count: <count>  ← 响应永远带此字段(v4)
  │ }
  ▼
[小程序] 根据 unread_count 显示/隐藏铃铛红点
```

### 6.2 进入通知中心

```
[小程序 铃铛点击]
  │
  │ 并行两个请求:
  │
  ├─► GET /api/notifications  (全列表,page=1, page_size=20)
  │   → 返回 items + unread_count
  │
  └─► POST /api/notifications/mark-all-read
      │
      │ → app/notification/service.py:mark_all_read
      │
      │ UPDATE notifications
      │   SET is_read=true
      │   WHERE user_id=? AND is_read=false
      │   → rowcount 即本次标读数(幂等:二次调用 rowcount=0)
      │
      │ 返回 { marked: N }

[小程序]
  │ 列表返回后渲染
  │ mark-all-read 返回后不需要刷新,UI 本地立即把所有条目变灰
  │ (先视觉化后端确认,更顺滑)
```

### 6.3 点击某条通知

```
[小程序] 通知条目 onTap
  │
  │ wx.navigateTo '/pages/leaderboard?segment_id={item.segment_id}'
  │
  ▼
[leaderboard.js onLoad(options)]
  │ segment_id = options.segment_id
  │ GET /api/segments/{segment_id}/leaderboard
  │ 渲染排行榜,定位并高亮当前用户记录(v4 批 8 双审修复)
```

### 6.4 幂等性

| 操作 | 幂等性 |
|---|---|
| mark-all-read | 幂等,第二次 rowcount=0 |
| GET notifications | 纯读,天然幂等 |

### 6.5 ⚠️ agent 注意

- `unread_count` 响应字段必须永远带,**不能根据 `unread_only` 参数决定带不带**(v4 task-7.8 的核心)
- `is_read` 是 bool,查询用 `== False` 或 `is False`,不能 `not is_read`(truthiness 陷阱 #1,NULL 会错判)
- 部分索引 `WHERE is_read=false` 只服务这一种查询,加了其他条件会走全表
- `/api/notifications` 当前 **只支持** `page` / `page_size` / `unread_only` 三个 query 参数,**不支持** `activity_id` / `event_type` 过滤。如果未来要按 activity / event_type 筛,需加 query 参数(tech-debt 候选)

---

## 7. 链路 7: 骑行详情页数据聚合

### 7.1 触发

- 小程序任何地方点击活动卡片 → 跳 detail 页

### 7.2 序列

```
[小程序 pages/detail.onLoad]
  │ activity_id = options.id
  │
  │ 并行 3 个请求(PR/KOM 徽章由 3 的返回 + 单独拉通知列表本地过滤):
  │
  ├─► GET /api/activities/{id}
  │   返回活动完整数据,含 simplified_track 画地图
  │
  ├─► GET /api/activities/{id}/timeseries
  │   返回速度/功率/心率时间序列,画图表
  │
  └─► GET /api/activities/{id}/segments
      → app/segment/router.py:get_activity_segments (activity_segment_router 挂载)
      SQL(真实代码,app/segment/service.py:get_activity_segments):
        SELECT se.segment_id, s.name, se.elapsed_time, se.avg_speed, se.avg_power
        FROM segment_efforts se
        JOIN segments s ON se.segment_id = s.id
        WHERE se.activity_id = ?
        ORDER BY se.start_index  ← 按轨迹 seq 顺序,不是 started_at
      service 层再循环算 rank(N+1 查询,tech-debt)
      返回: [{segment_id, segment_name, elapsed_time, rank, ...}]

  │ PR/KOM 徽章当前的真实做法:
  │   (由于 /api/notifications 不支持 activity_id/event_type 过滤)
  │   拉 /api/notifications?page_size=N 拿最近通知列表 →
  │   前端本地按 activity_id 和 event_type in ('pr','kom') 过滤 →
  │   合并到 segment 卡片上显示徽章
  │
  │ 渲染:地图 + 海拔 + 数据面板 + 经过赛段列表(带徽章)
```

### 7.3 为什么 PR/KOM 要前端 join

**ADR-004 决策**:PR/KOM 是**事件**,不是**状态**。
- 事件存 notifications 表(含时间、is_read、快照等事件属性)
- 状态(成绩数值)存 segment_efforts 表
- 两者不耦合,防止 notifications 表增长影响 effort 查询性能,也方便通知被标读/删除不影响成绩

**代价**: 前端要自行聚合两个接口结果,多一次网络请求。可接受,因为活动详情页一般是用户主动打开的慢操作。

### 7.4 ⚠️ agent 注意

- segment_efforts 表**没有** `is_pr` / `is_kom` 字段,想当然加会被 ADR-004 双审打回
- segment_efforts 表**没有** `started_at` / `avg_heart_rate` 字段,需要骑行开始时间要 JOIN activities.started_at,需要心率要看 trackpoints
- `/api/activities/{id}/segments` 的路由归属:路径前缀是 activities 但语义归 segment 模块,route 定义在 segment 模块的 `activity_segment_router`(main.py 挂载)
- `/api/notifications` 暂不支持按 activity_id / event_type 过滤,前端 join 用本地过滤,别自造 query 参数

---

## 8. 链路 8: 赛段详情与排行榜

### 8.1 赛段列表(探索/附近搜索)

```
GET /api/segments?near_lat=<>&near_lon=<>&radius=5000&page=1&page_size=20
  │
  │ → app/segment/service.py:get_segment_list
  │
  │ SQL:
  │   SELECT * FROM segments
  │   WHERE ST_DWithin(
  │     reference_line::geography,
  │     ST_SetSRID(ST_MakePoint(?, ?), 4326)::geography,
  │     ?  -- radius 米
  │   )
  │   ORDER BY ST_Distance(...) ASC
  │   LIMIT ? OFFSET ?
  │
  │ GIST 索引 idx_segments_geom(reference_line) 加速
```

⚠️ 索引名是 `idx_segments_geom`,不是 `idx_segments_reference_line`。

### 8.2 赛段详情 + TOP20

```
GET /api/segments/{id}
  │
  │ Step 1: SELECT * FROM segments WHERE id=?
  │
  │ Step 2 (嵌入 TOP20 榜):
  │   SELECT se.*, u.nickname, u.avatar_url
  │   FROM segment_efforts se
  │   JOIN users u ON se.user_id = u.id
  │   WHERE se.segment_id = ?
  │   ORDER BY se.elapsed_time ASC
  │   LIMIT 20
  │   ⚠️ N+1 风险(tech-debt):如果每条 effort 还要查其他字段循环,会爆
  │
  │ Step 3 (我的成绩,如登录):
  │   SELECT * FROM segment_efforts
  │   WHERE segment_id=? AND user_id=<current>
  │   ORDER BY elapsed_time ASC LIMIT 1  -- PR
  │
  │ 返回 { segment, top20, my_pr }
```

### 8.3 完整排行榜(分页)

```
GET /api/segments/{id}/leaderboard?page=1&page_size=50&bike_type=road
  │ 与 §8.2 Step 2 相同查询但带分页 + 车型过滤
```

### 8.4 我的所有成绩

```
GET /api/user/efforts
  │
  │ → app/segment/service.py:get_user_efforts (真实 SQL):
  │   SELECT se.segment_id, s.name, se.elapsed_time, se.avg_speed, se.created_at
  │   FROM segment_efforts se
  │   JOIN segments s ON s.id = se.segment_id
  │   WHERE se.user_id = <current>
  │   ORDER BY se.created_at DESC  ← 按成绩写入时间倒序,segment_efforts 无 started_at
  │   (service 层再对每条循环算 rank,N+1 tech-debt)
  │   注:此接口当前无 page/page_size 参数,一次返回全量
```

### 8.5 ⚠️ agent 注意

- 索引 `idx_efforts_segment_user_time(segment_id, user_id, elapsed_time)` 服务 §8.2 §8.3 所有查询
- 排名计算(`rank`)目前由 service 层循环算,N+1,tech-debt
- segment_efforts 无 `started_at` 字段,排序只能用 `created_at`(写入时间)或 JOIN activities 拿骑行时间

---

## 9. 链路 9: cleanup 僵尸扫描

### 9.1 触发

- cleanup 容器 `⟳` 每 300 秒

### 9.2 序列

```
[cleanup] ⟳ 每 5 分钟 → scripts/cleanup_zombies.py (脚本在 scripts/,不是根目录)
  │
  │ Step 1: 扫描卡死 activities
  │   UPDATE activities
  │   SET status='failed',
  │       error_message='解析超时,请重新上传',
  │       updated_at=now()
  │   WHERE status='processing'
  │     AND updated_at < now() - interval '10 minutes'
  │   RETURNING id
  │
  │ Step 2: log "置 failed 的 activities: [N, M, ...]"
  │
  │ ⚠️ 目前**不**清理孤儿文件(tech-debt):
  │   如果 activity 上传成功但 DB 插入失败 → /uploads 目录下有孤儿
  │   需要另一个清理任务
```

docker-compose 里 cleanup 容器启动命令是 `sh -c "while true; do python scripts/cleanup_zombies.py; sleep 300; done"`。

### 9.3 不变式

1. cleanup 只能向 failed 转换,不能向其他状态转
2. 10 分钟阈值来自历史经验,改动要谨慎(过短误杀正在解析的大文件)
3. 必须单实例部署
4. 字段名是 `error_message` 不是 `last_error`

### 9.4 ⚠️ agent 注意

- cleanup 不参与 Strava importing 状态的清理(importing 是 Strava 路径,需要单独处理,tech-debt)
- 孤儿文件清理是 tech-debt 里的独立工作,不在 cleanup 容器职责内

---

## 链路 10：AI 草稿生成（v5 task-1.B.1 / 5.B.2）

### 10.1 触发

admin H5 后台两条入口：
- POST `/admin/segments/{id}/ai-drafts`（直接生成）
- PATCH `/admin/curation-pool/{id}` selected=true（候选池勾选触发）

### 10.2 序列

```
admin endpoint → app.queue.ai_drafts_queue.enqueue('app.agent.tasks.generate_segment_draft_task', segment_id)
                 ↓ 返 202 不阻塞
worker（订阅 ai_drafts 队列）拿到 job
  ↓ generate_segment_draft_task(segment_id)
  ↓ SessionLocal() open db
  ↓ 查 Segment 不存在 → log + return
  ↓ 组装 segment_props 6 字段（兜底 '未知' / 0）
  ↓ 调 segment_writer.generate_segment_draft(props)
     ↓ DeepSeek API（OpenAI 兼容 SDK / base_url=api.deepseek.com）
     ↓ 任何失败返空字符串（无 key / 网络 / 嵌套字段缺）
  ↓ ai_text 空 → log + return（避免 RQ 重试浪费配额）
  ↓ UPSERT segment_ai_drafts:
     - existing.status='pending' → 覆盖 ai_draft_text
     - existing.status in (human_edited / approved / rejected) → log + skip 保护
     - 不存在 → 新建 status='pending'
  ↓ commit / IntegrityError 兜底 rollback + log
  ↓ db.close()
```

### 10.3 状态机

```
(无草稿) ──[task]──▶ pending ──[admin 改稿]──▶ human_edited ──[主管批]──▶ approved
                       │                                              │
                       │                            [主管打回]──────▶ rejected
                       │
                       └──[task 重跑]──▶ pending（覆盖）
                            （human_edited / approved / rejected 不被覆盖）
```

### 10.4 不变式

- `segment_id UNIQUE` 约束保证一段赛段一份草稿
- 失败路径不抛异常给 RQ（避免重试浪费 DeepSeek 配额）
- agent 模块**不反向 import** 业务模块 service（ADR-009 边界）
- 真实 API key 仅在生产 `.env`，不进 git

### 10.5 ⚠️ agent 注意

- DEEPSEEK_API_KEY 必须同步 4 处：`app/config.py` / `.env.example` / `docker-compose.yml` worker / `docker-compose.dev.yml` worker —— 漏一处生产 worker 容器内 `_client = None` 静默不工作（task-1.B.1 codex 抓的 Critical）

---

## 链路 11：worker 软目标监控（v5 task-1.C.1 / 5.7.1）

### 11.1 触发

`monitor` 容器 `while true; sleep 60` 每 60 秒跑一次 `python -m app.monitor.processing_health`。

### 11.2 序列

```
monitor 容器 cron → main()
  ↓ SessionLocal() open db
  ↓ scan_processing_health(db):
     ↓ now = datetime.now(timezone.utc) / cutoff = now - 4min
     ↓ 查 Activity WHERE status='processing' AND updated_at < cutoff
     ↓ 无命中 → 返 [] / 退码 0
     ↓ 有命中 → 渲染告警文本（含 id / user_id / elapsed）
        ↓ FEISHU_BOT_WEBHOOK 未配 → log warning + 返 stuck_ids
        ↓ 已配 → httpx.post(webhook, json=..., timeout=5)
                 → response.raise_for_status() 让 4xx/5xx 抛 HTTPStatusError
                 → catch 任何异常 → log error 不阻断
        ↓ 返 stuck_ids（退码 1）
  ↓ db.close()
```

### 11.3 与 cleanup 的区别

| 维度 | monitor（v5 / 软目标）| cleanup（v0 / 硬上限）|
|---|---|---|
| 阈值 | 4 分钟（PRD 5.7.1 / 80% 软告警）| 10 分钟（v4 _PROCESSING_TIMEOUT）|
| 周期 | 60 秒 | 300 秒 |
| 动作 | 推飞书告警，**不改业务** | 批量置 `failed`，**自愈** |
| 失败影响 | 我们三人收不到告警，业务正常 | 僵尸 activity 越积越多 |

### 11.4 不变式

- monitor **只读** activities 表 / **不改** status / `_PROCESSING_TIMEOUT` 沿用 v4 不动
- 飞书 webhook 失败（含 5xx 响应）catch 后仍返 stuck list（让 cron 退码反映状态）
- httpx 不用 requests（项目统一）/ 用 `raise_for_status()` 显式让 5xx 抛

---

## 链路 12：用户功率曲线查询 + 缓存（v5 task-2.C.2 / 5.C.2）

> **router 在 task-2.C.3 才暴露**——链路记录 service 层完整路径，router 跑通时回填 endpoint。

### 12.1 触发

- （未来）用户进个人主页 → "功率曲线"卡片 → 前端调 `GET /api/user/power-curve?period=this_month`
- worker 完成 activity 解析后，自动 `invalidate_power_curve_cache(user_id)` 清缓存（链路 1.4.5 Step 10.5 后续）

### 12.2 序列：cache hit（90% 路径）

```
[api]  GET /api/user/power-curve?period=this_month  (router 待 2.C.3)
  ↓ user.service.get_user_power_curve(db, user_id, period)
  ↓ cache_key = f"power_curve:user_{user_id}:period_{period}"
  ↓ cached = redis_conn.get(cache_key)  # bytes（redis-py 7+ 默认）
  ↓ if cached is not None:
       return json.loads(cached.decode())  # 直接返回，不查 DB
  ↓ p95 < 50ms（仅 1 次 Redis GET）
```

### 12.3 序列：cache miss（10% 路径 / 首次 / 过期 / 失效后）

```
[api]  cache miss
  ↓ start, end = _power_curve_period_window(period)
     period 5 档：this_month / last_month / this_year / last_year / all_time
     ⚠️ 用 BJ_TZ +8 划月（CLAUDE.md 时区约定 / 与链路 1.4.5 detector 共用辅助函数）
     跨年特例：1 月 last_month → 上一年 12 月
  ↓ activity_ids = SELECT Activity.id WHERE user_id=? AND status='completed'
                   AND started_at >= start AND started_at < end
  ↓ for each act_id:
       tps = SELECT Trackpoint WHERE activity_id=act_id ORDER BY seq
       activities_trackpoints.append(tps)
  ↓ curve_int_key = calculate_power_curve_from_activities(activities_trackpoints) ✨ 纯函数
     ⚠️ 禁止跨 activity 拼接 trackpoints（破坏"5min 最佳"语义）
     算法：每 activity 独立 calculate_power_curve，再 per-window 取 max
  ↓ curve = {str(k): v for k, v in curve_int_key.items()}
     ⚠️ JSON int→str key 转换：calculate_power_curve_from_activities 返 dict[int → float]，
     但 JSON.dumps 把 int key 转 str → cache hit 反序列化得 str key →
     调用方两次拿到不同类型 dict。service 层统一转 str（与 FastAPI JSON 协议一致）。
  ↓ result = {"period": period, "buckets": curve}
  ↓ redis_conn.setex(cache_key, 3600, json.dumps(result))  # TTL 1h
  ↓ return result
```

性能：100k trackpoints × 6 windows ≈ 32ms（O(n) per window 前缀和），p95 < 300ms。

### 12.4 序列：缓存失效（worker 完成 activity 后调）

```
worker 完成 activity → activity.status='completed' → 调用：
  ↓ user.service.invalidate_power_curve_cache(user_id)
  ↓ pattern = f"power_curve:user_{user_id}:*"
  ↓ for key in redis_conn.scan_iter(match=pattern):
       redis_conn.delete(key)
  ↓ p95 < 100ms（每 user 至多 5 个 period key）
```

⚠️ scan_iter 不是 keys：`KEYS power_curve:*` 在大 Redis 上会阻塞数十秒（生产事故级），
scan_iter 是 cursor 模式，不阻塞，对全库友好。

### 12.5 失败恢复

| 失败点 | 后果 | 自愈 |
|---|---|---|
| invalidate 时 Redis 不可用 | 缓存陈旧（看不到刚上传的活动）| 1h TTL 自然过期兜底（spec 决定接受陈旧 < 1h）|
| cache miss 路径 DB 查询慢 | API 慢 | activities 表已有 `(user_id, status, started_at)` 索引 |
| user A 失效误清 user B | 不会，pattern `power_curve:user_{A_id}:*` 冒号边界（user_10 不误中 user_100） | 测试 `test_invalidate_does_not_touch_other_users` 真验证 |

### 12.6 不变式

- service 层返回 `{"period": str, "buckets": dict[str, float]}`，**str key 不是 int key**（cache hit / miss 类型一致）
- **跨 activity 必须用 `_from_activities` 不直接拼 trackpoints**（破坏"5min 最佳"语义）
- "本月 / 本年" 一律按 BJ_TZ 划分（与 progress detector 共用 `_power_curve_period_window`）
- 应用层 `if cached is not None` 不用 truthy（CLAUDE.md 陷阱 #1 / 防空字符串误判 cache miss）

---

## 链路 13：城市热图 + PATCH 改 city（v5 task-2.C.2/C.3 / 5.A.1）

### 13.1 触发

- 用户进个人主页"城市热图"卡片 → 前端调 `GET /api/user/me/heatmap?city=beijing`
- 用户在 settings 改主城市 → 前端调 `PATCH /api/user/me` body `{"city": "shanghai"}`
- worker 完成 activity 解析自动推断 city（链路 1.4.6 / 仅 `user.city is None` 时）

### 13.2 GET /api/user/me/heatmap 序列

```
[api]  GET /api/user/me/heatmap?city=beijing  Auth: Bearer JWT
  ↓ schema 校验：city ∈ UserCity 7 枚举（不在 → 422）
  ↓ user.service.get_user_heatmap(db, user_id, "beijing")
  ↓ cache_key = f"heatmap:user_{user_id}:city_beijing"
  ↓ cached = redis_conn.get(cache_key)
  ↓ if cached is not None: return json.loads(...)  # cache hit p95 < 50ms
  ↓ cache miss 路径：
     ↓ activities = SELECT Activity WHERE user_id=? AND status='completed'
                    AND simplified_track IS NOT NULL
     ↓ filtered = [a for a in activities if infer_city_from_coords(a.simplified_track[0]) == city]
     ↓ tracks = [[[lon, lat] for pt in a.simplified_track] for a in filtered]  # D27 v2 polish 保留 activity 边界
     ↓ result = {"city", "tracks": tracks, "activity_count"}
     ↓ redis_conn.setex(cache_key, 3600, json.dumps(result))
  ↓ return tracks（前端画 polyline / 多条 opacity 重叠自然热力效果）
```

性能：500 用户 × 30 activity × 80 simplified 点 = 1.2M 点。聚合后端单次 < 1s（按 user_id 索引筛）。Redis 缓存 TTL 1h。

### 13.3 PATCH /api/user/me 序列（改 city）

```
[api]  PATCH /api/user/me  body={"city": "shanghai"}
  ↓ schema UserPatchRequest 校验（city ∈ UserCity 7 枚举 + None / 不传不改 / B2B-6 设计：与 PUT /profile 分开）
  ↓ body.model_dump(exclude_unset=True, mode="json")
     ↓ "未传 city" → 'city' not in update_data → 不调 service.update_user_city
     ↓ "传 city=null" → update_data['city'] is None → 调 service 传 None（清空 user.city）
     ↓ "传枚举值" → update_data['city'] = "shanghai" → 调 service 更新
  ↓ service.update_user_city(db, user_id, city):
     ↓ if city not in {7 枚举} and city is not None → ValueError("invalid city")
     ↓ user = db.query(User).filter(User.id == user_id).first()
     ↓ if not user → ValueError("user not found") → router 翻 404
     ↓ user.city = city / db.commit()
     ↓ 失效 heatmap 缓存：scan_iter("heatmap:user_{user_id}:*") + delete
  ↓ 返回最新 user（schemas.UserProfile / 沿用现有）
```

### 13.4 worker 自动推 city 子流程（链路 1.4.6 详细）

worker.py 步骤 10.6（status='completed' 后、db.commit 前）：

```
🔒 SAVEPOINT 隔离（CLAUDE.md 陷阱 #13 / 与 progress_detector 同 pattern）：
nested_city = db.begin_nested()
try:
    user = SELECT User WHERE id=user_id
            FOR UPDATE                    # 行锁防并发重复推断
            populate_existing()           # 陷阱 #12：刷新 identity map 防 stale
    if user.city is None and activity.simplified_track:
        first_pt = activity.simplified_track[0]
        if first_pt.lat / lon 都不为 None:
            user.city = infer_city_from_coords(lat, lon)  # 6 主城 / 'unknown'
    db.flush()  # 强制 INSERT/UPDATE 触达 DB（SAVEPOINT 内）
    nested_city.commit()
except Exception:
    nested_city.rollback()  # 失败只回退 SAVEPOINT，外层 activity.status / notification 不受影响
```

### 13.5 失败恢复

| 失败点 | 后果 | 自愈 |
|---|---|---|
| invalidate heatmap 时 Redis 不可用 | 缓存陈旧 | 1h TTL 自然过期兜底 |
| infer_city_from_coords 返 'unknown' | user.city = 'unknown' | 用户可手动 PATCH /me 改正 |
| worker city hook 内 DB 异常 | SAVEPOINT 回退 / activity 仍 completed | 下次上传新 activity 重试 |

### 13.6 不变式

- `user.city is None` 是触发条件（**不能用 truthy / 'unknown' 也是 truthy**——CLAUDE.md 陷阱 #1）
- 6 主城 + 'unknown' 7 枚举 = `_VALID_USER_CITIES` = `UserCity` enum = `ck_users_city` CHECK 约束（四方一致）
- **跨模块 SAVEPOINT 隔离**：worker city hook 失败不影响外层 activity / notification（陷阱 #13）

---

## 链路 14：看他人主页（v5 task-2.C.3 / 5.A.2）

### 14.1 触发

用户在 feed / 排行榜点击其他用户头像 → 跳转 user profile 页 → 前端调 `GET /api/user/{user_id}/profile`

### 14.2 序列

```
[api]  GET /api/user/{user_id}/profile  Auth: Bearer JWT
  ↓ get_current_user 解 JWT → requester_user_id
  ↓ user.service.get_user_profile_for_others(db, target_user_id, requester_user_id):
     ↓ target = SELECT User WHERE id=target_user_id
     ↓ if not target → ValueError("用户不存在") → router 翻 404
     ↓ totals = SELECT SUM(distance) / SUM(elevation_gain) / COUNT(id)
                FROM activities WHERE user_id=target AND status='completed'
     ↓ now_bj = now_utc.astimezone(BJ_TZ +8)
     ↓ first_of_month_utc = first_bj_month.astimezone(UTC)
     ↓ current_month = SELECT SUM(distance) / SUM(elevation_gain) / AVG(avg_power)
                       FROM activities WHERE user_id=target AND status='completed'
                       AND started_at >= first_of_month_utc
     ↓ raw_response = {id, nickname, avatar_url, city, ftp, bike_type,
                       total_distance_km, total_elevation_m, activity_count,
                       current_month_summary={distance_km, elevation_m, avg_power_w}}
     ↓ return _filter_profile_keys(raw_response)
              ↓ {k: v for k, v in raw_response.items() if k in _PROFILE_RESPONSE_KEYS}
  ↓ FastAPI 用 UserProfileResponse 序列化（schema 双层白名单 / Pydantic v2 默认 extra='ignore'）
  ↓ 前端拿到的 JSON 严格 10 字段
```

### 14.3 D-P08 红线"看自己 = 看他人"

`requester_user_id` 参数仅占位（v6 隐私开关预留）。当前**不区分** self / others：
- 看自己 ID 跟看他人**字段集合完全一致**
- 测试 `test_self_vs_others_same_field_set` 防回退

### 14.4 双层白名单（service + schema）

| 层 | 实现 | 防回退 |
|---|---|---|
| service | `_filter_profile_keys` 白名单 dict 推导式 | 测试反向构造含敏感字段的 raw_response → 验证被过滤 |
| schema | `UserProfileResponse` 严格 10 字段 / Pydantic v2 默认忽略多余 | 测试 mock service 返回含 openid → schema 过滤 |

任一层被破坏（删推导式 / 改 schema 加敏感字段），测试立即抓。

### 14.5 严格不返字段（D-P08 红线）

efforts / activities 列表 / heatmap / strava_access_token / strava_refresh_token / openid / mute_notifications / weight / weekly_goal / 任何 token

### 14.6 不变式

- `_PROFILE_RESPONSE_KEYS` 集合本身不应包含敏感字段名（元防回退测试）
- 改白名单字段时**必须同步**：service `_PROFILE_RESPONSE_KEYS` ↔ schema `UserProfileResponse` 字段
- BJ_TZ 划"本月"（与 link 12 power_curve / link 1.4.5 detector 一致）

### 14.7 v5 task-4.3 扩展：看他人 power-curve / heatmap

Sprint 4 task-4.3（commit `5de9f40` + `203ed44`）加 2 个看他人 endpoint：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/user/{user_id}/power-curve?period=` | 复用 `service.get_user_power_curve` / 看他人 = 同函数 + 不同 user_id |
| GET | `/api/user/{user_id}/heatmap?city=` | 复用 `service.get_user_heatmap` / city 同 v3 polish 改可选 |

合规：上面"严格不返字段"是 profile schema 的 D-P08 红线；power-curve / heatmap 不属 profile，
看自己看他人字段集合一致 → 设计上即"公开" → 直接放行。

---

## 链路 15：赛段创建（v5 task-3.A.5 + 3.A.6 / 5.B.1 + 5.D.4 + 5.D.6）

### 15.1 触发

admin H5 三个入口：
- POST `/api/admin/segments/from-gpx` — 上传 GPX 子段 → 计算 → 入库（task-3.A.6 / commit `1432fad`）
- POST `/api/admin/segments/from-activity` — 选已有 activity 的 trackpoint 范围 → 入库（task-3.A.5 / commit `8be37e3`）
- segment-creator.html 工具内调上面两个 endpoint（task-3.B.2 / 搬到 admin-h5 repo / commit `c01b7fd` + admin-h5 `71de031`）

老 endpoint `POST /api/segments` 与 `DELETE /api/segments/{id}` 已 deprecated（router.py 顶部 `deprecated=True` / Sunset 2026-06-30 / 沉淀 tech-debt）。

### 15.2 from-gpx 序列（task-3.A.6）

```
[admin H5]  前端 segment-creator.html 用 gpxpy 解析 .gpx 文件 → 提取 trackpoints
            POST /api/admin/segments/from-gpx
            JSON body: { name, description, reference_points: list[{lat, lon}], coordinate_system }
  ↓ require_admin 依赖
  ↓ admin.service.create_from_gpx(db, body):
     ↓ 接收前端解析后的 trackpoints（不在后端跑 gpxpy / 后端不收 .gpx 文件）
     ↓ 计算字段（app/segment/algorithms.py 纯函数）：
        - distance（haversine 累计）
        - elevation_gain / elevation_loss
        - avg_gradient / max_gradient（100m 滑窗）
        - elevation_profile（80 点采样）
        - difficulty（4 档枚举）
        - city（infer_city_from_coords / common.geo）
     ↓ wkt = build_linestring(...)
     ↓ _check_hausdorff_overlap(db, wkt) ✨ 共享 helper（task-3.A.6 抽 / from-gpx + from-activity 共用）
        ✨ dialect 守卫：if db.bind.dialect.name == "postgresql"
        ✨ ST_HausdorffDistance(reference_line, ST_GeomFromText(?, 4326)::geography) < 100
        ⚡ 命中 → raise SegmentOverlapError("已有 segment id=N 高度重叠") → router 翻 409
        ⚠️ SQLite 测试 fixture 跳过（陷阱清单 #15）
     ↓ INSERT segments（含全部 v5 字段）
     ↓ db.commit() → segment_id
  ↓ 返 201 + SegmentResponse
```

### 15.3 from-activity 序列（task-3.A.5）

```
[admin H5]  POST /api/admin/segments/from-activity body={activity_id, start_index, end_index, name, ...}
  ↓ require_admin
  ↓ admin.service.create_from_activity:
     ↓ 🔒 advisory lock：pg_advisory_xact_lock(hashtext('segment-create-from-activity'))（**全局 hash 字符串** / service_create.py:201 / 全 from-activity 调用串行 / 不是 per-activity）
     ↓ tps = SELECT Trackpoint WHERE activity_id=? AND seq BETWEEN start AND end ORDER BY seq
     ↓ if len(tps) < 10 → InvalidSegmentRangeError → router 翻 422
     ↓ 同 from-gpx 算字段
     ↓ 同 from-gpx 跑 _check_hausdorff_overlap（共享 helper）
     ↓ INSERT segments（advisory lock 自动随事务释放）
  ↓ 返 201
```

### 15.4 关键陷阱

| # | 陷阱 | 防御 |
|---|------|------|
| 1 | PostGIS `ST_*` 在 SQLite fixture 不可用（陷阱 #15）| `_check_hausdorff_overlap` 加 dialect 守卫 + 单测 mock dialect.name = "postgresql" |
| 2 | from-activity 并发 → 多 segment 并发写 | pg_advisory_xact_lock(hashtext('segment-create-from-activity')) **全局串行**所有 from-activity 调用 / 不是 per-activity / 简单稳妥 |
| 3 | 双路径重复算字段 = 复制粘贴风险 | 算法函数全在 `app/segment/algorithms.py` 纯函数 + 共享 helper |
| 4 | GCJ-02 vs WGS-84 坐标系混 | gpx 默认 WGS-84 / activity trackpoint 也是 WGS-84 / 入库前不转 |

### 15.5 不变式

- 全部 admin 创建路径走 require_admin 依赖（用户路径**永久禁止**创建 segment）
- 算字段函数纯函数 / 不碰 DB / 测试不挂 fixture
- Hausdorff 阈值 100m（spec §3.7 拍）/ 改阈值同时改测试 + 文档

---

## 链路 16：即时反馈（v5 task-1.A.3 / 5.C.1）

### 16.1 触发

用户在小程序赛段详情页打开某条赛段 → 前端调 `GET /api/segments/{segment_id}/efforts/me` → 展示"上次 vs PR vs 本次差值"6 字段。

### 16.2 序列

```
[api]  GET /api/segments/{segment_id}/efforts/me  Auth: Bearer JWT
  ↓ get_current_user 解 JWT → user_id
  ↓ router 显式查 segment 不存在 → 404（防 service 静默返 None）
  ↓ segment.service.get_my_effort_with_compare(db, segment_id, user_id):
     ↓ efforts = SELECT SegmentEffort WHERE segment_id=? AND user_id=?
                 ORDER BY created_at DESC LIMIT 100
     ↓ if not efforts → return {"current": None, "last": None, "pr": None,
                                 "diff_seconds": None, "is_pr": False, "is_first": True}
     ↓ current = efforts[0]
     ↓ last = efforts[1] if len(efforts) >= 2 else None
     ↓ pr = min(efforts, key=lambda e: e.elapsed_time)
     ↓ diff_seconds = current.elapsed_time - last.elapsed_time if last else None
     ↓ is_pr = (current.elapsed_time == pr.elapsed_time and len(efforts) >= 2)
     ↓ is_first = len(efforts) == 1
     ↓ return EffortCompareResponse 6 字段
```

### 16.3 spec 漂移修补痕

- task-1.A.2 codex 第一轮把 6 字段对比类（current / last / pr / diff / is_pr / is_first）误换成 4 字段排名类（my_best / my_latest / rank / total_riders）→ task-1.A.3 主开发发现 + 重写 + 沉淀 memory `feedback_three_review_pipeline.md`

---

## 链路 17：NPC 文案 hook（Persona Engine v0.1 / 2026-05-18）

### 17.1 触发

worker 完成 activity 解析 → status=completed 后、`db.commit()` 前 → 跑 step 10.7 NPC hook 给本次活动写一条 NPC 文案到 `persona_outputs`。同时小程序 detail/profile 等页打开时通过 `GET /api/persona/output` 拉这条文案给用户看。

### 17.2 序列（worker hook 写入侧）

```
[worker]  parse_activity → ... → step 10.6 user.city hook 完成 / 在 db.commit 之前
  ↓ if not is_duplicate:
  ↓ try: nested_persona = db.begin_nested()  # SAVEPOINT 隔离 / 失败不传染 activity 主流程
  ↓   try: db.flush()  # 让本次 activity 进 session 让 _query_weekly_count 包含本次
  ↓     weekly_count = _query_weekly_count(user_id, db)  # 本周一 北京 ZoneInfo
  ↓     is_pr = _detect_pr(activity, user_id, db)  # 4 字段任一打破历史 max
  ↓     total_distance_m = _query_total_distance(user_id, db)  # cycling sum
  ↓     event1 = PersonaEvent(type='activity_uploaded', ...)
  ↓     persona_service.generate_persona_output(event1, db)  # 6 步流水
  ↓       └→ trigger_router.route(event) → PR > 极端 > 段位 优先级
  ↓       └→ template_lib.get_templates_for_scene + pick_template（7 天去重）
  ↓       └→ filters.is_safe（宪法 §3 反例 9 类 + emoji + 长度 5-25）
  ↓       └→ cache.record_output（写 persona_outputs / 内层 SAVEPOINT 隔离）
  ↓     if weekly_count >= 5: event2 = consecutive_high_detected → 同上流水
  ↓     nested_persona.commit()
  ↓   except Exception as inner: nested.rollback() + logger.warning（不抛）
  ↓ except Exception as outer: logger.warning（catch begin_nested 本身失败 / 不传染）
  ↓ db.commit()  # activity 主流程不受 persona 任何影响（宪法 §7.2）
```

### 17.3 序列（endpoint 读取侧 / 便利贴 + 朋友圈分流）

```
[api]  GET /api/persona/output?scene_type=X[&activity_id=Y]
  ↓ get_current_user 解 JWT → user_id
  ↓ service.get_latest_output_for_scene(db, user_id, scene_type, activity_id):
  ↓   if activity_id is not None:  # 详情页 = 便利贴永远在
  ↓     先精确查 activity_id==Y（不限时间 / Codex C2 防覆盖）
  ↓     无命中 → fallback 查 activity_id IS NULL 限 24h（防 90 天前通用文案露面）
  ↓   else:  # "我的"页 = 朋友圈式 24h
  ↓     查 user × scene_type / shown_at >= now - 24h / 最新一条
  ↓ 返 200 + {template_text|null, scene_type, created_at}（**永不返 5xx / 宪法 §7.2**）
```

### 17.4 后台 scheduler（每日 24h cron）

```
[persona-scanner 容器 / sleep 86400 循环]:
  ↓ python -m scripts.persona_silence_scanner
  ↓   找 last_activity_started_at >= 7 天的 user / 触发 silence_detected event / 写 persona_outputs
  ↓ python -m scripts.persona_milestone_scanner
  ↓   3 类 milestone 扫：累计跨阈值（1万/5万/10万 km）+ 周年 + 节气（2026 表硬编码）
  ↓   同日幂等 guard：今日已写 surprise 的 user 跳过（防 cron 重复跑）
  ↓   ZoneInfo("Asia/Shanghai") 算 today_bj（防容器 TZ=UTC 偏一天）
```

### 17.5 关键陷阱

| 陷阱 | 原因 | 修法 |
|---|---|---|
| worker 没 rebuild | task-4 部署只 rebuild api + scanner / 漏 worker | 部署 SOP 改 `docker compose up -d --build`（不指定 service / 见 CLAUDE.md 部署 SOP）|
| avg_speed 双重转换 | save_parse_result 已 *3.6 转 km/h / NPC hook 又 *3.6 | NPC hook 直接用 `activity.avg_speed` 不再 *3.6（worker.py + backfill 都修）|
| db.flush() 在 hook 前 | SessionLocal autoflush=False / activity 还没落 DB / weekly_count 漏本次 | hook 内显式 `db.flush()` 让本次 activity 进 session 可查 |
| endpoint activity_id 被通用覆盖 | (activity_id=X OR NULL) order by shown_at desc → 更晚的通用 NPC 覆盖回填的活动专属 | 先精确查 activity_id=X / 无命中再 fallback NULL |
| 历史活动 backfill 段位错 | "现在段位算所有历史"违反真实时间线 | SQL window function 算"当时累计 km"（`scripts/persona_backfill.py`）|

### 17.6 实证

- 168 条 NPC 文案入库（v0.2 cycle / 7 个场景）
- 193 条历史活动回填（2026-05-20 / 286 扫描 / 93 边缘 segment 无 template 池为 no_output）
- worker hook 真用：上传 activity 422 / 55km / segment_distance/veteran_normal / "40km。蹬两脚意思意思。"
- task-1.A.3 决策点 2 修：spec 写 `distance_km` → 现有 router 契约已用 `distance` → doc fix `1a0631f` 同步 spec（不破前端）

### 16.4 不变式

- 先查 segment 存在性再查 effort（避免 segment_id 不存在时静默返"is_first=True"误导用户）
- 单次查询限 100 条 effort（防超长历史用户）
- 字段名 `elapsed_time` 不是 `time`（陷阱 #10 / 不脑补）

---

## 全局不变式

这些是跨所有链路必须遵守的:

### 10.1 单向依赖

```
核心链:   user ← activity ← segment ← notification
parsing:  纯函数层,被 activity + strava 调用,无反向依赖
strava:   与 notification 同层 —— 依赖 user + activity + segment + parsing,
          反向写入 activities / segment_efforts / notifications
```

只要 activity / segment / notification 不反向 import strava,就不构成循环。违反核心链 = 循环 import = FastAPI 启动崩溃。

### 10.2 时区

- DB 字段理想上全是 `DateTime(timezone=True)`,实际只有 users.strava_token_expires_at + strava_imports.cursor_before + strava_imports.updated_at 是 tz-aware(tech-debt #1)
- Python 禁用 `datetime.utcnow()`,用 `datetime.now(timezone.utc)`
- "本周/本月"按北京时间 UTC+8 计算

### 10.3 PostGIS 距离

- 所有 ST_DWithin 必须 `::geography` 转型
- 不转:参数单位变度(~111km),逻辑完全错

### 10.4 truthiness

- bool 字段判断用 `is True` / `== False`
- 可空字段存在性判断用 `is not None`
- 永远不要 `if user.mute_notifications:`(NULL 会错判)

### 10.5 SAVEPOINT

循环中有 flush + 可能 rollback → 必须 `db.begin_nested()`。典型场景:
- auto_match 每个 segment 独立 SAVEPOINT(链路 1.3)
- detect_events 每个 event 独立 SAVEPOINT(链路 1.4)
- strava import_scheduler 每个 activity 独立 SAVEPOINT

### 10.6 纯函数

以下文件绝对不碰 DB/文件系统,只接收参数返回结果:
- `parsing/gpx_parser.py`
- `parsing/fit_parser.py`
- `parsing/strava_adapter.py`
- `parsing/stats_calculator.py`
- `activity/simplify.py`
- `activity/power_zones.py`
- `segment/matcher.py`

(notification 的 detector 逻辑当前内联在 service.py,尚未抽为独立纯函数文件)

### 10.7 Alembic

改表结构必须生成 Alembic 迁移,禁止 `Base.metadata.create_all` 之外的手动 ALTER TABLE。

### 10.8 文件大小健康度

- 单文件 > 300 行 → 黄灯,汇报时提
- 单文件 > 500 行 → 红灯,评估是否拆分(职责统一的不强拆)

---

## 未实现链路(易踩坑)

**以下链路在 PRD v0 中规划过但实际未实现**,agent 不要假设存在:

### 11.1 骑行卡片后端 PNG 生成 ❌

- PRD v0 描述 "Worker generate_card + /api/activities/{id}/card 接口 + activities.card_image_url 字段"
- **实际:未实现**。卡片只在前端 Canvas 渲染,无后端 PNG 流水线
- agent 禁止假设此字段存在或此接口存在
- 如需分享:前端 Canvas toDataURL → wx.saveImageToPhotosAlbum → 用户手动发

### 11.2 赛段 status(draft/active/archived) ❌

- PRD v0 描述 segments 表有 status 字段
- **实际:未实现**,所有已创建的 segment 默认可见可匹配
- 如需禁用赛段,目前只能 DELETE

### 11.3 agent_suggestions / agent_feedback 表 ❌

- 之前讨论过 agent 层的数据表
- **实际:未建**,agent-native 是 v7+ 方向(ADR-009)

### 11.4 用户自建赛段 ❌

- PRD v0 描述 "用户在海拔剖面图滑动选起终点"
- **实际:未实现**,目前只有 admin 能 POST /api/segments
- v6+ 考虑

### 11.5 路线规划 / 导航 ❌ 永不实现

- ADR-010 决策:velo **永远不做**实时导航
- 跳转高德完成,velo 只输出 GPX

### 11.6 notifications 按 activity_id / event_type 过滤 ❌

- 新文档早期版本曾假设 `GET /api/notifications?activity_id=&event_type=`
- **实际:未实现**,router 只支持 `page / page_size / unread_only`
- 详情页徽章由前端拉全量通知后本地过滤

---

## 附录 A: 数据库读写矩阵

| 模块 \ 表 | users | activities | trackpoints | segments | segment_efforts | notifications | strava_imports |
|---|---|---|---|---|---|---|---|
| user | R/W | R | - | - | - | - | - |
| activity | R | R/W | R/W | - | R | - | - |
| segment | R | R | R | R/W | R/W | - | - |
| notification | R | R | - | R | R | R/W | - |
| strava | R/W | R/W | W | - | W | W | R/W |
| parsing ✨ | - | - | - | - | - | - | - |

✨ parsing 是纯函数模块,不碰 DB。

**strava 行说明:** import_scheduler 通过 `activity.worker.save_parse_result` 写入 activities + trackpoints;通过 `segment.auto_match.match_activity_against_segments` 间接写入 segment_efforts + notifications(因为 auto_match 内部会调 detect_events)。

**agent 注意:** 任何模块要访问表范围外的列,停下来 review 是否违反单向依赖。

---

## 附录 B: Redis key 约定

| key 前缀 | 用途 | TTL | 谁写 | 谁读 |
|---|---|---|---|---|
| `rq:queue:velo` | rq 队列(list) | - | api (LPUSH via Queue("velo")) | worker (BLPOP) |
| `rq:job:<job_id>` | 任务元数据(hash) | rq 内部 | rq | rq |
| `strava:state:<nonce>` | OAuth state | 600s | api (SET) | api (GETDEL) |
| `strava:ratelimit:<user_id>` | scheduler 限流 | 1s | scheduler (SETNX) | - |
| `strava:progress_rate:<user_id>` | 进度查询限流 | 1s | api (SETNX) | - |

⚠️ 队列名是 `velo`(app/activity/service.py 里 `Queue("velo", ...)`),不是 rq 默认的 `default`。

---

## 附录 C: 日志要点

关键步骤必须 log:

```
app/activity/worker.py:
  "parse_activity 开始 activity_id=42"
  "解析完成 activity_id=42 trackpoint_count=3000 status=completed"
  "解析失败 activity_id=42 error=<详情>"

app/segment/auto_match.py:
  "auto_match 开始 activity_id=42"
  "粗筛候选 activity_id=42 candidates=[3,7,12]"
  "精确匹配 activity_id=42 segment_id=3 success elapsed_time=620s"
  "精确匹配失败 activity_id=42 segment_id=7 reason=覆盖率 0.65<0.8"

app/notification/service.py:
  "检测事件 activity_id=42 new_events=[pr, kom]"

app/strava/import_scheduler.py:
  "tier1 进度 user_id=5 imported=30 remaining=?"
  "限流命中 user_id=5"
```

Worker 后台无界面,日志是唯一观察窗口。

---

## 附录 D: 文档交叉引用

| 如果想了解... | 去看 |
|---|---|
| 静态架构 | `architecture-guide.md` |
| 技术决策原因 | `adr/*.md` |
| 模块精确契约 | `contracts/*.md`(占位,待建) |
| 本期任务 | `spec-v{current}.md`(当前扁平在 docs/ 下) |
| 产品方向 | `prd/prd-v{current}.md`(占位,当前仅 TEMPLATE.md) |
| 模块内部 | `app/<模块>/README.md`(占位,待建) |
| 技术债务 | `tech-debt.md` |
| 开发约束 | `/CLAUDE.md` |
| 竞品分析与产品警示 | `competitive-analysis/*.md` |
