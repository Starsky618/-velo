# task skill spec（给 codex-skill-creator 的设计 brief）

> **本文件性质**：task skill 的设计意图、触发条件、5-phase SOP、测试场景的完整 spec。
> **目标读者**：codex-skill-creator（Codex 端 skill / 用它生成 ~/.codex/skills/task/SKILL.md）。
> **作者**：Claude + Tim 共写（2026-05-24 session 沉淀）/ 单一真相源。
> **下游**：Tim 在 Codex Desktop / CLI 调 codex-skill-creator + 喂这份 spec → 跑 Capture Intent / Interview / Draft / Eval / Iterate → 输出 SKILL.md + evals。

---

## 0. Why this skill exists（设计动机 / 元 context）

### 0.1 Tim persona 适配

- Tim 是产品架构师 / 不是程序员（自述 §1.2 §2.3）
- 强项：产品判断 / 业务逻辑拆解 / 架构设计完善
- 弱项：写 well-framed ticket 的工程化字段（Context / Done when 具体技术细节）
- 工作流：50%+ prompt 是模糊意图（"帮我优化 X" / "做个 Y" / "搞定 Z"）

→ Codex 第一性原理（"Best used when the ticket is already well-framed"）天然跟 Tim persona 错位。task skill = 弥合这个错位的桥梁。

### 0.2 Spec-Driven Development（业界 2026 标准）

- **Specify → Plan → Task → Execute**（业界 4 步 SDD）
- 在 Tim 场景里加 **Verify**（external source of truth / red-to-green）= 5 phase

引用：[Spec-Driven Development with AI Coding Agents - Medium](https://medium.com/predict/spec-driven-development-with-ai-coding-agents-the-definitive-guide-453fba1baf39)

### 0.3 Codex 官方原则（WebFetch 2026-05-24 实证）

- **Well-framed ticket 4 字段**：Goal / Context / Constraints / Done when
- **Reasoning levels**：Low / Medium / High / Extra High
- **Subagent fan-out/fan-in**：复杂任务并行拆 subagent
- **Project Manager gating**：subagent 之间 handoff 必须 gate
- **Context hygiene**：one coherent unit of work per thread
- **External source of truth**：测试 > Codex 自我判断

源：[Best practices – Codex | OpenAI Developers](https://developers.openai.com/codex/learn/best-practices) + [Subagents – Codex](https://developers.openai.com/codex/subagents)

### 0.4 七镜框架对齐（Tim §1.6）

- **模块价值 = 可替换性 + 接口面积最小化**：task skill 跟 hook / AGENTS.md 接口面积小 / 各管各
- **被约束下涌现的秩序**：把模糊 prompt 收紧到 well-framed ticket 集合 = Tim 创作母题
- **AI 时代人类价值在判断层 / 不在翻译层**：task skill 帮 Tim 在判断层 / 翻译层全交 skill

---

## 1. Identity（skill 身份）

### 1.1 Name

```
task
```

理由：

- 短 / 易记 / 跟 architect / neat-freak 同级简洁
- 涵盖完整 5 phase（Specify + Plan + Task + Execute + Verify）/ 不只 decomposition
- `task-decomposition` 只描述 Phase 3 / 不准

### 1.2 Description（按 architect skill 风格 + superpowers 1% 哲学）

```yaml
---
name: task
description: |
  Use this skill ALWAYS when handling any task with even 1% ambiguity. 
  It walks a 5-phase pipeline (Specify → Plan → Task → Execute → Verify) 
  that turns vague intent into well-framed tickets and executable subagent 
  workflows. Designed for product architects / non-programmers who can 
  define product goals but not engineering tickets.

  TRIGGER GENEROUSLY. When in doubt, invoke. Specifically trigger when:
  - User prompt contains vague Chinese phrases: "帮我优化 / 搞定 / 弄一下 / 实现一下 / 改一下 / 做个 X / 推一下 / 上线 X"
  - User prompt contains vague English phrases: "optimize / improve / clean up / handle / take care of / make it work / ship X"
  - Prompt missing any of 4 well-framed fields (Goal / Context / Constraints / Done when)
  - User describes a problem rather than a solution (e.g., "首页慢" without spec)
  - Task crosses 2+ modules or touches core schema
  - User asks "what's next" / "下一步做什么" / "接下来推什么" without specifying which module
  - User mentions a project component name (e.g., "strava / parsing / user / PMC / FTP") without Goal-level detail
  - You'd otherwise need to "guess at intent" before apply_patch / Bash / file edits

  Do NOT skip because:
  - The conversation "feels casual" or user says "随便做下"
  - You think you understand the user's intent without verification
  - The task "seems small" — small tasks with wrong scope waste more time than walking 5 phase

  Only skip when:
  - Ticket is unambiguously well-framed by 4 fields (Goal/Context/Constraints/Done when 全齐)
  - User explicitly says "skip task / go directly / 直接干 / 别拆"
  - Task is trivial lookup (what does this function do / 这文件在哪)
  - Continuing previously-decomposed work (mid-Phase 4 execution)

  The cost of invoking when not needed is low (5 minutes overhead).
  The cost of skipping when needed is high (wrong scope / Tim 不满 / 返工).
---
```

**关键设计**：

- 长 description 跟 architect 同级（~30 行）/ 不简短
- 含中英双语触发词
- "TRIGGER GENEROUSLY" + "When in doubt, invoke"（superpowers 风格）
- "Do NOT skip because..." 反命中清单
- "Only skip when..." 明确豁免
- 末尾"cost asymmetry" 解释（为什么默认调）

---

## 2. Triggers / Anti-triggers（完整触发条件）

### 2.1 Active Triggers（命中即调用）

**Vague phrase library**（已实证 Tim 高频用语）：

| 中文 | 英文 |
|---|---|
| 帮我优化 / 优化一下 | optimize / improve |
| 搞定 / 搞定它 | take care of / handle |
| 弄一下 / 弄个 | get it done / make it work |
| 实现一下 / 做个 / 写个 | implement / build / make |
| 改一下 / 调一下 | tweak / adjust |
| 推一下 / 推进 | push forward / advance |
| 下一步 / 接下来 | what's next / next up |
| 解决 / 处理 | resolve / fix（无具体描述时）|

**Well-framed missing fields**：

- Goal 缺 → "你想达到什么效果"
- Context 缺 → "动哪些文件 / 模块"
- Constraints 缺 → "不能动什么 / 兼容性要求"
- Done when 缺 → "怎么证明做对了"

**Module-level vagueness**（用户提了模块名但没具体 Goal）：

- "strava 怎么样了"
- "user 模块需要改"
- "PMC 那个东西"

### 2.2 Anti-triggers（命中不调用 / 直接执行）

- 已经 well-framed 的 5 字段 ticket（Goal/Context/Constraints/Done when + 项目级 Fallback）
- 显式跳过指令："直接干" / "不要拆" / "skip task"
- 单文件 trivial 查询："这文件在哪" / "function X 做啥"
- 继续之前已拆解的工作（mid Phase 4 状态恢复）

### 2.3 Edge cases

- **Tim 说"我想做 X 但不知道怎么开始"** → 命中 trigger（典型模糊意图）
- **Tim 喂完整 ticket 但用模糊语调** → 优先识别字段完整性 / 字段全 = 不调
- **Tim 在 brainstorm 阶段问 Codex 想法** → 不调 / 反向建议"这是 brainstorm / 找 Claude"

---

## 3. Body Structure（5 phases 完整 SOP）

### Phase 1 · Specify（问题界定）

**入条件**：从 trigger 进入。

**核心动作**：

1. **解析表层 vs 真问题**（归因精准 / Tim §1.1 思维方法）
   - 用户说"X 慢" → 真问题是 LCP / FCP / TTFB / 首屏渲染？
   - 用户说"X 不对" → 真问题是数据错 / 状态机错 / 显示错？
   - 不在表层动手

2. **识别问题域**（按项目约定 / 不需要 project.yml）
   - 根目录 Read CLAUDE.md / AGENTS.md（约定 · 几乎所有项目都有）
   - 找架构文档：`docs/architecture-guide.md` / `docs/ARCHITECTURE.md` / `README.md`
   - 找数据流文档：`docs/data-flow-guide.md` / `docs/dataflow.md`
   - 没找到 → Phase 1 报告 "项目缺架构文档 / 建议补 / 我先用 grep 探索"

3. **拿模块边界**
   - ls 项目模块根目录（`app/` / `src/` / `lib/` 按约定）
   - Read 影响模块的 `__init__.py` docstring / `README.md`

4. **找已知约束**（forbidden actions）
   - CLAUDE.md / AGENTS.md / docs/agent-rules/
   - 项目 tech-debt（`docs/tech-debt.md`）
   - 项目级反指标（如 velo §10.Y / 核心 4 表禁动）

5. **定义验收**（external source of truth）
   - 测试命令模板（pytest / npm test / 等）
   - 量化 metric（如 Lighthouse score / pytest pass / curl 200）
   - 用户可验证条件（"我打开页面看到 X")

**Gating 出条件**：

- 必须输出"Phase 1 报告"给用户审：
  ```
  # Phase 1 报告 · Specify

  ## 表层 vs 真问题
  你说："X"
  真问题（我归因）：Y / 因为 ...

  ## 问题域
  涉及模块：A / B / C
  数据流链路：...
  影响范围：[文件清单 file:line]

  ## 已知约束
  - 不能动：[列表 + 来源 file:line]
  - 已踩坑：[tech-debt 相关项]

  ## 验收
  目标：[量化 metric]
  命令：[pytest / curl / 等]

  ## 我需要你确认的
  1. 我的归因对吗？
  2. 影响范围有遗漏吗？
  3. 验收标准 ok 吗？
  ```

- **必须 Tim approve 才能进 Phase 2**（gate）

**反指标 / push back**：

- 找不到任何架构文档 → 报告"项目结构不清 / 建议先补架构文档 / 或我用 grep 探索（慢 + 可能漏）"
- 用户连 Goal 都说不清（连"X 慢"都没具体 metric）→ 反向建议"这是 brainstorm 阶段 / 找 Claude / 我接 well-framed ticket"

### Phase 2 · Plan（技术建模）

**入条件**：Phase 1 报告通过 Tim approve。

**核心动作**：

1. **画 current state → target state**
   - 当前是什么样：state diagram / data flow / API contract
   - 目标是什么样：同维度对比

2. **identify transitions + dependencies**
   - 从 current 到 target 中间要经过哪些 transition
   - 每个 transition 依赖什么前置条件
   - 拓扑排序（哪些必须串行 / 哪些可并行）

3. **风险识别**（故障思维 / Tim 七镜 §1.6 信条 2）
   - 哪些 transition 跨模块 / 不可逆 / 影响核心 schema
   - 状态机有没有非法转换
   - 并发场景（race / 重入 / 重试）
   - 边界情况（NULL / 0 / 极端值 / truthiness 陷阱）

4. **路由决策**（§10.Y 双主驾分工应用）
   - 哪些子任务我（Codex）直接干？
   - 哪些命中 §10.Y 反指标 → 反向派 Claude？
   - 哪些需要 Tim 拍板（产品 / 架构决策）？

**Gating 出条件**：

- 输出"Phase 2 路由方案"给 Tim 审：
  ```
  # Phase 2 报告 · Plan

  ## 状态变化
  当前：...
  目标：...

  ## 中间 transitions
  T1: [描述] · [依赖: 无] · [风险: 低]
  T2: [描述] · [依赖: T1] · [风险: 中 / 跨模块]
  T3: [描述] · [依赖: T1, T2] · [风险: 高 / 改核心表]

  ## 路由方案
  - T1 → 我（Codex）直接干（低风险 / 单模块）
  - T2 → 我（Codex）干 + Claude 异源审（跨模块）
  - T3 → 反向派 Claude（命中反指标 / 改核心表）
  - 你拍板的事：[列表]

  ## 风险清单
  - [风险描述] · [缓解方案]
  ```

- **必须 Tim approve 路由 + 风险** 才能进 Phase 3

**反指标 / push back**：

- 80%+ transition 命中 §10.Y 反指标 → 反向建议"这任务不适合派 Codex 主干 / 建议 Claude 主开发"
- 风险评估发现核心架构问题 → 反向建议"这不是实施层任务 / 是架构决策 / 找 Claude architect skill"

### Phase 3 · Task（拆 self-contained subtasks）

**入条件**：Phase 2 路由通过 Tim approve。

**核心动作**：

1. **compound task → primitive subtasks**
   - 按 SDD 方法 / 一个 transition 切成 N 个 self-contained subtask
   - 每个 subtask 满足：
     - **self-contained**：独立可跑 / 不依赖其他 subtask 中间状态
     - **well-framed**：4 字段（Goal / Context / Constraints / Done when）完整
     - **right-sized**：≤ 半天工作量 / 单 thread context 装得下

2. **写 well-framed ticket**（每 subtask）
   ```
   ## Subtask N: [简短描述]

   - **Goal**: [一句话 / 完成后能看到什么]
   - **Context**: [file:line 实证 / 涉及哪些代码]
   - **Constraints**: [不能动 / 必须保持 / 约束列表]
   - **Done when**: [可机器验证的条件 / 跑什么命令]
   - **Fallback**: [失败时停 / 还是继续 / 重试几次]
   ```

3. **拓扑排序**
   - 标依赖关系（DAG / 不能有环）
   - 决定串行 vs 并行（subagent fan-out 机会）

4. **写并行/串行执行图**
   ```
   Subtask 1 (Codex)
       ↓
   ┌─ Subtask 2a (Codex / 并行 1)
   ├─ Subtask 2b (Codex / 并行 2)
   └─ Subtask 2c (反向派 Claude / 异源审)
       ↓ (fan-in)
   Subtask 3 (Codex / 等前面都好)
       ↓
   Verify (Phase 5)
   ```

**Gating 出条件**：

- 输出"Phase 3 任务清单"给 Tim 审：
  - N 个 well-framed subtask 列表
  - 执行图（DAG / 并行机会）
  - 每个 subtask 路由 + 预估时间

- **Tim approve 任务清单 + 路由** 才能进 Phase 4

**反指标 / push back**：

- 任一 subtask 4 字段补不齐 → 回到 Phase 1 / 补 Specify
- subtask 数量 > 10 个 → 警告"这任务太大 / 建议拆 mini-sprint / 不是单 task skill"

### Phase 4 · Execute（编排执行）

**入条件**：Phase 3 任务清单通过 Tim approve。

**核心动作**：

1. **按 DAG 执行**
   - 串行 subtask：一个跑完跑下一个
   - 并行 subtask：spawn_subagent fan-out / 每个 subagent isolated context
   - 反向派 Claude 的 subtask：输出 well-framed prompt / 等 Tim 触发

2. **Project Manager gating**
   - 每个 subtask 完成 → 跑 Done when 验收命令
   - 验收通过 → handoff 下一个 subtask
   - 验收失败 → 升档 reasoning level / 或 push back / 或反向派

3. **Context hygiene**
   - "one coherent unit of work per thread"
   - 不让多个 subtask 串味 / 每个 subagent 独立 context
   - 主线程只汇总结果 / 不堆每个 subtask 的执行细节

4. **失败兜底**
   - subtask 失败 → 主线程判断：重试 / 升档 / 反向派 / 报告 Tim
   - 3 次失败后强制停 / 不死循环

**Gating 出条件**：

- 每 subtask 完成产出：
  - diff / 改动文件清单
  - 验收命令输出
  - 用 token / 用时

- 全部 subtask 完成 → 进 Phase 5

**反指标 / push back**：

- 任一 subtask 跑出 scope（改动超出 Constraints 范围）→ 停下 / 报告 Tim
- 跨 subtask 数据冲突（如 subtask A 改了 subtask B 假设的 schema）→ 停下 / 升档为架构决策 / 反向派 Claude

### Phase 5 · Verify（验证）

**入条件**：Phase 4 全部 subtask 完成。

**核心动作**：

1. **跑 Phase 1 定义的整体 Done when**
   - 不只是单 subtask 验收 / 是整任务的 external truth check
   - pytest / curl / Lighthouse / 用户可见行为

2. **跨 subtask 一致性检查**
   - subtask A 改了 schema / subtask B 用新 schema 兼容吗？
   - subtask 之间接口契约保持？

3. **异源 review**
   - 自己跑 `/review` 命令（base branch / uncommitted）
   - 或反向派 Claude code-reviewer / integration-reviewer subagent
   - red-to-green cycle 直到所有 assertion 全绿

4. **总结报告给 Tim**
   ```
   # Phase 5 报告 · Verify

   ## 整体目标
   [Phase 1 Goal]

   ## 验收结果
   - Done when 1: ✓ pytest passed (12/12)
   - Done when 2: ✓ curl /api/X returned 200
   - Done when 3: ✓ Lighthouse score 85+ (was 60)

   ## 改动汇总
   - 文件数：12
   - 净增行：+340 / -89
   - commit 候选：[列表]

   ## 异源 review 结果
   - Critical: 0
   - Important: 1 (已修)
   - Minor: 2 (建议入 tech-debt)

   ## 你需要拍板的
   - commit 信息 ok 吗？
   - Minor 入 tech-debt 还是修了再 commit？
   - 需要部署吗？（按项目部署 SOP）
   ```

**Gating 出条件**：

- 验收全绿 + Tim approve 报告 → 进入 commit / ship
- 验收有 Critical 失败 → 回 Phase 3 重切分 subtask / 不强 commit

---

## 4. Interface Contracts（与外部协作）

### 4.1 与 ~/.codex/AGENTS.md 的关系

- AGENTS.md 是触发本 skill 的"上游入口"
- AGENTS.md § 6 应有 trigger 规则：「接到模糊任务 / 复杂任务 / 跨模块改动 → 必须调 task skill」
- skill 内不复述 AGENTS.md 规则 / 只引用

### 4.2 与 hook（UserPromptSubmit）的关系

- Hook 不是必须 / skill 可以自我触发
- 但 velo 项目级 hook 4 通道（路由 / 模块 / PRD / SOP）会注入相关 context
- skill 启动时 Phase 1 应该利用 hook 已注入的 context（不重复 Read）

### 4.3 与 Claude 的反向接口

- Claude 不装本 skill（按 Tim 模块化原则 / Claude 端有 brainstorming + architect 替代）
- 本 skill 在 Phase 2 / Phase 3 / Phase 5 都可能反向派 Claude
- 反向派接口 = well-framed prompt（含 5 字段 + 上下文）+ 期望输出格式

### 4.4 与 superpowers skill 的关系

Codex 端如果装了 superpowers skills（如 `verification-before-completion` / `test-driven-development`）/ 本 skill 应在合适 phase 调用：

- Phase 4 Execute 时 → 调 `test-driven-development`（如果有测试驱动需求）
- Phase 5 Verify 时 → 调 `verification-before-completion`（claim 完成前必跑验证命令）

不重复实现 / 引用调用。

### 4.5 跨项目复用（约定大于配置）

本 skill 适用 Tim 所有未来项目 / 跨项目工作的轻约定：

- 项目根有 `CLAUDE.md` 或 `AGENTS.md`（Codex 启动自动加载）
- 项目根有 `README.md`（fallback）
- 架构文档在 `docs/`（候选名：`architecture-guide.md` / `ARCHITECTURE.md` / `data-flow-guide.md` / `dataflow.md`）
- 模块根在 `app/` 或 `src/` 或 `lib/` / 每个模块有 `__init__.py` 或 `README.md`
- 测试命令在项目 README 或 package.json scripts / pyproject.toml

→ 项目不满足约定 → skill Phase 1 报告"项目结构不清 / 建议补 X" / 不死锁。

---

## 5. Edge Cases / Failure Modes（边界条件）

### 5.1 跨 phase 失败处理

- Phase 1 卡住（找不到架构文档 + 用户也不补）→ 反向建议 brainstorm
- Phase 2 风险评估发现核心架构问题 → 反向派 Claude architect skill
- Phase 3 subtask > 10 → 拆 mini-sprint / 不在单 task 内做
- Phase 4 subtask 跑出 scope → 停 + 报告 Tim
- Phase 5 verify 失败 → 回 Phase 3 重切分

### 5.2 与 §10.Y 反指标的冲突

- 80%+ subtask 命中反指标 → 整任务反向派 Claude（不是 task skill 适合）
- 单个 subtask 命中反指标 → 该 subtask 反向派 / 其他继续

### 5.3 reasoning level 升档

- Low 跑不动 → 升 Medium
- Medium 跑不动 → 升 High
- High 跑不动 → 升 Extra High
- Extra High 还不动 → 反向派 Claude / 不死撑

---

## 6. Walkthrough Examples（真实场景）

### Example A · Sprint 10 PMC 训练负荷（典型模糊任务）

**Tim 输入**：
```
我想做 sprint 10 PMC 训练负荷
```

**skill 触发判断**：
- 命中 "做" + 模块名 "PMC" / 没 Goal-level detail
- 触发 task skill

**Phase 1 Specify**：
- Read velo 根 CLAUDE.md / AGENTS.md
- Read `docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md`（hook 通道 3 已注入）
- 拿模块边界：`app/activity/` / `app/user/`
- 找约束：CLAUDE.md "🛡 防火墙式扩展" / 不动核心表
- 表层 vs 真问题：用户说"做 PMC" / 真问题是"加哪些字段 + UI / 是装饰还是指导（Tim 装饰指导分原则 / Persona 教训）"

**Phase 1 报告给 Tim**：
```
## 真问题
PMC 是装饰展示还是主动指导？（Persona 教训）
- 装饰：activity detail 卡多个数字 → 用户看一眼 → 没行为变化
- 指导：CTL 太高时主动弹"建议休息" → 改变用户行为
你拍方向。

## 影响范围
- app/activity/ 加 3 字段（CTL / ATL / TSB）
- app/user/me 加聚合 endpoint
- 前端 detail 加显示卡

## 验收
- pytest test_pmc_calculator
- 真用回归：你看 1 周 PMC 曲线 / 有没有"行为变化触发点"

## 我需要你确认
1. 装饰 vs 指导？（决定 scope 翻 3 倍 / 跟你说战略）
2. 影响范围对吗？
```

**Tim 拍**：「指导 / 但 v1 先做装饰展示 / 等用户用了再加指导」

**Phase 2 Plan**：
- Current: 没 PMC
- Target: 3 字段入库 + detail 显示 + 1 周回归验证
- Transitions: T1 加字段 / T2 计算 worker / T3 detail 显示
- Routing: T1 + T3 → Codex（清晰 / 可测）/ T2 算法逻辑 → 派 Codex + Claude 异源审
- Risk: 算法错算（如 ftp_estimator 教训）→ verify 必须真实数据

**Phase 3 Task**：拆 4-5 subtask（每个 well-framed）

**Phase 4 Execute**：subagent fan-out + Project Manager gating

**Phase 5 Verify**：跑全套测试 + 真用回归

→ Tim 体验：6 句话（"我想做 PMC" / 拍方向 / approve Phase 1-3 各次 / approve Phase 5 报告）/ 完成整 sprint。

### Example B · 接 Garmin API（清晰技术任务）

**Tim 输入**：
```
按 dev-guide-demo Tab 3 扩展沙盘 / 接 Garmin Connect API / 走 OAuth 路径
```

**skill 触发判断**：
- Tim 已经指定 "走 OAuth 路径" → 部分 well-framed
- 但 Context / Done when 缺 → 命中触发

**Phase 1 Specify**：
- Read `app/strava/__init__.py`（hook 通道 2 已注入 / 直接拿）
- Read `docs/architecture-guide.md` 第三方集成章节
- 真问题：仿 strava 结构建 `app/garmin/` + parsing/garmin_adapter.py
- 已知约束：parsing/ 是纯函数 / save_parse_result 共享函数

**Phase 1 报告极简**：
```
## 真问题
仿 strava 路径接 Garmin（参考 dev-guide-demo Tab 3）

## 影响范围
- 新建 app/garmin/（仿 strava 11 文件结构）
- 新建 parsing/garmin_adapter.py
- 新建 2 张表（garmin_imports + garmin_tokens）
- 前端 profile 加"绑定 Garmin"按钮

## 验收
- pytest test_garmin_oauth
- 真机：在小程序绑定 Garmin → 同步活动出现

## 确认？
```

**Phase 2-5** 类似 strava 模式 / 详略。

### Example C · NON-trigger（不该调用）

**Tim 输入**：
```
跑 pytest tests/test_strava_webhook.py 看通不通
```

**skill 触发判断**：
- Goal 清楚（跑测试）
- Context 清楚（具体文件）
- Constraints 隐含（不改任何代码）
- Done when 隐含（pytest 退出码）

→ 已完整 well-framed / **不调用 skill** / 直接执行。

---

## 7. Test Cases（给 codex-skill-creator eval 用）

按 codex-skill-creator 标准 `evals/evals.json` 格式：

```json
{
  "skill_name": "task",
  "evals": [
    {
      "id": 1,
      "prompt": "帮我优化一下首页加载速度",
      "expected_output": "Skill triggers. Phase 1 asks: which metric (LCP/FCP/TTFB)? which page (home/detail/profile)? current vs target value? how to measure (Lighthouse/custom)?",
      "test_type": "vague-trigger"
    },
    {
      "id": 2,
      "prompt": "我想做 sprint 10 PMC 训练负荷",
      "expected_output": "Skill triggers. Phase 1 reads training-analytics-roadmap.md and asks Tim: 装饰 vs 指导? Persona lesson reference. Then proceeds.",
      "test_type": "module-name-trigger"
    },
    {
      "id": 3,
      "prompt": "把 app/strava/service_token.py:71 的 bound 字段加日志输出 / 不改任何业务逻辑 / 跑 pytest tests/test_strava_token.py 验证不破坏现有测试",
      "expected_output": "Skill does NOT trigger (already well-framed). Direct execution.",
      "test_type": "well-framed-no-trigger"
    },
    {
      "id": 4,
      "prompt": "下一步推什么",
      "expected_output": "Skill triggers. Reverse-suggests brainstorming with Claude (Goal 都没 / 不是 task skill 适合)",
      "test_type": "brainstorm-reverse-suggest"
    },
    {
      "id": 5,
      "prompt": "改一下 user 模块的 ftp 字段命名",
      "expected_output": "Skill triggers. Phase 1 reads app/user/__init__.py + grep ftp usage. Reports impact range (X callers / Y tests). Asks Tim to confirm rename scope.",
      "test_type": "rename-decomposition"
    }
  ]
}
```

**Assertions**（每个测试的判分点）：

- Test 1: 检查是否问 metric / 是否问 measurement tool
- Test 2: 检查是否引用 Persona 教训 / 是否问装饰 vs 指导
- Test 3: 检查是否直接执行 / 不进 Phase 1（false trigger）
- Test 4: 检查是否反向建议 Claude
- Test 5: 检查是否做影响范围分析 / 是否问 rename scope

---

## 8. 为 codex-skill-creator 的 Interview 阶段预先回答

按 codex-skill-creator SOP："1. What should this skill enable? 2. When should this skill trigger? 3. Output format? 4. Test cases?"

### 8.1 What should this skill enable

让 Codex 在 Tim 模糊任务时不擅自动手 / 而是按 5-phase pipeline 把模糊翻译成 well-framed ticket 集合 + 执行图 / 然后按 Tim approve 后执行。

让 Tim 的"产品架构师 persona"（强项是判断 / 弱项是工程化 ticket）能用 Codex / 不被卡在 well-framed gate。

### 8.2 When should this skill trigger

见 §2 Triggers 完整列表 + §1.2 description（已 pushy）。

### 8.3 Output format

每 phase 输出标准化 markdown 报告（见 §3 各 phase Gating 出条件）。

最终输出：

- 完整 5-phase 报告链
- N 个 well-framed subtask + 执行图
- 验收结果 + commit 候选 + Tim 拍板项

### 8.4 Test cases

见 §7（5 个测试场景 / 含 trigger / non-trigger / reverse-suggest 三类）。

### 8.5 Should we set up test cases

**Yes**。task skill 输出可机器验证（trigger 准确率 / phase 完成率 / Tim approve 率）→ 建议 codex-skill-creator 跑评估迭代。

---

## 9. Iteration plan（给 codex-skill-creator 的迭代建议）

1. **第 1 轮**：按本 spec 写 draft SKILL.md / 跑 5 测试场景 / 看触发率
2. **第 2 轮**：跑 `improve_description.py` 优化 description / 再测
3. **第 3 轮**：Tim 真实使用 Sprint 10 PMC 当 dry-run / 看哪 phase 卡 / 迭代
4. **稳定后**：写进 `~/.codex/skills/task/SKILL.md` / 推荐 description 进 architect 同级稳定

---

## 10. Meta-context for codex-skill-creator（设计哲学）

### 10.1 这 skill 跟 architect 的关系

- architect = Claude 端 + 设计阶段（spec / plan 写作）
- task = Codex 端 + 实施阶段（拆解 + 执行 + verify）
- **接口**：architect 输出 plans/phaseN/ → task 接到执行（按现有 9 阶段工作流）

但 task 是给 **Tim 直接派 Codex** 场景设计的 / 跳过 architect / Codex 自己拆。

### 10.2 这 skill 跟 superpowers brainstorming 的区别

- brainstorming = 发散（多方案对比 / Claude 端）
- task = 收敛（模糊 → well-framed / Codex 端）

Tim 真模糊（连 Goal 都不清） → brainstorming（Claude）
Tim 有 Goal 但工程化 ticket 不齐 → task（Codex）

### 10.3 这 skill 的元价值

不是"另一个 SOP" / 是 **跨 project 的 cross-tooling pattern**：

- 适用 Tim 所有未来项目（约定大于配置）
- 适用 Codex 所有 reasoning levels
- 适用单人 + 双主驾两种工作流

---

## 附录 A · 给 codex-skill-creator 的最终一段话

按你（codex-skill-creator）的 SOP / 请：

1. **Capture Intent** ✓（本 spec 已 capture）
2. **Interview**：本 spec § 8 已预先回答 / 但请仍跑一遍 Interview 确认 / 如有补充问 Tim
3. **Research**：参考 §0 引用的 Spec-Driven Development + Codex 官方文档（已 WebFetch 实证 / file:line）
4. **Draft SKILL.md**：按本 spec 各章节生成 / 但**不要照搬** / 按你的写作规范（imperative / theory of mind / 解释 why / 不 narrow-example）写
5. **Test cases**：按 §7 evals.json 格式 / 跑 with-skill + baseline 对照
6. **Iterate**：按 §9 计划 / 跑 `improve_description.py` 优化 description
7. **最终位置**：`~/.codex/skills/task/SKILL.md`（用户全局 / 跨项目复用）

我（Claude）已经退场。后续由你（codex-skill-creator）跟 Tim 直接对接。

---

## 附录 B · 已知漏洞 / 待 codex-skill-creator 补全

1. **Phase 1 fallback grep 策略**：项目没架构文档时 / 怎么用 grep 探索 / 探索深度 / 报告格式
2. **subagent fan-out 上限**：单次 Phase 4 最多 spawn 几个 subagent / 防 context 爆炸
3. **reasoning level 升档判断**：什么信号触发升档 / 阈值
4. **跨 session 中断恢复**：Phase 3 拆完 / Tim 切走 / 下次怎么恢复 mid-phase 状态

这些请在 Interview / Draft 阶段补完。

---

**spec 版本**：v1.0
**日期**：2026-05-24
**作者**：Claude（基于 Tim × Claude 2026-05-24 session 沉淀）
**下游**：Codex × codex-skill-creator
