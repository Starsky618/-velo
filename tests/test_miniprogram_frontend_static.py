"""小程序前端模块边界与共享地图、热力图回归。"""

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block_after(wxml: str, marker: str) -> str:
    return wxml.split(marker, 1)[1]


def test_meetup_frontend_is_fully_removed():
    app_json = json.loads(_read(MINI / "app.json"))
    registered_pages = app_json["pages"]
    tab_paths = [item["pagePath"] for item in app_json["tabBar"]["list"]]

    assert tab_paths == [
        "pages/home/home",
        "pages/explore/explore",
        "pages/upload/upload",
        "pages/profile/profile",
    ]
    assert "pages/map-picker/map-picker" not in registered_pages
    assert all("meetup" not in page.lower() for page in registered_pages)
    assert all("约骑" not in item.get("text", "") for item in app_json["tabBar"]["list"])

    removed_paths = [
        MINI / "pages" / "map-picker",
        MINI / "pages" / "meetup-create",
        MINI / "pages" / "meetup-detail",
        MINI / "pages" / "meetup-report",
        MINI / "pages" / "meetups-list",
        MINI / "pages" / "meetups-mine",
        MINI / "assets" / "icons" / "meetup",
        MINI / "utils" / "meetup-format.js",
    ]
    assert all(not path.exists() for path in removed_paths)

    allowed_account_deletion_disclosures = {
        MINI / "pages" / "settings" / "settings.js": [
            "已开放约骑会取消并解除关联后保留",
            "需删除已开放约骑",
        ],
        MINI / "pages" / "settings" / "settings.wxml": [
            "已开放约骑会取消并去关联保留",
        ],
        MINI / "utils" / "api.js": [
            "已开放约骑按后端规则去标识保留",
        ],
    }
    runtime_suffixes = {".js", ".json", ".wxml", ".wxss"}
    for path in MINI.rglob("*"):
        if not path.is_file() or path.suffix not in runtime_suffixes:
            continue
        if "design-system" in path.parts:
            continue
        source = _read(path)
        assert "meetup" not in source.lower(), f"{path} 仍残留约骑运行时代码"
        for disclosure in allowed_account_deletion_disclosures.get(path, []):
            assert disclosure in source
            source = source.replace(disclosure, "")
        assert "约骑" not in source, f"{path} 仍残留约骑用户文案或超出注销披露范围"


def test_route_and_upload_surfaces_keep_core_flows_without_meetup_links():
    route_guide_js = _read(MINI / "pages" / "route-detail" / "route-detail.js")
    route_guide_wxml = _read(MINI / "pages" / "route-detail" / "route-detail.wxml")
    route_book_js = _read(MINI / "pages" / "route-book-detail" / "route-book-detail.js")
    route_book_wxml = _read(MINI / "pages" / "route-book-detail" / "route-book-detail.wxml")
    upload_js = _read(MINI / "pages" / "upload" / "upload.js")
    upload_wxml = _read(MINI / "pages" / "upload" / "upload.wxml")

    assert "onOpenRouteMapPage" in route_guide_js
    assert "onDownloadRouteExport" in route_guide_js
    assert "onOpenRouteMapPage" in route_book_js
    assert "onDownloadRouteExport" in route_book_js
    assert "onStartMeetup" not in route_guide_js + route_book_js
    assert "约骑" not in route_guide_wxml + route_book_wxml

    assert "/api/activities/upload" in upload_js
    assert "pollStatus" in upload_js
    assert "buildScoreCard" in upload_js
    assert "查看骑行详情" in upload_wxml
    assert "/api/meetups" not in upload_js
    assert "meetupBannerVisible" not in upload_js + upload_wxml


def test_registered_pages_and_static_assets_still_exist():
    app_json = json.loads(_read(MINI / "app.json"))

    for page in app_json["pages"]:
        page_path = MINI / page
        for suffix in (".js", ".json", ".wxml", ".wxss"):
            assert page_path.with_suffix(suffix).exists(), f"{page}{suffix} 缺失"

    for item in app_json["tabBar"]["list"]:
        assert (MINI / item["iconPath"]).exists()
        assert (MINI / item["selectedIconPath"]).exists()

    asset_ref = re.compile(r'src="/(assets/[^"]+)"')
    for wxml_path in MINI.rglob("*.wxml"):
        for ref in asset_ref.findall(_read(wxml_path)):
            assert (MINI / ref).exists(), f"{wxml_path} 引用了不存在的 /{ref}"


def test_route_map_markers_keep_wechat_required_dimensions():
    for page in ("route-detail", "route-book-detail"):
        js = _read(MINI / "pages" / page / f"{page}.js")
        for title in ("起点", "终点"):
            marker = re.search(
                r"\{[^{}]*width:\s*18[^{}]*height:\s*18[^{}]*title:\s*'"
                + title
                + r"'[^{}]*\}",
                js,
            )
            assert marker, f"{page} 的{title} marker 缺少微信地图要求的 18x18 尺寸"


def test_route_detail_uses_free_paper_canvas_for_display_route_map():
    js = _read(MINI / "pages" / "route-detail" / "route-detail.js")
    wxml = _read(MINI / "pages" / "route-detail" / "route-detail.wxml")
    wxss = _read(MINI / "pages" / "route-detail" / "route-detail.wxss")

    assert "require('../../utils/route-thumb')" in js
    assert "drawRoutePreviewThumb" in js
    assert "require('../../utils/route-map-nav')" in js
    assert "onOpenRouteMapPage" in js
    assert "routeMapOverlayVisible" not in js
    display_block = _block_after(wxml, 'class="route-map-wrap"')
    assert "<map" not in display_block
    assert "route-map-overlay" not in wxml
    assert 'canvas-id="route-paper-preview"' in wxml
    assert 'bindtap="onOpenRouteMapPage"' in wxml
    assert ".route-paper-canvas" in wxss
    assert ".route-map-overlay" not in wxss


def test_route_detail_export_flow_has_clear_fallback_actions():
    js = _read(MINI / "pages" / "route-detail" / "route-detail.js")
    wxml = _read(MINI / "pages" / "route-detail" / "route-detail.wxml")
    api = _read(MINI / "utils" / "api.js")

    assert "promptShareExportFile" not in js
    assert "lastExportDownloadUrl" in js
    assert "onCopyLastExportLink" in js
    assert "showExportSendFallback" in js
    assert "复制下载链接" in wxml
    assert "尝试发送微信" not in wxml
    assert wxml.index("复制下载链接") < wxml.index("发送到微信")
    assert "先生成路线文件" in wxml
    assert "两步导入" in wxml
    assert "wx.env.USER_DATA_PATH" in api
    assert "saveDownloadedFile" in api
    assert "tempFilePath: tempFilePath" in api
    assert "savedFilePath: savedFilePath" in api
    assert "filePath: savedFilePath || tempFilePath" in api
    assert "lastExportSavedPath || this.data.lastExportTempPath" in js
    assert "开发者工具不支持发送文件，请用真机测试" in api
    assert "wx.getFileSystemManager" in api
    assert "err && err.errMsg" in api


def test_shared_paper_map_theme_exists_and_documents_paid_style_lesson():
    theme_path = MINI / "utils" / "map-theme.js"
    theme = _read(theme_path)

    assert "PAPER_MAP_CONFIG" in theme
    assert "buildRoutePreviewPolylines" in theme
    # 个性化底图机器已拆除（付费能力未购买，挂上 = 真机鉴权卡死）
    assert "getPaperMapData" not in theme
    assert "buildHeatmapPolyline" not in theme
    # 教训必须留在文件头：subkey 是先购买再使用的付费能力，防未来 agent 重新接上
    assert "付费" in theme
    assert "TENCENT_MAP_SK" not in theme


def test_shared_paper_map_theme_builds_orange_route_polylines():
    script = """
const assert = require('assert')
const mapTheme = require('./miniprogram/utils/map-theme')

assert.deepStrictEqual(mapTheme.buildRoutePreviewPolylines([]), [])
assert.deepStrictEqual(mapTheme.buildRoutePreviewPolylines([{ latitude: 1, longitude: 2 }]), [])

const lines = mapTheme.buildRoutePreviewPolylines([
  { latitude: 37.8, longitude: 112.5 },
  { latitude: 37.9, longitude: 112.6 },
])
assert.strictEqual(lines.length, 1)
assert.strictEqual(lines[0].color, '#FF9500')
assert.strictEqual(lines[0].points.length, 2)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_route_thumb_drawing_really_executes_and_draws_lines():
    # 回归锚（2026-06-13 全地图白屏事故）：drawRouteThumb 曾先把点归一化成 {x,y}
    # 再传给 projectTracks，后者二次归一化只认 [lon,lat] / {latitude,longitude}，
    # {x,y} 全被当非法点丢弃 → 所有路线缩略图静默画空白。字符串断言测不出执行层
    # 断裂——本测试用 wx 桩真跑绘制链路，断言"真画了线"。
    script = """
const assert = require('assert')
const calls = {}
function rec(name) { return function () { calls[name] = (calls[name] || 0) + 1 } }
global.wx = {
  createCanvasContext: function () {
    return {
      setFillStyle: rec('setFillStyle'), fillRect: rec('fillRect'),
      setStrokeStyle: rec('setStrokeStyle'), setLineWidth: rec('setLineWidth'),
      beginPath: rec('beginPath'), moveTo: rec('moveTo'), lineTo: rec('lineTo'),
      quadraticCurveTo: rec('quad'), stroke: rec('stroke'), arc: rec('arc'),
      fill: rec('fill'), setLineCap: rec('cap'), setLineJoin: rec('join'),
      clearRect: rec('clearRect'), draw: rec('draw'),
    }
  },
}
const rt = require('./miniprogram/utils/route-thumb')

// 后端原始格式 [[lon, lat], ...]（preview_points / track-thumbs 都是这个）
const pts = []
for (let i = 0; i < 40; i++) pts.push([112.5 + i * 0.001, 37.8 + Math.sin(i / 5) * 0.01])
assert.strictEqual(rt.drawRouteThumb('a', pts, { width: 320, height: 180, lineWidth: 4, paper: true }), true)

// buildRoutePreview 转换后格式 [{latitude, longitude}, ...]
const objPts = pts.map(p => ({ latitude: p[1], longitude: p[0] }))
assert.strictEqual(rt.drawRouteThumb('b', objPts, { width: 70, height: 70, lineWidth: 2 }), true)

// 真画了线 + 真提交了绘制
assert.ok(calls.lineTo > 40, 'lineTo 调用次数过少: ' + calls.lineTo)
assert.strictEqual(calls.draw, 2)

// 点不够时如实返回 false（调用方据此隐藏画布）
assert.strictEqual(rt.drawRouteThumb('d', [[112.5, 37.8]], { width: 70, height: 70 }), false)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_no_wrong_method_jumps_to_tabbar_pages():
    # 红线守卫（2026-06-13 全模块走查实证）：微信硬规则——wx.navigateTo / wx.redirectTo /
    # navigator 默认 open-type 都不能跳 tabBar 页，调用静默 fail、页面纹丝不动。
    # 实锤过的翻车：settings 退出登录后卡死原页 ×4 / home 登录按钮点了没反应 /
    # 战报"交卷"跳不进上传页。tabBar 页只能 wx.switchTab（且带不了 url 参数，
    # 上下文走 globalData 寄存柜约定）。
    app_json = json.loads(_read(MINI / "app.json"))
    tab_paths = {item["pagePath"] for item in app_json["tabBar"]["list"]}

    js_jump = re.compile(r"wx\.(navigateTo|redirectTo)\(\s*\{\s*url:\s*['\"]([^'\"]+)['\"]")
    for js_path in MINI.rglob("*.js"):
        for m in js_jump.finditer(_read(js_path)):
            target = m.group(2).lstrip("/").split("?")[0]
            assert target not in tab_paths, (
                f"{js_path}: wx.{m.group(1)} 跳 tabBar 页 {target} 会静默 fail，必须 wx.switchTab"
            )

    navigator_tag = re.compile(r"<navigator[^>]*url=\"([^\"]+)\"[^>]*>")
    for wxml_path in MINI.rglob("*.wxml"):
        for m in navigator_tag.finditer(_read(wxml_path)):
            target = m.group(1).lstrip("/").split("?")[0]
            if target in tab_paths:
                assert 'open-type="switchTab"' in m.group(0), (
                    f"{wxml_path}: navigator 指向 tabBar 页 {target} 缺 open-type=\"switchTab\""
                )


def test_no_wxml_in_whole_project_uses_paid_personalized_map_style():
    # 红线守卫：微信小程序个性化底图（subkey + layer-style）自 2023-06-29 起是
    # "先购买再使用"的付费能力，velo 未购买——任何 <map> 挂上这两个属性，
    # 真机鉴权必失败、地图卡死（2026-06-12 事故，codex 多轮代码修复全部无效）。
    # 这条测试把教训变成结构约束：全工程 wxml 永远不许再出现这两个属性。
    for wxml_path in MINI.rglob("*.wxml"):
        wxml = _read(wxml_path)
        assert "subkey" not in wxml, f"{wxml_path} 使用了付费个性化底图 subkey"
        assert "layer-style" not in wxml, f"{wxml_path} 使用了付费个性化底图 layer-style"


def test_miniprogram_runtime_does_not_commit_local_qa_api_origin():
    app_js = _read(MINI / "app.js")
    api_js = _read(MINI / "utils" / "api.js")

    assert "baseUrl: 'https://api.weiluai.top'" in app_js
    assert "var BASE_URL = 'https://api.weiluai.top'" in api_js
    assert "127.0.0.1:18001" not in app_js
    assert "127.0.0.1:18001" not in api_js


def test_heatmap_card_uses_one_interactive_native_map_and_opens_fullscreen():
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")
    wxml = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxml")
    wxss = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxss")

    assert "require('../../utils/heatmap-map')" in js
    assert "require('../../utils/heatmap-protocol')" in js
    assert "require('../../utils/heatmap-tile-cache')" in js
    assert "detail: 'meta'" in js
    assert "detail: 'card'" in js
    assert "buildHeatmapMetaModel" in js
    assert "detail: 'viewport'" in js
    assert "gcj02ToWgs84" in js
    assert "this._preferVectorLayer = isDeveloperTools()" in js
    assert "_vectorRequestViewport" in js
    assert "vectorBlockSize = gridZoom >= 16 || gridZoom <= 13 ? 8 : 4" in js
    assert "opacity: HEATMAP_LINE_OPACITY" in js
    assert "&v=" in js
    assert "limitTrackPoints(" not in js
    assert "buildPolylines" in js
    assert "downloadTemporaryFile" in js
    assert "addGroundOverlay" in js
    assert "removeGroundOverlay" in js
    assert "complete: function (result)" in js
    assert "var id = idSeed" in js
    assert "wx.navigateTo" in js
    assert "/pages/heatmap/heatmap" in js
    assert wxml.count("<map") == 1
    assert "<canvas" not in wxml
    assert 'polyline="{{polylines}}"' in wxml
    assert 'include-points="{{includePoints}}"' in wxml
    assert 'enable-scroll="{{true}}"' in wxml
    assert 'enable-zoom="{{true}}"' in wxml
    assert "全屏查看" in wxml
    assert "height: 480rpx" in wxss


def test_heatmap_card_vector_fallback_renders_current_raw_viewport():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    return Promise.resolve({
      tracks: [[[112.50, 37.80], [112.51, 37.82], [112.52, 37.80]]]
    })
  }
} }
let componentDefinition = null
global.Component = function (definition) { componentDefinition = definition }
global.wx = {}
require('./miniprogram/components/heatmap-card/heatmap-card')

const component = Object.assign({}, componentDefinition.methods, {
  _componentAlive: true,
  data: Object.assign({}, componentDefinition.data, { userId: 0 }),
  setData: function (update) { Object.assign(this.data, update) },
})
const viewport = {
  west: 112.4, south: 37.7, east: 112.7, north: 38.0, zoom: 11,
  mapWest: 112.4, mapSouth: 37.7, mapEast: 112.7, mapNorth: 38.0,
}

;(async function () {
  component._preferVectorLayer = true
  const visibleCount = component._vectorRequestViewports(viewport).length
  component._fetchViewport(viewport)
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(calls.length, visibleCount)
  assert.strictEqual(calls[0].params.detail, 'viewport')
  assert.strictEqual(calls[0].params.zoom, 13)
  assert.strictEqual(component.data.tileError, false)
  assert.strictEqual(component.data.polylines.length, visibleCount)
  assert.strictEqual(component.data.polylines[0].points.length, 3)
  assert.strictEqual(component.data.polylines[0].color, '#FF6B00C8')
  component._fetchViewport(Object.assign({}, viewport, {
    west: 112.401, south: 37.701, east: 112.701, north: 38.001,
    mapWest: 112.401, mapSouth: 37.701, mapEast: 112.701, mapNorth: 38.001,
  }))
  await new Promise(setImmediate)
  assert.strictEqual(calls.length, visibleCount)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_red_stays_strong_and_fractional_zoom_keeps_existing_frame():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
require.cache[apiPath] = { exports: {
  get: function () {
    return Promise.resolve({
      tracks: [[[112.50, 37.80], [112.51, 37.82], [112.52, 37.80]]]
    })
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _preferVectorLayer: true,
  _metadataLoaded: true,
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red' }),
  setData: function (update) { Object.assign(this.data, update) },
  _scheduleViewportRefresh: function (delay) { this._scheduledDelay = delay },
})
const viewport = {
  west: 112.4, south: 37.7, east: 112.7, north: 38.0, zoom: 10,
  mapWest: 112.4, mapSouth: 37.7, mapEast: 112.7, mapNorth: 38.0,
}

;(async function () {
  page._refreshVectorLayer(viewport)
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page.data.polylines[0].color, '#FF174FC8')
  assert.strictEqual(page._lastVectorZoom, 12)
  const previousPolylines = page.data.polylines
  const previousKey = page._lastVectorSetKey

  page.onMapRegionChange({ type: 'end', causedBy: 'scale', detail: { scale: 10.3 } })
  assert.strictEqual(page.data.polylines, previousPolylines)
  assert.strictEqual(page.data.updating, false)
  assert.strictEqual(page._lastVectorZoom, 12)
  assert.strictEqual(page._lastVectorSetKey, previousKey)
  assert.strictEqual(page._scheduledDelay, 0)

  page._refreshVectorLayer(Object.assign({}, viewport, { scale: 10.3 }))
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page.data.polylines[0].color, '#FF174FC8')
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_vector_view_uses_composable_fixed_blocks_across_pan_boundary():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition)
const zoom = 16
const count = Math.pow(2, zoom)
const blockX = 53240
const blockY = 25200
const lon = function (x) { return x / count * 360 - 180 }
const lat = function (y) {
  const mercator = Math.PI * (1 - 2 * y / count)
  return Math.atan(Math.sinh(mercator)) * 180 / Math.PI
}
const base = {
  west: 112.4, south: 37.7, east: 112.7, north: 38.0, zoom: zoom,
  mapWest: lon(blockX + 1.1), mapEast: lon(blockX + 7.5),
  mapNorth: lat(blockY + 1.1), mapSouth: lat(blockY + 7.5),
}
const first = page._vectorRequestViewports(base)
const crossed = page._vectorRequestViewports(Object.assign({}, base, {
  mapWest: lon(blockX + 7.5),
  mapEast: lon(blockX + 9.5),
}))
assert.strictEqual(first.length, 1)
assert.strictEqual(crossed.length, 2)
assert.strictEqual(crossed[0].key, first[0].key)
assert.strictEqual(crossed[0].maxX - crossed[0].minX + 1, 8)
assert.strictEqual(crossed[1].minX, crossed[0].maxX + 1)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_vector_pan_keeps_old_frame_until_missing_block_is_ready_then_appends():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
const resolvers = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    return new Promise(function (resolve) { resolvers.push(resolve) })
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _preferVectorLayer: true,
  _metadataLoaded: true,
  _heatmapCacheVersion: 'g12-double-buffer',
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red' }),
  setData: function (update) {
    if (Object.prototype.hasOwnProperty.call(update, 'polylines')) {
      this._polylineWrites = (this._polylineWrites || 0) + 1
    }
    Object.assign(this.data, update)
  },
  _prefetchVectorNeighbors: function () {},
})
const zoom = 16
const count = Math.pow(2, zoom)
const blockX = 53240
const blockY = 25200
const lon = function (x) { return x / count * 360 - 180 }
const lat = function (y) {
  const mercator = Math.PI * (1 - 2 * y / count)
  return Math.atan(Math.sinh(mercator)) * 180 / Math.PI
}
const firstViewport = {
  west: 112.4, south: 37.7, east: 112.7, north: 38.0, zoom: zoom, scale: zoom,
  mapWest: lon(blockX + 1.1), mapEast: lon(blockX + 7.5),
  mapNorth: lat(blockY + 1.1), mapSouth: lat(blockY + 7.5),
}
const crossedViewport = Object.assign({}, firstViewport, {
  mapWest: lon(blockX + 7.5), mapEast: lon(blockX + 9.5),
})

;(async function () {
  page._refreshVectorLayer(firstViewport)
  assert.strictEqual(calls.length, 1)
  resolvers.shift()({ tracks: [[[112.4400, 37.7700], [112.4402, 37.7702]]] })
  await new Promise(setImmediate); await new Promise(setImmediate)
  const oldPolylines = page.data.polylines
  assert.strictEqual(oldPolylines.length, 1)

  page._refreshVectorLayer(crossedViewport)
  assert.strictEqual(calls.length, 2)
  assert.strictEqual(page.data.polylines, oldPolylines)
  assert.strictEqual(page.data.updating, false)

  resolvers.shift()({ tracks: [[[112.4500, 37.7800], [112.4502, 37.7802]]] })
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page.data.polylines.length, 2)
  assert.strictEqual(page.data.polylines[0], oldPolylines[0])
  const writesAfterAppend = page._polylineWrites

  page._refreshVectorLayer(firstViewport)
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page._polylineWrites, writesAfterAppend)
  assert.strictEqual(page.data.polylines.length, 2)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_vector_zoom_switches_only_after_complete_new_lod_is_ready():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
const resolvers = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    return new Promise(function (resolve) { resolvers.push(resolve) })
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _preferVectorLayer: true,
  _metadataLoaded: true,
  _heatmapCacheVersion: 'g13-lod-buffer',
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red' }),
  setData: function (update) { Object.assign(this.data, update) },
  _prefetchVectorNeighbors: function () {},
})
const first = {
  west: 112.437, south: 37.770, east: 112.447, north: 37.785,
  zoom: 16, scale: 16,
  mapWest: 112.443, mapSouth: 37.776, mapEast: 112.453, mapNorth: 37.791,
}

;(async function () {
  const firstCount = page._vectorRequestViewports(first).length
  page._refreshVectorLayer(first)
  for (let index = 0; index < firstCount; index++) {
    resolvers.shift()({ tracks: [[[112.4400, 37.7700], [112.4402, 37.7702]]] })
  }
  await new Promise(setImmediate); await new Promise(setImmediate)
  const oldPolylines = page.data.polylines
  assert.ok(oldPolylines.length > 0)

  const zoomed = Object.assign({}, first, { zoom: 17, scale: 17 })
  const nextCount = page._vectorRequestViewports(zoomed).length
  page._refreshVectorLayer(zoomed)
  assert.strictEqual(page.data.polylines, oldPolylines)
  assert.strictEqual(page.data.updating, false)
  assert.strictEqual(calls.length, firstCount + nextCount)

  for (let index = 0; index < nextCount; index++) {
    resolvers.shift()({ tracks: [[[112.4500, 37.7800], [112.4502, 37.7802]]] })
  }
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page._vectorDisplayFamily, '17:19')
  assert.strictEqual(page.data.polylines.length, nextCount)
  assert.notStrictEqual(page.data.polylines, oldPolylines)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_dense_vector_display_keeps_visible_detail_but_caps_offscreen_frames():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red' }),
  setData: function (update) { Object.assign(this.data, update) },
})
const makeFrame = function (longitude, touched) {
  return {
    family: '16:18',
    preparedTracks: [[
      { longitude: longitude, latitude: 37.8 },
      { longitude: longitude + 0.001, latitude: 37.801 },
    ]],
    pointCount: 14000,
    lineCount: 600,
    touched: touched,
  }
}
page._vectorBlockFrames = {
  visible: makeFrame(112.50, 1),
  near: makeFrame(112.51, 3),
  far: makeFrame(112.52, 2),
}
const viewport = { zoom: 16, scale: 16 }
const visible = [{ key: 'visible', gridZoom: 16, zoom: 18 }]
const prefetched = [
  { key: 'near', gridZoom: 16, zoom: 18 },
  { key: 'far', gridZoom: 16, zoom: 18 },
]

page._renderVectorFrames(visible, viewport, prefetched)
assert.deepStrictEqual(page._vectorDisplayKeys, ['visible', 'near'])
assert.strictEqual(page.data.polylines.length, 2)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_dense_vector_view_prefetches_only_two_neighbors():
    script = """
const assert = require('assert')
global.setTimeout = function (callback) { callback(); return 1 }
global.clearTimeout = function () {}
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const calls = []
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _vectorPrefetchSeq: 0,
  _vectorBlockFrames: {},
  _loadVectorData: function (item) {
    calls.push(item.key)
    return Promise.resolve({ tracks: [] })
  },
  _renderVectorFrames: function () {},
})
const viewport = {
  west: 112.437, south: 37.770, east: 112.447, north: 37.785,
  zoom: 16, scale: 16,
  mapWest: 112.443, mapSouth: 37.776, mapEast: 112.453, mapNorth: 37.791,
}
const visible = page._vectorRequestViewports(viewport)
page._lastVectorSetKey = visible.map(function (item) { return item.key }).join('|')
visible.forEach(function (item) {
  page._vectorBlockFrames[item.key] = {
    family: item.gridZoom + ':' + item.zoom,
    preparedTracks: [],
    pointCount: 18000,
    lineCount: 1001,
    touched: 1,
  }
})

;(async function () {
  page._prefetchVectorNeighbors(visible, viewport)
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(calls.length, 2)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_vector_prefetch_never_competes_with_more_than_two_background_requests():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
const resolvers = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    return new Promise(function (resolve) { resolvers.push(resolve) })
  }
} }
global.setTimeout = function (callback) { callback(); return 1 }
global.clearTimeout = function () {}
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _preferVectorLayer: true,
  _metadataLoaded: true,
  _heatmapCacheVersion: 'g11-data-prefetch-limit',
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red' }),
  setData: function (update) { Object.assign(this.data, update) },
})
const viewport = {
  west: 112.437, south: 37.770, east: 112.447, north: 37.785, zoom: 16,
  mapWest: 112.443, mapSouth: 37.776, mapEast: 112.453, mapNorth: 37.791,
}

;(async function () {
  const visibleCount = page._vectorRequestViewports(viewport).length
  page._refreshVectorLayer(viewport)
  assert.strictEqual(calls.length, visibleCount)
  for (let index = 0; index < visibleCount; index++) {
    resolvers.shift()({ tracks: [[[112.44, 37.77], [112.45, 37.78]]] })
  }
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(calls.length, visibleCount + 2)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_high_zoom_vector_prefetches_neighbor_blocks_and_reuses_session_cache():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    return Promise.resolve({
      tracks: [[[112.4400, 37.7700], [112.4402, 37.7702]]]
    })
  }
} }
global.setTimeout = function (callback) { callback(); return 1 }
global.clearTimeout = function () {}
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _preferVectorLayer: true,
  _metadataLoaded: true,
  _heatmapGeneration: 11,
  _heatmapCacheVersion: 'g11-data-v1',
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red' }),
  setData: function (update) { Object.assign(this.data, update) },
})
const viewport = {
  west: 112.437, south: 37.770, east: 112.447, north: 37.785, zoom: 16,
  mapWest: 112.443, mapSouth: 37.776, mapEast: 112.453, mapNorth: 37.791,
}

;(async function () {
  const visibleCount = page._vectorRequestViewports(viewport).length
  page._refreshVectorLayer(viewport)
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(calls.length, visibleCount + 8)
  const current = page._vectorRequestViewport(viewport)
  const width = current.maxX - current.minX + 1
  const east = page._vectorViewportForTileRange(
    current.gridZoom,
    current.minX + width,
    current.maxX + width,
    current.minY,
    current.maxY,
    current.zoom
  )
  await page._loadVectorData(east)
  assert.strictEqual(calls.length, visibleCount + 8)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_fullscreen_heatmap_has_map_layer_controls_and_real_map_interactions():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "heatmap" / "heatmap.js")
    wxml = _read(MINI / "pages" / "heatmap" / "heatmap.wxml")
    wxss = _read(MINI / "pages" / "heatmap" / "heatmap.wxss")

    assert "pages/heatmap/heatmap" in app_json["pages"]
    assert "detail: 'meta'" in js
    assert "require('../../utils/heatmap-protocol')" in js
    assert "require('../../utils/heatmap-tile-cache')" in js
    assert "detail: 'full'" in js
    assert "available_years" in js
    assert "wx.createMapContext('personal-heatmap-map'" in js
    assert "detail: 'viewport'" in js
    assert "gcj02ToWgs84" in js
    assert "this._preferVectorLayer = isDeveloperTools()" in js
    assert "_vectorRequestViewport" in js
    assert "_prefetchVectorNeighbors" in js
    assert "heatmapTileCache.loadData" in js
    assert "vectorBlockSize = gridZoom >= 16 || gridZoom <= 13 ? 8 : 4" in js
    assert "opacity: HEATMAP_LINE_OPACITY" in js
    assert "data && data.cache_version" in js
    assert "heatmapTileCache.viewerScope()" in js
    assert "heatmapTileCache.audienceScope(this._userId)" in js
    assert "buildPolylines" in js
    assert "getRegion" in js
    assert "getScale" in js
    assert "_viewportRequestSeq" in js
    assert "_showOverviewLayer" not in js
    assert "this._viewportRequestSeq = (this._viewportRequestSeq || 0) + 1" in js
    assert "downloadTemporaryFile" in js
    assert "addGroundOverlay" in js
    assert "removeGroundOverlay" in js
    assert "complete: function (result)" in js
    assert "var id = idSeed" in js
    assert "boundsForTile" in js
    assert "includePoints" in js
    assert "buildHeatmapMetaModel" in js
    assert "MIN_TILE_ZOOM = 3" in js
    assert "VIEWPORT_MAX_POINTS" not in js
    assert 'polyline="{{polylines}}"' in wxml
    assert 'bindregionchange="onMapRegionChange"' in wxml
    assert 'enable-scroll="{{true}}"' in wxml
    assert 'enable-zoom="{{true}}"' in wxml
    assert "常骑区域" in wxml
    assert "全部足迹" in wxml
    assert "热度颜色" in wxml
    assert "yearOptions" in wxml
    assert "height: 100vh" in wxss
    assert "height: 88rpx" in wxss


def test_heatmap_map_model_keeps_one_geographic_space_and_converts_coordinates():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const model = heatmap.buildHeatmapMapModel([
  [[116.30, 39.90], [116.40, 39.95]],
  [[114.00, 22.50], [114.10, 22.55]],
], 'orange', 3)

assert.ok(model)
assert.strictEqual(model.polylines.length, 2)
// 轨迹仍在同一经纬度空间，而不是投影进多个互不相干的小格子。
assert.ok(model.allPoints[1].longitude - model.allPoints[0].longitude > 2)
assert.ok(model.allPoints[1].latitude - model.allPoints[0].latitude > 10)
// 中国境内 WGS-84 已转 GCJ-02，避免真实道路底图上偏移数百米。
assert.notStrictEqual(model.polylines[0].points[0].longitude, 116.30)
assert.notStrictEqual(model.polylines[0].points[0].latitude, 39.90)
assert.strictEqual(model.polylines[0].color, '#FF6B0052')
assert.strictEqual(model.polylines[0].width, 3)
assert.strictEqual(model.polylines[0].level, 'abovebuildings')
assert.strictEqual(model.focusPoints.length, 2)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_meta_model_converts_only_two_bounds_without_building_polylines():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const model = heatmap.buildHeatmapMetaModel(
  [[116.30, 39.90], [116.50, 40.00]],
  [[112.40, 37.60], [121.60, 40.10]]
)

assert.ok(model)
assert.strictEqual(model.focusPoints.length, 2)
assert.strictEqual(model.allPoints.length, 2)
assert.ok(!Object.prototype.hasOwnProperty.call(model, 'polylines'))
assert.notStrictEqual(model.focusPoints[0].longitude, 116.30)
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_card_falls_back_to_legacy_protocol_when_meta_is_unsupported():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    if (params.detail === 'meta') return Promise.reject({ code: 422 })
    return Promise.resolve({
      tracks: [[[112.50, 37.80], [112.51, 37.82], [112.52, 37.80]]],
      activity_count: 1,
    })
  }
} }
let componentDefinition = null
global.Component = function (definition) { componentDefinition = definition }
global.wx = {}
require('./miniprogram/components/heatmap-card/heatmap-card')

const component = Object.assign({}, componentDefinition.methods, {
  _componentAlive: true,
  data: Object.assign({}, componentDefinition.data, { userId: 0 }),
  setData: function (update, callback) {
    Object.assign(this.data, update)
    if (callback) callback()
  },
})

;(async function () {
  component._fetchHeatmap()
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.deepStrictEqual(calls.map((call) => call.params.detail), ['meta', 'card'])
  assert.strictEqual(component._preferVectorLayer, true)
  assert.strictEqual(component.data.error, false)
  assert.strictEqual(component.data.polylines.length, 1)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_fullscreen_heatmap_falls_back_to_legacy_protocol_when_meta_is_unsupported():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const calls = []
require.cache[apiPath] = { exports: {
  get: function (url, params) {
    calls.push({ url: url, params: params })
    if (params.detail === 'meta') return Promise.reject({ code: 422 })
    return Promise.resolve({
      tracks: [[[112.50, 37.80], [112.51, 37.82], [112.52, 37.80]]],
      activity_count: 1,
      available_years: [2026],
    })
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange' }),
  _endpoint: function () { return '/api/user/me/heatmap' },
  _ensureMapContext: function () { return null },
  _scheduleViewportRefresh: function () {},
  setData: function (update, callback) {
    Object.assign(this.data, update)
    if (callback) callback()
  },
})

;(async function () {
  page._fetchHeatmap(null, true)
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.deepStrictEqual(calls.map((call) => call.params.detail), ['meta', 'full'])
  assert.strictEqual(page._preferVectorLayer, true)
  assert.strictEqual(page.data.error, '')
  assert.strictEqual(page.data.polylines.length, 1)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_map_model_caps_render_payload_without_dropping_tracks():
    script = """
const assert = require('assert')
const heatmap = require('./miniprogram/utils/heatmap-map')

const tracks = Array.from({ length: 100 }, (_, trackIndex) =>
  Array.from({ length: 100 }, (_, pointIndex) => [
    116 + trackIndex * 0.001 + pointIndex * 0.0001,
    39 + pointIndex * 0.0001,
  ])
)
const model = heatmap.buildHeatmapMapModel(tracks, 'orange', 3, 1000)
const pointCount = model.polylines.reduce((sum, line) => sum + line.points.length, 0)

assert.strictEqual(model.polylines.length, 100)
assert.ok(pointCount <= 1000)
model.polylines.forEach((line) => assert.ok(line.points.length >= 2))
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_all_zoom_levels_use_tiles_without_overview_polyline_fallback():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const viewports = []
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _refreshTileLayer: function (viewport) { viewports.push(viewport) },
})

page._fetchViewport({ zoom: 3 })
page._fetchViewport({ zoom: 18 })

assert.deepStrictEqual(viewports.map((viewport) => viewport.zoom), [3, 18])
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_last_year_request_wins_and_map_context_waits_for_rendered_map():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const requests = []
require.cache[apiPath] = { exports: {
  get: function () { return new Promise((resolve) => requests.push(resolve)) },
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
let mapContextCreates = 0
global.wx = {
  createMapContext: function () { mapContextCreates += 1; return { id: 'map' } },
}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange' }),
  _endpoint: function () { return '/api/user/me/heatmap' },
  _scheduleViewportRefresh: function () {},
  setData: function (update, callback) {
    Object.assign(this.data, update)
    if (callback) callback()
  },
})

// loading 时 map 尚未挂载，不能提前创建 MapContext。
assert.strictEqual(page._ensureMapContext(), null)
assert.strictEqual(mapContextCreates, 0)
page._pageReady = true

page._fetchHeatmap(2025, false)
page._fetchHeatmap(2024, false)
const response = (year) => ({
  tracks: [],
  activity_count: 1,
  available_years: [2025, 2024],
  selected_year: year,
  focus_points: [[116.4, 39.9], [116.5, 40.0]],
  all_points: [[116.4, 39.9], [116.5, 40.0]],
})

;(async function () {
  requests[1](response(2024))
  await new Promise(setImmediate)
  requests[0](response(2025))
  await new Promise(setImmediate)
  assert.strictEqual(page.data.selectedYear, 2024)
  assert.strictEqual(mapContextCreates, 1)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_tiles_double_buffer_latest_view_and_remove_stale_overlays():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const downloads = []
require.cache[apiPath] = { exports: {
  downloadTemporaryFile: function (url) {
    return new Promise((resolve) => downloads.push({ url: url, resolve: resolve }))
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const removed = []
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
  setData: function (update) { Object.assign(this.data, update) },
  _addGroundOverlay: function (tile, filePath, id) { return Promise.resolve({ tile, filePath, id }) },
  _removeGroundOverlay: function (id) { removed.push(id) },
})
const first = {
  west: 116.2, south: 39.7, east: 116.6, north: 40.1, zoom: 10,
  mapWest: 116.2, mapSouth: 39.7, mapEast: 116.6, mapNorth: 40.1,
}
const latest = {
  west: 121.3, south: 31.0, east: 121.7, north: 31.4, zoom: 10,
  mapWest: 121.3, mapSouth: 31.0, mapEast: 121.7, mapNorth: 31.4,
}

;(async function () {
  page._fetchViewport(first)
  const firstCount = downloads.length
  assert.ok(firstCount > 0)
  page._fetchViewport(latest)
  assert.ok(downloads.length > firstCount)
  downloads.slice(0, firstCount).forEach((request) => request.resolve({ filePath: '/tmp/old.png' }))
  await new Promise(setImmediate); await new Promise(setImmediate)
  // 旧请求完成得再晚也不能复活；其已创建的 overlay 会立即清理。
  assert.ok(removed.length > 0)
  downloads.slice(firstCount).forEach((request) => request.resolve({ filePath: '/tmp/new.png' }))
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.ok(Object.keys(page._activeTileOverlays).length > 0)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_tile_files_reuse_inflight_and_session_cache():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const downloads = []
require.cache[apiPath] = { exports: {
  downloadTemporaryFile: function (url) {
    return new Promise((resolve) => downloads.push({ url: url, resolve: resolve }))
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'red', selectedYear: 2025 }),
})
const tile = { zoom: 12, x: 3328, y: 1582 }
const key = page._tileKey(tile)

;(async function () {
  const first = page._loadTileFile(tile, key)
  const concurrent = page._loadTileFile(tile, key)
  assert.strictEqual(downloads.length, 1)
  downloads[0].resolve({ filePath: '/tmp/tile.png' })
  assert.strictEqual(await first, '/tmp/tile.png')
  assert.strictEqual(await concurrent, '/tmp/tile.png')
  assert.strictEqual(await page._loadTileFile(tile, key), '/tmp/tile.png')
  assert.strictEqual(downloads.length, 1)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_card_and_fullscreen_share_generation_scoped_tile_files():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const downloads = []
require.cache[apiPath] = { exports: {
  downloadTemporaryFile: function (url) {
    return new Promise((resolve) => downloads.push({ url: url, resolve: resolve }))
  }
} }
let pageDefinition = null
let componentDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.Component = function (definition) { componentDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')
require('./miniprogram/components/heatmap-card/heatmap-card')

const page = Object.assign({}, pageDefinition, {
  _userId: 42,
  _heatmapGeneration: 7,
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
})
const card = Object.assign({}, componentDefinition.methods, {
  _heatmapGeneration: 7,
  data: Object.assign({}, componentDefinition.data, { userId: 42 }),
})
const tile = { zoom: 12, x: 3328, y: 1582 }

;(async function () {
  const pageKey = page._tileKey(tile)
  const cardKey = card._tileKey(tile)
  assert.strictEqual(pageKey, cardKey)
  const pageRequest = page._loadTileFile(tile, pageKey)
  const cardRequest = card._loadTileFile(tile, cardKey)
  assert.strictEqual(downloads.length, 1)
  assert.ok(downloads[0].url.includes('v=g7'))
  downloads[0].resolve({ filePath: '/tmp/shared-g7.png' })
  assert.strictEqual(await pageRequest, '/tmp/shared-g7.png')
  assert.strictEqual(await cardRequest, '/tmp/shared-g7.png')

  card._heatmapGeneration = 8
  const nextKey = card._tileKey(tile)
  assert.notStrictEqual(nextKey, cardKey)
  const nextRequest = card._loadTileFile(tile, nextKey)
  assert.strictEqual(downloads.length, 2)
  assert.ok(downloads[1].url.includes('v=g8'))
  downloads[1].resolve({ filePath: '/tmp/shared-g8.png' })
  assert.strictEqual(await nextRequest, '/tmp/shared-g8.png')
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_tile_cache_is_partitioned_by_viewer_and_cleared_on_logout():
    script = """
const assert = require('assert')
const cache = require('./miniprogram/utils/heatmap-tile-cache')
let session = { userId: 42, token: 'owner-token' }
global.getApp = function () { return { globalData: session } }

const ownerKey = [cache.viewerScope(), cache.userScope(42), cache.audienceScope(42), 'tile'].join(':')
session = { userId: 99, token: 'viewer-token' }
const publicKey = [cache.viewerScope(), cache.userScope(42), cache.audienceScope(42), 'tile'].join(':')
assert.notStrictEqual(ownerKey, publicKey)
assert.ok(ownerKey.includes('viewer-42:user-42:audience-owner'))
assert.ok(publicKey.includes('viewer-99:user-42:audience-public'))

let loads = 0
;(async function () {
  assert.strictEqual(await cache.load(ownerKey, function () {
    loads += 1
    return { filePath: '/tmp/owner-private.png' }
  }), '/tmp/owner-private.png')
  assert.strictEqual(await cache.load(publicKey, function () {
    loads += 1
    return { filePath: '/tmp/public.png' }
  }), '/tmp/public.png')
  assert.strictEqual(loads, 2)
  cache.clearAll()
  await cache.load(publicKey, function () {
    loads += 1
    return { filePath: '/tmp/public-new-session.png' }
  })
  assert.strictEqual(loads, 3)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_logout_and_401_clear_heatmap_tile_cache():
    app_js = _read(MINI / "app.js")
    api_js = _read(MINI / "utils" / "api.js")

    assert "heatmapTileCache.clearAll()" in app_js
    assert "function clearExpiredAuth(app)" in api_js
    assert "heatmapTileCache.clearAll()" in api_js


def test_heatmap_partial_tile_frame_keeps_previous_complete_tiles_and_retries():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const downloads = []
require.cache[apiPath] = { exports: {
  downloadTemporaryFile: function (url) {
    return new Promise((resolve, reject) => downloads.push({ url, resolve, reject }))
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const removed = []
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  data: Object.assign({}, pageDefinition.data, {
    selectedColor: 'orange', selectedYear: null,
  }),
  setData: function (update) { Object.assign(this.data, update) },
  _addGroundOverlay: function () { return Promise.resolve() },
  _removeGroundOverlay: function (id) { removed.push(id) },
  _activeTileOverlays: { stale: { key: 'stale', id: 77 } },
  _tileLayerVisible: true,
})
const viewport = {
  west: 116.2, south: 39.7, east: 116.6, north: 40.1, zoom: 10,
  mapWest: 116.2, mapSouth: 39.7, mapEast: 116.6, mapNorth: 40.1,
}

;(async function () {
  page._fetchViewport(viewport)
  const firstCount = downloads.length
  assert.ok(firstCount > 1)
  downloads[0].resolve({ filePath: '/tmp/one.png' })
  downloads.slice(1).forEach((request) => request.reject(new Error('network')))
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page._lastTileSetKey, '')
  assert.deepStrictEqual(Object.keys(page._activeTileOverlays || {}), ['stale'])
  assert.strictEqual(removed.length, 1)

  page._fetchViewport(viewport)
  const retry = downloads.slice(firstCount)
  assert.strictEqual(retry.length, firstCount - 1)
  retry.forEach((request, index) => request.resolve({ filePath: '/tmp/retry-' + index + '.png' }))
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.deepStrictEqual(page.data.polylines, [])
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_partial_initial_tile_frame_falls_back_instead_of_staying_blank():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const downloads = []
require.cache[apiPath] = { exports: {
  downloadTemporaryFile: function (url) {
    return new Promise((resolve, reject) => downloads.push({ url, resolve, reject }))
  }
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

let vectorFallbacks = 0
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  data: Object.assign({}, pageDefinition.data, {
    selectedColor: 'orange', selectedYear: null,
  }),
  setData: function (update) { Object.assign(this.data, update) },
  _addGroundOverlay: function () { return Promise.resolve() },
  _removeGroundOverlay: function () {},
  _refreshVectorLayer: function () { vectorFallbacks += 1 },
})
const viewport = {
  west: 116.2, south: 39.7, east: 116.6, north: 40.1, zoom: 10,
  mapWest: 116.2, mapSouth: 39.7, mapEast: 116.6, mapNorth: 40.1,
}

;(async function () {
  page._fetchViewport(viewport)
  assert.ok(downloads.length > 1)
  downloads[0].resolve({ filePath: '/tmp/one.png' })
  downloads.slice(1).forEach((request) => request.reject(new Error('network')))
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(page._preferVectorLayer, true)
  assert.strictEqual(vectorFallbacks, 1)
  assert.deepStrictEqual(Object.keys(page._activeTileOverlays || {}), [])
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_viewport_read_generation_keeps_newest_async_map_region():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const reads = []
const fetched = []
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _metadataLoaded: true,
  _ensureMapContext: function () { return {} },
  _readViewport: function () {
    return new Promise((resolve) => reads.push(resolve))
  },
  _fetchViewport: function (viewport) { fetched.push(viewport) },
})
const older = { west: 116.1, south: 39.7, east: 116.5, north: 40.1, zoom: 10 }
const newest = { west: 116.3, south: 39.7, east: 116.7, north: 40.1, zoom: 10 }

;(async function () {
  page._scheduleViewportRefresh(0)
  await new Promise((resolve) => setTimeout(resolve, 5))
  page._scheduleViewportRefresh(0)
  await new Promise((resolve) => setTimeout(resolve, 5))
  reads[1](newest)
  await new Promise(setImmediate)
  reads[0](older)
  await new Promise(setImmediate)
  assert.deepStrictEqual(fetched, [newest])
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_unload_does_not_resurrect_viewport_retry_timer():
    script = """
const assert = require('assert')
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

let resolveRead = null
const page = Object.assign({}, pageDefinition, {
  _pageAlive: true,
  _metadataLoaded: true,
  _ensureMapContext: function () { return {} },
  _readViewport: function () {
    return new Promise((resolve) => { resolveRead = resolve })
  },
})

;(async function () {
  page._scheduleViewportRefresh(0)
  await new Promise((resolve) => setTimeout(resolve, 5))
  page.onUnload()
  resolveRead(null)
  await new Promise(setImmediate)
  assert.strictEqual(page._pageAlive, false)
  assert.strictEqual(page._viewportTimer, null)
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_heatmap_unload_ignores_late_metadata_and_tile_network_responses():
    script = """
const assert = require('assert')
const apiPath = require.resolve('./miniprogram/utils/api')
const requests = []
require.cache[apiPath] = { exports: {
  get: function () { return new Promise((resolve) => requests.push(resolve)) },
  downloadTemporaryFile: function () { return new Promise((resolve) => requests.push(resolve)) },
} }
let pageDefinition = null
global.Page = function (definition) { pageDefinition = definition }
global.wx = {}
require('./miniprogram/pages/heatmap/heatmap')

const page = Object.assign({}, pageDefinition, {
  data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
  _pageAlive: true,
  _endpoint: function () { return '/api/user/me/heatmap' },
  setDataCalls: 0,
  setData: function (update) {
    this.setDataCalls += 1
    Object.assign(this.data, update)
  },
})
const metadataResponse = {
  tracks: [],
  activity_count: 1,
  available_years: [2026],
  focus_points: [[116.4, 39.9], [116.5, 40.0]],
  all_points: [[116.4, 39.9], [116.5, 40.0]],
}

;(async function () {
  page._fetchHeatmap(null, true)
  const callsBeforeUnload = page.setDataCalls
  page.onUnload()
  requests[0](metadataResponse)
  await new Promise(setImmediate)
  assert.strictEqual(page.setDataCalls, callsBeforeUnload)

  const viewportPage = Object.assign({}, pageDefinition, {
    data: Object.assign({}, pageDefinition.data, { selectedColor: 'orange', selectedYear: null }),
    _pageAlive: true,
    _addGroundOverlay: function () { return Promise.resolve() },
    _removeGroundOverlay: function () {},
    setDataCalls: 0,
    setData: function () { this.setDataCalls += 1 },
  })
  viewportPage._fetchViewport({
    west: 116.2, south: 39.7, east: 116.7, north: 40.2, zoom: 10,
    mapWest: 116.2, mapSouth: 39.7, mapEast: 116.7, mapNorth: 40.2,
  })
  const tileRequests = requests.slice(1)
  const tileCallsBeforeUnload = viewportPage.setDataCalls
  viewportPage.onUnload()
  tileRequests.forEach((resolve) => resolve({ filePath: '/tmp/late.png' }))
  await new Promise(setImmediate); await new Promise(setImmediate)
  assert.strictEqual(viewportPage.setDataCalls, tileCallsBeforeUnload)
  assert.deepStrictEqual(viewportPage._activeTileOverlays || {}, {})
})().catch(function (error) { console.error(error); process.exit(1) })
"""

    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_route_map_page_is_registered_and_uses_native_map_without_custom_subkey():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "route-map" / "route-map.js")
    wxml = _read(MINI / "pages" / "route-map" / "route-map.wxml")
    wxss = _read(MINI / "pages" / "route-map" / "route-map.wxss")

    assert "pages/route-map/route-map" in app_json["pages"]
    assert "pendingRouteMap" in js
    assert "onTapBack" in js
    assert "<map" in wxml
    assert "paperMapSubkey" not in wxml
    assert "layer-style" not in wxml
    assert 'polyline="{{polylines}}"' in wxml
    assert "route-map-page" in wxss


def test_route_preview_coordinate_helper_exports_converter():
    coords = _read(MINI / "utils" / "coords.js")

    assert "function wgs84ToGcj02" in coords
    assert "function gcj02ToWgs84" in coords
    assert "module.exports = { wgs84ToGcj02, gcj02ToWgs84 }" in coords
