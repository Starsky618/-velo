"""Route Draw V0 Task 4：手画路线页小程序静态合同测试。"""

import json
import subprocess
import textwrap
from pathlib import Path


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


def test_route_draw_declares_fuzzy_location_permission():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(PAGE_DIR / "route-draw.js")

    assert app_json["requiredPrivateInfos"] == ["getFuzzyLocation", "chooseLocation"]
    assert "路线绘制" in app_json["permission"]["scope.userFuzzyLocation"]["desc"]
    assert "wx.getFuzzyLocation" in js
    assert "wx.getLocation" not in js


def test_route_draw_page_uses_map_tap_as_default_input_and_sketch_only_touch_layer():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert 'bindtap="onMapTap"' in wxml
    assert "onMapTap: function" in js
    assert "mapScrollEnabled: true" in js
    assert 'enable-scroll="{{mapScrollEnabled}}"' in wxml
    assert 'enable-zoom="{{mapScrollEnabled}}"' in wxml
    assert 'class="route-draw-touch-layer"' in wxml
    assert 'wx:if="{{showSketchLayer}}"' in wxml
    assert "wx.createMapContext('route-draw-map'" in js
    assert ".fromScreenLocation" in js
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

    assert 'bindtap="onTapSearchLocation"' in wxml
    assert "搜地点" in wxml
    assert "onTapSearchLocation: function" in js
    assert "wx.chooseLocation" in js
    assert "点“+ 添加点”设为路线点" in js


def test_route_draw_has_center_crosshair_add_point_fallback():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    wxss = _read(PAGE_DIR / "route-draw.wxss")

    assert 'bindregionchange="onMapRegionChange"' in wxml
    assert 'class="route-draw-crosshair"' in wxml
    assert 'class="center-add-button' in wxml
    assert 'bindtap="onTapAddCenterPoint"' in wxml
    assert "添加点" in wxml
    assert "onTapAddCenterPoint: function" in js
    assert "readMapCenterPoint: function" in js
    assert ".getCenterLocation" in js
    assert "this.addRoutePoint(point)" in js
    assert "route-draw-crosshair" in wxss
    assert "center-add-button" in wxss


def test_route_draw_page_uses_builder_status_and_action_draft_state():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert "builderMode: 'smart'" in js
    assert "requestStatus: 'idle'" in js
    assert "routeDraft" in js
    assert "actions: []" in js
    assert "segments: []" in js
    assert "pending: null" in js
    assert "confirmedPoints" in js
    assert "currentRawPoints" in js
    assert "previewPoints" in js
    assert "markers" in js
    assert "buildDrawPolylines" in js
    assert "confirmedPolyline" in js
    assert "rawPolyline" in js
    assert "previewPolyline" in js
    assert "Manual Mode" in wxml
    assert "确认当前段" not in wxml
    assert "自由画线" not in wxml
    assert "segmentReady" not in js


def test_route_draw_bottom_sheet_includes_activity_type_and_elevation_placeholder():
    wxml = _read(PAGE_DIR / "route-draw.wxml")

    assert "运动类型" in wxml
    assert "骑行" in wxml
    assert "海拔图" in wxml
    assert "保存后生成海拔图" in wxml


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
    snap_block = js.split("startSnapPreview: function", 1)[1].split("onTapToggleManualMode", 1)[0]
    success_block = snap_block.split("api.snapManualDrawnRoute", 1)[1].split(".catch", 1)[0]

    assert "this.startSnapPreview(raw)" in add_point_block
    assert "mode: 'snap'" in snap_block
    assert "points: simplifyForSnap(raw)" in snap_block
    assert "commitSegmentAction" in success_block
    assert "requestStatus: 'idle'" in success_block
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


def test_manual_mode_uses_freehand_contract_without_snap_or_manual_backend_mode():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    manual_branch = js.split("if (this.data.builderMode === 'manual')", 1)[1].split("this.startSnapPreview", 1)[0]
    metadata_block = js.split("function buildDrawMetadata", 1)[1].split("function screenPointFromEvent", 1)[0]

    assert "Manual Mode" in wxml
    assert "mode: 'freehand'" in manual_branch
    assert "api.snapManualDrawnRoute" not in manual_branch
    assert "freehand_segment_count" in metadata_block
    assert "snap_provider: freehandCount === modes.length ? 'freehand' : 'tencent_bicycling'" in metadata_block
    assert "mode: 'manual'" not in js


def test_sketch_pencil_temporarily_takes_over_touch_and_then_restores_map():
    js = _read(PAGE_DIR / "route-draw.js")
    wxml = _read(PAGE_DIR / "route-draw.wxml")
    start_block = js.split("onTapStartSketch: function", 1)[1].split("onDrawTouchStart", 1)[0]
    finish_block = js.split("finishSketchSegment: function", 1)[1].split("onTapUndoAction", 1)[0]

    assert 'wx:if="{{showSketchLayer}}"' in wxml
    assert "builderMode: 'sketch'" in start_block
    assert "showSketchLayer: true" in start_block
    assert "mapScrollEnabled: false" in start_block
    assert "mapContextFromScreenLocation" in js
    assert "showSketchLayer: false" in finish_block
    assert "mapScrollEnabled: true" in finish_block
    assert "SKETCH_AUTO_FINISH_MS" in js
    assert "SKETCH_LOCATION_TIMEOUT_MS" in js
    assert "armSketchAutoFinish: function" in js
    assert "clearSketchAutoFinish: function" in js
    assert "finishSketchAfterCapture: function" in js
    assert "this.armSketchAutoFinish()" in js
    assert "this.clearSketchAutoFinish()" in js
    assert "fromScreenLocation timeout" in js


def test_route_draw_undo_is_action_based_and_invalidates_stale_snap_response():
    js = _read(PAGE_DIR / "route-draw.js")
    snap_block = js.split("startSnapPreview: function", 1)[1].split("onTapToggleManualMode", 1)[0]
    undo_block = js.split("onTapUndoAction: function", 1)[1].split("onTapStartSketch", 1)[0]

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
    assert "贴路服务还没上线，可以切 Manual Mode 继续画。" in js
    assert "贴路操作太快，稍等再试，或切 Manual Mode 继续画。" in js
    assert "路线没有保存成功，请稍后再试" in js
    assert "路线太长，分几段保存更稳" in js
    assert "腾讯" not in js
    assert "this.data.requestStatus === 'previewing'" in save_block
    assert "confirmedPoints.length < 2" in save_block
    assert 'disabled="{{!canSaveRoute}}"' in wxml
    assert "少于 2 个点时保存不可用" in wxml


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
                  const pointsBeforeBlockedEdit = JSON.stringify(secondPage.data.confirmedPoints)
                  secondPage.onMapTap({ detail: { longitude: 112.9, latitude: 37.9 } })
                  const pointsAfterBlockedEdit = JSON.stringify(secondPage.data.confirmedPoints)
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
                    draw_metadata: { warnings: ['x'.repeat(70 * 1024)] },
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
                const confirmed = [[112.5, 37.8], [112.51, 37.81]]
                const raw = [[112.52, 37.82], [112.53, 37.83]]
                const preview = [[112.54, 37.84], [112.55, 37.85]]
                process.stdout.write(JSON.stringify({
                  straightLength: draw.simplifyForSave(straight).length,
                  noisyLength: draw.simplifyForSave(noisy).length,
                  polylines: draw.buildDrawPolylines(confirmed, raw, preview).map((item) => item.role),
                  stats: draw.buildRouteStats([[112.5, 37.8], [112.51, 37.8]]),
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
    assert rows["noisyLength"] > 500
    assert rows["polylines"] == ["confirmedPolyline", "rawPolyline", "previewPolyline"]
    assert rows["stats"]["pointCount"] == 2
    assert rows["stats"]["distanceM"] > 800
    assert rows["metadata"]["tool"] == "route_draw_v0"
    assert rows["metadata"]["snap_provider"] == "tencent_bicycling"
    assert rows["metadata"]["segment_count"] == 1
    assert rows["metadata"]["freehand_segment_count"] == 0
    assert rows["metadata"]["raw_points_summary"]["total_raw_points"] == 2
    assert rows["metadata"]["warnings"] == ["系统贴出的路线可能偏离你的手画线，请检查后再保存。"]


def test_route_draw_center_add_flow_sets_anchor_then_snaps_second_point():
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                """
                ;(async function () {
                  let pageConfig
                  let center = [112.5, 37.8]
                  let snapCalls = []
                  global.getApp = function () {
                    return { globalData: { token: 'token-for-test', baseUrl: 'http://127.0.0.1' } }
                  }
                  global.wx = {
                    createMapContext: function () {
                      return {
                        getCenterLocation: function (options) {
                          options.success({ longitude: center[0], latitude: center[1] })
                        },
                        fromScreenLocation: function () {},
                      }
                    },
                    showToast: function () {},
                  }
                  const api = require('./miniprogram/utils/api.js')
                  api.snapManualDrawnRoute = function (payload) {
                    snapCalls.push(payload)
                    return Promise.resolve({
                      snapped_points: payload.points,
                      warnings: [],
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

                  await page.onTapAddCenterPoint()
                  const first = {
                    snapCalls: snapCalls.length,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                    statusText: page.data.statusText,
                  }

                  center = [112.51, 37.81]
                  await page.onTapAddCenterPoint()
                  await new Promise(function (resolve) { setTimeout(resolve, 0) })
                  const second = {
                    snapCalls: snapCalls.length,
                    snapMode: snapCalls[0] && snapCalls[0].mode,
                    coordinateSystem: snapCalls[0] && snapCalls[0].coordinate_system,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                    segmentMode: page.data.confirmedSegmentModes[0],
                  }
                  process.stdout.write(JSON.stringify({ first, second }))
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
    assert rows["second"]["snapCalls"] == 1
    assert rows["second"]["snapMode"] == "snap"
    assert rows["second"]["coordinateSystem"] == "gcj02"
    assert rows["second"]["pointCount"] == 2
    assert rows["second"]["canSaveRoute"] is True
    assert rows["second"]["segmentMode"] == "snap"


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
                        getCenterLocation: function (options) {
                          options.success({ longitude: 112.5, latitude: 37.8 })
                        },
                        fromScreenLocation: function (options) {
                          options.success({
                            longitude: 112.5 + options.x / 10000,
                            latitude: 37.8 + options.y / 10000,
                          })
                        },
                      }
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
                  page.updateMode('manual', { requestStatus: 'idle' })
                  page.onTapStartSketch()
                  page.onDrawTouchStart({ touches: [{ x: 0, y: 0 }] })
                  page.onDrawTouchMove({ touches: [{ x: 100, y: 0 }] })
                  for (let i = 0; i < 8; i += 1) await Promise.resolve()
                  timers.filter(function (timer) {
                    return timer.ms === 900 && !timer.cleared
                  }).pop().fn()
                  for (let i = 0; i < 8; i += 1) await Promise.resolve()
                  process.stdout.write(JSON.stringify({
                    builderMode: page.data.builderMode,
                    showSketchLayer: page.data.showSketchLayer,
                    mapScrollEnabled: page.data.mapScrollEnabled,
                    pointCount: page.data.routeStats.pointCount,
                    canSaveRoute: page.data.canSaveRoute,
                    segmentMode: page.data.confirmedSegmentModes[0],
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

    assert rows["builderMode"] == "manual"
    assert rows["showSketchLayer"] is False
    assert rows["mapScrollEnabled"] is True
    assert rows["pointCount"] >= 2
    assert rows["canSaveRoute"] is True
    assert rows["segmentMode"] == "freehand"


def test_route_draw_sketch_does_not_stay_trapped_when_location_callback_hangs():
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
                        getCenterLocation: function (options) {
                          options.success({ longitude: 112.5, latitude: 37.8 })
                        },
                        fromScreenLocation: function (options) {
                          if (options.x === 0) {
                            options.success({ longitude: 112.5, latitude: 37.8 })
                          }
                        },
                      }
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
                  page.updateMode('manual', { requestStatus: 'idle' })
                  page.commitSegmentAction({
                    mode: 'freehand',
                    rawPoints: [[112.5, 37.8], [112.51, 37.8]],
                    points: [[112.5, 37.8], [112.51, 37.8]],
                    warnings: [],
                  })
                  page.onTapStartSketch()
                  page.onDrawTouchStart({ touches: [{ x: 0, y: 0 }] })
                  page.onDrawTouchMove({ touches: [{ x: 100, y: 0 }] })
                  page.onDrawTouchEnd({ changedTouches: [{ x: 100, y: 0 }] })
                  await new Promise(function (resolve) { setTimeout(resolve, 850) })
                  process.stdout.write(JSON.stringify({
                    builderMode: page.data.builderMode,
                    showSketchLayer: page.data.showSketchLayer,
                    mapScrollEnabled: page.data.mapScrollEnabled,
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

    assert rows["builderMode"] == "manual"
    assert rows["showSketchLayer"] is False
    assert rows["mapScrollEnabled"] is True
    assert rows["pointCount"] >= 2
    assert rows["canSaveRoute"] is True


def test_route_draw_js_syntax():
    subprocess.run(
        ["node", "--check", str(PAGE_DIR / "route-draw.js")],
        cwd=ROOT,
        check=True,
    )
