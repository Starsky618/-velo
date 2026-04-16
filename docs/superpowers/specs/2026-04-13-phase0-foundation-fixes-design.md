# 第 0 期：地基修补 — 设计文档

> 前置条件：本文档中的 6 个修复必须全部完成后，才能进入第 1 期（数据来源翻译层）。
> 修复顺序：① → ② → ③ → ④ → ⑤ → ⑥，每个修复独立 commit。

---

## 背景

2026-04-13 的工程审查发现现有系统存在 5 个红灯级漏洞 + 1 个黄灯级缺陷。
这些问题在当前 1 人测试阶段不致命，但在接入 Strava、用户量增长后会引发：
- 内存溢出导致服务崩溃
- 重复数据污染排行榜
- 僵尸记录永久占用资源
- 并发写入导致数据错乱

必须在新功能开发前修复。

---

## 修复 ①：数据库连接池配置

### 问题
`database.py` 未显式配置连接池参数，SQLAlchemy 默认 pool_size=5。
API 进程（2 个 uvicorn worker）+ RQ Worker 共 3 个进程，各自独立连接池。
实际基础连接数 = 3 × 5 = 15，峰值可能更高。高并发时连接排队等待，请求超时。

### 方案
```python
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=8,
    max_overflow=12,
    pool_recycle=3600,
    pool_pre_ping=True,
)
```

### 参数依据（基于 2 核 4G 腾讯云服务器）
- 实际总基础连接：3 个进程 × 8 = 24（PostgreSQL max_connections=100，余量充足）
- 峰值总连接：3 × (8+12) = 60（仍在 max_connections 内）
- pool_recycle=3600：每小时回收，防止数据库重启后出现死连接
- 每连接内存 ~5-10MB，24 连接 ≈ 120-240MB，4G 服务器可承受

### 改动范围
- `app/database.py`：1 处，改 create_engine 参数

### 未来注意
用户量超过 300 后，考虑 API 和 Worker 分开配置连接池（Worker 单线程处理，pool_size=2 即够）。

---

## 修复 ②：轨迹点数量上限

### 问题
上传校验只检查文件大小（50MB），不检查轨迹点数量。
50MB GPX 可含 50 万点，解析时内存峰值 ~400MB，足以在 4G 服务器上触发 OOM。

### 方案：两层防御

**第一层（上传时，格式相关）：**
在 `validate_gpx_file()` 中，对原始字节做轻量标签计数：
```python
trkpt_count = file_bytes.count(b"<trkpt")
if trkpt_count > 50000:
    raise ValueError("轨迹点过多（最多 50000 个，约 14 小时骑行）")
```
- 纯字节扫描，50MB 耗时毫秒级，不建 DOM 树，不吃额外内存
- 上限 50000 点 ≈ 14 小时连续记录（1 秒/点），覆盖所有单日骑行

**第二层（Worker 中，格式无关）：**
在 `_do_parse()` 中，解析后检查：
```python
if len(result["trackpoints"]) > 50000:
    raise GPXParseError("轨迹点过多，请裁剪后重新上传")
```
- 安全网，防止第一层漏掉的边界情况（如异常格式）
- 未来 FIT/Strava 解析器共用同一个出口检查

### 可拓展性设计
第一层是格式相关的，未来每种格式实现自己的轻量计数：
- GPX：数 `<trkpt` 标签
- FIT：读文件头 data records 计数
- Strava Streams：JSON 数组 length

第二层是格式无关的，所有解析器输出标准 trackpoints 后统一检查。
这与第 1 期翻译层的"入口校验 + 出口校验"架构一致。

### 改动范围
- `app/activity/service.py`：`validate_gpx_file()` 加标签计数
- `app/activity/worker.py`：`_do_parse()` 解析后加 len() 检查

---

## 修复 ③：重复上传防护

### 问题
无任何去重机制。用户双击上传或隔天重传同一文件 → 两条 Activity、双倍 trackpoints、排行榜出现重复成绩。

### 方案：SHA-256 文件哈希去重

**上传时：**
```python
import hashlib
file_hash = hashlib.sha256(file_bytes).hexdigest()

existing = db.query(Activity).filter_by(user_id=user_id, file_hash=file_hash).first()
if existing:
    return existing  # 直接返回已有记录，不报错
```

**数据库约束：**
Activity 模型新增 `file_hash` 字段（String(64), nullable=True），并添加：
```python
UniqueConstraint("user_id", "file_hash", name="uq_user_file_hash")
```
- nullable=True：历史记录无哈希值，不影响约束
- UNIQUE 约束是并发插入的最后防线（应用层检查存在 TOCTOU 竞态窗口）

**应用层并发处理：**
如果两个请求同时通过应用层检查，第二个 INSERT 触发 UNIQUE 冲突 → catch IntegrityError → 查询已有记录返回。

### 不做的事
- 不做 started_at 模糊匹配（过度设计，误杀风险高，MVP 阶段无跨平台重复场景）
- 不做自动合并（合并涉及 trackpoints/efforts 级联操作，风险高，收益低）
- Strava 接入后用 `strava_activity_id` 天然去重，不需要模糊匹配

### 改动范围
- `app/activity/models.py`：Activity 新增 `file_hash` 字段 + UNIQUE 约束
- `app/activity/service.py`：`upload_gpx()` 加哈希计算 + 查重
- `migrations/versions/`：Alembic 迁移脚本

---

## 修复 ④：Worker 重入防护

### 问题
如果同一个 activity_id 的任务被入队两次（网络抖动重试、RQ 超时重入队等），
两个 Worker 同时处理 → trackpoints 双倍插入、统计字段互相覆盖。

### 方案：原子状态锁 + 合理超时

**Worker 入口改为原子操作：**
```python
from sqlalchemy import update

result = db.execute(
    update(Activity)
    .where(Activity.id == activity_id, Activity.status == "pending")
    .values(status="processing", updated_at=func.now())
    .returning(Activity.id)
)
if result.fetchone() is None:
    return  # 已有人在处理，或状态不对，直接退出

activity = db.query(Activity).filter_by(id=activity_id).first()
```
- 一条 SQL 完成"检查 + 锁定 + 更新"，原子性由 PostgreSQL 保证
- 第一个 Worker 拿到锁 → 继续处理
- 第二个 Worker 发现 status 不是 pending → 退出
- 零竞态窗口，零新依赖

**入队时设置超时 + 禁止重试：**
```python
_queue.enqueue(parse_activity, activity.id, job_timeout=120)
```
- 120 秒硬上限（正常任务 5-30 秒完成，120 秒是异常安全阀）
- RQ 默认不自动重试，保持默认即可
- 超时后 Worker 进程被终止，activity 卡在 processing → 由修复 ⑤ 僵尸回收处理

### 改动范围
- `app/activity/worker.py`：`_do_parse()` 入口改为原子 UPDATE
- `app/activity/service.py`：`_queue.enqueue()` 加 `job_timeout=120`

---

## 修复 ⑤：僵尸主动回收

### 问题
两种僵尸无人清理：
1. processing 僵尸：Worker 崩溃后 activity 永远卡在 processing（当前只有用户轮询时才检测）
2. pending 僵尸：Redis 宕机导致入队失败，activity 永远卡在 pending（无任何检测机制）

### 方案：独立 cron 定时扫描

**新增 `scripts/cleanup_zombies.py`，三个职责：**

```sql
-- 1. processing 僵尸 → 标记 failed
UPDATE activities
SET status = 'failed', error_message = '解析超时（系统自动回收）'
WHERE status = 'processing'
  AND updated_at < now() - interval '10 minutes';

-- 2. pending 僵尸 → 重新入队（给系统第二次机会，而不是甩锅给用户）
SELECT id FROM activities
WHERE status = 'pending'
  AND created_at < now() - interval '30 minutes';
-- 对每条结果：尝试 _queue.enqueue()，失败则 log 并跳过，下次再试

-- 3. 孤儿文件 → 清理磁盘
-- 扫描上传目录，找到 > 1 小时的文件且 DB 无对应 Activity 记录 → 删除
-- 1 小时阈值防止误删正在上传中的文件
```

**部署方式：docker-compose 独立容器**
```yaml
cleanup:
  image: velo-api  # 复用 API 镜像，不额外构建
  command: crond -f    # 前台运行 cron 守护进程
  volumes:
    - ./scripts:/app/scripts
    - ./crontab:/etc/crontabs/root
  depends_on:
    - db
    - redis
```

crontab 内容：
```
*/5 * * * * cd /app && python scripts/cleanup_zombies.py >> /var/log/cleanup.log 2>&1
```

### 防火墙隔离
- cron 容器挂了 → 僵尸堆积，但 API 和 Worker 完全不受影响
- cron 脚本只读写 activities 表 + 调用 RQ enqueue，不触碰 trackpoints/segments
- Redis 挂了 → 重新入队失败 → log 并跳过 → Redis 恢复后下次扫描自动成功

### 改动范围
- 新增 `scripts/cleanup_zombies.py`
- 新增 crontab 配置文件
- `docker-compose.yml` / `docker-compose.dev.yml`：新增 cleanup 服务

---

## 修复 ⑥：补缺失索引

### 问题
`segment_efforts` 表缺少 `(segment_id, user_id, elapsed_time)` 复合索引。
"用户在某赛段的个人最佳"查询（PR 检测的核心查询）走全表扫描。

### 方案
Alembic 迁移新增索引：
```python
op.create_index(
    "idx_efforts_segment_user_time",
    "segment_efforts",
    ["segment_id", "user_id", "elapsed_time"],
)
```

### 为什么是三列而不是两列
```sql
-- PR 检测查询：
SELECT MIN(elapsed_time) FROM segment_efforts
WHERE segment_id = :sid AND user_id = :uid;
```
三列索引可以做 index-only scan（不回表），两列索引还要回表读 elapsed_time。

### 改动范围
- `migrations/versions/`：新增 Alembic 迁移脚本
- `app/segment/models.py`：SegmentEffort.__table_args__ 中补上索引定义（保持模型和迁移一致）

---

## Alembic 迁移策略

修复 ③ 和 ⑥ 都需要数据库迁移。合并为一个迁移脚本：

```
migrations/versions/xxxx_phase0_foundation_fixes.py
  - activities 表新增 file_hash 列（String(64), nullable=True）
  - activities 表新增 UNIQUE(user_id, file_hash) 约束
  - segment_efforts 表新增 idx_efforts_segment_user_time 索引
```

一个迁移脚本 = 一次 `alembic upgrade head` = 原子性，要么全成功要么全回滚。

---

## 测试策略

| 修复 | 测试方法 |
|------|---------|
| ① 连接池 | 并发请求压测，观察连接等待时间 |
| ② 轨迹点上限 | 构造 > 50000 点的 GPX，验证上传拒绝 + Worker 拒绝 |
| ③ 重复上传 | 同文件上传两次，验证第二次返回已有 activity_id |
| ④ Worker 重入 | 同一 activity_id 入队两次，验证只有一个被处理 |
| ⑤ 僵尸回收 | 手动造 processing/pending 僵尸 + 孤儿文件，跑脚本验证清理 |
| ⑥ 索引 | EXPLAIN ANALYZE 验证 PR 检测查询用上了新索引 |

---

## 不在本期范围内的事

以下问题已识别但不在第 0 期修复：
- N+1 查询优化（get_user_efforts / get_activity_segments）→ 第 1 期顺带改
- 状态机 CHECK 约束 → 第 1 期翻译层会重构 Worker 流程，届时一起加
- trackpoints 表分区策略 → 数据量到千万级再做，当前 < 100 万行
