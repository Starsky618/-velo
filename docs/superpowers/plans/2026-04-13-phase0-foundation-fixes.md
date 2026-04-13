# 第 0 期 地基修补 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 5 个红灯级工程漏洞 + 1 个黄灯级索引缺陷，为后续 Strava 集成和用户量增长打下可靠基础。

**Architecture:** 6 个修复严格串行执行，每个独立 commit。不引入新模块，只在现有代码上加固：改配置、加校验、加字段、改入口逻辑、新增独立脚本。

**Tech Stack:** Python 3.11 / SQLAlchemy 2.0 / PostgreSQL 16 / Redis Queue / Alembic / Docker Compose

**设计文档:** `docs/superpowers/specs/2026-04-13-phase0-foundation-fixes-design.md`

---

## Task 1: 数据库连接池配置

**Files:**
- Modify: `app/database.py:22`

- [ ] **Step 1: 修改连接池参数**

将 `app/database.py` 第 22 行的 `create_engine` 调用替换为：

```python
# 创建数据库引擎——相当于打通了程序到数据库的"管道"
# pool_pre_ping=True：每次从连接池借连接前先"敲一下门"，
# 确认连接还活着，避免用到已断开的死连接
# pool_size=8：常驻 8 个连接（注意：每个进程独立连接池，
#   2 个 uvicorn worker + 1 个 rq worker = 实际 24 个基础连接）
# max_overflow=12：峰值时临时扩展到 20 个/进程，用完归还
# pool_recycle=3600：每小时回收连接，防止数据库重启后出现死连接
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=8,
    max_overflow=12,
    pool_recycle=3600,
    pool_pre_ping=True,
)
```

- [ ] **Step 2: 启动 Docker 验证无报错**

Run: `docker compose -f docker-compose.dev.yml up -d && docker compose -f docker-compose.dev.yml logs api --tail 20`
Expected: API 正常启动，无连接错误

- [ ] **Step 3: Commit**

```bash
git add app/database.py
git commit -m "fix(database): 显式配置连接池参数 pool_size=8 max_overflow=12 pool_recycle=3600"
```

---

## Task 2: 轨迹点数量上限 — 上传层校验

**Files:**
- Modify: `app/activity/service.py:39-66`
- Test: `tests/test_activity.py`

- [ ] **Step 1: 在 service.py 中添加常量和校验**

在 `app/activity/service.py` 的 `_MAX_FILE_SIZE` 下方添加常量：

```python
# 轨迹点数量上限：50000 个点 ≈ 14 小时连续记录（1 秒/点）
# 超大轨迹解析时内存峰值可达 400MB+，4G 服务器上会触发 OOM
_MAX_TRACKPOINTS = 50_000
```

在 `validate_gpx_file()` 函数末尾（内容检查之后）添加第四道关卡：

```python
    # 关卡 4：轨迹点数量预检（轻量字节扫描，不解析 XML）
    # GPX 中每个轨迹点以 <trkpt 标签开头，数标签数 ≈ 数轨迹点数
    # 纯字节扫描 50MB 耗时毫秒级，不建 DOM 树，不吃额外内存
    trkpt_count = file_bytes.count(b"<trkpt")
    if trkpt_count > _MAX_TRACKPOINTS:
        raise ValueError(
            f"轨迹点过多（{trkpt_count} 个，上限 {_MAX_TRACKPOINTS} 个，约 14 小时骑行）"
        )
```

- [ ] **Step 2: 写测试 — 超限文件被拒绝**

在 `tests/test_activity.py` 中添加测试：

```python
def test_validate_gpx_rejects_too_many_trackpoints():
    """轨迹点超过 50000 个的 GPX 应被拒绝"""
    # 构造一个包含 50001 个 <trkpt 标签的假 GPX
    header = b'<?xml version="1.0"?><gpx><trk><trkseg>'
    point = b'<trkpt lat="0" lon="0"></trkpt>'
    body = point * 50001
    footer = b'</trkseg></trk></gpx>'
    big_gpx = header + body + footer

    with pytest.raises(ValueError, match="轨迹点过多"):
        service.validate_gpx_file("test.gpx", big_gpx)


def test_validate_gpx_accepts_normal_trackpoints():
    """正常数量的轨迹点应通过校验"""
    header = b'<?xml version="1.0"?><gpx><trk><trkseg>'
    point = b'<trkpt lat="0" lon="0"></trkpt>'
    body = point * 100
    footer = b'</trkseg></trk></gpx>'
    normal_gpx = header + body + footer

    # 不应抛异常
    service.validate_gpx_file("test.gpx", normal_gpx)
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_activity.py -v -k "trackpoints"`
Expected: 2 个测试 PASS

- [ ] **Step 4: Commit**

```bash
git add app/activity/service.py tests/test_activity.py
git commit -m "fix(activity): 上传时轨迹点数量预检，上限 50000 个点"
```

---

## Task 3: 轨迹点数量上限 — Worker 层安全网

**Files:**
- Modify: `app/activity/worker.py:88`

- [ ] **Step 1: 在 worker.py 中添加常量和解析后校验**

在 `app/activity/worker.py` 顶部（`_BATCH_SIZE = 500` 下方）添加：

```python
# 轨迹点数量硬上限（与 service.py 的 _MAX_TRACKPOINTS 一致）
# 这是格式无关的安全网——不管从 GPX/FIT/Strava 哪种来源解析出来，
# 超过此上限都拒绝。第一层（上传时）按格式做轻量预检，这里是第二层兜底。
_MAX_TRACKPOINTS = 50_000
```

在 `_do_parse()` 中，`result = parse_gpx(...)` 之后、统计量写入之前添加：

```python
    # ===== 步骤 5.5：轨迹点数量安全网 =====
    # 第二层防御：解析后检查实际点数。
    # 即使第一层（上传时的标签计数）漏掉了异常格式，这里也能拦住。
    trackpoints = result["trackpoints"]
    if len(trackpoints) > _MAX_TRACKPOINTS:
        raise GPXParseError(
            f"轨迹点过多（{len(trackpoints)} 个，上限 {_MAX_TRACKPOINTS}），请裁剪后重新上传"
        )
```

同时把原来第 119 行的 `trackpoints = result["trackpoints"]` 删除（已经提前赋值了）。

- [ ] **Step 2: 运行现有测试确保无回归**

Run: `pytest tests/test_activity.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add app/activity/worker.py
git commit -m "fix(worker): 解析后轨迹点数量安全网，上限 50000"
```

---

## Task 4: 重复上传防护 — 数据模型 + 迁移

**Files:**
- Modify: `app/activity/models.py:55-106`
- Create: `migrations/versions/xxxx_phase0_foundation_fixes.py`（由 Alembic autogenerate）
- Modify: `app/segment/models.py:115-122`

- [ ] **Step 1: Activity 模型新增 file_hash 字段**

在 `app/activity/models.py` 的 `file_url` 字段下方添加：

```python
    # 文件内容的 SHA-256 哈希值（64 位十六进制字符串）
    # 用于去重：同一用户上传完全相同的文件时，秒级拦截返回已有记录
    # nullable=True：历史记录没有哈希值，不影响 UNIQUE 约束（NULL != NULL）
    file_hash = Column(String(64), nullable=True)
```

在 `__table_args__` 中添加 UNIQUE 约束：

```python
    __table_args__ = (
        Index("idx_activities_user_status", "user_id", "status"),
        Index("idx_activities_user_started", "user_id", "started_at"),
        # 同一用户 + 同一文件哈希 = 重复上传，数据库层最后防线
        UniqueConstraint("user_id", "file_hash", name="uq_user_file_hash"),
    )
```

需要在文件顶部的 import 中添加 `UniqueConstraint`：

```python
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text,
    ForeignKey, Index, UniqueConstraint, func,
)
```

- [ ] **Step 2: SegmentEffort 模型补索引定义**

在 `app/segment/models.py` 的 `__table_args__` 中添加：

```python
    __table_args__ = (
        UniqueConstraint("segment_id", "activity_id", name="uq_segment_activity"),
        Index("idx_efforts_segment_time", "segment_id", "elapsed_time"),
        Index("idx_efforts_user", "user_id"),
        # PR 检测索引：查"用户在某赛段的最佳成绩"，三列支持 index-only scan
        Index("idx_efforts_segment_user_time", "segment_id", "user_id", "elapsed_time"),
    )
```

- [ ] **Step 3: 生成 Alembic 迁移脚本**

Run: `docker compose -f docker-compose.dev.yml exec api alembic revision --autogenerate -m "phase0 foundation fixes"`
Expected: 生成新迁移文件，包含 file_hash 列 + uq_user_file_hash 约束 + idx_efforts_segment_user_time 索引

- [ ] **Step 4: 检查生成的迁移脚本**

读取生成的迁移文件，确认 upgrade() 包含：
1. `op.add_column('activities', sa.Column('file_hash', sa.String(64), nullable=True))`
2. `op.create_unique_constraint('uq_user_file_hash', 'activities', ['user_id', 'file_hash'])`
3. `op.create_index('idx_efforts_segment_user_time', 'segment_efforts', ['segment_id', 'user_id', 'elapsed_time'])`

如有遗漏或多余操作，手动修正迁移文件。

- [ ] **Step 5: 执行迁移**

Run: `docker compose -f docker-compose.dev.yml exec api alembic upgrade head`
Expected: 迁移成功，无报错

- [ ] **Step 6: 验证数据库结构**

Run: `docker compose -f docker-compose.dev.yml exec db psql -U ridemap -c "\d activities" | grep file_hash`
Expected: 看到 `file_hash | character varying(64)` 列

Run: `docker compose -f docker-compose.dev.yml exec db psql -U ridemap -c "\di" | grep -E "uq_user_file|idx_efforts_segment_user"`
Expected: 看到两个新索引/约束

- [ ] **Step 7: Commit**

```bash
git add app/activity/models.py app/segment/models.py migrations/versions/
git commit -m "feat(models): Activity 增加 file_hash 去重字段 + SegmentEffort 补 PR 检测索引"
```

---

## Task 5: 重复上传防护 — 业务逻辑

**Files:**
- Modify: `app/activity/service.py:69-99`
- Test: `tests/test_activity.py`

- [ ] **Step 1: 修改 upload_gpx() 添加哈希去重**

在 `app/activity/service.py` 顶部添加 import：

```python
import hashlib
from sqlalchemy.exc import IntegrityError
```

修改 `upload_gpx()` 函数：

```python
def upload_gpx(db: Session, user_id: int, filename: str, file_bytes: bytes) -> Activity:
    """
    处理 GPX 文件上传的完整流程。

    步骤：
    1. 计算文件哈希 → 检查是否重复
    2. 存储文件 → 拿到 file_url
    3. 创建 Activity 记录（status=pending）
    4. 把解析任务扔进队列

    返回新建的 Activity 对象（前端用 activity_id 查进度）。
    如果是重复文件，直接返回已有记录，不重新创建。
    """
    # 第一步：计算文件 SHA-256 哈希（64 字符十六进制）
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    # 第二步：检查是否已有同文件（同用户 + 同哈希 = 重复上传）
    existing = db.query(Activity).filter_by(
        user_id=user_id, file_hash=file_hash
    ).first()
    if existing:
        return existing  # 秒返已有记录，不报错、不创建新记录

    # 第三步：存储文件
    try:
        file_url = _storage.upload(file_bytes, filename)
    except Exception:
        raise RuntimeError("文件上传失败")

    # 第四步：创建数据库记录
    activity = Activity(
        user_id=user_id,
        file_url=file_url,
        file_hash=file_hash,
        status="pending",
    )
    db.add(activity)

    # 并发兜底：如果两个请求同时通过了应用层检查，
    # UNIQUE(user_id, file_hash) 约束会让第二个 INSERT 失败。
    # 捕获 IntegrityError，返回已有记录。
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Activity).filter_by(
            user_id=user_id, file_hash=file_hash
        ).first()
        if existing:
            return existing
        raise  # 不是哈希冲突的 IntegrityError，重新抛出

    db.refresh(activity)

    # 第五步：入队列，让 Worker 异步解析
    _queue.enqueue(parse_activity, activity.id, job_timeout=120)

    return activity
```

- [ ] **Step 2: 写测试 — 重复上传返回已有记录**

在 `tests/test_activity.py` 中添加：

```python
def test_upload_duplicate_file_returns_existing(db_session, mock_storage):
    """上传相同文件两次，第二次应返回第一次的 Activity 而不是创建新记录"""
    from app.activity.service import upload_gpx, validate_gpx_file

    gpx_content = b'<?xml version="1.0"?><gpx><trk><trkseg><trkpt lat="0" lon="0"></trkpt></trkseg></trk></gpx>'

    # 第一次上传
    activity1 = upload_gpx(db_session, user_id=1, filename="ride.gpx", file_bytes=gpx_content)

    # 第二次上传同一文件
    activity2 = upload_gpx(db_session, user_id=1, filename="ride.gpx", file_bytes=gpx_content)

    assert activity1.id == activity2.id  # 应该是同一条记录
```

注意：此测试需要已有的 test fixtures（db_session, mock_storage）。如果现有 conftest.py 没有 mock_storage，需根据现有测试模式适配。

- [ ] **Step 3: 运行测试**

Run: `pytest tests/test_activity.py -v -k "duplicate"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/activity/service.py tests/test_activity.py
git commit -m "fix(activity): SHA-256 文件哈希去重 + UNIQUE 约束并发兜底"
```

---

## Task 6: Worker 重入防护

**Files:**
- Modify: `app/activity/worker.py:65-83`

- [ ] **Step 1: 改写 Worker 入口为原子状态锁**

在 `app/activity/worker.py` 顶部添加 import：

```python
from sqlalchemy import update, func
```

将 `_do_parse()` 的步骤 1-4（第 65-83 行）替换为：

```python
def _do_parse(db, activity_id: int) -> None:
    """
    解析的核心流程，拆成独立函数方便异常处理包裹。
    """
    # ===== 步骤 1：原子抢锁 =====
    # 一条 SQL 同时完成"检查状态是 pending + 改为 processing"，
    # 由 PostgreSQL 保证原子性。如果另一个 Worker 已经抢到了这条任务，
    # WHERE status='pending' 不匹配 → 返回空 → 当前 Worker 直接退出。
    # 这就像自动售货机的"投币锁"：第一个硬币锁住商品，第二个硬币退回。
    result = db.execute(
        update(Activity)
        .where(Activity.id == activity_id, Activity.status == "pending")
        .values(status="processing", updated_at=func.now())
        .returning(Activity.id)
    )
    locked_row = result.fetchone()
    db.commit()  # 提交状态变更，让其他进程能看到

    if locked_row is None:
        # 任务已被其他 Worker 抢走，或状态不是 pending（已处理/已失败）
        return

    # ===== 步骤 2：取完整记录 =====
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if activity is None:
        return

    user = db.query(User).filter_by(id=activity.user_id).first()
    if user is None:
        raise ValueError(f"User {activity.user_id} 不存在")

    # ===== 步骤 3：下载 GPX 文件 =====
    gpx_content = _storage.download(activity.file_url)

    # ===== 步骤 4：解析 GPX =====
    # （原来的步骤 5，编号前移因为步骤 4"更新状态"已合并到步骤 1）
    weight = float(user.weight) if user.weight else 70.0
    result = parse_gpx(gpx_content, weight=weight)
```

后续代码（步骤 5.5 轨迹点检查、步骤 6-11）保持不变。

- [ ] **Step 2: 运行现有测试确保无回归**

Run: `pytest tests/test_activity.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add app/activity/worker.py
git commit -m "fix(worker): 原子状态锁防止重复处理同一任务"
```

---

## Task 7: 僵尸主动回收脚本

**Files:**
- Create: `scripts/cleanup_zombies.py`

- [ ] **Step 1: 创建僵尸回收脚本**

```python
"""
僵尸活动回收脚本——"快递站仓库巡检员"。

由 cron 每 5 分钟调用一次，负责三件事：
1. processing 僵尸：Worker 崩溃后卡在 processing 超过 10 分钟 → 标记 failed
2. pending 僵尸：Redis 宕机导致入队失败，卡在 pending 超过 30 分钟 → 重新入队
3. 孤儿文件：磁盘上有文件但数据库无对应记录（超过 1 小时）→ 删除

为什么不在 API 或 Worker 里做？
- API 依赖用户请求触发，没人访问就没扫描
- Worker 全挂时最需要扫描，但它自己也挂了
- 独立 cron 脚本不受其他服务影响，跑完就退出，不常驻内存
"""

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from redis import Redis
from rq import Queue
from sqlalchemy import text

# 项目根目录加入 Python 路径，让 import app.xxx 生效
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.database import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cleanup] %(message)s",
)
logger = logging.getLogger(__name__)

# 超时阈值
PROCESSING_TIMEOUT_MINUTES = 10
PENDING_TIMEOUT_MINUTES = 30
ORPHAN_FILE_AGE_HOURS = 1


def cleanup_processing_zombies(db) -> int:
    """
    processing 超过 10 分钟的活动 → 标记 failed。
    返回清理数量。
    """
    result = db.execute(
        text(
            "UPDATE activities "
            "SET status = 'failed', "
            "    error_message = '解析超时（系统自动回收）', "
            "    updated_at = now() "
            "WHERE status = 'processing' "
            "  AND updated_at < now() - interval ':minutes minutes'"
        ),
        {"minutes": PROCESSING_TIMEOUT_MINUTES},
    )
    count = result.rowcount
    if count > 0:
        db.commit()
        logger.info(f"清理 {count} 个 processing 僵尸")
    return count


def rescue_pending_zombies(db) -> int:
    """
    pending 超过 30 分钟的活动 → 尝试重新入队。
    Redis 不可用时静默跳过，下次再试。
    返回成功重新入队数量。
    """
    rows = db.execute(
        text(
            "SELECT id FROM activities "
            "WHERE status = 'pending' "
            "  AND created_at < now() - interval ':minutes minutes'"
        ),
        {"minutes": PENDING_TIMEOUT_MINUTES},
    ).fetchall()

    if not rows:
        return 0

    # 尝试连接 Redis 并重新入队
    try:
        redis_conn = Redis.from_url(settings.REDIS_URL)
        queue = Queue("ridemap", connection=redis_conn)
    except Exception as e:
        logger.warning(f"Redis 连接失败，跳过 pending 僵尸回收: {e}")
        return 0

    from app.activity.worker import parse_activity

    rescued = 0
    for row in rows:
        activity_id = row[0]
        try:
            queue.enqueue(parse_activity, activity_id, job_timeout=120)
            rescued += 1
            logger.info(f"重新入队 activity_id={activity_id}")
        except Exception as e:
            logger.warning(f"入队失败 activity_id={activity_id}: {e}")

    return rescued


def cleanup_orphan_files(db) -> int:
    """
    扫描上传目录，清理超过 1 小时且数据库无对应记录的孤儿文件。
    1 小时阈值防止误删正在上传中的文件。
    返回清理数量。
    """
    upload_dir = Path(settings.UPLOAD_DIR)
    if not upload_dir.exists():
        return 0

    cutoff = time.time() - ORPHAN_FILE_AGE_HOURS * 3600
    cleaned = 0

    for filepath in upload_dir.iterdir():
        if not filepath.is_file():
            continue
        # 文件创建时间早于 1 小时前
        if filepath.stat().st_mtime > cutoff:
            continue

        # 检查数据库中是否有引用此文件的 Activity
        # file_url 存的是相对路径（如 "uploads/xxx.gpx"）
        relative_path = str(filepath.relative_to(upload_dir.parent))
        exists = db.execute(
            text("SELECT 1 FROM activities WHERE file_url = :url LIMIT 1"),
            {"url": relative_path},
        ).fetchone()

        if exists is None:
            filepath.unlink()
            cleaned += 1
            logger.info(f"删除孤儿文件: {filepath.name}")

    return cleaned


def main():
    db = SessionLocal()
    try:
        cleanup_processing_zombies(db)
        rescue_pending_zombies(db)
        cleanup_orphan_files(db)
    except Exception as e:
        logger.error(f"清理脚本异常: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 本地测试脚本能正常运行**

Run: `docker compose -f docker-compose.dev.yml exec api python scripts/cleanup_zombies.py`
Expected: 正常退出，无报错（当前无僵尸时输出为空）

- [ ] **Step 3: Commit**

```bash
git add scripts/cleanup_zombies.py
git commit -m "feat(scripts): 僵尸活动回收脚本 — processing/pending/孤儿文件"
```

---

## Task 8: 僵尸回收 Docker 配置

**Files:**
- Create: `crontab`
- Modify: `docker-compose.dev.yml`
- Modify: `docker-compose.yml`

- [ ] **Step 1: 创建 crontab 配置文件**

项目根目录创建 `crontab`：

```
# 每 5 分钟执行僵尸回收脚本
*/5 * * * * cd /app && python scripts/cleanup_zombies.py >> /proc/1/fd/1 2>&1
```

注：`>> /proc/1/fd/1` 让 cron 输出进入 Docker 日志，方便 `docker logs` 查看。

- [ ] **Step 2: docker-compose.dev.yml 添加 cleanup 服务**

在 `services:` 下、`volumes:` 之前添加：

```yaml
  cleanup:
    build: .
    command: sh -c "cp /app/crontab /etc/crontabs/root && crond -f -l 2"
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://ridemap:${DB_PASSWORD}@db:5432/ridemap
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - uploads:/app/uploads
```

- [ ] **Step 3: docker-compose.yml（生产版）也添加相同的 cleanup 服务**

检查 `docker-compose.yml` 并添加同样的 cleanup 服务配置（环境变量按生产版调整）。

- [ ] **Step 4: 启动并验证 cron 在运行**

Run: `docker compose -f docker-compose.dev.yml up -d cleanup && docker compose -f docker-compose.dev.yml logs cleanup --tail 5`
Expected: 看到 crond 启动日志，无报错

- [ ] **Step 5: Commit**

```bash
git add crontab docker-compose.dev.yml docker-compose.yml
git commit -m "feat(deploy): 僵尸回收 cron 容器配置"
```

---

## Task 9: 最终验证

**Files:** 无新改动，纯验证

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS，无新增失败

- [ ] **Step 2: Docker 全服务启动验证**

Run: `docker compose -f docker-compose.dev.yml up -d && docker compose -f docker-compose.dev.yml ps`
Expected: api、worker、db、redis、cleanup 五个服务全部 running

- [ ] **Step 3: 端到端上传测试**

用已有的 JWT token 上传一个 GPX 文件，验证：
1. 上传成功返回 activity_id
2. 轮询状态从 pending → processing → completed
3. 重复上传同一文件返回同一个 activity_id

- [ ] **Step 4: 索引验证**

Run:
```sql
EXPLAIN ANALYZE SELECT MIN(elapsed_time) FROM segment_efforts WHERE segment_id = 1 AND user_id = 1;
```
Expected: 执行计划中出现 `idx_efforts_segment_user_time`

- [ ] **Step 5: 代码健康度巡检**

Run: `wc -l app/**/*.py`
确认无文件超过 500 行红线。

- [ ] **Step 6: 最终 Commit（如有微调）**

如果验证过程中有微调，统一 commit：
```bash
git commit -m "fix(phase0): 最终验证微调"
```
