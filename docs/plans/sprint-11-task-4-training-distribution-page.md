# Sprint 11 Task-4 — 小程序训练结构页 + Profile 入口

> 所属：Sprint 11（训练分布分析）/ 第 4 个 task / 小程序展示层。
> 前置：Task 3 `/api/training/distribution?range=6w` 已通过 API 测试。
> 范围：新增训练结构页、profile 入口、静态合同测试。

---

## ─────── 给 Tim 看 ───────

### 干啥用

用户从“我的”页点进“训练结构”，第一屏先看到一句判断和下周怎么改，再看三组时间分布和数据来源。

这个页面不是专业图表页，而是一个“训练翻译器”：把 Z1-Z6 翻译成用户能马上行动的一周建议。

### 用户故事

张三周日打开“我的”，看到“训练结构”。点进去后，页面告诉他最近 6 周练得像 Sweet Spot，原因是中强度太多；再往下看，他看到下周要先把一次节奏骑换成 90 分钟轻松骑。

### 怎么算做对了

- ✓ `app.json` 注册 `pages/training-distribution/training-distribution`。
- ✓ profile 新增“训练结构”入口，不覆盖现有“训练分析”入口。
- ✓ 页面只请求 `/api/training/distribution?range=6w`。
- ✓ 页面有 loading / error / 数据不足 / 正常四态。
- ✓ 页面展示 `current_description` / `target_description`，不自己编文案。
- ✓ `training-calendar` 仍注册，旧训练负荷入口仍能进。

### 这次不做

- 不写后端。
- 不从活动列表拼训练分布。
- 不改 `/api/training/load`。
- 不做训练计划编辑器。
- 不做 LLM 教练总结。

### 估时

0.5-1 天，含小程序静态测试和开发者工具验收。

---

## ─────── 执行 subagent 技术细节 ───────

<details>
<summary>展开</summary>

## 1. 起手必跑

```bash
nl -ba docs/prototypes/sprint11-training-distribution-demo.html | sed -n '473,610p'
nl -ba docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md | sed -n '47,107p;168,200p'
nl -ba miniprogram/app.json | sed -n '1,20p'
nl -ba miniprogram/pages/profile/profile.wxml | sed -n '112,130p'
nl -ba miniprogram/pages/profile/profile.js | sed -n '347,358p'
nl -ba miniprogram/pages/profile/profile.wxss | sed -n '519,550p'
nl -ba miniprogram/utils/api.js | sed -n '114,120p'
nl -ba tests/test_training_calendar_static.py | sed -n '16,60p'
```

已验证事实：
- 当前 `app.json` 最后一页是 `pages/training-calendar/training-calendar`，[✓ grep] `miniprogram/app.json:2-15`。
- profile 已有“训练分析”入口，[✓ grep] `miniprogram/pages/profile/profile.wxml:120-126`，JS 跳 `/pages/training-calendar/training-calendar`，[✓ grep] `miniprogram/pages/profile/profile.js:356-358`。
- profile action card 样式可复用，[✓ grep] `miniprogram/pages/profile/profile.wxss:519-550`。
- `api.get(path, params)` 已支持 query 参数，[✓ grep] `miniprogram/utils/api.js:114-120`。
- 现有静态测试会断言 training-calendar 是最后一页，[✓ grep] `tests/test_training_calendar_static.py:16-21`，本 task 必须更新为“仍注册 + 新页在末尾”。
- 原型的当前/建议对比卡文案在 `docs/prototypes/sprint11-training-distribution-demo.html:535-543`。

## 2. 文件改动清单

硬门：先创建/修改静态测试并确认失败，再写页面和入口；禁止先写页面后补测试。

- Create `miniprogram/pages/training-distribution/training-distribution.wxml`
- Create `miniprogram/pages/training-distribution/training-distribution.wxss`
- Create `miniprogram/pages/training-distribution/training-distribution.js`
- Create `miniprogram/pages/training-distribution/training-distribution.json`
- Modify `miniprogram/app.json`
- Modify `miniprogram/pages/profile/profile.wxml`
- Modify `miniprogram/pages/profile/profile.js`
- Create `tests/test_training_distribution_static.py`
- Modify `tests/test_training_calendar_static.py`

## 3. 页面数据合同

页面只使用 Task 3 response：
- `headline`
- `explanation`
- `current_label`
- `current_description`
- `target_label`
- `target_description`
- `groups`
- `raw_zones`
- `actions`
- `week_plan`
- `data_complete`
- `insufficient_power_data`
- `activity_count`
- `total_power_hours`

禁止：
- 禁止从 `/api/activities` 拉活动列表再拼。
- 禁止前端硬编码 5 类型文案。
- 禁止展示 `min_w/max_w`。

## 4. JS 状态机

`training-distribution.js` data：

```javascript
Page({
  data: {
    loading: true,
    loadError: false,
    dataComplete: false,
    insufficientPower: false,
    distribution: null,
    groups: [],
    rawZones: [],
    actions: [],
    weekPlan: [],
  },
})
```

请求：

```javascript
api.get('/api/training/distribution', { range: '6w' })
```

成功后：
- `dataComplete = !!res.data_complete`
- `insufficientPower = !!res.insufficient_power_data`
- `distribution = res || null`
- `groups = Array.isArray(res.groups) ? res.groups : []`
- `rawZones = Array.isArray(res.raw_zones) ? res.raw_zones : []`
- `actions = Array.isArray(res.actions) ? res.actions : []`
- `weekPlan = Array.isArray(res.week_plan) ? res.week_plan : []`

错误态：
- `catch` 后设置 `loadError: true`。
- toast 文案：`训练结构加载失败 / 请重试`。

## 5. WXML 结构

必须有四态：
- loading：`加载中`
- error：`训练结构加载失败 / 请重试`
- insufficient：`功率数据不足`
- normal：显示 hero、summary、groups、对比卡、actions、week plan、raw source。

正常态必须出现这些绑定：

```xml
<text>{{distribution.current_label}}</text>
<text>{{distribution.current_description}}</text>
<text>{{distribution.target_label}}</text>
<text>{{distribution.target_description}}</text>
<view wx:for="{{groups}}" wx:key="key">
  <text>{{item.label}}</text>
  <text>{{item.percent}}%</text>
  <text>{{item.role}}</text>
</view>
<view wx:for="{{weekPlan}}" wx:key="day">
  <text>{{item.day}}</text>
  <text>{{item.title}}</text>
  <text>{{item.focus}}</text>
</view>
```

## 6. Profile 入口

在现有“训练分析”入口后面加新卡：

```xml
<view class="profile-action-card" bindtap="onTapTrainingDistribution">
  <view class="action-main">
    <text class="action-title">训练结构</text>
    <text class="action-subtitle">看最近 6 周训练时间怎么分布</text>
  </view>
  <text class="action-arrow">›</text>
</view>
```

JS 新增：

```javascript
onTapTrainingDistribution() {
  wx.navigateTo({ url: '/pages/training-distribution/training-distribution' });
},
```

## 7. app.json 注册

追加到 pages 末尾：

```json
"pages/training-distribution/training-distribution"
```

`pages/home/home` 必须仍是第一项。

## 8. 静态测试清单

新增 `tests/test_training_distribution_static.py`：
1. 四文件存在。
2. app.json 注册 `pages/training-distribution/training-distribution` 且在末尾。
3. profile 有“训练结构”入口、subtitle 和 `onTapTrainingDistribution`。
4. JS 调 `/api/training/distribution` 且 range 为 `6w`。
5. WXML 使用 `current_description` / `target_description`。
6. WXML 使用 `groups`、`actions`、`weekPlan`。
7. JS 不出现 `/api/activities`。
8. 页面包含 loading / error / 功率数据不足文案。

修改 `tests/test_training_calendar_static.py`：
- `test_training_calendar_registered_at_app_json_tail` 改名为 `test_training_calendar_still_registered_after_distribution_page_added`。
- 断言：

```python
assert app_json["pages"][0] == "pages/home/home"
assert "pages/training-calendar/training-calendar" in app_json["pages"]
assert app_json["pages"][-1] == "pages/training-distribution/training-distribution"
```

## 9. 验收命令

```bash
python3 -m json.tool miniprogram/app.json >/tmp/velo-app-json-check.txt
python3 -m pytest tests/test_training_distribution_static.py tests/test_training_calendar_static.py -q
rg -n "pages/training-distribution/training-distribution|onTapTrainingDistribution|/api/training/distribution|current_description|target_description" miniprogram tests
git diff --check
```

真机 / 开发者工具验收：
- 进入 profile，两个入口都在：“训练分析”和“训练结构”。
- 点“训练结构”进入新页。
- 正常数据态先看判断和建议，不先看原始 zone。
- 数据不足态不显示训练建议。

## 10. 5 字段 issue 草稿

背景：Task 3 已给小程序完整响应；Task 4 要把原型落成真实小程序页面，并保留现有训练负荷入口。目标：新增训练结构页四文件、profile 新入口、app.json 注册和静态测试。验收命令：`python3 -m pytest tests/test_training_distribution_static.py tests/test_training_calendar_static.py -q && python3 -m json.tool miniprogram/app.json`。不要碰：后端、API、DB、`/api/training/load`、训练日历页面逻辑。失败处理：如果页面视觉和原型差太远，先保留数据结构和入口，标注视觉待 Tim 真机拍板；不要为了视觉重写后端字段。

## 11. commit message 模板

`feat(miniprogram): sprint11 task-4 training distribution page`

正文：`Add training distribution mini-program page, profile entry, app.json registration, and static contract tests. Keep training calendar intact and render only backend-provided distribution copy/data.`

</details>
