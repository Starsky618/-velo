# Coach Engine Design — 骑行教练总结设计稿

> **本文件性质**：Sprint 12 模块 D 的详细设计文档 / brainstorm 标准产物
> **上游路线图**：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md` 模块 D
> **维护**：Tim + Claude brainstorm 协作（2026-05-20 / 走完 brainstorm skill Step 1-5）
> **版本**：v0.1（首版 / 等 Sprint 9-11 ship 后转 `docs/prd/sprint-12-prd.md`）

---

## 0. 来源 + 上游 + Tim 拍过的关键决定

### 0.1 来源

- 2026-05-20 Tim + Claude brainstorm 全过程对话
- research subagent 调研：国际产品 + 算法 + 中国天气 API + 微信小程序限制 + LLM prompt 工程
- 跟另一线 brainstorm（roadmap.md / sprint-9-prd.md）合并讨论：原"规则版"改 LLM 版

### 0.2 跟另一线的关系

- 本文件 = `roadmap.md` 模块 D 的详细设计（LLM 版 / 替代原"规则版"）
- **前置依赖**：Sprint 9（FTP 智能化）+ Sprint 10（PMC 训练负荷曲线）+ Sprint 11（训练分布）必须先 ship
- **本设计不本 sprint 实施**：Sprint 9-11 全 ship 后 Sprint 12 开工时拿本文件转 `docs/prd/sprint-12-prd.md`

### 0.3 Tim 拍过的关键决定（按 brainstorm 时间序）

1. **产品定位**：装饰展示 vs 主动指导 / 选指导层（详 memory `feedback_decoration_vs_guidance_velo_persona_lesson.md` + 全局 CLAUDE.md §2.1）
2. **触发场景**：早上推 + 骑完复盘并行 / 但本 sprint 骑前优先
3. **训练目标来源**：用户在 profile 手动填一次（5 选 1）/ 留空 LLM 不写"今日目标"主观句
4. **入口路径**：动态 tab 顶部大卡 + 点击进完整"今天"页（不新建 tab）
5. **用户分层**：no_data / partial_data / full_data 三层
6. **LLM 失败处理**：自动回退现有算法选一条
7. **速率限制**：每用户每天 **4 次**手动刷新
8. **早上 cron 时间**：**6 点**跑（不是 8 点）
9. **persona 处理**：暂停不删 / 整目录晾着 / ship 后看真实反应再判断
10. **HRV / RPE 永久不做**（research 实证 / velo 拿不到 / 装就崩塌）

---

## 1. 产品形态

### 1.1 用户故事

接了 Strava + 有 6 周以上历史的严肃骑手早上 6 点 / 打开 velo / 默认动态 tab / 顶部看到大卡：

```
┌─────────────────────────────────┐
│ 🎯 低风险 Zone 2 有氧打底日       │
│ 27° 多云 / 高湿度 / 今日有雾     │
│ 60-75 分钟 / 避免冲刺            │
│              [点击看完整建议 →]   │
└─────────────────────────────────┘

（下面是原活动 feed）
```

点击大卡 → 进入完整"今天"页 / 4 段卡片：

```
27° 多云 / 高湿度 / 今日有雾

【今日教练总结】

低风险 Zone 2 有氧打底日

你近 7 天累计骑行 230 公里 / TSS 累积 320 / 状态 OK。
今天天气适合骑车但湿度高 + 有雾 / 建议缩短到
60-75 分钟稳定 Zone 2 / 避免节奏骑和冲刺。注意补水。

【训练决策】恢复一般 / 适合低中强度有氧堆量

60-75 分钟 / 限制 Zone 2 / 避免 Zone 4 以上 /
若体感灼热降到 Zone 1-2 恢复骑

           （DeepSeek 已更新 06:00 / 刷新按钮）
```

### 1.2 三层用户看到不同内容

| 用户类型 | 看到的内容 |
|---|---|
| **full_data**（接 Strava ≥ 6 周 + 有功率或心率） | 全 4 段卡片（上图）|
| **partial_data**（接了 Strava 但 < 4 周历史） | 天气 + 本周累计 + 简单状态判断 / 不写训练负荷 |
| **no_data**（没接 Strava / 没活动） | 只看到天气 + 一句"接 Strava 看本周状态" |

### 1.3 关键约束

- **训练目标**用户在 profile 手动填一次（5 选 1：endurance / ftp / long_distance / weight_loss / fun）/ 留空 LLM 不写"今日目标"
- **状态 OK** 判断 = 看一周 TSS 累计 + 7 天 vs 28 天 TSB 对比 / **不假装有 HRV**
- 抄截图语言风格（数据驱动 / 专业 / 有用）/ **不抄"HRV 偏低、静息心率偏高"那种装作有数据的句子**

---

## 2. 数据架构

按 velo CLAUDE.md "防火墙式扩展 / 默认放新表 / 不动核心表"红线：

### 2.1 改动 1：user 表加 `training_goal` 字段

- String / nullable
- 5 选 1 枚举：endurance / ftp / long_distance / weight_loss / fun
- 用户在 profile 主动填 / 可改

### 2.2 改动 2：新建 `coach_outputs` 表

字段：

- `id` / `user_id` / `generated_at`（生成时间）/ `source`（morning_scheduler / manual_refresh）
- `cards_json`（4 段卡片完整 JSON）
- `weather_snapshot`（生成时的天气 JSON / 留底排查用）
- `load_snapshot`（生成时的 TSS/CTL/ATL/TSB JSON / 留底）

策略：每用户每天最多一条 / 同日重生成覆盖。

**为什么不复用 persona_outputs**：persona_outputs 设计是"短文案台账"/ text_snapshot 存的是单句字符串。教练总结是 4 段卡片 + 数据快照 / 强行塞 JSON 是 schema 漂移。

### 2.3 改动 3：训练负荷 / 天气都不存表 / 实时算 / 实时拉

- **训练负荷**：每次 worker 跑教练总结时 SQL 滑窗算 / 100 用户 × 6 周历史 = 毫秒级
- **天气**：每次跑教练总结调和风 API / 一天 ~50 次 × 50000/月免费额度 / 充裕
- 后续真慢了再加 `activity_load` 表 / 现在不做

### 2.4 改动 4：新建 Alembic 迁移 `coach_engine_init.py`

加 `user.training_goal` 字段 + 建 `coach_outputs` 表。

### 2.5 不动

- activity 表（核心表 / 防火墙红线）
- user 表已有字段
- persona_outputs 表（老 persona 完全晾着）
- 整个 `app/agent/persona/` 目录

---

## 3. 算法

### 3.1 训练负荷公式（行业标准 / 不发明）

```
TSS = (时长秒 × NP × IF) / (FTP × 3600) × 100
IF = NP / FTP
```

- velo activity 已有 `normalized_power`（FIT 自带 / GPX 无功率时为 NULL）
- velo user 已有 `ftp`
- 没功率 → 用 hrTSS（基于乳酸阈心率 LTHR ≈ 用户最大心率 × 0.85）
- 都没有 → 跳过这次活动不算 TSS

**CTL**（近 42 天体能 / 滑窗指数加权）：

```
CTL_today = CTL_yesterday × e^(-1/42) + TSS_today × (1 - e^(-1/42))
```

**ATL** 同公式 / 时间常数 = 7（近 7 天疲劳）

**TSB = CTL - ATL**（正值 = 状态好 / 负值 = 疲劳）

### 3.2 用户分层

```python
def classify_user(user, db):
    if not has_strava and activity_count_30d == 0:
        return "no_data"      # 看到天气 + 引导接 Strava
    if weeks_history < 4 or not has_power_or_hr:
        return "partial_data" # 看到天气 + 本周累计
    return "full_data"        # 完整 4 段卡片
```

### 3.3 状态判断（不假装有 HRV）

TSB 阈值用 TrainingPeaks PMC 公开标准（实施时再精确定 / 不凭设计稿现在拍）。3 档：

- 状态饱满（TSB > +X）
- 状态 OK（中间）
- 状态一般（TSB < -X）

全部基于 TSS·CTL·ATL·TSB / **不用 HRV / 不用静息心率**。

### 3.4 天气接入

和风天气 API：`https://devapi.qweather.com/v7/weather/now?location=lng,lat&key=...`

注意 `user.city` 当前是字符串（grep 过 / `app/user/models.py:104`）/ 要转经纬度。一次性查 + 缓存到 user 表新加 `lat / lng` 字段（或新建 `user_geo` 表）/ 实施时自己拍。

拿字段：温度 / 湿度 / 雾天气代码 501-509 / PM2.5 / 风速。

### 3.5 文件分布

新建 `app/agent/coach/` 整目录（参照 persona/ 结构 / 但完全独立 / 不互相 import）：

| 文件 | 干啥 |
|---|---|
| `training_load.py` | TSS / CTL / ATL / TSB 公式（纯函数 / 不查 DB）|
| `classifier.py` | 用户分层（纯函数）|
| `weather.py` | 和风天气 client（HTTP + 重试 + 错误兜底）|
| `prompt_builder.py` | DeepSeek prompt 拼装（4 段卡片）|
| `service.py` | 顶层流水线（try/except 兜底）|
| `router.py` | GET /api/coach/today endpoint |
| `models.py` | CoachOutput ORM |
| `MANIFEST.md` | 资产清单（参照 persona MANIFEST 写法）|

新建 `scripts/coach_morning_scheduler.py` —— 早上 6 点 cron 跑 / 给所有活跃用户生成当日 coach_outputs。

**复用**：DeepSeek client `app/agent/segment_writer.py`（已就绪）。

---

## 4. LLM 流水线

### 4.1 DeepSeek prompt 结构

```
你是一个数据驱动的骑行教练。根据用户当前训练数据、天气、训练目标，
给出今日骑行建议。语言风格：严肃、专业、有用，类似 TrainingPeaks
训练分析报告。不要嘲讽、不要空话、不要假装知道你没见过的数据。

输出严格 4 段 JSON：
- headline: 标题 10-20 字（如"低风险 Zone 2 有氧打底日"）
- analysis: 综合分析 80-150 字（融合训练负荷 + 天气 + 训练目标）
- decision: 训练决策卡 / 含 zone / 时长 / 强度 / 60-100 字
- warning: 恢复预警 / 风险提醒 30-80 字 / 没风险时 null

不假装有的字段：HRV、静息心率、睡眠、夜间恢复。
```

按 research subagent 建议：用 user prompt 不用 system prompt / 不塞 few-shot examples / 指令简洁。

### 4.2 数据 schema（按用户分层）

| 层 | 喂 LLM 的内容 |
|---|---|
| **full_data** | training_goal + ftp + 训练负荷（CTL/ATL/TSB/weekly_tss）+ 天气 + 最近 7 条活动摘要 |
| **partial_data** | training_goal + ftp + 天气 + 最近活动摘要（**不传训练负荷**）|
| **no_data** | 天气 + flag `prompt_strava_binding: true`（让 LLM 写引导）|

### 4.3 失败 fallback

| 失败类型 | 处理 |
|---|---|
| 和风天气 API down | 跳过天气段 / LLM 写"无天气数据"版 |
| DeepSeek API down / 超时 / 限速 | 写一条简单兜底文案到 coach_outputs（"今日天气 27° / 注意补水"）/ scheduler 下次 tick 重试 |
| 用户 city 拿不到经纬度 | 用全国默认或用户最近活动城市 / 或不写天气段 |
| Strava token 失效 | 该用户当日不跑 / 等下次 token refresh |
| coach_outputs 写表失败 | 不影响其他用户（每用户独立事务）|

**硬规则**：worker 跑教练总结**绝不阻塞其他业务**。任何失败 → log + 继续下一个用户。沿用 persona 宪法 §7.2 "失败不传染"原则。

### 4.4 用户手动刷新

```
POST /api/coach/refresh
```

- 速率限制：每用户每天 **4 次**（防刷爆 LLM 余额）
- 复用 generation pipeline / source 字段记 `manual_refresh`

### 4.5 整体流水线

```
早上 6 点 coach_morning_scheduler 跑：
  for user in 活跃用户:
    try:
      分层 → 拉天气 → 算训练负荷（仅 partial/full）
      → 拼 prompt → 调 DeepSeek → 解析 4 段 JSON → 写 coach_outputs
    except:
      log + 继续下一个用户

用户开 App → 动态 tab → 顶部大卡 → 点击 → "今天"页
拿 GET /api/coach/today → 显示
```

---

## 5. 前端 + 部署 + 测试 + 验收

### 5.1 前端

**新建**：

- `miniprogram/pages/today/today.{wxml,wxss,js,json}` —— 完整"今天"页 / 4 段卡片渲染
- `miniprogram/utils/coach_fetch.js` —— `fetchCoachOutput()` / `refreshCoach()` 两个 helper

**改动**：

- `miniprogram/pages/home/home.{wxml,wxss,js}` —— 顶部加大卡片 / 点击 `wx.navigateTo` 到 `/pages/today/today`
- `miniprogram/pages/profile/profile.{wxml,js}` —— 加 5 选 1 "训练目标"字段
- `miniprogram/app.json` —— pages 列表加 `pages/today/today`

### 5.2 部署

- `.env` 加 `QWEATHER_API_KEY=xxx`
- `docker-compose.yml` 加 `coach-scheduler` 容器（参照现有 `persona-scanner` 结构 / cron 表达式触发早上 6 点北京时间）
- 部署 SOP：和风天气 key 进 .env → `docker compose up -d --build` → `alembic upgrade head` → curl 真 endpoint 验证（按 velo CLAUDE.md 部署 SOP 4 步）

### 5.3 测试

- 单元：`tests/test_coach_training_load.py`（TSS/CTL/ATL/TSB 公式）/ `test_coach_classifier.py`（用户分层）/ `test_coach_prompt_builder.py`（schema 拼装）
- 集成：mock DeepSeek 跑完整 worker / 检查 coach_outputs 写入
- 真用回归（按 memory `feedback_real_usage_vs_mock_blindspot.md`）：Tim 自用 + 几个铁哥们 / 早上 6 点真跑一次 / 看 4 段卡片真实质量

### 5.4 验收标准

| 验收点 | 标准 |
|---|---|
| Tim 自己用 | 早上 6 点起床打开 velo / 动态 tab 顶部大卡看到当日教练建议 / 点开 4 段卡片 / 内容真实有用（不假装有 HRV / 不空话）|
| 其他用户 | 100 用户分层正确：有数据的 ~30 人看完整 4 段 / 4 周内数据的 ~40 人看简版 / 没数据的 ~30 人看天气 + 引导 |
| LLM 成本 | ~100 次/天 × 几分钱 ≈ ¥3-5/天 / 月 ¥150 / 在 Tim 能接受范围 |
| 错误率 | DeepSeek 调用失败率 < 5% / 失败用户当日看到兜底文案 / 不空白 |

---

## 6. 关键事实表（research 实证 / 防未来 agent 凭印象写错）

### 6.1 国内骑行 App 零 AI 教练（research subagent 2026-05-20）

- 行者 / 黑鸟 / 咕咚 / 啊咔单车 **全部没有 AI 教练**
- 国内 AI 教练 = 完整空白市场
- **但壁垒不在 AI 而在硬件**（HRV / 静息心率拿不到）

### 6.2 HRV / 静息心率 velo 永远拿不到（research 实证 / 永久不做依据）

- 微信小程序 `wx.getWeRunData` **只返步数** / 没心率没 HRV
- 微信小程序**不能直接调 Apple HealthKit**（开发者社区硬限制）
- Strava API 官方明文**不返 HRV / 静息心率 / 恢复评分**
- 蓝牙手环可连但每品牌协议不一 / 体验差
- HRV 真测 = Polar H10 胸带 / Garmin 手表（velo 用户里 < 3% 有）
- **结论**：Whoop / Garmin 模式的壁垒是硬件不是软件。velo 永久不做"假装有 HRV"的功能 / 装就崩塌

### 6.3 国际对标（research subagent 2026-05-20）

| 产品 | 关键特征 | velo 抄什么 |
|---|---|---|
| **TrainingPeaks** | 行业标杆 / 本身没 AI / PMC 图为主 | CTL/ATL/TSB 公式 |
| **TrainerRoad** | 真 ML 自适应 / 数百次仿真 / 结构化任务非自然语言 | （不抄 / 我们用 LLM 自然语言）|
| **Strava Athlete Intelligence** | 2025-2026 主推 / 生成式 AI 写"活动总结" / 数据解读 | **结构最像** / 抄 4 段卡片格式 |
| **Whoop Coach**（OpenAI 驱动）| 最接近截图风格 / 壁垒是手环 | （不抄 / 我们没手环数据）|
| **Garmin Daily Suggested** | 基于 HRV + Body Battery / 算法非 LLM / 短模板文案 | （不抄 / 我们没 HRV）|

### 6.4 中国可用天气 API（research 实证）

| API | 免费额度 | 关键字段 | 评估 |
|---|---|---|---|
| **和风天气（QWeather）** | **50000 次/月** | 温度/湿度/能见度/雾代码/PM2.5/空气质量 | **首选** |
| 心知天气 | QPS=1 | 湿度有 / PM2.5 需付费 | 适合缓存 / QPS 太低 |
| 高德地图 | 5000/天 | 仅温度/风向/风力（无湿度无 PM2.5） | 字段不够 |
| OpenWeatherMap | 1000/天 | 全字段 | 中国境内不稳 |

### 6.5 DeepSeek prompt 工程要点（research 实证）

- **用 user prompt 不用 system prompt**
- **不要塞 few-shot examples**
- **指令简洁**
- DeepSeek 中文输出稳定性 OK
- **真壁垒不是 prompt 写法 / 是输入数据丰富度**

---

## 7. 不做项（明确划出来防 scope creep）

- **HRV / 静息心率接入** → 永久不做（硬件壁垒 / 微信小程序拿不到 / 装作有 = 信任级事故）
- **RPE 主观体感**（用户每天填体感）→ 永久不做（research 判断中国用户对填表接受度低 / 留存差）
- **CTL/ATL/TSB 长期趋势可视化图** → v1.5+（不本 sprint）
- **用户自定义早上推送时间** → v1.5+
- **骑后教练复盘**（替代老登便利贴） → 下个 sprint（Sprint 12 之后）
- **AI 教练对话**（用户跟 LLM 聊训练） → v2+（区别于本设计：本设计是定时推 4 段卡片 / 对话是用户主动跟 LLM 互动）

---

## 来源追溯

- 2026-05-20 Tim + Claude brainstorm（这次对话 / brainstorm skill Step 1-5 走完）
- research subagent 调研：网络 + GitHub 实证（5 国际对标 + 中国天气 API + 微信小程序限制 + 算法公式 + LLM prompt 工程）
- 跟另一线 brainstorm（`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md` + `docs/prd/sprint-9-prd.md`）合并讨论：模块 D 规则版 → LLM 版
- 元教训：memory `feedback_decoration_vs_guidance_velo_persona_lesson.md`（装饰展示 vs 主动指导）+ memory `feedback_llm_application_hybrid_split.md`（高频日常算法 / LLM 涌现场景 / NPC 写一次读多次例外）
