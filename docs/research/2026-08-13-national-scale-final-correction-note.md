# 全国规模扩展最终修正说明

> 本文是 GPT Pro 原始 PDF 的仓库内可检索文字版。下列规则覆盖主体及全国附录中的冲突表述；未列事项保持不变。原始版见 [`2026-08-13-national-scale-final-correction-note.pdf`](./2026-08-13-national-scale-final-correction-note.pdf)。

## R1. 局部版本、依赖失效、单快照读取

- 道路与派生物使用不可变局部版本：`cell_topology/geometry/metric/access_version[cell]`、`posting_version[shard]`、`arrangement_version[corridor]`、`evidence_version[cell]`、`portal_shortcut_version[pair]`；`partition_topology_version` 单独版本化。禁止把全国单一 `road_graph_version` 放入所有缓存 key。
- 每次发布原子地产生 `PublishedSnapshotRoot`。其 Merkle manifest 固定全部局部版本以及 relation/planner 参数版本。查询开始时 pin 一个 root；查询中后来触及的 cell、shard、shortcut 也只能由该 root 解析。新对象及派生闭包全部 staged 并校验后，才原子切换 root；旧 root 保留到 read lease 结束，禁止混读新旧版本。
- 缓存 key 为 `(artifact_type, logical_key, algorithm_version, dependency_fingerprint)`；fingerprint 只哈希该结果实际读取的局部版本、上游 hash 和参数版本。缓存项保存 dependency list；更新通过 reverse-dependency index 只失效命中项。未触及地区的缓存可跨 snapshot root 复用。

## R2. containment 分成两个查询方向

- `containers_of(short)`：查询“哪些长路径包含当前短路径”。从 short 选择最稀有 interior q-gram；对 short 正序与 reverse 分别召回包含该 q-gram 的 superpath。无 q-gram 的单 arc、partial boundary、极短路径走 carrier-arc/区间 containment fallback。
- `children_of(long)`：查询“当前长路径包含哪些短路径”。不得只选择 long 的一个 q-gram。必须联合扫描 long 正序与 reverse 的全部 distinct interior q-gram，并查询“以该 q-gram 为自身 deterministic anchor 的短路径”；无 q-gram 的短路径由 fallback anchor arc/区间索引召回。
- 两路都只是候选召回。最终逐 token 执行 occurrence-preserving exact embedding，验证 fixed-point boundary measure、gap、顺序、multiplicity 和全部 embedding；direction 另由有向签名判定。approximate containment 仍只保存 pair witness，不进入传递闭包。

## R3. exact 模式必须覆盖完整 hard-bound 范围

- `global_exact` 的 local graph 必须包含 admissible hard-bound 证明得到的完整 `A_Q` 及全部 turn state，只允许可逆 contraction。portal/corridor/skeleton 只能提供 lower bound、排序或 expansion hint，不能删除 `A_Q` 内道路。
- 只展开 top-K portal、部分 corridor union 或非完备 regional alternatives 时，结果必须标为 `approximate_*`；若部分展开是因为任一确定性搜索预算命中，则标为 `search_truncated`。
- `global_exact` 与 `proven_infeasible` 仅在 envelope、overlay、local solver、Validator 全部完成、无预算命中、frontier 穷尽且数据完整时成立。废止“对部分 portal skeleton 搜完即 exact”的状态。

## R4. 覆盖主体旧规则

1. 无向范围与有向签名分离。`ExtentOccurrence=(RoadCarrierEdge,m_lo,m_hi,seq_pos,visit_index)`；`RideOccurrence=(ExtentOccurrence,orientation)`。extent 的 exact/equivalent/containment/overlap 使用保留顺序与 multiplicity 的 `ExtentSequence`；same/reverse/mixed 使用 `DirectedRideSignature`。不得让 directed `RoadArc` token 同时承担两轴真值。
2. 先保留 occurrence，再去重热度。Projection、关系、距离、训练负荷和回头路均保留重复经过。进入热度前，仅按 `(source_fact_id,directed_evidence_cell_id)` 折叠同一来源事实的重复 occurrence；不同来源事实再按既定 max/lower-bound 聚合。禁止先把路径集合化。
3. 预算状态向上传播。envelope、portal、corridor、overlay、label、transition、frontier-byte、candidate-emission 或 validation 任一搜索预算命中，`CompletionLedger.complete=false`；即使已有 hard-feasible 候选，也不得返回 exact；没有候选也不得返回 proven infeasible。

## R5. 补齐预算变量与热门走廊启用策略

`BudgetManifest` 必须定义单位并版本化：

```text
relation: B_rel_offline_cmp, B_relation_storage_bytes
index: B_post_decode_occ, B_dense_work, B_arrangement_bytes, B_shard_bytes
route: B_arc_exact_online, B_overlay_touch, B_portal_expand,
       B_corridor_expand, B_label_expand, B_transition_relax,
       B_frontier_bytes, B_candidate_emit, B_validate
infra: B_cell_portal, B_overlay_memory_bytes, B_cache_memory_bytes,
       B_rebuild_work
SLO: S_truncated_max
```

旧名 `B_storage`、`B_dense`、`B_frontier`、“online arc budget”、“exact national route budget”分别由 `B_relation_storage_bytes`、`B_dense_work`、`B_frontier_bytes`、`B_arc_exact_online` 取代。查询完整性只由确定性计数/字节预算决定；wall-clock 仅作监控。

全国版第一天实现 SignatureGroup、plain interval posting、event stream、active-pattern bitmap 和 plain/arranged 双实现，但 corridor 默认 plain。仅当：

```text
(W_plain(c) > B_dense_work or p95_decode_occ(c) > B_post_decode_occ)
and W_arranged(c) < W_plain(c)
and arranged_bytes(c) <= B_arrangement_bytes
and plain_oracle_hash == arranged_oracle_hash
```

才在下一个 `PublishedSnapshotRoot` 将该 corridor 切换为 arranged；压缩状态不是永久道路属性。

## 修正后的伪代码

```python
def open_query(catalog, root_id=None):
    root = catalog.pin(root_id or catalog.latest_published_root())
    assert root.dependency_closure_complete
    return QueryView(root)


def cached_compute(view, logical_key, algorithm_version, compute):
    for entry in cache.lookup(logical_key, algorithm_version):
        if all(view.resolve_version(d.id) == d.version for d in entry.dependencies):
            return entry.value
    recorder = DependencyRecorder(view)
    value = compute(recorder.bind_immutable())
    deps = recorder.dependencies()
    cache.put(logical_key, algorithm_version, hash_stable(deps), value, deps)
    return value


def publish_delta(base_root, rebuilt):
    new_root = base_root.with_replacements(rebuilt)
    assert new_root.all_dependencies_complete()
    catalog.atomic_publish(new_root)
    reverse_deps.invalidate_only(rebuilt.changed_version_ids)


def containers_of(short, index):
    candidates = Bitmap()
    for seq in [short.extent_seq, reverse_extent(short.extent_seq)]:
        q = rarest_interior_qgram(seq)
        if q is not None:
            candidates |= index.qgram_occurrences[q]
        else:
            candidates |= index.arc_interval_containers(fallback_anchor(seq))
    return [
        g for g in stable(candidates)
        if exact_contiguous_embeddings(short.extent_seq, index.seq[g])
    ]


def children_of(long, index):
    candidates = Bitmap()
    for seq in [long.extent_seq, reverse_extent(long.extent_seq)]:
        for q in distinct_interior_qgrams(seq):
            candidates |= index.selected_anchor_groups[q]
        for arc in distinct_carrier_arcs(seq):
            candidates |= index.fallback_anchor_groups[arc]
    candidates &= index.length_at_most(long.extent_length)
    return [
        g for g in stable(candidates)
        if exact_contiguous_embeddings(
            index.seq[g], long.extent_seq, preserve_occurrence=True
        )
    ]


def nationwide_search(intent, mode, snapshot, B):
    ledger = CompletionLedger()
    envelope = prove_complete_hard_bound_envelope(
        intent, snapshot, B.B_overlay_touch, B.B_arc_exact_online, ledger
    )
    if mode == "exact":
        graph = reversible_contract(envelope.all_arcs_and_turn_states)
        hints = portal_corridor_order_only(envelope, B, ledger)
    else:
        partial = expand_partial_portal_corridors(envelope, B, ledger)
        graph = reversible_contract(partial.arcs_and_turn_states)
        hints = partial.order_hint
        ledger.approximation_used = True
    search = multi_resource_search(graph, hints, B, ledger)
    feasible = validate_up_to(search.candidates, B.B_validate, snapshot, ledger)
    if ledger.any_budget_hit:
        status = "search_truncated"
    elif ledger.approximation_used:
        status = "approximate_feasible" if feasible else "approximate_no_candidate"
    elif search.frontier_exhausted and snapshot.data_complete:
        status = "global_exact" if feasible else "proven_infeasible"
    else:
        status = "feasible_not_proven_optimal"
    return RouteSearchResult(feasible, status, ledger, snapshot.root_id)
```

## 验收用例

1. **局部更新**：北京一条 RoadArc 更新后，太原 cache key/hit 不变；北京只失效 reverse-dependency 命中的 projection、group、arrangement、overlay 和 route cache。
2. **快照一致**：查询 pin root-100 后发布 root-101；查询后来扩展的新 cell 仍读取 root-100。结果 manifest 不得混入两个 root 的版本。
3. **发布原子性**：局部道路已 staged，但 portal/evidence 派生闭包失败；新 root 不可见，查询不得读取 staged 对象。
4. **双向 containment**：`long=A-B-C-D-E`、`short=C-D`，两个 API 均正确返回。即使 long 的最稀有 q-gram 是 `A-B-C`，`children_of(long)` 也不得漏掉 `C-D`；单 arc partial、reverse child 和重复 embedding 同样通过。
5. **exact 范围**：hard-bound 内存在一条不在 top-K corridor 的可行路线；exact 必须找到，或预算命中时返回 `search_truncated`，不得返回无解。partial corridor 搜完只能是 `approximate_*`。
6. **预算传播**：任一列出的搜索预算命中后，即使候选通过 Validator，最终仍为 `search_truncated`；不得为 `global_exact/proven_infeasible`。
7. **occurrence/热度**：同一路三次经过保留三个 `visit_index`；距离和回头路按三次计算。同一 source fact 对同一 directed cell 只贡献一次，反向 cell 分离。
8. **热门走廊**：低压力 corridor 保持 plain；触发后下个 root 变为 arranged。两模式的 relation、multiplicity、evidence hash 与 plain oracle 完全一致。
9. **预算合同**：静态扫描所有 `B_*`；任一变量缺失、单位不明、旧名残留或未进入 `BudgetManifest`，发布必须失败。

