# Sprint 12 骑后教练引擎 — 技术架构成果（2026-05-26）

> **本文档是什么**：把今晚 brainstorm 的思想，落成工程师能照着搭的**技术骨架**——架构图、字段级数据设计、算法、带数字的例子。
>
> **标注约定**：✅ 今晚明确讨论/拍定 ｜ 🔵 基于今晚方向的初步技术设计（表名/字段名是建议值，开工时细化）｜ 📊 现有字段（grep 实证带 file 出处）｜ ⛔ 暂不开工
>
> **产品哲学/金句**在 `coach-engine-design.md` v2，本文档只讲技术怎么搭。

---

## 1. 总体架构：四层流水线 ✅

```
┌─────────────────────────────────────────────────────────────┐
│  原始数据层（已有 📊）                                          │
│  trackpoints[].power/heart_rate/cadence/speed/distance/timestamp│
│  activities.normalized_power/snapshot_ftp/tss/splits           │
│  daily_training_load.ctl/atl/tsb/status_band                   │
│  segment_efforts.elapsed_time/avg_power/start_index/end_index  │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  第 0 层 守门员 gating（纯函数）✅                              │
│  判断"这份数据配不配得出可信洞察" → 不配就 STOP，这趟沉默       │
└──────────────────────────┬──────────────────────────────────┘
                           ↓ 够格的才往下
┌─────────────────────────────────────────────────────────────┐
│  第 1 层 算法挖矿（纯函数 / 运动科学）✅                        │
│  脱钩值 ｜ 功率画像查档判型 ｜ 跨活动模式叠加                    │
│  → 写入洞察表 🔵 activity_insights / user_power_profile /      │
│              user_patterns                                     │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  第 2 层 洞察筛选器 selector（规则）✅                          │
│  从所有算出的洞察里，选"这趟最该说的 1 条" + 严重度 + 锚点      │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  第 3 层 LLM 翻译（DeepSeek，单次调用，非 agent）✅            │
│  喂"洞察包"(结论+锚点+约束) → 输出"判断+意义+行动"人话          │
│  即时点评(算法模板)永远兜底；深度复盘(LLM)可超时回退           │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
              UX：一句判断 + 渐进披露（数字藏第二层）✅
```

| 层 | 输入 | 输出 | 实现 | 失败处理 |
|---|---|---|---|---|
| 0 守门 | 活动元数据 + 数据完整度 | 能算哪些洞察的布尔 | 纯函数 | — |
| 1 挖矿 | 轨迹/历史/best power | 洞察值（数字）| 纯函数（运动科学）| 算不出→不写 |
| 2 筛选 | 全部洞察 + 用户上下文 | 1 条焦点 + 锚点 | 规则 | 无可信洞察→沉默 |
| 3 翻译 | 洞察包 | 人话 | DeepSeek 单次 | 超时→回退即时点评 |

---

## 2. 两个场景 + 落点 ✅

| 场景 | 时间尺度 | 入口 | 首发洞察 | 存储 🔵 |
|---|---|---|---|---|
| **骑后洞察** | 单次活动 | 活动详情页 | 有氧脱钩（整趟级）| `activity_insights` |
| **能力镜子** | 跨 90 天 | "我的"页常驻 | 骑手类型画像 | `user_power_profile` |

> 注意：截图那种"全程/1km/平路1"分段 tab，对应的是**未来的智能努力段**，不是首发。首发骑后洞察是**整趟级**（脱钩），不做分段 tab。截图给的是 UI 形式参考，velo 首发的内容是整趟洞察卡。

---

## 3. 现有数据资产盘点（哪些字段喂给教练）📊

| 表 | 可复用字段 | 出处 | 给谁用 |
|---|---|---|---|
| `trackpoints` | power, heart_rate, cadence, speed, distance, timestamp | `activity/models.py:228-244` | 脱钩（前后半切）、模式挖掘 |
| `activities` | normalized_power, snapshot_ftp, intensity_factor, tss, avg_power, avg_hr, moving_time, duration, activity_type, splits(JSONB), power_zones | `activity/models.py:74-163` | 脱钩守门、上下文 |
| `daily_training_load` | ctl, atl, tsb, status_band(fresh/ok/tired/overreached), weekly_tss | `training/models.py:44-49` | 脱钩 cardiac drift 区分、上下文 |
| `segment_efforts` | elapsed_time, avg_speed, avg_power, start_index, end_index | `segment/models.py:149-156` | 同赛段历史对比（阶段1可选）|
| `users` | ftp, weight | Sprint 9 | 画像 W/kg、上下文 |
| best power 滑窗 | 180/300/600/1200/3600 秒 | `ftp_estimator.py:75` `_sliding_window_best_power` | 画像（缺 5s/60s 要补）|

---

## 4. 新建数据表（初步字段设计）🔵

按防火墙红线：新洞察放新表，不动 activities/users 核心表。

**`activity_insights`**（单次活动的洞察，骑后洞察用）
| 字段 | 类型 | 说明 |
|---|---|---|
| id / activity_id(FK) / user_id | | |
| insight_type | String | 'decoupling' 等（首发只有脱钩）|
| gate_passed | Boolean | 守门是否通过（false 则前端不显示）|
| decoupling_pct | Float nullable | 脱钩% |
| ef_first_half / ef_second_half | Float | 前后半效率 |
| drift_start_minute | Integer | 从第几分钟开始掉 |
| verdict_band | String | 'good'(<5%) / 'mild'(5-8%) / 'high'(>8%) |
| immediate_text | Text | 即时点评（算法模板）|
| llm_text | Text nullable | AI 深度复盘（LLM / 可后补）|
| computed_at | DateTime | |

**`user_power_profile`**（跨 90 天能力画像，能力镜子用 / 缓慢更新）
| 字段 | 类型 | 说明 |
|---|---|---|
| id / user_id | | |
| p5s / p60s / p300s / p_ftp | Float nullable | 各时长 best power (W)，90 天滚动 |
| wkg_5s / wkg_60s / wkg_300s / wkg_ftp | Float nullable | W/kg |
| coggan_band_* | String | 各时长在 Coggan 表的档位 |
| rider_type | String | 'sprinter'/'pursuiter'/'all_rounder'/'tt_climber' |
| data_completeness | JSONB | 哪些时长"未测"（如 5s 无全力数据）|
| updated_at | DateTime | |

**`user_patterns`**（跨活动模式，模式挖掘用 / 阶段1后期数据够了才填）
| 字段 | 类型 | 说明 |
|---|---|---|
| id / user_id | | |
| pattern_type | String | 'endurance_wall' / 'pacing_error' 等 |
| location | String | 如 '90min' / 'hr>165' |
| consistency | Float | 跨活动一致性（波动越小越可信）|
| sample_size | Integer | 基于几条活动（太少标"趋势性"不下定论）|
| updated_at | DateTime | |

---

## 5. 三个洞察：数据 → 算法 → 输出（字段级 + 带数字例子）

### 5.1 有氧脱钩 ✅算法 / 🔵字段

**输入**：
| 来源 | 字段 |
|---|---|
| `trackpoints`（对半切）| power[], heart_rate[], timestamp[] |
| `activities` | normalized_power, moving_time, activity_type |
| `daily_training_load` | tsb, status_band（区分疲劳）|

**守门条件（全过才算）**：
| 条件 | 阈值 | 数据来源 |
|---|---|---|
| 时长够 | moving_time ≥ 20min | activities |
| 稳态 | VI = NP/avg_power ≈ 1（如 <1.05）| 算 |
| 非间歇 | activity_type 不是间歇/比赛 | activities |
| 强度阈下 | 平均强度 < FTP | activities/算 |

**算法**：`EF1 = NP前/HR前`，`EF2 = NP后/HR后`，`脱钩% = (EF1−EF2)/EF1 × 100`

**带数字例子**：
```
某活动：120min 稳态骑
  前 60min：NP=180W，avg_HR=145  → EF1 = 180/145 = 1.241
  后 60min：NP=178W，avg_HR=152  → EF2 = 178/152 = 1.171
  脱钩% = (1.241−1.171)/1.241 × 100 = 5.6%
守门：moving_time=120≥20 ✅ / VI=1.02 ✅ / type=Ride ✅ / 阈下 ✅ → 通过
判读：5.6% 落 'mild'（5-8%）
cardiac drift 检查：tsb=-5/status_band='ok' → 非疲劳态，脱钩可信
输出：verdict_band='mild', drift_start_minute=88
```

### 5.2 骑手类型画像 ✅算法 / 🔵字段

**输入**：90 天滚动 best power @ 5s/60s/300s/1200s（300s/1200s 现成，5s/60s 补滑窗）+ user.weight + Coggan 基准表（男女各 ~52 行）

**算法**：每时长 W/kg → 查 Coggan 档位 → 四点连线斜率判型

**带数字例子**：
```
90 天 best power：5s=未测, 60s=620W, 300s=290W, 1200s≈FTP=250W
体重 70kg → W/kg：5s=未测, 1min=8.86, 5min=4.14, FTP=3.57
对照 Coggan 男表：
  1min 8.86 → Good~Very Good（8.17~8.97）  ← 相对强
  5min 4.14 → Moderate~Good（3.98~4.60）
  FTP  3.57 → Moderate~Good（3.29~3.82）   ← 相对弱
连线：中段(1min/无氧)突出、FTP(耐力)偏弱 → 偏「追逐型 pursuiter」
data_completeness：{"5s":"未测"} → 前端提示"冲 15 秒解锁完整画像"
绝对档位（藏第二层）：整体 Good 区
```

### 5.3 跨活动模式挖掘 ✅算法 / 🔵字段 / ⛔数据不够暂不做

**输入**：同类活动集合（activity_type=Ride 且 moving_time≥90min）的归一化曲线

**算法**：① 同类归组 ② 每条按进度 0-100% 对齐、聚合效率曲线 ③ 找反复 + 低波动的拐点

**带数字例子**：
```
同类组：Ride 且 ≥90min，近期 n=3 条
对齐：每条归一化 0-100%，叠加效率(功率÷心率)曲线
发现：3 条都在 85-95% 进度（≈90min）效率降 >5%，波动小
输出：pattern_type='endurance_wall', location='90min',
      consistency=高, sample_size=3
⚠️ sample_size=3 偏少 → 标"趋势性"，措辞用"看起来"不用"你的天花板就是"
```

---

## 6. LLM 上下文包（六层 / 真实字段 JSON）✅结构

**喂给 DeepSeek 的不是原始数据，是嚼好的结论包**：
```json
{
  "user":      {"rider_type":"pursuiter","ftp":250,"weight":70,"training_goal":"endurance"},
  "state":     {"tsb":-5,"status_band":"ok"},
  "activity":  {"type":"Ride","moving_time_min":120,"gate_passed":true},
  "insight":   {"type":"decoupling","value_pct":5.6,"drift_start_min":88,"band":"mild"},
  "pattern":   {"type":"endurance_wall","location":"90min","sample_size":3,"confidence":"low"},
  "directive": {"focus":"endurance_wall","severity":"mid",
                "anchors":["第3趟","90分钟"],"tone":"差距+路径","max_chars":50}
}
```
**LLM 输出**（深度复盘）：
> "你连续第 3 趟在 90 分钟后掉效率了——不是这次的事，是你的耐力天花板就卡在 90 分钟。接下来几周往长里堆 Z2，先把这堵墙往后推。"

**即时点评（算法模板兜底，不调 LLM）**：
> "这趟稳态骑后半段效率略降，属于正常波动，继续保持节奏。"

---

## 7. 前端结构（参考截图范本 → velo 骑行版映射）🔵

截图给的是 UI 形式，velo 首发内容是整趟洞察（非分段）：

| 截图元素 | velo 骑行版 | 数据来源 |
|---|---|---|
| 顶部数据卡（距离/时长/配速）| 距离/时长/速度 + **效率指数(功率÷心率)±全程%** | activities + trackpoints |
| tab（全程/1km/平路1）| 首发只做「全程」；分段 tab = 未来智能努力段 | — |
| 绿色「即时点评」| `activity_insights.immediate_text`（算法模板）| 第 1 层 |
| 蓝色「AI 深度复盘」| `activity_insights.llm_text`（DeepSeek）| 第 3 层 |
| "响应超时保留即时点评" | LLM 超时 → 前端显示 immediate_text | 兜底 |
| 「阶段建议」三类 | 后半程节奏/动作/衔接 → 骑行版：配速/发力/下段 | LLM 输出结构 |

---

## 8. 数据闭环 4 阶段（现有/缺口/能做什么）✅

| 阶段 | 对比类型 | 数据前提 | velo 现状 |
|---|---|---|---|
| **阶段 1（数据已全就位）** | 跟过去的自己 / 跟你在某赛段的历史 / 跟科学规范 / 跟你的目标 | 个人+地理 | ✅ 全有 |
| 阶段 2 | 跟相似的人 / 跟你关注的人 | follow 表 | ❌ 无 |
| 阶段 3 | 跟圈子 / 约骑伙伴 | 俱乐部/约骑表 | ❌ 无 |
| 阶段 4 | agent：多维关联、对话、跨维因果 | 前三阶有序 | ❌ |

> velo 现 12 张表，社交关系（follow/俱乐部/约骑/路书/社交圈）**全无**。洞察上限 = 数据下限。

---

## 9. 暂不开工 + 开工前提 ⛔

**Tim 拍：现在不开工。** 两个前提没就位：
1. **数据飞轮没转起来**：100 用户量级，跨活动模式（§5.3）叠不出可信规律 → 现在只能做单次洞察（§5.1）+ 静态画像（§5.2）。
2. **社交/地图接口没建**：阶段 2/3 无数据源（follow 表都没有）。

**开工信号**：活跃用户人均同类活动 ≥ N 条（模式可信）+ 社交线起来（人际对比有源）。在那之前：**让用户骑、攒数据**（飞轮 = 护城河）。

**真正开工时第一步**：把本文档 🔵 部分（表名/字段名）逐一拍定 → 转 `docs/prd/sprint-12-prd.md` → 走 spec 双审。

---

> 配套：思想/金句 → `coach-engine-design.md` v2 §0-7；记忆 → `project_velo_sprint12_coach_vision` + `feedback_ai_coach_product_principles`。
