# Task 4：小程序画线页

## 目标

新增全屏画线页，让用户分段画路线、预览吸附结果、撤回错误段并保存。

实现前必须先读 `docs/spec-route-draw-v0.md`。真机反馈已经证明旧的常驻透明手势层会挡住地图；Task 4 的交互要按 Strava 式手机路线创建修正：地图默认可拖动缩放，点地图添加路线点，铅笔才进入手绘，Manual Mode 用于救路网失败。

## 用户多了什么体验

用户像在地图上拿笔描路。系统贴错了，他能马上看出来并重画，而不是保存后才发现整条路线歪了。

## 改动范围

- `miniprogram/pages/route-draw/route-draw.js`
- `miniprogram/pages/route-draw/route-draw.wxml`
- `miniprogram/pages/route-draw/route-draw.wxss`
- `miniprogram/pages/route-draw/route-draw.json`
- `miniprogram/app.json`
- `miniprogram/utils/api.js`
- `tests/test_route_draw_miniprogram_static.py`

## 输入输出合同

- 页面使用原生 `<map>` 展示底图和 polyline。
- 页面加载时必须检查登录态；未登录直达本页时提示登录，不能触发吸附预览或保存请求。
- 页面默认允许地图拖动、缩放；不得用常驻透明层挡住地图。
- 地图必须支持点击添加路线点：第一次点地图设置起点，第二次及之后在智能模式下调用 `api.snapManualDrawnRoute()` 接到上一点。
- Manual Mode 下点地图直接接线，不请求腾讯。
- UI 文案叫 Manual Mode；后端请求和保存元数据继续沿用既有 `freehand` 含义，不新增后端枚举，也不要把 `manual` 直接发给后端。
- 铅笔手绘是独立模式：只有用户点铅笔后才显示触摸层，进入手绘时禁用地图拖动，松手后恢复地图拖动。
- 手绘模式仍要保留手势 spike：拖动一段，能拿到连续屏幕点，并用 `MapContext.fromScreenLocation` 转成 GCJ-02 经纬度。
- 如果 `map bindtap` 在真机不能稳定返回经纬度，允许降级为“中心十字准星 + 添加点”，但必须先记录真机证据，不许继续上线一个点不动、拖不动的假画线页。
- 灰线显示当前手画原线。
- 橙线显示已确认路线。
- 第一次点地图后必须有可见起点 marker；后续点也要有可见端点或等价反馈。
- 等待吸附时可以显示当前预览线；成功后自动并入草稿，不再要求用户每段都点“确认当前段”。
- 用户可撤回上一步、切 Manual Mode、点铅笔手绘。
- 保存前输入路线名。
- 保存前把已确认路线简化到不超过 500 点；如果仍超过上限，提示“路线太长，分几段保存更稳”，不发保存请求。
- 保存调用 `api.createRouteBookFromManualDrawn()`，传 `coordinate_system = "gcj02"` 和 `draw_metadata`。
- 保存成功后跳到 `/pages/route-book-detail/route-book-detail?id=<route_book_id>`。
- 腾讯错误必须翻译成人话，不展示原始接口错误。
- 保存失败也必须翻译成人话：后端 503/422 时不跳详情页，提示“路线没有保存成功，请稍后再试”或更具体的海拔失败文案。
- `app.json` 只能在本任务创建完页面文件后注册 `route-draw`。

## 页面状态

至少拆成两层状态：
- `builderMode = smart`：默认模式，点地图后请求贴路。
- `builderMode = manual`：手动模式，点地图直接接线。
- `builderMode = sketch`：铅笔手绘中，短暂接管手势，结束后回到上一个模式。
- `requestStatus = idle`：没有在途请求。
- `requestStatus = previewing`：等待贴路预览。
- `requestStatus = saving`：保存正式路书。
- `requestStatus = error`：当前动作失败，但已确认路线不丢。

撤回必须按用户动作回退，而不是按原始点数组猜测。

## 测试和真用

必须覆盖：
- 手指画线不会造成页面明显卡顿。
- 页面默认能拖动、缩放地图。
- 第一次点地图只设置起点，不触发 snap 请求。
- 第二次点地图会触发 snap 请求并显示橙色路线段。
- 起点 marker、后续路线点或等价可见反馈存在。
- 未登录直达画线页时不能触发 snap/save 请求。
- 松手后能看到吸附预览。
- 等待中预览线和已确认路线能同时区分显示。
- 撤回上一步后路线统计同步回退。
- 腾讯失败时能改 Manual Mode 继续点地图接线。
- 底部抽屉至少展示距离、爬升或占位、预计时间或占位、路线来源图例、保存按钮。
- 少于 2 个点时保存按钮不可用。
- 保存接口返回 503/422 时留在当前页，不跳详情页，并给用户可理解提示。
- 超过 500 点的长路线不会直接提交失败，而是先给用户可理解提示。
- 保存成功后跳到 `route-book-detail`，不是 `route-detail`。

验收命令：

```bash
pytest tests/test_route_draw_miniprogram_static.py
node --check miniprogram/pages/route-draw/route-draw.js
node --check miniprogram/utils/api.js
git diff --check -- miniprogram/pages/route-draw tests/test_route_draw_miniprogram_static.py miniprogram/utils/api.js
```
