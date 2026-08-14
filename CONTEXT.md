# VELO Route World

VELO 路线世界区分骑手可发现、可排行的正式对象，和仅供规划器保证连通性的内部对象。

## Language

**Competitive Segment（竞技赛段）**:
面向骑手公开的有向固定区间，拥有探索卡片、活动匹配和独立排行榜身份。
_Avoid_: 内部连接段、补路线

**Internal Routing Connector（内部路线连接段）**:
经过人工复核、仅供路线规划器连接两处已知锚点的固定几何；它不向骑手展示，也不参与活动匹配或排行榜。双向连接段只保存一份物理几何，反向使用时倒序遍历。
_Avoid_: 隐藏赛段、公开赛段、腾讯临时路线

**Road Carrier（道路载体）**:
机械确认属于同一条实体道路后，无论有多少来源赛段或骑行方向，永远只保留一份版本化物理底稿；来源记录只投影为有向区间证据，正反骑行只生成不同 Traversal。尚未完成道路归并的来源线只能叫 Component Geometry，不能冒充 Road Carrier。
_Avoid_: 正向道路、反向道路、每条赛段一条路

**Traversal（有向穿越）**:
沿一份固定物理几何按指定方向行进一次；同一条公路连接只保存一份几何，反向骑行直接倒序生成 Traversal，并交换爬升/下降、改读反向热度证据。只有明确的物理阻断事实才能禁止反向，不因缺少反向地图查询而禁止。
_Avoid_: 反向复制线

**Route Pattern Candidate（路线骑法候选）**:
一个或多个 Mountain Route Block、来源走廊与过境道路 Traversal 的有序组合；机械系统先证明相邻边界、方向、距离、GLO 爬升/下降与热度证据，Agent 再解释适合谁、为什么和代价。山区内部候选不自动等于包含市区接驳与返程的完整骑行日程。
_Avoid_: 赛段排列组合、地图端点直连、完整城市路线

**Mountain Route Block（山区路线积木）**:
由版本化区域 manifest 和同一套通用机械算法生成的目的地研究视图。每块明确列出方向 Traversal、总距离、整线 GLO-30 总爬升/下降、方向化热度证据范围、来源范围锚点以及推荐理由。来源赛段端点只是 Evidence Boundary，不是 Road Terminal；跨山区路线由完整有序的过境道路 Traversal 串联，并单独计算资源与证据覆盖。它不是新的公开 Segment、永久道路实体或区域专属算法；新增山区只新增 manifest 与证据，算法升级必须换全局版本并回放既有山区。
_Avoid_: 任何区域专属 skill/算法（桃花沟、横岭只作例子）、把赛段山顶终点当作道路断头点、把两个目的地画成直接连接、把重叠赛段的距离/爬升/骑手数直接相加

**Named Climb（命名爬坡）**:
骑手共同认知的一条有向、固定基座到固定坡顶的爬坡对象，拥有明确的 base/summit anchors 和唯一物理走廊身份。它不等同于旧 RouteGuide、Strava Segment 或算法从高程中检测出的 Climb Occurrence。
_Avoid_: 路线介绍、排行榜赛段、任意上坡区间

**Full Named Climb Traversal（整坡）**:
从 Named Climb 的 canonical base anchor 连续走到 canonical summit anchor 的一次有向穿越；完整几何与逐点高程必须覆盖同一范围。赛段名称带“全程”、接近坡顶或只有总爬升数字，都不能单独证明整坡。
_Avoid_: 全赛段、整条 RouteGuide、接近山顶的半坡

**Partial Climb Traversal（半坡 / 局部坡）**:
只覆盖 Named Climb 真子区间、或缺少 canonical base/summit 任一锚点的有向穿越；必须保存父坡和轴上范围。若它嵌套在一个 top-level climb 内，只作为 child ramp/局部热度证据，不重复分类和累计爬升。
_Avoid_: 第二条整坡、独立重复爬升

**Climb Occurrence（地形爬坡段）**:
Climb Planner 从一条完整有向高程剖面中机械识别出的连续地形爬升区间；一条整坡可能产生一段或多段 occurrence，一条包含接驳和返程的路线也可能包含多条 Named Climb。Occurrence 是版本化派生事实，不决定道路或命名坡的身份边界。
_Avoid_: Named Climb、Competitive Segment、RouteGuide

新山区的导出、重放和回读入口见 [`data/research/mountain_modules/README.md`](data/research/mountain_modules/README.md)。
