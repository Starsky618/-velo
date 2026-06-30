# Task 3：我的路书详情页

## 目标

新增用户自己的路书详情页，承接“画线保存成功”后的下一步：看地图、看海拔、导出、发约骑。

## 用户多了什么体验

用户画完路线不是被丢回列表，而是马上看到这条路线已经变成一张能使用的“图纸”：哪里起伏、能不能导出、能不能约人骑，一眼看清。

## 改动范围

- `miniprogram/pages/route-book-detail/route-book-detail.js`
- `miniprogram/pages/route-book-detail/route-book-detail.wxml`
- `miniprogram/pages/route-book-detail/route-book-detail.wxss`
- `miniprogram/pages/route-book-detail/route-book-detail.json`
- `miniprogram/app.json`
- `miniprogram/utils/api.js`

## 输入输出合同

- 页面 URL：`/pages/route-book-detail/route-book-detail?id=<route_book_id>`。
- 页面读取 `api.getRouteBookDetail(id)`，也就是 `GET /api/route-books/{id}/detail`。
- `distance` 按米处理，展示时转成 km。
- 均坡前端用 `climb / distance * 100` 计算；`distance <= 0` 或 `climb` 缺失时隐藏均坡。
- 地图预览使用 `preview_points`，展示前 WGS-84 转 GCJ-02。
- 点地图预览时复用 `route-map-nav.openRouteMapPage()`。
- 海拔图使用 `elevation_profile`；没有时显示“海拔生成中”，不画假图。
- 导出按钮只在 `export_ready = true` 时显示或可点。
- 导出仍复用 `api.createRouteExport()` 和 `api.downloadRouteExport()`。
- “用这条路线发约骑”跳转 `/pages/meetup-create/meetup-create?route_book_id=<id>`。
- 不读取 `/api/route-guides/{id}`，不复用 `route-detail` 的 markdown 长文结构。
- 不使用后端内部 `file_id`。

## 测试和真用

必须覆盖：
- 有 `preview_points` 时地图预览出现。
- `distance` 米转 km 展示正确。
- 均坡计算使用米单位，不出现 `NaN`。
- 有可信海拔时展示海拔图。
- `export_ready = false` 时导出入口不误导用户。
- 点“用这条路线发约骑”后，`meetup-create` 能选中这条 route_book。

验收命令：

```bash
node --check miniprogram/pages/route-book-detail/route-book-detail.js
node --check miniprogram/utils/api.js
```
