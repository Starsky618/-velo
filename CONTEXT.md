# VELO Route World

VELO 路线世界区分骑手可发现、可排行的正式对象，和仅供规划器保证连通性的内部对象。

## Language

**Competitive Segment（竞技赛段）**:
面向骑手公开的有向固定区间，拥有探索卡片、活动匹配和独立排行榜身份。
_Avoid_: 内部连接段、补路线

**Internal Routing Connector（内部路线连接段）**:
经过人工复核、仅供路线规划器连接两处已知锚点的固定几何；它不向骑手展示，也不参与活动匹配或排行榜。双向连接段只保存一份物理几何，反向使用时倒序遍历。
_Avoid_: 隐藏赛段、公开赛段、腾讯临时路线

**Traversal（有向穿越）**:
沿一份固定几何按指定方向行进一次；同一条双向内部连接段可以产生正反两个 Traversal，而不复制几何。
_Avoid_: 反向复制线

**Mountain Route Block（山区路线积木）**:
由版本化区域 manifest 和同一套通用机械算法生成的可组合研究视图。每块明确列出入口/出口或未知连接、方向 Traversal、总距离、整线 GLO-30 总爬升/下降、方向化热度证据范围以及推荐/阻塞原因。它不是新的公开 Segment、永久道路实体或区域专属算法；新增山区只新增 manifest 与证据，算法升级必须换全局版本并回放既有山区。
_Avoid_: 任何区域专属 skill/算法（桃花沟、横岭只作例子）、把名称相似或端点接近当作能连接、把重叠赛段的距离/爬升/骑手数直接相加

新山区的导出、重放和回读入口见 [`data/research/mountain_modules/README.md`](data/research/mountain_modules/README.md)。
