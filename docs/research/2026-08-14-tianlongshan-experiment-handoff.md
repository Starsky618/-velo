# 天龙山—牛家口下游纵切：新 Session 实验交接

日期：2026-08-14
状态：待实验；只做 research artifacts，不写生产、不部署

## 1. 开工位置

必须继续使用现有独立工作树：

```text
/private/tmp/velo-xishan-multisegment-reproduction
branch: codex/xishan-multisegment-reproduction
baseline: 当前分支 HEAD
```

这条交付链覆盖五个连续阶段；具体 commit SHA 以当前分支 `git log` 为准：

```text
replay xishan transit paths
rank complete xishan route heat
assemble xishan route choices
codify regional analysis loop
hand off tianlongshan experiment
```

分支尚未 push、未开 PR、未部署。桌面主工作树 `/Users/macbookair/Desktop/velo` 不是本实验的实现现场；不要在那里重做或 cherry-pick 一套平行版本。

新 Session 开工前先执行 `git status --short` 和 `git log -5 --oneline`，以现场分支 HEAD 为准，不得回滚或覆盖任何后来出现的用户改动。

## 2. 本次只回答什么

做 `tianlongshan_niujiakou_v1` 的 **MountainModule / choice 下游纵切**：

```text
当前活跃 81 条已闭账硬事实
→ 复用关系 oracle 与通用投影
→ 冻结天龙山目的地内部 traversal/ports
→ 方向化原子热度与资源账
→ 若干个有证据的真实选择
→ Agent 解释适合谁、为什么、代价是什么
```

这些 observation 已进入当前 81 条 relation oracle，因此这不是 relation 层的全新 holdout，也不证明全国泛化。第一阶段不要求跨模块 TransitPath；先证明目的地内部不写天龙山专属算法也能成立。

当前 active-81 slice 足够做几何 probe，但只含 GLO 总距离、总爬升/下降和 fact ID，不含 MountainModule runner 必需的完整 `elevation_snapshot` / `elevation_profile`。正式 module 实验的第一项前置条件，是在新 Session 获得生产只读权限后，用 `scripts/export_mountain_module_snapshot.py` 从既有 `SegmentElevationFact` 导出候选 snapshot；它不重抓 Strava、不重算 GLO，也不写生产。拿不到只读事实时必须明确停在 `mountain_source_snapshot_unavailable`，不得用总爬升反造 profile。

## 3. 权威输入，不要重算

| 输入 | 位置 / 身份 |
|---|---|
| 活跃 81 条完整来源/GLO/热度 slice | `/Users/macbookair/.codex/evidence/velo/transit-paths/xishan-v1/xishan-relation-source-slice-81.json`；`slice_sha256=ea2043afdb48bad87107c33659de03597511fce7cf5e12dc52100e7f1fe3cf0c` |
| 活跃 selection | `/Users/macbookair/.codex/evidence/velo/transit-paths/xishan-v1/xishan-relation-selection-81.json`；`snapshot_sha256=7d929f96f2d4c18e9f9a0fedcb9868190850a5730198a56eab63744f9be41a8e` |
| 关系 pointer | `data/research/xishan_relation_oracle_v1_manifest.json` |
| 3,240 对完整 pair artifact | `/Users/macbookair/Desktop/velo/outputs/xishan-relation-oracle-v1/pairs.jsonl` |
| 通用 MountainModule 参考 | `data/research/mountain_modules/hengling_v1.json` + `scripts/export_mountain_module_snapshot.py` + `scripts/analyze_mountain_module.py` |
| 通用 choice 入口 | `scripts/analyze_route_choice_set.py` |
| 当前执行 SOP | `docs/research/2026-08-14-city-route-cognition-sop.md` |

不要重新抓 Strava、重新跑 81 条 GLO、恢复旧 25 对象 DFS、重做 3,240 全对、引入 OSM，或为了本次实验改生产数据库。

当前活跃 profile 是 `81/81/0`。六条 XC 已不在本地活跃 slice；生产仍待下次授权部署清理 observation `56,106,108,109,110,111`。本实验不得触碰生产清理。

## 4. 首轮候选与硬事实

先从下列来源建立候选集合，最终 membership 由投影结果决定，不能按名字强并：

| observation | Strava ID | 角色线索 | 距离 / GLO | 热度快照 |
|---:|---:|---|---|---|
| o4 | 20835564 | 牛家口—天龙山长线候选轴 | 11.707 km；+517.4/-19.2 m | 117 人 / 179 次 / 22 星 |
| o17 | 24481149 | 天龙山网红公路爬坡候选轴 | 9.282 km；+550.5/-59.4 m | 708 / 3,899 / 181 |
| o18 | 24836971 | 天龙山局部主爬 | 4.805 km；+322.3/-17.2 m | 954 / 6,489 / 19 |
| o55 | 32924675 | 隧道—豆腐店局部段 | 4.042 km；+180.6 m | 224 / 365 / 2 |
| o57 | 34211479 | 连环回旋高架局部段 | 3.185 km；+176.9/-30.0 m | 883 / 4,917 / 9 |
| o87 | 36442639 | 最后 1 km 局部段 | 0.978 km；+31.6 m | 833 / 4,395 / 3 |
| o89 | 36574001 | 牛家口反向来源 | 7.413 km；+3.0/-305.2 m | 57 / 125 / 0 |
| o96 | 36946253 | 天龙山岔口局部段 | 2.771 km；+193.4/-26.9 m | 959 / 6,427 / 5 |
| o97 | 37170432 | 石碑—天龙山石碑长线 | 9.664 km；+455.6/-28.5 m | 132 / 191 / 0 |

另把 o8/o93 与 o78/o79 放在候选边界：它们是不同 approach/反向对照，不得只因同名“天龙山”塞进 o17 主轴。

## 5. 首跑前冻结的预期与反例

以下只是在现有 raw oracle 上冻结的机械预期，不是道路人工 gold：

1. o78/o79 必须保留为 `equivalent + reverse_direction`。
2. o89 对 o55 是反向包含关系：o55 是 o89 的反向局部证据。
3. o8/o93 是同向 containment；它们属于另一侧 approach 候选，不能因山名相同并入 o17。
4. o4/o17、o4/o55、o4/o57、o4/o89、o4/o97，以及 o17/o18、o17/o57、o17/o87、o17/o96 在 raw oracle 中存在 self-overlap / multiple-projection 灰态。通用参考轴投影必须给出可审计 witness，或继续明确灰态；不能因为程序未报错就宣布同路。
5. 相同冻结 component geometry 只保存一次。反向 traversal 只交换 entry/exit、爬升/下降并读取反向热度，不复制物理线。

如果实跑证据否定以上预期，保留反例并解释；不得调阈值把预期硬凑出来。

## 6. 最小执行顺序

1. 读取 active 81 slice 和 pair oracle，从候选表机械产生两组 probe：以 o4 和 o17 分别作候选参考轴。几何 probe 不依赖完整海拔 profile。
2. 在写正式 manifest 前输出一份小型投影对照：每条候选的 matched runs、方向、source/axis coverage、灰态原因和几何身份。
3. 当前 `MountainModuleSpec` 是单参考轴。o4 与 o17 首轮必须分别形成候选 module/run，例如 `tianlongshan_niujiakou_o4_axis_v1` 与 `tianlongshan_o17_axis_v1`；根据投影事实选择 canonical 轴，或保留为两个不同 approach 模块。不得假装现有 harness 已支持一个 module 内多轴。
4. 当前本地没有可信业务数据库，active-81 slice 又缺完整 GLO profile。获得生产只读权限后，用既有 exporter 从已经落库的 GLO facts 导出候选 source snapshot；没有权限或读不到 exact facts 就 typed stop，不新增格式适配器、不重跑 GLO。
5. 用 `scripts/analyze_mountain_module.py` 生成 private run 与 public manifest；保存到本机 evidence ledger，不把完整坐标/GLO profile 提交 Git。
6. 根据实际通过 hard gate 的 route blocks 写 choice spec；数量由事实决定，不预设必须四条。用 `scripts/analyze_route_choice_set.py` 组装和解释。
7. 仅在同一 `comparison_scope + rider intent` 内，显式调用 `rank_heat_candidates()` 做 Pareto/lexicographic 排序。通用 choice CLI 本身只做组装、hard reject 和硬事实对比。
8. 回放横岭基线，确认通用代码或参数没有让既有结果漂移。

## 7. 完成标准

只有同时满足以下条件才算本纵切完成：

- active 81、selection、GLO 和关系身份未被重建或改写；
- probe 先于正式 membership，所有纳入/灰态/拆分都有 witness；
- 新增的是 manifest、private evidence、public manifest 和 choice spec，不存在 `tianlongshan_runner`、山名分支或区域专属阈值；
- 同一物理几何反向复用，重叠赛段只提高区间证据，不重复加距离/爬升；
- 每个选择输出 scope、距离、GLO 爬升下降、方向热度范围、unobserved、适合谁、为什么、代价和禁止脑补项；
- 没有风景、路面、车流、补给硬事实时不编；
- 预期/反例成立或被新证据明确证伪，同输入可重放，横岭回归不漂移；
- 最终仍标 `research_shadow`，不冒充正式路线、生产可用、全国泛化或 learned reranker。

## 8. 当前尚未闭合的系统边界

- `MountainModule` 和 route-choice core/CLI 已通用；
- `TransitPath` 核心对象和西山 replay 已有，但跨城市通用 provider/runner 尚未形成；
- 同一 rider job 的 Pareto 排名函数已实现，但未自动接入 choice CLI；
- 机械 replay loop 已形成；本次只验证下游泛化；
- 真实曝光、选择/拒绝、完成/放弃 episode 的产品 learning loop 尚未形成。

## 9. 交付纪律

先读真实 diff/status，再执行。允许用子 Agent 做独立只读 spec / integration 审查；不要让审查者改同一批文件。完成后分别汇报本地验证、CI、合并、部署、线上真用和资源清理；本 research slice 默认不部署。不要在没有 Tim 新授权时删除生产数据、推送、开 PR 或合并。

## 10. 新 Session 启动提示词

```text
使用 `ingest-velo-road-segments` skill，继续 VELO 的“天龙山—牛家口”下游纵切实验。允许使用子 Agent 做独立只读审查。

先进入并只使用现有工作树：
/private/tmp/velo-xishan-multisegment-reproduction
分支 codex/xishan-multisegment-reproduction，以当前分支 HEAD 为基线。不要在 /Users/macbookair/Desktop/velo 的 main 上重做。
先用 git status --short 和 git log -5 --oneline 核对现场，禁止回滚或覆盖用户改动。

第一步完整读取并以它为执行合同：
docs/research/2026-08-14-tianlongshan-experiment-handoff.md
再按其中链接读取：
docs/research/2026-08-14-city-route-cognition-sop.md
data/research/mountain_modules/README.md

目标不是重新抓 Strava、重算 81 条 GLO、重跑 3,240 全对或设计新算法，而是复用当前 active 81、relation oracle、通用投影、MountainModule 和 route-choice harness，完成 `tianlongshan_niujiakou_v1`：
1. 先以 o4、o17 为候选参考轴做小型投影 probe；
2. 用 handoff 中冻结的 o78/o79、o55/o89、o8/o93 和 o4/o17 等灰态反例验收语义；
3. o4、o17 分别按单参考轴生成候选 module/run，再由硬事实决定 canonical 轴或保留为不同 approach；
4. 生成由硬事实支持的真实选择，解释适合谁、为什么、代价是什么；选择数量由事实决定；
5. 同一物理几何只保存一份，反向只转换 traversal、交换爬升下降并读取反向热度；
6. 回放横岭基线，证明没有区域专属代码或参数漂移。

本实验只是已进入 81 条 oracle 后的 MountainModule/choice 下游纵切，不得冒充 relation 全链路 holdout、全国 RoadCarrierGraph、正式路线或 learned reranker。choice CLI 只做组装、hard reject 和硬事实对比；只有同一 scope/intent 的候选才显式调用 rank_heat_candidates()。

先做不依赖生产的几何 probe。进入正式 MountainModule 前，必须获得生产只读授权，用现有 exporter 导出候选的完整 GLO snapshot；这是只读导出，不重抓 Strava、不重算 GLO、不写生产。若没有权限或 exact facts 不可读，报告 `mountain_source_snapshot_unavailable` 后停止，不要靠新增代码绕开。拿到 snapshot 后直接执行到可重放 research artifacts、定向测试和独立复审完成。若现有机械门通过就继续，不要新增无关门禁或理论测试；只有 typed failure、冻结反例不符或语义证据冲突时，才做最小根因修复。不要推送、开 PR、合并、部署或删除生产数据，除非我在新 session 另行授权。

汇报时先用小学生能听懂的话说明：天龙山内部到底有几条不同骑法、哪些其实是同一条路的局部/反向、热度集中在哪里、适合谁、代价是什么；再列测试、证据边界和未完成项。
```
