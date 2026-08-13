# 西山公路路线规划确定性算法设计（对抗性审查后最终版 v2）

> 基线：`Starsky618/-velo@21731a1bcf87cc7e6122d4522fdedaa80be7f3a8`  
> 输入范围：`xishan-road-relation-input-20260813-v1`，87 条候选来源观测中 81 条 included、6 条 excluded  
> 适用任务：西山公路骑行路线候选生成、机械验证与确定性排序  
> 不在本设计范围：来源采集、授权、allowlist、人工 scope 审核、现有 route/source persistence 重构、骑中实时导航  
> 结论性质：算法与评测规范；任何未经实验校准的米数、百分比、权重和搜索预算均不在本文硬编码

---

# 0. 最终结论

推荐构建七个严格分离的计算层：

```text
FrozenObservationLedger
        ↓
VersionedRoadCarrierGraph
        ↓
MultiHypothesisProjection
        ↓
OverlapArrangement + RelationWitnessIndex
        ↓
PartiallyIdentifiedDirectedEvidenceField
        ↓
ContractedSearchGraph + BoundedDeterministicPlanner
        ↓
FullRouteValidator + ParetoDiversitySelector
```

核心对象如下：

- `SourceObservation`：现有冻结 Strava 来源事实；不等于道路。
- `RoadCarrierEdge`：当前 graph version 内的道路支持边；不声称跨 provider、跨版本是永恒“物理原子”。
- `RoadArc`：RoadCarrierEdge 的一个方向；projection 与 route eligibility 分离。
- `ArcSlice`：RoadArc 上的 linear-referenced 区间。
- `ProjectionHypothesis`：来源折线到有序 ArcSlice 序列的一个候选解释。
- `ProjectionSet`：保留 top-K/等价最优解释及质量向量；没有足够 margin 时不强选。
- `OverlapComponent`：两条 observation 在各自 source measure 上的一个连续、保序共享 witness。
- `PairRelation`：由 component set 摘要出的 extent/direction；fuzzy relation 不做强行全局分组。
- `DirectedEvidenceInterval`：方向化、临时 arrangement 上的部分识别证据区间。
- `SearchEdge`：为求解而收缩的宏边，可精确还原到底层 RoadArc。
- `RouteCandidate`：完整 approach/core/exit/return arc sequence 与搜索状态。
- `ValidationCertificate`：最终硬约束、几何覆盖、资源和失败证明。

最重要的架构决定：

1. **不把 81 条 Strava 赛段变成路网。** 它们只提供有方向的观测与聚合证据。
2. **道路载体图必须版本化且可怀疑。** graph/raw/provider 冲突进入 `indeterminate`，不能由 matcher 静默掩盖。
3. **Projection 是多假设对象。** 当前 access 不参与删除 map-matching 候选；access 只在路线可用性层裁决。
4. **关系真值是 witness set，不是单个比例。** `extent` 和 `direction` 是摘要，复杂路径保留多 component、multiplicity 与 embedding。
5. **只对精确 support signature 做 equivalence class。** `spatial-equivalent` fuzzy pair 不做 partition；近似 containment 不做 transitive closure。
6. **热度首版采用部分识别。** `max athlete_count` 是 union lower bound，不是去重人数估计；同时输出 upper bound、区间宽度与 coverage。
7. **独立几何等价观测可以增加证据下界。** 真正幂等的是同一 provenance fact 的重复写入。
8. **搜索必须有显式有限边界。** 先收缩图、构造 portal-pair envelope，再做整数资源、固定 expansion budget 的确定性求解；截断返回 typed failure。
9. **软热度不参与首版 hard-feasible 候选删除。** 热度只在完整候选通过 Validator 后排序。
10. **外部 router 可以提出多个 connector，但不能重写锁定 core。** 完整路线必须由 VELO 再证明。
11. **任何 no-result 必须区分“确实不可行”和“搜索未完成”。**
12. **LLM 不参与几何匹配、关系分类、成本计算、剪枝、access 判定或最终裁决。**

---

# 1. 仓库落点与边界

## 1.1 可直接复用的既有事实

当前仓库已经具备：

- 冻结 scope profile：`data/research/xishan_relation_input_profile_v1.json`；
- 81 included / 6 excluded 的人工范围决定；
- `SegmentSourceObservation` 的来源 ID、来源线、geometry resolution、统计字段和时间字段；
- source geometry hash 与 normalization version；
- 87/87 complete 的 GLO 派生事实绑定；
- read-only audit 与 input-set hash；
- `JudgmentRun`、typed audit 状态与来源可追溯结构；
- 已有 route reference line、RouteSegment 装配和路线审计边界。

新算法必须读取这些对象，不重新定义其事实语义。

## 1.2 不可复用为道路图的既有对象

`RouteSegment` 是路线版本的装配成员，支持：

- `segment_clip`；
- `custom_geometry`；
- `start_fraction/end_fraction`；
- `direction`；
- `component_geometry`；
- route line hash 与 accepted human judgment。

它不是：

- 交叉口图；
- 道路中心线图；
- 通行图；
- map-matching edge；
- route search edge。

因此新计算层不能把 `RouteSegment` 直接当 `RoadArc`。

## 1.3 两种 hash 必须并存

保留现有：

```text
stable_line_hash
```

用途：审计和并发身份；语义是“规范空白后的 WKT 字节一致”。

新增：

```text
source_exact_directed_hash_v1
source_exact_undirected_hash_v1
support_path_signature_v1
```

用途分别是：

- 来源点序列 exact；
- 忽略整体反向后的来源 extent exact；
- 固定 graph version 下的精确 ArcSlice 序列 identity。

不得更改旧 hash 的定义来兼容新算法。

---

# 2. 数学对象

## 2.1 冻结来源观测

第 \(i\) 条来源观测：

\[
O_i=
(id_i,\gamma_i,\ell_i,m_i,\tau_i,\rho_i,h_i)
\]

其中：

- \(\gamma_i:[0,\ell_i]\to\mathbb R^2\)：按来源顺序保留的有向折线，以 source arc length 参数化；
- \(\ell_i\)：来源线长度；
- \(m_i=(A_i,E_i,S_i,\ldots)\)：athlete、effort、star 等聚合字段；
- \(\tau_i\)：`observed_at`，以及可用时的 `source_created_at/source_updated_at`；
- \(\rho_i\)：geometry resolution、point count、来源状态；
- \(h_i\)：来源 geometry hash、normalization version、census batch、observation identity。

来源观测不可被 map matching 改写。

## 2.2 版本化道路载体图

\[
G^v=(V^v,E^v,A^v)
\]

其中：

- \(V^v\)：当前 graph version 内的拓扑锚点；
- \(E^v\)：RoadCarrierEdge；
- \(A^v\subseteq E^v\times\{+,-\}\)：方向化 RoadArc；
- \(v\)：包含 provider/source snapshot、构图代码、属性版本、CRS、量化政策和 access snapshot 的 manifest。

RoadCarrierEdge：

\[
e=(u,v,\eta_e,L_e,\lambda_e)
\]

- \(\eta_e:[0,L_e]\to\mathbb R^2\)：当前参考中心线；
- \(\lambda_e\)：road identity、carriageway、level、bridge/tunnel、surface、road class 等；
- edge ID 只保证 graph version 内稳定；
- 跨版本通过 lineage 表达 split/merge/replace。

RoadArc：

\[
a=(e,d,\chi_a,z_a)
\]

- \(d\in\{+,-\}\)；
- \(\chi_a\in\{\text{allowed},\text{forbidden},\text{unknown},\text{conditional}\}\)；
- \(z_a\)：方向化爬升、下降、坡度、时间模型与安全属性。

**Projection 可匹配到任何 \(\chi_a\)；路线搜索只可使用政策允许的 arc。**

## 2.3 ArcSlice

RoadArc \(a\) 上的区间：

\[
s=(a,[u,v]),\quad 0\le u<v\le L_a
\]

ArcSlice 是所有关系和 evidence 的共同空间单位。Strava 起终点只成为 \(u,v\)，不触发载体图切边。

## 2.4 ProjectionHypothesis

一条投影假设：

\[
H_i^r=
\left[
(a_1,[u_1,v_1],[p_1,q_1]),
\dots,
(a_k,[u_k,v_k],[p_k,q_k])
\right]
\]

同时保存：

- source interval \([p_j,q_j]\)；
- carrier interval \([u_j,v_j]\)；
- source 与 carrier 的方向；
- 未匹配 source intervals；
- 重复 arc 次数；
- raw-to-graph alignment witness；
- lateral/heading/network-length residual；
- topological transitions；
- access state，但不以此过滤；
- provider conflicts；
- score 与稳定 tie-break key。

ProjectionSet：

\[
\mathcal H_i=\{H_i^1,\dots,H_i^K\}
\]

状态：

```text
accepted_unique
accepted_equivalent_hypotheses
ambiguous_multimodal
graph_missing_raw_supported
graph_raw_conflict
no_candidate
geometry_insufficient
```

## 2.5 OverlapComponent

对两条观测 \(i,j\)，一个共享 component：

\[
w_q=
(I_i^q,I_j^q,S_q,\sigma_q,\epsilon_q,\kappa_q)
\]

- \(I_i^q\subseteq[0,\ell_i]\)、\(I_j^q\subseteq[0,\ell_j]\)：source measure intervals；
- \(S_q\)：共享 ArcSlice 序列或 raw-curve witness；
- \(\sigma_q\in\{+1,-1\}\)：同向/反向；
- \(\epsilon_q\)：距离、heading、length、endpoint residual；
- \(\kappa_q\)：embedding identity 与歧义信息。

component 集合必须：

- source interval 内部不重复使用；
- 保留 sequence；
- 保留 multiplicity；
- 显式记录多 embedding；
- 不把多个碎片简单相加成一个“包含”。

## 2.6 PairRelation

\[
R_{ij}=(X_{ij},D_{ij},W_{ij},Q_{ij})
\]

- extent \(X\)：
  - `source_geometry_identical`
  - `spatial_equivalent`
  - `a_contains_b`
  - `b_contains_a`
  - `partial_overlap`
  - `disjoint`
  - `indeterminate`
- direction \(D\)：
  - `same_direction`
  - `reverse_direction`
  - `mixed_direction`
  - `indeterminate`
- \(W_{ij}\)：所有 overlap components；
- \(Q_{ij}\)：质量、阈值位置、graph/raw 一致性、reason code。

`partial_overlap` 允许多个 component；它不是“只有一个中间重叠段”的同义词。

---

# 3. 必须保持的不变量

## I1：事实层与载体层分离

删除或修改 SourceObservation 不删除 RoadCarrierEdge。graph update 也不改写来源 geometry。

## I2：方向显式且分层

- source direction；
- projection orientation；
- RoadArc direction；
- relation component direction；
- route traversal direction；

五者不得压成一个布尔值。

## I3：Strava 边界不切道路

赛段起终点、名字、采样折点、重叠边界都只能成为 ArcSlice measure。

## I4：顺序与重复次数不丢失

Projection、Relation 和 Route 都是有序多重序列，不是 edge set。

## I5：平面相交不等于拓扑连通

bridge、tunnel、level、双幅路和平行辅路由图身份与 connectivity 区分。

## I6：Projection 与 route access 分离

map matching 不因当前 forbidden/unknown access 删除物理候选；路线使用再 fail-close。

## I7：多假设优先于假精确

top-1 与 top-2 接近、provider 冲突、重复 embedding、短线噪声等进入 indeterminate。

## I8：只对 provenance-identical fact 幂等

同一 observation identity 与 payload 重复导入，所有输出不变。不同 segment ID 的几何等价观测可以改变 bounds，但不得线性重复计票。

## I9：fuzzy equivalent 不形成强制 partition

只有 exact source hash 或 exact support signature 可形成安全 class。

## I10：只有 closure-safe containment 可传递

近似 containment 不通过 reachability 推导新关系。

## I11：证据区间 refinement 不改变积分

在没有新证据值的情况下，把一个 evidence interval 细分成多个子区间，路线级积分完全不变。

## I12：soft evidence 不证明 feasibility

热度、收藏、连续性偏好不能抵消方向、access、断路、预算、结构和关键未知。

## I13：搜索截断不等于无解

任何 expansion/label/portal budget 命中都返回 `search_truncated`，不能返回 `no_feasible_route`。

## I14：同一 manifest 可重放

固定：

```text
observation set hash
graph/provider/access snapshot
metric CRS and axis order
normalization and quantization
matcher/relation/heat/search versions
library versions
solver seed/thread count
expansion budgets
canonical serialization
```

必须得到相同 output hash 与 witness hash。

## I15：LLM 不进入确定性内核

LLM 只能把用户语言编译成已有 schema 的 RouteIntent，或解释 typed result。

---

# 4. RoadCarrierGraph：构建、切分与版本

## 4.1 应切分的位置

只在当前 provider/审核事实中可机械识别的事件切分：

1. 同层真实交叉与合法转向节点；
2. 道路端点、死胡同；
3. carriageway/road identity 改变；
4. 单双向或 direction-specific access 改变；
5. bridge/tunnel/level 改变；
6. surface/road class 等会改变 hard policy 或求解资源的属性改变；
7. 明确 gate/entrance/exit；
8. 经审核的 topology correction；
9. provider 对象真实 split。

## 4.2 不切分的位置

- Strava 起终点；
- 多条赛段重叠边界；
- POI 最近点；
- GPS 折点；
- router 临时 snap；
- 仅名称变化且 topology/policy/resource 属性未变化；
- 仅 heat 值变化。

## 4.3 graph provider bake-off

在构建 v1 前，至少比较一个候选道路图与人工标注，检查：

- 81 条线的可表达覆盖率；
- 平行路误吸附；
- bridge/tunnel/level；
- 双幅路；
- missing road；
- access unknown/错误；
- topology transition；
- graph update 稳定性。

gold 不要求 provider edge ID 一致，而记录 provider-independent corridor/road witness 和可接受 hypothesis 集。

## 4.4 lineage

graph update 输出：

```text
unchanged
split(old → new[])
merge(old[] → new)
replaced
deleted
attribute_only_change
topology_change
```

Projection 迁移只能在 lineage 与 raw geometry 同时支持时自动完成；否则重新匹配。

## 4.5 SearchGraph contraction

求解前构造可还原的宏图：

- 连续 degree-2 链可收缩；
- 遇到 portal、转向、access、level、surface、phase role、hard resource discontinuity 时停止；
- 每条 SearchEdge 保存底层 RoadArc sequence、几何、distance、climb、time interval、access 状态和 lineage；
- heat interval 边界通常不阻止收缩，因为 heat 在完成路径上积分；若实现需要增量 scoring，可保存 measure map。

---

# 5. 从有噪声折线到 ProjectionSet

## 5.1 source exact canonicalization

定义 `N_source_exact_v1`：

1. 验证 CRS/axis order；
2. 按来源合同固定坐标精度；
3. 删除连续、完全相同的零长度重复点；
4. 保留所有其余采样点、顺序和方向；
5. 使用固定二进制编码，不依赖 WKT 格式化差异；
6. 不 simplify、smooth、resample、snap 或移动端点。

\[
H_d(\gamma)=SHA256(N(\gamma))
\]

\[
H_u(\gamma)=\min(H_d(\gamma),H_d(reverse(\gamma)))
\]

同时保存 directed hash，才能判断 exact direction。

## 5.2 deterministic candidate generation

对固定政策重采样后的 source points/segments：

1. RoadArc spatial index 查询候选；
2. query radius 由 projection gold 的 residual recall 校准；
3. 候选不因 access forbidden/unknown 被删除；
4. level/road identity 只在 transition 和 graph topology 中约束；
5. 所有候选按稳定 key 排序。

候选状态至少包含：

```text
arc_id
measure
perpendicular_distance
heading_delta
source_resolution
road_level
candidate_generation_reason
access_state
```

## 5.3 HMM/Viterbi 或同类拓扑匹配

emission：

\[
C_E(q_t,a)=
-\log p(d_\perp,\Delta\theta,\rho_i\mid correct)
\]

transition：

\[
C_T(a,b)=
-\log p(
\Delta L_G-\Delta L_O,
turn,
topological_transition
\mid correct)
\]

仅在物理 topology 不可达时 \(+\infty\)。当前 access 不作为几何不可达。

输出 deterministic top-K：

- 固定 K 或 score envelope；
- fixed tie-break；
- 保存 top-1/top-2 gap；
- 保存所有候选 arc dependency；
- 不把 raw score 伪装成概率，除非 holdout calibration 通过。

## 5.4 raw monotone alignment cross-check

对 candidate pair 或 Projection：

- forward/reverse monotone alignment；
- source arc-length correspondence；
- tangent/heading residual；
- longest component；
- fragmentation；
- unmatched intervals；
- self-overlap；
- endpoint residual。

规则：

```text
graph + raw 一致且 margin 充分       → accepted
多个 graph hypothesis 对同一 corridor 等价 → accepted_equivalent_hypotheses
graph 缺路，raw 强支持              → graph_missing_raw_supported
graph 与 raw 冲突                   → graph_raw_conflict
多平行路/重复 embedding             → ambiguous_multimodal
```

`graph_missing_raw_supported` 可用于 pair relation 的有限几何结论，但不能直接用于 route search，直到载体图补全或人工 correction。

## 5.5 Projection acceptance

使用 selective classification：

```text
fail band
gray/abstain band
pass band
```

quality vector：

```text
matched_source_length_ratio
unmatched_intervals
lateral_error_quantiles
heading_error_quantiles
network_source_length_error
top1_top2_margin
parallel_road_ambiguity
repeated_arc_count
mixed_direction_length
provider_conflict
raw_graph_agreement
candidate_dependency_size
```

阈值由 corridor-group holdout risk-coverage curve 决定。

---

# 6. Candidate pair generation：避免生产全量 n²

## 6.1 四级索引

### A. exact identity index

```text
source_exact_directed_hash → observation IDs
source_exact_undirected_hash → observation IDs
support_path_signature → observation IDs
```

### B. raw subcurve R-tree

不仅索引整条 bbox，也索引固定 source-length chunk 的 bbox，降低长线 bbox 过宽造成的候选爆炸。

### C. ArcSlice postings

```text
road_arc_id →
  observation_id
  hypothesis_id
  source_interval
  arc_measure_interval
  occurrence_index
  orientation
  projection_status
```

同一 arc/direction 上用 interval tree 或 sweep-line 召回 measure 相交项。

### D. graph component / corridor coarse filter

- 同一 graph component；
- 或 raw expanded geometry 接近；
- 或 provider conflict 需要 cross-check。

tile 只做 coarse filtering，不能证明相同道路。

## 6.2 完整候选集合

\[
Cand(i)=
Exact(i)
\cup RawRTree(i)
\cup ArcPostings(i)
\cup ConflictNeighborhood(i)
\]

对 pair 取稳定 canonical ordering。

## 6.3 复杂度

设：

- \(P\)：总采样点；
- \(c\)：每点候选 arc 上限；
- \(B\)：posting interval boundary 总数；
- \(k\)：真正比较的 pair 数；
- \(\bar r\)：平均 relation alignment 成本。

初建：

\[
O(P\log |A|+Pc^2+B\log B+k\bar r)
\]

最坏所有 observation 都压在同一热门走廊，若要求物化所有 pair：

\[
k=\Theta(n^2)
\]

这是输出下界，不能靠索引消失。生产缓解：

- exact support signature 分组；
- interval arrangement；
- closure-safe containment 只存 cover edges；
- disjoint 不全量存；
- fuzzy relation 按需计算和缓存；
- heat 直接基于 postings/arrangement，不依赖所有 pair；
- dense component 超预算返回 `dense_component_pending`，不能把未算作 disjoint。

当前 \(n=81\) 时仍完整计算 \(3240\) pair，作为 candidate recall oracle。

---

# 7. Relation Engine

## 7.1 component alignment

对两个 accepted ProjectionSet：

1. 枚举兼容 hypothesis pair；
2. 在有序 ArcSlice sequence 上做非交叉最大 alignment；
3. 保留所有显著连续 components；
4. 每个 source interval 不可重复消费，除非明确对应 observation 的重复 traversal；
5. 计算 forward 与 reverse orientation；
6. raw alignment 交叉验证；
7. 多 hypothesis 给出一致摘要才可 determinate。

定义总共享 source coverage：

\[
C_i=
\frac{\left|\bigcup_q I_i^q\right|}{\ell_i}
\]

\[
C_j=
\frac{\left|\bigcup_q I_j^q\right|}{\ell_j}
\]

同时记录：

- longest component ratio；
- number of significant components；
- fragmentation；
- exclusive intervals；
- embedding count；
- endpoint measure residual；
- graph/raw consistency。

不再只依赖单个 \(M=\max(M_+,M_-)\)。

## 7.2 extent 判定

### 1. `source_geometry_identical`

同 normalization version 且 undirected exact hash 相同。

### 2. `spatial_equivalent`

必要条件：

- \(C_i,C_j\) 均进入 equivalent pass band；
- 双方 exclusive intervals 进入 negligible pass band；
- significant components 能组成一个全局保序 embedding；
- endpoint/residual 通过；
- 不存在显著未解释 loop；
- hypothesis 摘要一致；
- graph/raw 不冲突。

### 3. `a_contains_b`

- B 的 source coverage 进入 contain pass band；
- A 有显著 exclusive interval；
- B 对 A 存在稳定、保序、连续子路径 embedding；
- B 没有另一段显著未解释 geometry；
- 若多个 embedding 对 relation summary 等价但位置无法唯一，relation 可为 contains，但 `embedding_ambiguous=true`；若后续 attribution 依赖具体位置，则进入 indeterminate。

### 4. `partial_overlap`

- 至少一个 significant component 进入 overlap pass band；
- 不满足 equivalent；
- 不满足任一 containment；
- A/B 均可能有 exclusive interval；
- 可包含多个共享 components、same/reverse 混合。

### 5. `disjoint`

必须同时证明：

- exact 不同；
- accepted projection postings 无共享；
- raw expanded subcurve 无 significant alignment；
- candidate generation recall 条件满足；
- 双方 geometry/projection 质量足够；
- 无 graph missing/provider conflict。

### 6. `indeterminate`

任何 gray zone、multi-modal projection、graph/raw conflict、过短噪声、多 embedding 影响结论、输入质量不足。

判定优先级：

```text
source exact
→ spatial equivalent
→ containment
→ partial overlap
→ proved disjoint
→ indeterminate
```

这里的 `proved disjoint` 是证据充分的结论，不是“没召回候选”。

## 7.3 direction 判定

先在 component level：

```text
same
reverse
```

再汇总：

- 全部 significant components same → `same_direction`
- 全部 reverse → `reverse_direction`
- same/reverse 均显著或 observation 自身 out-and-back → `mixed_direction`
- hypothesis 之间方向摘要不一致或环线对称 → `indeterminate`

extent 与 direction 正交输出，但 heat attribution 使用 component orientation。

## 7.4 exact support signature

固定 graph version 下，对 accepted unique projection 构造：

```text
[
  (road_arc_id, occurrence_index,
   quantized_measure_start, quantized_measure_end,
   source_order)
]
```

规则：

- quantization policy 在 manifest；
- 相邻、同 arc、同 orientation 且 source continuity 的 slice 合并；
- 保留 multiplicity；
- 保留整体方向；
- 不跨 graph version 比较 identity。

完全相同 signature 才形成 `ExactSupportClass`。

## 7.5 fuzzy equivalence 不分组

`spatial_equivalent` 只存 pair edge。禁止：

- 普通 DSU；
- complete-link 贪心 partition；
- overlap connected component；
- 以单个“代表赛段”覆盖所有 fuzzy neighbors。

## 7.6 containment 双层结构

### closure-safe containment

定义在 exact support signatures 上：

\[
S_B \preceq S_A
\]

当且仅当 B 的完整有序 ArcSlice word 是 A 的连续子路径，且 interval inclusion 精确成立。

该关系可传递，允许：

- DAG；
- transitive reduction；
- reachability 推导；
- interval sweep 优化。

### approximate containment

由 relation classifier 的容差判定产生，只保存显式 pair witness：

```text
approx_contains_edges
```

不做 transitive closure。任何间接关系必须重新计算 A-C。

---

# 8. 增量更新

## 8.1 单条 observation 新增/修改

```text
1. 读取旧 raw bbox、ProjectionSet、candidate dependencies、postings
2. 删除旧 postings 与 exact/support signature membership
3. 用冻结 matcher params 生成新 ProjectionSet
4. neighbor union =
     old raw neighbors
   ∪ new raw neighbors
   ∪ old arc-posting neighbors
   ∪ new arc-posting neighbors
   ∪ graph-conflict neighborhood
5. 失效 observation-neighbor 显式 pair relations
6. 重算这些 pair
7. 更新 exact support class
8. 更新受影响 closure-safe containment interval structure
9. 重算触及 arc measure ranges 的 evidence arrangement
10. 对已有 hard-feasible route pool 重新积分与排序
11. 若 topology/hard resources 未变，不重新生成 feasibility pool
```

平均复杂度：

\[
O(P_i\log |A|+P_ic_i^2+d_iC_{rel}+B_i\log B_i+R_i)
\]

## 8.2 为什么 matcher 要保存 candidate dependencies

graph edge 即使未进入 top-1，也可能是 top-2/候选。若它后来修改，top-1 可能改变。因此每个 ProjectionSet 保存：

```text
all_considered_arc_ids
candidate_query_envelope
transition_dependency_edges
provider_version
```

graph update 的失效集合不能只看已接受 path。

## 8.3 graph update

```text
changed edges + lineage
→ observations whose accepted or candidate dependencies intersect
→ rematch ProjectionSets
→ recompute affected pair neighborhoods
→ rebuild affected evidence intervals
→ invalidate topology-dependent route pools
```

attribute-only change：

- 若只改 soft display attribute，可局部；
- 若改 access、direction、time、surface hard policy，失效 route feasibility；
- 若改 topology/geometry，失效 projection 与 relation。

## 8.4 heat model 参数更新

必须区分：

### operational incremental update

- heat model parameters frozen；
- 新 observation 只改局部 bounds/field；
- 可与 full rebuild 精确对齐。

### model refit/version migration

- length/exposure baseline、EB prior、calibration bands 改变；
- 可能改变所有 observations；
- 创建新 heat version；
- 全量重算，不冒充局部更新。

## 8.5 soft-score 与 candidate cache

首版候选生成不按 heat 剪枝，因此：

- heat-only update：重积分、重 Pareto、重多样性选择；
- topology/hard-resource update：重跑 search；
- ranking policy update：不需重做 feasibility，只重排。

---

# 9. 方向性热度：从“去相关估计”改为“部分识别证据”

## 9.1 可识别与不可识别

覆盖 directed interval \(c\) 的每个 observation 有 athlete set \(U_i\)，只知道：

\[
A_i=|U_i|
\]

未知：

\[
|U_i\cap U_j|
\]

真实观测并集：

\[
N_c=\left|\bigcup_{i\in I_c}U_i\right|
\]

同一可比较 census cohort 下：

\[
L_c=\max_{i\in I_c}A_i
\]

\[
U_c=\sum_{i\in I_c}A_i
\]

\[
L_c\le N_c\le U_c
\]

若有可信的 cohort universe size \(N\)：

\[
U_c=\min\left(N,\sum_iA_i\right)
\]

没有个体集合或交集统计时，不能唯一确定 \(N_c\)。

## 9.2 DirectedEvidenceInterval

在每条 RoadArc 上收集 accepted projection 的 measure boundaries，形成临时 arrangement：

```text
(arc_id, direction, start_measure, end_measure)
```

覆盖集合在 interval 内保持不变。

每个 interval 保存：

```text
covering_observation_fact_ids
covering_support_signatures
reach_union_lower_bound
reach_union_upper_bound
bound_width
projection_quality_floor
snapshot_comparability
raw_support_count
normalized_support_envelope (optional/shadow)
repeat_proxy_envelope
intent_proxy_envelope
```

reverse observation 进入 reverse arc field，不进入 forward field。

## 9.3 provenance 归并

在任何聚合前先按：

```text
source_platform
source_segment_id
census_batch_id
observation identity
metric payload hash
```

去除重复写入。

若同一 source segment 有多个时间快照：

- 默认只在同一 heat snapshot cohort 比较；
- 或明确选择 latest complete snapshot；
- 不把跨时间累计值当相互独立证据求和。

## 9.4 正确的幂等和有界性

必须通过：

1. 同一 fact 重复导入：bounds 不变；
2. 同一 fact 被派生拆成多个记录：provenance collapse 后不变；
3. 新几何等价独立 segment：
   - lower bound 可上升到新的 max；
   - upper bound 按新证据变宽；
   - 不直接相加成为单点 estimate；
4. reverse segment 不改变 forward field；
5. route 重复经过 interval 不重复获得 popularity credit；
6. cell 纯 refinement 不改变路线积分。

## 9.5 长度、爬升与暴露校正

只有在字段和样本支持时启用 segment-level shadow residual：

\[
y_i=\log(1+A_i)
\]

\[
\hat \mu_i=f(
\log \ell_i,
climb_i,
gradient_i,
exposure_i,
cohort_i
)
\]

\[
r_i=y_i-\hat\mu_i
\]

要求：

- `source_created_at` 可用且可信时才计算 exposure；
- 缺失时不插补假精度，可用 cohort fixed effect；
- \(f\) 采用简单、正则化、可解释模型；
- 按完整 corridor family 做 cross-fitting；
- 输出 prediction interval；
- 只有 holdout 相对 raw baseline 明显改善才晋级；
- \(r_i\) 叫 `segment_support_residual`，不能叫 unique road popularity。

cell 上的可选 support envelope：

\[
Q_c=
\max_{g\in Groups(I_c)}
LCB(r_g)
\]

其中 group 至少按 exact source/support identity 避免重复；LCB 的校准必须考虑选择多个候选后的最大值偏差。数据不足时不启用 \(Q_c\)。

## 9.6 repeat proxy

\[
X_i=\max(E_i-A_i,0)
\]

可定义平滑 repeat intensity：

\[
\hat\rho_i=
\frac{X_i+\alpha}{A_i+\beta}
\]

但必须标记：

- 这是 segment-level proxy；
- 不恢复 athlete repeat distribution；
- 不恢复 cell unique repeater；
- \(\alpha,\beta\) 来自冻结批次或多城市 hierarchical fit；
- 81 条不足时只展示原始 \(X_i/A_i\) 与区间。

## 9.7 star/intent proxy

仅当来源合同证明 denominator 兼容时使用 Beta-Binomial。否则：

- `log1p(star_count)`；
- 对 exposure/length 等做描述性 residualization；
- 只叫收藏/训练意图代理；
- 不解释为实际流量或通过人数。

## 9.8 路线级证据向量

令 \(C(R)\) 为路线第一次经过的 directed evidence intervals。

### coverage

\[
Coverage(R)=
\frac{\sum_{c\in C(R)}|c|\mathbf 1[I_c\neq\varnothing]}
{L_R}
\]

### conditional lower-bound support

\[
SupportLB(R)=
\frac{
\sum_{c\in C(R),I_c\neq\varnothing}
|c|\log(1+L_c)
}{
\sum_{c\in C(R),I_c\neq\varnothing}|c|
}
\]

### uncertainty width

\[
Uncertainty(R)=
\frac{1}{L_R}
\sum_{c\in C(R)}
|c|
\log\frac{1+U_c}{1+L_c}
\]

### connector ratio

\[
ConnectorRatio(R)=1-Coverage(R)
\]

### optional residual proxies

分别积分 `normalized_support_envelope`、repeat、intent，保留为独立维度。

普通 connector 的证据为“unobserved”，不是“被证明不热门”。其 lower-bound support 为 0，但 coverage 明确下降，避免把缺数据当负证据。

## 9.9 为什么首版不输出单一 heat score

必须输出向量：

```text
reach_union_lower_bound_surface
reach_union_upper_bound_surface
bound_width
evidence_coverage
conditional_support_lower_bound
projection_quality_coverage
snapshot_comparability
repeat_proxy
intent_proxy
connector_ratio
freshness
```

只有在积累冻结 rider choice/rejection episodes 后，才可在 hard-feasible Pareto 集上学习 utility。

---

# 10. 路线问题定义

## 10.1 RouteIntent

RouteIntent 至少包含：

```text
origin
return_destination
distance target/range/hard max
climb target/range/hard max
time target/range/hard max
allowed access policy
area/phase profile
route pattern:
  loop
  point_to_point
  forced_out_and_back_allowed
  hill_repeat
mountain continuity requirement
connector budget
retrace policy
required/forbidden corridor or traversal
rider objective policy version
```

Agent 只能填充 schema；缺少 hard 参数时追问或使用显式默认政策，不自行画路。

## 10.2 AreaRoleProfile 与 phase automaton

每个 RoadArc 可有 versioned role set：

```text
urban_approach
mountain_core
exit_corridor
urban_return
neutral_connector
```

角色来自 graph/区域结构与审核配置，不来自 Strava endpoint。

西山 mountain intent 的 automaton：

```text
APPROACH → MOUNTAIN → EXIT → RETURN → COMPLETE
```

允许 self-loop；禁止退出后重新进入 mountain，除非 intent 是明确 hill-repeat pattern。

真正搜索在 product graph：

\[
G_{product}=G_{search}\times Q_{phase}
\]

只有 arc role 与 automaton transition 都合法的边存在。

连续山地定义：

- route arc sequence 中 `MOUNTAIN` 状态形成一个连续区间；
- 该区间内不进入被定义为 urban approach/return 的 arc；
- neutral connector 是否允许以及最大长度由 calibrated policy 决定；
- hill repeat 使用另一台 automaton。

## 10.3 portal

portal 是 phase role 边界上的合法进入/退出状态，不是 Strava 端点。

每个 portal 保存：

```text
anchor/arc boundary
allowed entry/exit directions
reachable origin/return sets
minimum connector resources
access state
graph version
```

---

# 11. 有限、确定性的候选生成与搜索

## 11.1 问题复杂度

带：

- 距离、爬升、时间；
- 有向 access；
- phase；
- elementary path / repeat；
- route pattern；
- 多目标；

的路线搜索属于资源约束路径/环问题，最坏 NP-hard。

系统承诺的不是无限图上的全局最优，而是：

1. 明确 search envelope；
2. envelope 内若未截断则给出完备状态；
3. 所有输出通过 exact Validator；
4. 截断不冒充无解。

## 11.2 预计算 lower bounds

对 origin、return destination、portals 预计算：

\[
LB_D(v), LB_T(v), LB_C(v)
\]

至少 distance/time lower bound 必须 admissible。用于：

- portal pair 淘汰；
- label pruning；
- search envelope；
- full-route hard budget proof。

## 11.3 portal-pair search envelope

对 entry \(p\)、exit \(q\)，构造确定性诱导子图：

\[
V_{pq}=
\{v:
LB(o,v)+LB(v,d)\le B_{hard}
\}
\]

并与：

- allowed region；
- phase role；
- access policy；
- graph component；
- explicit corridor constraints；

取交集。

envelope policy 与 budget 版本化。若 envelope 本身因为未知 access/graph missing 不可靠，返回 typed unknown。

## 11.4 connector alternatives

对：

```text
origin → entry portal
exit portal → return destination
```

生成有限多个 connector alternatives：

- 内部图搜索或外部 router adapter；
- 固定 provider/profile/model hash；
- 返回完整 edge/path details；
- 不能只返回一条；
- 与 mountain core 在同一 total budget 下组合；
- connector 不可提前/重复穿越锁定 core，除非 Validator 允许。

## 11.5 mountain core solver

首版推荐：

### A. contracted graph 上的 deterministic multi-resource label-setting

状态：

\[
L=(v,a_{prev},phase,r,intent,H)
\]

- \(r=(distance,climb,time,connector,unknown)\)；
- \(H\)：当前 envelope 内 SearchEdge 使用状态；
- popularity evidence 不进入 feasibility state；
- hill repeat 使用显式 pattern state，不允许任意循环。

### B. 完整 history 只在小 envelope 使用

exact used-edge bitset 会指数增长，因此：

- 先 contraction；
- 再 portal-pair envelope；
- 当前西山以接近 exhaustive 的 label-setting 建 oracle；
- 更大图的 ng-route/ε-dominance/beam 只能在 oracle 校准后作为近似版本。

### C. 固定计算预算

不使用 wall-clock。manifest 固定：

```text
max_portal_pairs
max_expanded_labels
max_labels_per_state_key
max_complete_candidates
max_replacement_search_expansions
```

若命中：

```text
search_truncated
```

并保存：

```text
expanded_count
frontier_size
best_lower_bound
best_found_candidate
unexplored_state_summary
```

## 11.6 exact dominance

同一：

```text
vertex
previous arc
phase
intent pattern state
```

下，label \(p\) 支配 \(q\) 仅当：

- hard resources 均不高；
- unknown 不更多；
- used-edge history 对 future feasibility 不更差；
- repeat/backtrack state 不更差；
- 至少一项严格更优。

首版不把 soft heat 作为 dominance 条件，避免 soft update 改变可行候选池。

## 11.7 route pattern

### simple loop / point-to-point

mountain core 默认不重复 RoadCarrierEdge；允许合法 cycle，但 route arc sequence 中不出现 opposite-direction repeated subpath。

### forced out-and-back

只有：

- intent/目标允许；
- 或 required target 只能通过某 corridor 到达；

才进入候选。

### hill repeat

显式模板：

```text
enter climb corridor
→ climb traversal
→ legal reset/turnaround
→ descend/reset corridor
→ repeat N times
→ exit
```

repeat count 是 intent resource，不由通用图搜索偶然产生。

## 11.8 backtrack 分类

### immediate reverse

\[
a_{t+1}=reverse(a_t)
\]

默认 hard fail，除非 typed turnaround。

### opposite-direction repeated subpath

找 maximal repeated corridor，记录 divergence/rejoin、长度、phase 与原因。

### topologically forced

在**有向 access graph**中移除该 corridor 后，required target 与合法 return set 不可达。

### resource-forced

拓扑仍可达，但在完整、未截断 replacement envelope 中所有替代路径违反 hard budget。

### indeterminate

replacement search 截断、access unknown、graph conflict。

禁止仅凭无向 bridge/biconnected 结论证明 forced。

---

# 12. FullRouteValidator

每个 assembled candidate 必须完全展开到底层 RoadArc，重新计算。

## 12.1 hard checks

1. graph version 与 geometry hash；
2. 每对相邻 arc 拓扑连通；
3. RoadArc direction；
4. access allowed/conditional policy；
5. required traversal 完整、有向覆盖；
6. phase automaton；
7. distance/climb/time hard bounds；
8. route-wide GLO 与 directional ascent/descent；
9. immediate reverse；
10. opposite-direction repeated subpath；
11. connector/core duplication；
12. graph/provider critical conflict；
13. critical unknown；
14. search completeness status；
15. origin/return closure；
16. pattern-specific rules。

## 12.2 hard failure 不能被分数抵消

```text
access_forbidden
direction_violation
topology_break
required_core_not_fully_covered
phase_violation
hard_budget_infeasible
critical_geometry_unknown
critical_access_unknown
avoidable_immediate_reverse
search_truncated_without_policy
```

任一出现，不进入推荐 Pareto 集。

## 12.3 ValidationCertificate

输出：

```text
candidate_structure_hash
expanded_arc_sequence_hash
graph/access/DEM versions
resource recomputation
required coverage witnesses
phase trace
retrace witnesses
evidence integration hash
hard_gate results
typed failures
```

---

# 13. 排序、Pareto 与结构多样性

## 13.1 软目标向量

\[
F(R)=
\begin{bmatrix}
|D-D^*|\\
|G-G^*|\\
|T-T^*|\\
ConnectorRatio\\
AvoidableRetraceLength\\
CriticalUncertainty\\
- EvidenceCoverage\\
- SupportLB\\
EvidenceBoundWidth\\
- RepeatProxy\\
- IntentProxy\\
ContinuityPenalty
\end{bmatrix}
\]

不同 rider intent 选择不同 versioned lexicographic policy，不把所有维度压成一个固定加权和。

## 13.2 排序流程

```text
1. 删除 hard-gate fail
2. 区分 complete search 与 truncated search
3. 计算 Pareto 非劣集
4. 应用 intent-specific lexicographic policy
5. stable tie-break:
     structure signature
     expanded arc hash
     candidate ID
```

## 13.3 结构签名

```text
entry portal
exit portal
ordered mountain corridor sequence
key climb sequence
cycle/out-and-back/hill-repeat type
mountain backbone arc signature
```

市区小 connector 差异不自动形成新路线。

## 13.4 结构距离

组合：

- mountain phase length-weighted edge overlap；
- corridor sequence edit distance；
- entry/exit；
- route pattern；
- key climb order；
- opposite-direction backbone overlap。

阈值由骑手 pair label 校准。

## 13.5 最多三条

候选池规模允许时，对 \(k\le3\) 直接枚举小组合，按：

```text
quality policy
minimum pairwise structural distance
set-level dispersion
```

选最优集合，而不是必须贪心 farthest-first。

- 每个结构 class 最多一条；
- 只有两条合格就返回两条；
- 没有合格路线返回 typed no-result；
- 不用 connector 微调凑数。

---

# 14. 关键伪代码

## 14.1 ProjectionSet

```python
def project_observation(obs, graph, params):
    samples = deterministic_resample(
        obs.geometry,
        policy=params.resampling_policy,
        metric_crs=params.metric_crs,
    )

    candidate_layers = []
    dependency_arcs = set()

    for sample in samples:
        arcs = graph.spatial_index.query(
            sample,
            radius=params.query_radius(obs.geometry_resolution),
        )

        # 注意：不按当前 access 删除候选。
        states = []
        for arc in stable_sort(arcs, key=arc_stable_key):
            dependency_arcs.add(arc.id)
            states.append(
                MatchState(
                    arc=arc,
                    emission=emission_cost(sample, arc, params),
                    access_state=arc.access_state,
                )
            )
        candidate_layers.append(states)

    paths = deterministic_top_k_viterbi(
        candidate_layers,
        transition=lambda left, right, delta:
            topology_transition_cost(
                graph=graph,
                left=left,
                right=right,
                source_delta=delta,
                params=params,
            ),
        top_k=params.top_k,
        tie_break=path_signature,
    )

    hypotheses = [
        build_projection_hypothesis(path, obs, graph, params)
        for path in paths
    ]

    raw_check = raw_curve_cross_check(obs, hypotheses, params)
    quality = projection_quality(obs, hypotheses, raw_check)

    return select_projection_set(
        hypotheses=hypotheses,
        quality=quality,
        candidate_dependency_arcs=stable_ids(dependency_arcs),
        policy=params.selective_policy,
    )
```

## 14.2 relation candidate generation

```python
def generate_relation_candidates(observations, indexes):
    pairs = set()

    for bucket in indexes.source_exact_undirected.values():
        pairs.update(all_unordered_pairs(bucket))

    for bucket in indexes.support_signature.values():
        pairs.update(all_unordered_pairs(bucket))

    for obs in stable_sort(observations, key=lambda x: x.id):
        for other in indexes.raw_subcurve_rtree.query(
            expanded_raw_envelope(obs)
        ):
            pairs.add(stable_pair(obs.id, other.id))

    for arc_id in stable_sort(indexes.arc_postings):
        postings = indexes.arc_postings[arc_id]
        for left, right in interval_overlap_sweep(postings):
            pairs.add(stable_pair(
                left.observation_id,
                right.observation_id,
            ))

    return stable_sort(pairs)
```

## 14.3 relation classification

```python
def classify_relation(obs_a, obs_b, proj_a, proj_b, config):
    if exact_source_identity_compatible(obs_a, obs_b):
        if obs_a.undirected_exact_hash == obs_b.undirected_exact_hash:
            return exact_source_relation(obs_a, obs_b)

    if not projection_sets_relation_eligible(proj_a, proj_b, config):
        return indeterminate("projection_quality_or_multimodality")

    hypothesis_results = []
    for ha, hb in compatible_hypothesis_pairs(proj_a, proj_b):
        components = align_to_overlap_components(ha, hb, config)
        raw_witness = raw_pair_alignment(obs_a, obs_b, config)
        hypothesis_results.append(
            summarize_components(
                obs_a, obs_b, components, raw_witness, config
            )
        )

    consensus = relation_consensus(hypothesis_results, config)
    if not consensus.determinate:
        return indeterminate(consensus.reason, witnesses=hypothesis_results)

    return PairRelation(
        extent=consensus.extent,
        direction=consensus.direction,
        components=consensus.components,
        quality=consensus.quality,
        closure_safe_contains=exact_support_contains_flag(
            proj_a, proj_b, consensus
        ),
    )
```

## 14.4 evidence bounds

```python
def build_directed_evidence_intervals(
    road_arc,
    accepted_projection_postings,
    heat_manifest,
):
    postings = [
        p for p in accepted_projection_postings
        if p.snapshot_cohort == heat_manifest.snapshot_cohort
        and p.projection_status in heat_manifest.accepted_statuses
    ]

    # 先按 provenance-identical fact 去重。
    postings = collapse_identical_source_facts(postings)

    boundaries = {0, road_arc.length_quantized}
    for p in postings:
        boundaries.add(p.start_measure_q)
        boundaries.add(p.end_measure_q)

    for interval in consecutive_intervals(sorted(boundaries)):
        covering = [
            p for p in postings
            if p.continuously_covers(interval)
        ]

        if not covering:
            yield EvidenceInterval.unobserved(road_arc, interval)
            continue

        athlete_counts = [p.athlete_count for p in covering
                          if p.athlete_count is not None]

        lower = max(athlete_counts) if athlete_counts else None
        upper = sum(athlete_counts) if athlete_counts else None

        yield EvidenceInterval(
            road_arc_id=road_arc.id,
            measure=interval,
            reach_union_lower_bound=lower,
            reach_union_upper_bound=upper,
            bound_width=bound_width(lower, upper),
            snapshot_comparability=snapshot_comparability(covering),
            projection_quality_floor=min_quality(covering),
            supporting_fact_ids=stable_fact_ids(covering),
            normalized_support_envelope=optional_shadow_envelope(
                covering, heat_manifest
            ),
        )
```

## 14.5 bounded route search

```python
def search_routes(intent, carrier_graph, evidence, config):
    search_graph = contract_for_search(
        carrier_graph,
        area_role_profile=intent.area_role_profile,
        policy=config.contraction_policy,
    )

    portals = derive_portals(search_graph, intent)
    lower_bounds = precompute_admissible_bounds(
        search_graph,
        intent.origin,
        intent.return_destination,
    )

    portal_pairs = feasible_portal_pairs(
        portals, lower_bounds, intent, config
    )

    expansion_budget = config.max_expanded_labels
    expanded = 0
    complete_candidates = []

    for entry, exit in stable_sort(portal_pairs):
        envelope = build_portal_pair_envelope(
            search_graph, entry, exit, lower_bounds, intent, config
        )

        frontier = stable_priority_queue()
        labels = ExactLabelSets()
        frontier.push(initial_core_label(entry, intent))

        while frontier:
            if expanded >= expansion_budget:
                return SearchResult.truncated(
                    candidates=complete_candidates,
                    expanded=expanded,
                    frontier_summary=summarize_frontier(frontier),
                )

            label = frontier.pop()
            expanded += 1

            if violates_admissible_hard_bound(label, lower_bounds, intent):
                continue
            if labels.is_exactly_dominated(label):
                continue

            labels.insert(label)

            if reaches_exit_with_valid_pattern(label, exit, intent):
                complete_candidates.append(label)
                if len(complete_candidates) >= config.max_complete_candidates:
                    break
                continue

            for edge in stable_sort(envelope.outgoing(label.vertex)):
                nxt = transition_product_graph(label, edge, intent)

                if not phase_transition_allowed(nxt):
                    continue
                if route_access_fail(nxt, intent):
                    continue
                if hard_resource_fail(nxt, intent):
                    continue
                if illegal_repeat_pattern(nxt, intent):
                    continue

                frontier.push(nxt)

    assembled = assemble_with_connector_alternatives(
        complete_candidates, intent, search_graph, config
    )

    validated = [
        validate_full_route(c, intent, carrier_graph, evidence, config)
        for c in assembled
    ]

    feasible = [r for r in validated if r.hard_gate_pass]
    return rank_and_select_diverse(feasible, intent, limit=3, config=config)
```

---

# 15. 病态情况与机械处理

| 病态 | 正确处理 |
|---|---|
| 发卡弯两段空间很近 | source order、heading、graph transition；不靠 point-to-line |
| 桥上桥下平面相交 | level/road identity 无连接 |
| 双向分隔道路 | 独立 carrier edges/arcs |
| 当前 access forbidden 但历史线真实经过 | projection 保留；route eligibility fail |
| graph 缺路、raw 高一致 | relation 可 raw-supported；route search 不直接使用 |
| graph/raw 冲突 | indeterminate |
| 环线起终点相同 | ordered cyclic alignment，不用 endpoint |
| 环线因起点旋转而采样不同 | circular sequence alignment；不自动 exact |
| self-overlap | multiplicity 与 occurrence index |
| A 内两个 B embedding | relation 可 contains，但 attribution 位置歧义；必要时 indeterminate |
| same/reverse 两个共享 component | extent partial_overlap，direction mixed |
| 极短赛段 | 与噪声尺度比较；gray/indeterminate |
| 多 provider split 不同 | graph-version-local signature + raw witness |
| 新 observation 仅细分 evidence cell | 路线积分不变 |
| dense same-corridor component | arrangement/on-demand relation；超预算 typed pending |
| route 经过热门 cell 两次 | popularity 积分一次；distance/load 计两次 |
| 无 Strava 证据 connector | unobserved/coverage 下降，不解释为不热门 |
| directed graph 有替代路，无向图无桥 | 使用 directed reachability |
| replacement search 截断 | avoidability indeterminate |
| soft heat 更新 | 不重跑 feasibility pool，只重积分/排序 |
| graph/access 更新 | topology-dependent route pool 失效 |

---

# 16. 参数校准

| 参数/政策 | 校准方法 |
|---|---|
| metric CRS 与 distortion 验证 | 西山边界内距离/角度误差检查 |
| source/measure quantization | 数值重放稳定性与人工 endpoint residual；低于语义阈值、高于浮点噪声 |
| raw R-tree expansion | full 3240 pair non-disjoint recall vs candidate reduction |
| resampling policy | projection accuracy、top-K recall、运行成本 |
| emission distance/heading | projection gold 正确/错误候选分布 |
| transition model | gold path graph/source distance residual |
| top-1/top-2 margin | risk-coverage curve |
| equivalent bands | false equivalent 高代价 selective classification |
| containment bands | false containment、embedding ambiguity |
| meaningful overlap | shared-road human labels与下游影响 |
| exclusive interval bands | equivalent/contains/partial confusion matrix |
| support signature measure quantization | class stability、false merge |
| source exposure model | `source_created_at` completeness 与 holdout predictive value |
| length/climb residual model | leave-one-corridor-family-out CV |
| EB repeat/star priors | marginal likelihood/hierarchical fit；数据不足不启用 |
| phase role/neutral connector allowance | 西山 route regression 与人工结构标签 |
| graph contraction policy | exact path/resource reconstruction |
| expansion budgets | 小 envelope exhaustive oracle 的 feasible-route recall |
| approximate dominance/beam | 仅在 exact oracle 对照后 |
| structural distance | 骑手 pairwise same/different route labels |
| lexicographic intent policy | 冻结 rider choice/rejection episodes |
| time model | 真实活动回测与分层 calibration |

参数产物：

```text
parameter_manifest.json
training/calibration/holdout split hash
fit code version
metrics
promotion decision
```

---

# 17. 当前 81 条数据的标注与评测计划

## 17.1 阶段 A：graph provider 与 raw witness

对 81 条先标：

```text
road/corridor identity
direction
bridge/tunnel/level
parallel-road alternatives
known graph missing
self-overlap
out-and-back
source geometry quality
```

比较 candidate provider 后再冻结 CarrierGraph v1。

## 17.2 阶段 B：Projection gold

每条 observation 标注**可接受 hypothesis 集**：

```text
acceptable ordered carrier arc/slice sequences
source interval mapping
start/end measures
direction
unmatched intervals
parallel alternatives
provider conflicts
multiple equally valid projections
```

指标：

- length-weighted directed arc precision/recall；
- source-interval coverage；
- sequence edit distance；
- endpoint measure error；
- top-1/top-K accuracy；
- abstention precision/coverage；
- ambiguity detection；
- graph-missing detection；
- access-filter leakage test：forbidden arc 仍可正确匹配。

## 17.3 阶段 C：全 3240 pair gold

每对标：

```text
extent
pair direction
all significant overlap components
source intervals
same/reverse orientation per component
exclusive intervals
embedding count
closure-safe containment flag
graph/raw agreement
indeterminate reason
```

按完整 corridor family 分 train/calibration/holdout；建议 leave-one-family-out 报告区间，不只给单次 split。

指标：

- candidate recall for all non-disjoint；
- candidate reduction \(k/3240\)；
- determinate macro-F1；
- false equivalent；
- false containment；
- false direction；
- false proved-disjoint；
- abstention rate；
- risk-coverage；
- fuzzy relation 被错误 closure 的数量必须为 0；
- exact support class pairwise violation 必须为 0；
- input permutation output hash 一致。

## 17.4 阶段 D：evidence 数学不变量

1. duplicate identical fact → 完全不变；
2. derived split with same provenance → 完全不变；
3. independent equivalent segment → lower bound 取 max，不求和；
4. reverse segment → forward 不变；
5. contained segment → 只改变实际 ArcSlice ranges；
6. cell refinement → route integrals 不变；
7. repeated route traversal → popularity credit 一次；
8. different snapshot cohort → 不静默混合；
9. low-quality projection → 不进入生产 evidence；
10. bounds 永远满足 lower ≤ upper；
11. 若可人工构造 athlete sets，真实 union 必在 bounds 内；
12. normalized shadow model 未在 corridor holdout 胜出，不晋级。

## 17.5 阶段 E：路线回归

至少覆盖：

- `avoidable_reverse_retrace`；
- `macro_loop_backtrack`；
- S104 → 周家山 → 古交连续山地骨架；
- 桃花沟不同 Route Pattern；
- 枣杜真实死胡同 forced out-and-back；
- hill-repeat only under explicit intent；
- 无 Strava connector，coverage 降低但可使用；
- same geometry/current forbidden access：projection 成功、route fail；
- bridge/parallel road；
- legal loop；
- graph missing；
- search truncated；
- 城市平路 2–5 小时任务使用不同 automaton。

## 17.6 阶段 F：search oracle

在西山 contracted envelope 上：

1. 小 portal pair 做 exhaustive enumeration；
2. 对照 bounded label-setting：
   - feasible-route recall；
   - Pareto frontier recall；
   - best-policy route regret；
   - label count；
   - expansion budget 命中率；
3. soft heat 完全移除后，feasibility pool 不变；
4. heat-only update 只影响排序；
5. search truncation 永不报告 no feasible route。

## 17.7 阶段 G：增量/full rebuild 等价

逐条模拟：

```text
新增 observation
相同 fact 重复
geometry 微调
方向反转
端点变化
projection hypothesis 改变
删除
graph edge split/merge
access attribute change
heat model version migration
```

在参数冻结的 operational update 下要求：

```text
incremental relation/evidence/route ranking hashes
==
full rebuild hashes
```

模型 refit/graph version migration 不要求旧 version 相同，而要求新 manifest 全量可重放。

---

# 18. Typed failure taxonomy

## Projection

```text
projection_no_candidate
projection_multimodal
projection_graph_missing_raw_supported
projection_graph_raw_conflict
projection_geometry_insufficient
projection_provider_conflict
```

## Relation

```text
relation_threshold_gray_zone
relation_hypothesis_disagreement
multiple_subpath_embeddings
complex_mixed_overlap
disjoint_not_provable
dense_component_pending
```

## Evidence

```text
heat_snapshot_incomparable
heat_metric_missing
heat_projection_quality_insufficient
heat_bound_uninformative
heat_model_not_promoted
```

## Graph/access

```text
no_topological_connection
access_forbidden
access_unknown
graph_lineage_unresolved
critical_topology_conflict
```

## Search/route

```text
hard_budget_infeasible
no_feasible_portal_pair
no_continuous_mountain_phase
required_core_not_fully_covered
avoidable_immediate_reverse
avoidable_macro_backtrack
backtrack_avoidability_indeterminate
full_route_cost_unknown
search_truncated
connector_provider_conflict
no_structurally_diverse_candidate
```

`search_truncated` 与 `no_feasible_*` 绝不能混用。

---

# 19. 被否决的替代方案

## 1. Strava 赛段直接作为路网边

否决：重复表达、方向/长度重叠、connector 缺失、更新导致图漂移、热度与 topology 耦合。

## 2. 按 Strava 起终点切 RoadLeg

否决：来源平台定义越权、图碎片化、ID/cache 全局失效。

## 3. 全量 raw Hausdorff/Fréchet 作为唯一关系真值

否决：不识别 topology/level/parallel road；生产 \(n^2\)；方向与重复路径脆弱。raw alignment 只作 witness/cross-check。

## 4. matcher 中过滤当前 forbidden access

否决：把历史 observation 强吸到错误平行路；混淆“在哪里”与“现在能否使用”。

## 5. fuzzy equivalent pair 做 DSU 或 complete-link partition

否决：不传递；complete-link 分区不唯一；增量分裂非局部。

## 6. 所有 approximate containment 做 DAG closure

否决：容差与 embedding 组合不传递；reachability 会制造未计算事实。

## 7. overlap connected components 当 corridor/segment identity

否决：A-B、B-C overlap 不蕴含 A-C 同一 extent。

## 8. athlete/effort/star 直接相加

否决：未知 athlete set intersections；方向、包含、定义重复造成重复计票。

## 9. 把 cell `max` 称为去重唯一人数

否决：它只是 union lower bound；不是交集估计。

## 10. 要求任意 geometry-equivalent 新证据完全幂等

否决：独立 segment 可提供更强 lower bound；只应禁止线性重复膨胀。

## 11. 81 条直接训练复杂 latent road popularity

否决：定义选择、暴露、长度、区域人口和 endpoint 机制混杂；不可识别，holdout 太小。

## 12. 全图 exact label-setting + 完整 visited bitset、无 envelope

否决：指数状态；伪代码可写但不可运行。

## 13. soft heat 驱动首版 beam/pruning

否决：候选遗漏不可审计；heat 更新改变 feasibility pool；增量/full rebuild 难对齐。

## 14. 无向 bridge 直接证明 forced out-and-back

否决：道路是有向 access graph，且存在资源约束。

## 15. waypoint/entry-exit 命中即视为经过核心

否决：平行路、捷径、方向错误、U-turn、局部覆盖。

## 16. 全部目标压成一个加权分

否决：软热度可抵消硬错误，隐藏 Pareto trade-off。

## 17. 端到端生成路线模型

否决：无硬保证、无足够选择数据、不可审计。

---

# 20. 实施顺序

## 阶段 0：冻结评测合同

- 固定 commit、81+6 manifest、GLO batch；
- 建立 corridor/raw witness；
- 设计 annotation schema；
- 建 deterministic replay harness；
- 在此之前不定正式几何阈值。

## 阶段 1：CarrierGraph bake-off

- provider 对照；
- topology/level/access 审计；
- graph v1；
- lineage schema；
- SearchGraph contraction proof。

## 阶段 2：ProjectionSet

- source exact canonicalization；
- raw subcurve index；
- top-K deterministic matcher；
- access/projection 分离；
- raw cross-check；
- quality vector；
- 81 条 projection gold。

## 阶段 3：RelationWitnessIndex

- overlap components；
- extent/direction selective classifier；
- support signatures；
- exact support classes；
- closure-safe containment；
- fuzzy pair store；
- 3240 oracle；
- incremental neighbor rebuild。

## 阶段 4：Evidence bounds

- directed arrangement；
- provenance collapse；
- lower/upper bounds；
- coverage/uncertainty；
- refinement invariance；
- repeat/star proxy；
- normalized model只做 shadow。

## 阶段 5：Bounded planner

- AreaRoleProfile；
- phase product graph；
- portals；
- lower bounds；
- portal-pair envelope；
- exact bounded label-setting；
- explicit route patterns；
- search truncation contract。

## 阶段 6：Connector 与 Validator

- connector alternatives；
- locked core assembly；
- full GLO/time/distance recomputation；
- directed backtrack proof；
- ValidationCertificate；
- typed failures。

## 阶段 7：Pareto 与 diversity

- hard-gate filter；
- intent lexicographic policy；
- structural signature/distance；
- exact up-to-3 selection；
- route regression。

## 阶段 8：规模化近似

只有在 exact oracle 后引入：

- ng-route memory；
- resource buckets；
- ε-dominance；
- beam；
- evidence-guided priority。

每项必须报告 feasible/Pareto recall 和 `search_truncated`。

## 阶段 9：学习型排序

积累 rider choice/rejection episodes 后：

- latent support model；
- Pareto 内 utility；
- 分 intent calibration；
- shadow → canary → promotion。

---

# 21. 必须先实验才能拍板

1. 哪个道路图/组合能可靠表达西山 81 条来源线。
2. graph provider 更新时 split/merge 与 lineage 成本。
3. top-K HMM/Viterbi 与 raw monotone alignment 的最优组合。
4. projection 允许 hypothesis set 后，abstention/coverage 的合理边界。
5. equivalent/containment/overlap 的 pass/gray/fail bands。
6. exact support signature 的 measure quantization。
7. closure-safe containment 能覆盖多少实际 contains pair。
8. 81 条是否足以做任何 exposure/length correction。
9. `max` lower bound、bounds width 与 shadow residual 对 rider choice 的相对解释力。
10. phase role 与 neutral connector 对“连续山地”的人工一致性。
11. contracted graph 上 exact label 数量。
12. portal-pair envelope 是否保持近 exhaustive feasible recall。
13. directed resource-forced backtrack proof的成本。
14. connector alternatives 数量与总资源影响。
15. route structural distance 的骑手感知阈值。
16. 时间模型在不同 rider profile 下的区间 calibration。
17. 多城市后何时需要近似 dominance/beam。

---

# 22. 最终架构决定

**推荐架构：**

> 构建一个版本化、有向、多重、可线性引用的 Road Carrier Graph；把每条 Strava 线保持为独立 SourceObservation，通过 Multi-Hypothesis Projection 映射到 ArcSlice 序列。关系层保存 overlap components 与 pair witness，只对 exact support signature 建 class，只对 closure-safe containment 建可传递 DAG。热度层不伪造去重骑手数，而输出方向化 union bounds、coverage 与可选 shadow proxy。路线层在收缩后的 portal-pair envelope 上做有明确 expansion budget 的确定性多资源搜索，外部 router 只提供可验证 connector alternatives，最终由 FullRouteValidator 重新证明全程。

这个决定牺牲了三种“看起来漂亮”的简化：

- 不给每条观测强行分配唯一 fuzzy-equivalence family；
- 不输出一个貌似精确的 unique rider heat；
- 不承诺无限道路图上的全局最优路线。

换来的是：

- 不因近似关系传递而误合并；
- 不因 aggregate overlap 不可识别而伪造人数；
- 不因搜索截断而谎报无解；
- 新增/修改一条 observation 时可在参数冻结条件下局部重放；
- 每一个推荐都能给出可审计的 geometry、direction、access、resource、backtrack 与 evidence certificate。

最终安全原则：

> **宁可返回 `indeterminate`、`search_truncated`、较少路线或 typed no-result，也不把图源错误、近似传递、重复热度、当前 access 误吸附或未完成搜索包装成一条“看起来合理”的推荐。**
