# 任务 4.4：v5 复盘归档

## 🎯 目标

按 architect 信条 11 + CLAUDE.md "完工三问"，把 v5 期的"新 bug 模式 / 设计判断 / 流程问题"沉淀到 memory + ADR，让 v6+ 不重蹈覆辙。

## ⛓ 前置依赖

task-4.3（部署 + E2E 全过）。

## 📤 输出契约

| 产出 | 用途 |
|---|---|
| memory 新增 / 更新条目 | 跨会话沉淀经验 |
| `docs/adr/` 新 ADR（可选） | 架构决策固化 |
| `docs/tech-debt.md` v5 实施期发现 | 转下期处理 |

## 🛠 操作步骤

### 1. 三问复盘（architect 信条 11）

#### Q1：v5 期暴露的新 bug 模式 → 存检查清单

候选条目：
- "本月 / 本周"用 UTC 切片错（CLAUDE.md 时区约定）→ 加进强制检查清单 #N
- baseline=0 守卫（codex E1 漏抓 + R3-I1）→ 加"每个除法 / 减法的分母 / 被减数 0 时语义合法吗"硬规则
- ST_Intersection 双 LINESTRING 返 GeometryCollection 漏判 → 加 PostGIS 陷阱清单
- API 嵌套响应字段安全访问（陷阱 #9）模式确认有效

#### Q2：v5 期可复用设计判断 → 存 memory

候选 memory：
- spec 三轮双审收敛节奏（Critical 14 → 8 → 3 → 0）—— 每轮焦点不同，第二轮挖出第一轮没看到的，但是 Critical 数量递减可预期
- "代码事实表"在 spec §0.1 把"现有代码"事实预先 grep 列出 —— 后续章节避免脑补虚构，被双审抓出的 Critical 70% 是这类
- 主 agent = 中层管理（已 memory）—— 本期实证：让 Tim 看 600 行样本被怒怼"以后禁止越级上报"
- codex 异源审查的甜区：纯函数边界 + 数据流跨模块完整性，**不擅长**抓 spec 自洽 / 命名风格

#### Q3：v5 期暴露的流程问题 → 更新规范

候选改进：
- 主 agent 写大文档（spec / plans）默认禁止派 codex（已落进 memory + CLAUDE.md）
- 每次给 Tim 输出前过 3 个问题（已 memory 落实）
- spec 双审分批策略（按模块隔离）—— 是否进 architect skill v1.4

### 2. 写 memory 条目

按 `~/.claude/projects/-Users-macbookair-Desktop-velo/memory/` 的格式：

```markdown
---
name: spec dual review converges in 3 rounds with declining Critical counts
description: spec 三轮双审典型收敛节奏 14→8→3→0；每轮焦点不同抓上一轮盲区；按模块隔离派 batch 避免污染
type: feedback
---
（v5 实战内容）
```

更新现有 memory：
- `feedback_simplification_rule_vs_tool.md`（已加禁止越级 2026-04-29 拍）
- `feedback_main_agent_as_middle_manager.md`（v5 实证案例补充）

### 3. 写 ADR（如有架构级决策）

候选 ADR-011：
- "app/common/* 层引入决策"—— v5 抽 common.geo 解决反向依赖，未来共享工具放此层
- "AI 内容生成走 RQ 异步而非同步阻塞"—— 决策记录 + 替代方案对比

放 `docs/adr/`，按现有 ADR-001~010 格式。

### 4. tech-debt.md 新增 v5 期发现

候选条目（按 P1/P2 分级）：
- P2: power_curve 假设 1Hz 采样，非均匀采样精度不准（spec §7 已限定）
- P2: city 推断对跨省 / 海外起点不准（spec §7 限定靠 5.D.3 人工修）
- P2: 候选池脚本周一次跑，新赛段最长 7 天才进候选池（spec §7 限定）
- P3: AI 草稿质量依赖人工审核（PRD D-P10）

## ✅ 验收

```markdown
### v5 复盘归档（task 4.4）

- 新增 memory：N 条
- 更新 memory：N 条
- 新增 ADR：N 个（编号）
- tech-debt 新增：N 条 P2/P3
```

## 📝 commit

```
docs(retro): 任务 4.4 v5 复盘归档

- memory 新增/更新（N 条）
- ADR-011 / ADR-012（如有）
- tech-debt 新增 v5 实施期发现 P2/P3（N 条）

三问复盘：
- Q1 新 bug 模式：BJ 时区切片 / baseline=0 守卫 / ST_Intersection 漏判
- Q2 设计判断：spec 三轮收敛节奏 / 代码事实表预读
- Q3 流程改进：禁派 codex 写大文档 / 主 agent = 中层管理实证
```

## 🔍 自检三问（meta：复盘自身的复盘）

1. **诚实标准**：踩坑写实情况，不美化（"我做对了 X / 但漏了 Y"）。  
   → 是。memory 是给未来自己看的，骗自己没意义。

2. **可复用性**：写下来的 memory 半年后任意 v6+ 任务能拿来用吗？还是只对 v5 有效？  
   → 测试：抽一条 memory 想象在 v6 任意场景能不能用上。不能用的删。

3. **流程改进的可执行性**：每条改进有具体执行点（如"加进强制清单第 N 条"）还是空话（"以后注意"）？  
   → 必须有执行点。空话不进 memory。
