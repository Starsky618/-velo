# VELO 部署日志 — 从零到公网的完整踩坑记录

> 2026-04-13/14，Starsky + Claude 完成首次云部署。
> 本文档供团队成员和 AI agent 快速学习部署经验，避免重复踩坑。

## 环境信息

| 项 | 值 |
|----|-----|
| 服务器 | 腾讯云 2核4G，Ubuntu 22.04 + Docker 26 |
| 公网 IP | 114.132.190.245 |
| SSH 用户 | ubuntu（已配免密登录） |
| 代码位置 | 服务器 ~/velo |
| API 地址 | http://114.132.190.245 |
| API 文档 | http://114.132.190.245/docs |
| GitHub | Starsky618/-velo（私有） |

## 部署流程（最终确定版）

```
本地跑测试 → tar 打包 → scp 传到服务器 → 解压 → 清理 macOS 垃圾 → docker compose up --build → alembic 迁移 → curl 验证
```

详见 `/deploy` skill（`.claude/skills/deploy/SKILL.md`），以下只记**为什么这样做**和**踩过什么坑**。

---

## 踩坑记录

### 1. GitHub 在国内服务器不可用

**现象：** `git clone` 报 `GnuTLS recv error (-110): The TLS connection was non-properly terminated`

**原因：** 腾讯云服务器在国内，GFW 对 GitHub 的 HTTPS 连接不稳定，随机中断。

**解决方案：** 放弃 git clone，改用 scp 传 tar 包。流程：本地 `tar czf` → `scp` → 服务器 `tar xzf`。

**教训：** 国内服务器不要依赖 GitHub 作为部署通道。未来如果要自动化部署，考虑腾讯云的容器镜像服务（TCR）或 Coding DevOps。

### 2. macOS tar 打包带 `._*` 隐藏文件

**现象：** Alembic 迁移报 `SyntaxError: source code string cannot contain null bytes`

**原因：** macOS 的 tar 命令会把文件的扩展属性（xattr）打包成 `._filename` 格式的隐藏文件。这些文件包含二进制数据（null bytes）。Alembic 扫描 migrations/ 目录时把 `._xxx.py` 当成 Python 文件加载，就炸了。

**解决方案：** 解压后执行 `find ~/velo -name '._*' -delete`。已写入 deploy skill。

**教训：** 任何从 macOS 传到 Linux 的 tar 包，解压后都要清理 `._*` 文件。这不是个例，是 macOS 的系统行为。

### 3. SSH 终端不支持多行命令

**现象：** 粘贴多行命令（heredoc、多行 Python 等）到 SSH 终端，要么无反应，要么报 `IndentationError`。

**原因：** SSH 终端对多行输入的处理因客户端而异，macOS Terminal 通过 SSH 粘贴多行时会丢失换行或引入错误缩进。

**解决方案：** 所有 SSH 命令必须是单行。需要多行内容时，用以下替代方案：
- `echo 'line1' > file && echo 'line2' >> file`（逐行写入）
- `printf 'line1\nline2\n' | sudo tee file`（单行 printf）
- `sed -i 's/old/new/' file`（单行替换）
- 写成脚本文件 scp 过去再执行

**教训：** 已加入 CLAUDE.md 技术约束："SSH 只用单行命令"。这是硬性规则。

### 4. bash 中 `!` 是特殊字符

**现象：** `echo "DB_PASSWORD=Velo2026!Prod"` 报 `event not found`

**原因：** bash 中 `!` 触发历史展开（history expansion），`!Prod` 被解释为"查找以 Prod 开头的历史命令"。

**解决方案：** 用单引号包裹内容：`echo 'DB_PASSWORD=Velo2026Prod'`。单引号内所有字符都是字面量，不做任何解释。

### 5. cleanup 容器反复重启

**现象：** `velo-cleanup-1` 状态显示 `Restarting (1) 33 seconds ago`

**原因：** cleanup 容器的命令是 `cp /app/crontab /etc/crontabs/root && crond -f`，这是 Alpine Linux 的路径。但容器基于 `python:3.11-slim`（Debian），Debian 的 cron 路径和命令名都不同。

**解决方案：** 不用 cron，改用 sleep 循环：`sh -c "while true; do python scripts/cleanup_zombies.py; sleep 300; done"`。效果一样，兼容任何基础镜像。

**教训：** Docker 命令要和基础镜像的发行版匹配。`python:xxx-slim` 是 Debian，不是 Alpine。

### 6. pip install 在国内服务器超时

**现象：** `docker compose build` 时 pip install 报 `ReadTimeoutError: Read timed out`

**原因：** 服务器在国内，访问 PyPI（files.pythonhosted.org）走国际线路，不稳定。

**解决方案：** Dockerfile 中 pip install 加腾讯云镜像：
```dockerfile
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple --trusted-host mirrors.cloud.tencent.com
```
服务器就在腾讯云上，走内网下载，构建时间从 5 分钟降到 30 秒以内。

**教训：** 国内服务器做 Docker 构建，pip/npm 等包管理器都应该配国内镜像源。

### 7. 部署时 Caddyfile 被覆盖

**现象：** 部署后 API 返回 308 重定向，而不是 200。

**原因：** 服务器上的 Caddyfile 之前手动改成了 `:80`（无域名模式），但本地的 Caddyfile 还写着 `api.velo.cn`。scp 传包时把服务器上的正确配置覆盖了。

**解决方案：** 本地 Caddyfile 同步改成 `:80`，保持和服务器一致。

**教训：** 本地代码和服务器配置必须同步。任何只在服务器上改的东西，本地也要跟着改并 commit。

### 8. Docker 服务需要 sudo

**现象：** `docker compose up -d` 报 `permission denied while trying to connect to the Docker daemon socket`

**原因：** ubuntu 用户不在 docker 组里。腾讯云预装的 Docker 默认只有 root 能直接操作。

**解决方案：** 所有 docker 命令前加 `sudo`。也可以 `sudo usermod -aG docker ubuntu` 把用户加入 docker 组（需要重新登录生效），但 sudo 更简单。

---

## 关键决策记录

### 域名与 ICP 备案

**决策：** 当前不备案，用 IP 直接访问。

**原因：**
- ICP 备案需要 7-20 天，阻塞开发
- 微信小程序开发模式（体验版）可绕过域名校验，覆盖 ~100 测试用户
- 域名属于联合创始人 CCF，备案主体需要和域名持有者一致
- 团队计划成立有限责任公司，到时用公司身份一步到位备案

**风险：** 小程序正式发布（非体验版）时必须有备案域名，微信平台技术强制校验，不是"有没有人管"的问题。

### python-jose → PyJWT

**决策：** 替换 JWT 库。

**原因：** python-jose 有 CVE-2024-33663（算法混淆攻击漏洞）。PyJWT API 基本兼容，改动量小（2 个文件），且本地已安装。

### 依赖版本锁定

**决策：** requirements.txt 全部锁定到具体版本号。

**原因：** 之前所有包都未锁定版本，新服务器构建时可能拉到破坏性更新。锁定版本保证构建可复现。

---

## 服务器管理速查

```bash
# SSH 登录
ssh ubuntu@114.132.190.245

# 查看容器状态
sudo docker compose ps

# 查看某个服务日志
sudo docker compose logs api --tail 20
sudo docker compose logs worker --tail 20

# 重启某个服务
sudo docker compose restart api

# 全量重建并重启
sudo docker compose up -d --build

# 跑数据库迁移
sudo docker compose exec api alembic upgrade head

# 进入 PostgreSQL
sudo docker compose exec db psql -U velo

# 进入 API 容器的 Python 环境
sudo docker compose exec api python
```

## ✅ Sprint 1+2+3 部署完成（2026-05-05）

> **背景**：2026-05-05 D.5 admin-h5 部署执行时发现 `origin/main` HEAD 停在 `c36a204`（2026-04-29 Sprint 0 末尾），Mac 本地有 39 个未 push commit——整个 Sprint 1+2+3 所有开发都没上生产。Tim 当晚拍 5 决策点（窗口 2.5h / pg_dump 必备 / 独立 deploy key / 9000 安全组放行 / FEISHU 阶段 2 占位），分 3 阶段一次性上线。**整 40 commit / 12+ 周积压一次清空，单次部署窗口约 1 小时（远低于 2.5h 预算 / 因 image cache 复用瞬完成）。**

### 服务器现状（部署前 baseline）

```
服务器 ~/velo HEAD = c36a204  ← 2026-04-29 Sprint 0 末尾（战略升级第 4 commit）
docker stack 跑：api / caddy / cleanup / db / redis / scheduler / worker
不在 stack：monitor / curation-pool-cron / admin-h5（这 3 个是积压期内新增）
```

### 积压范围

**39 个未 push commit / 涵盖 12+ 周开发量**

| Sprint | 范围 | 关键改动 |
|---|---|---|
| **Sprint 0 末尾**（已 push 到 c36a204）| 已上线 | task-0.1 ~ 0.8 全部部署 |
| **Sprint 1**（赛段内容深化 / ~6 commit）| 未部署 | 新增 `app/agent/`（DeepSeek + RQ AI 草稿）/ `app/monitor/`（4min 软目标 + 飞书告警）/ segment 算法纯函数扩展 |
| **Sprint 2**（数据成长 + 个人页 / ~7 commit）| 未部署 | 新增 `app/notification/progress_detector.py` / `app/segment/power_curve.py` / user.router 4 endpoint / city 字段防回退 / SAVEPOINT 升级 |
| **Sprint 3**（admin 工具 + admin H5 / ~26 commit）| 未部署 | 新增 `app/admin/` 整模块（11 endpoint）/ `app/agent/segment_writer.py` / segment service 拆分（service.py + service_create.py + service_query.py）/ scripts/generate_curation_pool.py / admin-h5 docker service |

### 容器 stack 增量（docker-compose.yml）

需要新启动 3 个 service：
1. **monitor**：worker 软目标监控 + 飞书告警（Sprint 1 task-1.C.1 / 依赖 `FEISHU_BOT_WEBHOOK` env）
2. **curation-pool-cron**：候选池每周刷新（Sprint 3 task-3.C.1 / 依赖现有 DB env）
3. **admin-h5**：管理员后台（Sprint 3 D.5 / build context `../admin-h5` / ports 9000:80 / 依赖 admin-h5 repo 服务器 clone）

worker service 改动：`RQ_QUEUES: "velo,ai_drafts"` 多队列 + 加 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` env（Sprint 1 task-1.B.1）

### .env 新增变量（Tim 已配 ~/velo/.env / 2026-04-29 备份 ~/velo/.env.bak.20260429）

```
DEEPSEEK_API_KEY=<已配>             # Sprint 1.B.1 AI 草稿生成
DEEPSEEK_MODEL=deepseek-chat       # Sprint 1.B.1 默认值
FEISHU_BOT_WEBHOOK=<待 Tim 确认>    # Sprint 1.C.1 monitor 告警 / 没配则飞书告警静默
```

### Migration 改动

**0 个未 push migration**（所有 migration 都在 origin/main 已含 / 含 phase5_v5_db_changes + phase5_tz_aware）。但要确认这些是否真在生产 PG 跑过 —— 部署前必跑 `sudo docker compose exec api python -m alembic current` 看 head version 对得上不。

### 高风险点（部署前必 review）

1. **DB schema 已迁但生产是否 alembic 当前 head**：phase5_v5_db_changes.py 引入了 segments 城市枚举 / segment_curation_pool / segment_ai_drafts / progress_notification 等表 + ALTER 多表 → 必须真跑过 / 且回滚路径已实证
2. **worker 多队列**：从单 `velo` 队列扩到 `velo,ai_drafts` —— 旧 worker 重启拉新 RQ_QUEUES 才生效 / 部署时 worker 必须重启
3. **scheduler 改动**（task-0.3 ensure_valid_token 兜底）—— scheduler 容器必须重启
4. **admin endpoint 整模块新增**（11 endpoint 含 from-gpx 真 PG Hausdorff 查重 / 候选池 / AI 草稿 / segments PATCH+DELETE）—— 没在生产真 PG 实证过 / Sprint 3 收尾的 tech-debt 已记 dev stack 真 PG Hausdorff 集成测试缺失
5. **service.py 拆分**（task-pre-3.B / 重命名 + re-export）—— 任何外部 caller 用 import 路径有变 / 但内部用 re-export 兼容 / 风险低但要 grep import 实证
6. **3 个新 service 容器**：第一次起 / Dockerfile 共享 velo 主 Dockerfile（除 admin-h5 用 admin-h5 自己的 Dockerfile + nginx）→ 镜像 build 一次复用
7. **腾讯云安全组**：admin-h5 需要放行 TCP 9000 入站（首次 9000 端口暴露）

### 推荐部署顺序（分阶段 / 不一次性上）

**阶段 1：backend 主体上线**（含 Sprint 1+2 + Sprint 3 admin endpoints）
1. Mac `git push origin main`（一次性 39 个 commit）
2. 服务器 `cd ~/velo && git pull`
3. 服务器 `sudo docker compose build api worker scheduler cleanup`
4. 服务器 `sudo docker compose exec api python -m alembic current` 看版本 / 如不到 head 跑 `alembic upgrade head`
5. 服务器 `sudo docker compose up -d api worker scheduler cleanup`（重启已有 service）
6. **冒烟**：curl 几个核心 endpoint（GET /api/users/me / GET /api/admin/whoami（先生成 admin token）/ GET /api/admin/curation-pool）

**阶段 2：新 service 上线**（monitor + curation-pool-cron）
7. 服务器 `sudo docker compose up -d monitor curation-pool-cron`
8. **冒烟**：`docker compose logs monitor --tail 20`（看是否正常 4min 探测）

**阶段 3：admin-h5 部署**（Sprint 3 D.5）
9. **腾讯云控制台**：放行 TCP 9000 入站
10. Mac `git push origin main`（admin-h5 repo / 已 push 但确认）
11. 服务器 admin-h5 clone：因为服务器 SSH key 是 velo repo deploy key 不是账号级 → 必须用 ① HTTPS+PAT 或 ② 给 admin-h5 加 deploy key 或 ③ scp 备用方案（README 已写完整命令）
12. 服务器 `cd ~/velo && sudo docker compose build admin-h5 && sudo docker compose up -d admin-h5`
13. **冒烟**：`curl -I http://114.132.190.245:9000/`（期望 200）+ 浏览器粘贴 admin token 进候选池页

### 部署窗口前 review 清单

- [ ] 完整审 39 个 commit 的双审 / Codex 异源审记录（spot check 几个高风险 task：task-1.B.1 AI agent / task-2.A.1 SAVEPOINT 升级 / task-3.A.6 Hausdorff 查重 / task-pre-3.B service 拆分）
- [ ] tech-debt.md 扫一遍 Sprint 3 期间记的所有 follow-up（如 Hausdorff dev stack 真 PG 集成测试 / admin 草稿 reject human_edited_text 残留）
- [ ] .env 真有 DEEPSEEK_API_KEY 和 FEISHU_BOT_WEBHOOK
- [ ] 准备 admin-h5 deploy 凭证（PAT 或 deploy key 或 scp 方案）
- [ ] 部署窗口预留 2-4 小时 / 含 backup（DB pg_dump）+ 回滚路径
- [ ] 一阶段一阶段冒烟 / 不一次性全 up

### 实际执行记录（2026-05-05 21:28 ~ 23:18 / 约 1 小时 50 分钟）

**阶段 0：baseline + backup**（10 min）
- 服务器 `c36a204` ✅ / 9 service Up（积压前已含 7 个）
- alembic head = `phase5_v5_db_changes`（task-0.6 已迁 / Sprint 1+2+3 0 个新 migration）
- pg_dump 备份：`~/velo/backup/pre-sprint123-20260505-2129.sql`（16M / 几秒完成）

**阶段 1：backend 主体**（约 15 min / api+worker+scheduler+cleanup 重启）
- Mac `git push origin main` → c36a204..3840d92（40 commit）
- 服务器 `git pull` ✅ / `docker compose build api worker scheduler cleanup` ✅（含 openai-2.34.0 for DeepSeek SDK）
- 4 service Recreated + Started 22s 内 stable
- 冒烟：worker `*** Listening on velo, ai_drafts...` ✅（Sprint 1.B.1 多队列生效）/ curl /docs HTTP 200 / 103ms

**阶段 2：monitor + curation-pool-cron**（约 5 min）
- `.env` 加 `FEISHU_BOT_WEBHOOK=`（空占位 / 5B 决策）
- `docker compose up -d monitor curation-pool-cron` ✅
- curation-pool-cron 启动即跑：「写入 24 条候选池」
- monitor 进程：`while true; do python -m app.monitor.processing_health || true; sleep 60; done`（无问题不打印 = 设计静默）

**阶段 3：admin-h5**（约 10 min / 含 deploy key 配置 + Tim 控制台放行 9000）
- 服务器生成 ed25519 deploy key `~/.ssh/admin-h5-deploy`
- ssh config alias `github-admin-h5` 已配
- Tim 在 GitHub admin-h5 repo Settings → Deploy keys 加公钥（read-only）
- Tim 在腾讯云**轻量应用服务器（Lighthouse）防火墙**放行 TCP 9000（**关键修正**：之前误认为是 CVM / 实际是 Lighthouse / UI 路径完全不同）
- 服务器 `~/admin-h5` git clone（前次尝试已遗留）/ HEAD = `7e736d4`（D.5 容器化部署）
- Image build 全 cached（前次尝试已 build 过）
- 容器 Up：`0.0.0.0:9000->80/tcp`
- **冒烟**：外网 `curl http://114.132.190.245:9000/` HTTP 200 / 112ms ✅

### 关键经验沉淀

1. **腾讯云轻量服务器 ≠ CVM**——Lighthouse 控制台路径独立 / 安全组叫"防火墙" / UI 完全不同 / 部署文档之前误把它当 CVM（已修正）
2. **Image cache 复利**：D.5 部署积压前的"试运行 build"留下完整 image / 真部署时全 cache 命中 / build 阶段从预估 5-10 分钟降到秒级
3. **monitor 静默是设计**：4min 软目标超 + 飞书告警，无问题就不打印日志（避免日志噪音）/ 看 `docker compose top monitor` 验证进程在跑
4. **admin token 签发**：admin = 普通 user JWT + DB `users.is_admin=true` / 没独立登录 endpoint / 容器内 `python -c "from app.user.service import create_token; print(create_token(1))"`（user_id=1 是 admin_prod / 7 天有效）

### 当前生产 stack（10 service）

```
api / caddy / cleanup / curation-pool-cron / db / monitor / redis / scheduler / worker / admin-h5
```

### 待办（业务侧 / 不阻塞代码）

- [ ] 小程序前端 UI 接 Sprint 2 endpoint（power-curve / heatmap / profile）—— 属于 Sprint 4
- [ ] FEISHU_BOT_WEBHOOK 真配（建飞书机器人后改 `.env` + `docker compose up -d monitor` 重启 / 否则告警静默）
- [ ] 老数据格式化 bug（如「累计爬升 549.4000000000001m」—— v4 老 bug / 进 tech-debt / 与本次部署无关）

### 回滚路径（必要时）

```
# 数据回滚
sudo docker compose exec -T db psql -U velo velo < ~/velo/backup/pre-sprint123-20260505-2129.sql

# 代码回滚
cd ~/velo && git reset --hard c36a204 && sudo docker compose up -d --build api worker scheduler cleanup
sudo docker compose stop monitor curation-pool-cron admin-h5
```

---

## 给未来 Agent 的提醒

1. **读这个文件和 deploy skill 再动手。** 不要自作主张用 git clone 或多行 SSH 命令。
2. **改了本地代码后要同步到服务器。** 流程是 tar → scp → 解压 → 清理 `._*` → rebuild。
3. **Caddyfile 本地和服务器必须一致。** 当前是 `:80` 无域名模式。
4. **.env 文件不在 tar 包里（被 exclude 了）。** 服务器的 .env 需要单独管理，不要覆盖。
5. **Docker 命令前加 sudo。** ubuntu 用户没有 docker 组权限。
