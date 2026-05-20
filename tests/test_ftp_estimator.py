"""Sprint 9 task-5 单元测试：CP 3-param + 心率加权 eFTP 估算。

测试覆盖 4 个核心场景：
1. 标准 5 点拟合 / CP 应接近真实 ftp 220W ±10%
2. 数据不足（< 3 efforts）→ confidence='insufficient'
3. 退化数据（所有功率相同）→ 拟合 fail 或低 R² → insufficient/low
4. 新用户 0 条活动 → insufficient
"""
import pytest

from app.activity.ftp_estimator import (
    estimate_ftp_for_user,
    fit_cp3_model,
    EstimationResult,
)


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
        assert result.method == "cp3_no_hr"
