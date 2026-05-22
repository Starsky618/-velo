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


def main() -> int:
    _run_script("verify_tech_debt.py")
    print("[session_start] 周报不再自动写入 docs/agent-weekly；需要复盘时手动运行 scripts/weekly_report.py --write。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
