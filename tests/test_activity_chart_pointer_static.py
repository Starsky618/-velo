"""
活动详情图表指针静态测试——防止前端又退回“只能看不能摸”。

这里不启动微信开发者工具，只读小程序源码：
- WXML 的每张图必须绑定自己的 touch 事件和 chart 标识
- detail.js 只能保存单图指针状态，不能出现全图联动状态
- bindchart.js 的指针绘制必须是可选功能，旧调用不传 activeIndex 仍能画静态图
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_detail_wxml_binds_independent_touch_events_to_each_metric_canvas():
    wxml = _read("miniprogram/pages/detail/detail.wxml")

    for chart in ["elevation", "speed", "power", "hr", "cadence"]:
        assert f'data-chart="{chart}"' in wxml
    assert wxml.count('bindtouchstart="onChartTouchStart"') >= 5
    assert wxml.count('bindtouchmove="onChartTouchMove"') >= 5
    assert wxml.count('bindtouchend="onChartTouchEnd"') >= 5


def test_detail_js_has_single_chart_cursor_state_without_global_linking():
    js = _read("miniprogram/pages/detail/detail.js")

    assert "chartCursors" in js
    assert "_scheduleChartRedraw" in js
    assert "onChartTouchStart" in js
    assert "onChartTouchMove" in js
    assert "onChartTouchEnd" in js
    assert "_drawTimeseriesChart" in js
    assert "points=1200" in js
    assert "linkedChart" not in js
    assert "linkedCharts" not in js
    assert "syncChart" not in js


def test_bindchart_pointer_layer_is_optional_and_uses_active_index():
    js = _read("miniprogram/utils/bindchart.js")

    assert "activeIndex" in js
    assert "drawCursorOverlay" in js
    assert "getNearestIndexFromTouch" in js
    assert "page.__bindchartStates" in js
    assert "if (opts.activeIndex != null)" in js


def test_chart_colors_use_strava_reference_palette():
    js = _read("miniprogram/pages/detail/detail.js")
    wxss = _read("miniprogram/pages/detail/detail.wxss")

    for color in ["#3F7EDB", "#B268E6", "#D9504F", "#D14FBA", "#BFC1BB"]:
        assert color in js or color in wxss


def test_pointer_style_is_solid_black_with_bubble_above_plot():
    bindchart = _read("miniprogram/utils/bindchart.js")
    detail = _read("miniprogram/pages/detail/detail.js")

    assert "var pad = { top: 56" in bindchart
    assert "var pad = { top: 56" in detail
    assert "var bubbleY = 4" in bindchart
    assert "var bubbleY = 4" in detail
    assert "ctx.strokeStyle = '#000000'" in bindchart
    assert "ctx.fillStyle = '#000000'" in bindchart
    assert "ctx.strokeStyle = '#000000'" in detail
    assert "ctx.fillStyle = '#000000'" in detail
    assert "ctx.fillStyle = '#FFFFFF'" not in bindchart
    assert "setLineDash" not in bindchart
    assert "setLineDash" not in detail
