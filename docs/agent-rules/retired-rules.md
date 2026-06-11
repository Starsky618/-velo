# 退役规则归档

> 规则代谢条款（CLAUDE.md / 2026-06-10 拍）的落点：被替代 / 被脚本吸收的规则从 CLAUDE.md 硬加载移出，全文归档于此。归档 ≠ 否定——每条带退役原因与"复活条件"，历史实证锚保留可查。

---

## 三重审判（2026-04 立 → 2026-06-11 退役为"风险分层审查"的高危批次分支）

**退役原因**：2026-06-11 Sprint 13 实证账本——plans+T1 的审实比 11:1（约 55 万:5 万 token）；Critical 收敛曲线显示模型代际变强（v4/v5 时代 spec 双审 12→7→1→0，今 spec 四轮 0C / 代码 0C）；"无运行时后盾"的真发现（门禁路径 bug / SQLite FK 盲区）全部来自 grep 实证型集成审，spec 忠诚审在"task 卡已细化"的代码上只产出 cosmetic + 1 个误报。预读纪律 + TDD + pre-commit 门禁已接管旧双审的大半工作。Tim 拍：默认砍到 1 道集成审，高危批次（schema/迁移/隐私门禁/不可逆数据/并发竞态）保留完整三审。

**复活条件**：真用回归 / 上线 4 周数据开始抓到"原来双审会抓的事故" → 收紧回本制度（现行规则的度量退出条件已写明）。

**旧规则全文（2026-06-11 前的 CLAUDE.md 原则 8）**：

> 8. **三重审判（硬性，违反 = 双重违规）**：
>     - spec 层（写完 spec）+ 代码层（每批 subagent 产出后）跑 Claude 内部双审（Agent A 忠 spec / Agent B 集成审）
>     - **代码层 commit 前追加 Codex 异源第三审**（独立训练分布，抓 Claude 系统性盲区）
>     - Codex 审查协议：调用 `codex:codex-rescue` subagent，prompt 按 `docs/agent-rules/agent-collaboration.md §4 场景 B` 模板填
>     - 迭代纪律：Codex 抓到 Critical/Important → Claude 修 → **同 threadId `--resume` 复查** → 最多 3 轮收敛
>     - 跳过场景：纯文档 / 单文件 <50 行 / 紧急 hotfix（理由写在 commit message）——完整跳过清单见分工宪章 §5
>     - 2026-04-23 v4 task-7.10 实验 1 验证：Codex 一轮抓到 1 条核心反馈环级 Important + 1 条 UX Important，Claude 双审均漏
>     - 详见 architect 信条 5 + `docs/agent-rules/agent-collaboration.md`（Claude ↔ Codex 完整分工规则 + 4 个场景 prompt 模板）

**保留的历史实证锚（这些不退役，仍是高危批次保留三审的依据）**：
- 2026-04-23 v4 task-7.10：Codex 一轮抓到反馈环级 Important + UX Important，Claude 双审均漏
- 2026-05-28 约骑 spec Round 6：FK+CHECK 死锁，Claude 双 reviewer 12 轮全漏，Codex 异源抓出
- 2026-06-01：Claude 自写代码跳过 Codex 异源审 → 补审挖出 7 Important（/mine 按钮全错 / 孤儿文件 / 路径绕过 / 上传卡死）
- 2026-06-02：私圈 uploads 整卷泄露 Critical（隐私路径——正是新制度划入高危批次的原因）
