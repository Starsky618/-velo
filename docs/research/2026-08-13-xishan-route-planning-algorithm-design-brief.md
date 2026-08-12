# 西山公路路线规划算法设计任务书（交给 GPT Pro）

日期：2026-08-13  
状态：可开始正式算法设计；本文件不是生产实现证明  
目标读者：负责给出数学定义、确定性算法、复杂度、伪代码与评测方案的推理模型或算法工程师

## 0. 先给结论

现在可以正式设计算法。不能继续拍脑袋定死的只有几何容差、覆盖阈值和热度权重；这些参数要由已标注关系、反例、数据分布和后续骑手选择校准。

这项任务不是“让 AI 挑路线”。它要设计一套确定性、可审计、可增量重算、不会随模型措辞变化的机械系统：

1. 从大量有向 Strava 来源赛段中识别 exact、空间等价、包含、部分重叠、反向和不确定关系；
2. 把高度重叠、不同尺度、不同方向的来源观测还原成可规划的 RoadLeg/Traversal 图；
3. 用赛段热度作为骑手偏好证据，而不是把重叠赛段的数字直接相加；
4. 在时间、距离、爬升、方向、道路连续性和路线结构约束下，生成最多三条真正不同的完整路线；
5. 每个结论都能说明用了哪个输入版本、为什么通过或被剪枝。

## 1. 产品最终要得到什么

VELO 面向中国城市里的严肃公路车骑手。路线规划输出的是静态路线、GPX 和外部地图跳转，不做实时导航或动态改路。

用户输入至少包括：

- 起点/终点或允许的城市接入范围；
- 可用时间、目标距离、目标爬升及硬上限；
- 训练意图，例如长爬坡、连续山地、爬坡重复、恢复或探索；
- 是否接受真正死胡同折返、主动重复训练、特定风险或较低证据覆盖。

输出最多三条 Pareto 非劣、结构真正不同的完整路线。每条路线必须包括：

`城市接近段 → 连续山地阶段 → 明确退出/返程段`

并按全程而非“山中骨架”重新计算：

- 距离、GLO-30 爬升、预计移动时间；
- 道路重复距离、立即反向、宏观回头和回城再进山；
- 有向热门证据覆盖、普通连接道路长度；
- 关键几何、道路准入、router 冲突和其他未知项；
- 输入批次、几何 hash、道路图版本、算法和参数版本。

没有三条合格路线时必须只给一条、两条或 typed no-result，不能为凑数输出近重复或结构不成立的方案。

## 2. 必须使用的领域对象

请严格区分以下对象，不能让一个公共 `Segment` 同时扮演道路、热度来源和路线结构：

| 对象 | 含义 | 不能冒充什么 |
|---|---|---|
| Segment Observation | 某时间从 Strava 看到的一条有向来源观测，保留原始 ID、名称、指标和完整来源线 | 不是 VELO 已发布 Segment，不是道路真相 |
| Relation Input | 一个冻结批次中明确 include/exclude 的来源观测，并绑定 observation、Strava ID、geometry hash、GLO fact | 不是赛段间关系结论 |
| RoadLeg | 在稳定道路切分点之间的基础道路几何 | 不带 Strava 热度，不等于来源赛段 |
| Traversal | RoadLeg 的一个允许骑行方向 | 反向 Traversal 不自动继承正向热度 |
| Segment Projection | 一个来源观测映射到有序、有向 RoadLeg/Traversal 序列的结果 | 不能只用首尾点代表 |
| Corridor | 若干 RoadLeg 构成的可复用道路走廊 | 不等于完整路线 |
| Route Pattern | 有语义的进山、爬升、退出结构 | 共享端点或尾段不代表同一 Pattern |
| Internal Routing Connector | 只负责连接正式对象的内部道路 | 可以连通，但默认没有热门语义 |
| Route Candidate | 包含接近、山地、退出和返程的完整候选 | 研究骨架不是用户可推荐路线 |

## 3. 当前真实数据和证据边界

### 3.1 当前西山批次

正式数据库当前有：

- 普查批次 `xishan-20260813-v1`；
- 115 条唯一来源观测，其中 87 条与西山边界相交或位于边界内，28 条在边界外；
- 两遍枚举各见 112 条但各有 3 条不一致，因此 `run_status=completed_with_errors`、`enumeration_status=indeterminate`；
- 这意味着 87 是当前冻结研究集合，不得称为“西山全部 Strava 赛段”。

87 条候选的基础数据已经做到：

- Strava 原始 ID、URL、名称和详情字段逐行保存；
- 完整来源 geometry 与 observation ID 一一绑定；
- 自研 GLO-30 有意义爬升算法逐条计算并保存，批次为 `xishan-20260813-v1-glo30-v1-a1`；
- 87/87 GLO fact complete、0 failed，并保存 source geometry hash、normalization version 和 algorithm version；
- 2 条 source distance difference 超过当前质量提示阈值，需要作为质量 flag 保留，不能静默删除；
- leaderboard 没有采集，原始 Strava 响应也不能完整重放。现有热度只能使用已保存的 aggregate 字段并诚实表达缺失。

人工范围审核把 87 条精确分成：

- 81 条公路关系分析输入；
- 6 条纯 XC/山地越野来源观测，仅从“公路关系分析输入”中排除；
- 6 条的 observation、原始 Strava 信息、geometry 和 GLO fact 全部保留，不删除、不改写成全局 `is_road=false`。

排除的 Strava ID 是：

`33133333, 39979642, 40127007, 40437410, 40589205, 40835241`

旧 48 条本地来源集合与当前集合的机械对账是：

- 11 条属于西山，并且 11/11 全部进入当前 81 条 included；
- 37 条由用户明确确认不属于西山，不补抓、不纳入本次关系输入；
- 不能拿旧腾讯候选 GPX、稀疏参考点或名称猜测推翻这个范围决定。

### 3.2 已有实现与缺口

已经正式实现：

- 来源普查、逐行 observation、完整 geometry、区域 membership；
- append-only census 与 GLO fact；
- source ID、observation ID、geometry hash、算法版本和 GLO 事实的 exact-set 回读；
- 人工确认的 87→81+6 逐条 JudgmentRun；
- 本次基础交付不新增重复的关系输入表：保留现有逐条 JudgmentRun，另用版本化 scope profile 固定 `87=81+6`、六个 XC ID 和审核 payload hash；只读审计器把它与 87 条 GLO/source readback 及旧 48 清单机械对齐。

尚未正式实现：

- 81 条之间的 extent/direction 空间关系事实；
- RoadLeg 切分、Segment Projection 和道路拓扑图；
- 重叠热度去相关与路线查询时评分；
- 真正的图搜索、候选剪枝、路线结构验证；
- 用户可见的正式路线推荐。

已有 20 对象图原型、空间关系原型、临时长路线脚本和 feedback episodes 都只是设计/研究证据。原型 `ALL_PASS`、5 条 backbone 或一条 82.84km 骨架都不能冒充生产可用。

## 4. 已拍板的关系模型

### 4.1 两个正交轴

任意两个来源观测 A、B 的关系至少分成两个独立轴，不允许一个枚举值把空间范围和方向混在一起。

Extent 轴：

- `geometry_identical`：规范化后几何一致；
- `spatial_equivalent`：在容差内表达同一有向或无向道路范围；
- `a_contains_b` / `b_contains_a`：一个范围机械包含另一个；
- `partial_overlap`：有真实共享道路，但双方各有独占部分；
- `disjoint`：无共享道路；
- `indeterminate`：输入或匹配证据不足，不能稳定判断。

Direction 轴：

- `same_direction`；
- `reverse_direction`；
- `mixed_direction`，例如一条来源线本身含往返或重复；
- `indeterminate`。

端点关系、道路拓扑连通和是否适合作为路线前后继是另外的事实，不能由 overlap 自动推出。

### 4.2 机械规则

- 分类必须由确定性几何/图算法完成，禁止 LLM、名称正则、缩略图或“看起来像”参与判别；
- 必须使用完整有向来源线，不能只看起终点；
- 阈值附近、geometry 不完整、map matching 多解或 provider 冲突时返回 `indeterminate`；
- 每条事实绑定双方 observation ID、Strava ID、geometry hash、normalization、algorithm/parameter version；
- 任一 geometry hash 或道路图版本变化，旧投影、旧关系和相关路线候选必须失效，而不是原地覆盖；
- 原始 observation 和 GLO fact 永久保留，关系事实按新批次追加。

## 5. 需要 GPT Pro 正式设计的算法

### 5.1 候选对生成：不能全域暴力两两遍历

81 条的全组合只有 3,240 对，本地一次计算不贵；但把这个做法扩展到所有城市、所有观测和每次增量更新会爆炸。请设计 output-sensitive 的候选生成：

1. PostGIS GiST/R-tree 对扩张 bounding box 做空间粗筛；
2. 按区域 tile、道路组件或 map-matched RoadLeg 倒排表进一步缩小候选；
3. 只有共享候选 RoadLeg/缓冲区的观测才进入精确比较；
4. 新增或 geometry hash 改变时只重算受影响邻域；
5. 目标复杂度请表达为 `O(n log n + k × Cmatch)` 一类的输出相关形式，其中 k 是实际近邻候选对，并明确病态高密重叠时的最坏上界和保护策略。

不允许永久物化全局 `n²` disjoint 事实。没有候选边即可在某个已知空间索引版本下解释为 disjoint/未相交；只存有用邻接、indeterminate 和审计统计。

### 5.2 从来源线到 RoadLeg/Traversal

请设计 provider-neutral 的道路切分与 map matching：

- 稳定 Anchor/切分点来自道路交叉口、合法道路端点和受审 connector，不来自任意 Strava 端点；
- 一个 RoadLeg 生成两个可能的有向 Traversal，并单独保存骑行准入与证据；
- 来源线映射为有序 Traversal 序列，并输出连续覆盖率、反向覆盖率、横向偏差、未匹配区间、多解和置信边界；
- 桥、隧道、立交、同屏相交但不连通必须由图拓扑区别；
- router 只能产生连接候选或证据，不能成为道路真相。骑行/驾车 profile 冲突必须显式暴露。

### 5.3 关系压缩的数据结构

请明确哪些结构可安全使用：

- 仅对 `geometry_identical/spatial_equivalent` 做 equivalence class，可用 union-find；
- 包含关系形成有向无环图，并做 transitive reduction，避免保存所有传递边；
- partial overlap 保留稀疏邻接边；
- 不允许对所有 overlap 边直接取 connected components 后合并，因为 A≈B、B≈C 不保证 A≈C，链式过度合并会破坏空间意义；
- 在 RoadLeg 投影稳定后，优先把关系表达为有向区间/有序 leg 序列的集合关系，而不是反复对原始折线做昂贵比较。

请回答：如何检测混合方向、自交、往返、重复 RoadLeg，以及如何避免 containment/overlap 环由数值误差产生。

### 5.4 完整路线搜索

搜索状态至少要能表达：

- 当前节点/Traversal、已用 RoadLeg、多次经过次数；
- 已用距离、GLO 爬升、预计时间及剩余预算；
- 当前路线阶段：城市接近、山地、退出、返程；
- 已满足/未满足的训练意图；
- 热度证据覆盖、普通 connector 成本、证据置信度；
- 是否发生立即反向、可避免回头、合法环线、真实死胡同折返或主动 hill repeat；
- 输入与计算版本。

先过硬门，再做软排序：

1. 方向、道路可达、骑行准入、完整结构、硬预算和关键数据是 hard gates；
2. 热度不能抵消方向错误、断路、超预算或缺返程；
3. 默认禁止可避免的立即反向和宏观回头；真实死胡同或明确 hill-repeat 训练意图可成为 typed exception；
4. 进入山中后默认保持连续山地阶段，不能回城后再次进山；
5. 用 dominance/Pareto pruning、admissible lower bounds、分阶段 beam/A* 或其他有界策略控制候选爆炸；
6. 最终按完整路线重算全部成本，不信任各模块局部数字之和；
7. 最多返回三条结构不同的方案，需定义可解释的 route diversity，而不是只比较 GPX 点差。

### 5.5 热度如何进入推荐

热度是查询时、多维、有向、有来源时间的证据，不是一个永久全局分数。至少保留：

- `reach`：不同骑手覆盖广度，当前可用 athlete count；
- `repeat`：复骑强度，可从 effort/athlete 推出带不确定性的证据，必须对小样本做 shrinkage；
- `intent/competitive`：收藏、竞技或专门训练意图的代理，不能等同 reach；
- `direction`：正向热度不自动给反向；
- `observed_at/freshness`：数据观测时间与是否过期；
- `confidence/coverage`：来源字段完整性、投影质量、关系组覆盖比例。

核心约束：

- 相同/包含/高度重叠来源观测属于 correlation/evidence group，不能把 athlete/effort/star 直接相加；
- 普通连接道路可以通过，但热度贡献为零，不能称“热门”；
- 部分覆盖只能按连续、有序、同向的实际覆盖贡献，不能因碰到一小段就获得完整赛段奖励；
- `80%` 连续覆盖曾作为研究候选门槛，不是已经验证的真理；请给出校准方法和敏感性分析；
- 不要在没有选择数据前给出诸如 reach 0.4、repeat 0.3 的虚构权重。

请提出 query-time 多目标排序或 learning-to-rank 的可解释结构，但首版必须能在没有训练模型时用确定性配置运行。权重学习只能发生在 hard gates 之后，且输入应来自冻结的骑手选择/拒绝 episode、回归集和 holdout，而不是 LLM 自评。

## 6. Grilling 已暴露的反例与必须继承的结论

这些不是可重新讨论的口味问题，而是算法必须通过的结构反例：

1. Eval 001 A 出现 S104/柴化线方向错误，应以 `avoidable_reverse_retrace` 拒绝；
2. Eval 001 B 出现玉泉宏观回头，应以 `macro_loop_backtrack` 拒绝；
3. 用户修正骨架是 `S104 → 周家山 → 古交`，并要求进入山里后维持连续山地阶段；
4. 82.84km、+1657.2m、约 5.52h 的 v2 只证明骨架结构改善，不是最终几何、热度或用户推荐；
5. Backbone 3 含接近全段反向的 S104、约 4.3km 重复道路和约 18.55km map-only bridge，只能保留为 hill-repeat 研究家族，不能标成普通推荐；
6. 桃花沟“杜儿坪进山”“桃花沟出山”“进山—爬坡—出山”共享道路但属于不同 Route Pattern；
7. 枣杜式真实死胡同折返不能被“一律禁重复”误杀；
8. 研究漏斗从 4,933 条 chain 收缩到 1,975、615、23、5，只说明临时剪枝工作过，不证明算法、RoadLeg 或五条路线已经正式成立。

## 7. 绝不能接受的最差结果

以下任一项发生，都应视为算法失败而不是“体验有待优化”：

- LLM、名称正则、端点距离或地图缩略图决定 exact/包含/重叠/反向；
- 把 81 条说成西山完整枚举，掩盖 enumeration indeterminate；
- 删除六条 XC 的 observation/geometry/GLO，或把局部公路范围决定写成全局真相；
- 旧候选 GPX 推翻完整来源 geometry 或用户确认的 37 条非西山边界；
- 全域永久计算和存储所有 `n²` 对，新增一个对象就全量重跑；
- 用 overlap connected components 链式吞并不同道路范围；
- 反向、包含、异尺度和同源赛段的热度重复相加；
- 普通 connector 继承相邻赛段热度；
- 端点接近、POI 相同或地图上线条相交被当成道路可达；
- 正向热门赛段反向骑行仍获得正向奖励；
- 缺城市接近、退出或返程的山中骨架被称为完整路线；
- 距离、爬升和时间只算山中骨架，不计接近/connector/返程；
- 默认推荐可避免的立即反向、宏观回头或回城再进山；
- 为消灭回头而误杀合法环线和真实死胡同；
- 关键 geometry、骑行准入、桥隧连通或成本未知时仍给肯定推荐；
- soft heat 抵消 hard gate；
- 为凑满三条输出近重复方案；
- 为通过已知例子写死 S104、桃花沟、玉泉等地名；
- 阈值附近被强行二分类，系统没有 `indeterminate` 和人工复核队列；
- geometry/graph/version 变化后继续使用旧关系和旧路线候选；
- 把原型 `ALL_PASS`、5 条 backbone 或 v2 骨架描述为生产可用。

## 8. 要求 GPT Pro 回答的具体问题

请不要只给概念图。必须逐项回答：

1. RoadLeg/Anchor/Traversal 的数学对象、版本合同和构建算法是什么？
2. Segment Projection 的输入、输出、map-matching 状态、置信度和多解如何表达？
3. extent 与 direction 的正式定义、判别顺序、容差配置和 `indeterminate` 边界是什么？
4. 空间索引、候选对生成、equivalence class、containment DAG、overlap graph 分别用什么数据结构？
5. 初次构建、单条增量、批量更新的平均与最坏复杂度、内存和存储规模是什么？
6. 何时保存 relation fact，何时只靠索引推导 disjoint？怎样做 transitive reduction？
7. geometry hash、normalization、road graph、provider 和参数版本怎样触发精确失效与重算？
8. 完整路线搜索的 state、transition、hard gate、lower bound、dominance 和停止条件是什么？
9. 如何机械区分立即反向、宏观回头、合法环线、forced out-and-back 和 hill repeat？
10. 怎样定义最多三条候选的结构差异和 Pareto 非劣？
11. heat evidence group 如何去相关？reach/repeat/intent/direction/freshness/confidence 如何查询时组合？
12. 在没有足够用户选择数据前使用什么确定性 baseline；之后如何校准阈值和权重而不越过 hard gates？
13. 缺数据、无解、provider 冲突、候选爆炸分别返回什么 typed failure 和修复动作？
14. 如何保证同一冻结输入确定性重放、稳定 tie-break 和规则级解释？

## 9. 交付格式

GPT Pro 的设计稿必须包含：

1. 一页结论和关键取舍；
2. 对象与 I/O 合同，保持 schema-neutral，不直接假设现有 ORM；
3. 数学定义和判别真值表；
4. 候选对、map matching、关系归约、路线搜索、热度聚合的伪代码；
5. 平均/最坏复杂度和规模触发条件；
6. 所有阈值作为可版本化配置，并说明需要什么标注数据校准；
7. hard gates 与 soft ranking 的清晰矩阵；
8. 缓存、增量失效、幂等、重试和 deterministic readback；
9. typed failure taxonomy；
10. 单元、性质、反例、回归、holdout、性能和增量测试；
11. 从 81 条研究集到更多地区的分阶段迁移计划；
12. 明确声明：LLM 不参与几何分类、图连通、成本计算或剪枝。

暂时不要提交生产代码、数据库迁移或随意给出数值权重。先给可审查的算法设计和评测计划。

## 10. 最低验收题

关系层：

- 87 条输入必须机械对账为 81 include + 6 exclude，逐条绑定 source observation、Strava ID、geometry hash 和 complete GLO fact；
- 旧 48 必须对账为 11 当前命中 + 37 用户确认非西山，11 条全部 included、0 条落入 XC 排除；
- 六条 XC 不生成公路 pair relation，但原始 observation/GLO 仍可回读；
- 几何或版本变化使相关旧事实失效；
- exact/equivalent 的分组不因输入顺序变化；overlap 链不能误合并。

路线层开发/回归集：

- Eval 001 A 以 `avoidable_reverse_retrace` 拒绝；
- Eval 001 B 以 `macro_loop_backtrack` 拒绝；
- v2 只通过结构检查并显示数据边界，不直接晋级用户推荐；
- 枣杜真实死胡同允许 forced out-and-back；
- 桃花沟三个 Route Pattern 保持独立；
- 普通道路可连接 S104→周家山，但没有 segment 时热度奖励为零；
- 已知包含/部分重叠/无重叠只贡献一次、按实际方向和连续覆盖计算；
- provider profile 冲突必须暴露；
- 端点接近但路网不通必须拒绝；
- 关键几何、准入或全程成本缺失时 typed no-result。

Holdout：

- 一组未在本文出现过的山地道路家族，禁止地名特判；
- 一条合法环线；
- 一个新真实死胡同；
- 一条 2–5 小时城市/平路任务，验证山地阶段规则不外溢；
- 一个高密度重叠压力集和一次单条 geometry 增量更新。

最低通过标准：

- 0 条方向错误、断路或超硬预算候选进入展示；
- 每条通过候选都有完整接近/山地/返程结构、全程成本、规则证据和版本来源；
- 同一冻结输入可确定性重放；
- 开发、回归、holdout 同时通过；
- 不足三条时诚实返回更少或无解。

## 11. 可供核对的交付证据

- `app/route_cognition/census_models.py`、`scripts/census_strava_segments.py`：正式 census/observation 事实；
- `app/route_cognition/segment_elevation_facts.py`、`scripts/backfill_segment_elevation_facts.py`：GLO-30 与 exact-set 回读；
- `data/research/taiyuan_strava_local_48_20260812_v1.json`：旧 48 的 11+37 范围对账。
- `data/research/xishan_relation_input_profile_v1.json`：当前 87=81+6、六个 XC ID 和审核 payload hash；
- `scripts/audit_xishan_segment_alignment.py`：对生产 JudgmentRun、source observation、geometry hash、GLO fact 和两份清单做零写入机械回读。

本任务书已经把此前 Grilling、研究文档和 episodes 中与算法有关的目标、反例和底线自包含地写入正文；接收 GPT Pro 的一方不需要拿到那些本地临时/未提交材料。此前材料只提供设计证据，是否已实现仍必须以当前代码、数据库 readback、CI 和部署结果分别判断。
