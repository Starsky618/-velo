# 任务 2.C.1：user.models 加 city 字段

## ✅ 完成状态（2026-04-30）

**verify-only task**：grep 实证 ORM Column + CheckConstraint + migration 全在 task-1.A.1 / task-0.6 落地。
本 task 真做的事 = **加防回退测试**（5 case）。

- commit `<本次>` / 5 测试全过真 PG / 0.10s
- column_exists / check_constraint_exists / null_allowed / six_cities_allowed / invalid_value_rejected
- 跳过 codex 异源审：纯防回退测试 / 0 业务逻辑改动 / 等价 spec §11 跳过场景

## 🎯 目标

`app/user/models.py` User 类追加 `city = Column(String(32), nullable=True)` + CheckConstraint。task 0.6 迁移已落地 DB 列，本 task 只补 ORM 声明（这一步组内串行的最先做，让 service / router 后续步骤能引用此字段）。

## ⛓ 前置依赖

- task-0.6（v5 主迁移落地 users.city 列）
- task-1.A.1（Sprint 1 已加过 User.city）—— 实际若 1.A.1 已加，**本 task 仅验证不重复**

> ⚠ Sprint 时序检查：spec §8.2 模块组 A `1.A.1` 已加 User.city Column（因为 segment 模块需要先建 common.geo + user 字段一起建）。Sprint 2 task 2.C.1 实际是**确认字段已就位 + 拓展 user 模块的相关 ORM 声明**，不重复 add_column。

## 📤 输出契约

| 字段 / 约束 | 用途 |
|---|---|
| `User.city = Column(String(32), nullable=True)` | task-2.C.2 service.update_user_city / get_user_heatmap 用 |
| CheckConstraint `ck_users_city` | DB 层值域校验 |

## 🧱 现状

- `app/user/models.py:32-93` User 类定义
- task-0.6 迁移已加 DB 列
- task-1.A.1 已加 ORM Column（grep 确认）—— 本 task 实际是占位 + 验证

## 🛠 完整代码

如 task-1.A.1 未加（顺序异常），本 task 补：

```python
# User 类追加
city = Column(String(32), nullable=True)

__table_args__ = (
    # ... 沿用现有
    CheckConstraint(
        "city IS NULL OR city IN ('beijing','shanghai','hangzhou','shenzhen','chengdu','taiyuan','unknown')",
        name='ck_users_city',
    ),
)
```

如 1.A.1 已加（默认顺序），本 task 仅 verify：

```bash
python3 -c "from app.user.models import User; assert 'city' in User.__table__.columns.keys()"
```

## ✅ 测试

```python
def test_user_city_column_exists():
    assert User.__table__.columns['city'].type.length == 32
    assert User.__table__.columns['city'].nullable is True
def test_user_city_check_constraint():
    # 尝试插入非法 city → IntegrityError
    user = User(openid="test", city="invalid_city")
    db.add(user)
    with pytest.raises(IntegrityError):
        db.commit()
def test_user_city_null_allowed():
    user = User(openid="test", city=None)
    db.add(user)
    db.commit()  # 不抛
```

## 📝 commit

```
chore(user): 任务 2.C.1 user.models city 字段验证

确认 User.city ORM Column 已正确声明（task-1.A.1 已加 / task-0.6 已迁 DB）
+ CheckConstraint 6 城 + unknown + NULL
```

## 🔍 自检三问

1. **重复风险**：1.A.1 已加 city，本 task 不要重复 add_column。  
   → 验证后跳过即可。

2. **CheckConstraint 6 城枚举**：与 segments.city 6 城枚举一致吗？  
   → 是。同一城市集合（spec §3.1.3 _CITY_BOUNDS）。

3. **NULL 允许**：spec 拍 users.city 默认 NULL（未推断时）— ORM 声明 nullable=True 一致。  
   → 是。
