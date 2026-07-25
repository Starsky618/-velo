# Route Cognition v1.1 Scope Reset

> 2026-07-20 产品恢复说明：本文保留为数据库与内部流程的历史范围证据，不再充当公共
> Route UX 的当前入口。当前路线认知目标、两场会话合并裁决和下一实验见
> [`route_cognition_first_principles.md`](route_cognition_first_principles.md)。DB 地基完成
> 不授权继续扩 concept、candidate、relationship 或治理实体。

本文用于暂停继续扩张后的范围复位：重新说明 VELO route cognition v1.1 原本要建成什么、当时已经完成什么、当时还缺什么，以及后续为什么不再沿用混乱的 Batch 8 叫法。

2026-06-19 状态更新：

- 本文是历史范围复位文档，保留用于解释 Step A-D 为什么按这个顺序推进。
- Step A-D 已完成后，route cognition v1.1 DB foundation 已完成；当前完成态以 `route_cognition_v1_1_completion_report.md` 为准。
- DB 地基完成不等于产品运营完成；下一步内部 writer / 审核 / seed 数据计划以 `route_cognition_v1_1_operationalization_plan.md` 为准。

历史结论（本文写作时）：v1.1 还不能视为完成。除非产品方明确砍掉 concept / candidate / formal relationship，否则 route cognition v1.1 仍缺最关键的语义概念、候选审查、正式关系三层。

## 1. 原始产品目标

route cognition v1.1 的目标不是“多建几张表”，而是让 VELO 的路线知识从文案和手工判断，逐步变成可审计、可升级、可回滚的结构化系统。

- `route_books` 是路线身份。它回答“这条路线是谁”，例如一条固定训练路线、赛事路线或城市经典线路。
- `route_versions` 是路线几何 / 导航版本。它回答“这条路线在某个版本下长什么样、怎么骑”，因此是路线几何和导航快照的真相源。
- `segments` 必须通过 `route_cognition_segments` 进入路线认知。不是所有旧 `segments` 都自动进入认知系统；只有审核后进入白名单的 segment 才能被后续关系引用。
- `route_collections` 表示路线体系 / 区域专题对象。它是“把路线组织成一个容器”的东西，例如某城市爬坡体系、某训练走廊、某赛事路线家族。
- `concept_nodes` 表示语义概念。它是“一个被命名、可解释、可复用的概念”，例如地标、路况、安全风险、训练主题、本地骑行术语。
- candidate tables 承接算法 / agent 候选。AI、算法、外部搜索只能先提交候选，不能直接写进正式关系。
- formal relationships 只能从 candidate / human review 转正。正式关系必须有审核记录和判断依据，不能由 agent 直接落库。
- evidence / judgment / research 记录为什么这么判断。它们保存证据、判断过程和研究问题，而不是公开知识库。
- `content/routes/**` 和 `route_guides.content_md` 是用户文案投影，不是 agent 直接改写的知识源。路线认知系统可以解释这些内容，但不能绕过产品流程直接覆盖它们。

## 2. 已完成部分

以下是 v1.1 目前已经完成的地基。这里的“完成”指 schema / 内部能力已经落地，不代表整个产品闭环完成。

- Batch 1：`route_books` + `route_versions`
  - 建立路线身份和路线版本分离。
  - `route_books` 承载路线身份、发布状态、当前版本指针等。
  - `route_versions` 承载路线几何、导航文件、海拔摘要等版本快照。

- Batch 2：`route_guides` provenance
  - 给 `route_guides` 增加导入来源、内容 hash、导入时间、源路径等字段。
  - 明确 `route_guides.content_md` 是从 `guide.md` 导入后的 read model，不是 agent 直接写作区。

- Batch 3：route export foundation
  - 建立 `route_export_jobs` 和 `route_export_artifacts`。
  - 为未来路线导出、下载、分享等流程打基础。

- Batch 4：judgment ledger + research loop
  - 建立 `judgment_runs`、`evidence_items`、`judgment_run_evidence`、`research_questions`、`research_runs`。
  - 形成“证据是什么、谁判断、为什么判断、研究问题是什么”的审计底座。
  - 明确 `evidence_items` 不是公开知识库。

- Batch 5：segment eligibility foundation
  - 建立 `segment_geometry_sources`。
  - 建立 `route_cognition_segments`，作为正式 segments 进入路线认知系统的 0..1 白名单。
  - 明确未审核、被拒绝、待审的 segment 不进入 `route_cognition_segments`。
  - 保证 provenance-verified segment 必须有来源几何，并和 segment / geometry hash 保持一致。

- Batch 6：segment eligibility internal write workflow
  - 增加内部写入服务，用于写入 `route_cognition_segments`。
  - 修正 provenance-verified admission：当前 segment reference_line 的 hash 必须等于来源 geometry_hash。
  - 保持内部能力，不开放 public API，不做 admin UI。

- Batch 7：route_collections foundation
  - 建立 `route_collections` 本体。
  - 它只表示路线体系 / 区域专题容器本身。
  - 本批不包含成员关系，因此还没有 `collection_routes` / `collection_segments`。
  - 本批也不是 concept：没有实现 `concept_nodes`，没有 concept link，没有 candidate，没有 formal relationship。

## 3. 仍未完成但属于原始目标

下面这些不是“额外想加”，而是原始 route cognition 目标里仍然缺失的部分。

- `concept_nodes`
  - 语义概念对象尚未实现。
  - 目前系统没有正式概念层，无法表达“地标、路况、安全风险、训练主题、本地术语”等可复用概念。

- concept candidates
  - 算法 / agent 发现的概念候选还没有地方存放。
  - 这意味着现在不能安全地让 AI 提交“我认为这是一个概念”的结果。

- concept links
  - route / segment / collection 与 concept 的正式关系尚未实现。
  - 例如“某路线关联某训练主题”“某 segment 关联某安全风险”还没有正式表承接。

- route / segment / collection candidate tables
  - 针对路线、segment、collection 的关系候选表尚未实现。
  - 目前没有统一的候选层来承接算法、agent、外部搜索或人工草稿。

- `route_segments`
  - 路线由哪些正式 segment 组成、顺序是什么、方向是什么，尚未结构化。
  - 这不能替代 `route_versions` 的几何真相源，只能作为路线认知层的组成关系。

- `collection_routes`
  - collection 包含哪些 route 尚未实现。
  - 所以当前 `route_collections` 只是容器本体，还不是可浏览的路线体系。

- `collection_segments`
  - collection 包含哪些 segment 尚未实现。
  - 它适合表达训练走廊、区域爬坡集合、专题 segment 包等。

- `segment_submissions`
  - 用户或个人私有 segment 投稿 / 草稿池尚未实现。
  - 这属于未来产品输入面，不应和正式 `route_cognition_segments` 白名单混在一起。

- public / admin UI
  - 没有公开页面展示这些结构。
  - 没有后台审核页面让人把 candidate 转成 formal relationship。

- external search worker
  - 尚未实现外部搜索 / 抓取 worker。
  - 当前 research loop 只保留研究记录，不自动抓取并写入候选。

## 4. v1.1 与 v1.2 范围判断

建议把 v1.1 重新收束为“结构化路线认知最小闭环”，把用户投稿、外部抓取、公开展示和后台产品界面后置到 v1.2。

### 继续归入 v1.1

- `concept_nodes`
  - 理由：没有 concept，route cognition 只有路线 / segment / collection 容器，没有语义层。后续所有 concept links 和 candidates 都缺锚点。

- concept candidate tables
  - 理由：AI / agent 不能直接写正式概念或正式关系，必须先有候选池。

- route / segment / collection relationship candidate tables
  - 理由：正式关系要从候选和人工审核转正，候选层是安全阀。

- formal relationship tables
  - 理由：v1.1 原始目标要求“正式关系只能从 candidate / human review 转正”。如果没有 formal relationship，系统仍停留在材料和候选阶段。

- concept links
  - 理由：concept_nodes 只有被路线、segment、collection 引用后，才变成用户可理解的路线知识。

- `route_segments`
  - 理由：路线认知需要知道一条路线由哪些已审核 segment 组成。但它必须引用 `route_cognition_segments.segment_id`，不能直接把旧 `segments` 全量吸进来。

- `collection_routes`
  - 理由：`route_collections` 作为路线体系容器，最少需要能包含 route，否则它只是空壳。

- `collection_segments`
  - 理由：一些 collection 本质是 segment 主题集合，例如训练走廊、爬坡集合、安全风险区域。它应和 `collection_routes` 一起设计，但可以分步实现。

### 建议后置到 v1.2

- `segment_submissions`
  - 理由：这是用户输入面 / 投稿池，产品交互和审核流程复杂，不应阻塞 v1.1 的结构化地基。

- public UI
  - 理由：没有 concept / candidate / formal relationship 之前，公开展示会过早固化不完整结构。

- admin UI
  - 理由：后台审核页面依赖 candidate 和 formal relationship 的表结构稳定后再做。

- external search worker
  - 理由：外部搜索会引入大量脏数据和时效问题，应等候选池、审核规则、证据边界稳定后再接入。

## 5. 新后续顺序

不要继续使用“Batch 8”这个叫法。建议从现在起改成 v1.1 remaining steps。

### v1.1 remaining step A：concept_nodes foundation

只实现 `concept_nodes` 本体。

本步目标是让系统第一次拥有“语义概念”这类对象，但不建立任何 route / segment / collection 关系，不做 candidate，不做 hierarchy，不做 aliases 独立表，不做 public API，不做 admin UI。

### v1.1 remaining step B：candidate foundation

建立候选层，让算法 / agent / 人工草稿只能先提交候选。

本步应覆盖 concept candidates，以及 route / segment / collection 关系候选的最小公共规则：来源、置信度、证据指针、判断运行指针、状态、去重约束、不能直接变正式关系。

candidate foundation 必须使用 typed candidate tables：

- 允许为不同候选表复用公共字段约定，例如来源、置信度、状态、证据指针、判断运行指针。
- 公共字段可以通过 ORM mixin / 约定复用。
- DB 表必须具体化，例如 concept candidate、route relationship candidate、segment relationship candidate、collection relationship candidate 应是具体表。
- 禁止创建 generic polymorphic candidates 表。
- 禁止创建 `entity_type` / `entity_id` 式万能候选表。

### v1.1 remaining step C：concept formal relationship foundation

建立 concept 正式关系表，并强制只能从 candidate / human review 转正。

本步只覆盖：

- `route_concept_links`
- `segment_concept_links`
- `collection_concept_links`

所有 concept 正式关系都必须能追溯到审核判断，AI / agent 不允许直接写正式关系。

Step C 的 hard gate：

- 所有正式关系表必须有 `source_kind`。
- 所有正式关系表必须有 `source_candidate_id`。
- 所有正式关系表必须有 `accepted_judgment_run_id`。
- `source_kind = 'candidate_accepted'` 时，`source_candidate_id IS NOT NULL`，且 `accepted_judgment_run_id IS NOT NULL`。
- `source_kind IN ('manual_curated', 'legacy_import')` 时，`source_candidate_id IS NULL`，且 `accepted_judgment_run_id IS NOT NULL`。

### v1.1 remaining step D：route and collection membership foundation

建立路线和集合的组成关系。

建议包含：

- `route_segments`
- `collection_routes`
- `collection_segments`

关键规则：

- `route_segments.segment_id` 必须 FK 到 `route_cognition_segments.segment_id`。
- `collection_segments.segment_id` 必须 FK 到 `route_cognition_segments.segment_id`。
- 不允许 `route_segments.segment_id` 或 `collection_segments.segment_id` FK 到裸 `segments.id`。
- `collection_routes` 应引用 `route_books`。
- 这些表描述成员和顺序，不替代 `route_versions` 的几何版本真相源。

Step D 的 hard gate：

- 所有正式关系表必须有 `source_kind`。
- 所有正式关系表必须有 `source_candidate_id`。
- 所有正式关系表必须有 `accepted_judgment_run_id`。
- `source_kind = 'candidate_accepted'` 时，`source_candidate_id IS NOT NULL`，且 `accepted_judgment_run_id IS NOT NULL`。
- `source_kind IN ('manual_curated', 'legacy_import')` 时，`source_candidate_id IS NULL`，且 `accepted_judgment_run_id IS NOT NULL`。

### v1.2 step A：submission and review product surface

后置 `segment_submissions`、个人私有草稿、后台审核界面。

这里才开始处理“用户或运营如何提交、审核、退回、修改”的完整产品流程。

### v1.2 step B：public surface and external ingestion

后置 public UI、external search worker、公开 evidence 摘要展示。

这里才开始把路线认知系统变成用户能看到、搜索能补充、外部资料能持续进入的产品能力。

## 6. 明确边界

- `route_collections` 不是 `concept_nodes`。
  - collection 是有成员、统计、顺序、地图范围的容器。
  - concept 是语义标签 / 概念对象。

- concept 还没实现。
  - 现在没有 `concept_nodes`。
  - 也没有 concept hierarchy、concept aliases、concept links。

- candidate 还没实现。
  - 现在没有 concept candidates。
  - 也没有 route / segment / collection relationship candidate tables。

- formal relationship 还没实现。
  - 现在没有正式 route-concept / segment-concept / collection-concept 关系。
  - 也没有 candidate -> human review -> formal relationship 的转正链路。

- v1.1 不能被误认为已完成。
  - 除非产品方明确决定砍掉 concept / candidate / formal relationship，否则 v1.1 仍只是完成了路线、证据、segment 白名单、collection 本体等地基。
  - 如果产品方决定砍掉这些目标，需要写一份明确的 product scope cut 文档，而不是把“尚未实现”误写成“已经完成”。

## 7. 后续执行规则

- 每一步都必须先规划，再实现。
- 每一步只做一个层级，不顺手实现下一层。
- 不修改 `content/routes/**`。
- 不直接改 `route_guides.content_md`。
- 不让 AI / agent 直接写 formal relationship。
- 不把 `evidence_items` 当公开知识库。
- 不把 `route_collections` 偷偷扩展成 concept。
- 不把 `metadata_json` 当候选池或关系真相源。
- 每一步完成后，都必须生成给 schema owner / GPT Pro / Claude 的 review prompt，再进入下一步。
