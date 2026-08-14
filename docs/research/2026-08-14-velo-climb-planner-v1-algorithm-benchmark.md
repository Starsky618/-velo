# VELO Climb Planner v1：算法基准与可实现合同

日期：2026-08-14

状态：外部一手资料基准 + 已实现 v1 机械内核 + 已接入整坡/半坡 typed gate；西山 25 条物理道路轴已用生产落库 GLO 快照完成 50 个方向重放

## 一句话结论

VELO 不应只接入一套 Cat 1–4 / HC 标签，而应补成一条完整的纵向路线认知链：

```text
版本化高程证据
  → 有向连续爬坡检测
  → 客观 Cat 分类 + 独立坡型
  → 一条路线的有序爬坡组成
  → 基于骑手功率持续时间的耗时与配速规划
  → 分层置信度和可校准反馈
```

Garmin 与 Strava 公布的类别公式适合作为兼容基准，但它几乎退化为“净爬升量级”，不能区分长缓坡、稳定坡、阶梯坡和末段墙。VELO v1 的新增价值应是：保存同一物理几何一次，按 traversal 重新识别爬坡；同时解释“坡有多大”“坡长什么样”“它在整条路线第几个出现”“这个骑手要花多久、怎样分配功率、结论有多可靠”。

“世界最先进”只能作为产品目标，当前不能当成已经证明的事实。公开资料没有披露 Garmin 的完整起终点检测源码，VELO 也不应复制厂商 UI；可验证目标应是：覆盖公开产品能力，并在坡型、方向、多爬坡组成、个性化规划和不确定性上给出更完整、可审计的实现。

## 1. 外部基准：官方规则与未公开部分

### 1.1 Garmin ClimbPro / Climb Explore 公开事实

Garmin Edge 官方手册说明，ClimbPro 会给出爬坡出现位置、平均坡度、总爬升；进入当前爬坡后给出剩余距离、剩余平均坡度、当前坡度和剩余爬升，并在骑行后保存 climb splits。[Garmin Edge 550 Owner's Manual — Using ClimbPro](https://www8.garmin.com/manuals/webhelp/GUID-5951C9F9-0E2E-4ECC-A508-6F93D026685D/EN-US/GUID-EBAEC138-B55A-4730-8C10-DF21A40302A9.html)

Garmin 公开的爬坡识别最低条件是三项同时满足：

- 长度至少 500 m；
- 平均坡度至少 3%；
- `climb_score = length_m × average_grade_pct` 至少 1,500。

官方还明确说，一段爬坡中可以包含平路或下降，只要整段平均坡度仍不低于 3%，仍可作为一段爬坡。[Garmin Support — What is the ClimbPro Feature on an Edge Device?](https://support.garmin.com/en-GB/?faq=KKRLD2Fo6MAlCXOzUZb1e9)

Garmin 公布的类别阈值为：

| 类别 | climb score，严格大于 |
|---|---:|
| HC | 80,000 |
| Cat 1 | 64,000 |
| Cat 2 | 32,000 |
| Cat 3 | 16,000 |
| Cat 4 | 8,000 |
| Uncategorized | 1,500 |

Climb Explore 还支持按附近距离、爬升、长度、坡度、类别和路面类型浏览；自由骑模式会根据当前行进方向预测前方道路，遇到分支后可更新实际选择的爬坡 profile。[Garmin Support — ClimbPro: Tethered Versus Free Climbing](https://support.garmin.com/en-CA/?faq=zdggRttcfT4PGwTbfifMY5)

但 Garmin 没有公开以下实现细节：

- 高程曲线如何滤噪；
- 一个局部最低点和最高点何时成为正式起终点；
- 两段上坡之间多深、多长的下降才必须拆开；
- 多个重叠候选如何消歧；
- 个性化耗时或功率规划公式。

因此这些部分不能标为“Garmin 规则”，只能由 VELO 建立自己的版本化、可回放定义。

### 1.2 Strava 与职业赛事能提供什么

Strava 对已存在 segment 的分类同样使用 `length_m × grade_pct`，从 Cat 4 的 8,000 到 HC 的 80,000；它没有 Garmin 的 1,500–8,000 `Uncategorized` 层。Strava 还明确区分：它的公式是固定客观分类，而环法等赛事的分类存在赛段位置等主观语境。[Strava Support — Climb Categorization](https://support.strava.com/en-us/articles/15402015-climb-categorization)

环法官方赛段页把整条路线表达成有顺序的多坡组合。例如 2026 Stage 19 依次列出 Cat 2、Cat 1、Cat 2 和终点 HC，而不是只给全程累计爬升。[Tour de France — Stage 19](https://www.letour.fr/en/stage-19)

对 VELO 的直接含义是：

- Cat 只描述一段道路的客观量级，不应根据骑手水平改变；
- 路线难度不能压成一个 Cat 或总爬升，必须保留每段坡及其出现顺序；
- “前面已经骑了什么、两坡之间能否恢复、最后是不是顶峰终点”属于 route context，不应篡改基础 Cat。

### 1.3 官方类别的已知盲区

Garmin Connect 官方支持页明确指出，climb category 不考虑海拔高度、坡度波动和路面；同一类别可以是一条短陡坡，也可以是一条长缓坡。[Garmin Support — Planning Course Climbs in Garmin Connect](https://support.garmin.com/en-US/?faq=5Y8GPTBEYxAd4jtWebIXG9)

若 VELO 采用

```text
average_grade_pct = 100 × net_gain_m / length_m
climb_score       = length_m × average_grade_pct
```

则算术上有：

```text
climb_score = 100 × net_gain_m
```

也就是说，基础类别几乎只编码净爬升，没有编码坡长、坡度分布、墙段位置和恢复段。它适合做通用标签，不足以回答骑手真正关心的“这坡怎么虐、要顶多久”。

## 2. VELO v1 的事实边界

下面分清三种来源，避免把设计推导冒充行业标准。

| 项目 | 性质 | v1 处理 |
|---|---|---|
| 最短 500 m、均坡至少 3%、score 至少 1,500 | Garmin 官方公开规则 | 作为兼容识别门 |
| Cat 4 / 3 / 2 / 1 / HC 阈值 | Garmin、Strava 官方公开规则 | 保存 `category_system` 与版本 |
| 平路/短下降可属于同一爬坡 | Garmin 官方公开行为 | 允许父爬坡包含 recovery section |
| 具体起终点、合并/拆分 | 厂商未公开 | VELO 自有确定性算法 |
| 长缓、稳定、阶梯、前墙、后墙、短墙 | VELO 解释层 | 由原始坡度结构机械派生 |
| 反向重新识别 | VELO 领域约束 | 同一几何反转样本后重跑，不能只交换爬降 |
| 多坡组成与疲劳传递 | VELO 规划层 | 保留顺序、坡间恢复和累计负担 |
| FTP / PDC / CP / W' 个性化 | 论文支持的模型组件 | 仅在个人输入充分时启用 |
| “能否完成”“预计耗时” | VELO 预测 | 输出区间与证据质量，不作无条件承诺 |

### 2.1 先分清三种对象

VELO 后续不得再把下面三种对象压成一个“路线”：

1. **RouteGuide** 是内容介绍。生产现有 11 条旧路线属于这一层；名字、文字、总距离或一条无海拔 GPX 都不能证明它是一条完整爬坡。
2. **Named Climb** 是骑手共同认知的固定有向爬坡，例如“从哪一个公认基座开始，到哪一个公认坡顶结束”。它的身份边界先由道路、锚点和本地语义证明。
3. **Climb Occurrence** 是 Climb Planner 在完整有向高程剖面上检测出的地形爬升区间。它可能只占 Named Climb 的一部分；一条 Named Climb 也可能因真实长下降被拆成多段 occurrence。

因此，“完整奥申”和“算法检测到的一段 Cat 3”不是同义词。先证明输入覆盖完整奥申，再在该 traversal 上检测有几段坡、各是什么 Cat 和坡型。

### 2.2 整坡 / 半坡输入硬门

每个准备进入真实 Climb Planner 的命名坡，先冻结以下身份合同：

```text
named_climb_key / canonical_name
physical_axis_hash / traversal_direction
base_anchor / summit_anchor
extent_status = full_verified | full_candidate | partial | unknown
parent_named_climb_key + start/end offsets（partial 时必填）
geometry_coverage_ratio / elevation_profile_coverage_ratio
profile_fact_id / profile_hash / elevation algorithm version
```

只有同时满足以下条件，才能标 `full_verified`：

1. base 和 summit 是命名坡的真实语义锚点，不是“某条赛段刚好从这里开始/结束”；
2. 同一条连续有向物理几何从 base 覆盖到 summit，没有缺口、跳线、立即折返或重复累计；
3. 逐点高程与该几何同轴、同方向，覆盖率至少 99%，并通过 profile 质量门；
4. 正反方向分别建立 Traversal；反向必须反转剖面后重新检测，不能复制正爬 Cat；
5. 多个长短 Strava 赛段只投影为身份、局部热度或 effort 证据，不能投票决定整坡边界；
6. 入口存在多种本地公认上法时，分别建立 named-climb variant，不把两条 approach 拼成一条“平均整坡”。

以下任一情况只能标 `partial` 或 `unknown`：缺 base、缺 summit、只覆盖末段墙/前段、赛段端点尚未绑定地标、只有总爬升没有逐点 profile、旧 GPX 与当前 canonical axis 未对齐。半坡仍可分析其已观察区间，但产品必须显示“从半坡开始”；若它嵌套于 full top-level occurrence，则只保存为 child ramp，不另给第二份 top-level Cat，也不重复累计爬升。

`app/elevation/climb_profile_contract.py` 现已把上述身份合同接在 Climb Planner 前：完整输入剖面、完整命名坡、普通走廊、身份候选和完整长路线组合分别出具不同布尔门。底层 `build_climb_plan()` 仍只负责地形；真实西山批处理和生产投影只能走合同包装器。半坡缺少 `parent_scope_key`、覆盖率低于 99%，或普通走廊冒充命名整坡都会 typed reject。

### 2.3 旧 11 条 RouteGuide 的退役账

2026-08-14 对生产公开 API 与仓库 `content/routes/` 逐条回读：确有 11 条旧 RouteGuide，且 11 条全部 `climb_plan=pending`。其中 6 份旧 GPX 全部没有逐点海拔，现已从内容目录删除；`guide.md` 与照片继续保留。路线几何改由 `scripts/publish_climb_routes.py` 从完整 Strava source observation 和同轴落库 GLO snapshot 原子投影。

| 旧路线 | 当前几何/海拔事实 | 进入整坡 ClimbPro 前的结论 |
|---|---|---|
| 奥申 | 旧 267 点 GPX 已退役 | o27 完整轴及逐点 GLO snapshot 已重放，正式结果 Cat 2 / 末段墙 |
| 横岭 | 旧 518 点 GPX 已退役 | o2 完整轴及逐点 GLO snapshot 已重放，正式结果 Cat 2 / 末段墙 |
| 环太原汾河自行车道 | 无正式 RouteBook/GPX | 不是命名爬坡，不套 ClimbPro 模板 |
| 崛围山 | 旧 Guide 无正式 RouteBook | o14 崛围山—多福寺完整赛段剖面已重放，Cat 2 / 短陡墙；canonical base/summit 仍按 `full_candidate` 展示 |
| 狼坡 | 旧 228 点 GPX 已退役 | o38/o42 是正反整轴；正式结果 Cat 3 / 短陡墙，局部邀月阁/前段只作 child evidence |
| 庙前山 | 无正式 RouteBook/GPX | o73 仍是 1812 top/228 台身份候选，未闭合前不得称完整庙前山 |
| 清徐夜骑 | 旧 160 点 GPX 已退役 | 社交/夜骑路线，不是西山命名爬坡；不拿它生成 ClimbPro |
| 天龙山盘山公路 | 旧 411 点 GPX 已退役 | 已拆成东侧、北侧、牛家口南线和西门起伏四个对象，分别重放 |
| 启春阁 | 旧 110 点 GPX 已退役 | 仍是独立目的地内容；没有 Strava/GLO 身份绑定前不借奥申 o27 替换 |
| 小西沟 | 无正式 RouteBook/GPX | 先闭合道路身份与 base/summit |
| 玉泉山 | 旧 Guide 无正式 RouteBook | 南侧主爬 o15 与石膏厂入口 o88 分别重放，不能合并 |

经典杜关不在这 11 条旧 RouteGuide 里。当前研究态 o23 表示“杜儿坪—太古路”的经典杜关整轴候选；新修杜关旅游公路是另一条道路对象，不能共享一份 Cat 或完整性结论。

### 2.4 西山全轴 3D 重放结果

`data/research/xishan_climb_catalog_v1_result.json` 是公开安全结果：不含来源经纬度，但保留每条轴正反方向的距离—海拔曲线、GLO 总爬降、ClimbPro occurrence、Cat、坡型、500m/1km 持续坡度、child ramps 与完整 hash 链。私有 exact source geometry 只存在证据账和生产数据库。

- 25 条物理轴全部重放正反方向，共 50 份有向结果；目前只有横岭、奥申、狼坡 3 条在内容证据中明确绑定 canonical base/summit，标 `full_verified`；其余 15 条命名坡虽有完整赛段剖面，但 canonical 锚点证据仍不足，严格标 `full_candidate`。另有 5 条普通走廊、王封一线天景观核心轴和身份待确认的庙前山 o73。
- 狼坡 o52/o95、奥申 o103、经典杜关 o60/o72/o94 共 6 个已知半坡/局部段，均绑定父坡与轴上 start/end offsets，从父轴同一份 GLO snapshot 裁切重放；它们不另存物理几何，也不重复累计成第二条整坡。
- 奥申为 Cat 2、5.225 km、GLO +343.3m、末段墙，最难持续 1km 约 11.5%；狼坡为 Cat 3、3.415 km、+271.7m、短陡墙，最难持续 1km 约 11.6%。两者都不再描述为“稳定主爬”。
- 经典杜关为 Cat 2、9.286 km、+551.2m、阶梯坡；它和 14.9km 新杜关旅游路仍是两个对象。
- 枣杜 exact o116 为 8.825 km、GLO +469.9m，正向检测为 Cat 2 candidate / 长持续坡，最难持续 500m/1km 为 9.1%/8.4%；canonical 命名 base/summit 尚未闭合，所以只能标 `full_candidate`。
- 新杜关 exact o117 为 15.023 km、GLO +296.8/-13.3m，但全轴平均缓、夹有起伏，正反方向都没有合格 ClimbPro occurrence。它以 `road_corridor/not_applicable_corridor` 保存完整 3D profile，不能因距离长或累计上升接近 300m 就硬贴 Cat，也不能借经典杜关 o23 的身份与局部坡证据。
- 现有真实连接组成 10 条完整 profile 长路线并重跑多坡顺序；另 1 条太古路—店头—蒙山—北侧—西门因立即完整反向重走被 typed reject，没有进入工作量或排序。
- 生产发布器会把排除庙前山身份候选后的 24 条轴发布成 48 个有向 RouteBook；每个方向都携带对应 ClimbPlan。上述 10 条组合也会保存完整路线几何、3D profile 和 ClimbPlan，但它们使用的腾讯 TransitPath 仍是 `provider_path_not_bicycling_verified` / `connectivity_shadow_not_access_verified`：发布器必须将其保持为 `unlisted + draft + navigation pending`，写入 typed warning，不能进入公开列表或导出。只有连接段自行车准入另行验证后才能升级成公开长路线。
- stored GLO 爬降是权威总量；ClimbPlan occurrence 来自已落库逐点 snapshot 的确定性重放。两者都没有发起新 GLO 查询，重放因再次做坡型平滑可能与 stored 总量有数米差异，结果同时保留两列，不能偷偷择优。

## 3. 连续爬坡检测：可实现的 v1

### 3.1 输入不是一张缩略图

检测输入必须绑定到一条 canonical physical geometry 和一个 traversal：

```text
geometry_hash
traversal = forward | reverse
distance-indexed elevation samples [(s_m, elevation_m)]
elevation_source / algorithm_version / profile_hash
sampling_interval_m / smoothing_version / quality metadata
```

页面为了绘图下采样到 100 个点的 profile 不能反过来作为算法输入。GLO/DEM 只能发布其分辨率支持的持续坡度；v1 对 GLO 默认发布 500 m、1 km 窗口，不发布“精确 100 m 最大坡度”。只有经过校验的高分辨率 FIT/气压计数据，才允许增加 100 m、250 m 窗口，并必须标来源。

### 3.2 有向 profile 与反爬

canonical geometry 只保存一次。正向样本为 `z(s)`；反向 traversal 使用：

```text
s_reverse = total_length - s
z_reverse(s_reverse) = z(s)
```

随后完整重跑检测、分类和坡型。一个正向 Cat 2 爬坡反向后可能完全消失，也可能因道路起伏生成若干较小爬坡；绝不能把正向 occurrence 复制一份、只交换 ascent/descent。

### 3.3 去噪与多尺度稳定性

v1 建议：

1. 沿距离等间隔重采样，基准间隔 20 m；
2. 对 elevation 而不是逐点 grade 做距离域平滑，基准窗口 100 m；
3. 同时运行 80 / 100 / 150 m 三个检测变体，只把 100 m 结果作为主结果，另外两个用于边界稳定性；
4. 用 `MAD(raw_elevation - smoothed_elevation)` 估计局部噪声，转折点 prominence 门取 `max(15 m, 3 × MAD)`；
5. profile 缺口不插成确定事实；跨缺口的 occurrence 必须降级或拒绝。

上述窗口和 prominence 是 **VELO v1 初始参数**，不是 Garmin/UCI 标准；必须通过西山已知坡和未来城市 holdout 校准。

### 3.4 候选区间与消歧

在平滑后的有向曲线上识别满足 prominence 的局部最低点和后续局部最高点。每个“最低点 → 后续最高点”是候选 interval，只有同时通过三条 Garmin-compatible 门才进入候选集：

```text
length_m >= 500
average_grade_pct >= 3
climb_score >= 1500
```

候选消歧分两层：

1. **硬 recovery split**：若两次上升之间的回落深度大于 `max(20 m, 3 × MAD)`，并且下降/平缓区长度至少 500 m，则拆成两个 top-level climb；这两个阈值是 VELO 初值。
2. **父爬坡 + 内部结构**：未达到 hard split、且合并后仍满足平均坡度门时，保留为一个 top-level climb，把平路、短下降和重新抬升记录成内部 `recovery_section` / `ramp_section`，不丢失“阶梯”结构。

对无 hard split 的重叠候选，使用确定性 interval selection：

1. 优先覆盖更多已分类净爬升；
2. 再优先更高 climb score；
3. 再优先边界在三个平滑变体中更稳定；
4. 最后优先更少的 top-level occurrences。

可用 weighted interval scheduling 实现，选择互不重叠的 top-level occurrence。被父爬坡包含的短陡段不作为第二次爬升累计，而作为 child ramp 保存。若 80 / 100 / 150 m 变体产生不同 merge/split，主结果仍确定，但 `boundary_status=ambiguous` 并保存 alternative partition 摘要。

### 3.5 为什么必须有 child ramp

只有 top-level Cat 会把“奥申全段”和“奥申末段墙”压扁。child ramp 至少保存：

```text
start_offset_m / end_offset_m
length_m / gain_m / loss_m
rolling_grade_500m / rolling_grade_1km
position_fraction_in_climb
section_role = ramp | recovery | descent_inside_climb
```

它不是第二条重复赛段，也不重复累计爬升，而是解释父爬坡内部结构。

## 4. 客观分类与坡型必须分开

### 4.1 兼容类别

每个 occurrence 保存：

```text
average_grade_pct
climb_score
category
category_system = garmin_public_2026 | strava_public_2026
category_version
```

Garmin-compatible 模式包含 `uncategorized`；Strava-compatible 模式只在 score > 8,000 时给 Cat 4 以上标签。阈值使用严格 `>`，正好落在阈值上的值不擅自上调。

### 4.2 先保存坡型事实，再派生中文标签

基础坡型事实至少包括：

- 500 m / 1 km rolling grade 的 p10、p50、p90 与 IQR；
- `max_sustained_grade_500m`、`max_sustained_grade_1km` 及位置；
- 低于 1%、1–3%、3–6%、6–9%、9–12%、12%+ 的距离占比；
- occurrence 内累计下降、最长恢复段、恢复段数量；
- 最难 500 m 位于前 25%、中间 50% 还是最后 25%；
- 起点到最难段之前已有的爬升和距离。

中文坡型标签由版本化规则派生，而不是人工凭印象写：

| 标签 | VELO v1 初始规则，不是行业标准 |
|---|---|
| `long_gentle` 长缓坡 | 长度至少 8 km，均坡 3–6%，500 m p90 < 8% |
| `steady` 稳定坡 | 500 m rolling grade 的 p90-p10 ≤ 3%，内部下降 < 总爬升 5% |
| `staircase` 阶梯坡 | 一个父爬坡内至少有两个未触发 hard split 的 recovery sections |
| `short_wall` 短墙 | 长度不超过 4 km，且最难持续 500 m ≥ 10% |
| `early_wall` 前墙 | 最难 500 m 位于前 25%，且比全段均坡至少高 4 个百分点 |
| `late_wall` 后墙 | 最难 500 m 位于后 25%，且比全段均坡至少高 4 个百分点 |
| `mixed` 混合 | 未稳定命中以上规则 |

标签可以多选，例如 `Cat 2 + late_wall + staircase`。只发布 Cat 2 会掩盖末段墙，只发布“虐坡”又无法跨城市比较。

## 5. 一条路线由哪些坡组成

`RouteClimbComposition` 必须保存 ordered occurrences，而不是只把 ascent 求和：

```text
route_geometry_hash / traversal
ordered_climb_occurrence_ids
for each climb:
  route_start_km / route_end_km
  cumulative_distance_before_m
  cumulative_ascent_before_m
  distance_from_previous_climb_m
  descent_from_previous_climb_m
  predicted_recovery_time_s (仅个性化计划层)
finish_type = summit | descent | rolling | flat
categorized_ascent_m / uncategorized_ascent_m
unobserved_profile_distance_m
```

分类本身不随赛段位置改变；位置只进入 context。用户看到的解释应类似：

```text
Cat 2 长爬 → 8 km / 220 m 下降恢复 → Cat 3 短墙 → Cat 4 终点坡
```

这样才能区分“单独骑一座 Cat 3”和“已经骑完两座 Cat 2 后再遇到同一座 Cat 3”。

## 6. 个性化耗时与功率规划

### 6.1 物理层：功率不是只除以体重

经典道路骑行功率模型把骑手和车看作一个系统，主要阻力来自重力、滚阻、气动阻力，并可加入加速和传动损耗。Martin 等人在实际道路功率数据上验证的模型与实测高度相关，论文报告 `R²=.97`、标准误约 2.7 W；同时指出空气密度、风、坡度、滚阻、总质量和 drag area 都会影响功率—速度关系。[Martin et al., 1998 — Validation of a Mathematical Model for Road Cycling Power](https://pubmed.ncbi.nlm.nih.gov/28121252/)，[公开全文](https://collections.lib.utah.edu/dl_files/b4/8e/b48ef26086091662c561e673d7bd990d77868437.pdf)

VELO 对每个 profile cell 使用准稳态基线：

```text
η P_rider =
    m_system g sin(θ) v
  + Crr m_system g cos(θ) v
  + 0.5 ρ CdA (v + headwind)^2 v
```

其中 `m_system = rider_mass + bike_mass + cargo_mass`。需要模拟加速时再加 `m_effective × v × dv/dt`。求给定功率下的正速度根，再得到 cell time。没有风、CdA、Crr 时必须跑 low/base/high 情景，不能把默认值冒充个人事实。

W/kg 仍是有用的骑手比较指标，但爬坡耗时计算必须用总系统质量；同样 3 W/kg 的骑手，车和装备不同，结果不会完全相同。

### 6.2 生理层：FTP 不能单独回答能顶多久

一项 87 名公路车手研究中，按 20 分钟测试估算的 FTP 对应总体 TTE 中位数为 44 分钟，四个水平组的中位数从 35 到 51 分钟不等；研究结论要求 FTP 与 TTE 对每个骑手分别评估。[Sitko et al., 2022 — Time to exhaustion at estimated functional threshold power](https://repositori.udl.cat/server/api/core/bitstreams/8919df7b-ca2d-4e24-929a-64038c8c2ced/content)

所以 rider model 至少保存：

```text
rider_mass_kg / bike_mass_kg / cargo_mass_kg
power_duration_curve: 5s, 1m, 5m, 12m, 20m, 40m, 60m ...
FTP value + protocol + measured_at + TTE_if_known
CP / W_prime + test protocol + measured_at (可选)
historical matched climb efforts
preferred cadence range / lowest gear (可选)
```

只有 FTP 时，输出宽区间和低置信度，不静态声明“Cat 2 对应 3.0 W/kg”。

### 6.3 CP / W' 处理墙段与重复攻击

Skiba 等人的 cycling 模型使用：

```text
P(t) = CP + W' / t
```

其中 CP 是临界功率，W' 是高于 CP 可消耗的有限做功能力；后续模型用低于 CP 的恢复强度和时间估计 W' 重建。[Skiba et al., 2012 — Modeling the expenditure and reconstitution of work capacity above critical power](https://pubmed.ncbi.nlm.nih.gov/22382171/)

该模型在 8 名训练有素的铁三运动员实地功率文件中区分了力竭与完成条件，原研究报告 ROC AUC .914；但样本很小，不能据此承诺对所有骑手精确。[Skiba et al., 2014 — Validation of a novel intermittent W' model for cycling using field data](https://pubmed.ncbi.nlm.nih.gov/24509723/)

VELO v1 的使用边界：

- 只在骑手有可信 CP/W' 参数时启用 W' balance；
- 高于 CP 的 cell 扣减 W'，低于 CP 的 cell 按明确版本的恢复模型重建；
- 没有个人 CP/W' 时不从 FTP 硬推一个假 W'；
- 输出 `model=cp_wprime`、参数来源和剩余 W'，不把它包装成医学安全保证；
- 未来必须用 VELO 自己的完成/爆掉历史做校准和 holdout。

### 6.4 路线级配速求解

对给定 rider intent，v1 可做离线离散优化，而不是给全坡一个平均瓦数：

```text
state      = route_cell, elapsed_time_bin, W'_balance_bin
decision   = target_power（例如每 5 W 一个离散档）
transition = 物理模型求 cell time；更新 W' 和累计做功
constraints:
  target_power <= rider power-duration feasible envelope
  W'_balance >= intent.reserve
  cadence/gearing feasible（数据存在时）
objective:
  completion: 最大化终点余量，再最小化时间
  steady:     限制功率波动与墙段透支，再最小化时间
  best_time:  在保留最小终点余量下最小化时间
```

先在一条 climb occurrence 内求解，再按 `RouteClimbComposition` 顺序穿过多坡和恢复区；也可以直接对全路线 cells 求解，后者更准确。输出不要只有一个“最佳”数字，而应给 2–3 个 hard-feasible 方案：保守完成、稳定发挥、挑战成绩。

若只有经验 power-duration points、没有 CP/W'，可以用单调 PDC envelope 约束每段平均功率，但不模拟恢复后的 W'；该结果必须标 `physiology_model=pdc_only`。

### 6.5 耗时输出

每段坡至少输出：

```text
predicted_time_low / base / high
target_power_range_w / target_w_per_kg
hardest_continuous_duration_s
time_above_CP_s / W'_remaining_at_summit（仅参数充分时）
minimum_cadence_or_gearing_risk（仅齿比充分时）
model_inputs / assumptions / confidence dimensions
```

耗时区间来自明确的输入情景或个人历史误差，不得没有统计依据却写“95% CI”。

## 7. 置信度不能压成一个分数

VELO 应分别输出以下证据状态：

### 7.1 profile quality

- `source`: GLO / verified FIT barometer / other；
- 采样间隔、缺口比例、profile hash；
- raw 与 smooth residual MAD；
- 是否存在重复点、突跳或不可能坡度；
- 允许发布的最短坡度窗口。

### 7.2 boundary stability

对 80 / 100 / 150 m 平滑变体重跑检测。匹配 occurrence 后计算区间 IoU：

```text
boundary_stability = median(interval_IoU_across_variants)
```

同时保存起终点最大漂移米数。若 merge/split 数量不同，不得仅给高分，必须标 `ambiguous` 并保存 alternative partition。

### 7.3 category stability

```text
category_stability =
  得到同一 category 的有效 profile 变体数 / 有效变体总数
```

分数靠近 8k / 16k / 32k / 64k / 80k 阈值，或 elevation source 不足时，显示 `Cat 2 candidate`，而不是伪装确定。

### 7.4 rider prediction quality

分别记录：

- power curve 覆盖目标耗时区间与否；
- FTP/CP/W' 距今多久、测试协议是什么；
- 系统质量是否完整；
- 风、CdA、Crr 是实测、个人校准还是默认场景；
- 是否有该骑手相似坡历史用于误差校准。

最终解释应保留这些维度，不用一个 0–100 总置信度掩盖缺口。

## 8. v1 数据模型

建议新增独立领域对象，不向 segment 主表堆临时字段：

### `ElevationProfileFact`

```text
id
physical_geometry_hash
elevation_source
algorithm_version
profile_hash
samples[(distance_m, elevation_m)]
sampling_interval_m
quality_metadata
created_at
```

### `ClimbDetectionRun`

```text
id
profile_fact_id
traversal
detection_version
parameters
input_hash / result_hash
status
```

### `ClimbOccurrence`

```text
id
detection_run_id
start_offset_m / end_offset_m
length_m / gain_m / loss_m
average_grade_pct / climb_score
category / category_system / category_version
boundary_status / boundary_stability / category_stability
child_section_ids
```

### `ClimbShapeFact`

```text
climb_occurrence_id
grade_window_version
rolling_grade_statistics
grade_band_distance_shares
embedded_descent_m
recovery_sections
hardest_window_locations
shape_tags / shape_rule_version
```

### `RouteClimbComposition`

```text
route_candidate_id
route_geometry_hash / traversal
ordered_occurrences with route offsets
inter_climb recovery facts
finish_type
composition_version / input_hash
```

### `RiderPowerProfile`

```text
rider_id
body / bike / cargo mass
power_duration_points
FTP + protocol + TTE
CP / W' + protocol
gearing / cadence
measurement dates / source / quality
```

### `ClimbPlan`

```text
route_climb_composition_id
rider_power_profile_version
intent
environment_scenarios
physics_model_version / physiology_model_version
ordered target-power cells
per-climb time and burden
route total time range
assumptions / confidence dimensions
input_hash / result_hash
```

`ClimbOccurrence` 是 geometry + traversal + elevation version 的派生事实，不是 Strava segment；赛段只提供发现、热度或历史 effort 证据。

## 9. 最小实现顺序

1. **检测与回放**：从现有 GLO profile 生成有向 `ClimbOccurrence`，冻结算法参数、输入 hash 和输出 artifact。
2. **类别与坡型**：实现 Garmin/Strava-compatible 类别、500 m / 1 km 持续坡度和多标签 shape；先不碰个体功率。
3. **路线组成**：把每个 RoutePattern 展开为 ordered climbs，反向路线独立重跑；保持无坡 transit 为 unobserved，而不是零难度。
4. **物理估时**：以 rider/system mass + PDC + low/base/high 环境情景给出耗时范围。
5. **CP/W' 规划**：只对参数充分骑手启用多坡疲劳和恢复；保存模型版本和终点余量。
6. **真实校准**：用 VELO 活动中的实际爬坡 split、功率与完成/放弃结果做 calibration / holdout，不用一次西山样本宣称全国成立。

## 10. 必须通过的算法反例

至少冻结下列合成和真实坡型测试；它们检验通用语义，不需要为每条道路各写一套测试：

1. **稳定长坡**：5 km × 6%，应是一段 occurrence，shape=`steady`；
2. **前缓后墙**：全段 Cat 2，最后 1 km 明显更陡，应保留一个父 climb + `late_wall` child ramp；
3. **短墙**：3 km 左右、最难 500 m ≥10%，不能仅因 Cat 3 就解释成中等稳定坡；
4. **两坡分离**：中间有 ≥500 m 且超过噪声门的真实下降，应拆成两段；
5. **阶梯爬升**：短平路/小回落后继续上升，整体仍 ≥3%，应是一段父 climb + recovery sections；
6. **反向**：反转同一 physical geometry 后重新识别，正向 occurrence 不能原样存在；
7. **阈值稳定性**：score 在 8k/16k/32k 附近随平滑变体跨级，必须输出 candidate/ambiguous；
8. **缺失 profile**：允许几何和路线组合继续，但 climb facts 标 pending，不能伪造 0 climb；
9. **同坡不同骑手**：Cat 与 shape 完全相同，耗时、功率余量和适配结论可以不同；
10. **整条路线**：同一 Cat 3 单独骑与放在两座长坡之后骑，基础类别相同，route-context burden 不同。

## 11. 产品解释模板

每条真实选择先按骑手语言回答：

```text
这条路线由几段坡组成？各是什么级别？
每段是长缓、稳定、阶梯还是带墙？墙在哪里、要顶多久？
坡与坡之间有多少距离和下降可恢复？终点在坡顶还是还要返程？
按我的功率持续时间，保守/稳定/挑战分别多久、目标功率多少？
结论依赖哪些默认值，哪些仍是 pending 或 candidate？
```

不再用 `easy / medium / hard / extreme` 单标签替代这些问题，也不把热度赛段当作爬坡起终点或路线 waypoint。

## 12. 验收边界

达到以下证据前，不得宣称“世界最先进 ClimbPro 已接入”：

- 连续爬坡检测、反向重算和 merge/split 反例本地可重放；
- 西山至少覆盖稳定长坡、末段墙、短墙、阶梯坡和多坡路线；
- category 与 shape 不因同一物理几何重复累计；
- profile 缺失、边界不稳和阈值跨级会诚实降级；
- Named Climb 的 base/summit、整坡/半坡与 profile 覆盖由 typed identity gate 证明，调用方不能自行声称 `profile_complete_for_route=true`；
- 个性化估时明确区分实测参数与默认场景；
- CP/W' 只在个人参数充分时启用，并经过真实历史 holdout；
- 最终用户能同时看到路线组成、坡型、适合谁、耗时范围和代价，而不是只有一条海拔折线。

这份合同定义的是 VELO Climb Planner v1 的可实现先进性：公开规则兼容、内部算法可解释、输入输出可重放、缺失证据不脑补。它不代表厂商私有算法已被复刻，也不代表生产、真机或真实骑行验收已经完成。
