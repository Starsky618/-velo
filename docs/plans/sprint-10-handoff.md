# Sprint 10 Task-1 Codex Handoff
> 范围：只写给执行 subagent 的工程手册；不改 PRD / 不写代码 / 不碰 task-2 之后实现。依据：上次 commit `b295a59` 只改 `docs/prd/sprint-10-prd.md`（`git show --stat --oneline b295a59` 已验证）。

## 1. 起手必跑

执行者先把地基量一遍，像盖楼前复测地基标高；不要用 memory 或文件名排序猜 head，PRD 已点名 `alembic heads` 防 stale（`docs/prd/sprint-10-prd.md:79-86`, `docs/prd/sprint-10-prd.md:623-628`）。

```bash
python3 -m alembic heads
nl -ba docs/prd/sprint-10-prd.md | sed -n '53,185p'
nl -ba app/activity/models.py | sed -n '42,190p'
nl -ba app/segment/models.py | sed -n '161,170p'
nl -ba migrations/versions/sprint10_user_hr_profile.py | sed -n '1,60p'
rg -n "op.create_table|op.create_index|UniqueConstraint|ForeignKeyConstraint" migrations/versions app tests
```

必须实证三件事：当前 head 是 `sprint10_user_hr_profile`（本机 `python3 -m alembic heads` 输出已验证；PRD 同步写在 `docs/prd/sprint-10-prd.md:83-86`），ORM 继承 `Base`（`app/database.py:40-43`），新增模块要进 Alembic import 清单（`migrations/env.py:22-31`）。

## 2. 文件改动清单

- new `app/training/__init__.py`：约 5-8 行，一句话说明训练负荷模块；PRD 要 task-1 新建此文件（`docs/prd/sprint-10-prd.md:113-118`, `docs/prd/sprint-10-prd.md:141-143`）。
- new `app/training/models.py`：约 55-80 行，定义 `DailyTrainingLoad`；task-3 必须 import 它，不能拖到 task-4（`docs/prd/sprint-10-prd.md:117`, `docs/prd/sprint-10-prd.md:136`）。
- modify `migrations/env.py`：加 `import app.training.models  # noqa: F401`；否则 autogenerate 看不到新表（`migrations/env.py:22-31`）。
- new `migrations/versions/sprint10_daily_training_load.py`：约 70-95 行；revision/down_revision 按 PRD 固定（`docs/prd/sprint-10-prd.md:158-160`）。
- modify `tests/conftest.py`：约 +4 行，import `DailyTrainingLoad` 并 create/drop 表；现 fixture 手动建表/删表（`tests/conftest.py:272-299`）。
- new `tests/test_daily_training_load_model.py`：约 90-130 行，覆盖 ORM 合同、CRUD、UNIQUE、索引、状态枚举。
- keep `requirements.txt` unchanged：SQLAlchemy/Alembic/pytest 已存在（`requirements.txt:6-8`, `requirements.txt:37-38`）。
- do not touch `app/main.py`：router/service/schema 是 task-4 范围（`docs/prd/sprint-10-prd.md:333-340`）。

## 3. 数据 schema 决策

`DailyTrainingLoad.__tablename__ = "daily_training_load"`；表是新防火墙，不改 `activities` / `users` 核心表（`docs/prd/sprint-10-prd.md:141-144`, `docs/prd/sprint-10-prd.md:181-185`）。

- `id`: Python `int` / SQL `Integer` / `primary_key=True` / `autoincrement=True` / nullable no；现有模型同风格（`app/activity/models.py:42-45`, `app/segment/models.py:133-135`）。
- `user_id`: `int` / `Integer` / nullable no / FK `users.id` `ondelete="CASCADE"` / Alembic constraint name `fk_daily_training_load_user_id`；PRD 要 user 外键级联删（`docs/prd/sprint-10-prd.md:146-148`）。
- `date`: `datetime.date` / SQL `Date` / nullable no / 北京时间自然日；写入方先把 `started_at` 转 UTC+8 再 `.date()`（`docs/prd/sprint-10-prd.md:148`, `docs/prd/sprint-10-prd.md:595-599`）。
- `ctl`, `atl`, `tsb`, `tss_today`: `float` / `Float` / nullable no / 均保 1 位小数；字段含义和精度见 PRD（`docs/prd/sprint-10-prd.md:149-153`）。
- `weekly_tss`: `int` / `Integer` / nullable no / 写入前 `round(SUM(float))`；Sprint 12 也读这个整数（`docs/prd/sprint-10-prd.md:153`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:233-239`）。
- `status_band`: `str` / `String(20)` / nullable no / CHECK `ck_daily_training_load_status_band` in `fresh, ok, tired, overreached`（`docs/prd/sprint-10-prd.md:154`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:181`）。
- `updated_at`: `datetime` / `DateTime(timezone=True)` / nullable no / `server_default=sa.func.now()` / `onupdate=sa.func.now()`；项目时间戳用 tz-aware（`app/activity/models.py:164-167`, `docs/prd/sprint-10-prd.md:155`）。
- UNIQUE: `UniqueConstraint("user_id", "date", name="uq_daily_training_load_user_date")`；PRD 要每用户每天一条，task-6 upsert 靠它（`docs/prd/sprint-10-prd.md:156`, `docs/prd/sprint-10-prd.md:547`）。
- Index: `idx_dtl_user_date` on `(user_id, date DESC)`；task-4 365 天查询走它（`docs/prd/sprint-10-prd.md:157`, `docs/prd/sprint-10-prd.md:383`）。
- Alembic: `revision = "sprint10_daily_training_load"` / `down_revision = "sprint10_user_hr_profile"`；真实上游迁移 revision 在 `migrations/versions/sprint10_user_hr_profile.py:11-12`。

## 4. 单测列表

新增 5 个 pytest case。测试像给地基做抽检：不测 task-2 算法，只证明这张表能被后续任务安全使用。

- `test_daily_training_load_columns_match_contract`：断言字段名、nullable、SQL 类型、`status_band` 长度。
- `test_daily_training_load_crud_roundtrip`：用 `db` fixture 新建 User + DailyTrainingLoad，按 `user_id/date` 查回。
- `test_daily_training_load_unique_user_date_rejected`：同一 `user_id/date` 插两行应 `IntegrityError`；现有测试已用这个模式（`tests/test_user_city_field.py:110-120`）。
- `test_daily_training_load_index_exists`：用 `sqlalchemy.inspect(db.bind).get_indexes("daily_training_load")` 断言 `idx_dtl_user_date` 存在。
- `test_daily_training_load_status_band_check_declared`：断言 ORM constraints 里有 `ck_daily_training_load_status_band`，防状态枚举漂移。
- fixture 方向：在 `tests/conftest.py` 跟 `BreakthroughEvent.__table__.create/drop` 同层加 `DailyTrainingLoad.__table__.create/drop`（`tests/conftest.py:283-299`）。

## 5. 5 字段 issue 草稿

背景：Sprint 10 要让用户看到 CTL/ATL/TSB 曲线；task-1 是地基，给 task-3 回填、task-4 endpoint、task-6 hook 提供同一张 `daily_training_load` 表（`docs/prd/sprint-10-prd.md:27-32`, `docs/prd/sprint-10-prd.md:133-160`）。

目标：建 `app/training/models.py` + `daily_training_load` 迁移 + ORM/迁移测试；不写算法、不写 service/router、不跑回填。

验收命令 shell：
```bash
python3 -m alembic heads
python3 -m pytest tests/test_daily_training_load_model.py
python3 -m alembic upgrade head
python3 -m alembic downgrade -1
python3 -m alembic upgrade head
```

不要碰：`activities` 表、`users` 表、`app/main.py`、`app/training/service.py`、`app/training/router.py`、`scripts/backfill_daily_training_load.py`；这些边界来自 PRD task-1 不做项和 task-4/6 分工（`docs/prd/sprint-10-prd.md:181-185`, `docs/prd/sprint-10-prd.md:333-340`, `docs/prd/sprint-10-prd.md:542-557`）。

失败处理：若 Alembic head 不等于 `sprint10_user_hr_profile`，停止并报告；若 SQLite fixture 卡住，先只做 ORM declaration 测试，再让集成审决定是否改真 PG 测试。

## 6. commit message 模板

commit message：`feat(training): sprint10 task-1 daily training load schema`

正文模板：`Add DailyTrainingLoad ORM, sprint10_daily_training_load migration, and schema contract tests. Down revision: sprint10_user_hr_profile. No service/router/backfill in this task.`

## 7. 部署 SOP

本 task 有迁移，部署必须 4 步走；生产 compose 初始化说明也要求 `alembic upgrade head`（`docker-compose.yml:10-15`）。`api/worker/cleanup/monitor/scheduler/curation-pool-cron` 都是 `build: .`，最稳直接全量 build（`docker-compose.yml:40-43`, `docker-compose.yml:65-69`, `docker-compose.yml:90-94`, `docker-compose.yml:128-140`, `docker-compose.yml:158-165`, `docker-compose.yml:176-181`）。

```bash
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull origin main"
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m alembic upgrade head"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T db psql -U velo -d velo -c 'SELECT COUNT(*) FROM daily_training_load;'"
```

期望：第 4 步返回 0 行或空表计数；PRD 明确 task-3 回填前生产表应为空（`docs/prd/sprint-10-prd.md:176-179`）。

## 8. 下游接口约定

- task-2：只产出 `ctl/atl/tsb/status_band` 值，不 import ORM；写入精度必须匹配 task-1 字段合同（`docs/prd/sprint-10-prd.md:201-223`）。
- task-3：`from app.training.models import DailyTrainingLoad`，按 `UNIQUE(user_id, date)` upsert，写 `weekly_tss` 前先 `round(SUM(float))`（`docs/prd/sprint-10-prd.md:265-285`）。
- task-4：查 `DailyTrainingLoad`，按 `user_id + date range` 走 `idx_dtl_user_date`，返回 30/90/365 天曲线和 summary（`docs/prd/sprint-10-prd.md:323-340`, `docs/prd/sprint-10-prd.md:383-396`）。
- task-6：单条活动 hook 更新当天行；helper 不 `commit()`，由 caller 统一提交；Strava tier2 不逐条 hook，完工后调 task-3 helper（`docs/prd/sprint-10-prd.md:515-548`, `docs/prd/sprint-10-prd.md:607`）。
- Sprint 12：coach engine 读 `CTL/ATL/TSB/weekly_tss`，并复用 `app.training.training_load`，不重复实现公式（`docs/prd/sprint-10-prd.md:14`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:205`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:233-239`）。

---

# Sprint 10 Task-2 Codex Handoff
> 范围：只给执行 spec subagent 的工程手册；只新增纯函数算法层和对应单测，不查 DB、不写 service/router/backfill/worker。依据：上次 commit `f37f976` 只把 task-1 plan 写进本文；本段继续追加 task-2，不改 PRD / 不写代码。

## 1. 起手必跑

执行者先像校准功率计一样把公式、边界和本仓库纯函数风格复测一遍；PRD 已把 task-2 定成 `app/training/training_load.py` 纯函数模块（`docs/prd/sprint-10-prd.md:191-207`），公式来自 Sprint 10 PRD + coach-engine 同步稿（`docs/prd/sprint-10-prd.md:208-218`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:149-157`）。

```bash
nl -ba docs/prd/sprint-10-prd.md | sed -n '191,249p;595,603p;646,656p'
nl -ba docs/superpowers/specs/2026-05-20-coach-engine-design.md | sed -n '145,207p'
nl -ba app/activity/power_zones.py | sed -n '1,180p'
nl -ba app/activity/ftp_estimator.py | sed -n '1,140p'
rg --files tests | rg "power|ftp|training|load|activity.py"
test -f tests/test_power_zones.py && nl -ba tests/test_power_zones.py | sed -n '1,140p' || nl -ba tests/test_activity.py | sed -n '34,61p'
nl -ba tests/test_power_curve.py | sed -n '1,120p'
nl -ba tests/test_ftp_estimator.py | sed -n '69,140p'
```

现有参照点：`power_zones.py` 是纯计算、不碰 DB 的模块说明（`app/activity/power_zones.py:1-18`），`calculate_power_curve` 明确把 `power=0` 当合法值（`app/activity/power_zones.py:150-180`, `app/activity/power_zones.py:165-166`），FTP 估算器用 dataclass + 手算 fixture 验证数学输出（`app/activity/ftp_estimator.py:78-120`, `tests/test_ftp_estimator.py:69-106`），功率区间 fixture 目前在 `tests/test_activity.py` 而不是独立 `tests/test_power_zones.py`（`tests/test_activity.py:36-61`）。

## 2. 文件改动清单

新增 `app/training/training_load.py`，约 90-140 行：模块 docstring + 5 个纯函数 + 私有常量 / helper；新增 `tests/test_training_load.py`，约 120-180 行：纯单测、无 DB fixture；不动 `requirements.txt`、不动 `app/activity/*`、不动 `app/training/models.py/service.py/router.py`、不动 `scripts/backfill_daily_training_load.py`。边界来自 PRD：task-2 只写算法，task-3 才回填，task-4 才查表和 label 转换，task-6 才挂 worker hook（`docs/prd/sprint-10-prd.md:191-199`, `docs/prd/sprint-10-prd.md:265-288`, `docs/prd/sprint-10-prd.md:336-365`, `docs/prd/sprint-10-prd.md:515-548`）。

## 3. 函数签名 + 算法决策

5 个对外签名锁死，后续下游禁止改名；类型标注按 PRD 写 `float`，但运行时必须把 `None` 视为 0.0，因为 PRD 明确首日/无活动要容忍 None（`docs/prd/sprint-10-prd.md:230-238`）。

```python
def calculate_daily_ctl(last_ctl: float, tss_today: float) -> float: ...
def calculate_daily_atl(last_atl: float, tss_today: float) -> float: ...
def calculate_tsb(ctl: float, atl: float) -> float: ...
def classify_tsb_status(tsb: float) -> str: ...
def format_status_label(band: str) -> str: ...
```

CTL 用 `last_ctl * exp(-1 / 42) + tss_today * (1 - exp(-1 / 42))`，ATL 同式但 tau=7，TSB=`ctl - atl`（`docs/prd/sprint-10-prd.md:208-213`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:149-157`）。纯函数返 raw float，不在函数内 round；写表/接口调用方按字段合同 round 1 位，避免 backfill 365 天递推时双重 round 积累误差（`docs/prd/sprint-10-prd.md:230-233`, `docs/prd/sprint-10-prd.md:638-639`）。阈值边界按 PRD 闭区间落低档：`+10.0 -> ok`、`+10.1 -> fresh`、`-10.0 -> ok`、`-10.1 -> tired`、`-20.0 -> tired`、`-20.1 -> overreached`（`docs/prd/sprint-10-prd.md:214-218`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:172-181`）。`format_status_label` 只返短中文：fresh=`状态饱满` / ok=`状态 OK` / tired=`累` / overreached=`过累`（`docs/prd/sprint-10-prd.md:207`, `docs/prd/sprint-10-prd.md:245-249`）。

## 4. 单测列表

新增 9 个 pytest case：1) `calculate_daily_ctl(50, 80)` 约等于 50.71（PRD 手算实证，`docs/prd/sprint-10-prd.md:219-221`）；2) ATL 同公式用 tau=7 验证自然衰减；3) `last_ctl=0/tss_today=0` 返 0；4) `calculate_tsb(65.3, 78.1)` 返 raw float、不 round；5) 6 个 TSB 边界逐项断言（`+10.0/+10.1/-10.0/-10.1/-20.0/-20.1`）；6) `last_ctl=None` / `last_atl=None` 视为 0.0；7) `tss_today=None` 视为 0.0；8) 负 tss 抛 `ValueError`；9) 4 档中文 label + 模块独立 import。测试文件风格对齐现有纯函数测试：不碰 DB / 文件系统，用直接构造输入断言输出（`tests/test_power_curve.py:1-6`, `tests/test_power_curve.py:27-86`）。

```bash
python3 -m pytest tests/test_training_load.py
python3 -c "import app.training.training_load"
python3 -c "from app.training.training_load import calculate_daily_ctl; print(round(calculate_daily_ctl(50, 80), 2))"
```

## 5. 5 字段 issue 草稿

背景：Sprint 10 task-2 是训练负荷地基算法层，给 task-3 历史回填、task-4 endpoint、task-6 worker hook 和 Sprint 12 coach-engine 共用；PRD 和 coach-engine 都要求公式只在 `app.training.training_load` 实现一次（`docs/prd/sprint-10-prd.md:28`, `docs/prd/sprint-10-prd.md:288`, `docs/superpowers/specs/2026-05-20-coach-engine-design.md:205`）。目标：新增 `app/training/training_load.py` + `tests/test_training_load.py`，实现 5 个签名、None/负数边界、4 档阈值和中文 label。验收命令 shell：`python3 -m pytest tests/test_training_load.py && python3 -c "import app.training.training_load"`。不要碰：PRD、requirements、DB、service/router/backfill/worker、`app/activity/*`。失败处理：若发现 PRD §2.3 的 round 口径和本 handoff 的 raw float 冲突无法过审，停下让 Tim/Claude 拍板，不在代码里临场改接口。

## 6. commit message 模板

commit message：`feat(training): sprint10 task-2 training load formulas`

正文模板：`Add pure CTL/ATL/TSB/status helpers and unit tests for Sprint 10 task-2. Keep outputs raw floats; callers round at write/API boundaries. No DB, service, router, backfill, or worker changes.`

## 7. 部署 SOP

task-2 不动 endpoint / worker / schema，但新模块会被 task-3/4/6 和 Sprint 12 import；部署仍按完整 4 步走，像换了一块公共工具板，先 build 新镜像再让后续任务使用。`docker compose up -d --build` 不指定 service 是安全默认，task-1 handoff 已用同样全量 build + alembic 验证节奏（`docs/plans/sprint-10-handoff.md:81-90`）。

```bash
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull origin main"
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -c 'import app.training.training_load; print(\"training_load import ok\")'"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m pytest tests/test_training_load.py"
```

容器 rebuild 评估：本 task 只加 Python 源码；`api` / `worker` / `cleanup` / `monitor` / `scheduler` / `curation-pool-cron` 都是 `build: .`，全量 build 会让这些同镜像服务拿到新模块（`docker-compose.yml:40-43`, `docker-compose.yml:65-69`, `docker-compose.yml:90-94`, `docker-compose.yml:128-145`, `docker-compose.yml:158-165`, `docker-compose.yml:176-181`）。没有 Alembic 迁移，不需要 `alembic upgrade head`，但若同批部署夹带 task-1 或其他 sprint 迁移，仍按生产 SOP 跑 upgrade（`docs/prd/sprint-10-prd.md:601-607`）。

## 8. 下游接口约定

task-3 backfill 只调 `calculate_daily_ctl` / `calculate_daily_atl` / `calculate_tsb` / `classify_tsb_status`，然后自己 upsert + round 写表（`docs/prd/sprint-10-prd.md:276-288`）。task-4 `app/training/service.py` 查表后调 `format_status_label(status_band)` 填 `summary.current_status_label`，不让前端硬编码（`docs/prd/sprint-10-prd.md:336-365`, `docs/prd/sprint-10-prd.md:391-397`）。task-6 hook helper 同样只调前 4 个算法函数，`format_status_label` 不进写表链路（`docs/prd/sprint-10-prd.md:542-548`）。Sprint 12 coach-engine `service.py` 必须 import 5 个全部，禁止在 `app/agent/coach/` 复制公式（`docs/superpowers/specs/2026-05-20-coach-engine-design.md:191-205`）。
