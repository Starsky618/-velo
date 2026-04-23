# Claude ↔ Codex 分工宪章

> **一句话**：Claude 贵 + 宏观强，Codex 便宜 + 细致强——按工作性质分配，不一刀切。
>
> **适用**：velo 项目在 Claude Code 会话内调用 Codex（codex:codex-rescue subagent）完成细节类工作。
>
> **读者**：本文主要给 agent 读（规则 + 判断框架 + prompt 模板），但人类也能快速扫清档位和场景。

---

## §1 为什么要分工

### 两个极端都不行

**全 Claude**：贵。每一行小代码都走 1M 上下文 Opus，成本爆炸。细节活（写测试 / 扫陷阱清单 / 修 typo）其实不需要 Claude 的架构洞察。

**全 Codex**：盲区。v4 task-7.10 实证——Codex 第一轮审查没抓到 C1（leaderboard onLoad 读 query 参数），这条 Critical 是 Claude 集成审抓到的。**Codex 擅长微观细致，Claude 擅长宏观集成**，两种视角互补。

### 目标：把判断规则化，不凭感觉

每次遇到"这个小活谁做"就讨论一次 = 浪费时间。**本宪章决定谁做什么，Claude 按规则直接路由。**

---

## §2 三档分工清单（核心表）

| 档 | 特征 | 谁主导 | 典型场景 |
|---|---|---|---|
| **A 全外包 Codex** | 纯逻辑 / 单文件 / 有客观标准 | 🟨 Codex 做，Claude 不参与 | 写单元测试 / 补覆盖率 / 纯函数实现 / typo / 死代码清理 / lint / docstring 补全 / 按陷阱清单逐条扫 |
| **B 混合协作** | 跨文件但单模块 / 有 spec 约束 | 🟦 Claude 决策 + 🟨 Codex 执行 | 集成层代码（router/service）/ 浅 bug 修复 / Alembic 迁移脚本 / 复杂状态机实现 / **代码审查**（异源第三审已落地）|
| **C 不外包 Claude** | 跨模块决策 / 和人沟通 / 产品判断 | 🟦 Claude 主导 | PRD / spec 撰写 / 架构讨论 / 和 Starsky 沟通 / 9 阶段 ③④⑤（塑形→spec→计划）/ 跨模块 bug 调查 / 集成审 Agent B |

### §2.1 具体映射到 velo 纯函数模块

CLAUDE.md 标注的 5 个纯函数（不碰 DB / 不碰文件系统）**默认 A 档**：
- `parsing/gpx_parser.py` / `parsing/fit_parser.py`
- `activity/simplify.py`
- `segment/matcher.py`
- `activity/power_zones.py`
- `notification/detector.py`

这些模块**接口固定**（输入参数 → 返回结果），**测试可孤立**（不依赖外部状态）——Codex 写测试 / 补边界用例 / 修 typo 最擅长。

### §2.2 具体映射到 9 阶段工作流

| 阶段 | Codex 可代劳的动作 |
|---|---|
| ① 脑暴 | ❌ 不代劳（C 档）|
| ② PRD | ❌ 不代劳（C 档）|
| ③ 需求塑形 | ⚠️ 可代劳"Explore agent 式的代码库扫描"（B 档）|
| ④ Spec 撰写 | ⚠️ 可代劳"预读清单 grep 核对"（A 档）|
| ⑤ 实施计划 | ⚠️ 可代劳"任务拆分后的依赖图生成"（B 档）|
| ⑥ 并行执行 | ✅ **大量代劳**——单 task 的纯函数实现 / 测试 / 浅 bug 修复（A/B 档）|
| ⑦ 验证审查 | ✅ **异源第三审**（B 档，硬规则见 CLAUDE.md §开发原则 8）|
| ⑧ 部署 | ⚠️ 可代劳"部署前检查清单扫描"（A 档）|
| ⑨ 复盘归档 | ❌ 不代劳（需要跨期视角，C 档）|

---

## §3 五条判断法则（Claude 决策路由时查表）

遇到一个细节任务，Claude 问自己 5 个问题，**前 3 个任意一条命中 → Codex 做**：

| # | 问 | Yes → 分配给 |
|---|---|---|
| 1 | 是不是**单文件 / 单函数**的活？ | Codex（A 档）|
| 2 | 是不是**写测试 / 补文档 / 修 lint / 扫陷阱清单**？ | Codex（A 档）|
| 3 | 是不是**跨文件但单模块** + **有明确 spec 约束**？ | Claude 定边界 + Codex 实现（B 档）|
| 4 | 是不是**跨模块 / 涉及数据流**？ | Claude 主导 + Codex 验证审（B 档）|
| 5 | 是不是**涉及和 Starsky 沟通 / 架构决策 / 产品判断**？ | Claude（C 档）|

**冲突解法**：一个任务同时命中多条 → 取**最高档**（C > B > A）。

---

## §4 调用场景模板

每个场景给出：触发条件 / 调用方式 / prompt 骨架 / 期望输出 / 验收标准。

### 场景 A：写单元测试

**触发**：纯函数刚实现完 / 要补覆盖率 / 想加边界用例

**调用**：`Agent(subagent_type: "codex:codex-rescue", prompt: ...)`

**Prompt 骨架**：
```
你是 velo 项目的单测写手。

## 被测对象
- 文件：<path>:<line-range>
- 函数签名：<signature>
- 契约（从 spec-vN.md §X 抽）：<输入/输出/异常>

## 项目约束
- 纯函数不碰 DB / 文件系统（CLAUDE.md §纯函数规则）
- 测试框架：pytest
- 项目技术栈陷阱：见 CLAUDE.md §技术栈陷阱清单（重点注意 Python truthiness / naive-aware datetime / or 短路）

## 任务
1. 写覆盖以下场景的测试：正常值 / 边界（null/0/空/极端大值）/ 异常路径
2. 每个测试用例带一句中文 docstring 说明意图
3. 测试命名：test_<函数>_<场景>
4. 测试之间独立，不共享 fixture 状态

## 输出
给出完整可运行的测试文件内容。**不修改被测代码**。
```

**验收**：Claude 跑 `pytest tests/<new_file>` 通过 → 接受。失败 → 喂日志让 Codex 修。

---

### 场景 B：代码审查（异源第三审）

**触发**：代码写完 + Claude 内部双审已跑 + commit 前

**调用**：首次 `Agent(codex:codex-rescue)` / 迭代 `--resume` 同 threadId

**Prompt 骨架**：
```
你是 velo 项目的独立第二视角 reviewer。

## 审查目标
- Commit：<sha>
- 实际改动范围：<file list + 行数>
- 产品契约（从 spec 抽）：<bullet list>

## 明确跳过（Claude 双审已抓）
- <Claude 已列问题 1>
- <Claude 已列问题 2>

## 你要做什么
1. 读 commit diff：git show <sha>
2. 对照 spec：docs/spec-vN.md §X
3. 读 CLAUDE.md §技术栈陷阱清单 + §强制检查清单
4. 从集成审（architect 信条 5 Agent B）角度找问题

## 输出要求
Critical / Important / Minor 三档，每条：
- file:line + 代码片段
- 问题描述 1-2 句
- 影响范围
- 建议修法 1 句

硬约束：每条带 file:line，不泛泛而谈 / 证据分级 ✅ ⚠️ / 不复读已修项 / 不建议未来重构 / 诚实说"无新问题"比虚构强。
```

**验收**：Codex 给出清单 → Claude 按 §6 可信度分级处理 → 修了再 `--resume` 复查 → 最多 3 轮收敛。

**实证案例**：v4 task-7.10（2026-04-23），首轮抓到 1 条核心反馈环级 Important + 1 条 UX Important，Claude 双审均漏。

---

### 场景 C：技术栈陷阱清单扫描

**触发**：一批代码写完后、PR 发出前、想做"地毯式"检查

**调用**：`Agent(codex:codex-rescue)`

**Prompt 骨架**：
```
按 velo 项目的 10 条技术栈陷阱清单，对以下文件做逐条扫描：

## 陷阱清单
<从 CLAUDE.md §技术栈陷阱清单 复制过来，或直接说"见 CLAUDE.md"让 Codex 自己读>

## 扫描范围
<file list>

## 任务
每条陷阱都要扫一遍，不是挑感兴趣的。
- 命中 → file:line + 代码片段 + 按"正确姿势"列修法
- 未命中 → 列"本文件无此陷阱"
- 不要引入新建议，只按清单扫

## 输出
按陷阱编号组织（陷阱 1 / 陷阱 2 / ...），清晰显示每条是命中还是未命中。
```

**验收**：Claude 核对 Codex 命中条目是否真命中（grep 代码验证）→ 真命中按建议修 / 误报忽略 + 反馈给 Codex。

---

### 场景 D：浅 bug 修复

**触发**：单元测试失败 / 线上日志报错 / Claude 定位到 bug 点但懒得亲自修

**前置**：Claude **先完成定位**（因为定位跨模块 = C 档），再让 Codex 修。

**调用**：`Agent(codex:codex-rescue)`

**Prompt 骨架**：
```
velo 项目有个浅 bug 需要修。

## 定位（Claude 已完成）
- 文件：<path>:<line>
- 现象：<具体表现>
- 根因：<Claude 分析的根因>
- 失败日志/测试：<贴日志>

## 约束
- 只改这一处，不做顺手优化（CLAUDE.md §开发原则 5）
- 不碰核心表（CLAUDE.md §防火墙式扩展）
- 修完跑相关测试：<pytest 命令>

## 任务
1. 修这一处
2. 如果修法影响 caller，列出所有 caller 并确认影响
3. 修完跑测试并贴输出

## 输出
- diff（只这一处）
- 相关 caller 列表
- 测试输出
```

**验收**：Claude 读 diff（CLAUDE.md §commit 前 4 问第 1 条）+ 跑一次测试 → OK 则 commit，不 OK 喂失败日志让 Codex 再修。

---

## §5 成本意识

Codex 比 Claude 便宜，但**不是免费**。

### 批量化原则

❌ **反模式**：每改一行都调 Codex → 调用成本 / 网络开销 > 节省

✅ **正模式**：任务打包，一次外包完整 task（比如"写 10 个测试"一次给完）

### 跳过场景（承自 CLAUDE.md §开发原则 8 的三条，这里细化）

| 跳过场景 | 理由 |
|---|---|
| 纯文档改动 | 没代码逻辑，Codex 价值低 |
| 单文件 < 50 行改动 | Claude 读一眼就能定性，调 Codex 反而慢 |
| 紧急 hotfix | 争分夺秒时不走异步调用 |
| **改动低风险 + Claude 双审已覆盖** | 比如仅加 docstring 或 rename 变量，不必三审 |
| **重复性任务**（比如同类 10 条陷阱全部已命中）| 第 1 条让 Codex 扫，剩下 9 条 Claude 依样画葫芦 |

**跳过了必须在 commit message 写理由**——留痕便于复盘。

---

## §6 失败兜底

### Codex 输出可信度 3 级

| 级 | 特征 | Claude 怎么处理 |
|---|---|---|
| ✅ **必须信** | file:line 明确 + 附代码片段 + Claude grep 能验证 | 直接按建议修或路由给 Codex 修 |
| ⚠️ **参考性** | 观点性建议（"建议重构"/"可以更优雅"）| 按 CLAUDE.md §开发原则 5 "不做 spec 没要求的" → **默认跳过**，除非 Starsky 要求 |
| ❌ **必须验证** | 凭"经验"给结论（"这类代码通常…"）/ 没 file:line | Claude 亲自 grep / 跑命令核实再决定 |

### 冲突解决

- **Codex 和 Claude 判断矛盾** → **以证据为准**（谁给出 file:line + 可验证的代码片段谁赢）
- **都没硬证据** → 停下来跟 Starsky 讨论，不硬磕

### 3 轮不收敛

`--resume` 复查超过 3 轮还有未消化的 Critical/Important → **停下来跟 Starsky 讨论**。可能的原因：
- 问题本质上是 C 档（跨模块），不该让 Codex 反复修
- spec 本身有缺陷 → 回 ④ 补 spec
- Codex 和 Claude 视角鸿沟 → 需要人拍板

### 任务卡死 / 无响应（2026-04-23 实证）

**识别特征**：`codex-companion status <job-id>` 返回 `phase: running` 但 `updatedAt` 和 `createdAt` 间隔 < 1 分钟，之后几十分钟无新进度 → **挂了，不是慢**。

**判断阈值**：
- 启动 > 5 分钟无任何 `progressPreview` 新增 → 警戒
- 启动 > 15 分钟 `updatedAt` 不更新 → **认定卡死**
- elapsed > 30 分钟但活跃窗口 < 1 分钟 → **强制 cancel**

**兜底动作**：
1. 跑 `codex-companion cancel <job-id>` 释放进程
2. 根据任务档位决定：
   - A 档（写测试 / 纯函数）：Claude 亲自做（退而求其次）
   - B 档（代码审查 / 浅 bug 修）：若 Claude 自审修法明确 → 跳过这次 Codex，在 commit message 写明"因 Codex job 卡死兜底跳过"
   - C 档：本来就不该走 Codex
3. **一次卡死不改规则**——同类任务连续 3 次卡死才触发 §2 档位下调

**不做**：不要重试、不要 fresh 启动、不要等——已经耗过 15 分钟再多等也没用。

### `--resume` 可能不生效（2026-04-23 实证）

**现象**：调 `Agent(codex:codex-rescue, prompt: "--resume ...")` 后新任务的 `threadId` 和上一轮的 `threadId` 不同——**实际上开了新 session**，上一轮的上下文没继承。

**可能原因**：subagent 协议层吞了 `--resume` 参数，或 companion 判断不到 resume 候选。

**校验方法**：`--resume` 后跑 `codex-companion status <new-job-id> --json`，对比 `threadId` 和 `codex-companion task-resume-candidate --json` 输出的 `candidate.threadId`——不一致则 resume 未生效。

**兜底**：
- 若是"复查修法" → 可以接受新 session（重新给完整上下文即可），不阻塞流程
- 若是"追问上一轮某条" → resume 失败必须重写 prompt，把上一轮结论作为 context 喂进去，不指望 Codex"还记得"

---

## §7 落地引用

本宪章不是孤岛，被以下规则引用：

| 引用者 | 引用内容 |
|---|---|
| `CLAUDE.md §开发原则 8`（三重审判）| §4 场景 B 的调用协议 |
| `docs/README.md §2.2 各阶段小卡片` | §2.2 的 9 阶段 × Codex 可代劳表 |
| `codex:codex-rescue` 每次调用 | §4 对应场景的 prompt 模板 |

---

## §8 维护机制

### 什么时候必须改本文

1. **Codex 踩新坑**（某场景下大面积幻觉 / 误报 / 漏抓）→ 补进 §6 兜底 或 §4 对应模板的"硬约束"
2. **新增调用场景**（比如性能优化 / 国际化审查）→ §4 加新模板
3. **分工边界变化**（某类 B 档任务实战证明不适合外包）→ 修 §2 档位 和 §3 法则

### 触发重评估的场景

- 连续 3 次 Codex 在同一类场景给出低质量输出 → §2 可能要把该场景下调 1 档
- Codex 在某场景连续 5 次零新发现 → §4 可能要裁剪该场景的使用频率
- 出现新型 subagent 工具（比如别家 plugin）→ §2 和 §4 可能要分化

### 维护者

- 主维护：Starsky
- 协作：Claude（提议修订 / 实战反馈）

---

## §9 修订记录

- **2026-04-23 v1.0 初版**：基于 v4 task-7.10 异源审查实验（Codex 抓到 2 条 Claude 双审漏项）奠基 + 分三档 + 五条判断法则 + 4 个场景模板
- **2026-04-23 v1.1 补 §6 兜底**：同日第二轮复查实验中 Codex job 启动后 25 秒卡死 1 小时 + `--resume` 开了新 session——两个坑实证加进 §6，规则库从"正向场景"扩展到"异常场景"
