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

## 给未来 Agent 的提醒

1. **读这个文件和 deploy skill 再动手。** 不要自作主张用 git clone 或多行 SSH 命令。
2. **改了本地代码后要同步到服务器。** 流程是 tar → scp → 解压 → 清理 `._*` → rebuild。
3. **Caddyfile 本地和服务器必须一致。** 当前是 `:80` 无域名模式。
4. **.env 文件不在 tar 包里（被 exclude 了）。** 服务器的 .env 需要单独管理，不要覆盖。
5. **Docker 命令前加 sudo。** ubuntu 用户没有 docker 组权限。
