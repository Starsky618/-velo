"""
Strava 导入调度器——常驻进程，每 30s tick 一次。

为什么不用 rq-scheduler / celery-beat / APScheduler：
    1. 项目只有一个周期任务（tier1/tier2 导入），引入上述方案开销不成比例
    2. 简单 while + sleep 就能满足：30s tick 一次，每次 tick 处理所有 active 用户
    3. 异常绝对不中断循环——单次 tick 失败只记日志，下一轮继续
    4. 未来需要多个周期任务时（如定时发送骑行简报）再迁移到 rq-scheduler

为什么要在单独容器（不和 worker 合并）：
    worker 是 RQ 工作进程（消费队列），scheduler 是时间驱动进程（产生任务）。
    职责不同、重启策略不同（worker 崩溃影响单个任务，scheduler 崩溃影响全量导入）。
    分开更清晰也更便于监控。

运行方式：
    本地：python scheduler.py（cwd 必须是项目根目录，否则 import 失败）
    Docker：WORKDIR=/app + command: python scheduler.py
"""
import logging
import time

from app.meetup.cron import run_meetup_complete_tick
from app.strava.import_scheduler import run_import_tick


# 日志格式：时间 + 进程标识 + 消息——进容器日志后一眼能认出是哪个进程
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# tick 间隔（秒）——Strava 每 15 分钟配额 100 请求。
# 15s 一轮：tier2 4 calls/min × 15min = 60 calls + tier1/manual_sync 余量 40 = 100 上限内安全。
# 比 30s tick 提速 ×2（30 条活动 15→7.5 分钟）/ 配合前端 importing 状态卡片让等待感知消失。
# Tim 2026-05-06 真用回归发现 30s tick 在生产体验不可接受 / Q1 改动。
_TICK_INTERVAL_SECONDS = 15
_meetup_tick_counter = 0


def main():
    global _meetup_tick_counter
    logger.info("Strava scheduler 启动（tick 间隔 %ds）", _TICK_INTERVAL_SECONDS)

    while True:
        try:
            run_import_tick()
        except Exception:
            # 关键纪律：任何异常都不能让循环退出
            # logger.exception 会自动打印完整 traceback，便于诊断
            logger.exception("tick 执行失败")

        try:
            _meetup_tick_counter += 1
            if _meetup_tick_counter >= 20:
                run_meetup_complete_tick()
                _meetup_tick_counter = 0
        except Exception:
            # meetup tick 和 Strava tick 互不拖累：约骑收尾失败不能让导入停摆。
            logger.exception("meetup tick 失败")
            _meetup_tick_counter = 0

        time.sleep(_TICK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
