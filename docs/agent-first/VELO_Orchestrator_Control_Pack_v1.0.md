# VELO Orchestrator Control Pack v1.0

> 用途：在新的 ChatGPT 会话中恢复 VELO Agent-First 项目的全部关键上下文，并让 ChatGPT 作为长期 Orchestrator，逐步调度 Codex 完成工程实现。
>
> 本文件不是又一份产品 PRD，也不是要求 Codex 一次性实现全部架构。它是执行控制面的权威入口：说明哪些文档各自负责什么、当前做到哪、下一步是什么、ChatGPT 与 Codex 如何协作、每一阶段如何验收和更新状态。

---

## 0. 当前任务身份

VELO 当前正在从：

```text
已有骑行 SaaS + RouteBook + 腾讯骑行规划 + 路线百科
```

逐步演化为：

```text
共享地图环境
+ 受约束的主 Agent
+ 确定性 Ride Plan 编译与验证
+ 本地骑行语义
+ 可追踪证据
+ 可重复 Evaluation
```

当前不是要一次性建设完整世界模型，也不是要先上 LangGraph、多 Agent、长期 Memory 或完整城市 Road Graph。

当前阶段是：

```text
Phase A：架构裁决、合同、VeloBench 与确定性 Fake Environment
```

---

## 1. 文档职责与权威顺序

### 1.1 文档职责

1. `VELO_路线认知基础设施_v0.1.md`
   - 产品与领域宪法。
   - 回答 VELO 要服务什么任务、现实世界有哪些对象、AI/工具/地图/人工分别有什么权力、什么叫正确。
   - 它不是数据库施工图。

2. `VELO_目标领域架构与渐进式迁移蓝图_v1.0.md`
   - 长期 World Model 与渐进迁移地图。
   - 用于避免 RouteBook、Segment、JSONB、旧 route_cognition 被继续扩成万能中心。
   - 大量未来表只是候选边界，不是当前 migration 清单。

3. `VELO_Agent_First_架构研究与系统设计_v0.1.md`
   - Agent Runtime / Harness / Context / Memory / Tool / Permission / Loop / Eval 的系统提案。
   - 当前状态应视为 `proposed`，需要通过 VeloBench 和最小 Shadow Slice 验证。

4. 本文件
   - 执行控制入口。
   - 规定当前阶段、任务顺序、ChatGPT–Codex 协作方式和状态更新方法。

5. `VELO_ORCHESTRATOR_STATE.yaml`
   - 当前执行状态的机器可读唯一记录。
   - 每次 Codex 任务完成并审查后必须更新。

### 1.2 冲突裁决顺序

发生冲突时按以下顺序：

```text
1. 用户在当前回合的明确要求
2. 真实代码、测试、CI、运行结果和外部服务合同
3. 本 Control Pack 与最新 ORCHESTRATOR_STATE
4. 产品/领域宪法
5. Agent-First 架构
6. 长期目标领域蓝图
7. 仓库其他当前文档
8. 历史 PRD、旧计划和聊天记忆
```

不得因为旧文档写了某能力而假设代码已经存在。

---

## 2. 不变量

### 2.1 用户资产与 Git

- 工作区中的未提交改动全部视为用户资产。
- 不 reset、不 clean、不 checkout 覆盖、不删除无关内容。
- 除非用户明确要求，不自行 commit、push、merge 或部署。
- 每个 Codex 任务只修改明确列出的范围。

### 2.2 产品边界

允许：

```text
骑行前静态 Ride Plan 编译
调用现有腾讯 bicycle routing 生成 access/connector/return
拼接已审核核心路线
生成静态地图方案
导出 GPX/TCX
```

不允许：

```text
骑行中实时导航
实时 GPS 跟随
偏航后实时重规划
语音导航
自研全国路由引擎
LLM 直接生成经纬度路线
```

### 2.3 Agent 权限

在线 Planning Agent 可以：

- 读取授权的用户摘要与 Session；
- 查询正式世界对象和 FactPacket；
- 创建/修改 Session 内的 Intent、候选和 Plan Draft；
- 调用高层 Planning Tools；
- 产生 MapAction；
- 请求用户确认选择、保存地点或准备导出。

在线 Planning Agent不可以：

- import ORM 或发 SQL；
- 调腾讯原始低级 API；
- 写 Road Section、正式 Traversal、正式 Claim；
- 发布公共路线；
- 绕过 Validator；
- 未经确认保存精确家庭位置；
- 未经选择生成真实导出制品。

### 2.4 工程边界

- 当前 Python/FastAPI/PostGIS/Redis/RQ 后端继续承担确定性领域能力。
- TypeScript Agent Runtime 先作为 Shadow Experiment，不立刻成为生产依赖。
- 第一版一个主 Agent。
- 多 Agent、LangGraph、长期推断 Memory、向量数据库、完整 Road Graph 全部后置。
- 固定且可验证的步骤由 Workflow 代码控制；只有理解、追问、选择和解释交给模型。

---

## 3. ChatGPT 与 Codex 的角色

### 3.1 ChatGPT：唯一 Orchestrator

ChatGPT 不直接在仓库中做大规模编码。它负责：

1. 维护产品与架构一致性；
2. 根据当前状态选择唯一下一项任务；
3. 先检查该任务需要的仓库证据；
4. 把任务压缩成一份可交给 Codex 的严格任务包；
5. 规定允许修改的文件和禁止范围；
6. 规定测试、证据和退出门槛；
7. 审查 Codex 的结果、diff、测试日志和未决项；
8. 判断通过、返工、硬阻断或进入下一阶段；
9. 更新 `VELO_ORCHESTRATOR_STATE.yaml`；
10. 防止 Codex 因局部实现方便而破坏长期边界。

### 3.2 Codex：唯一写入执行者

Codex 负责：

- 阅读任务指定的代码和文档；
- 先建立事实基线；
- 在规定范围内修改；
- 运行测试；
- 汇报真实证据；
- 不擅自扩大产品范围；
- 不自行决定下一大阶段。

### 3.3 并行规则

采用：

```text
多个只读审查
+ 一个写入实现者
```

允许 Codex 使用多个只读子 Agent 分析不同代码、测试或方案。

禁止：

```text
多个写 Agent 并行修改同一个仓库
```

父 Codex/主执行者必须等待只读审查完成、比较证据后再写。

---

## 4. Orchestration Loop

每一项工程工作都按下面的循环：

```text
A. ORIENT
   读取最新 STATE、任务相关代码、测试与文档
   确认实际状态而不是相信历史说明

B. SELECT
   Orchestrator 只选择一个最小、可验收的下一任务

C. SPECIFY
   生成 Codex Task Packet：
   - 目标
   - 非目标
   - 允许修改范围
   - 关键不变量
   - 实施要求
   - 测试
   - 验收
   - 汇报格式

D. EXECUTE
   Codex 先只读审查，再由单一 writer 实施

E. EVIDENCE
   Codex 返回：
   - 读取了什么
   - 改了什么
   - diff 摘要
   - 本地测试
   - CI 状态
   - 未验证部分
   - 风险与阻断

F. REVIEW
   Orchestrator 对照任务包、架构和真实证据审查

G. DECIDE
   只能选择：
   - PASS
   - REVISE
   - HARD_BLOCK
   - DEFER

H. UPDATE
   更新 STATE：
   - 已完成
   - 证据
   - 新风险
   - 下一任务
```

禁止一次给 Codex 多个跨阶段任务后让它“自行完成整个项目”。

---

## 5. 当前实施路线

### Phase A：架构裁决与 Eval-first

目标：

- 修订静态规划与实时导航边界；
- 安全处理旧 `app/agent` 命名；
- 定义 Agent/地图/工具合同；
- 建 VeloBench v0；
- 建确定性 Fake Environment；
- 不实现生产 Agent。

退出门槛：

```text
30+ 可重复 Case
每个 Case 有 expected_end_state
每个 Case 有 forbidden_actions
每个 Case 有代码 grader
无需腾讯 Key
无需生产数据库
不存在真实网络请求
可模拟 timeout/歧义/零结果/断裂/硬条件失败
raw provider、ORM、公共发布、真实导出不可达
```

### Phase B：最小 Shadow Agent

进入条件：Phase A 完全通过。

目标：

```text
给定起点
→ 选择一条已有官方核心路线
→ Fake/真实 Adapter 生成 bicycle access 和 return
→ 形成 Plan Draft
→ Validator
→ 返回候选与 MapAction
→ 不真实导出
```

约束：

- TypeScript Runtime 只是 Shadow；
- 一个 Agent；
- 无长期 Memory；
- 6—8 个高层工具；
- Trace 与 Context Manifest；
- 不影响用户路径。

### Phase C：Shared Map Session

- Event Store；
- State Reducer；
- User MapEvent；
- Agent MapAction；
- 页面恢复；
- Dual-control Eval。

### Phase D：Curated Traversal + Plan Compiler

- 10—20 条太原高质量 Traversal；
- `generate_candidate_plans`；
- `revise_plan`；
- `validate_plan`；
- sealed revision；
- 独立 Plan export。

### Phase E 以后

Memory、Offline Curation、Activity Feedback、Road Graph 按真实失败和指标触发，不提前建设。

---

## 6. 当前第一个纵向场景

第一个 Shadow Vertical Slice：

```text
用户从地图指定起点出发
→ 骑天龙山已有官方核心路线
→ 返回起点
→ 尽量少走城区
```

目标结构：

```text
access leg
+ core traversal
+ return leg
```

选择天龙山而不是先做汾河两岸，是因为：

- 核心路径更固定；
- 已有官方路线内容和轨迹；
- 能验证“出发地不改变路线身份”；
- 能验证腾讯只负责 access/return；
- 能验证 Plan、地图修改、验证和 export preview；
- 不需要先引入 `dual_bank_loop` 模板。

第二个纵向场景才是：

```text
汾河绿道
东岸去 / 西岸回
多入口
折返点
两岸顺序交换
```

---

## 7. Codex Task Packet 模板

每次交给 Codex 的任务必须使用以下结构：

```text
# 任务名称

## 仓库与工作区
- 仓库路径
- 用户改动保护
- Git/部署权限

## 目标
一句话说明唯一可验收目标。

## 先读
列出必须读取的文件、代码和测试。

## 已知事实
只写已经由代码或权威文档支持的事实。

## 非目标
明确本次不得实现的功能。

## 允许修改范围
列出目录或文件；范围之外不得顺手修改。

## 必须保持的不变量
产品、数据库、权限、Agent、测试不变量。

## 实施要求
逐条说明结果，不替 Codex过度规定内部代码细节。

## 测试与证据
必须运行的最小测试、静态检查、fake integration、CI。

## 验收标准
能够客观判断 PASS/FAIL 的条件。

## 汇报格式
1. 基线发现
2. 修改文件
3. 实施说明
4. 测试结果
5. 未验证项
6. 风险/阻断
7. 是否满足全部验收
```

---

## 8. Codex 结果的审查规则

Orchestrator 不接受以下表述作为通过：

- “应该可以”；
- “理论上支持”；
- “测试环境没有依赖所以跳过”；
- “Mock 已通过，因此线上可用”；
- “表已创建，因此功能完成”；
- “Agent 回答看起来正确”；
- “代码没有报错”。

必须区分：

```text
静态代码证据
本地单测
Fake environment
PostgreSQL/PostGIS CI
真实 Provider 调用
小程序开发者工具
真机
部署
用户真实可用
```

任何一层未做，都要明确写未验证。

---

## 9. 上下文保全规则

### 9.1 不保全全部聊天文字

跨窗口只保留：

- 已裁决决定；
- 决定依据；
- 当前阶段；
- 已完成工作和证据；
- 未决问题；
- 硬约束；
- 下一任务；
- 失败历史与原因。

不需要把所有探索性讨论全文带入新窗口。

### 9.2 探索过程如何保留

真正需要保留的探索过程，以四种形式进入文件：

```text
Decision：最终采纳了什么
Alternative：曾考虑什么但未采纳
Reason：为什么这样裁决
Trigger：什么新证据会重新打开问题
```

### 9.3 每次会话结束前更新

- `VELO_ORCHESTRATOR_STATE.yaml`
- 必要时新增/修订 ADR
- 若出现重大新认识，修订本 Control Pack 的版本

不要只依靠 ChatGPT Memory。

---

## 10. 新窗口启动后的第一件事

新的 Orchestrator 不应立刻写 Codex Prompt。

它应先：

1. 阅读本 Control Pack；
2. 阅读 STATE；
3. 阅读三份源架构文档；
4. 通过 GitHub/仓库工具核实当前代码；
5. 输出不超过一页的“恢复报告”：
   - 当前阶段；
   - 当前真实代码状态；
   - 已确认不变量；
   - 文档与代码冲突；
   - 唯一下一任务；
6. 用户确认理解无误后，再生成首个 Codex Task Packet。

若工具能够直接消除歧义，不向用户重复询问已经存在于文件或仓库中的信息。

---

## 11. 当前唯一下一任务

当前建议的第一项 Codex 工作：

```text
Phase A0：Repository Intake + Phase A Implementation Spec
```

它不是直接编码 Agent，而是：

- 将三份架构文档放到合适的仓库文档路径；
- 核实当前 `main` 和旧 `app/agent`；
- 核实“不做导航/路径规划”规则冲突；
- 形成 Phase A 文件级实施清单；
- 给出合同目录、VeloBench 目录和 Fake Environment 的最小设计；
- 不修改生产行为；
- 不建新业务表；
- 不调用腾讯；
- 不部署。

Phase A0 经过 Orchestrator 审查后，才拆出：

```text
A1 ADR
A2 Contracts
A3 VeloBench Fixtures/Cases/Graders
A4 Fake Environment
A5 Phase B Shadow Spec
```

---

## 12. 一句话工作原则

> ChatGPT 负责长期决策、拆解、审查和状态；Codex 是唯一代码写入者；文件保存跨会话记忆；测试和最终环境状态决定是否通过，而不是任何模型的自我声明。
