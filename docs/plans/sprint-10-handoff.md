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

---

# Sprint 10 Task-3 Codex Handoff
> 范围：只给执行 spec subagent 的工程手册；新增历史回填脚本和脚本测试，不写 endpoint / worker / 小程序页面。依据：上次 commit `d28e327` 已由 `git log --oneline -1` 验证为 task-2 plan ship。

## 1. 用户故事 + 起手必跑

张三已经骑了一年，Sprint 10 上线当天点进训练日历，不应该只看到今天一条空线；脚本要像搬家前把旧账本录进新系统，把历史活动按北京时间一天一天算成训练负荷。

```bash
git log --oneline -1
rg -n "class DailyTrainingLoad|__tablename__|UniqueConstraint|idx_dtl_user_date" app/training/models.py docs/plans/sprint-10-handoff.md
rg -n "def calculate_daily_ctl|def calculate_daily_atl|def calculate_tsb|def classify_tsb_status|def format_status_label" app/training/training_load.py docs/plans/sprint-10-handoff.md
nl -ba scripts/backfill_max_cadence_and_power_zones.py | sed -n '31,205p'
nl -ba docs/prd/sprint-10-prd.md | sed -n '255,319p'
```

先实证 task-1 ORM 和 task-2 五函数都已落地；当前 handoff 里 task-1 字段合同在 `docs/plans/sprint-10-handoff.md:32-43`，task-2 五函数签名在 `docs/plans/sprint-10-handoff.md:132-137`，PRD 把 task-3 helper 写死为 `backfill_daily_training_load_for_user(db, user_id) -> int`（`docs/prd/sprint-10-prd.md:265-288`）。

## 2. 文件改动清单

- new `scripts/backfill_daily_training_load.py`：仿 `scripts/backfill_max_cadence_and_power_zones.py` 的 argparse / logging / SessionLocal 结构（`scripts/backfill_max_cadence_and_power_zones.py:33-47`, `scripts/backfill_max_cadence_and_power_zones.py:138-209`）。⚠ **旗标逻辑与模板相反**：模板默认写 DB / `--dry-run` 才安全；本脚本默认 dry-run / `--apply` 才写 DB（PRD §3.3 line 273）。**不要照抄模板的 `--dry-run` 旗标** / 用 `--apply` 模式防"默认跑就写 DB"安全事故。
- new `tests/test_backfill_daily_training_load.py`：用测试 DB 造用户 + completed cycling 活动，证明 dry-run 不写、apply 写入、复跑更新不重复。
- keep `app/training/training_load.py` unchanged：只 import task-2 五函数，不复制公式（`docs/plans/sprint-10-handoff.md:132-140`）。
- keep `app/training/models.py` unchanged：只 import task-1 ORM，不在脚本里重新声明字段名（`docs/plans/sprint-10-handoff.md:32-43`）。
- keep worker / router / miniprogram unchanged：这些分别是 task-4/5/6 范围（`docs/prd/sprint-10-prd.md:323-340`, `docs/prd/sprint-10-prd.md:409-456`, `docs/prd/sprint-10-prd.md:500-520`）。

## 3. 核心决策

脚本默认 dry-run，只有显式 `--apply` 才写 DB；支持 `--user-id X` 和 `--all-users`，不让“少打一个参数”变成生产写入。helper 只做一个用户的正序计算 + flush/upsert，返回写入行数；`main()` 负责 commit / rollback / sleep，task-6 的 scheduler 调用方也能决定外层事务。upsert 命中已有行时必须显式刷新 `updated_at=func.now()`，因为复跑回填和 task-6 增量更新都靠它证明“今天这页账本刚被重算过”。北京时间在脚本里独立声明 `_BJ_TZ = timezone(timedelta(hours=8))`，不跨模块 import 私有变量（`docs/prd/sprint-10-prd.md:595-599`）。活动起点从最早 completed cycling + `started_at is not None` 开始；每日 TSS 求和只吃 `tss is not None`，所以全是 GPX 无 TSS 的用户也会写出从首日到今天的 0 曲线，符合 PRD §3.7。**算法每日步骤明确调 task-2 五函数 / 不自己算公式**：`calculate_daily_ctl(last_ctl, tss_today)` + `calculate_daily_atl(last_atl, tss_today)` + `calculate_tsb(ctl, atl)` + `classify_tsb_status(tsb)`（共享逻辑红线 / 详 `docs/plans/sprint-10-handoff.md:132-137`）。节流 sleep 0.5s 来源 PRD §7.2 性能约束（10 用户 < 10 分钟 / 0.5s × 10 = 5 秒额外开销可接受）。

## 4. 单测列表

新增 7 个 pytest case：dry-run 返回 preview 且 DB count 不变；apply 单用户写入多日；复跑同一用户行数不增长（**PRD §3.8 验收 ③**）；无 completed cycling 活动返回 0；某日多个活动合并 tss；**首日 last_ctl=None 起步时第一天 ctl 接近 `tss_today * (1 - exp(-1/42))`**（不测函数被调次数 / 测 observable output / PRD §3.8 数学验收）；**`--all-users` 路径写入 2 fixture 用户都有 daily_training_load 行**（PRD §3.8 验收 ④）。验收命令：

```bash
python3 -m pytest tests/test_backfill_daily_training_load.py
python3 -m scripts.backfill_daily_training_load --user-id 2
python3 -m scripts.backfill_daily_training_load --apply --user-id 2
python3 -m scripts.backfill_daily_training_load --apply --all-users
```

## 5. 5 字段 issue 草稿

背景：Sprint 10 要让老用户上线第一天就看到 90 天 / 全年曲线，PRD 要 task-3 写一次性回填脚本，并把 helper 留给 task-6 scheduler 完工后复用（`docs/prd/sprint-10-prd.md:255-288`）。目标：新增 `scripts/backfill_daily_training_load.py` + `tests/test_backfill_daily_training_load.py`，默认 dry-run，`--apply` 才写表，helper 返回写入行数。验收命令 shell：`python3 -m pytest tests/test_backfill_daily_training_load.py && python3 -m scripts.backfill_daily_training_load --user-id 2`。不要碰：router/service/worker/miniprogram/PRD；不要改 task-1 ORM 字段和 task-2 函数签名。失败处理：若 task-1/2 实现文件不存在或签名不匹配，停下报 Tim；若单 task 卡 >30 min，段末标 `⚠ task-3 部分跑`。

## 6. commit message 模板

commit message：`feat(training): sprint10 task-3 daily load backfill`

正文模板：`Add dry-run/apply backfill script for daily_training_load, with reusable per-user helper and tests. Reuse task-2 training load helpers and task-1 ORM; no endpoint, worker, or miniprogram changes.`

## 7. 部署 SOP

部署像把旧账本导入新库：先确认表已迁移，再 dry-run 看数字，再 apply。生产命令：

```bash
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull origin main"
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m alembic upgrade head"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m scripts.backfill_daily_training_load --user-id 2"
# ⚠ dry-run 验收门：肉眼确认 CTL 范围合理（≥ 30 / ≤ 90 / PRD §3.8 验收 ①）+ 跨度天数 ≈ 295 条历史 / 14 个月 / 否则 STOP 报 Tim
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m scripts.backfill_daily_training_load --apply --user-id 2"
```

## 8. 下游接口约定

task-4 只读 `daily_training_load`，不现场补算历史；task-6 import_scheduler 完工只调 `backfill_daily_training_load_for_user(db, user_id)` 做全量正序递推，不挂倒序单条 hook（`docs/prd/sprint-10-prd.md:508-520`, `docs/prd/sprint-10-prd.md:607`）。Sprint 12 仍读同一张表和 task-2 五函数，不在 coach-engine 复制算法。

---

# Sprint 10 Task-4 Codex Handoff
> 范围：只给执行 spec subagent 的工程手册；新增训练负荷后端查询接口和测试，不改回填脚本 / worker / 小程序页面。

## 1. 用户故事 + 起手必跑

张三点开训练日历页，前端只发一次请求，就拿到 30 天曲线点和顶部状态卡；后端像服务台，把表里的每日记录整理成前端能直接画的清单。

```bash
git log --oneline -1
rg -n "class DailyTrainingLoad|idx_dtl_user_date|status_band" app/training/models.py docs/plans/sprint-10-handoff.md
rg -n "def format_status_label|def calculate_daily_ctl|def calculate_daily_atl|def calculate_tsb|def classify_tsb_status" app/training/training_load.py docs/plans/sprint-10-handoff.md
nl -ba app/main.py | sed -n '1,65p'
nl -ba docs/prd/sprint-10-prd.md | sed -n '323,405p'
```

接口必须挂进 `app/main.py`，否则用户点页面永远 404；现有路由都靠 import router + `app.include_router(...)` 进入大门（`app/main.py:14-22`, `app/main.py:41-54`）。鉴权模式对齐 `GET /api/user/stats`（`app/user/router.py:141-153`）。

## 2. 文件改动清单

- new `app/training/router.py`：`APIRouter(prefix="/api/training", tags=["training"])`，提供 `GET /load`。
- new `app/training/schemas.py`：响应 schema。**summary 必含字段**：`current_ctl/current_atl/current_tsb/tss_today` round 1 位（float）/ `weekly_tss` int / `current_status_band: str`（4 枚举不 round）/ `current_status_label: str`（中文不 round）/ **`data_complete: bool`（必填 / 不可 Optional）**；Pydantic v2 validator 风格可参考 `app/admin/schemas.py:6` 和 `app/admin/schemas.py:144-170`。
- new `app/training/service.py`：查 `DailyTrainingLoad`，补缺日，调用 `format_status_label()` 填 summary 中文标签。
- modify `app/main.py`：加 `from app.training.router import router as training_router` + `app.include_router(training_router)`（`app/main.py:41-54`）。
- new `tests/test_training_load_api.py`：覆盖 30d / 90d / 1y / 无数据 / 非法 range / status_label 中文。

## 3. 核心决策

本 task 不重新定义字段名，读写都以 task-1 ORM 为准；schema 只负责把返回给小程序的数字修成 1 位，service 负责查表和补缺日。`summary.current_status_label` 必须由 service 调 `format_status_label(summary.current_status_band)` 填，不放 schema 自动算、不让前端硬编码（`docs/prd/sprint-10-prd.md:364-365`, `docs/plans/sprint-10-handoff.md:177`）。**3 种数据状态分支**（PRD §4.3 + §4.7 完整边界）：① 完全无记录 → `points=[]` + 全 0 summary + `data_complete=false`；② **有记录但总天数 < 14 → 返实际 points（不补 0 到 window 长度）+ `data_complete=false`**（前端文案"再骑 N 天能看完整曲线"/ PRD §4.7 line 387）；③ ≥ 14 天 → 窗口内缺日补 0 点（tss_today=0 代入 `calculate_daily_ctl/atl` 走自然衰减递推 / 不是直接 ctl=0）+ `data_complete=true`。

## 4. 单测列表

新增 7 个 pytest case：30d 返回 30 个点；90d / 1y range 分别返回目标长度；无记录用户返回空 points + `data_complete=false`；非法 range 422；schema round 1 位；`current_status_label` 是中文；**mock 13 天历史 → 返 13 个点 + `data_complete=false`**（PRD §4.7 line 387 < 14 天分支必测）。验收命令：

```bash
python3 -m pytest tests/test_training_load_api.py
python3 -c "from app.main import app; print(any('/api/training/load' in getattr(r, 'path', '') for r in app.routes))"
python3 -c "from app.training.training_load import format_status_label; print(format_status_label('tired'))"
```

## 5. 5 字段 issue 草稿

背景：task-5 训练日历页需要一次请求拿曲线和顶部状态卡；PRD 要 `app/training/{router,service,schemas}.py` + `app/main.py` 注册路由（`docs/prd/sprint-10-prd.md:323-341`）。目标：实现 `GET /api/training/load?range=30d|90d|1y`，只返当前登录用户数据，数字 1 位小数，summary 带中文状态。验收命令 shell：`python3 -m pytest tests/test_training_load_api.py && python3 -c "from app.main import app; print(app)"`。不要碰：backfill/worker/miniprogram/PRD；不要改 task-2 五函数。失败处理：若 task-1 ORM 或 task-2 `format_status_label` 缺失，停下报 Tim；若单 task 卡 >30 min，段末标 `⚠ task-4 部分跑`。

## 6. commit message 模板

commit message：`feat(training): sprint10 task-4 load endpoint`

正文模板：`Add /api/training/load router, schemas, service, and app registration. Round API floats to one decimal and fill current_status_label through task-2 format_status_label.`

## 7. 部署 SOP

本 task 新增 API，大门和服务进程都要更新。生产命令：

```bash
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull origin main"
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m pytest tests/test_training_load_api.py"
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -c 'from app.main import app; print([r.path for r in app.routes if r.path.startswith(\"/api/training\")])'"
```

## 8. 下游接口约定

task-5 只调 `GET /api/training/load?range=30d|90d|1y`，不自己拼多接口；task-6 只写表，不改 response schema。Sprint 12 coach-engine 读原始 `status_band`，小程序展示才用 `current_status_label`（`docs/prd/sprint-10-prd.md:365`）。

---

# Sprint 10 Task-5 Codex Handoff
> 范围：只给执行 spec subagent 的工程手册；新增小程序训练日历页 + 我的页入口，不改后端接口 / worker / 回填脚本。

## 1. 用户故事 + 起手必跑

张三周末打开“我的”，看到“训练分析”，点进去马上看见状态卡和三条曲线；入口永远在，不因为他这周休息就消失，让严肃老用户不用猜产品把功能藏哪了。

```bash
git log --oneline -1
nl -ba miniprogram/app.json | sed -n '1,20p'
nl -ba miniprogram/pages/profile/profile.wxml | sed -n '104,122p'
nl -ba miniprogram/pages/profile/profile.js | sed -n '147,156p;347,354p'
rg -n "canvas|type=\"2d\"|setTimeout\\(function \\(\\)|createSelectorQuery|hidden=\\\"" miniprogram/pages miniprogram/components
```

PRD 已拍训练页四文件 + app.json 末尾注册（`docs/prd/sprint-10-prd.md:421-441`），入口常显是为了避开 `period=week` 误藏：profile 当前确实只取本周统计（`miniprogram/pages/profile/profile.js:147-156`），而入口位置可贴在“我的荣誉”下方（`miniprogram/pages/profile/profile.wxml:112-118`）。

## 2. 文件改动清单

- new `miniprogram/pages/training-calendar/training-calendar.wxml`：状态卡、时间窗 tab、canvas、空数据态。
- new `miniprogram/pages/training-calendar/training-calendar.wxss`：4 档状态卡背景色 + canvas 稳定高度。
- new `miniprogram/pages/training-calendar/training-calendar.js`：调 task-4 接口、切 30d/90d/1y、`setTimeout(fn, 100)` 后画 canvas。
- new `miniprogram/pages/training-calendar/training-calendar.json`：页面标题。
- modify `miniprogram/pages/profile/profile.wxml` + `.js`：加常显入口和 `onTapTrainingAnalysis()`。
- modify `miniprogram/app.json`：把 `pages/training-calendar/training-calendar` 加到 pages 末尾，不能插第一项（`miniprogram/app.json:2-15`）。

## 3. 核心决策

canvas 节点用 `<canvas type="2d" id="pmc-chart">`，渲染前用 `setData(..., callback)` 再 `setTimeout(fn, 100)`，对齐现有功率曲线的低端机兜底（`miniprogram/components/power-curve-card/power-curve-card.js:201-205`, `miniprogram/components/power-curve-card/power-curve-card.js:234-252`）。三条线只画 task-4 返回的 `points`，状态卡只吃 `summary`；完全空数据不画假曲线。入口复用 `profile-action-card` 样式，不新增一套卡片体系（`miniprogram/pages/profile/profile.wxss:519-550`）。

## 4. 单测 / 真机验收列表

小程序本仓没有自动 UI 测试，本 task 用 grep + 真机验收。至少覆盖：app.json 页面不是第一项；入口常显且 navigateTo 地址正确；30d/90d/1y 请求路径正确；canvas 有 100ms 兜底；空数据态不画曲线。可跑命令：

```bash
python3 -m json.tool miniprogram/app.json >/tmp/velo-app-json-check.txt
rg -n "pages/training-calendar/training-calendar|onTapTrainingAnalysis|/api/training/load|pmc-chart|setTimeout" miniprogram
rg -n 'wx:if=|hidden=' miniprogram/pages/training-calendar/training-calendar.wxml   # 验证空数据态 wxml 控制（单引号包裹避免 shell 引号歧义）
rg -n '状态饱满|状态 OK|建议中低|强烈建议休息' miniprogram/pages/training-calendar/training-calendar.js   # 验证 4 档文案硬编码（PRD §5.3 line 431-434）
```

## 5. 5 字段 issue 草稿

背景：Sprint 10 的用户可见价值在训练日历页；PRD 要训练页四文件、我的页入口常显、app.json 追加到末尾、canvas 三曲线和顶部状态卡（`docs/prd/sprint-10-prd.md:409-456`）。目标：用户从“我的”进入训练分析，看到 30/90/全年训练负荷曲线；无数据用户看到空态，不看假曲线。验收命令 shell：`python3 -m json.tool miniprogram/app.json && rg -n "pages/training-calendar/training-calendar|onTapTrainingAnalysis|pmc-chart" miniprogram`。不要碰：后端 task-4 接口、worker、回填脚本；不要用 user_stats 判断是否显示入口。失败处理：若小程序开发者工具 canvas 初次渲染不稳定，先保留 setTimeout 100ms 兜底并报 Tim；若单 task 卡 >30 min，段末标 `⚠ task-5 部分跑`。

## 6. commit message 模板

commit message：`feat(miniprogram): sprint10 task-5 training calendar`

正文模板：`Add training calendar page, permanent profile entry, app.json registration, and canvas rendering for CTL/ATL/TSB. Keep entry always visible and let page empty state handle no-data users.`

## 7. 部署 SOP

本 task 是小程序前端，先本地开发者工具真机看，再发版；后端必须先有 task-4 接口。检查命令：

```bash
python3 -m json.tool miniprogram/app.json >/tmp/velo-app-json-check.txt
rg -n "pages/training-calendar/training-calendar" miniprogram/app.json
rg -n "GET /api/training/load|/api/training/load|range" miniprogram/pages/training-calendar miniprogram/utils/api.js
```

真机回归按 PRD：你账号 30d 三线出来，90d / 1y 可切；无活动测试号入口仍显示，进去只看空态（`docs/prd/sprint-10-prd.md:479-485`）。

## 8. 下游接口约定

task-5 不重新解释训练负荷，只展示 task-4 response；顶部卡背景按 `summary.current_status_band` 四档，文案可前端短句硬编码，但 `current_status_label` 用后端给的中文。Sprint 12 如果要主动推教练总结，另走动态 tab 大卡，不挤本页入口（`docs/prd/sprint-10-prd.md:486-494`）。

---

# Sprint 10 Task-6 Codex Handoff
> 范围：只给执行 spec subagent 的工程手册；新增增量写表 helper 和 2 条单活动 hook，Strava 历史批量导入只在 tier2 完工后调 task-3 helper。

## 1. 用户故事 + 起手必跑

张三今天上传一条 GPX 或 Strava 同步一条新骑行，活动处理完成时，当天训练负荷也顺手更新；他下次打开训练日历，今天的点已经在图上，不用等人手动跑回填。

```bash
git log --oneline -1
nl -ba app/activity/worker.py | sed -n '260,371p'
nl -ba app/strava/worker_strava.py | sed -n '230,370p'
nl -ba app/strava/import_scheduler.py | sed -n '423,448p;590,607p'
rg -n "backfill_daily_training_load_for_user|update_daily_load_for_activity|def calculate_daily_ctl|class DailyTrainingLoad" app scripts docs/plans/sprint-10-handoff.md
```

hook 位置必须在 caller `db.commit()` 前；GPX worker 现有 5 个 hook 都在 `activity.status='completed'` 后、`db.commit()` 前（`app/activity/worker.py:260-371`），Strava webhook worker 也是 `_strava_post_parse_hooks()` 后再 commit（`app/strava/worker_strava.py:262-266`）。import_scheduler tier2 当前是最新优先（`app/strava/import_scheduler.py:432-441`），所以不能逐条触发 CTL/ATL 正序递推。

## 2. 文件改动清单

- modify `app/training/service.py`：新增 `update_daily_load_for_activity(db, user, activity)`，内部独立声明 `_BJ_TZ`。
- modify `app/activity/worker.py`：breakthrough hook 后、`db.commit()` 前加步骤 10.9，SAVEPOINT 包住 daily load helper。
- modify `app/strava/worker_strava.py`：在 `_strava_post_parse_hooks()` 末尾加第 6 个 hook block，不在 caller 层另挂。
- modify `app/strava/import_scheduler.py`：`activity is None` 完工分支（line 444-448 / 实证 `import_task.status = "completed"` → `logger.info` → `return`）。**backfill 必须插在现有 `return` 语句之前** / `import_task.status = "completed"` 设置之后 + `db.commit()` 之后 / try/except 兜底调 `backfill_daily_training_load_for_user(db, import_task.user_id)`。⚠ **不要加在 return 之后** / early-return 分支死代码永远跑不到。
- modify / add tests：`tests/test_training_daily_load_hook.py`，必要时补 `tests/test_strava_import_scheduler.py`。
- keep `app/strava/import_scheduler.py` single-activity path free of daily-load hook；只做完工 backfill（`docs/prd/sprint-10-prd.md:508-520`）。

## 3. 核心决策

单活动 helper 只调 task-2 前 4 个函数，不调 `format_status_label()`；展示中文是 task-4 的事（`docs/plans/sprint-10-handoff.md:177`）。helper 不 `commit()`，hook block 也不 `commit()`，只 `db.flush()`；caller 现有提交统一把 activity.status 和 daily_training_load 一起落库。upsert 命中当天已有行时必须显式刷新 `updated_at=func.now()`，覆盖“GPX 无 TSS 但今日账本被重算”的验收场景。SAVEPOINT 模式照抄 breakthrough 双层 try/except，失败只 `nested.rollback()`，不碰外层事务（`app/activity/worker.py:345-371`）。Strava tier2 完工调 task-3 helper 全量正序递推；backfill 失败只 log，不影响 import_task completed 状态（`docs/prd/sprint-10-prd.md:550-559`）。

## 4. 单测列表

新增 8 个 pytest case：GPX hook 成功写当天行；Strava webhook hook 成功写当天行；activity.tss 为 None 时只用同日其他活动求和；**activity.started_at 为 NULL（脏数据）→ helper 跳过 + log warn / 不影响主流程**（PRD §6.7 漏覆盖补）；已有当天行走更新；最近历史记录不限 7 天；helper 异常时 SAVEPOINT 不污染 activity commit；import_scheduler 完工调用 backfill helper 且不逐条 hook。验收命令：

```bash
python3 -m pytest tests/test_training_daily_load_hook.py
python3 -m pytest tests/test_strava_import_scheduler.py
python3 -c "from app.training.service import update_daily_load_for_activity; print(update_daily_load_for_activity)"
```

## 5. 5 字段 issue 草稿

背景：task-3 只解决历史，task-6 要让新活动自动更新当天训练负荷；PRD 已拍 2 个 caller 加单条 hook，Strava 历史批量导入完工后走 backfill helper（`docs/prd/sprint-10-prd.md:500-589`）。目标：实现 `update_daily_load_for_activity(db, user, activity)` + GPX/Strava webhook hook + import_scheduler 完工 backfill。验收命令 shell：`python3 -m pytest tests/test_training_daily_load_hook.py tests/test_strava_import_scheduler.py`。不要碰：小程序页面、task-4 response schema、task-3 dry-run CLI 行为；不要在 helper 或 hook 里加内层 `db.commit()`。失败处理：若 SAVEPOINT 测试出现事务污染，先停下收窄到 GPX worker 一条路径；若单 task 卡 >30 min，段末标 `⚠ task-6 部分跑`。

## 6. commit message 模板

commit message：`feat(training): sprint10 task-6 daily load hooks`

正文模板：`Add incremental daily_training_load update helper, GPX and Strava single-activity hooks, and tier2 completion backfill for Strava imports. Keep hooks inside caller transactions with SAVEPOINT isolation and no inner commit.`

## 7. 部署 SOP

本 task 同时影响 api / worker / scheduler，必须全量 build；scheduler 不 rebuild 就拿不到 import_scheduler 完工 backfill。生产命令：

```bash
# 本地先跑 pytest（生产容器跑 pytest 有 SQLite/PG dialect 问题 / 陷阱清单 #15）
python3 -m pytest tests/test_training_daily_load_hook.py tests/test_strava_import_scheduler.py
# 本地全过后才部署
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull origin main"
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"   # 不指定 service / 所有 build:. 服务共享 image
# 真用回归（PRD §7.4 回归 4 / 不只 COUNT(*) / 必须逐日 CTL/ATL/TSB 比对完整 backfill 结果）
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T db psql -U velo -d velo -c 'SELECT date, ctl, atl, tsb FROM daily_training_load WHERE user_id=2 ORDER BY date DESC LIMIT 30;'"
# 若 webhook 新活动触发 hook：30 秒后再跑一次上面 SQL / 确认当日 tss_today 反映新活动
```

## 8. 下游接口约定

task-5 用户看到的是 task-4 查询结果，task-6 只保证新活动把表更新好；不做删活动回退、不做 ftp 变更后重算、不做每天 0 点全用户 cron（`docs/prd/sprint-10-prd.md:584-587`）。Sprint 12 如果要用当天状态做教练总结，直接读 daily_training_load，不能再绕开 task-2 算法函数。
