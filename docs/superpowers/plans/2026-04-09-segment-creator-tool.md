# 赛段创建工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Strava 风格的赛段创建工具（HTML 页面），从 GPX 文件中截取赛段，通过海拔图拖选 + 地图预览确认后保存到后端。

**Architecture:** 单 HTML 文件（tools/segment-creator.html）内联 JS/CSS，CDN 引入 Leaflet + Chart.js。后端仅在 Segment 模型上新增 3 个 nullable 字段（elevation_loss、avg_gradient、elevation_profile），通过 Alembic 迁移。前后端唯一交互点是 POST /api/segments。

**Tech Stack:** HTML/JS/CSS（内联）、Leaflet + OpenStreetMap、Chart.js、FastAPI、SQLAlchemy、Alembic、Caddy

**隔离约束:** 不修改 app/activity/ 或 app/user/ 下的任何文件。所有后端改动仅限 app/segment/ 目录。现有 68 个测试必须全部通过。

---

## 文件结构

**新建：**
- `tools/segment-creator.html` — 赛段创建工具前端页面（单文件，约 800~1000 行）

**修改（仅 app/segment/）：**
- `app/segment/models.py` — Segment 模型新增 3 个字段
- `app/segment/service.py` — create_segment 计算并填充新字段
- `app/segment/schemas.py` — SegmentResponse 新增 3 个可选字段，距离精度 1→2 位
- `app/segment/router.py` — 响应构造加上新字段

**新建（迁移）：**
- `migrations/versions/xxxx_add_segment_elevation_fields.py` — Alembic 迁移脚本

**新建（测试）：**
- `tests/test_segment_fields.py` — 新字段计算逻辑的单元测试

**修改（部署）：**
- `Caddyfile` — 新增 tools 静态文件路由

---

## Task 1: Segment 模型新增字段

**Files:**
- Modify: `app/segment/models.py:46-48`

- [ ] **Step 1: 在 Segment 模型中新增 3 个字段**

在 `elevation_gain` 字段下方添加三个新字段：

```python
    # 赛段长度和爬升
    distance = Column(Float, nullable=False)          # 米
    elevation_gain = Column(Float, nullable=True)      # 米
    elevation_loss = Column(Float, nullable=True)      # 累计海拔下降（米）
    avg_gradient = Column(Float, nullable=True)        # 平均坡度（%）
    elevation_profile = Column(Text, nullable=True)    # 海拔采样 JSON 数组（约 80 个数值）
```

注意：`elevation_profile` 用 `Text` 而非 `JSON` 类型，因为 SQLite 测试环境不支持原生 JSON 列，用 Text 存 JSON 字符串兼容两边。service 层负责 `json.dumps` / `json.loads`。

- [ ] **Step 2: 确认现有测试不受影响**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: 68 passed（新增 nullable 字段不影响已有逻辑）

- [ ] **Step 3: Commit**

```bash
git add app/segment/models.py
git commit -m "feat(segment): Segment 模型新增 elevation_loss/avg_gradient/elevation_profile 字段"
```

---

## Task 2: Service 层计算新字段

**Files:**
- Modify: `app/segment/service.py:56-147`（create_segment 函数）
- Test: `tests/test_segment_fields.py`

- [ ] **Step 1: 创建测试文件，编写新字段计算测试**

```python
# tests/test_segment_fields.py
"""
赛段新增字段测试——验证 elevation_loss、avg_gradient、elevation_profile 的计算逻辑。

纯逻辑测试，通过 API 端点调用间接测试 service 层计算。
使用 SQLite 测试数据库，不涉及 PostGIS。
"""

import json

import pytest

from app.dependencies import create_token
from app.user.models import User


@pytest.fixture()
def admin_user(db):
    """创建一个管理员测试用户。"""
    user = User(openid="admin_openid_999", is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def admin_header(admin_user):
    """生成管理员 JWT 请求头。"""
    token = create_token(admin_user.id)
    return {"Authorization": f"Bearer {token}"}


def test_01_create_segment_new_fields(client, admin_header):
    """创建带海拔数据的赛段，验证新增字段正确计算。"""
    # 模拟一段先上坡后下坡的赛段：800m → 900m → 850m
    payload = {
        "name": "测试坡段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55, "ele": 800.0},
            {"lat": 37.871, "lon": 112.55, "ele": 850.0},
            {"lat": 37.872, "lon": 112.55, "ele": 900.0},
            {"lat": 37.873, "lon": 112.55, "ele": 880.0},
            {"lat": 37.874, "lon": 112.55, "ele": 850.0},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    assert resp.status_code == 200
    data = resp.json()

    # elevation_gain = (850-800) + (900-850) = 100m
    assert data["elevation_gain"] == 100.0
    # elevation_loss = (900-880) + (880-850) = 50m
    assert data["elevation_loss"] == 50.0
    # avg_gradient = elevation_gain / distance * 100
    assert data["avg_gradient"] is not None
    assert data["avg_gradient"] > 0
    # elevation_profile 是 JSON 数组
    assert data["elevation_profile"] is not None
    profile = data["elevation_profile"]
    assert isinstance(profile, list)
    assert len(profile) > 0
    # 首尾值应接近原始首尾海拔
    assert abs(profile[0] - 800.0) < 1.0
    assert abs(profile[-1] - 850.0) < 1.0


def test_02_create_segment_no_elevation(client, admin_header):
    """无海拔数据时，新字段应为 null。"""
    payload = {
        "name": "无海拔赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    assert resp.status_code == 200
    data = resp.json()

    assert data["elevation_gain"] is None
    assert data["elevation_loss"] is None
    assert data["avg_gradient"] is None
    assert data["elevation_profile"] is None


def test_03_create_segment_distance_precision(client, admin_header):
    """距离精度应为 2 位小数。"""
    payload = {
        "name": "精度测试",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55},
            {"lat": 37.875, "lon": 112.55},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    data = resp.json()

    # 距离字符串化后小数点后应有 1~2 位
    dist_str = str(data["distance"])
    if "." in dist_str:
        decimal_places = len(dist_str.split(".")[1])
        assert decimal_places <= 2


def test_04_flat_segment_zero_gradient(client, admin_header):
    """完全平坦的赛段，坡度应为 0。"""
    payload = {
        "name": "平坦赛段",
        "reference_points": [
            {"lat": 37.87, "lon": 112.55, "ele": 800.0},
            {"lat": 37.871, "lon": 112.55, "ele": 800.0},
            {"lat": 37.872, "lon": 112.55, "ele": 800.0},
        ],
        "coordinate_system": "wgs84",
    }
    resp = client.post("/api/segments", json=payload, headers=admin_header)
    data = resp.json()

    assert data["elevation_gain"] == 0.0
    assert data["elevation_loss"] == 0.0
    assert data["avg_gradient"] == 0.0
```

- [ ] **Step 2: 运行测试，确认失败（新字段不存在）**

Run: `python3 -m pytest tests/test_segment_fields.py -v --tb=short`
Expected: FAIL（SegmentResponse 缺少 elevation_loss 等字段）

- [ ] **Step 3: 修改 service.py create_segment 函数**

在 `elevation_gain` 计算逻辑后面，追加 `elevation_loss`、`avg_gradient`、`elevation_profile` 的计算：

```python
    # 计算累计爬升（米）和累计下降（米）
    elevation_gain = None
    elevation_loss = None
    avg_gradient = None
    elevation_profile = None
    if all(p.get("ele") is not None for p in reference_points):
        elevation_gain = 0.0
        elevation_loss = 0.0
        for i in range(1, len(reference_points)):
            diff = reference_points[i]["ele"] - reference_points[i - 1]["ele"]
            if diff > 0:
                elevation_gain += diff
            elif diff < 0:
                elevation_loss += abs(diff)

        # 平均坡度（%）= 累计爬升 / 水平距离 × 100
        # total_distance 已在前面计算过（米）
        avg_gradient = round(elevation_gain / total_distance * 100, 1) if total_distance > 0 else 0.0

        # 海拔缩略图：等距采样约 80 个点的海拔值
        elevation_profile = _sample_elevation_profile(reference_points, target_count=80)
```

在 `_haversine` 函数下方添加 `_sample_elevation_profile` 辅助函数：

```python
def _sample_elevation_profile(
    points: list[dict], target_count: int = 80,
) -> list[float]:
    """
    从参考路线中等距采样海拔值，生成缩略图数据。

    好比把一条海拔曲线"压缩"成固定数量的采样点：
    原始路线可能有几千个点，缩略图只需要约 80 个点就能画出形状。
    等距采样保证曲线形状不失真——每隔固定距离取一个海拔值。

    返回：海拔值的浮点数列表，如 [800.0, 810.5, 835.2, ...]
    """
    n = len(points)
    if n <= target_count:
        return [round(p["ele"], 1) for p in points]

    # 等距采样：在 [0, n-1] 范围内均匀取 target_count 个索引
    step = (n - 1) / (target_count - 1)
    return [round(points[int(i * step)]["ele"], 1) for i in range(target_count)]
```

在 `Segment` 赋值处添加新字段：

```python
    segment = Segment(
        name=name,
        description=description,
        distance=total_distance,
        elevation_gain=elevation_gain,
        elevation_loss=elevation_loss,
        avg_gradient=avg_gradient,
        elevation_profile=json.dumps(elevation_profile) if elevation_profile is not None else None,
        start_lat=first["lat"],
        ...
    )
```

在文件顶部添加 `import json`。

- [ ] **Step 4: 修改 schemas.py SegmentResponse 新增字段**

```python
class SegmentResponse(BaseModel):
    """赛段完整信息——创建成功后返回"""
    id: int
    name: str
    description: Optional[str] = None
    distance: float                          # 公里
    elevation_gain: Optional[float] = None   # 米
    elevation_loss: Optional[float] = None   # 米（新增）
    avg_gradient: Optional[float] = None     # %（新增）
    elevation_profile: Optional[list[float]] = None  # 海拔采样数组（新增）
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    match_tolerance: float
    min_match_ratio: float
    created_at: Optional[datetime] = None
```

- [ ] **Step 5: 修改 router.py 响应构造**

```python
    return schemas.SegmentResponse(
        id=segment.id,
        name=segment.name,
        description=segment.description,
        distance=round(segment.distance / 1000.0, 2),  # 精度 1→2 位
        elevation_gain=segment.elevation_gain,
        elevation_loss=segment.elevation_loss,
        avg_gradient=segment.avg_gradient,
        elevation_profile=json.loads(segment.elevation_profile) if segment.elevation_profile else None,
        start_lat=segment.start_lat,
        start_lon=segment.start_lon,
        end_lat=segment.end_lat,
        end_lon=segment.end_lon,
        match_tolerance=segment.match_tolerance,
        min_match_ratio=segment.min_match_ratio,
        created_at=segment.created_at,
    )
```

在 router.py 顶部添加 `import json`。

- [ ] **Step 6: 运行全量测试**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: 所有测试通过（原 68 个 + 新增 4 个 = 72 个）

- [ ] **Step 7: Commit**

```bash
git add app/segment/models.py app/segment/service.py app/segment/schemas.py app/segment/router.py tests/test_segment_fields.py
git commit -m "feat(segment): 新增 elevation_loss/avg_gradient/elevation_profile 字段计算"
```

---

## Task 3: 距离精度修正（所有响应统一 2 位小数）

**Files:**
- Modify: `app/segment/service.py`（get_segment_list、get_segment_detail 中的 round 调用）

- [ ] **Step 1: 全局搜索 service.py 中所有 `round(segment.distance / 1000.0, 1)` 并改为 2 位**

`service.py` 中有两处（get_segment_list 第 210 行附近、get_segment_detail 第 277 行附近）：

```python
# 改前
"distance": round(segment.distance / 1000.0, 1),
# 改后
"distance": round(segment.distance / 1000.0, 2),
```

- [ ] **Step 2: 运行全量测试确认无破坏**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: 全部通过

- [ ] **Step 3: Commit**

```bash
git add app/segment/service.py
git commit -m "fix(segment): 距离精度从 1 位改为 2 位小数"
```

---

## Task 4: Caddyfile 添加 tools 静态路由

**Files:**
- Modify: `Caddyfile`

- [ ] **Step 1: 在 Caddyfile 中添加 tools 目录的静态文件服务**

```
api.ridemap.cn {
    # 赛段创建等管理工具（静态 HTML 文件）
    handle /tools/* {
        root * /app
        file_server
    }

    # API 反向代理
    handle {
        reverse_proxy api:8000
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add Caddyfile
git commit -m "feat(deploy): Caddy 添加 /tools/ 静态文件路由"
```

---

## Task 5: 前端页面 — GPX 解析 + 海拔剖面图

**Files:**
- Create: `tools/segment-creator.html`

这是最大的任务。分为三个子步骤：先搭骨架 + GPX 解析，再加海拔图，最后加地图和交互。

- [ ] **Step 1: 创建 HTML 骨架 + GPX 解析逻辑**

创建 `tools/segment-creator.html`，包含：
- HTML 结构：顶部工具栏（文件导入 + JWT 输入）、海拔图容器、地图容器、表单区
- CDN 引入 Chart.js 和 Leaflet
- JS：GPX XML 解析函数（DOMParser 提取 trkpt 的 lat/lon/ele）
- JS：haversine 距离计算函数
- JS：为每个轨迹点计算累计公里数
- 导入 GPX 后打印摘要到页面（总距离、总爬升、轨迹点数）

使用 frontend-design skill 实现高质量 UI。页面整体风格参考 Strava 的暗色主题赛段创建页面。

- [ ] **Step 2: 运行验证（本地打开 HTML 文件）**

用浏览器直接打开 `tools/segment-creator.html`，导入一个 GPX 文件，确认：
- 文件能正确解析
- 摘要数据（距离、爬升）合理
- 无 JS 控制台报错

- [ ] **Step 3: 添加 Chart.js 海拔剖面图**

- x 轴：累计公里数
- y 轴：海拔（米）
- 双层渲染：原始数据灰色填充 + 移动平均平滑曲线
- 移动平均窗口：轨迹点总数的 2%，clamp(5, 30)

- [ ] **Step 4: 添加双滑块拖选**

- 海拔图 x 轴下方两个可拖拽手柄（起点/终点）
- 使用 Chart.js annotation plugin 或自定义 canvas overlay
- 拖动时实时更新：高亮区间、公里数输入框、截取段统计
- 支持直接在输入框输入精确公里数
- 最小间距 0.5km

- [ ] **Step 5: 验证海拔图交互**

本地打开 HTML，导入 GPX：
- 拖动滑块，观察高亮区间变化
- 输入公里数，观察滑块位置同步
- 确认截取段统计（距离、爬升、下降、坡度）正确

- [ ] **Step 6: Commit**

```bash
git add tools/segment-creator.html
git commit -m "feat(tools): 赛段创建工具 — GPX 解析 + 海拔剖面图 + 拖选"
```

---

## Task 6: 前端页面 — Leaflet 地图 + 联动

**Files:**
- Modify: `tools/segment-creator.html`

- [ ] **Step 1: 添加 Leaflet 地图**

- OpenStreetMap 瓦片
- GPX 导入后绘制完整轨迹（灰色 polyline）
- 使用 Douglas-Peucker 简化到约 800 点（JS 实现）
- 地图自动缩放到轨迹范围（fitBounds）

- [ ] **Step 2: 海拔图与地图联动**

- 滑块拖动时，地图上选中段用红色 polyline 高亮
- 非选中部分保持灰色
- 起终点分别放置标记（圆形 marker）
- 海拔图和地图宽度对齐

- [ ] **Step 3: 验证联动**

本地打开 HTML，导入 GPX：
- 拖动滑块，地图红色高亮同步变化
- 输入公里数，地图同步更新
- 起终点标记位置正确

- [ ] **Step 4: Commit**

```bash
git add tools/segment-creator.html
git commit -m "feat(tools): 赛段创建工具 — Leaflet 地图 + 海拔图联动"
```

---

## Task 7: 前端页面 — 赛段创建 + JSON 降级

**Files:**
- Modify: `tools/segment-creator.html`

- [ ] **Step 1: 添加赛段创建表单和提交逻辑**

- 赛段名称输入框（必填）
- 描述输入框（可选）
- "创建赛段"按钮：
  - 从截取段轨迹点构造 `reference_points` 数组（含 lat/lon/ele）
  - POST /api/segments，header 带 JWT token，coordinate_system="wgs84"
  - 成功：显示结果摘要（名称、距离km、爬升m、下降m、坡度%、tolerance、match_ratio）
  - 失败：显示错误信息
- "下载 JSON"按钮：
  - 生成与 API 请求相同格式的 JSON
  - 触发浏览器下载（Blob + URL.createObjectURL）

- [ ] **Step 2: 验证完整流程**

本地打开 HTML：
1. 导入 GPX → 看到海拔图和地图
2. 拖选赛段 → 看到高亮和统计
3. 输入名称 → 点"下载 JSON" → 检查 JSON 文件内容正确
4. （如果 API 可用）点"创建赛段" → 看到成功摘要

- [ ] **Step 3: Commit**

```bash
git add tools/segment-creator.html
git commit -m "feat(tools): 赛段创建工具 — 表单提交 + JSON 降级下载"
```

---

## Task 8: 隔离审查

**Files:** 无新改动，纯审查

- [ ] **Step 1: 运行全量测试**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: 72 passed（68 原有 + 4 新增）

- [ ] **Step 2: 隔离检查**

Run: `git diff --name-only HEAD~6` （查看所有改动的文件列表）

确认：
- [ ] 没有修改 `app/activity/` 下的任何文件
- [ ] 没有修改 `app/user/` 下的任何文件
- [ ] `tools/segment-creator.html` 可以独立打开（不依赖后端）
- [ ] 新增的 Segment 字段都是 nullable（不破坏已有记录）

- [ ] **Step 3: 代码健康度巡检**

Run: `wc -l app/segment/*.py`

检查：
- service.py 是否仍在 500 行以内？（如果超了，需要拆分）
- segment 模块文件数是否 ≤8？

- [ ] **Step 4: 更新 changelog**

在 `docs/changelog.md` 顶部添加本次变更记录。

- [ ] **Step 5: Commit**

```bash
git add docs/changelog.md
git commit -m "docs: 更新 changelog — 赛段创建工具"
```
