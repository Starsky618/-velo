#!/usr/bin/env python3
"""
UserPromptSubmit hook: lightweight evidence reminder.

This script prints a short note that Claude Code injects before each user
prompt. Keep it tiny: the hook should nudge evidence work, not become another
always-on rulebook.
"""

import sys

INJECTION = """<evidence-ledger-before-response>
回答前先确认：
1. 涉及现有文件 / 字段 / API / 路径 / 状态值：先 Read 或 rg，结论带 file:line。
2. 没查到就写“未验证”，不要用记忆、注释或 commit message 补猜。
3. schema / 生产数据 / 部署 / commit 等高风险动作：先查 CLAUDE.md 启动卡和 agent-collaboration 对应门禁。
</evidence-ledger-before-response>
"""


def main() -> int:
    sys.stdout.write(INJECTION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
