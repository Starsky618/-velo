# Agent 协作宪章

> **一句话**：Claude 和 Codex 都可主开发 / 都可审查。共识在 git-tracked 文档，单一裁决链不漂移。
>
> **本文前身**：`codex-division-of-labor.md`（v1.0-v1.3 / 2026-04-23 起）。2026-04-29 升级为中性双主驾视角 v2.0。
>
> **读者**：本文给 agent 读（规则 + 判断框架 + prompt 模板），人类也能扫清档位和场景。

---

## §0 顶层原则（v2.0 新增）

### 单一裁决链（4 层规则）

Tim ↔ Claude ↔ Codex 协作时，遇分歧或漂移按下面顺序裁决：

| 层 | 内容 | 谁能改 |
|---|---|---|
| **1** | 用户当轮指令（Tim 本轮明确说什么）| Tim |
| **2** | 项目宪法（CLAUDE.md / 当前 spec / 当前 task 卡）| Tim 拍板 + agent 提议 |
| **3** | 协作协议（本文）| Tim 拍板 + agent 提议 |
| **4** | 工具适配（Claude Read/Edit/Task / Codex rg/apply_patch）| 各 agent 自己写 |

**核心**：平等的是 **agent 开发地位**，不是 **规则源地位**。规则源只有 1-3 层。

### 共识在 git，不在私有 memory

agent 私有 memory（Claude `~/.claude/.../memory/` / Codex session history）**永远不自动同步**——Claude 学到的教训 Codex 看不见，反之亦然。

→ 任何"如果对方不知道会重蹈覆辙"的规则 / 教训 / 陷阱 **必须**沉淀进 git-tracked 文档（CLAUDE.md / 本文 / docs/）。memory 只留 user 偏好 / agent 自己工作模式反思。

详见 §9 memory → 文档升级机制。

---

## §1 角色定位

### 双主驾视角（2026-04-29 v2.0 升级）

Claude 和 Codex 都可承担"主开发"或"审查方"角色，按任务边界自然切换。**不预设谁是中枢**——v1.x 把 Claude 作中枢，v2.0 起改为对称协作。

| 任务类型 | 主开发偏好 | 审查方偏好 |
|---|---|---|
| 跨模块决策 / 产品判断 / 和 Tim 沟通 | Claude | — |
| 单文件 / 纯函数 / 写测试 / 扫陷阱 | Codex | Claude |
| 中等任务（明确 spec / 跨文件单模块）| 都可（按当下上下文）| 异源（另一方）|

### Codex 的独特价值是"异源"，不是"更快"

常见误区：以为 Codex 擅长"快速写代码"——市场叙事，不是 velo 实证。

**真相**：GPT-5.4 和 Opus 4.7 在单纯代码生成上没数量级差距。写同一函数谁快取决于上下文准备。

**Codex 真正不可替代的是"训练分布独立"**：同一个系统性盲区 Claude 双 agent 一起漏，Codex 不会。v4 task-7.10 实证——Codex 一轮抓到 2 条 Claude 双审都漏的 Important，其中 1 条是核心反馈环级问题。

**所以路由直觉**：
- Claude = **宏观集成 + 跨模块决策 + 和人沟通 + skill 生态**
- Codex = **独立异源审判 + 局部执行**（反 Claude 系统性盲区 + 重复性任务批量化省 token）

"Codex 便宜"是真的，但便宜的价值是**允许把重复性扫描外包**（单测 / 覆盖率 / 陷阱清单），不是"因为便宜所以让它多写代码"。**兜底代码总量要最小化**——兜底多 = 状态机漏（见 §4 场景 E）。

---

## §2 三档分工清单

| 档 | 特征 | 主开发 | 审查方 | 典型场景 |
|---|---|---|---|---|
| **A 全外包** | 纯逻辑 / 单文件 / 客观标准 | 🟨 Codex | 跳过（双审已覆盖）| 写单测 / 补覆盖率 / 纯函数实现 / typo / 死代码 / lint / docstring / 按陷阱清单扫 |
| **B 混合协作** | 跨文件单模块 / 有 spec / 单 task < 50K token | 🟦 Claude 决策 + 🟨 Codex 执行（**也可反过来**）| 异源（另一方）| 集成层（router/service）/ 浅 bug 修 / Alembic 迁移 / 复杂状态机 / 代码审查 / 大文档 review-only |
| **C 不外包** | 跨模块决策 / 和人沟通 / 产品判断 | 🟦 Claude | — | PRD / spec 撰写 / 架构讨论 / 和 Tim 沟通 / 9 阶段 ③④⑤ / 跨模块 bug 调查 / 集成审 |

### §2.1 velo 纯函数模块（A 档默认）

CLAUDE.md 标注的纯函数（不碰 DB / 不碰文件系统）：
- `parsing/gpx_parser.py` / `parsing/fit_parser.py`
- `activity/simplify.py`
- `segment/matcher.py` / `segment/algorithms.py`（v5 新增）
- `activity/power_zones.py`
- `notification/detector.py`
- `app/common/geo.py`（v5 新增）

接口固定 + 测试可孤立 → A 档。

### §2.2 9 阶段工作流 × Codex 可代劳

| 阶段 | Codex 可代劳的动作 |
|---|---|
| ① 脑暴 | ❌ 不代劳（C 档）|
| ② PRD | ❌ 不代劳（C 档）|
| ③ 需求塑形 | ⚠️ 代码库扫描（B 档）|
| ④ Spec 撰写 | ⚠️ 预读 grep（A 档）/ ⚠️ 写完后异源审（B 档 review-only）；❌ **禁止派 codex 写正文**（见 §5 大文档硬禁止）|
| ⑤ 实施计划 | ⚠️ 任务依赖图（B 档）/ ⚠️ 写完后异源审（B 档 review-only）；❌ **禁止派 codex 写正文** |
| ⑥ 并行执行 | ✅ **大量代劳**——单 task A/B 档 |
| ⑦ 验证审查 | ✅ **异源第三审**（B 档，详见 §4 场景 B + §8 必跑命令门禁）|
| ⑧ 部署 | ⚠️ 部署前检查清单（A 档）|
| ⑨ 复盘归档 | ❌ 不代劳（C 档）|

---

## §3 五条判断法则

主开发 / 审查方接到细节任务时按表查：

| # | 问 | Yes → 路由 |
|---|---|---|
| 1 | 单文件 / 单函数？ | A 档 |
| 2 | 写测试 / 补文档 / 修 lint / 扫陷阱？ | A 档 |
| 3 | 跨文件单模块 + 有 spec 约束？ | B 档（**主开发可 Claude 也可 Codex**）|
| 4 | 跨模块 / 涉及数据流？ | C 档主导 + B 档审 |
| 5 | 涉及和 Tim 沟通 / 架构决策 / 产品判断？ | C 档 |

**冲突解法**：一个任务命中多条 → 取**最高档**（C > B > A）。

---

## §4 调用场景模板

每场景给：触发 / 调用方式 / prompt 骨架 / 期望输出 / 验收。

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
- 项目技术栈陷阱：见 CLAUDE.md §技术栈陷阱清单（重点：Python truthiness / naive-aware datetime / or 短路）

## 任务
1. 写覆盖以下场景：正常值 / 边界（null/0/空/极端大值）/ 异常路径
2. 每个测试带一句中文 docstring 说明意图
3. 测试命名：test_<函数>_<场景>
4. 测试之间独立，不共享 fixture 状态

## 输出
完整可运行的测试文件内容。**不修改被测代码**。
```

**验收**：跑 `pytest tests/<new_file>` 通过 → 接受。失败 → 喂日志让 Codex 修。

---

### 场景 B：代码审查（异源第三审）+ ⭐ 必跑命令门禁

**触发**：代码写完 + 内部双审已跑 + commit 前

**⭐ 升级（2026-04-29 v2.0 / A 议题）**：审查 [动 DB / 动外部 API / 动文件系统] 类代码时，**必须**在真/近真环境跑命令验证行为，**不能仅凭 mock 测试通过就放行**。

**触发分类**：

| 代码类型 | 必跑？|
|---|---|
| 纯算法函数 / 纯字符串处理 | ❌ 静态 + 单测够 |
| **动 DB（含 PostGIS / 复杂 SQL）**| ✅ 必跑 |
| **动外部 API（Strava / DeepSeek）**| ✅ 必跑（mock 也行但要近真）|
| **动文件系统** | ✅ 必跑 |

**实证（task-0.7）**：Codex 写 backfill 报"5 mock 测试全过 ✅"，但 mock 里 `reference_line = "line-1"`（字符串），生产是 EWKB hex —— 静态全过 / 生产首跑 24/24 炸。教训：**mock ≠ 真环境**。

**本地 docker stack（待配 `docker-compose.dev.yml` + 种子数据）替代频繁 SSH 生产**——一次性投入，毫秒反馈，不动生产，不消耗 SSH approval。详见 §8。

**调用**：首次 `Agent(codex:codex-rescue)` / 迭代 `--resume` 同 threadId

**Prompt 骨架**：
```
你是 velo 项目的独立第二视角 reviewer。

## 审查目标
- Commit：<sha>
- 实际改动范围：<file list + 行数>
- 产品契约（从 spec 抽）：<bullet list>

## 明确跳过（双审已抓）
- <已列问题 1>
- <已列问题 2>

## 你要做什么
1. 读 commit diff：git show <sha>
2. 对照 spec：docs/spec-vN.md §X
3. 读 CLAUDE.md §技术栈陷阱清单 + §强制检查清单
4. 集成审视角找问题

## 必跑命令（如果代码动 DB / 外部 API / 文件系统）⭐
- 启 docker stack：docker compose -f docker-compose.dev.yml up -d
- 容器内跑：python -m <脚本>（贴输出到对话）
- SQL 验证：docker compose exec db psql -U velo -d velo -c "<query>"
- mock 测试通过 ≠ 通过——必须真环境复现 1 次

## 输出要求
Critical / Important / Minor 三档，每条：
- file:line + 代码片段
- 问题描述 1-2 句
- 影响范围
- 建议修法 1 句

硬约束：每条带 file:line，证据分级 ✅ ⚠️ / 不复读已修项 / 不建议未来重构 / 诚实说"无新问题"比虚构强。
```

**验收**：Codex 给清单 → 按 §6 可信度分级处理 → 修了再 `--resume` 复查 → 最多 3 轮收敛。

**实证案例**：
- v4 task-7.10：核心反馈环级 Important + UX Important 抓到 ✅
- v5 task-0.7：mock-only 审查导致 24/24 失败 ❌（教训沉淀本节"必跑命令"门禁）

---

### 场景 C：技术栈陷阱清单扫描

**触发**：一批代码写完后、PR 发出前、想做"地毯式"检查

**调用**：`Agent(codex:codex-rescue)`

**Prompt 骨架**：
```
按 velo 项目的技术栈陷阱清单，对以下文件做逐条扫描：

## 陷阱清单
<从 CLAUDE.md §技术栈陷阱清单 复制过来，或直接说"见 CLAUDE.md">

## 扫描范围
<file list>

## 任务
每条陷阱都要扫一遍，不是挑感兴趣的。
- 命中 → file:line + 代码片段 + 按"正确姿势"列修法
- 未命中 → 列"本文件无此陷阱"
- 不要引入新建议，只按清单扫

## 输出
按陷阱编号组织（陷阱 1 / 陷阱 2 / ...），清晰显示每条命中还是未命中。
```

**验收**：核对 Codex 命中条目是否真命中（grep 验证）→ 真命中按建议修 / 误报忽略 + 反馈给 Codex。

---

### 场景 D：浅 bug 修复

**触发**：单元测试失败 / 线上日志报错 / 已定位 bug 点

**前置**：主开发**先完成定位**（定位跨模块 = C 档），再让 Codex 修。

**调用**：`Agent(codex:codex-rescue)`

**Prompt 骨架**：
```
velo 项目有个浅 bug 需要修。

## 定位（已完成）
- 文件：<path>:<line>
- 现象：<具体表现>
- 根因：<分析的根因>
- 失败日志/测试：<贴日志>

## 约束
- 只改这一处，不做顺手优化（CLAUDE.md §开发原则 5）
- 不碰核心表（CLAUDE.md §防火墙式扩展）
- 修完跑相关测试：<pytest 命令>

## 任务
1. 修这一处
2. 修法影响 caller，列出所有 caller 并确认影响
3. 修完跑测试并贴输出

## 输出
- diff（只这一处）
- 相关 caller 列表
- 测试输出
```

**验收**：读 diff（CLAUDE.md §commit 前 4 问第 1 条）+ 跑一次测试 → OK 则 commit。

---

### 场景 E：状态机漏洞扫描

**触发**：spec 里定义了状态机 / 代码里要写大量兜底 try/except / 怀疑异常恢复路径有洞

**前置认知**：**兜底代码多 = 状态机设计破洞**，正解不是外包兜底，是把状态机建完整。Codex 在这里**扫漏洞**不是**写兜底**——后者会糊上反而看不到根因。

**Prompt 骨架**：
```
你是 velo 项目的状态机审查员。**不要写兜底代码**，只列漏洞清单。

## 状态机定义（事实）
- 实体：<比如 activity>
- 状态字段：<status 字段名 + 值域>
- 合法转换：
  - pending → processing（触发：worker 抢锁）
  - processing → completed（触发：解析成功）
  - processing → failed（触发：解析异常）
  - <其他转换列全>
- 状态 server_default：<从 model 抄真实值>

## 当前代码
- model 文件：<path:line>
- service 文件（状态写入点）：<path:line>
- worker 文件（状态推进点）：<path:line>

## 你要扫的 5 类漏洞
1. **漏转换**：业务上合法但图里没画？
2. **漏异常恢复**：每个非终态 crash 后能自愈吗？
3. **并发冲突**：UPDATE WHERE 原子性保证？
4. **级联一致性**：上游删除 → 下游怎么办？
5. **值域不符**：spec / model / service 三处一致？

## 输出（Critical / Important / Minor）
每条：漏洞类型 / 具体场景 / file:line / 建议补什么（**不写代码**）

## 硬约束
- 不要写兜底代码
- 不要泛说"建议加异常处理"——具体说"状态 X 缺少转到 Y 的路径"
- 证据分级：✅ ⚠️ ❌
- 诚实说"状态机完整"比虚构漏洞强
```

**验收**：核对漏洞是否真漏 → 真漏的改 **spec**（不是直接写代码）→ 按正常流程推进。**严禁跳过 spec 直接给 Codex 写兜底代码补上去。**

---

## §5 成本意识

Codex 比 Claude 便宜，但**不是免费**。

### 批量化原则

❌ **反模式**：每改一行都调 Codex
✅ **正模式**：任务打包，一次外包完整 task

### 跳过场景

| 跳过场景 | 理由 |
|---|---|
| 纯文档改动 | 没代码逻辑 |
| 单文件 < 50 行 | 一眼定性 |
| 紧急 hotfix | 速度优先 |
| 改动低风险 + 双审已覆盖 | 比如加 docstring / rename |
| 重复性任务（同类已扫过）| 第 1 条扫，剩下依样画 |
| **大文档撰写**（spec / plans / > 800 字 / > 1500 行）⭐**硬禁止** | codex CLI 单 task 输入+输出 > 50K token 几乎必卡（已知 bug 链 #13738/#14048/#18723 + spec-v5 实证卡死 30+ 分钟）。**默认路径**：主 agent 自己写（chunk by chunk）→ 写完派 codex review-only |

**跳过了必须在 commit message 写理由**——留痕便于复盘。

### §5.1 授权改动留痕（2026-04-29 task-0.7 实证）

**背景**：task-0.7 互审实验里，codex 改了 CLAUDE.md 两处核心规则（健康度红灯 500→600 / 第 9 项规则改名）。Claude 审查时只看 diff + commit message，**无法分辨"Tim 授权"vs"codex 自作主张"**——按默认策略一律按 scope creep 报 Critical。

**硬规则**：codex / 任何 subagent 改下面"高敏感文件"时，commit message **必须**含一行授权来源：

```
授权来源：Tim YYYY-MM-DD 对话 / Tim 在 task-X.X 卡里写明 / 等
```

**高敏感文件清单**：
- `CLAUDE.md`
- `docs/agent-rules/*.md`（含本文）
- `docs/spec-v*.md`
- `docs/prd/velo-vision.md` / `velo-strategy.md` / `velo-product-spec.md`
- `.claude/settings.json` / hook 配置

**没写授权来源的改动 = 默认按越权处理**——审查报 Critical，要求撤回或补授权说明。

> 不在清单上的文件（业务代码 / 测试 / task 卡）：照常执行，不需要授权痕。

---

## §6 失败兜底

### Codex 输出可信度 3 级

| 级 | 特征 | 怎么处理 |
|---|---|---|
| ✅ **必须信** | file:line + 代码片段 + 可 grep 验证 | 直接按建议修 |
| ⚠️ **参考性** | 观点性建议 | 默认跳过，除非 Tim 要求 |
| ❌ **必须验证** | 凭"经验"给结论 / 没 file:line | 亲自 grep / 跑命令核实 |

### 冲突解决

- **Codex 和 Claude 矛盾** → 以证据为准（谁给 file:line + 可验证片段谁赢）
- **都没硬证据** → 停下来跟 Tim 讨论

### 3 轮不收敛

`--resume` 复查 > 3 轮还有未消化 Critical → 停下跟 Tim 讨论。原因可能：
- 问题本质 C 档（跨模块）
- spec 本身有缺陷 → 回 ④ 补 spec
- 视角鸿沟 → 需要人拍板

### 任务卡死 / 无响应（2026-04-23 实证）

**识别**：`status` 返回 `phase: running` 但 `updatedAt` 和 `createdAt` 间隔 < 1 分钟 → 挂了，不是慢。

**判断阈值**：
- 启动 > 5 分钟无 progressPreview 新增 → 警戒
- > 15 分钟 updatedAt 不更新 → 认定卡死
- elapsed > 30 分钟但活跃窗口 < 1 分钟 → 强制 cancel

**兜底动作**：
1. 跑 `codex-companion cancel <job-id>`
2. 按档位决定：A 档 Claude 亲自做 / B 档若修法明确则跳过本次 Codex 在 commit 写明 / C 档本就不该走 Codex
3. 一次卡死不改规则——同类连续 3 次才触发档位下调

**不做**：不要重试 / 不要 fresh 启动 / 不要等。

### `--resume` 可能不生效（2026-04-23 实证）

**现象**：`--resume` 后新任务的 threadId 和上一轮不同 → 实际开了新 session，上下文没继承。

**校验**：跑 `status <new-job-id> --json`，对比 `threadId` 和 `task-resume-candidate --json` 输出。

**兜底**：
- 复查修法 → 接受新 session（重新给完整上下文）
- 追问上一轮某条 → resume 失败必须重写 prompt，把上一轮结论作为 context 喂进去

---

## §7 信息整流原则（v2.0 新增 / B 议题）

### 翻译层句式（默认硬规则）

给 Tim 提议时**必须**用这个格式：

> **干啥用**：用户故事一句话
> **触发**：什么场景启用
> **影响**：会改什么 / 不会改什么
> **风险**：低 / 中 / 高 + 一句理由
> **建议**：y / n / show
>
> *(技术细节默认折叠，主动 show 才贴 diff / raw 输出)*

**禁止**：只贴 diff / 长输出 / 代码片段 / 术语堆砌。raw 细节是底层，Tim 主动 show 才展开。

类比：CEO 不该直接读代码——该看产品经理翻译过的"为什么改、影响什么、风险多大"。

### 高风险动作硬 checklist

下面这些动作**必须**走 checklist，每项打钩贴对话——无关主观信心：

| 高风险动作 | 必走 checklist |
|---|---|
| 动 schema（alembic upgrade / 迁移）| ✅ pg_dump 备份 / ✅ 跑前 SQL snapshot / ✅ 跑后 schema 比对 |
| 动生产数据（写脚本回填）| ✅ 真环境 dry-run / ✅ SAVEPOINT 隔离审 / ✅ 幂等验证（两次跑结果一致）|
| 改 CLAUDE.md / agent-rules | ✅ 授权来源声明（§5.1）/ ✅ 不在 task 范围内禁改 |
| commit + push | ✅ 跑测试 / ✅ git diff 自审 |

不走 = 协议违规 = Tim 拒收。

类比：飞机起飞前飞行员**强制 checklist 走完一遍**，无关主观信心。

### 最低限度不确定度自报

**只在 agent 提议"未在 checklist 上的非常规动作"时触发**——不是每条提议都加。

实证（task-0.7 反例）：
> "🟡 我推测 task-0.6 含 progress_records 表（基于 task 卡描述推断 / **未 grep migration 验证**）。要不要先 grep 确认再说？"

让 Tim 选"信我猜继续 / 先验证再走"。

**为什么不每条都加颜色标签**：
- 高频触发 → token 浪费（10 session 多 3000 token vs checklist 10 sprint 共 4000 token）
- 标签泛滥 → Tim 麻木（70% 标 🟡 等于没标）
- 形式主义陷阱：AI 标了但实际没真验证 → 自我应验，比不标更危险

### 动作 trigger 自查（必）

每次写报告 / 给 Tim 提议前 mental check 3 问：

1. 我有没有把代码细节推给 Tim？（违反 → 改翻译层句式）
2. 我做了哪些实证 / 没做哪些？（涉及未做的 → 走最低限度不确定度自报）
3. 这是高风险动作吗？（涉及 schema / 生产 / 核心规则 → 走硬 checklist）

**光"知道规则"不够——必须动作 trigger 强制自查**。否则下次又翻车（task-0.7 实证：刚立信息整流原则下一条提议就违反）。

---

## §8 运行时验证门禁（v2.0 新增 / A 议题）

### 第一性原理

主开发可能错的来源两类：

| 错的来源 | 审查方怎么 catch |
|---|---|
| 静态错（字段名 / 路径 / 类型）| grep + 读相关代码 |
| **动态错**（DB 行为 / 外部 API / 真实数据格式）| **必须独立跑命令**——光看代码无解 |

第二种通过 §4 场景 B 的"必跑命令"门禁强制。

### 落地：本地 docker stack

**目标**：替代频繁 SSH 生产（每次都要 Tim 点头不可持续）。

**待配**：`docker-compose.dev.yml` + 种子数据（PostGIS / Redis）

**回报**：
- 一次性投入：~30-60 分钟
- 收益：之后所有审查在本地跑，毫秒反馈，不动生产，不消耗 SSH approval

**部署链路对比**：

| 当前 | 配 docker stack 后 |
|---|---|
| 本地写 → mock 测 → push → 生产 build → 生产跑 → 炸 | 本地写 → mock 测 → **本地 docker 真跑** → push → 生产跑（大概率不炸）|

---

## §9 memory → 文档升级机制（v2.0 新增 / C 议题）

### 不对称发现

| | Claude | Codex |
|---|---|---|
| 私有 memory | ✅ 有 | ❌ 没（session 跑完清）|
| 漂移源 | memory 私有不共享 | 教训当场不入文档就丢失 |
| 解法 | memory → 文档**升级机制** | 教训**当场**入文档（无升级）|

### 升级 trigger（每次 save memory 自问）

> "这条如果对方 agent 看不见会重蹈覆辙吗？" — 是 → 升级到 git-tracked 文档

### 升级目标查表（agent 自决）

| 教训类型 | 升级到 |
|---|---|
| 协作协议 / 流程 | `docs/agent-rules/agent-collaboration.md`（本文）|
| 项目特定技术陷阱 | `CLAUDE.md` 技术栈陷阱清单 |
| 安全 / 边界 | `CLAUDE.md` 顶部硬规则 |
| 产品决策 | `docs/agent-rules/product-decisions.md` |
| 架构演进决策 | `docs/adr/` |
| 一次性踩坑（非通用）| `docs/changelog.md` / `docs/deployment-diary.md` |

### 半自动机制（升级问 Tim）

实际句式：

> "已 save memory `<file>.md`。
> **推荐升级到** `<目标文档>` §X.Y。
> **干啥用**：[一句话翻译]
> **影响**：[一句话]
> **建议**：y
> *(diff 已写好，y 立即提交 / n 不要 / show 给我看 diff)*"

90% Tim 扫一眼 y / 10% n 或 edit。**主权在 Tim 手里 + 单次 token 几乎零**。

---

## §10 切换 trigger（v2.0 新增 / D 议题）

### 默认：按自然边界切换

按 **spec 章节 / PR / task 卡完工** 这种自然边界切换主开发。重建上下文成本可控 + 异源价值大。

### 例外清单（不切换）

| 场景 | 理由 |
|---|---|
| 紧急 hotfix | 速度优先，切换成本不值 |
| 纯文档重构 | 一致性比异源重要 |
| 任务量 < 30 分钟 | 切换成本 > 收益 |
| Tim 明确要求"一气呵成" | 主权 |

### Tim 主权

Tim 可随时叫"现在 Codex 接手 / Claude 接手"——agent 不能反驳。

### 任务类型分类

| 任务 | 双主驾 ROI |
|---|---|
| 明确 spec 的中等 task（task-0.7 类）| ✅ 高 |
| 独立模块开发（task-1.A.1 类）| ✅ 高 |
| 极复杂战略任务（spec 设计阶段）| ⚠️ 低——上下文太大，切换成本爆炸 |
| 紧急 hotfix | ❌ 不切换 |
| 纯文档重构 | ❌ 不切换 |

---

## §11 落地引用

本文被以下规则引用：

| 引用者 | 引用内容 |
|---|---|
| `CLAUDE.md §开发原则 8`（三重审判）| §4 场景 B 调用协议 + §8 运行时验证 |
| `CLAUDE.md §0` 顶部硬规则 | §7 信息整流原则 |
| `docs/README.md §2.2 各阶段小卡片` | §2.2 9 阶段 × Codex 可代劳 |
| `codex:codex-rescue` 每次调用 | §4 对应场景 prompt 模板 |

---

## §12 维护机制

### ⭐ 少增加文档原则（2026-04-29 v2.0 新增 / Tim push back）

**硬规则**：新增文档类型需 Tim 拍板。能合并到现有文档章节，不允许独立成文。

**Why**：文档膨胀 = 双方认知负荷加重 + 系统不稳定性加重（漂移源更多 / 维护成本高）。velo 已有 30+ 文档 / 4 期 spec / 10 ADR / 5 竞品分析——继续单向膨胀风险大。

**How to apply**：
- agent 想新建 `.md` 文件前 → 自查"现有哪份文档有这个章节归属？"
- 找不到 / 真必要 → 显式问 Tim 拍板
- 例外：改名（如本文从 codex-division-of-labor.md 改名而来）不算新增

> **见 memory: feedback_rule_system_entropy_risk.md**——Tim 已警觉的第三阶问题（规则系统熵增），待专题讨论清理机制。

### 什么时候必须改本文

1. Codex/Claude 踩新坑 → 补 §6 兜底 / §4 模板 / §7 trigger 自查
2. 新增调用场景 → §4 加新模板
3. 分工边界变化 → 修 §2 档位 + §3 法则
4. §7-§10 任一议题（信息整流 / 验证门禁 / memory 升级 / 切换 trigger）漏洞 → 修对应章节

### 触发重评估

- 连续 3 次 Codex 同类场景低质 → §2 下调 1 档
- Codex 某场景 5 次零新发现 → §4 裁剪频率
- 出现新型 subagent 工具 → §2 §4 分化

### 维护者

- 主维护：Tim
- 协作：Claude（提议修订 / 实战反馈）+ Codex（异源审查时）

### 待实证实验（计划任务）

| # | 实验 | 触发期 | 目的 | 成功标准 | 失败处理 |
|---|---|---|---|---|---|
| E1 | **Spec 层 Codex 三审** A/B 对比 | v5 期第一个 spec 写完后 | 验证 Codex 异源在 spec 层的边际价值 | Codex 抓到 Claude spec 双审漏的 Critical ≥ 1 → 加 §4 场景 F | 零新发现 → spec 层只 Claude × 2 |
| E2 | **本地 docker stack 配置 + 实战** | task-1.A.2 或 1.A.3 开工前 | §8 落地验证 | 在本地 docker 跑 backfill 类脚本，与生产 SSH 跑结果一致 | 失败 → 退回审查方 SSH 跑（Tim 点头每次）|

---

## §13 修订记录

- **2026-04-23 v1.0 初版**（codex-division-of-labor.md）：基于 v4 task-7.10 异源审查实验奠基 + 三档 + 五法则 + 4 场景模板
- **2026-04-23 v1.1**：补 §6 兜底（Codex job 卡死 + `--resume` 不生效两坑实证）
- **2026-04-24 v1.2**：校正定位（Codex 异源不是更快）+ 加场景 E + 立 E1 实验
- **2026-04-28 v1.3**：撤回"派 codex 写大文档"硬禁止（spec-v5 实证卡死 30+ 分钟）
- **2026-04-29 v2.0**（本版 / 授权来源：Tim 2026-04-29 对话）：从 `codex-division-of-labor.md` **改名**升级为 `agent-collaboration.md`，从 Claude-中枢视角改为**双主驾**视角。task-0.7 完工后 Tim ↔ Claude 长讨论收敛 4 议题（B 角色定位 / A 运行时验证 / C 记忆同步 / D 切换 trigger），落地为：
  - §0 顶层原则（4 层规则 + 共识在 git）
  - §1 双主驾视角（v1.x 的 Claude 中枢被废）
  - §4 场景 B 升级"必跑命令门禁"
  - §7 信息整流原则（翻译层句式 + 高风险硬 checklist + 最低限度不确定度自报 + 动作 trigger 自查）
  - §8 运行时验证门禁（本地 docker stack 配 docker-compose.dev.yml）
  - §9 memory → 文档升级机制（半自动 + agent 自决目标 + 翻译层问 Tim）
  - §10 切换 trigger（自然边界 + 例外清单 + Tim 主权）
  - §12 少增加文档原则（置顶硬规则）
  - §12 加 E2 实验（本地 docker stack 实战验证）
  
  **实证驱动**：task-0.7 部署链路暴露的 6 个问题（mock ≠ 真环境 / 容器 rebuild 验证 / PAT 泄露 / progress_records 误报 / EWKB hex 字段 / 信息整流原则违反）全部沉淀进新章节。
