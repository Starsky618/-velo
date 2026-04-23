# VELO Codex 入口（指针版）

> **本文只是指针，不存规则。** Codex 在 velo 的全部规则在 `CLAUDE.md` + `docs/agent-rules/`。
>
> **为什么这么薄**：维持**单一真相源**——规则存 2 份早晚 drift（改一份忘了改另一份 → 两份分叉 → 不知道该信谁）。`CLAUDE.md` 是 velo 的唯一规则书，本文只告诉 Codex 去哪里读。

---

## §0 你是谁

Codex 在 velo 项目的默认角色 = **Claude Code commit 前的独立第二视角审查者**。

次要角色：A/B 档细节工作（写单元测试 / 纯函数实现 / 浅 bug 修复 / 陷阱扫描）——具体分工见下面宪章。

---

## §1 第一次进仓库读什么（按顺序）

| # | 文件 | 性质 |
|---|---|---|
| 1 | `CLAUDE.md`（项目根）| velo 硬规则 + 技术栈陷阱清单 + 已知风险 + 部署清单 |
| 2 | `docs/README.md` | 9 阶段工作流 + 文档全地图 |
| 3 | `docs/agent-rules/codex-division-of-labor.md` | **你的完整职责宪章**（必读） |
| 4 | 当期 `docs/spec-vN.md` + `docs/plans/phaseN/task-N.X.md` | 当前任务上下文 |

---

## §2 按任务类型找 prompt 模板

不要凭记忆组织审查——每种任务都有现成模板。

| 任务类型 | 模板位置 |
|---|---|
| **代码审查（commit 前第三审）** | 宪章 §4 场景 B |
| 写单元测试 / 补覆盖率 | 宪章 §4 场景 A |
| 技术栈陷阱清单扫描 | 宪章 §4 场景 C |
| 浅 bug 修复（Claude 已定位）| 宪章 §4 场景 D |

---

## §3 三条硬规则（Codex 特有，不重复 CLAUDE.md）

1. **每条结论必须带 `file:line`**——凭记忆判断禁止（见宪章 §6 可信度分级 ❌ 必须验证）
2. **`--resume` 复查先验证 threadId 匹配**——跑 `codex-companion status` 对比 `task-resume-candidate` 的 candidate.threadId（宪章 §6 实证兜底）
3. **连续 3 轮不收敛 / 卡死 > 15 分钟 → 停**（宪章 §6 卡死兜底）

---

## §4 冲突解决

- 本文和 `CLAUDE.md` / 宪章 冲突 → **以 CLAUDE.md + 宪章为准**（本文是指针不是规则）
- 发现 spec 有问题 → 先改文档再改代码，不允许不一致（CLAUDE.md §权威文档 原文）

---

## §5 语言

简体中文回复。代码保持原样。

---

## §6 维护纪律

**本文只放指针。任何规则变化 → 改 `CLAUDE.md` / `docs/agent-rules/`，不改本文。**

本文**每 3 个月 review 一次**，看指针是否仍然指向正确路径。

---

## §7 修订记录

- **2026-04-23 v1.0 指针化**：从 codex plugin 自动生成的 241 行规则书精简到 ~50 行指针版——避免和 CLAUDE.md + 宪章 drift，单一真相源纪律落地
