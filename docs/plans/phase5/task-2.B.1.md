# 任务 2.B.1：activity.power_zones 算法（calculate_power_curve + _from_activities）

## ✅ 完成状态（2026-04-30）

- commit `661a717` / 15 测试全过 / 0.02s
- 性能 bench：100k trackpoints × 6 windows = 32ms（spec 期望 < 500ms）
- codex 异源审 Critical=0 / 1 Important（test_must_not_concatenate 假阳性 / A/B 都 100W 拼不拼都 100 → 重设计为 A 末尾高 + B 开头高，错拼会算出连续 5 个 1000W）已修

## 🎯 目标

`app/activity/power_zones.py` 追加两个新增纯函数：
- `calculate_power_curve(trackpoints, windows_sec)` 单次骑行内 6 buckets（1/5/30/60/300/1200s）滑窗最大平均功率
- `calculate_power_curve_from_activities(activities_trackpoints, windows_sec)` 跨 N 次骑行 per-window max（**禁止跨 activity 拼接 trackpoints**——破坏"5min 最佳"语义）

## ⛓ 前置依赖

无（独立 worktree，与 Sprint 2 其他模块并行）。

## 📤 输出契约（多 task 依赖）

| 函数 | 用途 | 调用方 |
|---|---|---|
| `calculate_power_curve(tps, windows_sec) -> dict[int, float]` | 单次曲线 | task-2.C.2 service / task-2.A.1 detector |
| `calculate_power_curve_from_activities(acts_tps, windows_sec) -> dict[int, float]` | 跨多次 per-window max | task-2.C.2 service.get_user_power_curve / task-2.A.1 detector baseline |

## 🧱 现状

- `app/activity/power_zones.py` 已存在（4740 字节，含 `calculate_power_zones` / `_get_zone_index`），本 task 追加两个新函数
- `Trackpoint.power = Column(Integer, nullable=True)` 单位 W，可能 NULL，spec §0.1 已查实

## 🛠 完整代码

抄 spec：

| 函数 | spec 引用 |
|---|---|
| `calculate_power_curve` | `docs/spec-v5.md §3.3.1`（行 1170-1205）—— 含 truthiness 陷阱注释（power=0 是合法值） |
| `calculate_power_curve_from_activities` | `docs/spec-v5.md §3.3.1.1`（行 1240-1295）—— 跨 activity 取 per-window max，**docstring 含警告"禁止跨 activity 拼接 trackpoints"** |

## ✅ 测试（每函数 ≥ 5 case，spec §9.1）

```python
# tests/test_power_curve.py
def test_calculate_power_curve_empty_trackpoints():
    assert calculate_power_curve([]) == {1: 0.0, 5: 0.0, 30: 0.0, 60: 0.0, 300: 0.0, 1200: 0.0}
def test_calculate_power_curve_all_none_power():
    # 所有 tp.power = None → 全 0
def test_calculate_power_curve_single_point():
    # n=1，所有 window 走 fallback 用全部数据平均
def test_calculate_power_curve_standard_200w():
    # 1Hz 600 个点全 200W → 全 buckets 接近 200
def test_calculate_power_curve_spike_1200w_1s():
    # window=1 ~1200, window=5 ~240（平均稀释）
def test_calculate_power_curve_power_zero_is_valid():
    # tp.power = 0 不被当 None（陷阱 #1）

def test_from_activities_empty_list():
    # 空 list of list → 全 0
def test_from_activities_single_activity_equiv_single_curve():
    # list of 1 等价直接调 calculate_power_curve
def test_from_activities_per_window_max_across_activities():
    # 2 个 activity 不同 5min 最佳：A=180, B=220 → 返 220
def test_from_activities_must_not_concatenate():
    # 关键：横跨两 activity 5min 滑窗不能"借"对方 trackpoint
    # 构造 A 末尾 5min=100 / B 开头 5min=100 / 拼接后会出现 200 的虚假窗口
    # 期望：返 100（per-activity 独立算后取 max），不是 200
def test_from_activities_each_inner_list_independent(): ...
```

```bash
python3 -m pytest tests/test_power_curve.py -x -v
```

## 📝 commit

```
feat(activity): 任务 2.B.1 power_curve 算法（含跨 activity 安全）

新增 app/activity/power_zones.py：
- calculate_power_curve(tps, windows_sec) 单次骑行 6 buckets 滑窗 max
- calculate_power_curve_from_activities(acts_tps, windows_sec) 跨多次 per-window max
  - docstring 含警告：禁止跨 activity 拼接 trackpoints（破坏"5min 最佳"语义）
  - 算法：每 activity 独立 calculate_power_curve，再 per-window 取 max

性能：100k trackpoints O(n) per window × 6 windows = 600k ops < 500ms
```

## 🔍 自检三问

1. **跨 activity 边界**：`calculate_power_curve` docstring 是否明写"不允许跨 activity 拼接 trackpoints"警告？  
   → 是。第二轮已加。subagent 抄时确认警告段在。

2. **truthiness 陷阱**：`tp.power if tp.power is not None else 0` —— 不是 `tp.power or 0`（后者会把 0 当 None 兜底，吞掉合法 0 值）。  
   → 是。spec 已加注释。

3. **性能**：100k trackpoints 跑 6 windows 用 prefix sum O(n)，应 < 500ms。bench 验证：
   ```python
   tps = [Trackpoint(power=200) for _ in range(100_000)]
   import time; t = time.time(); calculate_power_curve(tps); print(time.time() - t)
   ```
   → 期望 < 0.5s。
