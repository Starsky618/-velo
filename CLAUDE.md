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

### 🔄 动作 trigger 自查（每次写报告前 mental check 5 问）

1. 我有没有把代码细节直接推给 Tim？（违反 → 改翻译层句式）
2. 我做了哪些实证 / 没做哪些？（涉及未做的 → 用最低限度不确定度自报：🟡 + 一句"未 grep / 未跑命令"）
3. 这是高风险动作吗？（涉及 schema / 生产数据 / 核心规则 → 走硬 checklist）
4. 我有没有给 Tim 任何"未来承诺"句式（"记住了 / 学到了 / 待会做 X"）？有 → **立刻** save memory / TaskCreate / 写文件落实
5. 这次决策 / 评审是否引入 spec / task 卡 / 文档偏离？是 → **立刻** Edit 同步文档（或先 git commit doc fix），再动代码。不允许"代码先改、文档后补、文档不补"
   - 修补类 edit 完成后，必须在 `CLAUDE.md` / `AGENTS.md` / `docs/spec-v*.md` / `docs/plans/**` / `docs/agent-rules/**` 范围内 `rg <旧符号>`，确认旧签名 / 旧路径 / 旧决策无残留

**光"知道规则"不够——必须动作 trigger 强制自查**。否则下次又翻车。

> 详细规则、5 条翻车实证表：`docs/agent-rules/agent-collaboration.md` §7

> 详细规则、checklist 表格、实证案例：`docs/agent-rules/agent-collaboration.md` §7

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
- **技术规格**：`docs/spec-v1.md` ~ `docs/spec-v4.md`（当前 v4 已完成，v5 待规划）
- **实施计划**：`docs/plans/phaseN/`（subagent 派工的输入）
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

> **活文档**：每踩新陷阱在这加一条（不要回 architect skill 加——那里只留跨栈通用 3 条）。

## 协作硬约束（项目特定）

- **Starsky 验证你的结论**：说"完成"前必须查代码验证，不只看清单。说"不确定"比说错好——他尊重诚实，不尊重自信的错误
- **细节判断 AI 自己做**：Starsky 是产品设计师视角，不会判断技术细节。AI 应自己拿主意，给整体效果让他过目（**不要列每段命运逐项让他过审**——那是强行让他做不擅长的事）
- **并行 agent 不浪费等待**：讨论同时后台跑调研

详细沟通格式（决策表格、三段节奏、生活类比）见 architect 信条 7。

## 部署经验（第 2 期踩坑总结）

> **核心教训：本地测试全绿 ≠ 生产能跑。** 测试用 SQLite + mock，不连真 Docker/PostgreSQL/Strava API。

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

## 当前进度

### 已完成（v0 期 + 各任务）
- v0 期所有基础任务（项目骨架/DB/JWT/User/Activity/Segment/部署）✅
- 第 0 期：地基修补 ✅
- 小程序 MVP（5 tab + 详情页 + 海拔图）✅
- 第 1 期：翻译层（10 任务 / 40 测试）✅
- 第 2 期：Strava 集成（7 任务 / 19 测试 / 已部署 / 30 条活动导入）✅
- 第 3 期：事件通知系统（6 任务 / 16 测试 / 已部署 / PR+KOM+荣誉表）✅

### 第 4 期：前端反馈环 + Strava 加固（已完成代码 + 文档收尾，待部署 + 真实 E2E）
- [x] 任务 7.1：Alembic 迁移 + 4 model 改动
- [x] 任务 7.2+7.3：OAuth state 加固 + callback 防重复绑定
- [x] 任务 7.4：Webhook subscription_id 校验
- [x] 任务 7.5：import-progress stalled + Redis 限速
- [x] 任务 7.6：Strava 现有函数加固（I7/I8/I9/I10）
- [x] 任务 7.7：解析器 activity_type 分流
- [x] 任务 7.8：mark-all-read + unread_count
- [x] 任务 7.9：scheduler 容器部署
- [x] 任务 7.10：小程序前端瘦身版（通知中心 + 荣誉 + 红点 + 免打扰；**Strava 绑定 UI 砍**留第 5 期）
- [x] 任务 7.11：收尾文档（架构导览刷新 + 黑盒度三问 + changelog；**集成测试跳过**——单元已覆盖；真实 E2E 留生产部署后）

**第 4 期总结**：
- 8 Critical + 11 Important 风险全修复
- 181 测试 passed / 0 failed
- 13 commit + 双审制度沉淀（信条 5 升级 + CLAUDE.md 顶部 3 硬规则）
- 待做（独立批次）：生产部署 + Strava 真实 E2E + 小程序手工回归

### 第 5 期：赛段内容深化 + 数据成长 + 个人页 + admin 工具（进行中）

**总览**：4 主轴（B 赛段内容 / C 数据成长 / A 个人页 / D admin 工具）= 14 子任务 / 29 张实施卡 / 8-10 周（三人并行）

**关键文档**：
- 战术 PRD：`docs/prd/phase-5-prd.md`（v0.4，Tim 拍 11 yes 决策点）
- 技术 spec：`docs/spec-v5.md`（2879 行，3 轮双审 Critical=0 收敛）
- 实施计划：`docs/plans/phase5/`（README.md + 29 张 task 卡，subagent 启动只读 README + 自己那张）

**关键产品决策（Tim 拍）**：
- 赛段目录公开访问（不要求登录）
- 看他人主页默认公开（无隐私开关）
- AI 介绍 30-50 条精选 / 单条 50-100 字
- 5W 是 5 分钟功率进步推送阈值
- 6 城枚举 + unknown：beijing / shanghai / hangzhou / shenzhen / chengdu / taiyuan
- AI 草稿 202 异步（不阻塞 admin）
- from-activity advisory lock 串行
- LLM API 走 **DeepSeek**（OpenAI 兼容 SDK，Tim 2026-04-29 拍国产 + 国内访问稳 + 极便宜）
- admin H5 独立部署（域名暂不买，先 IP）

**Sprint 进度**：
- ✅ Sprint 0 task-0.1（datetime 全局 tz-aware）— 三审收敛 commit `4a94097` + alembic 双向真 PG 验证
- ✅ Sprint 0 task-0.2（ensure_valid_token 签名改造）— commit `022e2b1` + Codex 异源审抓到的 SQLAlchemy `populate_existing` Important 已修 commit `db7e475`（CLAUDE.md 陷阱清单第 12 条沉淀）
- ✅ Sprint 0 task-0.3（ensure_valid_token 未绑定路径 + scheduler 兜底）— commit `07327b1`（Codex 抓到 scheduler 未 catch UnboundStravaError 的 Important，已闭环）
- ✅ Sprint 0 task-0.4（SQLAlchemy legacy `.get()` 替换）— commit `5e44c4f`（实测 8 处 task 卡声明 5 处）
- ✅ Sprint 0 task-0.8（app/queue.py 单一 Redis 源）— commit `04bb17d`（Codex 跳过 / 工具基础设施版本不兼容；Claude code-reviewer 4 Important 全处理）
- ✅ Sprint 0 task-0.5（scheduler Redis 复用）— **并入 task-0.8 commit `04bb17d`**，无独立 commit。task-0.8 时为便于测试 patch app.queue.redis_conn 已用局部 `from app.queue import redis_conn as r` 替代 Redis.from_url，task-0.5 目标"消除连接散点"实质已完成
- ✅ Sprint 0 task-0.6（v5 主迁移 + ORM 同步）— commit `91a3691`（Codex 异源审抓到 2 Critical：event_type VARCHAR(20) 容不下 progress_monthly_summary、payload 字段被误判推迟；2 轮收敛。spec §2 修订补遗 5.5/5.6 全部落地：payload JSONB + uniq_progress_notification_per_activity 部分唯一索引）
- ✅ Sprint 0 task-0.7（老数据回填）— commit `daf6f1f` + `01caa5e`（24 segments + 2 users 全部回填 / 双主驾首次互审 / codex 误用 ORM 实例属性 fix）

**Sprint 1：赛段内容深化 ✅ 全部完成 / 2026-04-30**
- ✅ task-1.A.1 算法纯函数 + common 包（41 测试）— `a9c1bff`（Codex 异源抓 2 Critical / haversine 对跖点 + spec import 路径偏离）
- ✅ task-1.A.2 service 扩展（搜索 + 即时反馈 + from-activity）— `9b24465`（**双主驾首战**：codex 主开发 + Claude 异源审 2 轮收敛 I1 SQL seq 切片 / I2 elevation_loss 字段缺）+ E1 修（service 契约对齐 spec §3.2.1 / 第一轮把 6 字段对比类换成 4 字段排名类，重写）— 13 测试
- ✅ task-1.A.3 router 扩展 + 即时反馈 endpoint — `bbef245` + doc fix `1a0631f`（distance_km → distance / 沿用 v4 字段名不破前端）— 11 测试
- ✅ task-1.B.1 agent 模块（DeepSeek + RQ 异步 + 状态机）— `fc3f007` + `70d4104`（codex 异源抓 1 Critical：生产 docker-compose worker 缺 DEEPSEEK_* env / 3 Important 全修）— 15 测试
- ✅ task-1.C.1 monitor 软目标（4min + 飞书告警）— `f228a6c`（codex 抓 1 Important：httpx.post 默认遇 5xx 不抛 / raise_for_status 修补）— 6 测试
- ✅ dev stack 隔离 — `3e9f50d`（独立 project name `velo-dev` 不撞生产 / db:5435 redis:16379 api:8001）

**2026-04-30 §7 升级（commit `02261e4`）**：mental check 3 问 → 5 问
- 第 4 问"承诺立刻动作落实"
- 第 5 问"决策即同步 spec/task/文档"
- CLAUDE.md 顶部 + agent-collaboration.md §7 同步
- 新增 memory `feedback_spec_drift_immediate_doc_fix.md`

**Sprint 2：A + B + C 主轴 ✅ 全部完成 / 2026-04-30**
- ✅ task-2.B.1 power_curve 算法 — `661a717`（codex 抓 1 Important：拼接测试假阳性 / 重设计为 A 末尾高 + B 开头高）— 15 测试
- ✅ task-2.A.1 progress_detector + worker hook + SAVEPOINT 升级 — `7611042` + `3abcd83`（CLAUDE.md 陷阱 #13）/ 主动捕获 spec §3.4 隐患（detector rollback 回退 worker activity.status）/ codex 网络断走 3 层兜底 — 10 测试
- ✅ task-2.C.2 part1 power_curve service + 真 invalidate — `a306bd1`（codex Critical=0 / 1 Nice-to-have `if cached is not None` 已修；JSON int→str key 统一 service 层转换）— 7 测试
- ✅ task-2.C.1 city 字段防回退（verify-only / grep 实证 ORM/Constraint/migration 全已落地）— `eee3d98` — 5 测试
- ✅ task-2.C.2 part2 余下 3 函数 + worker city hook — `1250df1`（codex 抓 2 Important：白名单测试弱 / SAVEPOINT 隔离；UnboundLocalError 修：函数顶部已 import User，函数内重复 import 触发 Python 函数作用域将名视为局部 → 之前的引用全 UnboundLocalError）— 16 测试
- ✅ task-2.C.3 user.router 4 endpoint — `bdec206`（路径命名修订 spec /api/users → /api/user 单数 / Tim 拍 A；codex 配额上限走 3 层兜底）— 17 测试

**反馈环完整跑通**：
1. 上传 GPX → worker 解析 → status='completed'
2. progress_detector 推进步通知（payload JSONB / SAVEPOINT 隔离）
3. worker 自动推 city（SELECT FOR UPDATE + populate_existing + SAVEPOINT）
4. invalidate_power_curve_cache 真删 Redis
5. 用户进个人页 → GET /api/user/me/power-curve / GET /api/user/me/heatmap / GET /api/user/{id}/profile

**Sprint 3：admin 工具 + admin H5（进行中 / 2026-05-05 batch A+B+C+D.1 完成）**

A 主轴（admin 后端 / 11 endpoint 全部 /api/admin/* 前缀）：
- ✅ task-3.A.1 ~ 3.A.5 admin 框架 + 候选池 + 草稿 + 批量管理 + from-activity（5 connection 串行 / 10 endpoint）
- ✅ task-3.A.6 admin from-gpx endpoint + 老 POST /api/segments Sunset 2026-06-30 deprecated + Hausdorff 共享 helper（commit `1432fad`）
- ✅ task-3.A.7 admin whoami endpoint（commit `4796704` / admin H5 D.1 登录验证用）

C 主轴（数据基础）：
- ✅ task-3.C.1 候选池脚本 + cron（commit `6c14efa`）

B 主轴（admin H5）：
- ✅ task-pre-3.B segment/service.py 拆分（793 红灯 → service.py 189 + service_create.py 257 + service_query.py 380 / commit `1c70a02` / 元层 blocker）
- ✅ task-3.B.1 D.1 admin H5 项目骨架 + JWT 登录 + 路由壳（独立 repo `~/Desktop/admin-h5` / GitHub `Starsky618/admin-h5` private / Vite + React 19 + TS + AntD 6 / vite build 262ms 0 TS errors / commit `b8d4043` 在 admin-h5 repo）
- ⏳ task-3.B.1 D.2 候选池审查页（下一个 sub-task）
- ⏳ task-3.B.1 D.3 草稿审核页 / D.4 批量管理页 / D.5 部署
- ⏳ task-3.B.2 segment-creator.html 增强（D 全完成后）

**Sprint 3 元层升级（2026-05-05 本会话）**：
- 全局 ~/.claude/CLAUDE.md TL;DR + §2.1 加"元认知批判性思考（决策前必跑 / 区分合格 vs 顶级工程师的核心层）"为最高优先级锚点
- velo CLAUDE.md 技术栈陷阱清单第 15 条（PostGIS `ST_*` 函数在 SQLite 测试 fixture 不可用 / 加 dialect 守卫）
- memory 6 处升级（详 MEMORY.md / 含元认知批判 / 视觉冲击 vs 真复杂度 / 读 diff 不只读报告 / pytest exit code 不可信 / Edit 全角标点 / untracked 待办列表）

**当前位置**：Sprint 3 D.1 完成 / 下一个 = **task-3.B.1 D.2（候选池审查页 / ~1 天 / 派 codex 主开发 + Claude 多轮审）**。

**生产环境配置**（Tim 已配 ~/velo/.env）：
- DEEPSEEK_API_KEY ✅
- DEEPSEEK_MODEL=deepseek-chat ✅
- 备份：`~/velo/.env.bak.20260429`

**Sprint 0 closure 硬约束（v2 / 2026-04-29 调整）**：task-0.1 ✅ + task-0.6 ✅ + task-0.8 ✅ = Sprint 0 schema 闭环完成；task-0.7 与 task-1.A.1 配对延后（先做 1.A.1，再回 0.7 真跑+verify）。
- 调整理由：原 closure 把 0.7 列必做，但 0.7 spec §2.6 顶层 import `app.segment.service.calculate_max_gradient` 等函数，这些函数在 1.A.1 才实现 → 0.7 现在写完连 Python load 都炸 → "占位脚本"无价值。
- Sprint 1 启动条件实际是：DB schema 就位（0.6 已落地）+ 单一 Redis 源（0.8 已落地）+ tz-aware（0.1 已落地）。算法函数 1.A.1 写完后 0.7 立刻回填 = Sprint 1 内部第一动作。

**新会话起手必读**（给下次 /clear 后的主 agent）：
1. 本 CLAUDE.md（项目规则 + 进度 / **Sprint 3 D.1 完成** / 当前 = `task-3.B.1` D.2 候选池审查页）
2. `docs/plans/phase5/task-3.B.1.md`（D.2-D.5 sub-task 在 §5-§7 / 完整代码模板可直接抄改）
3. **admin H5 工作目录** `~/Desktop/admin-h5`（独立 GitHub repo `Starsky618/admin-h5` private / Vite + React 19 + TS + AntD 6 / baseline 已就绪 / vite build 实证通过）
4. **velo backend admin endpoint 全在** `/api/admin/*` 前缀（task-3.A.1 ~ 3.A.7 / 11 个 endpoint / 含 `/admin/whoami` 给 admin H5 登录用）
5. memory（自动加载 / 25 条 / 含元认知批判性思考 + 视觉冲击 vs 真复杂度 + 三审 3 层兜底 + 等）
**禁止**：读 spec-v5.md 全文（2879 行污染上下文）—— task 卡有 spec 行号引用，需要时只读那段。
**D.2 起手第一动作**：派 codex 主开发 + Claude 多轮审 / codex prompt 强调"baseline 已就绪 / 不要 npm install / 只需写 src/api/curation.ts + src/pages/CurationPoolPage.tsx + 实证 npm run build / 不要 commit 让 Claude 多轮审"。
