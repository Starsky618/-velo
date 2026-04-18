"""scheduler.py 是守护进程入口，单测只验证三件事：
1. import 不崩
2. 循环结构正确（while + sleep）
3. 异常不中断循环
"""
from unittest.mock import patch


def test_scheduler_imports_cleanly():
    """确认 scheduler.py 能 import 不报错。"""
    import scheduler  # noqa: F401


def test_main_loop_calls_run_tick_and_sleeps():
    """验证 main 循环调用 run_import_tick + time.sleep。"""
    import scheduler

    call_count = {"tick": 0, "sleep": 0}

    def fake_tick():
        call_count["tick"] += 1
        if call_count["tick"] >= 2:
            raise KeyboardInterrupt()  # 跳出 while True

    def fake_sleep(seconds):
        assert seconds == scheduler._TICK_INTERVAL_SECONDS
        call_count["sleep"] += 1

    with patch.object(scheduler, "run_import_tick", side_effect=fake_tick), \
         patch.object(scheduler.time, "sleep", side_effect=fake_sleep):
        try:
            scheduler.main()
        except KeyboardInterrupt:
            pass

    assert call_count["tick"] == 2
    assert call_count["sleep"] >= 1


def test_main_loop_survives_exception():
    """tick 抛异常 → 循环继续下一轮。"""
    import scheduler

    call_count = {"tick": 0}

    def fake_tick():
        call_count["tick"] += 1
        if call_count["tick"] == 1:
            raise RuntimeError("模拟 tick 崩")
        if call_count["tick"] >= 3:
            raise KeyboardInterrupt()

    with patch.object(scheduler, "run_import_tick", side_effect=fake_tick), \
         patch.object(scheduler.time, "sleep"):
        try:
            scheduler.main()
        except KeyboardInterrupt:
            pass

    # 第一次崩了，但循环没退——第 2、3 次都跑了
    assert call_count["tick"] >= 2
