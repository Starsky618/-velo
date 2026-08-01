# ADR-009: 为什么 agent 层独立,不污染主 SaaS

## 状态
superseded (2026-07-29) — 由 `docs/agent-rules/product-decisions.md` D-P07 取代

本 ADR 保留为历史决策记录。关于 Agent 的当前产品角色、实施顺序和确定性业务边界,以 D-P07 为准。

## 上下文

velo 长期路线图(v7+)包含 **agent-native 演化方向**: 用户不需要打开 app,velo 在合适时机主动推送建议(例如:"周日早 6 点天气好,西山爬坡路线,你上周刚完成,继续?")。这需要 agent 能理解用户上下文(骑行历史 / 偏好 / 社群 / 天气 / 时间)并主动决策。

架构问题: agent 能力**怎么构建在现有 SaaS 之上**?

两种思路:
- **深度耦合**: agent 直接调 SaaS 数据库 / 共享 session / 反向 import 业务模块代码,像一个新模块嵌入进去
- **薄接口**: agent 是独立 service,通过只读 API + 事件订阅拿数据,不触碰 SaaS 内部

v5 规划期(2026-04)Tim 明确: "agent 作为 v7+ 独立模块,薄接口连接,不污染主 SaaS"。

## 决策

v7+ 启动 agent 能力时,**严格以独立模块形式构建**:

- **代码位置**: `app/agent/`,与其他业务模块平级
- **数据表**: agent 自己的表(如 `agent_suggestions` / `agent_feedback` / `agent_rag_chunks`),不修改核心表
- **接口**: 只通过内部 API(`/api/internal/*`)读主 SaaS 数据,**不反向 import 业务模块代码**
- **写操作**: agent **不代用户直接改数据**,而是生成"建议",用户确认后再由主 SaaS 执行
- **独立性**: 如果 v7+ 发现 Python 不够用(换成 Go / Rust / 独立 service),可以整体换掉 agent 模块不影响主 SaaS

## 理由

1. **AI/LLM 领域变化极快,主 SaaS 必须稳定**。2024-2026 年间 LLM 价格降了 100 倍,框架(LangChain → LlamaIndex → 原生 API)换了 3 代,架构模式(RAG → Agent → ReAct → MCP)也在演进。主 SaaS 服务 100 活跃用户,**必须稳定**,不能因 agent 实验性迭代影响。

2. **Agent 商业价值是"服务规模化杠杆",不是"产品差异化"**。Tim 的战略判断:velo 的差异化来自**地理社交 + 身份图谱**(见 PRD),不来自 agent。agent 是**后期**用来把 "1 个教练服务 10 人" 变成 "agent 辅助服务 500 人" 的规模化工具。这意味着 agent 晚 2-3 年启动也不影响产品核心定位。

3. **技术栈可能换**。如果未来发现 Python 生态 RAG 性能不够,或者某个场景需要实时流式(WebSocket),或者需要 GPU 调度,agent 可能用完全不同的技术栈实现。薄接口让"换技术栈"的代价是"重写 agent 模块",不是"重写整个 velo"。

4. **避免"agent 污染"心智**。很多创业公司走错的路:AI 时代 → 所有功能都要 AI → 主产品被 AI 不确定性绑架(LLM 调用慢 / 费用高 / 出错)。velo 明确:**主 SaaS 走传统工程路线**(确定性),**agent 作为独立服务增强**(可选)。用户关掉 agent velo 还能正常用。

5. **agent 数据隔离有商业意义**。agent 生成的建议、用户对建议的接受/拒绝反馈,是 velo 自己的专有数据(训练数据集)。与业务数据分开存,未来可以独立商业化(比如把 "10 万用户对 AI 建议的反馈数据" 作为 LLM 训练供应商或自研小模型的基础),不被业务数据耦合限制。

## 后果

### 正面
- 主 SaaS v1-v6 不受 agent 话题干扰,工程焦点清晰
- agent 实验可以快速迭代 / 频繁重写,不影响主业务
- agent 技术栈未来可换,架构层面无锁定
- 商业化灵活:可以"关掉 agent 单卖 SaaS"也可以"agent 单独订阅",两路并行

### 负面
- 初期双写成本: agent 要拉数据而非共享 session,增加网络开销(v7+ 级别数据量下可接受)
- 功能集成感弱: 用户可能感知"agent 是附加的"而非"velo 原生",需要 UX 设计补偿
- 实现比"直接嵌入"多一层抽象(薄接口 / 事件订阅 / 独立存储),初期工作量大一些

### 触发重新评估的条件

v10+ 或以下极端场景:
- agent 能力完全成熟且稳定(框架 / 模型 / prompt 都不再频繁变化),隔离价值下降
- agent 深度介入 SaaS 核心流程(如 agent 实时决定匹配结果 / 排行榜展示),薄接口延迟太高
- 商业化路径证实 agent 是核心而非增强,需要深度集成

## 接口约定

v7+ agent 与主 SaaS 的通信协议(预先约定,避免实现时临时设计):

**Agent 读主 SaaS 数据**:
- 通过 `/api/internal/*` 只读接口
- 典型接口: `GET /api/internal/users/{id}/context`(用户完整上下文:骑行历史 + 偏好 + 社群)
- 认证: 服务间 JWT(与用户 JWT 隔离)

**Agent 写主 SaaS 数据**:
- **不直接写**。所有"修改"都通过"生成建议 → 用户确认 → 主 SaaS 执行"
- 典型流程: agent 分析用户数据 → 写 `agent_suggestions` 表(建议内容)→ 推送到用户 → 用户点击"采纳" → 调用主 SaaS 正常业务 API

**Agent 自己的数据**:
- 独立表: `agent_suggestions` / `agent_feedback` / `agent_rag_chunks` / `agent_user_context_cache`
- 独立迁移: `migrations/agent/` 子目录
- 独立 schema: 可以用独立数据库 / 独立 PostgreSQL schema

## 违反代价

如果未来 PR 让 agent 模块深度嵌入主 SaaS(反向 import 业务模块 / 共享 session / 修改核心表):

1. **技术栈锁定**: agent 想换技术栈时,发现业务代码都耦合了 Python / FastAPI / SQLAlchemy,无法独立演化
2. **不确定性传染**: LLM 调用慢 / 费用 / 出错会影响主 SaaS 响应,用户体验下降
3. **回滚困难**: agent 出 bug 想关掉,发现业务功能也依赖 agent 某些输出
4. **数据混淆**: agent 训练数据和业务数据混在同一套表里,未来分离困难

**防御措施**:
- 架构 guide v2 §2.1 agent 模块预留槽位(文件夹不存在,等 v7+ 新建)
- 架构 guide v2 §7.3 agent-native 独立性原则
- 新增 agent 相关需求时,必须先 check "是否破坏薄接口原则",是则 ADR 修订或拒绝

## 相关文档

- 架构 guide v2 §1.2 "不包含机器学习/深度学习模型(RAG 独立小项目)" / §2.1 agent 模块预留 / §7.3 agent-native 独立性
- PRD 主文档 §Agent 演化路径(批次 7 产出)
- ADR-008(防火墙式扩展)— 本决策是该原则的极端应用
- 参考业界: Shopify 的 Sidekick AI(独立服务,与 Shopify 核心商品/订单系统薄接口)
