# 运行时合同

## 当前数据链

```text
人工观察 Strava 页面
  -> target identity gate（边界 / 方向 / 距离 / 路形）
  -> coordinate provenance gate（新收录 / 历史回归）
  -> WGS-84 起点 / 锚点 / 终点
  -> xyconvert.wgs2gcj
  -> 腾讯指定 profile 分段算路（bicycling 或 driving，GCJ-02）
  -> app.segment.coord_convert.convert_points_to_wgs84
  -> 重建距离 gate（必须落在 target_definition 范围）
  -> app.elevation.route_elevation.build_route_elevation_result
  -> candidate bundle（needs_review）
  -> 人工地图对照
  -> verified bundle 或 verified_regression bundle
```

## 代码真值入口

运行前确认这些入口仍存在且合同未变：

- `app/route_book/tencent_direction.py`：腾讯骑行/驾车路线，输入和输出都是 GCJ-02。
- `app/segment/coord_convert.py`：腾讯点串转 WGS-84。
- `app/elevation/route_elevation.py`：唯一的 GLO-30 路线海拔工厂。
- `app/segment/service_create.py`：当前 Segment 距离、爬升、坡度和写入语义。
- `app/route_cognition/geometry_hash.py`：路线认知使用的几何 hash 口径。
- `app/route_cognition/services/segment_eligibility.py`：带 provenance 的准入门。

如果任何入口漂移，先修 skill 脚本或合同，再继续批量生产。不要复制一套旧算法进 skill。

## 候选 bundle 关键字段

- `status`：生成后固定为 `needs_review`；只有复核脚本能生成 `verified`、`verified_regression` 或 `rejected`。只有 `verified` 有发布资格。
- `identity_evidence`：保留搜索前定义的目标、选中依据、公开页面指标和被拒候选；不能从腾讯结果反推目标。
- `hard_knowledge.geometry.source`：必须是 `tencent_directions`。
- `hard_knowledge.geometry.routing_profile`：必须是 `bicycling` 或 `driving`，并与 provenance 一致；它不是骑行许可结论。
- `hard_knowledge.geometry.coordinate_system`：必须是 `wgs84`。
- `hard_knowledge.geometry.geometry_hash`：直接调用 `hash_segment_geometry_wkt()`，不在 skill 里复制第二套 hash 算法。
- `hard_knowledge.elevation.method`：来自 `ROUTE_ELEVATION_METHOD`。
- `hard_knowledge.elevation.metadata`：来自 `route_elevation_metadata()`，保存网格、平滑、事件门槛、DEM 数据集和垂直基准；同一路线跨版本比较时必须一起看。
- `popularity_observation`：原样保留主候选与邻近候选的数字、页面、比较范围和时间，不能混入 `hard_knowledge`。
- `derived_judgments`：初始为空；路线认知阶段另行提出并对质。
- `quality_gates.target_identity_match`：必须在腾讯调用前通过。它证明“选的是目标赛段”，不证明腾讯几何已经对。
- `quality_gates.gpx_independent_coordinates`：新收录为 `passed`；旧轨迹参与精确取点时只能是 `regression_only`，即使路形复核通过也不能发布。
- `quality_gates.tencent_distance_match`：腾讯 WGS-84 点串距离必须落在搜索前冻结的目标范围内；不通过时不得调用 DEM。
- `quality_gates`：腾讯与海拔生成通过不等于腾讯路形通过，endpoint、direction、shape 仍必须由人工复核。
- `provenance.routing_points_gcj02`：只用于腾讯网页/URI 的人工地图复核。内部几何仍以 WGS-84 保存；两套坐标不能混用。

## 失败和重试

- 缺 `TENCENT_MAP_KEY` / `TENCENT_MAP_SK`：停止；只报告未配置。
- 本地未设置 `GLO30_CACHE_DIR`：skill CLI 自动使用系统临时目录下的专用缓存；生产服务仍遵守自身环境配置。
- 腾讯单段失败：停止；缩短该段或增加准确锚点后重跑。
- 腾讯整条明显过短或过长：停止且不调用 DEM；先切换 routing profile，再检查是否需要最少锚点。
- 腾讯返回明显绕行：保留 warning，人工核对；不要自动接受。
- DEM 缺点或服务失败：停止；不得混用 GPX/FIT 海拔补洞。
- 人工对照不一致：拒绝或增加锚点重建。
- 同名或高度重叠 Segment 已存在：不要直接覆盖；走版本/迁移判断。
- 页面候选与目标定义不一致：在调用腾讯前拒绝；不能因为页面热度高或名字像而放宽目标。

## 天龙山历史回归锚

2026-07-16 的真实算法实验确实算出过约 561m：完整下坡实骑片段长 10.34km，`SRTM3-project` 经 20m 网格、median 3 点、Gaussian `sigma=150m` 后直接累计下降为 `561.4113779904653m`，反向即约 561m 爬升。这个数是历史算法输出，不是页面抄值。

当前生产入口在 2026-07-18 演进为 `glo30_meaningful_ascent_v1`：GLO-30、20m 网格、100m Gaussian、3m prominence、100m minimum span。同一条路若当前结果不再等于 561m，不得改数字迎合历史值；必须同时报告轨迹版本、method、metadata 与结果，说明算法口径发生了什么变化。

## 发布边界

skill 脚本只生产和复核 bundle，不写数据库。原因是当前旧入口仍带 `from-gpx` 语义，而路线认知准入还要求独立的人工 Judgment 和 provenance。把腾讯候选硬塞进旧入口会得到“数据写进去了、来源却说谎”的假完成。

需要发布时，先确认当前正式 writer 能在一个事务中完成：

1. 创建或版本化 Segment；
2. 保存腾讯来源和生成参数；
3. 保存 geometry hash；
4. 关联人工接受的 Judgment；
5. 进入 RouteCognitionSegment 白名单；
6. 失败时完整回滚。

旧 Segment 可能已经被 effort、约骑或历史记录引用。即使新几何更好，也不要删除或复用旧 ID；先设计兼容和迁移。
