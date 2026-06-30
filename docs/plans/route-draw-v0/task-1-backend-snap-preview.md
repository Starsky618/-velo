# Task 1：后端吸附预览 API

## 目标

把用户手画的一小段线，交给腾讯骑行路线规划尽量贴到道路上，再把贴路结果返回给前端预览。这个任务只做草稿预览，不写数据库。

## 用户多了什么体验

用户不用再忍受“只选起终点”的死板规划。他可以自己决定大方向，VELO 只帮他把线修到道路上；贴错了能马上撤回，不会污染正式路书。

## 改动范围

- `app/route_book/tencent_direction.py`
- `app/route_book/draw_snap_service.py`
- `app/route_book/schemas.py`
- `app/route_book/router.py`
- `miniprogram/utils/api.js`
- `tests/test_route_draw_snap.py`
- `tests/test_route_book_api.py`

## 输入输出合同

- 新增 `POST /api/route-books/manual-drawn/snap-preview`。
- 请求必须登录，router 用 `get_current_user`。
- 必须限流；key 固定为 `route-book-draw-snap-preview`，额度为 `20/300s/user`。
- 请求体字段：`coordinate_system: "gcj02"`、`mode: "snap" | "freehand"`、`points: [[lon, lat], ...]`。
- 对外点数组是 `[lon, lat]`；调腾讯前必须转换为 `(lat, lon)`，不能把 `[112, 37]` 当 `(lat, lon)` 传进去。
- `coordinate_system` 只允许 `gcj02`；传 `wgs84`、`unknown` 或空值返回 422。
- 原始点最少 2 个，最多 120 个。
- 后端按保形抽稀得到候选关键点；候选关键点超过 11 个或段数超过 10 段时返回 422，不为了凑上限强行压缩复杂路线。
- `mode = freehand` 不调用腾讯，只校验并返回原线。
- 腾讯响应仍返回 GCJ-02，正式保存时再转 WGS-84。
- 响应必须包含 `snapped_points/raw_points/anchor_points/raw_distance_m/distance_m/segment_count/warnings/failed_segment`。
- `api.js` 增加 `snapManualDrawnRoute(payload)`，供画线页调用。

## 实现注意

- `plan_tencent_bicycling_route()` 当前固定 `timeout=8.0`；本任务要支持可选 `timeout_sec` 或在 wrapper 层控制总预算，避免 10 段全部等满 8 秒。
- 预览整体预算为 12 秒；测试必须证明分段调用会传较短 `timeout_sec`，或证明 service 有总预算保护，不会让 10 段各等满 8 秒。
- 单元测试里用太原坐标 `lon=112.x, lat=37.x` 断言传给腾讯函数的是 `(37.x, 112.x)`。
- 腾讯错误要翻译成可预期异常，router 分别返回 422 或 503。
- 拼接多段时去掉重复端点。
- 不允许在这个任务里创建 `RouteBook`。

## 测试

必须覆盖：
- 登录用户可以拿到 snap 预览。
- 未登录请求返回 401。
- 超过预览限流时返回 429，且不会调用腾讯。
- 非 `gcj02` 坐标系返回 422。
- 10 段预览不会各自等待默认 8 秒；测试断言 `timeout_sec` 或总预算保护生效。
- 腾讯调用收到的是 `(lat, lon)`，不会把经度 112 当成纬度。
- `freehand` 模式不调用腾讯。
- 原始点超过 120 个返回 422。
- 保形抽稀后关键段超过 10 个返回 422，且不会调用腾讯。
- 单段腾讯失败返回可读错误，不创建路书。
- 多段拼接会去掉重复端点。
- `api.js` 新方法路径正确。

验收命令：

```bash
pytest tests/test_route_draw_snap.py tests/test_route_book_api.py
node --check miniprogram/utils/api.js
```
