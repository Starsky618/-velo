# Route Draw V0 实施计划

## 用户故事

骑友在探索页点“画一条路线”，先像正常地图一样拖动、缩放、点起点和路线点；VELO 帮他把路线贴到附近可骑行道路上，每一步都能看见，错了能撤回。保存后，这条路线变成自己的路书，能看海拔、发约骑、导出码表。

## 范围

本期只做 V0：
- 探索页新增画路线入口。
- 新增小程序全屏画线页。
- 后端提供手画线吸附预览 API。
- 保存用户确认后的路线，复用现有手画路线和统一海拔链路。
- 新增“我的路书详情”页，承接保存后的地图、海拔、导出、发约骑。
- 记录吸附来源和警告，方便以后换地图源。

不做：
- 热力图推荐。
- 自动最佳路线。
- 实时导航。
- 转弯提示。
- 腾讯轨迹云默认链路。
- 自建路网。
- 非机动车道强承诺。
- 新后台队列。
- 数据库迁移。

## 任务卡

实现 Task 4 前必须先读 `docs/spec-route-draw-v0.md` 和 `task-4-route-draw-page.md`。真机反馈后的交互修正已经收回这两份主合同：地图默认可拖动缩放，点地图加路线点，铅笔才进入手绘，Manual Mode 用于救路网失败。

1. [Task 1：后端吸附预览 API](task-1-backend-snap-preview.md)
2. [Task 2：保存路线、海拔和导出状态](task-2-save-route-elevation.md)
3. [Task 3：我的路书详情页](task-3-route-book-detail.md)
4. [Task 4：小程序画线页](task-4-route-draw-page.md)
5. [Task 5：探索页入口](task-5-explore-entry.md)
6. [Task 6：验收、合规和对抗性复审](task-6-verification.md)

依赖顺序：

```text
Task 1 -> Task 4
Task 2 -> Task 3 -> Task 4
Task 4 -> Task 5
Task 1-5 -> Task 6
```

## 全局约定

- 小程序地图采集到的手势点按 GCJ-02 处理。
- 数据库和 GPX/TCX 导出继续以 WGS-84 为准。
- 腾讯只做贴路助手，最终路线归档在 VELO 的 `route_versions.reference_line_snapshot`。
- V0 复用 `source = manual_drawn` 和 `geometry_source = manual_drawn`，吸附来源写入 `navigation_metadata_json.draw`。
- 统一海拔仍由现有共享海拔链路写入，画线元数据不能覆盖海拔元数据。
- 用户看到的文案只说“优先贴近可骑行道路”，不说“自动吸附到非机动车道”。
- `route-detail` 继续服务路线百科；自画路线保存后进入 `route-book-detail`。
- 任何任务都不能先在 `app.json` 注册一个还不存在的页面。

## 验收命令

```bash
pytest tests/test_route_draw_snap.py tests/test_route_book_api.py tests/test_route_elevation_backfill.py
node --check miniprogram/pages/explore/explore.js
node --check miniprogram/pages/route-draw/route-draw.js
node --check miniprogram/pages/route-book-detail/route-book-detail.js
node --check miniprogram/utils/api.js
git diff --check
```

## 真用回归

- 从探索页进入画线页。
- 打开画线页后，不进入手绘也能拖动、缩放地图。
- 点地图设置起点，再点一个位置后看到橙色路线段。
- 点铅笔后才能手绘；松手后地图恢复拖动、缩放。
- 撤回上一步后，地图和统计都回退。
- 腾讯贴路失败时，可以改用 Manual Mode 继续点地图接线。
- 底部抽屉能看到距离、爬升或占位、预计时间或占位、路线来源图例；少于 2 个点时保存不可用。
- 保存后进入我的路书详情，能看到路线图、海拔起伏和总爬升。
- 从我的路书详情点“用这条路线发约骑”，约骑创建页选中这条路线。
- 这条路线能继续导出 GPX/TCX，文件内保留逐点海拔。
