"""约骑模块 Task 9：小程序静态合同测试。"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _else_map_block(wxml: str) -> str:
    return wxml.split("<map wx:else", 1)[1].split("</map>", 1)[0]


def _block_after(wxml: str, marker: str) -> str:
    return wxml.split(marker, 1)[1]


def test_meetup_pages_are_registered_at_app_json_tail():
    app_json = json.loads(_read(MINI / "app.json"))

    assert app_json["pages"][0] == "pages/home/home"
    assert app_json["pages"][-3:] == [
        "pages/meetups-list/meetups-list",
        "pages/meetup-detail/meetup-detail",
        "pages/meetup-create/meetup-create",
    ]


def test_meetup_tab_is_registered_in_tabbar():
    # 约骑必须有底部 tab 入口（spec 用户故事："velo '约骑' tab"），否则用户进不去
    app_json = json.loads(_read(MINI / "app.json"))
    tab_paths = [tab["pagePath"] for tab in app_json["tabBar"]["list"]]
    assert "pages/meetups-list/meetups-list" in tab_paths
    assert len(app_json["tabBar"]["list"]) <= 5  # 微信 tabBar 上限 5 个


def test_meetup_page_files_exist():
    for page in ("meetups-list", "meetup-detail", "meetup-create"):
        folder = MINI / "pages" / page
        for suffix in ("js", "wxml", "wxss", "json"):
            assert (folder / f"{page}.{suffix}").exists()


def test_api_helpers_use_meetup_endpoints():
    api = _read(MINI / "utils" / "api.js")

    for snippet in [
        "getMeetupsList",
        "getMeetupDetail",
        "createMeetup",
        "updateMeetup",
        "publishMeetup",
        "cancelMeetup",
        "joinMeetup",
        "leaveMeetup",
        "getRouteBooksList",
        "getRouteBookActivityCandidates",
        "createRouteBookFromActivity",
        "createRouteBookFromTencentDirection",
        "getSegmentsList",
        "requestForm",
    ]:
        assert snippet in api
    assert "/api/meetups" in api
    assert "/api/route-books" in api


def test_list_page_loads_open_meetups_and_navigates_to_detail():
    js = _read(MINI / "pages" / "meetups-list" / "meetups-list.js")
    wxml = _read(MINI / "pages" / "meetups-list" / "meetups-list.wxml")

    assert "api.getMeetupsList" in js
    assert "status: 'OPEN'" in js
    assert "/pages/meetup-detail/meetup-detail?id=" in js
    assert 'wx:for="{{meetups}}"' in wxml
    assert "发起约骑" in wxml


def test_detail_page_joins_and_leaves_without_user_chat():
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    wxml = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxml")

    assert "api.joinMeetup" in js
    assert "api.leaveMeetup" in js
    assert "api.getMeetupDetail" in js
    assert "onTapJoin" in js
    assert "onTapLeave" in js
    # 发起人取消：详情页按角色显示取消按钮（is_creator）+ 二次确认走 cancelMeetup
    assert "onTapCancel" in js
    assert "api.cancelMeetup" in js
    assert "is_creator" in js
    assert 'wx:if="{{meetup.canCancel}}"' in wxml
    # 照片墙：creator 上传 + 列表展示 + 删除
    assert "onTapAddMedia" in js
    assert "api.getMeetupMedia" in js
    assert "api.uploadMeetupMedia" in js
    assert "照片墙" in wxml
    assert "私信" not in wxml
    assert "评论" not in wxml


def test_create_page_is_three_step_flow_and_uses_backend_state():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "steps: [" in js
    assert "route" in js and "details" in js and "publish" in js
    assert "api.createMeetup" in js
    assert "api.publishMeetup" in js
    assert "api.updateMeetup" in js
    assert "draft_exists" in js
    assert "api.getSegmentsList" in js
    assert "api.getRouteBooksList" in js
    assert "api.getRouteBookActivityCandidates" in js
    assert "api.createRouteBookFromTencentDirection" in js
    assert "selectedSegmentId" in js
    assert "selectedRouteBookId" in js
    assert "selectedActivityId" in js
    assert "tencentStartText" in js
    assert "tencentEndText" in js
    assert "onTapCreateTencentRoute" in js
    assert "currentStep" in wxml
    assert "路线" in wxml and "时间" in wxml and "发布" in wxml
    assert "腾讯地图生成" in wxml
    # 时间必须用微信日期/时间选择器，不能用文本框让用户手敲 ISO 字符串
    assert 'mode="date"' in wxml
    assert 'mode="time"' in wxml


def test_create_page_uses_map_picker_instead_of_native_location_popup():
    app_js = _read(MINI / "app.js")
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "wx.chooseLocation" not in js
    assert "/pages/map-picker/map-picker?kind=" in js
    assert "onTapChooseTencentStart" in js
    assert "onTapChooseTencentEnd" in js
    assert "consumePendingMapPoint" in js
    assert "pendingMapPoint" in app_js
    assert "chooseLocation" not in json.dumps(app_json, ensure_ascii=False)
    assert "scope.userLocation" not in json.dumps(app_json, ensure_ascii=False)


def test_create_page_lets_user_name_tencent_route_before_generating():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "tencentRouteName" in js
    assert "tencentRouteName" in wxml
    assert "onTencentRouteNameInput" in js
    assert 'bindinput="onTencentRouteNameInput"' in wxml
    assert "buildTencentRouteName" in js
    assert "name: routeName" in js


def test_create_page_blocks_past_start_time_before_saving_or_publishing():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "minStartDate" in js
    assert 'start="{{minStartDate}}"' in wxml
    assert "ensureFutureMeetupTime" in js
    assert js.count("ensureFutureMeetupTime") >= 4


def test_confirm_page_route_detail_and_pace_controls_are_real_actions():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert 'bindtap="onTapPreviewRouteDetail"' in wxml
    assert "routeMapOverlayVisible" not in js
    assert "route-map-overlay" not in wxml
    assert "require('../../utils/route-map-nav')" in js
    assert "routeMapNav.openRouteMapPage" in js
    assert "paceIndex" in js
    assert 'class="pv-pace-picker"' in wxml
    assert 'bindchange="onPaceChange"' in wxml
    assert "this.updatePreviewDerived()" in js


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


def test_meetup_detail_uses_free_paper_canvas_for_display_route_map():
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    wxml = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxml")
    wxss = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.wxss")

    assert "require('../../utils/route-thumb')" in js
    assert "drawRoutePreviewThumb" in js
    assert "require('../../utils/route-map-nav')" in js
    assert "onOpenRouteMapPage" in js
    assert "routeMapOverlayVisible" not in js
    display_block = _block_after(wxml, 'class="map-card"')
    assert "<map" not in display_block
    assert "route-map-overlay" not in wxml
    assert 'canvas-id="meetup-route-preview"' in wxml
    assert 'bindtap="onOpenRouteMapPage"' in wxml
    assert ".route-preview-canvas" in wxss
    assert ".route-map-overlay" not in wxss


def test_confirm_publish_persists_confirm_page_pace_change():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]

    assert "pace_level: this.data.form.pace_level" in publish_block


def test_create_page_supports_meeting_point_map_and_favorites():
    api = _read(MINI / "utils" / "api.js")
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "getMeetupFavoritePlaces" in api
    assert "saveMeetupFavoritePlace" in api
    assert "deleteMeetupFavoritePlace" in api
    assert "/api/meetups/favorite-places" in api
    assert "favoritePlaces" in js
    assert "loadFavoritePlaces" in js
    assert "onTapChooseMeetingPoint" in js
    assert "saveMeetingPointAsFavorite" in js
    assert "applyFavoritePlace" in js
    assert "kind=meeting" in js
    assert "point.kind === 'meeting'" in js
    assert "bindtap=\"onTapChooseMeetingPoint\"" in wxml
    assert "bindtap=\"saveMeetingPointAsFavorite\"" in wxml
    assert "bindtap=\"applyFavoritePlace\"" in wxml


def test_create_page_persists_custom_power_speed_hints():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    ensure_block = js.split("ensureDraft: function ()", 1)[1].split("saveDraft: function ()", 1)[0]
    save_block = js.split("saveDraft: function ()", 1)[1].split("updateField: function", 1)[0]
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]

    assert "recommended_power_label" in js
    assert "average_speed_range" in js
    assert "recommended_power_label: draft.recommended_power_label" in js
    assert "average_speed_range: draft.average_speed_range" in js
    assert "Object.assign({}, that.data.form" in ensure_block
    assert "Object.assign({}, that.data.form" in save_block
    assert "recommended_power_label: this.data.form.recommended_power_label" in publish_block
    assert "average_speed_range: this.data.form.average_speed_range" in publish_block
    assert 'data-field="recommended_power_label"' in wxml
    assert 'data-field="average_speed_range"' in wxml
    assert 'bindinput="updateField"' in wxml


def test_map_picker_supports_meeting_search():
    api = _read(MINI / "utils" / "api.js")
    js = _read(MINI / "pages" / "map-picker" / "map-picker.js")
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")

    assert "searchMeetupPlace" in api
    assert "/api/meetups/place-search" in api
    assert "kind === 'meeting'" in js
    assert "选择集合点" in js
    assert "api.searchMeetupPlace" in js
    assert "wgs84ToGcj02" in js
    assert "searchKeyword" in js
    assert "placeSearchResults" in js
    assert "selectedSearchPlace" in js
    assert "sourceLatitude" in js
    assert "coordinate_system: 'wgs84'" in js
    assert "coordinate_system: 'gcj02'" in js
    assert "address: picked.address" in js
    assert "event.causedBy !== 'update'" in js
    assert "selectedSearchPlace: null" in js
    assert "onSearchKeywordInput" in js
    assert "onTapSearchPlace" in js
    assert 'wx:if="{{kind === \'meeting\'}}"' in wxml
    assert 'bindinput="onSearchKeywordInput"' in wxml
    assert 'bindtap="onTapSearchPlace"' in wxml
    assert 'wx:for="{{placeSearchResults}}"' in wxml


def test_confirm_publish_blocks_cutoff_window_before_backend_raw_error():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    publish_block = js.split("onConfirmPublish: function ()", 1)[1].split("resolveRouteBookId", 1)[0]

    assert "MEETUP_PUBLISH_CUTOFF_BUFFER_MS" in js
    assert "ensurePublishableMeetupTime" in js
    assert "30 * 60 * 1000 + 30 * 1000" in js
    assert "离出发太近，不能发布" in js
    assert "formatMeetupPublishError" in js
    assert "meetup cutoff passed" in js
    assert "ensurePublishableMeetupTime()" in publish_block


def test_tencent_route_names_are_bounded_and_errors_are_human():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    picker_wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")

    assert "TENCENT_POINT_NAME_MAX_LENGTH" in js
    assert "TENCENT_ROUTE_NAME_MAX_LENGTH" in js
    assert "limitTencentRouteName" in js
    assert "formatTencentRouteError" in js
    assert "生成失败，请检查路线名称和起终点" in js
    assert 'maxlength="40"' in picker_wxml


def test_create_page_formats_meter_distance_as_kilometers():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "distanceText(item.distance, type)" in js
    assert "type === 'segment'" in js
    assert "/ 1000" in js


def test_create_page_hides_tencent_env_config_errors_from_users():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "路线服务暂不可用" in js
    assert "err && err.code === 503" in js


def test_create_page_draws_light_route_preview_map():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    assert "wgs84ToGcj02" in js
    assert "preview_points" in js
    assert "drawMainRoutePreview" in js
    assert 'canvas-id="route-preview-main"' in wxml
    preview_block = _block_after(wxml, 'class="route-preview-shell"').split('class="pv-card pv-route-card"', 1)[0]
    assert "<map" not in preview_block
    assert "route-preview-wash" not in wxml
    assert ".route-preview-canvas" in wxss


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


def test_no_wxml_in_whole_project_uses_paid_personalized_map_style():
    # 红线守卫：微信小程序个性化底图（subkey + layer-style）自 2023-06-29 起是
    # "先购买再使用"的付费能力，velo 未购买——任何 <map> 挂上这两个属性，
    # 真机鉴权必失败、地图卡死（2026-06-12 事故，codex 多轮代码修复全部无效）。
    # 这条测试把教训变成结构约束：全工程 wxml 永远不许再出现这两个属性。
    for wxml_path in MINI.rglob("*.wxml"):
        wxml = _read(wxml_path)
        assert "subkey" not in wxml, f"{wxml_path} 使用了付费个性化底图 subkey"
        assert "layer-style" not in wxml, f"{wxml_path} 使用了付费个性化底图 layer-style"


def test_create_page_uses_shared_paper_map_theme_for_route_preview():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")
    wxss = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxss")

    assert "require('../../utils/map-theme')" in js
    assert "getPaperMapData" not in js
    assert "buildRoutePreviewPolylines" in js
    assert "routePreviewMapSubkey" not in js
    preview_block = _block_after(wxml, 'class="route-preview-shell"').split('class="pv-card pv-route-card"', 1)[0]
    assert "paperMapSubkey" not in preview_block
    assert "paperMapLayerStyle" not in preview_block
    assert "route-map-overlay" not in wxml
    assert "route-preview-wash" not in wxml
    assert "rgba(255, 255, 255" in wxss


def test_heatmap_card_uses_free_paper_canvas_instead_of_native_map():
    js = _read(MINI / "components" / "heatmap-card" / "heatmap-card.js")
    wxml = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxml")
    wxss = _read(MINI / "components" / "heatmap-card" / "heatmap-card.wxss")

    assert "require('../../utils/route-thumb')" in js
    assert "drawHeatmapThumb" in js
    assert "#FFD700CC" not in js
    assert "<map" not in wxml
    assert 'canvas-id="heatmap-canvas"' in wxml
    assert "heatmap-map-wash" not in wxml
    assert "background: #eef3ee" in wxss


def test_map_picker_page_is_registered_and_uses_native_map_without_custom_subkey():
    app_json = json.loads(_read(MINI / "app.json"))
    js = _read(MINI / "pages" / "map-picker" / "map-picker.js")
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")
    wxss = _read(MINI / "pages" / "map-picker" / "map-picker.wxss")

    assert "pages/map-picker/map-picker" in app_json["pages"]
    assert "require('../../utils/map-theme')" not in js
    assert "selectMapPoint" in js
    assert "<map" in wxml
    assert "paperMapSubkey" not in wxml
    assert "layer-style" not in wxml
    assert "map-picker-pin" in wxml
    assert "map-picker-wash" not in wxml
    assert "位置名称" in wxml
    assert "{{confirmText}}" in wxml
    assert "rgba(255, 255, 255" in wxss
    assert "pointer-events: none" in wxss


def test_map_picker_keeps_default_cartography_context():
    wxml = _read(MINI / "pages" / "map-picker" / "map-picker.wxml")

    assert 'enable-poi="{{false}}"' not in wxml
    assert 'enable-building="{{false}}"' not in wxml
    assert 'enable-traffic="{{false}}"' in wxml


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


def test_create_route_preview_card_uses_canvas_but_detail_opens_dedicated_map_page():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    preview_block = _block_after(wxml, 'class="route-preview-shell"').split('class="pv-card pv-route-card"', 1)[0]
    assert "<map" not in preview_block
    assert "route-map-overlay" not in wxml
    assert 'canvas-id="route-preview-main"' in wxml
    assert "require('../../utils/route-map-nav')" in js
    assert "routeMapNav.openRouteMapPage" in js


def test_create_page_avoids_object_spread_for_wechat_runtime():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    assert "...routePreview" not in js
    assert "...buildRoutePreview" not in js


def test_route_preview_coordinate_helper_exports_converter():
    coords = _read(MINI / "utils" / "coords.js")

    assert "function wgs84ToGcj02" in coords
    assert "module.exports = { wgs84ToGcj02 }" in coords


def test_meetup_pages_have_no_dash_placeholder():
    # Tim 2026-05-15 永久规则：前端永不显示 "-" 占位符，字段缺失整块隐藏（wx:if）
    for page in ("meetups-list", "meetup-detail", "meetup-create", "meetups-mine"):
        js = _read(MINI / "pages" / page / f"{page}.js")
        assert "'--'" not in js, f"{page}.js 不应有 '--' 占位符"


def test_my_meetups_page_registered_and_wired():
    # 个人页"我的约骑"：注册 + 四件套存在 + 两 tab + 个人页有入口
    app_json = json.loads(_read(MINI / "app.json"))
    assert "pages/meetups-mine/meetups-mine" in app_json["pages"]
    for suffix in ("js", "wxml", "wxss", "json"):
        assert (MINI / "pages" / "meetups-mine" / f"meetups-mine.{suffix}").exists()

    js = _read(MINI / "pages" / "meetups-mine" / "meetups-mine.js")
    wxml = _read(MINI / "pages" / "meetups-mine" / "meetups-mine.wxml")
    assert "api.getMyMeetups" in js
    assert "created" in js and "joined" in js
    assert "我发起的" in wxml and "我加入的" in wxml

    profile_js = _read(MINI / "pages" / "profile" / "profile.js")
    assert "onTapMyMeetups" in profile_js
    assert "meetups-mine" in profile_js


def test_v1_out_of_scope_features_are_absent():
    all_text = "\n".join(_read(path) for path in (MINI / "pages").glob("meetup*/*.*"))

    assert "路线足迹" not in all_text
    assert "算法推荐" not in all_text
    assert "为你推荐" not in all_text
    assert "私聊" not in all_text


def test_create_page_has_preview_step_and_social_fields():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    wxml = _read(MINI / "pages" / "meetup-create" / "meetup-create.wxml")

    assert "'confirm'" in js  # 2026-06 流程重排：preview 步改名 confirm（route→edit→confirm）
    assert "onTapGoPreview" in js
    assert "onConfirmPublish" in js
    assert "toggleAudienceTag" in js
    assert "onSelectVisibility" in js  # 可见范围改两盒子点选（不再用 picker 的 onVisibilityChange）
    assert "applySafetyTemplate" in js
    for field in ("supply_point", "eligibility_note", "safety_note", "visibility"):
        assert field in js and field in wxml
    # 标签：js 存 form.audience_tags，wxml 走 audienceOptions(带 selected 标志)+ toggleAudienceTag
    assert "audience_tags" in js
    assert "audienceOptions" in wxml and "toggleAudienceTag" in wxml
    assert "recommended_power_label" in js
    assert "average_speed_range" in js
    assert "VELO 反骚扰机制" in wxml
    # 继续邀请走微信原生转发（不是站内定向邀请）
    assert 'open-type="share"' in wxml
    # WXML 不支持 .indexOf()，选中态必须在 JS 算成 selected 标志
    assert "form.audience_tags.indexOf" not in wxml
    # 旧"发布约骑"直发按钮已被 onTapGoPreview/onConfirmPublish 两步取代
    assert 'bindtap="onPublish"' not in wxml
    # 发布前总览页用 canvas 轨迹缩略线，点"查看详情"再打开完整地图，避免小 map 抢按钮手势
    assert 'canvas-id="route-thumb-confirm"' in wxml
    assert "route-map-overlay" not in wxml


def test_pace_display_table_covers_all_four_pace_levels():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")

    for pace in ("relaxed", "cruise", "training", "race"):
        assert pace in js
    assert "不限功率" in js
    assert "FTP 160W+ 更舒服" in js
    assert "FTP 220W+" in js
    assert "FTP 280W+" in js


def test_create_page_restores_draft_and_share_path_carries_invite_token():
    js = _read(MINI / "pages" / "meetup-create" / "meetup-create.js")
    api = _read(MINI / "utils" / "api.js")

    # 草稿恢复
    assert "restoreDraft" in js
    assert "api.getMyMeetupDraft" in js
    assert "loadMedia()" in js
    assert "buildRoutePreview" in js
    # 微信原生转发邀请（invite_only 带 token）
    assert "onShareAppMessage" in js
    assert "draft.share_token" in js
    assert "shareToken" in js
    assert "token=" in js
    # api helper：participants 新增 / detail + join 替换为带 token 签名
    assert "getMeetupParticipants" in api
    # S13-T3/T5：detail 签名加了 source（埋点来路标记），token 合同不变
    assert "getMeetupDetail: function (meetupId, token, source)" in api
    assert "joinMeetup: function (meetupId, token)" in api
    assert "getRouteBookDetail" in api


def test_meetup_detail_consumes_invite_token_from_share_link():
    # 私圈分享链接 ?id=X&token=Y 落地详情页：必须收下 token 并透传给详情/加入/照片，
    # 否则受邀者带链接进来后端门禁返回 404（这是 task5+6 双审抓到的 Critical，加静态测试锁死）
    js = _read(MINI / "pages" / "meetup-detail" / "meetup-detail.js")
    assert "options.token" in js
    assert "shareToken" in js
    # S13-T3/T5：调用点第三参是 source（埋点来路），token 透传合同不变
    assert "getMeetupDetail(this.data.meetupId, this.data.shareToken, source)" in js
    assert "options.source" in js  # 分享卡 ?source=share_card 必须被读取，否则①触达埋点恒为 0（集成审 Critical 锁死）
    assert "joinMeetup(this.data.meetupId, this.data.shareToken)" in js
    assert "getMeetupMedia(this.data.meetupId, this.data.shareToken)" in js
