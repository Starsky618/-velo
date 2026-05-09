"""
功率曲线纯函数测试——v5 Sprint 2 task-2.B.1。

只测算法正确性，不碰 DB / 不碰文件系统。
用 SimpleNamespace mock Trackpoint ORM 对象（只需要 .power 和 .seq 属性）。
"""
from types import SimpleNamespace

import pytest

from app.activity.power_zones import (
    calculate_power_curve,
    calculate_power_curve_from_activities,
)


def _tp(seq: int, power):
    """构造 mock Trackpoint：只暴露 .seq 和 .power 两个属性。"""
    return SimpleNamespace(seq=seq, power=power)


# ───────────────────────────────────────────────────────────────────────
# calculate_power_curve（单 activity 内最大平均功率）
# ───────────────────────────────────────────────────────────────────────


class TestCalculatePowerCurve:
    def test_empty_trackpoints_returns_all_zero(self):
        """空 trackpoints → 所有 window 返 0.0（默认 7 档 / D26 v2 polish）。"""
        result = calculate_power_curve([])
        assert result == {0: 0.0, 3: 0.0, 30: 0.0, 60: 0.0, 300: 0.0, 1200: 0.0, 3600: 0.0}

    def test_all_none_power_treated_as_zero(self):
        """所有 tp.power = None → 累加和全 0 → 所有 window 返 0。"""
        tps = [_tp(i, None) for i in range(10)]
        result = calculate_power_curve(tps)
        for window, value in result.items():
            assert value == 0.0, f"window={window} 非 0"

    def test_single_point_uses_fallback(self):
        """单点 → 所有 window 都走 fallback 用全部数据平均（即该点功率本身）。"""
        tps = [_tp(0, 250)]
        result = calculate_power_curve(tps)
        for window, value in result.items():
            assert value == 250.0, f"window={window} 非 250"

    def test_steady_200w_all_buckets_close_to_200(self):
        """1Hz 600 个点全 200W → 所有 window 都接近 200。"""
        tps = [_tp(i, 200) for i in range(600)]
        result = calculate_power_curve(tps)
        for window, value in result.items():
            # window 超过 600 时也走 fallback，但平均仍是 200
            assert abs(value - 200.0) < 0.01, f"window={window} 偏离 200: {value}"

    def test_spike_1200w_one_second(self):
        """单点 1200W spike + 周围 200W → window=0 单点最大=1200, window=5 被稀释到 ≈ 400。"""
        # 先稳定 200W 共 60 点 → spike 1200W 1 点 → 再 200W 60 点
        tps = (
            [_tp(i, 200) for i in range(60)]
            + [_tp(60, 1200)]
            + [_tp(i, 200) for i in range(61, 121)]
        )
        # 自定义 windows / 跳过默认 7 档限制 / 也覆盖旧版有的 1/5 档
        result = calculate_power_curve(tps, windows_sec=[0, 1, 5, 30])
        # window=0：单点最大 = 1200（D26 v2 polish 新增语义）
        assert abs(result[0] - 1200.0) < 0.01
        # window=1：spike 单点本身 = 1200
        assert abs(result[1] - 1200.0) < 0.01
        # window=5：连续 5 个里有 1 个 1200 + 4 个 200 → 平均 (1200+800)/5 = 400
        assert abs(result[5] - 400.0) < 0.01
        # window=30：1200 + 29*200 全在 30 个点里 → 平均 (1200+5800)/30 ≈ 233.3
        assert abs(result[30] - (1200 + 29 * 200) / 30) < 0.01

    def test_power_zero_is_valid_not_treated_as_none(self):
        """power=0 是合法值（休息段），不被当 None 兜底——陷阱 #1。"""
        # 100 点全 0W → 所有 window 应为 0（不是被当 None 跳过）
        tps_zero = [_tp(i, 0) for i in range(100)]
        result = calculate_power_curve(tps_zero)
        for window, value in result.items():
            assert value == 0.0, f"power=0 被错处理为非 0: window={window} 值={value}"

        # 50 个 0W + 50 个 100W → 5 秒最大平均应该是连续 5 个 100W = 100
        # 不应被当 None 跳过 0 段然后只算 100W 段（那就漏了 0 是合法这个语义验证）
        tps_mixed = [_tp(i, 0) for i in range(50)] + [_tp(i + 50, 100) for i in range(50)]
        result = calculate_power_curve(tps_mixed, windows_sec=[5])
        assert abs(result[5] - 100.0) < 0.01

    def test_unsorted_input_gets_sorted(self):
        """输入未按 seq 排序时，函数内部排序保险——结果不受影响。"""
        # 倒序输入 0..49 全 200W
        tps = [_tp(49 - i, 200) for i in range(50)]
        result = calculate_power_curve(tps, windows_sec=[5])
        # 排序后等价 50 个 200W，window=5 应等于 200
        assert abs(result[5] - 200.0) < 0.01

    def test_window_zero_returns_max_single_point_power(self):
        """window=0 特殊语义：单点最大瞬时功率（D26 v2 polish / 不走 sliding window）。"""
        # 50 点 200W + 1 点 1500W spike + 49 点 200W → 单点 max = 1500
        tps = (
            [_tp(i, 200) for i in range(50)]
            + [_tp(50, 1500)]
            + [_tp(i, 200) for i in range(51, 100)]
        )
        result = calculate_power_curve(tps, windows_sec=[0, 5])
        # window=0 = 单点 max（不被 sliding window 稀释）
        assert abs(result[0] - 1500.0) < 0.01
        # window=5 = 5s sliding window max（spike 被稀释）
        # 连续 5 个里有 1 个 1500 + 4 个 200 → (1500 + 800)/5 = 460
        assert abs(result[5] - 460.0) < 0.01

    def test_custom_windows_sec(self):
        """自定义 windows_sec 参数生效，不强制走默认 7 档（D26 v2 polish）。"""
        tps = [_tp(i, 100) for i in range(20)]
        result = calculate_power_curve(tps, windows_sec=[3, 7])
        assert set(result.keys()) == {3, 7}
        assert abs(result[3] - 100.0) < 0.01
        assert abs(result[7] - 100.0) < 0.01


# ───────────────────────────────────────────────────────────────────────
# calculate_power_curve_from_activities（跨 activity per-window max）
# ───────────────────────────────────────────────────────────────────────


class TestCalculatePowerCurveFromActivities:
    def test_empty_list_returns_all_zero(self):
        """空 list of list → 所有 window 返 0（默认 7 档 / D26 v2 polish）。"""
        result = calculate_power_curve_from_activities([])
        assert result == {0: 0.0, 3: 0.0, 30: 0.0, 60: 0.0, 300: 0.0, 1200: 0.0, 3600: 0.0}

    def test_single_activity_equiv_calculate_power_curve(self):
        """list of 1 activity → 等价直接调 calculate_power_curve。"""
        tps = [_tp(i, 250) for i in range(100)]
        single = calculate_power_curve(tps)
        agg = calculate_power_curve_from_activities([tps])
        assert single == agg

    def test_per_window_max_across_activities(self):
        """A 5min 最佳 220 / B 5min 最佳 240 → 5min 取 240。"""
        # A：300+ 个 220W
        tps_a = [_tp(i, 220) for i in range(400)]
        # B：300+ 个 240W
        tps_b = [_tp(i, 240) for i in range(400)]
        result = calculate_power_curve_from_activities([tps_a, tps_b])
        assert abs(result[300] - 240.0) < 0.01

    def test_must_not_concatenate_trackpoints(self):
        """⚠ 关键反例（codex 异源审 I1 修订）：A/B 都用 100W 时，错拼接 vs 不拼接结果都是 100，
        测试无法捕获拼接 bug。这版用"A 末尾高 + B 开头高"构造：
        - A 内部最佳 5s ≤ 200（高功率不够 5 个连续点）
        - B 内部最佳 5s ≤ 200（同上）
        - 若错误拼接：A 末尾 2 个 1000 + B 开头 3 个 1000 = 连续 5 个 1000 → 5s 平均 = 1000

        正确（per-activity 独立算）：max(200, 200) = 200
        错误（拼接）：1000 → 测试断言失败 → 拼接 bug 被抓。
        """
        # A：3 个 0W + 2 个 1000W（末尾高）→ A 内部最佳 5s = (0+0+0+1000+1000)/5 = 400
        tps_a = [_tp(0, 0), _tp(1, 0), _tp(2, 0), _tp(3, 1000), _tp(4, 1000)]
        # B：3 个 1000W + 2 个 0W（开头高）→ B 内部最佳 5s = (1000+1000+1000+0+0)/5 = 600
        tps_b = [_tp(0, 1000), _tp(1, 1000), _tp(2, 1000), _tp(3, 0), _tp(4, 0)]

        # 拼接后会出现 [0,0,0,1000,1000, 1000,1000,1000,0,0]
        # 中间连续 5 个 1000 → 拼接路径 5s 平均会算成 1000
        result = calculate_power_curve_from_activities(
            [tps_a, tps_b], windows_sec=[5]
        )

        # 正确算法：max(A 5s 内最佳, B 5s 内最佳) = max(400, 600) = 600
        # 错误算法（拼接）：1000 → 这条断言会炸
        assert abs(result[5] - 600.0) < 0.01, (
            f"跨 activity 边界出现虚假极值 {result[5]}，"
            "说明 from_activities 错误拼接了 trackpoints"
        )

    def test_empty_inner_lists_skipped(self):
        """内层 list 为空 → 跳过，不影响其他 activity 的曲线计算。"""
        tps_a = [_tp(i, 200) for i in range(100)]
        result = calculate_power_curve_from_activities([[], tps_a, []], windows_sec=[5])
        assert abs(result[5] - 200.0) < 0.01

    def test_each_inner_list_independent_different_windows(self):
        """A 在 window=0 单点最大称王 / B 在 window=300 称王 → 各 window 各取最高。
        即 max 是 per-window 独立的，不强制取同一 activity。
        """
        # A：1 个 1200W spike + 周围 200W（window=0 单点最大称王）
        tps_a = (
            [_tp(i, 200) for i in range(50)]
            + [_tp(50, 1200)]
            + [_tp(i, 200) for i in range(51, 100)]
        )
        # B：稳定 250W 共 600 点（window=300 称王）
        tps_b = [_tp(i, 250) for i in range(600)]
        result = calculate_power_curve_from_activities([tps_a, tps_b], windows_sec=[0, 300])
        # window=0：A 的单点 1200 应胜出（B 单点最大 250）
        assert abs(result[0] - 1200.0) < 0.01
        # window=300：B 的 250 应胜出（A 在 300s 里被稀释）
        assert abs(result[300] - 250.0) < 0.01

    def test_custom_windows_sec_propagates(self):
        """自定义 windows_sec 应传播到内部 calculate_power_curve 调用。"""
        tps = [_tp(i, 100) for i in range(20)]
        result = calculate_power_curve_from_activities([tps], windows_sec=[7])
        assert set(result.keys()) == {7}
        assert abs(result[7] - 100.0) < 0.01
