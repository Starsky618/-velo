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

5. **一次性脚本部署 3 次踩坑**（2026-05-06 R1 恢复脚本 / 跨项目通用教训）：
   - **错 1**：`python -m scripts.x` 失败 / `No module named 'scripts.x'` —— scripts/ 目录没 `__init__.py` 不是 Python 包。**修**：用文件路径 `python scripts/x.py`
   - **错 2**：`python scripts/x.py` 失败 / `No such file: /app/scripts/x.py` —— 服务器 git pull 拿到新脚本但 `velo-api` image 没 rebuild / 容器内 `/app/scripts/` 是旧 image 快照。**修**：`sudo docker compose build api && up -d api` 让 image 含新脚本
   - **错 3**：rebuild 后跑 `python scripts/x.py` 失败 / `No module named 'app'` —— 脚本 `from app.xxx` 但 cwd `/app` 不在 `sys.path`（python 默认 sys.path[0] = 脚本所在目录 `/app/scripts`）。**修**：`docker compose exec -T -e PYTHONPATH=/app api python scripts/x.py`
   - **永久修**（写新一次性脚本时）：脚本顶部加 `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`（参考 `cleanup_zombies.py` line 1 / 项目已有 pattern）/ 这样不需要 PYTHONPATH 也能跑

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

---

## ⚠️ 2026-05-06 admin H5 502 事故复盘（"token 过期"伪信号）

### 现象
Tim 真用 admin H5 (http://114.132.190.245:9000)，登录页粘 token 显示"token 无效或过期"。
重新签发 token 仍失败。第一次以为是 JWT 过期问题，定位浪费 30 分钟。

### Root cause（三层）

**表层：前端误显示**
- `LoginPage.tsx` 旧版 `} catch { messageApi.error('token 无效或过期') }` —— 把 401/403/5xx/网络错全吞成同一句
- 实际后端返的是 502，被显示成"token 失效" → 整条排查方向走错

**中层（真根因）：nginx + docker DNS 缓存**
- admin-h5 nginx.conf 写 `proxy_pass http://api:8000`（hostname 直接出现在 proxy_pass 里）
- nginx 启动时解析一次 `api` hostname 拿到 IP 缓存，之后不再解析
- velo-api 容器某次重启（OOM 自愈 / 部署 / docker prune）拿到新 IP
- admin-h5 nginx 仍连旧 IP → connection refused → 502
- 时间戳证据：`docker compose ps` 看 admin-h5 启动 14h ago，api 启动 12h ago，2h 窗口内 api 重启过一次

**深层：监测盲区**
- `velo-monitor` 只盯 api 进程层（pending activities / scheduler stale）
- 没有"admin H5 → api 反代是否通"的端到端探针
- 真用打开页面才发现，监测系统沉默

### 紧急止血
```
sudo docker compose restart admin-h5   # 让 admin-h5 nginx 重新解析 api hostname
```

### 长期修（已落地 / commit `<刚 commit 哈希>`）

1. **`admin-h5/nginx.conf` 加 resolver 防止 DNS 缓存**：
   ```nginx
   resolver 127.0.0.11 valid=10s ipv6=off;   # docker 内置 DNS

   location /api/ {
       set $upstream_api http://api:8000;     # proxy_pass 变量化 → 不缓存
       proxy_pass $upstream_api;
       ...
   }
   ```
   `proxy_pass` 出现变量时 nginx 强制每次连接前查 resolver。api 容器换 IP 最多 10 秒后 admin-h5 自动恢复，**不需要手动 restart admin-h5**。

2. **`admin-h5/src/api/error.ts` 升级 `getErrorDetail` 单一真相源**：按状态码分流——网络断 / 5xx 后端挂 / 401 token 失效 / 403 不是 admin / 4xx 业务错。LoginPage + 4 个业务页面共用，零误导。

3. **`admin-h5/src/api/client.ts` 修 interceptor 显式 token 被覆盖的 race**（codex 异源审抓到）：原版无条件用 store token 覆盖，导致 LoginPage 显式传新 token 时被 store 旧 token 顶替。改成"仅在请求未自带 Authorization 时才补"。

### 需要部署后验证
- 服务器 `cd ~/admin-h5 && git pull && sudo docker compose build admin-h5 && sudo docker compose up -d admin-h5`
- 重新打开 http://114.132.190.245:9000/login，故意输错 token 看是否显示"token 已失效，请去小程序重新签发"而非"token 无效或过期"
- 故意停掉 api 容器（`docker compose stop api`），看 LoginPage 是否显示"后端服务异常（HTTP 502）..."

### 给未来 Agent 的硬规则

1. **生产报错排查第一步永远是 `docker compose ps` + 看时间戳**，不是猜应用层（token / 权限 / DB）。容器栈状态错位（不同 service 启动时间相差 > 30 分钟）= 强信号有重启过 / 某个依赖容器换 IP。
2. **任何 hostname-based proxy_pass 都要配 resolver + 变量化**，不论 nginx 还是 caddy。docker 容器 IP 不稳定是常态。
3. **前端错误文案绝对不能 catch-all**——一句"操作失败"对运维来说等于 0 信息。轻则浪费时间，重则误导排查方向。**强制按 axios error 形态分流**（无 response = 网络层 / 5xx = 后端挂 / 4xx = 业务）。
4. **部署 admin H5 类静态站时**，service 时间戳要和依赖的后端 service 一致。如果后端重启过，admin-h5 nginx 也跟着 restart 一次。这条加进部署 SOP。

---

## 2026-05-18：Persona Engine v0.1 全 Sprint ship（NPC 文案系统 6 task 完结）

**Sprint 时间线**（4 天高密度执行 / 2026-05-15 brainstorm → 2026-05-18 task-6 ship）：

| task | commit | 工程 |
|---|---|---|
| task-1 地基（3 表 + 5 空骨架 + Alembic head）| `f3490fc` | 4 测试通过 |
| task-2 文案库（168 条 + template_lib 4 函数）| `fd8308c` + `7a2f5d4` | 12 测试 / 8 轮 cycle Tim 拍板 |
| task-3 决策大脑（router/filters/cache/service）| `af3c603` | 35 测试 / Critical 3 全修 |
| task-4 业务接入（worker hook + endpoint + scanner 容器）| `ee555ad` | 9 测试 / Critical 2 全修 / persona-scanner 容器 Up |
| task-5 小程序展示（5 page + utils + api 拦截器）| `68c6742` | 20 处 PERSONA_START/END / Critical 3 全修 |
| task-6 final gate（拔出脚本 + diary + Sprint 收尾）| TBD | 1 day |

**真用激活待 Tim 完成**（task-6 plan § 8 场景 / 微信开发者工具上传体验版）：
- 场景 1：注册 + profile 开场 → 看到至少 1 条 NPC 文案
- 场景 2：上传 PR 活动 → toast 显示 PR 场景文案
- 场景 3：上传普通 80km → toast 显示段位文案
- 场景 4：上传极端数据（< 5km / > 150km / 23 点后 / > 35 km/h）
- 场景 5：连骑高频 mock → consecutive_high 文案
- 场景 6：沉寂 8 天 mock + 跑 silence scanner
- 场景 7：累计跨 10000km + 跑 milestone scanner → "1 万了。老登正式入会。"
- 场景 8：断网 + 损坏 GPX → 错误页文案

**第三方依赖激活状态**（按 memory feedback_real_usage_vs_mock_blindspot 第 5 类盲区）：
- DeepSeek LLM：暂不调（v0.5+ 才接 / 当前 100% 算法 + 模板）
- 后端 endpoint：100% 真用通路（curl 401 verify ✓ + persona-scanner 容器 Up ✓）
- 微信小程序前端：Tim 上传体验版后才能真用

**已知非阻塞项**（task-6 final gate 前不卡 / 留 v1.0+）：
- 24h endpoint 窗口 vs 7 天 cache 语义不完全一致（Codex 抓 / 留真用回归确认）
- 节气表 _SOLAR_TERMS_2026 写死 / 2027 起需刷新
- 闰年 2/29 注册用户周年永远不触发（小概率边界）
- N+1 查询 _check_milestone_distance（100 用户量级可接受）

---

## 2026-05-25：Sprint 10 小程序前端开发版本上传

**范围**：只分发小程序前端，不部署服务器。后端代码与生产容器未变。

**本地源码**：`b11d985`（包含 `3c24dd1` 训练分析读图说明 + `b11d985` Sprint 10 文档状态收尾），已 `git push origin main`。

**微信开发者工具 CLI**：
- `cli islogin`：已登录，IDE service port `http://127.0.0.1:55858`
- `cli preview --project /Users/macbookair/Desktop/velo/miniprogram --qr-format terminal`：成功，包体 `175.2 KB`
- `cli upload --project /Users/macbookair/Desktop/velo/miniprogram --version 2026.05.25.1519 --desc '训练分析读图说明 + Sprint10收尾'`：成功，包体 `177.9 KB`

**注意**：预览二维码写文件模式曾因 `二维码输出路径无效或不存在` 失败；终端二维码模式可用。后续若要自动保存二维码图片，先单独验证 `--qr-output` 的路径规则。

---

## 2026-05-28：单次骑行功率曲线分析 ship + 工程基础设施一组（CI / COS 异地备份 / fail2ban）

**范围**：功能层 1 ship（用户可见单次骑行功率曲线分析） + 运维层 3 升级。详细变更见 `docs/changelog.md` 2026-05-28 段。本节只记**服务器侧关键参数 + 未来接手必知的配置位置**。

### 新增运维资产清单

| 资产 | 位置 | 用途 / 接手必知 |
|---|---|---|
| `.github/workflows/test.yml` | 仓库 | 每次 push + PR 自动跑 pytest（GitHub Actions / 公开仓库无限免费）。改 CI 配置需要 token 带 `workflow` scope（默认 OAuth App 没有 / 用 `gh auth refresh -s workflow` 临时加）|
| `~/.cos_backup_creds` | 服务器 ubuntu home（chmod 600 / 不进 git） | 腾讯云 COS 凭证 / TENCENT_SECRET_ID + TENCENT_SECRET_KEY 两行 / 来自 CAM 子账号 `velo-backup-writer` |
| `~/scripts/backup_db.sh` | 服务器 ubuntu home（host / 不在 docker） | 每天 23:30 跑 / 镜像 `~/velo/backups/` 到 COS bucket `velo-db-114514-1421559057/daily/` / S3 协议接入（rclone）/ 30 天保留 |
| host crontab `30 23 * * *` | `crontab -l` 可见 | 调度 backup_db.sh / 紧跟 docker `db-backup` 容器（23:05）25 分钟后跑 |
| fail2ban service | systemd enabled | SSH 防爆破 / 默认 maxretry=5 / bantime=10min / 监控 /var/log/auth.log |

### COS 备份系统架构

**两层防御**：
1. **现有 docker `db-backup` 容器**（Sprint 5 task-1 ship / 不动）：每天 23:05 → `pg_dump | gzip` → `~/velo/backups/velo_YYYYMMDD_HHMMSS.sql.gz` / 本地 7 天滚动 / monitor 容器有 `backup_freshness` 探针
2. **2026-05-28 新加 host cron**（异地兜底）：每天 23:30 → `rclone copy ~/velo/backups/ → velocos:velo-db-114514-1421559057/daily/` / COS 30 天滚动

**为啥不用 docker 容器统一处理**：现有 `db-backup` 容器基于 `postgres:16-alpine`，里面没 rclone。强行往容器里塞 rclone 等于改 Dockerfile / 高耦合。host cron 只做"镜像同步" / 不重新 pg_dump / 单一真相源。

**转云路径**（未来改阿里云 OSS / AWS S3）：只改 backup_db.sh 顶部 2 个 export 行（`RCLONE_CONFIG_VELOCOS_PROVIDER` + `_ENDPOINT`），其他不动。S3 协议全兼容。

**恢复演练**：`~/scripts/velo_restore_drill.sh` 一行跑 / 拉最新 COS 备份 → 还原到临时 db `velo_restore_test` → 对比 5 关键表 row count → 删临时 db。**已演练通过 / 5 表 row count 完全一致**。

### 服务器侧关键决策记录

#### Q：为什么 fail2ban 用默认配置不自定义？
Ubuntu 22.04 默认 sshd jail 已 enabled / maxretry=5 / bantime=10min。Tim 用 SSH key 不会触发密码失败计数 / 默认配置够。未来如果想看被尝试爆破的 IP：`sudo fail2ban-client status sshd`。

#### Q：为什么 staging 没建？
按 100 用户单人项目 ROI 4 问筛掉（详 memory `feedback_user_pushback_framework_4_questions`）—— 不做没人发现 ✗ / 用户感知不到 ✗ / 100 用户不需要 ✗ / 可回退 ✓ = 1/4 yes。等触发再回来建（用户 > 500 / 或某次 alembic 真炸 / 或大数据量性能改动）。

#### Q：为什么飞书告警没接？
同 4 问筛掉 = 1/4 yes。tech-debt 已记 / 真要时改 .env 一行即可激活（memory `project_velo_alert_channel_deferred`）。

### 给未来 Agent 的硬规则（本 session 沉淀）

1. **建任何"基础设施类"东西前必跑 5 项 grep**（memory `feedback_pre_build_must_grep_server_state`）—— 否则 90% 概率"提议的东西已存在"，重复造轮子。本 session DB 备份事故是反面教材：陪 Tim 跑 90 分钟创 COS bucket / CAM / 演练 → 后期才发现 velo 早有 db-backup 容器。
2. **deploy SOP 加 DEPLOY-7 本地 git pull**（deploy-sop.md / commit `8a14df6`）—— 服务器 deploy 完后**必跑** `cd ~/Desktop/velo && git pull`，否则微信开发者工具读旧 miniprogram = 用户报"完全看不到"。
3. **OAuth App token 改 `.github/workflows/` 会被拒**——错误信息 `refusing to allow an OAuth App ... without 'workflow' scope`。用 `gh auth refresh -s workflow --hostname github.com` 触发设备码授权 / Tim 浏览器 1 步授权后即可 push CI 文件。

## 2026-06-05：发起约骑新原型 — 后端部署（meetups 加 6 列 + 私圈口令门禁）

- **改动**：纯后端 schema + 逻辑（meetups 加 6 列 / 私圈 share_token 门禁 / GET /{id}/participants / publish 截止）。前端 UI 还原本轮只 commit+push **未走服务器**（小程序前端在微信开发者工具本地编译上传，不经服务器）。
- **6 步 SOP 实跑**：DEPLOY-0 `git push origin main`（69f7f4e..7884b72）→ DEPLOY-1 服务器 `git pull`（→7884b72）→ DEPLOY-2 跳过（本次不涉及 heatmap/power_curve 缓存）→ DEPLOY-3 `sudo docker compose up -d --build`（全容器重建，api 启动无报错）→ DEPLOY-4 `alembic upgrade head`（`20260602_tencent_route_book → 20260603_meetup_create_fields`，加 6 列 + visibility CHECK，存量行 server_default 兜底）→ DEPLOY-5 curl 验证（api 容器内 `GET /api/meetups` 200 + 6 新字段序列化正常，存量 6 条约骑无 500）。DEPLOY-6/7 本轮前端在本地 main 已就绪、不需。
- **踩坑**：`curl localhost:8000` 从宿主机返回 000——api 端口只在 docker 网络（caddy 反代），不映射宿主机。验证要么进 api 容器 `docker compose exec -T api`、要么走 caddy 公网域名。本次用容器内 python urllib 验。
- **⚠ 待真用激活回归**（owner 24h 内真机跑）：① 私圈分享：建 invite_only 约骑 → 转发带 token 链接 → 好友能进能报名 / 陌生人猜 id → 404 ② 草稿恢复 ③ 图二就地编辑 + 图一确认 + 发布 ④ publish 30min 截止拦。**Tim 需先在微信开发者工具重新上传小程序**（前端 head aefd411）用户才看到新 UI。

## 2026-06-11：Sprint 13+14 上线冲刺部署（熟人约骑闭环 + 路线百科上架）

- **代码**：`60f660c` → `a813956`（18 commits / S13 T1-T5+T4 + S14 T7-T9 + 折叠 UX + subkey + 日志 hotfix）
- **迁移**：`20260611_meetup_activities` + `20260612_route_guides` 一次 upgrade 到 head，全量 `--build`（scheduler 挂 attach tick / worker 验 garmin_fit_sdk import ok）
- **灌库**：route_guides 11 条全进（dry-run → apply → SQL count=11）；**全部 track_pending**（content 目录暂无 track.gpx）——路线页有完整介绍但无曲线/无地图/「发起约骑」按钮不显示，等 GPX 补充后重跑灌库脚本幂等升级（升级路径已有测试锚）
- **真用回归抓到喇叭没插电第 4 例**：api 容器（uvicorn）从未配应用层日志 handler，业务 logger.info 全被吞——五环节 SENSOR 埋点请求 200 但日志零输出；caplog 测试测不出。修法 = main.py 一行 basicConfig（`a813956`），复测 SENSOR view 行真实出现
- **TENCENT_MAP_KEY**：生产 .env 存在（spec §0.1 ⚠️ 销账）；同 key 已填前端 map-theme subkey 启用个性化底图
- **待 Tim 真机**：小程序上传 / FIT 真传一次（喇叭位 2）/ 5 文件计时 p90 落 PRD / share_token 半生人剧本（喇叭位 3）/ 折叠页观感 + 底图浅色样式确认（layerStyle 编号不对就改 map-theme 一个数字）

## 2026-06-12：weiluai.top HTTPS 全链路打通（防火墙 443 + 前端切域名 + Strava 回调切换）

- **昨天卡点的真相分层**（诊断教训）：昨天判"备案白名单未同步"临时回退 IP；今天复查发现备案其实已同步（80 端口 308 跳转实证），真正卡点是**轻量服务器防火墙没放行 443**。两个症状的判别指纹：备案 SNI 阻断 = TCP 握手后 reset；安全组/防火墙拦 = SYN 直接丢（连接超时）。本次服务器自访 443 超时 → 防火墙实锤。
- **关键认知：证书签发成功 ≠ HTTPS 可用**——Let's Encrypt ACME HTTP-01 challenge 走 80 端口，80 通就能签证书；443 被防火墙挡着证书照样续期、HTTPS 照样全不通。看到"证书在管"别推断"https 没问题"。
- **操作记录**：① CDP 浏览器复用 Tim 登录态进腾讯云轻量控制台（实例 lhins-66ggox65 / 广州），防火墙规则表实证只有 9000/22/80/ICMP，添加 TCP 443 允许 ✅ ② 服务器自测 https://api.weiluai.top 从超时变 401（业务正常）✅ ③ 微信小程序服务器域名昨天已配好（request/uploadFile/downloadFile 三栏 = api.weiluai.top，无需动）④ 前端 baseUrl 两处切 https 域名（`80cceab9`）⑤ Strava 后台 Authorization Callback Domain：114.132.190.245 → api.weiluai.top（先改后台再改 .env，顺序反了授权流程会断）⑥ 服务器 .env STRAVA_REDIRECT_URI 切 https 域名 + `up -d --force-recreate api`（**restart 不重读 env_file，必须 recreate**）。
- **⚠ 待真用激活回归**：① Tim 真机重新编译走 https 域名跑全功能 ② Strava 解绑重绑一次验证新回调（回调域改了，老 authorize 链接缓存可能失效）③ **业务域名缺口挂账**：web-view 打开 Strava 授权页需要"业务域名"配置（与"服务器域名"是两个配置项），IP 时代本来就没配过（IP 配不进业务域名），正式版 Strava 绑定流程依赖它——需在 mp 后台业务域名加 strava.com + api.weiluai.top（要下载校验文件放服务器，下轮做）。
