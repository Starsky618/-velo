#!/usr/bin/env python3
"""
SessionStart hook entrypoint.

Keep session startup read-only and quiet. It may run fast safety checks, but it
must not create repo-tracked documents or expand the agent's default context.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_script(name: str) -> None:
    """Run a child script and never let hook failures block the session."""
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name)],
            check=False,
            cwd=ROOT,
        )
    except Exception as exc:
        print(f"[session_start] {name} failed: {exc}", file=sys.stderr)


DUAL_AGENT_ROUTING_CARD = """
<dual-agent-routing-card>
双主驾分工速查（精简版 / 详 agent-collab.md §10.Y）：
- 角色画像：Codex = 任务执行器（清楚边界） / Claude = 结对同事（讨论权衡）
- 决策三轴：歧义度（低 → Codex）/ 可测性（高 → Codex）/ 可回滚（可 → Codex）
- Codex 反指标：改核心规范 / 内容已在上下文 / 大文档 > 800 字（命中 = push back）
- 派 Codex 5 字段：背景 / 目标 / 验收命令 / 不要碰 / 失败处理
</dual-agent-routing-card>
"""


def main() -> int:
    _run_script("verify_tech_debt.py")
    print("[session_start] 周报不再自动写入 docs/agent-weekly；需要复盘时手动运行 scripts/weekly_report.py --write。")
    # 注入双主驾分工速查到 SessionStart developer context（精简版 / 长期常驻）
    # 完整版 §10.Y 由 UserPromptSubmit hook 按 keyword 触发
    sys.stdout.write(DUAL_AGENT_ROUTING_CARD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
