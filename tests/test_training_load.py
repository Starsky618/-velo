"""Sprint 10 task-2：训练负荷 CTL/ATL/TSB 纯函数测试。"""

import math

import pytest

from app.training.training_load import (
    calculate_daily_atl,
    calculate_daily_ctl,
    calculate_tsb,
    classify_tsb_status,
    format_status_label,
)


def test_calculate_daily_ctl_matches_hand_calculation():
    """CTL 42 天指数加权：last_ctl=50 / tss=80 应约等于 PRD 手算 50.71。"""
    result = calculate_daily_ctl(50.0, 80.0)

    assert result == pytest.approx(50.71, abs=0.01)


def test_calculate_daily_atl_uses_7_day_time_constant():
    """ATL 用 7 天时间常数，比 CTL 更快响应今天的训练压力。"""
    expected = 50.0 * math.exp(-1 / 7) + 80.0 * (1 - math.exp(-1 / 7))

    assert calculate_daily_atl(50.0, 80.0) == pytest.approx(expected)


def test_zero_history_and_zero_tss_stays_zero():
    """新用户第一天没有训练时，体能和疲劳都从 0 起步。"""
    assert calculate_daily_ctl(0.0, 0.0) == pytest.approx(0.0)
    assert calculate_daily_atl(0.0, 0.0) == pytest.approx(0.0)


def test_calculate_tsb_returns_raw_float_without_rounding():
    """TSB 只做减法并返回原始 float，写表/API 层再统一保留 1 位。"""
    result = calculate_tsb(65.34, 78.19)

    assert result == pytest.approx(-12.85)


@pytest.mark.parametrize(
    ("tsb", "expected"),
    [
        (10.0, "ok"),
        (10.1, "fresh"),
        (-10.0, "ok"),
        (-10.1, "tired"),
        (-20.0, "tired"),
        (-20.1, "overreached"),
    ],
)
def test_classify_tsb_status_boundaries(tsb, expected):
    """4 档边界按 Tim 拍板：+10/-10 落 OK，-20 落 tired。"""
    assert classify_tsb_status(tsb) == expected


def test_classify_tsb_status_treats_missing_value_as_ok():
    """TSB 缺失时按 0 处理；这里显式测 None，避免用 truthiness 混判。"""
    assert classify_tsb_status(None) == "ok"


def test_none_inputs_are_treated_as_zero():
    """None 代表没有历史或当天没活动，按 0.0 算自然衰减。"""
    assert calculate_daily_ctl(None, None) == pytest.approx(0.0)
    assert calculate_daily_atl(None, None) == pytest.approx(0.0)


def test_negative_tss_raises_value_error():
    """负 TSS 是脏数据，必须显式报错，不能悄悄算出假曲线。"""
    with pytest.raises(ValueError):
        calculate_daily_ctl(50.0, -1.0)

    with pytest.raises(ValueError):
        calculate_daily_atl(50.0, -1.0)


def test_format_status_label_returns_short_chinese_labels():
    """状态标签只返短中文，长建议文案留给前端短句或 Sprint 12 教练总结。"""
    assert format_status_label("fresh") == "状态饱满"
    assert format_status_label("ok") == "状态 OK"
    assert format_status_label("tired") == "累"
    assert format_status_label("overreached") == "过累"


def test_format_status_label_rejects_unknown_band():
    """未知状态不静默兜底，避免前后端把拼错字段当正常文案展示。"""
    with pytest.raises(ValueError):
        format_status_label("sleepy")
