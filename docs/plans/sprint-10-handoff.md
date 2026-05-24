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
