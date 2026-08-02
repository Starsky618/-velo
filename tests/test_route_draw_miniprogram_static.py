"""Route Draw V0 Task 4：手画路线页小程序静态合同测试。"""

import json
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"
PAGE_DIR = MINI / "pages" / "route-draw"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_route_draw_page_files_are_registered_after_creation():
    app_json = json.loads(_read(MINI / "app.json"))

    assert "pages/route-draw/route-draw" in app_json["pages"]
    for suffix in ("js", "wxml", "wxss", "json"):
        assert (PAGE_DIR / f"route-draw.{suffix}").exists()


def test_route_draw_declares_exact_location_permission():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(PAGE_DIR / "route-draw.js")

    assert app_json["requiredPrivateInfos"] == ["getLocation", "chooseLocation"]
    assert "路线绘制" in app_json["permission"]["scope.userLocation"]["desc"]
    assert "wx.getLocation" in js
    assert "wx.getFuzzyLocation" not in js


def test_route_draw_page_uses_map_tap_as_default_input_and_sketch_only_touch_layer():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert 'bindtap="onMapTap"' in wxml
    assert "onMapTap: function" in js
    assert "mapScrollEnabled: true" in js
    assert 'enable-scroll="{{mapScrollEnabled}}"' in wxml
    assert 'enable-zoom="{{mapScrollEnabled}}"' in wxml
    assert 'setting="{{mapInteractionSettings}}"' in wxml
    assert "enableScroll: Boolean(enabled)" in js
    assert "enableZoom: Boolean(enabled)" in js
    assert 'class="route-draw-touch-layer"' in wxml
    assert 'wx:if="{{showSketchLayer}}"' in wxml
    assert '<canvas' in wxml
    assert 'type="2d"' in wxml
    assert 'id="routeSketchCanvas"' in wxml
    assert 'disable-scroll="{{true}}"' in wxml
    assert "wx.createMapContext('route-draw-map'" in js
    assert ".getRegion" in js
    assert "sketchViewportFromParts" in js
    assert "mapPointFromSketchViewport" in js
    assert ".fromScreenLocation" not in js
    assert "onDrawTouchStart" in js
    assert "onDrawTouchMove" in js
    assert "onDrawTouchEnd" in js
    assert 'catchtouchstart="onDrawTouchStart"' in wxml
    assert 'catchtouchmove="onDrawTouchMove"' in wxml
    assert 'catchtouchend="onDrawTouchEnd"' in wxml
    assert "onTapStartSketch" in js


def test_route_draw_can_search_and_center_an_exact_location():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert 'catchtap="onTapSearchLocation"' in wxml
    assert "搜地点" in wxml
    assert "onTapSearchLocation: function" in js
    assert "wx.chooseLocation" in js
    assert "直接点地图设置路线点" in js


def test_route_draw_removes_center_crosshair_and_add_center_fallback():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    wxss = _read(PAGE_DIR / "route-draw.wxss")

    assert 'bindregionchange="onMapRegionChange"' in wxml
    assert 'class="route-draw-crosshair"' not in wxml
    assert 'class="center-add-button' not in wxml
    assert 'bindtap="onTapAddCenterPoint"' not in wxml
    assert "onTapAddCenterPoint: function" not in js
    assert "readMapCenterPoint: function" not in js
    assert ".getCenterLocation" not in js
    assert "route-draw-crosshair" not in wxss
    assert "center-add-button" not in wxss


def test_route_draw_page_keeps_full_route_state_off_the_view_data_bridge():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert "builderMode: 'smart'" in js
    assert "requestStatus: 'idle'" in js
    assert "_routeActions" in js
    assert "_routePending" in js
    assert "actionCount: 0" in js
    assert "routeDraft" not in js
    assert "confirmedSegments" not in js
    assert "MAX_DISPLAY_POINTS = 500" in js
    assert "simplifyForDisplay" in js
    assert "_confirmedPoints" in js
    assert "currentRawPoints" in js
    assert "previewPoints" in js
    assert "markers" in js
    assert "buildDrawPolylines" in js
    assert "confirmedPolyline" in js
    assert "rawPolyline" in js
    assert "previewPolyline" in js
    assert "Manual Mode" not in wxml
    assert "onTapToggleManualMode" not in js
    assert "确认当前段" not in wxml
    assert "自由画线" not in wxml
    assert "segmentReady" not in js


def test_route_draw_bottom_sheet_has_live_elevation_states_without_activity_selector():
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert "运动类型" not in wxml
    assert "保存后生成海拔图" not in wxml
    assert "累计爬升" in wxml
    assert "海拔曲线" in wxml
    assert 'id="routeElevationCanvas"' in wxml
    assert "elevationStatus === 'loading'" in wxml
    assert "onTapRetryElevation" in wxml


def test_first_map_tap_sets_start_marker_without_snap_request():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    map_tap_block = js.split("onMapTap: function", 1)[1].split("onTapToggleManualMode", 1)[0]
    add_point_block = js.split("addRoutePoint: function", 1)[1].split("\n  startSnapPreview: function", 1)[0]
    anchor_block = js.split("commitAnchorAction: function", 1)[1].split("commitSegmentAction", 1)[0]

    assert "this.addRoutePoint(point)" in map_tap_block
    assert "this.commitAnchorAction(normalized)" in add_point_block
    assert "api.snapManualDrawnRoute" not in add_point_block
    assert "api.snapManualDrawnRoute" not in anchor_block
    assert "actions.push({ kind: 'anchor', point: point })" in anchor_block
    assert 'markers="{{markers}}"' in wxml
    assert "buildMarkers" in js


def test_second_smart_map_tap_snaps_and_auto_merges_draft_segment():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    add_point_block = js.split("addRoutePoint: function", 1)[1].split("\n  startSnapPreview: function", 1)[0]
    snap_block = js.split("startSnapPreview: function", 1)[1].split("onTapStartSketch", 1)[0]
    success_block = snap_block.split("api.snapManualDrawnRoute", 1)[1].split(".catch", 1)[0]

    assert "this.startSnapPreview([lastPoint, normalized])" in add_point_block
    assert "mode: 'snap'" in snap_block
    assert "points: simplifyForSnap(raw)" in snap_block
    assert "commitSegmentAction" in success_block
    assert "result.requires_confirmation" in success_block
    assert "requestStatus: 'confirming'" in success_block
    assert "onTapAcceptDetour" in js
    assert "onTapConfirmSegment" not in js
    assert "确认当前段" not in wxml


def test_first_marker_moves_to_the_confirmed_snapped_start():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                global.Page = function () {}
                const helpers = require('./miniprogram/pages/route-draw/route-draw.js')
                const markers = helpers.buildMarkers([
                  { kind: 'anchor', point: [112.5, 37.8] },
                  {
                    kind: 'segment',
                    mode: 'snap',
                    rawPoints: [[112.5, 37.8], [112.6, 37.9]],
                    points: [[112.5003, 37.8002], [112.6, 37.9]],
                    warnings: [],
                  },
                ])
                process.stdout.write(JSON.stringify(markers))
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    markers = json.loads(result.stdout)

    assert [markers[0]["longitude"], markers[0]["latitude"]] == [112.5003, 37.8002]
    assert markers[0]["callout"]["content"] == "起点"
    assert markers[-1]["callout"]["content"] == "终点"


def test_route_draw_uses_centered_circle_assets_instead_of_offset_labels_or_default_pins():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                global.Page = function () {}
                const helpers = require('./miniprogram/pages/route-draw/route-draw.js')
                const markers = helpers.buildMarkers([
                  { kind: 'anchor', point: [112.5, 37.8] },
                  {
                    kind: 'segment',
                    mode: 'snap',
                    points: [[112.5, 37.8], [112.55, 37.85]],
                    rawPoints: [[112.5, 37.8], [112.55, 37.85]],
                    warnings: [],
                  },
                ])
                process.stdout.write(JSON.stringify(markers))
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    markers = json.loads(result.stdout)

    assert len(markers) == 2
    assert markers[0]["iconPath"] == "/assets/route-marker-start.png"
    assert markers[-1]["iconPath"] == "/assets/route-marker-end.png"
    assert all(marker["width"] == 20 and marker["height"] == 20 for marker in markers)
    assert all(marker["anchor"] == {"x": 0.5, "y": 0.5} for marker in markers)
    assert all("label" not in marker for marker in markers)
    for asset in ("route-marker-start.png", "route-marker-waypoint.png", "route-marker-end.png"):
        assert (MINI / "assets" / asset).exists()


def test_route_draw_exposes_smart_tap_and_true_manual_pencil_modes():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    api_js = _read(MINI / "utils" / "api.js")
    wxss = _read(PAGE_DIR / "route-draw.wxss")
    metadata_block = js.split("function buildDrawMetadata", 1)[1].split("function screenPointFromEvent", 1)[0]

    assert "Manual Mode" not in wxml
    assert "builderMode === 'manual'" not in js
    assert 'catchtap="onTapStartSketch"' in wxml
    assert "this.startSnapPreview([lastPoint, normalized])" in js
    assert "this.startSnapPreview(raw, 'freehand')" not in js
    assert "supports_detour_confirmation" not in js
    assert "'X-VELO-Detour-Confirmation': '1'" in api_js
    assert "mode: 'freehand'" in js
    assert 'bindtap="onTapAcceptDetour"' in wxml
    assert 'bindtap="onTapSketchDetour"' in wxml
    assert ">手绘这一小段</button>" in wxml
    assert "freehand_segment_count" in metadata_block
    assert "snap_provider: freehandCount === modes.length ? 'freehand' : 'tencent_bicycling'" in metadata_block
    assert "mode: 'manual'" not in js
    assert "手绘会保留原线，不再自动绕路" in wxml
    assert "松手后会自动贴到可骑行道路" not in wxml
    detour_button_block = wxss.split(".detour-button {", 1)[1].split("}", 1)[0]
    assert "min-height: 44px" in detour_button_block


def test_sketch_pencil_temporarily_takes_over_touch_and_then_restores_map():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    start_block = js.split("onTapStartSketch: function", 1)[1].split("onDrawTouchStart", 1)[0]
    finish_block = js.split("finishSketchSegment: function", 1)[1].split("onTapUndoAction", 1)[0]

    assert 'wx:if="{{showSketchLayer}}"' in wxml
    assert "builderMode: 'sketch'" in start_block
    assert "showSketchLayer: false" in start_block
    assert "mapScrollEnabled: false" in start_block
    assert "wx.nextTick" in start_block
    assert "revealSketchLayer" in start_block
    assert "restoreSketchMapPosition" in js
    assert ".moveToLocation" not in start_block
    assert "prepareSketchViewport" in js
    assert "prepareSketchCanvas" in js
    assert "drawSketchInkPoint" in js
    assert "mapPointFromSketchViewport" in js
    assert "sketchViewportReady" in js
    assert "showSketchLayer: false" in finish_block
    assert "mapScrollEnabled: true" in finish_block
    assert "SKETCH_AUTO_FINISH_MS" in js
    assert "SKETCH_PREPARE_TIMEOUT_MS" in js
    assert "armSketchAutoFinish: function" in js
    assert "clearSketchAutoFinish: function" in js
    assert "this.armSketchAutoFinish()" in js
    assert "this.clearSketchAutoFinish()" in js
    assert "fromScreenLocation" not in js


def test_sketch_draws_in_screen_space_without_rerendering_the_native_map_on_every_move():
    js = _read(PAGE_DIR / "route-draw.js")
    start_block = js.split("onDrawTouchStart: function", 1)[1].split("onDrawTouchMove", 1)[0]
    move_block = js.split("onDrawTouchMove: function", 1)[1].split("onDrawTouchEnd", 1)[0]
    capture_block = js.split("captureTouchLocation: function", 1)[1].split("finishSketchSegment", 1)[0]
    finish_block = js.split("finishSketchSegment: function", 1)[1].split("finishSketchMode", 1)[0]

    assert "applyDraftState" not in start_block
    assert "setData" not in move_block
    assert "drawSketchInkPoint" in capture_block
    assert "buildDrawPolylines" not in capture_block
    assert "mapPointFromSketchViewport" not in capture_block
    assert "screenPoints.map" in finish_block
    assert "mapPointFromSketchViewport" in finish_block
    assert "screenPoints.length < 3" in finish_block
    assert "renderSketchInk" not in js


def test_sketch_tap_does_not_fall_back_to_selecting_a_straight_line_endpoint():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test' } }
                  }
                  global.wx = {
                    createMapContext: function () {
                      return {
                        getRegion: function (options) {
                          options.success({
                            southwest: { longitude: 112.5, latitude: 37.8 },
                            northeast: { longitude: 112.6, latitude: 37.9 },
                          })
                        },
                      }
                    },
                    createSelectorQuery: function () {
                      const query = {
                        in: function () { return query },
                        select: function () {
                          return {
                            boundingClientRect: function (callback) {
                              callback({ left: 0, top: 0, width: 100, height: 100 })
                            },
                          }
                        },
                        exec: function () {},
                      }
                      return query
                    },
                    showToast: function () {},
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  page.onReady()
                  page.commitAnchorAction([112.5, 37.8])
                  await page.onTapStartSketch()
                  page.onDrawTouchStart({ touches: [{ clientX: 10, clientY: 90 }] })
                  page.onDrawTouchEnd({ changedTouches: [{ clientX: 90, clientY: 10 }] })
                  process.stdout.write(JSON.stringify({
                    builderMode: page.data.builderMode,
                    actionCount: page.data.actionCount,
                    confirmedPointCount: page.data.confirmedPointCount,
                    statusText: page.data.statusText,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows == {
        "builderMode": "sketch",
        "actionCount": 1,
        "confirmedPointCount": 1,
        "statusText": "请按住地图并连续拖动画线",
    }


def test_sketch_locks_native_map_one_render_turn_before_showing_touch_layer():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let nextTickCallback = null
                  let patches = []
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test' } }
                  }
                  global.wx = {
                    nextTick: function (callback) { nextTickCallback = callback },
                    createMapContext: function () {
                      return {
                        getRegion: function (options) {
                          options.success({
                            southwest: { longitude: 112.5, latitude: 37.8 },
                            northeast: { longitude: 112.6, latitude: 37.9 },
                          })
                        },
                      }
                    },
                    createSelectorQuery: function () {
                      const query = {
                        in: function () { return query },
                        select: function () {
                          return {
                            boundingClientRect: function (callback) {
                              callback({ left: 0, top: 0, width: 100, height: 100 })
                            },
                          }
                        },
                        exec: function () {},
                      }
                      return query
                    },
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch, callback) {
                      patches.push(patch)
                      this.data = Object.assign({}, this.data, patch)
                      if (callback) callback()
                    },
                  })
                  page.onReady()
                  const startPromise = page.onTapStartSketch()
                  const beforeReveal = {
                    scroll: page.data.mapScrollEnabled,
                    settingScroll: page.data.mapInteractionSettings.enableScroll,
                    settingZoom: page.data.mapInteractionSettings.enableZoom,
                    layer: page.data.showSketchLayer,
                  }
                  nextTickCallback()
                  await startPromise
                  const patchCountBeforeGuard = patches.length
                  page.onMapRegionChange({ type: 'begin', causedBy: 'gesture' })
                  process.stdout.write(JSON.stringify({
                    beforeReveal,
                    afterReveal: {
                      scroll: page.data.mapScrollEnabled,
                      layer: page.data.showSketchLayer,
                      ready: page.data.sketchViewportReady,
                    },
                    guardPatch: patches[patchCountBeforeGuard],
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["beforeReveal"] == {
        "scroll": False,
        "settingScroll": False,
        "settingZoom": False,
        "layer": False,
    }
    assert rows["afterReveal"] == {"scroll": False, "layer": True, "ready": True}
    assert isinstance(rows["guardPatch"]["latitude"], float)
    assert isinstance(rows["guardPatch"]["longitude"], float)


def test_route_draw_undo_is_action_based_and_invalidates_stale_snap_response():
    js = _read(PAGE_DIR / "route-draw.js")
    snap_block = js.split("startSnapPreview: function", 1)[1].split("onTapStartSketch", 1)[0]
    undo_block = js.split("onTapUndoAction: function", 1)[1].split("clearElevationPreviewTimer", 1)[0]

    assert "var snapSeq = this._snapSeq" in snap_block
    assert "if (snapSeq !== that._snapSeq) return" in snap_block
    assert "this._snapSeq = (this._snapSeq || 0) + 1" in undo_block
    assert "actions.pop()" in undo_block
    assert "this._snapSeq = (this._snapSeq || 0) + 1" in undo_block


def test_route_draw_page_blocks_unauthenticated_snap_and_save():
    js = _read(PAGE_DIR / "route-draw.js")

    assert "notLoggedIn" in js
    assert "ensureLoggedIn" in js
    assert "if (!this.ensureLoggedIn()) return" in js
    assert "api.snapManualDrawnRoute" in js
    assert "api.createRouteBookFromManualDrawn" in js
    assert js.index("if (!this.ensureLoggedIn()) return") < js.index("api.snapManualDrawnRoute")
    assert js.index("if (!this.ensureLoggedIn()) return") < js.index("api.createRouteBookFromManualDrawn")


def test_route_draw_save_contract_and_error_copy():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    save_block = js.split("onTapSave: function", 1)[1].split("var name =", 1)[0]

    assert "coordinate_system: 'gcj02'" in js
    assert "draw_metadata" in js
    assert "tool: 'route_draw_v0'" in js
    assert "snap_provider: freehandCount === modes.length ? 'freehand' : 'tencent_bicycling'" in js
    assert "route_book_id" in js
    assert "/pages/route-book-detail/route-book-detail?id=" in js
    assert "/pages/route-detail/route-detail" not in js
    assert "defaultRouteName(new Date())" in js
    assert "先给路线起名" not in js
    assert "路线保存服务还没上线，先更新服务后再试。" in js
    assert "贴路服务还没上线，请更新服务后再试。" in js
    assert "贴路操作太快，稍等一下再继续。" in js
    assert "路线没有保存成功，请稍后再试" in js
    assert "路线太长，分几段保存更稳" in js
    assert "TENCENT_MAP_KEY" not in js
    assert "this.data.requestStatus === 'previewing'" in save_block
    assert "confirmedPoints.length < 2" in save_block
    assert 'disabled="{{!canSaveRoute}}"' in wxml
    assert "点地图设置起点和终点后即可保存" in wxml


def test_saved_route_navigation_failure_does_not_post_a_duplicate_route():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let saveCalls = 0
                  let redirectAttempts = 0
                  let navigateAttempts = 0
                  let toasts = []
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test' } }
                  }
                  global.wx = {
                    showToast: function (options) { toasts.push(options.title) },
                    redirectTo: function (options) {
                      redirectAttempts += 1
                      if (options.fail) options.fail({ errMsg: 'redirectTo:fail' })
                    },
                    navigateTo: function (options) {
                      navigateAttempts += 1
                      if (options.fail) options.fail({ errMsg: 'navigateTo:fail' })
                    },
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.createRouteBookFromManualDrawn = function () {
                    saveCalls += 1
                    return Promise.resolve({ id: 42 })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  const actions = [{
                    kind: 'segment',
                    mode: 'freehand',
                    points: [[112.5, 37.8], [112.51, 37.81]],
                    rawPoints: [[112.5, 37.8], [112.51, 37.81]],
                    warnings: [],
                  }]
                  page.applyDraftState(actions, null, { routeName: '已保存路线' })

                  page.onTapSave()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const afterFailure = {
                    savedRouteBookId: page.data.savedRouteBookId,
                    saving: page.data.saving,
                    requestStatus: page.data.requestStatus,
                    canSaveRoute: page.data.canSaveRoute,
                    statusText: page.data.statusText,
                  }
                  page.onTapSave()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  process.stdout.write(JSON.stringify({
                    afterFailure,
                    saveCalls,
                    redirectAttempts,
                    navigateAttempts,
                    toasts,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["afterFailure"]["savedRouteBookId"] == 42
    assert rows["afterFailure"]["saving"] is False
    assert rows["afterFailure"]["requestStatus"] == "saved"
    assert rows["afterFailure"]["canSaveRoute"] is False
    assert "已保存" in rows["afterFailure"]["statusText"]
    assert rows["saveCalls"] == 1
    assert rows["redirectAttempts"] >= 1
    assert rows["navigateAttempts"] >= 1
    assert any("已保存" in text for text in rows["toasts"])


def test_ambiguous_save_failure_blocks_retry_but_clear_4xx_allows_retry():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let currentCode = -1
                  let saveCalls = 0
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test' } }
                  }
                  global.wx = { showToast: function () {} }
                  const api = require('./miniprogram/utils/api.js')
                  api.createRouteBookFromManualDrawn = function () {
                    saveCalls += 1
                    return Promise.reject({ code: currentCode })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const actions = [{
                    kind: 'segment',
                    mode: 'freehand',
                    points: [[112.5, 37.8], [112.51, 37.81]],
                    rawPoints: [[112.5, 37.8], [112.51, 37.81]],
                    warnings: [],
                  }]

                  async function simulate(code) {
                    currentCode = code
                    saveCalls = 0
                    const page = Object.assign({}, pageConfig, {
                      data: JSON.parse(JSON.stringify(pageConfig.data)),
                      setData: function (patch) {
                        this.data = Object.assign({}, this.data, patch)
                      },
                    })
                    page.applyDraftState(actions, null, { routeName: '响应边界路线' })
                    page.onTapSave()
                    await new Promise(function (resolve) { setTimeout(resolve, 0) })
                    const first = {
                      requestStatus: page.data.requestStatus,
                      canSaveRoute: page.data.canSaveRoute,
                      statusText: page.data.statusText,
                    }
                    page.onTapSave()
                    await new Promise(function (resolve) { setTimeout(resolve, 0) })
                    return { first, saveCalls }
                  }

                  process.stdout.write(JSON.stringify({
                    network: await simulate(-1),
                    server: await simulate(500),
                    validation: await simulate(422),
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    for key in ("network", "server"):
        assert rows[key]["first"]["requestStatus"] == "unknown"
        assert rows[key]["first"]["canSaveRoute"] is False
        assert "不确定" in rows[key]["first"]["statusText"]
        assert rows[key]["saveCalls"] == 1
    assert rows["validation"]["first"]["requestStatus"] == "error"
    assert rows["validation"]["first"]["canSaveRoute"] is True
    assert rows["validation"]["saveCalls"] == 2


def test_pending_save_survives_page_restart_and_replays_the_same_request_once():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let calls = []
                  let committedRoute = null
                  const storage = { userId: 7 }
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', userId: 7 } }
                  }
                  global.wx = {
                    showToast: function () {},
                    redirectTo: function () {},
                    getStorageSync: function (key) { return storage[key] },
                    setStorageSync: function (key, value) {
                      storage[key] = JSON.parse(JSON.stringify(value))
                    },
                    removeStorageSync: function (key) { delete storage[key] },
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.createRouteBookFromManualDrawn = function (payload) {
                    calls.push(JSON.parse(JSON.stringify(payload)))
                    if (!committedRoute) {
                      committedRoute = { id: 99 }
                      return Promise.reject({ code: -1 })
                    }
                    if (calls.length === 2) return Promise.reject({ code: 429 })
                    return Promise.resolve(committedRoute)
                  }
                  global.Page = function (config) { pageConfig = config }
                  const helpers = require('./miniprogram/pages/route-draw/route-draw.js')
                  function makePage() {
                    return Object.assign({}, pageConfig, {
                      data: JSON.parse(JSON.stringify(pageConfig.data)),
                      setData: function (patch) {
                        this.data = Object.assign({}, this.data, patch)
                      },
                    })
                  }
                  const actions = [{
                    kind: 'segment',
                    mode: 'freehand',
                    points: [[112.5, 37.8], [112.51, 37.81]],
                    rawPoints: [[112.5, 37.8], [112.51, 37.81]],
                    warnings: [],
                  }]

                  const firstPage = makePage()
                  firstPage.applyDraftState(actions, null, { routeName: '跨页面恢复路线' })
                  firstPage.onTapSave()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const pendingKey = 'route_draw_pending_save_v1:7'
                  const frozenBeforeRestart = JSON.parse(JSON.stringify(storage[pendingKey]))

                  const secondPage = makePage()
                  secondPage.onLoad()
                  const callsAfterRestore = calls.length
                  const pointsBeforeBlockedEdit = JSON.stringify(secondPage._confirmedPoints)
                  secondPage.onMapTap({ detail: { longitude: 112.9, latitude: 37.9 } })
                  const pointsAfterBlockedEdit = JSON.stringify(secondPage._confirmedPoints)
                  secondPage.onTapConfirmPendingSave()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const afterRateLimit = {
                    status: secondPage.data.requestStatus,
                    locked: secondPage.data.pendingSaveLocked,
                    pendingKept: storage[pendingKey] !== undefined,
                  }
                  secondPage.onTapConfirmPendingSave()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })

                  storage[pendingKey] = JSON.parse(JSON.stringify(frozenBeforeRestart))
                  api.createRouteBookFromManualDrawn = function (payload) {
                    calls.push(JSON.parse(JSON.stringify(payload)))
                    return Promise.reject({ code: 410 })
                  }
                  const gonePage = makePage()
                  gonePage.onLoad()
                  gonePage.onTapConfirmPendingSave()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const afterGone = {
                    status: gonePage.data.requestStatus,
                    locked: gonePage.data.pendingSaveLocked,
                    pendingCleared: storage[pendingKey] === undefined,
                    canSaveRoute: gonePage.data.canSaveRoute,
                  }

                  const maxPoints = Array.from({ length: 500 }, function (_, index) {
                    return [112.5 + index * 0.00001, 37.8]
                  })
                  const bounded = helpers.normalizePendingSavePayload({
                    name: '最大点数路线',
                    client_request_id: 'test-bounded-pending-payload',
                    coordinate_system: 'gcj02',
                    points: maxPoints,
                    draw_metadata: { warnings: [], raw_points_summary: { sample: maxPoints.slice(0, 20) } },
                  })
                  const oversizedAccepted = helpers.persistPendingSave({
                    name: '超大待确认路线',
                    client_request_id: 'test-oversized-pending-payload',
                    coordinate_system: 'gcj02',
                    points: [[112.5, 37.8], [112.6, 37.9]],
                    draw_metadata: { warnings: ['x'.repeat(270 * 1024)] },
                  })

                  process.stdout.write(JSON.stringify({
                    firstStatus: firstPage.data.requestStatus,
                    firstLocked: firstPage.data.pendingSaveLocked,
                    restoredStatus: secondPage.data.requestStatus,
                    restoredLocked: secondPage.data.pendingSaveLocked,
                    callsAfterRestore,
                    totalCalls: calls.length,
                    samePayload: calls.every(function (call) { return JSON.stringify(call) === JSON.stringify(calls[0]) }),
                    sameId: calls.every(function (call) { return call.client_request_id === calls[0].client_request_id }),
                    frozenMatchesCall: JSON.stringify(frozenBeforeRestart) === JSON.stringify(calls[0]),
                    blockedEdit: pointsBeforeBlockedEdit === pointsAfterBlockedEdit,
                    afterRateLimit,
                    afterGone,
                    savedRouteBookId: secondPage.data.savedRouteBookId,
                    pendingCleared: storage[pendingKey] === undefined,
                    boundedPayloadBytes: JSON.stringify(bounded).length,
                    oversizedAccepted,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    row = json.loads(result.stdout)

    assert row["firstStatus"] == "unknown"
    assert row["firstLocked"] is True
    assert row["restoredStatus"] == "saved"
    assert row["restoredLocked"] is True
    assert row["callsAfterRestore"] == 1
    assert row["totalCalls"] == 4
    assert row["samePayload"] is True
    assert row["sameId"] is True
    assert row["frozenMatchesCall"] is True
    assert row["blockedEdit"] is True
    assert row["afterRateLimit"] == {
        "status": "unknown",
        "locked": True,
        "pendingKept": True,
    }
    assert row["afterGone"] == {
        "status": "error",
        "locked": False,
        "pendingCleared": True,
        "canSaveRoute": True,
    }
    assert row["savedRouteBookId"] == 99
    assert row["pendingCleared"] is True
    assert row["boundedPayloadBytes"] < 64 * 1024
    assert row["oversizedAccepted"] is False


def test_logout_clears_only_the_current_users_pending_route_save():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                let appConfig
                const storage = {
                  token: 'token-for-user-7',
                  userId: 7,
                  'route_draw_pending_save_v1:7': { name: '用户 7 私有路线' },
                  'route_draw_pending_save_v1:8': { name: '用户 8 私有路线' },
                }
                global.App = function (config) { appConfig = config }
                global.wx = {
                  getStorageSync: function (key) { return storage[key] },
                  removeStorageSync: function (key) { delete storage[key] },
                }
                require('./miniprogram/app.js')
                appConfig.globalData.token = storage.token
                appConfig.globalData.userId = storage.userId
                appConfig.logout()
                process.stdout.write(JSON.stringify({
                  tokenCleared: storage.token === undefined,
                  userIdCleared: storage.userId === undefined,
                  user7PendingCleared: storage['route_draw_pending_save_v1:7'] === undefined,
                  user8PendingKept: storage['route_draw_pending_save_v1:8'] !== undefined,
                  globalUserId: appConfig.globalData.userId,
                }))
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    row = json.loads(result.stdout)

    assert row == {
        "tokenCleared": True,
        "userIdCleared": True,
        "user7PendingCleared": True,
        "user8PendingKept": True,
        "globalUserId": 0,
    }
    api_js = _read(MINI / "utils" / "api.js")
    unauthorized_block = api_js.split("if (res.statusCode === 401)", 1)[1].split("return", 1)[0]
    assert "route_draw_pending_save_v1" not in unauthorized_block


def test_route_draw_helpers_are_executable_and_keep_save_limit():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                global.Page = function () {}
                global.wx = {}
                const draw = require('./miniprogram/pages/route-draw/route-draw.js')
                const straight = []
                for (let i = 0; i < 620; i += 1) straight.push([112.5 + i * 0.00001, 37.8])
                const noisy = []
                for (let i = 0; i < 620; i += 1) noisy.push([112.5 + i * 0.00001, 37.8 + (i % 2 === 0 ? 0.02 : -0.02)])
                const fourMeterWiggle = []
                for (let i = 0; i < 602; i += 1) fourMeterWiggle.push([112.5 + i * 0.00001, 37.8 + (i % 2 === 0 ? 0.000036 : -0.000036)])
                const confirmed = [[112.5, 37.8], [112.51, 37.81]]
                const raw = [[112.52, 37.82], [112.53, 37.83]]
                const preview = [[112.54, 37.84], [112.55, 37.85]]
                const viewport = draw.sketchViewportFromParts(
                  { left: 10, top: 20, width: 200, height: 100 },
                  {
                    southwest: { longitude: 112.5, latitude: 37.8 },
                    northeast: { longitude: 112.7, latitude: 38.0 },
                  }
                )
                process.stdout.write(JSON.stringify({
                  straightLength: draw.simplifyForSave(straight).length,
                  noisyLength: draw.simplifyForSave(noisy).length,
                  fourMeterWiggleLength: draw.simplifyForSave(fourMeterWiggle).length,
                  polylines: draw.buildDrawPolylines(confirmed, raw, preview).map((item) => item.role),
                  stats: draw.buildRouteStats([[112.5, 37.8], [112.51, 37.8]]),
                  readyStats: draw.buildRouteStats(
                    [[112.5, 37.8], [112.51, 37.8]],
                    { climb_m: 123.4, descent_m: 20, elevation_profile: [[0, 700], [1, 720]] },
                    'ready'
                  ),
                  viewportCenter: draw.mapPointFromSketchViewport({ x: 110, y: 70 }, viewport),
                  metadata: draw.buildDrawMetadata(
                    ['snap'],
                    [[[112.5, 37.8], [112.51, 37.8]]],
                    [['系统贴出的路线可能偏离你的手画线，请检查后再保存。']]
                  ),
                }))
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert 2 <= rows["straightLength"] <= 500
    assert 500 < rows["noisyLength"] <= 5000
    assert rows["fourMeterWiggleLength"] == 602
    assert rows["polylines"] == ["confirmedPolyline", "rawPolyline", "previewPolyline"]
    assert rows["stats"]["pointCount"] == 2
    assert rows["stats"]["distanceM"] > 800
    assert rows["stats"]["climbText"] == "—"
    assert rows["readyStats"]["climbText"] == "123 m"
    assert rows["viewportCenter"][0] == pytest.approx(112.6)
    assert rows["viewportCenter"][1] == pytest.approx(37.9, abs=0.001)
    assert rows["metadata"]["tool"] == "route_draw_v0"
    assert rows["metadata"]["snap_provider"] == "tencent_bicycling"
    assert rows["metadata"]["segment_count"] == 1
    assert rows["metadata"]["freehand_segment_count"] == 0
    assert rows["metadata"]["raw_points_summary"]["total_raw_points"] == 2
    assert rows["metadata"]["warnings"] == ["系统贴出的路线可能偏离你的手画线，请检查后再保存。"]


def test_long_route_keeps_canonical_points_internal_and_bounds_view_payload():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let savedPayload = null
                  let timerId = 0
                  const patches = []
                  const storage = { userId: 7 }
                  global.setTimeout = function () { timerId += 1; return timerId }
                  global.clearTimeout = function () {}
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', userId: 7 } }
                  }
                  global.wx = {
                    showToast: function () {},
                    setStorageSync: function (key, value) { storage[key] = value },
                    removeStorageSync: function (key) { delete storage[key] },
                    getStorageSync: function (key) { return storage[key] },
                    redirectTo: function () {},
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.createRouteBookFromManualDrawn = function (payload) {
                    savedPayload = JSON.parse(JSON.stringify(payload))
                    return Promise.resolve({ id: 701 })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      patches.push(JSON.parse(JSON.stringify(patch)))
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  const totalPointCount = 19 * 399 + 1
                  const longitudeSpan = 1.375
                  for (let segment = 0; segment < 19; segment += 1) {
                    const points = []
                    for (let index = 0; index < 400; index += 1) {
                      const absolute = segment * 399 + index
                      points.push([
                        112.5 + longitudeSpan * absolute / (totalPointCount - 1),
                        37.8 + Math.sin(absolute / 20) * 0.0001,
                      ])
                    }
                    page.commitSegmentAction({
                      mode: 'snap',
                      rawPoints: [points[0], points[points.length - 1]],
                      points: points,
                      warnings: [],
                    })
                  }
                  const routePatches = patches.filter(function (patch) { return patch.drawPolylines })
                  const elevationPatches = patches.filter(function (patch) {
                    return patch.elevationStatus && !patch.drawPolylines
                  })
                  const renderedPointCounts = routePatches.map(function (patch) {
                    const line = patch.drawPolylines.find(function (item) {
                      return item.role === 'confirmedPolyline'
                    })
                    return line ? line.points.length : 0
                  })
                  const routePatchBytes = routePatches.map(function (patch) {
                    return JSON.stringify(patch).length
                  })
                  page.setData({ routeName: '121 公里长路线回归' })
                  page.onTapSave()
                  await Promise.resolve()
                  await Promise.resolve()
                  process.stdout.write(JSON.stringify({
                    internalPointCount: page._confirmedPoints.length,
                    distanceM: page.data.routeStats.distanceM,
                    routePatchCount: routePatches.length,
                    maxRenderedPointCount: Math.max.apply(Math, renderedPointCounts),
                    maxRoutePatchBytes: Math.max.apply(Math, routePatchBytes),
                    routePatchKeys: Object.keys(routePatches[routePatches.length - 1]),
                    elevationPatchesCarryPolyline: elevationPatches.some(function (patch) {
                      return patch.drawPolylines || patch.confirmedPoints || patch.routeDraft
                    }),
                    internalSegmentCount: page._segmentModes.length,
                    savedPointCount: savedPayload && savedPayload.points.length,
                    savedSegmentCount: savedPayload && savedPayload.draw_metadata.segment_count,
                    savedRawPointCount: savedPayload && savedPayload.draw_metadata.raw_points_summary.total_raw_points,
                    savedFirstPoint: savedPayload && savedPayload.points[0],
                    savedLastPoint: savedPayload && savedPayload.points[savedPayload.points.length - 1],
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    row = json.loads(result.stdout)

    assert row["internalPointCount"] > 7_000
    assert 115_000 < row["distanceM"] < 130_000
    assert row["routePatchCount"] == 19
    assert row["maxRenderedPointCount"] <= 500
    assert row["maxRoutePatchBytes"] < 200_000
    assert row["internalSegmentCount"] == 19
    assert row["savedPointCount"] <= 500
    assert row["savedSegmentCount"] == 19
    # 19 个首尾相接的两点段合并后保留 20 个唯一锚点。
    assert row["savedRawPointCount"] == 20
    assert row["savedFirstPoint"] == pytest.approx([112.5, 37.8])
    assert row["savedLastPoint"] == pytest.approx([113.875, 37.8], abs=0.001)
    assert "routeDraft" not in row["routePatchKeys"]
    assert "confirmedSegments" not in row["routePatchKeys"]
    assert "confirmedPoints" not in row["routePatchKeys"]
    assert row["elevationPatchesCarryPolyline"] is False


def test_route_draw_map_tap_flow_sets_anchor_snaps_and_loads_elevation():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let snapCalls = []
                  let elevationCalls = []
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', baseUrl: 'http://127.0.0.1' } }
                  }
                  global.wx = {
                    createMapContext: function () {
                      return {}
                    },
                    showToast: function () {},
                    createSelectorQuery: function () { return null },
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.snapManualDrawnRoute = function (payload) {
                    snapCalls.push(payload)
                    return Promise.resolve({
                      snapped_points: payload.points,
                      warnings: [],
                    })
                  }
                  api.previewManualDrawnElevation = function (payload) {
                    elevationCalls.push(payload)
                    return Promise.resolve({
                      climb_m: 42.4,
                      descent_m: 10,
                      elevation_profile: [[0, 700], [1.4, 742]],
                    })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  page.onReady()

                  page.onMapTap({ detail: { longitude: 112.5, latitude: 37.8 } })
                  const first = {
                    snapCalls: snapCalls.length,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                    statusText: page.data.statusText,
                  }

                  page.onMapTap({ detail: { longitude: 112.51, latitude: 37.81 } })
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const duringElevation = {
                    canSaveRoute: page.data.canSaveRoute,
                    elevationStatus: page.data.elevationStatus,
                  }
                  await new Promise(function (resolve) { setTimeout(resolve, 850) })
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const second = {
                    snapCalls: snapCalls.length,
                    snapMode: snapCalls[0] && snapCalls[0].mode,
                    coordinateSystem: snapCalls[0] && snapCalls[0].coordinate_system,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                    segmentMode: page._segmentModes[0],
                    elevationCalls: elevationCalls.length,
                    elevationStatus: page.data.elevationStatus,
                    climbText: page.data.routeStats.climbText,
                  }
                  process.stdout.write(JSON.stringify({ first, duringElevation, second }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["first"]["snapCalls"] == 0
    assert rows["first"]["pointCount"] == 1
    assert rows["first"]["canSaveRoute"] is False
    assert rows["duringElevation"]["elevationStatus"] == "loading"
    assert rows["duringElevation"]["canSaveRoute"] is True
    assert rows["second"]["snapCalls"] == 1
    assert rows["second"]["snapMode"] == "snap"
    assert rows["second"]["coordinateSystem"] == "gcj02"
    assert rows["second"]["pointCount"] == 2
    assert rows["second"]["canSaveRoute"] is True
    assert rows["second"]["segmentMode"] == "snap"
    assert rows["second"]["elevationCalls"] == 1
    assert rows["second"]["elevationStatus"] == "ready"
    assert rows["second"]["climbText"] == "42 m"


def test_map_pan_does_not_add_point_and_extreme_detour_waits_for_confirmation():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let now = 1000
                  let snapCalls = 0
                  const toasts = []
                  Date.now = function () { return now }
                  global.setTimeout = function () { return 1 }
                  global.clearTimeout = function () {}
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test' } }
                  }
                  global.wx = {
                    showToast: function (options) { toasts.push(options.title) },
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.snapManualDrawnRoute = function () {
                    snapCalls += 1
                    return Promise.resolve({
                      snapped_points: [
                        [112.5, 37.8],
                        [112.55, 37.85],
                        [112.501, 37.8],
                      ],
                      display_points: [
                        [112.5, 37.8],
                        [112.55, 37.85],
                        [112.501, 37.8],
                      ],
                      warnings: ['系统贴出的路线可能偏离你的手画线，请检查后再保存。'],
                      requires_confirmation: true,
                    })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  page.commitAnchorAction([112.5, 37.8])
                  page.onMapRegionChange({ type: 'begin', causedBy: 'gesture' })
                  page.onMapRegionChange({ type: 'end', causedBy: 'gesture' })
                  page.onMapTap({ detail: { longitude: 112.501, latitude: 37.8 } })
                  const callsAfterPan = snapCalls

                  now += 451
                  page.onMapTap({ detail: { longitude: 112.501, latitude: 37.8 } })
                  await Promise.resolve()
                  await Promise.resolve()
                  const beforeAccept = {
                    requestStatus: page.data.requestStatus,
                    segmentCount: page._segmentModes.length,
                    pendingPointCount: page._routePending.previewPoints.length,
                    canSaveRoute: page.data.canSaveRoute,
                  }
                  page.onMapTap({ detail: { longitude: 112.502, latitude: 37.8 } })
                  const callsWhileConfirming = snapCalls
                  page.onTapAcceptDetour()
                  const afterAccept = {
                    requestStatus: page.data.requestStatus,
                    segmentMode: page._segmentModes[0],
                    pointCount: page._confirmedPoints.length,
                    pendingCleared: page._routePending === null,
                    canSaveRoute: page.data.canSaveRoute,
                  }
                  process.stdout.write(JSON.stringify({
                    callsAfterPan,
                    callsWhileConfirming,
                    snapCalls,
                    beforeAccept,
                    afterAccept,
                    toasts,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    row = json.loads(result.stdout)

    assert row["callsAfterPan"] == 0
    assert row["callsWhileConfirming"] == 1
    assert row["snapCalls"] == 1
    assert row["beforeAccept"] == {
        "requestStatus": "confirming",
        "segmentCount": 0,
        "pendingPointCount": 3,
        "canSaveRoute": False,
    }
    assert row["afterAccept"] == {
        "requestStatus": "idle",
        "segmentMode": "snap",
        "pointCount": 3,
        "pendingCleared": True,
        "canSaveRoute": True,
    }
    assert any("移动地图" in text for text in row["toasts"])
    assert any("先处理当前绕行" in text for text in row["toasts"])


def test_route_draw_ignores_stale_elevation_result_after_geometry_changes():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  const elevationResolvers = []
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', baseUrl: 'http://127.0.0.1' } }
                  }
                  global.wx = {
                    showToast: function () {},
                    createSelectorQuery: function () { return null },
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.previewManualDrawnElevation = function () {
                    return new Promise(function (resolve) { elevationResolvers.push(resolve) })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })

                  page.commitSegmentAction({
                    mode: 'snap',
                    rawPoints: [[112.5, 37.8], [112.51, 37.81]],
                    points: [[112.5, 37.8], [112.51, 37.81]],
                    warnings: [],
                  })
                  await new Promise(function (resolve) { setTimeout(resolve, 850) })
                  page.commitSegmentAction({
                    mode: 'snap',
                    rawPoints: [[112.51, 37.81], [112.52, 37.82]],
                    points: [[112.51, 37.81], [112.52, 37.82]],
                    warnings: [],
                  })
                  await new Promise(function (resolve) { setTimeout(resolve, 850) })

                  elevationResolvers[1]({
                    climb_m: 20,
                    descent_m: 3,
                    elevation_profile: [[0, 700], [2, 720]],
                  })
                  await Promise.resolve()
                  await Promise.resolve()
                  elevationResolvers[0]({
                    climb_m: 999,
                    descent_m: 0,
                    elevation_profile: [[0, 700], [1, 1699]],
                  })
                  await Promise.resolve()
                  await Promise.resolve()

                  process.stdout.write(JSON.stringify({
                    elevationCalls: elevationResolvers.length,
                    elevationStatus: page.data.elevationStatus,
                    climbText: page.data.routeStats.climbText,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["elevationCalls"] == 2
    assert rows["elevationStatus"] == "ready"
    assert rows["climbText"] == "20 m"
    assert rows["pointCount"] == 3
    assert rows["canSaveRoute"] is True


def test_failed_next_snap_reschedules_the_cancelled_elevation_preview():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let elevationCalls = 0
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test' } }
                  }
                  global.wx = {
                    showToast: function () {},
                    createSelectorQuery: function () { return null },
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.snapManualDrawnRoute = function () {
                    return Promise.reject({ code: 422 })
                  }
                  api.previewManualDrawnElevation = function () {
                    elevationCalls += 1
                    return Promise.resolve({
                      climb_m: 12,
                      descent_m: 2,
                      elevation_profile: [[0, 700], [1, 712]],
                    })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  page.commitSegmentAction({
                    mode: 'snap',
                    rawPoints: [[112.5, 37.8], [112.51, 37.81]],
                    points: [[112.5, 37.8], [112.51, 37.81]],
                    warnings: [],
                  })
                  page.startSnapPreview([[112.51, 37.81], [112.52, 37.82]])
                  await Promise.resolve()
                  await Promise.resolve()
                  await new Promise(function (resolve) { setTimeout(resolve, 850) })
                  await Promise.resolve()
                  await Promise.resolve()
                  process.stdout.write(JSON.stringify({
                    elevationCalls,
                    elevationStatus: page.data.elevationStatus,
                    climbText: page.data.routeStats.climbText,
                    requestStatus: page.data.requestStatus,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    row = json.loads(result.stdout)

    assert row == {
        "elevationCalls": 1,
        "elevationStatus": "ready",
        "climbText": "12 m",
        "requestStatus": "error",
    }


def test_route_draw_sketch_auto_finish_restores_map_when_touchend_is_lost():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let timers = []
                  let snapCallCount = 0
                  global.setTimeout = function (fn, ms) {
                    timers.push({ fn, ms, cleared: false })
                    return timers.length - 1
                  }
                  global.clearTimeout = function (id) {
                    if (timers[id]) timers[id].cleared = true
                  }
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', baseUrl: 'http://127.0.0.1' } }
                  }
                  global.wx = {
                    createMapContext: function () {
                      return {
                        getRegion: function (options) {
                          options.success({
                            southwest: { longitude: 112.5, latitude: 37.8 },
                            northeast: { longitude: 112.6, latitude: 37.9 },
                          })
                        },
                      }
                    },
                    createSelectorQuery: function () {
                      const query = {
                        in: function () { return query },
                        select: function () {
                          return {
                            boundingClientRect: function (callback) {
                              callback({ left: 0, top: 0, width: 100, height: 100 })
                            },
                          }
                        },
                        exec: function () {},
                      }
                      return query
                    },
                    showToast: function () {},
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.snapManualDrawnRoute = function (payload) {
                    snapCallCount += 1
                    return Promise.resolve({ snapped_points: payload.points, warnings: [] })
                  }
                  api.previewManualDrawnElevation = function () {
                    return Promise.resolve({
                      climb_m: 18,
                      descent_m: 2,
                      elevation_profile: [[0, 700], [10, 718]],
                    })
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  page.onReady()
                  page.commitAnchorAction([112.5, 37.8])
                  await page.onTapStartSketch()
                  page.onDrawTouchStart({ touches: [{ clientX: 0, clientY: 100 }] })
                  page.onDrawTouchMove({ touches: [{ clientX: 50, clientY: 100 }] })
                  page.onDrawTouchMove({ touches: [{ clientX: 100, clientY: 100 }] })
                  for (let i = 0; i < 8; i += 1) await Promise.resolve()
                  timers.filter(function (timer) {
                    return timer.ms === 900 && !timer.cleared
                  }).pop().fn()
                  for (let i = 0; i < 8; i += 1) await Promise.resolve()
                  timers.filter(function (timer) {
                    return timer.ms === 800 && !timer.cleared
                  }).pop().fn()
                  for (let i = 0; i < 8; i += 1) await Promise.resolve()
                  process.stdout.write(JSON.stringify({
                    builderMode: page.data.builderMode,
                    showSketchLayer: page.data.showSketchLayer,
                    mapScrollEnabled: page.data.mapScrollEnabled,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                    segmentMode: page._segmentModes[0],
                    snapCallCount: snapCallCount,
                    elevationStatus: page.data.elevationStatus,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["builderMode"] == "smart"
    assert rows["showSketchLayer"] is False
    assert rows["mapScrollEnabled"] is True
    assert rows["pointCount"] >= 2
    assert rows["canSaveRoute"] is True
    assert rows["segmentMode"] == "freehand"
    assert rows["snapCallCount"] == 0
    assert rows["elevationStatus"] == "ready"


def test_route_draw_sketch_does_not_stay_trapped_when_region_callback_hangs():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', baseUrl: 'http://127.0.0.1' } }
                  }
                  global.wx = {
                    createMapContext: function () {
                      return {
                        getRegion: function () {},
                      }
                    },
                    createSelectorQuery: function () {
                      const query = {
                        in: function () { return query },
                        select: function () {
                          return {
                            boundingClientRect: function (callback) {
                              callback({ left: 0, top: 0, width: 100, height: 100 })
                            },
                          }
                        },
                        exec: function () {},
                      }
                      return query
                    },
                    showToast: function () {},
                  }
                  global.Page = function (config) { pageConfig = config }
                  require('./miniprogram/pages/route-draw/route-draw.js')
                  const page = Object.assign({}, pageConfig, {
                    data: JSON.parse(JSON.stringify(pageConfig.data)),
                    setData: function (patch) {
                      this.data = Object.assign({}, this.data, patch)
                    },
                  })
                  page.onReady()
                  await page.onTapStartSketch()
                  process.stdout.write(JSON.stringify({
                    builderMode: page.data.builderMode,
                    showSketchLayer: page.data.showSketchLayer,
                    mapScrollEnabled: page.data.mapScrollEnabled,
                    statusText: page.data.statusText,
                    errorMessage: page.data.errorMessage,
                  }))
                })().catch(function (err) {
                  console.error(err && err.stack ? err.stack : err)
                  process.exit(1)
                })
                """
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)

    assert rows["builderMode"] == "smart"
    assert rows["showSketchLayer"] is False
    assert rows["mapScrollEnabled"] is True
    assert rows["statusText"] == "地图还没有准备好手绘"
    assert "重新点一次手绘" in rows["errorMessage"]


def test_route_draw_js_syntax():
    subprocess.run(
        ["node", "--check", str(PAGE_DIR / "route-draw.js")],
        cwd=ROOT,
        check=True,
    )
