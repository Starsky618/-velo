# Route Export V0 实施计划

## 用户故事

骑友在 VELO 路线详情页看到一条公开路线，点“导出到码表”，拿到 GPX/TCX 文件，再去自己熟悉的码表 App 里导入。VELO 不抢实时导航，只把路线安全交给专业工具。

## 范围

本期只做 V0 下载优先：
- 后端生成 GPX/TCX。
- 后端提供创建导出和下载文件接口。
- 小程序路线详情页展示下载入口和品牌导入说明。
- 文档写清 V1/V2 不混入本期。
- 有 VELO 原始逐点海拔时，导出文件携带这份海拔。
- 旧路线不自动猜海拔；官方路线通过重灌或精确来源回填生成新版，用户旧路线只能在拿得到原始精确数据时回填。

不做：
- FIT。
- Garmin OAuth 或 Courses API。
- iGPSPORT / 迈金 / Wahoo 私有协议。
- 转弯提示。
- 没有原始海拔时自动猜海拔。
- 新队列、新 worker、新 docker-compose 配置。

## 任务卡

1. [Task 1：后端导出核心](task-1-backend-core.md)
2. [Task 2：后端接口合同](task-2-api-contract.md)
3. [Task 3：小程序路线详情入口](task-3-miniprogram-route-detail.md)
4. [Task 4：文档和验收](task-4-docs-verification.md)
5. Task 5：精确海拔回填
   - 目标：拿到同一路线的外部精确海拔时，能安全补进 VELO 当前路线版本。
   - 工具：`scripts/backfill_route_elevation.py`
   - 门禁：默认 dry-run；几何不同线直接拒绝；`--apply` + `--source-license-note` 才新建 `route_versions`。
   - 不做：不同路线套海拔、DEM 猜测、品牌私有同步。

## 验收命令

```bash
pytest tests/test_route_export_foundation.py tests/test_route_book_api.py
pytest tests/test_route_elevation_backfill.py
pytest tests/test_route_elevation_backfill_pg.py
pytest tests/test_route_guides_import.py tests/test_route_guides_api.py
pytest tests/test_meetup_models.py tests/test_route_guides_import_pg.py
node --check miniprogram/utils/api.js
node --check miniprogram/pages/route-detail/route-detail.js
git diff --check
```

## 生产上线顺序

1. 先部署新代码并跑 `python3 -m alembic upgrade head`，确认 `route_versions.elevation_points_snapshot` 已存在。
2. 再跑 `python3 scripts/import_route_guides.py --content-dir content/routes`，让官方路线用原始 GPX 重灌出带逐点海拔的新当前版本。
3. 抽查至少一条官方路线：`route_books.current_version_id` 指向新版，当前 `route_versions.elevation_points_snapshot` 非空。
4. 如果是外部路书来源，优先先保存来源 JSON，再跑 `python3 scripts/backfill_route_elevation.py --route-book-id <id> --source-json <file>` 做 dry-run；只有确认同线，且确认来源授权或用户自有数据依据，才加 `--apply --source-license-note "<说明>"`。
5. 回填后再跑同一命令 dry-run，必须返回 no-op；SQL 抽查同一路线只能有一个 `status='current'`，且 `route_books.current_version_id` 指向新版。
6. 真实创建 GPX/TCX 导出并下载文件，检查 GPX 有 `<ele>`、TCX 有 `AltitudeMeters`。
7. 用户上传 / 活动派生的旧路线不在本步骤里自动猜海拔；只有能拿到原始文件或原始 trackpoints 时，才允许单独回填。
