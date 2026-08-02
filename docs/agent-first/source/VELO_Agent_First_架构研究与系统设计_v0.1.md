# VELO Agent-First 架构研究与系统设计 v0.1

> **定位**：本文不是对既有《VELO 目标领域架构与渐进式迁移蓝图》的简单补丁，而是补齐此前缺失的 Agent Runtime / Harness / Context / Memory / Tool / Permission / Environment / Loop / Evaluation 架构，并重新裁决世界模型、数据库与 Agent 之间的主次关系。
>
> **研究对象**：Anthropic 的 Agent、Context Engineering、Trustworthy Agents 与 Evals 实践；OpenAI 的 Agents SDK、内部 Data Agent 与工程指南；LangGraph 的持久化和 Human-in-the-loop；SWE-agent 的 Agent-Computer Interface；τ-bench / τ²-bench 的端到端状态评测；Letta 的持久记忆；Baidu Maps MCP 的地图工具接口；GraphHopper、Valhalla、BRouter 的路由与 Map Matching；以及 VELO 当前仓库中 RouteBook、腾讯路线、地图页、导出和现有 `app/agent` 的真实实现。

---

# 0. 结论先行

## 0.1 “正经 Agent 开发”不是先选框架，也不是先建巨型数据库

成熟 Agent 系统的共同做法不是：

```text
挑 LangChain / LangGraph
→ 接一个大模型
→ 给很多工具
→ 把数据库全塞进 RAG
→ 让模型循环直到完成
```

而是：

```text
先定义任务与可验证成功状态
→ 划分确定性工作流和模型自主决策
→ 为模型设计专门的环境接口（ACI）
→ 管理每一轮上下文
→ 区分会话状态、运行状态、长期记忆和业务真相
→ 为每个工具设权限、副作用与审批
→ 建立有界循环、停止条件和恢复机制
→ 记录完整 Trace
→ 用端到端环境状态和真实任务持续评测
→ 只有评测证明需要时，才增加框架、多 Agent、数据库和自主性
```

## 0.2 VELO 不是“纯 Agent”，而是受约束的混合式 Agentic System

VELO 的正确架构不是让 LLM 自由规划路线，也不是把所有步骤写成死流程。

它应是：

> **确定性工作流骨架 + 单一主 Agent 的动态决策 + 共享地图环境 + 可验证 Plan 状态。**

模型负责：

- 理解不完整、含糊、会变化的骑行愿望；
- 识别当前最关键的未知信息；
- 选择应该查询哪个骑行对象；
- 在多个可行方案之间做取舍；
- 理解用户拒绝和修改；
- 用自然语言解释方案与代价。

确定性系统负责：

- POI 和语义对象解析后的 ID 校验；
- 腾讯骑行路线调用；
- Canonical Path 拼接；
- 几何连续性；
- 骑行模式；
- 距离、爬升、时间；
- 硬约束；
- 权限；
- 版本与 hash；
- GPX/TCX 导出。

## 0.3 VELO 的真正核心控制面是 Agent Runtime，不是数据库

目标系统应分成五个平面：

```text
1. Interaction Plane
   微信小程序、聊天、地图、用户点击与拖动

2. Agent Control Plane
   Runtime、Harness、Context Compiler、Memory、Policy、Permissions、Tools、Loop

3. Deterministic Domain Plane
   语义查询、腾讯规划、Plan Compiler、Validator、Elevation、Export

4. Canonical Data Plane
   用户、Activity、路线语义、Canonical Path、Evidence、版本、Plan

5. Evaluation & Operations Plane
   Trace、Replay、VeloBench、Shadow、指标、人工审查、回归门禁
```

数据库是第四平面中的持久化机制；它不是 Agent 的“大脑”，也不是 Agent 每轮看到的 Context。

## 0.4 当前仓库中的 `app/agent` 不是目标意义上的 Agent Runtime

当前 `app/agent/segment_writer.py` 是一次性的赛段文案生成调用；`app/agent/tasks.py` 是 RQ 异步任务，直接查询 Segment 并写 `segment_ai_drafts`。它没有：

- 多轮工具循环；
- Session；
- 地图状态；
- Context Compiler；
- 长期记忆；
- Capability；
- Human approval；
- Plan 状态机；
- Trace/Replay；
- Agent eval。

因此建议把现有模块重新命名为：

```text
app/content_ai/
或
app/segment_draft_ai/
```

避免未来真正的 `agent-runtime` 与旧文案功能语义冲突。

## 0.5 当前最重要的工作不是继续建世界模型表，而是建立 Agent 骨架与 VeloBench

正确优先级应改为：

```text
1. 澄清产品与权限边界
2. 建 VeloBench 与可验证环境
3. 定义 MapEvent / MapAction / Tool / AgentAction 合同
4. 建最小 Agent Runtime
5. 用现有 RouteBook + 腾讯 API 做 Shadow Vertical Slice
6. 建共享 Session 与地图工作台
7. 由真实失败推动 Traversal、Knowledge、Memory 和 Road Graph 扩张
```

---

# 1. 研究结论：精英团队如何看待 Agent

## 1.1 Workflow 与 Agent 必须分开

成熟工程实践首先区分：

- **Workflow**：代码预先决定执行路径；
- **Agent**：模型根据环境反馈动态决定下一步与工具使用。

不是所有带 LLM 的系统都需要 Agent。固定、可预测、可验证的步骤应该继续由代码控制；只有无法提前写死、需要理解和取舍的部分交给模型。

VELO 的路线生成天然包含两者：

```text
固定工作流：
加载 Session
→ 编译 Context
→ 权限检查
→ Plan 验证
→ 输出校验
→ Trace

动态 Agent：
是否追问
→ 查询哪个对象
→ 选择哪些候选
→ 如何理解用户拒绝
→ 如何解释取舍
```

## 1.2 Agent 是“模型 + Harness + Tools + Environment”

只讨论模型能力会漏掉大部分生产风险。

同一个模型：

- 在只读工具中很安全；
- 在可发布公共路线的工具中风险巨大；
- 在干净结构化事实环境中表现稳定；
- 在混入外部帖子指令的 Context 中可能被 Prompt Injection；
- 在有停止条件的 Harness 中可控；
- 在无限循环中成本与错误会累积。

因此 VELO Agent 的架构对象不是一个 `Agent` 类，而是：

```text
VeloAgentSystem
├── Model
├── Harness
├── Tool Interface
├── Environment
├── State
├── Permissions
├── Memory
└── Evaluation
```

## 1.3 Context Engineering 比“长 Prompt”更重要

模型每轮看到的所有 Token 都是 Context：

- 系统规则；
- 工具定义；
- 对话历史；
- Session 状态；
- 地图状态；
- 用户记忆；
- 世界事实；
- 工具结果；
- 候选 Plan。

上下文越大不等于越好。生产 Agent 应追求：

> **足以完成当前决策的最小高信号 Context。**

因此 VELO 不应：

```text
查询桃花沟
→ 把桃花沟全部 Evidence、全部帖子、全部 Activity、全部历史版本、全部相邻路线塞进 Prompt
```

而应：

```text
先给一份桃花沟 FactPacket
→ Agent 需要边界证据时再调用 Evidence 工具
→ 需要接入路线时再调用 Planning 工具
→ 需要用户历史时再调用 Rider Context 工具
```

## 1.4 Tool / ACI 的设计可能比 Prompt 更重要

SWE-agent 的核心贡献不是新模型，而是为模型设计更适合它的 Agent-Computer Interface。

对 VELO 而言，Agent 不应操作：

```text
raw_tencent_direction
raw_sql
route_books CRUD
geometry WKT
arbitrary JSONB
```

而应操作：

```text
resolve_ride_object
generate_candidate_plans
revise_plan
validate_plan
select_plan
prepare_export
```

工具应让错误“难以发生”，而不是靠 Prompt 告诉 Agent 小心。

## 1.5 评测必须检查环境最终状态，而不是只看回答

τ-bench 的关键思想是：

```text
Agent 最后说“已完成”
≠
任务真的完成
```

评测应检查对话结束后的数据库或环境状态。

VELO 的任务：

> “从家去汾河绿道，东岸去西岸回，最后回家。”

不能只评“回答听起来是否合理”，还必须检查：

```text
origin 是否为用户选定地点
return_to_origin 是否为 true
core traversal 是否正确
outbound 与 return 是否为不同岸线
所有 provider leg 是否为 bicycle
Plan 是否连续
hard constraint 是否通过
selected revision 与 export hash 是否一致
Agent 是否保存了未经授权的家庭地址
```

---

# 2. 可参考的案例与开源项目

## 2.1 Anthropic Building Effective Agents

可借鉴：

- 简单、可组合模式优先；
- Workflow 与 Agent 分离；
- 单 Agent 先行；
- 环境反馈驱动循环；
- 最大迭代和 Human checkpoint；
- Tool 文档与 ACI 需要大量工程投入；
- 复杂度必须由评测证明价值。

不应照搬：

- 它是跨领域指导，不提供 VELO 的空间对象、地图状态或骑行约束。

## 2.2 OpenAI 内部 Data Agent

这是和 VELO 最接近的“复杂领域上下文 Agent”案例。

它没有把所有表和文档直接塞给模型，而是把 Context 分层：

1. 结构与使用元数据；
2. 人工注释；
3. 生成数据的代码语义；
4. 组织知识；
5. 纠正和非显而易见规则的可编辑 Memory；
6. 运行时实时查询。

VELO 对应为：

```text
1. 路线/Traversal/Plan 的结构化元数据
2. 本地专家审核的语义与边界
3. 几何、海拔、腾讯规划和算法 provenance
4. 本地骑行知识与词汇
5. 用户确认的偏好与纠正
6. 本轮动态规划、天气和地图状态
```

另一个重要原则是权限继承：Agent 只能看用户本来有权访问的数据，而不是获得一份全局超级权限。

## 2.3 SWE-agent

可借鉴：

- 把模型视为一个新的“软件用户”；
- 为模型设计专门命令，而不是暴露人类界面的全部复杂性；
- 反馈格式直接影响 Agent 行为；
- 接口应贴合模型能力；
- Tool/ACI 应大量做失败案例回归。

VELO 对应：

```text
Agent-Map Interface
Agent-Plan Interface
Agent-World Interface
```

## 2.4 τ-bench 与 τ²-bench

τ-bench：

- 对话、工具、领域规则；
- 最终数据库状态；
- `pass^k` 衡量重复运行一致性。

τ²-bench：

- 用户和 Agent 都能操作同一个动态环境；
- 重点测试沟通、协调和共同状态。

VELO 的聊天 + 地图正是 Dual-control：

```text
Agent 高亮候选
用户在地图改起点
Agent 重新规划
用户切换候选
Agent 理解“这个太长”
```

因此 VeloBench 应明显借鉴 τ²-bench，而不是普通聊天 QA benchmark。

## 2.5 LangGraph

可借鉴：

- Checkpoint；
- Thread-scoped state；
- Interrupt；
- 暂停后恢复；
- Human approval；
- 长时间工作流。

适合：

```text
路线资料收集
→ 等人工确认边界
→ 继续几何对比
→ 等权利审核
→ 发布
```

不适合一开始就包住所有在线骑行对话。短时在线 Planning Agent 用普通状态机和 Agent SDK 更透明。

## 2.6 OpenAI Agents SDK TypeScript

提供：

- 内置 Agent Loop；
- Zod 工具 Schema；
- Guardrails；
- Sessions；
- Human-in-the-loop；
- RunState 恢复；
- Tracing；
- MCP；
- TypeScript 类型。

适合作为 VELO 在线 Runtime 的候选，但 SDK 不会替 VELO 设计：

- Context Packet；
- Memory policy；
- Plan 状态机；
- 权限矩阵；
- 地图状态；
- Tool 语义；
- VeloBench。

## 2.7 Letta

可借鉴：

- Memory 与普通对话历史分离；
- Memory block；
- Agent-managed context；
- 跨会话状态。

不建议第一版直接采用“Agent 可自由自改长期记忆”。VELO 的路线和用户隐私场景更适合：

```text
Memory proposal
→ Policy validation
→ 必要时用户确认
→ 生效
```

## 2.8 Baidu Maps MCP

证明了地图能力可以被结构化为 Agent 工具：

- geocode；
- reverse geocode；
- POI search；
- place details；
- directions；
- cycling route；
- matrix；
- weather；
- traffic。

但它只解决通用 LBS，不知道“桃花沟经典骑法”“横岭—二库—阁楼”“汾河两岸训练环线”。

VELO 应借鉴它的地图工具规范，但在上层提供骑行领域工具。

## 2.9 GraphHopper / Valhalla / BRouter

可用于：

- 离线路由研究；
- Map Matching；
- 自行车 Profile；
- Alternative routes；
- Elevation；
- 与腾讯结果做独立对照。

第一版不必替换腾讯地图；更合理的是作为离线评测与未来 Road Graph 的研究底座。

## 2.10 Inspect AI

可用于：

- 多轮 Agent eval；
- Tool-use eval；
- 模型评分；
- 自定义 Scorer；
- 预构建评测组件。

VeloBench 的业务环境和状态 grader 必须自己写，但不必从零做完整评测运行器。

---

# 3. 当前 VELO 代码的 Agent 架构审计

## 3.1 已经具备的确定性能力

仓库已经有：

```text
RouteBook
RouteVersion
腾讯 bicycle direction
手画路线
Snap Preview
WGS84 / GCJ02 转换
GLO-30 海拔
GPX/TCX export
权限和 hash
PostGIS
Redis/RQ
Activity/Trackpoint
Route cognition writer/human review
```

这些是 Agent Environment 的优质工具基础。

## 3.2 当前缺失的 Agent Control Plane

不存在：

```text
Agent Session
Map Session State
Context Compiler
Context Manifest
Tool Registry
Capability Engine
Approval Gate
Agent Run Controller
Run Budget
Typed AgentAction
Typed Tool Error
Memory Manager
Replay
Shadow
VeloBench
```

## 3.3 当前 `app/agent` 应重命名

现在它只是：

```text
Segment props
→ Prompt
→ DeepSeek
→ 文案字符串
→ RQ 写草稿
```

它可以保留，但命名为 `agent` 会误导后续开发，使新的 Agent Runtime 继续直接 import ORM、直接写业务表。

建议迁移：

```text
app/agent/segment_writer.py
→ app/content_ai/segment_draft_generator.py

app/agent/tasks.py
→ app/content_ai/tasks.py
```

## 3.4 产品决策存在一个需要修订的冲突

旧产品不变式写着“不做实时导航/路径规划”，但仓库已经有腾讯静态骑行路线生成；新的 D-P07 又要求确定性服务生成路线。

应新增明确裁决：

```text
VELO 不做：
- 自研全国实时路由引擎
- 骑行中实时导航
- 偏航重规划
- 语音播报

VELO 要做：
- 骑行前静态 Ride Plan 编译
- 调用获批准的地图 Provider 生成 access/connector/return
- 拼接已审核核心 Traversal
- 导出静态 GPX/TCX
```

否则 Agent 调腾讯地图会在产品规则层被错误判定为违反“不做路径规划”。

---

# 4. VELO 的目标 Agent 类型

## 4.1 定义

VELO 应被定义为：

> **Mixed-Initiative Spatial Decision Agent（混合主动式空间决策 Agent）**

它具有四个特点：

1. 用户意图不完整，会通过候选逐渐形成；
2. Agent 和用户都能改变共享地图状态；
3. 成功不仅是回答正确，而是形成可执行 Plan；
4. 世界几何与硬约束可以被确定性验证。

## 4.2 它不是

- 纯聊天机器人；
- 纯 RAG；
- 自动地图点击机器人；
- 通用旅行 Agent；
- LLM 直接生成 GPX；
- 完全自主的长时 Agent；
- 一堆互相讨论的多 Agent。

## 4.3 自主性边界

| 决策 | LLM | 确定性代码 | 用户 |
|---|---:|---:|---:|
| 理解“腿一般” | 主 | 辅 | 可纠正 |
| 是否需要追问 | 主 | 有规则边界 | 回答 |
| 路线对象候选 | 主 | 检索过滤 | 选择/拒绝 |
| 精确几何 | 否 | 主 | 地图可改锚点 |
| 连通性 | 否 | 主 | - |
| 距离/爬升 | 否 | 主 | - |
| 硬约束 | 否 | 主 | 定义 |
| 多方案取舍 | 主 | 提供指标 | 最终决定 |
| 保存长期偏好 | 提议 | Policy | 确认/删除 |
| 导出 | 解释/发起 | 主 | 明确选择 |
| 发布公共路线 | 否 | Reviewer workflow | 管理员/专家 |

---

# 5. 五平面架构

```text
┌──────────────────────────────────────────────────────────┐
│ 1. Interaction Plane                                    │
│ Mini Program / Chat / Map / Elevation / Candidate UI    │
└───────────────────────┬──────────────────────────────────┘
                        │ MapEvent + UserTurn
┌───────────────────────▼──────────────────────────────────┐
│ 2. Agent Control Plane                                  │
│ RunController / ContextCompiler / Memory / Policy       │
│ ToolGateway / ModelRouter / Guardrails / Trace          │
└───────────────────────┬──────────────────────────────────┘
                        │ Typed Domain Commands/Queries
┌───────────────────────▼──────────────────────────────────┐
│ 3. Deterministic Domain Plane                           │
│ Semantic Catalog / Planning / Tencent Adapter           │
│ Geometry / Elevation / Validator / Export               │
└───────────────────────┬──────────────────────────────────┘
                        │ Repositories
┌───────────────────────▼──────────────────────────────────┐
│ 4. Canonical Data Plane                                 │
│ User / Activity / Traversal / Evidence / Plan / Memory  │
└───────────────────────┬──────────────────────────────────┘
                        │ Trace + Fixtures + Outcomes
┌───────────────────────▼──────────────────────────────────┐
│ 5. Evaluation & Operations Plane                        │
│ VeloBench / Replay / Shadow / Metrics / Human Review    │
└──────────────────────────────────────────────────────────┘
```

核心规则：

- Agent Control Plane 不 import SQLAlchemy ORM；
- Agent 只拿 typed refs，不拿数据库自增 ID 之外的内部结构；
- Domain Plane 永远能在没有 LLM 时运行和测试；
- UI 不从 Agent 文本反推地图动作；
- Evaluation 能从固定环境快照重放完整 Run。

---

# 6. 六种状态必须分开

## 6.1 Canonical World State

保存：

- 正式路线对象；
- Traversal；
- Canonical Path；
- Evidence/Claim；
- 动态状态；
- 版本与来源。

Owner：领域服务。

Agent：只读，不能直写。

## 6.2 User State

保存：

- 用户明确资料；
- 保存地点；
- 明确偏好；
- Activity；
- 历史选择与反馈。

Owner：用户/业务服务。

Agent：授权读取；写入必须通过用户资产工具。

## 6.3 Session State

保存当前交互：

- 当前 Intent；
- 当前对象；
- 当前候选；
- 当前选中 Plan；
- 地图锚点；
- 假设；
- 未知项；
- 用户刚刚的 MapEvent。

Owner：Interaction service。

生命周期：一次决策会话。

## 6.4 Agent Run State

保存一次模型循环：

- 当前 step；
- 剩余预算；
- 已调用工具；
- pending approval；
- model output；
- retry 状态；
- stop reason。

Owner：Harness。

它不是用户 Memory，也不是业务 Session。

## 6.5 Long-term Memory

保存跨 Session 有用的用户知识：

- 用户确认的偏好；
- 有证据的偏好假设；
- 过去方案选择/拒绝模式；
- 用户对系统的纠正。

Owner：Memory service + 用户控制。

不保存路线世界事实。

## 6.6 Trace / Eval State

保存：

- Context Manifest；
- Tool call；
- Latency/cost；
- Guardrail；
- 最终状态；
- grader；
- replay ref。

Owner：Evaluation/Ops。

它不能成为业务真相。

---

# 7. Context Compiler

## 7.1 每一轮不是“加载历史”，而是编译 Context

```text
UserTurn/MapEvent
→ Task Mode
→ Session Snapshot
→ Permission Context
→ Relevant Memory
→ Relevant World Facts
→ Plan Summary
→ Prompt Assembly
→ Context Manifest
```

## 7.2 Context Packet

### A. Policy Packet

稳定规则：

- Agent 权限；
- 事实与未知；
- Tool 使用原则；
- 不得输出经纬度；
- 何时确认；
- 何时返回无结果。

### B. Task Playbook Packet

当前模式：

```text
discover
understand
compare
revise
execute
```

每个模式只提供相关启发式和可用动作。

### C. Rider Packet

只提供当前任务相关内容：

- 车型；
- 常用出发点 handle；
- 当前时间预算；
- 相关速度模型；
- 相关路线熟悉度；
- 明确偏好；
- 经过筛选的偏好假设。

精确家庭地址不直接写进 Prompt；使用：

```text
saved_place_ref = sp_home_01
display_label = 太原站附近
```

Domain Tool 内部解析精确点。

### D. Session + Map Packet

```text
focused object
selected candidate
map anchors
viewport
last map event
assumptions
unknowns
```

### E. World Fact Packet

包含：

- Object ref/revision；
- Traversal；
- 最小事实；
- accepted claim summary；
- active state；
- freshness；
- unknown；
- provenance refs。

不含全部原始 Evidence。

### F. Plan Packet

候选概要：

- leg 结构；
- metrics；
- validation；
- tradeoff tags；
- unresolved issues；
- geometry ref。

## 7.3 Just-in-time Retrieval

首轮只提供：

- 用户；
- Session；
- 城市；
- 当前焦点；
-少量检索结果。

Agent 根据需要调用：

```text
get_ride_object_fact_packet
get_route_evidence_summary
get_rider_familiarity
get_candidate_plan_details
```

## 7.4 Context Manifest

每次模型调用保存：

```text
manifest_id
run_id
prompt_policy_version
playbook_version
tool_registry_version
session_version
memory_item_ids
fact_packet_ids
plan_revision_ids
omitted_sections
token_counts
created_at
```

这是调试“Agent 为什么错”的关键。

---

# 8. Memory Architecture

## 8.1 Working Memory

就是 Session 当前状态，不需要再复制一份文本记忆。

## 8.2 Explicit Memory

用户明确说或确认：

```text
“以后默认从太原站附近出发。”
“我骑公路车，不走明显土路。”
```

可以长期保存。

## 8.3 Inferred Preference Hypothesis

例如：

```text
“用户可能偏好完整长爬”
```

必须保存：

```text
hypothesis
evidence_count
supporting_event_ids
contradicting_event_ids
confidence_state
last_observed_at
decay_policy
user_confirmation_status
```

它不是永久真相。

## 8.4 Episodic Memory

保存高价值事件摘要：

```text
何时
用户想做什么
看过哪些候选
拒绝原因
最终选择
是否导出
是否实际骑行
骑后预期差
```

检索时按当前路线、城市和任务相关性取少量事件。

## 8.5 Correction Memory

用户纠正系统：

```text
“阁楼不是那个 POI。”
“我说的二库是汾河二库。”
```

这类 Memory 很有价值，但如果涉及公共世界事实，应：

```text
先存个人纠正
→ 同时生成 World Knowledge Proposal
→ 审核后再影响其他用户
```

## 8.6 Procedural Memory

Agent 从失败中学到的系统级经验不应由线上 Agent 自改 Prompt。

正确流程：

```text
Trace failure
→ Eval triage
→ Tool/Prompt/Policy patch
→ version
→ regression
→ release
```

## 8.7 Memory Write Gate

Agent 只能调用：

```text
propose_memory_item
```

Policy 决定：

- 自动保存；
- 需要确认；
- 只保留 Session；
- 拒绝；
- 转成世界知识 proposal。

---

# 9. Agent-Computer Interface：工具体系

## 9.1 Tool Contract

每个工具必须定义：

```typescript
interface VeloTool<I, O> {
  name: string
  description: string
  inputSchema: ZodSchema<I>
  outputSchema: ZodSchema<O>

  capability: Capability
  sideEffect: "read" | "ephemeral" | "personal" | "external" | "canonical"
  approval: "never" | "policy" | "always"
  idempotency: "required" | "optional" | "none"

  timeoutMs: number
  retryPolicy: RetryPolicy
  dataClassification: DataClassification
  freshnessPolicy?: FreshnessPolicy
}
```

## 9.2 第一版只暴露少量高层工具

### Context / Resolve

```text
resolve_place
resolve_ride_object
get_relevant_rider_context
```

### World

```text
search_ride_objects
get_ride_object_fact_packet
get_area_structure
```

### Planning

```text
compile_ride_intent
generate_candidate_plans
validate_plan
revise_plan
compare_plans
```

### Execution

```text
select_plan
prepare_export
save_start_place
propose_memory_item
```

约 12—15 个工具足够。

## 9.3 不能暴露给在线 Agent 的工具

```text
raw_tencent_api
raw_sql
publish_traversal
accept_claim
activate_dynamic_state
write_geometry
direct_gpx_generator
arbitrary_routebook_update
```

## 9.4 Provider 只活在 Domain Plane

Agent：

```text
generate_candidate_plans(intent_id)
```

Planning service 内部：

```text
Canonical Path
+ Tencent Bicycle Provider
+ Connector rules
+ Geometry assembler
+ Validator
```

这样以后换腾讯/百度/GraphHopper，不改 Agent Prompt 和工具合同。

## 9.5 Tool Output 需要“渐进披露”

默认返回：

```json
{
  "status": "ok",
  "summary": {},
  "refs": [],
  "warnings": [],
  "unknowns": [],
  "next_page_token": null
}
```

避免返回完整 Provider JSON、几千个坐标和全部 Evidence。

---

# 10. 地图是共享环境，不是图片

## 10.1 MapEvent（用户→系统）

```text
origin_pinned
destination_pinned
ride_object_selected
candidate_switched
leg_selected
elevation_range_selected
viewport_changed
anchor_removed
plan_confirmed
```

## 10.2 MapAction（Agent→前端）

```text
fit_bounds
show_area
highlight_object
show_candidate_set
highlight_plan_leg
dim_objects
show_anchor
show_warning_scope
```

## 10.3 State Reducer

所有 MapEvent 和 MapAction 都经过 deterministic reducer，得到当前地图状态。

Agent 不直接“控制前端”，只产生声明式动作。

## 10.4 为什么这属于 Dual-control

用户和 Agent 都能修改共享状态：

```text
Agent 推荐 A/B/C
→ 用户点击 B
→ Session.selected = B
→ 用户拖动起点
→ Plan 失效
→ Agent 看到结构化事件
→ 调 revise_plan
→ 新 revision
```

VeloBench 必须模拟双方动作。

---

# 11. Permissions 与 Human Control

## 11.1 Capability

```text
world.read
user_context.read_authorized
session.write
plan.draft.create
plan.draft.revise
plan.select
export.request
saved_place.create
memory.propose
```

在线 Planning Agent 永远没有：

```text
world.publish
claim.accept
route.activate
dynamic_state.verify
user_data.admin_read
```

## 11.2 Side-effect Level

### Level 0：只读

自动允许。

### Level 1：Session 临时状态

自动允许，可撤销。

### Level 2：个人可逆资产

例如保存地点、保存草稿，需要明确用户意图；部分操作弹确认。

### Level 3：外部/不可逆

导出、分享、发送，必须确认或明确当前指令。

### Level 4：公共世界真相

在线 Agent 禁止。

## 11.3 Pass-through Permission

Agent 不获得超级账号。

Domain API 按：

```text
user identity
service identity
capability
data scope
```

共同判断。

## 11.4 精确位置

精确家庭位置：

- 默认不进入模型 Context；
- Context 只见 handle；
- Tool 内解析；
- 用户可查看和删除；
- Shadow/Eval 默认去标识化。

---

# 12. Environment Isolation

## 12.1 Production Planning Environment

允许：

- typed domain APIs；
- authorized user context；
- Session；
- Planning。

禁止：

- shell；
-任意网络；
- raw web；
- SQL；
- public write。

## 12.2 Curation Environment

允许：

- 搜索/读取外部来源；
- 几何对比；
- candidate；
- Evidence/Claim proposal。

禁止：

- 直接 published；
- 访问无关用户私有数据；
- 把外部页面指令当作系统指令。

## 12.3 Eval Environment

要求：

- 固定数据库 fixture；
- 固定时间；
- 固定地图 Provider 或录制响应；
- 无真实副作用；
- 可重置；
- 可重复；
- 可检查最终状态。

## 12.4 Shadow Environment

真实请求的去标识化副本：

- Agent 运行；
- 不向用户显示；
- 不产生副作用；
- 与当前产品结果比较。

## 12.5 Prompt Injection

外部网页/UGC 永远标记为 untrusted data。

Curation Agent：

- 无公共写权限；
- 外部内容与系统指令分区；
- 提取结果必须 schema 化；
- 所有 action tool 调用需 Tool Guardrail；
- 高风险来源在隔离 Context 中处理。

---

# 13. 在线 Agent Loop

## 13.1 顶层状态机

```text
RECEIVE_EVENT
→ LOAD_STATE
→ COMPILE_CONTEXT
→ DECIDE
   ├─ ASK_ONE_QUESTION
   ├─ CALL_TOOL
   ├─ PRESENT_CANDIDATES
   ├─ REQUEST_CONFIRMATION
   ├─ FINALIZE
   └─ NO_RESULT
→ APPLY_OBSERVATION
→ VALIDATE
→ UPDATE_SESSION
→ TRACE
→ RESPOND
```

## 13.2 决策流程

```text
UNDERSTAND
→ 是否缺少会改变候选的关键信息？
   ├─ 是：只问一个高信息量问题
   └─ 否
→ DISCOVER
→ MATERIALIZE PLAN
→ DETERMINISTIC VALIDATE
   ├─ fail：修正一次或换候选
   └─ pass
→ PRESENT
→ WAIT USER
   ├─ reject：更新本轮偏好，重新 discover
   ├─ revise：修改 Plan
   ├─ select：seal
   └─ pause
→ EXPORT
```

## 13.3 Budget

每个 Run 有：

```text
max_model_turns
max_tool_calls
max_plan_generations
max_same_tool_retries
wall_clock_deadline
token_budget
cost_budget
```

触发预算后：

- 输出当前进度；
- 返回明确未知/失败；
- 或保存可恢复状态；
- 不无限反思。

## 13.4 Error Taxonomy

```text
PLACE_AMBIGUOUS
RIDE_OBJECT_AMBIGUOUS
NO_PUBLISHED_TRAVERSAL
NO_BICYCLE_ROUTE
PLAN_DISCONNECTED
HARD_CONSTRAINT_FAILED
ROUTING_PROVIDER_TIMEOUT
STALE_REVISION
PERMISSION_DENIED
APPROVAL_REQUIRED
CONTEXT_STALE
BUDGET_EXCEEDED
```

Agent 根据错误码决策，不解析供应商随机错误文案。

## 13.5 不要默认 Evaluator-Agent Loop

路线几何和硬约束由代码验证。

只有语言质量、复杂研究或候选解释确实能被明确 rubric 改进时，才使用 evaluator-optimizer；且必须有次数上限和 eval 证据。

---

# 14. 离线路线 Curation Loop

```text
SOURCE_INGESTED
→ RIGHTS_CHECK
→ EXTRACT_EVIDENCE
→ GEOMETRY_CANDIDATE
→ MAP/ROUTE_COMPARE
→ CLAIM_PROPOSAL
→ CONFLICT_ANALYSIS
→ HUMAN_INTERRUPT
→ APPROVE / REJECT / REQUEST_MORE
→ PUBLISH REVISION
→ ACTIVITY/EVAL CHECK
```

它需要：

- durable checkpoint；
- 几天后恢复；
- 人审；
- 幂等副作用；
- 版本锁定。

这是 LangGraph、Temporal 或类似 durable workflow 的适用场景。

在线 Planning Agent 与 Curation Workflow 必须：

- 不同身份；
- 不同工具；
- 不同权限；
- 不同 Prompt；
- 不同数据库 writer。

---

# 15. Prompt Architecture

## 15.1 四层 Prompt

### Immutable Policy

权限、事实、未知、隐私、工具、审批、停止条件。

### Planning Playbook

VELO 的骑行决策启发式：

- Route identity vs Ride Plan；
- 门到门；
- 如何询问；
- 如何处理拒绝；
- 如何展示 0—3 候选；
- 主流→反馈→可信小众；
- 不确定性表达。

### Task-mode Instructions

当前状态允许做什么：

```text
当前为 REVISE 模式
只能修改 selected plan
不得重新创建公共路线对象
```

### Dynamic Packets

Context Compiler 生成。

## 15.2 版本

```text
policy_version
playbook_version
context_compiler_version
tool_registry_version
output_schema_version
model_policy_version
```

Prompt 改动必须跑 VeloBench。

---

# 16. TypeScript 与技术栈裁决

## 16.1 不应该重写现有 Python 后端

保留 Python/FastAPI：

- PostGIS；
- 路线几何；
- 腾讯 Adapter；
- Elevation；
- GPX；
- Activity；
-事务；
- RQ。

## 16.2 新 Agent Control Plane 推荐 TypeScript

候选栈：

```text
Node.js 22+
TypeScript
@openai/agents
Zod
Fastify
OpenAPI-generated client
OpenTelemetry
PostgreSQL
Redis
```

理由：

- Agent 输入输出本质是 JSON/事件；
- Zod 做工具与 MapAction runtime validation；
- 前端地图类型可共享；
- SDK 提供 Loop、Session、Guardrails、HITL、Tracing；
- Agent runtime 可独立替换，不污染 Python 领域逻辑。

## 16.3 但先以 Shadow Service 进入

不要立即让生产依赖 Node 服务。

```text
agent-runtime-ts
→ 调 FastAPI internal APIs
→ 跑 Shadow + VeloBench
→ 达到门槛后 feature flag
→ 再成为用户路径
```

## 16.4 Framework 使用决策

| 组件 | 结论 |
|---|---|
| OpenAI Agents SDK TS | 在线 Runtime 首选候选 |
| LangChain | 不作为领域架构地基 |
| LangGraph | 长时 Curation/HITL 需要时使用 |
| Letta | 借鉴 Memory，不首期引入 |
| MCP | 外部互操作；内部首期直接 typed API |
| AutoGen/OpenHands | 学习 Runtime/环境隔离，不直接采用 |
| Inspect AI | VeloBench 执行框架候选 |
| pgvector | Evidence 规模与检索 eval 证明需要后再加 |

## 16.5 Model Selection

流程：

```text
先用最强可用模型建立能力上限
→ VeloBench 建 baseline
→ 对较小/便宜模型做同套 eval
→ 按任务路由
```

不能先按单次 token 价格选模型。

---

# 17. 数据库：Agent 需要什么，而不是什么都建

## 17.1 五类存储

```text
业务真相：现有/新领域表
Session：当前地图与决策
Run checkpoint：一次 Agent 执行
Memory：跨会话用户知识
Trace/Eval：调试和质量
```

## 17.2 最小 Agent 表

```text
agent_sessions
agent_session_events
agent_runs
agent_run_checkpoints
agent_context_manifests
agent_context_manifest_items
agent_tool_calls
agent_approval_requests
agent_memory_items
agent_memory_evidence
agent_feedback_events
```

如果 Trace 全部进入 OpenTelemetry 后端，数据库只保留 trace ref 和核心 audit，不复制所有 span。

## 17.3 不应存

```text
agent_context_blob
agent_everything_jsonb
agent_route_facts
agent_copy_of_user
agent_copy_of_plan
```

Agent 表只存引用、运行与记忆；世界事实继续由 Domain owner 管理。

## 17.4 新表门槛

任何新表必须拥有：

1. 独立语义；
2. 独立生命周期；
3. Writer；
4. Reader；
5. 权限；
6. 至少两个真实场景；
7. 自动测试；
8. 删除/迁移策略；
9. 可观测规模触发器。

---

# 18. VeloBench

## 18.1 Case Schema

```json
{
  "case_id": "taiyuan_fenhe_dual_bank_001",
  "environment_fixture": "...",
  "user_profile": "...",
  "initial_session": "...",
  "conversation_script": [],
  "user_map_actions": [],
  "allowed_capabilities": [],
  "expected_end_state": {},
  "forbidden_actions": [],
  "language_rubric": {},
  "max_budget": {}
}
```

## 18.2 评测组

### Intent

- “骑桃花沟” vs “去桃花沟景区”；
- “从这儿下”；
- “明天去哪儿”。

### Dual-control Map

- 用户改起点；
- 切候选；
- 选对象后说“这个”；
- Agent 地图动作与文字一致。

### Tool

- 选对高层工具；
- 不调 raw provider；
- bicycle mode；
- 参数与 ID 正确；
- 不重复调用。

### End State

- Origin；
- Core Traversal；
- Leg；
- Return；
- Revision；
- Validation；
- Export hash。

### Constraint

- 时间；
- 公路车路面；
- 回原点；
- 必经对象；
- 零方案诚实。

### Permission

- 未经确认不存精确地点；
- 不发布公共路线；
- 不越权读数据；
- 不绕过 validator。

### Memory

- 保存明确偏好；
- 不把一次表达永久化；
- 能纠正；
- 不复制世界事实。

### Prompt Injection

- 外部帖子要求 Agent 忽略规则；
- POI 名称或介绍含指令；
- Tool 输出含恶意文本。

### Knowledge

- 引用错误对象；
- 反方向知识；
- 过期状态；
- 主观当事实。

### Export

- 地图 geometry hash；
- sealed revision；
- GPX parse；
- 设备导入。

## 18.3 Grader

```text
Code grader：环境和数据库状态
Trace grader：工具、权限、循环
LLM grader：解释和沟通
Human expert：路线合理集合
Real ride：骑后预期差
```

## 18.4 指标

```text
final_state_success
hard_constraint_violation_rate
geometry_pass_rate
tool_selection_accuracy
redundant_tool_call_rate
permission_violation_rate
map_text_mismatch_rate
unsupported_fact_rate
memory_write_precision
no_result_honesty
latency
cost
pass^k
```

## 18.5 第一批 Case

先做 30—50 个，不追求几千条：

- 汾河绿道；
- 桃花沟；
- 横岭；
- 一线天；
- 天龙山；
- 起点修改；
- 候选全拒绝；
- 零可行；
- 同名 POI；
- Provider timeout；
- 用户地图与文本冲突；
- 导出后再修改。

---

# 19. 分阶段开发路线

## Phase A：架构裁决与 Eval-first

- 修订“不做路径规划”的边界；
- 重命名旧 `app/agent`；
- 定义 Tool、MapEvent、MapAction、AgentAction、Error Schema；
- 建 VeloBench v0；
- 建确定性 fake environment。

退出门槛：

- 30+ Case；
- 所有 Case 有 end-state grader；
- 不调用真实腾讯也能重复运行。

## Phase B：最小 Shadow Agent

- TypeScript Runtime；
- 一个 Agent；
- 无长期 Memory；
- 6—8 个只读/Plan draft 工具；
- 现有 RouteBook/Tencent/elevation/export adapter；
- Trace + Context Manifest。

场景：

```text
给定起点
→ 选择一条现有官方路线
→ 腾讯接入/返程
→ 生成候选
→ 验证
→ 不真实导出
```

## Phase C：Shared Map Session

- Event store；
- State reducer；
- User MapEvent；
- Agent MapAction；
- 页面恢复；
- Dual-control eval。

## Phase D：Curated Traversal + Plan Compiler

- 10—20 条太原高质量 Traversal；
- 高层 `generate_candidate_plans`；
- `revise_plan`；
- `validate_plan`；
- sealed revision；
- 独立 Plan export。

## Phase E：Personal Memory

先只上：

- 保存起点；
- 用户明确偏好；
- 选择/拒绝 episode。

Inferred preference 先 shadow，准确率达到门槛再影响推荐。

## Phase F：Offline Curation Workflow

- Source/Evidence；
- Geometry compare；
- Human interrupt；
- publish gate；
- LangGraph/Temporal 评估。

## Phase G：Activity Feedback

- Activity ↔ Plan；
- 熟悉度；
- 实际时间；
- 偏离；
- 预期差；
- Memory/World proposal。

## Phase H：Road Graph /受约束组合

只有当现有 Traversal + Provider 无法覆盖大量真实需求时才进入。

---

# 20. 需要新增或修订的 ADR

1. VELO 是 Mixed-Initiative Spatial Decision Agent；
2. Workflow skeleton + bounded single Agent；
3. Agent Runtime 与 Domain Plane 分离；
4. Context Packet 与 Context Manifest；
5. Session / Run / Memory / World / Trace 分离；
6. Tool ACI 与原始 Provider 隔离；
7. Capability + Side-effect + Approval；
8. MapEvent / MapAction 双向共享环境；
9. VeloBench end-state 与 pass^k；
10. 在线 Planning 与离线 Curation 两套 Loop；
11. 静态 Ride Plan 允许，实时导航/自研路由继续禁止；
12. TypeScript Agent Runtime Shadow-first；
13. Agent Memory 只能存用户/交互，不复制世界真相；
14. 外部内容一律视为 untrusted data。

---

# 21. 明确禁止的反模式

- 先建完整数据库再接 Agent；
- 一个 Prompt 处理全部模式；
- 把全部聊天历史永远回填 Context；
- Agent 自由修改长期偏好；
- Agent 直连腾讯低级 API；
- Agent 直写 ORM；
- 80 个重叠工具；
- 多 Agent 互相讨论代替 Validator；
- 将工具异常作为自然语言让模型猜；
- 无最大轮次；
- 只看最终文字；
- Eval 使用生产环境；
- 外部帖子和系统指令混入同一权限域；
- 把模型 Context 当数据库；
- 把向量库当世界真相；
- 把 Trace 当业务数据；
- 使用 LangGraph 只因为任务“有循环”；
- 使用 TypeScript 只因为“Agent 都流行 TypeScript”。

---

# 22. 最终架构判断

VELO 的长期优势不是：

```text
数据库表最多
Prompt 最长
Agent 数量最多
框架最新
```

而是：

```text
1. 本地骑行语义比通用地图更准确
2. Agent-Map Interface 比通用聊天更自然
3. Plan 的最终状态可以被确定性验证
4. Context 可以精确解释模型当时看到了什么
5. 权限和副作用受到系统而非 Prompt 控制
6. 用户和 Agent 能共同修改同一个空间环境
7. 每次失败都能变成可重复 Eval
8. 模型、框架和 Prompt 可以替换，业务状态不变
```

一句话：

> **VELO 不应该先建设一个“聪明模型所需的巨大数据库”，而应该建设一个对模型友好、对用户可控、对结果可验证的骑行决策环境。数据库服务于这个环境；Context Compiler 决定模型看什么；Tool ACI 决定模型能做什么；Harness 决定它如何循环和停止；VeloBench 决定一切复杂度是否真的有价值。**


---

# 附录：本轮重点研究来源

## 官方工程实践

- Anthropic — *Building effective agents*
- Anthropic — *Effective context engineering for AI agents*
- Anthropic — *Trustworthy agents in practice*
- Anthropic — *Demystifying evals for AI agents*
- OpenAI — *A practical guide to building agents*
- OpenAI — *Inside OpenAI’s in-house data agent*
- OpenAI Agents SDK for TypeScript — Sessions / Guardrails / Human-in-the-loop / Tracing
- LangGraph — Persistence / Interrupts / Subgraph state

## 研究与 Benchmark

- SWE-agent — *Agent-Computer Interfaces Enable Automated Software Engineering*
- τ-bench — *A Benchmark for Tool-Agent-User Interaction in Real-World Domains*
- τ²-bench — *Evaluating Conversational Agents in a Dual-Control Environment*

## 开源项目

- `SWE-agent/SWE-agent`
- `baidu-maps/mcp`
- `UKGovernmentBEIS/inspect_ai`
- `letta-ai/letta`
- `All-Hands-AI/OpenHands`
- GraphHopper
- Valhalla
- BRouter

> 这些来源提供的是通用原则、运行时组件、地图工具接口和评测方法；没有任何一个项目能够直接替代 VELO 的本地骑行语义、Plan Compiler、共享地图 Session 和真实骑行反馈闭环。
