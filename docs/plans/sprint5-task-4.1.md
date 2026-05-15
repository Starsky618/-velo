# Sprint 5 Task-4.1 — 加骑行隐私设置 + 整条隐藏过滤

> 所属：Sprint 5 task-4 系列（segment ↔ activity 双向打通 + 隐私体系，共 6 个 task）
> 这是第 1 个 task / 地基层
> 上下文：v5 期 100% 完结后 / 真用回归阶段发现 segment 详情页几个 UX 问题 / 顺手把 Strava 风格的隐私体系也搭起来

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

给"每一次骑行"配一个**隐私控制台**——决定它能不能被别人看到、哪些数据能被别人看到。

这次先把**地基**打好：
- 建数据库表
- 默认所有骑行公开
- "整条隐藏"开关生效

下一步（task-4.6）才在小程序里加 UI 让用户切开关 + 加"隐藏功率/心率"细粒度开关。

### 用户故事

**故事 A — 默认公开**
我（Tim）上传一次新骑行 → 系统自动标"公开" → CCF 用他的 ID 直接打开我这条骑行链接 → 完整看到距离/速度/轨迹/功率/心率

**故事 B — 整条隐藏**
我把"去医院那次"骑行设为"仅自己可见"（这次 task-4.6 才加 UI 开关，本 task 只能用后端测试模拟）→ CCF 拿那条骑行的链接打开 → 显示"骑行不存在" → 但我自己用我账号打开同一条 → 完整能看

**故事 C — 排行榜过滤（私密成绩完全不显示给他人）**
我在妙峰山骑过一次 5:42（排第 3）→ 我把那次骑行设为私密 →
- 别人刷新排行榜 → 那条记录**完全消失** / "共 5 人骑过"变"共 4 人骑过" / 排名 1-2-**4**-5 自动收紧成 1-2-3-4（不跳号 / 别人察觉不到曾经有这条）
- 我自己刷新排行榜 → 仍能看到我那条 5:42 排在原位（带"🔒 仅自己可见"小标记）/ 跟"自己看自己的私密活动详情仍完整可看"是同一个哲学

排名重新编号（不跳号）的理由：跳号会暗示"这里有个私密成绩"，等于泄露隐私存在性。Strava 也是这么做。

**故事 D — 老骑行兼容**
v5 之前已经上传的所有骑行 → 不用做任何事 → 全部自动当成"公开"（默认值兜底）

### 怎么算做对了

- ✓ 新上传任意一条骑行 → 默认公开 → 别人能看
- ✓ 后台把一条骑行标 visibility='private' → 别人访问详情接口 → 404
- ✓ 自己访问自己的私密骑行 → 完整数据照常返回
- ✓ 赛段排行榜里 visibility=private 的记录 → 他人看时**完全消失** / 排名重新连续编号 / "共 N 人骑过"不算私密的
- ✓ 本人看排行榜 → 自己的私密记录仍在原位 + 带"🔒 仅自己可见"标记
- ✓ 老数据（无隐私行）→ 视同 public
- ✗ 任何编辑/删除接口被非本人调用成功 → 是 bug

### 这次**不做**的事（task-4.6 再做）

- 小程序里的隐私开关 UI（设置入口）
- "隐藏功率/心率"两个细粒度开关（这次只建字段不接逻辑）
- "全网 feed"列表（velo 当前根本没这个 endpoint / 是另一期工程）

### 估时

1 天（含双审 + Codex 异源审）

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 现状 grep 实证

- Activity 模型当前**没有** visibility 字段（`rg "visibility" app/activity/models.py` 0 命中）
- 隐私检查 5 处 `if activity.user_id != user_id: raise PermissionError`（`app/activity/service.py:236, 255, 278, 308, 457`）
  - `:236` get_activity_detail（读）
  - `:255` update_activity（写 / 保留仅本人）
  - `:278` delete_activity（删 / 保留仅本人）
  - `:308` get_activity_segments（读）
  - `:457` get_activity_trackpoints（读）
- 排行榜 query 2 处（`app/segment/service_query.py:134-150` TOP20 + `:230-275` 分页）—— task-4.2 才改去重，本 task 只加匿名化 JOIN
- 活动列表 endpoint `/api/activities`（`app/activity/router.py:62`）→ 只返当前用户自己的 → **本 task 不动**（velo 当前无全网 feed）
- migration 命名风格：`migrations/versions/sprint5_xxx.py`（实证 `sprint5_activity_dedupe.py / sprint5_moving_time.py`）

### 新表 activity_privacy

```sql
CREATE TABLE activity_privacy (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    visibility VARCHAR(16) NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'private')),
    hide_power BOOLEAN NOT NULL DEFAULT FALSE,
    hide_heartrate BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_activity_privacy_visibility ON activity_privacy(visibility);
```

migration 文件：`migrations/versions/sprint5_activity_privacy.py`
依赖：`sprint5_moving_time` 之后（最新 migration）

设计取舍说明：
- **独立表 不加 activities 字段** — 符合 CLAUDE.md「防火墙式扩展」硬规则 / 未来加新开关只改这一张表 / 删隐私功能时只删表
- `hide_power / hide_heartrate` 字段建表时建好但本 task 不接逻辑 —— 避免下次 task 再发 migration
- CHECK 约束 + NOT NULL + DEFAULT —— DB 层兜底，应用层失误也不会写脏数据

### ORM

`app/activity/models.py` 加：

```python
class ActivityPrivacy(Base):
    __tablename__ = "activity_privacy"
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True)
    visibility = Column(String(16), nullable=False, default="public")
    hide_power = Column(Boolean, nullable=False, default=False)
    hide_heartrate = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    activity = relationship("Activity", back_populates="privacy")
```

`Activity` 类加：
```python
privacy = relationship("ActivityPrivacy", back_populates="activity",
                       cascade="all, delete-orphan", uselist=False)
```

`uselist=False` —— 一对一关系（每条 activity 最多一行 privacy）

### 服务层改动

**`app/activity/service.py` 加 helper**：

```python
def _can_view_activity(activity, viewer_user_id: int | None) -> bool:
    """
    访问控制：本人始终可看 / 其他人按 privacy.visibility 判定。
    无 privacy 行 = 视同 public（老数据兜底 / LEFT JOIN 自动兜底）。
    """
    if viewer_user_id == activity.user_id:
        return True
    privacy = activity.privacy  # None 或 ActivityPrivacy 实例
    if privacy is None:
        return True  # 默认公开
    return privacy.visibility == "public"
```

**改动 3 处读权限**：`:236 / :308 / :457`，把
```python
if activity.user_id != user_id:
    raise PermissionError("无权查看此活动")
```
改成：
```python
if not _can_view_activity(activity, user_id):
    raise ValueError("活动不存在")  # 404 / 不暴露 private 存在性
```

注意：raise `ValueError` 触发 404，**不是 PermissionError 触发 403**。理由：private 活动对他人应当视同"不存在"，不暴露"有但不让看"。Strava 也是这么做的。

**保留不动**：`:255 update_activity` / `:278 delete_activity` 仍 raise PermissionError —— 编辑删除仅本人。

### 排行榜过滤（私密成绩完全不返给他人）

`app/segment/service_query.py:134-150 / :230-275`：

leaderboard 查询 LEFT JOIN `activity_privacy` + WHERE 过滤：

```python
.outerjoin(ActivityPrivacy, ActivityPrivacy.activity_id == SegmentEffort.activity_id)
.filter(
    or_(
        ActivityPrivacy.visibility == "public",
        ActivityPrivacy.visibility.is_(None),  # 老数据无 privacy 行 → 视同 public
        SegmentEffort.user_id == current_user_id,  # 本人始终能看到自己的
    )
)
```

注意：

1. **rank 必须在过滤之后再编号** —— ORDER BY elapsed_time ASC → 过滤 private → enumerate 1,2,3,4。绝对不能"先编号再过滤"（那样会出现 1-2-4-5 跳号 → 泄露存在性）。
2. **total 也要按过滤后算** —— "共 N 人骑过"统计在过滤后的结果集做 COUNT，不能直接 COUNT(\*) 原表。
3. **本人的私密 effort 仍在结果集** —— `SegmentEffort.user_id == current_user_id` OR 条件兜底。前端拿到后用 `is_private_self=true` 标记，渲染"🔒 仅自己可见"。返回字段加一个 bool：

```python
items.append({
    "rank": ...,
    "user_id": row.user_id,
    "nickname": row.nickname,
    "avatar_url": row.avatar_url,
    "elapsed_time": row.elapsed_time,
    "is_private_self": (row.privacy_visibility == "private"),  # 本人才会看到这条
    ...
})
```

4. **未登录用户**（current_user_id=None）→ 没有"本人"概念 → OR 条件第三支不生效 → 私密的对未登录用户完全消失。
5. **my_rank 计算**（service_query.py:298-305）也要排除 private 的 effort（算"比我快的人数"时跳过私密成绩）—— 否则 my_rank 跟主榜对不上。

### activity 列表 endpoint 是否需要改

`app/activity/router.py:62 list_activities` —— 当前只返 `user_id=current` 的活动，**不需要改**（本来就是私有列表 / 本人看自己的）。velo 没有"全网 feed"endpoint，那是另一期工程。

### 测试覆盖（pytest）

- `test_activity_privacy_default_public` — 新建 activity 无 privacy 行 → `_can_view_activity` 返 True
- `test_activity_privacy_private_blocks_others` — visibility='private' → 他人调 get_activity → 404
- `test_activity_privacy_self_always_visible` — 本人 visibility='private' → 自己调 get_activity → 200
- `test_leaderboard_filters_private_for_others` — 5 条 effort 1 条私密 → 他人看到 4 条 + 排名 1-2-3-4 连续 / total=4
- `test_leaderboard_shows_own_private_to_self` — 本人看 → 私密那条仍在 + is_private_self=true
- `test_leaderboard_rank_continuous_after_filter` — 第 3 名是私密 → 他人看不到跳号（不是 1-2-4-5）
- `test_my_rank_excludes_private_efforts` — my_rank 计算不数比我快的私密 effort
- `test_old_activities_default_public` — fixture 不建 privacy 行 → 他人访问 → 200
- `test_edit_delete_still_owner_only` — 设 visibility='public' 后他人仍不能 PATCH / DELETE

### 风险 / 边界

- **status='importing' 的临时活动** —— Strava 导入中的活动 user 不该看到自己的"半成品"？目前 detail endpoint 已有 importing 状态过滤 / 本 task 不动
- **trackpoints endpoint** (`:457`) —— private 时 trackpoints 也挡 / 一并匿
- **segment effort 的 created_at** —— 排行榜 row 仍带 effort.created_at（不匿日期）/ 行业惯例：成绩展示要带时间 / 不算敏感

### Codex 异源审重点

派 Codex 时强调：
- 老数据兜底（无 privacy 行 = public）—— 检查 LEFT JOIN + IS NULL 兜底是否覆盖所有读路径
- 排行榜 rank 编号是**过滤后**再编号（不是先编号再过滤 / 否则跳号泄露存在性）
- total / "共 N 人" 统计是否也跟着过滤后算
- 本人能看到自己的私密 effort 标记（is_private_self）
- my_rank 计算是否一致排除 private
- 未登录用户访问排行榜 → 私密 effort 完全消失（OR 条件第三支不生效）
- 编辑/删除是否仍保留 owner-only
- migration 在 PostgreSQL 上是否能跑（CHECK 约束语法 / 类型转换）
- raise ValueError vs PermissionError 的语义切换是否影响 router 异常映射

</details>

---

## 完工汇报模板（task 跑完 commit 前填）

- [ ] migration 在本地 PG 跑过 `alembic upgrade head` 成功
- [ ] 6 个测试用例全绿
- [ ] Claude A 忠 spec 审过
- [ ] Claude B 集成审过
- [ ] Codex 异源审过
- [ ] 我亲自 diff 过 / 没让 subagent 报告替代
