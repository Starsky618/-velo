# Sprint 6 Task-2 — 数据徽章规则模块

> 所属：Sprint 6（"我的"页基础落地 / 共 6 task）
> 这是第 2 个 task / 依赖 task-1
> 上下文：2026-05-15 brainstorm 创新 1 / Tim 拍 / velo 护城河 = "真实骑行数据自动生成徽章 / 无法编造 / 高信任"
> v0.2（2026-05-16）：修 Activity 字段名（distance / elevation_gain）/ 白名单 `|=` 追加 / 共享 6 城常量
> v0.3（2026-05-16）：修第二轮双审 Critical/Important —— cities.py 起手建（task-2 负责 / task-3 弱依赖）+ cities.py 引用 geo.py 单一真相源 / FTP 加脏数据下界 guard `ftp >= 50` / `_filter_profile_keys` 防回退测试同步更新

---

## ─────── 给 Tim 看（你审这层就够）───────

### 干啥用

后端写一个"徽章自动计算"模块——根据用户的真实骑行数据，自动算出 2-3 个**身份徽章**挂在头像旁。用户没法手填 / 全是数据算出来的 / 所以骗不了人。

这次只动后端：建规则函数 + profile 接口返徽章列表。**前端怎么显示徽章 icon / 颜色 / 排版 留给 task-4**。

### 用户故事

**故事 A — 5 秒判断身份**
CCF 在赛段榜看到陌生骑友"老王" / 点头像进 user 页 / 头像旁挂着 🏔️ FTP 240W / 📏 累计 8500km / 🏆 雀儿山常客 三个徽章。CCF **0.5 秒**判断"这是个 240W 的本地老炮 / 常骑雀儿山"。不用读简介 / 不用翻活动列表 / 决策瞬间完成。

**故事 B — 萌新无徽章**
新注册用户小白 / 还没上传任何活动 / FTP / 城市都没填 → 头像旁不挂徽章（0 个 / 整行隐藏）→ 他骑几次后系统自动算出徽章 → 第一次解锁那刻心里偷偷开心。

**故事 C — 数据驱动自动解锁**
小明在雀儿山骑了第 5 次 → 系统识别"同一座山骑过 5 次 +" → "🏆 雀儿山常客" 徽章自动解锁 → 下次他打开"我的"页 / 别人点他头像 / 都能看到新徽章 → 不需要他做任何操作。

**故事 D — 新字段自他对称**
小明自己看自己 profile / CCF 看小明 profile → badges 字段**完全一致**（同样 3 个 / 同样顺序 / 字段集相同）。本次新增字段强制对称。

### 怎么算做对了

- ✓ 5 种徽章规则按优先级算：**FTP > 山名常客 > 累计里程 > 累计爬升 > 城市本地**
- ✓ 每个用户最多返 **3 个徽章**（top 3）/ 按优先级排序
- ✓ 自他对称（GET /api/user/profile.badges === GET /api/user/{user_id}/profile.badges）
- ✓ 用户无活动 / ftp NULL / city NULL → 跳过对应徽章 / 不报错 / 返空数组 []
- ✓ 单次聚合 < 200ms（不引入 N+1 查询）
- ✓ 既有白名单 9 字段 + badges = 10 字段（追加不覆写）
- ✗ 用户能手填徽章 / 自定义徽章 → 是 bug（**永远禁止 / 破坏护城河**）
- ✗ 不同用户看到的徽章数 / 顺序不一致 → 是 bug

### 这次**不做**的事

- 前端徽章 icon / 颜色 / 排版（task-4）
- 徽章动画 / 闪烁 / 视觉特效（永不做）
- **用户手填徽章 / 自定义徽章**（永不做 / 红线）
- 历史徽章解锁日期 / 解锁通知 push（保留给未来"成就系统"Sprint）
- W/kg 徽章（需要 weight 字段 / 大量用户没填 / 数据不可靠）
- 速度俱乐部徽章（边缘 / 数据噪声大）

### 估时

1 天（含 Claude 双审 + Codex 异源审）

---

## ─────── 折叠：执行 subagent 看的技术细节 ───────

<details>
<summary>展开</summary>

### 起手必跑：现状 grep

```bash
# Activity 字段（PRD § 0.1 已实证 / 复查防 stale）
rg "distance|elevation_gain" app/activity/models.py | head -10

# 用户累计 stats 现有计算位置
rg "get_user_stats|total_distance|total_elevation" app/user/service_stats.py

# segment_efforts 频次查询 helper（山名常客需要）
rg "SegmentEffort|segment_efforts" app/segment/

# city 7 枚举（CHECK 约束实证 PRD § 0.1）
rg "CHECK.*city" app/user/models.py

# profile endpoint 返回构造
rg "_PROFILE_RESPONSE_KEYS" app/user/service_social.py
```

**事实表实证（PRD § 0.1）**：
- Activity 字段：`distance`（Float / 米）/ `elevation_gain`（Float / 米）/ ⚠️ **不是** `distance_m` / `elevation_gain_m`
- segment_efforts 表已有 user_id + segment_id 索引
- city 7 枚举：6 城 + unknown（CHECK 约束）/ 真实 6 城 = beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan
- `_PROFILE_RESPONSE_KEYS` 现有 9 字段（service_social.py:71-75）

### 新模块 `app/user/badges.py`（纯函数）

按 CLAUDE.md "纯函数规则"：不碰 DB / 不碰文件系统 / 只接收 dict 返结果。

```python
"""
徽章规则模块 - 根据真实骑行数据自动算用户身份徽章。

干啥用：
- profile endpoint 调用 / 返 top 3 徽章
- 规则全是真实数据 = 无法编造 = velo 护城河

操作注意：
- 纯函数 / 不 import service / 不查 DB
- 输入：dict（user 基本字段 + 累计统计 + 山名频次列表 + city）
- 输出：list[dict]（每个含 type / label）/ 按优先级排序 / 最多 3 个

红线：
- 永远不允许用户手填徽章 / 自定义徽章
- top 3 限制 / 视觉密度防爆炸
"""

from typing import Optional
from app.user.cities import VALID_CITY_CODES, CITY_LABELS  # 共享 6 城常量

BADGE_TYPE_FTP = "ftp"
BADGE_TYPE_DISTANCE = "distance"
BADGE_TYPE_ELEVATION = "elevation"
BADGE_TYPE_REGULAR_MOUNTAIN = "regular_mountain"
BADGE_TYPE_CITY_LOCAL = "city_local"

# 优先级（数字小=优先级高）
PRIORITY = {
    BADGE_TYPE_FTP: 1,
    BADGE_TYPE_REGULAR_MOUNTAIN: 2,
    BADGE_TYPE_DISTANCE: 3,
    BADGE_TYPE_ELEVATION: 4,
    BADGE_TYPE_CITY_LOCAL: 5,
}

# 累计里程阶梯（米 / 阈值 1000km = 1_000_000m）
DISTANCE_TIERS = [
    (10_000_000, "累计 10000km+"),
    (8_000_000, "累计 8000km"),
    (5_000_000, "累计 5000km"),
    (3_000_000, "累计 3000km"),
    (1_000_000, "累计 1000km"),
]

# 累计爬升阶梯（米）
ELEVATION_TIERS = [
    (100_000, "爬升 100000m+"),
    (50_000, "爬升 50000m"),
    (30_000, "爬升 30000m"),
    (10_000, "爬升 10000m"),
    (5_000, "爬升 5000m"),
]

REGULAR_MOUNTAIN_THRESHOLD = 5  # 同一赛段骑过 ≥ 5 次


def compute_badges(
    *,
    ftp: Optional[int],
    total_distance_m: float,
    total_elevation_m: float,
    city: Optional[str],
    top_segments: list[dict],  # [{"segment_id": int, "segment_name": str, "count": int}, ...]
) -> list[dict]:
    """计算用户徽章列表，按优先级返回最多 3 个。"""
    badges = []

    # 1. FTP 徽章
    # v0.3 加回脏数据下界 guard：ftp >= 50（与 schemas.py PUT /profile 范围 50-500 一致）
    # 历史脏数据 ftp=10 等会被过滤 / 不渲染怪 label "FTP 10W"
    if ftp is not None and ftp >= 50:
        badges.append({
            "type": BADGE_TYPE_FTP,
            "label": f"FTP {ftp}W",
            "priority": PRIORITY[BADGE_TYPE_FTP],
        })

    # 2. 山名常客徽章
    if top_segments:
        eligible = [s for s in top_segments if s["count"] >= REGULAR_MOUNTAIN_THRESHOLD]
        if eligible:
            # 稳定排序：频次降序 / segment_id 升序做 tie-breaker
            eligible.sort(key=lambda s: (-s["count"], s["segment_id"]))
            top = eligible[0]
            badges.append({
                "type": BADGE_TYPE_REGULAR_MOUNTAIN,
                "label": f"{top['segment_name']}常客",
                "priority": PRIORITY[BADGE_TYPE_REGULAR_MOUNTAIN],
            })

    # 3. 累计里程徽章（取最高阶梯）
    if total_distance_m > 0:
        for threshold, label in DISTANCE_TIERS:
            if total_distance_m >= threshold:
                badges.append({
                    "type": BADGE_TYPE_DISTANCE,
                    "label": label,
                    "priority": PRIORITY[BADGE_TYPE_DISTANCE],
                })
                break

    # 4. 累计爬升徽章
    if total_elevation_m > 0:
        for threshold, label in ELEVATION_TIERS:
            if total_elevation_m >= threshold:
                badges.append({
                    "type": BADGE_TYPE_ELEVATION,
                    "label": label,
                    "priority": PRIORITY[BADGE_TYPE_ELEVATION],
                })
                break

    # 5. 城市本地徽章（city 在 6 城枚举内 / 排除 unknown / NULL）
    if city in VALID_CITY_CODES:  # VALID_CITY_CODES = 6 城 / 不含 unknown
        badges.append({
            "type": BADGE_TYPE_CITY_LOCAL,
            "label": CITY_LABELS[city],
            "priority": PRIORITY[BADGE_TYPE_CITY_LOCAL],
        })

    # 按优先级排序 / 取 top 3
    badges.sort(key=lambda b: b["priority"])
    return badges[:3]
```

### 共享 6 城常量 `app/user/cities.py`（v0.3：task-2 起手建 / 引用 geo.py 单一真相源）

**归属（v0.3 修 / Codex Critical）**：本文件由 **task-2 起手创建并 commit** / task-3 弱依赖（city-medals 用此常量）/ 必须在 task-3 之前 merge。

**单一真相源（v0.3 修 / Codex 第二个 Critical）**：6 城真值在 `app/common/geo.py:29-36` 的 `_CITY_BOUNDS` 字典 keys / cities.py **不重复列 6 城字符串** / 从 geo.py import 生成。未来加城市只改 geo.py + Alembic CHECK 约束两处（不需改 cities.py）。

```python
"""6 城枚举常量 - 单一真相源（v0.3）。

不重复定义 6 城 / 从 geo.py._CITY_BOUNDS 派生 / 避免双真相源 drift。

badges.py / service_social.py（city-medals）共用此常量。
"""

from app.common.geo import _CITY_BOUNDS

# 6 真实城市 tuple（按 geo.py 字典 keys 插入顺序 / Python 3.7+ dict 保序）
VALID_CITY_CODES: tuple[str, ...] = tuple(_CITY_BOUNDS.keys())

# 含 unknown 兜底的全集（与 users.city / activities.city CHECK 约束一致）
ALL_CITY_CODES_WITH_UNKNOWN: tuple[str, ...] = VALID_CITY_CODES + ("unknown",)

# 中文 label 映射（这里手维护 / 因为 geo.py 是 GPS bounds 不带中文名）
# 但 VALID_CITY_CODES 是从 geo.py 派生 / 加新城时若忘了加 CITY_LABELS 会 KeyError 显式提示
CITY_LABELS: dict[str, str] = {
    "beijing": "北京",
    "shanghai": "上海",
    "hangzhou": "杭州",
    "shenzhen": "深圳",
    "chengdu": "成都",
    "taiyuan": "太原",
}

# 自检：CITY_LABELS keys 必须与 VALID_CITY_CODES 完全一致（防漏维护）
assert set(CITY_LABELS.keys()) == set(VALID_CITY_CODES), (
    f"CITY_LABELS 漏维护 / VALID_CITY_CODES={VALID_CITY_CODES} / "
    f"CITY_LABELS keys={list(CITY_LABELS.keys())}"
)
```

**测试要求**：pytest 一条 case 确保 `VALID_CITY_CODES` 与 `_CITY_BOUNDS.keys()` 完全一致 + 与 Alembic CHECK 约束 7 枚举（含 unknown）对齐。

### service 层聚合 badges 输入

```python
# app/user/service_social.py 或 service_stats.py 加 helper

from sqlalchemy import func
from app.activity.models import Activity
from app.segment.models import SegmentEffort, Segment
from app.user.badges import compute_badges


def _aggregate_badges_input(db, user_id) -> dict:
    """聚合 badges.py 需要的全部输入字段。"""
    user = db.query(User).get(user_id)

    # Activity 字段名 = distance / elevation_gain（v0.2 修 / 不是 distance_m / elevation_gain_m）
    stats = db.query(
        func.coalesce(func.sum(Activity.distance), 0),
        func.coalesce(func.sum(Activity.elevation_gain), 0),
    ).filter(
        Activity.user_id == user_id,
        Activity.status == "completed",
        Activity.duplicate_of.is_(None),  # Sprint 5 dedupe 兼容
    ).one()
    total_distance_m, total_elevation_m = stats

    # 山名 top 5 频次
    top_segments_rows = db.query(
        SegmentEffort.segment_id,
        Segment.name,
        func.count().label("cnt"),
    ).join(Segment, SegmentEffort.segment_id == Segment.id) \
     .filter(SegmentEffort.user_id == user_id) \
     .group_by(SegmentEffort.segment_id, Segment.name) \
     .order_by(func.count().desc(), SegmentEffort.segment_id.asc()) \
     .limit(5).all()

    return {
        "ftp": user.ftp,
        "total_distance_m": float(total_distance_m or 0),
        "total_elevation_m": float(total_elevation_m or 0),
        "city": user.city,
        "top_segments": [
            {"segment_id": s.segment_id, "segment_name": s.name, "count": s.cnt}
            for s in top_segments_rows
        ],
    }


def get_user_badges(db, user_id) -> list[dict]:
    inputs = _aggregate_badges_input(db, user_id)
    return compute_badges(**inputs)
```

### schemas 更新（`app/user/schemas.py`）

```python
class Badge(BaseModel):
    type: str  # ftp / distance / elevation / regular_mountain / city_local
    label: str  # "FTP 220W" / "雀儿山常客" / ...

class UserProfile(BaseModel):
    # ... 现有字段 + task-1 加的 bio
    badges: list[Badge] = []  # 默认空数组 / 永不 null

class UserProfileResponse(BaseModel):
    # ... 现有 9 字段 + task-1 加的 bio
    badges: list[Badge] = []
```

### 看他人白名单（v0.2 修 / `|=` 追加 / 不覆写）

```python
# app/user/service_social.py:71-75
# 现状 9 字段：id / nickname / avatar_url / city / bike_type /
#              total_distance_km / total_elevation_m / activity_count / current_month_summary

# task-1 已追加 bio：
_PROFILE_RESPONSE_KEYS |= {"bio"}

# task-2 追加 badges：
_PROFILE_RESPONSE_KEYS |= {"badges"}

# 最终 11 字段
# **红线**：永远用 |= 追加 / 永远不整体重写（防 v0.1 Critical 复发）
```

### endpoint 改动（`/api/user` 单数）

- GET /api/user/profile → 内部聚合 + 算 badges → 含 badges 字段
- GET /api/user/{user_id}/profile → 同上 / 自他一致

### 测试要求（最少 9 条 pytest）

1. 用户 ftp = 220 / 累计 distance 8500km → badges 含 FTP 220W + 累计 8000km
2. 用户无活动 / ftp NULL → badges = []
3. 用户骑过雀儿山 6 次 → badges 含"雀儿山常客"
4. 用户骑过雀儿山 4 次（未达 5 阈值）→ badges 不含"雀儿山常客"
5. 优先级测试：用户 FTP + 山 + 里程 + 爬升 + 城市 5 个全有 → 只返 top 3（FTP / 山 / 累计里程）
6. 自他对称：GET /api/user/profile.badges === GET /api/user/{user_id}/profile.badges
7. 山名并列频次 → segment_id 小者优先（稳定排序）
8. 性能：100 条 activities 的用户聚合 + 算 badges < 200ms
9. **白名单回归**：既有 10 字段（含 task-1 bio）+ badges = 11 字段都透出 / 不允许覆写丢字段
10. **_filter_profile_keys 防回退测试同步更新**（v0.3 加 / reviewer-integration 抓的）：测试反向构造含敏感字段输入 / 断言期望白名单 = 11 字段 / task-1/2 ship 后必须同步更新该测试的期望集合
11. **FTP 脏数据下界**（v0.3 加）：用户 ftp=10（< 50）→ badges 不含 FTP 徽章 / 用户 ftp=50 → 含
12. **cities.py 单一真相源**（v0.3 加）：assert `VALID_CITY_CODES == tuple(_CITY_BOUNDS.keys())`

### 双审顺序

1. **Claude A 忠 PRD**：5 种规则全在 / 优先级正确 / top 3 限制 / 自他对称
2. **Claude B 集成审**：N+1 查询防御 / SegmentEffort JOIN 索引 / `|=` 追加 vs 覆写
3. **Codex 异源审**：扫"compute_badges 边界（负数 / 0 / NaN / 空 list）" + "山名稳定排序" + "白名单覆写 vs 追加" + "Activity 字段名实证"

### 依赖 / 顺序

- 依赖：task-1（schema 同位字段 bio / `|=` 追加 pattern 已建立）
- **本 task 起手必须先建 `app/user/cities.py`**（v0.3 修 / Codex Critical）/ task-3 弱依赖此文件
- 阻塞：task-4（前端 profile 改造时需 badges 字段已 ship）/ task-3（city-medals 需要 cities.py）

### 部署 SOP

按 task-1 同款 5 步 SOP（含清 Redis profile cache / curl verify badges 字段）

</details>
