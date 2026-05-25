# Sprint 11 训练分布技术 Spec

> **本文件性质**：Sprint 11 写代码前的技术合同。它只锁字段、函数、接口、测试和删除边界；不代表已经可以直接开工。
>
> **上游**：`docs/prd/sprint-11-prd.md`、`docs/prototypes/sprint11-training-distribution-demo.html`
>
> **审查前置**：`docs/plans/sprint-11-field-review-handoff.md` 交给 Claude 异源审后，再进入实现。

---

## 0. 用户会经历什么

小明周日打开“我的”，点“训练结构”。他第一眼看到一句话：“你最近 6 周强度太挤在中间，容易累但突破不明显。”下面不是一堆专业词，而是三块清楚的时间分布：耐力、节奏/阈值、高强度。最后 velo 给他下周三件事：一次轻松骑、一次短间歇、一次阈值控制。小明知道自己不是“不够努力”，而是训练结构要分开。

这个功能只回答一件事：最近 6 周你练得像哪种结构，以及下周先改什么。

---

## 1. 已核实字段

| 字段 | 来源 | 合同 |
|---|---|---|
| `activities.power_zones` | [✓ grep] `app/activity/models.py:159-162` | 训练分布唯一核心数据源；不新建表 |
| `power_zones[].zone/name/min_w/max_w/seconds/percent` | [✓ grep] `app/activity/power_zones.py:31-45`、`:97-104` | 读取 `zone/name/seconds/percent`；响应禁止带 `min_w/max_w` |
| `activities.status` | [✓ grep] `app/activity/models.py:54-56` | 只统计 `completed` |
| `activities.activity_type` | [✓ grep] `app/activity/models.py:100-108` | 只统计 `cycling` |
| `activities.duplicate_of` | [✓ grep] `app/activity/models.py:117-128` | 必须 `IS NULL`，避免同一骑行重复算 |
| `activities.started_at` | [✓ grep] `app/activity/models.py:91-94` | 用北京时间自然日窗口转 UTC 查询 |
| SQLite 测试 `power_zones` | [✓ grep] `tests/conftest.py:118-120` | service 要兼容 JSON string |
| 功率隐私 | [✓ grep] `app/activity/service.py:82-95` | endpoint 只给当前用户；不做他人训练结构页 |
| 现有训练负荷接口 | [✓ grep] `app/training/router.py:16-26` | 新增 `/distribution` 不能影响 `/load` |

---

## 2. 请求与响应

### 请求

```text
GET /api/training/distribution?range=6w
```

- 鉴权：必须登录，读取当前登录用户。
- `range`：只接受 `6w`；其他值返回 FastAPI 参数校验错误。
- 不提供 `user_id` 参数，不支持看别人训练结构。

### 响应字段

```python
TrainingDistributionRange = Literal["6w"]
TrainingDistributionType = Literal["polarized", "pyramidal", "sweet_spot", "threshold", "mixed"]

class TrainingDistributionZone(BaseModel):
    zone: Literal["Z1", "Z2", "Z3", "Z4", "Z5", "Z6"]
    name: str
    seconds: int
    percent: int

class TrainingDistributionGroup(BaseModel):
    key: Literal["endurance", "tempo_threshold", "high_intensity"]
    label: str
    zones: list[str]
    seconds: int
    percent: int
    role: str

class TrainingDistributionAction(BaseModel):
    title: str
    body: str

class TrainingDistributionWeekItem(BaseModel):
    day: str
    title: str
    focus: str

class TrainingDistributionResponse(BaseModel):
    range: TrainingDistributionRange
    window_days: int
    activity_count: int
    total_power_seconds: int
    total_power_hours: float
    data_complete: bool
    insufficient_power_data: bool
    current_type: TrainingDistributionType | None
    current_label: str
    current_description: str
    target_label: str
    target_description: str
    headline: str
    explanation: str
    groups: list[TrainingDistributionGroup]
    raw_zones: list[TrainingDistributionZone]
    actions: list[TrainingDistributionAction]
    week_plan: list[TrainingDistributionWeekItem]
```

硬规则：
- `raw_zones` 只返回 `zone/name/seconds/percent`。
- 不返回 `min_w/max_w`，因为这两个值能反推用户 FTP。
- 本接口 `insufficient_power_data` 恒等于 `not data_complete`；因为查询已过滤 `power_zones IS NOT NULL`，数据不足只剩“有功率活动太少或时间太短”这一种原因。
- `data_complete=false` 时，`current_type=None`，`actions/week_plan` 必须为空数组。
- `total_power_seconds` = Z1+Z2+Z3+Z4+Z5+Z6 的总秒数，含 Z1。
- `total_power_hours` 只用于展示，按 `total_power_seconds / 3600` 得出，保 1 位，也含 Z1。
- `current_description` / `target_description` 用来承接原型“当前 vs 建议方向”两张对比卡下面的小句子，不能丢给前端现场编。
- `groups` 三组不含 Z1，所以 `sum(groups[].seconds)` 不等于 `total_power_seconds`；两者相差的就是 Z1 秒数。
- `groups` 文案固定：`endurance` = label `耐力` / zones `["Z2"]` / role `打底时间`；`tempo_threshold` = label `中强度` / zones `["Z3", "Z4"]` / role `最容易堆累`；`high_intensity` = label `高强度` / zones `["Z5", "Z6"]` / role `刺激偏少`。
- `week_plan` 必须拆成 7 个结构化项，例如 `{day: "一", title: "Z2", focus: "45 分"}`，不要把整周计划作为一整句字符串返回。

---

## 3. 查询合同

service 查询 `Activity` 时必须同时满足：

```text
Activity.user_id == 当前用户
Activity.status == "completed"
Activity.activity_type == "cycling"
Activity.duplicate_of IS NULL
Activity.started_at IS NOT NULL
Activity.started_at >= start_utc
Activity.started_at < end_utc
Activity.power_zones IS NOT NULL
```

时间窗口：
- `today_bj = datetime.now(UTC+8).date()`
- `start_day = today_bj - timedelta(days=41)`
- `end_day = today_bj + timedelta(days=1)`
- `start_utc/end_utc` 用北京时间 00:00 转 UTC。

参考现有训练负荷模块的时间 helper：[✓ grep] `app/training/service.py:39`、`:73-75`、`:107-123`。

实现方式写死：
- `distribution_service.py` 直接 `from app.training.service import _bj_day_start_utc, _today_bj`。
- 不复制北京时间计算逻辑。
- 不为了抽公共 helper 去重构 `app/training/service.py`；这个文件属于 Sprint 10 训练负荷，删除 Sprint 11 时不能动它。

---

## 4. 函数合同

新增纯函数文件：`app/training/distribution.py`。

建议对外函数：

```python
def normalize_power_zones(value: list[dict] | str | None) -> list[dict]:
    """把 DB 或 SQLite 测试里的 power_zones 统一成 list[dict]。"""

def aggregate_power_zones(zone_sets: list[list[dict]]) -> dict:
    """累计 Z1-Z6 秒数、百分比和三组页面分布。"""

def classify_distribution(stats: dict) -> str | None:
    """把累计结果分成 polarized/pyramidal/sweet_spot/threshold/mixed。"""

def build_training_distribution_payload(stats: dict) -> dict:
    """生成页面需要的 headline、解释、行动建议和一周示意安排。"""
```

纯函数要求：
- 不 import SQLAlchemy / FastAPI / DB Session。
- 不读 `Activity`。
- 不知道当前用户是谁。
- 输入里出现 `min_w/max_w` 时可以读取但不能进入输出。
- 对缺 zone、非数字 seconds、空数组做稳健处理，不能把 0 秒当成缺失。

### 4.1 五种类型文案草表

**Tim 已确认本表作为 v1 上线文案**。Sweet Spot 一栏来自原型现成文案；其余 4 类先按当前草稿进入 v1，后续根据真实用户反馈再调整。实现 agent 不允许现场改写文案后直接上线。

| 类型 | current_description | target_description | headline | explanation | actions（3 条） | week_plan（7 个结构化项） |
|---|---|---|---|---|---|---|
| `sweet_spot` | 时间紧、想快点见效时常见，但中强度堆多了会觉得天天都累。 | 更多轻松骑打底，保留少量真正高强度，训练更分明。 | 你最近练得太挤在中间，容易累，但突破感不强。 | 过去 6 周，你有较多时间卡在节奏和阈值区。下周先把一次中强度骑换成轻松长骑，让身体有空间吸收训练。 | 把一次节奏骑换成 90 分钟轻松骑：目标是让 Z2 时间涨起来，能完整说话，不追速度。<br>保留一次短间歇：例如 5 组 3 分钟高强度，中间充分恢复。<br>阈值骑只留一次：如果本周已经爬坡或拉扯很多，就不要再补一场硬骑。 | `{day:"一", title:"Z2", focus:"45 分"}`；`{day:"二", title:"Z5", focus:"短间歇"}`；`{day:"三", title:"休", focus:"恢复"}`；`{day:"四", title:"Z2", focus:"90 分"}`；`{day:"五", title:"Z3", focus:"轻节奏"}`；`{day:"六", title:"Z2", focus:"长骑"}`；`{day:"日", title:"休", focus:"看状态"}` |
| `polarized` | 轻松骑和高强度都有，中间区很少，训练日之间分得比较清楚。 | 继续守住轻松日的轻松，只保留少量真正高强度，不要把每次都骑成半硬不硬。 | 你最近练得很分明，轻松骑和高强度都有，但中间区很少。 | 这种结构接近 80/20，适合有时间做耐力打底、也愿意保留真正刺激的车手。下周重点不是再加一堆中强度，而是守住轻松日的轻松。 | 保留两次真正轻松的 Z2，不要骑着骑着变成节奏骑。<br>高强度只留一次，做短而清楚的间歇。<br>如果感觉累，先砍高强度，不要砍恢复。 | `{day:"一", title:"Z2", focus:"45 分"}`；`{day:"二", title:"休", focus:"恢复"}`；`{day:"三", title:"Z5", focus:"短间歇"}`；`{day:"四", title:"Z2", focus:"60 分"}`；`{day:"五", title:"休", focus:"恢复"}`；`{day:"六", title:"Z2", focus:"长骑"}`；`{day:"日", title:"Z1", focus:"轻松恢复"}` |
| `pyramidal` | 耐力最多，中强度次之，高强度最少，是比较稳的训练底座。 | 保持耐力底座，同时让一次高强度更清楚，别把刺激都摊成中强度。 | 你的训练像金字塔，耐力最多，中强度次之，高强度最少。 | 这是一种稳健结构，适合逐步变强。下周不要急着变成 80/20，先保持底座，同时给一次清楚的高强度刺激。 | 保留本周最长的 Z2 骑，继续打底。<br>把一次随意拉扯改成有目的的短间歇。<br>中强度不要天天出现，给恢复日留空。 | `{day:"一", title:"休", focus:"恢复"}`；`{day:"二", title:"Z2", focus:"60 分"}`；`{day:"三", title:"Z4", focus:"控制骑"}`；`{day:"四", title:"Z2", focus:"45 分"}`；`{day:"五", title:"休", focus:"恢复"}`；`{day:"六", title:"Z2", focus:"长骑"}`；`{day:"日", title:"Z5", focus:"短刺激"}` |
| `threshold` | 阈值附近待得太久，容易把训练骑成比赛，短期爽但恢复压力大。 | 先减少硬顶，把更多时间还给轻松骑，只留一次清楚的阈值课。 | 你最近太常在阈值附近硬顶，短期很爽，但恢复压力会变大。 | Z4 时间过高说明你经常把训练骑成比赛。下周先把硬骑次数降下来，让高强度更少、更清楚。 | 阈值训练只保留一次，其他日不追均速。<br>加一到两次 Z2 轻松骑，把恢复空间补回来。<br>高强度间歇宁可短，不要把整场都拖成硬顶。 | `{day:"一", title:"休", focus:"恢复"}`；`{day:"二", title:"Z2", focus:"45 分"}`；`{day:"三", title:"Z4", focus:"阈值一次"}`；`{day:"四", title:"休", focus:"恢复"}`；`{day:"五", title:"Z2", focus:"60 分"}`；`{day:"六", title:"Z2", focus:"长骑"}`；`{day:"日", title:"Z1", focus:"轻松恢复"}` |
| `mixed` | 强度分布还不稳定，可能今天轻松、明天硬顶，身体很难形成节奏。 | 先把一周安排变简单，固定轻松日和强度日，再谈更专业的训练结构。 | 你最近训练结构还不稳定，先别急着贴训练流派。 | 过去 6 周的时间分布不够清楚，可能是活动太杂、强度忽高忽低。下周先把一周安排变简单，让身体知道每一天在练什么。 | 先固定两次 Z2 轻松骑。<br>只安排一次明确的强度课。<br>其他骑行不要临时加码，先让节奏稳定下来。 | `{day:"一", title:"休", focus:"恢复"}`；`{day:"二", title:"Z2", focus:"45 分"}`；`{day:"三", title:"Z5/Z4", focus:"一次强度"}`；`{day:"四", title:"休", focus:"恢复"}`；`{day:"五", title:"Z2", focus:"60 分"}`；`{day:"六", title:"自由", focus:"轻松骑"}`；`{day:"日", title:"休", focus:"恢复或休息"}` |

---

## 5. 分类 v1

先算三组：
- `endurance = Z2`
- `tempo_threshold = Z3 + Z4`
- `high_intensity = Z5 + Z6`
- `Z1` 保留在 `raw_zones`，不做训练类型主轴。

百分比分母必须分成两套：
- `groups[].percent` 和分类判断的分母 = Z2+Z3+Z4+Z5+Z6，剔除 Z1。原型三组 44%+47%+9%=100，用的就是这个口径。
- `raw_zones[].percent` 的分母 = Z1+Z2+Z3+Z4+Z5+Z6，沿用现有单条活动 `power_zones[].percent` 口径。
- `total_power_seconds` / `total_power_hours` 含 Z1，用来告诉用户“最近 6 周有多少有功率记录”，不是饼图分母。

分类顺序：
1. `threshold`：Z4 单区占比 >= 30%。这里的占比用分类分母，也就是剔除 Z1 后的 Z2-Z6 总秒数；v1 阈值可调。
2. `sweet_spot`：Z3-Z4 >= 40%。
3. `polarized`：Z2 >= 70%，Z5+ >= 8%，Z3-Z4 <= 22%。
4. `pyramidal`：Z2 > Z3-Z4 > Z5+。
5. `mixed`：其他情况。

数据不足：
- `activity_count < 3`，或 `total_power_seconds < 10800`，返回 `data_complete=false`。
- 不足时只解释“功率数据还不够”，不冒充教练给建议。
- 数据不足时也必须返回完整响应字段，避免前端猜默认值：
  - `current_type = None`
  - `current_label = "功率数据不足"`
  - `current_description = "最近 6 周有功率区间的骑行还不够，暂时不能判断训练结构。"`
  - `target_label = "先补记录"`
  - `target_description = "先多记录几次有功率计的骑行，再让 velo 判断训练时间怎么分布。"`
  - `headline = "功率数据还不够，先别急着判断训练结构。"`
  - `explanation = "最近 6 周至少需要 3 条有功率区间的骑行，且总有功率时间达到 3 小时。"`
  - `actions = []`
  - `week_plan = []`

---

## 6. 删除边界

删 Sprint 11 只能撤这些：
- `app/training/distribution.py`
- `app/training/distribution_service.py`
- `app/training/schemas.py` 里 Sprint 11 的 schema 类
- `app/training/router.py` 里 `/distribution` route
- `miniprogram/pages/training-distribution/`
- `miniprogram/app.json` 新页面注册
- `miniprogram/pages/profile/` 新入口和新跳转函数
- Sprint 11 专属测试

不能撤这些：
- `/api/training/load`
- `app/training/service.py`
- `app/training/training_load.py`
- `app/training/models.py`
- `daily_training_load` 表
- GPX / Strava worker 里 Sprint 10 的 daily training load hook

---

## 7. 任务验收

实现前验收：
- PRD、spec、执行计划、字段审查总结都存在。
- Claude 异源审核确认 Critical=0。

实现后验收命令：

```bash
pytest tests/test_training_distribution.py tests/test_training_distribution_api.py tests/test_training_distribution_static.py
pytest tests/test_training_load_api.py tests/test_training_calendar_static.py
pytest tests/test_training_daily_load_hook.py
git diff --check
```

必须新增测试点：
- `raw_zones` 不含 `min_w/max_w`。
- `current_description` / `target_description` 在完整数据和数据不足时都有确定值。
- `groups` 固定 label/role。
- `week_plan` 是 7 个结构化项；数据不足时为空数组。
- 缺 zone、非数字 seconds、空数组/全 0 秒输入不会炸，也不会把 0 秒当缺失。
- 42 天窗口有 `start_utc` 和 `end_utc` 双边界。
- `duplicate_of IS NULL` 生效。
- SQLite JSON string 形式的 `power_zones` 可读。
- `/api/training/load` 仍可用。
- Sprint 10 worker/import hook 回归仍通过。
- `training-calendar` 仍注册；新增 `training-distribution` 后静态测试不再要求 training-calendar 永远最后。
