# 西山多路段连接实验：旧证据恢复与当前 TransitPath treatment

日期：2026-08-13
状态：research shadow；不写生产、不构成骑行准入或用户推荐

完整 provider 几何、道路 steps、81 条活跃公路 source slice 与逐条 relation witness 保存在本机 evidence ledger `~/.codex/evidence/velo/transit-paths/xishan-v1/`（权限 `0600`）；Git 只保存去几何的 public manifest、输入 hash 和结论。换 Agent 后先按 selection pointer、provider 和 evidence SHA-256 对账，再用 `scripts/analyze_xishan_transit_path.py` 对 exact 81 条重新投影；不要从本段文字抄数字。

## 结论

2026-08-12 的旧实验值得保留为 baseline 和错题集，但不能继续作为规划内核。它的主要贡献是把组合爆炸量化为 `4,933 → 1,975 → 615 → 23 → 5`，并用地图反例证明“能连、够长、道路复用率合格”仍可能是一条坏路线。它的根本模型错误是：把 Strava observation 和旧 route GPX 当成路网节点，再按端点到端点生成边。

本轮 treatment 改成：

```text
目的地积木的 exit port
→ provider 生成完整、连续、有序的过境道路
→ 当前 81 条来源赛段投影到过境道路，只贡献方向化热度证据
→ 下一个目的地积木的 entry port
```

两条连接候选、两条 portal-pair 对照与一条回走失败样本已跑通，其中第一条是：横岭上端 observation boundary 到桃花沟化客头入口的腾讯驾车路网候选为 **16.856 km**，道路顺序为 **未命名道路 9.217 km → 柴化线 7.618 km → S104 10 m**；使用 `glo30_meaningful_ascent_v1` 得到 **+211.7 / -324.1 m**。当天腾讯 bicycling key 配额耗尽，因此它只能标为 `research_candidate_not_bicycling_verified` / `provider_path_not_bicycling_verified`，不能冒充骑行 access 已证明。

按用户纠正，再把 observation 6「化客头—桃花沟」完整接入后，当前第一条完整目的地组合是 **横岭完整爬坡 10.932 km → 过境道路 16.856 km → 化客头—桃花沟 10.100 km**，合计 **37.888 km、+1100.3 / -390.3 m**。路线级热度程序给出同方向 evidence coverage **55.5%**、reach **7,566–10,854 person-km**；中间过境路的反向 witness 不进入当前方向热度。

## 旧实验的历史证据基线

旧输入只有 25 个对象：20 条腾讯重建的 Strava 候选 GPX，加启春阁、天龙山、奥申、狼坡、横岭 5 条旧 content GPX。它不是当前 81 条完整西山 source facts；奥申、狼坡、横岭当时也没有 Strava source binding。

冻结 hash、漏斗数字和被证伪假设见 [`xishan_multisegment_baseline_20260812_v1.json`](../../data/research/xishan_multisegment_baseline_20260812_v1.json)。原始脚本和 JSON 仍只存在本机 `/tmp`，所以当前能做的是“身份固定的历史 baseline”，不是可从 GitHub 精确重放的正式程序。

旧漏斗逐步是：

1. 端点直线不超过 5 km 才调用腾讯驾车；道路不超过 8 km、绕行比不超过 3.5，得到 46 条有向边，在 25 个对象上 DFS 枚举 2–10 对象链，共 4,933 条。
2. 九个连通片之间补最短地图桥，再保留 50–130 km、来源爬升至少 1,000 m、连接占比不超过 48%、最多两座桥，剩 1,975 条。
3. 20 m 采样落入 40 m 网格，独立格子比例至少 80%，剩 615 条。
4. 只保留单对象爬升至少 250 m 或距离至少 8 km 的有序 core signature，剩 23 个临时家族。
5. 可视化再筛总长至少 70 km，恰好显示 5 条；这不是新的算法优选门。

## 旧实验哪部分有效

- 保留了方向和顺序，不是无向地点拼图。
- 腾讯道路距离确实打掉了“地图上看着很近”的假连接。
- 将来源对象、短连接、跨片区地图桥分层显示。
- Backbone 3 的人工倒查抓到了 S104 约 98.7% 反向重叠、随后再回走约 4.3 km 的结构反例。
- 已经得到正确经验：普通连接路没有 Strava 赛段也可走，只是不能继承热门语义。

## 旧实验的主要失败

### 1. 对象排列冒充道路搜索

旧“横岭—桃花沟”代表为：

```text
二库赛段 → 横岭旧 GPX → 这个坡很痛苦 → 柴化线赛段
→ 玉泉山南段 → S104 爬坡 → 化客头—桃花沟
```

84.6 km 中有 33.3 km 地图连接。中间的赛段被强制当成 waypoint，因此回答不了横岭出来实际经过什么路，也把普通过境证据误升格成目的地。

### 2. 40 m 道路复用率抓不到立即掉头

Backbone 3 在 S104 下去再爬回，又沿柴化线回走，仍以约 86.5% 独立道路率通过。这证明 aggregate unique ratio 不是顺序化掉头检测器。

### 3. provider profile 会改变结构

桃花沟同一 anchor pair 曾出现驾车约 22.9 km、骑行约 10.1 km 的冲突。旧实验全用 driving 第一条结果，因此只能产生候选，不能裁决真实骑法。

### 4. 热度并未进入排序

旧代码读取了 athlete / effort / star，但只用于展示；候选生成、剪枝、family 和 5 条代表的选择都未使用热度。

## 本轮横岭—桃花沟 treatment

### 目的地边界

- 横岭：使用当前 observation 2 的完整来源线；从上端 boundary 离开。
- 桃花沟：过境路先接到 observation 6「化客头—桃花沟起伏」起点，再完整骑完该赛段才到桃花沟；connector 不能冒充目的地本体。
- 过境道路不要求先有 Strava 赛段，赛段也不成为必须访问的中间节点。

### 实跑道路和成本

| 项目 | 结果 |
|---|---:|
| provider | 腾讯 driving，2026-08-13 |
| 完整距离 | 16.856 km |
| 完整几何 | 647 点 WGS84 |
| GLO-30 爬升/下降 | +211.7 / -324.1 m |
| 未命名道路 | 9.217 km |
| 柴化线 | 7.618 km |
| S104 接缝 | 0.010 km |

活跃的 81 条公路 source slice 逐一重新投影后，有两条 observation 提供明显反向覆盖：

- o82 `马头水岔口-横岭`：约 4.590 km，覆盖过境路径约 27.2%，覆盖自身 100%；
- o53 `柴化线下坡 化客头-大窊村`：约 3.843 km，覆盖过境路径约 22.8%，覆盖自身约 99.6%。

两者合计给出约 **8.433 km / 50.0%** 的几何证据覆盖下界，但它们全部是**反向**；当前行进方向的同向覆盖为 0。因此 50% 只能用于 coverage QA，不能直接抬高当前方向推荐热度。其余约一半保留 `unobserved`，不是 0 热度，也不因此判道路不能走。o82/o53 也不能简单相加为唯一骑手数；当前 treatment 只保存各 fact、方向、覆盖区间和原始 athlete/effort/star。

### 奥申—狼坡—桃花沟旧链的当前事实复跑

这轮没有停在横岭一条边。使用当前 o27「西山旅游公路 奥申正爬」、o38「狼坡」和 o22「桃花沟爬坡」的完整来源线，继续按“积木端口 → 完整过境路 → 赛段证据后投影”重跑：

| 连接 | 距离 | GLO 爬升/下降 | 方向证据覆盖下界 | 解释 |
|---|---:|---:|---:|---|
| 奥申上端 → 狼坡入口 | 2.250 km | +19.9 / -195.4 m | 81.9%（全为反向） | o7「奥申反爬」反向覆盖约 1.843 km；本 treatment 暂把它作为过境证据，它是否也是奥申的备选 traversal 仍未决 |
| 狼坡入口 → 桃花沟东入口 | 14.957 km | +231.3 / -247.0 m | 7.6%（同向；另有灰态诊断不入权重） | portal-pair control；它从狼坡山脚出发，跳过了完成狼坡爬坡后的山顶状态，不能冒充“骑完狼坡再接桃花沟” |

这回答了旧实验里最容易混淆的一点：**“尚未归入某个目的地积木”不等于“赛段没用”。** o7 与奥申核心 o27/o103 不是同一条 traversal，但它天然落在奥申到狼坡的过境道路上，所以本轮先按区间贡献反向证据；未来仍可验证它是否也是奥申模块的一种 approach/exit variant。旧模型把这些角色压成一个 waypoint，新模型保留多角色可能性。

狼坡上端直接接桃花沟东入口的驾车候选为 18.335 km，其中前 3.37 km 实际又完整走回狼坡；这不是另一个好连接，而是路线级顺序复走反例。因此正式公共候选保存的是狼坡入口 → 桃花沟东入口 14.957 km 对照；若要先完成狼坡爬坡再去桃花沟，必须另选出口或让完整路线组装器明确判复走成本，不能悄悄把回头路藏在 connector 里。

### 一个有意保留的对照

若从横岭山脚直接接桃花沟东侧入口，腾讯 driving 给出 28.534 km，经汾西北路、西中环路、南内环西街、虎峪河北沿岸和杜儿坪街，GLO 为 +417.9/-85.8 m。它只应作为另一 portal pair 的结构对照，不与 16.856 km 山区过境候选混成同一条边。

这说明“横岭—桃花沟”不是一个固定距离：入口/出口方向不同，就对应不同的完整 TransitPath。规划器应枚举有限 portal pair，而不是枚举赛段排列。

## 相对旧实验的可证伪新增能力

1. **旧：** 赛段/route 是节点，边连接对象端点。
   **新：** destination port 是端点，provider 先给完整过境道路，赛段后投影。
2. **旧：** 过境赛段决定必须走哪里。
   **新：** o82/o53 只给自然命中的方向热度证据，不改变道路序列。
3. **旧：** connector 没统一爬升。
   **新：** provider 生产阶段已对整条 16.856 km 用同一 GLO 算法生成 +211.7/-324.1 m，并随 snapshot 冻结；本重放器只核其身份和结构。
4. **旧：** 缺赛段是地图桥标签。
   **新：** 道路连通和证据覆盖分账；未覆盖部分为 `unobserved`。
5. **旧：** 在对象排列空间组合爆炸。
   **新：** 当前只消除了固定 port pair 内的 observation 排列；全国规模所需的 portal 召回、local envelope 和 bounded label-setting 仍未实现，不能声称最坏复杂度已经解决。

## 还没有证明的事

- 腾讯 bicycling 今日额度耗尽，未做同日骑行 profile 复核；
- driving 路网连续不等于现实骑行准入、路况或施工已通过；
- 未命名道路 9.217 km 需要骑行 provider、真实活动或人工地图复核；
- 已生成横岭—桃花沟、奥申—狼坡两个连接候选，横岭山脚—桃花沟和狼坡山脚—桃花沟两个 portal-pair control，以及狼坡山顶首条候选回走 3.37 km 的冻结失败样本；当时奥申、狼坡尚未各自固化为完整 MountainModule，也还没有完整路线组装器。2026-08-14 已新增通用 `route_pattern_assembly.py` 与 `analyze_route_choice_set.py`，不得按这条历史缺口重复造轮子；
- 确定性热度层已经落成并用于上述完整组合：hard gate → Pareto → `popular_reliable_lexicographic_v1`；学习 reranker 仍等待冻结 choice/outcome episodes，只能在 hard-feasible Pareto 集内工作。

## 对象分层边界

`TransitPath` 是 provider 给出的 research candidate/envelope，不是第二套道路真值，也不会直接写成正式 `InternalRoutingConnector`。经过骑行 profile、access、人工审查和端点绑定后，才允许晋级到既有隐藏 connector 或未来的 RoadCarrierGraph。当前脚本重放 81 条几何投影，并校验端口、距离与冻结 GLO 事实结构；它不重跑腾讯或 GLO 生产器。

## 历史后续 backlog

> 2026-08-14 状态更新：本节列出的奥申/狼坡工作仍是未完成 backlog，但不再是紧接本报告的当前实验。当前西山南部区域级批处理已由 [`2026-08-14-xishan-south-experiment-handoff.md`](./2026-08-14-xishan-south-experiment-handoff.md) 接管。

当时建议以这条 treatment 做最小闭环，而不是恢复 25 对象 DFS：

1. 将本轮已使用的奥申、狼坡 source facts 与 typed ports 固化进各自 MountainModule；
2. 只对路线意图需要的有限 portal pair 补 TransitPath，不再做赛段全排列；
3. 把更多完整候选交给已落地的路线级热度程序，输出 Pareto 集与具体推荐理由；
4. 累积真实 choice/rejection/completion episodes 后，再评估 learned reranker。
