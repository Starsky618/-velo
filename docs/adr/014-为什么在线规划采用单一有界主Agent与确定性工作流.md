# ADR-014: 为什么在线规划采用单一有界主 Agent 与确定性工作流

> **状态：Proposed — A1.2，等待 Orchestrator 审查**
>
> **一句话核心决策：在线骑前规划采用“单一有界主 Agent + 确定性工作流”，模型只拥有受类型约束的动作提议权，代码始终拥有状态推进、工具门禁、领域事实、校验、持久化与停止权。**

## 1. 决策范围

本 ADR 只裁决一次在线规划 run 内，模型与确定性代码分别控制什么。

它承接 [ADR-013](./013-为什么区分骑前静态规划与骑中实时导航.md) 已允许的骑前静态规划，不扩大到骑中实时导航，也不授权实现 Runtime、合同、数据库、API、小程序、Provider、导出或部署。

`Agent` 在本文中特指一次 run 内唯一的逻辑模型决策主体；更换模型、模型降级或模型路由不产生第二个平级决策主体。

## 2. 当前仓库事实

- 当前 `app/agent` 是 DeepSeek 赛段文案生成、RQ task 与直接 ORM 写入，不是在线规划 Control Plane。
- Route Draw 与腾讯骑行规划已经通过确定性服务生成和校验坐标，不由 LLM 生成几何。
- 路线版本、哈希、海拔成品、可信来源、导出权限与 stale artifact 已有代码门禁。
- 当前代码中不存在 `RunController`、`ContextCompiler`、规划 `ToolRegistry`、`AgentAction`、`AgentSession` 或在线规划循环的实现。
- 当前依赖与运行代码中没有 LangGraph、LangChain、OpenAI Agents SDK、TypeScript Agent Runtime 或 multi-agent planning 实现。

因此本轮是在确定控制边界，不是在给既有 Runtime 补文档。

## 3. 考虑过的选项

### 选项 A：纯确定性 Workflow

所有意图解析、分支与响应都写成代码规则；不使用模型做动态决策。

- 优点：最容易重放和证明边界。
- 缺点：无法经济地理解开放式骑行意图、歧义和自然语言修订；规则复杂度会转移到脆弱的条件分支。
- 结论：拒绝作为完整交互方案，但保留确定性代码对状态与执行的全部权威。

### 选项 B：模型主导的自由 Agent 循环

模型自行保管上下文、选择工具、判断重试、决定何时写状态并结束。

- 优点：原型快，代码骨架少。
- 缺点：预算、门禁、重放、幂等和停止条件依赖提示词；难以证明模型没有绕过校验或触发副作用。
- 结论：拒绝。VELO 的路线几何、版本、权限和导出不能依赖模型自律。

### 选项 C：多 Agent 协商或主管—子 Agent 编排

把意图、路线、校验、研究或审核拆给多个平级或层级 Agent。

- 优点：角色描述直观，可并行探索。
- 缺点：产生多个逻辑权威，增加冲突解决、预算放大、状态同步与 trace 归因难度；当前没有评测证据证明这些成本必要。
- 结论：拒绝 A1.2 在线主路径采用；本决策不允许同一 run 内启动 peer agent 或 subagent。

### 选项 D：单一有界主 Agent + 确定性工作流

一个逻辑模型主体负责动态理解与候选比较；代码负责所有不可跳过的状态和能力门禁。

- 优点：保留自然语言推理价值，同时能确定性限制副作用、预算、重试、校验与停止；易于 trace、重放和评测。
- 缺点：需要明确合同、状态机和 typed observation，早期实现比自由循环更严格。
- 结论：选择。

## 4. 正式决策

采用 `deterministic_run_controller_with_single_logical_main_agent`，即“单一逻辑主 Agent + 确定性 Run Controller”。

一次 run 只有一个逻辑主 Agent。主 Agent 可以在预算内多轮提议动作，但不能创建平级 Agent、subagent 或新的决策权威；该边界是 `no multi-agent`。基础设施可以路由或替换底层模型；替换前后的模型共享同一受控 run、同一状态版本与同一权限边界。

模型输出只是 typed action proposal。proposal 不是命令、事实、校验结果或副作用授权；只有确定性工作流接受并执行后，状态才可改变。顶层顺序固定为 receive event → load state → compile context → model decide → gate → execute approved high-level tool → apply typed observation → reduce state → validate → persist → trace → respond/wait/stop。

## 5. 控制权归属

| 主体 | 拥有 | 不拥有 |
|---|---|---|
| 单一主 Agent | 理解意图、识别歧义、提出澄清、选择高层工具类别、比较已验证候选、解释拒绝/修订、生成用户可读说明 | 状态直接写入、原始 Provider/ORM/SQL、几何/距离/海拔真相、跳过校验、批准敏感副作用、无限重试 |
| 确定性 Workflow | 接收事件、加载状态、编译上下文、执行 policy/tool/schema gate、形成 typed observation、reducer 推进、领域校验、持久化、trace、停止与恢复 | 代替用户做产品偏好选择、让未验证模型文本成为领域事实 |
| Domain Plane | 路线事实、Provider 结果、几何、距离、海拔、时间/指标、硬约束验证、版本/revision/hash、导出工件 | 解释开放式用户意图、替用户选择最终方案 |
| 用户 | 纠正意图、确认精确起点、消除关键歧义、选择最终计划、批准敏感或有副作用的动作 | 绕过系统硬校验或伪造领域事实 |

## 6. Action proposal 边界

主 Agent 只可提出受支持的高层动作，例如 `ASK_CLARIFYING_QUESTION`、`CALL_APPROVED_TOOL`、`PRESENT_VALID_CANDIDATES`、`REQUEST_CONFIRMATION`、`FINALIZE_RESPONSE` 或 `NO_RESULT`。

具体 action schema、字段、版本、错误结构与序列化格式延后到 A2；Session/Run/Memory 生命周期延后到 A1.3，即 `exact state schema deferred to A1.3/A2`。本文不预写数据库表、API payload 或框架类。

所有 proposal 必须携带足够的状态版本与意图引用，供未来工作流检查 stale proposal；具体字段仍由后续合同任务裁决。

## 7. 不可绕过的确定性门禁

工作流必须按代码定义的顺序控制以下类别，模型不能通过自然语言跳过：

1. 当前状态/revision 与 run 状态检查；每次 Plan 变更使旧 validation 失效。
2. capability、policy、approval 与 side-effect gate；raw Provider、ORM/SQL、public publish 与 real export 对在线 Agent 不可达。
3. tool registry、输入 schema、deadline 与幂等检查。
4. typed observation 与 deterministic reducer；地图状态不能从 Agent 自然语言反推，工具原始返回不能直接成为用户可选计划。
5. 几何、距离、海拔、硬约束、来源、版本与 hash 的领域校验；未通过 hard validation 的 Plan 不能成为 viable、selected 或 export-ready。
6. 状态与领域对象的受控持久化、trace 和副作用 ledger。
7. 预算、停止原因、等待用户与恢复入口。

Capability/Approval/Side Effect 的完整分类属于 A1.4，即 `approval taxonomy deferred to A1.4`；在其通过前，任何未明确注册或可能产生敏感副作用的能力都应 fail closed。

## 8. 有界循环与停止语义

每次 run 必须由确定性控制器配置并累计至少以下预算：

- `max_model_turns`
- `max_tool_calls`
- `max_plan_generations`
- `max_same_tool_retries`
- `wall_clock_deadline`
- `token_or_cost_budget`

任一预算耗尽都由代码停止，模型不能自行延长。未来具体默认值由实现与 VeloBench 证据决定，本 ADR 不猜数值。

终态/暂停原因至少包括：

- `completed`
- `waiting_for_user`
- `no_result`
- `approval_required`
- `budget_exceeded`
- `deterministic_error`

每个 `stop reason` 必须进入可审计状态和 trace；网络断开、超时或恢复不能偷偷重置已消耗预算或重复副作用。

## 9. Framework choice: DEFERRED

A1.2 不选择 Python/TypeScript Runtime，也不采用 OpenAI Agents SDK、LangGraph、LangChain 或其他编排框架。

框架必须等语言中立合同、VeloBench 与 Fake Environment 暴露真实需求后再评估。若未来采用框架，它只能实现本 ADR 的边界，不能把框架默认行为提升为产品权威。

## 10. 与其他任务的关系

- ADR-013 回答“允许规划什么”；ADR-014 回答“一次在线规划由谁控制”。两者互补，ADR-014 不修改或 supersede ADR-013。
- A1.3 决定 World Fact、Session、Run 与 Memory 生命周期，不得把长期记忆偷塞进本 ADR。
- A1.4 决定 Capability、Approval 与 Side Effect taxonomy，不得把 action proposal 当审批。
- A1.5 决定旧 `app/agent` 命名迁移，不把当前文案生成模块误称为本 ADR 的 Runtime。
- A2 定义可机器验证的语言中立合同；A3/A4 用评测和 Fake Environment 验证边界。

在 Orchestrator 接受本 ADR 前，A1.2 仍为 `in_review`；A1.3–A1.5 与 A2–A5 继续 blocked。

## 11. Trade-off 与后果

我们放弃自由循环和多 Agent 的短期开发便利，换取单一责任主体、确定性停止、可复查 trace、预算封顶和硬门禁不可绕过。

确定性 Workflow 会增加合同与状态机设计成本，但它让模型失败表现为可分类的 proposal/reject/stop，而不是不可解释的生产副作用。

模型升级不会自动改变领域事实或权限；Domain Plane 和用户权威边界保持稳定。

## 12. 非目标

- `No runtime implementation`：不实现 Runtime、controller、schema、数据库表、API 或 UI。
- 不修改腾讯、Route Draw、海拔、RouteBook、导出或存储代码。
- 不调用真实 Provider，不生成真实导出，不接生产流量。
- 不决定 Memory 生命周期、approval taxonomy 或旧目录迁移。
- 不开始 A1.3，不把 ADR Proposed 写成 PASS/Accepted。
- 不把 Draft PR 切换为 Ready for Review，不合并，也不授权部署。

## 13. 触发重评估的条件

满足以下任一条件时，可新开 ADR 重评估，不直接改写本文：

- VeloBench 证明单一逻辑 Agent 无法在预算内完成核心骑前规划，而多主体方案有可重复、显著且安全的收益。
- 确定性工作流无法表达真实高层工具的新失败语义，且扩展合同会破坏关键安全边界。
- 已稳定的合同和至少 30 个评测 case 证明某框架能满足全部门禁，并给出清晰的退出与替换路径。
- 法规、隐私、Provider 合同或生产故障要求更严格的人类审批或更小的 Agent 权限。

## 14. 引用路径

- [ADR-013](./013-为什么区分骑前静态规划与骑中实时导航.md)
- [Agent-First 文档入口](../agent-first/README.md)
- [Phase A 文件级实施规格](../agent-first/phase-a-implementation-spec.md)
- [产品决策 D-P07](../agent-rules/product-decisions.md)
- [VELO Orchestrator State](../../VELO_ORCHESTRATOR_STATE.yaml)
