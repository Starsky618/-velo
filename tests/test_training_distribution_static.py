"""Sprint 11 task-4：小程序训练结构页静态合同测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "miniprogram"
TRAINING_DISTRIBUTION_PAGE = MINI / "pages" / "training-distribution"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_training_distribution_files_exist():
    """训练结构页四文件必须齐全。"""
    for suffix in ("wxml", "wxss", "js", "json"):
        assert (TRAINING_DISTRIBUTION_PAGE / f"training-distribution.{suffix}").exists()


def test_training_distribution_registered_at_app_json_tail():
    """新页追加到 app.json 末尾，不能抢走默认首页。"""
    app_json = json.loads(_read(MINI / "app.json"))

    assert app_json["pages"][0] == "pages/home/home"
    assert "pages/training-calendar/training-calendar" in app_json["pages"]
    assert app_json["pages"][-1] == "pages/training-distribution/training-distribution"


def test_profile_has_training_distribution_entry():
    """我的页保留训练分析，同时新增训练结构入口。"""
    wxml = _read(MINI / "pages" / "profile" / "profile.wxml")
    js = _read(MINI / "pages" / "profile" / "profile.js")

    assert "训练分析" in wxml
    assert "训练结构" in wxml
    assert "看最近 6 周训练时间怎么分布" in wxml
    assert 'bindtap="onTapTrainingDistribution"' in wxml
    assert "onTapTrainingDistribution" in js
    assert "/pages/training-distribution/training-distribution" in js


def test_training_distribution_js_uses_distribution_endpoint_only():
    """页面只能请求训练结构接口，不能自己拉活动列表拼结果。"""
    js = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.js")

    assert "api.get('/api/training/distribution', params)" in js
    assert "/api/activities" not in js


def test_training_distribution_exclude_zero_switch_is_persisted_and_sent_to_api():
    """页面开关要记住用户选择，并把 exclude_zero 传给后端。"""
    js = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.js")
    wxml = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.wxml")

    assert "training_distribution_exclude_zero" in js
    assert "wx.getStorageSync" in js
    assert "wx.setStorageSync" in js
    assert "exclude_zero" in js
    assert 'bindchange="onExcludeZeroChange"' in wxml
    assert "不计滑行/停顿时间" in wxml


def test_training_distribution_wxml_uses_backend_copy_fields():
    """当前/建议对比卡必须展示后端返回文案。"""
    wxml = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.wxml")

    assert "{{distribution.current_label}}" in wxml
    assert "{{distribution.current_description}}" in wxml
    assert "{{distribution.target_label}}" in wxml
    assert "{{distribution.target_description}}" in wxml


def test_training_distribution_wxml_renders_groups_actions_and_week_plan():
    """页面展示三组分布、三条行动建议和一周安排。"""
    wxml = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.wxml")

    assert 'wx:for="{{groups}}"' in wxml
    assert 'wx:for="{{actions}}"' in wxml
    assert 'wx:for="{{weekPlan}}"' in wxml
    assert "{{item.label}}" in wxml
    assert "{{item.percent}}%" in wxml
    assert "{{item.role}}" in wxml
    assert "{{item.day}}" in wxml
    assert "{{item.title}}" in wxml
    assert "{{item.focus}}" in wxml


def test_training_distribution_shows_raw_power_zones_next_to_donut():
    """饼图旁边必须直接展示 Z1-Z6；否则 exclude_zero 开关看起来像没反应。"""
    js = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.js")
    wxml = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.wxml")
    wxss = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.wxss")

    assert "power-zones" in js
    assert "formatPowerZoneRows" in js
    assert "res.raw_zones" in js
    assert 'class="chart-split"' in wxml
    assert 'class="raw-zone-list"' in wxml
    assert 'wx:for="{{rawZones}}"' in wxml
    assert "{{item.timeText}}" in wxml
    assert ".chart-split" in wxss
    assert ".raw-zone-row" in wxss


def test_activity_detail_defaults_power_zones_to_pedaling_time():
    """单次活动详情页默认不含 0W，和训练结构页的真实蹬踏口径一致。"""
    js = _read(MINI / "pages" / "detail" / "detail.js")
    wxml = _read(MINI / "pages" / "detail" / "detail.wxml")
    util = _read(MINI / "utils" / "power-zones.js")

    assert "power-zones" in js
    assert "buildPedalingPowerZones(data.power_zones)" in js
    assert "zero_seconds" in util
    assert "默认不计 0W" in wxml
    assert "Z{{item.zone}}" not in wxml


def test_training_distribution_states_are_present():
    """页面必须覆盖 loading / error / 数据不足 / 正常四态。"""
    wxml = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.wxml")
    js = _read(TRAINING_DISTRIBUTION_PAGE / "training-distribution.js")

    assert "加载中" in wxml
    assert "训练结构加载失败" in wxml
    assert "功率数据不足" in wxml
    assert "loading" in js
    assert "loadError" in js
    assert "dataComplete" in js
    assert "insufficientPower" in js
