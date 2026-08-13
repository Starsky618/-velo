# 从多赛段到“本地老骑友”解释：城市骑行路网机械 SOP

日期：2026-08-14
状态：可重放 research harness；西山北部已有实证，南部留出区尚未运行

## 一句话目标

把零散赛段先变成可审计的道路证据，再把目的地、过境道路和方向化热度组成有限个真实骑法；Agent 最后只根据硬数据解释“哪里值得骑、怎么组合、适合谁、为什么、代价是什么”。

它不是让 LLM 猜路线。机械程序负责身份、几何、爬升、方向、重叠和连接；Agent 负责读懂这些结果并用骑友听得懂的话比较。

## 当前状态流

```mermaid
flowchart LR
    A["来源观测闭账\nID / 完整有向线 / 热度快照"] --> B["GLO-30 单条事实\n距离 / 爬升 / 下降"]
    B --> C["空间关系与投影\n包含 / 重叠 / 反向 / 灰态"]
    C --> D["目的地积木\nMountainModule + ports"]
    D --> E["完整过境道路\nTransitPath"]
    E --> F["真实骑法候选\nRoutePattern choice set"]
    F --> G["硬数据解释\n适合谁 / 为什么 / 代价"]
    G -. "未来真实选择与完成记录" .-> H["learned reranker\n只重排 hard-feasible Pareto 集"]
```

| 状态 | 机械完成条件 | 当前实现 |
|---|---|---|
| `facts_ready` | 活跃 exact set 无重无漏；每条 ID、来源线、geometry hash、热度快照和 GLO-30 一一绑定 | 已实现；当前西山活跃 81 条 |
| `relation_ready` | 候选检索后做确定性关系/投影；方向轴与范围轴分开；灰态不硬猜 | 已实现 research 版 |
| `module_ready` | 同一目的地的参考轴、来源证据、完整 traversal 与 typed ports 可离线重放 | 已实现通用 runner；横岭已实跑 |
| `transit_ready` | 从一个积木 exit 到另一个 entry 保存完整有序道路、距离、GLO 和方向证据 | 核心对象与西山 replay 已实现；跨城市通用 provider/runner 尚未形成 |
| `choice_ready` | 多个模块、过境路和来源走廊按顺序组装；连接、反向复用、爬降交换与 hard failures 机械校验 | 已实现通用 core + 通用 CLI；同一 rider job 的 Pareto 排名函数仍是独立入口 |
| `explanation_ready` | 输出距离、爬升下降、热度范围、未观测比例、适合谁、推荐理由、代价与禁止脑补项 | 已实现硬数据 v1 |
| `learning_ready` | 同一候选集的展示、选择/拒绝、完成/放弃形成冻结 episode，可在 holdout 上评测 | **未实现**；当前没有资格声称 learned reranker 已闭环 |

## 每个新区域都执行的 SOP

### 1. 先冻结对象，不先写故事

- 用道路、地标和 polygon 冻结区域；保存活跃 observation exact set 与 hash。
- 单条逐项对账 Strava 原始 ID、完整有向来源线、热度快照、geometry hash 与 `glo30_meaningful_ascent_v1`。
- 来源赛段是证据，不直接等于现实道路；未知值保持未知。

### 2. 机械找“同路、局部、反向”，不做全量排列

- 先用空间索引/包围盒/签名召回少量可能有关的 pair，再运行确定性关系判别器。
- exact / equivalent / containment 只组织关系；模糊、自交、多投影保留 `indeterminate`，交给参考轴投影，不强行二选一。
- 当前 81 条研究 oracle 的候选索引把 3,240 对缩到 138 对，并召回全部 90 个 relation-relevant pair；这证明当前候选漏斗有用，但还不是全国规模证明。

### 3. 同一份物理几何只保存一次，方向只是 traversal

- `SourceObservation` 可以有多条；它们投影到方向无关的 `Component Geometry` 上贡献证据。
- 同一冻结几何反向骑不复制线，只交换 entry/exit、爬升/下降，并读取反向热度。
- 不同来源线何时能晋级为同一条现实 `RoadCarrier`，仍必须由几何/拓扑事实证明；不能因为名字相同就合并。

### 4. 先做目的地积木，再做区域组合

每个山区只新增 manifest 与证据快照，交给同一套 `scripts/analyze_mountain_module.py`：

- 参考轴与多个局部赛段投影成方向原子区间；
- 重叠赛段在同一区间只积分一次，热度保留 reach 下界/上界而不是拍脑袋总分；
- 输出完整 traversal 的距离、GLO 爬升下降、方向热度、重复骑行 proxy、入口和出口；
- 同一个目的地若有不同进山道路，保留为不同 traversal，不因终点相同而混成一条。

### 5. 只枚举有限 port pair，过境路不是赛段排列

积木之间按真实路线意图选择少量 exit→entry，由 provider 生成完整 `TransitPath`。赛段随后投影上去，只贡献方向热度；普通道路没有赛段就标 `unobserved`，不记为 0，也不强制变成 waypoint。当前西山已有可重放入口 `scripts/analyze_xishan_transit_path.py`；它可直接服务天龙山这次同区域 holdout，但还不是跨城市通用 TransitPath 生产器。

### 6. 组装真实骑法，再作同层比较

使用通用入口：

```bash
python3 scripts/analyze_route_choice_set.py \
  --choice-spec data/research/REGION_choice_set.json \
  --source-slice /private/path/source-slice.json \
  --selection-snapshot /private/path/selection.json \
  --module-run /private/path/MODULE.run.json \
  --transit-run /private/path/TRANSIT.run.json \
  --output /private/path/REGION.choice-result.json
```

组件文件可重复传入；没有模块或过境路的候选可以省略对应参数。程序校验 exact-set 身份、上游 hash、组件顺序、端点连接、方向与同线反转，逐个输出 `hard_feasible` / `hard_rejected` 和硬事实对比。不同用户任务（单爬核心段、区域串联、完整城市往返）不强行放进一个总分池。只有同一 `comparison_scope`、同一 rider intent 的可行候选，才另交现有 `rank_heat_candidates()` 做 Pareto → lexicographic 排序；当前 CLI 不自动代做这一步。

### 7. Agent 只解释硬数据允许的结论

每个候选固定回答：

1. **这是什么骑法**：目的地核心段、区域串联或完整 outing；
2. **适合谁**：只从距离、爬升结构、热度可靠性、重复骑行密度与未观测比例推理；
3. **为什么值得骑**：哪一段是当地反复骑的主轴，哪一段只是自然过境；
4. **代价是什么**：总距离、爬升下降、冷门/未观测连接和结构性回头；
5. **不能说什么**：没有风景、路面、车流、补给事实时不编。

## 下一块：西山南部区域级批处理

下一步一次处理 `xishan_south_destination_network_v1`，覆盖牛家口、天龙山多入口、天龙山西门、龙山、店头与蒙山，不再把任务切成单个牛家口 probe。它不是赛段全排列：先按固定地理窗口从 active 81 机械取 exact 候选，再用关系/投影形成少量真实 traversal、目的地积木和区域组合。

当前窗口 `lon 112.36..112.48 / lat 37.67..37.78` 与 active-81 相交得到 exact 21 条：`[4,8,9,17,18,21,28,49,50,51,55,57,78,79,85,87,89,93,96,97,98]`。窗口只是本批 census 边界，不宣称窗口里的对象天然同路。

执行顺序：

1. 一次导出 exact 21 条既有完整 GLO facts，不重新抓 Strava、不重算 GLO；
2. 用现有 oracle 和通用投影批量建立 corridor families，至少覆盖牛家口、天龙山东侧主爬、天龙山北侧/龙山、天龙山西门、店头—蒙山；
3. 每个 family 选择自己的单参考轴生成 MountainModule；同一现实道路的不同来源只投影成证据，同一物理几何只冻结一次；
4. 为已形成的积木端口批量生成有限 TransitPath，连接自然相邻的目的地，不枚举 observation 排列；
5. 组装区域内可执行的短、中、长选择，输出总距离、GLO 爬升下降、方向热度、unobserved、适合谁、为什么和代价；同一 scope/intent 内直接跑 Pareto/意图排序；
6. 冻结并机械验收已有反例：o78/o79 同线反向；o55 是 o89 的反向局部证据；o8/o93 是另一 approach；raw `indeterminate` 必须由投影给 witness 或保持灰态；
7. 批内某个 family 或连接失败，只 hard-reject 对应候选并继续其余区域批次；不要因一条灰态让整片停摆；
8. 通过条件是：21 条 exact 对账、多个积木与组合可重放、横岭基线不漂移、没有区域专属算法、Agent 能给出一张南部骑行选择地图式解释。

## 三个 Loop 的真实边界

- **机械重放 Loop：已形成。** 冻结输入/hash → 确定性运行 → artifact → 回放一致性与反例测试；路线选择集合当前输出硬事实对比，不自动跨 rider job 排名。
- **下游泛化 Loop：进入区域批处理。** 横岭是首个单积木实证；西山南部 21 条批次同时验证多个 MountainModule、TransitPath 和 choice 的通用处理。它仍不证明 relation 全链路泛化；真正全链路 holdout 以后选未进入当前 81 oracle 的区域。
- **产品学习 Loop：尚未形成。** 需要在真实产品里记录候选曝光、选择/拒绝、完成/放弃与当时位置概率；在此之前，同一 rider job 可显式调用确定性 Pareto/意图排序，不等 ML，也不编权重。

当前完成标准不是“又分析完一个坡”，而是一次得到西山南部多个可组合目的地积木、有限过境路和真实选择集；通用内核不因山名分叉，单个坏候选不拖停整批，Agent 能像本地骑友一样解释整片区域。跨城市通用 TransitPath runner 仍是后续缺口，不能用本批冒充全国已解决。
