# Paper Map Theme And Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every VELO mini-program map feel like a pale paper base, while keeping routes, heat lines, and selected points visually prominent.

**Architecture:** Put the shared map look in `miniprogram/utils/map-theme.js`, then let each page ask this helper for Tencent custom-style settings, pale overlay settings, and route-line colors. Replace the native Tencent location popup with `miniprogram/pages/map-picker/`, so the start/end point selection screen can use the same pale base as route preview maps.

**Tech Stack:** WeChat Mini Program JS/WXML/WXSS/JSON, Tencent `<map>` component, CommonJS utilities, pytest static contract tests, Node syntax checks.

---

## User Story

陈哥周五晚上发起约骑，先在创建页看到一张很淡的路线预览图：城市和山体像纸面背景，红色骑行轨迹才是主角。他点“选择起点”时进入 VELO 自己的地图页，仍然是同一张浅底图，只把绿色选点针和红色路线线条凸出来；他不会再突然看到一张腾讯默认的高饱和地图。

## Files By Responsibility

- Create: `miniprogram/utils/map-theme.js`  
  The single source for paper-map colors, Tencent custom-style config, shared map flags, and polyline styles.
- Modify: `miniprogram/pages/meetup-create/meetup-create.js`  
  Uses `map-theme.js` for preview map data and later consumes `map-picker` selections.
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxml`  
  Renders the route preview map and start/end picker buttons with the shared paper-map config.
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxss`  
  Keeps the pale paper overlay and route label visually consistent.
- Modify: `miniprogram/components/heatmap-card/heatmap-card.js`  
  Uses the same paper-map config and a muted heat polyline style.
- Modify: `miniprogram/components/heatmap-card/heatmap-card.wxml`  
  Renders heatmap maps through the shared paper-map branches.
- Modify: `miniprogram/components/heatmap-card/heatmap-card.wxss`  
  Adds the shared pale wash without changing the component layout.
- Create: `miniprogram/pages/map-picker/map-picker.js`  
  Lets users pick a point on the same pale Tencent map.
- Create: `miniprogram/pages/map-picker/map-picker.wxml`  
  Provides the map, center pin, and confirm/cancel controls.
- Create: `miniprogram/pages/map-picker/map-picker.wxss`  
  Styles the picker as a work screen, not a marketing page.
- Create: `miniprogram/pages/map-picker/map-picker.json`  
  Declares page title and component options.
- Modify: `miniprogram/app.json`  
  Registers the map picker page and removes the need for native `chooseLocation` privacy text once no caller remains.
- Test: `tests/test_meetup_miniprogram_static.py`  
  Adds static contracts for the shared map theme, heatmap map, route preview map, and map picker routing.

## Evidence Anchors

- [✓ grep] Route preview already renders Tencent `<map>` in `miniprogram/pages/meetup-create/meetup-create.wxml`.
- [✓ grep] Native point selection still calls `wx.chooseLocation` in `miniprogram/pages/meetup-create/meetup-create.js`.
- [✓ grep] Heatmap still renders a plain `<map>` in `miniprogram/components/heatmap-card/heatmap-card.wxml`.
- [✓ grep] Current front-end Tencent style config is local-only and must not include the server SK in `miniprogram/app.js`.

## Task 1: Shared Paper Map Theme

**Files:**
- Create: `miniprogram/utils/map-theme.js`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: Write the failing static test**

Add this test near the existing route-preview tests:

```python
def test_shared_paper_map_theme_exists_and_hides_server_secret():
    theme_path = MINI / "utils" / "map-theme.js"
    theme = _read(theme_path)

    assert "PAPER_MAP_CONFIG" in theme
    assert "getPaperMapData" in theme
    assert "buildRoutePreviewPolylines" in theme
    assert "buildHeatmapPolyline" in theme
    assert "TENCENT_MAP_SK" not in theme
    assert "server SK" in theme or "服务端 SK" in theme
```

- [ ] **Step 2: Run the red test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_shared_paper_map_theme_exists_and_hides_server_secret -q`

Expected: FAIL because `miniprogram/utils/map-theme.js` does not exist.

- [ ] **Step 3: Implement the shared helper**

Create `miniprogram/utils/map-theme.js` with:

```javascript
// 这个文件像一盒彩铅：所有小程序地图都从这里拿底图颜色、路线颜色和显示开关。
// 注意：这里只能放前端可公开的 Tencent 地图 subkey / layer-style，不能放服务端 SK。

const PAPER_MAP_CONFIG = {
  subkey: '',
  layerStyle: 1,
  routeColor: '#F04452',
  routeBorderColor: '#FFFFFF',
  heatColor: '#FFB020CC',
}

function getPaperMapData() {
  return {
    paperMapSubkey: PAPER_MAP_CONFIG.subkey,
    paperMapLayerStyle: PAPER_MAP_CONFIG.layerStyle,
    paperMapHasCustomStyle: Boolean(PAPER_MAP_CONFIG.subkey),
  }
}

function buildRoutePreviewPolylines(points) {
  if (!points || points.length < 2) return []
  return [
    { points, color: PAPER_MAP_CONFIG.routeBorderColor, width: 9 },
    { points, color: PAPER_MAP_CONFIG.routeColor, width: 5 },
  ]
}

function buildHeatmapPolyline(points, dottedLine) {
  return {
    points,
    color: PAPER_MAP_CONFIG.heatColor,
    width: 4,
    dottedLine: Boolean(dottedLine),
  }
}

module.exports = {
  PAPER_MAP_CONFIG,
  getPaperMapData,
  buildRoutePreviewPolylines,
  buildHeatmapPolyline,
}
```

- [ ] **Step 4: Run the green test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_shared_paper_map_theme_exists_and_hides_server_secret -q`

Expected: PASS.

## Task 2: Apply Paper Theme To Route Preview

**Files:**
- Modify: `miniprogram/pages/meetup-create/meetup-create.js`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxml`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxss`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: Write the failing static test**

Add:

```python
def test_create_page_uses_shared_paper_map_theme_for_route_preview():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" in js
    assert "buildRoutePreviewPolylines" in js
    assert "routePreviewMapSubkey" not in js
    assert "paperMapSubkey" in wxml
    assert "paperMapLayerStyle" in wxml
    assert "route-preview-wash" in wxml
    assert "rgba(255, 255, 255" in wxss
```

- [ ] **Step 2: Run the red test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_create_page_uses_shared_paper_map_theme_for_route_preview -q`

Expected: FAIL because the page still owns its own map config.

- [ ] **Step 3: Move route preview data to `map-theme.js`**

In `meetup-create.js`, require the helper:

```javascript
const mapTheme = require('../../utils/map-theme')
```

Initialize page data with:

```javascript
Object.assign({}, mapTheme.getPaperMapData(), {
  routePreview: null,
})
```

Build the preview polylines with:

```javascript
polyline: mapTheme.buildRoutePreviewPolylines(points)
```

- [ ] **Step 4: Rename WXML bindings to shared names**

Use `paperMapHasCustomStyle`, `paperMapSubkey`, and `paperMapLayerStyle` in the two existing `<map>` branches.

- [ ] **Step 5: Run the green test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_create_page_uses_shared_paper_map_theme_for_route_preview -q`

Expected: PASS.

## Task 3: Apply Paper Theme To Heatmap Card

**Files:**
- Modify: `miniprogram/components/heatmap-card/heatmap-card.js`
- Modify: `miniprogram/components/heatmap-card/heatmap-card.wxml`
- Modify: `miniprogram/components/heatmap-card/heatmap-card.wxss`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: Write the failing static test**

Add:

```python
def test_heatmap_card_uses_shared_paper_map_theme():
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")
    wxml = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxml")
    wxss = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxss")

    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" in js
    assert "buildHeatmapPolyline" in js
    assert "#FFD700CC" not in js
    assert "paperMapSubkey" in wxml
    assert "heatmap-map-wash" in wxml
    assert "rgba(255, 255, 255" in wxss
```

- [ ] **Step 2: Run the red test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_heatmap_card_uses_shared_paper_map_theme -q`

Expected: FAIL because the component still owns a hard-coded heat line and plain map.

- [ ] **Step 3: Use the helper in `heatmap-card.js`**

Require `map-theme.js`, merge `getPaperMapData()` into component data, and replace the hard-coded polyline object with:

```javascript
return mapTheme.buildHeatmapPolyline(points, seg.distance < 2000)
```

- [ ] **Step 4: Add the pale overlay in WXML/WXSS**

Render the map with custom-style and fallback branches, then add `cover-view class="heatmap-map-wash"` over the map.

- [ ] **Step 5: Run the green test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_heatmap_card_uses_shared_paper_map_theme -q`

Expected: PASS.

## Task 4: Map Picker Page

**Files:**
- Create: `miniprogram/pages/map-picker/map-picker.js`
- Create: `miniprogram/pages/map-picker/map-picker.wxml`
- Create: `miniprogram/pages/map-picker/map-picker.wxss`
- Create: `miniprogram/pages/map-picker/map-picker.json`
- Modify: `miniprogram/app.json`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: Write the failing static test**

Add:

```python
def test_map_picker_page_is_registered_and_uses_paper_map():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "map-picker" / "map-picker.js")
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")
    wxss = _read(MINI / "pages" / "map-picker" / "map-picker.wxss")

    assert "pages/map-picker/map-picker" in app_json["pages"]
    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" in js
    assert "selectMapPoint" in js
    assert "paperMapSubkey" in wxml
    assert "map-picker-pin" in wxml
    assert "确认位置" in wxml
    assert "rgba(255, 255, 255" in wxss
```

- [ ] **Step 2: Run the red test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_map_picker_page_is_registered_and_uses_paper_map -q`

Expected: FAIL because the picker page does not exist.

- [ ] **Step 3: Register and create the page**

Add `"pages/map-picker/map-picker"` to `miniprogram/app.json`. Create the four page files. The page should show a Tencent map, a fixed center pin, “取消”, and “确认位置”.

- [ ] **Step 4: Store the selected point**

When the user confirms, write this shape to `getApp().globalData.pendingMapPoint`:

```javascript
{
  kind: this.data.kind,
  latitude: this.data.latitude,
  longitude: this.data.longitude,
  name: this.data.name || '地图选点'
}
```

Then call `wx.navigateBack()`.

- [ ] **Step 5: Run the green test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_map_picker_page_is_registered_and_uses_paper_map -q`

Expected: PASS.

## Task 5: Replace Native Location Popup In Meetup Create

**Files:**
- Modify: `miniprogram/pages/meetup-create/meetup-create.js`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxml`
- Modify: `miniprogram/app.js`
- Modify: `miniprogram/app.json`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [ ] **Step 1: Write the failing static test**

Add:

```python
def test_meetup_create_uses_map_picker_instead_of_choose_location():
    app_js = _read(MINI / "app.js")
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "wx.chooseLocation" not in js
    assert "pages/map-picker/map-picker?kind=start" in js
    assert "consumePendingMapPoint" in js
    assert "pendingMapPoint" in app_js
    assert "chooseLocation" not in json.dumps(app_json, ensure_ascii=False)
```

- [ ] **Step 2: Run the red test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_meetup_create_uses_map_picker_instead_of_choose_location -q`

Expected: FAIL because `meetup-create.js` still uses the native location popup.

- [ ] **Step 3: Add pending map point storage**

In `miniprogram/app.js`, add:

```javascript
pendingMapPoint: null,
```

- [ ] **Step 4: Replace start/end selection**

In `meetup-create.js`, change `onTapChoosePoint` to navigate to the picker:

```javascript
wx.navigateTo({
  url: '/pages/map-picker/map-picker?kind=' + kind,
})
```

In `onShow`, call `consumePendingMapPoint()` and apply the returned point to `startPoint` or `endPoint`.

- [ ] **Step 5: Remove native choose-location privacy entry**

After no caller uses `wx.chooseLocation`, remove `chooseLocation` from `miniprogram/app.json` required privacy descriptors.

- [ ] **Step 6: Run the green test**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_meetup_create_uses_map_picker_instead_of_choose_location -q`

Expected: PASS.

## Final Verification

- [ ] Run focused static tests:

```bash
python3 -m pytest tests/test_route_book_api.py tests/test_meetup_miniprogram_static.py -q
```

- [ ] Run JavaScript syntax checks:

```bash
node --check miniprogram/utils/map-theme.js
node --check miniprogram/components/heatmap-card/heatmap-card.js
node --check miniprogram/pages/meetup-create/meetup-create.js
node --check miniprogram/pages/map-picker/map-picker.js
node --check miniprogram/app.js
```

- [ ] Run whitespace check:

```bash
git diff --check
```

- [ ] Open WeChat Developer Tools project after code verification and visually check:
  - Route preview map shows a pale base.
  - Heatmap card still renders route lines.
  - Start/end selection opens VELO map picker, not the native Tencent popup.
