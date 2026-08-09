---
name: ingest-velo-road-segments
description: Use when VELO needs to discover, reconstruct, verify, or batch-create fixed cycling road segments from publicly visible Strava segment clues, including requests such as “收录这条赛段”, “按 Strava 起终点用腾讯重建”, “补齐太原热门路段”, or “给路线认知准备硬数据和热度证据”. Also use when replacing GPX-first segment research with the Strava-discovery, Tencent Directions, and VELO-elevation workflow. Do not use for importing a rider's Strava activities, producing a complete door-to-door route, or writing the final route introduction alone.
---

# 收录 VELO 真实路段

把公开赛段线索变成一份可审计的 VELO 路段候选。这里的目标不是复制 Strava，而是让它回答“哪里值得收、从哪到哪、哪边是主方向”，再由腾讯生成内部轨迹、VELO 计算海拔，最后由人确认是不是同一条路。

## 先守住三层真相

| 层 | 装什么 | 能决定什么 |
|---|---|---|
| 硬知识 | 腾讯轨迹、方向、距离、海拔、爬升、坡度、geometry hash | 能否匹配、导出、拼路线 |
| 热度观测 | Strava 页面看到的骑行人数、尝试次数、收藏数、观察时间 | 优先收哪条、哪些路最有代表性 |
| 认知判断 | “经典爬坡”“冷门陡坡”“本地主干线”等结论及依据 | 路线介绍和推荐理由 |

热度不能修改几何或安全事实；一次观察到的数字也不能变成永久结论。保留 `observed_at`，以后追加新快照。

## 工作流

### 0. 检查现场

1. 在仓库根目录确认分支、工作区和当前代码。旧文档只作线索。
2. 搜索同名 Segment、相近起终点和已有候选，避免重复生产。
3. 确认腾讯服务端 key 和 GLO-30 海拔链可用，只报告“已配置/未配置”，不要打印密钥。
4. 读取 [runtime-contract.md](references/runtime-contract.md)，确认当前实现入口没有漂移。

### 1. 先定义目标，再人工观察公开赛段

先在搜索结果出现前写清 `target_definition`：它在现实中承担哪一段道路、方向、预期距离范围、必须出现的路形和已知起终点。再搜索同区域所有可能候选。不能看到第一个名字相似的 marker 就开工，也不能用一个“成功跑过腾讯和海拔”的旧任务证明当前候选身份正确。

候选必须同时通过边界、方向、距离和路形四项身份检查。名字、热度或大致位于同一山体都不够；任一项不通过，脚本会在腾讯调用前拒绝输入。

在可见网页或用户提供的截图中记录：

- 赛段名、城市、页面 URL、观察时间；
- 页面可见的距离、爬升、均坡、最低和最高海拔；
- 主方向、起点和终点 WGS-84 坐标；
- 会决定走哪条岔路的中间锚点；
- 可见的参与人数、尝试次数、收藏数；
- 同区域候选的上述数字、比较范围，以及它们为什么不是本次目标；
- 路形、岔口和方向的观察备注。

不要调用 Strava API，不下载或复制 Strava polyline，也不要把 GPX 当默认入口。Strava 页面只提供发现、边界、方向与热度线索。

起终点坐标按这套无 API 方法取得：

1. 在 Strava 当前页面确认绿色起点 marker 和方格终点 marker 都真实可见，先截图保留上下文；
2. 根据 marker 所在道路、附近地标和整段路形，在腾讯地图定位同一现实点；
3. 腾讯侧坐标先按 GCJ-02 记录，再用项目现有转换入口生成内部 WGS-84；
4. 在 `coordinate_observation` 写明 `acquisition_mode`、对齐方法、预计精度和判断依据；新收录必须是 `strava_visible_markers_aligned_to_tencent_map`，看不清或无法唯一对齐就停止；
5. 已有 GPX 可以在事后做同轨误差回归，但不能替代前四步、不能成为新数据的默认出生证明。

旧赛段若历史上确实用过 GPX 或旧轨迹取得精确坐标，必须如实标为 `legacy_verified_geometry_regression`。它能验证腾讯和海拔链路，但最终只生成 `verified_regression`，不能冒充可发布的新收录。

按 [input-contract.md](references/input-contract.md) 写输入 JSON，把未选候选放进 `selection.rejected_candidates`，先运行：

```bash
python3 .agents/skills/ingest-velo-road-segments/scripts/build_candidate.py INPUT.json --validate-only
```

### 2. 让腾讯重建轨迹并让 VELO 计算海拔

在 `reconstruction.tencent_routing_profile` 显式选择 `bicycling` 或 `driving`，并写清依据。它只是腾讯重建道路几何时采用的算路模型，不代表骑行许可或安全结论。普通骑行道路先用 `bicycling`；遇到立交、盘桥或发卡弯被抄近路、重复绕行时，对比 `driving`。天龙山螺旋高架的当前实测是：`bicycling` 会缩短或重复，`driving` 起终点直算能还原完整道路。

```bash
python3 .agents/skills/ingest-velo-road-segments/scripts/build_candidate.py INPUT.json \
  --output /private/tmp/SEGMENT.candidate.json
```

脚本按起点、锚点、终点逐段调用指定的腾讯算路模式，保留模式与每段原始诊断；把腾讯 GCJ-02 点串转回 WGS-84。先检查重建距离是否落在预先冻结的目标范围，失败就停止且不浪费 DEM 调用；通过后再调用项目唯一的 GLO-30 路线海拔工厂，生成逐点海拔、曲线、爬升、下降和坡度，并保存当前算法参数 metadata。任何一段算路或海拔失败都停止，不输出“已验证”半成品。

### 3. 对照页面做路线核验

把腾讯候选线显示在真实腾讯地图上，与第一步看到的道路形状逐段对照：

- 起终点是否落在同一位置；
- 方向是否一致；
- 每个关键发卡弯、岔口和道路分支是否一致；
- 腾讯是否为了偏好平缓道路绕去了另一条线。

腾讯网页和 URI 使用 GCJ-02。人工地图复核时必须使用候选 `provenance.routing_points_gcj02`，不能把内部 WGS-84 起终点直接粘进去；天龙山实测中，错误粘贴 WGS-84 会把同一目标显示成 3.7 公里隧道捷径，而正确 GCJ-02 显示 10 公里天龙山路。

只看起终点不能证明同一路。若走错，先判断是 routing profile 还是岔口歧义，再切换 profile 或增加最少必要锚点并重新生成；不要手改输出点串。立交密集处锚点过多也可能制造重复绕行。仍无法一致时，把候选判为 `rejected` 或保留 `needs_review`，不要入库。

### 4. 冻结人工复核结果

确认三项都一致后运行：

```bash
python3 .agents/skills/ingest-velo-road-segments/scripts/review_candidate.py \
  /private/tmp/SEGMENT.candidate.json \
  --verdict accept \
  --endpoint-match yes --direction-match yes --shape-match yes --warnings-reviewed yes \
  --reviewer REVIEWER --note "逐段对照说明" \
  --output /private/tmp/SEGMENT.verified.json
```

任一项不一致就用 `--verdict reject`，并写清哪一段不一致。复核脚本生成新文件，不覆盖原候选，防止复核结论与被复核几何脱钩。

### 5. 发布或交给路线认知

只有 `status=verified` 且 `publication_eligible=true` 的 bundle 才有发布资格。`verified_regression` 只证明重建链路与旧路一致。发布前重新读取当前 Segment、`SegmentGeometrySource`、人工 Judgment 和白名单写入路径；使用能完整保存腾讯来源、geometry hash 和 reviewer 的正式入口。

当前入口若仍把任意坐标点叫作 `from-gpx`，不要为了“能写进去”而伪造 GPX provenance。先保留 verified bundle，再补或修正正式 writer。生产写入、迁移和覆盖旧 Segment 都必须走项目的数据库、CI 和人工审核门禁。

路线认知消费时：

- 硬知识直接引用 verified bundle 的版本与 hash；
- 热度数字作为带时间的 Evidence，不塞进硬知识；
- “最火、经典、冷门”等文字必须作为派生 Judgment，写明比较范围和证据；
- “最火”只能表示声明的比较范围和观察时间内数字最高，不能外推为整个城市或永久事实；
- 后续 Activity 和骑友反馈只能提出新证据，不能静默改写已发布几何。

## 失败模式

| 看似省事的动作 | 为什么会坏 | 正确补救 |
|---|---|---|
| 只给起终点，腾讯成功就入库 | 山路和岔路可能选错线 | 补关键锚点并逐段对照 |
| 把腾讯模式永远写死成骑行 | 立交盘桥可能被抄近路或重复绕行 | 显式记录 profile，对比路形与距离后选择 |
| 驾车模式还原正确就说“适合骑行” | 算路模式只证明道路几何，不证明骑行许可或安全 | 把合法性、安全性作为独立证据核验 |
| 把 WGS-84 坐标直接贴到腾讯网页复核 | 腾讯按 GCJ-02 解释，起终点会偏移并可能选错路 | 使用输出里的 `routing_points_gcj02` |
| 点开第一个同名赛段就开工 | 同一区域常有全程、局部爬坡和反向赛段 | 先比较候选的边界、方向和热度，再选目标 |
| 名字像、距离也差不多就算同一条 | 同一山体可能有不同入口、终点和岔路 | 在搜索前冻结目标，再逐项核对边界、方向、距离和路形 |
| 某次腾讯和海拔链跑通，就说目标也对 | 链路正确与赛段身份正确是两件事 | 每条候选都独立保存身份依据，未过门槛不允许算路 |
| 复制 Strava 轨迹或改走 API | 把外部数据当内部真相，偏离本流程 | 只记录可见线索，轨迹由腾讯重建 |
| 把“500 人骑过”写进硬知识 | 热度会变，也不能证明道路物理属性 | 存成带时间的 popularity observation |
| 腾讯绕路后手改几个点 | 破坏可重放性，hash 也失去来源 | 修改输入锚点，整条重新生成 |
| 生成 JSON 就称完成 | 候选还没证明是同一条路 | 必须留下三项人工复核结果 |
| 借用 `from-gpx` 写入腾讯候选 | provenance 变假，未来无法审计 | 使用专用 writer；没有就停在 verified bundle |

## 可检查的完成标准

一次收录只有同时满足以下条件才结束：

- 输入先定义了目标，并记录页面、观察时间、方向、起终点、页面指标、热度快照和候选比较范围；
- target identity 的 boundary、direction、distance、shape 四项均在腾讯调用前通过；
- 新收录的起终点来源门槛为 `gpx_independent_coordinates=passed`；历史回归明确停在 `regression_only`；
- 输出几何来源是 `tencent_directions`，明确记录 `bicycling` 或 `driving` profile，坐标系是 WGS-84；
- 腾讯重建后的实际距离落在目标定义范围内，才允许调用海拔并进入人工复核；
- 海拔方法来自当前 VELO 统一工厂，逐点海拔完整；
- 海拔结果同时保存 method 和算法 metadata，不能只留一个会漂移的“爬升数字”；
- endpoint、direction、shape 三项人工复核均通过；
- 热度观测与硬知识分开，派生判断没有冒充原始事实；
- geometry hash、输入摘要、复核人和复核时间可追溯；
- 未经明确授权，没有写生产数据库或覆盖历史 Segment。

最终汇报候选/已验证/已发布三个阶段，不把脚本成功、数据库写入和用户可用混成一个状态。

## 按需参考

- [input-contract.md](references/input-contract.md)：创建输入 JSON 时读取。
- [runtime-contract.md](references/runtime-contract.md)：运行脚本、排错或准备发布时读取。
- [tianlongshan-y7-public-observation-2026-08-09.json](examples/tianlongshan-y7-public-observation-2026-08-09.json)：七月已核对、当前页面重新确认的天龙山同轨赛段输入；只作为身份与公开观测样例，腾讯和海拔结果另产出。
- [tianlongshan-y7-verification-2026-08-09.json](examples/tianlongshan-y7-verification-2026-08-09.json)：同一输入的真实腾讯、当前 VELO 海拔、地图复核和 7 月 561m 历史算法锚；明确标注未写数据库。
