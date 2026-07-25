# VELO 项目规则书

## 🎯 产品层硬约束(在写任何功能代码前确认)

1. 这个功能对严肃公路车骑手有价值吗?
2. 是否违反 INV-P01 到 INV-P06?(见 `docs/agent-rules/product-decisions.md`)
3. 是否符合 60:40 社交工具比例?
4. 是否 spec 明确要求的?(防 scope creep)

违反任一 → 停下来与 Tim 讨论,不要自行推进。

产品层完整决策规则: `docs/agent-rules/product-decisions.md`（涉及产品方向时按需读取）
产品复杂决策走: `docs/agent-rules/velo-mental-model.md` § 10 问框架（按需加载）
技术层完整规则: 本文档后续内容
📖 **根 `AGENTS.md` 是唯一常驻入口**。本文只保留按需检索的技术陷阱和历史说明；`workflow-kernel.md` 仅在 Tim 明确点名工作流实验时使用。

## 🔴 commit 前 4 问（每次会话开头必看）

写代码 / commit 前回答下面 4 问，不能全答 yes 就停下：

1. 我**亲自读了 diff** 吗？（不是只看 subagent 报告 / pytest 数字）
2. pytest 跑过吗？
3. 这个改动**是 spec 说要的**吗？（防 scope creep）
4. 改动 >300 行 / 跨模块：**按原则 8 风险分层跑了对应审查**吗？（常规=1 道集成审；schema/隐私/不可逆=双审+异源）

**附加门禁已升级为结构约束（2026-06-10 拍）**：`scripts/pre_commit_gate.sh` 已装入 `.git/hooks/pre-commit`——承载性目录（app/migrations/tests/miniprogram，2026-06-11 修正：迁移真实目录是 migrations/ 非 alembic/，旧写法令迁移铃永不响）的 untracked 文件物理拦截提交，>300 行新增响铃提醒双审留痕，动 models.py 没迁移文件响铃。干净 clone 后需重装：`cp scripts/pre_commit_gate.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`。

**ship 后 1 问（与 commit 前 4 问对称 / 2026-06-10 拍 / 治「产品反馈环在规则层为零」）**：user-facing 功能 ship 时必答——这个功能的使用数据从哪条 SQL / 哪个日志可见？何时回看（写具体日期，进 PRD「数据回看」字段）？答不出 = 这个功能 ship 后永远不知道有没有人用，等于没装传感器。

## 🔍 调试 / 排查硬规则（2026-05-11 重大事故拍 / 每次 debug 必跑 / 压过"行动优先"）

用户报"看不到 X / 同步失败 / X 不工作"前，**禁止直接推测中间链路**。强制顺序：

1. **grep 本地配置** — `scope` / `permission` / `role` / env var / 白名单 / token 字段权限；**5 秒能锁定的事不许跳**
2. **读官方文档源头** — 第三方 API 的 scope 语义 / 过滤规则 / 可见性约束；WebSearch + WebFetch 真官方页，**禁止凭印象 / 凭训练数据**。**网络不可达时**：标该步骤为 `🟡 未验证`，继续走 Step 3（非破坏性验证 / read-only），但 Step 4 改 DB / 派 subagent / 跑 SQL 仍**强制阻断**直到文档可读再放行
3. **验证最远源头是否真包含目标对象** — 数据 / token / scope 够吗
4. **才能动中间链路**（webhook / scheduler / dedupe / token refresh / SQL 改 DB）

**违反代价**：错误根因 + 错误叙事 → 用户信任崩塌 → 整个 debug 体系全废 → 项目不可维护。

**实证（2026-05-11 Strava 私密活动事故）**：用户报"Strava 上传后 velo 看不到"，agent 直奔 webhook → subscription → token → cursor → dedupe → 跑 SQL 改 strava_imports，连续给出 5 个错误根因（含"webhook 链路从来没生效""Strava 那边没你今天的活动"反向误导用户），用户被错误的"严重事故"叙事**情绪崩溃**。**真根因 = OAuth scope `activity:read` 过滤 Only You 活动，5 秒 grep `scope=` 锁定**（详陷阱清单 #20）。

**红线**：第 2 次诊断仍未锁根因 / 想改 DB / 派 subagent / 跑 raw SQL 前——**强制回 Step 1 重跑**。

## 📐 任务规模预算（防 v4 复杂度失控）

- 一期任务数 **≤ 6**——写到第 7 个停下自问"该拆下期吗？"
- spec **≤ 800 行**——超了说明塞了脂肪，先审视哪些能砍
- 违反 = 复杂度失控信号，立即与 Starsky 讨论

## ♻️ 规则代谢条款（2026-06-10 拍 / 治「沉淀只加不退」）

- 新规则必须带生效日期（无日期的存量规则视为 2026-06-10 前）
- 每期 /neat 收尾跑**退役一问**：本期 0 次被引用的规则 / 已被脚本（hook/CI/schema 约束）吸收的规则 → 移出 CLAUDE.md 硬加载，归档到 docs/agent-rules/retired-rules.md。**散文升级成结构约束后必须删散文**——本文件曾 600 行砍回 343 又涨回 363，靠手术不如靠代谢
- 新增行为规则须配一次实弹测试(live-fire:干净 agent 真任务,看规则点不点火)并记录结果——规则写→测→调闭环(Tim 2026-06-07 提出,2026-06-10 落地)
- 已知风险表每行的「应对」列须含最后核实信息；`scripts/recheck_scanner.sh` 每期开工前跑一次，点名所有逾期复检项（persona 晾着 / 待 vN 修 / 真用观察类），每条要么拍板关闭要么写新日期续期，不许静默滚动

## 🛡 防火墙式扩展（防核心表被未来需求污染）

**新功能默认放新表 / 新模块**，禁止修改核心表（`users` / `activities` / `segments` / `segment_efforts`）——除非修 bug。

- 理由：核心表稳定 → 新功能是"加房间"不是"拆墙"。未来想删只删新模块，不动核心
- 反例（v4 教训）：把 `mute_notifications` 加到 `users`、`activity_type` 加到 `activities`——未来想砍代价大
- 正例：积分系统应建 `user_progress` 独立表，不在 `users` 加 `score/level` 字段

---

## 🤝 协作硬规则（v5 新增 / 双 agent 协作 / 授权来源：Tim 2026-04-29 对话）

> **3 条 meta 规则**——约束 agent 怎么和 Tim / 另一个 agent 协作。详细规则在 `docs/agent-rules/agent-collaboration.md`。

### ⚙️ 信息整流原则

给 Tim 提议 / 报告**必须**用翻译层句式：

> **干啥用** / **触发** / **影响** / **风险** / **建议** y/n/show

**禁止**：只贴 diff / 长输出 / 代码片段 / 术语堆砌。技术细节默认折叠，Tim 主动 show 才展开。

类比：CEO 看产品经理翻译，不直接读代码。

### 📦 少增加文档

新增文档类型需 Tim 拍板。能合并到现有文档章节，不允许独立成文。改名（如旧版"codex 分工宪章" → 现 `agent-collaboration.md`）不算新增。

**Why**：文档膨胀 = 双方认知负荷加重 + 漂移源更多 + 系统不稳定性加重。

### 🔄 动作 trigger 自查（每次写报告前 mental check 6 问）

1. 我有没有把代码细节直接推给 Tim？（违反 → 改翻译层句式）
2. 我做了哪些实证 / 没做哪些？（涉及未做的 → 用最低限度不确定度自报：🟡 + 一句"未 grep / 未跑命令"）
3. 这是高风险动作吗？（涉及 schema / 生产数据 / 核心规则 → 走硬 checklist）
4. 我有没有给 Tim 任何"未来承诺"句式（"记住了 / 学到了 / 待会做 X"）？有 → **立刻** save memory / TaskCreate / 写文件落实
5. 这次决策 / 评审是否引入 spec / task 卡 / 文档偏离？是 → **立刻** Edit 同步文档（或先 git commit doc fix），再动代码。不允许"代码先改、文档后补、文档不补"
   - 修补类 edit 完成后，必须在 `CLAUDE.md` / `AGENTS.md` / `docs/spec-v*.md` / `docs/plans/**` / `docs/agent-rules/**` 范围内 `rg <旧符号>`，确认旧签名 / 旧路径 / 旧决策无残留
6. **我刚 commit 完吗？这是 user-facing bug fix / feature 吗？是 → 立刻触发部署 SOP**（git push + 服务器 pull + docker rebuild + alembic upgrade + curl verify）
   - **commit ≠ ship**：Tim 打开小程序连的是生产 / 本地 commit 跑的还是老代码 / 用户看不到改动
   - 跳过场景：纯文档 / 纯 spec / tooling-only / 多 commit 中尚未完工的中间 commit
   - 实证：2026-05-15 Sprint 5 task-4 系列 6 task + 2 hotfix 全程未主动部署 → Tim 真用回归看到老代码"5月6日全部一样" → 反问"为什么会犯同样的错误"

**光"知道规则"不够——必须动作 trigger 强制自查**。否则下次又翻车。

> 详细规则、6 条翻车实证表：`docs/agent-rules/agent-collaboration.md` §7

---

## 🧭 决策反向索引（每次决策前自查 / 永远加载）

> agent 任何决策前先来这表，再去 `agent-collaboration.md` 详读对应章节。**索引让我永远看到决策点 → 主动去深读详细规则**。

| 决策类型 | 必查规则 |
|---|---|
| 加规则到哪文件 | `agent-collaboration.md` §9 升级路由表 |
| 该不该立规则 | `agent-collaboration.md` §12 规则成熟度（含 80% 高频例外）|
| 高风险动作前（动 schema/生产/核心规则）| `agent-collaboration.md` §7 硬 checklist |
| 切换主开发 vs 一气呵成 | `agent-collaboration.md` §10 切换 trigger |
| 会话拥挤 / 长讨论收尾 / 换窗口 | `agent-collaboration.md` §10 工作交接桥梁 |
| 给 Tim 提议 / 报告前 | `agent-collaboration.md` §7 翻译层句式 |
| **user-facing fix/feature commit 完** | `agent-collaboration.md` §7 mental check 第 6 问 → 部署 SOP |
| 代码审查（动 DB / 外部 API / 文件系统）| `agent-collaboration.md` §4 场景 B 必跑命令 |
| 经验是否沉淀 / 沉淀到哪 | `agent-collaboration.md` §0 经验沉淀三层路径 |

> **索引膨胀风险**：本表 ≤ 10 行硬约束（关联 §12 熵增警觉）。新增决策类型须 Tim 拍板 + 同时考虑合并/精简既有项。

---

## 项目概述

VELO 是公路骑行垂直平台的后端 API + 微信小程序前端。
MVP 目标（2026-06-11 按 D-006 同步）：码表文件上传解析 → 开奖与成绩卡分享 → 熟人约骑闭环。（旧版第三柱「赛段匹配排行榜」已按 D-006 押后）
团队：3 人大一学生，100 活跃用户量级。

**核心反馈环**（功能优先级跟着这个环走 / 2026-06-10 按 D-006 换轴，旧版含赛段排行已过时）：
`用户骑车 → 上传码表文件 → 开奖+成绩卡 → 晒卡到群/约骑战报(熟人可见) → 被看见所以继续骑、继续传`
环上最脆弱的节点 = 最该先投入的地方。当前激励源 = 熟人可见性，不是排名；赛段/排行榜为密度产品，按 D-006 押后等点火（详 inspiration-vault/strategy/velo/decisions.md）。

## 权威文档

> 📖 **文档全地图**：`docs/README.md`——含产品全景、文档索引、场景速查和旧九阶段历史参考。新任务先服从根 `AGENTS.md`，再按任务需要检索这里列出的专项文档。

**执行与技术（agent 线）**
- **技术规格**：`docs/spec-v5.md`（v5 期 / 当前现行）/ 历史 `docs/archive/spec-v1.md` ~ `spec-v4.md`（v1-v4 已 ship 归档）
- **实施计划**：历史已 ship 全归档 `docs/archive/plans-phase[3-5]-*.md` + `plans-sprint-*.md`（新 sprint 启动时建新 plans/ 目录）
- **架构导览**：`docs/architecture-guide.md`（系统静态全景，每期收尾刷新）
- **数据流全景**：`docs/data-flow-guide.md`（9 条链路动态视图，修跨模块 bug 必读）
- **架构决策历史**：`docs/adr/`（10 份 ADR / 见 `docs/adr/README.md` 索引）—— 有人提议改决策时必读
- **每期战术 PRD**：`docs/prd/phase-N-prd.md`（每期开工前写，含用户故事 + 验收标准）

**战略与产品（人类线）**
- **战略 PRD**：`docs/prd/velo-vision.md` / `velo-strategy.md` / `velo-product-spec.md`（3 份核心 / 见 `docs/prd/README.md` 索引）
- **专题战略**：`docs/prd/velo-route-flywheel-strategy.md`（路线百科与数据飞轮战略 / 2026-06-09 立 / ⚠ 部分判断待重审：数据获取是物理约束非架构锅、变现/市场规模未深算）
- **竞品深度分析**：`docs/competitive-analysis/`（5 份 / 见 `docs/competitive-analysis/README.md` 索引）

**运行规则（按任务路由）**
- **agent 产品规则**：`docs/agent-rules/product-decisions.md`（新功能、商业化或用户范围决策时读取）
- **agent 思考框架**：`docs/agent-rules/velo-mental-model.md`（按需，mental model 层）
- **Persona 宪法**：`docs/agent-rules/persona-constitution.md`（**2026-05-20 模块已砍 / 文档保留作教训**）

**Persona Engine（2026-05-20 砍掉 / 装饰展示层不应上 sprint 主线）**
- 整目录 `app/agent/persona/` + 3 张 persona_* 表 + 6 task plans + 宪法 v0.1 **暂停不删 / 晾着**——等 3-5 天看真实反应再回头判断（永久砍 / 复用为骑后教练复盘 / 或部分组件 DeepSeek client + persona_outputs 台账复用）。**⚠ 复检已逾期（2026-06-10 审计：5-20 落款的 3-5 天窗口过期 16 天无复判,三张僵尸表仍在 schema。待 Tim 拍板:永久砍 / 复用 / 续期到具体日期）**
- **战略失误复盘**：memory `feedback_decoration_vs_guidance_velo_persona_lesson.md` + 全局 `~/.claude/CLAUDE.md` §2.1 "装饰展示 vs 主动指导"原则
- **训练分析线**：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md`（5 模块 6-8 周）
  - **Sprint 9 模块 A（FTP 智能化）✅ 2026-05-21 ship**：8 task + 9 hotfix / 详 `docs/prd/sprint-9-prd.md` + `docs/changelog.md` 2026-05-20→21 段
  - **Sprint 10 模块 B（PMC 训练负荷曲线 CTL/ATL/TSB）✅ 2026-05-25 ship**：6 task / Codex Desktop 首次主写代码 + Claude 异源审 / 详 `docs/prd/sprint-10-prd.md` + `docs/changelog.md` 2026-05-25 段
  - **Sprint 11 模块 C（训练分布 Polarized/Pyramidal/SweetSpot）✅ 2026-05-26 ship**：7 commit（`7426b6e` Codex 主写 → `93e820e`）/ 默认不计滑行 0W（不再给用户开关）+ 184 条 backfill + 门槛 3→2 + 圆饼图 conic-gradient + 全类型动态百分比 + demo 风格 UI / 服务器已部署到 `93e820e` / 详 `docs/changelog.md` 2026-05-26 段 / 遗留：小程序待上传发布 + 真机发布后再复核圆饼图
  - **当前主线**：Sprint 12 模块 D（LLM 教练总结）待开 PRD / 产品形态愿景见 memory `project_velo_sprint12_coach_vision`（两场景：骑前每日教练 + 骑后分段复盘）+ 设计稿 `docs/superpowers/specs/2026-05-20-coach-engine-design.md`
  - **P1 tech debt**：FTP HR-gated 自动估算已替代旧 CP3 盲扫；Tim 当前仍因合格 20min 心率+功率窗口不足返回 insufficient（`docs/tech-debt.md`）/ 继续真用观察
  - **Sprint 10 收尾**：PMC 覆盖率门槛已按 range 联动（30d=42 天 / 90d=90 天 / 1y=365 天），训练分析图已补人话读图提示；剩余只是真用观察，不再作为 Sprint 10 阻断项

**历史档案**
- **变更记录**：`docs/changelog.md`
- **部署踩坑**：`docs/deployment-diary.md`
- **技术债务**：`docs/tech-debt.md`（每期开工前必扫）

**规则**：发现 spec 有问题 → 先改文档再改代码，不允许代码和文档不一致。

## 技术栈（不可变更）

- Python 3.11+ / FastAPI（**同步模式，禁止 async def**）
- SQLAlchemy 2.0 同步 session / PostgreSQL 16 + PostGIS
- Redis Queue (rq) 异步任务
- 微信小程序前端

## 开发原则

1. **严格按 spec 任务顺序**，不跳步、不并行有依赖任务
2. **每任务单独 commit**，格式 `feat(模块): 任务X.X 简要描述`
3. **TDD 红→绿（A 档新业务逻辑硬性）**：测试先行（红）→ 实现（绿）/ 测试者≠实现者 / **最后跑 pytest ≠ TDD**。详 `agent-collaboration.md §0.5 协议①`
4. **模块单向依赖**：User ← Activity ← Segment ← Notification ← Strava ← RouteBook ← Meetup（meetup 依赖 segment/route_book，正向）。**例外：2 处 spec 明确批准的反向 hook**（Tim 2026-05-28 拍方案 A / 约骑 spec §15.2 + §15.3 删除 SOP）——① `app/user/service.py` `delete_user` 函数内**延迟 import** meetup（删号级联清约骑）② `app/segment/router.py` 顶层 import meetup.models（赛段页 upcoming-meetups）。新增反向依赖仍禁止，这 2 处是已登记债
5. **不做 spec 没要求的功能 / 顺手优化**
6. **稳扎稳打有疑必停**：架构不清晰 / 自查发现隐患 / 信心不足 → 立即停，与 Starsky 讨论再动手。宁可多花一天讨论，不带隐患赶进度
7. **独立判断**：方案过度设计 / 时机不对 / 性价比低 → 直接反驳给替代方案（详见 architect 信条 3）
8. **风险分层审查（2026-06-11 Tim 拍 / 替代旧"三重审判"默认全跑 / Sprint 13+14 实弹试运行）**：
    - **分层判据 = 错误有没有运行时后盾**：写错类名/字段/逻辑 → pytest+门禁会抓，审查是重复保险；门禁路径漂移/测试盲区/跨模块契约漂移 → 没有运行时信号，只有 grep 实证型审查能抓
    - **常规批次（默认）**：1 审 = `reviewer-integration`（grep 实证集成审）+ pytest 全套 + pre-commit 门禁。砍 spec 忠诚审（task 卡已是 spec 忠诚转写 + TDD 测试 = 可执行的 spec 断言）、砍 Codex 第三审（Codex 写 + Claude 审本身已异源）
    - **高危批次（保留双审 + 异源三审）**：动 schema/迁移 / 隐私·门禁·鉴权路径 / 不可逆数据操作 / 并发竞态位——历史上异源审真抓过大鱼的位置（FK+CHECK 死锁 / 私圈 uploads 泄露）。Codex 审查协议照旧走 `agent-collaboration.md §4 场景 B`
    - spec 层双审保留（写完 spec 时）；plans/docs 层 1 道集成审封顶
    - 审查发现修完若为机械修复且 pytest 绿 → 不跑"修完复查"轮
    - **度量退出条件（规则代谢：写→测→调）**：真用回归 / 上线 4 周数据是终审；真用开始抓到"原来双审会抓的事故" → 收紧回旧制
    - 实证账本（2026-06-11 立此规则的依据）：S13 plans+T1 审实比 11:1（约 55 万:5 万 token），全部"无运行时后盾"的发现（pre-commit 门禁路径 bug / SQLite FK 测试盲区）均来自集成审；spec 忠诚审在"卡片已细化"的代码上只产出 cosmetic + 1 个误报
    - 本条在本项目内覆盖 architect 信条 5 的双审默认；旧三重审判全文 + 历史实证锚（2026-04-23 v4 task-7.10 等）归档 `docs/agent-rules/retired-rules.md`，sprint 收尾 /neat 时评估是否回流 architect skill
    - ⭐ **派 codex 写大文档禁令保留**（2026-04-28：spec / plans / >800 字走 Codex Desktop 原生或主 agent 自写；codex CLI 通道 >50K token 必卡，详分工宪章 §5 + memory `feedback_main_agent_as_middle_manager.md` §2.1）
9. **链路收尾三问复盘**（spec 链路完成时跑，不是每个 task）：新 bug 模式 / 设计判断 / 流程问题 → 识别完直接调 `/neat` 分发到 memory / CLAUDE.md / docs（详见 architect 信条 11 + neat-freak skill）
10. **spec 自审 2 项**（architect Step 7 双审之外的项目特定补充）：
    - **状态机完整性**：所有合法状态转换画完整图，含异常恢复路径——遗漏一个状态转换 = 未来踩 bug
    - **共享逻辑识别**：两处做同样事的代码必须抽共享函数，禁止复制粘贴（如 GPX/Strava 都要把 ParseResult 写入 DB → 抽 `save_parse_result` 共享）
11. **审核工具分层使用（2026-04-28 沉淀，三者不可互替）**：
    - **写代码过程中**（在编辑器随手扫一段）→ `/simplify` 做局部漂亮度检查（单 LLM 调用，10 秒级）
    - **commit 前**（硬性，详见原则 8）→ 风险分层审查（常规批次 1 道集成审；高危批次双审 + Codex 异源，2026-06-11 起）
    - **任务完工 / claim 完成前** → 重新运行本任务的真实验收命令，读完整输出并核对真实 diff；没有本轮新鲜证据，不得声称完成
    - 关键：simplify ≠ 三审的轻量替代——砍三审 = 失 spec 字段对照（v4 已踩 `fk_xxx` vs `_fkey` 命名坑）+ 异源盲区扫（v4 task-7.10 实证 Codex 一轮抓到 Claude 双审漏的反馈环级 Important）。三者各管一段时间窗，不互斥

## 代码健康度自动巡检

每次任务完工汇报必附健康度检查：

| 指标 | 黄灯 | 红灯 |
|------|------|------|
| 单文件行数 | >300 | >600 |
| 单函数行数 | >50 | >80 |
| 测试总耗时 | >10s | >30s |
| 单模块文件数 | >8 | >12 |

- 黄灯：汇报中标注"⚠ xxx.py 已达 320 行"
- 红灯：先评估职责是否统一——同一职责的"成绩单计算器"不拆；职责混杂才拆
- 命令：`wc -l app/**/*.py` / `pytest --durations=0`

## 防黑盒化（每期开工前 + 收尾必做）

- **开工前**：扫本期改动模块的历史代码，列 tech-debt 进 `docs/tech-debt.md`。**新期 spec 不允许依赖 tech-debt 中的项**——先修清理再做
- **开工前**：跑 `bash scripts/recheck_scanner.sh`（复检点火器，2026-06-10 立）——所有逾期复检项当场拍板关闭或写新日期续期
- **收尾**：刷新 `docs/architecture-guide.md` + 答黑盒度三问（10 分钟讲全貌 / 数据流复述 / 30 秒读懂任意文件）
- 任何一项不满意当期清完，不留下期。**清理动作 5 种**：加注释解释设计意图 / 拆分职责混杂文件 / 补接口文档 / 更新模块 `__init__.py` 一句话说明 / 重命名歧义变量

## 命名规范

- API 路径：RESTful 复数（`/api/activities`）
- Python：snake_case
- 数据库表名：复数小写（`users`, `activities`, `segments`）
- 分页参数：`page` + `page_size`（不用 `limit`）

## 关键技术约定

- **距离单位**：DB 存米，API 返回 km，转换在 service 层
- **时区**：DB 存 UTC，"本周/本月"按北京时间 UTC+8 计算
- **PostGIS 距离查询**：`ST_DWithin` 必须转 `::geography`，否则单位是度
- **GPX 上传**：先跳过 BOM 再检查 XML 头
- **JWT**：7 天有效期，401 时前端 wx.login() 静默续期
- **Activity 状态机**：`pending → processing → completed/failed`，禁止非法转换。Strava 导入用 `importing` 中间态。processing >10 分钟自动 failed
- **SAVEPOINT 隔离**：循环里 flush 后可能 rollback 必须用 `db.begin_nested()`
- **Alembic 迁移纪律**：改表结构必须 Alembic 生成迁移脚本，禁止手动 ALTER TABLE
- **admin 类 PATCH endpoint**：用户可改字段必须 schema `extra="forbid"` 422 + 显式 Literal 枚举校验，防 admin 误改 distance / reference_line 等核心字段后看到 200 OK 假成功（v5 task-3.A.4 + 3.A.5 复利实证）

## 纯函数规则

以下模块**不碰数据库 / 不碰文件系统**，只接收参数返回结果：
- `parsing/gpx_parser.py` / `parsing/fit_parser.py` — GPX/FIT 解析
- `activity/simplify.py` — 轨迹简化
- `segment/matcher.py` — GPS 精确匹配
- `activity/power_zones.py` — 功率区间计算
- `notification/detector.py` — 事件分类

价值：可独立测试 / 可替换实现 / 无副作用。调用方负责 DB 读写。

## 日志规范

Worker 和 service 关键步骤必须 `logging` 输出，含实体 ID：
```
"开始解析 activity_id=42"
"匹配 segment_id=3 失败，覆盖率 0.65 < 0.8"
```
日志是生产唯一眼睛——Worker 后台跑无界面，出问题靠日志回溯。

## 强制检查清单（写涉及状态变更的代码前必答）

- [ ] 进程被 kill → 数据处于什么状态？能自愈吗？
- [ ] 同时执行两次（并发/重试）→ 结果幂等吗？
- [ ] 外部依赖（DB/Redis/API）超时或报错 → 上游怎么回滚？（详见技术栈陷阱清单 #14 / v5 task-3.A.2 实证）
- [ ] 创建了什么资源（文件/记录/连接）→ 清理路径在哪？
- [ ] 查询在 10 万行下执行计划是？有索引支撑吗？
- [ ] 输入最大可能规模？内存峰值能控制在多少？
- [ ] 每个 `if x` 判断：x=0 / x="" 是合法值吗？是 → 用 `if x is not None`（**truthiness 陷阱已在 6.2/6.3 连续踩坑两次**）
- [ ] 循环中 flush/rollback：要 SAVEPOINT 隔离吗？（matcher / import_scheduler 已有此模式）

故障思维 5 维背景（崩溃/并发/批量/边界/级联）见 architect 信条 2。

## 技术栈陷阱清单（项目专属，写代码前必扫）

| # | 陷阱 | 错误表现 | 正确姿势 |
|---|------|---------|---------|
| 1 | **Python truthiness**（NULL/0/"" 都为 False） | `if user.mute_notifications:` NULL 被当 False；`if count:` 0 被误判 | bool 字段 `is True` / `== False`；存在性 `is not None` |
| 2 | **naive vs aware datetime** | `datetime.now(UTC) - db_value` TypeError | DB 字段 `DateTime(timezone=True)`；Python 端 `datetime.fromtimestamp(ts, tz=UTC)` |
| 3 | **Python `or` 短路永真** | `type == 'Ride' or 'VirtualRide'` 永真 | 用 `type in ('Ride', 'VirtualRide')` |
| 4 | **SQLAlchemy `.one()` vs `.first()`** | `.one()` 遇零记录抛 NoResultFound → 500 | `.first()` + `if not x: raise ValueError` |
| 5 | **redis-py 返 bytes** | `redis.execute_command('GETDEL', k)` 返 bytes | Redis 7+ 用原生 `redis.getdel(k)`；必要时 `.decode()` |
| 6 | **PostgreSQL 外键自动命名** | spec 写 `fk_<table>_<col>` 自编 → drop_constraint 报错 | 默认是 `<table>_<column>_fkey`；不确定用 inspector 反查 |
| 7 | **Alembic alter_column 类型转换** | naive 改 tz-aware 忘 `postgresql_using` | `postgresql_using="col_name AT TIME ZONE 'UTC'"` |
| 8 | **SAVEPOINT 隔离**（同关键技术约定）| 循环 flush 后 rollback 炸循环外 | 循环内 `db.begin_nested()` |
| 9 | **第三方响应嵌套** | 假设 `data['athlete']['id']` 固定 → KeyError | `.get()` 链 + 显式存在性检查 |
| 10 | **状态机值脑补** | spec 写 `'running'/'pending'`，真实是 `active/paused/completed` | grep server_default 和 service 赋值抄真实值 |
| 11 | **aware datetime 手工拼 Z**（v5 新踩） | `created_at.isoformat() + "Z"` 在 tz-aware 后变 `2026-04-29T12:00:00+00:00Z` 畸形，前端解析必炸 | 让 Pydantic 自动序列化 / 或 `.isoformat()` 不加 Z；**禁止手工拼 Z 后缀** |
| 12 | **`with_for_update()` 单独不够 → 配 `populate_existing()`**（v5 task-0.2 codex 抓的） | 同 session identity map 返回旧 ORM 缓存——**行锁 SQL 拿到了但字段值是 stale 的**，并发场景下会读到过时 token / 状态导致逻辑误判 | `.with_for_update().populate_existing().first()` 强制刷新 identity map 里已有对象的 attributes，确保字段值 = 加锁后 DB 最新值 |
| 13 | **跨模块场景 SAVEPOINT 隔离**（v5 task-2.A.1 实施时捕获 / 区别于 #8 循环场景）| 内层模块（detector / 通知写入器 / progress 检测器）被 worker / endpoint 调用时，若内部直接 `db.commit()` 成功会把外层未 commit 的改动一起提交（OK），但 `db.rollback()` 失败会把外层改动**一起回退**！worker 改的 `activity.status='completed'` 因 detector UNIQUE 冲突被回退 = worker 白干 | 内层用 `nested = db.begin_nested()` + `db.flush()` + `nested.commit()/nested.rollback()`，让失败只回退到嵌套点；外层 commit 由调用者统一做。详见 memory `feedback_savepoint_isolation_for_inner_modules.md` |
| 14 | **DB 状态变更 + Queue/API 副作用不一致**（v5 task-3.A.2 实证） | `db.commit()` 后再 `queue.enqueue()` / 外部 API 调用，若副作用失败，DB 已显示成功；重试又被幂等守卫挡住，形成"已选中但无 task"这类死局 | 优先同事务内完成可回滚状态；若必须 commit 后调用外部依赖，必须写补偿路径 + 503/可重试错误 + 回归测试。复杂高频场景再升级 outbox / dispatcher |
| 15 | **PostGIS `ST_*` 函数在 SQLite 测试 fixture 不可用**（v5 task-3.A.6 实证）| service 层加 PostGIS 查询（`ST_HausdorffDistance` / `ST_GeomFromText` 等）时，SQLite fixture 跑会 `OperationalError: no such function: ST_xxx` 让真路径单元测试 fail（task-3.A.6 加 from-gpx 查重时引发 `tests/test_segment_fields.py` 4 fail） | 加 dialect 守卫：`if db.bind.dialect.name == "postgresql":` 内层跑 PostGIS 查询；SQLite 跳过（视为"无重叠"让流程继续）/ 真 PG 才跑产品保护逻辑；MagicMock 测试用 `db.bind.dialect.name = "postgresql"` 显式 mock；dev stack 真 PG 集成测试补真行为。**共享逻辑识别**（CLAUDE.md spec 自审 #2）：跨调用方相同 PostGIS 业务规则必抽 helper（如 `_check_hausdorff_overlap`），守卫在 helper 内统一 |
| 16 | **Strava API `before` 参数 inclusive 边界 / dedupe 全部时 cursor 不推进死循环**（v5 真用回归实证）| import_scheduler tier1 拉 page1 后 cursor_before = 最老活动 started_at；下次 tick `before=该 ts` Strava 仍返回**等于该时间戳**的边界活动（inclusive）；这些活动全已 created → dedupe 全 continue → oldest_start_date 不推进 → cursor 卡同一 ts → 死循环 → activity 永远卡 importing | tier1 循环里把 `oldest_start_date` 推进**移到 dedupe 之前**：先解析 start_date 推进游标，再做 dedupe。dedupe 跳过的活动也算游标推进 → cursor 持续向更老方向走，直到拉真空 list 触发 tier1 完成 |
| 17 | **小程序 `wx:if` 控制 canvas 创建 → setData callback wx.nextTick 仍有 race**（v5 真用回归实证 / 90% 设备折线图不渲染）| home/detail 的速度/功率/心率/踏频 chart `<canvas>` 用 `wx:if="{{hasTimeseries}}"` 控制创建；setData 后 wx.nextTick 调 bindLineChart 时 canvas 2d node 在某些机型仍未 ready；selector 失败 → 静默 return → 图永远不画。海拔图无 wx:if（DOM 永远在）所以 100% 工作 = 对照组 | 1）改 `wx:if` → `hidden`（DOM 永远在 / canvas 一开始就 ready）2）setData callback 用 `setTimeout(fn, 100)` 替代 `wx.nextTick`（兜底极慢机型 canvas 2d 初始化）3）整个 section 的 wx:if 保留时（如踏频 section 控制是否显示标题）/ 内部 canvas 配 setTimeout 兜底 |
| 18 | **nginx + docker hostname-based proxy_pass 缓存 IP**（2026-05-06 admin H5 502 事故实证）| `proxy_pass http://api:8000` 用 hostname 时 nginx 启动时解析一次就缓存；api 容器任何重启（OOM 自愈 / 部署 / docker prune）拿到新 IP → admin-h5 nginx 仍连旧 IP → 502。被 LoginPage catch-all "token 无效或过期"误显示 → 排查 30 分钟走错路径 | `resolver 127.0.0.11 valid=10s ipv6=off`（docker 内置 DNS）+ `set $upstream_api http://api:8000; proxy_pass $upstream_api;`（变量化 → nginx 不缓存 / 每次连接前重查）。10 秒内自动恢复，无需手动 restart 容器。**配套**：前端错误文案禁用 catch-all / 必须按状态码分流（401 / 403 / 5xx / 网络）|
| 19 | **第三方依赖激活状态 mock 测试不到 / 真用才发现"喇叭没插电源"**（2026-05-06 task-monitor-admin-h5 实证）| 监测探针单测全 mock httpx + 11 测试通过；生产 .env 里 `FEISHU_BOT_WEBHOOK` 是空（Tim 从没用过飞书）→ 探测真生效但 webhook 推送进 logger.warning"未配置跳过"分支 / 告警进垃圾桶。Mock 测了"agent 调用了什么"，没测"通道真激活了"  | 部署高风险第三方依赖（飞书 / 微信 / SMTP / Stripe / Strava webhook 等）必须**有意激活回归**：部署后 24h 内 owner 故意触发一次失败场景，确认告警 / 回调 / 推送真到达。把激活状态写进 deployment-diary 防遗忘 |
| 20 | **Strava OAuth scope `activity:read` 不返回私密活动**（2026-05-11 重大事故实证）| velo OAuth 默认申请 `read,activity:read` → Strava API 对 visibility="Only You" 活动**一律静默过滤**（不报错 / 列表少一条）；用户改成"公开"后是否立刻同步**官方文档无承诺**（可能 Strava 后端缓存 / indexing lag）；事故中 agent **跳过 grep `scope=`** 直奔 webhook / scheduler / token / dedupe 5 层中间链路 debug 30+ 分钟 + 给出错误"事故"叙事吓崩用户 | OAuth URL `scope=read,activity:read_all`（read_all 含 activity:read + 私密活动 + privacy zone data，Strava 官方文档原话）；**切换 scope 后用户必须在小程序重新点"绑定 Strava"一次**（旧 token 不会自动升级 scope，Strava 强制重新授权流程）；改完代码两处：`app/strava/service.py` build_authorize_url 旧版 + v4 版都要改 |
| 21 | **`with db.begin()` 在已 autobegin 的 session 上抛 InvalidRequestError**（2026-06-01 约骑 task7 delete_user 实证）| `SessionLocal` 是 `autocommit=False`（SQLAlchemy 2.0 autobegin 默认）。真实端点用 `Depends(get_db)` 注入 session 后，任何一次 query（如 `get_current_user` 的鉴权查询）就触发 autobegin；service 内再 `with db.begin()` 二次开启事务 → `InvalidRequestError: A transaction is already begun` → 500。测试若在调用前最后一步是 `commit()`（session 不在事务中）会**侥幸通过**，不代表生产可用 | service 函数统一用末尾单次 `db.commit()`（和项目所有其他 service 一致），**禁止 `with db.begin()`**；要测真实端点场景就先 query 触发 autobegin 再调函数 |
| 22 | **小程序个性化底图 subkey 是"先购买再使用"的付费能力，根因在商务层改代码救不回**（2026-06-12 地图事故实证）| 给 `<map>` 挂 `subkey` + `layer-style` 想换浅色底图 → 真机鉴权失败、地图直接卡死。微信官方文档：自 2023-06-29 起个性化地图须在**微信公众平台-付费管理**购买后才能用——只在腾讯位置服务控制台建 key / 调样式 / 绑定 / 授权 AppID 是不够的半套手续。codex 多轮改代码中间链路（去 wash 蒙层 / 统一 preview / fallback context）全部无效，因为根因不在代码 | 全工程 `<map>` 禁止传 subkey / layer-style（`tests/test_meetup_miniprogram_static.py` 有全局红线守卫）；装饰性展示用 `utils/route-thumb.js` canvas 自绘纸面，交互地图（选点/全屏）用免费默认底图；想复活纸面底图先去微信公众平台付费管理购买、再填 subkey，顺序不能反。**元教训 = 调试硬规则 Step 2 的又一实证：真机第三方能力故障先读官方文档查"该能力的开通条件/收费政策"，再动代码** |
| 23 | **alembic revision id 超 32 字符炸版本登记**（2026-06-13 部署实证）| `alembic_version.version_num` 列是 varchar(32)；revision id（如 `20260612_meetup_place_power_hints` 33 字符）超长时 **schema 改动全部执行成功后**版本登记 UPDATE 抛 StringDataRightTruncation → 事务整体回滚，报错信息指向 UPDATE 语句极具迷惑性 | 项目命名式 revision id（日期_名字）**≤32 字符**，起名后 `len()` 自查；超了改短名字（改 revision 字符串+文件名，未入库的 revision 重命名安全）|
| 24 | **navigateTo/redirectTo/默认 navigator 跳 tabBar 页静默 fail**（2026-06-13 全模块走查实证）| `wx.navigateTo`/`wx.redirectTo`/`<navigator>`（默认 open-type）目标是 tabBar 页（home/explore/upload/meetups-list/profile）时调用直接 fail、页面纹丝不动且无报错——实锤：settings 退出登录卡死原页 ×4 / home 登录按钮点了没反应 / 战报"交卷"跳不进上传页 | tabBar 页只能 `wx.switchTab`（navigator 加 `open-type="switchTab"`）；**switchTab 带不了 url 参数**——上下文走 `app.globalData.pendingXxx` 寄存柜约定（写入→switchTab→目标页 onShow 取即清空）；静态守卫测试 `test_no_wrong_method_jumps_to_tabbar_pages` 已锁红线 |
| 25 | **canvas 被任何 `wx:if`/`block wx:if` 包裹 → observer 首次绘制 race 静默画空**（2026-06-14 ride-card cover 模式实证 / 陷阱 #17 的变体，自己违反了 #17 铁律）| 给共用组件加新布局模式时，用 `<block wx:if="{{layout}}">` 把含 canvas 的整块卡片包进去 → 组件 observer 首次调 `createCanvasContext` 绘制时，canvas 节点随条件块延迟一帧挂载、拿不到 → 静默画空（profile 列表轨迹一度全部消失）。#17 说的是单页 wx:if，这条是"组件内 layout 分支的 block wx:if 同样致命"，即使 layout 值恒定不翻转也会栽在首帧时序 | canvas 节点**提到所有 layout 条件块外**、作为卡片根节点直接子级、**唯一一份永远渲染**，class 随 layout 切外观、可见性用 `hidden`（DOM 常在）；纯文字区（头像行/信息区）才允许 `wx:if`（与 canvas race 无关）。判据：**凡是 canvas，先问"它的 DOM 节点是不是无条件常在"，是 wx:if 后代就改结构** |
| 26 | **旧 canvas API `createCanvasContext` 绘制尺寸写死 rpx÷2 → 大屏不居中/不占满**（2026-06-14 ride-card 轨迹缩略实证 / log 实锤 winW=428）| 旧 canvas API 的绘制坐标单位 = CSS px，而 canvas 节点的 CSS 尺寸由 wxss 的 rpx 决定；rpx→px 换算随屏幕宽度变（750rpx = 屏宽 px）。写死"rpx÷2"只在 375px 屏成立——428px 屏上 1rpx=0.571px，canvas 实际 px > 绘制 px → 绘制坐标系比画布小 → 轨迹偏左上、右下留白、越宽屏越偏。注：起终点/投影居中算法本身没错，错在绘制尺寸基准 | 绘制尺寸按当前屏宽动态换算：`var winW=(wx.getSystemInfoSync().windowWidth)||375; var rpx2px=winW/750; 绘制px = wxss真实rpx × rpx2px`。把 wxss 的真实 rpx（含容器 padding 算出的全宽）乘 rpx2px 传给 drawRouteThumb，绘制坐标系才和画布 CSS px 严丝合缝。**别在 route-thumb.js 共用工具里写死——调用方按自己 wxss 的 rpx 现算传入** |

> **活文档**：每踩新陷阱在这加一条（不要回 architect skill 加——那里只留跨栈通用 3 条）。

## 协作硬约束（项目特定）

- **Starsky 验证你的结论**：说"完成"前必须查代码验证，不只看清单。说"不确定"比说错好——他尊重诚实，不尊重自信的错误
- **细节判断 AI 自己做**：Starsky 是产品设计师视角，不会判断技术细节。AI 应自己拿主意，给整体效果让他过目（**不要列每段命运逐项让他过审**——那是强行让他做不擅长的事）
- **并行 agent 不浪费等待**：讨论同时后台跑调研

详细沟通格式（决策表格、三段节奏、生活类比）见 architect 信条 7。

## 部署经验（第 2 期踩坑总结）

> **核心教训：本地测试全绿 ≠ 生产能跑。** 测试用 SQLite + mock，不连真 Docker/PostgreSQL/Strava API。

📖 **完整部署 SOP（单一真相源）→ `docs/agent-rules/deploy-sop.md`**

6 步 SOP（push → pull → 清 Redis → rebuild → alembic → curl verify → grep 前端入口）+ Pre-deploy checklist + 部署后真用回归 6 类盲区 + 故障排查因果链 + 运维脚本纪律 + SSH 脱敏，全在该文件。部署前必须主动读全文；不再用关键词 hook 把摘要塞进每轮上下文。

> ⚠ 历史的 4 步 SOP / checklist 已迁入 deploy-sop.md 并升级为 6 步——CLAUDE.md 不再保留正文，避免两处漂移。

### 服务器信息

| 项目 | 值 |
|------|---|
| IP | 114.132.190.245 |
| 用户 | ubuntu |
| 代码路径 | ~/velo |
| Docker 命令前缀 | sudo |
| 部署方式 | git pull 或 scp |
| 数据库迁移 | `sudo docker compose exec api python3 -m alembic upgrade head` |
| 看日志 | `sudo docker compose logs api --tail 30` |

## 已知风险（持续维护）

| 风险 | 级别 | 说明 | 应对 / 修复状态 |
|------|------|------|----------------|
| Worker 僵尸 | 🟢 | activity 卡 processing/pending | 僵尸扫描脚本（5min 一轮）+ 原子状态锁 ✅ `0e2c690` |
| 重复上传 | 🟢 | 用户双击 → 重复 activity | SHA-256 哈希 + UNIQUE + IntegrityError 兜底 ✅ `e1dcba1` |
| 内存爆炸 | 🟢 | 50MB GPX → 50 万点 → 400MB | 上限 50000 点 + 500 条批量插入 ✅ `c15daf8` |
| 连接池不足 | 🟢 | pool_size=5 默认 | pool_size=8, max_overflow=12, pool_recycle=3600 ✅ `845e226` |
| Worker 重入 | 🟢 | RQ 超时重试 → 双重处理 | UPDATE WHERE 原子抢锁 ✅ `414fce9` |
| OAuth state CSRF/重放 | 🟢 | JWT state 可重放 | Redis nonce GETDEL 一次性消费 ✅ v4 task-7.2 |
| Webhook 裸奔 | 🟢 | 任意人可伪造回调 | subscription_id 校验 ✅ v4 task-7.4 |
| scheduler 不跑 | ⚠️ | 无独立容器 → 导入永远不推进 | 状态过期待复检（2026-06-10 审计：本行写「待 v4 修」而 v4 早已归档——要么已修未销账，要么搁置 2 月。下期开工前核实真实状态再改本行）|
| N+1 查询 | 🟡 | 排名计算循环 SQL | 代码 TODO ⚠️ tech-debt |
| 孤儿文件 | 🟡 | 上传成功 DB 失败 → 磁盘泄漏 | 无清理机制 ❌ tech-debt |
| 匹配断裂 | 🟡 | 解析完成但匹配前崩溃 | 失败静默跳过 ❌ tech-debt |
| trackpoints 无 UNIQUE(activity_id, seq) | 🟡 | Worker 重试可能插入重复轨迹点 | 缺 DB 约束 ❌ tech-debt |
| status 字段无 CHECK 约束 | 🟡 | DB 层可写任意字符串 | 应用层校验 ⚠️ |
| trackpoints 表无分区策略 | 🟡 | 百万级时在线加分区需锁表 | 未来事 ❌ |
| 删 importing 中 activity | 🟡 | Worker 报外键错（脏日志，数据安全）| 未处理 ❌ |
| admin-h5 nginx DNS 缓存 | 🟢 | api 容器重启换 IP 后 admin-h5 一直连旧 IP → 502 | resolver 127.0.0.11 + 变量化 proxy_pass ✅ admin-h5 commit `91ca336`（2026-05-06）|
| admin H5 端到端监测盲区 | 🟢 | api/admin/* 反代挂时无主动告警 | monitor 容器加 admin_h5_health 探针（log-only / D 决策）✅ velo commit `6d6657f` |
| 前端错误文案 catch-all | 🟢 | 401/403/5xx/网络错全显示同一句"token 无效"误导排查 | getErrorDetail 单一真相源按状态码分流 ✅ admin-h5 commit `91ca336` |

## 当前进度

> 2026-05-13 整理：原"当前进度"258 行（v0+ / 第 4 期 / 第 5 期 Sprint 0-4 / v5 收尾 / Sprint 5 全部 task 细节）已归档到 memory（按需加载 / 不挤本文件 hard load）。CLAUDE.md 从 600 行砍回 ~343 行进入软上限。

- **当前位置 + 下一步 + 起手必读** → memory `project_velo_current_position.md`（每次 /clear 后先 grep）
- **历史 task 进度细节 / commit hash / D 决策** → memory `project_velo_full_progress_history.md`（按需 grep）
- **跨期复盘 / 最新 ship 总结** → `docs/changelog.md`
