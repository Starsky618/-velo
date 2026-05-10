"""
backup_freshness 探针单测（Sprint 5 task-1）。

不连真 docker volume / 全用 tmp_path fixture 造文件：
- 4 case 覆盖：目录不存在 / 目录为空 / 文件新鲜 / 文件陈旧
- 不真跑 pg_dump / 只 stat mtime
"""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.monitor import backup_freshness


def test_dir_not_exists_returns_error(tmp_path, caplog):
    """目录不存在 → log error + 返 1。"""
    nonexistent = tmp_path / "nonexistent_dir"
    with caplog.at_level("ERROR"):
        result = backup_freshness.check_backup_freshness(nonexistent)
    assert result == 1
    assert "backup dir 不存在" in caplog.text


def test_empty_dir_returns_error(tmp_path, caplog):
    """目录存在但无任何 velo_*.sql.gz 文件 → log error + 返 1。"""
    with caplog.at_level("ERROR"):
        result = backup_freshness.check_backup_freshness(tmp_path)
    assert result == 1
    assert "backup dir 为空" in caplog.text


def test_fresh_backup_returns_healthy(tmp_path, caplog):
    """最新备份 < 30h → 不打日志 + 返 0。"""
    fresh_file = tmp_path / "velo_20260510_030000.sql.gz"
    fresh_file.write_bytes(b"fake gzip content")
    # mtime 设为 1 小时前（远小于 30h 阈值）
    one_hour_ago = time.time() - 3600
    os.utime(fresh_file, (one_hour_ago, one_hour_ago))

    with caplog.at_level("WARNING"):
        result = backup_freshness.check_backup_freshness(tmp_path)
    assert result == 0
    # 健康路径不打 warning/error
    assert "stale" not in caplog.text
    assert "为空" not in caplog.text


def test_stale_backup_returns_warning(tmp_path, caplog):
    """最新备份 > 30h → log warning + 返 1。"""
    stale_file = tmp_path / "velo_20260508_030000.sql.gz"
    stale_file.write_bytes(b"fake gzip content")
    # mtime 设为 35 小时前（超 30h 阈值）
    thirty_five_hours_ago = time.time() - 35 * 3600
    os.utime(stale_file, (thirty_five_hours_ago, thirty_five_hours_ago))

    with caplog.at_level("WARNING"):
        result = backup_freshness.check_backup_freshness(tmp_path)
    assert result == 1
    assert "stale" in caplog.text
    assert "35" in caplog.text  # 距今小时数应反映在日志中


def test_exactly_30h_is_healthy(tmp_path, caplog):
    """精确 mtime = 30h → 阈值是 > 30 / 等于 30 视为健康（边界 case / codex 异源审 2026-05-10 抓 Nice）。"""
    edge_file = tmp_path / "velo_20260509_030000.sql.gz"
    edge_file.write_bytes(b"fake")
    # mtime 设为 30 小时整 - 1 秒（刚好不超阈值 / 防 wallclock drift 导致测试 flaky）
    almost_thirty_h = time.time() - (30 * 3600 - 1)
    os.utime(edge_file, (almost_thirty_h, almost_thirty_h))

    with caplog.at_level("WARNING"):
        result = backup_freshness.check_backup_freshness(tmp_path)
    assert result == 0
    assert "stale" not in caplog.text


def test_just_over_30h_triggers_warning(tmp_path, caplog):
    """精确 mtime = 30h + 1min → 触发 warning（阈值边界另一侧 / codex 异源审 Nice）。"""
    over_file = tmp_path / "velo_20260509_030000.sql.gz"
    over_file.write_bytes(b"fake")
    # mtime 设为 30 小时 + 60 秒（确保超阈值 / 防 wallclock drift）
    just_over = time.time() - (30 * 3600 + 60)
    os.utime(over_file, (just_over, just_over))

    with caplog.at_level("WARNING"):
        result = backup_freshness.check_backup_freshness(tmp_path)
    assert result == 1
    assert "stale" in caplog.text


def test_multi_files_picks_latest_mtime(tmp_path, caplog):
    """多个文件存在 → 应取 mtime 最新的判断（不是文件名时间戳）。"""
    # 老文件名"显示 2026-05-09"但 mtime 设为 35 小时前（陈旧）
    fake_old_name_actually_stale = tmp_path / "velo_20260509_030000.sql.gz"
    fake_old_name_actually_stale.write_bytes(b"fake")
    os.utime(fake_old_name_actually_stale, (time.time() - 35 * 3600,) * 2)

    # 新文件名"显示 2026-05-10"但 mtime 设为 1 小时前（新鲜）
    fake_new_name_actually_fresh = tmp_path / "velo_20260510_030000.sql.gz"
    fake_new_name_actually_fresh.write_bytes(b"fake")
    os.utime(fake_new_name_actually_fresh, (time.time() - 3600,) * 2)

    with caplog.at_level("WARNING"):
        result = backup_freshness.check_backup_freshness(tmp_path)
    # 应取 mtime 新的那个判断 → 返 0（健康）
    assert result == 0
    assert "stale" not in caplog.text
