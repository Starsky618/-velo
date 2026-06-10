# Sprint 13 Task-1 — 约骑↔活动自动关联（meetup_activities 表 + attach tick）

> 所属：Sprint 13 闭环主链 / 第 1 个 task / 唯一新后端逻辑，S13 一切的地基。
> 上游：`docs/spec-v6.md` §2.1 / §2.3 / §3.1 / D1-D4 / D9-D10。
> 前置门：无（本 task 是起点）。T2/T3/T5 等本 task commit 后才能开。

---

## ─────── 给 Tim 看 ───────

### 干啥用

约骑当天谁骑完传了文件，系统每 5 分钟自动把那条骑行"挂"到约骑上——战报页每人一格，这个 task 就是格子的点灯人。

类比：约骑像一场考试，每人交的卷子（骑行文件）散落在各自抽屉里。这个 task 是个每 5 分钟巡一圈的收卷员，看到"这人报了周六的约骑、卷子也是周六骑的"，就把卷子钉到那场考试的成绩册上。

### 用户故事

老张周六骑完天龙山，晚上 9 点才想起传文件。传完最多 5 分钟，约骑战报上他的格子就亮了——他自己什么都不用做，不用"选择关联到哪场约骑"。

### 怎么算做对了

- ✓ 约骑当天（按北京日历日）出发前 30 分钟以后开始的骑行，自动挂上。
- ✓ 一人一场只挂一条（当天骑两趟取最早那趟）。
- ✓ 骑完第 3 天才传也能挂上（截止 = 出发后 7 天）。
- ✓ 取消的约骑永远不挂。
- ✓ 系统重复跑、并发跑都不会挂出两条（数据库兜底）。
- ✓ 晚上 8 点出发的约骑不会因为时区算到第二天（北京 20:00 = UTC 12:00 测试用例必须过）。

### 这次不做

- 不在 activity 上传 worker 里触发关联（D1 否决：反向依赖）。
- 不做"用户手动选约骑"的 UI。
- 不迁移 training / notification 里两处存量 `_BJ_TZ` 定义（登记 tech-debt，本期不动已 ship 模块）。
- 不建 route_guides 表（那是 T7 的迁移文件）。

### 估时

1.5 天，含 TDD 与三审。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑（re-grep，偏差先报告再动手）

```bash
nl -ba docs/spec-v6.md | sed -n '46,65p;93,158p'        # §2.1 表定义 + §2.3 bj_time + §3.1 全文
sed -n '1,45p' app/meetup/cron.py                        # complete tick 现状（同模式抄）
sed -n '20,65p' scheduler.py                             # 仓库根目录！counter 块与 import 行
rg -n "^revision|^down_revision" migrations/versions/20260603_meetup_create_prototype_fields.py
sed -n '350,375p' tests/conftest.py                      # SQLite fixture 建表方式
ls tests/ | rg "meetup"                                  # 既有 meetup 测试风格（test_meetup_cron_delete_user.py 等）
```

已验证事实（2026-06-11 主 agent grep）：
- 迁移链末 = revision `"20260603_meetup_create_fields"`（文件名是 `20260603_meetup_create_prototype_fields.py`，revision 串和文件名不同，down_revision 写 revision 串）[✓ grep]
- scheduler 在**仓库根目录** `scheduler.py`：import 行 :22，counter 块 :53-61，`if _meetup_tick_counter >= 20:` 在 :55 [✓ Read]
- `run_meetup_complete_tick` 模式 = 无参 + 自建 `SessionLocal()` + finally close [✓ Read cron.py:35-44]
- meetup/models.py 已 import `Index`(:16) / `UniqueConstraint`(:21)，MeetupActivity 无需新增 import [✓ grep]
- `Activity.started_at` 是 `DateTime(timezone=True), nullable=True` [✓ grep app/activity/models.py:94]；activity 状态值域 pending/processing/completed/failed [✓ grep :54-56]
- Meetup 模型零 relationship，查参与者一律显式 query [✓ spec §0.1 + service.py:427 惯例]
- conftest 的 SQLite fixture：`_test_metadata.create_all` + SQLite 兼容的 ORM 表单独 `__table__.create`（StravaImport 先例 conftest:361-366）；activities 表用手动简化版 `_activities_table`——**T1 测试建 MeetupActivity 表照 StravaImport 先例办**
- training/service.py:39 与 notification/progress_detector.py:46 各有一份 `_BJ_TZ`（存量豁免，登记 tech-debt 不动）[✓ grep]

## 2. 文件改动清单

- Create `app/common/bj_time.py`（**必须先建**，cron.py import 它——blocking 顺序）
- Create `migrations/versions/20260611_meetup_activities.py`（只建本表，与 T7 迁移隔离）
- Modify `app/meetup/models.py`：追加 MeetupActivity 类（文件头 docstring 同步提一句）
- Modify `app/meetup/cron.py`：新增 import 块 + `ATTACH_WINDOW_DAYS` + `attach_meetup_activities` + `run_meetup_attach_tick`；文件头 docstring 更新（模块现在管"收尾"和"收卷"两件事）
- Modify `scheduler.py`（仓库根目录）：:22 import 行加 `run_meetup_attach_tick`；:55 if 块内 complete 之后插一行（**唯一合法插入点**，放 if 外 = 15 秒全量扫描事故）
- Create `tests/test_meetup_attach_tick.py`
- Modify `tests/conftest.py`：按 StravaImport 先例补 `MeetupActivity.__table__.create`（若 `_test_metadata` 未自动覆盖）
- Modify `docs/tech-debt.md`：登记两条——① 存量 `_BJ_TZ` 双定义待迁移 bj_time ② segment↔meetup 历史双向 import（spec §3.9）
- Modify `app/user/service.py` :114 附近注释：delete_user 级联清单补提 `meetup_activities`（user_id CASCADE 自动删，纯注释 5 字改动，防新维护者漏算——双审建议，已授权）
- **Do not** import segment（任何形式）/ **Do not** 写 `meetup.participants` relationship / **Do not** 动 activity worker

## 3. 完整代码

### 3.1 `app/common/bj_time.py`（整文件）

```python
"""
北京时间小工具——全项目共享的"挂钟"。

干啥用：把数据库里的 UTC 时间换算成北京日历上的日期。约骑关联要判断
"这趟骑行是不是约骑当天骑的"，必须按北京时间切日，不能按 UTC 切——
否则晚上 8 点后出发的骑行会被算到第二天（UTC 已过午夜）。
操作注意事项：training/service.py 与 notification/progress_detector.py 还各有一份
旧的 _BJ_TZ 定义（存量豁免，已记 docs/tech-debt.md），新代码一律 import 本模块。
输入/输出：进 datetime（aware 或 naive），出北京日历 date；naive 按 UTC 语义补齐。
"""
from datetime import date, datetime, timedelta, timezone

# 北京时区 = UTC+8。像挂在墙上的"北京钟"：不管库里存的是什么时间，
# 看日历日期前先对一眼这面钟。
BJ_TZ = timezone(timedelta(hours=8))


def to_bj_date(dt: datetime) -> date:
    """把一个时间点换算成北京日历上的日期。

    naive（不带时区）输入按 UTC 处理：生产 PG 字段是 timezone=True 永远 aware，
    只有 SQLite 测试 fixture 取出的是 naive 值（项目陷阱清单 #2），语义上就是 UTC。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BJ_TZ).date()
```

### 3.2 `app/meetup/models.py` 追加（spec §2.1 原文）

```python
class MeetupActivity(Base):
    """约骑↔活动关联——战报上"每人一格"的那颗钉子。"""

    __tablename__ = "meetup_activities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meetup_id = Column(Integer, ForeignKey("meetups.id", ondelete="CASCADE"), nullable=False)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("meetup_id", "activity_id", name="uq_meetup_activity"),
        UniqueConstraint("meetup_id", "user_id", name="uq_meetup_user_one_cell"),
        Index("idx_meetup_activities_meetup", "meetup_id"),
    )
```

### 3.3 迁移 `migrations/versions/20260611_meetup_activities.py`（整文件；动笔前对照 20260603 文件抄项目迁移写法）

```python
"""meetup_activities 关联表（Sprint 13 T1）

约骑↔活动的自动关联落点：attach tick 每 5 分钟把约骑当天的骑行挂进来，
战报页每人一格靠它点亮。双 UNIQUE = 幂等兜底（同场同活动 / 同场同人各一道闸）。
"""
from alembic import op
import sqlalchemy as sa

revision = "20260611_meetup_activities"
down_revision = "20260603_meetup_create_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meetup_activities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meetup_id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["meetup_id"], ["meetups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("meetup_id", "activity_id", name="uq_meetup_activity"),
        sa.UniqueConstraint("meetup_id", "user_id", name="uq_meetup_user_one_cell"),
    )
    op.create_index("idx_meetup_activities_meetup", "meetup_activities", ["meetup_id"])


def downgrade():
    op.drop_index("idx_meetup_activities_meetup", table_name="meetup_activities")
    op.drop_table("meetup_activities")
```

### 3.4 `app/meetup/cron.py` 新增（import 块 + 两个函数）

新增 import（spec §3.1 点名，漏一个 = scheduler 启动即崩）：

```python
from datetime import timedelta   # datetime/timezone 已有则并入现有行

from sqlalchemy.exc import IntegrityError

from app.activity.models import Activity
from app.common.bj_time import to_bj_date
from app.meetup.models import MeetupActivity, MeetupParticipant

# 补传截止：约骑出发时刻起 7 天（D4）。锚 = start_time 时刻，与扫描窗同粒度，无日切歧义。
ATTACH_WINDOW_DAYS = 7
```

```python
def attach_meetup_activities(db: Session) -> int:
    """把约骑当天骑完的活动自动挂到约骑上——战报格子的"点灯人"。

    设计思路（spec v6.4 §3.1 / D1-D4）：
    - 方向：meetup 侧轮询查 activity（零反向依赖，D1）
    - 窗口：约骑当天北京日历日 + started_at >= 出发前 30 分钟（D2）
    - 一人一格：每人每场只挂窗口内最早一条（D3），数据库双 UNIQUE 兜底
    - 截止：出发时刻 + 7 天（D4）
    返回本轮新挂了几条。
    """
    now = datetime.now(timezone.utc)
    attached = 0
    meetups = (
        db.query(Meetup)
        .filter(
            Meetup.status.in_(["OPEN", "COMPLETED"]),
            Meetup.start_time >= now - timedelta(days=ATTACH_WINDOW_DAYS),
        )
        .all()
    )
    for meetup in meetups:
        # Meetup 模型零 relationship，查参与者一律显式 query（项目惯例 service.py:427）
        participants = db.query(MeetupParticipant).filter_by(meetup_id=meetup.id).all()
        for participant in participants:
            # 幂等快路径：本人在本场已有格子就跳过。两个条件缺一不可——
            # 只按 user_id 查会把"他在另一场的格子"误判成"本场已挂"（D10 跨场不互斥）。
            exists = (
                db.query(MeetupActivity.id)
                .filter(
                    MeetupActivity.meetup_id == meetup.id,
                    MeetupActivity.user_id == participant.user_id,
                )
                .first()
            )
            if exists is not None:
                continue
            # 候选：SQL 先用粗时间窗收口（下界 = 出发前 30 分钟，上界 = 出发 +1 天——
            # 同一个北京日历日最晚也落在这个范围里），再用 to_bj_date 精确判"同一个北京日"。
            # 日切判断放 Python 端：SQL 端做时区日切在 SQLite/PG 两方言写法不一，纯函数最稳。
            candidates = (
                db.query(Activity)
                .filter(
                    Activity.user_id == participant.user_id,
                    Activity.status == "completed",
                    Activity.started_at.isnot(None),
                    Activity.started_at >= meetup.start_time - timedelta(minutes=30),
                    Activity.started_at < meetup.start_time + timedelta(days=1),
                )
                .order_by(Activity.started_at.asc())
                .all()
            )
            match = None
            for activity in candidates:
                if to_bj_date(activity.started_at) == to_bj_date(meetup.start_time):
                    match = activity
                    break
            if match is None:
                continue
            # 先把 id 取成普通整数再 commit——commit 后 ORM 对象会过期，
            # 直接在日志里访问属性会触发一次多余的回库查询。
            meetup_id, user_id, activity_id = meetup.id, participant.user_id, match.id
            db.add(MeetupActivity(meetup_id=meetup_id, activity_id=activity_id, user_id=user_id))
            try:
                db.commit()
            except IntegrityError:
                # 并发 tick / worker 重试撞 UNIQUE——uq_meetup_activity 与
                # uq_meetup_user_one_cell 两种冲突的正确动作都是跳过，
                # 不解析异常串区分（项目 IntegrityError 惯例，meetup/service.py:191-196）。
                db.rollback()
                continue
            attached += 1
            logger.info(
                "SENSOR attach meetup_id=%s user_id=%s activity_id=%s",
                meetup_id, user_id, activity_id,
            )
    return attached


def run_meetup_attach_tick() -> int:
    """给 scheduler 调的外壳：自己借数据库钥匙，用完一定归还（与 complete tick 同模式）。"""
    db = SessionLocal()
    try:
        return attach_meetup_activities(db)
    finally:
        db.close()
```

**SAVEPOINT 纪律声明（spec B-C2 定案）**：逐行 add+commit 在自建 session 顶层进行，无外层事务，陷阱 #8/#13 不适用——它们管的是"内层模块污染外层事务"，本函数自己就是最外层。reviewer 不要按 SAVEPOINT 缺失报问题。

### 3.5 `scheduler.py`（仓库根目录）两处

```python
# :22 改为
from app.meetup.cron import run_meetup_attach_tick, run_meetup_complete_tick
```

```python
# :53-61 现状是带 try/except 的块（双审 I4 实证，spec 伪码省略了它——改完必须保持异常隔离原样）：
        try:
            _meetup_tick_counter += 1
            if _meetup_tick_counter >= 20:
                run_meetup_complete_tick()
                run_meetup_attach_tick()        # ← 新增仅这一行，5 分钟节拍复用同一个计数器
                _meetup_tick_counter = 0
        except Exception:
            # meetup tick 和 Strava tick 互不拖累（现有注释保留）
            logger.exception("meetup tick 失败")
            _meetup_tick_counter = 0
```

attach tick 抛异常会被这层 except 接住、不会让 scheduler 主循环崩——**不许把新行加在 try 块外**。

## 4. 测试用例（spec §3.1 边界表 12 行各一测，TDD 先写）

`tests/test_meetup_attach_tick.py`，fixture 风格照 `tests/test_meetup_cron_delete_user.py` 抄：

| # | 用例 | 断言 |
|---|---|---|
| 1 | A 当天两骑 | 只挂 started_at 最早一条 |
| 2 | B 两场窗口重叠（不同人各报一场） | 各挂各的，不串场 |
| 3 | F 同人真报两场重叠约骑（D10） | 同一活动挂两场，两行都在 |
| 4 | C 骑完第 3 天才传（COMPLETED 态约骑） | 7 天内照常挂上 |
| 5 | C2 CANCELLED 约骑 | 永不关联 |
| 6 | D 补传昨天的文件 | 按 started_at 匹配，与上传时间无关 |
| 7 | E 幂等双跑 | 连跑两轮 attach，行数不变 |
| 8 | 同人同场二次上传 | 第二条被 uq_meetup_user_one_cell 拒，except 跳过不炸 |
| 9 | 崩在循环中途（模拟：先挂 1 条再跑全量） | 已 commit 的保留，续扫补齐其余 |
| 10 | 参与者退出后才上传 | 不挂（JOIN 当前 participants） |
| 11 | **北京时区日切**：约骑北京 20:00（=UTC 12:00）开始，活动 started_at=UTC 12:30 | 同一北京日，命中 |
| 12 | 未来约骑（明天出发） | 今天的活动不匹配（D2 日期相等天然不命中） |
| 13 | 出发前 31 分钟开始的活动 | 不挂（>=start_time−30min 边界） |
| 14 | status='processing' 的活动 | 不挂（只认 completed） |
| 15 | **凌晨场日切**：约骑北京 00:30（=UTC 前日 16:30）开始，活动当天北京 20:00（=UTC 12:00）开始 | 命中（SQL 上界 start+24h=UTC 当日 16:30=北京次日 00:30，恒覆盖整个北京日——钉死"上界截断候选"的疑虑，双审 I1 误报复核用例） |

另：`to_bj_date` 纯函数单测（aware UTC / aware BJ / naive 三态）。

## 5. 自检（commit 前）

- [ ] 查询计划自检（spec 风险 1）：dev PG 上 `EXPLAIN` attach 扫描主查询，确认走 `idx_meetups_status_start`；结论写进交付报告
- [ ] `rg -n "import segment" app/meetup/cron.py` 必须为空（§3.9 禁令）
- [ ] `python scheduler.py` 本地干跑 10 秒不崩（import 链完整性）
- [ ] pytest 全套绿（不只新增文件）
- [ ] 自检三问：做了卡外的事吗 / 验收命令都真跑了吗 / 与 spec §3.1 逐条对照过吗

## 6. commit 指令

```
feat(meetup): S13-T1 约骑活动自动关联（meetup_activities 表 + attach tick + bj_time 共享模块）
```

</details>
