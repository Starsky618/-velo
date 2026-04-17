# 技术债务清单

> 项目 CLAUDE.md 防黑盒化机制 3："每期开工前做回溯体检"——新期 Spec 不允许依赖"还在 tech-debt 清单里"的功能，先修清理再做。

---

## 第 5 期（下期）P1 清单 — 开工前必评估

### 来源：第 4 期批 1-6 双审判（2026-04-17）

#### 1. datetime 栈内不一致（naive vs aware）

**现状**：
- `strava_imports.updated_at` 已是 `DateTime(timezone=True)`（task-7.1）
- `activities.started_at` / `activities.updated_at` / `notifications.expires_at` 仍是 naive `DateTime`
- `app/notification/service.py:69-71, 124, 202, 316` 用 `datetime.utcnow()`（naive + Python 3.12+ Deprecation）

**风险**：
- 任何跨这两种字段的减法 → TypeError
- Python 3.14 彻底移除 `datetime.utcnow()` 后编译失败

**下期动作**：
- 把全项目 `datetime.utcnow()` 替换成 `datetime.now(timezone.utc)`
- 把所有 `DateTime` 字段迁移成 `DateTime(timezone=True)`（Alembic 迁移 + 老数据 `AT TIME ZONE 'UTC'`）

#### 2. `ensure_valid_token` 行锁约束只在注释里

**现状**（`app/strava/service.py`）：
- task-7.6 I8 给函数入口加 `SELECT FOR UPDATE`
- 但 caller `StravaClient._request` 在刷 token 后仍持有入参 `self.user` 引用
- 约束只靠注释："调用方只用返回的 token 字符串，不写 user 字段"
- 未来有人改 client.py 会静默失效

**下期动作**：
- 把 `ensure_valid_token` 签名改为 `(db, user_id: int) -> tuple[User, str]` 返回行锁 user + token
- 或封装成 `refresh_token_atomically(db, user_id) -> str` 彻底不传 user 对象
- caller 显式用返回的 user 做后续操作

#### 3. `ensure_valid_token` 对未绑定用户路径脆弱

**现状**：
- `user.strava_token_expires_at is None` 时进入刷新分支
- 用 `refresh_token=None` 请求 Strava → 400 → 抛"Strava 授权已失效"
- Race condition：sync 进行中另一个请求调 401 清 token → sync 的下一次 API 调用会触发此脆弱路径

**下期动作**：
- 函数入口加 `if user.strava_refresh_token is None: raise ValueError("Strava 未绑定")`

#### 4. SQLAlchemy legacy `.get()` 用法

**现状**：`tests/test_notification.py` 多处 `Session.query().get()`（Deprecated since 2.0）

**下期动作**：批量替换为 `session.get()`

#### 5. scheduler 的 Redis 连接每次新建

**现状**（`app/strava/import_scheduler.py:187-198`）：
- 每次空返回都 `Redis.from_url(settings.REDIS_URL)` 新建连接
- 应复用全局 `_redis` 客户端（`app/strava/client.py:59`）

**下期动作**：refactor 用全局 `_redis`

---

### 来源：生产部署缺陷（CLAUDE.md 已有条目）

已在主 CLAUDE.md "已知部署缺陷"小节记录：
- OAuth callback 可重复创建 strava_imports（本期 task-7.3 已修）
- ~~无 scheduler 容器~~（本期 task-7.9 将修）

---

## P2（远期）

### 前端相关
- 小程序 web-view 业务域名白名单未配（task-7.10 临时用剪贴板+模态过渡）
- 积分 + 骑行等级系统（spec §9.5，用户活跃度达标后启动）
- 微信服务消息推送（spec §9.3，独立大任务）

### 后端相关
- N+1 查询（排名计算循环发 SQL）—— 代码已标 TODO
- trackpoints 表无分区策略（百万级用户后要加）
- service.py 单文件已达 727 行（黄灯 >300 / 红灯 >500）—— 职责内聚暂保留，下次修改时评估拆分

---

## 清理节奏

> 每期 10-20% 时间处理 P1，P2 评估性价比再决定。
> 完成清理的条目从本文件移除并在 `docs/changelog.md` 记录一句。
