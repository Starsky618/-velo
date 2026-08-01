# velo 部署 SOP（Codex / 任何 agent 部署前必读）

> **读者**：Codex（主开发或 hotfix 后部署时）、Claude Code、任何要把 velo 推上生产的 agent。
>
> **目标**：让 agent 部署 velo 时不再踩"本地全绿 → 生产炸"的坑。本文是部署动作的**单一真相源**。
>
> **核心信条**：**本地测试全绿 ≠ 生产能跑**。测试用 SQLite + mock，不连真 Docker / PostgreSQL / Strava API。`commit ≠ ship`——commit 完代码还在本地，用户连的是生产，没部署 = 用户看不到改动。
>
> **来源**：合并自 Claude 侧 9 条 memory（deploy-curl-verify / deploy-rebuild-all-containers / diagnosis-container-stack-first / real-usage-vs-mock-blindspot / ssh-remote-secret-redact / standalone-script-orm-loading / logger-warning-narrative-trap / throttling-real-rate-limit / oneshot-cron-sentinel / alert-channel-deferred）+ `~/.claude/skills/deploy` skill。本文已把 mock 盲区从 skill 旧版的 5 类**更新到 6 类**（补 2026-05-21 Sprint 9 算法语义错实证）。
>
> **部署前请读全文** §2（6 步 SOP）+ §3（checklist）+ §5（排查因果链），不要只看顶部摘要。

---

## §1 服务器信息

| 项目 | 值 |
|---|---|
| IP | 114.132.190.245 |
| 用户 | ubuntu |
| 代码路径 | ~/velo |
| Docker 命令前缀 | sudo（所有 docker compose 命令都要 sudo）|
| 部署方式 | git pull + `docker compose up -d --build`（备用 scp+tar）|
| 数据库迁移 | `sudo docker compose exec api python3 -m alembic upgrade head` |
| 看日志 | `sudo docker compose logs api --tail 30` |
| Redis cache prefix | `heatmap:` / `power_curve:`（改了对应 response schema 必清）|
| 容器列表 | api / worker / scheduler / db / redis / monitor / db-backup / admin-h5 / nginx |

> 多个容器共享同一 image（`build: .`）：api / worker / scheduler / monitor / cleanup / curation-pool-cron。改了某个 service 的 `.py`，必须 rebuild **该 service 对应的容器**。

---

## §2 部署 SOP（6 步，顺序不可乱，缺一不算部署完成）

### 路径 A：git + docker build（推荐）

```bash
# DEPLOY-0  本地先 push（最基础但最常漏 / 2026-05-09 事故根因）
git status -sb               # 看 ahead origin / 期望 ahead 0
git log origin/main..HEAD    # 列待 push 的本地 commit
git push origin main         # 本地 commit 上 origin / 远端才能 pull
# 若 ahead > 0 还没 push，远端 git pull 会"already up to date"假成功

# DEPLOY-1  远端 pull
ssh ubuntu@114.132.190.245
cd ~/velo
git fetch && git log --oneline HEAD..origin/main   # 确认有待部署 commit
git pull
git log --oneline -3                               # 验证 head 真到了最新 commit

# DEPLOY-2  改了对外响应 schema 字段 → build 前先清相关 Redis cache
# 判断：commit diff 含"对外响应 schema 字段改名/增删/类型变化" = 必清（否则旧 cache 命中 → ResponseValidationError 500）
sudo docker compose exec -T redis redis-cli --scan --pattern 'heatmap:*' \
  | xargs -I {} sudo docker compose exec -T redis redis-cli del {}
sudo docker compose exec -T redis redis-cli --scan --pattern 'power_curve:*' \
  | xargs -I {} sudo docker compose exec -T redis redis-cli del {}

# DEPLOY-3  rebuild（不能只 restart）
# 原因：build:. 无 volume mount，restart 只重启进程不重建 image，容器跑的还是旧代码
# 纯 website/ 静态内容例外：website 通过只读 bind mount 进入 Caddy，服务器 git pull
# 后立即生效。确认整个待部署 commit 范围没有后端、Caddyfile 或 Compose 变更时，跳过
# 本步的 build/recreate，直接执行官网专项公网 gate 和 API 健康回归；website/ 已从
# 后端 Docker build context 排除，静态资源不应触发 api/worker/scheduler 镜像重建。
# 改 Caddyfile 时先用不占端口的一次性容器读取当前工作树做 preflight，失败就停，不能先打断 API：
sudo docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile
sudo docker compose up -d --build           # 默认不指定 service，自动 rebuild 所有受影响容器（最稳）
sudo docker compose logs api --tail 20      # 看启动日志确认 healthy
# ⚠ 若指定 service：改 worker.py 必须 rebuild worker，别只 rebuild api（2026-05-20 漏 worker 静默失效 30min）
# ⚠ preflight 通过后，只有改 Caddyfile 或 Caddy volumes 时才 recreate caddy；纯 website/
#   内容是 bind mount，禁止为此重启共享 API 入口：
#   sudo docker compose up -d --force-recreate caddy
#   sudo docker compose logs caddy --tail 30

# DEPLOY-4  alembic（硬性必跑，哪怕你"觉得这次没改 schema"）
# 并行开发时别人加的迁移你也得跑；2026-05-15 跳过这步 → 生产全 endpoint 500
sudo docker compose exec -T api python3 -m alembic upgrade head

# DEPLOY-5A  OpenAPI 合同（新增 / 改动 endpoint 时必跑；网络上只发 GET）
# `--require POST:/path` 只是检查 OpenAPI 是否声明 POST，不会真的调用业务接口。
# 下列占位符故意无法通过；每次必须替换为本次新增 / 改动的全部方法与真实路径。
sudo docker compose exec -T api python3 scripts/check_live_api_contract.py \
  --base-url https://api.weiluai.top \
  --require 'POST:/api/<changed-resource>' \
  --require 'GET:/api/<changed-resource>/{id}'
# 任一非 0 都阻断：1=脚本异常，2=参数错误，3=目标/OpenAPI 不可采信，4=合同缺失。

# DEPLOY-5B  authenticated curl verify（必跑 / 不能信 docker ps Up）
# docker ps "Up" 只代表容器进程在跑，不代表代码更新了
TOKEN=$(sudo docker compose exec -T api python -c '<token 签发 snippet>' | tail -1)
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8000/<改动的 endpoint>"
# 期望：200 + response schema 跟新代码一致
# 失败 422 / Field required → git pull 没生效 / image 没 rebuild / schema 漂移

# DEPLOY-6  grep 前端入口（涉及"让用户在 UI 点 X / 走 Y 流程"时必跑）
grep -rn "<按钮文案 或 endpoint key>" miniprogram/pages/ miniprogram/components/
# 期望 ≥ 1 hit / 0 hit = 用户无法触达 = SOP 失效（2026-05-11：后端修好了但前端 0 个 OAuth 入口）
# 纯后端 endpoint 改动不涉及用户主动触发 → 这步可跳（curl 就够）

# DEPLOY-7  本地工作树 git pull（涉及 miniprogram/ 改动时硬性必跑 / 反复踩 ≥2 次的坑）
# 微信开发者工具读的是本地 ~/Desktop/velo/miniprogram/ 源码，不是服务器代码
# 服务器 deploy 完 + 本地工作树没 pull = IDE 看不到新组件 = 用户报"完全没有"
# 现象：组件标签找不到 → wxml 静默跳过（不报错不显示）= "完全没有"的伪信号
cd ~/Desktop/velo && git pull --no-rebase --no-edit
# 之后微信开发者工具点编译刷新按钮，新组件出现
# 纯后端改动（无 miniprogram/ diff）可跳

# DEPLOY-8  清部署垃圾（每次 --build 部署后顺手跑 / 2026-06-11 实证：283 个镜像只有 11 个在用，
# 38GB 旧镜像把 59G 盘吃到 82%——业务数据本身才 180MB。prune 只删无容器引用的镜像，在跑的不动）
ssh ubuntu@114.132.190.245 "sudo docker image prune -a -f && sudo docker builder prune -f"
```

### 官网 / Caddy 专项 gate

涉及 `website/`、`Caddyfile`、Caddy volume 或根域 DNS 时，在通用步骤之外必须完成：

1. DNSPod 权威查询确认 `weiluai.top A → 114.132.190.245`、`www CNAME → weiluai.top`，且 `api.weiluai.top` 记录未变化；
2. 改 `Caddyfile` 或 Caddy volume 时，先用不占端口的一次性 Caddy 容器读取当前工作树并执行 `caddy validate`；通过后再用 `docker compose up -d --force-recreate caddy` 让配置或新增挂载进入正式容器，并检查启动日志。仅改 `website/` 内容时，确认只读 bind mount 已更新，不重建或重启 Caddy；
3. 公网分别验证根域首页、公司页、两份隐私政策、中英文页、未知路径 404、`www` 永久跳转和 `api` 健康检查；
4. 验证根域请求 `/uploads/`、`/uploads/meetup_media/`、`/uploads/route_covers/` 和编码路径穿越均不能读取文件；
5. 检查 Caddy 日志，确认根域与 `www` 证书已签发且没有持续 ACME 错误。

官网回滚必须同时处理代码与 DNS：先恢复上一版 Caddy/Compose 并 recreate
Caddy；如果上一版没有根域站点，则同步删除或暂停根域 A 与 `www` CNAME，避免 HTTP
请求落入 `:80` API 兜底。回滚后再次验证 `api.weiluai.top` 正常。

### 路径 B：scp + tar（备用 / 大陆服务器连 GitHub 不稳时）

```bash
cd ~/velo-local && python -m pytest tests/ -x -q     # 测试不全绿 = 不许部署
tar czf /tmp/velo.tar.gz --exclude='.venv' --exclude='__pycache__' \
  --exclude='.env' --exclude='uploads' --exclude='.DS_Store' -C ~/velo-local .
scp /tmp/velo.tar.gz ubuntu@114.132.190.245:~
ssh ubuntu@114.132.190.245 "cd ~/velo && tar xzf ~/velo.tar.gz && find . -name '._*' -delete"
# 之后同路径 A 的 DEPLOY-3 ~ DEPLOY-6
```

---

## §3 Pre-deploy Checklist（每次部署前必过）

- [ ] **requirements.txt 完整**？本地 pip install 的新包都写进去
- [ ] **docker-compose.yml 同步**？`.env` 加新变量 → docker-compose `environment` 段也加
- [ ] **Alembic 迁移在 PostgreSQL 上能跑**？别在迁移脚本用 Python try/except 包 DDL（PG 事务 abort 后所有后续 SQL 都失败）→ 用 `DO $$ EXCEPTION` 块隔离
- [ ] **第三方 OAuth 回调地址配了**？代码里写 redirect_uri 不够，第三方平台后台也要配
- [ ] **scope 够不够**？Strava `activity:read` 会静默过滤私密活动，要私密活动用 `activity:read_all`
- [ ] **服务器能连 GitHub**？大陆服务器不稳 → 备用走路径 B
- [ ] **改了 schema** → 提前确定要清哪些 Redis cache prefix

---

## §4 部署后真用回归（Final Gate / 单测过 ≠ 生产工作）

**owner 部署后 24h 内必须真用一次**（核心反馈环 + admin 工具 + 数据迁移路径）。下面 6 类是 mock/单测测不出、只有真路径才暴露的盲区。

1. **Mock 断言只验"调了什么 args"，不验"被调组件能否消化"**
   - 实证：admin RQ `enqueue(retry={"max":2})` dict 单测过 / 真 RQ 2.7 期望 `Retry` 对象 → 生产 503
   - 防御：高风险第三方依赖用 dev stack 真组件集成测试，不用 mock

2. **独立进程 ORM metadata 不完整**
   - 实证：`agent/tasks.py` worker 只 import `Segment` 没 import `User` → FK 解析 `NoReferencedTableError`
   - 防御：worker.py / scheduler.py / scripts/*.py 等独立进程入口**顶部显式 import 所有关联 model**（`# noqa: F401`）

3. **SQLite fixture vs 真 PostgreSQL（dialect 差异）**
   - 实证：PostGIS `ST_*` 在 SQLite 不存在 → `OperationalError: no such function`
   - 防御：dialect 守卫 `if db.bind.dialect.name == "postgresql":` + dev stack 真 PG 跑关键路径

4. **单线程测试 vs 真容器集群（race / 网络 / cache）**
   - 实证：nginx DNS 缓存旧 IP 502 / 小程序 wx:if canvas race 90% 设备不渲染 / Strava cursor inclusive 死循环
   - 防御：dev stack 真容器集群跑关键链路

5. **第三方依赖激活状态（"喇叭没插电源"）**
   - 实证：admin_h5_health 探针 11 单测全过 / 生产 `.env` 没配 `FEISHU_BOT_WEBHOOK` → 告警进 logger.warning 垃圾桶
   - 防御：部署高风险第三方依赖后 24h 内**故意触发一次失败场景**，确认告警/回调/推送真到达；写进 deployment-diary

6. **用户物理直觉抓三审都漏的算法语义错**（2026-05-21 Sprint 9 实证 / skill 旧版缺这条）
   - 实证：ftp_estimator 滑窗 bug 三审（spec+quality+Codex）全过 / Tim 真用一句"5min 一定不在同一条活动、不科学"当场打脸（短窗输出 > 长窗 = 物理矛盾）
   - 模式：数学公式正确 ≠ 输出符合物理约束；reviewer 跑测试但不做物理 sanity check
   - 防御：算法类 task 真用回归必须有**物理直觉断言**；用户报"这数不可能"= Critical，不能因"三审过"反驳

---

## §5 故障排查（按因果链，不直接猜应用层）

> 前端 toast 文案（"token 过期" / "操作失败"）多半是**表层伪信号**，真因常在容器栈/反代/网络层。**第一动作永远先看容器栈，不是查 token/DB**。

```bash
# DEBUG-1  容器栈状态（第一步永远先跑这条）
sudo docker compose ps
# 看 Up/Restarting + 时间戳（错位 > 30min = 强信号 / 某容器刚 OOM 重启过）
# 有 Restarting → sudo docker compose logs <服务名> --tail 50

# DEBUG-2  代码栈状态（容器内 vs host / image 缓存旧版最容易漏）
cd ~/velo && git log --oneline -3                              # host 代码 head
sudo docker compose exec api head -5 /app/<入口文件>           # 容器内代码
sudo docker compose exec api cat /app/<schemas.py> | grep <NewField> -A 5   # 字段级对照
# 不一致 = image 没 rebuild → docker compose up -d --build

# DEBUG-3  Redis schema 缓存（改了 response schema 时）
sudo docker compose exec -T redis redis-cli --scan --pattern '<prefix>:*' \
  | xargs -I {} sudo docker compose exec -T redis redis-cli del {}

# DEBUG-4  第三方依赖激活状态（.env 真配了没 / 故意触发验证告警到达）

# DEBUG-5  跨容器 DNS / 网络
# nginx 用 hostname proxy_pass http://api:8000 启动时解析一次缓存 → api 重启换 IP → 502
# 防御：resolver 127.0.0.11 valid=10s ipv6=off; + set $upstream_api http://api:8000; proxy_pass $upstream_api;
```

**已踩坑**：2026-05-06 admin H5 502，前端显示"token 过期"误导，真根因 nginx DNS 缓存，排查 30 分钟走错路径 —— 第一步看容器栈即可锁定。

---

## §6 运维脚本纪律（scripts/*.py）

1. **节流 sleep 基于官方真限流算，不凭直觉**
   - Strava 真限流 100 req/15min ≈ **9s/req**（不是 100/min）；曾错算 36 倍，跑 25 秒就被踢
   - 写法：查清最严档时间窗 → 平均间隔 = 窗口时长/配额 → sleep ≥ 平均间隔 × 1.2；干跑预估 = total × sleep，不是凭感觉

2. **catch 块第一行 `logger.exception` 打 traceback，不用 `logger.warning("token 无效")`**
   - 错误信息描述**动作**（"初始化 client 失败"）不描述**推测根因**（"token 无效"）
   - 实证：`StravaClient(user)` 漏传 db 参数的 TypeError 被 except 吞 + warning 编出"token 失效"假叙事 → Tim 一天后才发现 410 条全 NULL

3. **顶部显式 import 所有外键关联 ORM**（`# noqa: F401`）
   - 否则真跑 commit 时炸 `could not find table 'users'`；实证 backfill 真跑 286 条全失败

4. **gate = dry-run + apply 至少 1 条成功**
   - pytest（conftest 直接建 SQLite 表，不走 ORM metadata）和 code review 都测不出 ORM 注册时机陷阱

5. **一次性延时任务用 crontab + sentinel 文件**（不用 atd / systemd timer / nohup+sleep）
   ```bash
   0 2 * * * test ! -f ~/TASK.done && cd ~/velo && sudo docker compose exec -T api python3 -m scripts.TASK > ~/TASK.log 2>&1 && touch ~/TASK.done
   ```
   - 绝对路径（cron 无 $HOME 展开）/ `docker compose exec -T` 关 TTY（cron 无 TTY）/ sentinel 跑完自挡 / SSH 断无影响 / 失败不创建 sentinel 次日自动重试

---

## §7 硬约束（违反代价高）

- **SSH 只用单行命令**：绝不多行 / heredoc / 未转义 `!`
- **所有 docker compose 前加 sudo**
- **macOS tar 后服务器必清隐藏文件**：`find ~/velo -name '._*' -delete`（否则 alembic 报 null bytes）
- **SSH 远程命令前脱敏 secret**：`git remote -v` / `cat .env` / `docker config` 会吐 token/密码，必须先 sed 脱敏再跑（2026-04-29 曾把 GitHub PAT 完整打印到上下文泄露）
  - 安全替代：`git config --get remote.origin.url | sed 's/:[^:@]*@/:***@/'` / `cat .env | sed 's/=.*/=<REDACTED>/'`
  - 绿灯（无 secret 可放心跑）：`git log/status/diff` / `docker compose ps` / `docker compose logs <service>` / `alembic current/history`

---

## §8 决策提醒

- **告警通道（D 决策）**：velo 现阶段 100 用户量级 + admin H5 仅内部用 → 监测探针代码沉淀但**暂不接通告警通道**（log-only）。别硬塞"必须装监测 = 业界标准"。激活路径 = `.env` 加一行 webhook URL + `restart monitor`，**0 行代码改动**。除非用户量到 1000 / admin H5 故障真影响真用户，否则别重新走论证。

---

## §9 常见问题速查

| 现象 | 大概率根因 → 动作 |
|---|---|
| pip install 失败 | 服务器网络抖动 → 重试 `sudo docker compose build api` |
| alembic 报 null bytes | macOS `._*` 文件没清 → `find ~/velo -name '._*' -delete` |
| 容器反复重启 | `sudo docker compose logs <服务名> --tail 20` 看日志 |
| 502 / 504 | DEBUG-1 看容器栈 + nginx DNS resolver 配了没 |
| 422 ResponseValidationError | image 没 rebuild OR Redis cache 未清 → DEPLOY-2 + DEPLOY-3 |
| 部署了但用户看不到改动 | DEBUG-2 对照容器内 vs host 代码 / 多半 restart 没 rebuild OR 本地没 push |
| OAuth 失败 | 第三方平台回调地址 / scope 够不够（read vs read_all 过滤私密数据）|

---

## §10 实证踩坑链（来源 / 防忘 why）

- **2026-04-29 task-0.7** GitHub PAT 泄露 → SSH 远程命令脱敏（§7）
- **2026-05-06 admin H5 502** → 故障排查"容器栈第一" + nginx DNS resolver 变量化（§5）
- **2026-05-06 飞书 webhook** 喇叭没插电源 → 第三方激活状态有意激活回归（§4.5）
- **2026-05-09 task-4.2 v2 polish 3 次踩坑** → SOP 升 5 步（git push 漏 / restart 不 rebuild / Redis schema cache）
- **2026-05-11 Strava scope hotfix 二段** → SOP 加 DEPLOY-6 grep 前端入口（后端修好但前端 0 个 OAuth 入口）
- **2026-05-15 隐私 sprint 迁移** → alembic upgrade 升为硬性步骤（跳过 → 全 endpoint 500）
- **2026-05-15 backfill 节流** → sleep 基于真限流算（错算 36 倍）+ cron+sentinel 调度
- **2026-05-16 backfill ORM** → standalone 脚本顶部 import 所有关联 model + dry-run gate + logger.exception
- **2026-05-20 Persona task-4** → rebuild 所有受影响容器（漏 worker 静默失效 30min）
- **2026-05-21 Sprint 9 ftp_estimator** → mock 盲区第 6 类：用户物理直觉抓算法语义错

---

**骑车路上见。部署完，真用一次再说"修好了"。**
