# Task 2：保存路线、海拔和导出状态

## 目标

把用户确认后的路线保存成正式路书，并接上现有统一海拔链路和导出状态判断。

## 用户多了什么体验

用户点保存后，不只是得到一条地图线，而是得到一条能看海拔、能发约骑、能导出码表的正式路线。

## 改动范围

- `app/route_book/schemas.py`
- `app/route_book/router.py`
- `app/route_book/service.py`
- `tests/test_route_book_api.py`
- `tests/test_route_elevation_backfill.py`

## 输入输出合同

- 扩展 `POST /api/route-books/manual-drawn`，允许 `coordinate_system` 和 `draw_metadata`。
- `coordinate_system` 缺省为 `wgs84`，保证旧调用不受影响。
- route-draw 页面提交 `gcj02` 时，后端入库前转 WGS-84。
- 对外 `points` 是 `[lon, lat]`；调用 `convert_points_to_wgs84()` 前必须转换成 `{"lon": lon, "lat": lat}` 字典列表。
- 数组转字典后、GCJ-02 转 WGS-84 后都必须校验经纬度范围；如果经纬度反了，不能让非法纬度进入 WKT。
- 路书仍写 `source = manual_drawn`。
- 路线版本仍写 `geometry_source = manual_drawn`。
- `navigation_metadata_json.draw` 写入工具名、吸附来源、段数、警告、原始手画线摘要。
- `draw_metadata` 不存完整原始触摸轨迹：`raw_points_summary.sample` 超过 20 个点返回 422，`warnings` 超过 20 条返回 422，序列化后总 JSON 超过 8KB 返回 422。
- 统一海拔函数继续维护 `navigation_metadata_json.elevation`，画线元数据不能覆盖它。
- 后端重新计算距离、海拔和爬升，不信任前端统计。
- 海拔查询失败必须回滚，不创建没有逐点海拔的正式路书。
- 新增展示用 `GET /api/route-books/{route_book_id}/detail`，返回页面需要的字段和 `export_ready/export_formats/export_block_reason`。
- router 中建议把 `/{route_book_id}/detail` 定义在 `/{route_book_id}` 前面；测试必须证明 detail 路径命中新展示 schema。
- 详情响应绝不返回内部 `file_id`。

## 导出状态规则

- 创建者自己的私有路书，只要当前版本 ready 且可信逐点海拔完整，就可以导出。
- 公开已发布路书游客也可导出。
- 不能复用 `service_guides._export_state()`，因为它会把私有路书挡成 `not_public`；实现时新增 route_book 专用 export-state helper，内部调用 `export_service.can_export_route()` 并检查可信逐点海拔。
- 无 `current_version_id` 或版本未 ready：`export_block_reason = "no_current_version"`。
- 缺可信逐点海拔：`export_block_reason = "no_elevation"`。
- `distance` 在详情响应里继续保持米单位，前端详情页转 km。

## 测试

必须覆盖：
- 老调用只传 `name/points` 仍能保存。
- `coordinate_system = gcj02` 会转成 WGS-84 入库。
- 坐标转换测试使用 `lon=112.x, lat=37.x`，断言不会把经度当纬度传入转换函数。
- 反向映射成 `{"lat": lon, "lon": lat}` 会被拒绝，不会写入 WKT。
- `draw_metadata.raw_points_summary` 被写进 `navigation_metadata_json.draw`。
- 过大的 `draw_metadata` 被拒绝，不会把完整触摸轨迹写进 DB。
- 写画线元数据后，可信海拔 metadata 仍存在。
- 海拔查询失败时 DB 不留下 route_book / route_version 半成品。
- 创建者私有路书有可信海拔时 `export_ready = true`。
- 详情响应有 `export_formats = ["gpx", "tcx"]`。
- 缺当前版本、缺逐点海拔时返回正确 blocked reason。
- 路书详情响应不包含 `file_id`。
- `GET /api/route-books/{id}/detail` 命中新展示 schema。

验收命令：

```bash
pytest tests/test_route_book_api.py tests/test_route_elevation_backfill.py
```
