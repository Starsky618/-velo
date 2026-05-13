#!/usr/bin/env python3
"""
SessionStart hook 总入口——每次会话起手自动跑。

干啥用：
    Claude Code 每次开会话 / /clear 后会调用本脚本（见 .claude/settings.json hooks）。
    本脚本是个"调度员"，决定起手时跑哪些自检任务。

类比：
    每天进家门时门口的"小管家"——
    1. 先扫一眼地板有没有过期食品（tech-debt 扫描）
    2. 看看日历：今天周一吗？是 → 跑一下"每周大盘点"（生成周报）
    3. 输出全部塞到 agent 起手上下文 / Tim 间接看到

当前包含的任务：
    - verify_tech_debt.py（每次起手都跑 / < 1 秒 / 0 噪音）
    - weekly_report.py（距上次报告 ≥ 7 天才跑 / 生成本周报告）

未来扩展（按需加）：
    - memory 老化检测（> 30 天没读的 memory）
    - 文档同步检测（代码改了 / 文档没改）
    - 月度复盘（距上次月报 ≥ 28 天）

注意事项：
    - 任何子任务 fail 都不能挂 hook / 全部 try/except + 退出码 0
    - 输出控制在 30 行内 / 别污染上下文
    - 周报判断用 last-run.txt 时间戳 / 跨机器一致
"""

import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "docs" / "agent-weekly"


def _run_script(name: str) -> None:
    """跑子脚本 / 输出直传 stdout / 异常吞掉。"""
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name)],
            check=False,
            cwd=ROOT,
        )
    except Exception as e:
        print(f"[session_start] {name} 跑失败：{e}", file=sys.stderr)


def _should_run_weekly() -> bool:
    """
    判断本周报告是否已生成：看 docs/agent-weekly/YYYY-WNN.md 是否存在。
    本周报告在 = 跳过 / 不在 = 首次进入本周 / 触发生成。
    用文件存在性而不是 last-run.txt 时间戳——好处：跨机器一致（Mac / 腾讯云不会重复跑）/
    每周固定一次（不靠"距上次 ≥ 7 天"漂移）。
    """
    iso = datetime.datetime.now().isocalendar()
    week_report = WEEKLY_DIR / f"{iso[0]}-W{iso[1]:02d}.md"
    return not week_report.exists()


def main() -> int:
    # 任务 1: tech-debt 扫描（每次都跑 / < 1 秒）
    _run_script("verify_tech_debt.py")

    # 任务 2: 周报（本周首次进入才跑）
    if _should_run_weekly():
        print()
        _run_script("weekly_report.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
