# VELO 项目文档说明书

> **这份文档给谁看**：你（Starsky）、任何新加入的人、以及每一个进入仓库工作的 agent。
>
> **一句话定位**：开新任务时，人类和 agent 如何借助**已有文档 + skills** 走完一条**从模糊想法到生产上线**的完整路径。
>
> **双读者共识**：人类读**视觉地图和场景**，agent 读**路径表格和硬规则**。本文每节都兼顾两者——开头一句讲清场景，主体用表格和路径精确约束。

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

**agent 索引纪律**：agent 每次进入仓库先扫本文 §5 目录地图建索引，不默认全量加载子目录。

---

## §2 开新任务完整工作流（9 阶段）⭐ 核心章

每开一期新功能 / 每个新模块都按这 9 步走。每步**谁主导 / 读什么 / 用哪个 skill / 产出什么文件**都固定下来。

### §2.1 全景表

| # | 阶段 | 主导 | 输入文档 | Skill | 产出 | 时长 |
|---|---|---|---|---|---|---|
| ① | 脑暴探索 | 你 | `prd/velo-vision.md` + `prd/velo-strategy.md` | `superpowers:brainstorming` | 对话记录（无文件） | 0.5-1 天 |
| ② | PRD 撰写 | 你 | `prd/velo-vision.md` + `prd/velo-product-spec.md` + `competitive-analysis/` | 无 | `prd/phase-N-prd.md` ⚠️ | 1-2 天 |
| ③ | 需求塑形 | agent | phase PRD + `agent-rules/` + `competitive-analysis/` | `architect` Step 1-3 | 技术方向 3 选 1 锁定 | 0.5-1 天 |
| ④ | Spec 撰写 | **主 agent 自己写**（chunk by chunk，⭐ 2026-04-28 起禁派 codex 写正文）| 上一步方向 + `architecture-guide.md` + `data-flow-guide.md` + `adr/` | `architect` Step 4-8 | `spec-vN.md`（Critical=0） | 1-2 天 |
| ⑤ | 实施计划 | **主 agent 自己写**（chunk by chunk，⭐ 2026-04-28 起禁派 codex 写正文）| `spec-vN.md` | `architect` Step 9 + `superpowers:writing-plans` | `plans/phaseN/README.md` + `task-N.X.md` | 0.5-1 天 |
| ⑥ | 并行执行 | agent 群 | `plans/phaseN/` | `subagent-driven-development` + `using-git-worktrees` + `test-driven-development` | 代码 + 单测 + commits | 3-10 天 |
| ⑦ | 验证审查 | agent + 你 | 代码 + spec | `verification-before-completion` + `requesting-code-review` + `receiving-code-review` | 双审报告 | 1-2 天 |
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
- **必看**：`architecture-guide.md`（现有系统静态视图）+ `data-flow-guide.md`（现有 9 条链路）+ `adr/`（相关决策）+ `CLAUDE.md § 技术栈陷阱清单`
- **硬规则**：
  - 预读清单（信条 14）：spec 里**任何字段 / 函数 / 状态值**引用必须先 grep 核对
  - 双审判 Agent A + Agent B 并行，prompt 互补，**Critical = 0 才能进下一步**
  - spec ≤ 800 行，一期任务数 ≤ 6
  - ⭐ **2026-04-28 起：spec 正文由主 agent 自己写**（chunk by chunk，每段写完 Edit 落盘）——**禁止派 codex 写**（codex CLI 长任务卡死 bug 链 #13738/#14048/#18723，spec-v5 实证卡死 30+ 分钟）。codex 仍用于：预读清单 grep 核对（A 档）/ spec 写完后异源审查（B 档 review-only）。详见 `docs/agent-rules/codex-division-of-labor.md` §5
- **踩坑**：凭记忆写字段名 → 双审判必抓一堆虚构引用。v4 实战 12 条 Critical 里一半是这类

#### ⑤ 实施计划 —— 把 spec 拆成可派工的任务卡

**像**：把施工图拆成每个工人的当日任务单（几号砖、几块板、装哪）。

- **关键动作**：产出 `plans/phaseN/README.md`（总调度）+ 每个 `task-N.X.md`（单任务独立卡片）
- **必看**：`plans/phase3/README.md` + `plans/phase4/README.md`（历史样板）
- **硬规则**：2 层扁平结构（README + task 文件），**严禁加第三层索引**（`architect` 信条 + 反模式表）。每个 task 卡含：目标 / 前置依赖 / 输入输出契约 / 完整代码 / 测试用例 / commit 指令 / 自检三问
  - ⭐ **2026-04-28 起：plans 正文由主 agent 自己写**（chunk by chunk，每个 task 卡写完 Edit 落盘）——**禁止派 codex 写**，理由同 ④（codex CLI 长任务卡死 bug 链）。codex 仍用于：plans 写完后异源审查（B 档 review-only）
- **踩坑**：task 卡只写"抽成函数 X"而不给完整实现 → agent 当虚构函数处理

#### ⑥ 并行执行 —— subagent 群同时干活

**像**：每个工人在自己的独立工棚干活，互不踩脚。

- **关键动作**：`using-git-worktrees` 建隔离工作目录 → `dispatching-parallel-agents` 派多个 subagent → 每个 agent 启动时**只读 README + 自己那份 task 卡**
- **🟨 Codex 可代劳**（按 `docs/agent-rules/codex-division-of-labor.md §4` 场景模板）：
  - A 档：纯函数实现（parser/matcher/simplify）/ 写单元测试 / 补覆盖率（场景 A）
  - B 档：浅 bug 修复（场景 D）——Claude 定位，Codex 执行修复
- **必看**：每个 subagent 进到自己 worktree 后读 `CLAUDE.md` + 对应 `task-N.X.md` + 分工宪章
- **硬规则**：
  - subagent 一次只加载一个 task 文件（防注意力稀释）
  - TDD 纪律：先写测试再实现（`test-driven-development`）
  - 每任务单独 commit，格式 `feat(模块): 任务X.X 简要描述`
- **踩坑**：多 subagent 跨任务传数据走共享状态 → 应该走 task 的"输入输出契约"章节显式声明

#### ⑦ 验证审查 —— 代码层三重审判（Claude 双审 + Codex 异源第三审）

**像**：验收前三个独立监理——两个看工艺（Claude 内部），一个是**从完全不同学校毕业的专家**（Codex）来看别的监理的盲区。

- **关键动作**：
  - **第一轮**：Agent A（code-reviewer）看忠于 spec / 语言陷阱 / 幂等崩溃恢复 / 测试假通过；Agent B（集成审）看 grep caller / 对现有流程干扰 / 数据一致性跨模块 / 前向不兼容
  - **第二轮**（commit 前必做）：调 `codex:codex-rescue` subagent，prompt 按分工宪章 §4 场景 B 模板填（spec + diff + Claude 已列问题禁止复读）
  - Codex 若抓到 Critical/Important → Claude 修 → **同 threadId `--resume` 复查** → 最多 3 轮收敛
- **必看**：本期 spec + 修改的代码 + `CLAUDE.md § 技术栈陷阱清单` + `docs/agent-rules/codex-division-of-labor.md §4 场景 B`
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

## §3 两个核心 skill 的分工（左右脑）

velo 工作流由两套大脑支撑：

| | 🟦 `architect` | 🟨 `superpowers` |
|---|---|---|
| **定位** | 建筑师大脑（规划 + 审查） | 工程队大脑（执行 + 运行时） |
| **装载内容** | 14 条 velo 私人信条 + 9 步流水线 | 业界通用方法（brainstorm / TDD / worktree / code-review） |
| **用在阶段** | ③④⑤（塑形→spec→计划） | ①⑤后半⑥⑦（脑暴→细化→执行→验证） |
| **特色** | 实战踩坑沉淀，反模式速查 | 不用重造轮子 |

### 重叠点取舍

| 重叠 | architect | superpowers | 用法 |
|---|---|---|---|
| 需求探索 | —— | `brainstorming` | **先发散** |
| 需求塑形 | Step 2 一问一答 | —— | **再收敛** |
| 实施计划 | Step 9 架构骨架 | `writing-plans` 细化 | **串联两个** |
| 代码审查 | 双审判（spec 级）| `requesting-code-review`（代码级）| **两层都用** |

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
| `docs/spec-v1.md` ~ `spec-v4.md` | 每期技术规格（当前最新 v4） | 写代码前 |
| `docs/plans/phaseN/README.md` | 每期施工总调度 | 派 subagent 前 |
| `docs/plans/phaseN/task-N.X.md` | 单任务独立卡片 | subagent 自己读 |
| `docs/architecture-guide.md` | 系统静态全景：7 容器 / 6 模块 / 7 表 | 新人入职 / 加新模块 |
| `docs/data-flow-guide.md` | 9 条数据流动态链路 | 修跨模块 bug |
| `docs/adr/README.md` | 10 份 ADR 总表 + 按场景索引 | 有人提议改决策时 |
| `docs/adr/001-010-*.md` | 单条决策的完整论证 | 需要权威先例时 |
| `docs/dev-guide.md` | 老版员工手册（⚠️ 待评估是否归档） | 历史参考 |

### C. 运行规则（硬约束）

| 路径 | 定位 | 加载时机 |
|---|---|---|
| `/CLAUDE.md`（项目根） | 技术 + 产品硬约束 + 部署清单 + 技术栈陷阱 + 已知风险 | **每次会话常驻** |
| `docs/agent-rules/README.md` | agent 规则体系索引 + ID 命名规范 | 首次加载 |
| `docs/agent-rules/product-decisions.md` | 378 行规则化结论（INV-P01~P06 / D-P01~P10 / 活人感 / 禁止词） | **agent 常驻加载** |
| `docs/agent-rules/velo-mental-model.md` | 756 行思考框架（公司定位 / 画像深描 / 10 问框架） | 复杂决策按需加载 |
| `docs/agent-rules/codex-division-of-labor.md` | Claude ↔ Codex 分工宪章：3 档 / 5 判断法则 / 4 场景 prompt 模板 | 调用 Codex 前按需加载 |

### D. 历史档案

| 路径 | 定位 | 何时读 |
|---|---|---|
| `docs/changelog.md` | 所有改动流水账 | 查"这改动何时合的" |
| `docs/deployment-diary.md` | 部署踩坑笔记 | 部署前 / 踩新坑后追加 |
| `docs/tech-debt.md` | 已知债务清单 | **每期开工前必扫** |
| `docs/handover.md` | 老交接文档（⚠️ 待评估是否归档） | 历史参考 |

### E. 个人与归档

| 路径 | 定位 |
|---|---|
| `docs/learning/VELO学习笔记.docx` | Starsky 的 CS 学习积累 |
| `docs/superpowers/plans/` + `superpowers/specs/` | 旧 superpowers 工作流归档（低频访问） |

---

## §6 文档命名规范

保持整齐，避免"同一件事这期叫 phase4 下期叫 2026-05-01"。

| 类型 | 命名 | 示例 |
|---|---|---|
| 战略 PRD | `docs/prd/velo-{vision/strategy/product-spec}.md` | 固定 3 份 |
| 战术 PRD | `docs/prd/phase-N-prd.md` | `phase-5-prd.md` |
| 技术 Spec | `docs/spec-vN.md` | `spec-v5.md` |
| 实施计划目录 | `docs/plans/phaseN/` | `plans/phase5/` |
| 任务卡 | `docs/plans/phaseN/task-N.X.md` | `plans/phase5/task-8.1.md` |
| ADR | `docs/adr/0XX-为什么{决策}.md` | `adr/011-为什么xxx.md` |
| 竞品分析 | `docs/competitive-analysis/{对手}-对标.md` 或 `-深度解码.md` 或 `-失败模式.md` | 见 §5A |

**老遗产**：第 3 期之前用过日期扁平命名（`2026-04-16-xxx.md`），已归档到 `docs/plans/phase3/`，以后不再用。

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
2. **本文 `docs/README.md`**（你正在看，5 分钟）—— 整体地图 + 工作流
3. **`docs/agent-rules/product-decisions.md`**（agent 专属，5 分钟）—— 产品判断规则
4. **`docs/architecture-guide.md`**（10 分钟速浏）—— 系统静态全景
5. **当前期 `docs/spec-vN.md`**（2 分钟速浏）—— 在做什么

看完这 5 份你就有了**战略 + 规则 + 架构 + 当期**的四视角。

---

## §9 修订记录

- 2026-04-17 初版：5 楼结构 + 9 阶段
- **2026-04-23 v2 重构**：双轨读者分层 + 9 阶段 × 文档 × skill 全景表 + 每阶段执行卡 + 场景速查 + 5 分类目录地图；删除"5 楼办公楼"物理隐喻
- **2026-04-28 v2.1**：撤回"派 codex 写 spec/plans"——§2.1 全景表 ④⑤ 行主导改回主 agent / §2.2 ④⑤ 卡加硬规则行禁派 codex 写正文（chunk by chunk 自己写 → 写完 codex review-only）。理由：codex CLI 长任务卡死 bug 链（#13738/#14048/#18723），实证 spec-v5 卡死 30+ 分钟
