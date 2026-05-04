# 任务 pre-3.B：segment/service.py 拆分（红灯文件清理 / 元层 blocker）

## 📌 30 秒看懂（给 Tim）

`app/segment/service.py` 现在 **793 行红灯**。admin H5（task-3.B.1 / 3.A.6 / 3.B.2）实施期会再加 segment 调用 → 不拆这个文件，800 + 行越来越烂。

**这次任务**：把这 793 行**按职责切成 3 个文件**，对外**完全透明**——所有调用方代码（router / admin / notification / 测试 / 脚本）**一行不用改**。

来源：brainstorming v2 拍板执行顺序 + memory `feedback_project_health_dashboard_gap.md` 优先级 2。

---

## 🎯 目标

| 维度 | 要求 |
|---|---|
| **拆分** | 793 行 → 3 文件（含原 service.py） |
| **对外契约** | 100% 不变（5 个调用方 import 路径全部继续工作） |
| **行为** | 100% 不变（pytest 全部继续绿） |
| **行数** | 拆完后每个新文件 < 300 行（service.py 主入口可以更小） |

## 📐 拆分方案（推荐 / codex 可微调）

| 新文件 | 行数估 | 函数列表 | 说明 |
|---|---|---|---|
| `app/segment/service_create.py` | ~250 行 | `create_segment` (113 行) / `create_segment_from_activity` (113 行) | 创建赛段相关 |
| `app/segment/service_query.py` | ~340 行 ⚠️ 接受黄灯 | `get_segment_list` (90) / `get_segment_detail` (67) / `get_leaderboard` (68) / `get_user_efforts` (49) / `get_activity_segments` (68) | 查询相关 |
| `app/segment/service.py` 保留 | ~200 行 | `delete_segment` (22) / `get_effort_rank` (29) / `get_my_effort_with_compare` (83) + 转导出 | 主入口 + 其他 |

**接受 service_query.py 340 行黄灯**（轻微 >300）的理由：
- 替代方案是再拆出 `service_leaderboard.py` → 模块文件数 11 → 14（红灯阈值 >12）
- 单文件 340 行黄灯 vs 模块文件数红灯 = 选前者更轻量
- query 函数都共享相同 imports + JOIN 模式（一起读更易维护）

如 codex 实施时发现更优拆法且不破坏对外契约 + 不超模块文件数红灯，可微调（汇报 Claude 审核同意后再做，不要自作主张）。

## 🔌 对外契约（必须 100% 不变）

### 5 个调用方（grep 已实证 2026-05-05）

| 调用方 | 行 | 当前 import |
|---|---|---|
| `app/notification/service.py` | :26 | `from app.segment.service import get_effort_rank` |
| `app/admin/router.py` | :10 | `from app.segment import service as segment_service` |
| `app/segment/router.py` | 多处 | `from app.segment import schemas, service` |
| `tests/test_segment_concurrency.py` | :22 | `from app.segment.service import create_segment_from_activity, get_my_effort_with_compare` |
| `tests/test_segment_service_v5.py` | :14 | `from app.segment import service` |
| `scripts/backfill_phase5.py` | :35 | `from app.segment.service import calculate_difficulty, calculate_max_gradient` |

**全部必须继续工作**——`service.py` 通过转导出实现：

```python
# app/segment/service.py 顶部
# v5 task-pre-3.B：service.py 793 行红灯 → 拆 3 文件，对外契约不变
# 调用方按 `from app.segment.service import xxx` 继续工作，不必感知文件分拆细节

from app.segment.service_create import (  # noqa: F401 — 转导出
    create_segment,
    create_segment_from_activity,
)
from app.segment.service_query import (  # noqa: F401 — 转导出
    get_segment_list,
    get_segment_detail,
    get_leaderboard,
    get_user_efforts,
    get_activity_segments,
)

# 已有的 algorithms.py 转导出（保留不动）
from app.segment.algorithms import (  # noqa: F401 — 转导出
    _haversine_distance,
    calculate_difficulty,
    calculate_max_gradient,
)

# 本文件保留的函数（其他业务调用集中度低 / 暂不再拆）
def delete_segment(...): ...
def get_effort_rank(...): ...
def get_my_effort_with_compare(...): ...
```

## 📥 输入 / 📤 输出

**输入**（codex 必须读完整）：
- `app/segment/service.py`（793 行 / 待拆）
- 5 个调用方文件（确认 import 行号 + 验证拆分后仍能 import）

**输出**：
- ✏️ `app/segment/service.py`（重写 / ~200 行 / 保留 3 函数 + 转导出 + docstring）
- ➕ `app/segment/service_create.py`（新建 / ~250 行）
- ➕ `app/segment/service_query.py`（新建 / ~340 行）

## 🚫 禁止动的边界（hard rules）

| 禁止 | 原因 |
|---|---|
| 改任何函数签名 / 参数 / 返回值 | 调用方依赖现有契约 |
| 改函数行为 / 业务逻辑（哪怕看起来"应该重构"） | 本次仅是物理切分，不是逻辑优化 |
| 改 docstring 内容（保留原文移到新文件） | 文档完整性 |
| 改 5 个调用方文件中任一行 | 对外契约不变 |
| 删 algorithms.py 转导出（service.py 顶部那 5 行）| `scripts/backfill_phase5.py` 依赖 |
| 改 segment/__init__.py（除非必须） | 只在出现循环 import 等问题时才动 |
| 增加新函数 / 删除老函数 | 本次纯重构 |

## ✅ 验证步骤（codex 必跑 / Claude 审）

### 1. import 兼容性

```bash
python -c "from app.segment.service import create_segment, get_segment_list, get_segment_detail, get_leaderboard, get_user_efforts, get_activity_segments, get_effort_rank, get_my_effort_with_compare, delete_segment, create_segment_from_activity, calculate_difficulty, calculate_max_gradient"
```
期望：无 ImportError。

### 2. pytest 全绿

```bash
cd /Users/macbookair/Desktop/velo
source .venv/bin/activate
pytest tests/test_segment_*.py tests/test_admin*.py tests/test_notification*.py -v
```
期望：所有 segment / admin / notification 相关测试 100% 通过。任何一条 fail = 拆分破坏行为，必须修复。

### 3. 行数验证

```bash
wc -l app/segment/service.py app/segment/service_create.py app/segment/service_query.py
```
期望：
- `service.py` < 250 行
- `service_create.py` < 300 行
- `service_query.py` < 400 行（接受黄灯）

### 4. 模块文件数验证

```bash
ls app/segment/*.py | wc -l
```
期望：≤ 13（黄灯但未红灯）。

## 🔍 实施步骤建议

1. **完整读** `app/segment/service.py`（793 行 / 不要跳读）
2. **完整读** 5 个调用方相关 import 行（grep 已给行号）
3. **创建** `service_create.py`：
   - 复制 `create_segment`（含 imports）
   - 复制 `create_segment_from_activity`（含 imports）
   - **去重 imports**（两函数共享部分合并）
   - 保留 `# ====================` 分割注释 + 模块顶部 docstring
4. **创建** `service_query.py`：
   - 复制 5 个 query 函数（含 imports）
   - 去重 imports
   - 保留分割注释
5. **重写** `service.py`：
   - 删除已搬走的 6 个函数 + 它们的 imports
   - 加 `from app.segment.service_create import ...` 转导出
   - 加 `from app.segment.service_query import ...` 转导出
   - 保留 `delete_segment` / `get_effort_rank` / `get_my_effort_with_compare`
   - 保留 algorithms 转导出（不删）
   - 更新顶部 docstring（标注拆分历史）
6. **运行** 验证步骤 1-4
7. **报告**（不要直接 commit）—— Claude 多轮审后才 commit

## 📝 commit message（codex 准备但 Claude 多轮审通过后再 commit）

```
refactor(segment): 任务 pre-3.B service.py 拆分（793 行 → 3 文件）

- service_create.py：create_segment + create_segment_from_activity（~250 行）
- service_query.py：list/detail/leaderboard/user_efforts/activity_segments（~340 行）
- service.py 保留：delete + get_effort_rank + get_my_effort_with_compare + 转导出（~200 行）

对外契约 100% 不变：5 个调用方（router/admin/notification/tests/scripts）零修改。
行为 100% 不变：pytest segment/admin/notification 全绿。

来源：memory feedback_project_health_dashboard_gap.md 优先级 2 + brainstorming v2 拍板执行顺序。
admin H5 实施前先清红灯，避免 segment 模块进一步腐化。
```

## 🔍 自检三问

1. **为什么不顺手优化代码（如 N+1 查询 TODO）？**
   → 本次是**纯物理重构**。优化逻辑会引入行为风险，超出"拆分不改行为"的边界。N+1 优化作为单独 task 处理（已记 TODO 在 service.py 第 428 行 / 第 489 行）。

2. **为什么 service.py 主入口保留 3 个函数？为什么不全部移走？**
   → `delete_segment` / `get_effort_rank` / `get_my_effort_with_compare` 三者业务集中度低（删除 / 共享 / v5 新加 compare），各自独立，不属于 create 也不属于 query。集中放主入口避免再多一个文件。如未来某类增长（如 compare 类多了）再单独拆。

3. **如果 pytest 失败怎么办？**
   → codex **必须修复至全绿**才能交付。修复时优先检查：
   - import 链是否正确（顶部 / 函数内）
   - imports 转导出是否漏写某函数
   - 函数体是否完整复制（特别是注释 + docstring）
   - 模块顶部 docstring 是否影响了其他文件 import 行为
