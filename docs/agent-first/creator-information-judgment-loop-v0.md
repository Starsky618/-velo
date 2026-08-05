# Creator Information & Judgment Loop v0

> 状态：TypeScript 本地闭环已通过 PR #49 合并；spec 忠诚审查与跨模块集成审查均为 Critical 0 / Important 0，CI TypeScript 56/56、pytest 2447 passed / 0 skipped。它证明 JSONL Shadow 的事件合同、权限和 Context 重放，不代表生产 Agent、数据库或 UI 已上线。

## 1. 这次真正解决什么

Creator Agent 的目标不是记住更多聊天，而是让下面四类东西永远不再混成一团：

1. 原始话语和路线材料；
2. Agent 基于材料提出的判断；
3. Tim 对某个精确判断的确认或拒绝；
4. 当前模型运行真正加载的判断、证据、矛盾和省略项。

本闭环的用户效果是：即使聊天窗口被压缩、Codex 任务结束或 Node 进程重启，Creator 仍能从追加事件重建“Tim 当前确认了什么、旧判断为何失效、依据来自哪里、还有什么冲突没有解决”。

## 2. 从 Reborn 学到什么

研究基线是 `Reborn@cb9a8ae` 及其最新会话 `019fc7cf-66d1-7af1-ae36-54e7acf568c9`，不是旧总结。

| Reborn 机制 | 实证 | VELO 怎样吸收 |
|---|---|---|
| 通道角色不等于实际作者 | `agent_runtime/state/engine.ts:162-267` 分开校验 `source_role`、`actor`、`authorship_basis` | Creator 原始 turn 保存三者；只有 Tim 用户 turn 且有直接/人工复核作者证据，才可能承载判断响应 |
| 候选不能自动成为 Current | `agent_runtime/state/engine.ts:249-275` 对 `current_explicit` 设置额外门禁 | Agent 只有 `judgment.propose`；`judgment.decide` 属于独立 reviewer capability |
| Current 与低权重 recall 分开 | `agent_runtime/state/engine.ts:733-765,822-876` | Creator Context 只装载未被替代的 `tim_confirmed` 判断；拒绝和旧版本只进入 omission，不冒充当前真值 |
| 主线允许发散，但分支状态不能丢 | `agent_runtime/learning/engine.ts:658-697` | v0 先保留 Creator mission、pending proposal、未决 contradiction；讨论分支账本暂不复制到 VELO |
| “听过”与“现实验证”不是一个等级 | `agent_runtime/learning/engine.ts:195-218,243-290` | Context 冷启动一致只是机械 Eval；它不证明路线判断真实，也不能直接发布 Published World |
| 智能放进确定性外环 | `.reborn/experiments/E005-two-lane-learning-mastra.md:64-91` | 模型端口只返回 typed action；event validator、capability、revision、确认绑定、替代和 Eval 由 TypeScript reducer 掌控 |

## 3. 哪些不能照搬

### 3.1 不按“最新时间”自动替代 Tim 判断

Reborn 当前快照对同 key 事件默认按 `observed_at` 选择最后一条，只有同一时刻冲突才要求显式 `supersedes`（`agent_runtime/state/engine.ts:366-407`）。这适合 Current Tim v0 的受控导入，却不够支撑 VELO 审核动作。

VELO 的替代必须经过三步：

1. 新 proposal 明确引用 `supersedes_judgment_id`；
2. Tim 响应绑定新 proposal ID 与 statement hash；
3. 只有响应为 `tim_confirmed`，旧判断才标记 `superseded`。

新提议被拒绝时，旧确认判断继续有效。

### 3.2 不把 CLI 开关冒充 Tim 身份

Reborn 的 `allowCurrentExplicit` 是导入门禁，不是已认证的人机审核收据。VELO v0 因此把权限拆成 Creator Agent 与 Tim Reviewer 两个 principal；JSONL 保存由 Store 在授权后生成的 principal/product/environment/capability receipt，冷重放不再注入万能 principal。当前仍只有 test principal，生产 UI 必须把 reviewer capability 绑定到真实登录和不可伪造的审核动作。

### 3.3 不复制手写 stale lock

Reborn 当前手写锁会在判定 stale 后递归删除 lock，并在 finally 再删除（`agent_runtime/state/engine.ts:484-537`），存在所有权竞争需要继续审计。VELO 继续使用 `proper-lockfile` 的原子 mkdir、heartbeat、stale recovery 和 ownership-aware release，不复制这段实现。

### 3.4 Context 必须带 Manifest

Reborn 当前文本 Context 会输出选中项，但没有记录完整 source revision、遗漏原因和编译 hash（`agent_runtime/state/engine.ts:822-876`）。Creator v0 每次编译同时返回：

- workspace revision 和最后 event；
- 带确定性 `as_of` 的 request hash 与 context hash；
- 当前 judgment、pending proposal、turn、evidence、contradiction refs；
- source event/rights revision、不可变 blob/provider ref、content hash 与 provenance；
- superseded、rejected、resolved、subject mismatch、rights not allowed、review due、already processed 和 budget omission。

支持当前判断的证据不受 `max_evidence` 预算裁掉；预算只能删可选背景证据。source 最新 rights 不再 allowed、judgment 到达 `review_at` 或引用跨 subject 时 fail closed，不能继续把原文交给模型。

## 4. 当前事件闭环

```text
source_ingested + rights_checked
  ↓
conversation_turn_recorded / evidence_recorded
  ↓
Creator model consumes compiled context
  ↓
judgment_proposed (proposal + statement hash + context hash + model ref)
  ↓
Tim turn with exact judgment_response interaction
  ↓
judgment_responded: tim_confirmed | rejected
  ↓
contradiction → explicit replacement → confirmation → resolution
  ↓
compile current context → cold replay Eval
```

几个硬边界：

- 普通“我同意”文字没有 `judgment_response` interaction，不能确认任何判断。
- Agent principal 即使拿到正确 proposal 和 Tim turn，也没有 `judgment.decide` capability。
- 同一 `source_message_ref` 不能重复写入；同 event ID 不同内容 fail closed。
- `judgment_response` turn 必须在 exact active proposal 之后记录，不能先伪造“Tim 已确认”再补 proposal。
- replacement proposal 不会提前抹掉旧判断；确认新判断后才替代。
- `needs_more_evidence` 继续保持 contradiction 未决；只有 dismissed/superseded 才关闭。
- resolved contradiction 和 superseded/rejected/review-due/rights-blocked judgment 不进入 current context，但保留在事件链和 omission manifest。
- Creator private read 在调用模型前校验 capability；commit 响应不明时按 exact event 重读，重试同 event 不再次调用模型。
- Creator 仍然只有 World Change Proposal，没有 publish 事件。

## 5. 代码所有权

| 路径 | 责任 |
|---|---|
| `agent_runtime/creator/state/` | 事件合同、exact-key 校验、revision reducer、权限、替代与矛盾状态 |
| `agent_runtime/creator/context/` | 从 CreatorView 编译最小 Context 与 Manifest |
| `agent_runtime/creator/runtime/` | 可替换模型端口、确定性 fake model、typed action 到 event 的提交 |
| `agent_runtime/creator/eval/` | 空聊天上下文、冷进程重放一致性与禁止旧判断复活的 Eval |
| `tests-ts/creator-information-loop.test.ts` | 真实天龙山定本和路线认知蓝图的本地 Shadow 闭环 |

## 6. 真实材料证明了什么

测试直接读取仓库中的：

- `content/routes/tianlongshan/guide.md`；
- `content/routes/tianlongshan/meta.json` 的 Tim 拍定本来源；
- `docs/agent-first/source/VELO_路线认知基础设施_v0.1.md` 的“线性 / 核心爬坡 / 半开放”分类。

闭环先形成较粗判断，再用蓝图证据提出显式替代；Shadow Tim reviewer 确认后，全新 Node 进程冷启动 Context 只保留新判断，旧判断和已解决矛盾只出现在 omission。repository Source 保存当前内容对应的 Git blob ref；每条 event 保存实际 test principal/capability receipt。这里的 reviewer 是测试协议，不冒充 Tim 在生产环境已经执行过审核。

它证明：合同、权限、替代语义、来源追踪和重放有效。它没有证明：材料本身百分之百真实、模型推荐质量、腾讯连接质量、骑友接受度或 Published World 可以上线；Judgment → Claim/Eval → World Change 的 adapter 与防旧信息发布 Eval 明确留给后续切片。

## 7. 数据库现在可以怎样进入

本地闭环已经暴露了第一批稳定读写：

- workspace revision 的串行追加；
- source 与 exact raw turn 去重；
- proposal/decision 的强绑定；
- 当前 judgment 投影与 supersession；
- contradiction 生命周期；
- Context 按 subject、状态和 evidence ref 查询；
- run 所用 context hash/model ref 的审计。

最小 PostgreSQL 持久化已经形成 [`CREATOR_POSTGRESQL_SPEC_V0.md`](../../agent_runtime/CREATOR_POSTGRESQL_SPEC_V0.md)：以 append-only event 为真值，同事务维护可重建投影；固定 revision CAS、幂等 event ID、source message 唯一键、decision 对 proposal/turn/hash 的复合约束、Context 查询、冷重放与提交后断线 reconciliation。它仍不直接改 `users`、`activities`、`segments` 或 `segment_efforts`，也不把 JSONL 的整个 `CreatorView` 当一行大 JSON 永久固化。

下一阶段不是继续写架构叙事，而是按该规格在 CI 临时 PostgreSQL 实现首个 migration/repository 切片，并用天龙山同一事件链对账 JSONL 与 Postgres Context hash。只有空库迁移、并发、回放和回滚通过，才允许考虑生产启用。
