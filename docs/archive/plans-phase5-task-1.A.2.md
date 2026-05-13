# 任务 1.A.2：segment service 扩展（搜索 + 即时反馈 + from-activity）

## 🎯 目标

扩展 `app/segment/service.py`：
- `get_segment_list` 加 search / city / difficulty 参数（**保留现有 tuple + entries 契约**）
- 新增 `get_my_effort_with_compare` 即时反馈
- 新增 `create_segment_from_activity` admin from-activity（含 advisory lock）

## ⛓ 前置依赖

task-1.A.1（算法函数 + 字段已落地）。

## 📤 输出契约

| 函数 | 用途 | 谁调用 |
|---|---|---|
| `get_segment_list(..., search, city, difficulty)` 扩展 | 5.B.3 搜索 + 5.B.1 筛选 | router.py（task-1.A.3）|
| `get_my_effort_with_compare(db, segment_id, user_id) -> dict` | 5.C.1 即时反馈 | router.py（task-1.A.3）|
| `create_segment_from_activity(db, activity_id, name, start_index, end_index, ...) -> Segment` | 5.D.4 from-activity | admin/router.py（task-3.A.5）|
| 新异常 `SegmentOverlapError` / `InvalidSegmentRangeError` | from-activity 错误细化 | admin router catch 翻 4xx |

## 🧱 现状

- `app/segment/service.py:152-228` `get_segment_list` 现有签名 + 实现（已 grep 验证）
- 新增三个函数追加在文件末尾，不改现有函数（除 get_segment_list 扩展）

## 🛠 完整代码

主体抄 spec：

| 函数 | spec 引用 |
|---|---|
| `get_segment_list` 扩展 | `docs/spec-v5.md §3.1.4`（行 850-940）—— **保留 tuple + entries_count outerjoin + radius=50000 default**（第二轮双审 B1-B1/B1-B2 已修） |
| `get_my_effort_with_compare` | `docs/spec-v5.md §3.2.1`（行 1086-1166）—— **必须 join Activity 按 started_at 排序**（codex E1 I27 + R3 时序一致性） |
| `create_segment_from_activity` | `docs/spec-v5.md §3.1.5`（行 1000-1140）—— **入函数立即 `pg_advisory_xact_lock(hashtext('segment-create-from-activity'))`** + **重复检测用 ST_HausdorffDistance < 0.0005**（不用 ST_Intersection + ST_Length） |

### 新异常类（追加 `app/segment/exceptions.py`）

```python
class SegmentOverlapError(Exception):
    """from-activity 重复检测命中（Hausdorff 阈值）。"""
    pass


class InvalidSegmentRangeError(Exception):
    """from-activity 起止索引非法 / 子序列点数不足 / 太短。"""
    pass
```

将 spec 抄入 service.py 时，把 `raise ValueError(...)` 替换为对应自定义异常（语义更准）。

## ✅ 测试

### 单元（mock DB）

```python
# tests/test_segment_service_v5.py
def test_get_segment_list_signature_compatible(): 
    # 沿用现有调用 service.get_segment_list(db, page, page_size, near_lat, near_lon)
    # 应仍返 tuple[list, int]，每条 dict 含 entries 字段
def test_get_segment_list_search_filter(): ...
def test_get_segment_list_city_filter(): ...
def test_get_my_effort_with_compare_first_attempt(): ...  # is_first_attempt=True
def test_get_my_effort_with_compare_pr_attempt(): ...
def test_get_my_effort_with_compare_orders_by_activity_started_at(): 
    # 关键：补传 started_at 顺序乱的两条 effort（先骑后传 vs 先传后骑）
    # 验证按 Activity.started_at 排序而非 SegmentEffort.created_at
def test_create_segment_from_activity_basic(): ...
def test_create_segment_from_activity_too_short_raises(): ...
def test_create_segment_from_activity_overlap_raises(): ...
def test_create_segment_from_activity_invalid_range_raises(): ...
```

### 集成（真 PG + advisory lock）

```python
# tests/test_segment_concurrency.py
def test_from_activity_advisory_lock_serializes_concurrent_creates():
    # 启 2 个线程同时调 create_segment_from_activity 同一段轨迹
    # 期望：1 个成功，另 1 个 SegmentOverlapError
```

```bash
python3 -m pytest tests/test_segment_service_v5.py tests/test_segment_concurrency.py -x -v
```

## 📝 commit

```
feat(segment): 任务 1.A.2 service 扩展（搜索 + 即时反馈 + from-activity）

- get_segment_list 加 search/city/difficulty 参数（保留 tuple+entries 契约）
- 新增 get_my_effort_with_compare（join Activity 按 started_at 排序）
- 新增 create_segment_from_activity（advisory lock 串行 + ST_HausdorffDistance 重复检测）
- 新建 app/segment/exceptions.py：SegmentOverlapError / InvalidSegmentRangeError
```

## 🔍 自检三问

1. **现有契约保留**：`get_segment_list` 改完后，现有 router.py:123 `items, total = service.get_segment_list(...)` 解构仍正确吗？entries 字段还在吗？  
   → 是。返回 `tuple[list[dict], int]` + 每 dict 含 entries label。**禁止改 → dict**。

2. **advisory lock 时序**：`pg_advisory_xact_lock` 进函数立即取，在重复检测 / db.add / db.commit 之前——并发场景下两个 admin 同时调能保证只有一个成功吗？  
   → advisory lock 串行化整个事务，第二个等第一个 commit 后再进，重复检测会命中已建赛段抛 SegmentOverlapError。

3. **时序基准对**：`get_my_effort_with_compare` join Activity 后，`pr_elapsed_time` 子查询是 MIN(elapsed_time) 不需要 join——确认 PR 是历史最佳与时序无关吗？  
   → 是。PR 只比 elapsed_time 数值，谁先谁后无关。docstring 已明写。
