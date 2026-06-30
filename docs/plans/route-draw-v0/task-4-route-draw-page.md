# Task 4：小程序画线页

## 目标

新增全屏画线页，让用户分段画路线、预览吸附结果、撤回错误段并保存。

## 用户多了什么体验

用户像在地图上拿笔描路。系统贴错了，他能马上看出来并重画，而不是保存后才发现整条路线歪了。

## 改动范围

- `miniprogram/pages/route-draw/route-draw.js`
- `miniprogram/pages/route-draw/route-draw.wxml`
- `miniprogram/pages/route-draw/route-draw.wxss`
- `miniprogram/pages/route-draw/route-draw.json`
- `miniprogram/app.json`
- `miniprogram/utils/api.js`

## 输入输出合同

- 页面使用原生 `<map>` 展示底图和 polyline。
- 页面加载时必须检查登录态；未登录直达本页时提示登录，不能触发吸附预览或保存请求。
- 画线模式下禁用地图拖动，避免用户想画线却把地图拖走。
- 先做手势 spike：拖动一段，能拿到连续屏幕点，并用 `MapContext.fromScreenLocation` 转成 GCJ-02 经纬度。
- spike 失败时停止本任务，不上线入口，不用“点选多个点”冒充手画路线。
- 灰线显示当前手画原线。
- 橙线显示已确认路线。
- 当前预览线显示“刚吸附但还没确认”的结果，必须和已确认路线分开存状态、分开渲染；用户点确认后，它才并入已确认路线。
- 当前段松手后调用 `api.snapManualDrawnRoute()`。
- 用户可确认当前段、撤回上一段、切自由画线。
- 保存前输入路线名。
- 保存前把已确认路线简化到不超过 500 点；如果仍超过上限，提示“路线太长，分几段保存更稳”，不发保存请求。
- 保存调用 `api.createRouteBookFromManualDrawn()`，传 `coordinate_system = "gcj02"` 和 `draw_metadata`。
- 保存成功后跳到 `/pages/route-book-detail/route-book-detail?id=<route_book_id>`。
- 腾讯错误必须翻译成人话，不展示原始接口错误。
- 保存失败也必须翻译成人话：后端 503/422 时不跳详情页，提示“路线没有保存成功，请稍后再试”或更具体的海拔失败文案。
- `app.json` 只能在本任务创建完页面文件后注册 `route-draw`。

## 页面状态

至少有这些状态：
- `idle`：未画线。
- `drawing`：正在手指描线。
- `previewing`：松手后等待吸附。
- `segmentReady`：当前段可确认。
- `saving`：保存正式路书。
- `error`：当前段失败，但已确认路线不丢。

## 测试和真用

必须覆盖：
- 手指画线不会造成页面明显卡顿。
- 未登录直达画线页时不能触发 snap/save 请求。
- 松手后能看到吸附预览。
- 未确认预览线和已确认路线能同时区分显示。
- 撤回上一段后路线统计同步回退。
- 腾讯失败时能改自由画线。
- 保存接口返回 503/422 时留在当前页，不跳详情页，并给用户可理解提示。
- 超过 500 点的长路线不会直接提交失败，而是先给用户可理解提示。
- 保存成功后跳到 `route-book-detail`，不是 `route-detail`。

验收命令：

```bash
node --check miniprogram/pages/route-draw/route-draw.js
node --check miniprogram/utils/api.js
```
