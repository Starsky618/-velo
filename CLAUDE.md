# VELO 项目规则书

## 🎯 产品层硬约束(在写任何功能代码前确认)

1. 这个功能对严肃公路车骑手有价值吗?
2. 是否违反 INV-P01 到 INV-P06?(见 `docs/agent-rules/product-decisions.md`)
3. 是否符合 60:40 社交工具比例?
4. 是否 spec 明确要求的?(防 scope creep)

违反任一 → 停下来与 Tim 讨论,不要自行推进。

产品层完整决策规则: `docs/agent-rules/product-decisions.md`（常驻）
产品复杂决策走: `docs/agent-rules/velo-mental-model.md` § 10 问框架（按需加载）
技术层完整规则: 本文档后续内容
📖 **开新任务前先读 `docs/README.md` § 2** —— 9 阶段工作流 × 文档 × skill 全景

## 🔴 commit 前 4 问（每次会话开头必看）

写代码 / commit 前回答下面 4 问，不能全答 yes 就停下：

1. 我**亲自读了 diff** 吗？（不是只看 subagent 报告 / pytest 数字）
2. pytest 跑过吗？
3. 这个改动**是 spec 说要的**吗？（防 scope creep）
4. 改动 >300 行 / 跨模块：**跑了代码层双审**吗？（详见 architect skill 信条 5）

**附加门禁（每次 commit 前必跑）**：`git status --short && git diff --cached --stat`。有新增 import / router / schema / migration / test helper 文件时，必须确认对应 untracked 新文件已 stage；否则干净 clone 会 ImportError 或迁移缺文件。详见 `docs/agent-rules/agent-collaboration.md §5.0`。

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
MVP 目标：GPX 上传解析 → 骑行卡片生成分享 → 赛段匹配排行榜。
团队：3 人大一学生，100 活跃用户量级。

**核心反馈环**（功能优先级跟着这个环走）：
`用户骑车 → 上传 GPX → 系统解析 → 匹配赛段 → 更新排行榜 → 用户看到排名被激励 → 继续骑`
环上最脆弱的节点 = 最该先投入的地方。

## 权威文档

> 📖 **文档全地图**：`docs/README.md`（开新任务前必读）——含 9 阶段工作流 × 文档 × skill 全景、场景速查、5 分类目录。

**执行与技术（agent 线）**
- **技术规格**：`docs/spec-v5.md`（v5 期 / 当前现行）/ 历史 `docs/archive/spec-v1.md` ~ `spec-v4.md`（v1-v4 已 ship 归档）
- **实施计划**：历史已 ship 全归档 `docs/archive/plans-phase[3-5]-*.md` + `plans-sprint-*.md`（新 sprint 启动时建新 plans/ 目录）
- **架构导览**：`docs/architecture-guide.md`（系统静态全景，每期收尾刷新）
- **数据流全景**：`docs/data-flow-guide.md`（9 条链路动态视图，修跨模块 bug 必读）
- **架构决策历史**：`docs/adr/`（10 份 ADR / 见 `docs/adr/README.md` 索引）—— 有人提议改决策时必读
- **每期战术 PRD**：`docs/prd/phase-N-prd.md`（每期开工前写，含用户故事 + 验收标准）

**战略与产品（人类线）**
- **战略 PRD**：`docs/prd/velo-vision.md` / `velo-strategy.md` / `velo-product-spec.md`（3 份 / 见 `docs/prd/README.md` 索引）
- **竞品深度分析**：`docs/competitive-analysis/`（5 份 / 见 `docs/competitive-analysis/README.md` 索引）

**运行规则（agent 常驻）**
- **agent 产品规则**：`docs/agent-rules/product-decisions.md`（常驻，规则层）
- **agent 思考框架**：`docs/agent-rules/velo-mental-model.md`（按需，mental model 层）
- **Persona 宪法**：`docs/agent-rules/persona-constitution.md`（**2026-05-20 模块已砍 / 文档保留作教训**）

**Persona Engine（2026-05-20 砍掉 / 装饰展示层不应上 sprint 主线）**
- 整目录 `app/agent/persona/` + 3 张 persona_* 表 + 6 task plans + 宪法 v0.1 **暂停不删 / 晾着**——等 3-5 天看真实反应再回头判断（永久砍 / 复用为骑后教练复盘 / 或部分组件 DeepSeek client + persona_outputs 台账复用）
- **战略失误复盘**：memory `feedback_decoration_vs_guidance_velo_persona_lesson.md` + 全局 `~/.claude/CLAUDE.md` §2.1 "装饰展示 vs 主动指导"原则
- **训练分析线**：`docs/superpowers/specs/2026-05-20-training-analytics-roadmap.md`（5 模块 6-8 周）
  - **Sprint 9 模块 A（FTP 智能化）✅ 2026-05-21 ship**：8 task + 9 hotfix / 详 `docs/prd/sprint-9-prd.md` + `docs/changelog.md` 2026-05-20→21 段
  - **Sprint 10 模块 B（PMC 训练负荷曲线 CTL/ATL/TSB）✅ 2026-05-25 ship**：6 task / Codex Desktop 首次主写代码 + Claude 异源审 / 详 `docs/prd/sprint-10-prd.md` + `docs/changelog.md` 2026-05-25 段
  - **当前主线**：Sprint 11 模块 C（训练分布 Polarized/Pyramidal/SweetSpot）待开新 PRD
  - Sprint 12 LLM 教练总结预留设计：`docs/superpowers/specs/2026-05-20-coach-engine-design.md`
  - **P1 tech debt**：ftp_estimator 算 ftp=117W vs Tim 真实 1200s best 250W（`docs/tech-debt.md`）/ 专题待排
  - **P2 tech debt**：PMC 覆盖率门槛固定 42 天窗口 / 全年视图被一刀切挡（`docs/tech-debt.md` / Sprint 10 遗留 / 下次修 range 联动）

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
3. **纯函数模块先 fixture 后实现**
4. **模块单向依赖**：User ← Activity ← Segment ← Notification ← Strava
5. **不做 spec 没要求的功能 / 顺手优化**
6. **稳扎稳打有疑必停**：架构不清晰 / 自查发现隐患 / 信心不足 → 立即停，与 Starsky 讨论再动手。宁可多花一天讨论，不带隐患赶进度
7. **独立判断**：方案过度设计 / 时机不对 / 性价比低 → 直接反驳给替代方案（详见 architect 信条 3）
8. **三重审判（硬性，违反 = 双重违规）**：
    - spec 层（写完 spec）+ 代码层（每批 subagent 产出后）跑 Claude 内部双审（Agent A 忠 spec / Agent B 集成审）
    - **代码层 commit 前追加 Codex 异源第三审**（独立训练分布，抓 Claude 系统性盲区）
    - Codex 审查协议：调用 `codex:codex-rescue` subagent，prompt 按 `docs/agent-rules/agent-collaboration.md §4 场景 B` 模板填
    - 迭代纪律：Codex 抓到 Critical/Important → Claude 修 → **同 threadId `--resume` 复查** → 最多 3 轮收敛
    - 跳过场景：纯文档 / 单文件 <50 行 / 紧急 hotfix（理由写在 commit message）——完整跳过清单见分工宪章 §5
    - 2026-04-23 v4 task-7.10 实验 1 验证：Codex 一轮抓到 1 条核心反馈环级 Important + 1 条 UX Important，Claude 双审均漏
    - 详见 architect 信条 5 + `docs/agent-rules/agent-collaboration.md`（Claude ↔ Codex 完整分工规则 + 4 个场景 prompt 模板）
    - ⭐ **2026-04-28 新增硬规则**：派 codex 写大文档（spec / plans / > 800 字 / > 1500 行）= **默认禁止**——codex CLI 单 task 输入+输出 > 50K token 几乎必卡（已知 bug 链 #13738/#14048/#18723，2026-04-28 v5 spec 实证卡死 30+ 分钟）。**默认路径**：主 agent 自己写 → 写完派 codex review-only。详见分工宪章 §5 + memory `feedback_main_agent_as_middle_manager.md` §2.1
9. **链路收尾三问复盘**（spec 链路完成时跑，不是每个 task）：新 bug 模式 / 设计判断 / 流程问题 → 识别完直接调 `/neat` 分发到 memory / CLAUDE.md / docs（详见 architect 信条 11 + neat-freak skill）
10. **spec 自审 2 项**（architect Step 7 双审之外的项目特定补充）：
    - **状态机完整性**：所有合法状态转换画完整图，含异常恢复路径——遗漏一个状态转换 = 未来踩 bug
    - **共享逻辑识别**：两处做同样事的代码必须抽共享函数，禁止复制粘贴（如 GPX/Strava 都要把 ParseResult 写入 DB → 抽 `save_parse_result` 共享）
11. **审核工具分层使用（2026-04-28 沉淀，三者不可互替）**：
    - **写代码过程中**（在编辑器随手扫一段）→ `/simplify` 做局部漂亮度检查（单 LLM 调用，10 秒级）
    - **commit 前**（硬性，详见原则 8）→ architect 三重审判（spec 一致性 + 跨模块集成 + Codex 异源盲区，3-5 次 LLM 调用）
    - **任务完工 / claim 完成前** → `superpowers:verification-before-completion`（强制跑验证命令读完整输出，防"嘴上说测过了实际没跑"）
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

> **活文档**：每踩新陷阱在这加一条（不要回 architect skill 加——那里只留跨栈通用 3 条）。

## 协作硬约束（项目特定）

- **Starsky 验证你的结论**：说"完成"前必须查代码验证，不只看清单。说"不确定"比说错好——他尊重诚实，不尊重自信的错误
- **细节判断 AI 自己做**：Starsky 是产品设计师视角，不会判断技术细节。AI 应自己拿主意，给整体效果让他过目（**不要列每段命运逐项让他过审**——那是强行让他做不擅长的事）
- **并行 agent 不浪费等待**：讨论同时后台跑调研

详细沟通格式（决策表格、三段节奏、生活类比）见 architect 信条 7。

## 部署经验（第 2 期踩坑总结）

> **核心教训：本地测试全绿 ≠ 生产能跑。** 测试用 SQLite + mock，不连真 Docker/PostgreSQL/Strava API。

### 部署 SOP（每次部署必跑 4 步，顺序不可乱）

```bash
# 1. 服务器 pull 最新代码
ssh ubuntu@114.132.190.245 "cd ~/velo && git pull origin main"

# 2. rebuild 所有受影响容器（不是 restart / restart 不会拿新代码）
# ⚠ 2026-05-20 实证：只 rebuild api 漏 worker / 让 worker NPC hook 静默失效 30 分钟（Persona 已砍 / 教训留底）
# api / worker / cleanup / monitor / scheduler / curation-pool-cron 共享 `build: .` 同一 image
# 改任意 app/*.py 都要 rebuild 该 service 对应的容器（worker 改了必 rebuild worker）
# 最稳：不指定 service / docker 自动 rebuild + 重启所有受影响容器
ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build"
# 边界确定时才指定（仅改 router.py 等只影响 api）：
# ssh ubuntu@114.132.190.245 "cd ~/velo && sudo docker compose up -d --build api"

# 3. 跑 alembic upgrade（硬性必跑 / 哪怕你"觉得这次没改 schema"）
#    2026-05-15 实证：跳过这步 = 生产新代码引用未建表 / 全 endpoint 500
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -m alembic upgrade head"

# 4. curl 真 endpoint 验证（不只看 docker ps Up）
ssh ubuntu@114.132.190.245 "sudo docker compose -f ~/velo/docker-compose.yml exec -T api python3 -c \"import urllib.request,json; print(json.load(urllib.request.urlopen('http://localhost:8000/api/segments/1'))['id'])\""
```

**为什么 alembic upgrade 升成硬性步骤**：并行开发时，**任何 sprint 加了迁移文件，所有人部署时都得跑**——哪怕你这次没改 schema。2026-05-15 实证：Tim 隐私 sprint 加了 `activity_privacy` 表迁移，我做坡度 sprint 部署时没跑 → 生产全 endpoint 500。

### 部署前强制检查清单

- [ ] **requirements.txt 完整**？本地 pip install 的新包都写进去
- [ ] **docker-compose.yml 同步**？.env 加新变量 → docker-compose 的 environment 也加
- [ ] **Alembic 迁移在 PostgreSQL 上能跑**？不要在迁移脚本中用 Python try/except 包 DDL——PG 事务 abort 后所有后续 SQL 都失败。用 `DO $$ EXCEPTION` 块隔离
- [ ] **第三方 OAuth 回调地址配了**？代码里写 redirect_uri 不够，第三方平台后台也要配
- [ ] **服务器能连 GitHub**？大陆服务器不稳定。备用：本地 scp 上传 / 服务器 sed 改文件

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
| scheduler 不跑 | ⚠️ | 无独立容器 → 导入永远不推进 | 待 v4 task-7.9 修 |
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

