# VELO Route Export V0

## 一句话结论

骑友在 VELO 看到一条公开路线，点“导出到码表”，小程序下载 GPX/TCX 文件，并可发送到微信聊天或文件传输助手；用户再去 Garmin Connect / iGPSPORT / 顽鹿 / Wahoo 的路线导入页选择这个文件。V0 不承诺自动打开目标 App。

## 用户故事

周六早上，小明在 VELO 路线详情页看到“天龙山西线”。他先看距离、爬升和路线图，确认适合今天训练，然后点“导出到码表”。他下载 GPX，把文件交给自己常用的 Garmin Connect。出门前，他仍然用熟悉的码表导航；VELO 只负责把路线安全送到他手里。

这个版本解决的是“不同平台路书很难简单导入码表”的第一段路：先让用户拿到一个标准文件。自动同步到每个品牌 App 是后续单独立项，不混进 V0。

## 当前证据

| 证据 | 说明 |
| --- | --- |
| `docs/adr/010-为什么不做实时导航.md:21` | VELO 明确不做实时导航。 |
| `docs/adr/010-为什么不做实时导航.md:23` | 骑行前由 VELO 生成 GPX 路线文件。 |
| `app/route_book/models.py:294` | 导出 job 已有 `target_platform`。 |
| `app/route_book/models.py:295` | 导出 job 已有 `export_format`。 |
| `app/route_book/models.py:314` | 导出格式只允许 `gpx/tcx`，FIT 不进 V0。 |
| `app/route_book/models.py:332` | artifact 是内部文件登记，不直接给前端。 |
| `app/route_book/export_service.py:31` | 公开已发布路线允许发起导出。 |
| `app/route_book/export_service.py:110` | 下载必须核 artifact、job、版本、格式一致。 |
| `app/route_book/schemas.py:55` | 新增导出请求 schema。 |
| `app/route_book/schemas.py:64` | 新增导出响应 schema，不包含内部 `file_id`。 |
| `app/route_book/schemas.py:131` | 路线详情独立暴露 `export_ready`。 |
| `miniprogram/pages/route-detail/route-detail.wxml:25` | 路线详情新增“导出到码表”入口。 |

## V0 范围

包含：
- GPX/TCX 文件生成。
- 后端创建导出和下载接口。
- 路线详情页入口、下载按钮、导入说明。
- 公开且已发布路线免登录下载。
- 私有路线只允许创建者或管理员导出。
- 路线版本必须有完整逐点海拔才能导出；GPX/TCX 每个轨迹点都必须携带海拔。

不包含：
- FIT 文件生成。
- Garmin 官方 Courses API 同步。
- iGPSPORT / 迈金 / Wahoo 私有接口。
- 自动拉起目标 App。
- 转弯提示、实时导航。
- 缺少可信路线版本时让目标 App 自行猜海拔。
- RQ 队列和 worker 配置变更。

## 后端合同

### 创建导出

`POST /api/route-books/{route_book_id}/exports`

请求体：

```json
{
  "format": "gpx",
  "target_platform": "generic"
}
```

`format` 只允许 `gpx` 或 `tcx`。

`target_platform` 可为 `generic`、`garmin`、`igpsport`、`magene`、`wahoo` 或 `null`。V0 只记录用户意图，不做品牌私有同步。

响应：

```json
{
  "job_id": 1,
  "artifact_id": 1,
  "route_book_id": 106502,
  "route_version_id": 7,
  "format": "gpx",
  "filename": "天龙山西线-106502-v7.gpx",
  "download_url": "/api/route-books/106502/exports/1/download"
}
```

响应绝不返回 `file_id`。

### 下载文件

`GET /api/route-books/{route_book_id}/exports/{artifact_id}/download`

返回二进制文件，必须包含：
- `Content-Type: application/gpx+xml` 或 `application/vnd.garmin.tcx+xml`
- `Content-Disposition: attachment; filename="..."`

下载时必须核对：
- artifact 的 `export_job_id` 等于 job.id
- artifact/job 的 `route_book_id` 等于 URL 路书 id
- artifact/job 的 `route_version_id` 一致
- artifact.format 等于 job.export_format
- artifact 未过期

## 文件生成规则

- 文件从 `route_versions.reference_line_snapshot` 生成线路。
- `route_versions.elevation_points_snapshot` 必须存在、点数必须和 `reference_line_snapshot` 一致、每个点必须有合法海拔；否则拒绝导出。
- 不从 `RouteBook.file_id` 原始上传文件直出，避免绕过版本门禁和权限门禁。
- GPX 输出 `gpx > trk > trkseg > trkpt(lat/lon) > ele`；每个点都必须有 `<ele>`。
- TCX 输出 `TrainingCenterDatabase > Courses > Course > Track > Trackpoint > Position + AltitudeMeters`；每个点都必须有 `AltitudeMeters`。
- 不生成 Course Points。
- 文件名格式为 `{route_name}-{route_book_id}-v{route_version_id}.{gpx|tcx}`，路线名要清理路径字符和超长文本。

## 海拔生成合同

1. **线上统一底座**：当前可信方法为 `glo30_meaningful_ascent_v1`。后端从 GLO-30 查询中心线高度，沿路线约每 20m 重采样，依次执行 3 点中值去毛刺和 100m Gaussian 平滑；总爬升只累计抬升至少 3m、水平跨度至少 100m 的完整上升事件。页面海拔图、预计总爬升和导出逐点海拔必须来自同一条成品剖面。
2. **可审计元数据**：路线版本必须记录 GLO-30 的 source / license / accuracy / point_count、`dataset_id=COP-DEM_GLO-30-DGED`、`vertical_datum=EGM2008 (EPSG:3855)`、`grid_registration=RasterPixelIsPoint`，以及 `processing_grid_m=20`、`median_filter_points=3`、`smoothing_sigma_m=100`、`ascent_prominence_m=3`、`ascent_minimum_span_m=100`、`maximum_processing_distance_m=1000000`。旧方法快照不能继续被视为当前可信结果，必须重新生成。
3. **离线校准证据**：ALOS、用户 FIT 与已获授权的 Strava 赛段数据用于拟合参数、发现桥梁/高架/山体侧坡等系统偏差和回归验证；它们不在用户请求时按固定权重混入 GLO-30，也不靠单条路线特调线上结果。
4. **授权逐点导入**：确有独立授权来源的逐点高度仍可通过 `authorized_point_elevation_csv_v1` 导入，但必须记录 source / license / accuracy / point_count；它不改变默认 GLO-30 链路。
5. **没有可信逐点海拔**：不导出。iGPSPORT 真机 A/B 已验证：无 `<ele>` 的 GPX 会触发目标 App 自行补算，可能得到显著偏高的爬升。

这里的“可信”表示同一路线版本可复现、来源与算法可追踪，并达到骑前规划的参考标准；不表示测绘真值，也不承诺每个点达到测量级绝对精度。

## 路线详情合同

`RouteGuideOut` 增加：

```json
{
  "export_ready": true,
  "export_formats": ["gpx", "tcx"],
  "export_block_reason": null
}
```

`export_block_reason` 可为：
- `no_route_book`
- `no_current_version`
- `not_public`
- `no_elevation`
- `null`

前端只用 `export_ready` 决定是否显示下载按钮。`ready` 仍表示这篇路线手册是否挂了路书，不再拿来判断是否能下载。

## 失败场景

| 场景 | 用户看到什么 |
| --- | --- |
| 没有 route_book_id | “这条路线还没有可下载轨迹” |
| 没有 current_version_id | “这条路线还没有可下载轨迹” |
| 没有完整逐点海拔 | “这条路线还在补全海拔，暂时不能导出到码表” |
| 私有路线匿名导出 | “这条路线暂时不能下载” |
| 网络失败 | “网络失败，请稍后再试” |
| 服务端失败 | “服务器开小差了，请稍后再试” |
| 目标 App 没出现在微信文件转发后的打开列表里 | 提示用户去目标 App 的路线导入页手动选择文件 |

## 后续版本

V1：调研并申请 Garmin Courses API 官方同步。只有拿到官方授权、明确用户授权流程和同步失败处理后才做。

V2：确认 iGPSPORT / 迈金 / Wahoo 是否有开放接口或官方导入协议。没有公开接口时，继续保持“标准文件下载 + 用户手动导入”。

FIT 文件生成、转弯点、官方品牌同步都不进 V0。用户 FIT 仅作为后台离线校准证据，不作为默认导出源。

## 验收命令

```bash
pytest tests/test_route_export_foundation.py tests/test_route_book_api.py tests/test_route_elevation_backfill.py
pytest tests/test_route_guides_import.py tests/test_route_guides_api.py
node --check miniprogram/utils/api.js
node --check miniprogram/pages/route-detail/route-detail.js
git diff --check
```

真用回归：
- 用一条真实公开且有 `current_version_id` 的路线，在小程序详情页下载 GPX 和 TCX。
- 确认未登录用户下载公开路线不会 403。
- 确认私有路线匿名下载不会泄露文件。
- 至少把一个下载文件手动导入 Garmin Connect / iGPSPORT / 顽鹿 / Wahoo 中的一个。
