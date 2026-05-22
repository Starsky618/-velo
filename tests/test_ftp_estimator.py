"""Sprint 9/10 FTP 估算测试：CP3 底层拟合 + 20min 心率门控入口。

测试覆盖 4 个核心场景：
1. 标准 5 点拟合 / CP 应接近真实 ftp 220W ±10%
2. 数据不足（< 3 efforts）→ confidence='insufficient'
3. 退化数据（所有功率相同）→ 拟合 fail 或低 R² → insufficient/low
4. 新用户 0 条活动 → insufficient
5. 对外估算入口必须同时满足功率 + 心率 + 20min 强度门槛
"""
import pytest

from datetime import datetime, timedelta, timezone

from app.activity.ftp_estimator import (
    estimate_ftp_for_user,
    fit_cp3_model,
    EstimationResult,
    _sliding_window_best_power,
)
from app.activity.models import Activity, Trackpoint


class TestSlidingWindowMonotonicity:
    """v0.2 滑窗 bug 修复回归测试（Tim 2026-05-21 真用回归实证：
    单条活动内出现 best 180s=218 < best 300s=278 物理矛盾 / 90% 容差 + index 平均双 bug）。

    物理保证：单条活动内 best(短窗) ≥ best(长窗) / 因短窗是长窗子集。
    """

    @staticmethod
    def _make_tps(power_seq: list[float], dt_seconds: float = 1.0) -> list[tuple[float, datetime]]:
        """构造均匀采样 trackpoints / 间隔 dt 秒。"""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [(p, base + timedelta(seconds=i * dt_seconds)) for i, p in enumerate(power_seq)]

    def test_monotonic_short_window_ge_long(self):
        """1Hz 均匀采样 600 秒 / best 180s 必 ≥ best 300s（短窗 ≥ 长窗 / 物理约束）"""
        # 模拟前 200 秒 250W 高强度 + 后 400 秒 100W 恢复
        power_seq = [250.0] * 200 + [100.0] * 400
        tps = self._make_tps(power_seq, dt_seconds=1.0)
        best_180 = _sliding_window_best_power(tps, 180)
        best_300 = _sliding_window_best_power(tps, 300)
        # 180s 窗口可以完全在 250W 高强度段 → best_180 ≈ 250
        # 300s 窗口必须跨高低段 → best_300 < 250
        assert best_180 >= best_300, f"违反物理约束: best 180s={best_180:.1f} < best 300s={best_300:.1f}"
        assert best_180 >= 240, f"best 180s 应 ≈ 250W / 实际 {best_180:.1f}"

    def test_uneven_sampling_4hz_vs_1hz(self):
        """采样不均匀（4Hz vs 1Hz）/ 时间加权平均应对 / 不被 index 数量混淆"""
        # 前 90 秒 4Hz (360 点 / 200W) + 后 90 秒 1Hz (90 点 / 200W) = 180s 均 200W
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        tps = []
        for i in range(360):  # 4Hz × 90s
            tps.append((200.0, base + timedelta(seconds=i * 0.25)))
        for i in range(1, 91):  # 1Hz × 90s
            tps.append((200.0, base + timedelta(seconds=90 + i)))
        best_180 = _sliding_window_best_power(tps, 180)
        # 时间加权平均 = 200W / 不被 index 计数（360 个 4Hz vs 90 个 1Hz）干扰
        assert abs(best_180 - 200.0) < 1.0, f"时间加权 best 180s 应 ≈ 200 / 实际 {best_180:.2f}"

    def test_short_window_returns_zero_when_data_too_short(self):
        """活动只有 60s / 求 best 180s → 时长不够返 0（严格 ≥ window_seconds / 不再 90% 容差）"""
        power_seq = [200.0] * 60
        tps = self._make_tps(power_seq, dt_seconds=1.0)
        best_180 = _sliding_window_best_power(tps, 180)
        assert best_180 == 0.0, f"60s 数据求 180s window 应返 0 / 实际 {best_180}"


class TestFtpEstimator:
    def test_fit_cp3_with_known_ftp(self):
        """5 个 best efforts 拟合 / CP 应接近真实 ftp 220W ±10%（容差宽防数值噪声）。"""
        # 用反解公式 P(t) = CP + W' * (P_max - CP) / (W' + t * (P_max - CP)) 反算
        # CP=220 / W'=20000J / Pmax=900W
        # t=180s: P = 220 + 20000*680/(20000+180*680) = 220 + 13600000/142400 = 220 + 95.5 ≈ 315
        # t=300s: P ≈ 220 + 13600000/224000 ≈ 220 + 60.7 ≈ 281
        # t=600s: P ≈ 220 + 13600000/428000 ≈ 220 + 31.8 ≈ 252
        # t=1200s: P ≈ 220 + 13600000/836000 ≈ 220 + 16.3 ≈ 236
        # t=3600s: P ≈ 220 + 13600000/2468000 ≈ 220 + 5.5 ≈ 226
        efforts = [
            (180, 315.0),
            (300, 281.0),
            (600, 252.0),
            (1200, 236.0),
            (3600, 226.0),
        ]
        result = fit_cp3_model(efforts)
        assert result.ftp is not None, f"拟合失败 result={result}"
        assert 198 <= result.ftp <= 242, f"ftp={result.ftp} 不在 220±10% 范围"
        assert result.r2 > 0.85, f"R²={result.r2} 太低"
        assert result.confidence in ("high", "medium", "low")
        assert result.method == "cp3_no_hr"

    def test_insufficient_data_too_few_efforts(self):
        """只有 1-2 个 best effort → confidence='insufficient'。"""
        efforts = [(180, 320.0), (300, 280.0)]
        result = fit_cp3_model(efforts)
        assert result.confidence == "insufficient"
        assert result.ftp is None
        assert result.method == "cp3_no_hr"

    def test_fit_fails_returns_insufficient(self):
        """退化数据（所有 effort 同 power）→ 拟合可能 succeed 但 R² 低 / 或 fail。"""
        efforts = [(180, 220.0), (300, 220.0), (600, 220.0), (1200, 220.0), (3600, 220.0)]
        result = fit_cp3_model(efforts)
        # 拟合可能 succeed 但 R² 低 / 或 fail；都视为 insufficient/low
        assert result.confidence in ("insufficient", "low")

    def test_estimator_zero_activities(self, db, test_user):
        """新用户 0 条活动 → insufficient。"""
        # test_user fixture 创建一个全新的用户（无 ftp、无活动）
        result = estimate_ftp_for_user(db, test_user.id)
        assert result.confidence == "insufficient"
        assert result.ftp is None
        assert result.method == "p20_hr_gated_cp3_check"

    def test_non_monotonic_data_returns_insufficient(self):
        """非单调（长时长 power > 短时长）= 物理不可能 → insufficient。

        想象百米跑得比一公里慢——身体物理不允许；CP 模型假设 P(t) 严格单调递减。
        这里 300s=250 > 180s=200 矛盾 / 拟合参数无物理意义 / 直接 insufficient。
        """
        efforts = [(180, 200.0), (300, 250.0), (600, 220.0), (1200, 210.0), (3600, 200.0)]
        result = fit_cp3_model(efforts)
        assert result.confidence == "insufficient", f"non-monotonic 应 insufficient / 实际 {result}"
        assert result.ftp is None

    def test_only_3_efforts_downgraded(self):
        """3 efforts 自由度 0 → R² 数学必 1.0 → 但强制降级最高 low / 不能 high/medium。

        Codex 异源审抓的 Critical：3 个 (t,P) 点拟合 3 参数 (W',CP,Pmax) 必完美拟合
        / R²=1.0 = 虚假置信度欺骗用户；本测确保算法不会输出 high/medium。
        """
        efforts = [(180, 315.0), (300, 282.0), (600, 248.0)]
        result = fit_cp3_model(efforts)
        # 必须降级 / 不能 high 或 medium
        assert result.confidence in ("low", "insufficient"), (
            f"3 efforts 不能 high/medium / 实际 {result}"
        )


class TestHrGatedFtpEstimator:
    """Sprint 10 FTP 精度专题：20min 心率门控主锚点。

    测试重点不是 CP3 数学本身，而是入口数据闸门：
    必须同一窗口同时有功率 + 心率，且心率强度足够，才允许估算 FTP。
    """

    @staticmethod
    def _activity_with_points(
        db,
        user,
        title: str,
        seconds: int,
        power: int | None,
        hr: int | None,
        started_offset_days: int = 7,
    ) -> Activity:
        started = datetime.now(timezone.utc) - timedelta(days=started_offset_days)
        activity = Activity(
            user_id=user.id,
            title=title,
            status="completed",
            activity_type="cycling",
            started_at=started,
            duration=seconds,
            avg_power=power,
            avg_hr=hr,
        )
        db.add(activity)
        db.flush()

        for seq in range(seconds + 1):
            db.add(Trackpoint(
                activity_id=activity.id,
                seq=seq,
                latitude=30.0,
                longitude=120.0,
                timestamp=started + timedelta(seconds=seq),
                power=power,
                heart_rate=hr,
            ))
        db.commit()
        return activity

    def test_power_without_hr_is_not_eligible(self, db, test_user):
        """有功率但无心率 → 不能估 FTP，防 CP3 盲扫日常功率活动。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "power_only", 1200, power=260, hr=None)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.confidence == "insufficient"
        assert result.ftp is None

    def test_hr_without_power_is_not_eligible(self, db, test_user):
        """有心率但无功率 → 不能估 FTP，心率不能单独反推瓦数。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "hr_only", 1200, power=None, hr=180)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.confidence == "insufficient"
        assert result.ftp is None

    def test_low_hr_power_window_is_not_eligible(self, db, test_user):
        """20min 功率够高但平均心率低于 85% maxHR → 视为非阈值努力。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "tempo_not_threshold", 1200, power=260, hr=150)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.confidence == "insufficient"
        assert result.ftp is None

    def test_target_20min_window_missing_hr_is_not_eligible(self, db, test_user):
        """整条活动有心率和功率，但目标 20min 高功率窗口缺心率 → 不入选。"""
        test_user.max_hr = 200
        started = datetime.now(timezone.utc) - timedelta(days=7)
        activity = Activity(
            user_id=test_user.id,
            title="mixed_but_anchor_missing_hr",
            status="completed",
            activity_type="cycling",
            started_at=started,
            duration=1500,
            avg_power=228,
            avg_hr=180,
        )
        db.add(activity)
        db.flush()

        for seq in range(1501):
            in_high_power_block = seq <= 1200
            db.add(Trackpoint(
                activity_id=activity.id,
                seq=seq,
                latitude=30.0,
                longitude=120.0,
                timestamp=started + timedelta(seconds=seq),
                power=260 if in_high_power_block else 100,
                heart_rate=None if in_high_power_block else 180,
            ))
        db.commit()

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.confidence == "insufficient"
        assert result.ftp is None

    def test_qualified_20min_anchor_returns_p20_with_5w_bias(self, db, test_user):
        """合格 20min 窗口 → raw=p20*0.95，最终建议值再 +5W。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "threshold_20min", 1200, power=250, hr=172)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.method == "p20_hr_gated_cp3_check"
        assert result.confidence == "low"
        assert result.ftp == 243  # round(250 * 0.95)=238，再加 5W 产品偏移

    def test_suggested_ftp_is_clamped_to_response_bounds(self, db, test_user):
        """最终建议值上限只在输出层 clamp 到 500，不影响 raw 内部计算。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "too_high", 1200, power=700, hr=190)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.ftp == 500

    def test_suggested_ftp_is_clamped_to_minimum_response_bound(self, db, test_user):
        """最终建议值下限只在输出层 clamp 到 50。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "too_low", 1200, power=20, hr=190)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.ftp == 50

    def test_birth_year_fallback_can_estimate_but_caps_confidence_low(self, db, test_user):
        """缺 max_hr 但有 birth_year → Tanaka 公式兜底，confidence 最高 low。"""
        current_year = datetime.now(timezone.utc).year
        test_user.birth_year = current_year - 30
        test_user.max_hr = None
        db.commit()
        self._activity_with_points(db, test_user, "age_formula", 1200, power=250, hr=160)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.ftp == 243
        assert result.confidence == "low"

    def test_cp3_with_less_than_5_efforts_cannot_raise_confidence(self, db, test_user):
        """少于 5 个合格窗口时，CP3 即使接近 p20 也不能把 confidence 升到 medium。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "p5", 300, power=281, hr=183)
        self._activity_with_points(db, test_user, "p10", 600, power=252, hr=182)
        self._activity_with_points(db, test_user, "p20", 1200, power=236, hr=176)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.confidence == "low"

    def test_cp3_close_to_p20_can_raise_confidence(self, db, test_user):
        """5/10/20/60min 合格窗口与 CP3 接近 → confidence 可升到 medium/high。"""
        test_user.max_hr = 200
        db.commit()
        self._activity_with_points(db, test_user, "p3", 180, power=315, hr=184)
        self._activity_with_points(db, test_user, "p5", 300, power=281, hr=183)
        self._activity_with_points(db, test_user, "p10", 600, power=252, hr=182)
        self._activity_with_points(db, test_user, "p20", 1200, power=236, hr=176)
        self._activity_with_points(db, test_user, "p60", 3600, power=226, hr=174)

        result = estimate_ftp_for_user(db, test_user.id)

        assert result.method == "p20_hr_gated_cp3_check"
        assert result.confidence in ("medium", "high")
        assert result.ftp == 229  # round(236 * 0.95)=224，再加 5W
