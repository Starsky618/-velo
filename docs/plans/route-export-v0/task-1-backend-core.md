# Task 1：后端导出核心

## 目标

把路线版本底片变成用户能交给码表 App 的 GPX/TCX 文件。

## 用户多了什么体验

以前用户只能在 VELO 看路线；现在能把路线拿走，放进自己已经信任的导航工具里。对骑友来说，这比 VELO 自己做半成品导航更可靠。

## 改动范围

- `app/route_book/export_generator.py`
- `app/route_book/export_workflow.py`
- `app/route_book/export_service.py`
- `tests/test_route_export_foundation.py`

## 合同

- 线路只从 `route_versions.reference_line_snapshot` 生成。
- 有 `route_versions.elevation_points_snapshot` 时，GPX/TCX 必须优先写入 VELO 原始逐点海拔。
- GPX 输出 `trk/trkseg/trkpt`。
- TCX 输出 `Course/Track/Trackpoint/Position`。
- 少于 2 个点拒绝生成。
- 不生成 FIT、转弯点。
- 没有原始逐点海拔时不自动猜海拔。
- 下载前核 artifact、job、route version、format 是否完全一致。

## 验收

```bash
pytest tests/test_route_export_foundation.py
```
