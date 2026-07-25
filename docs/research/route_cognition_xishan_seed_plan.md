# Route Cognition 西山真实 Seed 规划

## 0. 边界

这是一份未来 Taiyuan / Xishan 内部真实 seed 的规划文档。本轮只规划，不写数据。

硬边界：

- 不写 migration。
- 不改 schema。
- 不开 public API。
- 不做 admin UI。
- 不写 seed script。
- 不写生产数据库。
- 不改 `content/routes/**`。
- 不改 `guide.md`。
- 不改 `route_guides.content_md`。
- 不做自动 backfill。
- 不让 AI / agent 直接写正式关系。
- 不把 `evidence_items` 当通用知识库。

Seed 原则：

- concept 和 collection 本体可以规划成 `private / draft / manual`。
- candidate relationship 只有在存在成功的 proposal judgment 后才能提出。
- formal relationship 必须经 `human_review` promotion。
- route / segment membership 必须经 `human_review`。
- route cognition 不能修改 `route_books.reference_line`、`route_versions.reference_line_snapshot`、旧 `segments.reference_line` 或 `segment_efforts`。

## 1. 已验证来源

### 1.1 仓库里的路线内容

`content/routes` 是路线介绍的内容面，不是 DB seed 来源本身。README 写明：`guide.md` 是文案真源，图片是媒体真源，结构化数据和证据链仍在 route JSON 一侧（`content/routes/README.md:1-5`）。README 也列出了当前已有的太原路线内容目录，包括 `tianlongshan`、`hengling`、`huanfenhe`、`jueweishan`、`wanmu`、`langpo`、`aoshen`、`miaoqianshan`、`xixigou`、`yuquanshan`（`content/routes/README.md:20-34`）。

当前可用的路线内容来源：

| 内容路线 | 证据 |
|---|---|
| 横岭 | `content/routes/hengling/meta.json:2-8`; `content/routes/hengling/guide.md:1-15` |
| 天龙山盘山公路 | `content/routes/README.md:24`; `content/routes/tianlongshan/guide.md:1-15` |
| 奥申 | `content/routes/README.md:31`; `content/routes/aoshen/guide.md:1-18` |
| 玉泉山 | `content/routes/README.md:34`; `content/routes/yuquanshan/guide.md:1-21` |
| 狼坡 | `content/routes/README.md:30`; `content/routes/langpo/guide.md:1-21` |
| 环太原汾河自行车道 | `content/routes/README.md:26` |

当前未发现 `环西山正骑` 对应的 `content/routes` 目录。因此，`环西山正骑` 暂时不能当作已存在路线介绍。

### 1.2 服务器数据库边界

按当前人工确认：真实 VELO 数据库跑在服务器上。服务器目前主要有赛段数据，路线介绍还没有进服务器 DB。路线介绍材料现在散落在桌面 HTML 文件，以及仓库里的 `content/routes`。

本机 Docker 数据库只是沙盒，不是这次真实 seed 的判断依据。

之前只读看过本机环境，结论仅用于解释为什么不能拿本机当真源：

- 默认 app `DATABASE_URL` 读取失败，原因是认证失败；未打印任何 secret。
- `velo-db-1` 在这个范围内只有 `segments`，没有 `route_books`。
- `velo-dev-db-1` 有 `route_books`、`route_versions`、`segments`、`judgment_runs`，但没有这次 seed 需要的 route cognition 表，例如 `route_collections`、`concept_nodes`、`route_cognition_segments`、formal link tables。
- `velo-dev-db-1` 中相关 route 查询没有返回 `route_books` / `route_versions`。
- `velo-dev-db-1` 中相关 segment 查询只返回 `segments.id=7, name=汾河西岸 - dev, city=taiyuan`，没有查到 `横岭`。

规划结论：

- 本机 DB 结果不能当真实 seed 依据。
- 服务器 DB 只需要先做赛段和 `route_cognition_segments` 的只读核验。
- 不应假设服务器已有 Taiyuan / Xishan 的路线介绍、`route_books` 或 `route_versions`。
- `content/routes` 和桌面 HTML 才是当前路线介绍来源池，但它们不是 DB 真源。
- `route_cognition_segments` 白名单状态先标记为 `server_segment_pending`。

未来最小只读核验清单：

| 目标 | 服务器上需要核验什么 |
|---|---|
| route cognition schema | 目标内部 seed DB 是否在 Alembic head `20260618_membership_formal`，并且有 route cognition 表。 |
| segments | `横岭` 等西山候选是否已经是正式 segment。 |
| route_cognition_segments | 每个正式 segment 是否已通过 legacy review，且有非空 `geometry_hash`。 |
| existing seed collision | 这些 slug / relationship 是否已经存在，避免重复 seed。 |

### 1.3 桌面路线介绍 HTML

桌面上找到了多份路线百科 HTML。这些是未来路线介绍入库的内容来源，不是 DB 行，也不能直接当 route cognition 写入对象。

| 路线介绍草稿 | 文件 |
|---|---|
| 横岭 | `/Users/macbookair/Desktop/横岭-velo路线百科.html` |
| 天龙山 | `/Users/macbookair/Desktop/天龙山-velo路线百科MVP-v11.html` |
| 奥申 | `/Users/macbookair/Desktop/奥申-velo路线百科.html` |
| 玉泉山 | `/Users/macbookair/Desktop/玉泉山-velo路线百科.html` |
| 狼坡 | `/Users/macbookair/Desktop/狼坡-velo路线百科.html` |
| 环太原汾河自行车道 | `/Users/macbookair/Desktop/环太原汾河自行车道-velo路线百科.html` |
| 崛围山 | `/Users/macbookair/Desktop/崛围山-velo路线百科.html` |
| 庙前山 | `/Users/macbookair/Desktop/庙前山-velo路线百科.html` |
| 小西沟 | `/Users/macbookair/Desktop/小西沟-velo路线百科.html` |
| 启春阁 | `/Users/macbookair/Desktop/启春阁-velo路线百科.html` |
| 清徐夜骑 | `/Users/macbookair/Desktop/清徐夜骑-velo路线百科.html` |

规划结论：

- 不从这些 HTML 直接 seed route_book-backed cognition 记录。
- 如果未来需要 `route_book / route_version`，应先单独做“路线介绍导入计划”，从桌面 HTML / `content/routes` 进入 route content 系统。
- route cognition 这一轮仍可以规划 concept、collection 本体；赛段关系则等服务器赛段白名单核验后再做。

## 2. 第一批 route_collections

这里只规划 collection 本体，不包含成员关系。

| name | slug | collection_type | city | visibility | publish_status | source | 状态 | 备注 |
|---|---|---|---|---|---|---|---|---|
| 西山训练体系 | `xishan-training-system` | `area_system` | `taiyuan` | `private` | `draft` | `manual` | ready_to_seed | 只创建集合本体；不自动加路线或赛段。 |
| 环太原赛路线族 | `tour-of-taiyuan-route-family` | `race_route_family` | `taiyuan` | `private` | `draft` | `manual` | ready_to_seed | 只创建集合本体；与赛事概念的关系需要 candidate + human_review promotion。 |

Writer 兼容性：

- `area_system` 和 `race_route_family` 是允许的 collection type（`app/route_cognition/services/route_collection_writer.py:22-29`）。
- slug 格式由 writer 校验（`app/route_cognition/services/route_collection_writer.py:226-230`）。

## 3. 第一批 concept_nodes

这里只规划 concept 本体，不代表已经有正式关系。

| name | slug | node_type | scope_type | scope_value | visibility | publish_status | source | 状态 | 证据 / 原因 |
|---|---|---|---|---|---|---|---|---|---|
| 新手有氧 | `beginner-aerobic` | `training_theme` | `city` | `taiyuan` | `private` | `draft` | `manual` | ready_to_seed | 天龙山文案说它对新手不算劝退，也适合有氧 / 阈值 / FTP 训练（`content/routes/tianlongshan/guide.md:11-15`）。 |
| 爬坡训练 | `climbing-training` | `training_theme` | `region` | `taiyuan-xishan` | `private` | `draft` | `manual` | ready_to_seed | 横岭被描述为 11km 持续爬坡（`content/routes/hengling/guide.md:7-15`）；西山研究数据也是爬坡中心结构（`docs/research/2026-06-15-taiyuan-18segments-data.md:3-24`）。 |
| FTP测试 | `ftp-test` | `practice_type` | `city` | `taiyuan` | `private` | `draft` | `manual` | ready_to_seed | 天龙山 guide 明确提到 FTP（`content/routes/tianlongshan/guide.md:15`）；研究文档把奥申反爬标为短陡 FTP 测试（`docs/research/2026-06-15-taiyuan-18segments-data.md:21`）。 |
| 碎石风险 | `gravel-risk` | `safety_risk` | `region` | `taiyuan-xishan` | `private` | `draft` | `manual` | ready_to_seed | 横岭 guide 提到小石子爆胎和下坡风险（`content/routes/hengling/guide.md:15`, `content/routes/hengling/guide.md:37-41`）。 |
| 废道 | `abandoned-road` | `road_condition` | `region` | `taiyuan-xishan` | `private` | `draft` | `manual` | needs_review | 庙前山附近有旧路 / 土路语境，玉泉山有废弃采石场历史（`content/routes/yuquanshan/guide.md:13`），但还不能证明“废道”就是一个稳定骑行概念。需要人工确认命名。 |
| 环太原赛 | `tour-of-taiyuan` | `event` | `city` | `taiyuan` | `private` | `draft` | `manual` | ready_to_seed | 研究文档记录了 2019 / 2023 / 2024 环太原赛证据（`docs/research/2026-06-15-taiyuan-xishan-cycling-cognition.md:36-38`），也说明了它的本地意义（`docs/research/2026-06-15-taiyuan-xishan-cycling-cognition.md:176`）。 |
| 网红桥 | `viral-bridge` | `landmark` | `city` | `taiyuan` | `private` | `draft` | `manual` | needs_review | 天龙山 guide 把螺旋高架叫作“网红桥”（`content/routes/tianlongshan/guide.md:7`），但它到底应是 landmark 还是 local term、scope 是否是 city，还需要一次人工命名确认。 |

Writer 兼容性：

- `practice_type`、`landmark`、`road_condition`、`safety_risk`、`event`、`training_theme` 都是允许的 node type（`app/route_cognition/services/concept_writer.py:22-32`）。
- `city` 和 `region` 是允许的 scope type（`app/route_cognition/services/concept_writer.py:33-36`）。

## 4. 第一批 route_books / route_versions

First Visible Slice 里用了 `环西山正骑`，但真实情况是：服务器现在主要有赛段，路线介绍还没有入库。路线介绍材料在桌面 HTML 和 `content/routes`，不是服务器里的 `route_book / route_version`。

| planned route | 路线介绍来源 | server route_book / route_version | 状态 | 备注 |
|---|---|---|---|---|
| 环西山正骑 | missing | 本轮 seed 不可用 | missing_data | 未发现对应 `content/routes` 目录，也未发现桌面 HTML。不要为它创建 route membership、route concept candidate 或 route_segments。 |
| 横岭 | `content/routes/hengling`; 桌面 HTML | 本轮 seed 不可用 | needs_review | 内容存在（`content/routes/hengling/meta.json:2-8`），桌面 HTML 也存在。但这只是路线介绍材料，不是服务器 route_book。后续要决定它是 route_book、segment page，还是两者都要。 |
| 天龙山盘山公路 | `content/routes/tianlongshan`; 桌面 HTML | 本轮 seed 不可用 | needs_review | 内容支持新手有氧 / FTP / 网红桥概念（`content/routes/tianlongshan/guide.md:7-15`），但路线介绍入库是单独阶段。 |
| 奥申 | `content/routes/aoshen`; 桌面 HTML | 本轮 seed 不可用 | needs_review | 内容存在（`content/routes/aoshen/guide.md:1-18`），但路线介绍入库是单独阶段。 |
| 玉泉山 | `content/routes/yuquanshan`; 桌面 HTML | 本轮 seed 不可用 | needs_review | 内容支持环太原赛语境（`content/routes/yuquanshan/guide.md:11`, `content/routes/yuquanshan/guide.md:28`），但路线介绍入库是单独阶段。 |

规划结论：

- 本轮不创建 `collection_routes`。
- 不创建 route concept candidates，除非未来先完成 route_book / route_version 的单独导入和审核。
- 不创建 `route_segments`，除非未来有带非空 `line_hash` 和 `reference_line_snapshot` 的 route_version。
- 本轮真实 seed 只适合 concept / collection 本体；赛段相关记录要等服务器赛段白名单核验。

## 5. 第一批 segments

First Visible Slice 里用了 `横岭` 作为 route_cognition_segment。服务器是否已有正式 `横岭` segment、是否已经进入 `route_cognition_segments`，还需要只读核验。

| planned segment | server segment | 内容证据 | route_cognition_segments 白名单 | 状态 | 备注 |
|---|---|---|---|---|---|
| 横岭 | server_segment_pending | exists as content route / guide | server_segment_pending | server_segment_pending | `content/routes/hengling/guide.md:1-15` 支持这个对象，但服务器还要核验 formal segment 和非空 `route_cognition_segments.geometry_hash`。 |
| 天龙山网红公路 / 天龙山盘山公路 | server_segment_pending | exists as content route and GPX name | server_segment_pending | server_segment_pending | 适合未来做 segment review，但 formal segment 状态要以服务器为准。 |
| 奥申 | server_segment_pending | exists as content route | server_segment_pending | server_segment_pending | 需要服务器 segment 核验和 legacy review 状态。 |
| 玉泉山 | server_segment_pending | exists as content route | server_segment_pending | server_segment_pending | 需要服务器 segment 核验和 legacy review 状态。 |
| 汾河西岸 - dev | local-only sandbox row | not part of Xishan seed | not relevant | do_not_seed_yet | 本机 dev-only 行不是西山 seed 目标，也不是服务器真源。不要拿它当占位。 |

规划结论：

- 服务器 `route_cognition_segments` 状态未核验前，不创建 `collection_segments`。
- source segment 未进入服务器 route cognition 白名单前，不创建 segment concept candidates。
- 不创建 segment formal links。
- 不用裸 `segments.id` 代替 `route_cognition_segments`。

## 6. 计划关系

关系规则：

- `suitable_for`、`has_risk`、`part_of_event`、`training_theme` 是允许的 relation type（`app/route_cognition/services/concept_candidate_writer.py:30-40`）。
- candidate 只能在成功的 proposal judgment 后创建。
- formal link 仍然必须经 `human_review` promotion。
- “可以 private/draft seed”只适用于 concept / collection 本体。关系行没有 `visibility / publish_status`，必须先停在 candidate，直到人工审核后 promotion。

| source object | relation_type / membership | target | 当前证据 / judgment | 可以 private/draft seed? | 是否需要 human_review? | 状态 |
|---|---|---|---|---|---|---|
| 西山训练体系 | collection body | route_collection | private/draft 本体不需要 judgment | yes | body 不需要 | ready_to_seed |
| 环太原赛路线族 | collection body | route_collection | private/draft 本体不需要 judgment | yes | body 不需要 | ready_to_seed |
| 新手有氧 | concept body | concept_node | 天龙山文本证据（`content/routes/tianlongshan/guide.md:11-15`） | yes | body 不需要 | ready_to_seed |
| 爬坡训练 | concept body | concept_node | 横岭和西山研究支持爬坡主题（`content/routes/hengling/guide.md:7-15`; `docs/research/2026-06-15-taiyuan-18segments-data.md:3-24`） | yes | body 不需要 | ready_to_seed |
| FTP测试 | concept body | concept_node | 天龙山和奥申反爬支持（`content/routes/tianlongshan/guide.md:15`; `docs/research/2026-06-15-taiyuan-18segments-data.md:21`） | yes | body 不需要 | ready_to_seed |
| 碎石风险 | concept body | concept_node | 横岭下坡小石子风险（`content/routes/hengling/guide.md:15`, `content/routes/hengling/guide.md:37-41`） | yes | body 不需要 | ready_to_seed |
| 废道 | concept body | concept_node | 证据间接，概念命名未审 | maybe | body 不需要，但命名需要 review | needs_review |
| 环太原赛 | concept body | concept_node | 赛事证据存在（`docs/research/2026-06-15-taiyuan-xishan-cycling-cognition.md:36-38`, `docs/research/2026-06-15-taiyuan-xishan-cycling-cognition.md:176`） | yes | body 不需要 | ready_to_seed |
| 网红桥 | concept body | concept_node | 天龙山证据存在（`content/routes/tianlongshan/guide.md:7`），但 scope/type 命名需要 review | maybe | body 不需要，但命名需要 review | needs_review |
| 环西山正骑 | `suitable_for` | 新手有氧 | 路线介绍来源缺失；没有 route_book / route_version；没有 proposal judgment | no | yes | missing_data |
| 横岭 | `suitable_for` | 爬坡训练 | 服务器 segment / route cognition 白名单待核验；没有 proposal judgment | no | yes | server_segment_pending |
| 横岭 | `has_risk` | 碎石风险 | 服务器 segment / route cognition 白名单待核验；内容证据存在；没有 proposal judgment | no | yes | server_segment_pending |
| 西山训练体系 | `training_theme` | 爬坡训练 | collection 本体可以存在；没有 proposal judgment | relationship 暂不 seed | formal 需要 | needs_review |
| 环太原赛路线族 | `part_of_event` | 环太原赛 | collection 和 concept 本体可以存在；event 证据存在；没有 proposal judgment | relationship 暂不 seed | formal 需要 | needs_review |
| 西山训练体系 | collection route membership | 环西山正骑 | 当前 seed 范围没有 route_book / route_version；没有 human_review | no | yes | missing_data |
| 西山训练体系 | collection segment membership | 横岭 | 服务器 `route_cognition_segments` 白名单待核验；没有 human_review | no | yes | server_segment_pending |
| 环西山正骑 route_version | route composition seq 1/2/3 | custom_geometry + 横岭 segment_clip | 当前 seed 范围没有 route_version；segment 白名单仍待服务器核验；没有 human_review | no | yes | missing_data |

## 7. 最终分桶

### ready_to_seed

这些只是不带关系的 private / draft 本体。真实 seed 前仍要先做服务器重复检查。

| object | 为什么可以准备 seed |
|---|---|
| route_collection: 西山训练体系 | 只写本体；允许 `area_system`；不带 members。 |
| route_collection: 环太原赛路线族 | 只写本体；允许 `race_route_family`; 不带 members。 |
| concept_node: 新手有氧 | 允许 `training_theme`；证据存在。 |
| concept_node: 爬坡训练 | 允许 `training_theme`；证据存在。 |
| concept_node: FTP测试 | 允许 `practice_type`；证据存在。 |
| concept_node: 碎石风险 | 允许 `safety_risk`；证据存在。 |
| concept_node: 环太原赛 | 允许 `event`；证据存在。 |

### needs_review

这些需要人工过一遍，再决定是否 seed 或 promotion：

| object / relationship | 需要 review 什么 |
|---|---|
| concept_node: 废道 | 证据间接。确认命名、type，以及它是不是稳定骑行概念。 |
| concept_node: 网红桥 | 证据存在，但要确认它是 landmark 还是 local term，以及 city scope 是否足够。 |
| 西山训练体系 -> training_theme -> 爬坡训练 | 先要 proposal judgment；formal link 必须 human_review promotion。 |
| 环太原赛路线族 -> part_of_event -> 环太原赛 | 先要 proposal judgment；formal link 必须 human_review promotion。 |

### server_segment_pending

这些依赖真实服务器赛段库，不依赖本机沙盒：

| object / relationship | 服务器上需要什么证据 |
|---|---|
| segment: 横岭 | 需要确认服务器有 formal segment，且有 `route_cognition_segments` 白名单行。 |
| segment candidates / formal links | 需要 server route_cognition_segment，以及 proposal / human_review judgments。 |
| collection segment membership: 西山训练体系 -> 横岭 | 需要 server route_cognition_segment 和 human_review judgment。 |

### missing_data

这些目前没有被仓库内容或当前信息证明：

| object / relationship | 缺什么 |
|---|---|
| route introduction: 环西山正骑 | 没有找到对应 `content/routes` 目录或桌面 HTML。 |
| route_book / route_version for route intros | 服务器目前是赛段数据，不是路线介绍。路线介绍入库是未来单独阶段。 |
| route_book-backed candidates | 需要路线介绍入库后生成并审核过的 route_book、route_version、line_hash。 |
| collection route membership: 西山训练体系 -> 环西山正骑 | 需要 route_book / route_version 和 human_review judgment。 |
| route_segments composition for 环西山正骑 | 需要 route_book / route_version / route_cognition_segment 和 human_review judgment。 |
| “废道”的精确来源 | 证据间接；不能在没有人工确认时当成稳定概念。 |

### do_not_seed_yet

| item | 原因 |
|---|---|
| 任何 formal concept link | AI / agent 不能直接写正式关系。必须 candidate + human_review promotion。 |
| 任何 route 或 segment membership | 需要 verified route_book / route_cognition_segment 和 human_review。 |
| 任何 route_segments row | 它只是路线组成说明层，必须有 verified route_version 和 human_review。 |
| 路线介绍导入 | 本计划不是路线 HTML / content importer，不能创建 route_book / route_version。 |
| 任何 `evidence_items` row | 本计划不是 evidence ingestion，不能把 evidence_items 变成公共知识库。 |
| dev-only segment `汾河西岸 - dev` | 它不是西山 seed 目标，不能当占位。 |
| 任何 content route mutation | 本规划步骤不改 `content/routes`。 |

## 8. 建议后的实施顺序

这不是现在开始实现的指令。

1. 在目标内部 seed DB 上确认 route cognition migration 状态。
2. 对服务器正式 segment 和 `route_cognition_segments` 做只读核验。
3. 只 seed `ready_to_seed` 里的 private/draft concept 和 collection 本体。
4. judgment 只能通过批准的 review 流程创建。
5. 路线介绍先单独做导入计划：从桌面 HTML / `content/routes` 进入 route_book / route_version，不要混进本次 route cognition seed。
6. 等 `横岭` 成为服务器 formal segment，并进入 `route_cognition_segments` 后，再规划 segment candidates 和 collection segment membership。
7. 等真实 route 通过路线介绍导入路径生成 route_book / route_version 后，再规划 route candidates、collection route membership 和 route_segments composition。
8. 只有 human_review promotion 后，才能重新读 First Visible Slice demo snapshot。

最终判断：

当前证据支持先规划第一批 concept 和 collection 本体。它还不支持真实 seed route memberships、segment memberships、formal relationships 或 route_segments composition。
