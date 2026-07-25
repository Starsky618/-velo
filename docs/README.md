# VELO 项目文档说明书

> **这份文档给谁看**：你（Starsky）、任何新加入的人、以及每一个进入仓库工作的 agent。
>
> **一句话定位**：开新任务时，人类和 agent 如何借助**已有文档 + skills** 走完一条**从模糊想法到生产上线**的完整路径。
>
> **双读者共识**：人类读**视觉地图和场景**，agent 读**路径表格和硬规则**。本文每节都兼顾两者——开头一句讲清场景，主体用表格和路径精确约束。

---

## §0 velo 是什么 · 现在长什么样（30 秒建立直觉）⭐

> 这一页给**总建筑师和新人**：打开就知道 velo 是什么、长什么样、做到哪了。
> 要看本质 → `prd/velo-vision.md`；要架构精确到字段 → `architecture-guide.md`；要看当前在做什么 → 最新 `prd/sprint-N-prd.md`。

**一句话**：velo 是给中国一线城市严肃公路车骑手的「骑行身份图谱」——用 Letterboxd 记电影的方式记骑行：**每次骑车都沉淀成身份，每条赛段都是一个微型社区**。

**核心引擎**（一切功能围着这条环转，环上最脆弱的点 = 最该投入的点）：

```
骑车 → 上传 / Strava 同步 → 解析 → 匹配赛段 → 排行榜 → 看到排名被激励 → 继续骑
```

**系统现在长什么样**：一个主引擎，挂着四组扩展——新功能默认开新房间，不拆主引擎的墙（防火墙式扩展）。

```
                      用户（严肃公路车骑手）
                            │ 骑完车
                            ▼
  ══════════════════════════════════════════════════════════
   🚲 主引擎 · 把骑行变成成绩和身份
      上传 / Strava 同步 → 解析（GPX/FIT）→ 匹配赛段 → 排行榜
      → 通知（破纪录 / 抢 KOM）→ 个人主页（你的赛段身份图谱）
      模块：user · activity · parsing · segment · notification · strava
  ══════════════════════════════════════════════════════════
                            │ 骑行数据沉淀下来，长出四组新能力
                            ▼
   📊 训练大脑 · 看懂自己的身体
      · 训练负荷（累不累）· 训练分布（练对没）
      模块：training
   ──────────────────────────────────────────────────────
   🤝 社交房间 · 把路线变成一起骑　✅ 已上线
      · 约骑 meetup · 路书 route_book
      模块：meetup · route_book
   ──────────────────────────────────────────────────────
   🧭 路线认知审稿室 · 把路线/赛段/概念变成可审关系　🧪 内部可读
      · concept · collection · candidate · human_review formal link
      · route_segments composition overlay（不是路线几何真相）
      模块：route_cognition
   ──────────────────────────────────────────────────────
   🔧 后勤 · 看不见但撑着主引擎运转
      · AI 赛段写手 agent · 监控告警 monitor · 管理后台 admin
      · 存储 / 工具 storage · common
```

**做到哪了**：

- ✅ **已上线**：MVP（上传 → 赛段 → 排行）· Strava 接入 · 训练分析三件套（FTP 估算 / 训练负荷 PMC / 训练分布）· 约骑 + 路书（创建配图 / 照片墙 / 账号注销 / 2026-06-02 全 ship 合 main + 部署）
- 🧪 **内部已验证**：route cognition v1.1 DB foundation + internal writer slice + First Visible Slice dry-run；还没有 public API、admin UI、真实 seed、真实 backfill、external search worker。
- 📋 **待开**：LLM 骑后教练总结（Sprint 12 / 设计稿见 `docs/superpowers/specs/2026-05-26-coach-architecture.md`）

---

## §1 两条主轴（30 秒读完）

velo 的文档**不是一个大通用文档**，是**两套为不同读者服务的平行体系 + 一套共享档案**。

```
       ┌────────────────────────────────┐
       │   人类线（你拍板 / 对外讲故事）   │
       │   prd/ + competitive-analysis/  │
       │   CLAUDE.md 顶部 4 条硬约束      │
       └────────────────┬───────────────┘
                        │
                        ▼
           ┌──────────────────────┐
           │   共享档案（所有人都读）  │
           │   architecture-guide  │
           │   data-flow-guide     │
           │   adr/ (10 份历史档案)│
           │   changelog / tech-debt│
           └──────────────────────┘
                        ▲
                        │
       ┌────────────────┴───────────────┐
       │   agent 线（日常执行 / 判断）     │
       │   agent-rules/ + CLAUDE.md      │
       │   spec-vN.md + plans/phaseN/    │
       └────────────────────────────────┘
```

**核心原则**：人类读的（PRD / 竞品 / 品牌气质）和 agent 读的（规则 / spec / 任务卡）**物理分开**——合一份会既长又抽象，两头不讨好。

**agent 索引纪律**：需要寻找专项文档时再扫本文 §5 目录地图；普通任务不默认加载本文或全部子目录。

---

## §2 旧九阶段工作流（历史参考）

> 根 `AGENTS.md` 是唯一常驻入口。`workflow-kernel.md` 目前只用于 Tim 明确点名的工作流实验；本节保留给旧任务迁移和历史追溯。

旧制要求每期新功能 / 新模块固定走完下面 9 步；现仅用于理解历史任务的文档结构与迁移来源。

### §2.1 全景表

| # | 阶段 | 主导 | 输入文档 | Skill | 产出 | 时长 |
|---|---|---|---|---|---|---|
| ① | 脑暴探索 | 你 | `prd/velo-vision.md` + `prd/velo-strategy.md` | 已退役：旧 Superpowers 脑暴 | 对话记录（无文件） | 0.5-1 天 |
| ② | PRD 撰写 | 你 | `prd/velo-vision.md` + `prd/velo-product-spec.md` + `competitive-analysis/` | 无 | `prd/phase-N-prd.md` ⚠️ | 1-2 天 |
| ③ | 需求塑形 | agent | phase PRD + `agent-rules/` + `competitive-analysis/` | `architect` Step 1-3 | 技术方向 3 选 1 锁定 | 0.5-1 天 |
| ④ | Spec 撰写 | **主 agent 自己写**（chunk by chunk，⭐ 2026-04-28 起禁派 codex 写正文）| 上一步方向 + `architecture-guide.md` + `data-flow-guide.md` + `adr/` | `architect` Step 4-8 | `spec-vN.md`（Critical=0） | 1-2 天 |
| ⑤ | 实施计划 | **主 agent 自己写**（chunk by chunk，⭐ 2026-04-28 起禁派 codex 写正文）| `spec-vN.md` | 已退役：旧 Superpowers 写计划 | `plans/phaseN/README.md` + `task-N.X.md` | 0.5-1 天 |
| ⑥ | 并行执行 | agent 群 | `plans/phaseN/` | 已退役：旧 Superpowers 多 agent 流程 | 代码 + 单测 + commits | 3-10 天 |
| ⑦ | 验证审查 | agent + 你 | 代码 + spec | 已退役：旧 Superpowers 验证与审查流程 | 双审报告 | 1-2 天 |
| ⑧ | 部署上线 | agent + 你 | `CLAUDE.md §部署前强制检查清单` + `deployment-diary.md` | `deploy` | 生产上线 | 0.5 天 |
| ⑨ | 复盘归档 | agent + 你 | 本期所有产出 | 无（CLAUDE.md 防黑盒化三问） | 刷新 `architecture-guide.md` / `data-flow-guide.md` / `changelog.md` / `tech-debt.md`；必要时新增 `adr/0XX.md` | 0.5 天 |

⚠️ **区分两种 PRD**：`prd/velo-*.md` 是**战略级 PRD**（5 年 north star，半年一修），`prd/phase-N-prd.md` 是**每期战术级 PRD**（用户故事 + 验收标准，每期一份）。两者不冲突，战术级必须和战略级不矛盾。

### §2.2 每阶段执行卡

每张卡片都是一个**最小执行闭环**：关键动作 → 必看文档 → 硬规则 → 常见踩坑。

#### ① 脑暴探索 —— 跳出本项目框架

**像**：你和一群懂行的朋友喝咖啡，聊"如果骑行社交重新设计一遍该是什么样"。

- **关键动作**：发散 → 吐槽当前方案 → 挖真实用户 intent → 不下技术决策
- **必看**：`prd/velo-vision.md`（对齐 north star，避免发散到非 velo 方向）+ `prd/velo-strategy.md`（对齐战略红线，避免和小而美哲学冲突）
- **硬规则**：这个阶段**不写文件**、**不做技术选型**、**不讨论实现**。违反 = 提前收敛
- **踩坑**：跳过本阶段直接写 PRD = 闭门造车。`architect` 信条 10 已明文提醒

#### ② PRD 撰写 —— 把想法变成可验收的产品

**像**：给"要盖什么房子"画设计草图。有几个房间、谁住、客人怎么进出。

- **关键动作**：填用户故事 + 验收标准 + 优先级 + **明确不做什么**
- **必看**：`prd/velo-vision.md` § 产品定位 + `prd/velo-product-spec.md` § 用户画像 + `competitive-analysis/letterboxd-对标.md`（产品模板）
- **硬规则**：PRD 必须有"明确不做什么"章节——scope creep 伪装成"完整性"是最常见陷阱（`architect` 信条 4）
- **踩坑**：把技术方案写进 PRD = 产品/技术混写，双读者都不舒服。PRD 只讲 what 和 why，不讲 how

#### ③ 需求塑形 —— 把产品需求收敛到可执行的技术方向

**像**：建筑师听完业主要求后，提 2-3 种可行的建筑形式让业主选。

- **关键动作**：扫代码库（Explore agent）→ 一问一答锁定决策 → 提 2-3 方案对比 → 你选一个
- **必看**：phase PRD + `agent-rules/product-decisions.md`（D-P01 到 D-P10）+ `agent-rules/velo-mental-model.md` § 10 问框架
- **硬规则**：方案对比**必须表格化**（复杂度 / 耦合度 / 扩展性），附推荐理由；用当前用户量 / 团队规模判断合理性，**拒绝为假想未来过度设计**（信条 3）
- **踩坑**：agent 只给一个方案让你选 yes/no → 违反决策格式（信条 7）

#### ④ Spec 撰写 —— 把方向变成可审查的技术规格

**像**：建筑师出施工图，每面墙承重、每根管道走向都标清楚。

- **关键动作**：分段设计（模块 → 数据模型 → 数据流 → API）→ 故障分析五维（崩溃 / 并发 / 批量 / 边界 / 级联）→ **双重审判**（内部一致性 + 代码兼容性并行）→ 翻译成 yes/no 清单让你过审
- **必看**：`architecture-guide.md`（现有系统静态视图）+ `data-flow-guide.md`（现有链路，含 route cognition 内部 writer / demo 链路）+ `adr/`（相关决策）+ `CLAUDE.md § 技术栈陷阱清单`
- **硬规则**：
  - 预读清单（信条 14）：spec 里**任何字段 / 函数 / 状态值**引用必须先 grep 核对
  - 双审判 Agent A + Agent B 并行，prompt 互补，**Critical = 0 才能进下一步**
  - spec ≤ 800 行，一期任务数 ≤ 6
  - ⭐ **2026-04-28 起：spec 正文由主 agent 自己写**（chunk by chunk，每段写完 Edit 落盘）——**禁止派 codex 写**（codex CLI 长任务卡死 bug 链 #13738/#14048/#18723，spec-v5 实证卡死 30+ 分钟）。codex 仍用于：预读清单 grep 核对（A 档）/ spec 写完后异源审查（B 档 review-only）。详见 `docs/agent-rules/agent-collaboration.md` §5
- **踩坑**：凭记忆写字段名 → 双审判必抓一堆虚构引用。v4 实战 12 条 Critical 里一半是这类

#### ⑤ 实施计划 —— 把 spec 拆成可派工的任务卡

**像**：把施工图拆成每个工人的当日任务单（几号砖、几块板、装哪）。

- **关键动作**：产出 `plans/phaseN/README.md`（总调度）+ 每个 `task-N.X.md`（单任务独立卡片）
- **必看**：`docs/archive/plans-phase3-README.md` + `plans-phase4-README.md`（历史样板 / 已归档）
- **硬规则**：2 层扁平结构（README + task 文件），**严禁加第三层索引**（`architect` 信条 + 反模式表）。每个 task 卡含：目标 / 前置依赖 / 输入输出契约 / 完整代码 / 测试用例 / commit 指令 / 自检三问
  - ⭐ **2026-04-28 起：plans 正文由主 agent 自己写**（chunk by chunk，每个 task 卡写完 Edit 落盘）——**禁止派 codex 写**，理由同 ④（codex CLI 长任务卡死 bug 链）。codex 仍用于：plans 写完后异源审查（B 档 review-only）
- **踩坑**：task 卡只写"抽成函数 X"而不给完整实现 → agent 当虚构函数处理

#### ⑥ 并行执行 —— subagent 群同时干活

**像**：每个工人在自己的独立工棚干活，互不踩脚。

- **关键动作**：按当前平台原生方式建隔离工作目录并派多个 subagent → 每个 agent 启动时**只读 README + 自己那份 task 卡**
- **🟨 Codex 可代劳**（按 `docs/agent-rules/agent-collaboration.md §4` 场景模板）：
  - A 档：纯函数实现（parser/matcher/simplify）/ 写单元测试 / 补覆盖率（场景 A）
  - B 档：浅 bug 修复（场景 D）——Claude 定位，Codex 执行修复
- **必看**：每个 subagent 进到自己 worktree 后读 `CLAUDE.md` + 对应 `task-N.X.md` + 分工宪章
- **硬规则**：
  - subagent 一次只加载一个 task 文件（防注意力稀释）
  - TDD 纪律：高风险新业务逻辑先写失败测试，再写实现；低风险改动按任务风险决定
  - 每任务单独 commit，格式 `feat(模块): 任务X.X 简要描述`
- **踩坑**：多 subagent 跨任务传数据走共享状态 → 应该走 task 的"输入输出契约"章节显式声明

#### ⑦ 验证审查 —— 代码层三重审判（Claude 双审 + Codex 异源第三审）

**像**：验收前三个独立监理——两个看工艺（Claude 内部），一个是**从完全不同学校毕业的专家**（Codex）来看别的监理的盲区。

- **关键动作**：
  - **第一轮**：Agent A（code-reviewer）看忠于 spec / 语言陷阱 / 幂等崩溃恢复 / 测试假通过；Agent B（集成审）看 grep caller / 对现有流程干扰 / 数据一致性跨模块 / 前向不兼容
  - **第二轮**（commit 前必做）：调 `codex:codex-rescue` subagent，prompt 按分工宪章 §4 场景 B 模板填（spec + diff + Claude 已列问题禁止复读）
  - Codex 若抓到 Critical/Important → Claude 修 → **同 threadId `--resume` 复查** → 最多 3 轮收敛
- **必看**：本期 spec + 修改的代码 + `CLAUDE.md § 技术栈陷阱清单` + `docs/agent-rules/agent-collaboration.md §4 场景 B`
- **硬规则**：
  - **不做代码层双审 = 违反 `CLAUDE.md § commit 前 4 问`第 4 条 + `architect` 信条 5**
  - **不跑 Codex 异源第三审 = 违反 `CLAUDE.md § 开发原则 8`**
  - Critical 必修 / Important 按优先级 / Minor 入 `tech-debt.md`
  - Codex 输出可信度分级见分工宪章 §6
- **跳过场景**（理由写在 commit message）：纯文档改动 / 单文件 <50 行 / 紧急 hotfix（完整清单见分工宪章 §5）
- **踩坑**：
  - 只看 pytest passed 就 commit → v4 批 1-6 被补审抓出 1 Critical + 3 Important
  - 只跑 Claude 双审不跑 Codex → v4 task-7.10 Claude 双审漏掉 leaderboard fallback（第一页未命中时跳错赛段，核心反馈环断），Codex 一轮抓到

#### ⑧ 部署上线 —— 从本地到生产

**像**：从沙盘搬到真实工地，土地、水电、规章都是新的。

- **关键动作**：按 `CLAUDE.md § 部署前强制检查清单` 逐项对齐 → git pull 或 scp → docker compose 重启 → alembic 迁移 → 日志核验
- **必看**：`CLAUDE.md § 部署经验` + `deployment-diary.md`（历史踩坑）
- **硬规则**：**本地测试全绿 ≠ 生产能跑**。requirements.txt / docker-compose.yml / OAuth 回调地址 / 服务器网络 4 项必查
- **踩坑**：第 2 期 Alembic 迁移脚本 Python try/except 包 DDL → PG 事务 abort 全崩

#### ⑨ 复盘归档 —— 防黑盒化

**像**：工程完工后更新楼宇图、归档施工日志、提炼经验教训。

- **关键动作**：刷新 `architecture-guide.md` + `data-flow-guide.md` + `changelog.md`；若出现新 bug 模式 → 进 `CLAUDE.md § 技术栈陷阱清单`；若出现重大架构决策 → 新增 `adr/0XX-为什么xxx.md`
- **必看**：`CLAUDE.md § 防黑盒化`
- **硬规则**：必答黑盒度体检三问——10 分钟讲全貌 / 数据流复述 / 30 秒读懂任意文件。不满意当期清完，**不留下期**
- **踩坑**：只更 changelog 不更 architecture-guide → 下期 agent 读不懂新结构

---

## §3 旧双工作流已退役

2026-07-12 起，Superpowers 插件及全部 skills 已卸载，不再作为 VELO 的执行层。模型负责通用的分析、计划、调试和验证；项目只提供它不可能凭空知道的目标、产品合同、权限边界和真实验收方法。

`docs/superpowers/` 只是历史目录名，里面仍有已落地功能的产品合同和设计证据，**不代表 Superpowers 仍在运行**。新任务由根 `AGENTS.md` 给出常驻边界；是否写计划、先写测试、派 subagent 或做异源审，按任务风险决定，不再固定走一套仪式。

---

## §4 场景速查 —— 不走全流程时用

按"你想干什么"查文档，每条路径 5-15 分钟。

| 场景 | 读什么 | 时长 |
|---|---|---|
| 新人 / 新 agent 第一天上岗 | `CLAUDE.md` → 本文 → `architecture-guide.md` → `agent-rules/product-decisions.md` → 最新 `spec-vN.md` | 30 分钟 |
| 改数据库 / 加新表 | `CLAUDE.md § 防火墙式扩展` → `adr/008-为什么防火墙式扩展.md` → `architecture-guide.md § 数据模型` | 10 分钟 |
| 修跨模块 bug | `data-flow-guide.md` 对应链路 → `architecture-guide.md` 对应模块 → grep 代码 | 15 分钟 |
| 有人提议改技术栈 | 对应 `adr/001/002/003` → 看"触发重评估条件"是否真触发 | 15 分钟 |
| 和投资人讲 velo | `prd/velo-vision.md`（15 分钟）→ `prd/velo-strategy.md § 8 投资人 Q&A` | 30 分钟 |
| 设计新功能 | `agent-rules/product-decisions.md` D-P0N → `competitive-analysis/letterboxd-对标.md` + `行者-黑鸟-骑记-失败模式.md` | 30 分钟 |
| 查"之前部署怎么踩坑的" | `deployment-diary.md` + `changelog.md` | 10 分钟 |
| 线上救火 | `tech-debt.md` → `data-flow-guide.md` 对应链路 → `CLAUDE.md § 已知风险` | 5 分钟 |
| 产品复杂决策不知怎么拍板 | `agent-rules/velo-mental-model.md § 10 问框架` | 15 分钟 |

---

## §5 文档全目录地图

按"我在找什么"分 5 类，每条给**一句说明 + 精确路径**。agent 建索引时扫这节即可。

### A. 战略与产品（人类线）

| 路径 | 定位 | 何时读 |
|---|---|---|
| `docs/prd/README.md` | 3 份战略 PRD 的读者路线图 | 进 prd/ 前先读 |
| `docs/prd/velo-vision.md` | 5 年 north star / 立国宣言 | 融资 / 对外定位 |
| `docs/prd/velo-strategy.md` | 深度战略论证 + 投资人 Q&A | 战略决策 |
| `docs/prd/velo-product-spec.md` | 产品细节 + 用户画像 + UGC 治理 | 设计新功能 |
| `docs/prd/phase-N-prd.md` | 每期战术级 PRD（N = 期号） | 每期开工前写 |
| `docs/competitive-analysis/README.md` | 5 份竞品索引 | 进 competitive-analysis/ 前读 |
| `docs/competitive-analysis/strava-深度解码.md` | Strava 的 4 个结构性死穴 | 融资答疑 |
| `docs/competitive-analysis/letterboxd-对标.md` | velo 的北极星，产品模板 | 设计新功能 |
| `docs/competitive-analysis/komoot-对标.md` | 反面教材（工具 / 路线规划陷阱） | 被劝做路径规划时 |
| `docs/competitive-analysis/行者-黑鸟-骑记-失败模式.md` | 中国前辈 5 大失败模式 | 被劝做电商 / 综合化时 |
| `docs/competitive-analysis/outbase-dogfood-模板.md` | **待 Tim 亲自 dogfood 填写** | Tim 正在 dogfood 时 |

### B. 执行与技术（agent 线）

| 路径 | 定位 | 何时读 |
|---|---|---|
| `docs/spec-v5.md` | v5 期技术规格（当前现行） | 写代码前 |
| `docs/spec-route-export-v0.md` | 路书导出到码表的 V0 合同 | 改 GPX/TCX 导出前 |
| `docs/spec-route-draw-v0.md` | 探索页手画路线 + 腾讯贴路 V0 合同 | 改画路线 / 路线吸附前 |
| `docs/plans/route-draw-v0/` | Route Draw V0 任务卡 | 执行画路线功能前 |
| `docs/archive/spec-v1.md` ~ `spec-v4.md` | v1-v4 期已 ship 归档（含 sunset 注释防陷阱） | 历史参考 |
| `docs/archive/plans-phaseN-README.md` | 历史已 ship 总调度（phase3-5 + sprint-*） | 历史参考 |
| `docs/archive/plans-phaseN-task-N.X.md` | 历史已 ship 任务卡 | 历史参考 |
| `docs/architecture-guide.md` | 系统静态全景（模块 / 容器 / 表 / 依赖图）| 新人入职 / 加新模块 |
| `docs/data-flow-guide.md` | 数据流动态链路（含主干、约骑、训练、route cognition 内部链路） | 修跨模块 bug |
| `docs/adr/README.md` | 10 份 ADR 总表 + 按场景索引 | 有人提议改决策时 |
| `docs/adr/001-010-*.md` | 单条决策的完整论证 | 需要权威先例时 |
| `docs/dev-guide.html` | Tim 专属 mental model 速查（7 tab 可交互 / 浏览器打开）| Tim 自己用 / 架构 + 协作机制全景速查 |
| `docs/superpowers/specs/2026-05-24-task-skill-spec.md` | task skill 设计 brief（给 codex-skill-creator / 5-phase SOP / cross-project pattern）| 给 Codex 装 task skill 时 / 或迁移到别项目时 |
| `docs/prd/sprint-9/10/11-prd.md` | 训练分析三件套战术 PRD（FTP 估算 / 训练负荷 PMC / 训练分布）| 改训练模块前 |
| `docs/superpowers/specs/2026-05-25-sprint-11-training-distribution-spec.md` | 训练分布技术 spec | 改训练分布前 |
| `docs/superpowers/specs/2026-05-28-meetup-module-design.md` | 约骑 + 路书模块设计（✅ 已 ship 合 main）| 改约骑 / 路书前 |
| `docs/superpowers/plans/2026-05-28-meetup-module/` | 约骑 + 路书任务卡（02 路书 / 03 约骑 service / 04 约骑 API / 08 赛段约骑入口）| 执行约骑 / 路书时 |

> `architecture-guide.md` + `data-flow-guide.md` 已收录约骑 / 路书模块，也已同步 route cognition v1.1 DB foundation、内部 writer slice、First Visible Slice dry-run 的边界。

### C. 运行规则（硬约束）

| 路径 | 定位 | 加载时机 |
|---|---|---|
| `/AGENTS.md`（项目根） | 唯一常驻入口：产品边界、风险动作和验收入口 | 每次会话常驻 |
| `/CLAUDE.md`（项目根） | 技术陷阱、部署历史和旧规则说明 | 命中对应技术或事故时检索 |
| `docs/agent-rules/README.md` | agent 规则体系索引 + ID 命名规范 | 需要寻找专项规则时 |
| `docs/agent-rules/product-decisions.md` | 378 行规则化结论（INV-P01~P06 / D-P01~P10 / 活人感 / 禁止词） | 产品方向、用户范围或商业化决策时 |
| `docs/agent-rules/velo-mental-model.md` | 756 行思考框架（公司定位 / 画像深描 / 10 问框架） | 复杂决策按需加载 |
| `docs/agent-rules/agent-collaboration.md` | Claude ↔ Codex 分工宪章：3 档 / 5 判断法则 / 4 场景 prompt 模板 | 调用 Codex 前按需加载 |

### D. 历史档案

| 路径 | 定位 | 何时读 |
|---|---|---|
| `docs/changelog.md` | 所有改动流水账 | 查"这改动何时合的" |
| `docs/deployment-diary.md` | 部署踩坑笔记 | 部署前 / 踩新坑后追加 |
| `docs/tech-debt.md` | 已知债务清单 | **每期开工前必扫** |
| `docs/archive/handover.md` | 2026-04-08 后端技术快照（已归档） | 历史参考 |

### E. 个人与归档

| 路径 | 定位 |
|---|---|
| `docs/learning/VELO学习笔记.docx` | Starsky 的 CS 学习积累 |
| `docs/archive/` | 历史归档 59 file（spec-v1~v4 + plans-phase3-5 + plans-sprint-* + handover）|

### F. 升级路由表：教训类型 → 进哪份文档（agent 自决用）⭐

> agent 每次 save memory 后自问"这条对方看不见会重蹈覆辙吗？"——是 → 按下表升级到 git 文档。
> 详细机制见 `docs/agent-rules/agent-collaboration.md §9`。

| 教训类型 | 升级目标 | 示例 |
|---|---|---|
| 协作协议 / 流程改进 | `docs/agent-rules/agent-collaboration.md` | "rebuild 后必须验容器代码版本" / "SSH 命令必须 sed 脱敏" |
| 项目特定技术陷阱（写代码时易踩）| `CLAUDE.md` § 技术栈陷阱清单 | "EWKB hex vs WKT" / "populate_existing 配 with_for_update" |
| 安全 / 边界硬护栏 | `CLAUDE.md` 顶部硬规则 | "防火墙式扩展" / "PAT 不进 git" |
| 产品决策规则 | `docs/agent-rules/product-decisions.md` | INV-P01 ~ P06 类硬约束 |
| 架构演进决策（含理由）| `docs/adr/` | "为什么不用 Redis Cluster" |
| 一次性踩坑（非通用）| `docs/changelog.md` / `docs/deployment-diary.md` | "task-0.7 24/24 失败诊断 → fix" |

**留 memory（不升级）的类型**：
- user 偏好（Tim 偏爱压缩输出 / 战略发散）
- agent 自己工作模式反思
- 项目背景（朋友圈 / 战略 PRD 关系）

**核心标准**：如果对方 agent（Claude ↔ Codex 互换主开发时）看不见会重蹈覆辙 → 升级；如果只是 agent 自己工作偏好 → memory 即可。

---

## §6 文档命名规范

保持整齐，避免"同一件事这期叫 phase4 下期叫 2026-05-01"。

| 类型 | 命名 | 示例 |
|---|---|---|
| 战略 PRD | `docs/prd/velo-{vision/strategy/product-spec}.md` | 固定 3 份 |
| 战术 PRD | `docs/prd/phase-N-prd.md` | `phase-5-prd.md` |
| 技术 Spec | `docs/spec-vN.md` | `spec-v5.md` |
| 实施计划（新 sprint） | `docs/plans/phaseN/` 或自定义 | 新 sprint 启动时建 |
| 历史已 ship 实施计划 | `docs/archive/plans-phaseN-*.md` | `archive/plans-phase5-task-8.1.md` |
| ADR | `docs/adr/0XX-为什么{决策}.md` | `adr/011-为什么xxx.md` |
| 竞品分析 | `docs/competitive-analysis/{对手}-对标.md` 或 `-深度解码.md` 或 `-失败模式.md` | 见 §5A |

**老遗产**：第 3 期之前用过日期扁平命名（`2026-04-16-xxx.md`），已归档到 `docs/archive/plans-phase3-*`，以后不再用。

---

## §7 维护机制

这份 README 是**活文档**。**每期 §9 复盘归档** 时必答一问：**本文还准确吗**？

### 什么时候必须改本文

1. 新增文档类型（比如以后加 `docs/postmortem/` 事故复盘）→ 同步更新 §5 目录地图
2. 新增 / 调整工作流阶段 → 同步更新 §2 全景表 + §2.2 执行卡
3. 新增或废弃 skill → 同步更新 §2 全景表 + §3 分工表
4. 新增子目录 README（prd/adr/等）→ 在 §5 加索引行

### 硬约束

- ⚠️ **路径错一个就是灾难**——改动后全文 grep 所有涉及路径
- ⚠️ 修订后最后一节追加一行修订记录，注明日期 + 改了啥
- ⚠️ 不要让本文"只追加不删除"——老内容过时直接删，**过时文档比没文档更坑**

---

## §8 新人 / 新 agent 第一次上岗清单

按顺序，30 分钟进入工作状态：

1. **`/CLAUDE.md`**（项目根，8 分钟）—— 硬规则 + 技术栈陷阱 + 已知风险 + 部署清单
2. **本文 `docs/README.md` §0 全景 + 全文**（你正在看，5 分钟）—— 先用 §0 建立"velo 是什么 / 长什么样"的宏观直觉，再看整体地图 + 工作流
3. **`docs/agent-rules/product-decisions.md`**（agent 专属，5 分钟）—— 产品判断规则
4. **`docs/architecture-guide.md`**（10 分钟速浏）—— 系统静态全景
5. **当前期 `docs/spec-vN.md`**（2 分钟速浏）—— 在做什么

看完这 5 份你就有了**战略 + 规则 + 架构 + 当期**的四视角。

---

## §9 修订记录

- 2026-04-17 初版：5 楼结构 + 9 阶段
- **2026-04-23 v2 重构**：双轨读者分层 + 9 阶段 × 文档 × skill 全景表 + 每阶段执行卡 + 场景速查 + 5 分类目录地图；删除"5 楼办公楼"物理隐喻
- **2026-04-28 v2.1**：撤回"派 codex 写 spec/plans"——§2.1 全景表 ④⑤ 行主导改回主 agent / §2.2 ④⑤ 卡加硬规则行禁派 codex 写正文（chunk by chunk 自己写 → 写完 codex review-only）。理由：codex CLI 长任务卡死 bug 链（#13738/#14048/#18723），实证 spec-v5 卡死 30+ 分钟
- **2026-05-25**（git 有改动、当时漏留记录，今日补注）：neat-freak 同步 2026-05-23~25 双主驾协作机制 session 沉淀
- **2026-05-30 v2.2**：新增 **§0 velo 全景章**（一句话本质 + 核心引擎反馈环 + "1 主引擎 / 3 组扩展"架构图 + 进度三态）——补上"产品本质 + 架构全貌"的人话入口；§5B 目录补约骑 / 路书 / 训练分析指针 + architecture-guide 行去掉写死的过时数字（原"7 容器 / 6 模块 / 7 表"）；§8 新人清单首读 §0
- **2026-06-29 v2.3**：neat 同步 route cognition v1.1 post-foundation 状态——§0 从 3 组扩展改为 4 组扩展，新增“路线认知审稿室”；修正 data-flow-guide 不再是“9 条链路”的旧说法，明确 route cognition 目前是内部可读，不是 public API / admin UI。
