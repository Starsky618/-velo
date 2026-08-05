# Creator PostgreSQL Persistence v0 · 双审记录

日期：2026-08-06
分支：`codex/creator-pg-persistence-v0`

## 审查结论

- spec 忠诚审查：Critical 0 / Important 0。
- 跨模块集成审查：Critical 0 / Important 0。
- 两位审查 Agent 均基于最终冻结 diff 独立复跑门禁，不采信实现者的“已修复”声明。

## 审查中修掉的问题

- Python 接受 TypeScript 无法冷重放的非规范时间、错误 content hash、非法 Context budget 和非有限 scalar。
- JavaScript safe integer、Unicode scalar 与 UTF-16 排序未形成跨语言精确合同，可能让 PostgreSQL event truth 在 Node 回读时静默变值、重排或 hash 失败。
- workspace ID 可进入 HTTP path segment，bootstrap 冲突映射不准确，source message uniqueness 与真实 reducer 语义不一致。
- HTTP Store 在并发 writer 后可能把 revision N+1 错当成 N 的提交结果，且 Runtime 对账可能认领另一 principal 的同 payload 事件。
- Python 接受 TypeScript persistence v0 不支持的事件族；现由两端显式九类 allowlist fail closed。
- migration 存在冗余 unique，rights check ID 可在历史上复用；现由约束和回归测试关闭。
- 交接文档曾把 projection-native Context 冒充已完成，并写错 6 个真实表名；现已按 migration 和运行边界同步。

## 最终验证

- `npm test`：81 passed / 0 failed / 0 skipped。
- 强制真实 PostgreSQL：16 passed / 0 failed / 0 skipped。
- `python3 -m alembic heads`：`20260806_creator_pg_v0 (head)`。
- Python compileall、YAML parse、`git diff --check`：通过。
- 完整历史 migration、PostGIS 与 Redis：仍由本 PR GitHub CI 作为合并门禁。

## 未启用边界

- 未执行生产 migration，未挂载 Creator router，未配置生产 bearer 身份。
- 未实现 projection-native Context、drift-stop/alarm、真实 Tim UI 或真实模型 loop。
- 未修改 Rider、Published World、腾讯、Strava、小程序或既有核心业务表。
