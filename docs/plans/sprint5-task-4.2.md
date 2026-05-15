# Sprint 5 Task-4.2 — 排行榜按用户去重 + 显示 activity_id 让点击可跳

> 所属：Sprint 5 task-4 系列（segment ↔ activity 双向打通 + 隐私体系，6 个 task）
> 这是第 2 个 task
> 前置：task-4.1 已完成（commit `f877844`）

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

修两件相关的事：
1. **排行榜按人去重**——同一个人骑了 3 次只显示他最快那次（现在会显示 3 行 / "共 3 人骑过"但实际只有 1 人）
2. **每行返 activity_id**——让前端能拿到"这次最快记录对应哪次原始骑行"的引用（task-4.4 才接前端点击跳转 / 本 task 只把数据备好）

### 用户故事

**A — 排行榜每个人只一行**
我自己骑过 3 次妙峰山（5:42 / 6:18 / 7:01）→ 打开赛段详情看排行榜 →
- 现在：显示 "Tim 5:42 / Tim 6:18 / Tim 7:01" 三行 / "共 3 人骑过"
- 改完：只显示 "Tim 5:42" 一行 / "共 1 人骑过"

**B — 数据带 activity_id 备好跳转**
排行榜每行返回多带一个字段 `activity_id`（前端 console.log 能看到）→
task-4.4 时小程序拿这字段做点击跳转 / 本 task 不接前端点击

**C — my_rank 跟着去重逻辑走**
妙峰山有 10 个人骑过 / 我 PR 排第 3 → my_rank=3。如果 CCF 骑了 5 次都比我慢 → 他还是只算 1 人 / 不会把我挤到第 8。

### 怎么算做对了

- ✓ 排行榜每个 user_id 只出现 1 次（取那个人最快那次 effort）
- ✓ "共 N 人骑过"是真的人数（不是 effort 条数）
- ✓ 每条返回带 `activity_id` 字段（对应最快那次 effort 的 activity）
- ✓ created_at 是最快那次的时间（不是最近骑的那次）
- ✓ my_rank 计算只数比我快的"人"不是"次"
- ✓ task-4.1 的隐私过滤行为不变（私密 effort 该消失的还消失）

### 这次**不做**（task-4.4 再做）

- 小程序点击 › 跳转 activity 详情（本 task 只让后端把 activity_id 带上 / 前端 wxml/js 不动）

### 估时

0.5 天

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 现状 grep 实证

- `app/segment/service_query.py:134-175` get_segment_detail TOP20：直接 ORDER BY elapsed_time / 无 GROUP BY user_id / 无 DISTINCT ON
- `app/segment/service_query.py:230-300` get_leaderboard 分页：同样直接 ORDER BY / 无去重
- `app/segment/schemas.py:121-133` LeaderboardEntry：无 activity_id 字段
- `app/segment/models.py` SegmentEffort：有 `activity_id` FK 字段（task-4.1 LEFT JOIN ActivityPrivacy 已用）
- my_pr_query (task-4.1 已改) 取 MIN(elapsed_time) → 本质就是每人最佳 / my_rank 现在数的是"effort 数"不是"人数" → 需同步改

### 实施范围

**1. `app/segment/service_query.py:get_segment_detail` TOP20**

改造思路：
- 用窗口函数 `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY elapsed_time ASC) AS rn` 给每个人的多条 effort 编号
- 外层只保留 rn=1（每人最快的那条）
- 再 ORDER BY elapsed_time ASC LIMIT 20

PostgreSQL 写法（SQLAlchemy）：

```python
from sqlalchemy import func, over

# 子查询：给每条 effort 按 user_id 分组编号（按 elapsed_time 升序）
row_number = func.row_number().over(
    partition_by=SegmentEffort.user_id,
    order_by=[SegmentEffort.elapsed_time.asc(), SegmentEffort.id.asc()],
).label("rn")

subq = (
    db.query(
        SegmentEffort.id.label("effort_id"),
        SegmentEffort.user_id,
        SegmentEffort.activity_id,
        SegmentEffort.elapsed_time,
        SegmentEffort.avg_speed,
        SegmentEffort.avg_power,
        SegmentEffort.created_at,
        ActivityPrivacy.visibility.label("privacy_visibility"),
        row_number,
    )
    .outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
    .filter(SegmentEffort.segment_id == segment_id)
    .filter(or_(
        ActivityPrivacy.visibility == "public",
        ActivityPrivacy.visibility.is_(None),
        SegmentEffort.user_id == current_user_id,
    ))
    .subquery()
)

# 外层：rn=1 + JOIN User + ORDER BY elapsed_time LIMIT 20
leaderboard_rows = (
    db.query(...)
    .select_from(subq)
    .join(User, User.id == subq.c.user_id)
    .filter(subq.c.rn == 1)
    .order_by(subq.c.elapsed_time.asc())
    .limit(20)
    .all()
)
```

**注意 SQLite 兼容性**：SQLite 3.25+ 支持窗口函数。CI 测试 fixture 用的 SQLite 版本要确认 ≥ 3.25。grep `sqlite3.sqlite_version` 验证一下。备选：用 `subquery: SELECT user_id, MIN(elapsed_time) AS best FROM ... GROUP BY user_id` 然后 JOIN 回原表——SQLite 兼容但 SQL 更复杂。

**2. `app/segment/service_query.py:get_leaderboard` 分页**

同样改造 + total 也要按去重后算：

```python
# total = DISTINCT user_id 数（过滤隐私后）
total_query = (
    db.query(func.count(func.distinct(SegmentEffort.user_id)))
    .outerjoin(ActivityPrivacy, ...)
    .filter(SegmentEffort.segment_id == segment_id)
    .filter(or_(... 同主查 ...))
)
total = total_query.scalar()
```

注意 bike_type filter 同步加在 DISTINCT 子查询里。

**3. `app/segment/service_query.py:get_leaderboard` 的 my_rank**

当前 my_rank query：`COUNT(SegmentEffort.id) WHERE elapsed_time < my_pr` → 数 effort 数。
新逻辑：数"比我快的人数"，即 `COUNT(DISTINCT user_id) WHERE elapsed_time < my_pr AND NOT (user_id != me AND visibility=private)`。

写法：
```python
faster_users = (
    db.query(func.count(func.distinct(SegmentEffort.user_id)))
    .outerjoin(ActivityPrivacy, ...)
    .filter(SegmentEffort.segment_id == segment_id)
    .filter(SegmentEffort.elapsed_time < my_elapsed_time)
    .filter(or_(... 同主榜 ...))
)
my_rank = faster_users.scalar() + 1
```

**4. `app/segment/schemas.py:LeaderboardEntry` 加字段**

```python
class LeaderboardEntry(BaseModel):
    ...
    activity_id: Optional[int] = None  # task-4.2：最快那次 effort 对应的活动 ID（前端 task-4.4 用来跳转）
```

Optional 是保险（极端情况某条 effort 的 activity_id 是 NULL / 防 Pydantic 校验失败）。

**5. `app/segment/service_query.py:get_user_efforts` 暂不动**

这是"当前用户在所有赛段的成绩"——每个赛段可能有多次 effort 都展示是合理的（用户想看自己进步轨迹）。不去重 / 不改。

**6. `app/segment/service_query.py:get_activity_segments` 的 rank**

rank 当前算的是"比我快的 effort 数 + 1"。task-4.2 后**主榜显示的 rank 是"比我快的人数 + 1"**——两套要保持一致。

修改：rank query 改成 COUNT(DISTINCT user_id) 而不是 COUNT(SegmentEffort.id)。

### 红线

- 不动 get_user_efforts 去重逻辑（保留每条 effort 单独显示 / 那是用户自己的成绩单）
- 不动 task-4.1 隐私过滤逻辑（OR 三支保持原样）
- 不预写小程序前端跳转（task-4.4 范围）

### 测试覆盖（新加）

- `test_leaderboard_dedupes_by_user` — 同一人 3 条 effort → 榜上只 1 行 / total=1
- `test_leaderboard_returns_activity_id` — 每行有 activity_id 字段 / 对应最快那次的 activity
- `test_leaderboard_dedupe_keeps_best_effort` — 3 条 elapsed_time = [120/90/150]，榜上显示 90 那条的 created_at + activity_id
- `test_leaderboard_total_counts_users_not_efforts` — 5 个 user × 各 3 条 effort，total=5 而不是 15
- `test_my_rank_counts_users_not_efforts` — CCF 骑 5 次都比我慢，my_rank 不被挤
- `test_activity_segments_rank_uses_distinct_users` — activity 详情 rank 跟主榜 rank 一致
- `test_segment_detail_top20_dedupes_too` — TOP20 路径也按人去重

### Codex 异源审重点

- 窗口函数在 SQLite 测试 fixture 真能跑吗？（grep sqlite version / 必要时改 GROUP BY MIN 兼容写法）
- DISTINCT user_id + bike_type filter 是否兼容（DISTINCT 子句 + JOIN User）
- total 去重和主榜去重是否真的一致（参数 / OR 条件 / bike_type 三处对齐）
- my_rank 是否真按"人数"算（不是 effort 数 / 用 DISTINCT user_id）
- activity_id 字段在所有路径（TOP20 / 分页 / my_rank 关联）都正确取到了最快那次的 activity_id
- 一致性：activity 详情页 rank 也改成"比我快的人数"——避免跟主榜对不上号

</details>

---

## 完工汇报模板（task 跑完 commit 前填）

- [ ] pytest 全套绿
- [ ] 窗口函数 / DISTINCT 在 SQLite + PostgreSQL 两个 dialect 都跑通
- [ ] 7 个新测试用例全通过
- [ ] Claude A spec 忠诚审过
- [ ] Claude B 集成审过
- [ ] 我亲自看 diff / 没让 subagent 报告替代
