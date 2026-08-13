# 附录 A：全国规模扩展——分区、压缩、按需关系与分层求解

> 本附录为 append-only 扩展，不修改主体第 0–22 章的对象、关系、不变量、失败语义和实施顺序。  
> 假设规模：全国存在数万至十万级 `SourceObservation`、百万级 `RoadArc`，并持续发生单条赛段、局部道路和局部 access 更新。  
> 本附录的目标不是承诺“全国图上所有多目标路线均全局最优”，而是明确全国总量如何被分解为**版本化分区、局部 posting、查询 envelope、portal overlay 与有限 label frontier**，并说明 exact、approximate 与 `search_truncated` 的机械边界。

---

## A.0 不改变主体的全国扩展原则

主体中的以下结论在全国规模下仍保持不变：

1. `SourceObservation` 仍然是来源观测，不是道路图边。
2. `RoadCarrierGraph`、`ProjectionSet`、`RelationWitnessIndex`、`DirectedEvidenceField` 与路线求解层仍严格分离。
3. exact、反向、包含、重叠最终仍由可审计的有序 `ArcSlice` witness 决定；任何近似索引只能做候选召回，不能成为最终关系真值。
4. fuzzy `spatial_equivalent` 不形成强制 partition；只有 exact support signature 可以形成安全 group。
5. 只有 closure-safe containment 可以做传递归约；approximate containment 保持 pair witness。
6. 热度仍是部分识别、方向化证据，不伪造唯一骑手数。
7. ML 永远不能决定几何关系、access、拓扑连通、hard feasibility 或 Validator 结果。
8. `search_truncated` 永远不能被包装成 `no_feasible_route`。

全国化新增的是四个计算层，不是新的事实语义：

```text
HierarchicalStorageTiles
        +
NestedRoutingPartitions / DirectionalPortals
        +
SignatureGroup + IntervalArrangement Compression
        +
NationalOverlay → RegionalCorridor → LocalContracted Search
```

---

# A.1 全国规模的符号、密度与复杂度合同

## A.1.1 全局规模符号

设：

| 符号 | 含义 |
| --- | --- |
| \(N\) | 全国 active `SourceObservation` 数量；目标量级 \(10^4\sim10^5\) |
| \(H_i\) | observation \(i\) 保留的 `ProjectionHypothesis` 数；accepted primary、并列最优和必要 alternative 均计入 |
| \(H=\sum_iH_i\) | 全国 retained projection hypothesis 总数 |
| \(G\) | exact `support_signature_group` 数量；group 的成员是 projection hypothesis，因此 \(G\le H\)，不保证 \(G\le N\) |
| \(M\) | `RoadCarrierEdge` 数量 |
| \(A\) | 有向 `RoadArc` 数量；全国目标量级约 \(10^6\) |
| \(R_i\) | observation \(i\) 经 deterministic resampling 后的 matcher 点数 |
| \(R=\sum_iR_i\) | 全国 matcher 输入点总数 |
| \(T_{i,h}\) | observation \(i\) 的 hypothesis \(h\) 的 canonical token 数 |
| \(P=\sum_{i,h}T_{i,h}\) | hypothesis 级 `ArcSlice posting occurrence` 总数 |
| \(U\) | exact support group 去重后的 canonical token 总数，\(U\le P\) |
| \(p_a\) | RoadArc \(a\) 上的**group-occurrence 级** interval posting 数；同一 group 重复经过同一 arc 会产生多个 posting |
| \(p_a^{member}\) | 若展开到 hypothesis member 后的 posting 数；仅用于审计，不用于几何主索引 |
| \(b_a\) | RoadArc \(a\) 上 arrangement boundary 数，\(b_a\le2p_a+2\) |
| \(r_a\) | RoadArc \(a\) 上 active-set pattern run 数，\(r_a\le b_a-1\) |
| \(L\) | routing partition 层数 |
| \(\mathcal P_\ell\) | 第 \(\ell\) 层 nested graph partition |
| \(b(c)\) | partition cell \(c\) 的 direction/turn-aware portal state 数 |
| \(Q\) | 一次在线查询或单 observation 更新形成的局部 envelope |
| \(A_Q\) | envelope 中 RoadArc 数量 |
| \(P_Q\) | envelope 中被读取的 posting 数量 |
| \(G_Q\) | envelope 中被触及的 support signature group 数量 |
| \(K_Q\) | 经 exact index 召回后真正进入 relation witness 计算的 group pair 数 |
| \(V_Q,E_Q\) | local contracted search graph 的顶点和边数量 |
| \(H_Q\) | national/regional overlay 查询触及的 portal/shortcut 数量 |
| \(Z_Q\) | multi-resource route solver 实际扩展的 label 数量 |
| \(C_{rel}\) | 一次候选 group pair 精确关系计算的平均成本 |

`posting` 的计数单位必须明确：

```text
一个 projection hypothesis 在同一 RoadArc 上出现两次
→ 两个 posting occurrence，不能集合化为一个。

同一 exact support group 有 100 个 hypothesis member
→ group relation index 只存 canonical sequence 中每个 occurrence 一次；
  member/provenance/quality 另存，不把 100 个成员展开为 100 份几何 posting。

同一 SourceObservation 可以拥有多个 retained hypothesis
→ 它可以出现在多个 support group；只有主体规则允许的 accepted primary
  hypothesis 才能进入正式 evidence，alternatives 只用于歧义与关系召回。
```

## A.1.2 局部密度符号

全国平均密度没有决策价值；复杂度由局部热点决定。定义：

\[
\lambda_a = p_a
\]

表示 arc 级 group posting 压力；若需要按长度归一化：

\[
\bar\lambda_a = \frac{p_a}{\max(L_a,\epsilon)}
\]

查询 envelope 的平均 posting 密度：

\[
\lambda_Q = \frac{P_Q}{\max(|A_Q|,1)}
\]

但 pair explosion 更准确的压力不是 \(p_a\)，而是 arrangement 每个 cell 的 distinct active group 数。设 arc \(a\) 的 arrangement cells 为 \(J_a\)，cell \(j\) 的 distinct active group 数为 \(h_{a,j}\)，另记 active posting occurrence 数为 \(m_{a,j}\)。relation pair 压力按 \(h_{a,j}\) 计算，但 arrangement 必须保存 \(m_{a,j}\) 的 occurrence/multiplicity。若物化所有 overlap pair，潜在输出压力为：

\[
X_a = \sum_{j\in J_a}\binom{h_{a,j}}{2}
\]

同一 pair 可能在多个 cell 出现，因此 \(X_a\) 是上界型 workload 指标，不是唯一 pair 数。它用于判断是否进入 heavy-corridor 压缩模式。

全国查询必须以 envelope-local 变量报告成本：

```text
不报告“全国有 100,000 条赛段，所以查询是 O(100,000)”；
报告“本次 envelope 触及 8,200 个 arcs、31,000 个 group postings、420 个 candidate groups”。
```

## A.1.3 存储复杂度

不物化全国 pair 表时，核心存储上界为：

\[
O(M+A+P+U+\sum_a r_a+C_{cache})
\]

其中：

- \(M+A\)：道路载体图与方向状态；
- \(P\)：observation projection/posting；
- \(U\)：group 去重后的 canonical token sequence；
- \(\sum_a r_a\)：heavy arc/corridor 的 arrangement run；
- \(C_{cache}\)：有容量和 TTL/version 边界的 on-demand relation cache。

明确禁止的全国存储：

\[
\Theta(N^2)
\]

的 observation pair relation 表，或：

\[
\Theta(G^2)
\]

的 group pair relation 表。

若调用方明确要求导出所有 pair，则输出本身存在 \(\Omega(Z)\) 下界，其中 \(Z\) 为实际返回 pair 数；系统应分页、异步离线导出或返回 `relation_output_too_large`，不能假装索引能消除输出下界。

## A.1.4 核心操作复杂度

### 单条 observation map matching

设 observation \(i\) 的每个 resampled point 平均召回 \(c_i\) 个 RoadArc candidate；候选只在相交 storage tiles 和 halo 中搜索。一个 top-K Viterbi/HMM 类 matcher 的主要成本写为：

\[
O\left(
R_i\log A_{tile(i)}
+
R_i c_i^2 C_{trans}
\right)
\]

其中：

- \(A_{tile(i)}\) 是本次实际加载分区中的 arc 数，而非全国 \(A\)；
- \(C_{trans}\) 是一次候选状态转移的局部路网成本；应通过局部 transition cache 或 bounded shortest-path 限制；
- top-K 是版本化预算，不把未搜索完的路径解释为不存在。

### projection token 与 posting 更新

一条 observation 的 canonical tokenization：

\[
O(T_i)
\]

将 \(T_i\) 个 interval posting 写入按 arc 分区的排序/LSM 结构，摊销为：

\[
O\left(
\sum_{t\in i}\log p_{arc(t)}
\right)
\]

批量构建时可以按 `arc_id` 外排，成本为：

\[
O(P\log P)
\]

或按已分桶数据写成：

\[
O\left(P+\sum_a p_a\log p_a\right)
\]

### exact/reverse lookup

对 query group token sequence \(S_g\)：

\[
O(|S_g|)
\]

计算 directed/reversed signature，哈希查找平均 \(O(1)\)。返回成员列表的成本与输出成员数成正比。

### on-demand relation query

令 query group \(g\) 触及的 interval index 输出总量为 \(Z_g\)，经去重后 candidate group 数为 \(K_g\)。则：

\[
O\left(
|S_g|\log p_{max}
+
Z_g
+
K_gC_{rel}
\right)
\]

其中 \(p_{max}=\max_{a\in S_g}p_a\)。这是 output-sensitive 成本；与全国 \(N\) 解耦。

### evidence 查询或局部重建

对 envelope \(Q\)：

\[
O\left(
P_Q\log P_Q + \sum_{a\in A_Q}r_a
\right)
\]

若 arrangement 已构建，读取现有 evidence pattern 的成本接近：

\[
O\left(
|A_Q| + \text{decoded pattern bytes}
\right)
\]

### 分层路线查询

全国 overlay 的 scalar lower-bound/portal skeleton 查询近似：

\[
O\left((V_O^Q+E_O^Q)\log V_O^Q\right)
\]

regional corridor 展开成本记为 \(C_Q^{regional}\)，local multi-resource solver 为：

\[
O\left(Z_Q\log Z_Q + \text{transition expansions}\right)
\]

其中 \(Z_Q\) 在最坏情况下仍可指数增长。全国分区不能消除资源约束路径问题的 NP-hard 性；它只能使在线求解依赖局部 envelope 和 portal skeleton，而不是扫描百万级全图。

---

# A.2 全国道路图：双重分区、跨区 portal 与局部失效

## A.2.1 必须区分 storage tile 与 routing partition

全国系统需要两套正交分区：

### 1. `StorageTile`

用途：

- 几何存储；
- R-tree/GiST/H3/S2 等空间召回；
- projection posting 分片；
- 数据下载、缓存和版本发布；
- graph delta 的空间定位。

它可以是固定的层级地理网格，但只提供**存储和粗召回**。不能用“同一格/父子格”证明：

- 道路拓扑连通；
- 桥上桥下相同；
- 两条道路属于同一 corridor；
- route 可以跨越格边界。

### 2. `RoutingCell`

用途：

- 图分区；
- portal 数量最小化；
- overlay shortcut；
- metric customization；
- exact lower bound；
- route search envelope。

`RoutingCell` 必须从 `RoadCarrierGraph` 的方向、turn state、access 与切边结构产生，而不是直接把地理网格当路由图分区。

因此：

```text
StorageTile 是“数据在哪里”；
RoutingCell 是“搜索如何跨区域”；
两者可以互相映射，但不能合并为一个真值对象。
```

## A.2.2 Nested routing partition

构造嵌套分区：

\[
\mathcal P_0 \prec \mathcal P_1 \prec \dots \prec \mathcal P_L
\]

其中：

- \(\mathcal P_0\)：最细 local cells；
- 中间层：城市、城市群、区域 corridor cells；
- 顶层：省际/全国 overlay cells；
- 每个 child cell 只属于一个 parent cell；
- RoadArc 有唯一 canonical owner cell；跨边界只保存只读 stub/portal reference，避免双写真值。

分区优化目标不是单一“边数均衡”，而是：

\[
\min
\left(
\alpha\cdot\text{edge imbalance}
+
\beta\cdot\text{directional portal count}
+
\gamma\cdot\text{turn-state boundary count}
+
\delta\cdot\text{historical query cut rate}
\right)
\]

这里的 \(\alpha,\beta,\gamma,\delta\) 不能凭感觉设置；应在冻结 workload 上比较：

- overlay 大小；
- portal-pair customization 成本；
- p95/p99 查询触及 cell 数；
- graph delta 导致的 ancestor 重建范围。

分区版本独立于 graph metric 版本：

```text
partition_topology_version
road_graph_version
metric_customization_version
access_snapshot_version
```

道路权重或热度更新不应自动触发 repartition。

## A.2.3 Portal 必须是方向和 turn-aware state

一个普通 boundary vertex 不足以描述跨区可达性。Portal state 至少包含：

```text
portal_id
boundary_anchor_id
cell_id
parent_cell_id
direction: enter / exit
incoming_arc_or_turn_state
outgoing_arc_or_turn_state
access_class
level / bridge / tunnel state
graph_version
```

在 edge-based/turn-aware graph 中，portal 更准确地表示：

\[
p=(v,a_{in},a_{out},dir,access)
\]

而不是单独的 \(v\)。这样才能避免：

- 同一交叉点不同转向被错误合并；
- 单行道跨 cell 后方向丢失；
- 禁止左转/掉头在 overlay 中被绕过；
- 桥隧层级在边界处被压平。

跨区 RoadArc 的 ownership 规则必须确定性：

```text
canonical owner = stable_min(cell_id of tail/head under partition version)
```

或其他固定规则。相邻 cell 只保存 portal stub 和 owner reference。

## A.2.4 Overlay summary 的 exact 边界

对 cell \(c\) 的 portal pair \((p,q)\)，可以保存：

```text
portal_from
portal_to
metric_version
exact scalar shortest distance/time lower bound
turn-aware witness path hash
witness child cells
access summary
resource lower-bound vector
optional Pareto summaries
```

### 对单一非负可加标量 metric

若 cell 内部所有 boundary-to-boundary shortest paths 被完整 customization，overlay 可以保持 exact shortest-path 语义。

### 对多资源、phase、history 和 backtrack 状态

若要全局 exact，必须为 portal pair 保存所有不可支配状态：

```text
distance
climb
time
phase
intent progress
used-road / repeat state
uncertainty
```

其数量可能指数增长。因此全国 overlay 默认只承担：

1. exact scalar lower bounds；
2. hard reachability/access pruning；
3. portal skeleton candidate generation；
4. local solver 的 admissible heuristic。

除非明确物化了完整 state-lifted Pareto set，否则 overlay 不得声称完成全国多资源 exact 求解。

## A.2.5 全国 graph 的两类 customization

### topology customization

触发：

- RoadArc 新增/删除；
- 交叉口连接变化；
- turn restriction 变化；
- bridge/tunnel/level 变化；
- partition portal 变化。

影响：local cell + 必要 halo + ancestors。

### metric customization

触发：

- distance/time/grade cost 变化；
- 当前 access 状态变化；
- surface/road class preference 变化；
- 用户 profile metric 变化。

若 topology 未变，只需重算受影响 cell 的 portal-pair cost 和 ancestors；不应重跑所有 observation map matching。

## A.2.6 增量 map matching 的 dependency footprint

每个 `ProjectionSet` 除主体已有字段外，全国版必须保存：

```text
source_geometry_hash
matcher_version
road_graph_version
storage_tile_versions_loaded
routing_cells_loaded
candidate_arc_ids_considered
candidate_arc_geometry_versions
transition_subgraph_ids_considered
top_k_projection_arc_ids
raw_buffer_envelope
parallel-road alternatives
```

这形成 `candidate_dependency_footprint`。道路 delta 到来后，不采用“同一城市全部重匹配”，而按以下集合召回：

\[
O_{affected}
=
O_{lineage}
\cup
O_{candidate\_arc}
\cup
O_{raw\_envelope}
\cup
O_{transition\_subgraph}
\]

其中：

- \(O_{lineage}\)：旧 arc 被 split/merge/replace 的 projection；
- \(O_{candidate\_arc}\)：matcher 曾考虑过发生变化的 candidate arc；
- \(O_{raw\_envelope}\)：原始折线 buffer 与新增/移动道路相交；
- \(O_{transition\_subgraph}\)：候选间 transition witness 所依赖的局部拓扑变化。

只记录最终 top-1 path 不够，因为新增一条平行道路可能让此前未选中的 alternative 变为最优。

## A.2.7 graph delta 的局部失效分类

| delta 类型 | Projection | Relation | Evidence | Route/Overlay |
| --- | --- | --- | --- | --- |
| 仅 speed/time metric 变化 | 不失效 | 不失效 | 不失效 | metric customization；相关 route cache 失效 |
| 当前 access 变化、几何拓扑不变 | 不重匹配 | 几何关系不失效 | 道路证据仍保留，route eligibility 分离 | access summary、route cache、Validator 失效 |
| RoadArc 属性变化但不影响候选几何 | 通常不重匹配 | support signature 可保持 | 对应展示属性更新 | local/ancestor overlay 重定制 |
| 中心线局部移动 | dependency footprint 命中者重评 | 相关 signature/relation 失效 | 受影响 arrangement 失效 | local route cache 失效 |
| 1→1 lineage 且存在严格单调 measure map | 可做 deterministic remap | 重新 hash 后局部关系重算 | 局部重建 | local/ancestor overlay 更新 |
| split/merge 且 lineage 可精确展开 | token 重写，不必重新 HMM；仍需 quality recheck | group membership 与关系局部重建 | 局部重建 | local/ancestor overlay 更新 |
| 新增平行路、拓扑连接变化 | footprint 内 observation 重匹配 | 局部关系重建 | 局部重建 | topology customization |
| partition 变化、RoadArc identity 不变 | 不失效 | 不失效 | 不失效 | overlay/portal 全部按 partition version 重建 |
| matcher 参数/模型版本变化 | 属于算法迁移，不是数据增量 | 相关全量重建 | 相关全量重建 | route cache 版本隔离 |

## A.2.8 局部失效闭包

全国更新采用依赖闭包：

```text
changed road arcs / topology
        ↓
affected ProjectionSet
        ↓
affected support_signature_group membership
        ↓
affected interval arrangement / on-demand relation cache
        ↓
affected DirectedEvidenceInterval
        ↓
affected route cache / portal customization
```

闭包先限制在最小 RoutingCell + halo。只有出现以下情况才升级到 parent：

1. cell portal set 变化；
2. boundary reachability 变化；
3. portal-pair lower bound 变化；
4. child shortcut witness 穿过变化 arc；
5. parent 的 metric summary 依赖变化 child summary。

若变化一直传播到顶层，也只是 overlay ancestor customization，不等于全国 observation 全量重匹配。

应记录 typed 更新结果：

```text
lineage_remapped
local_rematch_complete
local_relation_rebuilt
ancestor_overlay_recustomized
partition_rebuild_required
algorithm_version_migration_required
```

---

# A.3 将关系转化为 directed road token sequence 与按需 witness

## A.3.1 Canonical directed road token

在固定：

```text
road_graph_version
linear_reference_version
projection_normalization_version
```

下，把每个 retained `ProjectionHypothesis` \(h\) 表达为 token sequence：

\[
S_{i,h}=[\tau_1,\tau_2,\dots,\tau_{T_{i,h}}]
\]

每个道路 token：

\[
\tau=(a,\mu_s,\mu_t)
\]

其中：

- \(a\)：有向 RoadArc ID；
- \(\mu_s,\mu_t\)：该 RoadArc 上 deterministic fixed-point linear measure；
- sequence position 天然保留同一 RoadArc 的重复出现；posting record 另外派生 `visit_index` 作为 occurrence identity，但 `visit_index` 不进入 token equality；
- unmatched source interval 以显式 gap token 表达，不能静默删除。gap token 至少包含 source-measure 区间和 raw subcurve hash，避免不同缺口被错误分到同一 support group。

measure exact equality使用 graph builder 的固定点整数表示；不使用米级容差。容差只进入 fuzzy relation witness，不进入 exact signature。

对反向 RoadArc \(\bar a\)，定义 token reverse transform：

\[
\rho(a,[\mu_s,\mu_t])
=
(\bar a,[L_a-\mu_t,L_a-\mu_s])
\]

完整序列反向：

\[
\rho(S_{i,h})
=
[\rho(\tau_{T_{i,h}}),\dots,\rho(\tau_1)]
\]

反向 posting 时再按新顺序派生 `visit_index`；它只标识 occurrence，不改变 token sequence 的几何语义。

## A.3.2 三种不可混淆的 identity

### source exact identity

```text
source_exact_directed_hash
source_exact_undirected_hash
```

证明来源点序列 exact/reverse exact。

### support exact identity

```text
support_directed_signature = H(S_{i,h})
support_undirected_signature = min(H(S_{i,h}), H(ρ(S_{i,h})))
```

证明在固定 graph/projection version 下支持 token sequence exact/reverse exact。

### fuzzy spatial relation

由 `OverlapComponent`、raw alignment 和 quality vector 判定；绝不能写入 exact signature group。

## A.3.3 全国关系索引

全国版至少需要六类索引：

### 1. signature dictionary

```text
support_directed_signature → support_group_id
support_undirected_signature → forward_group_id / reverse_group_id
```

### 2. group membership

```text
support_group_id →
  (observation_id, projection_hypothesis_id, hypothesis_rank,
   acceptance_state, evidence_eligible, quality_ref, provenance_ref)
```

成员 ID 可用 delta-varint/Roaring bitmap 辅助压缩，但完整 membership record 不能只剩 observation bitmap，因为同一 observation 可以有多个 hypothesis。几何只存一份 canonical group sequence；member-specific raw residual、quality 和 provenance 仍独立保存。

### 3. ArcSlice interval postings

```text
arc_id →
  group_id
  measure_start
  measure_end
  sequence_position
  visit_index
  projection_hypothesis_group_version
```

每个 arc 使用 interval tree、segment tree、sorted endpoint stream 或 immutable run + delta LSM。

### 4. carrier-symbol q-gram inverted index

先从 support token 派生 candidate-only carrier symbol：

```text
kappa(token) = arc_id / explicit_gap_symbol
```

对**interior full-arc symbols**建立：

```text
hash(kappa[j:j+q]) → (group_id, sequence_position)
```

不能把首尾 partial-token 的 exact measure 直接放进 containment q-gram，否则短区间被长区间包含时二者 token 不相等，会产生 false negative。对没有足够 interior full-arc q-gram 的短 sequence，使用首尾 ArcSlice interval posting + exact boundary verification。

### 5. sequence prefix/rolling hash

每个 support group 保存：

```text
prefix_hash
reverse_prefix_hash
token_count
length
first/last partial-token metadata
```

在候选起点已知后，以 \(O(1)\) hash + exact token readback 验证 contiguous subsequence；hash 只能预筛，最终仍逐 token 验证碰撞。

### 6. raw subcurve R-tree

只处理：

- graph 缺路；
- projection indeterminate；
- graph/raw conflict；
- candidate recall 审计。

它不承担全国主要 relation index。

## A.3.4 exact 与反向

对 observation/group \(g\)：

```text
exact_same_direction:
  lookup H(S_g)

exact_reverse_direction:
  lookup H(ρ(S_g))
```

复杂度：

\[
O(|S_g|+output)
\]

若 group member 数巨大，API 默认返回 group summary，不自动展开全部 observation member。

## A.3.5 closure-safe containment

只对 exact support sequence 定义可传递 containment。

设较短 sequence 为 \(S_s\)，较长为 \(S_l\)。必要条件：

1. \(S_s\) 的 carrier-token 顺序在 \(S_l\) 中存在连续 embedding；
2. interior full-token 完全相等；
3. 第一个和最后一个 partial token 的 interval 被较长 path 对应 interval 精确包含；
4. sequence multiplicity 与 gap token 内容一致；`visit_index` 只用于区分候选 occurrence，不要求较短和较长 sequence 的绝对 ordinal 相等；
5. embedding 唯一，或调用方明确请求所有 embedding。

候选生成：

1. 从 \(S_s\) 的 interior full-arc carrier symbols 中选 posting frequency 最低的 q-gram；若不存在，则使用首尾 ArcSlice interval posting intersection；
2. 查出可能的 \((group,position)\)；
3. 用长度、首尾 arc、partition path summary 剪枝；
4. rolling hash 预校验；
5. exact token readback；
6. 输出 embedding witness。

若较短 sequence 存在至少 \(q\) 个连续 interior full-arc symbols，exact containment 必然共享这些 carrier-symbol q-gram，因此选择 rarest q-gram 不降低 exact recall。只有 partial boundary、单 arc 或极短 sequence 不满足此前提，必须走 interval-posting fallback。反向 containment 通过对 \(\rho(S_s)\) 执行同一流程处理。

单 query 成本：

\[
O(|S_s|+f^*(S_s)+K_sC_{verify})
\]

其中 \(f^*\) 是所选 rare q-gram 的 posting frequency。

## A.3.6 approximate containment

approximate containment 不进入 q-gram exact closure。其候选来自：

- ArcSlice interval overlap postings；
- raw buffered subcurve；
- exact support near-neighbor；
- projection alternative 的局部相交。

最终必须重新计算 component witness。它只能缓存 pair result，不能从 A contains B、B contains C 推导 A contains C。

## A.3.7 partial overlap

对 query group \(g\)：

1. 对每个 token 的 arc interval 查询相交 group postings；
2. 合并同一 candidate group 的 token-position match；
3. 在 source sequence position 上做稀疏 ordered chaining；
4. 生成 maximal `OverlapComponent`；
5. 分别计算同向、反向和 mixed witness；
6. raw monotone alignment cross-check；
7. 由主体 Relation Engine 汇总 extent/direction。

若 candidate token match 集为 \(Y_{g,h}\)，pair 计算不需要构造 \(|S_g|\times|S_h|\) 的完整矩阵，而只在实际共享 arc/interval 的稀疏 match 上链式处理：

\[
O\left(|Y_{g,h}|\log|Y_{g,h}|+C_{raw\_check}\right)
\]

## A.3.8 on-demand relation cache

缓存 key：

```text
road_graph_version
relation_parameter_version
projection_signature_a
projection_signature_b
support_group_a
support_group_b
```

group-level 缓存 value：

```text
support_extent
support_direction
graph-supported overlap_components
embedding witnesses
computed_at
```

member-specific quality、raw alignment 和 graph/raw agreement 不放入 group cache；它们进入独立的 `ObservationPairRelationCache`：

```text
observation_a / observation_b
retained_hypothesis_set_hashes
raw_geometry_hashes
member_quality_refs
final extent/direction or indeterminate
```

以下变化不应误失效 `GroupSupportRelationCache`：

- athlete/effort/star 更新；
- route ranking model 更新；
- 当前 access 更新但 graph geometry/topology 不变；
- member raw geometry 变化但 canonical support group 未变。

以下变化必须失效 group cache：

- 任一 support signature 变化；
- graph lineage 改写相关 arcs；
- support-relation parameter version 变化。

raw geometry hash、member quality 或 retained hypothesis set 变化只失效对应 observation-pair cache。两类缓存均采用容量上限、版本前缀和 LFU/LRU 混合淘汰；它们是加速层，不是真值层。

## A.3.9 group relation 与 observation relation 的组合边界

`SupportSignatureGroup` 只证明 graph-supported token sequence 相同，不证明所有 member 的 raw source geometry、projection margin 和 provider conflict 都相同。因此全国版分两步：

1. `GroupSupportRelation`：在 canonical group sequence 之间计算 exact/reverse/closure-safe containment/graph-supported overlap；
2. `ObservationPairRelation`：把两条 observation 的 retained hypothesis 组合、member-specific raw alignment、quality vector 和 graph/raw conflict 加回来。

若同一 observation 的多个 retained hypothesis 对 pair relation 给出不一致结论，或某个 member 的 raw witness 与 group support relation 冲突，最终 observation pair 必须降级为 `indeterminate`，不能因为 group 已缓存而强行继承。

因此：

```text
group cache = 可复用的支持路径关系
member evaluation = 最终 observation pair 的质量/冲突裁决
```

Evidence 层只读取 `evidence_eligible=true` 的 accepted primary hypothesis；alternative hypothesis 不能同时向多个走廊贡献热度。

---

# A.4 超热门走廊：避免 pair explosion 的压缩结构

## A.4.1 热门走廊的真正问题

若 \(n_c\) 条 observation 全部覆盖同一热门爬坡，直接物化 pair 关系需要：

\[
\Theta(n_c^2)
\]

但实际独立几何信息通常远少于 \(n_c\)：

- 多个 observation 可能有相同 source exact geometry；
- 更多 observation 可能有相同 support token sequence；
- 其余 observation 主要表现为同一 carrier path 上不同起终 measure；
- 只有少数分叉、折返、反向或 raw conflict 需要 pair witness。

因此压缩必须按“事实 → exact support → interval arrangement → on-demand pair”逐级进行。

## A.4.2 第一层：provenance fact collapse

同一来源平台、同一 source segment、同一 snapshot/geometry hash 的重复写入只保留一个事实节点：

```text
ProvenanceFactKey =
(source_platform, source_segment_id, snapshot_id, geometry_hash)
```

这保证真正幂等。

## A.4.3 第二层：support signature group

所有 exact support token sequence 相同的 projection hypothesis 进入：

```text
SupportSignatureGroup
```

group 保存：

```text
canonical directed token sequence
reverse signature
member hypothesis/provenance IDs
member statistics/time snapshots
member raw/quality references
projection quality envelope
```

graph-supported relation 计算发生在 group，而不是重复计算每个 member hypothesis；最终 observation pair 仍按 A.3.9 合并 member-specific raw/quality。若走廊中 \(h_c\) 个 retained hypothesis 压缩为 \(g_c\) 个 group，则支持路径 relation 的最坏 pair 基数从：

\[
\binom{h_c}{2}
\]

降为：

\[
\binom{g_c}{2}
\]

但仍不应默认全部物化。

## A.4.4 第三层：deterministic CarrierBlock coordinate

为压缩连续多 arc posting，可从主体的 reversible contracted graph 派生 `CarrierBlock`：

- block 是确定性的有向 token block；
- 必须可无损展开到底层 RoadArc；
- 只用于存储/索引压缩；
- 不宣称 block 是新的“物理道路身份”；
- branch、turn ambiguity、level/access 变化处必须断开。

对严格沿同一 block 单调前进的 projection，可把多个 full-arc token 压成：

```text
(block_id, block_measure_start, block_measure_end, direction)
```

这使一条长爬坡的 interval arrangement 不必在每个 RoadArc 重复维护相同 active set。

## A.4.5 第四层：interval arrangement event stream

对 heavy RoadArc/CarrierBlock，存 endpoint events：

```text
measure
add_posting_occurrence_ids
remove_posting_occurrence_ids
```

按 measure sweep 得到 active posting-occurrence multiset，并同时派生 distinct active group bitmap。相邻 cells 只有在 occurrence multiset 与 group bitmap 都相同的情况下才合并为一个 run：

```text
[start, end, active_pattern_id]
```

`active_pattern_id` 指向 interned pattern：

```text
pattern_id →
  compressed posting-occurrence bitmap / sequence-position refs
  + derived distinct-group bitmap
```

relation 查询必须读取 occurrence/sequence-position，才能保留同一 group 对同一 arc 的多次访问；evidence 查询则按主体 provenance-collapse 规则从 occurrence 派生一次性的 group/provenance 支持，不能把重复访问重复加热度。

构建成本：

\[
O(p_c\log p_c)
\]

存储约为：

\[
O(p_c+r_c+bitmap\ bytes)
\]

而不是 \(O(p_c^2)\)。

## A.4.6 第五层：按需 relation，而不是 pair 表

热门走廊默认提供以下查询：

```text
which posting occurrences and groups cover this interval?
which groups contain this query interval?
which groups overlap this projection hypothesis?
what are the maximal shared components of group A and B?
```

而不是：

```text
materialize every pair among all groups on this corridor
```

对 query interval 的 stabbing/reporting：

\[
O(\log p_c+z)
\]

其中 \(z\) 是返回 posting occurrence/group 数；若返回 bitmap，解码成本与压缩后输出字节数相关。

## A.4.7 coverage-pattern compression

若热门走廊上很多相邻 cells 的 active occurrence/group pattern 仅发生少量增删，可使用：

- checkpoint bitmap；
- delta add/remove event；
- periodic full snapshot；
- persistent bitmap tree。

选择依据是实际：

```text
full bitmap bytes
vs.
checkpoint + delta bytes
vs.
query decode latency
```

不能固定“每 100 个边界做一次 checkpoint”之类未经 benchmark 的值。

## A.4.8 closure-safe containment 的 Hasse edge

只有在以下条件同时满足时，热门 corridor 才可物化立即 containment parent/child：

1. group 都映射到同一 deterministic CarrierBlock coordinate；
2. interval exact nesting；
3. direction 相同；
4. 不存在额外 token/gap/branch；
5. embedding 唯一。

此时可按：

```text
start ascending
end descending
```

的 sweep/stack 计算 interval nesting Hasse edges，成本：

\[
O(g_c\log g_c)
\]

跨 block、带分叉、multi-visit 的 containment 仍按需计算，不强行塞进 corridor interval DAG。

## A.4.9 heavy-corridor 触发条件

不按“posting 超过某个拍脑袋数字”触发。对每个 candidate heavy unit \(c\)，估计：

\[
Cost_{pair}(c)
=
\hat c_{pair}\cdot X_c
+
\hat m_{pair}\cdot Z_c
\]

以及：

\[
Cost_{arr}(c)
=
\hat c_{sort}p_c\log p_c
+
\hat c_{pattern}r_c
+
\hat m_{bitmap}\cdot bytes_c
\]

当：

```text
Cost_pair exceeds rebuild/query budget
or
Cost_arr is empirically lower while preserving exact recall
```

进入 arrangement mode。

`heavy` 是 workload/version 属性，不是永久道路标签。

## A.4.10 无法消除的输出下界

如果调用方要求：“列出此走廊上所有互相 partial-overlap 的 group pair”，且实际有 \(Z\) 个 pair，则任何算法都至少需要：

\[
\Omega(Z)
\]

的输出时间。正确策略是：

- group-level 返回；
- pagination/cursor；
- interval query；
- relation-on-demand；
- typed `relation_output_too_large`；
- 离线 export job。

不能用“分布式”掩盖输出本身的二次规模。

---

# A.5 全国路线搜索：National Overlay、Regional Corridor、Local Contracted 三层

## A.5.1 三层图的职责

### 1. `NationalOverlayGraph`

节点：

- 高层 directional portals；
- 省际/城市群边界 portal；
- 重要长距离 corridor 入口。

边：

- cell 内 portal-to-portal scalar shortest-path shortcut；
- 跨 cell canonical connector；
- exact lower-bound resource summary；
- 可展开 witness/child summary。

职责：

- 全国 reachability；
- distance/time admissible lower bound；
- 长距离 portal skeleton；
- partition pruning。

不负责：

- 完整多资源 history；
- 方向热度最终积分；
- macro backtrack 最终证明；
- hard Validator。

### 2. `RegionalCorridorGraph`

节点：

- 城市/山地 portal；
- corridor junction；
- 训练区域边界；
- route phase transition anchor。

边：

- 可无损展开的 contracted corridor；
- 多个结构不同的 portal-pair alternatives；
- distance/time/climb/evidence/uncertainty summary；
- route pattern metadata。

职责：

- 枚举区域结构骨架；
- 避免全国 overlay 直接展开城市每条小路；
- 形成 local exact envelope 的候选 corridor set。

### 3. `LocalContractedGraph`

包含 query envelope 内：

- 所有 hard-relevant RoadArc；
- turn/access state；
- ArcSlice evidence；
- 完整 route history tracking；
- locked core 与 connector alternatives。

职责：

- multi-resource exact/approx label-setting；
- phase automaton；
- repeat/backtrack 分类；
- 完整 arc-sequence candidate；
- FullRouteValidator。

## A.5.2 用 admissible potential 构造 exact budget envelope

全国图不能先凭经验裁一个城市 bbox，再声称全局完备。若用户给出 hard distance 上限 \(D_{max}\)，点到点任务 \(o\to t\) 的 arc \(a=(u,v)\) 只有在：

\[
LB_D(o,u)+L(a)+LB_D(v,t)\le D_{max}
\]

时才可能属于可行路线。

因此 exact distance envelope 可定义为：

\[
A_Q^D=
\left\{
(u,v)
\mid
LB_D(o,u)+L(u,v)+LB_D(v,t)\le D_{max}
\right\}
\]

对 origin-return loop：

\[
A_Q^{loop}=
\left\{
(u,v)
\mid
LB_D(o,u)+L(u,v)+LB_D(v,o)\le D_{max}
\right\}
\]

只要 lower bound admissible，删除 envelope 外 arc 不会删除任何满足 distance hard bound 的路线。

同理可使用 time lower bound 取交集：

\[
A_Q=A_Q^D\cap A_Q^T
\]

climb 通常只有非负下界 0，剪枝能力弱，但仍可用于已消耗资源检查。

若用户不给任何有限 hard bound，系统不能宣称构造了有限且全局 complete 的 nationwide envelope。必须：

- 从产品 task policy 获得明确上限；
- 或返回 `unbounded_route_scope`；
- 或明确进入 approximate exploratory mode。

## A.5.3 分层求解流程

```text
1. origin/destination/mandatory core 定位到 local cells
2. NationalOverlay 计算 exact scalar lower bounds
3. 用 hard budget 构造可证明的 partition envelope
4. 枚举 portal skeletons
5. RegionalCorridorGraph 展开结构骨架与 alternatives
6. 形成 local contracted graph union
7. 运行 phase-aware multi-resource solver
8. 展开所有 shortcut 到底层 RoadArc
9. FullRouteValidator 全程重算
10. Pareto + structural diversity + optional ML reorder
```

`portal skeleton` 可以限制 query cost，但 exact mode 与 approximate mode 必须分开：

- exact mode：local graph 包含由 admissible hard-bound 证明的完整 envelope，skeleton 只用于排序、lower bound 和 expansion order；
- approximate mode：local graph 只取 top-K skeleton 的 corridor tube/union，此时可能漏解，完整性状态必须降级。

## A.5.4 完备、近似和截断状态

### `global_exact`

只有同时满足：

1. query scope 有有限 hard bound；
2. envelope 由 admissible lower bound 证明完整；
3. overlay 对所需 state 是 exact，或只用于不丢解的 lower bound；
4. local solver 未采用 beam、resource bucket 或 ε-dominance；ML pruning 在本设计中始终禁止；
5. frontier 被完全穷尽或被现有解严格支配；
6. graph/access/resource 数据完整；
7. FullRouteValidator 通过。

全国多资源路线一般很难达到该状态，但标量最短路可以。

### `exact_within_declared_envelope`

local solver 在给定 envelope 内完整，但 envelope 由产品区域或人工 corridor 限定，而非全局 hard-bound 证明。必须把 envelope manifest 返回给调用方。

### `exact_within_portal_skeleton_set`

对已枚举 skeleton 完整，但 skeleton 集不是全部可能 portal 序列。不能声称全国完备。

### `approximate_feasible`

使用任一：

- top-K portal skeleton；
- ε-dominance；
- resource bucketing；
- beam；
- approximate nearest-neighbor candidate recall；
- 非完备 corridor alternative set。

所有输出仍必须通过 hard Validator，但可能漏掉更优或其他可行路线。

### `feasible_not_proven_optimal`

已找到至少一个 hard-feasible route，但 frontier 尚未证明无更优解。

### `search_truncated`

固定 expansion/label/deterministic-byte budget 到达，且 frontier 中仍存在未被 incumbent/Pareto set 证明支配的 label。预算必须按 label 数、transition 数或可重复计算的序列化字节计量，不能依赖 wall-clock 或进程 RSS 的偶然波动。

必须保存：

```text
expanded_label_count
frontier_size
frontier_best_lower_bound
incumbent_objective_or_pareto
budget_version
resume_token_or_frontier_hash
```

### `proven_infeasible`

只有 exact envelope、完整数据和未截断 frontier 下才能返回。若只是 top-K skeleton 无解，不能返回该状态。

## A.5.5 route query complexity

一次查询成本写成：

\[
C_Q=
C_{overlay}(H_Q)
+
C_{regional}(Q)
+
C_{local}(V_Q,E_Q,Z_Q)
+
C_{validate}(|R|)
\]

而不是：

\[
C_Q=O(A)
\]

其中：

\[
C_{overlay}=O((V_O^Q+E_O^Q)\log V_O^Q)
\]

local solver 最坏仍由 \(Z_Q\) 决定。若 query 是 2–5 小时本地骑行，hard budget envelope 通常只触及少量 partitions；若 query 是跨省超长路线，envelope 自然扩大，成本应随请求范围增长，而不是假装仍为常数。

## A.5.6 Shortcut witness 与最终验证

每条 overlay/corridor shortcut 必须保存：

```text
shortcut_id
from_portal
to_portal
child_version
metric_version
witness_path_hash
child_shortcut_ids or RoadArc expansion
lower_bound vector
access summary
```

最终 candidate 必须展开到 RoadArc。Validator 不接受只有 shortcut ID 的路径，因为：

- evidence 需要 ArcSlice 积分；
- backtrack 需要底层重复道路；
- access/turn 需要逐 arc 验证；
- graph delta 需要 witness dependency；
- core coverage 需要 exact token sequence。

## A.5.7 全国 route cache 的局部失效

route cache key 至少包含：

```text
origin/destination cell
RouteIntent hash
road_graph_version
access_snapshot_version
metric_version
overlay_version
planner_version
evidence_version
ranking_model_version(optional)
```

依赖记录：

```text
used RoadArc IDs
used shortcut IDs
touched partition cells
portal skeleton
evidence pattern IDs
```

道路 delta 只失效依赖变化 witness 的 cache；ranking model 更新只失效排序结果，不失效 hard-feasible candidate/ValidationCertificate。

---

# A.6 查询复杂度如何与全国总量解耦

## A.6.1 解耦机制

全国总量解耦依赖以下链条：

```text
query geometry / intent
        ↓
storage-tile + routing-cell envelope
        ↓
local ArcSlice postings / support groups
        ↓
on-demand relation witness
        ↓
portal overlay skeleton
        ↓
local contracted search labels
```

在线查询不扫描：

- 全国所有 observations；
- 全国所有 support groups；
- 全国所有 RoadArcs；
- 全国所有 relation cache；
- 全国所有 route candidates。

## A.6.2 各操作的真正依赖量

| 操作 | 依赖全国总量吗 | 在线主要依赖 |
| --- | --- | --- |
| exact/reverse 查询 | 否 | query token length + hash output |
| 单 group containment 查询 | 否 | rare q-gram frequency + candidate verify |
| 单 group overlap 查询 | 否 | query arcs 的 interval posting 输出 |
| 局部 evidence 读取 | 否 | envelope pattern runs/bitmap bytes |
| 本地路线规划 | 否 | portal skeleton + local graph + label frontier |
| 单 observation 增量 | 否 | candidate dependency footprint + local closure |
| 全国 graph version migration | 是 | \(A+P\)，离线任务 |
| heat model 全量 refit | 是 | 训练数据量，离线任务 |
| 导出全部 pair | 是 | 实际输出 pair 数 |
| 无界全国探索请求 | 是 | 请求本身没有有限 envelope |

## A.6.3 破坏解耦的四类请求

1. “列出全国所有重叠 pair”；
2. “在没有距离/时间/区域上限的全国图找任意最优环线”；
3. graph/matcher/relation algorithm version 全量迁移；
4. 要求一次 query 同时比较全国所有城市/走廊。

这些不是索引失败，而是请求输出或搜索域本身接近全局。系统应将其转为：

- offline job；
- 分页/分区结果；
- 明确 budget；
- typed unbounded/global migration 状态。

---

# A.7 ML 仅用于证据补全与 hard-feasible 候选排序

## A.7.1 机械边界

允许的 ML 位置只有：

```text
A. road evidence completion / uncertainty
B. hard-feasible candidate ranking
```

禁止 ML：

- 生成 RoadArc topology；
- 判断 exact/reverse/containment/overlap；
- 覆盖 access hard rule；
- 决定 route 是否连通；
- 删除唯一 hard-feasible route；
- 将 `search_truncated` 改写为 `no route`；
- 绕过 FullRouteValidator。

## A.7.2 道路证据补全的训练对象

现有 aggregate 不能提供“真实唯一骑手流量”。因此 evidence model 不能以伪造真值为目标。建议分成两个输出：

### 1. observation propensity

\[
\pi_c=P(\text{cell }c\text{ 获得可见来源观测}\mid x_c,region,time)
\]

用于描述：某类道路被创建 Strava segment、被采集并进入冻结输入的概率。

### 2. conditional evidence distribution

对已观测 cell：

\[
y_c^{reach}=\log(1+A_c^{LB})
\]

或主体定义的 repeat/intent proxy，学习：

\[
p(y_c\mid observed,x_c)
\]

模型输出必须命名为：

```text
imputed_observable_evidence
```

而不是：

```text
true road popularity
```

只有在 propensity 可识别、positivity 成立并通过 holdout 后，才可形成带 selection correction 的 latent proxy；仍不得称为真实流量。

## A.7.3 evidence model 的训练目标

推荐多任务但不绑定具体模型：

```text
loss =
  propensity calibration loss
+ observed-evidence quantile loss
+ temporal holdout loss
+ corridor/city holdout loss
```

输出：

```text
P10 / P50 / P90 evidence proxy
observation propensity
OOD score
support count / effective sample size
model version
```

使用 quantile/interval 输出而不是单点分数，原因是：

- source selection 非随机；
- 不同城市覆盖差异大；
- 冷门道路经常是“没被观测”，不是“没人骑”；
- 全国迁移存在显著 domain shift。

## A.7.4 曝光偏差与选择偏差

### 来源赛段偏差

Strava segment 的存在受：

- 用户创建行为；
- 平台活跃度；
- 城市覆盖；
- 道路知名度；
- 赛段长度与爬坡定义习惯；
- 数据可见/采集协议；
- 时间窗口。

影响。缺失不是随机负样本。

因此：

1. 不把“没有 segment”标成 0 popularity；
2. propensity 需要来自随机/系统性道路审核、跨来源覆盖或已知采样协议；
3. 只有 \(\pi_c>0\) 且支持区间重叠时才使用 inverse propensity weighting；
4. 权重必须 clip，并报告 effective sample size；
5. 仅有 position propensity 不足以自动修正 trust bias；若展示位置同时改变用户对路线质量的信任，需要随机干预或更完整的 exposure model；
6. propensity 不可识别或接近 0 时模型 abstain。

### route ranking 曝光偏差

用户只能选择被展示的候选；高排名候选天然获得更多点击/接受。训练不能把未展示路线当负样本。

必须记录：

```text
candidate_set_id
all generated-and-validated candidates in this search run
search completeness / approximation status
which candidates were displayed
display position
logging policy probability
user action: choose/reject/no-choice
route completed or abandoned
intent/context
```

未生成或未展示的路线不能被当作负样本；当 search 本身为 approximate/truncated 时，日志必须保留该状态。训练使用：

- randomized/interleaved exploration traffic；
- propensity-weighted pairwise/listwise loss；
- 或 doubly robust estimator；
- 仅在同一次 candidate set 中建立 preference comparison。

没有可验证 logging propensity 时，只能做 supervised shadow study，不能宣称无偏排序。

## A.7.5 hard-feasible candidate ranker 的目标

输入只来自：

```text
FullRouteValidator hard_gate_pass == true
```

训练目标可为：

1. 用户在同一候选集中的选择；
2. explicit reject/no-choice；
3. 实际完成率；
4. 完成后的满意度；
5. 与 intent 的 pairwise preference。

pairwise propensity-weighted objective 示例：

\[
\min_\theta
\sum_e
w_e
\log\left(1+\exp\left[-(f_\theta(R_e^+)-f_\theta(R_e^-))\right]\right)
\]

其中：

\[
w_e=\operatorname{clip}\left(\frac{1}{\pi_e},w_{max}\right)
\]

\(\pi_e\) 必须来自版本化 logging policy，而不是模型自行猜测。

ranker 只能：

- 重排 hard-feasible Pareto/候选集；
- 在满足结构多样性约束后选择展示顺序；
- 给解释层提供软偏好贡献。

ranker 不能改变 candidate 的 ValidationCertificate。

## A.7.6 冷启动

### 新城市/新道路

若没有足够 observed evidence 或 propensity support：

```text
imputed evidence = unavailable
uncertainty = high
fallback evidence = source-derived lower/upper bounds or zero-with-unknown flag
```

不能用全国平均强行填高热度。

### 新用户

使用：

- 明确 RouteIntent；
- 人群级但保守的版本化 deterministic policy；
- Pareto + lexicographic fallback；
- 可选少量显式偏好问题。

不从年龄、设备等弱代理推断高风险骑行偏好。

### 新 route pattern

模型未见过的 pattern 进入 OOD；回退到 deterministic ranking，不允许因高不确定性被误当高分。

## A.7.7 置信度与 abstention

ML confidence 不是 feasibility probability。必须分开：

```text
prediction interval
calibration error
OOD distance
training support count
effective sample size
propensity range
model freshness
```

模型可用于线上重排的必要条件：

1. 当前样本在训练支持域内；
2. 分组 calibration 达标；
3. prediction interval 宽度低于版本化接受门；
4. propensity/ESS 足够；
5. model/data version 未过期；
6. shadow/holdout 未发现安全回归。

否则：

```text
ml_abstained = true
```

## A.7.8 机械 fallback

```python
if not model_available:
    return deterministic_pareto_lexicographic_rank(candidates)

if model_stale or ood or calibration_failed:
    return deterministic_pareto_lexicographic_rank(candidates)

if prediction_uncertainty_too_high or propensity_support_insufficient:
    return deterministic_pareto_lexicographic_rank(candidates)

ranked = model_reorder(candidates)
return enforce_validator_and_structural_diversity(ranked)
```

fallback 必须：

- 无模型也能完整运行；
- 结果 deterministic；
- 保留 hard-feasible candidates；
- 不依赖网络模型服务可用性；
- 返回 `ranking_policy=deterministic_fallback`。

## A.7.9 ML promotion gate

模型从 shadow 晋级必须同时满足：

1. hard-feasible acceptance 错误仍为 0，因为 Validator 不变；
2. route-choice holdout 按 city/corridor/time 分组，而非随机 row；
3. 对 cold-start/OOD 子集有明确 abstention；
4. IPS/SNIPS/DR 等离线估计与随机流量方向一致；
5. calibration 和 prediction interval 覆盖达标；
6. deterministic fallback 可随时接管；
7. 排序版本、训练数据 hash、logging policy 均可追溯。

---

# A.8 城市级与全国级 scale trigger

## A.8.1 先定义可测预算

所有 trigger 从目标硬件、服务 SLO 和离线 rebuild window 推导，不直接写死赛段数。定义：

```text
B_rel_offline      一次离线批次可承受的精确 relation compare 数
B_post_online      单 query 可解码的 posting/pattern 字节或数量
B_label_online     单 query 可扩展的 deterministic label 数
B_overlay_memory   overlay portal summary 内存预算
B_cell_portal      单 cell 可承受 portal state 数
B_rebuild_time     局部/全国版本发布窗口
B_cache_memory     relation/route cache 容量
```

通过 benchmark 得到：

```text
ĉ_rel_p95          一次精确 relation witness 的 p95 成本
ĉ_label_p95        一个 label 扩展成本
m̂_rel              一个 pair result 的平均存储
m̂_portal           一个 portal summary 的平均存储
```

由此推导：

\[
B_{pair}
=
\min\left(
\frac{B_{rebuild\_time}}{\hat c_{rel,p95}},
\frac{B_{storage}}{\hat m_{rel}}
\right)
\]

这比“超过 5,000 条就近似”更可审计。

## A.8.2 城市级 trigger

### Trigger C1：停止 full all-pairs materialization

城市 observation 数为 \(N_c\)。若：

\[
\binom{N_c}{2}>B_{pair}
\]

则：

- 评测集不再全量 materialize；
- 生产始终使用 index + on-demand；
- 保留分层抽样和小 corridor oracle；
- 这不是近似，最终 pair relation 仍 exact witness。

### Trigger C2：启用 signature group

实际上从第一版就应启用。若：

\[
\frac{H_c}{G_c}>1
\]

或 token 压缩比：

\[
\frac{P_c}{U_c}>1
\]

说明已有重复 support；group 立即减少几何重复。即使压缩比接近 1，group 仍提供稳定 cache key。

### Trigger C3：启用 heavy-corridor arrangement

对 arc/block \(c\)，若：

```text
predicted pair materialization cost > B_dense
or
online interval query decompression > B_post_online
```

启用 event stream + active-pattern bitmap。最终 relation 仍 on-demand exact。

### Trigger C4：routing partition 从单城图升级为多层

若冻结 workload 的 p99 exact envelope 扫描满足任一：

```text
|A_Q| exceeds online arc budget
portal-free Dijkstra latency misses SLO
local graph cannot remain in target cache
single-cell delta rebuild exceeds release window
```

引入 nested RoutingCell/portal overlay。

### Trigger C5：从 exact local search 升级到 approximate local search

必须先完成：

1. reversible contraction；
2. admissible lower bounds；
3. exact dominance；
4. phase pruning；
5. portal-pair envelope；
6. hard resource bounds。

若之后仍满足：

```text
p99 Z_Q > B_label_online
or
search_truncated rate > accepted SLO
or
memory frontier > B_frontier
```

才进入：

- ε-dominance；
- resource buckets；
- bounded beam；
- top-K regional alternatives。

并返回 `approximate_feasible` 或 `search_truncated`。不能为了平均延迟直接让 ML 删 hard-feasible branch。

### Trigger C6：raw geometry candidate 近似化

只有当 exact R-tree/subcurve 查询的 candidate output 本身超过预算，才允许增加 ANN/LSH/learned prefilter。要求：

- 在 full pair/corridor holdout 上 non-disjoint candidate recall 达到版本化目标；
- raw exact geometry verification 保留；
- 低置信或 OOD 自动回退 exact spatial query；
- final relation 不近似。

## A.8.3 全国级 trigger

在“数万至十万赛段 + 百万 RoadArc”的假设下，以下不是未来优化，而应从全国版第一天启用：

1. StorageTile 分片；
2. nested RoutingPartition；
3. direction/turn-aware portals；
4. support signature group；
5. ArcSlice interval postings；
6. on-demand relation；
7. heavy-corridor arrangement；
8. national/regional/local 分层搜索；
9. graph lineage dependency index。

### Trigger N1：增加 partition 层级

若顶层/中层 query 的 p99：

```text
portal nodes touched > B_overlay_query
or
overlay search latency misses SLO
or
single parent cell contains too many child portals
```

增加一层或重新平衡 partition。

### Trigger N2：repartition

仅当：

\[
\frac{b(c)}{|E_c|}
\]

的 portal ratio、cell imbalance、historical query cut rate 或 delta rebuild scope 持续超出 benchmark 接受域时触发。普通道路更新只 customization，不 repartition。

### Trigger N3：全国 multi-resource overlay 从 exact Pareto summary 降为近似

若所有 portal-pair 不可支配 label 总量：

\[
\sum_{(p,q)}|\mathcal L_{p,q}|
>
B_{overlay\_memory}
\]

则不能继续声称 state-lifted exact overlay。可选择：

- 只保留 exact scalar lower bounds；
- ε-Pareto portal summaries；
- top-K structural corridor alternatives；
- 把完整 multi-resource 状态推迟到 local solver。

状态必须标为 approximate skeleton，不影响最终 hard Validator。

### Trigger N4：relation index 分片

若：

```text
P or arrangement bytes exceed one shard memory/rebuild budget
```

按 canonical storage owner tile/partition 分片；跨 tile observation 的 posting 分别落到涉及 arc 的 owner shard，group metadata 由 stable group owner 持有。查询通过 envelope 只 fan-out 到相交 shards。

这改变部署，不改变 relation 算法。

### Trigger N5：全国 exact route request 降级

若 hard-bound envelope 本身满足：

```text
A_Q > exact national route budget
or
Z_Q prediction > B_label_online
or
portal skeleton set cannot be exhaustively enumerated
```

系统必须在以下三者中明确选择：

1. 要求用户缩小预算/区域；
2. 运行 offline exact job；
3. 在线 approximate search，并返回 approximation manifest。

不能静默截断后声称最优。

## A.8.4 “升级”并不总是“近似”

全国扩展的优先顺序：

```text
full materialization
→ exact index + on-demand
→ exact group/arrangement compression
→ exact partition/lower-bound envelope
→ exact contracted local search
→ 最后才是 approximate candidate/search
```

以下升级仍是 exact：

- hash/signature group；
- interval tree；
- arrangement；
- on-demand relation；
- nested partition；
- scalar exact overlay；
- reversible contraction；
- admissible envelope；
- deterministic cache。

真正 approximate 的只有：

- approximate spatial candidate prefilter；
- top-K portal skeleton；
- ε-dominance/resource buckets；
- beam；
- 不完整 regional alternatives；

## A.8.5 近似算法 promotion gate

任一 approximation 上线前必须证明：

1. final Validator 未改变；
2. hard-infeasible route acceptance 仍为 0；
3. 对 exact oracle 小图的 hard-feasible recall 达到版本化门槛；
4. relation candidate prefilter 对 non-disjoint recall 达标；
5. approximation 参数和误差界被写入 manifest；
6. budget hit 返回 `search_truncated`，不伪造无解；
7. exact fallback/offline replay 可用；
8. incremental 与 full rebuild 在同 approximation manifest 下 hash 一致。

---

# A.9 推荐的全国级核心数据结构

本节只定义计算对象，不要求立即改写现有 persistence。

## A.9.1 `RoadPartitionVersion`

```text
id
road_graph_version
partition_algorithm_version
parent_version
level_count
cell_count
portal_count
input_graph_hash
build_manifest
status
```

## A.9.2 `RoutingCell`

```text
partition_version
cell_id
level
parent_cell_id
owned_arc_range_or_bitmap
boundary_portal_ids
bbox/storage_tile_refs
edge_count
portal_count
query_workload_stats
```

## A.9.3 `DirectionalPortalState`

```text
portal_id
cell_id
anchor_id
enter_exit
incoming_arc_state
outgoing_arc_state
access_class
turn_state
parent_portal_id
graph_version
```

## A.9.4 `OverlayShortcut`

```text
partition_version
metric_version
from_portal
to_portal
scalar_lower_bounds
optional_pareto_summary
witness_child_ids
witness_hash
access_summary
customization_status
```

## A.9.5 `SupportSignatureGroup`

```text
group_id
road_graph_version
projection_version
directed_signature
undirected_signature
canonical_token_blob_ref
reverse_group_id
member_record_ref
member_bitmap_ref(optional acceleration)
member_hypothesis_count
distinct_observation_count
quality_envelope
```

## A.9.6 `ArcSlicePostingRun`

```text
arc_or_block_id
posting_run_version
sorted interval records
delta run refs
min/max measure
group_count
checksum
```

## A.9.7 `HeavyIntervalArrangement`

```text
arc_or_block_id
arrangement_version
boundary_event_blob
pattern_run_blob
pattern_dictionary_ref
occurrence_multiplicity_preserved
evidence_collapse_policy_version
source_posting_hash
build_stats
```

## A.9.8 `GroupSupportRelationCache` 与 `ObservationPairRelationCache`

```text
GroupSupportRelationCache:
  relation_cache_key
  support_group_a
  support_group_b
  support_relation_parameter_version
  graph_overlap_component_blob
  support_extent
  support_direction
  expires_or_version_bound

ObservationPairRelationCache:
  observation_a
  observation_b
  retained_hypothesis_set_hashes
  raw_geometry_hashes
  member_quality_version
  final_extent
  final_direction
  indeterminate_reason
  expires_or_version_bound
```

## A.9.9 `ProjectionDependencyFootprint`

```text
observation_id
source_geometry_hash
road_graph_version
candidate_tile_versions
candidate_arc_bitmap
transition_subgraph_bitmap
top_k_arc_bitmap
raw_buffer_geometry
```

## A.9.10 `RouteQueryManifest`

```text
query_id
intent_hash
origin/destination
hard_bound_manifest
partition/overlay versions
declared envelope cells/arcs
portal skeleton policy
search mode: exact/approximate
expansion/label budgets
approximation parameters
frontier hash
validation certificate refs
ranking policy/model version
```

---

# A.10 全国版关键伪代码

## A.10.1 on-demand relation query

```python
def query_relations(group_id, relation_kind, indexes, versions):
    group = indexes.signature_groups.get(group_id)
    tokens = group.canonical_tokens

    if relation_kind in {"exact", "reverse"}:
        signatures = exact_and_reverse_signatures(tokens, versions)
        return indexes.signature_dictionary.lookup(signatures)

    candidate_groups = set()

    # Exact interval postings are the complete graph-supported overlap recall path.
    for token in tokens:
        hits = indexes.interval_postings[token.arc_id].overlap(
            token.measure_start,
            token.measure_end,
        )
        candidate_groups.update(hit.group_id for hit in hits)

    if relation_kind == "closure_safe_contains":
        rare_qgram = choose_rarest_interior_carrier_qgram(
            tokens, indexes.qgram_frequency
        )
        if rare_qgram is not None:
            candidate_groups &= indexes.qgram_index.lookup(rare_qgram)
        else:
            candidate_groups &= boundary_interval_containment_candidates(
                tokens, indexes.interval_postings
            )

    # Raw geometry only supplements graph-supported recall/conflict analysis.
    if group.requires_raw_fallback:
        raw_hypothesis_hits = indexes.raw_rtree.query(group.raw_expanded_envelope)
        candidate_groups.update(
            indexes.hypothesis_to_group[h] for h in raw_hypothesis_hits
        )

    results = []
    for other_id in stable_sort(candidate_groups - {group_id}):
        key = relation_cache_key(group_id, other_id, versions)
        cached = indexes.relation_cache.get(key)
        if cached is not None:
            results.append(cached)
            continue

        relation = compute_group_support_relation_witness(
            group,
            indexes.signature_groups.get(other_id),
            versions,
        )
        indexes.relation_cache.put(key, relation)
        results.append(relation)

    # Final observation-pair relation is composed later with member raw/quality.
    return stable_sort_relations(results)
```

## A.10.2 graph delta invalidation

```python
def invalidate_graph_delta(delta, deps, partitions):
    affected_observations = set()

    affected_observations |= deps.by_old_arc_ids(delta.lineage_old_arc_ids)
    affected_observations |= deps.by_candidate_arc_ids(delta.changed_arc_ids)
    affected_observations |= deps.by_transition_subgraphs(delta.changed_subgraphs)
    affected_observations |= deps.by_raw_envelope(delta.changed_geometry_envelope)

    if delta.kind == "metric_only":
        recustomize_metric_cells(delta.cells_and_ancestors)
        invalidate_route_cache_by_shortcuts(delta.changed_shortcuts)
        return UpdateResult(metric_only=True)

    remapped = set()
    rematch = set()
    for obs_id in stable_sort(affected_observations):
        if has_exact_monotone_lineage_remap(obs_id, delta):
            deterministic_token_remap(obs_id, delta)
            remapped.add(obs_id)
        else:
            rematch.add(obs_id)

    recompute_projection_sets(rematch)
    changed_groups = rebuild_local_signature_groups(remapped | rematch)
    rebuild_local_arrangements(changed_groups)
    invalidate_relation_cache(changed_groups)
    rebuild_local_evidence(changed_groups)

    changed_portals = rebuild_local_routing_cells(delta)
    recustomize_ancestors(changed_portals)
    invalidate_route_cache_by_dependencies(delta, changed_groups, changed_portals)

    return UpdateResult(
        lineage_remapped=stable_ids(remapped),
        rematched=stable_ids(rematch),
        changed_groups=stable_ids(changed_groups),
        changed_portals=stable_ids(changed_portals),
    )
```

## A.10.3 hierarchical route search

```python
def nationwide_route_search(intent, graph_stack, budgets):
    hard_bounds = compile_finite_hard_bounds(intent)
    if hard_bounds.is_unbounded:
        return typed_failure("unbounded_route_scope")

    lower_bounds = graph_stack.national_overlay.compute_admissible_bounds(
        intent.origin,
        intent.destination,
        hard_bounds,
    )

    envelope = build_proven_budget_envelope(lower_bounds, hard_bounds)

    skeleton_result = enumerate_portal_skeletons(
        graph_stack.national_overlay,
        envelope,
        policy=budgets.portal_skeleton_policy,
    )

    regional = graph_stack.regional_corridors.expand_skeletons(
        skeleton_result.skeletons,
        envelope,
    )

    local_graph = graph_stack.local_graph.build_reversible_contracted_union(
        envelope,
        regional.corridor_witnesses,
        intent.locked_cores,
    )

    search = deterministic_multi_resource_search(
        intent=intent,
        graph=local_graph,
        label_budget=budgets.label_budget,
        expansion_budget=budgets.expansion_budget,
        approximation=budgets.approximation_manifest,
    )

    validated = [
        full_route_validator(candidate.expand_to_road_arcs(), intent)
        for candidate in search.candidates
    ]
    feasible = [x for x in validated if x.hard_gate_pass]

    status = derive_completeness_status(
        envelope=envelope,
        skeleton_result=skeleton_result,
        search=search,
        feasible=feasible,
    )

    return RouteSearchResult(
        candidates=rank_with_mechanical_fallback(feasible, intent),
        completeness_status=status,
        frontier_certificate=search.frontier_certificate,
        query_manifest=build_query_manifest(...),
    )
```

## A.10.4 ML ranking fallback

```python
def rank_with_mechanical_fallback(candidates, intent):
    deterministic = deterministic_pareto_lexicographic_rank(candidates, intent)

    model = load_compatible_ranker(intent, candidates)
    if model is None:
        return deterministic.with_policy("deterministic_fallback")

    diagnostics = model.support_diagnostics(intent, candidates)
    if (
        diagnostics.ood
        or diagnostics.stale
        or not diagnostics.calibrated
        or diagnostics.effective_sample_size_insufficient
        or diagnostics.interval_too_wide
    ):
        return deterministic.with_policy("deterministic_fallback")

    reordered = model.reorder_only(deterministic)
    return enforce_structural_diversity_and_validator(reordered)
```

---

# A.11 全国规模标注、压力测试与验收

## A.11.1 relation scale corpus

构造三类 corpus：

1. 真实多城市冻结 observation；
2. 由真实 corridor token sequence 派生的可控合成数据；
3. 病态 dense corridor：
   - 大量 exact duplicates；
   - 大量同 support group 成员；
   - nested intervals；
   - overlap chain；
   - reverse/mixed direction；
   - repeated arc；
   - parallel-road ambiguity。

必须比较：

```text
full pair oracle on small components
vs.
indexed/on-demand output
```

要求 relation witness hash 完全一致。

## A.11.2 partition/overlay 验收

指标：

- cell edge imbalance；
- directional portal ratio；
- portal-pair summary bytes；
- p50/p95/p99 query touched cells；
- exact scalar shortest-path equality；
- graph delta ancestor propagation depth；
- partition rebuild 与 metric customization 成本分离；
- shortcut expansion witness hash。

## A.11.3 query decoupling 验收

逐步把全国背景数据从：

```text
10k observations / small graph
→ 50k observations
→ 100k observations / million arcs
```

扩展，同时保持同一个本地 query envelope 不变。检查：

- exact/reverse latency；
- relation query posting decode；
- route overlay/local labels；
- memory；
- output hash。

预期：除全局 dictionary/partition lookup 的对数或常数级变化外，在线成本主要由 \(A_Q,P_Q,G_Q,H_Q,Z_Q\) 决定，而不是全国 \(N,A\)。

## A.11.4 approximation 验收

每种 approximate mode 必须与 exact small-graph oracle 对照：

```text
hard-feasible recall
best-route objective gap
Pareto-frontier recall
structural-diversity recall
search_truncated rate
validator rejection count
```

必须分别报告：

- 候选生成漏解；
- search approximation 漏解；
- ranking 误序；
- graph/access 数据缺失；
- Validator 拒绝。

不能把它们合成一个模糊“成功率”。

## A.11.5 ML 验收

Evidence completion：

- whole-corridor holdout；
- city holdout；
- future-snapshot holdout；
- propensity calibration；
- interval coverage；
- OOD abstention；
- cold-start degradation。

Candidate ranker：

- only hard-feasible candidates；
- randomized/interleaved logging subset；
- IPS/SNIPS/DR offline estimate；
- no-choice/reject modeling；
- city/user cold-start；
- deterministic fallback parity；
- model outage test。

---

# A.12 全国扩展实施顺序

## 阶段 A1：token 与 group，不先做全国 pair

- canonical directed token；
- reverse transform；
- support signatures；
- group membership；
- group-level posting；
- relation cache key。

## 阶段 A2：interval postings 与 heavy arrangement

- per-arc immutable posting runs；
- delta LSM；
- interval overlap query；
- CarrierBlock compression；
- active-pattern bitmap；
- dense-corridor benchmark。

## 阶段 A3：双重分区与 portals

- StorageTile；
- nested RoutingCell；
- direction/turn-aware portal；
- graph ownership/stub；
- partition version。

## 阶段 A4：incremental dependency footprint

- candidate arcs；
- transition subgraph；
- raw envelope；
- lineage remap；
- local invalidation closure；
- ancestor customization。

## 阶段 A5：national/regional/local search

- exact scalar lower bounds；
- hard budget envelope；
- portal skeleton；
- regional corridor alternatives；
- local contracted exact solver；
- completeness status。

## 阶段 A6：approximation only after exact pressure evidence

- ε-dominance/resource buckets；
- top-K skeleton；
- approximate spatial prefilter；
- explicit approximation manifest；
- exact oracle recall gate。

## 阶段 A7：ML shadow

- observation propensity；
- evidence quantile model；
- hard-feasible ranker；
- randomized logging；
- OOD/abstention；
- deterministic fallback。

---

# A.13 全国规模最终架构决定

在数万至十万来源赛段、百万 RoadArc 下，推荐的全国内核为：

```text
Versioned RoadCarrierGraph
    ├── Hierarchical Storage Tiles
    ├── Nested Routing Partitions
    ├── Direction/Turn-aware Portals
    └── Metric-specific Overlay Customization

Projection Layer
    ├── Local Candidate Dependency Footprint
    ├── Canonical Directed ArcSlice Tokens
    └── Exact Support Signature Groups

Relation Layer
    ├── Arc/CarrierBlock Interval Postings
    ├── Heavy Interval Arrangements
    ├── Exact q-gram / sequence indexes
    └── On-demand Pair Witness Cache

Evidence Layer
    ├── Provenance Collapse
    ├── Directional Partial-identification Bounds
    ├── Arrangement Pattern Compression
    └── Optional ML Imputation with Abstention

Route Layer
    ├── National Overlay Lower Bounds
    ├── Regional Corridor Skeletons
    ├── Local Contracted Multi-resource Search
    ├── Full RoadArc Expansion
    └── FullRouteValidator + Deterministic/ML-fallback Ranking
```

全国扩展的核心不是“把 \(O(N^2)\) 放到更多机器”，而是从语义上停止构造不需要的 pair：

- exact/reverse 用 signature；
- closure-safe containment 用 token subsequence/interval nesting；
- overlap 用 interval postings 和 on-demand components；
- 热门走廊用 group + arrangement；
- route query 用 portal/envelope/local labels；
- ML 只补软证据和重排已验证候选；
- approximation 只在可测资源压力超过 exact budget 后启用，并显式返回误差与截断状态。

最终全国安全原则：

> **全国总量必须被压缩为版本化分区和局部查询量，但任何压缩都不能删除方向、顺序、interval、provenance、witness 或失败边界。宁可按需计算、返回 approximate/search_truncated，或要求缩小查询范围，也不物化百亿 pair、不用 ML 猜 hard feasibility、不把局部搜索包装成全国完备。**

---

## A.14 外部算法先例的使用边界

本附录只把以下工作视为工程先例，不直接照搬其产品语义：

1. Delling、Goldberg、Pajor、Werneck 的 **Customizable Route Planning**：证明道路拓扑分区与 metric customization 可以分离，并可在大陆级道路图上支持 turn cost 与快速 metric 更新。
2. OSRM 的 MLD pipeline：采用 extract → partition → customize → route 的分离，说明 partition/customization 是成熟的道路路由工程结构。
3. Valhalla 的 hierarchical graph tiles：说明全国图可按层级道路和 tile 组织、按查询加载；VELO 仍需自己的 direction/turn-aware portal 与多资源完整性语义。
4. H3/S2 类层级空间索引：适合 StorageTile、粗召回和数据 join；不能用 cell hierarchy 证明道路拓扑或几何 exact containment。
5. Counterfactual Learning-to-Rank：说明展示/位置偏差下需要 logging propensity、IPS/DR 或随机流量；它不自动解决 trust bias、source selection bias 或 positivity 缺失，因此低支持区必须 abstain。

