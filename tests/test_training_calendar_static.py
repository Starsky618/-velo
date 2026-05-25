"""Sprint 10 task-5：小程序训练日历页静态合同测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"
TRAINING_PAGE = MINI / "pages" / "training-calendar"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_training_calendar_still_registered_after_distribution_page_added():
    """训练日历仍注册；Sprint 11 新训练结构页追加到末尾。"""
    app_json = json.loads(_read(MINI / "app.json"))

    assert app_json["pages"][0] == "pages/home/home"
    assert "pages/training-calendar/training-calendar" in app_json["pages"]
    assert app_json["pages"][-1] == "pages/training-distribution/training-distribution"


def test_profile_entry_is_always_visible_and_navigates_to_training_calendar():
    """我的页入口常显，不用本周 rides 粗筛，点击进入训练分析页。"""
    wxml = _read(MINI / "pages" / "profile" / "profile.wxml")
    js = _read(MINI / "pages" / "profile" / "profile.js")

    assert "训练分析" in wxml
    assert "看 30/90/全年训练负荷曲线" in wxml
    assert "bindtap=\"onTapTrainingAnalysis\"" in wxml
    training_card = wxml[wxml.index("训练分析") - 180:wxml.index("训练分析") + 180]
    assert "wx:if" not in training_card
    assert "onTapTrainingAnalysis" in js
    assert "/pages/training-calendar/training-calendar" in js


def test_training_calendar_files_and_api_contract_exist():
    """训练页四文件齐全，并只调用 Task 4 的单 endpoint。"""
    for suffix in ("wxml", "wxss", "js", "json"):
        assert (TRAINING_PAGE / f"training-calendar.{suffix}").exists()

    js = _read(TRAINING_PAGE / "training-calendar.js")
    assert "/api/training/load" in js
    assert "range:" in js
    assert "30d" in js and "90d" in js and "1y" in js
    assert "/api/user/stats" not in js


def test_training_calendar_range_tab_drives_api_range_param():
    """用户切 30/90/全年 tab 后，请求参数必须跟 currentRange 一起变。"""
    wxml = _read(TRAINING_PAGE / "training-calendar.wxml")
    js = _read(TRAINING_PAGE / "training-calendar.js")

    assert 'data-range="{{item.value}}"' in wxml
    assert 'bindtap="onRangeTap"' in wxml
    assert "this.setData({ currentRange: range }" in js
    assert "const range = this.data.currentRange" in js
    assert "api.get('/api/training/load', { range: range })" in js


def test_training_calendar_explains_metrics_in_plain_language():
    """训练分析不是给懂 PMC 的人背缩写，要把图翻译成用户能行动的语言。"""
    wxml = _read(TRAINING_PAGE / "training-calendar.wxml")

    assert "健身度 CTL" in wxml
    assert "疲劳 ATL" in wxml
    assert "状态 TSB" in wxml
    assert "本周训练量" in wxml
    assert "绿线慢慢涨" in wxml
    assert "黄线冲高" in wxml
    assert "蓝线低于 -10" in wxml


def test_training_calendar_canvas_and_empty_state_are_safe():
    """canvas 需要 100ms 兜底；空数据态不能画假曲线。"""
    wxml = _read(TRAINING_PAGE / "training-calendar.wxml")
    js = _read(TRAINING_PAGE / "training-calendar.js")

    assert 'canvas type="2d"' in wxml
    assert 'id="pmc-chart"' in wxml
    assert "wx:if" in wxml
    assert "dataComplete" in wxml
    assert "setTimeout" in js and "100" in js
    assert "pmc-chart" in js
    assert "if (!this.data.dataComplete)" in js
    assert "return" in js[js.index("if (!this.data.dataComplete)"):js.index("if (!this.data.dataComplete)") + 120]


def test_training_calendar_error_state_does_not_fall_into_empty_state():
    """接口失败是加载错误，不是数据不够；用户应该看到 toast 并退出页。"""
    wxml = _read(TRAINING_PAGE / "training-calendar.wxml")
    js = _read(TRAINING_PAGE / "training-calendar.js")

    assert "loadError" in js
    assert "wx.navigateBack" in js
    assert "训练分析加载失败 / 请重试" in js
    assert 'wx:elif="{{loadError}}"' in wxml
    assert wxml.index('wx:elif="{{loadError}}"') < wxml.index('wx:elif="{{!dataComplete}}"')


def test_training_calendar_status_copy_covers_four_bands():
    """四档短文案都在前端，中文状态标签仍使用后端 current_status_label。"""
    js = _read(TRAINING_PAGE / "training-calendar.js")

    assert "current_status_label" in js
    assert "你状态饱满" in js
    assert "按计划训练即可" in js
    assert "建议中低强度或休息" in js
    assert "强烈建议休息" in js
