# velo 路线认知数据库 · 最终 schema（双异源审收敛 + Tim 全拍定 / 2026-06-16）

> **SUPERSEDED / 已被 v1.1 取代（2026-06-18）**：本文只保留作历史审查轨迹，不能再作为建表依据。当前落地只执行 `route-cognition-schema-v1.1` 的 Batch 0 + Batch 1：`route_books` 私有/发布状态 + `route_versions`；不建 concept / candidate / judgment / research / export / segment provenance 表，也不再采用本文里的 `route_books.parent_id`、旧 concept link 等设计。
>
> **状态**：经 Claude reviewer-integration + Codex 双异源审，4 个 Critical 全解，Tim 逐项拍定。**这是建表依据**，下一步 Codex 写 alembic 迁移照此建。
> **审查产物**：Codex 审 + Claude 审的完整结果在两个 subagent transcript；草案演进史在 `_REVIEW_route_db_schema_draft.md`。

## 核心拍定（地基）

1. **路线唯一身份 = 复用已有 `route_books`**，绝不新建 routes 表（双审 Critical 1：新建必造双轨、动 meetup 外键、全表搬家）。
2. **跨层关系全用"具体关联表"**，废弃万能 `node_links`（双审 Critical 2：PostgreSQL 多态 FK 无完整性保证、埋孤儿数据雷）。
3. **赛段认知与路线认知分开**：赛段存"地理固有事实"，路线存"组合意图叙事"，叙事引用事实不复制（双审 #1 一致结论）。
4. **防火墙式扩展**：复用 3 张已有表（route_books/route_guides/segments），新建表全部带真外键。

---

## A. 改已有表（最小改动）

### route_books（路线唯一身份，已有）
加 2 字段：
- `elevation_profile TEXT` —— DEM 算出的海拔采样 JSON 数组（同 segments 格式）。手绘路线的海拔起伏图落地处（Tim 拍①）。
- `parent_id INTEGER NULL FK→route_books.id` —— 大路线（环西山）用自引用表达，不建 meta_routes（Tim 拍②）。
- `source` CHECK 约束：现有 `file_upload/activity_derived/tencent_direction` 已覆盖"GPX 型/活动裁切型/手绘型"，**GPX 裁切走 file_upload 或 activity_derived，无需加新枚举**（双审：tencent_direction 就是手绘型）。

**route_books.reference_line = 路线权威完整轨迹**（可以是拼接结果，也可包含手绘延伸段）。route_segments 是"赛段覆盖层"，不是轨迹唯一来源，两者独立不强制一致（Tim 拍④）。

### segment_ai_drafts + segments.description（已有，不动）
保持现状：赛段**文字介绍**走 ai_drafts → 审批 → 写 segments.description。segment_cognition 只装结构化，不碰文字路径（Tim 拍③）。

### route_guides（路线认知层，已有）
已有 content_md/highlights/elevation_profile/gallery_urls。= 路线的"组合意图叙事"。后续按需加结构化字段（本期可不动）。

---

## B. 新建表（全带真外键）

### 1. segment_cognition —— 赛段结构化认知（1:1 挂 segment）
- `segment_id INTEGER FK→segments.id CASCADE UNIQUE`
- `route_role`（枚举：race_road / local_training / commute / net_celebrity…）赛事路 vs 本地训练路
- `practice_spectrum`（结构化：能干哪些练法——新手有氧/FTP测试/多圈耐力/比赛/间歇）
- `descent_risk`（枚举：heaven / hell + 结构化险情标签）放坡风险
- `difficulty_truth`（含"陡点出场顺序"这种隐藏难度）
- `belongs_to_world`（枚举：road_cycling / hiking / scenic…）属于谁的世界
- `best_timing`（季节/封山/避赛事日，结构化）
- **只装结构化枚举/数值字段，零 Text 描述**（双审 Important：文字走 ai_drafts，防重复塞）
- 每条认知带来源追踪：`source_url / collected_at / trust_level`（双审 Important：蒸馏互联网内容必须可复核）
- 类型专属字段：当前量级用**固定列 + NULL + segment_type 枚举**（双审建议：几百赛段下比 JSONB 可维护，出现 5+ 类型再转 JSONB）

### 2. route_segments —— 路线←赛段拼接（组合核心）
- `id` 独立主键（**不用 (route_id,segment_id) 复合**——环线同段二次经过会冲突，双审 Important）
- `route_book_id INTEGER FK→route_books.id CASCADE`
- `seq INTEGER` —— 顺序；`UNIQUE(route_book_id, seq)`
- `direction`（枚举：forward / reverse）——**反向渲染需 ST_Reverse(reference_line)，写进实现 spec**（双审 Critical 3）
- `component_type`（枚举：segment_clip / custom_geometry）
- `segment_id INTEGER NULL FK→segments.id` —— 是赛段时填
- `custom_geometry Geometry(LINESTRING,4326) NULL` —— 手绘延伸段时填（segment_id 为空）（Tim 拍④ 用此承载延伸段）
- `start_measure_m / end_measure_m FLOAT NULL` —— 部分使用赛段（半环）时的起止距离
- `INDEX(segment_id)` —— 反查"哪些路线用过这段"

### 3. segment_relations —— 赛段间关系
- `id`；`segment_a_id / segment_b_id FK→segments.id`；`relation_type`（同廊道/对比/可串接）
- 无向关系用 canonical ordering 存一行（`least/greatest` 复合唯一）防反向漂移（双审 Important）
- `INDEX` 两列都建，支持双向反查（双审 Important）

### 4. concept_nodes —— 跨层概念节点
- `id`；`node_type`（枚举：**列全** race_event/scenic_spot/practice_type/abandoned_road…，双审 nice-to-have：列全免改 CHECK）；`name`；`description_md`；`metadata JSONB`
- 例：环太原赛、网红桥、FTP测试、废道

### 5. segment_concept_links —— 赛段↔概念（替代 node_links 一部分）
- `segment_id FK→segments.id CASCADE`；`concept_id FK→concept_nodes.id CASCADE`；`UNIQUE(segment_id,concept_id)`

### 6. route_concept_links —— 路线↔概念
- `route_book_id FK→route_books.id CASCADE`；`concept_id FK→concept_nodes.id CASCADE`；`UNIQUE(route_book_id,concept_id)`

---

## C. 废弃（我草案里被双审证伪的）
- ✗ `routes` 新表 → 用 route_books
- ✗ `node_links` 万能多态链接 → 拆成 segment_concept_links + route_concept_links + route_segments（各有真外键）
- ✗ `meta_routes` 表 → 用 route_books.parent_id 自引用

---

## D. 模块归属（双审 Claude 指出的草案漏洞）
新建表放新模块 `app/route_cognition/`，FK 指向 segments + route_books，依赖方向"在 RouteBook 下游"，不违反现有依赖链。不反向 import 业务模块。

## E. 建表注意（双审检查清单）
- alembic revision id ≤ 32 字符（陷阱 #23）
- 新模块建立后 `docker compose up -d --build`（不是 restart）
- 手绘海拔需调 DEM，复用 `app/segment/dem_client.py`
- 反向轨迹 ST_Reverse 渲染需真机实测反骑场景

---

## 未决（留给建表后，本期不阻塞）
- route_guides 要不要加更多结构化字段（本期 content_md 够用）
- segment_cognition 各枚举的具体取值表（建表时和 Tim 定）
- "练法光谱"具体怎么结构化（是枚举数组还是带强度的对象）
