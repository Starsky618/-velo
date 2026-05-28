"""单次 activity 功率曲线卡片的小程序静态合同测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"
DETAIL = MINI / "pages" / "detail"
COMP = MINI / "components" / "activity-power-curve-card"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_activity_power_curve_component_files_exist():
    """组件必须四件套齐全，才能被详情页独立挂载。"""
    for suffix in ("wxml", "wxss", "js", "json"):
        assert (COMP / f"activity-power-curve-card.{suffix}").exists()


def test_detail_page_registers_and_mounts_activity_power_curve_card():
    """详情页只负责放卡片入口；请求和绘图留给组件自己做。"""
    detail_json = json.loads(_read(DETAIL / "detail.json"))
    detail_wxml = _read(DETAIL / "detail.wxml")

    assert detail_json["usingComponents"]["activity-power-curve-card"] == (
        "/components/activity-power-curve-card/activity-power-curve-card"
    )
    assert "<activity-power-curve-card" in detail_wxml
    assert 'activity-id="{{activity.id}}"' in detail_wxml


def test_component_uses_hidden_canvas_and_100ms_render_guard():
    """canvas 必须保留在 DOM 里，并在 setData 后等 100ms 再画。"""
    wxml = _read(COMP / "activity-power-curve-card.wxml")
    js = _read(COMP / "activity-power-curve-card.js")

    assert 'canvas type="2d"' in wxml
    assert 'id="activityPowerCurveCanvas"' in wxml
    assert 'hidden="{{!visible || loading || error}}"' in wxml
    assert 'wx:if="{{visible}}"' not in wxml
    assert "setTimeout" in js
    assert "100" in js


def test_component_fetches_summary_and_exact_effort_endpoints():
    """卡片先拿智能点画图，拖动停住后再查任意秒数的精确读数。"""
    js = _read(COMP / "activity-power-curve-card.js")

    assert "'/api/activities/' + activityId + '/power-curve'" in js
    assert "'/api/activities/' + activityId + '/power-curve/effort'" in js
    assert "duration_sec: durationSec" in js
    assert "api.get(summaryUrl, { points: 1000 })" in js
    assert "api.get(effortUrl, { duration_sec: durationSec })" in js


def test_component_touch_interaction_uses_log_time_and_canvas_local_x():
    """拖动要按时间对数坐标找时长，并优先使用 canvas 本地 touch.x。"""
    wxml = _read(COMP / "activity-power-curve-card.wxml")
    js = _read(COMP / "activity-power-curve-card.js")

    assert 'bindtouchstart="onCurveTouchStart"' in wxml
    assert 'bindtouchmove="onCurveTouchMove"' in wxml
    assert 'bindtouchend="onCurveTouchEnd"' in wxml
    assert 'bindtouchcancel="onCurveTouchEnd"' in wxml
    assert "Math.log" in js
    assert "Math.exp" in js
    assert "touch.x != null" in js
    assert "touch.clientX" in js
