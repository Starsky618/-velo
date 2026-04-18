# VELO 架构导览

> 给架构师看的地图，不是给程序员看的手册。
> 5 分钟读完，脑子里有张图。出了 bug 知道去哪找，AI 改了代码知道动了哪块。

---

## 一句话说清楚

VELO 是一台"骑行成绩加工厂"：**用户把骑行数据扔进去，工厂自动加工成成绩单、排行榜、通知，用户拿走结果。**

---

## 六个车间

把整个工厂想象成六个车间，每个车间干一件事，通过传送带（函数调用）连接。

```
┌─────────────────────────────────────────────────────────┐
│                    用户（小程序）                          │
│         登录 / 上传文件 / 查排行榜 / 看通知                 │
└────────┬──────────┬──────────┬──────────┬───────────────┘
         │          │          │          │
    ┌────▼───┐ ┌────▼────┐ ┌──▼───┐ ┌────▼────┐
    │ 用户   │ │ 活动    │ │ 赛段 │ │ 通知    │
    │ user/  │ │activity/│ │segment│ │notifi-  │
    │        │ │         │ │      │ │cation/  │
    │ 微信   │ │ 上传    │ │ 匹配 │ │ PR/KOM  │
    │ 登录   │ │ 解析    │ │ 排行 │ │ 检测    │
    │ JWT    │ │ 统计    │ │ 榜   │ │ 荣誉表  │
    └────────┘ └────┬────┘ └──▲───┘ └────▲────┘
                    │         │          │
              ┌─────▼─────────┴──────────┘
              │        Worker（后厨）
              │  解析文件 → 写轨迹点 → 匹配赛段 → 检测通知
              └─────┬─────────────────────────
                    │
    ┌───────────────▼───────────────┐
    │  翻译层 parsing/ + Strava集成   │
    │  GPX / FIT / Strava → 统一格式  │
    └─────────────────────────────────┘
```

| 车间 | 类比 | 干什么 | 文件夹 | 代码量 |
|------|------|--------|--------|--------|
| **用户** | 门卫室 | 验身份、发通行证（JWT） | `app/user/` | 591 行 |
| **活动** | 收发室 | 收文件、排队、派工 | `app/activity/` | 1617 行 |
| **赛段** | 计时裁判 | 匹配路线、记成绩、排名次 | `app/segment/` | 1843 行 |
| **通知** | 广播室 | 检测 PR/KOM、通知用户、标读 | `app/notification/` | 693 行 |
| **翻译层** | 翻译官 | GPX/FIT/Strava → 统一语言 | `app/parsing/` | 1802 行 |
| **Strava** | 海关 | 对接 Strava 平台、导入骑行、OAuth/Webhook 加固 | `app/strava/` | 1996 行 |

**总计 8927 行 Python（v4 后增长 ~160 行，主要在 strava/notification）+ 微信小程序前端约 2000 行。**

---

## 数据怎么流的

从用户骑完车到看到排名，数据经过这条路：

```
第①步                第②步              第③步             第④步            第⑤步
用户上传文件     →   Worker 解析     →   匹配赛段      →   检测通知     →   用户查看
或 Strava 同步       翻译成统一格式       和已有赛段比对      有没有破纪录       排行榜/通知

文件/API数据      →  Activity 表      →  SegmentEffort  →  Notification  →  API 返回
                    Trackpoint 表        （成绩表）         （通知表）        JSON
```

**关键：每一步只往右走，不回头。** 活动不知道通知的存在，赛段不知道 Strava 的存在。这样一块坏了不会连锁倒塌。

---

## 七张数据表

| 表名 | 存什么 | 类比 | 量级预估 |
|------|--------|------|---------|
| **users** | 用户档案 | 会员卡 | ~100 行 |
| **activities** | 每次骑行记录（v4 加 activity_type 种子）| 比赛登记表 | ~3000 行 |
| **trackpoints** | GPS 轨迹点 | 心电图采样点 | ~300 万行 |
| **segments** | 赛段定义 | 赛道图纸 | ~30 行 |
| **segment_efforts** | 赛段成绩 | 成绩单 | ~5000 行 |
| **strava_imports** | Strava 导入进度（v4 改 updated_at tz-aware）| 搬运工进度条 | ~50 行 |
| **notifications** | PR/KOM 通知（v4 加 is_read + 部分索引；外键改 SET NULL）| 广播便签 | ~500 行 |

**表之间的关系（谁依赖谁）：**

```
users ← activities ← trackpoints
                   ← segment_efforts → segments
                   ← notifications
strava_imports → users
```

箭头方向 = 删除方向。删用户 → 自动删他的活动 → 自动删轨迹点和成绩。

---

## 七个进程

服务器上跑着 7 个进程（Docker 容器），各司其职：

| 容器 | 干什么 | 类比 | 出问题的症状 |
|------|--------|------|------------|
| **api** | 接收用户请求、返回数据 | 前台柜员 | 小程序报 500 错误 |
| **worker** | 后台解析文件、匹配赛段 | 后厨 | 上传后一直"处理中" |
| **scheduler** | 每 30s 推进 Strava 历史导入（v4 新增）| 搬家调度员 | Strava 同步进度不动 / view_status=stalled |
| **cleanup** | 每 5 分钟扫僵尸活动（>10min 的）| 保洁员 | 僵尸活动越积越多 |
| **db** | PostgreSQL 数据库 | 档案柜 | 所有功能都报错 |
| **redis** | 消息队列 + state nonce + 限流计数器 | 传话筒 | Worker/Scheduler 收不到任务 / OAuth 失败 |
| **caddy** | HTTPS + 反向代理 | 大门保安 | 完全无法访问 |

---

## 出了 bug 去哪找

### 快速定位表

| 症状 | 最可能的车间 | 看哪个日志 | 查哪个文件 |
|------|------------|----------|----------|
| 登录失败 | 用户 | api 日志 | `user/service.py` |
| 上传后卡在"处理中" | 活动/Worker | worker 日志 | `activity/worker.py` |
| 上传成功但无赛段成绩 | 赛段 | worker 日志 | `segment/auto_match.py` |
| 排行榜数据不对 | 赛段 | api 日志 | `segment/service.py` |
| 没收到 PR/KOM 通知 | 通知 | worker 日志 | `notification/service.py` |
| 通知红点不消失 / 不显示 | 通知 / 前端 | api 日志 | `notification/service.py:mark_all_read` + `home.js` |
| Strava 同步不动 | Strava | **scheduler 日志** | `strava/import_scheduler.py` + `scheduler.py` |
| Strava 进度卡 / view_status=stalled | Strava | scheduler 日志 | scheduler 容器是否在跑 + `service.py:get_import_progress` |
| Webhook 收 403 | Strava | api 日志 | `STRAVA_WEBHOOK_SUBSCRIPTION_ID` env 是否配 |
| OAuth 回调失败 | Strava | api 日志 | `service.py:handle_callback` + Redis state |
| GPX 解析出错 | 翻译层 | worker 日志 | `parsing/gpx_parser.py` |
| FIT 文件解析出错 | 翻译层 | worker 日志 | `parsing/fit_parser.py` |
| 所有功能都挂 | 数据库或 Redis | db/redis 日志 | Docker 容器状态 |

### 看日志的命令

```bash
# SSH 到服务器
ssh ubuntu@114.132.190.245

# 进项目目录
cd ~/velo

# 看 API 日志（前台柜员）
sudo docker compose logs api --tail 30

# 看 Worker 日志（后厨）—— GPX/FIT 上传 bug 在这里
sudo docker compose logs worker --tail 30

# 看 Scheduler 日志（Strava 调度）—— Strava 同步问题在这里
sudo docker compose logs scheduler --tail 30

# 看数据库日志
sudo docker compose logs db --tail 30

# 看所有容器状态
sudo docker compose ps
```

---

## AI 改了代码，怎么判断动了哪块

| AI 说改了这个文件 | 它动的是 | 可能影响 |
|-----------------|---------|---------|
| `user/*.py` | 登录/个人资料 | 所有需要登录的功能 |
| `activity/*.py` | 上传/解析/查询 | 骑行详情页、统计 |
| `segment/auto_match.py` | 赛段匹配算法 | 成绩准不准 |
| `segment/service.py` | 排行榜查询 | 排名对不对 |
| `notification/*.py` | 通知检测 | PR/KOM 通知 |
| `parsing/*.py` | 文件解析 | 所有数据来源的第一步 |
| `strava/*.py` | Strava 对接 | 同步功能 |
| `main.py` | 路由注册 | 新 API 能不能访问到 |
| `scheduler.py` | Strava 调度入口（v4 新增）| Strava 同步是否在跑 |
| `migrations/*.py` | 数据库结构 | 需要跑迁移才生效 |
| `docker-compose.yml` | 容器配置 | 需要重启容器 |
| `miniprogram/pages/notification/*` | 通知中心页 | 红点点击后看到的页面 |
| `miniprogram/pages/honor/*` | 荣誉页 | "我的"页 → 荣誉入口 |
| `miniprogram/pages/settings/*` | 设置页（免打扰）| 静音开关 |

---

## API 地图

一共 **22 个接口**，分五组：

### 用户（4 个）
| 方法 | 路径 | 干什么 |
|------|------|--------|
| POST | `/api/user/login` | 微信登录 |
| GET | `/api/user/profile` | 看个人资料 |
| PUT | `/api/user/profile` | 改个人资料 |
| GET | `/api/user/stats` | 骑行统计（总里程等） |

### 活动（7 个）
| 方法 | 路径 | 干什么 |
|------|------|--------|
| POST | `/api/activities/upload` | 上传 GPX/FIT |
| GET | `/api/activities` | 骑行列表 |
| GET | `/api/activities/{id}` | 骑行详情 |
| PATCH | `/api/activities/{id}` | 改标题 |
| DELETE | `/api/activities/{id}` | 删骑行 |
| GET | `/api/activities/{id}/timeseries` | 速度/功率曲线数据 |
| GET | `/api/activities/{id}/status` | 解析进度轮询 |

### 赛段（7 个）
| 方法 | 路径 | 干什么 |
|------|------|--------|
| POST | `/api/segments` | 创建赛段（管理员） |
| DELETE | `/api/segments/{id}` | 删赛段（管理员） |
| GET | `/api/segments` | 赛段列表（支持附近搜索） |
| GET | `/api/segments/{id}` | 赛段详情 + TOP20 |
| GET | `/api/segments/{id}/leaderboard` | 完整排行榜 |
| GET | `/api/user/efforts` | 我的所有赛段成绩 |
| GET | `/api/activities/{id}/segments` | 这次骑行经过的赛段 |

### 通知（3 个）
| 方法 | 路径 | 干什么 |
|------|------|--------|
| GET | `/api/notifications` | 通知列表（v4 加 `unread_only` 参数 + 响应永远带 `unread_count`）|
| POST | `/api/notifications/mark-all-read` | 一键标读（v4 新增，幂等）|
| GET | `/api/user/honors` | KOM + 前十荣誉表 |

### Strava（6 个）
| 方法 | 路径 | 干什么 |
|------|------|--------|
| GET | `/api/strava/authorize` | 获取授权链接（v4 改 Redis nonce state）|
| GET | `/api/strava/callback` | 授权回调（v4 重写防重复绑定 + 换号清理）|
| GET | `/api/strava/status` | 绑定状态（v4 响应加 `bound` 别名 = `connected`）|
| POST | `/api/strava/sync` | 手动同步（v4 联动 tier1_completed）|
| GET | `/api/strava/import-progress` | 导入进度（v4 加 `view_status`：none/active/stalled/paused/completed + Redis 1s/user 限速）|
| GET/POST | `/api/strava/webhook` | Webhook（v4 加 subscription_id 校验防伪造）|

---

## 技术栈速查

| 层 | 用什么 | 为什么选它 |
|----|--------|----------|
| 后端框架 | FastAPI (Python) | 快、自动生成文档、同步模式简单 |
| 数据库 | PostgreSQL 16 + PostGIS | 空间查询（"附近有哪些赛段"） |
| 消息队列 | Redis + rq | 异步解析不阻塞用户操作 |
| 反向代理 | Caddy | 自动 HTTPS、配置极简 |
| 容器 | Docker Compose | 一条命令启动所有服务 |
| 前端 | 微信小程序（原生） | 目标用户在微信生态 |
| 文件解析 | garmin-fit-sdk + 自研 GPX 解析 | FIT 用官方库、GPX 自己写更灵活 |
| 坐标转换 | xyconvert + numpy | GCJ-02（国内偏移）→ WGS-84（标准） |

---

## 和团队对接时的一分钟话术

> "VELO 分六个模块。用户模块管登录，活动模块管上传和解析，赛段模块管匹配和排行榜，通知模块管 PR 和 KOM 提醒，翻译层负责把不同格式的骑行文件翻译成统一格式，Strava 模块负责从 Strava 导入数据。
>
> 数据流是单向的：上传 → 解析 → 匹配 → 通知 → 用户看到红点 → 点开看排名。每个模块只管自己的事，一个崩了不影响其他的。
>
> 后端跑在 Docker 里，**七个容器**：API 接请求、Worker 解析文件、Scheduler 推 Strava 同步（每 30s）、Cleanup 扫僵尸、PostgreSQL 存数据、Redis 传消息+OAuth state+限流、Caddy 管 HTTPS。
>
> 小程序 5 个 tab + 通知中心 + 荣誉页 + 设置页（免打扰开关）。
>
> 目前 **24 个 API 接口**，**181 个自动化测试**，~9500 行 Python + ~2000 行小程序代码。"

---

## 附录：v4 收尾 — 黑盒度体检三问答卷（2026-04-18）

> 防黑盒化机制 2 要求每期收尾必答。

**Q1：10 分钟讲解挑战 — 我能用 10 分钟给陌生人讲清整个系统吗？哪个模块卡壳最多？**

> 能。骑行成绩加工厂的比喻 + 7 个容器 + 4 步数据流，10 分钟够。
>
> **卡壳最多的模块：Strava**（OAuth 流程 + 两层导入 + scheduler/Webhook/手动 sync 三入口 + 行锁/Redis state/限流多个机制叠加）。这是 v4 加固后的复杂度代价。**清理动作**：service.py 727 行已黄灯，下期触达时考虑拆 OAuth / token 管理 / 业务同步三个独立文件。

**Q2：数据流复述 — 挑一个典型用户操作，从按钮点击到数据落库能在纸上画清楚吗？**

> 选"上传 GPX 看到赛段成绩 + 通知"全链路：
>
> 1. 小程序 → `POST /api/activities/upload`（带 JWT）
> 2. api 容器：哈希去重 → 文件落 LocalStorage → DB 写 Activity(pending) → 入 Redis 队列
> 3. worker 容器：从队列取任务 → 原子抢锁 status=processing → 下载文件 → **activity_type 分流**（v4 task-7.7：非 cycling 直接 failed）→ 翻译层解析 → 写 Trackpoint → 写 Activity 统计字段 → status=completed
> 4. worker 同步触发 auto_match → 匹配赛段 → SAVEPOINT 隔离写入 SegmentEffort → 调 detect_events → SAVEPOINT 隔离写 Notification
> 5. 用户回首页 → onShow → `GET /notifications?unread_only=true&page_size=1` → 拿 unread_count → 红点显示
> 6. 用户点铃铛 → 通知中心页 → 并行调 GET 列表 + POST mark-all-read → UI 立即视觉化已读
> 7. 用户点通知条目 → wx.navigateTo `/leaderboard?segment_id=X` → leaderboard.onLoad 接参数定位赛段（v4 批 8 双审修复）
>
> 全链路画清楚。每个箭头对应代码文件 file:line 我都能指出。

**Q3：30 秒读懂 — 有没有哪个文件 / 函数自己看都要想超过 30 秒才明白意图？**

> 有 2 处需要后续清理：
> - `app/strava/service.py:handle_callback`（重写后 7 步流程，146 行）—— 有详细注释，但流程长，第一次读需要 1 分钟。**对策**：保留（流程本身就是这 7 步必要的，砍任何一步都丢功能）。建议下期触达时把 7 步抽成 7 个内部函数。
> - `app/strava/import_scheduler.py:_run_tier1`（含 SAVEPOINT 嵌套 + Redis 计数器 + SQL 原子表达式，70+ 行）—— v4 加固后变厚。**对策**：暂保留，下期触达时考虑拆 fetch / persist / progress 三步。

> 三问体检结论：黑盒度可控。两处复杂度高的函数已识别 + 写进 `docs/tech-debt.md` 下期清。
