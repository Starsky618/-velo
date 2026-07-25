# Route Cognition v1.1 First Visible Slice Plan

## 1. 目标

这次 first visible slice 要证明一件事：route cognition v1.1 已经不只是“表建好了”，而是能用一小组 Taiyuan / Xishan 数据，把路线、赛段、集合、概念、候选判断、人审正式关系、集合成员、路线组成说明串成一个内部可读的样子。

具体证明：

- “西山训练体系”可以作为一个内部路线集合存在。
- “环西山正骑”可以作为一条 route_book / route_version 存在。
- “横岭”可以先进入 `route_cognition_segments` 白名单，再被路线组成和集合成员引用。
- “新手有氧 / 爬坡训练 / 碎石风险 / 环太原赛”可以作为 concept_nodes 存在。
- route / segment / collection 到 concept 的关系先进入 candidates，再经过 `human_review` promotion 成为 formal links。
- collection 可以包含 route 和 segment，也可以通过 formal concept link 表达赛事归属。
- route_version 可以带有 `route_segments` composition overlay，但不改变 route geometry truth。

这个 slice 的用户故事是：内部 reviewer 打开一份只读 demo，不需要理解数据库表，也能看到“西山训练体系里有什么路线、什么赛段、每个对象为什么被打上这些骑行概念、这条路线由哪些组成片段解释出来”。

## 2. 不做什么

本阶段明确不做：

- public API
- admin UI
- external search worker
- segment_submissions
- real production seed
- route guide rewrite
- content/routes 修改
- evidence public display
- automatic backfill

也不做：

- 新表
- migration
- schema change
- 新 writer
- 真实库写入脚本
- route generation from components
- 用户可见页面

## 3. 最小数据集

以下是 first visible slice 需要创建的最小对象。这里只写字段草案，不写 SQL。

### concept_nodes

1. 新手有氧
   - `name`: 新手有氧
   - `slug`: beginner-aerobic
   - `node_type`: training_theme
   - `scope_type`: city
   - `scope_value`: taiyuan
   - `visibility`: private
   - `publish_status`: draft
   - `source`: manual
   - `summary`: 适合新手用低强度完成的有氧骑行主题
   - `metadata_json`: 只放展示补充信息，不放 route / segment / collection id

2. 爬坡训练
   - `name`: 爬坡训练
   - `slug`: climbing-training
   - `node_type`: training_theme
   - `scope_type`: region
   - `scope_value`: taiyuan-xishan
   - `visibility`: private
   - `publish_status`: draft
   - `source`: manual
   - `summary`: 与坡度、持续输出、爬升能力相关的训练主题

3. 碎石风险
   - `name`: 碎石风险
   - `slug`: gravel-risk
   - `node_type`: safety_risk
   - `scope_type`: region
   - `scope_value`: taiyuan-xishan
   - `visibility`: private
   - `publish_status`: draft
   - `source`: manual
   - `summary`: 路面碎石、破损或抓地不稳定造成的骑行风险

4. 环太原赛
   - `name`: 环太原赛
   - `slug`: tour-of-taiyuan
   - `node_type`: event
   - `scope_type`: city
   - `scope_value`: taiyuan
   - `visibility`: private
   - `publish_status`: draft
   - `source`: manual
   - `summary`: 与太原本地赛事、赛道认知和骑行讨论相关的主题

### route_collections

1. 西山训练体系
   - `name`: 西山训练体系
   - `slug`: xishan-training-system
   - `collection_type`: area_system
   - `city`: taiyuan
   - `visibility`: private
   - `publish_status`: draft
   - `source`: manual
   - `summary`: 以西山方向训练路线、爬坡赛段和风险认知组成的内部路线体系
   - `metadata_json`: 不存 route ids / segment ids / membership truth
   - `stats_json`: 只做可重新计算的展示投影，不存成员真相

2. 环太原赛路线族
   - `name`: 环太原赛路线族
   - `slug`: tour-of-taiyuan-route-family
   - `collection_type`: race_route_family
   - `city`: taiyuan
   - `visibility`: private
   - `publish_status`: draft
   - `source`: manual
   - `summary`: 与环太原赛相关的路线族内部集合
   - `metadata_json`: 不存 route ids / segment ids / membership truth
   - `stats_json`: 只做可重新计算的展示投影，不存成员真相

### route_book / route_version

1. 环西山正骑
   - `route_books.name`: 环西山正骑
   - `route_books.city`: taiyuan
   - `route_books.visibility`: private
   - `route_books.publish_status`: draft
   - `route_books.source`: manual_drawn 或现有测试环境等价来源
   - `route_books.reference_line`: 保持当前版本投影，不由 route cognition writer 修改
   - `route_versions.version_no`: 1
   - `route_versions.reference_line_snapshot`: 作为路线几何真相源
   - `route_versions.line_hash`: 非空，由 reference line 计算或测试 fixture 明确设置

### route_cognition_segment

1. 横岭
   - `segments.name`: 横岭
   - `segments.city`: taiyuan
   - `segments.reference_line`: 保持旧 segment 几何，不由 route cognition writer 修改
   - `route_cognition_segments.segment_id`: 横岭 segment id
   - `route_cognition_segments.geometry_hash`: 非空，来自 reviewed segment geometry
   - `route_cognition_segments.review_basis`: legacy_reviewed 或 provenance_verified
   - `route_cognition_segments.eligibility_status`: active
   - `route_cognition_segments.accepted_judgment_run_id`: human_review judgment id

### judgment_runs

最少需要以下 judgment runs：

1. Concept / collection / route / segment draft 创建可不要求 judgment。
2. Candidate proposal runs:
   - `run_type`: human_review / semantic_agent / spatial_algorithm / research_synthesis 中已允许的 succeeded proposal run
   - `status`: succeeded
   - 用于创建 candidate 的 `created_by_judgment_run_id` 和 `latest_judgment_run_id`
3. Formal acceptance runs:
   - `run_type`: human_review
   - `status`: succeeded
   - `confidence_state`: human_accepted 或 stable
   - 用于 promotion、collection membership、route_segments composition acceptance

### candidates

1. 环西山正骑 -> suitable_for -> 新手有氧
   - target: route_book + route_version
   - `relation_type`: suitable_for
   - `candidate_status`: proposed 或 needs_review
   - `proposer_kind`: human / agent / algorithm 中符合 writer 约束的值
   - `created_by_judgment_run_id`: succeeded proposal judgment
   - `latest_judgment_run_id`: succeeded proposal judgment
   - `accepted_by_judgment_run_id`: 初始为空

2. 横岭 -> suitable_for -> 爬坡训练
   - target: route_cognition_segment 横岭
   - `relation_type`: suitable_for
   - 需要冻结 `segment_geometry_hash`

3. 横岭 -> has_risk -> 碎石风险
   - target: route_cognition_segment 横岭
   - `relation_type`: has_risk
   - 需要冻结 `segment_geometry_hash`

4. 西山训练体系 -> training_theme -> 爬坡训练
   - target: route_collection 西山训练体系
   - `relation_type`: training_theme

5. 环太原赛路线族 -> part_of_event -> 环太原赛
   - target: route_collection 环太原赛路线族
   - `relation_type`: part_of_event

### formal links

上述五条 candidate 经 human_review promotion 后成为 formal links：

1. route_concept_link
   - 环西山正骑 -> suitable_for -> 新手有氧
   - `source_kind`: candidate_accepted
   - `accepted_judgment_run_id`: human_review acceptance judgment

2. segment_concept_link
   - 横岭 -> suitable_for -> 爬坡训练
   - `source_kind`: candidate_accepted
   - 冻结 reviewed `segment_geometry_hash`

3. segment_concept_link
   - 横岭 -> has_risk -> 碎石风险
   - `source_kind`: candidate_accepted

4. collection_concept_link
   - 西山训练体系 -> training_theme -> 爬坡训练
   - `source_kind`: candidate_accepted

5. collection_concept_link
   - 环太原赛路线族 -> part_of_event -> 环太原赛
   - `source_kind`: candidate_accepted
   - `accepted_judgment_run_id`: human_review acceptance judgment

### collection memberships

1. 西山训练体系 -> 环西山正骑
   - table: collection_routes
   - `source_kind`: manual_curated
   - `membership_status`: active
   - `accepted_judgment_run_id`: human_review judgment
   - `reviewed_route_line_hash`: 自动等于 route_versions.line_hash

2. 西山训练体系 -> 横岭
   - table: collection_segments
   - `source_kind`: manual_curated
   - `membership_status`: active
   - `accepted_judgment_run_id`: human_review judgment
   - `segment_geometry_hash`: 自动等于 route_cognition_segments.geometry_hash

### route_segments

环西山正骑 route_version 的 composition overlay：

1. seq 1
   - `component_type`: custom_geometry
   - `source_kind`: manual_curated
   - `membership_status`: active
   - `component_geometry`: 简单 LINESTRING，表示进山连接段
   - `route_line_hash`: 自动等于 route_versions.line_hash

2. seq 2
   - `component_type`: segment_clip
   - `segment_id`: 横岭 route_cognition_segment
   - `direction`: forward
   - `start_fraction`: null
   - `end_fraction`: null
   - `component_geometry`: 简单 LINESTRING
   - `segment_geometry_hash`: 自动等于 route_cognition_segments.geometry_hash

3. seq 3
   - `component_type`: custom_geometry
   - `source_kind`: manual_curated
   - `membership_status`: active
   - `component_geometry`: 简单 LINESTRING，表示出山连接段

## 4. 写入方式

计划使用以下 internal writers：

- `concept_writer`
  - 创建四个 concept_nodes。
  - 默认 private / draft / manual。

- `route_collection_writer`
  - 创建“西山训练体系”和“环太原赛路线族” route_collections。
  - 默认 private / draft / manual。

- `concept_candidate_writer`
  - 创建五条 concept candidates。
  - candidate writer 只写 proposed / needs_review，不创建 accepted candidate。

- `concept_formal_link_writer`
  - 将五条 accepted candidates promotion 为 formal links。
  - 只走 candidate_accepted promotion。
  - 需要 human_review acceptance judgment。

- `collection_membership_writer`
  - 写入 collection_routes 和 collection_segments。
  - 使用 manual_curated + human_review。

- `route_segment_writer`
  - 写入三条 route_segments composition overlay。
  - 不生成 route_versions。
  - 不修改 route_books.reference_line。
  - 不修改 route_versions.reference_line_snapshot。

所有写入必须满足：

- internal only
- no public API
- no admin UI
- no db.commit inside writer
- default private/draft unless explicitly reviewed
- human_review required for formal writes
- metadata_json 不存关系真相
- evidence_items 不作为展示内容来源

## 5. 验证方式

本阶段只规划一个内部 read/demo 查询，不写实现。

目标输出：

```text
西山训练体系
- route: 环西山正骑
- segment: 横岭
- route concepts: 新手有氧
- segment concepts: 爬坡训练 / 碎石风险
- collection concepts: 爬坡训练
- route composition:
  1. custom_geometry
  2. 横岭 segment_clip
  3. custom_geometry

环太原赛路线族
- collection concepts: 环太原赛
```

内部 demo 查询需要证明：

- collection 能读出 member route。
- collection 能读出 member segment。
- route 能读出 formal route concepts。
- segment 能读出 formal segment concepts。
- collection 能读出 formal collection concepts。
- 环太原赛路线族能读出 `part_of_event` -> 环太原赛。
- route_version 能读出 route_segments，并按 seq 排序。
- route_segments 中的 segment_clip 指向 route_cognition_segments，而不是裸 segments。
- route_versions.reference_line_snapshot 仍是路线几何真相源。
- route_books.reference_line 仍是当前版本投影。

输出形式建议先用测试断言或内部 markdown snapshot，不做 API，不做 UI。

## 6. 风险

- 真实旧 segments 未 legacy reviewed，不能直接进入 route_cognition_segments。
- route_book / route_version 真实数据可能不干净，line_hash、reference_line_snapshot、current projection 需要先核对。
- concept 命名可能重复，需要先查 slug 和 scope。
- formal links 需要 human_review，不能让 agent 直接写正式关系。
- metadata guard 仍可能需要扩展，尤其是嵌套 alias、缩写、外部系统字段。
- 这只是 internal demo，不是用户产品。
- route_segments 是说明层，容易被误读成路线生成系统，需要在 demo 文案里明确它不是 geometry truth。
- `manual_curated` / `legacy_import` concept formal writer 还没做，concept formal link 只能从 accepted candidate promotion 进入。

## 7. 验收标准

First visible slice 规划通过后，未来实现必须证明：

- 所有数据只在测试库或 internal seed 环境创建。
- 不写 public API。
- 不改 content/routes。
- 不改 route_guides.content_md。
- 不改 route_versions.reference_line_snapshot。
- 不改 route_books.reference_line。
- 不改 segments.reference_line。
- 不写 evidence_items，除非真实 judgment 使用了证据。
- 能读出完整内部 demo 结构。
- writer 不调用 db.commit。
- 不新增 migration。
- 不改 schema。
- 不创建 membership candidate tables。
- 不启动 external search worker。

## 8. 下一步建议

规划完成后，下一步只允许做：

First Visible Slice dry-run implementation in test/internal DB

下一步仍然不应直接做：

- public API
- admin UI
- production seed
- automatic backfill
- external research automation

建议下一步先写一个只读 dry-run 测试或 internal demo snapshot：它先用现有 writers 在测试库里创建上述对象，再用只读查询把“西山训练体系”结构读出来。这个测试通过后，再决定是否需要设计内部 reviewer 工作流。
