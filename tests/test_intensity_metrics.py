"""Sprint 9 task-2 单元测试：calculate_intensity_metrics helper。"""
import pytest
from app.activity.worker import calculate_intensity_metrics


class TestIntensityMetrics:
    def test_normal_case_full_data(self):
        """正常：NP 200W / FTP 220W / 1 小时 → IF≈0.909 / TSS≈82.6"""
        if_val, tss = calculate_intensity_metrics(np=200, ftp=220, duration_seconds=3600)
        assert if_val == 0.909
        assert tss == 82.6

    def test_np_none(self):
        """NP 缺失（GPX 路径）→ 返 (None, None)"""
        assert calculate_intensity_metrics(np=None, ftp=220, duration_seconds=3600) == (None, None)

    def test_ftp_none(self):
        """用户没填 ftp → 返 (None, None)"""
        assert calculate_intensity_metrics(np=200, ftp=None, duration_seconds=3600) == (None, None)

    def test_ftp_zero(self):
        """ftp=0 防除零 → 返 (None, None)"""
        assert calculate_intensity_metrics(np=200, ftp=0, duration_seconds=3600) == (None, None)

    def test_duration_zero(self):
        """duration=0 → 返 (None, None)"""
        assert calculate_intensity_metrics(np=200, ftp=220, duration_seconds=0) == (None, None)

    def test_duration_none(self):
        """duration=None → 返 (None, None)"""
        assert calculate_intensity_metrics(np=200, ftp=220, duration_seconds=None) == (None, None)
