# 任务 3.B.2：segment-creator.html 增强 + 搬到 admin-h5

> **brainstorming v2 / 2026-05-05 决策落地**（决策 4 = Y3：admin H5 砍 from-activity 页面，下放给现成 segment-creator.html）。

## 🎯 目标

现有 `tools/segment-creator.html`（4 月 16 日已成熟 / 4 commit 迭代 / 海拔图 + 键盘 ±20m 微调）：
- **加 activity_id 模式**：除拖 GPX 外，支持输入 activity_id 从后端拉 trackpoints
- **改调新 admin endpoint**（task-3.A.6 上线后）
- **搬到 admin-h5 repo `public/segment-creator.html`**，通过 `admin.velo.com/segment-creator.html` 访问
- velo backend repo 删 `tools/segment-creator.html`

**目的**：保留这个工具的精度交互（用户级核心需求 / 赛段排名按秒计），不重写为 React。

## ⛓ 前置依赖

- task-3.A.6（admin from-gpx endpoint 上线）
- task-3.B.1（admin-h5 repo 项目骨架建好 / 至少 public/ 目录可放）
- 后端 `GET /api/activities/{id}/trackpoints` endpoint（存在性待 grep / 不存在则本卡新增 admin only 版）

## 📤 输出契约

| 产物 | 内容 |
|---|---|
| segment-creator.html v2 | 加 activity_id 模式 + 改调 admin endpoint + 视觉与 admin H5 协调 |
| admin H5 navigation | 在批量管理页或顶栏加链接"打开赛段创建工具" → `/segment-creator.html` |
| 后端可能新增 endpoint | `GET /api/admin/activities/{id}/trackpoints`（如不存在） |

## 🧱 现状（grep 已验证 2026-05-05）

- `tools/segment-creator.html` 现存（59KB / 1700+ 行）
- 已有功能：拖 GPX + Chart.js 海拔剖面 + Leaflet 地图 + 海拔图拖选起终点 + 键盘 ←→ ±20m 微调 + 长按连续 + 起终点标签可选中视觉增强
- 调 endpoint：`POST /api/segments`（task-3.A.6 后改为 `POST /api/admin/segments/from-gpx`）
- 4 commit 历史：`630cb54`（初版）→ `ed3eb16`（键盘微调）→ `e2c0b1f`（视觉增强）→ `5b4c494`（品牌重命名）
- 登录方式：JWT 输入框（与 brainstorming 路径 1 完全一致）

## 🛠 完整改造

### 1. 加 activity_id 模式（HTML / JS 增量）

#### UI 改动（在拖放区上方加面板）

```html
<!-- 在 .drop-zone 上方插入 -->
<div class="activity-mode-panel">
  <div class="mode-tabs">
    <button class="mode-tab active" data-mode="gpx">从 GPX 文件</button>
    <button class="mode-tab" data-mode="activity">从已上传活动</button>
  </div>
  <div class="activity-input" style="display: none;">
    <input type="number" id="activityIdInput" placeholder="输入 activity_id" />
    <button id="loadActivityBtn">从活动拉取</button>
  </div>
</div>
```

#### JS 逻辑

```javascript
// 在主文件靠近 GPX 解析的地方加
async function loadFromActivity(activityId) {
  const jwt = document.getElementById('jwtInput').value.trim();
  const resp = await fetch(`${API_BASE_URL}/api/admin/activities/${activityId}/trackpoints`, {
    headers: { 'Authorization': `Bearer ${jwt}` },
  });
  if (!resp.ok) {
    alert(`拉取失败 ${resp.status}`);
    return;
  }
  const data = await resp.json();
  // 转成与 GPX 解析后等价的格式
  const trackpoints = data.trackpoints.map(p => ({
    lat: p.lat,
    lon: p.lon,
    ele: p.elevation,
    time: p.timestamp,
  }));
  // 复用现有渲染逻辑
  state.trackpoints = computeCumDist(trackpoints);
  renderElevationChart();
  renderMap();
}

document.getElementById('loadActivityBtn').addEventListener('click', () => {
  const id = parseInt(document.getElementById('activityIdInput').value);
  if (!isNaN(id)) loadFromActivity(id);
});
```

### 2. 改调新 admin endpoint

```javascript
// async function createSegment() 内
// 旧: const resp = await fetch(`${API_BASE_URL}/api/segments`, {
// 新:
const resp = await fetch(`${API_BASE_URL}/api/admin/segments/from-gpx`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${jwt}`,
  },
  body: JSON.stringify({
    name,
    description,
    reference_points,
    coordinate_system: 'wgs84',
  }),
});
```

### 3. 后端可能新增（如果现有不存在）

grep 验证：`GET /api/activities/{id}/trackpoints` 是否已实现 admin 可访问版本。
- 如已存在且能取所有人活动 → 直接用（确认 admin 权限校验）
- 如不存在或仅看自己 → 新加 `GET /api/admin/activities/{id}/trackpoints`（require_admin / 任何活动可看）

```python
# app/admin/router.py 追加（如需要）
@router.get("/activities/{activity_id}/trackpoints", response_model=schemas.TrackpointListResponse)
def get_activity_trackpoints_admin(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """admin 可读任意活动的 trackpoints（不限 own）。"""
    activity = db.query(Activity).filter_by(id=activity_id).first()
    if not activity:
        raise HTTPException(404, "activity not found")
    points = db.query(Trackpoint).filter_by(activity_id=activity_id).order_by(Trackpoint.seq).all()
    return {
        "activity_id": activity_id,
        "trackpoints": [
            {"lat": p.lat, "lon": p.lon, "elevation": p.elevation, "timestamp": p.timestamp.isoformat()}
            for p in points
        ],
    }
```

### 4. 搬迁文件

```bash
# admin-h5 repo 内
cd ~/Desktop/admin-h5
mkdir -p public
git mv ~/Desktop/velo/tools/segment-creator.html public/segment-creator.html
# 修改部分内容（步骤 1-2）后 commit
```

```bash
# velo backend repo 内
cd ~/Desktop/velo
git rm tools/segment-creator.html
# 同时考虑：tools/ 目录是否还需要保留？如已空可一并删除
git commit -m "chore(tools): segment-creator.html 搬到 admin-h5 repo（task-3.B.2）"
```

### 5. admin H5 加导航链接

`admin-h5/src/components/AppLayout.tsx` 顶栏 / 侧栏加：
```tsx
<a href="/segment-creator.html" target="_blank">打开赛段创建工具</a>
```

### 6. 视觉协调（可选 / 如有时间）

segment-creator.html 当前用自己的 dark theme（Strava 橙）。admin H5 用 AntD dark theme。如视觉差异明显可微调 segment-creator 的 CSS 变量靠近 AntD 色板。**优先级低**，本卡先不做。

## ✅ 端到端验收

- [ ] **GPX 模式**：拖文件 → 海拔图 + 地图渲染 → 拖选起终点 → 键盘 ±20m 微调 → 创建成功
- [ ] **activity_id 模式**：输入 activity_id → 拉取 trackpoints → 同样的渲染 + 拖选 + 微调 → 创建成功
- [ ] **API 切换**：fetch URL 走 `/api/admin/segments/from-gpx`，老路径无调用
- [ ] **admin 守卫**：非 admin token → 403 拒绝
- [ ] **键盘微调精度**：±20m 步进准确（手动验证 5-10 次）
- [ ] **admin H5 链接**：从批量管理页能跳到 segment-creator.html
- [ ] **velo backend repo `tools/`**：segment-creator.html 已删

## 📝 commit（admin-h5 repo）

```
feat(segment-creator): 任务 3.B.2 增强 activity_id 模式 + 切 admin endpoint

- 加"从已上传活动"模式（输入 activity_id 拉 trackpoints）
- fetch URL 切到 /api/admin/segments/from-gpx
- 文件搬入 admin-h5/public/
- admin H5 导航加链接"打开赛段创建工具"

附后端（velo backend repo / 如需要）：
- GET /api/admin/activities/{id}/trackpoints（require_admin / 任何活动可读）
```

```
chore(tools): segment-creator.html 搬到 admin-h5 repo（task-3.B.2）
- velo backend repo 删 tools/segment-creator.html
```

## 🔍 自检三问

1. **为什么不重写为 React 组件**？
   → 现有 HTML 是 4 个 commit 迭代过的成熟工具（精度交互打磨过）。重写成 React 风险高（精度复刻可能失真）+ 5-7 天工时。增量加 activity_id 模式 + 改 fetch URL 1-1.5 天搞定。
   见 brainstorming Y2 vs Y3 决策。

2. **activity_id 模式的 trackpoints API 现存吗**？
   → 待 grep 验证（task-3.B.2 实施起手第一动作）。如不存在，新加 `GET /api/admin/activities/{id}/trackpoints`（任何活动 admin 可读 / require_admin）。

3. **轨迹精度怎么保证**？
   → segment-creator.html 现有 ✅
     - 海拔图鼠标拖选起终点
     - 起终点标签 tabindex 选中后键盘 ←→ ±20m 微调
     - 长按连续微调
   → activity_id 模式直接复用同样 UI，无新精度风险。
