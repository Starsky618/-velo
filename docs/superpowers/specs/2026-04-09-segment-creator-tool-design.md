# 赛段创建工具 — 设计文档

## 1. 概述

管理员/开发者专用的赛段创建工具。从骑行 GPX 文件中截取赛段，通过 Strava 风格的海拔图拖选交互确认起止点，创建赛段并保存到后端。

部署在服务器上长期使用（Caddy 伺服静态文件），非一次性本地工具。

## 2. 隔离原则（硬约束）

本工具必须与已有模块严格隔离，防止污染现有代码：

### 2.1 前端隔离

- 工具是一个**独立的静态 HTML 文件**（`tools/segment-creator.html`），不嵌入 FastAPI 路由
- 所有 JS/CSS 内联或通过 CDN 引入，不引入构建工具链（无 npm、无 webpack）
- GPX 解析在浏览器端用 JS 独立实现，**不复用、不 import 后端 Python 模块**
- 与后端的唯一交互是 HTTP API 调用（`POST /api/segments`）

### 2.2 后端隔离

- 新增 Segment 模型字段（elevation_loss、avg_gradient、elevation_profile）必须**向后兼容**：
  - 所有新字段设为 `nullable`，不破坏现有记录
  - 现有 API 响应新增可选字段，不改变已有字段的含义
- 新增字段通过 **Alembic 迁移**添加，禁止手动 ALTER TABLE
- `create_segment` service 函数的改动必须确保：不传新字段时行为与改动前完全一致
- 距离精度从 1 位改 2 位小数仅影响 API 响应的 `round()` 调用，不改变数据库存储

### 2.3 审查检查清单

每个实施步骤完成后，审查 agent 必须检查：
- [ ] 是否修改了 `app/activity/` 下的任何文件？（不应该）
- [ ] 是否修改了 `app/user/` 下的任何文件？（不应该）
- [ ] 现有 68 个测试是否全部通过？
- [ ] API 响应是否向后兼容（新字段可选，旧字段不变）？
- [ ] `tools/segment-creator.html` 是否可以独立打开运行（不依赖后端即可展示 UI）？

## 3. 技术架构

### 3.1 前端（tools/segment-creator.html）

单 HTML 文件，外部依赖：
- **Leaflet**（CDN）— 地图渲染，OpenStreetMap 瓦片
- **Chart.js**（CDN）— 海拔剖面图

所有逻辑内联在 `<script>` 标签中：
- GPX XML 解析（DOMParser）
- haversine 距离计算
- 海拔统计（爬升、下降、坡度）
- Douglas-Peucker 轨迹简化（地图展示用）
- 海拔数据平滑（移动平均，展示用）

### 3.2 后端改动（Segment 模块）

仅涉及 `app/segment/` 目录：

**模型新增字段（models.py）**：
- `elevation_loss: Float, nullable` — 累计海拔下降（米）
- `avg_gradient: Float, nullable` — 平均坡度（%）
- `elevation_profile: JSON, nullable` — 海拔采样数组（约 80 个数值）

**Service 层（service.py）**：
- `create_segment` 计算并填充 `elevation_loss`、`avg_gradient`、`elevation_profile`
- 仅在 `reference_points` 包含 `ele` 数据时计算，否则字段为 null
- `avg_gradient` = elevation_gain / distance × 100（%）
- `elevation_profile` = 等距采样截取段的海拔值，固定输出 80 个点（PostgreSQL JSON 列存储）

**Schema 层（schemas.py）**：
- `SegmentResponse` 新增三个可选字段
- 距离字段精度：`round(distance / 1000.0, 2)`（1 位 → 2 位）

**迁移**：Alembic 生成迁移脚本，新增三列。

### 3.3 部署

- `tools/segment-creator.html` 通过 Caddy 伺服（在 Caddyfile 中加一条静态文件路由）
- 访问路径：`https://{域名}/tools/segment-creator`
- 与 API 同域名，无 CORS 问题
- 认证方式：页面顶部输入框粘贴管理员 JWT token

## 4. 用户工作流

```
1. 打开 https://{域名}/tools/segment-creator
2. 粘贴 JWT token
3. 点击"导入 GPX"选择文件
4. 页面解析并展示：
   - 摘要栏：总距离、总爬升、骑行时间
   - 海拔剖面图（Chart.js）：x 轴公里数，y 轴海拔
   - 路线地图（Leaflet + OSM）：灰色完整轨迹
5. 拖动海拔图上的双滑块选择起止点
   - 海拔图：选中区间红色高亮
   - 地图：选中段红色高亮，其余灰色
   - 摘要实时更新：距离、爬升、下降、坡度
   - 也可在输入框直接输入精确公里数
6. 输入赛段名称和描述（可选）
7. 点击"创建赛段"：
   - POST /api/segments，coordinate_system="wgs84"
   - 成功 → 显示结果摘要（名称、距离、爬升、下降、坡度、tolerance、match_ratio）
   - 失败 → 显示错误信息
8. 点击"下载 JSON"：API 不可用时的降级方案，保存赛段定义到本地文件
```

## 5. 海拔剖面图细节

### 5.1 双层渲染

- **底层**：原始海拔数据折线（锯齿状，半透明灰色填充）
- **顶层**：移动平均平滑曲线（窗口大小取轨迹点总数的 2%，最小 5 点，最大 30 点）

### 5.2 双滑块交互

- 两个可拖拽的圆形手柄，位于海拔图 x 轴上
- 拖拽时实时更新：
  - 海拔图高亮区间
  - 地图高亮路段
  - 截取段统计数据
- 手柄之间有最小间距限制（至少 0.5km），防止零距离赛段

### 5.3 海拔图与地图垂直对齐

- 两个组件宽度相同，x 轴（公里数）一一对应
- 鼠标悬停海拔图某点时，地图上对应位置显示标记点（可选增强，非必须）

## 6. 赛段保存标准

一条完整可用的赛段必须包含：

| 字段 | 来源 | 格式 |
|------|------|------|
| 名称 | 用户输入 | 字符串，1~128 字符 |
| 描述 | 用户输入（可选） | 字符串 |
| 距离 | 自动计算 | km，2 位小数 |
| 海拔爬升 | 自动计算 | 米，整数 |
| 海拔下降 | 自动计算 | 米，整数 |
| 平均坡度 | 自动计算 | %，1 位小数 |
| 海拔缩略图 | 自动生成 | JSON 数组（约 80 个海拔采样值） |
| 起终点坐标 | 自动提取 | lat/lon |
| 参考路线 | 自动提取 | 截取段全部坐标点 |

海拔缩略图的渲染规格：橙色描边曲线 + 灰色填充，无坐标轴，纯形状。前端用 SVG 或 Canvas 从 JSON 数组渲染，可自适应任意尺寸。

## 7. 不做的事

- 不做用户认证 UI（粘贴 JWT token）
- 不做 match_tolerance / min_match_ratio 自定义（用默认值 50m / 80%）
- 不做多文件批量处理（一次一个 GPX）
- 不做移动端适配（桌面浏览器专用）
- 不在 `app/activity/` 或 `app/user/` 下做任何改动
