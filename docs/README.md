# VELO 项目文档说明书

> **这份文档给谁看**：你（Starsky）或任何新加入的人，第一眼打开 `docs/` 时用的地图。
>
> **一句话总结**：docs/ 是一栋 5 层办公楼，整个开发流程是 9 阶段流水线。

---

## 📍 先看这里：docs/ 结构地图（5 层办公楼）

```
docs/
│
├── ⸺⸺ 1 楼：永久陈列馆（"这项目是什么"）⸺⸺
│   architecture-guide.md      建筑平面图
│   dev-guide.md               员工手册
│   handover.md                交接文档
│   （CLAUDE.md 住在项目根目录，算 0 楼）
│
├── ⸺⸺ 2 楼：本期设计区（"这期要做啥"）⸺⸺
│   prd/                       产品需求文档（新增）
│   ├── TEMPLATE.md            PRD 空白模板
│   └── phase-N-prd.md         每期一份用户故事 + 验收标准
│
│   spec-v1.md                 第 1 期技术规格
│   spec-v2.md                 第 2 期技术规格
│   spec-v3.md                 第 3 期技术规格
│   spec-v4.md                 第 4 期技术规格（当前）
│
├── ⸺⸺ 3 楼：施工现场（"这期怎么做"）⸺⸺
│   plans/
│   ├── phase3/
│   │   └── README.md          第 3 期施工计划（从老命名归档而来）
│   └── phase4/
│       ├── README.md          第 4 期施工总调度
│       └── task-7.1.md ~ task-7.11.md  每个工人的施工卡
│
├── ⸺⸺ 4 楼：历史档案室（"已经发生过啥"）⸺⸺
│   changelog.md               所有改动的流水账
│   deployment-diary.md        部署踩坑笔记
│
└── ⸺⸺ 5 楼：个人学习室（"我自己成长"）⸺⸺
    learning/
    └── VELO学习笔记.docx      Starsky 的 CS 基础积累
```

---

## 🗺️ 每层给谁看、什么时候看

| 层 | 谁看 | 什么时候看 |
|---|------|----------|
| 1 楼 永久陈列 | 你 + 我 + 新队友 | 项目全程，新人入职先看 |
| **2 楼 本期设计（PRD + Spec）** | **你拍板用** + 我设计用 | 每期**开始前**讨论 |
| **3 楼 施工现场（plans）** | **Agent 执行用** | 每期**执行期间** |
| 4 楼 历史档案 | 翻旧账时 | 查"以前这事怎么处理" |
| 5 楼 个人学习 | 你 | 学 CS 知识 |

**核心洞察**：**你和 Agent 看不同楼层**
- 你看 **2 楼**（PRD + Spec）——策略、why、边界
- Agent 看 **3 楼**（plans）——代码、测试、commit
- 这就是为什么每期要分 3 份文档（PRD + Spec + Plans），合一份就乱了

---

## 🔄 完整开发工作流（9 阶段）

每开一期新功能，按这 9 步走。每步有**指定 skill** 指引——不用每次从零思考：

```
═══════════════════════════════════════════════════════════════
                  一期完整开发流水线（phase N）
═══════════════════════════════════════════════════════════════

① 脑暴探索                 🟨 superpowers:brainstorming      0.5-1 天
   发散 + 跳出本项目框架，挖掘真实 intent
   无文档产出，只是开放讨论
                        ↓
② 📝 PRD（产品需求）       你主导（用 docs/prd/TEMPLATE.md）  1-2 天
   用户故事 + 验收标准 + 优先级 + 明确不做什么
   产出：docs/prd/phase-N-prd.md
                        ↓
③ 需求塑形 + 技术讨论      🟦 architect Step 1-3              0.5-1 天
   基于 PRD 收敛到可执行的技术方向
                        ↓
④ 📝 Spec 撰写            🟦 architect Step 4-8              1-2 天
   分段设计 + 故障分析 + 双审判 + 你审阅
   产出：docs/spec-vN.md（Critical=0）
                        ↓
⑤ 📝 实施计划             🟦 architect Step 9（架构）        0.5-1 天
                          🟨 superpowers:writing-plans（细化）
   产出：docs/plans/phaseN/README.md + task-N.X.md
                        ↓
⑥ 并行执行                🟨 superpowers:subagent-driven     3-10 天
                          🟨 using-git-worktrees
                          🟨 dispatching-parallel-agents
                          🟨 test-driven-development
   产出：代码 + 单测 + commits
                        ↓
⑦ 集成验证 + 代码审查     🟨 verification-before-completion  1-2 天
                          🟨 requesting-code-review
                          🟨 receiving-code-review
                        ↓
⑧ 部署上线                🟩 deploy skill                    0.5 天
   按 CLAUDE.md 部署前检查清单走
                        ↓
⑨ 复盘归档                CLAUDE.md 防黑盒化机制              0.5 天
   刷新 architecture-guide + changelog + deployment-diary
   回答黑盒度体检三问
        ↓
   ────── 下一期从 ① 重新开始 ──────
```

---

## 🧠 两个核心 skill 的分工（左右脑）

### 🟦 architect = 建筑师的大脑（规划 + 审查）

**用在阶段 ③④⑤ 前半（技术讨论 → Spec → 实施计划架构）**

内容：
- 14 条核心信条（怀疑优先 / 故障思维 / 独立判断 / 证据分级 等）
- 9 步流水线（上下文 → 需求塑形 → 架构方案 → 分段 → 故障 → Spec → 双审 → 审阅 → 实施计划）
- 反模式速查表

**优势**：装载项目私人定制经验（14 条信条来自我们实战踩坑）。

### 🟨 superpowers = 工程队的大脑（执行 + 运行时）

**用在阶段 ①⑤ 后半⑥⑦（脑暴 → 实施细化 → 执行 → 验证）**

内容：
- brainstorming：发散探索
- writing-plans / executing-plans：实施计划
- subagent-driven-development / dispatching-parallel-agents：并行执行
- test-driven-development：TDD 纪律
- verification-before-completion：完成前验证
- requesting / receiving-code-review：代码审查
- using-git-worktrees：分支隔离
- systematic-debugging：调试

**优势**：业界通用实战方法，不用重造轮子。

### 重叠点取舍

| 重叠概念 | architect | superpowers | 用法 |
|---------|-----------|-------------|------|
| 需求探索 | —— | brainstorming | **先发散** |
| 需求塑形 | Step 2 一问一答 | —— | **再收敛** |
| 实施计划 | Step 9 架构 | writing-plans 细化 | **两个串联** |
| 代码审查 | 双重审判（spec 级）| requesting-code-review（代码级）| **两层都用** |

---

## 📋 文档命名规范

保持整齐，避免"同一个东西这期叫 phase4 下期叫 2026-05-01"。

| 类型 | 命名 | 示例 |
|------|------|------|
| PRD | `docs/prd/phase-N-prd.md` | `docs/prd/phase-4-prd.md` |
| Spec | `docs/spec-vN.md` | `docs/spec-v4.md` |
| 实施计划目录 | `docs/plans/phaseN/` | `docs/plans/phase4/` |
| 实施主文档 | `docs/plans/phaseN/README.md` | `docs/plans/phase4/README.md` |
| 任务卡片 | `docs/plans/phaseN/task-N.X.md` | `docs/plans/phase4/task-7.1.md` |

**老遗产**：第 3 期之前的文件用了日期扁平命名（`2026-04-16-xxx.md`）——已归档到 `docs/plans/phase3/`，以后不再用这种命名。

---

## 🚀 新人入职 / 新 Agent 上岗第一天看什么

按顺序（15 分钟搞懂项目全貌）：

1. **`CLAUDE.md`**（项目根，5 分钟）——硬规则 + 团队文化
2. **本文件 `docs/README.md`**（你正在看的，3 分钟）——整体地图
3. **`docs/architecture-guide.md`**（5 分钟）——系统架构全景
4. **当前期 `docs/spec-v{最新版}.md`**（2 分钟速浏）——在做什么

看完这 4 份你就有了宏观和微观的**双视角**。

---

## 🔗 各文档之间的信息流

单向从抽象到具体：

```
脑暴    →  PRD       →  Spec      →  Plans      →  代码 + 部署
(思考)  (产品视角)  (技术视角)  (执行视角)  (真实世界)

每一步的产出 = 下一步的输入
没有双向依赖、没有循环
```

---

## ✍️ 修订这份 README 的时机

这份是**活文档**。什么时候改：

- 新增了一种文档类型（比如以后加 `docs/postmortem/` 事故复盘）
- 调整了工作流阶段（比如觉得 9 阶段要变 10 阶段）
- 引入了新 skill（整合进阶段图）

**不要让这份过时**——过时文档比没文档更坑（会骗人）。每期收尾时的"防黑盒化体检"里包含"看一眼这份 README 是否还准确"。

---

## 📚 修订记录

- 2026-04-17：初版，建立 5 楼结构 + 9 阶段工作流 + 两 skill 分工
