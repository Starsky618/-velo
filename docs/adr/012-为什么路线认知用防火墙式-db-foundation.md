# ADR-012: 为什么路线认知用防火墙式 DB foundation,不直接改旧路线主流程

## 状态
accepted (2026-06-19)

## 上下文

velo 原本只有两类路线相关对象：

- `segments`：正式赛段,服务上传匹配、排行和 PR/KOM 主反馈。
- `route_books` / `route_guides`：路线/路书内容,服务约骑、路线百科和用户文案展示。

2026-06 路线认知设计把问题扩大了：VELO 不只是要存一条路线,还要知道“这条路线为什么被这样理解”。

这带来一组新对象：

- 路线版本：`route_versions`
- 证据和判断：`judgment_runs` / `evidence_items`
- 进入路线认知的 segment 白名单：`route_cognition_segments`
- 路线体系容器：`route_collections`
- 语义概念：`concept_nodes`
- 候选关系：typed candidate tables
- 正式关系：formal concept links / membership tables

架构上有三种选择：

1. **胖旧表**：把概念、关系、审核字段直接加进 `segments` / `route_books` / `route_guides`。
2. **万能图谱表**：建 `nodes` / `links` 或 `entity_type/entity_id` 泛型关系表。
3. **防火墙式 DB foundation**：在 `app/route_cognition/` 下建强类型表,用真实外键接旧表,先完成数据库地基,不立刻接 public API / admin UI。

## 决策

采用方案 3：**route cognition 用防火墙式 DB foundation。**

核心规则：

- 新表放在 `app/route_cognition/` 对应的模型和迁移里。
- 旧 `segments` 不自动进入路线认知；必须通过 `route_cognition_segments` 白名单。
- `route_versions.reference_line_snapshot` 是路线几何真相源；`route_segments` 只是组成/解释层。
- `route_collections` 是有成员、统计、顺序、地图范围的容器,不是 `concept_nodes`。
- `concept_nodes` 是语义概念,不等于路线集合。
- candidate 必须是 typed tables,禁止 generic polymorphic candidates。
- formal links / formal memberships 不能由 AI 或 agent 直接写,必须有 human_review judgment。
- v1.1 DB foundation 完成后停止继续建 schema,转入内部 writer、审核流程和小范围 seed 数据。

## 理由

1. **不污染主反馈链路**。VELO 的核心用户体验仍是上传骑行 → 匹配赛段 → 排行榜 → 通知。路线认知如果直接改 `segments` 或 `segment_efforts`,任何 schema 失误都会打到主反馈。

2. **路线知识需要审计,不是直接生成**。概念、路线体系、成员关系都带判断色彩。AI 可以提出候选,但正式关系必须能回答“谁审核、依据是什么、为什么成立”。

3. **强类型外键比万能图谱更安全**。`route_concept_links`、`segment_concept_links`、`collection_concept_links` 分表后,PostgreSQL 能用真实外键防止错挂。万能 `entity_type/entity_id` 看起来省表,实际把一致性检查推给应用层。

4. **DB foundation 和产品运营要分开**。先建表是为了把边界钉牢,不是为了立刻让用户看到。没有 writer、admin review、seed 数据和只读 API 前,产品还不能算运营完成。

5. **未来可以小步接入**。内部 writer 可以先服务 Taiyuan/Xishan 小样本,验证判断和审核流程；等数据可信后,再接 route concepts、collection details、route composition 这类只读 API。

## 后果

### 正面

- 主路线/赛段/约骑链路保持稳定。
- 旧内容投影 `content/routes/**`、`guide.md`、`route_guides.content_md` 不被 agent 直接改。
- typed candidates 和 formal hard gate 把 AI 建议、人工审核、正式关系分开。
- `route_segments` 可以解释路线组成,但不会篡改路线几何真相源。
- v1.1 完成态可清楚表达：DB foundation complete, product not operationally complete。

### 负面

- 表数量明显增加,主架构文档需要额外说明。
- 初期没有用户可见收益,容易被误判为“只是在建表”。
- 后续 writer / reviewer / seed 数据不做,这些表会长期空转。
- 查询 route concepts 或 route composition 时需要 join 多张表。

## 触发重新评估的条件

以下情况出现时,可以新开 ADR 修订本决策：

- route cognition 进入大规模 public API / UI 阶段,需要读模型或缓存层重新设计。
- typed table 数量继续膨胀,维护成本超过外键带来的收益。
- formal writer 工作流成熟,需要把 write guard 抽成跨模块通用审计框架。
- 未来真的引入 external search worker / embeddings,需要新证据层或索引层。

## 当前边界

截至 2026-06-19：

- 最终 Alembic head：`20260618_membership_formal`。
- 已完成：route cognition v1.1 DB foundation。
- 未完成：public API、admin UI、external search worker、segment_submissions、membership candidates、bulk backfill、用户可见 concept 页面。
- 下一步：内部 writer services、共享 write guard、reviewer/admin workflow、小范围 Taiyuan/Xishan seed 数据。

## 相关文档

- `docs/research/route_cognition_v1_1_completion_report.md`
- `docs/research/route_cognition_v1_1_operationalization_plan.md`
- `docs/research/route_cognition_v1_1_status.md`
- `docs/research/route_cognition_v1_1_scope_reset.md`
- `docs/architecture-guide.md` §2 / §4 / §7.4
- `docs/data-flow-guide.md` §10.9 / 链路 22
- ADR-008: 为什么防火墙式扩展
- ADR-009: 为什么 agent 层独立
