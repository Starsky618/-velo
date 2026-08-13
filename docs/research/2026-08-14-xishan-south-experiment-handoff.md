# 西山南部区域级批处理：新 Session 实验交接

日期：2026-08-14  
状态：待实验；目标是一次读懂一片骑行区，不再做单赛段小纵切

## 1. 开工现场

继续使用现有独立工作树：

```text
/private/tmp/velo-xishan-multisegment-reproduction
branch: codex/xishan-multisegment-reproduction
baseline: 当前分支 HEAD
PR: https://github.com/Starsky618/-velo/pull/75
```

开工先执行 `git status --short`、`git log -5 --oneline` 和 `gh pr checks 75`。不得在 `/Users/macbookair/Desktop/velo` 的旧 main 另造一套，也不得回滚现场改动。

## 2. 这轮必须得到什么

实验对象是 `xishan_south_destination_network_v1`，一次覆盖：

```text
牛家口
  ↘
天龙山东侧主爬 ─ 天龙山石碑 ─ 天龙山西门
  ↗                 ↘
龙山 / 店头 ───────── 蒙山与太古路入口
```

最终不是一条“牛家口路线”，而是一份南部骑行选择网络：哪些来源其实是同一条路的局部或反向、哪些是不同入口、哪些目的地能自然串联，以及短、中、长分别怎么骑。

一次交付应产生：

- 3–5 个由事实形成的道路族 / 目的地积木；
- 自然相邻端口之间的有限 TransitPath，不做赛段排列组合；
- 目标 6–12 个短、中、长真实选择；硬事实不支持的候选直接淘汰，但不能拖停整批；
- 每个选择的总距离、GLO 爬升/下降、方向热度、未观测比例、适合谁、为什么和代价；
- 一份让陌生骑友能看懂南部地区的总览，而不只是算法日志。

这些 observation 已进入当前 relation oracle，所以本批验证的是区域级下游组装能力，不冒充全国 relation 全链路 holdout。

## 3. exact 21 候选，不再手挑几条

固定批次窗口：

```text
lon: 112.36 .. 112.48
lat:  37.67 .. 37.78
selection rule: source geometry bbox intersects window
source universe: active exact 81
```

机械相交得到 exact 21：

```text
[4, 8, 9, 17, 18, 21, 28, 49, 50, 51, 55,
 57, 78, 79, 85, 87, 89, 93, 96, 97, 98]
```

| o | Strava ID | 来源名称 | 距离 / GLO | 热度（人/次/星） |
|---:|---:|---|---|---|
| 4 | 20835564 | 牛家口-天龙山 | 11.707 km；+517.4/-19.2 m | 117/179/22 |
| 8 | 22350888 | 天龙山反爬 | 6.931 km；+389.0/-16.8 m | 244/730/34 |
| 9 | 22350896 | 店头-蒙山 | 5.192 km；+258.1/-17.4 m | 263/991/10 |
| 17 | 24481149 | 天龙山网红公路爬坡 | 9.282 km；+550.5/-59.4 m | 708/3899/181 |
| 18 | 24836971 | 天龙山岔路口到岔路口 | 4.805 km；+322.3/-17.2 m | 954/6489/19 |
| 21 | 25962995 | 龙山店头下坡 | 5.185 km；+0.0/-276.8 m | 704/2687/11 |
| 28 | 28884424 | 店头古堡最陡坡 | 0.577 km；+70.9/-0.0 m | 106/233/6 |
| 49 | 31912051 | 太古路 植物园-店头古堡 | 3.852 km；+107.2/-0.0 m | 107/225/3 |
| 50 | 32024332 | 龙山陡坡 climb | 0.511 km；+57.9/-0.0 m | 266/880/3 |
| 51 | 32229851 | 豆腐店爬坡 | 0.552 km；+47.4/-0.0 m | 340/986/18 |
| 55 | 32924675 | 天龙山隧道-豆腐店岔口 | 4.042 km；+180.6/-0.0 m | 224/365/2 |
| 57 | 34211479 | 天龙山连环回旋高架桥 | 3.185 km；+176.9/-30.0 m | 883/4917/9 |
| 78 | 35402170 | 天龙山景区西门-石碑起伏 | 5.051 km；+170.6/-104.2 m | 26/32/1 |
| 79 | 35402181 | 天龙山石碑-景区西门起伏 | 5.140 km；+105.1/-172.8 m | 23/29/1 |
| 85 | 35961319 | 太古路（植物园-狼坡） | 15.369 km；+624.0/-3.0 m | 19/28/3 |
| 87 | 36442639 | 天龙山最后1公里 sprint | 0.978 km；+31.6/-0.0 m | 833/4395/3 |
| 89 | 36574001 | 牛家口放坡 | 7.413 km；+3.0/-305.2 m | 57/125/0 |
| 93 | 36620273 | 天龙山反爬清明被追击 | 5.723 km；+336.9/-5.6 m | 263/802/1 |
| 96 | 36946253 | 天龙山岔口到两圈圈 | 2.771 km；+193.4/-26.9 m | 959/6427/5 |
| 97 | 37170432 | 2019环太原石碑-天龙山石碑 | 9.664 km；+455.6/-28.5 m | 132/191/0 |
| 98 | 37394053 | 龙山 climb 大桥-观景台 | 5.066 km；+273.8/-5.0 m | 271/861/1 |

窗口只是候选边界，绝不代表这 21 条天然同路；道路族仍由几何、方向、区间和端口事实产生。

## 4. 权威输入与一次性事实导出

| 输入 | 位置 / 身份 |
|---|---|
| active 81 几何/GLO 总量/热度 slice | `/Users/macbookair/.codex/evidence/velo/transit-paths/xishan-v1/xishan-relation-source-slice-81.json`；`slice_sha256=ea2043afdb48bad87107c33659de03597511fce7cf5e12dc52100e7f1fe3cf0c` |
| active selection | `/Users/macbookair/.codex/evidence/velo/transit-paths/xishan-v1/xishan-relation-selection-81.json`；`snapshot_sha256=7d929f96f2d4c18e9f9a0fedcb9868190850a5730198a56eab63744f9be41a8e` |
| relation pointer | `data/research/xishan_relation_oracle_v1_manifest.json` |
| 3,240 对完整 oracle | `/Users/macbookair/Desktop/velo/outputs/xishan-relation-oracle-v1/pairs.jsonl` |
| MountainModule 程序 | `scripts/export_mountain_module_snapshot.py` + `scripts/analyze_mountain_module.py` |
| Transit / choice 程序 | `scripts/analyze_xishan_transit_path.py` + `scripts/analyze_route_choice_set.py` |

active-81 slice 已足够让 exact 21 同时做几何/关系分组；它没有完整 elevation profile。获得生产只读权限后，一次性从既有 `SegmentElevationFact` 导出这 21 条完整 GLO snapshots，数据库写入必须为 0。没有只读权限时，继续完成所有几何分组和组合候选，不得让整个批次停在“等数据”；只有需要完整 profile 的最终 MountainModule 资源账标 `glo_profile_pending_readonly_export`。

禁止重新抓 Strava、重新算 GLO、重跑 3,240 全对、引入 OSM、恢复旧 DFS，或把研究对象直接写成正式 RouteBook。

六条 XC 已不在 active 81。本批不再讨论它们；生产清理由下一次授权部署单独完成。

## 5. 批量形成道路族，不写 21 套逻辑

先用 oracle 召回，再用通用 projection 对候选参考轴批量跑。初始 family hypothesis 只用于调度，不是结论：

- 牛家口—天龙山长线：o4、o89、o55、o97 等；
- 天龙山东侧热门主爬：o17、o18、o57、o87、o96 等；
- 天龙山北侧 / 龙山 / 店头：o8、o21、o28、o49、o50、o51、o93、o98、o9；
- 天龙山西门往返方向：o78、o79；
- 太古路长范围边界/过境候选：o85。

当前 `MountainModuleSpec` 是单参考轴，因此每个实际道路族各自选择 canonical axis；不是每条赛段建一个 module，也不为多轴重写大框架。若两个 family 只是同一路不同方向/局部，合并到一份物理几何；若确属不同 approach，保留不同 traversal/module。

已有冻结反例必须继续成立：

- o78/o79 是同线反向；
- o55 是 o89 的反向局部证据；
- o8/o93 同向但属于另一 approach，不能按“天龙山”名称强并进 o17；
- o4/o17 及多组 self-overlap / multiple-projection 灰态必须由 projection 给 witness，或保持灰态；
- 同一物理几何永远只保存一份，反向只转换 traversal、交换 entry/exit 与爬升下降并读取反向热度。

## 6. 连接与选择：直接做成区域产品原型

道路族形成后，直接进入有限连接和选择组装：

1. 只对自然相邻的 module exit→entry 请求腾讯路线；腾讯骑行或开车都可作为本轮 connectivity shadow，记录 provider profile，不把它冒充路况事实。
2. Strava 赛段只作为 transit 上的热度证据，不作为 waypoint；没有赛段的普通道路是 `unobserved`。
3. 先生成目的地核心、双目的地串联、南部横穿/环线等候选，再让 hard gate 淘汰断链、重复资源或回走异常。
4. 目标 6–12 个可解释选择，按 scope 分组：短核心爬坡、中等双目的地、长距离区域串联。不同 scope 不做粗暴总排名。
5. 同 scope/intent 内直接运行确定性 Pareto + intent lexicographic 排序，不等待 ML。
6. Agent 最终必须给骑友说清：去哪、怎么串、多少公里和爬升、热门段在哪、普通过境在哪、适合谁、代价是什么。

不要为每个候选补一套新测试。复用现有机械门；只有真实批次触发 typed failure、冻结反例被破坏或算法语义冲突时，才补最小回归。

## 7. 完成标准

同时满足以下条件才结束：

- exact 21 来源身份、几何 hash、GLO fact ID 和热度逐条对账；
- 形成多个道路族 / MountainModule，而不是只交付牛家口或 o4/o17 两个 probe；
- 相同物理几何不复制，反向和重叠不重复累计距离/爬升；
- 自然相邻积木有完整 TransitPath 或 typed reject；单个失败不拖停整批；
- 产出 6–12 个目标选择，或明确列出事实允许的最大集合及淘汰原因；
- 每个通过候选有资源、方向热度、未观测、适合谁、为什么和代价；
- 横岭基线 replay 不漂移，同输入可重放；
- 最终给出一张“西山南部怎么骑”的清晰总览；
- 仍标 research candidate，不声称已进入生产或全国泛化。

## 8. 新 Session 启动提示词

```text
使用 `ingest-velo-road-segments` skill，继续 VELO 的西山南部区域级批处理实验。允许使用子 Agent 做独立只读审查和并行事实盘点。

只使用现有工作树：
/private/tmp/velo-xishan-multisegment-reproduction
分支 codex/xishan-multisegment-reproduction，PR #75，以现场 HEAD 为准。先运行 git status --short、git log -5 --oneline 和 gh pr checks 75；不要在桌面 main 重做。

完整读取执行合同：
docs/research/2026-08-14-xishan-south-experiment-handoff.md
docs/research/2026-08-14-city-route-cognition-sop.md
data/research/mountain_modules/README.md

不要再做“牛家口一个点”或 o4/o17 小 probe。一次处理 `xishan_south_destination_network_v1`：固定窗口 lon 112.36..112.48 / lat 37.67..37.78，从 active 81 机械得到 exact 21 observation IDs：
[4,8,9,17,18,21,28,49,50,51,55,57,78,79,85,87,89,93,96,97,98]

直接完成：
1. exact 21 身份/几何/GLO fact/热度对账，并批量跑 oracle + projection；
2. 形成牛家口、天龙山东侧、天龙山北侧/龙山店头、天龙山西门、店头蒙山等实际道路族；由证据决定合并或拆分；
3. 每个实际道路族选择 canonical 单轴，生成多个 MountainModule；同一物理几何只保存一次，反向只转换 traversal 和交换爬降；
4. 对自然相邻端口生成有限腾讯 TransitPath。骑行或开车 profile 均可作 connectivity shadow；赛段只投影热度，不当 waypoint；
5. 组装目标 6–12 个短、中、长真实选择，同 scope/intent 内直接跑 Pareto/意图排序；
6. 给出“西山南部怎么骑”的区域总览，并逐条解释适合谁、为什么、代价是什么。

active-81 slice 没有完整 elevation profile。几何分组不得因此停工；获得生产只读权限后，用现有 exporter 一次导出 exact 21 已落库 GLO snapshots，0 DB write、0 GLO 重算。没权限时只把最终资源账标 pending，继续完成其余批处理。

复用现有机械门和 harness，不重抓 Strava、不重跑 3,240 全对、不引入 OSM、不恢复旧 DFS、不为每条候选堆测试。单个 typed failure 只淘汰相应候选并继续；只有真实语义冲突才做最小根因修复。完成到可重放 artifacts、区域选择集、横岭回归与独立复审。不要部署或删除生产数据，除非本 Session 另有明确授权。

汇报先说人话：这片区域到底分几种骑法、主流路线是哪条、局部热门段如何嵌套、哪些入口能串起来、短中长分别适合谁。然后再列证据和边界。
```
