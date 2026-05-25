# Sprint 11 task-6：训练结构区间分布支持"排除滑行 0W"

> **本文件性质**：给执行 agent（Codex）的开发执行手册。目标、标准、界限、接口、输入输出全部写死，照着做即可。
>
> **作者**：Claude（架构 + 现状 grep 实证）。**版本** v0.1 / 2026-05-25。
>
> **上游**：Sprint 11 训练分布（`docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md` 已 ship）。本 task 是其后续小补丁。
>
> **触发**：Tim 真机看到训练结构页 Z1 占 79%（≈5.4h），其中大量是下坡滑行/等灯/停顿的 0W 时间被灌进恢复区，让区间比例失真。

---

## 派工 5 字段速览

1. **背景**：训练结构页（`/api/training/distribution`）的原始区间分布里，Z1（恢复区）被"骑行中不蹬踏"的 0W 时间灌水，导致 Z1 占比虚高、区间比例参考性下降。
2. **目标**：训练结构页和单次活动详情页都默认按真实蹬踏时间展示功率区间，不再给用户选择是否包含 0W 的开关。两处都只改展示口径，别动其它功率指标。
3. **验收命令**：见 §7（pytest 新增测试 + 现有训练分布/负荷套件回归 + curl 验证默认不计 0W）。
4. **不要碰**：见 §4 红线清单（分类判断 / groups / 文案 / power_curve / FTP / TSS / power_zones list 结构 / 核心表）。
5. **失败处理**：任何一步发现现状与 §0 事实表不符 → **停下来报告，不要脑补继续**。历史数据 backfill（§6）单独跑、单独验证，不和代码改动混在一个 commit。

---

## §0 代码事实表（Claude 已 grep 实证 / 写代码前再各核一遍）

| 事实 | 证据 | 用途 |
|---|---|---|
| 功率区间唯一计算函数 | `app/activity/power_zones.py:31` `calculate_power_zones(trackpoints, ftp)` | 改这一个函数 = 3 入口全覆盖 |
| 0W 现在的处理：只跳 None，0 照算 | `power_zones.py:60`（`if prev_tp["power"] is None ...`）| 0W 进了 Z1，需单独统计 |
| 0W 必落 Z1 | `power_zones.py:115`（`ratio = power_w/ftp`）+ `:126`（`else: return 0`）| 排除 0W 只影响 Z1，别处不变 |
| 3 个产生入口都调同一函数 | GPX `gpx_parser.py:175` / FIT `fit_parser.py:147` / Strava `strava_adapter.py:206` | 改 `calculate_power_zones` 即三入口自动生效 |
| backfill 也调同一函数 | `backfill_ftp.py:113` | FTP 重算路径自动带新字段 |
| 存储列 | `app/activity/models.py:162` `power_zones = Column(JSONB)` | 存 6 个 zone 的 list |
| trackpoint 功率字段 | `app/activity/models.py:239` `power = Column(Integer, nullable=True)` | backfill 数 0W 用 |
| worker 写入点 | `app/activity/worker.py:473` `activity.power_zones = result.power_zones` | ParseResult 透传，无需改 |
| 训练分布聚合 | `app/training/distribution.py:174` `aggregate_power_zones` / `:222` `classify_distribution` | 分类分母 `classification_seconds` 本就剔除 Z1（`:185`），**排除 0W 不影响分类** |
| 训练分布响应 schema | `app/training/schemas.py:68` `TrainingDistributionZone`（`extra="forbid"`，仅 zone/name/seconds/percent）| raw_zones 输出不带 zero_seconds，扣减在聚合层完成 |
| endpoint | `app/training/router.py:29` `GET /api/training/distribution` | `exclude_zero` 默认 true；旧调用仍可显式传 false 兼容 |

---

## §1 需求（做到什么样）

用户在训练结构页看到的功率区间默认就是"真实蹬踏时间"。

- **默认**：Z1 只统计真实蹬踏的低强度时间（扣掉 0W），`total_power_seconds` 同步扣，所有区间百分比按新分母重算。Z2-Z6 的秒数不变，但因为分母变小，它们的百分比会相应变大。
- **不再给用户开关**：产品规则从"两套口径让用户选"收成"一套默认口径"，避免用户看到两个结果反而不知道该信哪个。
- **兼容旧调用**：后端仍保留 `exclude_zero=false` query 通道，便于测试和旧客户端过渡；小程序不暴露这个入口。
- **判定 0W 的口径**：精确 `power == 0`（v1）。理由：功率计停踩主流记 0，先做最简最确定的；若未来发现部分功率计记 1-3W 的滑行漏网，再讨论改成 `< 阈值`。实现处留一行注释标这个扩展点。

---

## §2 设计方案（4 处改动 / 一步到位）

### 改动 1：`calculate_power_zones` 多记一个 `zero_seconds`（power_zones.py）

遍历相邻点累计区间秒数时，**同一套 dt 逻辑里**额外累计 `power == 0` 的 dt（口径必须和 Z1.seconds 完全一致，见 §5 陷阱 1）。把结果放进 **Z1 那个 zone dict** 里：

```python
# Z1 dict 形如：
{"zone": "Z1", "name": "恢复", "min_w": 0, "max_w": 129, "seconds": 19280, "percent": 79, "zero_seconds": 15000}
```

- `seconds` 仍是含 0W 的 Z1 总秒数（不动，保持向后兼容）。
- `zero_seconds` 是其中 power==0 的部分（新增 / 仅 Z1 dict 带此字段）。
- power_zones 仍是 6 元素的 list，**结构不变**（只是 Z1 dict 多一个 key）。

### 改动 2：`aggregate_power_zones` 接收 exclude 开关（distribution.py）

聚合多条活动时，累计一个 `total_zero_seconds`（各活动 Z1 dict 的 `zero_seconds` 之和，缺失按 0）。`exclude_zero` 默认 true；当 `exclude_zero=True`：

- `Z1.seconds_effective = Z1.seconds - total_zero_seconds`（夹 0 保护，不为负）
- `total_power_seconds_effective = total_power_seconds - total_zero_seconds`
- `raw_zones[].percent` 用新分母 `total_power_seconds_effective` 重算（含 Z1 用扣减后的值）
- `total_power_hours` 用扣减后的值
- **`classification_seconds`（Z2-Z6）不变 / `groups` 不变 / 分类不变 / 文案不变**

### 改动 3：endpoint + service 默认不计 0W（router.py / distribution_service.py）

- `router.py`：`GET /api/training/distribution` 保留 `exclude_zero` query，但默认 `Query(True)`
- `distribution_service.get_training_distribution_response` 保留 `exclude_zero` 参数，但默认 `True`，透传给 `aggregate_power_zones`

### 改动 4：前端固定真实蹬踏口径（miniprogram/pages/training-distribution/）

- 页面不再展示 switch/toggle
- 不读写 `wx.setStorageSync`，不保留 `excludeZero` 状态
- 请求固定带 `exclude_zero: true`，重渲染 raw_zones

---

## §3 接口与输入输出

**请求**：`GET /api/training/distribution?range=6w&exclude_zero=true`
- `exclude_zero`：bool，默认 true。旧客户端可显式传 false 得到含 0W 的历史口径，但小程序不再暴露这个选择。

**响应**：字段结构与现状**完全一致**（`TrainingDistributionResponse`），不新增字段。
- `exclude_zero=true` 时，受影响字段：`raw_zones[].seconds/percent`（仅 Z1 的 seconds 变 + 全体 percent 因分母变而变）、`total_power_seconds`、`total_power_hours`。
- **不受影响字段**：`groups`、`current_type`、`current_label/description`、`headline`、`explanation`、`actions`、`week_plan`、`activity_count`、`data_complete`、`insufficient_power_data`。

> 注意：`data_complete` 的门槛（activity_count≥2 且 total_power_seconds≥10800）**仍用含 0W 的原始 total 判定**——排除 0W 是展示口径，不改"数据够不够"的判定，避免开关一开就把人踢进"数据不足"。这条要写进测试。

---

## §4 边界红线（不要碰）

- ❌ 不动 `classification_seconds` / `classify_distribution` / `groups` —— 分类分母本就剔除 Z1，0W 与它无关
- ❌ 不动五类文案 `_TYPE_COPY` / `_INSUFFICIENT_COPY`
- ❌ 不动 `calculate_power_curve` / `calculate_power_curve_from_activities` —— 功率曲线排 0W 会拼出虚假连续窗口（`power_zones.py:168` 已警告同类错误）
- ❌ 不动 FTP 估算 / TSS / NP / PMC（Sprint 9/10）
- ❌ 不把 power_zones 从 list 改成 dict（破坏 detector / activity detail / 历史数据所有消费方）
- ❌ 不在 `TrainingDistributionZone` schema 加 `zero_seconds`（聚合层扣减完就丢，不进 API 响应）
- ❌ 不动核心表结构（`activities` 不加列，`zero_seconds` 进 JSONB 内部）
- ✅ 活动详情页本轮追加：默认展示不含 0W 的 Z1-Z6 百分比；只在小程序展示层扣 `zero_seconds`，不改 `/api/activities/{id}` 返回结构、不改 DB 原始 `power_zones`

---

## §5 关键陷阱

1. **口径一致（最重要）**：`zero_seconds` 必须和 Z1.seconds 用**同一套 dt 累计逻辑**算（相邻点 dt 归前一点功率）。若 backfill 另写一套数 0W 的逻辑，口径一偏 → `Z1.seconds - zero_seconds` 可能算出负数或残留。**backfill 直接复用 `calculate_power_zones` 重算整条 power_zones**（见 §6），不要手写第二套 0W 统计。
2. **truthiness 陷阱**（CLAUDE.md 陷阱 #1）：判 0W 用 `power == 0`，判缺失用 `power is None`，**绝不能 `if not power`**（会把 None 和 0 混为一谈）。
3. **夹 0 保护**：`Z1.seconds - zero_seconds` 理论上 ≥0，但脏数据防御仍要 `max(0, ...)`。
4. **百分比四舍五入**：扣减后重算 percent 仍用现有 `_percent` helper（`distribution.py:292`），不另写。

---

## §6 历史数据 backfill（单独 commit / 单独跑 / 单独验证）

历史活动的 `power_zones` 没有 `zero_seconds`，不 backfill 的话最近 6 周老活动开开关无效果。

- 脚本：遍历 `completed` + `cycling` + `power_zones IS NOT NULL` 的活动，从 trackpoint **复用 `calculate_power_zones` 重算**整条 power_zones（带上新的 `zero_seconds`），写回。
- 用什么 FTP：用该活动 user 的**当前 ftp**（与 `backfill_ftp.py` 现有 pattern 一致）。注意这会让历史 power_zones 的区间边界按当前 ftp 重算——若不希望动 Z1-Z6 边界，则改为"只补 zero_seconds 字段、不覆盖 seconds"，但那要保证 0W 统计口径和原 seconds 一致（见 §5 陷阱 1）。**两条路二选一，在 commit message 写清选哪条及理由。**
- 独立 python 脚本陷阱（CLAUDE.md memory `standalone_script_orm_loading`）：脚本顶部显式 import 所有外键关联 ORM（User / Activity / Trackpoint），`# noqa: F401`，否则 standalone 进程 `NoReferencedTableError`。
- 节流：若涉及大量 trackpoint 查询，参考 `backfill_ftp.py` 的批处理 + SAVEPOINT。
- 先 dry-run 打印前 3 条的 before/after zero_seconds，人工核对合理（Z1 79% 里扣出的 0W 应是大头）再 apply。

---

## §7 验收

**新增测试点**（纯函数 + API）：
- `calculate_power_zones`：含 0W 点的 trackpoints → Z1 dict 有 `zero_seconds` 且 = 0W 段 dt 之和；全程无 0W → `zero_seconds == 0`；power=None 的点不计入 zero_seconds 也不计入任何区间。
- `aggregate_power_zones`：`exclude_zero=True` 时 Z1.seconds 和 total 各扣 total_zero_seconds、percent 按新分母、Z2-Z6 seconds 不变、classification_seconds 不变、groups 不变。
- `aggregate_power_zones` 默认等同 `exclude_zero=True`；旧含 0W 口径必须显式传 `exclude_zero=False`。
- `exclude_zero=True/False` 两态下 `current_type` / `groups` / 文案完全一致（证明分类不受影响）。
- `GET /api/training/distribution?range=6w` 默认等同 `exclude_zero=true`。
- 小程序训练结构页不出现 switch、不读写 `training_distribution_exclude_zero`，固定请求 `exclude_zero: true`。
- `data_complete` 用含 0W 原始 total 判定（exclude_zero 不把人踢进数据不足）。
- 缺 `zero_seconds` 字段的老活动（dict 无此 key）→ 按 0 处理不报错。

**回归命令**：
```bash
pytest tests/test_training_distribution.py tests/test_training_distribution_api.py tests/test_training_distribution_static.py
pytest tests/test_power_zones.py   # 若存在；power_zones 纯函数测试
pytest tests/test_training_load_api.py
git diff --check
```

**curl 验证**（部署后）：
```
GET /api/training/distribution?range=6w                    # 默认：Z1 扣 0W / total 变小
GET /api/training/distribution?range=6w&exclude_zero=false # 兼容：Z1 含 0W（旧口径）
```
对比两次响应：`groups` / `current_type` / 文案应完全相同；默认响应应等同 `exclude_zero=true`；显式 false 的 `raw_zones` Z1 seconds 和全体 percent 可不同。

---

## 三审与部署

- 代码层改完按 CLAUDE.md 三重审判：Claude 双审（spec 忠诚 + 集成）+ Codex 异源（若本 task 由 Codex 主写，则反过来 Claude 异源审）。
- backfill 脚本属"动生产数据"高风险 → 走 §6 dry-run gate。
- 部署：纯后端改动 rebuild api（worker/scheduler 不依赖 distribution）；小程序页面随小程序上传；backfill 在 api 部署后单独跑。
