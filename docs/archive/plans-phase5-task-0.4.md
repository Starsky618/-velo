# 任务 0.4：SQLAlchemy legacy `.get()` 替换

## 🎯 目标

把测试里残留的 `Session.query(Model).get(id)` 老式语法（SQLAlchemy 1.x 风格，2.0 废弃）改为 `db.get(Model, id)` 新风格。

## ⛓ 前置依赖

无。可与其他 Sprint 0 任务并行。

## 📤 输出契约

| 产出 | 用途 |
|------|------|
| `db.get(Model, id)` 取代 `db.query(Model).get(id)` | 消除 SQLAlchemy 2.0 LegacyAPIWarning |

## 🧱 现状（grep 已验证）

`tests/test_notification.py`：

| 行 | 用法 |
|----|------|
| 192 | `db.query(SegmentEffort).get(eff2_id)` |
| 213 | `db.query(SegmentEffort).get(eff_id)` |
| 232 | `db.query(SegmentEffort).get(eff_id)` |
| 250 | `db.query(SegmentEffort).get(eff_id)` |
| 277 | `db.query(SegmentEffort).get(eff_id)` |

合计 5 处。

> 检查其他文件确认无遗漏：`grep -rn "\.query(.*)\.get(" app/ tests/`

## 🛠 完整代码

`tests/test_notification.py`：

```diff
- effort = db.query(SegmentEffort).get(eff2_id)
+ effort = db.get(SegmentEffort, eff2_id)
```

5 处全替换。其他文件若 grep 出来同样改。

## ✅ 测试

```bash
python3 -m pytest tests/ -W error::DeprecationWarning -W error::sqlalchemy.exc.LegacyAPIWarning -x -q
```

预期：全 passed，无 warning 触发。

## 📝 commit

```
chore(tests): 任务 0.4 SQLAlchemy legacy .get() → db.get()

5 处 db.query(SegmentEffort).get(id) → db.get(SegmentEffort, id)
消除 SQLAlchemy 2.0 LegacyAPIWarning
```

## 🔍 自检三问

1. **遗漏检查**：除了 test_notification.py，其他文件是否也有？  
   → grep 全项目 `\.query\(.*\)\.get\(`，列出所有命中位置都改。

2. **行为一致**：`db.get(Model, id)` 与 `db.query(Model).get(id)` 行为完全等价吗？  
   → 是。都是 PK 查询，identity map 命中行为相同；区别仅在 API 风格 + 类型提示。

3. **下游波及**：测试 fixture 没改，会不会影响断言？  
   → 不影响。返回类型一致（Model 实例 or None）。
