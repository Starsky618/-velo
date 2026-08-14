# docs/research —— velo 路线认知调研 + 数据库设计档案

> 2026-06-14→19 的"开放探索 agent 调研 + 路线认知数据库设计"产物。route cognition v1.1 数据库地基已完成，后续进入内部写入服务、审核流程和小范围种子数据阶段。

## 正式产物（要看的）

| 文件 | 是什么 | 状态 |
|---|---|---|
| **2026-08-14-velo-climb-planner-v1-algorithm-benchmark.md** | Garmin/Strava 公布门槛、连续爬坡检测、Cat+坡型、多坡组成、功率物理估时和置信度的 Climb Planner v1 一手资料合同 | **当前纵向路线算法基准**。实现入口是 `app/elevation/climb_planner.py`，离线重放入口是 `scripts/analyze_climb_plan.py`，冻结样例在 `data/research/climb_plans/`；奥申样例明确是合成坡型控制而非真实完整海拔，不把厂商未公开分段算法冒充 Garmin 规则 |
| **2026-08-14-xishan-south-experiment-handoff.md** | 新 Session 一次处理牛家口、天龙山多入口、天龙山西门、龙山、店头和蒙山的区域级批处理启动单 | **当前实验启动单**。active-81 地理窗口机械得到 exact 21；批量产出多个积木、有限连接和真实选择，不再只做牛家口小纵切 |
| **2026-08-14-city-route-cognition-sop.md** | 从多赛段闭账、关系/投影、山区积木、过境路、路线组合到硬数据骑友解释的通用状态流；同时标明 replay loop 与尚未形成的产品 learning loop | **当前执行 SOP**。下一块一次处理西山南部 destination network，不复制区域算法；它不冒充 relation 全链路 holdout |
| **2026-08-13-xishan-multisegment-reproduction-v1.md** | 西山旧多赛段 DFS/地图桥实验的历史证据恢复，以及两条连接候选、两个 portal-pair 对照和一个回走失败样本 | **当前跨积木实证**。provider 先产完整过境路，赛段只投影方向化证据；腾讯 driving shadow 不等于骑行准入 |
| **2026-08-13-hengling-mountain-module-slice.md** | 横岭公路主走廊第二个山区目的地积木 research slice：通用 Strava 参考轴投影、方向化重叠热度与完整上/下坡证据 | **当前第二走廊实证**。赛段端点不是道路终点；不使用 OSM，不声称直接连接桃花沟，也不证明 o40/o82 接入或完整路线可达 |
| **route_cognition_v1_1_completion_report.md** | route cognition v1.1 数据库地基最终收口报告：最终 Alembic head、commit 链、表清单、验证摘要、已完成/未完成范围 | **最终完成态事实源**。判断 v1.1 DB foundation 是否完成先看这里 |
| **route_cognition_v1_1_operationalization_plan.md** | DB 地基完成后的运营化计划：内部 writer、审核流程、安全 seed、未来只读 API 与后置工作 | **DB foundation 专线的后续计划**，不是当前西山南部实验入口；不要继续为本实验加 schema |
| **route_cognition_v1_1_status.md** | route cognition v1.1 当前实现状态与批次边界 | **当前事实源**。后续窗口先看这里，再看仓库 live files |
| **route_cognition_v1_1_scope_reset.md** | 2026-06-18 暂停扩张时的范围复位文档，记录为什么不再使用 Batch 8、为什么把后续拆成 Step A-D | **历史决策轨迹**。已被 completion report + operationalization plan 接管当前状态 |
| **route_cognition_schema_FINAL.md** | 路线认知数据库历史 schema（双异源审 + Tim 全拍定） | **已被 v1.1 supersede**。只保留作历史审查轨迹，不再作为建表依据 |
| **2026-06-15-taiyuan-xishan-cycling-cognition.md** | 太原西山骑行完整认知（AI 开放探索涌现 + Tim 验证）。三个世界/三场环太原赛/赛事路vs本地路 | Tim 验证基本都真 |
| **2026-06-15-taiyuan-platform-newcomer-research.md** | 太原码表硬件+软件平台生态 + 新骑友归宿调研（补盲区） | Tim 验证；证伪了"约骑散微信群无平台" |
| **2026-06-15-bigcity-cycling-community-structure.md** | 北上杭蓉骑行社群结构调研（中心化大俱乐部vs solo vs 小团） | Codex 跑 |
| **2026-06-15-taiyuan-18segments-data.md** | 太原西山 18 赛段 Strava 实采数据（CR校验过） | 原始数据 |
| **2026-06-15-taiyuan-research-process-raw.md** | 第一轮开放探索 agent 的完整过程（好奇清单+对质过程，从中断 transcript 抢救） | 过程档案 |

## 关联

- **开放探索配置方法论**（这些调研怎么产出的）→ memory `feedback_open_exploration_agent_config`
- **市场结构判断** → memory `project_velo_taiyuan_market_structure`
- **判断引擎设计现场** → `docs/superpowers/specs/2026-06-14-judgment-engine-design-genesis.md` + `2026-06-15-judgment-engine-uncertainty-descent.md`
- **骑行第一性原理地基**（开放探索 agent 的知识地基）→ `~/.claude/skills/judge/references/cycling-first-principles.md`
