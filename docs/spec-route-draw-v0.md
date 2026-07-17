# VELO Route Draw V0

## 一句话结论

骑友在“探索”页点“画一条路线”，先像正常地图一样拖动、缩放、点地图落起点和路线点；VELO 把新增路线段尽量贴到可骑行道路上。遇到路网不好时，用户可以切 Manual Mode 自己落点，或点铅笔短暂手绘一段。保存后的路线走 VELO 自己的路线版本、统一海拔、GPX/TCX 导出，不把腾讯地图当成长期数据主人。

## 用户故事

周五晚上，小明想规划周末的西山绕圈。他不想只选起点终点，因为自动规划总把他带到不想骑的主路。于是他打开 VELO 的“探索”页，点“画一条路线”，先把地图拖到熟悉的路口，放大看清路名，然后点一下作为起点。

之后他每点一个路口，VELO 就把橙色路线接过去。如果橙线跳到隔壁辅路，他点撤回，缩短下一点的距离；如果这段确实不是路网里的路，他切 Manual Mode 自己落点。只有想像拿笔一样描一段小路时，他才点铅笔手绘，松手后地图马上恢复拖动。最后他点保存，进入“我的路书详情”：马上看到距离、海拔起伏、总爬升，也能一键去发约骑或导出到码表。

## 0. 代码侧事实表

| 证据 | 说明 |
| --- | --- |
| `miniprogram/app.json:4` | “探索”已经是 tab 页面，适合作为路线发现和路线创建的并列入口。 |
| `miniprogram/pages/explore/explore.wxml:3` | 现在探索页主标题是“路线百科”，还没有“画路线”入口。 |
| `miniprogram/pages/explore/explore.js:57` | 当前探索页只拉取 `/api/route-guides`，数据面是路线百科列表。 |
| `miniprogram/app.json:16` | 已有 `map-picker`，但它是单点选择页，不是画线页。 |
| `miniprogram/pages/map-picker/map-picker.js:173` | 当前地图交互只保存一个点到 `pendingMapPoint`。 |
| `app/route_book/router.py:75` | 后端已有腾讯起终点路线生成接口。 |
| `app/route_book/router.py:102` | 后端已有手画路线保存接口，并会走统一海拔。 |
| `app/route_book/router.py:115` | 当前手画保存只把 `name/points` 交给 service，还没有坐标系和画线元数据。 |
| `app/route_book/router.py:195` | 已有 `GET /api/route-books/{route_book_id}`，可复用底层读取逻辑；V0 详情页需要一个不暴露内部 `file_id` 的展示响应。 |
| `app/route_book/schemas.py:31` | `RouteBookResponse` 目前有 `preview_points/elevation_ready/elevation_profile`，但没有 `export_ready/export_formats/export_block_reason`。 |
| `app/route_book/schemas.py:197` | 手画路线请求已有 `points`，最多 500 点。 |
| `app/route_book/schemas.py:157` | `RouteGuideOut` 已有导出状态字段，可以复用同一套展示语义。 |
| `app/route_book/service.py:341` | 手画路线保存已经创建 `RouteBook + RouteVersion` 并写逐点海拔。 |
| `app/route_book/service.py:385` | 手画保存通过 `write_route_elevation_result()` 写统一海拔结果。 |
| `app/route_book/service.py:437` | 私有路书只有创建者能读；公开已发布路书游客可读。 |
| `app/route_book/tencent_direction.py:20` | 当前腾讯客户端调用的是 `/ws/direction/v1/bicycling/`。 |
| `app/route_book/tencent_direction.py:74` | `plan_tencent_bicycling_route()` 接收 `(lat, lon)`，和前端数组 `[lon, lat]` 顺序相反。 |
| `app/route_book/tencent_direction.py:91` | 当前腾讯请求参数只有 `from/to/key/output`，没有多途经点。 |
| `app/route_book/tencent_direction.py:100` | 当前单次腾讯请求同步等待，超时是 8 秒；V0 不能让一个手画段触发几十次 8 秒等待。 |
| `app/segment/coord_convert.py:128` | `convert_points_to_wgs84()` 接收 `{"lat": ..., "lon": ...}` 字典，不接 `[lon, lat]` 数组。 |
| `app/route_book/models.py:139` | `route_versions.reference_line_snapshot` 已能保存路线版本底片。 |
| `app/route_book/models.py:144` | `route_versions.elevation_points_snapshot` 已能保存逐点海拔。 |
| `app/route_book/models.py:148` | `route_versions.navigation_metadata_json` 可保存吸附来源、警告和用户原始手画线摘要。 |
| `app/route_book/export_workflow.py:67` | 导出 GPX/TCX 前已经检查可信逐点海拔。 |
| `app/route_book/export_service.py:31` | 导出门禁允许公开已发布路线、创建者和管理员导出。 |
| `miniprogram/utils/api.js:563` | 小程序已有 `getRouteBookDetail(routeBookId)`，当前读取 `/api/route-books/{id}`；V0 可把它切到展示用详情接口，只要保留 `preview_points/name` 等调用方需要的字段。 |
| `miniprogram/pages/route-detail/route-detail.js:146` | 现有 `route-detail` 读取 `/api/route-guides/{id}`，它是路线百科详情，不是用户自己的路书详情。 |
| `miniprogram/pages/meetup-create/meetup-create.js:281` | 约骑创建页已能从 URL 接收 `route_book_id`。 |
| `miniprogram/pages/meetup-create/meetup-create.js:352` | 约骑创建页能按 `route_book_id` 恢复路线预览。 |
| `miniprogram/utils/route-map-nav.js:12` | 已有全屏路线地图跳转助手，可复用于路书详情的查看地图。 |

## 1. 外部证据

| 来源 | 判断 |
| --- | --- |
| 腾讯路线规划文档：`https://lbs.qq.com/webservice_v1/guide-road.html` | 腾讯有“骑行（bicycling）路线规划”，官方描述是“基于自行车的骑行路线”。公开文档里骑行示例和参数只展示 `from/to/key`；驾车路线才展示 `waypoints`。同页也说明起点、终点、途经点不在道路上时会自动吸附到附近道路。 |
| 腾讯轨迹云概述：`https://lbs.qq.com/service/tracks/tracksGuide/tracksOverview` | 轨迹云提供去噪、抽稀、绑路、补偿等优化，但它面向真实定位轨迹管理，不是 V0 默认的手绘路线规划接口。 |
| 腾讯开放 API 协议：`https://lbs.qq.com/terms.html` | 腾讯对调用次数、数据量、位置数据存储展示责任、交互数据归属都有约束；V0 必须把合规复核写成上线前门槛。 |
| 微信小程序 map 组件：`https://developers.weixin.qq.com/miniprogram/dev/component/map.html` | 原生 map 支持路线绘制、标记和地图事件，但手指“自由描线”的触摸采集要通过页面结构验证，不能靠想象。 |
| 微信 `MapContext.fromScreenLocation`：`https://developers.weixin.qq.com/miniprogram/dev/api/media/map/MapContext.fromScreenLocation.html` | 可以把屏幕点转成地图经纬度；V0 画线页必须先做手势 spike，证明这个转换在真机 / 开发者工具里可用。 |
| Strava 路线创建说明：`https://support.strava.com/en-us/articles/15401660-creating-routes-on-mobile` | Strava 移动端支持用手指描线，路线会贴近道路/小径，也提供手动模式。VELO V0 抄的是这个用户手感，不是完整复制 Strava 的热力图能力。 |

## 2. 产品范围

包含：
- 探索页新增“画一条路线”入口，和路线百科列表平行。
- 新增全屏 `route-draw` 页面。
- 页面默认可拖动、缩放地图；用户点地图添加起点和后续路线点。
- 智能模式下新增点会触发吸附预览，成功后自动并入草稿；V0 不做边画边实时吸附。
- 每一步用户动作都能撤回。
- 支持“智能贴路模式”、Manual Mode 和铅笔手绘。
- 保存后生成 `RouteBook + RouteVersion`，并复用统一 GLO-30 + VELO v1 海拔链路。
- 新增“我的路书详情”页面，展示地图、海拔、导出、发约骑入口。
- 保存后的路线能被约骑选择、GPX/TCX 导出。

暂时不包含（第二版再做）：
- 不做热力图推荐。
- 不做自动帮用户选最佳路线。
- 不做实时导航。
- 不做转弯提示。
- 不自建路网。
- 不承诺一定吸附到非机动车道。
- 不接腾讯轨迹云作为 V0 默认链路。
- 不新增后台队列。
- 不新增数据库迁移；V0 复用已有 `manual_drawn` 来源和 `navigation_metadata_json`。

## 3. 非机动车道判断

腾讯确实有骑行路线规划，官方描述是“基于自行车的骑行路线”。这意味着 V0 可以把腾讯骑行规划作为“优先贴近可骑行道路”的工具。

但 V0 不能对用户承诺“自动吸附到非机动车道”，原因有三个：

1. 公开骑行路线规划文档没有暴露“只走非机动车道”或“返回道路类型为非机动车道”的明确参数。
2. 地图路网是否有完整自行车道数据，属于腾讯底层数据质量，VELO 无法验证每个城市、每条路。
3. 用户真正关心的是公路车可骑、少红绿灯、路况好、车少，这些不是普通地图 API 能完全回答的。

所以 V0 文案只能写：“优先贴近可骑行道路，保存前请检查路线是否贴对。”不能写“自动识别非机动车道”。

## 4. 关键决策

### 决策 1：入口放在“探索”页，不塞进约骑表单

“画路线”是用户创造路线的入口，不是发约骑时的一个表单字段。探索页现在已经是发现路线的地方，把“路线百科”和“画一条路线”并列，用户心智更顺：先发现或创造路线，再决定是否发约骑。

### 决策 2：点地图或手绘结束后再吸附，不做实时吸附

实时吸附看起来高级，但用户会感觉系统在抢方向盘。V0 的主流程是“点地图新增一个路线点 -> 生成橙色贴路线 -> 错了撤回或切 Manual Mode”。铅笔手绘只是补充入口：用户点铅笔后短暂画一段，松手后再吸附或保存为手动段。

### 决策 3：腾讯只做贴路助手，VELO 保存定稿路线

腾讯返回的是临时计算结果。用户确认后，VELO 把最终路线转换成 WGS-84，保存进 `route_versions.reference_line_snapshot`。以后换底图源，历史路线仍然能展示、算海拔、导出。

### 决策 4：不新增路线来源枚举

V0 继续让 `RouteBook.source = manual_drawn`、`RouteVersion.geometry_source = manual_drawn`。腾讯吸附信息写进 `RouteVersion.navigation_metadata_json`，避免为一个 V0 入口改数据库枚举和迁移。

### 决策 5：前端保存的是用户确认后的路线，不保存未确认吸附结果

吸附预览只是草稿。只有用户点“保存路线”后，后端才创建正式路书、补海拔、写版本底片。

### 决策 6：官方路线详情和用户路书详情分开

现有 `route-detail` 是路线百科详情，读 `/api/route-guides/{id}`。用户自己画出来的是 `route_book`，不是一篇官方导览文章。V0 新增 `pages/route-book-detail/route-book-detail`，读展示用路书详情接口；这样 route_guides 继续做内容层，route_books 继续做路线身份层。

### 决策 7：吸附预览必须限流和限段

腾讯骑行接口现在是同步请求，一个请求最多等 8 秒。V0 不能让用户随手画一长串就触发几十次外部请求。单次预览最多 120 个原始触摸点，后端做保形抽稀得到候选关键点；候选关键点超过 11 个，也就是超过 10 段腾讯调用时，就让用户分段画。

### 决策 8：路线定稿后统一生成一条 VELO 成品海拔剖面

保存后的路线统一使用 GLO-30 主底座和 `glo30_meaningful_ascent_v1`：沿路线约每 20m 重采样，先做 3 点中值去毛刺，再做 100m Gaussian 平滑；总爬升只累计抬升至少 3m、水平跨度至少 100m 的完整上升事件。页面海拔图、预计总爬升和导出逐点海拔必须来自同一条成品剖面，不能各算一套。

ALOS、用户 FIT 和已获授权的 Strava 赛段数据只用于离线校准、拟合与回归验证，不在请求时按固定权重混入路线。这个结果是骑前规划估算，不宣称测绘真值；任一离线证据也不能通过单条路线特调改变线上算法。

## 5. 用户完整流程

```text
探索页
  -> 点“画一条路线”
  -> route-draw 页面
  -> 拖动、缩放地图
  -> 点地图设置起点
  -> 点地图添加下一个路线点
  -> 后端吸附预览并返回橙色贴路线
  -> 撤回 / 继续点 / 切 Manual Mode / 点铅笔手绘
  -> 输入路线名并保存
  -> route-book-detail 页面
  -> 看地图、海拔、爬升
  -> 可导出 GPX/TCX
  -> 可点“用这条路线发约骑”
```

## 6. 数据流

```text
探索页
  -> route-draw 页面通过 map bindtap 采集 GCJ-02 点
  -> 第一次点只设置起点
  -> 第二次及之后按“上一点 + 新点”生成候选路线段
  -> POST /api/route-books/manual-drawn/snap-preview
  -> 后端压缩关键点并分段调用腾讯骑行路线
  -> 返回橙色吸附线 + 警告
  -> 前端自动并入本地草稿，用户可撤回上一步
  -> POST /api/route-books/manual-drawn
  -> 后端 GCJ-02 转 WGS-84
  -> 写 route_books / route_versions
  -> 后端用统一 GLO-30 + VELO v1 算法生成成品海拔剖面和逐点海拔
  -> route-book-detail、meetup-create、route export 读取同一版路线
```

## 7. 后端接口合同

### 7.1 吸附预览

`POST /api/route-books/manual-drawn/snap-preview`

请求体：

```json
{
  "coordinate_system": "gcj02",
  "mode": "snap",
  "points": [
    [112.54812, 37.87091],
    [112.54928, 37.87140]
  ]
}
```

规则：
- 必须登录；复用 `get_current_user`。
- 必须限流：固定 key 为 `route-book-draw-snap-preview`，额度为 `20/300s/user`。这一步会打外部地图服务，不能匿名开放。
- `coordinate_system` V0 只允许 `gcj02`，因为小程序地图手势点来自国内地图展示坐标。
- `mode = snap` 时调用腾讯骑行路线规划。
- `mode = freehand` 时不调用腾讯，只做点数、距离、范围检查后返回原线。
- 输入点少于 2 个拒绝。
- 单次原始触摸点最多 120 个。
- 对外接口点数组统一是 `[lon, lat]`；调腾讯前必须转换成 `plan_tencent_bicycling_route((lat, lon), (lat, lon))`，不能把数组原样传进去。
- 后端先做保形抽稀得到候选关键点；如果候选关键点超过 11 个，也就是段数超过 10 段，返回 422，让用户分短一点画；不为了凑上限强行把长复杂路线压到 11 点。
- 整个预览请求目标耗时上限 12 秒；实现时可以给 `plan_tencent_bicycling_route()` 增加可选 `timeout_sec`，避免 10 段都等满 8 秒。
- 拼接重复端点时去重。
- 单段失败时返回失败段，不创建路书。
- 响应点仍是 GCJ-02，给小程序地图直接展示；正式入库只发生在保存接口。

响应：

```json
{
  "mode": "snap",
  "coordinate_system": "gcj02",
  "snapped_points": [
    [112.54810, 37.87090],
    [112.54931, 37.87142]
  ],
  "raw_points": [
    [112.54812, 37.87091],
    [112.54928, 37.87140]
  ],
  "anchor_points": [
    [112.54812, 37.87091],
    [112.54928, 37.87140]
  ],
  "raw_distance_m": 176.2,
  "distance_m": 182.4,
  "segment_count": 1,
  "warnings": [],
  "failed_segment": null
}
```

错误：
- 401：未登录。
- 422：点数太少、点数太多、坐标越界、腾讯返回空路线。
- 503：腾讯 key 未配置或地图服务暂时不可用。

### 7.2 保存手画路线

扩展现有 `POST /api/route-books/manual-drawn`。

请求体新增可选字段：

```json
{
  "name": "周末西山绕圈",
  "coordinate_system": "gcj02",
  "points": [
    [112.54810, 37.87090],
    [112.54931, 37.87142]
  ],
  "draw_metadata": {
    "tool": "route_draw_v0",
    "snap_provider": "tencent_bicycling",
    "segment_count": 6,
    "freehand_segment_count": 1,
    "warnings": [],
    "raw_points_summary": {
      "total_raw_points": 96,
      "sample": [
        [112.54812, 37.87091],
        [112.54880, 37.87112]
      ]
    }
  }
}
```

规则：
- `coordinate_system` 缺省视为 `wgs84`，保持现有调用兼容。
- 来自 `route-draw` 页面时传 `gcj02`，后端保存前转成 WGS-84。
- 对外 `points` 仍是 `[lon, lat]`；复用 `convert_points_to_wgs84()` 前必须先变成 `{"lon": lon, "lat": lat}` 字典列表。
- 后端重新计算距离和海拔，不信任前端传来的距离。
- 保存时写 `navigation_metadata_json.draw`，记录工具、吸附来源、段数、警告和原始手画线摘要。
- `draw_metadata` 必须有硬上限：不存完整原始触摸轨迹，`raw_points_summary.sample` 超过 20 个点返回 422，`warnings` 超过 20 条返回 422，序列化后总 JSON 超过 8KB 返回 422。
- `navigation_metadata_json.elevation` 仍归统一海拔写入函数维护；不要让画线元数据覆盖海拔元数据。
- 路书仍写 `source = manual_drawn`。
- 路线版本仍写 `geometry_source = manual_drawn`。
- 海拔查询失败时必须回滚，不创建没有逐点海拔的正式路书。

### 7.3 我的路书详情

新增展示用接口：

`GET /api/route-books/{route_book_id}/detail`

这个接口复用现有 `service.get_route_book()` 的权限和读取逻辑，但返回新的展示 schema，供 `pages/route-book-detail/route-book-detail` 使用。不要把现有 `RouteBookResponse.file_id` 继续带到新页面。

响应字段：

```json
{
  "id": 123,
  "name": "周末西山绕圈",
  "distance": 18240.5,
  "climb": 436.0,
  "preview_points": [[112.5481, 37.8709], [112.5493, 37.8714]],
  "elevation_ready": true,
  "elevation_profile": [[0, 804.2], [1000, 812.6]],
  "export_ready": true,
  "export_formats": ["gpx", "tcx"],
  "export_block_reason": null
}
```

规则：
- router 里建议把 `/{route_book_id}/detail` 定义在 `/{route_book_id}` 之前；测试重点不是猜 FastAPI 匹配细节，而是确认 `GET /api/route-books/{id}/detail` 命中新展示 schema，且不返回 `file_id`。
- 创建者、公开且已发布路线可读；私有路线对非本人仍返回 404。
- 管理员导出门禁仍由导出接口处理；V0 不通过小程序路书详情扩大管理员读取权限。
- `distance` 保持 route_book 的米单位；小程序展示时自己转 km。不要照搬 `RouteGuideOut.distance` 的 km 语义。
- `export_ready` 必须看当前版本和可信逐点海拔，不复用 `elevation_profile` 图表数据。
- 不能复用 `service_guides._export_state()`：官方路线 helper 要求 `public/published`，但用户自己的私有路书创建者也可以导出。这里要新增 route_book 专用 export-state helper，内部按 `export_service.can_export_route()` + `has_trusted_route_elevation()` 判断。
- 创建者自己的私有路书，如果 `current_version_id` ready 且逐点海拔可信，也应允许导出。
- 缺当前版本返回 `export_block_reason = "no_current_version"`。
- 缺可信逐点海拔返回 `export_block_reason = "no_elevation"`。
- 这个接口绝不返回内部 `file_id`。

### 7.4 导出接口

不新增导出接口。路书详情页继续调用既有：

- `POST /api/route-books/{route_book_id}/exports`
- `GET /api/route-books/{route_book_id}/exports/{artifact_id}/download`

## 8. 前端合同

### 8.1 探索页

`pages/explore/explore` 顶部新增一个“画一条路线”入口，和“路线百科”列表平行，而不是塞进某张路线卡里面。

推荐结构：
- 顶部标题从“路线百科”调整为“探索”。
- 第一块是“创建路线”，主按钮“画一条路线”。
- 第二块是“路线百科”，沿用现有官方路线列表。

### 8.2 画线页

新增 `pages/route-draw/route-draw`。

必须有：
- 全屏地图。
- 地图默认可拖动、缩放、点选。
- 底部数据抽屉：运动类型、距离、爬升、预计时间、海拔图占位、保存。
- 浮动工具：关闭、定位、Manual Mode、铅笔手绘、撤回。
- 铅笔手绘时显示灰色原始线。
- 橙色已确认路线。
- 等待吸附时的当前预览线。
- 保存前路线名输入。
- 失败提示用人话，不展示腾讯原始错误。

手势实现要求：
- 默认状态不得显示常驻透明触摸层，地图必须可拖动、缩放。
- 点地图主流程使用 `map bindtap` 读取经纬度；如果真机证明 `bindtap` 不稳定，降级为“中心十字准星 + 添加点”，并记录真机证据。
- 只有点铅笔后才显示透明触摸层或 canvas 层采集连续手绘点。
- 铅笔手绘状态下禁用地图拖动，避免用户想画线却把地图拖走；松手后立刻恢复地图拖动。
- 铅笔手绘仍要做最小手势 spike：用户拖动一段，页面能拿到连续屏幕点，并用 `MapContext.fromScreenLocation` 转成 GCJ-02 经纬度。

保存成功：
- 成功后跳转 `/pages/route-book-detail/route-book-detail?id=<route_book_id>`。
- 不跳现有 `/pages/route-detail/route-detail`，因为那页读的是 route guide id。

V0 不需要：
- 路线编辑点拖拽。
- 中途插入点。
- 自动推荐路线。
- 海拔图实时预览。

### 8.3 我的路书详情页

新增 `pages/route-book-detail/route-book-detail`。

必须有：
- 路线名。
- 距离、总爬升、均坡。
- 轻量地图预览；点开后复用 `route-map` 全屏查看。
- 海拔起伏图。
- GPX / TCX 导出入口。
- “用这条路线发约骑”按钮，跳转 `/pages/meetup-create/meetup-create?route_book_id=<id>`。

它不需要：
- 官方路线长文。
- 真实画面图集。
- route guide 的 markdown 折叠内容。

均坡展示：
- 前端用 `climb / distance * 100` 计算；这里的 `distance` 是米、`climb` 是米。
- `distance <= 0` 或 `climb` 缺失时隐藏均坡，不显示 `NaN` 或 `0.0%` 假数据。

## 9. 失败场景

| 场景 | 用户看到什么 | 系统动作 |
| --- | --- | --- |
| 用户未登录就画路线 | “登录后才能保存和贴路。” | 不请求腾讯。 |
| 腾讯未配置 key | “路线贴路服务暂时不可用，可以先用 Manual Mode 保存。” | 返回 503，前端保留 Manual Mode；保存元数据继续写现有 `freehand`。 |
| 腾讯超时 | “这段没有贴上路，换短一点再试。” | 不创建路书。 |
| 腾讯返回空路线 | “这段附近没有找到可骑行道路。” | 用户可撤回或切 Manual Mode。 |
| 吸附线明显太绕 | “系统贴出的路线可能偏离你的手画线，请检查后再保存。” | 加 warning，不阻止用户。 |
| 用户画太短 | “再多画一点路线。” | 不请求腾讯。 |
| 点数太多 | “这段太长了，松手分几段画更稳。” | 前端先简化，仍超限则拒绝。 |
| 关键分段太多 | “这一段太长了，分几段画更稳。” | 后端返回 422，不打大量腾讯请求。 |
| 手势 spike 失败 | 不上线画线入口。 | 停在 Task 4，不做假页面。 |
| 海拔查询失败 | “路线没有保存成功，海拔暂时生成失败，请稍后再试。” | 回滚事务，不保存正式路书。 |
| 保存成功 | “路线已保存。” | 跳到我的路书详情页。 |
| 详情页导出不可用 | “路线还在补全海拔，暂时不能导出到码表。” | 不展示下载按钮或禁用按钮。 |

## 10. 已知风险与对策

| 风险 | 严重度 | 对策 |
| --- | --- | --- |
| 吸附到辅路、高架、河对岸 | 高 | 同屏显示当前意图线和橙色吸附线；每一步可撤回。 |
| 腾讯骑行规划不支持多途经点 | 高 | V0 后端分段调用起终点规划，拼接结果；不宣称腾讯支持整条手画线。 |
| 非机动车道识别不稳定 | 高 | 文案只写“可骑行道路”，不写“非机动车道”；真实用户保存前必须检查。 |
| 调用量和延迟上升 | 高 | 登录门禁、用户限流、单次最多 10 段、整体 12 秒预算。 |
| 坐标系偏移 | 高 | route-draw 输入标记 `gcj02`；后端入库前转 WGS-84；导出只读 WGS-84 路线版本。 |
| 路书详情和路线百科混用 id | 高 | 新增 `route-book-detail`，不让自画 route_book 进入 `route-detail`。 |
| 小程序 map 无法连续采集手画线 | 高 | Task 4 先做手势 spike；失败就暂停，不上线入口。 |
| 保存腾讯结果的合规边界不清 | 高 | 上线前复核腾讯协议；V0 存的是用户确认后的路线和元数据，不存腾讯地图瓦片或路网。 |
| 路线太长导致 500 点不够 | 中 | V0 保存前简化到 500 点以内；长路线提示分段保存或后续做更高上限。 |

## 11. 合规边界

- 后端 SK 只留在服务端，不进小程序。
- V0 不存腾讯地图瓦片、路网数据、道路属性。
- V0 存用户确认后的路线点、吸附来源、警告、粗略原始手画摘要。
- 上线前必须记录一次腾讯协议复核结论：当前调用量、缓存方式、展示方式、数据保存方式是否符合协议。

## 12. 后续版本

V1：
- 评估腾讯轨迹云“绑路/优化”是否能更好服务手画路线。
- 支持编辑已保存路线。
- 支持路线反向、复制成我的路线。

V2：
- 用真实骑行轨迹和公开路书沉淀 VELO 自己的骑行偏好。
- 逐步识别“公路车友好路段”：路面、红绿灯、车流、补给点、爬坡。
- 再讨论是否需要自建轻量骑行路网。

## 13. 验收命令

```bash
pytest tests/test_route_draw_snap.py tests/test_route_book_api.py tests/test_route_elevation_backfill.py
node --check miniprogram/pages/explore/explore.js
node --check miniprogram/pages/route-draw/route-draw.js
node --check miniprogram/pages/route-book-detail/route-book-detail.js
node --check miniprogram/utils/api.js
git diff --check
```

真用回归证据必须留下：
- 路书 id、截图或录屏、测试城市和大致道路。
- 在探索页点“画一条路线”，能进入全屏画线页。
- 打开画线页后，不进入手绘也能拖动、缩放地图。
- 点地图设置起点，再点一个位置后看到橙色路线段。
- 点铅笔后才能手绘；松手后地图恢复拖动、缩放。
- 贴错时能撤回上一步。
- 腾讯失败时能切 Manual Mode 继续点地图接线。
- 底部抽屉能看到距离、爬升或占位、预计时间或占位、保存按钮；少于 2 个点时保存不可用。
- 保存后进入我的路书详情，能看到路线图、海拔起伏和总爬升。
- 从我的路书详情点“用这条路线发约骑”，约骑创建页能选中这条路线。
- 导出的 GPX/TCX 继续带逐点海拔；抽样检查 GPX `<ele>` 或 TCX `AltitudeMeters`。
- 至少 3 条真实城市道路用真腾讯接口人工验证；记录请求是否超时、是否明显贴错。
- 100 条虚拟手画路线用 mock 腾讯返回跑过吸附、保存、海拔生成。
