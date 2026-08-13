# 桃花沟 Carrier / Projection / 方向热度最小纵切

日期：2026-08-13
状态：research shadow；不晋级为正式道路图、正式热度或路线推荐

## 结论

西山下一步先用桃花沟 7 条来源赛段验证一条完整链：

```text
真实 Strava 来源线
→ 一条有版本的道路载体候选
→ 保序、方向化投影
→ 道路 measure 原子区间
→ 正反向分账的 reach bounds / repeat proxy / star proxy
```

这一步回答“多条重叠赛段怎样落到同一条路、热度怎样不重复膨胀”。它不回答道路是否已经适合骑行，也不生成路线组合。

## 为什么选桃花沟

当前 3,240 对 raw-geometry oracle 中，桃花沟 7 条观察形成一个小而完整的压力样本：

- 同向与反向都有；
- 有长赛段包含短赛段；
- 有部分重叠；
- 有反向等价；
- 12 个相关 pair 的方向均可判断，范围只有 3 个 raw gray case。

天龙山类型更多，但 28 个相关 pair 中 19 个范围关系为 raw indeterminate，更适合第二轮压力测试，不适合作为第一次道路投影落地。

冻结输入见 [`taohuagou_projection_slice_v1.json`](../../data/research/taohuagou_projection_slice_v1.json)。其中每条 observation 继续绑定原始 Strava ID、source geometry hash、GLO fact 和热度聚合字段。

## 道路底板

本切片只采用一个 provider candidate：OSM way `840111674` v6。道路坐标、node 顺序、provider timestamp、快照 hash 和 ODbL attribution 冻结在 [`taohuagou_carrier_candidate_v1.json`](../../data/research/taohuagou_carrier_candidate_v1.json)。

双快照机械对账：

- 2026-08-13 OSM API 小范围快照；
- 2026-08-06 Geofabrik 山西 PBF；
- 该 way 的 389 个坐标及顺序完全一致。

这只能证明“当前两份 OSM 数据对这条 way 一致”，不能证明 OSM 是现实道路最终真值。`highway=tertiary` 存在，但 `access/bicycle/surface` 未给出，因此 `access_state=unknown`，不得进入正式路线可用性裁决。

## 投影与热度规则

### 投影

- 输入完整来源线，不使用名称、缩略图或首尾点猜测；
- 对载体折线固定间距采样并做保序单调匹配；
- 正序与反序分别求解，方向独立输出；
- 输出 source/carrier measure witness、连续覆盖、距离分位数、未匹配范围、状态和 reason code；
- 阈值只属于 `research_shadow`，不晋级为正式 ProjectionSet policy。

### 方向热度

在 carrier measure 上收集 accepted posting 的起终边界，切成覆盖集合恒定的原子区间。正反方向分别生成 field。

每个区间先按：

```text
(source_fact_id, directed_evidence_cell_id)
```

折叠同一来源事实的重复 occurrence。然后：

- reach lower bound = 覆盖该区间的 `athlete_count` 最大值；
- reach upper bound = 覆盖该区间的独立事实 `athlete_count` 之和；
- repeat 只保留原始 `max(effort-athlete, 0) / athlete` proxy 范围；
- star 只保留 `log1p(star_count)` proxy 范围；
- 反向观察不改变正向 field；
- 没有来源事实覆盖的正反向区间显式输出 `unobserved`，不把未知写成 0；
- 不同统计 cohort 的事实禁止合并，避免把不同快照人数相加；
- 同一路线重复经过该区间，热度 credit 只取一次，但距离、爬升和回头路仍按实际 occurrence 计算。

这里的 `max` 只是观测并集人数的下界，不是“去重后的唯一骑手数”。upper-lower 越宽，说明来源之间的人员交集越未知；重叠赛段越多不会自动把一条路炒得越来越热。

## 验收边界

本切片通过后只证明：

1. 7 条来源线能机械投影到该 OSM 走廊候选，或给出 typed abstention；
2. 正反向和包含/部分覆盖能转成 measure 区间；
3. 重复 fact 幂等、方向隔离、区间 refinement 不改变路线级积分；
4. 固定输入与版本能重放出同一 hash。

当前投影阈值和所有区间证据都处于 `research_probe_unpromoted` / `shadow_only_not_route_ranking_input`。它们用于揭示投影误差和证据缺口，不能进入正式路线排序。

## 2026-08-13 真实重放结果

冻结 runner 对 7 条完整来源线重放后得到：

- 7/7 为 `research_projected`，5 条 forward、2 条 reverse；
- 7 条 projection 的连续 matched runs 共形成 12 个 posting；内部未匹配缺口不会再被 envelope 填成连续热度；
- 12.824 km 的道路候选按覆盖边界切成 26 个方向区间：18 个 `observed`、8 个 `unobserved`；
- 单一区间最多由 3 个来源事实共同支持；reach 只输出上下界，没有输出“唯一骑手”或单一热度分；
- 正向 10.410–10.422 km 与 10.502–11.597 km 区间的 reach bounds 最宽，为 376–1,124；中间未匹配缺口独立保留。这表示人员交集未知，不等于有 1,124 名唯一骑手；
- observation 70 的 source coverage 只有 0.434，是当前最明显的阈值校准灰区。它留在 shadow 输出中供审查，不是可晋级参数的正例；
- 数据库写入 0，网络请求 0；同一冻结输入重放得到相同 run hash。

不含坐标的冻结摘要见 [`taohuagou_carrier_projection_v1_manifest.json`](../../data/research/taohuagou_carrier_projection_v1_manifest.json)。完整产物位于 gitignored 的 `outputs/taohuagou-carrier-projection-v1/`。

它仍不证明：

- 桃花沟道路 access、路面、施工或现实通行状态；
- 这条 OSM way 已组成完整 `RoadCarrierGraph`；
- 城市接入、返程和各道路之间拓扑连通；
- 热度各维度应怎样学习成用户效用权重；
- 任一候选已经可以推荐给用户。

下一步只有在本切片投影误差与人工地图核对可接受后，才扩到 81 条，并加入保留完整 OSM node/turn/bridge/tunnel/level 身份的 CarrierGraph provider bake-off。
