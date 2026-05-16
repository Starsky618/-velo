# Sprint 6 Task-3 — activities.city 字段 + worker hook + 城市勋章 endpoint

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 3 个 task / 后端独立 / 无前置依赖
> v0.2（2026-05-16）：v0.1 假设 activities.city 存在 / 实际不存在 / Tim 拍路 B 落地：加字段 + 迁移 + worker hook + 旧数据 backfill
> v0.3（2026-05-16）：修第二轮双审 4 处 Critical/Important —— 空轨迹**留 NULL 不写 unknown** / 标弱依赖 task-2 cities.py / partial index 加 SQLite dialect 守卫 / worker hook 定位 worker.py（不是 service.py）/ 补 FIT 路径测试 / conftest._activities_table 加 city 列
> v0.4（2026-05-16）：修第三轮 Critical —— backfill 脚本空 track / 坐标缺失 → 保持 NULL（与 worker hook 对齐 / 不写 'unknown'）；spec 注明 Strava 导入路径 worker hook 实施时锁定具体行 + 测试 case 验证；声明"维护城市真实 3 处"（geo.py + users.city CHECK + activities.city CHECK）
> 上下文：2026-05-15 brainstorm 创新 3 / Tim 拍 / 把"我去过哪儿"从工具升级成"游戏化驱动" / 2026-05-16 双审 Critical 实证后改路 B

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

让"我的"页能显示一面"城市征服墙"——6 个城市每个一格 / 已骑过的点亮 / 没骑过的灰色 / 标题"城市征服：3 / 6"。

但 v5 期的 activity 表**没有**记录"这次活动是在哪个城市骑的"——只有 user 表上有用户的主城。所以这次必须：
1. 给每条骑行记录加一格"骑行起点城市"
2. 改造 worker（GPX / Strava / FIT 三条上传路径都改）/ 在解析完成时自动写入这一格
3. 写脚本回填历史活动（用已存的轨迹起点经纬度算城市）
4. 写一个后端接口：算用户在哪几个城市骑过 / 返已点亮列表 + 进度

完成后前端 task-4 才能显示城市勋章墙。

### 用户故事

**故事 A — 看到征服进度**
小明打开"我的"页 → 看到一面墙 "🏙️ 城市征服：3 / 6" → 北京 / 上海 / 杭州 三格亮着 / 深圳 / 成都 / 太原 三格灰着。

**故事 B — 出差顺便骑解锁**
小明下个月去成都出差 → 带车骑了一圈环城绿道 → 上传 GPX → worker 解析时识别起点经纬度落在成都 → 写 activity.city = "chengdu" → 第二天打开"我的"页 → 成都格自动点亮 → 进度变 "4 / 6"。

**故事 C — 自看 = 他看**
CCF 点小明头像看 user 页 → 看到的勋章墙跟小明自己看的完全一样（同 3 个点亮 / 同进度 3 / 6）。

**故事 D — 萌新无勋章**
新注册用户没上传任何活动 → 勋章墙全 6 城灰色 / 进度 0 / 6。

**故事 E — 历史活动回填**
v5 期之前的老活动也算数 → 部署 task-3 时跑回填脚本 → 老活动起点城市自动算 → 用户的勋章不会"丢"。

### 怎么算做对了

- ✓ 用户骑过北京 + 上海 → 接口返 unlocked = ["beijing", "shanghai"] / 进度 2 / 6
- ✓ 起点不在 6 城（如骑老家小县城）→ activity.city 写 "unknown" / 不计入勋章解锁
- ✓ 起点没坐标（旧数据 simplified_track 为空）→ activity.city NULL / 不报错
- ✓ 接口同时返 "全 6 城列表 + 中文 label"（前端不用自己维护城市名）
- ✓ 自他对称（新字段强制一致）
- ✓ 单用户聚合 < 100ms
- ✓ Backfill 脚本干跑 + 真跑 / 历史活动起点城市正确写入
- ✗ 用户能手填解锁城市 / 是 bug
- ✗ 7 城外字符串（如"南京"）混进解锁 / 是 bug
- ✗ Worker hook 写城市失败导致 activity 创建失败 / 是 bug（应该容错跳过）

### 这次**不做**的事

- 前端勋章墙样式 / icon / 灰色vs点亮视觉（task-4）
- 解锁动画 / 庆祝特效（永不做）
- 首次解锁城市的通知推送（保留给未来通知扩展）
- 用户自定义城市 / 海外城市（永不做 / 6 城 + unknown 白名单制）
- 解锁日期 / 解锁顺序展示（本 Sprint 只关心解锁集合）
- 按城市筛 feed / 按城市排行榜（未来 Sprint / activities.city 是基础设施 / 服务多个未来功能）

### 估时

**1-1.5 天**（v0.2 改 / 加迁移 + worker hook 改造 + backfill 脚本 / 含双审）

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 起手必跑：现状 grep

```bash
# Activity 当前字段（PRD § 0.1 实证 无 city）
rg "Column" app/activity/models.py | head -25

# worker GPX 解析完成后写 activity 字段位置
rg "status.*completed|activity.status" app/parsing/ app/activity/

# Strava 导入路径
rg "import_activity|create_activity_from_strava" app/strava/

# infer_city_from_coords 当前用法（v5 期写 user.city）
rg "infer_city_from_coords" app/

# users.city CHECK 约束实证（复用同枚举）
rg "CHECK.*city" app/user/models.py

# 最新迁移 head
rg "^revision = " migrations/versions/sprint5_activity_privacy.py
```

**事实表实证（PRD § 0.1）**：
- Activity 字段：distance / elevation_gain / status / simplified_track（JSONB）/ duplicate_of / etc / **无 city 字段**
- `infer_city_from_coords`（app/common/geo.py:39-60）：纯函数 / 输入 lat,lon / 返 6 城之一 或 'unknown'
- v5 期 worker 用此函数写 `user.city`（用户主城）/ 本 Sprint 让它**同时**写 `activity.city`（活动起点）
- users.city CHECK：6 城 + unknown / 复用同枚举给 activities.city

### Alembic 迁移：加 `activities.city` 字段

> **维护城市的真实 3 处**（v0.4 承认 / 第三轮 Codex Important）：未来加新城市必须**同步改 3 处**：
> 1. `app/common/geo.py:29-36` `_CITY_BOUNDS` 字典（GPS 边界 box / 单一数据源）
> 2. `users` 表的 `ck_users_city` CHECK 约束（Alembic 迁移）
> 3. `activities` 表的 `ck_activities_city` CHECK 约束（本 task 加的迁移 / 见下）
>
> `cities.py` 从 `_CITY_BOUNDS.keys()` 派生 / 不算第 4 份。Alembic 迁移文件不能 import 应用代码（迁移要可独立跑）所以 CHECK 字符串必须写死 / 这是工程不可避免约束。

文件：`migrations/versions/sprint6_activity_city.py`

```python
"""sprint6_activity_city

Revision ID: sprint6_activity_city
Revises: sprint6_user_bio  # 在 task-1 迁移之后
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa

revision = "sprint6_activity_city"
down_revision = "sprint6_user_bio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'activities',
        sa.Column('city', sa.String(32), nullable=True),
    )
    # CHECK 约束（与 users.city 完全一致 / 6 城 + unknown）
    op.create_check_constraint(
        'ck_activities_city',
        'activities',
        "city IS NULL OR city IN ('beijing','shanghai','hangzhou',"
        "'shenzhen','chengdu','taiyuan','unknown')",
    )
    # partial index 加速 city-medals 聚合（v0.3：PG 才创建 / SQLite 跳过 / CLAUDE.md 陷阱 #15 pattern）
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.create_index(
            'idx_activities_user_city_completed',
            'activities',
            ['user_id', 'city'],
            postgresql_where=sa.text(
                "status = 'completed' AND city IS NOT NULL AND duplicate_of IS NULL"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.drop_index('idx_activities_user_city_completed', table_name='activities')
    op.drop_constraint('ck_activities_city', 'activities', type_='check')
    op.drop_column('activities', 'city')
```

**Model 同步**（`app/activity/models.py:31` Activity 类追加字段）：
```python
city = Column(
    String(32),
    nullable=True,
    comment="活动起点城市：6 城 + unknown 或 NULL（旧数据 / 起点经纬度缺失）",
)

# __table_args__ 内追加 CheckConstraint（与迁移一致）
```

### Worker hook：解析完成时写 activity.city

GPX / FIT / Strava 三条上传路径都要改。位置：**`app/activity/worker.py`**（不是 service.py / v0.3 修 / 实证现有 user.city hook 在 worker.py:222-253 同位置）/ `status='completed'` 赋值后同处加：

```python
# app/activity/worker.py - 现有 user.city hook 同位置追加 activity.city 写入
from app.common.geo import infer_city_from_coords

def _set_activity_city(activity, simplified_track: list[dict] | None) -> None:
    """从轨迹起点经纬度推断城市 / 写 activity.city。

    语义（v0.3 修 / 与 PRD § 3.3 异常情况对齐）：
    - simplified_track 为空 / 起点坐标缺失 → **不写值**（DB 保持 NULL）
    - 坐标在 6 城内 → 写 6 城之一
    - 坐标在中国但不在 6 城内 → 写 'unknown'（infer_city_from_coords 自然返）
    - 异常 → **不写值**（DB 保持 NULL / 不阻断 activity 创建）

    NULL vs 'unknown' 语义区分：
    - NULL = "从未推断过"（旧数据 / 解析失败 / 无坐标）
    - 'unknown' = "推断过但不在 6 城"（用户骑老家小县城）
    """
    try:
        if not simplified_track:
            return  # 无值 / DB NULL
        first_pt = simplified_track[0]
        lat = first_pt.get('lat')
        lon = first_pt.get('lon')
        if lat is None or lon is None:
            return  # 坐标缺失 / DB NULL
        activity.city = infer_city_from_coords(lat, lon)  # 返 6 城之一 或 'unknown'
    except Exception:
        # 容错：worker 不能因 city 推断失败而炸活动创建 / 保持 NULL
        return
```

**三条上传路径都接入**（任一漏 = 该路径上传的活动 city 永远 NULL）：
1. **GPX 上传 worker**：`app/activity/worker.py` 主 process_activity 函数 / status='completed' 赋值同位置
2. **FIT 上传 worker**：同 worker.py / file_ext 分支 / GPX 和 FIT 走同一 worker 函数 / 一次接入即可覆盖
3. **Strava 导入**：**实施时必须 grep 锁定具体行**（v0.4 加 / 第三轮 reviewer-integration 抓 / spec 不锁会漏掉风险）：
   ```bash
   rg "status.*completed|save_parse_result|simplified_track" app/strava/import_scheduler.py app/strava/service_sync.py
   ```
   预期接入点：`import_scheduler._process_strava_activity` SAVEPOINT 后 / activity.status = 'completed' 赋值同位置 / 调 `_set_activity_city(activity, simplified_track)`。**测试 case-9（Strava worker hook）必须真覆盖该路径**（不能只 mock activity / 必须从 import_scheduler 起跑到 hook）。

### Backfill 脚本 `scripts/backfill_activity_city.py`

```python
"""一次性回填脚本：给历史 activity 写 city。

干啥：遍历所有 simplified_track is not None 的 activity / 推断起点城市 / UPDATE city。

操作注意：
- 限速 5 条/秒（节流 / 防 DB 风暴 / 100 用户量级 ≈ 1000-5000 条 activity / 总 5-15 分钟）
- 干跑模式（--dry-run）：只打印将要 UPDATE 的 row 数 / 不真写
- 真跑模式：写一行 UPDATE 一行（不批量 / 失败一行不影响其他）

部署纪律：
- 先干跑确认 row 数合理
- 再真跑 / 跑完 grep activity.city 分布看 6 城 + unknown 计数
"""

import argparse
import time
from app.database import SessionLocal
from app.activity.models import Activity
from app.common.geo import infer_city_from_coords


def main(dry_run: bool):
    db = SessionLocal()
    try:
        activities = db.query(Activity).filter(
            Activity.simplified_track.isnot(None),
            Activity.city.is_(None),  # 只回填未写过的
        ).all()

        print(f"找到 {len(activities)} 条待回填 activity")
        if dry_run:
            print("--dry-run 模式 / 不写")
            return

        for a in activities:
            try:
                track = a.simplified_track or []
                if not track:
                    # v0.4 修：空轨迹 → 保持 NULL（与 worker hook NULL 语义一致 / 第三轮 Critical）
                    # NULL = 从未推断过 / unknown = 推断过但不在 6 城 / 不可混淆
                    continue
                first = track[0]
                lat = first.get('lat')
                lon = first.get('lon')
                if lat is None or lon is None:
                    continue  # 坐标缺失 / 保持 NULL
                a.city = infer_city_from_coords(lat, lon)  # 返 6 城之一 或 'unknown'
                db.commit()
                print(f"activity_id={a.id} city={a.city}")
            except Exception as e:
                db.rollback()
                print(f"activity_id={a.id} 失败：{e}")
            time.sleep(0.2)  # 5 条/秒
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(args.dry_run)
```

### 城市勋章 endpoint（`app/user/router.py` + `service_social.py`）

```python
# app/user/router.py（前缀 /api/user 单数 / 已有）
@router.get("/me/city-medals", response_model=schemas.CityMedalsResponse)
def get_my_city_medals(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service_social.get_city_medals(db, user_id)


@router.get("/{user_id}/city-medals", response_model=schemas.CityMedalsResponse)
def get_user_city_medals(
    user_id: int,
    requester_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        service.get_user_by_id(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return service_social.get_city_medals(db, user_id)
```

### Service 聚合（`app/user/service_social.py`）

```python
from app.user.cities import VALID_CITY_CODES, CITY_LABELS  # task-2 共享 6 城常量


def get_city_medals(db, user_id: int) -> dict:
    """聚合用户已点亮城市（6 城枚举内 / 排除 unknown / 排除 NULL）。"""
    # 单条 SQL / GROUP BY / partial index 命中 / 不引入 N+1
    unlocked_rows = db.query(Activity.city).filter(
        Activity.user_id == user_id,
        Activity.status == "completed",
        Activity.duplicate_of.is_(None),  # Sprint 5 dedupe 兼容
        Activity.city.isnot(None),
        Activity.city.in_(VALID_CITY_CODES),  # 排除 unknown / 排除 7 城外异常值
    ).group_by(Activity.city).all()

    unlocked = sorted({row[0] for row in unlocked_rows})

    medals = [
        {"city": code, "label": CITY_LABELS[code], "unlocked": code in unlocked}
        for code in VALID_CITY_CODES
    ]

    return {
        "unlocked": unlocked,
        "unlocked_count": len(unlocked),
        "total": len(VALID_CITY_CODES),  # 6
        "medals": medals,
    }
```

### Schemas（`app/user/schemas.py`）

```python
class CityMedal(BaseModel):
    city: str  # "beijing"
    label: str  # "北京"
    unlocked: bool


class CityMedalsResponse(BaseModel):
    unlocked: list[str]  # ["beijing", "shanghai"]
    unlocked_count: int  # 2
    total: int  # 6
    medals: list[CityMedal]  # 全 6 城（前端不用自己维护城市名）
```

### 测试要求（v0.3：最少 11 条 pytest / 加 FIT 路径 + NULL 语义 + 看不存在用户）

1. 用户骑过 beijing + shanghai → unlocked = ["beijing", "shanghai"] / count = 2
2. 用户无活动 → unlocked = [] / count = 0 / total = 6
3. 用户活动 city = 'unknown' → 不计入解锁
4. **用户活动 city = NULL（旧数据 / 无坐标）→ 不计入解锁 / 不报错**（v0.3 加 / 区分 NULL vs 'unknown'）
5. 用户活动 city = 'nanjing'（CHECK 约束应拒收 / DB 层兜底）→ IntegrityError
6. activities.city CHECK 约束在 PG 生效 / SQLite fixture 跳过约束（dialect 守卫）
7. Worker hook：GPX 上传 → activity.city 写入（mock infer_city_from_coords）
8. **Worker hook：FIT 上传 → activity.city 写入**（v0.3 加 / 即使 GPX/FIT 共 worker 函数也要独立验证）
9. Worker hook：Strava 导入 → activity.city 写入
10. **Worker hook：simplified_track 空 / lat lon 缺失 → activity.city = NULL（不写 'unknown'）**（v0.3 加 / NULL 语义验证）
11. Backfill 脚本干跑：列出 row 数 / 不真写
12. 自他对称：GET /api/user/me/city-medals === GET /api/user/{user_id}/city-medals
13. **看不存在用户：GET /api/user/{999}/city-medals → 404**（v0.3 加）
14. 性能：1000 条 activities 用户聚合 < 100ms（partial index 命中）

**conftest 提醒**（v0.3 加 / reviewer-integration 抓的）：`tests/conftest.py` 的 `_activities_table` 当前可能缺 `city` 列 / worker hook 测试若用 ORM `Activity` 对象会因 SQLite 测试表无此列报错 / **必须在 conftest 同步加 `Column("city", String(32), nullable=True)`**。

### 双审顺序

1. **Claude A 忠 PRD**：6 城枚举正确 / 自他对称 / 0 解锁返空数组而非 null / activities.city CHECK 约束与 users.city 完全一致
2. **Claude B 集成审**：GPX/FIT/Strava 三路径 worker hook 都接入 / 任一漏 = bug / partial index 是否真生效 / dedupe `duplicate_of IS NULL` 过滤
3. **Codex 异源审**：扫"未知 / null / 7 城外字符串过滤完整性" + "Backfill 脚本限速 + 容错" + "GROUP BY 性能 + partial index 是否覆盖"

### 依赖 / 顺序

- **弱依赖：task-2**（cities.py 共享常量 `VALID_CITY_CODES` / `CITY_LABELS` 由 task-2 起手建 / task-3 import 使用）
  - 部署顺序：task-2 先 commit cities.py / task-3 再合并 / 否则 task-3 单独执行会 ImportError
  - 严格说本 task 不需要 task-2 完整 ship / 只需 task-2 的 cities.py 文件已 merge
- 阻塞：task-4（前端勋章墙依赖此 endpoint）
- **Alembic 链顺序**：本 task 迁移 `down_revision = "sprint6_user_bio"`（task-1 迁移之后）/ 部署时 `alembic upgrade head` 自动按链跑 / 但 task-1 / task-3 并行开发时需注意 commit 顺序

### 部署 SOP（v0.2 多两步）

1. 本地 `git push origin main`
2. 远端 `git pull`
3. **Alembic upgrade head**（加 activity.city 字段 + CHECK + partial index）
4. **跑 backfill 脚本**：先 `--dry-run` / 再真跑
5. 清 Redis cache（profile / user / city-medals 相关 key）
6. `docker compose up -d --build`（worker 镜像必须 rebuild / 加 hook 代码）
7. curl verify：
   - `curl /api/user/me/city-medals -H "Authorization: Bearer $TOKEN"` → 含 unlocked / total=6
   - 上传一条 GPX 活动 → 查 DB `SELECT city FROM activities ORDER BY id DESC LIMIT 1` → 应有 6 城或 unknown

</details>
