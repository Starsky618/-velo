# 任务 1.A.1：segment 算法纯函数 + 模型字段

## 🎯 目标

实现 v5 segment 模块四个新增纯函数 + 同步模型类含 city/difficulty/max_gradient 字段（task 0.6 迁移已落地，这里只补 ORM 类的 Column 声明 + 算法实现）。

## ⛓ 前置依赖

- task-0.1（datetime tz-aware）
- task-0.6（v5 主迁移完成，DB 列已存在）
- task-0.8（app/queue.py，部分函数用到 Redis）

## 📤 输出契约（Sprint 1+ 多 task 依赖）

| 函数 / 字段 | 位置 | 用途 |
|---|---|---|
| `app/common/__init__.py` | 新建空文件 | 标识 common 是包 |
| `app/common/geo.py` 新建 | `infer_city_from_coords(lat, lon) -> str` | segment / user 两模块共享 |
| `app/segment/service.py` | `_haversine_distance(lat1, lon1, lat2, lon2) -> float`（米）| from-activity 算 distance |
| `app/segment/service.py` | `calculate_max_gradient(trackpoints) -> float \| None` | 100m 滑窗最大坡度 % |
| `app/segment/service.py` | `calculate_difficulty(distance, elev_gain, max_gradient) -> str` | 4 档枚举 |
| Segment 模型加 3 字段 | `app/segment/models.py` | difficulty / max_gradient / city Column 声明 |
| User 模型加 1 字段 | `app/user/models.py` | city Column 声明（task-2.C.1 也会用） |

## 🧱 现状（grep 已验证）

- `app/common/` 目录**不存在**（v5 新建）
- `app/segment/service.py` 现有 `create_segment / get_segment_list / get_segment_detail / get_leaderboard / get_user_efforts / get_activity_segments / delete_segment / get_effort_rank` —— v5 新增 4 个函数追加在文件末尾
- `app/segment/models.py` Segment 类 line 40-69，无 difficulty/max_gradient/city 字段

## 🛠 完整代码（主 agent 已查 spec，subagent 直接抄即可）

### 1. 新建 `app/common/__init__.py` 空文件

```python
"""通用工具层：无业务逻辑，可被任何模块依赖（common 在所有业务模块下方）。"""
```

### 2. 新建 `app/common/geo.py`

抄 `docs/spec-v5.md §3.1.3`（行 815-848）—— 含 `_CITY_BOUNDS` 6 城 + `infer_city_from_coords(lat, lon)`。

### 3. `app/segment/service.py` 末尾追加

抄 `docs/spec-v5.md §3.1.1`（行 696-781）`calculate_max_gradient` + `_haversine_distance`，`§3.1.2`（行 783-813）`calculate_difficulty`。

### 4. `app/segment/models.py` Segment 类追加 Column

```python
# Segment 类 line 60 后追加
difficulty = Column(
    String(16),
    server_default='medium',
    nullable=False,
)
max_gradient = Column(Float, nullable=True)
city = Column(
    String(32),
    server_default='unknown',
    nullable=False,
)

__table_args__ = (
    CheckConstraint(
        "difficulty IN ('easy','medium','hard','extreme')",
        name='ck_segments_difficulty',
    ),
    CheckConstraint(
        "city IN ('beijing','shanghai','hangzhou','shenzhen','chengdu','taiyuan','unknown')",
        name='ck_segments_city',
    ),
    Index('idx_segments_city_difficulty', 'city', 'difficulty'),
    # 沿用现有 __table_args__ 其他项
)
```

### 5. `app/user/models.py` User 类追加 Column

```python
city = Column(String(32), nullable=True)
# 加 CheckConstraint 进 __table_args__：
# CheckConstraint("city IS NULL OR city IN (6城+'unknown')", name='ck_users_city')
```

## ✅ 测试

### 单元测试（每函数 ≥ 5 case，spec §9.1）

```python
# tests/test_segment_algorithms.py 新增
def test_calculate_max_gradient_empty(): ...
def test_calculate_max_gradient_single_point(): ...
def test_calculate_max_gradient_flat(): ...
def test_calculate_max_gradient_standard_5pct(): ...
def test_calculate_max_gradient_extreme_20pct(): ...

def test_calculate_difficulty_4_tiers_boundary(): ...
def test_calculate_difficulty_steep_short(): ...
def test_calculate_difficulty_long_flat(): ...

def test_infer_city_6_cities_typical_points(): ...
def test_infer_city_none_input_returns_unknown(): ...
def test_infer_city_overseas_returns_unknown(): ...
def test_infer_city_boundary_point(): ...

def test_haversine_same_point_zero(): ...
def test_haversine_1km_straight(): ...
def test_haversine_cross_equator(): ...
```

```bash
python3 -m pytest tests/test_segment_algorithms.py -x -v
```

预期：全 passed。

### 模型字段加载

```bash
python3 -c "from app.segment.models import Segment; print(Segment.__table__.columns.keys())"
# 期望含 difficulty / max_gradient / city
python3 -c "from app.user.models import User; print(User.__table__.columns.keys())"
# 期望含 city
```

## 📝 commit

```
feat(segment): 任务 1.A.1 segment 算法纯函数 + 模型字段

新增：
- app/common/__init__.py + app/common/geo.py（infer_city_from_coords）
- app/segment/service.py 追加 _haversine_distance / calculate_max_gradient / calculate_difficulty
- app/segment/models.py Segment 加 difficulty / max_gradient / city Column + CheckConstraint
- app/user/models.py User 加 city Column + CheckConstraint

测试：tests/test_segment_algorithms.py 4 函数 × ≥5 case 全 passed
```

## 🔍 自检三问

1. **陷阱核查**：`calculate_max_gradient` 双指针 j 单调推进——n=2 极小输入 / n=百万极大输入 都不爆吗？  
   → 100m 滑窗算法 O(n)，prefix sum 一次过，不是 O(n²)。空 / 单点边界已加守卫。

2. **跨模块依赖确认**：`app/common/geo.py` 不依赖任何业务模块（segment / user / activity）吗？  
   → 是。仅依赖 stdlib + 6 城常量字典。验证 grep `from app\.` /Users/macbookair/Desktop/velo/app/common/geo.py 应 0 hits。

3. **模型字段同步**：models.py 改完后 `alembic check` 显示无 schema 偏移吗？  
   → task 0.6 已迁这 4 字段，本 task 仅补 ORM Column 声明，alembic check 应 clean。
