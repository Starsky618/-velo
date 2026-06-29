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

## 验收命令

```bash
pytest tests/test_route_export_foundation.py tests/test_route_book_api.py
pytest tests/test_route_guides_import.py tests/test_route_guides_api.py
node --check miniprogram/utils/api.js
node --check miniprogram/pages/route-detail/route-detail.js
git diff --check
```
