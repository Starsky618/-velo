# Sprint 5 Task-4.6 — 隐私分项开关 + 后端全工程字段挖空

> Sprint 5 task-4 系列 / 第 6 个 / 终章 / 前置：4.1 / 4.2 / 4.3 / 4.4 / 4.5

---

## ─────── 给 Tim 看 ───────

### 干啥用

把 task-4.1 建好但没接逻辑的 **hide_power / hide_heartrate** 两个开关接通：
- 前端：骑行详情页加 3 个隐私开关（公开/私密 + 隐藏功率 + 隐藏心率）
- 后端：用户设了隐藏后，**他人在所有能看到这个用户数据的位置**（活动详情 / 赛段排行榜 / 活动列表 / 时序图）功率/心率字段全部挖空 → 前端整块自动消失

### 用户故事

**A — CCF 设隐藏功率**
CCF 打开自己 80 公里骑行 → 点右上角设置 → 勾选"隐藏功率" → 保存

之后我（Tim）打开 CCF 的活动详情看到：
- 距离 / 速度 / 轨迹 / 心率 / 海拔 ✓ 都在
- **功率卡片整块消失**（跟没装功率计的车一模一样）
- **时序功率曲线也消失**

我打开妙峰山赛段排行榜看到：
- CCF 5:42 第 1 名 / 姓名 / 头像 / 速度 ✓ 都在
- **avg_power 那列对 CCF 这行显示 "-"** ← 关键

我从我自己的骑行进 segment 详情页 → 排行榜 CCF 那行的 avg_power 也是 "-"

CCF 自己看自己 → 全部数据完整可见（不挖空）

**B — CCF 设隐藏心率**
同 A 逻辑，全工程他人看 CCF 心率全是 "-"

**C — CCF 设整条私密**（task-4.1 已实现）
CCF 那条 80 公里骑行**完全消失** / 排行榜匿名化 / 不变

### 怎么算做对了

- ✓ detail 页加 3 个开关 UI（公开/私密 + 隐藏功率 + 隐藏心率）
- ✓ 后端 PATCH `/api/activities/{id}/privacy` 接收 3 字段（schema `extra="forbid"`）
- ✓ 仅本人能改自己的隐私（PermissionError 403）
- ✓ 他人在所有读路径看到 owner 隐藏的数据 = null：
  - activity 详情：avg_power / max_power / np / powers 时序数组
  - activity 时序：powers 整个数组
  - segment 详情 TOP20：avg_power
  - segment leaderboard 分页：avg_power
  - my-efforts（他人不能调 / 只查自己 / 不影响）
  - get_activity_segments（他人看公开活动的途经赛段）：avg_power
  - 同上规则对 hide_heartrate → avg_hr / max_hr / heartrates 时序
- ✓ 本人始终看自己完整数据
- ✓ 老 activity 无 privacy 行 → 视同全公开（既有 task-4.1 兜底）

### 这次**不做**
- 隐藏起终点的隐私区（Strava 那种 200m 半径模糊）/ 仍写入 tech-debt
- 设置页全局默认值（单条切就够）

### 估时
1 天

---

## ─────── 折叠：技术细节 ───────

<details>

### 后端改动 1：新 PATCH endpoint

`PATCH /api/activities/{activity_id}/privacy`
- 接收 schema：`ActivityPrivacyUpdate { visibility?: 'public'|'private', hide_power?: bool, hide_heartrate?: bool }` (`extra="forbid"`)
- 仅 owner 可改（user_id 校验 / 否则 403）
- 实现：upsert activity_privacy 行（无则 insert / 有则 update）
- 返回更新后的 privacy 对象

### 后端改动 2：字段挖空 helper

`app/activity/service.py` 加：

```python
def _apply_privacy_mask(activity_dict: dict, privacy, viewer_user_id: int | None) -> dict:
    """
    根据 ActivityPrivacy 把 activity 字典里他人看不到的字段挖空成 None。
    
    本人查看时不挖空（始终完整）。privacy 为 None 时视同全公开。
    挖空字段：
    - hide_power=True → avg_power / max_power / normalized_power / powers 数组
    - hide_heartrate=True → avg_hr / max_hr / heartrates 数组
    """
```

调用方：
- `get_activity_detail`（返字典前调一次）
- `get_activity_timeseries`（返字典前调 / 只挖 powers / heartrates 数组）

### 后端改动 3：segment 模块字段挖空

类似 helper（或复用 `_apply_privacy_mask` 改成"挖单条 row"）应用到：
- `app/segment/service_query.py:get_segment_detail` TOP20 leaderboard
- `app/segment/service_query.py:get_leaderboard` 分页
- `app/segment/service_query.py:get_activity_segments`

每条 row 已经 LEFT JOIN ActivityPrivacy 拿到 privacy_visibility（task-4.1）→ 同时也带 privacy_hide_power / privacy_hide_heartrate（task-4.6 新增 JOIN 列）→ 渲染时按 `row.user_id != viewer_user_id` + `privacy_hide_power=True` → avg_power=None。

### 后端改动 4：activity 列表挖空

`get_activity_list` 也要挖（home 页 / explore 卡片显示功率数字）。

### 前端改动

**detail.wxml + detail.js 加 3 个开关**：
- 详情页右上角加齿轮图标 → 点击展开隐私设置抽屉
- 3 个 switch：visibility（公开/私密） / hide_power / hide_heartrate
- 切换 → 调 PATCH endpoint → 重新拉详情

**api.js 加 `updateActivityPrivacy(activityId, partial)` helper**

### 测试覆盖

- `test_update_privacy_visibility` / `test_update_privacy_hide_power` / `test_update_privacy_hide_heartrate`
- `test_update_privacy_forbids_unknown_field`（schema extra=forbid）
- `test_update_privacy_other_user_403`
- `test_others_see_null_power_when_hidden`（detail）
- `test_owner_sees_full_power_when_hidden`（owner 不挖空）
- `test_leaderboard_hides_power_for_others`（赛段排行榜）
- `test_leaderboard_shows_own_power`（本人看自己的 row）
- `test_old_activity_no_privacy_row_shows_all`（兜底）
- `test_get_activity_segments_hides_power_for_others`

### 红线

- 不动 task-4.1 visibility 整条隐藏逻辑
- 不做隐私区（起终点模糊）
- 不做全局默认值开关
- PATCH endpoint schema 必须 `extra="forbid"` 防 admin 误改其他字段

### Codex 异源审重点

- 挖空 helper 是否覆盖**所有他人读路径**（grep 全工程 SegmentEffort.avg_power / Activity.avg_power）
- 本人 always 完整可见（viewer_user_id == owner 时不挖空）
- 老 activity（无 privacy 行）默认全显示
- 前端开关 PATCH 后是否真重拉 detail（防 stale UI）
- schema extra=forbid 防 admin 越权

</details>
