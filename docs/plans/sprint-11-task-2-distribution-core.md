# Sprint 11 Task-2 — 训练分布纯函数 + 分类测试

> 所属：Sprint 11（训练分布分析）/ 第 2 个 task / 算法层。
> 上游：`docs/prd/sprint-11-prd.md`、`docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md`。
> 前置门：Task 1 字段合同与 Claude 异源审已确认 Critical=0；本 task 不写 API、不查 DB、不改小程序。
> 文案门：Tim 已确认 spec §4.1 的 5 类型文案表先作为 v1 上线；实现 agent 不允许现场改写文案。

---

## ─────── 给 Tim 看 ───────

### 干啥用

把每条骑行里已经算好的 Z1-Z6 功率区间，合成一个“最近 6 周你像哪种练法”的判断器。

如果 Activity 模块是每次骑行的小账本，那这个 task 就是把 6 周账本摊开，按颜色分堆：哪些时间在打底，哪些时间在半累不累，哪些时间是真高强度。

### 用户故事

张三最近 6 周骑了很多次。以前他只知道“我骑了 16 小时”，但不知道这 16 小时到底花在哪里。这个 task 完成后，系统能把这些时间拆成“耐力 / 中强度 / 高强度”，再判断他是 Sweet Spot、Polarized、Pyramidal、Threshold，还是 Mixed。

### 怎么算做对了

- ✓ 原型口径能复现：Z2=44%、Z3-Z4=47%、Z5+=9%，三组加起来 100。
- ✓ `raw_zones` 仍保留 Z1-Z6 原始百分比，分母含 Z1。
- ✓ `groups` 分母剔除 Z1，`total_power_seconds` 分母含 Z1，两者不强行相等。
- ✓ Z4 单区占比 `>= 30%` 时先判 `threshold`，不会被 `sweet_spot` 吞掉。
- ✓ 数据不足时不输出训练建议。
- ✓ 纯函数不 import DB / FastAPI / SQLAlchemy。

### 这次不做

- 不查 `Activity` 表。
- 不新增 `/api/training/distribution`。
- 不改 `app/training/schemas.py` / `router.py`。
- 不写小程序页面。
- 不碰 `daily_training_load` / `/api/training/load`。

### 估时

0.5 天，含 TDD 和 Claude 复审。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md | sed -n '141,205p'
nl -ba docs/prd/sprint-11-prd.md | sed -n '161,218p'
nl -ba app/activity/power_zones.py | sed -n '79,106p'
nl -ba app/training/training_load.py | sed -n '1,120p'
rg --files tests | rg "training|power|ftp"
```

已验证事实：
- `power_zones` 单条活动输出含 `zone/name/min_w/max_w/seconds/percent`，[✓ grep] `app/activity/power_zones.py:97-104`。
- 单条活动 `percent` 分母是总有功率秒数，含 Z1，[✓ grep] `app/activity/power_zones.py:93-95`。
- Sprint 11 spec 写死 `groups` 分母剔除 Z1、`raw_zones` 分母含 Z1，[✓ grep] `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md:190-193`。
- 训练模块已有纯函数文件风格可参考 `app/training/training_load.py`，[✓ grep] `app/training/schemas.py:7-8` 显示训练 schema 已复用 `round_1`。

## 2. 文件改动清单

- Create `app/training/distribution.py`：纯函数模块，约 180-260 行。
- Create `tests/test_training_distribution.py`：纯单测，不用 DB fixture。
- Do not modify `app/training/service.py`、`app/training/router.py`、`app/training/schemas.py`。
- Do not modify `app/activity/*`。

## 3. 公开接口锁定

```python
def normalize_power_zones(value: list[dict] | str | None) -> list[dict]:
    """把 DB 或 SQLite 测试里的 power_zones 统一成 list[dict]。"""


def aggregate_power_zones(zone_sets: list[list[dict]]) -> dict:
    """累计 Z1-Z6 秒数、raw 百分比和三组页面分布。"""


def classify_distribution(stats: dict) -> str | None:
    """按 spec 顺序返回 threshold/sweet_spot/polarized/pyramidal/mixed。"""


def build_training_distribution_payload(stats: dict) -> dict:
    """生成 headline、解释、行动建议和一周示意安排。"""
```

返回 dict 必须包含：
- `activity_count`
- `total_power_seconds`
- `total_power_hours`
- `data_complete`
- `insufficient_power_data`
- `current_type`
- `current_label`
- `current_description`
- `target_label`
- `target_description`
- `headline`
- `explanation`
- `groups`
- `raw_zones`
- `actions`
- `week_plan`

## 4. 算法决策

固定 zone 顺序：

```python
ZONE_ORDER = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
GROUPS = [
    ("endurance", "耐力", ["Z2"], "打底时间"),
    ("tempo_threshold", "中强度", ["Z3", "Z4"], "最容易堆累"),
    ("high_intensity", "高强度", ["Z5", "Z6"], "刺激偏少"),
]
```

百分比：
- `raw_zones[].percent = round(zone_seconds / (Z1+Z2+Z3+Z4+Z5+Z6) * 100)`。
- `groups[].percent = round(group_seconds / (Z2+Z3+Z4+Z5+Z6) * 100)`。
- `total_power_seconds = Z1+Z2+Z3+Z4+Z5+Z6`。
- `sum(groups.seconds)` 不等于 `total_power_seconds`，差值是 Z1。

分类顺序：
1. `threshold`：Z4 / (Z2+Z3+Z4+Z5+Z6) `>= 30%`。
2. `sweet_spot`：(Z3+Z4) / (Z2+Z3+Z4+Z5+Z6) `>= 40%`。
3. `polarized`：Z2 `>= 70%` 且 Z5+ `>= 8%` 且 Z3-Z4 `<= 22%`。
4. `pyramidal`：Z2 > Z3-Z4 > Z5+。
5. `mixed`：其他。

数据不足：
- `activity_count < 3` 或 `total_power_seconds < 10800`，返回 `data_complete=False`。
- 本接口 `insufficient_power_data == (not data_complete)`。
- 不足时 `current_type=None`，`actions=[]`，`week_plan=[]`。

## 5. TDD 单测清单

硬门：先创建测试并确认失败，再写 `app/training/distribution.py`；禁止先写实现后补测试。

新增 `tests/test_training_distribution.py`，至少 17 个 case：

1. `test_normalize_power_zones_accepts_list`
2. `test_normalize_power_zones_accepts_json_string`
3. `test_normalize_power_zones_rejects_malformed_json_as_empty`
4. `test_aggregate_uses_group_denominator_without_z1`
5. `test_raw_zones_percent_uses_total_with_z1`
6. `test_threshold_wins_before_sweet_spot_when_z4_reaches_30_percent`
7. `test_classifies_sweet_spot`
8. `test_classifies_polarized`
9. `test_classifies_pyramidal`
10. `test_classifies_mixed`
11. `test_data_incomplete_when_activity_count_less_than_three`
12. `test_data_incomplete_when_total_power_under_three_hours`
13. `test_payload_does_not_include_min_w_or_max_w`
14. `test_week_plan_has_seven_structured_items_for_complete_data`
15. `test_missing_zone_is_treated_as_zero_seconds`
16. `test_non_numeric_seconds_is_ignored_without_crashing`
17. `test_empty_or_all_zero_input_returns_incomplete_payload`

关键测试数据：

```python
def zones(z1=0, z2=0, z3=0, z4=0, z5=0, z6=0):
    return [
        {"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": z1, "percent": 0},
        {"zone": "Z2", "name": "耐力", "min_w": 130, "max_w": 176, "seconds": z2, "percent": 0},
        {"zone": "Z3", "name": "节奏", "min_w": 177, "max_w": 211, "seconds": z3, "percent": 0},
        {"zone": "Z4", "name": "阈值", "min_w": 212, "max_w": 247, "seconds": z4, "percent": 0},
        {"zone": "Z5", "name": "VO2max", "min_w": 248, "max_w": 282, "seconds": z5, "percent": 0},
        {"zone": "Z6", "name": "无氧", "min_w": 283, "max_w": None, "seconds": z6, "percent": 0},
    ]
```

原型口径 fixture：

```python
sample = zones(z1=1000, z2=4400, z3=3000, z4=1700, z5=900, z6=0)
# groups 分母 = 10000：Z2 44%，Z3-Z4 47%，Z5+ 9%
# raw 分母 = 11000：Z1 9%，Z2 40%，Z3 27%，Z4 15%，Z5 8%，Z6 0%
```

Threshold fixture：

```python
threshold_case = zones(z1=500, z2=3500, z3=1500, z4=3000, z5=1500, z6=500)
# Z4 / (Z2-Z6) = 30%，且 Z3+Z4 = 45%，必须先返回 threshold。
```

Polarized fixture：

```python
polarized_case = zones(z1=800, z2=8200, z3=600, z4=1000, z5=900, z6=300)
# Z2 >= 70%，Z5+ >= 8%，Z3-Z4 <= 22%。
```

Pyramidal fixture：

```python
pyramidal_case = zones(z1=700, z2=6000, z3=2500, z4=500, z5=800, z6=200)
# 60 > 30 > 10。
```

Mixed fixture：

```python
mixed_case = zones(z1=500, z2=3500, z3=2500, z4=1000, z5=2500, z6=500)
# Z2 == Z3-Z4，不满足 pyramidal；中强度 < 40；Z4 < 30。
```

## 6. 验收命令

```bash
python3 -m pytest tests/test_training_distribution.py -q
python3 -c "from app.training.distribution import aggregate_power_zones, classify_distribution; print(aggregate_power_zones)"
git diff --check
```

## 7. 5 字段 issue 草稿

背景：Sprint 11 要把最近 6 周的功率区间翻译成训练结构类型；spec 已锁定两套百分比分母、threshold 30%、5 类型文案草表和数据不足规则。目标：新增 `app/training/distribution.py` + `tests/test_training_distribution.py`，只做纯函数和确定性分类。验收命令：`python3 -m pytest tests/test_training_distribution.py -q && python3 -c "from app.training.distribution import aggregate_power_zones"`。不要碰：DB、service、router、schemas、小程序、`app/activity/*`。失败处理：若发现文案草表里 4 类待确认影响实现，只保留类型和字段结构，停止上线文案给 Tim 拍板，不在代码里现场改文案。

## 8. commit message 模板

`feat(training): sprint11 task-2 distribution core`

正文：`Add pure training distribution aggregation/classification helpers and unit tests. Keep DB/API/miniprogram untouched; lock Z1 denominator, threshold, privacy-safe raw_zones, and data-incomplete behavior.`

</details>
