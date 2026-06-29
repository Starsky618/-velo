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
- 如果路线版本有 VELO 原始逐点海拔，GPX/TCX 导出必须携带这份海拔。

不包含：
- FIT 文件生成。
- Garmin 官方 Courses API 同步。
- iGPSPORT / 迈金 / Wahoo 私有接口。
- 自动拉起目标 App。
- 转弯提示、实时导航。
- 没有原始海拔时自动猜海拔。
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
- 如果 `route_versions.elevation_points_snapshot` 有逐点海拔，导出必须优先使用它。
- `elevation_points_snapshot` 只能补高度，不能替换线路坐标；点数或坐标对不上时退回二维导出。
- 不从 `RouteBook.file_id` 原始上传文件直出，避免绕过版本门禁和权限门禁。
- GPX 输出 `gpx > trk > trkseg > trkpt(lat/lon)`；有海拔时每个有值的点输出 `<ele>`。
- TCX 输出 `TrainingCenterDatabase > Courses > Course > Track > Trackpoint > Position`；有海拔时输出 `AltitudeMeters`。
- 不生成 Course Points。
- 文件名格式为 `{route_name}-{route_book_id}-v{route_version_id}.{gpx|tcx}`，路线名要清理路径字符和超长文本。

## 海拔数据优先级

1. **VELO 原始逐点海拔**：来自用户上传 GPX/FIT 或 route_book 绑定的源活动 trackpoints，和路线点一一对应。导出时先用这份数据，让 Garmin / iGPSPORT / 迈金 / Wahoo 尽量读取 VELO 给出的海拔。
2. **VELO 合规高程补全**：后续只能接中国合法合规、可商用授权的高程数据源；没有授权前不把 DEM 猜测写成精确海拔。
3. **目标 App 自行补算**：只有前两层都没有时才退回二维文件。这个模式最低优先级，因为不同厂商会用自己的高程库重算爬升，用户看到的数据会漂。

### 精确海拔回填

- 对旧路线补海拔时，只接受同一路线的精确来源，例如原始 GPX/FIT、已有活动 trackpoints、或经几何匹配确认同线的公开路书数据。
- `scripts/backfill_route_elevation.py` 是运维回填工具，默认 dry-run；只有 `--apply` 才会创建新版。
- 如果路书本身由一次 VELO 骑行生成，优先用 `--use-route-source-activity` 从 `route_books.source_activity_id` 读取原始 trackpoints，不先求助第三方数据。
- 源活动回填时，逐点海拔用于 GPX/TCX 导出；`route_books.climb` 和新版 `route_versions.climb` 优先沿用 `activities.elevation_gain`，避免用裸逐点高差覆盖设备/解析摘要口径。
- `--apply` 必须附带来源/授权说明；能访问公开链接不等于 VELO 可以缓存并再分发这份海拔。
- 外部来源的坐标只用于寻找高度，最终写入 `elevation_points_snapshot` 的坐标必须是 VELO 当前 `route_versions.reference_line_snapshot` 的坐标。
- 几何匹配超过阈值时必须拒绝，不能为了让导出文件“看起来有海拔”而把另一条路线的高度贴上来。
- 回填成功必须创建新的 `route_versions` 当前版本，旧版本归档，已有导出文件仍指向旧版本。

### 旧路线回填边界

- 新创建 / 新导入路线会保存 `elevation_points_snapshot`。
- 已存在的旧路线不会因为迁移自动获得逐点海拔；迁移只加字段，不凭空猜数据。
- 官方路线重灌时，如果轨迹或逐点海拔变化，必须创建新的 `route_versions` 当前版本，旧版本归档，避免旧导出文件和旧版本底片语义分叉。
- 用户上传或活动派生的旧路线，只有能重新拿到原始文件或原始 trackpoints 时才允许回填；拿不到原始精确数据时继续二维导出，不写 DEM 猜测值。

### 合规高程源调研闸门

| 候选 | 当前判断 | 下一步 |
| --- | --- | --- |
| 高德 / 腾讯 / 百度公开 WebService | 官方公开 WebService 文档能确认路线规划、地理编码等能力；本轮未找到可直接商用的逐点高程接口。 | 继续只作为地图/路线规划候选，不默认当高程源。 |
| 天地图 / 国家基础地理信息中心体系 | 合规来源优先级最高，但需要确认 API、授权、使用范围、成果展示/分发规则。 | 作为第二优先级首选调研对象，先走授权确认，再写代码。 |
| SRTM / Mapbox / Google 等境外或全球 DEM | 技术上可补海拔，但中国境内地图/测绘合规、服务稳定性、商用授权都不适合作为默认生产源。 | 不进默认链路，只能做离线评估样本。 |

参考入口：
- 高德 WebService API：https://lbs.amap.com/api/webservice/summary
- 腾讯位置服务 WebService API：https://lbs.qq.com/webservice_v1/index.html
- 百度地图开放平台常见问题：https://lbsyun.baidu.com/index.php?title=open/question
- 国家基础地理信息中心：https://www.ngcc.cn/
- 本轮调研记录：`docs/research/2026-06-29-route-elevation-data-source.md`

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
- `null`

前端只用 `export_ready` 决定是否显示下载按钮。`ready` 仍表示这篇路线手册是否挂了路书，不再拿来判断是否能下载。

## 失败场景

| 场景 | 用户看到什么 |
| --- | --- |
| 没有 route_book_id | “这条路线还没有可下载轨迹” |
| 没有 current_version_id | “这条路线还没有可下载轨迹” |
| 私有路线匿名导出 | “这条路线暂时不能下载” |
| 网络失败 | “网络失败，请稍后再试” |
| 服务端失败 | “服务器开小差了，请稍后再试” |
| 目标 App 没出现在微信文件转发后的打开列表里 | 提示用户去目标 App 的路线导入页手动选择文件 |

## 后续版本

V1：调研并申请 Garmin Courses API 官方同步。只有拿到官方授权、明确用户授权流程和同步失败处理后才做。

V2：确认 iGPSPORT / 迈金 / Wahoo 是否有开放接口或官方导入协议。没有公开接口时，继续保持“标准文件下载 + 用户手动导入”。

FIT、转弯点、官方品牌同步都不进 V0。合规高程补全单独立项。

## 验收命令

```bash
pytest tests/test_route_export_foundation.py tests/test_route_book_api.py
pytest tests/test_route_elevation_backfill.py
pytest tests/test_route_elevation_backfill_pg.py
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
