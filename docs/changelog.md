# VELO 开发变更日志

## 2026-04-09 ~ 2026-04-13 本轮开发总结

### 一、GCJ-02 → WGS-84 坐标系转换（04-09）
- **问题**：赛段创建接口 reference_points 无坐标系约定，腾讯地图坐标（GCJ-02）与 GPX 轨迹（WGS-84）偏移 100~700m，导致 50m 容差下匹配必然失败
- **修复**：新增 `app/segment/coord_convert.py` 纯函数模块，SegmentCreateRequest 增加 `coordinate_system` 字段（默认 gcj02），service 层自动转换
- **测试**：7 个转换测试（`tests/test_coord_convert.py`）
- 文件：`coord_convert.py`、`schemas.py`、`service.py`、`router.py`

### 二、赛段创建工具（04-09）
- **功能**：Strava 风格的管理员工具（`tools/segment-creator.html`），从 GPX 文件截取赛段
- **交互**：GPX 导入 → Chart.js 海拔剖面图 + 双滑块拖选 → Leaflet+OSM 地图联动 → POST /api/segments 创建或 JSON 降级下载
- **键盘微调**：点击"起点/终点"标签选中，← → 箭头每次 ±20m，长按连续调整
- **后端增强**：Segment 模型新增 `elevation_loss`、`avg_gradient`、`elevation_profile` 三个 nullable 字段；距离精度 1→2 位小数；`_geo_utils.py` 拆分避免 service.py 超 500 行
- **部署**：Caddyfile 新增 `/tools/*` 静态文件路由
- **测试**：4 个字段计算测试（`tests/test_segment_fields.py`）

### 三、本地 Docker 部署（04-12）
- **环境**：`docker-compose.dev.yml`（不含 Caddy），PostgreSQL+PostGIS / Redis / FastAPI / rq Worker
- **迁移**：Alembic 初始迁移脚本，清理 PostGIS tiger 内置表干扰，修复 geoalchemy2 自动空间索引冲突
- **配置修复**：`.env` 与 pydantic-settings 兼容（`extra="ignore"`）；端口冲突改用 5434；CORS 中间件允许跨域
- **验证**：24 条太原赛段 JSON 全部导入成功，上传 GPX 自动匹配 21 条赛段

### 四、Matcher 算法增强（04-13）
1. **独立端点容差**：`endpoint_tolerance` 与 `match_tolerance` 分离，起终点检测和覆盖率校验可独立调整
2. **Moving Time 自动暂停**：速度 + 时间双条件（连续低于阈值 ≥30 秒才扣除），阈值 0.5 km/h，避免误扣陡坡慢速骑行
3. **DELETE /api/segments/{id}**：管理员删除赛段接口，连带清除所有成绩记录
- 与 Strava 成绩对比验证：柴化线两条赛段误差缩至 9~16 秒

### 五、API 接入调研（04-10）
- Strava API：免费，2000 次/天，Webhook 推送，但条款限制数据缓存 ≤7 天
- Garmin API：免费基础接入，需企业身份申请，Push 模式秒级推送
- 行者：有官方开发者中心（XOSS 开放平台）
- 顽鹿/iGPSport：无官方 API
- **结论**：先接 Strava（秒批），同时申请 Garmin（用"共演纪"个体户身份）

### 当前状态
- 后端 API 功能完整，本地 Docker 端到端验证通过
- 24 条太原赛段已入库，匹配算法与 Strava 成绩误差 <20 秒
- 赛段创建工具可用（HTML 单文件，在线/离线双模式）
- **待做**：云服务器部署 → 微信小程序前端 → Strava API 接入

## 2026-04-09 赛段创建工具 + Segment 模型增强

### 新功能
1. **赛段创建工具**（`tools/segment-creator.html`）：Strava 风格的管理员工具，从 GPX 文件中截取赛段。功能：GPX 导入解析 → Chart.js 海拔剖面图 + 双滑块拖选 → Leaflet 地图联动 → POST /api/segments 创建 + JSON 降级下载。单 HTML 文件，CDN 依赖 Chart.js + Leaflet，部署在 Caddy /tools/ 路由下。

### Segment 模型增强
2. **新增 3 个字段**：`elevation_loss`（累计下降）、`avg_gradient`（平均坡度%）、`elevation_profile`（海拔采样 JSON，约 80 个值，供前端画 sparkline 缩略图）
3. **距离精度提升**：API 返回距离从 1 位小数改为 2 位小数（如 48.25 km）
4. **service.py 拆分**：`_haversine` 和 `_sample_elevation_profile` 提取到 `_geo_utils.py`，service.py 从 533 行降至 491 行

### 部署
5. **Caddyfile**：新增 `/tools/*` 静态文件路由

### 隔离验证
- app/activity/ 和 app/user/ 零修改
- 72 个测试全部通过（新增 4 个字段计算测试）
- 所有新 Segment 字段 nullable，向后兼容

## 2026-04-09 GCJ-02 → WGS-84 坐标系转换

### 问题
赛段创建接口（POST /api/segments）的 `reference_points` 没有坐标系约定。管理员从腾讯地图取的坐标是 GCJ-02（偏移 100~700m），而 GPX 轨迹点是 WGS-84。两套坐标在 matcher 里做距离计算时会偏移，导致 50m 容差下匹配必然失败。

### 修复
1. **新增 `app/segment/coord_convert.py`**：纯函数模块，GCJ-02 → WGS-84 转换，精度 <1m
2. **`SegmentCreateRequest` 新增 `coordinate_system` 字段**：`"gcj02"`（默认，腾讯/高德地图）或 `"wgs84"`（GPS/GPX 原始坐标）
3. **`service.create_segment` 集成转换**：在距离计算前调用 `convert_points_to_wgs84`，确保存入 PostGIS 的 reference_line 始终是 WGS-84（SRID=4326）
4. **新增 5 个测试用例**（test_21 ~ test_25）验证转换精度和边界情况

### Spec 偏离记录
- 原 spec 未提及坐标系，现在 API 层明确约定默认 GCJ-02 输入、内部统一 WGS-84 存储
- 向后兼容：不传 `coordinate_system` 字段默认走 GCJ-02 转换

## 2026-04-08 Alembic 迁移初始化 + Worker 超时保护 + 卡片天气字段决策

### 基础设施
1. **Alembic 初始化**：生成 `alembic.ini` + `migrations/env.py`，数据库地址从 `app/config.py` 统一读取。部署时执行 `alembic revision --autogenerate` + `alembic upgrade head` 即可生成并应用迁移。

### 功能增强
2. **Worker 超时保护（方案 A）**：`get_activity_status` 新增超时判断——activity 在 processing 状态超过 10 分钟时，自动标记为 failed 并提示"解析超时，请重新上传"。轻量方案，仅在前端轮询时触发，不引入额外基础设施。未来流量增长后可叠加定时扫描方案，两者不冲突。

### Spec 偏离记录
3. **v1 骑行卡片不显示天气**：spec 5.1 卡片设计包含 `22°C · 晴`，但 Activity 表无天气字段，前端获取天气也增加复杂度。决定 v1 卡片标题区仅显示日期（如 `2026.04.07`），天气留到 v2 按需添加。

## 2026-04-08 Task 4.5 排行榜接口 + 代码拆分

### 架构变更
1. **service.py 拆分**：自动匹配逻辑（`match_activity_against_segments` + `_parse_linestring_wkt`）从 `service.py` 拆到 `auto_match.py`。原因：service.py 达 468 行接近 500 行红线，新增排行榜函数后会突破。拆分后 service.py 410 行、auto_match.py 206 行。

### Spec 增强（向后兼容）
2. **排行榜 bike_type 字段**：`get_segment_detail` 的 TOP20 排行榜增加 `bike_type` 字段（来自 User 表）。Spec 原始定义无此字段，但 Task 4.5 的独立排行榜接口需要它，为保持一致性统一添加。不影响已有消费方（多返回一个可选字段）。

### 设计决策
3. **bike_type 过滤语义**：排行榜按 `bike_type` 过滤时，查的是用户当前车型（User 表），非骑行时车型。用户换车后历史成绩的车型会随之变化。MVP 阶段可接受。

## 2026-04-07 技术文档终版（v3 → 终版）

基于 ChatGPT 编写的 v3 技术文档，经 Claude 审查后修正 9 个问题：

### 严重修复
1. **ST_DWithin 单位错误**：PostGIS `geometry` 类型的 `ST_DWithin` 距离单位是度，不是米。所有空间查询加 `::geography` 转换
2. **缺少 HTTPS**：微信小程序强制要求 HTTPS。部署方案新增 Caddy 反向代理，自动 SSL 证书

### 功能修复
3. **距离单位不统一**：活动接口返回米、统计接口返回公里。统一为所有 API 返回公里
4. **时区未定义**：新增约定——数据库存 UTC，周期计算按 UTC+8
5. **GPX BOM 头**：上传校验增加 BOM 跳过处理
6. **活动标题不可编辑**：新增 `PATCH /api/activities/{id}` 接口
7. **路段创建无权限**：users 表增加 `is_admin`，创建路段需管理员权限
8. **JWT 无续期说明**：新增静默续期机制文档
9. **分页参数不一致**：统一为 `page_size`
