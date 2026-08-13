# 西山与全国路线规划算法：权威阅读入口

日期：2026-08-13  
状态：算法合同已冻结；实现仍按阶段交付

## 给后续 Agent 的一句话

先读本文，再按下面顺序读三份原文。不要把 Strava 赛段当道路，不要做全国赛段全配对，也不要让机器学习参与几何、拓扑、准入和硬约束裁决。

## 阅读顺序与优先级

1. [`2026-08-13-xishan-route-planning-algorithm-final-v2.md`](./2026-08-13-xishan-route-planning-algorithm-final-v2.md)：主体算法与西山实施顺序。
2. [`2026-08-13-xishan-route-planning-national-scale-appendix.md`](./2026-08-13-xishan-route-planning-national-scale-appendix.md)：全国规模下的分区、索引、压缩、按需关系和分层搜索。
3. [`2026-08-13-national-scale-final-correction-note.md`](./2026-08-13-national-scale-final-correction-note.md)：最终修正规则；与前两份冲突时，以本文件为准。
4. [`2026-08-13-national-scale-final-correction-note.pdf`](./2026-08-13-national-scale-final-correction-note.pdf)：GPT Pro 交付的原始 PDF，供核对排版与原文。

上游问题、真实数据边界和不能接受的结果见 [`2026-08-13-xishan-route-planning-algorithm-design-brief.md`](./2026-08-13-xishan-route-planning-algorithm-design-brief.md)。该任务书是输入，不覆盖上述最终方案。

## 已冻结的核心决定

- `SourceObservation` 是来源观测，不是道路；完整原始线永远保留。
- 道路范围和骑行方向是两个独立轴：`ExtentSequence` 判断 exact、包含、重叠，`DirectedRideSignature` 判断同向、反向、混合。
- 关系事实保存连续、有序、保留重复次数的 witness；模糊等价不做并查集，近似包含不做传递闭包。
- 全国规模不做 observation 全配对。用 exact signature group、ArcSlice posting、interval arrangement 和查询 envelope 召回局部候选；最终仍由确定性验证器判真。
- 道路与派生物采用不可变局部版本，由 `PublishedSnapshotRoot` 原子发布并在单次查询中固定读取。
- 热度是有方向、部分识别的证据范围；不能把重叠赛段的 athlete/effort 直接相加，也不能伪造唯一骑手数。
- 机器学习将来只能补软证据或给已经通过硬约束的完整路线重排；确定性回退必须始终存在。
- 任一确定性搜索预算命中都向上传播为 `search_truncated`；不能包装成 exact 或 proven infeasible。

## 当前西山执行位置

当前真实冻结输入是 87 条候选中的 81 条公路关系输入；6 条纯 XC 只退出本次公路关系分析，原始 observation、Strava 字段、geometry 与 GLO-30 事实都保留。

本轮“西山最小纵切”只推进主体实施阶段 0：

```text
81 条冻结 SourceObservation
→ 完整 3240 对 raw-geometry witness
→ exact / 方向 / 包含与重叠候选 / 不确定原因
→ 可重放结果和人工标注入口
```

它的用途是证明输入、机械计算和证据输出能端到端跑通，并为阈值校准提供真实分布。它不是 `RoadCarrierGraph`、不是正式关系真值，也还不能生成用户可用路线。桥隧、平行道路、graph missing、access 等必须在 CarrierGraph bake-off 和 ProjectionSet 阶段补齐。

### 2026-08-13 实跑结果

只读临时进程已经对生产中冻结的 81 条 included observation 完整计算 3,240 个无序 pair：

- 3,240/3,240 complete，0 truncated，数据库写入 0；
- raw subcurve bbox 索引召回 138 个候选，较全配对减少 95.7407%；
- 对当前 raw oracle 中 90 个 non-disjoint 或 proximity/ambiguity 相关 pair，候选召回 100%；
- 未晋级阈值下产生：0 exact、6 equivalent、32 containment、6 partial overlap、46 indeterminate、3,150 disjoint。

详细冻结摘要见 [`data/research/xishan_relation_oracle_v1_manifest.json`](../../data/research/xishan_relation_oracle_v1_manifest.json)。完整可重放产物位于 gitignored 的 `outputs/xishan-relation-oracle-v1/`；它包含 81 条无坐标输入摘要、3,240 条 pair witness 和 90 条 review 子集，不进入 Git。

这里的“100% 召回”只是当前算法 full-pair oracle 对候选器的回归，不是人工真值准确率。下一步必须人工核对所有 equivalent、containment、partial、indeterminate 和边界样本，形成 corridor-aware gold，再决定是否晋级这些米数和比例阈值。

### 2026-08-13 下一纵切：桃花沟

下一步没有直接枚举路线，而是选择桃花沟 7 条来源观察做第一个 Carrier / Projection / 方向热度 research shadow：先证明多条正反向、包含和部分重叠赛段能落到同一条有版本道路载体候选，再在道路 measure 区间上做 provenance 去重和 reach bounds。

执行边界与证据见 [`2026-08-13-taohuagou-carrier-projection-slice.md`](./2026-08-13-taohuagou-carrier-projection-slice.md)。该切片不是完整 `RoadCarrierGraph`，不证明 access，也不生成用户可用路线。

## 实施时必须补上的一个细节

最终修正说明的双向 containment 要求已经明确，但其 `containers_of` 伪代码最后一行只展示了正向 exact embedding。实现必须对正序和整体反向都做 occurrence-preserving exact embedding，再单独判断 direction，不能只召回反向候选却用正向验证把它漏掉。

## 原始交付校验值

| 文件 | SHA-256 |
| --- | --- |
| 西山最终版 v2 | `e7d4692070c9672e86c9518bb3b1efed38b25a110460ca3280a0c9ae576d1569` |
| 全国规模附录 | `b17af9ba76654d28ab6c39d0619a7f0ec6f045e77e3a9a627a49d7c427393187` |
| 最终修正 PDF | `8c076f9d9dec681ae1e858d4801934e8494f44981185be2f5773d044b3dbf38a` |
