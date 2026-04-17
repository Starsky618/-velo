# 任务 7.9：scheduler 容器部署

> 修 Critical-03：当前 Strava 调度器**根本没跑**——docker-compose 里没这个容器。生产 30 条活动导入完全靠手动 sync 碰运气，用户绑定后看到"正在导入..."可能永远不动。

---

## 🎯 目标（一句话）

给 VELO 生产环境加一个"常驻调度器进程"——每 30 秒钟自动去 Strava 拉新活动、推进导入进度，不依赖任何外部触发。

---

## ⛓ 前置依赖

- **task-7.5**（`get_import_progress` 新接口 view_status 已就位，stalled 判定生效后用户能看到调度器是否在跑）
- **task-7.6**（I9 tier1 连续 2 次空确认机制生效，调度器行为更可靠）

> 理论上 7.9 不**强依赖** 7.5/7.6 才能部署，但上线顺序上 **7.5/7.6 先合入**有利于部署验证——用户能立刻看到 stalled 自愈行为和进度推进。

## 📥 输入契约

**现有代码事实核对**：

| 项目 | 位置 | 现状 |
|------|------|------|
| 调度器核心 | `app/strava/import_scheduler.py:46 run_import_tick()` | 已实现完整 tick 逻辑 |
| Worker 模式参考 | `worker.py`（根目录） | 长期运行的守护进程模板 |
| 现有 Dockerfile | `Dockerfile` | `WORKDIR=/app`，已复制所有 app/ 代码 |
| docker-compose 已有服务 | api / worker / cleanup / caddy | 无 scheduler |

## 📤 输出契约

| 产出 | 位置 | 说明 |
|------|------|------|
| `scheduler.py` | 项目根目录（新建） | 常驻守护进程脚本 |
| `docker-compose.yml` 加 scheduler 服务块 | yml 文件 | 与 worker 同模式、独立容器 |

---

## 🛠 完整代码

### 1. 新建 `scheduler.py`（项目根目录）

```python
"""
Strava 导入调度器——常驻进程，每 30s tick 一次。

为什么不用 rq-scheduler / celery-beat / APScheduler：
    1. 项目只有一个周期任务（tier1/tier2 导入），引入上述方案开销不成比例
    2. 简单 while + sleep 就能满足：30s tick 一次，每次 tick 处理所有 active 用户
    3. 异常绝对不中断循环——单次 tick 失败只记日志，下一轮继续
    4. 未来需要多个周期任务时（如定时发送骑行简报）再迁移到 rq-scheduler

为什么要在单独容器（不和 worker 合并）：
    worker 是 RQ 工作进程（消费队列），scheduler 是时间驱动进程（产生任务）。
    职责不同、重启策略不同（worker 崩溃影响单个任务，scheduler 崩溃影响全量导入）。
    分开更清晰也更便于监控。

运行方式：
    本地：python scheduler.py（cwd 必须是项目根目录，否则 import 失败）
    Docker：WORKDIR=/app + command: python scheduler.py
"""
import logging
import time

from app.strava.import_scheduler import run_import_tick


# 日志格式：时间 + 进程标识 + 消息——进容器日志后一眼能认出是哪个进程
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# tick 间隔（秒）——Strava 每 15 分钟配额 100 请求，30s 一轮完全吃得消
_TICK_INTERVAL_SECONDS = 30


def main():
    logger.info("Strava scheduler 启动（tick 间隔 %ds）", _TICK_INTERVAL_SECONDS)

    while True:
        try:
            run_import_tick()
        except Exception:
            # 关键纪律：任何异常都不能让循环退出
            # logger.exception 会自动打印完整 traceback，便于诊断
            logger.exception("tick 执行失败")

        time.sleep(_TICK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
```

### 2. `docker-compose.yml` 加 scheduler 服务

在 `cleanup` 服务块之后、`caddy` 之前**插入**：

```yaml
  # ===== Scheduler：Strava 导入调度器 =====
  # 每 30s 触发一次 run_import_tick，推进所有 active 用户的 tier1/tier2 导入
  # 和 worker 分开的理由：worker 是队列消费者，scheduler 是时间驱动
  # 职责不同 → 独立容器便于监控和重启
  scheduler:
    build: .
    command: python scheduler.py
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://velo:${DB_PASSWORD}@db:5432/velo
      REDIS_URL: redis://redis:6379/0
      STRAVA_CLIENT_ID: ${STRAVA_CLIENT_ID}
      STRAVA_CLIENT_SECRET: ${STRAVA_CLIENT_SECRET}
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads
```

> **为什么 env 列表比 api 少**：scheduler 只需要 DB + Redis + Strava 凭证。不需要 JWT_SECRET（它不处理请求）、不需要 WX_APPID（不涉及微信）、不需要 STRAVA_REDIRECT_URI（不接 OAuth）、不需要 WEBHOOK 相关（不收 webhook）。**严格按需**最小化攻击面。

### 3. 不改 `Dockerfile`

**预读验证**：`Dockerfile` 已有 `WORKDIR=/app` 和 `COPY . .`（或 `COPY app/ app/` + 根目录 .py）——scheduler.py 会被自动包含，无需改 Dockerfile。若 Dockerfile 是严格白名单 COPY（比如只 COPY worker.py），需要追加 `COPY scheduler.py .`——打开 Dockerfile 确认一下。

---

## 🚀 部署步骤

### 本地开发验证

```bash
# 1. 在 VELO 项目根目录
cd /Users/macbookair/Desktop/velo

# 2. 本地直接跑（cwd 必须是根目录）
python scheduler.py

# 应看到：
# 2026-04-xx xx:xx:xx [scheduler] INFO Strava scheduler 启动（tick 间隔 30s）
# （每 30s 会有 import_scheduler 内部日志）

# 3. Ctrl+C 停止
```

### 生产部署（服务器 ubuntu@114.132.190.245）

```bash
# 1. scp 新文件上去（因大陆 GitHub 不稳）
scp scheduler.py ubuntu@114.132.190.245:~/velo/
scp docker-compose.yml ubuntu@114.132.190.245:~/velo/

# 2. SSH 进去启动
ssh ubuntu@114.132.190.245
cd ~/velo
sudo docker compose up -d scheduler

# 3. 验证日志
sudo docker compose logs scheduler --tail 30

# 4. 应看到：
#    xxx [scheduler] INFO Strava scheduler 启动
#    xxx 跑了 tier1/tier2 的实际日志（看现有 StravaImport 有哪些 active 任务）
```

### 生产验证 checklist

```bash
# 1. 容器在跑
sudo docker compose ps | grep scheduler
# 应该是 Up 状态

# 2. 日志无异常堆栈
sudo docker compose logs scheduler --tail 100

# 3. 用户侧验证
# 找一个有 active import 的用户，调 import-progress：
curl -H "Authorization: Bearer TOKEN" \
  https://DOMAIN/api/strava/import-progress
# 等 1 分钟后再调，total / completed 应有变化

# 4. 异常重启测试
sudo docker compose restart scheduler
sudo docker compose logs scheduler --tail 30
# 应看到重新"Strava scheduler 启动"日志
```

---

## 🧪 测试

### 单测：`tests/test_scheduler_entry.py`（新建）

```python
"""scheduler.py 是守护进程入口，单测只验证三件事：
1. import 不崩
2. 循环结构正确（while + sleep）
3. 异常不中断循环
"""
from unittest.mock import patch


def test_scheduler_imports_cleanly():
    """确认 scheduler.py 能 import 不报错。"""
    import scheduler  # noqa: F401


def test_main_loop_calls_run_tick_and_sleeps():
    """验证 main 循环调用 run_import_tick + time.sleep。"""
    import scheduler

    call_count = {"tick": 0, "sleep": 0}

    def fake_tick():
        call_count["tick"] += 1
        if call_count["tick"] >= 2:
            raise KeyboardInterrupt()  # 跳出 while True

    def fake_sleep(seconds):
        assert seconds == scheduler._TICK_INTERVAL_SECONDS
        call_count["sleep"] += 1

    with patch.object(scheduler, "run_import_tick", side_effect=fake_tick), \
         patch.object(scheduler.time, "sleep", side_effect=fake_sleep):
        try:
            scheduler.main()
        except KeyboardInterrupt:
            pass

    assert call_count["tick"] == 2
    assert call_count["sleep"] >= 1


def test_main_loop_survives_exception():
    """tick 抛异常 → 循环继续下一轮。"""
    import scheduler

    call_count = {"tick": 0}

    def fake_tick():
        call_count["tick"] += 1
        if call_count["tick"] == 1:
            raise RuntimeError("模拟 tick 崩")
        if call_count["tick"] >= 3:
            raise KeyboardInterrupt()

    with patch.object(scheduler, "run_import_tick", side_effect=fake_tick), \
         patch.object(scheduler.time, "sleep"):
        try:
            scheduler.main()
        except KeyboardInterrupt:
            pass

    # 第一次崩了，但循环没退——第 2、3 次都跑了
    assert call_count["tick"] >= 2
```

---

## 📦 Commit 指令

```bash
git add scheduler.py docker-compose.yml tests/test_scheduler_entry.py

git commit -m "$(cat <<'EOF'
feat(deploy): 任务 7.9 新增 scheduler 容器（修 C3）

scheduler.py（项目根目录）：
- 常驻进程，每 30s 调 run_import_tick() 一次
- 异常绝不中断循环（只记 logger.exception）
- 学习 worker.py 模式：简单 while + time.sleep

docker-compose.yml 加 scheduler 服务：
- build 同 api/worker 镜像
- command: python scheduler.py
- restart: unless-stopped
- 最小 env：DB + Redis + Strava 凭证
- 不需 JWT/WX/REDIRECT_URI/WEBHOOK

部署步骤见 docs/plans/phase4/task-7.9.md 的"部署步骤"节。

测试：3 个用例验证 import 清洁、循环调度、异常不中断。
EOF
)"
```

---

## ✅ 自检三问

**1. 10 分钟挑战**：讲清加了什么、为什么现在才加？

> 我们一直有个"Strava 导入调度器"的函数（`run_import_tick`），逻辑完整——但从来没人**周期性地调它**。生产上 30 条活动能导入其实是靠"绑定时一次性拉"+"用户手动 sync"，系统后台根本没在跑。
>
> 这次加一个独立容器 `scheduler`，里面一个死循环每 30 秒调一次 tick 函数。跟工厂门口的打卡机一样，机器不停地响，就会不停地推进所有人的导入进度。

**2. 崩溃场景**：scheduler 进程挂了怎么办？

> Docker 的 `restart: unless-stopped` 自动重启。进程级崩溃（比如 OOM）几秒内恢复。
>
> 更关键的是：即使 scheduler 挂 10 分钟，用户也不会"数据丢失"——只是进度推不动。前端的 stalled 判定（task-7.5）会识别"updated_at 超 5 分钟"，给用户一个"导入似乎卡住了"的提示，避免前端傻转。

**3. 边界纪律**：有没有做 spec 没要求的"顺手优化"？

> 没有。严格 §4.1 范围：
> - 没用 rq-scheduler / celery-beat（简单 while 够用，引入框架开销不成比例）
> - 没加 Prometheus metrics（监控是下一期的事）
> - 没加 healthcheck（Docker 层面已有 restart 兜底）
> - 没改 tick 间隔（保持 spec 写的 30s）
> - 没动 import_scheduler.py（那是逻辑层，本任务只写运维层）
